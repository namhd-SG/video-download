"""Profile Chromium theo job: cờ, thư mục 0700, UA ghim, xoá khi xong, bộ quét, registry.

Đi qua tầng thật khi có thể: vá `scraper.scrape_music_page` (LỚP TRONG) bằng
`gia_lap_scraper`, không vá `_fetch_refs`; registry thì chạy `scrape_music_page`
thật với Playwright giả. Không trình duyệt, không mạng.
"""
from __future__ import annotations

import itertools
import os
import stat
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader.utils import VideoRef
from web import models, profile_theo_job
from web import queue as queue_mod
from web.queue import JobWorker, process_job



def gia_lap_scraper(monkeypatch, tra_ve, so_vong: int = 1):
    """Như `tests/test_web_queue.py::gia_lap_scraper`: vá LỚP TRONG
    (`scraper.scrape_music_page`) để `scrape_music_page_multi` thật vẫn chạy."""
    monkeypatch.setattr(scraper_mod, "scrape_music_page", tra_ve)
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", so_vong)
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda _s: None)

URL_PROFILE = "https://www.tiktok.com/@nguoi.dung"
URL_MUSIC = "https://www.tiktok.com/music/bai-hat-123"

# Bộ khoá `scrape_music_page_multi` luồn xuống `scrape_music_page` ở bản trước khi có
# profile theo job (đo từ edaf0fc): `max_videos`+`thong_ke_feed` do `_multi` tự thêm,
# phần còn lại là kwargs `_fetch_refs` truyền.
KHOA_BAN_CU = {"max_videos", "thong_ke_feed", "cookies_path", "proxy", "profile_dir", "dem_trang"}


@pytest.fixture(autouse=True)
def _xoa_env(monkeypatch):
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA, raising=False)
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_HEADFUL, raising=False)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "data" / "jobs.db"
    models.init_db(db_path)
    return db_path


def _job(db, url=URL_PROFILE, nguoi="a@x.vn"):
    return models.create_job(db, url, 10, nguoi)


def _bat_co(monkeypatch, headful=False):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    if headful:
        monkeypatch.setenv(profile_theo_job.ENV_PROFILE_HEADFUL, "true")


def _ghi_lai(goi: list):
    """Scraper giả ghi kwargs + trạng thái thư mục LÚC được gọi."""
    def fake(url, **kw):
        pd = kw.get("profile_dir")
        info = dict(kw)
        if pd is not None:
            info["_ton_tai"] = os.path.isdir(pd)
            info["_mode"] = stat.S_IMODE(os.stat(pd).st_mode)
            info["_mode_cha"] = stat.S_IMODE(os.stat(os.path.dirname(pd)).st_mode)
        goi.append(info)
        return []
    return fake


# ---------------------------------------------------------------------------
# Cờ TẮT: Y HỆT bản cũ
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [URL_PROFILE, URL_MUSIC])
def test_co_tat_kwargs_y_het_ban_cu(monkeypatch, db, url):
    goi: list = []
    gia_lap_scraper(monkeypatch, _ghi_lai(goi))
    jid = _job(db, url)
    queue_mod._fetch_refs(url, max_videos=10, cookies_path=None, db_path=db, job_id=jid)
    assert set(goi[0]) == KHOA_BAN_CU
    assert goi[0]["profile_dir"] is None
    assert not (db.parent / "profiles").exists()
    assert models.get_job(db, jid)["ua_job"] is None


def test_co_phu_headful_khong_co_tac_dung_khi_co_chinh_tat(monkeypatch, db):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_HEADFUL, "1")
    goi: list = []
    gia_lap_scraper(monkeypatch, _ghi_lai(goi))
    jid = _job(db)
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=jid)
    assert set(goi[0]) == KHOA_BAN_CU


# ---------------------------------------------------------------------------
# Cờ BẬT
# ---------------------------------------------------------------------------

def test_co_bat_job_profile_dir_rieng_0700_job_music_van_none(monkeypatch, db):
    old = os.umask(0o022)  # umask thường gặp: mkdir trần sẽ ra 0755
    try:
        _bat_co(monkeypatch)
        goi: list = []
        gia_lap_scraper(monkeypatch, _ghi_lai(goi))
        jp = _job(db, URL_PROFILE)
        jm = _job(db, URL_MUSIC)
        queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=jp)
        queue_mod._fetch_refs(URL_MUSIC, max_videos=10, cookies_path=None, db_path=db, job_id=jm)
    finally:
        os.umask(old)
    profile, music = goi
    assert profile["profile_dir"] == str(db.parent / "profiles" / str(jp))
    assert profile["_ton_tai"] is True
    assert profile["_mode"] == 0o700
    assert profile["_mode_cha"] == 0o700
    assert stat.S_IMODE(os.stat(db.parent / "profiles").st_mode) == 0o700
    assert profile["headless"] is True
    assert profile["user_agent"]
    # Job music cùng lúc: y hệt bản cũ.
    assert set(music) == KHOA_BAN_CU and music["profile_dir"] is None
    assert not (db.parent / "profiles" / str(jm)).exists()


def test_co_bat_headful(monkeypatch, db):
    _bat_co(monkeypatch, headful=True)
    goi: list = []
    gia_lap_scraper(monkeypatch, _ghi_lai(goi))
    jid = _job(db)
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=jid)
    assert goi[0]["headless"] is False


def test_co_bat_nhung_khong_co_db_hoac_job_id_giu_hanh_vi_cu(monkeypatch):
    _bat_co(monkeypatch)
    goi: list = []
    gia_lap_scraper(monkeypatch, _ghi_lai(goi))
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None)
    assert set(goi[0]) == KHOA_BAN_CU and goi[0]["profile_dir"] is None


def test_scraper_call_profile_dir_none_except_profile_job_when_flag_on(monkeypatch, db):
    """Thay cho test cũ "luôn None": khoá ranh giới — None cho mọi job TRỪ job profile
    khi cờ bật, và khi đó dir chứa `job_id` nằm dưới `profiles/`."""
    _bat_co(monkeypatch)
    goi: list = []
    gia_lap_scraper(monkeypatch, _ghi_lai(goi))
    for url in (URL_MUSIC, "https://www.tiktok.com/search?q=abc", URL_PROFILE):
        queue_mod._fetch_refs(url, max_videos=10, cookies_path=None, db_path=db, job_id=_job(db, url))
    assert [g["profile_dir"] is None for g in goi] == [True, True, False]
    pd = goi[2]["profile_dir"]
    assert os.path.basename(os.path.dirname(pd)) == "profiles"
    assert os.path.basename(pd).isdigit()


# ---------------------------------------------------------------------------
# UA ghim theo job
# ---------------------------------------------------------------------------

def test_ua_ghim_theo_job_qua_hai_luot_dao_sau_va_hai_lan_goi(monkeypatch, db):
    _bat_co(monkeypatch)
    dem = itertools.count(1)
    monkeypatch.setattr(queue_mod, "random_user_agent", lambda: f"UA-{next(dem)}")
    goi: list = []

    def fake(url, **kw):
        goi.append(kw["user_agent"])
        # Mỗi lượt ra một ref mới ⇒ `_multi` đi tiếp lượt kế.
        return [VideoRef(video_id=str(len(goi)), url=f"{URL_PROFILE}/video/{len(goi)}")]

    gia_lap_scraper(monkeypatch, fake, so_vong=2)
    j1, j2 = _job(db), _job(db)
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=j1)
    assert len(goi) == 2 and goi[0] == goi[1], "hai lượt đào sâu cùng job phải CÙNG UA"
    # Lần gọi `_fetch_refs` thứ hai của CÙNG job (lượt khác, context đóng giữa chừng).
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=j1)
    assert len(set(goi)) == 1
    assert models.get_job(db, j1)["ua_job"] == goi[0]
    # Job khác chọn riêng.
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=j2)
    assert goi[-1] != goi[0]
    assert models.get_job(db, j2)["ua_job"] == goi[-1]


def test_ua_chon_moi_chi_goi_mot_lan(db):
    jid = _job(db)
    dem = itertools.count(1)
    a = models.chon_ua_job(db, jid, lambda: f"UA-{next(dem)}")
    b = models.chon_ua_job(db, jid, lambda: f"UA-{next(dem)}")
    assert a == b == "UA-1"


# ---------------------------------------------------------------------------
# Xoá dir khi job kết thúc
# ---------------------------------------------------------------------------

def _chay_process_job(db, tmp_path, jid):
    job = models.get_job(db, jid)
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)


def test_dir_bi_xoa_sau_khi_job_xong(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    ton_tai = []

    def fake(url, **kw):
        ton_tai.append(os.path.isdir(kw["profile_dir"]))
        return []

    gia_lap_scraper(monkeypatch, fake)
    jid = _job(db)
    _chay_process_job(db, tmp_path, jid)
    assert ton_tai == [True]
    assert not (db.parent / "profiles" / str(jid)).exists()
    assert models.get_job(db, jid)["trang_thai"] in ("done", "failed")


def test_dir_bi_xoa_khi_job_nem_ngoai_le(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)

    def fake(url, **kw):
        assert os.path.isdir(kw["profile_dir"])
        raise ValueError("scraper nổ")

    gia_lap_scraper(monkeypatch, fake)
    jid = _job(db)
    _chay_process_job(db, tmp_path, jid)
    assert not (db.parent / "profiles" / str(jid)).exists()
    assert models.get_job(db, jid)["trang_thai"] == "failed"


def test_xoa_trat_khong_lam_hong_trang_thai_job_va_bo_quet_don_sau(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    gia_lap_scraper(monkeypatch, lambda url, **kw: [])
    that = profile_theo_job.shutil.rmtree

    def hong(*a, **k):
        raise OSError("đĩa hỏng")

    monkeypatch.setattr(profile_theo_job.shutil, "rmtree", hong)
    jid = _job(db)
    _chay_process_job(db, tmp_path, jid)
    assert models.get_job(db, jid)["trang_thai"] in ("done", "failed")
    assert (db.parent / "profiles" / str(jid)).exists()
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem == {"da_xoa": 0, "giu": 0, "xoa_truot": 1, "bo_qua": 0}
    monkeypatch.setattr(profile_theo_job.shutil, "rmtree", that)
    assert profile_theo_job.quet_profile_mo_coi(db)["da_xoa"] == 1
    assert not (db.parent / "profiles" / str(jid)).exists()


# ---------------------------------------------------------------------------
# Bộ quét
# ---------------------------------------------------------------------------

def _dung_profiles(db):
    """done, failed, interrupted, cancelled (mồ côi) · running, pending (sống) · không tồn tại · tên lạ."""
    ids = {}
    for ten in ("done", "failed", "running", "pending", "interrupted", "cancelled"):
        ids[ten] = _job(db)
    models.finish_job(db, ids["done"], "done")
    models.finish_job(db, ids["failed"], "failed")
    with models._connect(db) as c:
        for ten in ("running", "interrupted", "cancelled"):
            c.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (ten, ids[ten]))
    ids["khong_ton_tai"] = 9999
    goc = db.parent / "profiles"
    goc.mkdir(parents=True, exist_ok=True)
    for jid in ids.values():
        (goc / str(jid)).mkdir()
        (goc / str(jid) / "Cookies").write_text("x")
    (goc / "abc").mkdir()
    (goc / "abc" / "giu-lai").write_text("x")
    return ids, goc


def test_bo_quet_xoa_mo_coi_giu_song_bo_qua_ten_la_va_tra_dung_so_dem(db):
    ids, goc = _dung_profiles(db)
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem == {"da_xoa": 5, "giu": 2, "xoa_truot": 0, "bo_qua": 1}
    for ten in ("done", "failed", "interrupted", "cancelled", "khong_ton_tai"):
        assert not (goc / str(ids[ten])).exists(), ten
    for ten in ("running", "pending"):
        assert (goc / str(ids[ten]) / "Cookies").exists(), ten
    assert (goc / "abc" / "giu-lai").exists()


def test_bo_quet_khong_co_thu_muc_profiles(db):
    assert profile_theo_job.quet_profile_mo_coi(db) == {"da_xoa": 0, "giu": 0, "xoa_truot": 0, "bo_qua": 0}


def _worker(db, tmp_path, **kw):
    return JobWorker(db, tmp_path / "dl", tmp_path / "ck", **kw)


def test_bo_quet_nhip_it_nhat_60_giay(monkeypatch, db, tmp_path):
    goi = []
    that = profile_theo_job.quet_profile_mo_coi
    monkeypatch.setattr(profile_theo_job, "quet_profile_mo_coi", lambda p: goi.append(1) or that(p))
    w = _worker(db, tmp_path)
    assert w._quet_profile_dinh_ky(bay_gio=1000.0) is not None
    assert w._quet_profile_dinh_ky(bay_gio=1030.0) is None
    assert w._quet_profile_dinh_ky(bay_gio=1059.9) is None
    assert len(goi) == 1
    assert w._quet_profile_dinh_ky(bay_gio=1060.0) is not None
    assert len(goi) == 2


def test_bo_quet_hong_khong_ne_ra_khoi_worker(monkeypatch, db, tmp_path):
    def no(_p):
        raise RuntimeError("quét nổ")
    monkeypatch.setattr(profile_theo_job, "quet_profile_mo_coi", no)
    assert _worker(db, tmp_path)._quet_profile_dinh_ky(bay_gio=1.0) is None


def _cho(dieu_kien, giay=5.0):
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        time.sleep(0.02)
    return dieu_kien()


def test_bo_quet_chay_luc_khoi_dong(db, tmp_path):
    goc = db.parent / "profiles"
    (goc / "777").mkdir(parents=True)
    w = _worker(db, tmp_path, disk_guard_fn=lambda p: SimpleNamespace(ok=False, reason="đầy"))
    w.start()
    try:
        assert not (goc / "777").exists()
    finally:
        w.stop()


def test_bo_quet_van_chay_khi_dia_duoi_nguong(monkeypatch, db, tmp_path):
    """Cổng đĩa `continue` TRƯỚC `claim` ⇒ bộ quét đặt sau cổng sẽ không bao giờ chạy
    đúng lúc đĩa cạn."""
    monkeypatch.setattr(queue_mod, "NHIP_QUET_PROFILE_GIAY", 0.0)
    goc = db.parent / "profiles"
    w = _worker(db, tmp_path, poll_interval=0.01,
                disk_guard_fn=lambda p: SimpleNamespace(ok=False, reason="đầy"))
    w.start()
    try:
        (goc / "888").mkdir(parents=True)
        assert _cho(lambda: not (goc / "888").exists()), "bộ quét không chạy khi đĩa cạn"
        assert w.trang_thai()["cho_dia"] == "đầy"
    finally:
        w.stop()


def test_bo_quet_chay_ca_khi_hang_co_job_pending(monkeypatch, db, tmp_path):
    monkeypatch.setattr(queue_mod, "NHIP_QUET_PROFILE_GIAY", 0.0)
    goc = db.parent / "profiles"
    xong = threading.Event()

    def chay(*a, **k):
        # Job đang chạy: tạo mồ côi rồi chờ bộ quét... nhưng worker một luồng nên bộ quét
        # chỉ chạy ở vòng KẾ; ở đây chỉ cần pending thứ hai tồn tại khi vòng kế bắt đầu.
        xong.set()

    _job(db, URL_MUSIC)
    _job(db, URL_MUSIC)
    w = _worker(db, tmp_path, poll_interval=0.01, process_job_fn=chay,
                disk_guard_fn=lambda p: SimpleNamespace(ok=True, reason=""))
    w.start()
    try:
        assert xong.wait(5)
        (goc / "555").mkdir(parents=True)
        assert _cho(lambda: not (goc / "555").exists())
    finally:
        w.stop()


# ---------------------------------------------------------------------------
# Registry một-dir-một-context (Playwright giả)
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, hong_cookies=False):
        self.closed = False
        self._hong_cookies = hong_cookies

    def add_init_script(self, *_a):
        pass

    def add_cookies(self, *_a):
        if self._hong_cookies:
            raise RuntimeError("cookie hỏng")

    def new_page(self):
        return object()

    def close(self):
        self.closed = True


class _Pw:
    def __init__(self, hong_mo=False, hong_cookies=False):
        self.chromium = self
        self.ctxs: list[_Ctx] = []
        self._hong_mo = hong_mo
        self._hong_cookies = hong_cookies

    def launch_persistent_context(self, **kw):
        if self._hong_mo:
            raise OSError("không mở được Chromium")
        c = _Ctx(self._hong_cookies)
        self.ctxs.append(c)
        return c


def _dung_pw(monkeypatch, pw, auto_scroll=None):
    @contextmanager
    def sp():
        yield pw

    monkeypatch.setattr(scraper_mod, "sync_playwright", sp)
    monkeypatch.setattr(scraper_mod, "_watch_feed_api", lambda *a, **k: None)
    monkeypatch.setattr(scraper_mod, "_mo_trang_co_ham_phien", lambda *a, **k: None)
    monkeypatch.setattr(scraper_mod, "_load_cookies", lambda p: [])
    monkeypatch.setattr(scraper_mod, "_auto_scroll", auto_scroll or (lambda *a, **k: []))
    scraper_mod._PROFILE_DANG_MO.clear()


def test_registry_mo_hai_lan_cung_dir_nem_runtime_error(monkeypatch, tmp_path):
    pw = _Pw()
    _dung_pw(monkeypatch, pw)
    d = tmp_path / "p1"
    scraper_mod._open_context(pw, True, None, d, "ua")
    with pytest.raises(RuntimeError, match="đang được một context khác mở"):
        scraper_mod._open_context(pw, True, None, d / ".." / "p1", "ua")  # đường dẫn khác chữ, cùng dir
    assert len(pw.ctxs) == 1, "context thứ hai không được phép được mở"
    scraper_mod._nha_profile_dir(d)


def test_registry_long_nhau_trong_scrape_music_page_va_nha_sau_khi_dong(monkeypatch, tmp_path):
    d = str(tmp_path / "p2")
    loi = []

    def auto_scroll(*a, **k):
        try:
            scraper_mod.scrape_music_page("u", profile_dir=d)
        except RuntimeError as exc:
            loi.append(exc)
        return []

    pw = _Pw()
    _dung_pw(monkeypatch, pw, auto_scroll)
    scraper_mod.scrape_music_page("u", profile_dir=d)
    assert len(loi) == 1 and len(pw.ctxs) == 1 and pw.ctxs[0].closed
    # Đã đóng ⇒ mở lại được.
    _dung_pw(monkeypatch, pw)
    scraper_mod.scrape_music_page("u", profile_dir=d)
    assert len(pw.ctxs) == 2


def test_registry_nha_khi_loi_giua_chung(monkeypatch, tmp_path):
    d = str(tmp_path / "p3")

    def no(*a, **k):
        raise ValueError("cuộn nổ")

    pw = _Pw()
    _dung_pw(monkeypatch, pw, no)
    with pytest.raises(ValueError):
        scraper_mod.scrape_music_page("u", profile_dir=d)
    assert pw.ctxs[0].closed
    _dung_pw(monkeypatch, pw)
    scraper_mod.scrape_music_page("u", profile_dir=d)  # không bị khoá treo
    assert len(pw.ctxs) == 2


def test_registry_nha_khi_add_cookies_hong_va_context_van_duoc_dong(monkeypatch, tmp_path):
    d = str(tmp_path / "p4")
    pw = _Pw(hong_cookies=True)
    _dung_pw(monkeypatch, pw)
    with pytest.raises(RuntimeError, match="cookie hỏng"):
        scraper_mod.scrape_music_page("u", profile_dir=d, cookies_path="/x")
    assert pw.ctxs[0].closed
    assert not scraper_mod._PROFILE_DANG_MO


def test_registry_nha_khi_mo_context_trat(monkeypatch, tmp_path):
    d = str(tmp_path / "p5")
    _dung_pw(monkeypatch, _Pw(hong_mo=True))
    with pytest.raises(OSError):
        scraper_mod.scrape_music_page("u", profile_dir=d)
    assert not scraper_mod._PROFILE_DANG_MO


def test_ctx_tam_khong_dung_registry(monkeypatch):
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **k: SimpleNamespace(
        new_context=lambda **kw: _Ctx())))
    scraper_mod._PROFILE_DANG_MO.clear()
    scraper_mod._open_context(pw, True, None, None, "ua")
    scraper_mod._open_context(pw, True, None, None, "ua")  # hai context tạm cùng lúc: được
    assert not scraper_mod._PROFILE_DANG_MO


def test_scrape_music_page_truyen_user_agent_da_ghim(monkeypatch, tmp_path):
    pw = _Pw()
    _dung_pw(monkeypatch, pw)
    thay = {}
    that = scraper_mod._open_context
    monkeypatch.setattr(scraper_mod, "_open_context",
                        lambda *a, **k: thay.update(ua=k["user_agent"]) or that(*a, **k))
    scraper_mod.scrape_music_page("u", profile_dir=str(tmp_path / "p6"), user_agent="UA-GHIM")
    assert thay["ua"] == "UA-GHIM"


def test_dir_giu_lai_khi_job_chua_ket_thuc_sau_process_job(monkeypatch, db, tmp_path):
    """Chỉ xoá khi job đã ở trạng thái kết thúc trong DB. Ở đây ghi kết thúc bị
    chặn (job còn ở trạng thái chưa kết thúc) ⇒ profile phải CÒN để bộ quét/lượt sau quyết.
    ĐỘT BIẾN: xoá vô điều kiện trong `finally` ⇒ ĐỎ."""
    _bat_co(monkeypatch)
    gia_lap_scraper(monkeypatch, lambda url, **kw: [])
    monkeypatch.setattr(models, "finish_job", lambda *a, **kw: None)
    jid = _job(db)
    _chay_process_job(db, tmp_path, jid)
    assert models.get_job(db, jid)["trang_thai"] not in profile_theo_job.TRANG_THAI_KET_THUC
    assert (db.parent / "profiles" / str(jid)).is_dir()


def test_dir_co_san_0755_bi_siet_ve_0700(db):
    """Thư mục đã tồn tại với quyền rộng (vd sót từ bản khác) ⇒ phải siết lại.
    ĐỘT BIẾN: chỉ chmod khi vừa tạo mới ⇒ ĐỎ."""
    goc = db.parent / "profiles"
    (goc / "7").mkdir(parents=True)
    os.chmod(goc, 0o755)
    os.chmod(goc / "7", 0o755)
    thu_muc = profile_theo_job.chuan_bi_profile_job(db, 7)
    assert stat.S_IMODE(os.stat(goc).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(thu_muc).st_mode) == 0o700


def test_bo_quet_chi_go_lien_ket_con_khong_di_theo_ra_ngoai(db, tmp_path):
    """Mục con tên số là symlink trỏ ra ngoài ⇒ chỉ gỡ link, đích còn nguyên.
    ĐỘT BIẾN: bỏ nhánh `is_symlink()` trong `_xoa_cay` ⇒ ĐỎ."""
    ngoai = tmp_path / "ngoai"
    ngoai.mkdir()
    (ngoai / "quy.txt").write_text("x")
    goc = db.parent / "profiles"
    goc.mkdir(parents=True)
    (goc / "999").symlink_to(ngoai, target_is_directory=True)
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["da_xoa"] == 1
    assert not (goc / "999").exists() and not (goc / "999").is_symlink()
    assert (ngoai / "quy.txt").read_text() == "x"


def test_bo_quet_bo_qua_khi_profiles_la_lien_ket(db, tmp_path):
    """`profiles/` là symlink ⇒ không quét qua nó (nơi nó trỏ không phải của mình)."""
    ngoai = tmp_path / "ngoai2"
    (ngoai / "5").mkdir(parents=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    (db.parent / "profiles").symlink_to(ngoai, target_is_directory=True)
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 1 and dem["da_xoa"] == 0
    assert (ngoai / "5").is_dir()

