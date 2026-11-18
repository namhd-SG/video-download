"""Kiểm thử liệt kê trang TikTok `@profile` qua yt-dlp (`nguon_profile_yt_dlp.py`),
nhánh ưu tiên trong `TikTokCollection.liet_ke` (`nguon.py`) và cổng `cho_xac_minh` ở `web/queue.py`.

Toàn bộ lời gọi `YoutubeDL` và trình quét trình duyệt đều được thay bằng bản giả qua `monkeypatch` —
không gọi mạng, không mở trình duyệt thật.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import nguon_profile_yt_dlp as prof_yt
from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader.nguon import TikTokCollection
from tiktok_music_downloader.nguon_profile_yt_dlp import (
    ENV_PROFILE_YT_DLP,
    SO_MUC_MOI_TRANG,
    liet_ke_profile_yt_dlp,
)
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED,
    STOP_COMPLETE,
    STOP_STALLED,
    VideoRef,
)
from web import models, profile_theo_job
from web import queue as queue_mod
from web.queue import process_job

URL_PROFILE = "https://www.tiktok.com/@lynherne"
URL_PROFILE_CO_QUERY = "https://www.tiktok.com/@lynherne?lang=en&sec_token=bi_mat_123"


def _id_tt(n: int) -> str:
    """ID video TikTok 19 chữ số hợp lệ (`^\\d{15,25}$`)."""
    return f"740000000000000{n:04d}"


def _muc_phang(
    n: int,
    *,
    vid: str | None = None,
    url: str | None = "mac_dinh",
    title: str | None = None,
    uploader: str | None = "lynherne",
    duration: int | None = 15,
) -> dict:
    ma = _id_tt(n) if vid is None else vid
    link = f"https://www.tiktok.com/@lynherne/video/{ma}" if url == "mac_dinh" else url
    d: dict = {"id": ma}
    if link is not None:
        d["url"] = link
    if title is not None:
        d["title"] = title
    if uploader is not None:
        d["uploader"] = uploader
    if duration is not None:
        d["duration"] = duration
    return d


class FakeYtdlp:
    """Bản giả `YoutubeDL` kiểm tra duyệt lười trong khối `with`, ghi lại `opts` và số mục đã kéo."""

    def __init__(
        self,
        muc: list,
        *,
        loi_extract: Exception | None = None,
        loi_o_muc: int | None = None,
        loi_giua: Exception | None = None,
    ):
        self.muc = muc
        self.loi_extract = loi_extract
        self.loi_o_muc = loi_o_muc
        self.loi_giua = loi_giua or RuntimeError("đứt mạng trang kế")
        self.opts_da_nhan: list[dict] = []
        self.url_da_goi: list[tuple[str, bool, bool]] = []
        self.so_muc_da_keo = 0
        self.so_phien_mo = 0
        self.keo_ngoai_with = False

    def __call__(self, opts: dict):
        self.opts_da_nhan.append(dict(opts))
        return self

    def __enter__(self):
        self.so_phien_mo += 1
        return self

    def __exit__(self, *_a):
        self.so_phien_mo -= 1
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        self.url_da_goi.append((url, download, process))
        if self.loi_extract is not None:
            raise self.loi_extract

        def _gen():
            for idx, item in enumerate(self.muc):
                if self.so_phien_mo <= 0:
                    self.keo_ngoai_with = True
                if self.loi_o_muc is not None and idx == self.loi_o_muc:
                    raise self.loi_giua
                self.so_muc_da_keo += 1
                yield item

        return {"_type": "playlist", "id": "sec_uid", "title": "lynherne", "entries": _gen()}


@pytest.fixture(autouse=True)
def _moi_truong_sach(monkeypatch):
    # conftest TẮT yt-dlp cho cả suite (không gọi mạng); file này bật lại để kiểm nhánh yt-dlp bằng YoutubeDL giả.
    monkeypatch.setenv(ENV_PROFILE_YT_DLP, "1")
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA, raising=False)
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_HEADFUL, raising=False)


def _cb_macdinh():
    return dict(
        already_have=lambda ids: set(),
        on_skip=lambda r: None,
        on_stop=lambda s: None,
        on_pages=lambda n: None,
        dem_trang=lambda: None,
    )


# ---------------------------------------------------------------------------
# (a) Duyệt lười: generator 1000 mục, max 5 mới ⇒ kéo đúng 5 + số đã có, trong `with`
# ---------------------------------------------------------------------------

def test_a_duyet_luoi_1000_muc_dung_ngay_khi_du_5_moi_trong_khoi_with(monkeypatch):
    ds = [_muc_phang(i, title=f"video {i}") for i in range(1, 1001)]
    da_co = {_id_tt(2), _id_tt(4)}
    gia = FakeYtdlp(ds)
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    bo_qua: list[VideoRef] = []
    so_trang = [0]
    refs = liet_ke_profile_yt_dlp(
        URL_PROFILE,
        max_videos=5,
        proxy="http://127.0.0.1:8080",
        already_have=lambda ids: {i for i in ids if i in da_co},
        on_skip=bo_qua.append,
        dem_trang=lambda: so_trang.__setitem__(0, so_trang[0] + 1),
    )

    assert refs is not None
    assert [r.video_id for r in refs] == [_id_tt(1), _id_tt(3), _id_tt(5), _id_tt(6), _id_tt(7)]
    assert [r.video_id for r in bo_qua] == [_id_tt(2), _id_tt(4)]
    # 5 mới + 2 đã có = kéo đúng 7 mục từ generator 1000 mục.
    assert gia.so_muc_da_keo == 7
    assert not gia.keo_ngoai_with and gia.so_phien_mo == 0
    assert gia.url_da_goi == [(URL_PROFILE, False, False)]
    opts = gia.opts_da_nhan[0]
    assert opts["extract_flat"] == "in_playlist"
    assert opts["quiet"] is True
    assert opts["skip_download"] is True
    assert opts["proxy"] == "http://127.0.0.1:8080"
    assert "cookiefile" not in opts
    assert "playlistend" not in opts
    assert so_trang[0] == 1


# ---------------------------------------------------------------------------
# (b) Lọc already_have + on_skip + khử trùng + dem_trang mỗi 15 mục + trần kéo + on_stop
# ---------------------------------------------------------------------------

def test_b_loc_already_have_on_skip_khu_trung_va_dem_trang_moi_15_muc(monkeypatch):
    # 31 mục hợp lệ (kèm 1 bản trùng của mục 1 ở đầu) ⇒ 32 lần kéo từ generator ⇒ 3 trang (mục 1, 16, 31).
    ds = [_muc_phang(1)] + [_muc_phang(i, title=f"t{i}", uploader="tacgia", duration=20 + i) for i in range(1, 32)]
    da_co = {_id_tt(1), _id_tt(2), _id_tt(3)}
    gia = FakeYtdlp(ds)
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    bo_qua: list[VideoRef] = []
    trang = [0]
    refs = liet_ke_profile_yt_dlp(
        URL_PROFILE,
        max_videos=50,
         proxy=None,
        already_have=lambda ids: {i for i in ids if i in da_co},
        on_skip=bo_qua.append,
        dem_trang=lambda: trang.__setitem__(0, trang[0] + 1),
    )

    assert refs is not None
    assert len(refs) == 28
    assert [r.video_id for r in bo_qua] == [_id_tt(1), _id_tt(2), _id_tt(3)]
    assert gia.so_muc_da_keo == 32
    # 32 mục kéo: gọi dem_trang ở da_keo = 0, 15, 30 ⇒ 3 lần.
    assert SO_MUC_MOI_TRANG == 15 and trang[0] == 3
    assert refs[0].title == "t4" and refs[0].author == "tacgia" and refs[0].duration == 24
    assert "proxy" not in gia.opts_da_nhan[0]


def test_b_tran_muc_keo_ung_voi_max_300_hoac_5_lan_max_videos(monkeypatch):
    # 400 mục đều đã có trong thư viện, max_videos=10 ⇒ trần kéo max(300, 50) = 300 mục rồi dừng.
    ds = [_muc_phang(i) for i in range(1, 401)]
    gia = FakeYtdlp(ds)
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    trang = [0]
    refs = liet_ke_profile_yt_dlp(
        URL_PROFILE,
        max_videos=10,
        proxy=None,
        already_have=lambda ids: set(ids),
        on_skip=lambda _r: None,
        dem_trang=lambda: trang.__setitem__(0, trang[0] + 1),
    )

    assert refs == []
    assert gia.so_muc_da_keo == 300
    assert trang[0] == 20  # 300 / 15 = 20 trang


def test_b_on_stop_du_already_owned_va_thieu_do_het_danh_sach(monkeypatch):
    ds_3 = [_muc_phang(1), _muc_phang(2), _muc_phang(3)]
    monkeypatch.setattr(
        nguon_mod,
        "scrape_music_page_multi",
        lambda *a, **k: pytest.fail("yt-dlp thành công thì không được gọi browser"),
    )

    # 1. Đủ max_videos ⇒ STOP_COMPLETE
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds_3))
    dung_du: list[str] = []
    nguon_ra_du: dict = {}
    ra_du = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=3,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None, "nguon_ra": nguon_ra_du},
        **{**_cb_macdinh(), "on_stop": dung_du.append},
    )
    assert len(ra_du) == 3 and dung_du == [STOP_COMPLETE] and nguon_ra_du == {"nguon": "yt_dlp"}

    # 2. Có mục hợp lệ nhưng thư viện đã có hết ⇒ STOP_ALREADY_OWNED (không rơi về browser)
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds_3))
    dung_het: list[str] = []
    ra_het = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=3,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None},
        **{**_cb_macdinh(), "already_have": lambda ids: set(ids), "on_stop": dung_het.append},
    )
    assert ra_het == [] and dung_het == [STOP_ALREADY_OWNED]

    # 3. Thiếu so với max_videos do hết danh sách ⇒ STOP_STALLED
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds_3))
    dung_thieu: list[str] = []
    ra_thieu = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=10,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None},
        **{**_cb_macdinh(), "on_stop": dung_thieu.append},
    )
    assert len(ra_thieu) == 3 and dung_thieu == [STOP_STALLED]


# ---------------------------------------------------------------------------
# (c) Ném ở extract_info ⇒ None ⇒ TikTokCollection gọi scrape_music_page_multi
# ---------------------------------------------------------------------------

def test_c_extract_info_nem_loi_tra_none_va_roi_ve_scrape_music_page_multi(monkeypatch):
    gia = FakeYtdlp([], loi_extract=RuntimeError("HTTP Error 403"))
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    goi_browser: list[tuple[str, dict]] = []
    ref_browser = [VideoRef(video_id=_id_tt(99), url=f"{URL_PROFILE}/video/{_id_tt(99)}")]
    monkeypatch.setattr(
        nguon_mod,
        "scrape_music_page_multi",
        lambda url, **kw: goi_browser.append((url, kw)) or ref_browser,
    )

    nguon_ra: dict = {}
    ra = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=5,
        proxy="http://p:8080",
        cookies_path="/tmp/ck.json",
        passes=2,
        max_seconds=120.0,
        kw_profile={"profile_dir": "/tmp/prof", "nguon_ra": nguon_ra},
        **_cb_macdinh(),
    )

    assert ra == ref_browser
    assert nguon_ra == {"nguon": "browser"}
    assert len(goi_browser) == 1
    assert goi_browser[0][0] == URL_PROFILE
    assert goi_browser[0][1]["profile_dir"] == "/tmp/prof"
    assert "nguon_ra" not in goi_browser[0][1], "khoá nguon_ra không được lọt vào scrape_music_page_multi"


# ---------------------------------------------------------------------------
# (d) 0 mục ⇒ None ⇒ rơi browser
# ---------------------------------------------------------------------------

def test_d_0_muc_tra_none_va_roi_ve_browser(monkeypatch):
    gia = FakeYtdlp([])
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    goi_browser: list[str] = []
    ref_browser = [VideoRef(video_id=_id_tt(1), url=f"{URL_PROFILE}/video/{_id_tt(1)}")]
    monkeypatch.setattr(
        nguon_mod,
        "scrape_music_page_multi",
        lambda url, **kw: goi_browser.append(url) or ref_browser,
    )

    nguon_ra: dict = {}
    ra = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=5,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None, "nguon_ra": nguon_ra},
        **_cb_macdinh(),
    )

    assert ra == ref_browser
    assert goi_browser == [URL_PROFILE]
    assert nguon_ra == {"nguon": "browser"}


# ---------------------------------------------------------------------------
# (e) Lỗi giữa chừng sau 3 mục ⇒ trả 3 (không rơi về browser)
# ---------------------------------------------------------------------------

def test_e_loi_giua_chung_sau_3_muc_tra_3_muc_da_co(monkeypatch):
    ds = [_muc_phang(1), _muc_phang(2), _muc_phang(3), _muc_phang(4), _muc_phang(5)]
    gia = FakeYtdlp(ds, loi_o_muc=3, loi_giua=RuntimeError("trang 2 lỗi mạng"))
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)
    monkeypatch.setattr(
        nguon_mod,
        "scrape_music_page_multi",
        lambda *a, **k: pytest.fail("đã có 3 mục từ yt-dlp thì không được rơi về browser"),
    )

    dung: list[str] = []
    nguon_ra: dict = {}
    ra = TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=10,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None, "nguon_ra": nguon_ra},
        **{**_cb_macdinh(), "on_stop": dung.append},
    )

    assert [r.video_id for r in ra] == [_id_tt(1), _id_tt(2), _id_tt(3)]
    assert dung == [STOP_STALLED]
    assert nguon_ra == {"nguon": "yt_dlp"}


# ---------------------------------------------------------------------------
# (f) Env VIDEODL_PROFILE_YT_DLP="0" ⇒ không gọi YoutubeDL, trả None ngay
# ---------------------------------------------------------------------------

def test_f_env_tat_khong_goi_youtubedl_va_roi_ve_browser(monkeypatch):
    monkeypatch.setenv(ENV_PROFILE_YT_DLP, "0")
    monkeypatch.setattr(
        prof_yt,
        "YoutubeDL",
        lambda *a, **k: pytest.fail("VIDEODL_PROFILE_YT_DLP=0 thì không được khởi tạo YoutubeDL"),
    )

    assert liet_ke_profile_yt_dlp(URL_PROFILE, max_videos=5) is None

    goi_browser: list[str] = []
    monkeypatch.setattr(
        nguon_mod,
        "scrape_music_page_multi",
        lambda url, **kw: goi_browser.append(url) or [],
    )
    nguon_ra: dict = {}
    TikTokCollection().liet_ke(
        URL_PROFILE,
        max_videos=5,
        proxy=None,
        cookies_path=None,
        passes=1,
        max_seconds=60.0,
        kw_profile={"profile_dir": None, "nguon_ra": nguon_ra},
        **_cb_macdinh(),
    )
    assert goi_browser == [URL_PROFILE]
    assert nguon_ra == {"nguon": "browser"}


# ---------------------------------------------------------------------------
# (g) ID rác bị bỏ; kiểm dựng URL + log INFO 1 dòng không rò URL/query/cookie
# ---------------------------------------------------------------------------

def test_g_id_rac_bi_bo_va_url_duoc_dung_dung_dang(monkeypatch, caplog):
    ds = [
        None,
        "khong-phai-dict",
        {"id": None},
        {"id": "abc123456789012345"},          # có chữ cái
        {"id": "12345678901234"},              # 14 chữ số (< 15)
        {"id": "1" * 26},                      # 26 chữ số (> 25)
        {"id": f"tt-{_id_tt(1)}"},             # có tiền tố
        _muc_phang(1, url=None),               # thiếu url ⇒ tự dựng từ handle trang profile
        _muc_phang(2, url="https://evil.example/video/123"),  # không phải tiktok ⇒ tự dựng từ handle
        _muc_phang(3, url=f"https://www.tiktok.com/@khac/video/{_id_tt(3)}"),  # URL TikTok hợp lệ ⇒ ưu tiên giữ
    ]
    gia = FakeYtdlp(ds)
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)

    with caplog.at_level(logging.INFO, logger="ttmd"):
        refs = liet_ke_profile_yt_dlp(URL_PROFILE_CO_QUERY, max_videos=5)

    assert refs is not None
    assert [(r.video_id, r.url) for r in refs] == [
        (_id_tt(1), f"https://www.tiktok.com/@lynherne/video/{_id_tt(1)}"),
        (_id_tt(2), f"https://www.tiktok.com/@lynherne/video/{_id_tt(2)}"),
        (_id_tt(3), f"https://www.tiktok.com/@khac/video/{_id_tt(3)}"),
    ]
    dong_info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(dong_info) == 1
    assert "keo=10" in dong_info[0] and "moi=3" in dong_info[0] and "da_co=0" in dong_info[0]
    assert "lynherne" not in dong_info[0]
    assert "bi_mat_123" not in dong_info[0]
    assert "tiktok.com" not in dong_info[0]


def test_g_toan_id_rac_tra_none(monkeypatch):
    ds = [{"id": "rac"}, {"id": "123"}, {"id": None}]
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds))
    assert liet_ke_profile_yt_dlp(URL_PROFILE, max_videos=5) is None


# ---------------------------------------------------------------------------
# (h) Test queue: yt-dlp trả < max_videos + cờ profile-captcha BẬT ⇒ KHÔNG vào cho_xac_minh,
#     giữ nguyên refs; nhánh browser cùng điều kiện ⇒ vẫn có khong_do_duoc_feed.
#     Và khi cờ profile-captcha TẮT, nhánh yt-dlp vẫn chạy.
# ---------------------------------------------------------------------------

def test_h_queue_yt_dlp_tra_it_hon_max_khi_co_profile_captcha_bat_khong_vao_cho_xac_minh(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    db = tmp_path / "data" / "jobs.db"
    models.init_db(db)

    ds_2 = [_muc_phang(1, title="v1"), _muc_phang(2, title="v2")]
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds_2))
    monkeypatch.setattr(
        scraper_mod,
        "scrape_music_page",
        lambda *a, **k: pytest.fail("yt-dlp thành công thì không được gọi trình duyệt"),
    )

    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    xac_minh: dict = {}
    dung: dict = {}
    refs = queue_mod._fetch_refs(
        URL_PROFILE,
        max_videos=10,
        cookies_path=None,
        db_path=db,
        job_id=jid,
        ly_do_ra=dung,
        xac_minh_ra=xac_minh,
    )

    assert [r.video_id for r in refs] == [_id_tt(1), _id_tt(2)]
    assert xac_minh == {}, "nguồn yt-dlp trả < max_videos không được kích hoạt ly_do_can_xac_minh"
    assert dung.get("ly_do") == STOP_STALLED

    # Chạy cả `process_job`: không vào `cho_xac_minh`, giữ đủ 2 refs đưa vào `download_all`.
    job1 = models.claim_next_pending_job(db)
    assert job1["id"] == jid
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp(ds_2))
    da_tai: list[list[str]] = []
    monkeypatch.setattr(
        queue_mod,
        "download_all",
        lambda r_list, *a, **k: da_tai.append([r.video_id for r in r_list]),
    )
    process_job(db, tmp_path / "dl", tmp_path / "ck", job1)

    sau = models.get_job(db, jid)
    assert sau["trang_thai"] != "cho_xac_minh"
    assert sau["tim_thay"] == 2
    assert da_tai == [[_id_tt(1), _id_tt(2)]]


def test_h_queue_nhanh_browser_cung_dieu_kien_van_co_khong_do_duoc_feed(monkeypatch, tmp_path):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    db = tmp_path / "data" / "jobs.db"
    models.init_db(db)

    # yt-dlp trả 0 mục ⇒ rơi về browser; browser trả 2 link nhưng thống kê feed 0/0 (< max_videos=10).
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp([]))
    ref_lac = [
        VideoRef(video_id=_id_tt(1), url=f"{URL_PROFILE}/video/{_id_tt(1)}"),
        VideoRef(video_id=_id_tt(2), url=f"{URL_PROFILE}/video/{_id_tt(2)}"),
    ]
    goi_kw: list[dict] = []

    def _browser_gia(url, **kw):
        goi_kw.append(dict(kw))
        return list(ref_lac)

    monkeypatch.setattr(scraper_mod, "scrape_music_page", _browser_gia)
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda _s: None)

    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    xac_minh: dict = {}
    refs = queue_mod._fetch_refs(
        URL_PROFILE,
        max_videos=10,
        cookies_path=None,
        db_path=db,
        job_id=jid,
        xac_minh_ra=xac_minh,
    )

    assert len(refs) == 2
    assert xac_minh == {"ly_do": "khong_do_duoc_feed"}
    assert "nguon_ra" not in goi_kw[0], "khoá nguon_ra không được lọt xuống scrape_music_page"

    # Chạy `process_job` trên cùng điều kiện ⇒ job vào `cho_xac_minh`, không gọi `download_all`.
    job1 = models.claim_next_pending_job(db)
    assert job1["id"] == jid
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp([]))
    monkeypatch.setattr(
        queue_mod,
        "download_all",
        lambda *a, **k: pytest.fail("nhánh browser đòi xác minh thì không được tải link lạc"),
    )
    process_job(db, tmp_path / "dl", tmp_path / "ck", job1)
    sau = models.get_job(db, jid)
    assert sau["trang_thai"] == "cho_xac_minh"
    assert sau["ly_do_dung"] == "khong_do_duoc_feed"


def test_h_queue_nhanh_yt_dlp_van_chay_khi_co_profile_captcha_tat(monkeypatch, tmp_path):
    # Cờ profile-captcha TẮT (mặc định: kw_profile chỉ {"profile_dir": None}) ⇒ yt-dlp vẫn chạy trước.
    db = tmp_path / "data" / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(prof_yt, "YoutubeDL", FakeYtdlp([_muc_phang(1), _muc_phang(2)]))
    monkeypatch.setattr(
        scraper_mod,
        "scrape_music_page",
        lambda *a, **k: pytest.fail("cờ profile-captcha tắt nhưng yt-dlp sống thì không được gọi browser"),
    )

    jid = models.create_job(db, URL_PROFILE, 5, "a@x.vn")
    refs = queue_mod._fetch_refs(
        URL_PROFILE,
        max_videos=5,
        cookies_path=None,
        db_path=db,
        job_id=jid,
    )
    assert [r.video_id for r in refs] == [_id_tt(1), _id_tt(2)]
    assert not (db.parent / "profiles").exists()
