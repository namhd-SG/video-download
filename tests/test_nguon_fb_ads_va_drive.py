"""Nguồn Facebook Ads Library và thư mục Google Drive nối vào hàng đợi web.

Không mạng, không mock DB: `jobs.db` file thật trong tmp_path, `process_job` thật. Chỉ RANH GIỚI
bị giả: `gdown` (module thư viện, qua `gdrive.gdown`), `scrape_ads_library` (Playwright),
`_download_url_direct` (HTTP tới FBCDN), `verify_video_stream` (ffmpeg) và hook đẩy Drive.
"""
from __future__ import annotations

import base64
import collections
import io
import json
import logging
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from tiktok_music_downloader import downloader as downloader_mod
from tiktok_music_downloader import gdrive as gdrive_mod
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import scraper_fb
from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.nguon import DriveFolder, FbAdsLibrary, chon_nguon
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED,
    STOP_SOURCE_EMPTY,
    VideoRef,
    che_url,
    parse_fb_video_url,
)
from web import app as app_mod
from web import models
from web import queue as queue_mod
from web.queue import JobWorker

URL_FB = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
          "&country=VN&view_all_page_id=1234567890")
ID_THU_MUC = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
URL_DRIVE = f"https://drive.google.com/drive/folders/{ID_THU_MUC}"
GoogleDriveFileToDownload = collections.namedtuple("GoogleDriveFileToDownload", ("id", "path", "local_path"))

# Id file Drive thật dài tới ~44 ký tự và có `-`/`_`.
VIDEO_DRIVE = [("1vidAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "clip-1.mp4"),
               ("1vidBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "Phim-2.MOV"),
               ("1vid_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", "con/clip-3.webm")]
ANH_DRIVE = [("1imgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "bia.jpg"),
             ("1imgBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "ghi-chu.png")]


# ---------------------------------------------------------------- giả lập ranh giới

class GdownGia:
    """Thay module `gdown`: chỉ có `download_folder` và `download`, ghi lại mọi lời gọi.

    `download_folder(skip_download=False)` ghi MỌI file vào `output` (hành vi thật của gdown) — để
    một cài đặt tải cả thư mục lộ ra ở phép đếm file trên đĩa. `goc` là thư mục làm việc giả, nơi
    gdown ghi khi không có `output`.
    """

    def __init__(self, goc: Path, files=None, loi_liet_ke: Exception | None = None):
        self.goc = goc
        self.files = list(files if files is not None else VIDEO_DRIVE + ANH_DRIVE)
        self.loi_liet_ke = loi_liet_ke
        self.goi_thu_muc: list[dict] = []
        self.goi_file: list[str] = []
        self.dem_tren_dia: list[int] = []   # số file trên đĩa NGAY SAU mỗi lần ghi
        self.dem_ngay_truoc: list[int] = []  # ... NGAY TRƯỚC mỗi lần ghi
        self.dem_dia = lambda: 0

    def download_folder(self, url=None, output=None, skip_download=False, **kw):
        self.goi_thu_muc.append({"url": url, "output": output, "skip_download": skip_download, **kw})
        if self.loi_liet_ke is not None:
            raise self.loi_liet_ke
        ra = []
        for fid, path in self.files:
            ra_path = (Path(output) if output else self.goc) / path
            if skip_download:
                ra.append(GoogleDriveFileToDownload(fid, path, str(ra_path)))
            else:
                ra_path.parent.mkdir(parents=True, exist_ok=True)
                ra_path.write_bytes(b"x" * 10)
                ra.append(str(ra_path))
        return ra

    def download(self, url=None, output=None, id=None, **kw):
        self.goi_file.append(id)
        self.dem_ngay_truoc.append(self.dem_dia())
        Path(output).write_bytes(b"VIDEO" * 100)
        self.dem_tren_dia.append(self.dem_dia())
        return output


def _dem_file(*goc: Path):
    def dem() -> int:
        return sum(1 for g in goc if g.exists() for p in g.rglob("*") if p.is_file())
    return dem


def _cai_gdown(monkeypatch, tmp_path, **kw) -> GdownGia:
    g = GdownGia(tmp_path / "cwd", **kw)
    (tmp_path / "cwd").mkdir(exist_ok=True)
    g.dem_dia = _dem_file(tmp_path / "cwd", tmp_path / "dl")
    monkeypatch.setattr(gdrive_mod, "gdown", g)
    return g


class HookDayDrive:
    """Thay hook đẩy Drive: ghi lại số file trên đĩa LÚC được gọi, ghi `videos` như hook thật, rồi XOÁ file."""

    def __init__(self, db, dem_dia):
        self.db, self.dem_dia = db, dem_dia
        self.dem_luc_goi: list[int] = []
        self.ids: list[str] = []

    def __call__(self, *, job_id, ref, path, db_path=None):
        self.dem_luc_goi.append(self.dem_dia())
        self.ids.append(ref.video_id)
        models.record_video(self.db, job_id=job_id, video_id=ref.video_id, url=ref.url, title=ref.title)
        path.unlink()
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="x")


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "jobs.db"
    models.init_db(p)
    return p


@pytest.fixture
def nhanh(monkeypatch):
    """Bỏ nghỉ jitter giữa hai lượt tải và thay ffmpeg bằng phép kiểm file tồn tại, không rỗng."""
    class KhongNghi:
        def __init__(self, *a, **k): pass
        def wait(self): pass
    monkeypatch.setattr(downloader_mod, "JitterThrottle", KhongNghi)
    monkeypatch.setattr(queue_mod, "verify_video_stream",
                        lambda p, *a, **k: p.exists() and p.stat().st_size > 0)


def _chay_job(db, tmp_path, url, so_luong, nen_tang, hook):
    jid = models.create_job(db, url, so_luong, "a@x.vn", nen_tang=nen_tang)
    job = models.claim_next_pending_job(db, lane=models.LANE_KHAC)
    assert job is not None and job["id"] == jid
    queue_mod.process_job(db, tmp_path / "dl", tmp_path / "ck", job, lifecycle_hook=hook)
    return models.get_job(db, jid)


# ---------------------------------------------------------------- định tuyến + lane

def test_chon_nguon_nhan_fb_ads_va_drive():
    assert chon_nguon(URL_FB).ten == "fb_ads"
    assert chon_nguon(URL_DRIVE).ten == "drive"
    assert chon_nguon(f"https://drive.google.com/drive/u/1/folders/{ID_THU_MUC}").ten == "drive"
    # Link lẻ Facebook / file Drive đơn không phải trang Ads Library / thư mục.
    assert chon_nguon("https://www.facebook.com/watch/?v=1") is None
    assert chon_nguon("https://drive.google.com/file/d/abc/view") is None


def test_fb_ads_nhan_dung_tap_url_khong_nhan_moi_thu():
    n = FbAdsLibrary()
    assert n.nhan(URL_FB)
    for url in ("https://www.tiktok.com/@a", URL_DRIVE, "https://example.com/ads/library/?x=1", "x"):
        assert not n.nhan(url), url
    d = DriveFolder()
    assert d.nhan(URL_DRIVE) and not d.nhan(URL_FB) and not d.nhan("https://www.tiktok.com/music/a-1")


def _dung_app(db, monkeypatch):
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)


@pytest.mark.parametrize("url,ten", [(URL_FB, "fb_ads"), (URL_DRIVE, "drive")])
def test_post_jobs_ghi_nen_tang_va_chi_lane_khac_nhat(db, monkeypatch, url, ten):
    _dung_app(db, monkeypatch)
    ra = app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=5), nguoi_tao="a@x.vn")
    assert ra["nen_tang"] == ten and ra["trang_thai"] == "pending"
    assert models.get_job(db, ra["id"])["nen_tang"] == ten
    # Lane TikTok KHÔNG BAO GIỜ nhặt; lane khac nhặt đúng job đó.
    assert models.claim_next_pending_job(db, lane=models.LANE_TIKTOK) is None
    assert models.claim_next_pending_job(db, uu_tien_cho_giai=True, lane=models.LANE_TIKTOK) is None
    nhat = models.claim_next_pending_job(db, lane=models.LANE_KHAC)
    assert nhat is not None and nhat["id"] == ra["id"]


def test_hai_worker_that_moi_lane_chi_xu_ly_job_cua_minh(db, monkeypatch, tmp_path):
    _dung_app(db, monkeypatch)
    ids = {}
    for url in (URL_FB, URL_DRIVE, "https://www.tiktok.com/tag/abc"):
        ids[url] = app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=1),
                                      nguoi_tao="a@x.vn")["id"]
    da_xu_ly: dict[str, list[int]] = {"tiktok": [], "khac": []}

    def fn_cua(lane):
        def fn(db_path, _d, _c, job):
            da_xu_ly[lane].append(job["id"])
            models.finish_job(db_path, job["id"], "done")
        return fn

    class Dia:
        ok = True
        reason = ""

    ws = [JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=0.02, lane=lane,
                    process_job_fn=fn_cua(lane), disk_guard_fn=lambda _p: Dia())
          for lane in ("tiktok", "khac")]
    for w in ws:
        w.start()
    try:
        han = time.monotonic() + 5
        while time.monotonic() < han and sum(map(len, da_xu_ly.values())) < 3:
            time.sleep(0.02)
    finally:
        for w in ws:
            w.stop()
    assert da_xu_ly["tiktok"] == [ids["https://www.tiktok.com/tag/abc"]]
    assert sorted(da_xu_ly["khac"]) == sorted([ids[URL_FB], ids[URL_DRIVE]])


def test_400_khi_khong_nguon_nao_nhan_liet_ke_cac_loai_link(db, monkeypatch):
    _dung_app(db, monkeypatch)
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url="https://www.youtube.com/watch?v=a", so_luong=5),
                           nguoi_tao="a@x.vn")
    assert e.value.status_code == 400
    for chu in ("TikTok", "Facebook Ads Library", "Google Drive"):
        assert chu in e.value.detail
    assert models.list_jobs(db, None) == []


# ---------------------------------------------------------------- Drive

def test_drive_liet_ke_dung_3_video_bo_anh_va_khong_tai(monkeypatch, tmp_path):
    g = _cai_gdown(monkeypatch, tmp_path)
    bo_qua: list[str] = []
    dung: list[str] = []
    refs = DriveFolder().liet_ke(URL_DRIVE, max_videos=50, already_have=lambda ids: set(),
                                 on_skip=lambda r: bo_qua.append(r.video_id), on_stop=dung.append)
    assert [r.video_id for r in refs] == [f"gd-{fid}" for fid, _ in VIDEO_DRIVE]
    assert [r.title for r in refs] == ["clip-1", "Phim-2", "clip-3"]
    assert bo_qua == [] and dung == []
    # Liệt kê KHÔNG tải: mọi lời gọi `download_folder` đều `skip_download=True`, đĩa trống.
    assert g.goi_thu_muc and all(c["skip_download"] is True for c in g.goi_thu_muc)
    assert g.dem_dia() == 0 and g.goi_file == []


def test_drive_tran_max_videos_ap_dung_sau_khi_loc_trung(monkeypatch, tmp_path):
    _cai_gdown(monkeypatch, tmp_path)
    da_co = {f"gd-{VIDEO_DRIVE[0][0]}"}
    bo_qua: list[str] = []
    refs = DriveFolder().liet_ke(URL_DRIVE, max_videos=1, already_have=lambda ids: da_co & set(ids),
                                 on_skip=lambda r: bo_qua.append(r.video_id), on_stop=lambda s: None)
    # Cái đã có bị bỏ (còn dấu nguồn), trần 1 áp lên video MỚI nên lấy cái thứ hai, không phải cái đầu.
    assert [r.video_id for r in refs] == [f"gd-{VIDEO_DRIVE[1][0]}"]
    assert bo_qua == [f"gd-{VIDEO_DRIVE[0][0]}"]


def test_drive_loc_theo_duoi_video(monkeypatch, tmp_path):
    ds = [(f"1id{i}", ten) for i, ten in enumerate(
        ["a.mp4", "b.MOV", "c.m4v", "d.webm", "e.mkv", "f.jpg", "g.pdf", "h.srt", "khong-duoi", "i.mp4.txt"])]
    _cai_gdown(monkeypatch, tmp_path, files=ds)
    refs = DriveFolder().liet_ke(URL_DRIVE, max_videos=50, already_have=lambda ids: set(),
                                 on_skip=lambda r: None, on_stop=lambda s: None)
    assert [r.video_id for r in refs] == ["gd-1id0", "gd-1id1", "gd-1id2", "gd-1id3", "gd-1id4"]


def test_drive_thu_muc_toan_anh_hoac_rong_bao_source_empty(monkeypatch, tmp_path):
    _cai_gdown(monkeypatch, tmp_path, files=ANH_DRIVE)
    dung: list[str] = []
    refs = DriveFolder().liet_ke(URL_DRIVE, max_videos=5, already_have=lambda ids: set(),
                                 on_skip=lambda r: None, on_stop=dung.append)
    assert refs == [] and dung == [STOP_SOURCE_EMPTY]


def test_drive_thu_muc_da_co_het_bao_already_owned(monkeypatch, tmp_path):
    _cai_gdown(monkeypatch, tmp_path)
    dung: list[str] = []
    refs = DriveFolder().liet_ke(URL_DRIVE, max_videos=5, already_have=lambda ids: set(ids),
                                 on_skip=lambda r: None, on_stop=dung.append)
    assert refs == [] and dung == [STOP_ALREADY_OWNED]


def test_drive_loi_liet_ke_thanh_loi_co_ten_nguon_khong_mang_id(monkeypatch, tmp_path):
    _cai_gdown(monkeypatch, tmp_path,
               loi_liet_ke=ConnectionError(f"Cannot retrieve the folder https://drive.google.com/drive/folders/{ID_THU_MUC}"))
    with pytest.raises(RuntimeError) as e:
        DriveFolder().liet_ke(URL_DRIVE, max_videos=5, already_have=lambda ids: set(),
                              on_skip=lambda r: None, on_stop=lambda s: None)
    assert "drive" in str(e.value) and ID_THU_MUC not in str(e.value)


def test_drive_tai_tung_file_mot_file_tren_dia_moi_luc(db, monkeypatch, tmp_path, nhanh):
    """Job Drive đi trọn `process_job`: mỗi file tải theo id, qua verify, hook đẩy Drive XOÁ nó, rồi mới
    tới file kế. ĐỘT BIẾN (a): `liet_ke` tải cả thư mục (`skip_download=False`) ⇒ nhiều file cùng nằm
    trên đĩa và cờ `skip_download` sai ⇒ ĐỎ."""
    g = _cai_gdown(monkeypatch, tmp_path)
    hook = HookDayDrive(db, g.dem_dia)
    job = _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", hook)
    assert job["trang_thai"] == "done" and job["xong"] == 3 and job["loi"] == 0
    assert hook.ids == [f"gd-{fid}" for fid, _ in VIDEO_DRIVE]
    assert g.goi_file == [fid for fid, _ in VIDEO_DRIVE], "tải từng file theo id, theo thứ tự thư mục"
    # Trước mỗi lần ghi đĩa trống (file trước đã xoá), sau khi ghi đúng một file; hook thấy đúng một file.
    assert g.dem_ngay_truoc == [0, 0, 0] and g.dem_tren_dia == [1, 1, 1]
    assert hook.dem_luc_goi == [1, 1, 1]
    assert all(c["skip_download"] is True for c in g.goi_thu_muc)
    assert g.dem_dia() == 0, "đĩa sau job = trước job"


def test_drive_tran_max_videos_cua_job(db, monkeypatch, tmp_path, nhanh):
    g = _cai_gdown(monkeypatch, tmp_path)
    job = _chay_job(db, tmp_path, URL_DRIVE, 2, "drive", HookDayDrive(db, g.dem_dia))
    assert job["xong"] == 2 and len(g.goi_file) == 2


def test_drive_chay_lai_job_bo_qua_cai_da_co(db, monkeypatch, tmp_path, nhanh):
    g = _cai_gdown(monkeypatch, tmp_path)
    _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", HookDayDrive(db, g.dem_dia))
    g.goi_file.clear()
    job2 = _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", HookDayDrive(db, g.dem_dia))
    assert g.goi_file == [], "id `gd-…` có trong `videos` thì không tải lại"
    assert job2["bo_qua"] == 3 and job2["ly_do_dung"] == STOP_ALREADY_OWNED
    assert job2["trang_thai"] == "done"


def test_drive_file_loi_khong_de_lai_tep_dan_va_job_tiep_tuc(db, monkeypatch, tmp_path, nhanh):
    g = _cai_gdown(monkeypatch, tmp_path)
    goc_download = g.download

    def download_trung(url=None, output=None, id=None, **kw):
        if id == VIDEO_DRIVE[1][0]:
            g.goi_file.append(id)
            Path(output).write_bytes(b"")       # quota: gdown để lại tệp rỗng
            return output
        return goc_download(url=url, output=output, id=id, **kw)

    g.download = download_trung
    job = _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", HookDayDrive(db, g.dem_dia))
    assert job["xong"] == 2 and job["loi"] == 1 and job["trang_thai"] == "done"
    assert g.dem_dia() == 0, "không để lại `.part` hay file rỗng"


# ---------------------------------------------------------------- Facebook Ads Library

def _url_fbcdn(asset: int, ky: str = "AAA") -> str:
    efg = base64.b64encode(json.dumps({"xpv_asset_id": asset, "vencode_tag": "x"}, separators=(",", ":")).encode()).decode()
    return (f"https://video.xx.fbcdn.net/o1/v/t2/f2/m366/{ky}.mp4?efg={efg}"
            f"&_nc_ht=video.xx.fbcdn.net&oh=00_AfSECRETHASH&oe=6700ABCD")


class FakePage:
    """Trang Ads Library đã render: `eval_on_selector_all("video")` trả src; cuộn thêm lô mới."""

    def __init__(self, lo: list[list[str]]):
        self.lo, self.i = lo, 0

    def eval_on_selector_all(self, sel, js):
        return [u for batch in self.lo[: self.i + 1] for u in batch]

    def evaluate(self, js):
        self.i = min(self.i + 1, len(self.lo) - 1)


def test_scraper_fb_dung_id_fb_asset_tu_html_mau(monkeypatch):
    monkeypatch.setattr(scraper_fb.time, "sleep", lambda s: None)
    page = FakePage([[_url_fbcdn(111), _url_fbcdn(222, "BBB")], [_url_fbcdn(333, "CCC")]])
    refs = scraper_fb._auto_scroll(page, max_videos=10, scroll_pause=0, idle_rounds=2)
    # `_collect_video_urls` trả set ⇒ thứ tự trong cùng một lô không xác định; so theo tập.
    assert sorted(r.video_id for r in refs) == ["fb-111", "fb-222", "fb-333"]


def _gia_scrape(monkeypatch, refs, goi=None):
    def scrape(url, **kw):
        if goi is not None:
            goi.append((url, kw))
        return list(refs)
    monkeypatch.setattr(nguon_mod, "scrape_ads_library", scrape)


def test_fb_liet_ke_headless_khong_cookie_max_theo_job(monkeypatch):
    goi: list = []
    _gia_scrape(monkeypatch, [parse_fb_video_url(_url_fbcdn(1))], goi)
    refs = FbAdsLibrary().liet_ke(URL_FB, max_videos=7, proxy=None, cookies_path="/se/khong/dung",
                                  already_have=lambda ids: set(), on_skip=lambda r: None,
                                  on_stop=lambda s: None, passes=3, kw_profile={"profile_dir": "p"})
    assert [r.video_id for r in refs] == ["fb-1"]
    (url, kw), = goi
    assert url == URL_FB and kw["max_videos"] == 7 and kw["headless"] is True
    assert kw["profile_dir"] is None and kw["proxy"] is None and "cookies_path" not in kw


def test_fb_khong_ra_video_nao_bao_source_empty_co_tieng_nguon(monkeypatch, caplog):
    _gia_scrape(monkeypatch, [])
    dung: list[str] = []
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        refs = FbAdsLibrary().liet_ke(URL_FB, max_videos=5, already_have=lambda ids: set(),
                                      on_skip=lambda r: None, on_stop=dung.append)
    assert refs == [] and dung == [STOP_SOURCE_EMPTY]
    assert any("fb_ads" in r.getMessage() for r in caplog.records)


def test_fb_ref_di_tai_truc_tiep_khong_qua_ytdlp(db, monkeypatch, tmp_path, nhanh):
    """ĐỘT BIẾN thêm: định tuyến `fb-` về yt-dlp ⇒ `_download_one` bị gọi ⇒ test này ĐỎ."""
    _gia_scrape(monkeypatch, [parse_fb_video_url(_url_fbcdn(a, f"v{a}")) for a in (11, 22, 33)])
    truc_tiep: list[str] = []

    def tai_truc_tiep(url, target, proxy):
        truc_tiep.append(target.name)
        target.write_bytes(b"VIDEO" * 50)

    monkeypatch.setattr(downloader_mod, "_download_url_direct", tai_truc_tiep)
    monkeypatch.setattr(downloader_mod, "_download_one",
                        lambda *a, **k: pytest.fail("ref fb- không được đi yt-dlp"))
    hook = HookDayDrive(db, _dem_file(tmp_path / "dl"))
    job = _chay_job(db, tmp_path, URL_FB, 10, "fb_ads", hook)
    assert truc_tiep == ["fb-11.mp4", "fb-22.mp4", "fb-33.mp4"]
    assert job["trang_thai"] == "done" and job["xong"] == 3
    assert hook.dem_luc_goi == [1, 1, 1]


def test_fb_chay_lai_bo_qua_id_da_co(db, monkeypatch, tmp_path, nhanh):
    _gia_scrape(monkeypatch, [parse_fb_video_url(_url_fbcdn(a, f"v{a}")) for a in (11, 22)])
    dem = {"n": 0}

    def tai(url, target, proxy):
        dem["n"] += 1
        target.write_bytes(b"V" * 50)

    monkeypatch.setattr(downloader_mod, "_download_url_direct", tai)
    hook = HookDayDrive(db, _dem_file(tmp_path / "dl"))
    _chay_job(db, tmp_path, URL_FB, 10, "fb_ads", hook)
    dem["n"] = 0
    job2 = _chay_job(db, tmp_path, URL_FB, 10, "fb_ads", hook)
    assert dem["n"] == 0 and job2["bo_qua"] == 2 and job2["ly_do_dung"] == STOP_ALREADY_OWNED


def test_job_fb_khong_bi_jar_cookie_tiktok_hong_chan(db, monkeypatch, tmp_path, nhanh):
    """Jar TikTok hết hạn dừng job TikTok; job Facebook Ads / Drive không dùng cookie nên không bị ảnh hưởng."""
    chet = []
    monkeypatch.setattr(queue_mod, "cookies_path_for_user", lambda d, u: chet.append(u) or "/jar/hong")
    monkeypatch.setattr(queue_mod, "ly_do_jar_khong_dung_duoc", lambda p: "cookie_het_han")
    _gia_scrape(monkeypatch, [parse_fb_video_url(_url_fbcdn(5, "v5"))])
    monkeypatch.setattr(downloader_mod, "_download_url_direct",
                        lambda url, target, proxy: target.write_bytes(b"V" * 50))
    job = _chay_job(db, tmp_path, URL_FB, 3, "fb_ads", HookDayDrive(db, _dem_file(tmp_path / "dl")))
    assert job["trang_thai"] == "done" and job["xong"] == 1 and chet == []


# ---------------------------------------------------------------- log

FBCDN_CO_QUERY = ("https://scontent-sin6-1.xx.fbcdn.net/o1/v/t2/f2/m366/abc.mp4?efg=eyJ4cHZfYXNzZXRfaWQiOjF9"
                  "&oh=00_AfSECRETHASH&oe=6700ABCD")


def test_che_url_che_fbcdn_co_query_ky_hmac():
    for t in (f"✗ fb-1: 410 Client Error: Gone for url: {FBCDN_CO_QUERY}",
              f"({FBCDN_CO_QUERY})",
              "ConnectionError host=scontent-sin6-1.xx.fbcdn.net/o1/v/t2/f2/m366/abc.mp4?oh=00_AfSECRETHASH&oe=6700"):
        ra = che_url(t)
        assert "oh=" not in ra and "oe=" not in ra and "fbcdn" not in ra and "AfSECRET" not in ra, ra
    assert "410 Client Error" in che_url(f"410 Client Error: Gone for url: {FBCDN_CO_QUERY}"), "giữ chữ chẩn đoán"


@pytest.mark.parametrize("t", [
    f"navigating to https://drive.google.com/drive/folders/{ID_THU_MUC}?usp=sharing",
    f"link drive.google.com/drive/folders/{ID_THU_MUC}",
    f"link drive.google.com/drive/u/1/folders/{ID_THU_MUC}",
    f"Cannot retrieve the public link of the file https://drive.google.com/uc?id={VIDEO_DRIVE[0][0]}",
    f"Failed to download folders/{ID_THU_MUC}/clip.mp4",
    f"✓ gd-{VIDEO_DRIVE[0][0]}.mp4",
    f"✗ gd-{VIDEO_DRIVE[2][0]}: Drive không trả nội dung file",
])
def test_che_url_che_id_drive(t):
    """ĐỘT BIẾN (e): bỏ mẫu che Drive ⇒ ĐỎ (các dạng không scheme / `gd-<id>` lọt qua mẫu URL)."""
    ra = che_url(t)
    for fid, _ in VIDEO_DRIVE:
        assert fid not in ra, ra
    assert ID_THU_MUC not in ra, ra


def test_che_url_giu_nguyen_id_tiktok_va_fb_asset():
    """Id TikTok (số) và `fb-<asset>` công khai: GIỮ để người vận hành đối chiếu."""
    assert che_url("✓ 7692740350766517525.mp4 / fb-123456789.mp4") == "✓ 7692740350766517525.mp4 / fb-123456789.mp4"


def test_log_job_drive_va_fb_khong_mang_id_hay_url(db, monkeypatch, tmp_path, nhanh):
    """Cả vòng đời job (qua `CheUrlFormatter` như dịch vụ thật), kể cả đường lỗi, không rò id/URL."""
    from web.app import CheUrlFormatter

    ra = io.StringIO()
    h = logging.StreamHandler(ra)
    h.setFormatter(CheUrlFormatter("%(levelname)s %(name)s: %(message)s"))
    lg = logging.getLogger()
    cu_lv = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        g = _cai_gdown(monkeypatch, tmp_path)
        # file giữa lỗi để đi qua đường `✗` (id + thông điệp lỗi)
        goc_download = g.download

        def download(url=None, output=None, id=None, **kw):
            if id == VIDEO_DRIVE[1][0]:
                raise RuntimeError(f"Failed to retrieve file url: https://drive.google.com/uc?id={id}")
            return goc_download(url=url, output=output, id=id, **kw)

        g.download = download
        _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", HookDayDrive(db, g.dem_dia))
        # FB: lỗi 410 mang URL FBCDN có `oh=`/`oe=`
        _gia_scrape(monkeypatch, [VideoRef(video_id="fb-77", url=FBCDN_CO_QUERY)])

        def het_han(url, target, proxy):
            raise RuntimeError(f"410 Client Error: Gone for url: {url}")

        monkeypatch.setattr(downloader_mod, "_download_url_direct", het_han)
        _chay_job(db, tmp_path, URL_FB, 5, "fb_ads", HookDayDrive(db, g.dem_dia))
        # Drive: liệt kê hỏng
        g.loi_liet_ke = ConnectionError(f"boom https://drive.google.com/drive/folders/{ID_THU_MUC}")
        _chay_job(db, tmp_path, f"https://drive.google.com/drive/folders/{ID_THU_MUC}x", 5, "drive",
                  HookDayDrive(db, g.dem_dia))
    finally:
        lg.removeHandler(h)
        lg.setLevel(cu_lv)
    text = ra.getvalue()
    assert text, "phải có log để phép kiểm có nghĩa"
    assert "✗" in text and "410 Client Error" in text, text
    for cam in ("oh=", "oe=", "fbcdn", "drive.google.com", ID_THU_MUC, VIDEO_DRIVE[0][0],
                VIDEO_DRIVE[1][0], VIDEO_DRIVE[2][0], "AfSECRET"):
        assert cam not in text, f"{cam!r} lọt vào log:\n{text}"


# ---------------------------------------------------------------- log theo lane

class _Dia:
    def __init__(self, ok, reason=""):
        self.ok, self.reason = ok, reason


@pytest.mark.parametrize("lane", ["tiktok", "khac"])
def test_worker_log_mot_dong_bat_dau_co_ten_lane(db, tmp_path, caplog, lane):
    w = JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01, lane=lane,
                  disk_guard_fn=lambda _p: _Dia(True))
    with caplog.at_level(logging.INFO):
        w.start()
        w.stop()
    dong = [r.getMessage() for r in caplog.records if "bắt đầu" in r.getMessage()]
    assert dong == [f"worker lane {lane}: bắt đầu"]


@pytest.mark.parametrize("lane", ["tiktok", "khac"])
def test_worker_log_cho_dia_kem_ten_lane(db, tmp_path, caplog, lane):
    w = JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01, lane=lane,
                  disk_guard_fn=lambda _p: _Dia(False, "đĩa còn 1 MB"))
    with caplog.at_level(logging.INFO):
        w.start()
        han = time.monotonic() + 3
        while time.monotonic() < han and not any("CHỜ" in r.getMessage() for r in caplog.records):
            time.sleep(0.01)
        w.stop()
    cho = [r.getMessage() for r in caplog.records if "CHỜ" in r.getMessage()]
    assert cho and all(f"lane {lane}" in m and "đĩa còn 1 MB" in m for m in cho), cho


# ---------------------------------------------------------------- ảnh thu nhỏ của id có tiền tố

@pytest.mark.parametrize("video_id", [f"gd-{VIDEO_DRIVE[0][0]}", "fb-123456789", "7692740350766517525"])
def test_thumb_nhan_id_co_tien_to(db, monkeypatch, video_id):
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    with pytest.raises(HTTPException) as e:        # qua cổng hình dạng, rồi 404 vì chưa có ảnh
        app_mod.get_thumb(video_id, nguoi_tao="a@x.vn")
    assert e.value.detail == "chưa có ảnh cho video này"


@pytest.mark.parametrize("video_id", ["gd-", "gd-../x", "gd-a/b", "gd-a.webp", "xx-123", "GD-abc",
                                      "gd-" + "a" * 70, "fb-1 ", "../fb-1"])
def test_thumb_van_chan_hinh_dang_la(db, monkeypatch, video_id):
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    with pytest.raises(HTTPException) as e:
        app_mod.get_thumb(video_id, nguoi_tao="a@x.vn")
    assert e.value.detail == "video_id không hợp lệ"


# ---------------------------------------------------------------- gdown THẬT, chỉ giả phiên HTTP

import re
import requests
from gdown.exceptions import DownloadError as GdownDownloadError


def _phan_hoi(status=200, text="", headers=None, chunks=None, loi_giua_luong=None, content_length=None):
    """`requests.Response` thật; thân là luồng tự dựng để ép đứt / thiếu byte giữa chừng."""
    r = requests.Response()
    r.status_code = status
    r.url = "https://drive.google.com/uc?id=x"
    r._content = text.encode() if chunks is None and loi_giua_luong is None else False
    r.headers.update(headers or {})
    if chunks is not None or loi_giua_luong is not None:
        class Luong:
            def stream(self, n, decode_content=True):
                yield from (chunks or [])
                if loi_giua_luong is not None:
                    raise loi_giua_luong

            def close(self): pass
        r.raw = Luong()
        if content_length is not None:
            r.headers["Content-Length"] = str(content_length)
        r.headers.update({"Content-Type": "video/mp4",
                          "Content-Disposition": 'attachment; filename="clip.mp4"'})
    return r


def _cai_session(monkeypatch, phan_hoi):
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: phan_hoi)


def _tat_ca_duoi(goc: Path):
    return sorted(str(p) for p in goc.rglob("*"))


# Câu chữ lấy từ mã gdown đã cài (`download_folder.py`, `download.py`) — không tự bịa.
@pytest.mark.parametrize("phan_hoi,mong", [
    (_phan_hoi(status=404, text="nope"), "status code 404"),
    (_phan_hoi(status=200, text="<html><body>x</body></html>"), "Failed to parse folder contents"),
])
def test_drive_loi_gdown_that_khong_lo_id_thu_muc_qua_traceback(monkeypatch, phan_hoi, mong):
    """Lỗi THẬT của gdown mang "… folder ID: <id>". Qua `CheUrlFormatter` (cả traceback) không còn id.
    ĐỘT BIẾN: bỏ `from None` ⇒ `__cause__`/ngữ cảnh còn lỗi gốc ⇒ ĐỎ; bỏ mẫu `ID:` ⇒ ĐỎ."""
    from web.app import CheUrlFormatter

    _cai_session(monkeypatch, phan_hoi)
    ra = io.StringIO()
    h = logging.StreamHandler(ra)
    h.setFormatter(CheUrlFormatter("%(levelname)s %(name)s: %(message)s"))
    lg = logging.getLogger("videodl.web")
    lg.addHandler(h)
    try:
        try:
            DriveFolder().liet_ke(URL_DRIVE, max_videos=5, already_have=lambda ids: set(),
                                  on_skip=lambda r: None, on_stop=lambda s: None)
            pytest.fail("phải ném lỗi")
        except RuntimeError as exc:
            assert exc.__cause__ is None and exc.__suppress_context__, "không xích lỗi gốc mang id"
            lg.exception("job crashed")
    finally:
        lg.removeHandler(h)
    text = ra.getvalue()
    assert "Traceback" in text and "nguồn drive" in text and mong in text, text
    assert ID_THU_MUC not in text and "drive.google.com" not in text, text


@pytest.mark.parametrize("t", [
    f"Failed to retrieve folder contents for folder ID: {ID_THU_MUC} (status code 404). You may need",
    f"Failed to parse folder contents for folder ID: {ID_THU_MUC}. The page structure may have changed.",
    f"folder id:{ID_THU_MUC}",
])
def test_che_url_che_dang_folder_id_cua_gdown(t):
    assert ID_THU_MUC not in che_url(t)


def test_che_url_giu_chu_id_ngan_khong_phai_id_drive():
    assert che_url("job ID: 42 xong") == "job ID: 42 xong"


def _gdown_that_tai(monkeypatch, tmp_path, phan_hoi):
    monkeypatch.setattr(gdrive_mod, "gdown", __import__("gdown"))
    _cai_session(monkeypatch, phan_hoi)
    dl = tmp_path / "dl"
    dl.mkdir()
    return dl, dl / "gd-abc.mp4"


def test_drive_tai_that_thanh_cong_chi_con_dung_file_dich(monkeypatch, tmp_path):
    dl, target = _gdown_that_tai(monkeypatch, tmp_path, _phan_hoi(chunks=[b"a" * 300, b"b" * 200], content_length=500))
    gdrive_mod.download_file("abc", target)
    assert _tat_ca_duoi(dl) == [str(target)] and target.stat().st_size == 500


@pytest.mark.parametrize("ten,phan_hoi", [
    ("dut_mang", _phan_hoi(chunks=[b"a" * 300], loi_giua_luong=requests.exceptions.ConnectionError("reset"),
                           content_length=1000)),
    ("thieu_byte", _phan_hoi(chunks=[b"a" * 400], content_length=1000)),
])
def test_drive_tai_dang_do_khong_de_lai_tep_nao(monkeypatch, tmp_path, ten, phan_hoi):
    """gdown THẬT tạo `<tên>.part<rand>.part` và CHỦ Ý giữ khi đứt. ĐỘT BIẾN: bỏ `rmtree` ⇒ ĐỎ."""
    dl, target = _gdown_that_tai(monkeypatch, tmp_path, phan_hoi)
    with pytest.raises(Exception):
        gdrive_mod.download_file("abc", target)
    assert _tat_ca_duoi(dl) == [], "mọi tệp dưới thư mục tải phải biến mất"


# ---------------------------------------------------------------- hiệu năng mẫu che

@pytest.mark.parametrize("mau", ["a" * 200_000, "a." * 100_000, "x-" * 100_000, "1" * 200_000,
                                 "ID: " + "z" * 200_000, "folders/" * 25_000, "drive.google" * 16_000])
def test_che_url_khong_bung_no_tren_chuoi_dai(mau):
    t0 = time.perf_counter()
    che_url(mau, toi_da=None)
    assert time.perf_counter() - t0 < 0.5


def test_che_url_fbcdn_van_che_sau_khi_neo_dau_token():
    ra = che_url("x scontent.xx.fbcdn.net/v/a.mp4?oh=1&oe=2 y")
    assert ra == "x <url> y"


# ---------------------------------------------------------------- cổng đĩa từng file

def test_drive_dung_job_truoc_file_ke_khi_dia_duoi_nguong(db, monkeypatch, tmp_path, nhanh):
    """ĐỘT BIẾN: không truyền hook kiểm đĩa cho `download_all` ⇒ tải đủ 3 file ⇒ ĐỎ."""
    g = _cai_gdown(monkeypatch, tmp_path)
    lan = {"n": 0}

    class Dia:
        def __init__(self, ok): self.ok, self.reason = ok, "đĩa còn 10 MB, dưới ngưỡng an toàn 300 MB"

    def guard(path):
        lan["n"] += 1
        return Dia(lan["n"] <= 1)

    monkeypatch.setattr(queue_mod, "check_disk_guard", guard)
    job = _chay_job(db, tmp_path, URL_DRIVE, 10, "drive", HookDayDrive(db, g.dem_dia))
    assert g.goi_file == [VIDEO_DRIVE[0][0]], "chỉ file đầu được tải"
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "het_dia" and job["xong"] == 1
    assert g.dem_dia() == 0


def test_job_tiktok_khong_bi_cong_dia_moi_file(db, monkeypatch, tmp_path, nhanh):
    monkeypatch.setattr(queue_mod, "check_disk_guard",
                        lambda p: pytest.fail("job TikTok không đi cổng đĩa từng file"))
    refs = [VideoRef(video_id="777", url="https://www.tiktok.com/@a/video/777")]
    monkeypatch.setattr(queue_mod, "_fetch_refs", lambda *a, **k: refs)
    def tai_yt(url, opts):
        Path(opts["outtmpl"] % {"id": "777", "ext": "mp4"}).write_bytes(b"v" * 9)
        return {}

    monkeypatch.setattr(downloader_mod, "_download_one", tai_yt)
    jid = models.create_job(db, "https://www.tiktok.com/tag/abc", 3, "a@x.vn")
    job = models.claim_next_pending_job(db, lane=models.LANE_TIKTOK)
    queue_mod.process_job(db, tmp_path / "dl", tmp_path / "ck", job,
                          lifecycle_hook=HookDayDrive(db, _dem_file(tmp_path / "dl")))
    assert models.get_job(db, jid)["xong"] == 1


# ---------------------------------------------------------------- FB: .part, 403, lọc trùng khi cuộn

class _LuongFb:
    def __init__(self, status=200, loi=None):
        self.status_code, self.loi = status, loi

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass

    def iter_content(self, chunk_size):
        yield b"x" * 100
        if self.loi:
            raise self.loi


def _tat_tenacity(monkeypatch):
    monkeypatch.setattr(downloader_mod._download_url_direct.retry, "sleep", lambda s: None)


def test_fb_tai_dut_giua_luong_khong_de_lai_part(monkeypatch, tmp_path):
    """ĐỘT BIẾN: bỏ `try/finally` xoá `.part` ⇒ ĐỎ."""
    _tat_tenacity(monkeypatch)
    import requests as rq
    monkeypatch.setattr(rq, "get", lambda *a, **k: _LuongFb(loi=rq.exceptions.ConnectionError("reset")))
    with pytest.raises(rq.exceptions.ConnectionError):
        downloader_mod._download_url_direct("https://x.fbcdn.net/a.mp4", tmp_path / "fb-1.mp4", None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("ma", [403, 410])
def test_fb_403_va_410_la_loi_tung_video_khong_retry(monkeypatch, tmp_path, ma):
    """ĐỘT BIẾN: bỏ nhánh 403 ⇒ `raise_for_status` không ném (giả) hoặc retry ⇒ ĐỎ."""
    _tat_tenacity(monkeypatch)
    import requests as rq
    goi = []
    monkeypatch.setattr(rq, "get", lambda *a, **k: goi.append(1) or _LuongFb(status=ma))
    with pytest.raises(RuntimeError, match=str(ma)):
        downloader_mod._download_url_direct("https://x.fbcdn.net/a.mp4", tmp_path / "fb-1.mp4", None)
    assert len(goi) == 1 and list(tmp_path.iterdir()) == []


def test_fb_cuon_den_khi_du_video_moi_khong_dem_cai_da_co(monkeypatch):
    """Trang có 3 video đã có rồi mới tới video mới. `max_videos=2` mà dừng ở 3 ref đầu thì lượt chạy lại
    nhận toàn cái đã có. ĐỘT BIẾN: bỏ `da_co` khỏi điều kiện dừng ⇒ ĐỎ."""
    monkeypatch.setattr(scraper_fb.time, "sleep", lambda s: None)
    page = FakePage([[_url_fbcdn(i, f"k{i}") for i in (1, 2, 3)], [_url_fbcdn(4, "k4")], [_url_fbcdn(5, "k5")]])
    da_co = {"fb-1", "fb-2", "fb-3"}
    refs = scraper_fb._auto_scroll(page, max_videos=2, scroll_pause=0, idle_rounds=2,
                                   da_co=lambda ids: da_co & set(ids))
    assert {"fb-4", "fb-5"} <= {r.video_id for r in refs}


def test_fb_cuon_co_tran_khi_trang_toan_video_da_co(monkeypatch):
    monkeypatch.setattr(scraper_fb.time, "sleep", lambda s: None)
    lo = [[_url_fbcdn(i, f"k{i}") for i in range(b * 3, b * 3 + 3)] for b in range(10)]
    page = FakePage(lo)
    refs = scraper_fb._auto_scroll(page, max_videos=2, scroll_pause=0, idle_rounds=2,
                                   da_co=lambda ids: set(ids))
    assert len(refs) <= 2 * scraper_fb.HE_SO_TRAN_DA_CO + 3, "dừng ở trần, không cuộn vô hạn"


def test_fb_liet_ke_truyen_da_co_cho_trinh_quet(monkeypatch):
    goi: list = []
    _gia_scrape(monkeypatch, [parse_fb_video_url(_url_fbcdn(1))], goi)
    ds = lambda ids: set()
    FbAdsLibrary().liet_ke(URL_FB, max_videos=3, already_have=ds, on_skip=lambda r: None, on_stop=lambda s: None)
    assert goi[0][1]["da_co"] is ds


# ---------------------------------------------------------------- trần ngày chỉ của TikTok

URL_TIKTOK = "https://www.tiktok.com/tag/abc"


def _dung_app_co_tran(db, monkeypatch, tmp_path, toi_da_job=2):
    """Cổng trần THẬT (`daily_cap_rejection`, đếm trên DB thật) với trần job hạ còn `toi_da_job`."""
    from web import lifecycle
    thật = lifecycle.daily_cap_rejection
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "ck")
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection",
                        lambda **kw: thật(max_jobs_per_day=toi_da_job, **kw))


def _tao(url, so_luong=5):
    return app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=so_luong), nguoi_tao="a@x.vn")


def test_nguoi_cham_tran_tiktok_van_tao_duoc_job_drive_va_fb(db, monkeypatch, tmp_path):
    _dung_app_co_tran(db, monkeypatch, tmp_path)
    _tao(URL_TIKTOK), _tao(URL_TIKTOK)
    with pytest.raises(HTTPException) as e:
        _tao(URL_TIKTOK)
    assert e.value.status_code == 429, "đối chứng: trần TikTok đang thật sự chặn"
    assert _tao(URL_DRIVE)["nen_tang"] == "drive"
    assert _tao(URL_FB)["nen_tang"] == "fb_ads"


def test_job_drive_fb_khong_an_vao_tran_tiktok(db, monkeypatch, tmp_path):
    """ĐỘT BIẾN: bỏ lọc `nen_tang` (ở cổng hoặc ở các hàm đếm) ⇒ ĐỎ."""
    from web import lifecycle
    _dung_app_co_tran(db, monkeypatch, tmp_path)
    for _ in range(4):
        _tao(URL_DRIVE)
        _tao(URL_FB)
    assert lifecycle.jobs_today_for_cookie(db, tmp_path / "ck", "a@x.vn") == 0
    assert lifecycle.videos_today_for_cookie(db, tmp_path / "ck", "a@x.vn") == 0
    assert _tao(URL_TIKTOK)["nen_tang"] == "tiktok"
    assert lifecycle.jobs_today_for_cookie(db, tmp_path / "ck", "a@x.vn") == 1


def test_tran_tiktok_cu_khong_doi(db, monkeypatch, tmp_path):
    from web import lifecycle
    _dung_app_co_tran(db, monkeypatch, tmp_path)
    _tao(URL_TIKTOK, 7)
    assert lifecycle.jobs_today_for_cookie(db, tmp_path / "ck", "a@x.vn") == 1
    assert lifecycle.videos_today_for_cookie(db, tmp_path / "ck", "a@x.vn") == 7
    _tao(URL_TIKTOK)
    with pytest.raises(HTTPException) as e:
        _tao(URL_TIKTOK)
    assert e.value.status_code == 429 and "2/2 job" in e.value.detail
    with pytest.raises(HTTPException) as e:        # URL lạ: vẫn qua cổng trần trước, như cũ
        _tao("https://www.youtube.com/watch?v=a")
    assert e.value.status_code == 429


class _TrangDemCuon(FakePage):
    def __init__(self, lo):
        super().__init__(lo)
        self.so_lan_cuon = 0

    def evaluate(self, js):
        self.so_lan_cuon += 1
        super().evaluate(js)


def test_fb_cuon_nhieu_hon_idle_rounds_khi_van_con_video_moi(monkeypatch):
    """Mỗi lần cuộn lộ 2 video mới; cần 9 lần cuộn (> idle_rounds=6) mới đủ 20.
    ĐỘT BIẾN: khôi phục phép so `len(refs)` ngay sau cuộn (chưa thu) ⇒ dừng sau 6 lần cuộn ⇒ ĐỎ."""
    monkeypatch.setattr(scraper_fb.time, "sleep", lambda s: None)
    lo = [[_url_fbcdn(b * 2 + i, f"k{b}-{i}") for i in (1, 2)] for b in range(11)]
    page = _TrangDemCuon(lo)
    refs = scraper_fb._auto_scroll(page, max_videos=20, scroll_pause=0, idle_rounds=6)
    assert len(refs) == 20 and page.so_lan_cuon == 9


def test_fb_het_video_sau_3_lan_cuon_dung_sau_idle_rounds_lan_khong_moi(monkeypatch):
    monkeypatch.setattr(scraper_fb.time, "sleep", lambda s: None)
    lo = [[_url_fbcdn(b * 2 + i, f"k{b}-{i}") for i in (1, 2)] for b in range(4)]   # lô 0 + 3 lần cuộn có video
    page = _TrangDemCuon(lo)
    refs = scraper_fb._auto_scroll(page, max_videos=100, scroll_pause=0, idle_rounds=6)
    assert len(refs) == 8 and page.so_lan_cuon == 3 + 6


def test_moi_ma_dung_deu_duoc_phan_loai_o_bang_bao_thieu():
    """Mỗi mã dừng phải nằm ở bảng `bao-thieu.js` (nút chạy lại / nhãn) hoặc trong danh sách "đã cân nhắc,
    không nút" dưới đây — mã MỚI chưa ai cân nhắc ⇒ ĐỎ. ĐỘT BIẾN: xoá `het_dia` khỏi bảng ⇒ ĐỎ."""
    from tiktok_music_downloader import utils as utils_mod
    from web import cookies as cookies_mod
    js = (Path(__file__).resolve().parent.parent / "web/static/bao-thieu.js").read_text(encoding="utf-8")
    chay_lai = set(re.findall(r'"(\w+)"', re.search(r"MA_CHAY_LAI_DUOC = new Set\(\[(.*?)\]\)", js, re.S).group(1)))
    nhan = set(re.findall(r"^\s+(?:(\w+):)", re.search(r"NHAN_THEO_LY_DO = Object.freeze\(\{(.*?)\}\)", js, re.S).group(1), re.M))
    nhan |= set(re.findall(r"\b(\w+): \"", re.search(r"NHAN_THEO_LY_DO = Object.freeze\(\{(.*?)\}\)", js, re.S).group(1)))
    ma = {v for k, v in vars(utils_mod).items() if k.startswith("STOP_") and v}
    ma |= set(cookies_mod.MA_LOI_COOKIE)
    da_can_nhac_khong_nut = {"index_failed", "feed_rong", "hashtag_khong_tra_duoc"} | set(cookies_mod.MA_LOI_COOKIE)
    assert chay_lai >= {"het_vong", "het_thoi_gian", "page_cap", "het_dia"}, chay_lai
    assert ma - chay_lai - nhan - da_can_nhac_khong_nut == set()
