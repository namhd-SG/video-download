"""Lối vào quét trên page có sẵn, dừng sớm khi feed rỗng (chỉ khi được yêu cầu),
gate theo cờ của phần dọn profile, và bộ quét không xoá thư mục của Chromium còn sống.

Playwright giả thuần Python, không mạng, không trình duyệt thật.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader.utils import (
    STOP_FEED_RONG,
    VideoRef,
)
from web import models, profile_theo_job
from web import queue as queue_mod
from web.queue import JobWorker, process_job

URL_PROFILE = "https://www.tiktok.com/@nguoi.dung"
URL_MUSIC = "https://www.tiktok.com/music/bai-hat-123"
FEED_PROFILE = "/api/post/item_list/"


def _ref(vid: str) -> VideoRef:
    return VideoRef(video_id=vid, url=f"https://www.tiktok.com/@a/video/{vid}")


@pytest.fixture(autouse=True)
def _xoa_env(monkeypatch):
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA, raising=False)
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_HEADFUL, raising=False)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "data" / "jobs.db"
    models.init_db(db_path)
    return db_path


def _bat_co(monkeypatch):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")


# ---------------------------------------------------------------------------
# Lối vào trên page có sẵn
# ---------------------------------------------------------------------------

class _Req:
    method = "GET"


class _Resp:
    """Phản hồi feed rỗng (Content-Length: 0) — thứ `_watch_feed_api` đếm là `rong`."""
    def __init__(self, path: str = FEED_PROFILE) -> None:
        self.url = "https://www.tiktok.com" + path + "?x=1"
        self.status = 200
        self.request = _Req()

    def header_value(self, name: str):
        return "0" if name == "content-length" else None


class _TrangGia:
    """Ghi THỨ TỰ các lời gọi; `goto`/`reload` bắn một phản hồi feed rỗng tới bộ nghe
    ĐÃ gắn lúc đó (chưa gắn ⇒ phản hồi lọt, đúng như trên trình duyệt thật)."""

    def __init__(self) -> None:
        self.su_kien: list[str] = []
        self.bo_nghe = None

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.su_kien.append("on")
        self.bo_nghe = handler

    def _tai(self, ten: str) -> None:
        self.su_kien.append(ten)
        if self.bo_nghe is not None:
            self.bo_nghe(_Resp())

    def goto(self, url, **_kw) -> None:
        self._tai("goto")

    def reload(self, **_kw) -> None:
        self._tai("reload")

    def wait_for_selector(self, *_a, **_kw) -> None:
        return None

    def eval_on_selector_all(self, *_a, **_kw):
        return []


@pytest.fixture
def cuon_gia(monkeypatch):
    goi = []

    def fake(page, max_videos, scroll_pause, idle_rounds):
        goi.append((max_videos, scroll_pause, idle_rounds))
        return {_ref("1"), _ref("3"), _ref("2")}

    monkeypatch.setattr(scraper_mod, "_auto_scroll", fake)
    return goi


def test_quet_tren_trang_reload_gan_watch_truoc_reload(cuon_gia):
    """ĐỘT BIẾN: gắn `_watch_feed_api` SAU reload ⇒ ĐỎ (phản hồi của chính lượt reload
    lọt khỏi bộ đếm ⇒ 0/0 giả, và thứ tự `on` sau `reload`)."""
    page, tk = _TrangGia(), {}
    refs = scraper_mod.quet_tren_trang(page, URL_PROFILE, 10, thong_ke_feed=tk,
                                       tai_lai_truoc_khi_cuon=True)
    assert page.su_kien == ["on", "reload"], "watch trước, đúng MỘT reload, không goto"
    assert tk == {"rong": 1, "co_du_lieu": 0}
    assert [r.video_id for r in refs] == ["3", "2", "1"]  # video_id giảm dần
    assert cuon_gia == [(10, 1.5, 12)]


def test_quet_tren_trang_mac_dinh_goto_nhu_cu(cuon_gia):
    page, tk = _TrangGia(), {}
    scraper_mod.quet_tren_trang(page, URL_PROFILE, 10, thong_ke_feed=tk)
    # Profile + feed rỗng + chưa thấy dữ liệu ⇒ hâm phiên mở lại ĐÚNG một lần: 2 goto.
    assert page.su_kien == ["on", "goto", "goto"]
    assert "reload" not in page.su_kien


def test_quet_tren_trang_cat_theo_max_videos(cuon_gia):
    refs = scraper_mod.quet_tren_trang(_TrangGia(), URL_MUSIC, 2)
    assert [r.video_id for r in refs] == ["3", "2"]


def test_quet_tren_trang_cong_thong_ke_ca_khi_cuon_no(monkeypatch):
    def no(*a, **k):
        raise ValueError("cuộn nổ")

    monkeypatch.setattr(scraper_mod, "_auto_scroll", no)
    tk = {"rong": 5, "co_du_lieu": 2}
    with pytest.raises(ValueError):
        scraper_mod.quet_tren_trang(_TrangGia(), URL_PROFILE, 10, thong_ke_feed=tk,
                                    tai_lai_truoc_khi_cuon=True)
    assert tk == {"rong": 6, "co_du_lieu": 2}


class _CtxGia:
    def __init__(self, loi_cookies=None, loi_dong=None) -> None:
        self.da_dong = False
        self._loi_cookies, self._loi_dong = loi_cookies, loi_dong
        self.trang = _TrangGia()

    def add_init_script(self, *_a):
        pass

    def add_cookies(self, *_a):
        if self._loi_cookies:
            raise self._loi_cookies

    def new_page(self):
        return self.trang

    def close(self):
        self.da_dong = True
        if self._loi_dong:
            raise self._loi_dong


class _PwGia:
    def __init__(self, ctx) -> None:
        self.chromium = self
        self._ctx = ctx

    def launch_persistent_context(self, **_kw):
        return self._ctx

    def launch(self, **_kw):
        return SimpleNamespace(new_context=lambda **kw: self._ctx, close=lambda: None)


def _dung_pw(monkeypatch, ctx):
    @contextmanager
    def sp():
        yield _PwGia(ctx)

    monkeypatch.setattr(scraper_mod, "sync_playwright", sp)
    monkeypatch.setattr(scraper_mod, "_load_cookies", lambda p: [])
    scraper_mod._PROFILE_DANG_MO.clear()


def test_scrape_music_page_di_qua_quet_tren_trang(monkeypatch):
    ctx = _CtxGia()
    _dung_pw(monkeypatch, ctx)
    thay = {}

    def fake(page, url, max_videos, scroll_pause, idle_rounds, **kw):
        thay.update(page=page, url=url, max=max_videos, kw=kw)
        return [_ref("9")]

    monkeypatch.setattr(scraper_mod, "quet_tren_trang", fake)
    tk, dem = {}, (lambda: None)
    out = scraper_mod.scrape_music_page(URL_MUSIC, max_videos=7, thong_ke_feed=tk, dem_trang=dem)
    assert [r.video_id for r in out] == ["9"]
    assert thay["page"] is ctx.trang and thay["url"] == URL_MUSIC and thay["max"] == 7
    assert thay["kw"] == {"dem_trang": dem, "thong_ke_feed": tk}
    assert ctx.da_dong


def test_close_loi_khong_de_loi_goc(monkeypatch, tmp_path, caplog):
    """`add_cookies` ném A (browser chết), `close` ném B ⇒ ra ngoài là A, B vào log."""
    ctx = _CtxGia(loi_cookies=RuntimeError("A-goc"), loi_dong=OSError("B-dong"))
    _dung_pw(monkeypatch, ctx)
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        with pytest.raises(RuntimeError, match="A-goc"):
            scraper_mod.scrape_music_page(URL_MUSIC, profile_dir=str(tmp_path / "p"),
                                          cookies_path="/x")
    assert ctx.da_dong
    assert any("B-dong" in r.getMessage() for r in caplog.records)
    assert not scraper_mod._PROFILE_DANG_MO, "khoá profile vẫn phải nhả"


def test_close_loi_khi_khong_co_loi_goc_van_ne_ra(monkeypatch, tmp_path):
    """Không có lỗi gốc thì lỗi đóng KHÔNG bị nuốt (hành vi cũ)."""
    ctx = _CtxGia(loi_dong=OSError("B-dong"))
    _dung_pw(monkeypatch, ctx)
    monkeypatch.setattr(scraper_mod, "quet_tren_trang", lambda *a, **k: [])
    with pytest.raises(OSError, match="B-dong"):
        scraper_mod.scrape_music_page(URL_MUSIC, profile_dir=str(tmp_path / "p"))
    assert not scraper_mod._PROFILE_DANG_MO


# ---------------------------------------------------------------------------
# thong_ke_feed_ra + dừng sớm
# ---------------------------------------------------------------------------

def _dung_multi(monkeypatch, moi_luot):
    """`scrape_music_page` giả: lượt k khai `moi_luot[k]` = (rong, co_du_lieu, [video_id])."""
    ngu = []
    goi = []
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda s: ngu.append(s))

    def fake(url, thong_ke_feed=None, **kw):
        k = len(goi)
        goi.append(kw)
        rong, co, ids = moi_luot[min(k, len(moi_luot) - 1)]
        thong_ke_feed["rong"] = thong_ke_feed.get("rong", 0) + rong
        thong_ke_feed["co_du_lieu"] = thong_ke_feed.get("co_du_lieu", 0) + co
        return [_ref(v) for v in ids]

    monkeypatch.setattr(scraper_mod, "scrape_music_page", fake)
    return goi, ngu


def test_thong_ke_feed_ra_nhan_tong_sau_nhieu_luot(monkeypatch):
    goi, _ = _dung_multi(monkeypatch, [(1, 0, ["10"]), (0, 2, ["11", "12"]), (1, 1, ["13", "14"])])
    ra: dict = {}
    scraper_mod.scrape_music_page_multi(URL_MUSIC, passes=3, max_videos=100,
                                        thong_ke_feed_ra=ra)
    assert len(goi) == 3
    assert ra == {"rong": 2, "co_du_lieu": 3}


def test_thong_ke_feed_ra_mac_dinh_none_khong_anh_huong(monkeypatch):
    _dung_multi(monkeypatch, [(1, 0, ["10"])])
    scraper_mod.scrape_music_page_multi(URL_MUSIC, passes=1, max_videos=100)


def test_dung_som_true_dung_sau_luot_1_du_co_link_moi_va_khong_ngu(monkeypatch):
    """Lượt 1 feed rỗng nhưng có 1 link lạc MỚI ⇒ dừng ngay, không lượt 2, không ngủ.

    ĐỘT BIẾN: thêm `and not moi` vào điều kiện dừng sớm ⇒ ĐỎ (chạy tiếp lượt 2 và ngủ).
    """
    goi, ngu = _dung_multi(monkeypatch, [(1, 0, ["10"]), (1, 0, ["11"])])
    ly_do: list[str] = []
    out = scraper_mod.scrape_music_page_multi(
        URL_PROFILE, passes=3, max_videos=100, dung_som_khi_feed_rong=True,
        on_stop=ly_do.append)
    assert len(goi) == 1, "lượt 2 không được gọi"
    assert ngu == [], "không ngủ chờ lượt sau"
    assert ly_do == [STOP_FEED_RONG]
    assert [r.video_id for r in out] == ["10"], "link lạc vẫn được trả như cũ"


def test_dung_som_false_hanh_vi_cu(monkeypatch):
    """Mặc định: link lạc mới ⇒ KHÔNG vào nhánh feed_rong; chạy tiếp (ngủ + lượt 2).

    ĐỘT BIẾN: dừng sớm luôn bật (bỏ tham số) ⇒ ĐỎ.
    """
    goi, ngu = _dung_multi(monkeypatch, [(1, 0, ["10"]), (1, 0, ["10"])])
    ly_do: list[str] = []
    out = scraper_mod.scrape_music_page_multi(URL_MUSIC, passes=3, max_videos=100,
                                              on_stop=ly_do.append)
    assert len(goi) == 2 and len(ngu) == 1
    assert ly_do and ly_do[0] != STOP_FEED_RONG
    assert [r.video_id for r in out] == ["10"]


def test_dung_som_true_nhung_feed_co_du_lieu_hoac_khong_do_duoc_thi_khong_dung(monkeypatch):
    for luot in ([(1, 1, ["10"]), (0, 1, ["11"])], [(0, 0, ["10"]), (0, 0, ["11"])]):
        goi, _ = _dung_multi(monkeypatch, luot)
        scraper_mod.scrape_music_page_multi(URL_PROFILE, passes=2, max_videos=100,
                                            dung_som_khi_feed_rong=True)
        assert len(goi) == 2, luot


def test_dung_som_true_khong_chuyen_xuong_scrape_music_page(monkeypatch):
    """Hai tham số mới do `_multi` giữ lại, không luồn xuống `scrape_music_page`."""
    goi, _ = _dung_multi(monkeypatch, [(0, 1, ["10"])])
    scraper_mod.scrape_music_page_multi(URL_PROFILE, passes=1, max_videos=100,
                                        dung_som_khi_feed_rong=True, thong_ke_feed_ra={})
    assert set(goi[0]) == {"max_videos"}  # `max_videos` do `_multi` tự thêm


# ---------------------------------------------------------------------------
# _fetch_refs truyền dung_som_khi_feed_rong
# ---------------------------------------------------------------------------

def _bat_kwargs_multi(monkeypatch):
    thay: list[dict] = []

    def fake(url, **kw):
        thay.append(kw)
        return []

    monkeypatch.setattr(queue_mod, "scrape_music_page_multi", fake)
    return thay


@pytest.mark.parametrize("url", [URL_PROFILE, URL_MUSIC])
def test_fetch_refs_co_tat_khong_truyen_dung_som(monkeypatch, db, url):
    """ĐỘT BIẾN: truyền `dung_som_khi_feed_rong` cả khi cờ TẮT ⇒ ĐỎ."""
    thay = _bat_kwargs_multi(monkeypatch)
    jid = models.create_job(db, url, 10, "a@x.vn")
    queue_mod._fetch_refs(url, max_videos=10, cookies_path=None, db_path=db, job_id=jid)
    assert "dung_som_khi_feed_rong" not in thay[0]


def test_fetch_refs_co_bat_profile_truyen_dung_som_music_thi_khong(monkeypatch, db):
    _bat_co(monkeypatch)
    thay = _bat_kwargs_multi(monkeypatch)
    jp = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    jm = models.create_job(db, URL_MUSIC, 10, "a@x.vn")
    queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=jp)
    queue_mod._fetch_refs(URL_MUSIC, max_videos=10, cookies_path=None, db_path=db, job_id=jm)
    assert thay[0]["dung_som_khi_feed_rong"] is True
    assert "dung_som_khi_feed_rong" not in thay[1]


# ---------------------------------------------------------------------------
# Gate theo cờ: bộ quét + finally
# ---------------------------------------------------------------------------

def _worker(db, tmp_path, **kw):
    return JobWorker(db, tmp_path / "dl", tmp_path / "ck", **kw)


def test_bo_quet_co_tat_khong_cham_profiles(monkeypatch, db, tmp_path):
    """ĐỘT BIẾN: bỏ kiểm cờ ở `_quet_profile_dinh_ky` ⇒ ĐỎ."""
    mo_coi = db.parent / "profiles" / "777"
    mo_coi.mkdir(parents=True)
    (mo_coi / "Cookies").write_text("x")
    monkeypatch.setattr(profile_theo_job, "quet_profile_mo_coi",
                        lambda p: pytest.fail("cờ TẮT mà bộ quét vẫn chạy"))
    monkeypatch.setattr(models, "get_job", lambda *a, **k: pytest.fail("SELECT khi cờ TẮT"))
    w = _worker(db, tmp_path)
    assert w._quet_profile_dinh_ky(buoc_ep=True) is None
    assert w._quet_profile_dinh_ky(bay_gio=1.0) is None
    assert w._quet_profile_luc is None
    assert (mo_coi / "Cookies").exists()


def test_bo_quet_co_bat_van_xoa_mo_coi(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    mo_coi = db.parent / "profiles" / "777"
    mo_coi.mkdir(parents=True)
    dem = _worker(db, tmp_path)._quet_profile_dinh_ky(buoc_ep=True)
    assert dem["da_xoa"] == 1 and not mo_coi.exists()


def test_start_co_tat_khong_xoa_mo_coi(db, tmp_path):
    mo_coi = db.parent / "profiles" / "777"
    mo_coi.mkdir(parents=True)
    w = _worker(db, tmp_path, disk_guard_fn=lambda p: SimpleNamespace(ok=False, reason="đầy"))
    w.start()
    try:
        assert mo_coi.is_dir()
    finally:
        w.stop()


def test_finally_co_tat_khong_xoa_thu_muc_profile_job(monkeypatch, db, tmp_path):
    """ĐỘT BIẾN: bỏ kiểm cờ trong `finally` của `process_job` ⇒ ĐỎ."""
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod, "scrape_music_page", lambda url, **kw: [])
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    thu_muc = db.parent / "profiles" / str(jid)
    thu_muc.mkdir(parents=True)
    (thu_muc / "Cookies").write_text("x")
    process_job(db, tmp_path / "dl", tmp_path / "ck", models.get_job(db, jid))
    assert models.get_job(db, jid)["trang_thai"] in profile_theo_job.TRANG_THAI_KET_THUC
    assert (thu_muc / "Cookies").exists()


def test_finally_co_bat_xoa_thu_muc_profile_job(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod, "scrape_music_page", lambda url, **kw: [])
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    process_job(db, tmp_path / "dl", tmp_path / "ck", models.get_job(db, jid))
    assert not (db.parent / "profiles" / str(jid)).exists()


# ---------------------------------------------------------------------------
# Cảnh báo lúc khởi động: cờ TẮT mà profiles/ còn thư mục con
# ---------------------------------------------------------------------------

def _canh_bao(caplog):
    return [r for r in caplog.records
            if r.name == "videodl.web" and r.levelno == logging.WARNING
            and "profiles/" in r.getMessage()]


def test_start_co_tat_profiles_con_thu_muc_ghi_dung_mot_warning_co_so_dem(db, tmp_path, caplog):
    """ĐỘT BIẾN: bỏ dòng warning ⇒ ĐỎ."""
    goc = db.parent / "profiles"
    for ten in ("bi-mat-12345", "abc"):
        (goc / ten).mkdir(parents=True)
        (goc / ten / "Cookies").write_text("x")
    (goc / "tep-le.txt").write_text("x")  # không phải thư mục con ⇒ không đếm
    w = _worker(db, tmp_path, disk_guard_fn=lambda p: SimpleNamespace(ok=False, reason="đầy"))
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        w.start()
        w.stop()
    ghi = _canh_bao(caplog)
    assert len(ghi) == 1
    msg = ghi[0].getMessage()
    assert "2" in msg
    assert "bi-mat-12345" not in msg and "abc" not in msg and "Cookies" not in msg
    assert (goc / "bi-mat-12345" / "Cookies").exists(), "chỉ đếm, không xoá"


def test_start_khong_warning_khi_khong_co_hoac_rong_hoac_co_bat(monkeypatch, db, tmp_path, caplog):
    w = _worker(db, tmp_path, disk_guard_fn=lambda p: SimpleNamespace(ok=False, reason="đầy"))
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        w.start()
        w.stop()
        assert _canh_bao(caplog) == []                # không có profiles/
        (db.parent / "profiles").mkdir()
        w.start()
        w.stop()
        assert _canh_bao(caplog) == []                # profiles/ rỗng
        (db.parent / "profiles" / "5").mkdir()
        _bat_co(monkeypatch)
        w.start()
        w.stop()
        assert _canh_bao(caplog) == []                # cờ BẬT


def test_canh_bao_khong_select_khong_xoa(monkeypatch, db, tmp_path):
    (db.parent / "profiles" / "5").mkdir(parents=True)
    monkeypatch.setattr(models, "get_job", lambda *a, **k: pytest.fail("SELECT"))
    _worker(db, tmp_path)._canh_bao_profiles_khi_co_tat()
    assert (db.parent / "profiles" / "5").is_dir()


# ---------------------------------------------------------------------------
# Bộ quét không xoá thư mục của Chromium còn sống (SingletonLock)
# ---------------------------------------------------------------------------

def _pid_da_chet() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _dung_mo_coi(db, lock_dich: str | None, ten: str = "41") -> object:
    """Thư mục job KHÔNG có trong DB (⇒ mồ côi) với `SingletonLock` -> `lock_dich`."""
    thu_muc = db.parent / "profiles" / ten
    thu_muc.mkdir(parents=True)
    (thu_muc / "Cookies").write_text("x")
    if lock_dich is not None:
        os.symlink(lock_dich, thu_muc / "SingletonLock")
    return thu_muc


def test_lock_host_dung_pid_song_thi_giu(db):
    """ĐỘT BIẾN: bỏ kiểm SingletonLock ⇒ ĐỎ."""
    d = _dung_mo_coi(db, f"{socket.gethostname()}-{os.getpid()}")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem == {"da_xoa": 0, "giu": 0, "xoa_truot": 0, "bo_qua": 0, "giu_dang_mo": 1}
    assert (d / "Cookies").exists()


def test_lock_host_dung_pid_chet_thi_xoa(db):
    d = _dung_mo_coi(db, f"{socket.gethostname()}-{_pid_da_chet()}")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["da_xoa"] == 1 and "giu_dang_mo" not in dem
    assert not d.exists()


def test_lock_khong_co_thi_xoa_nhu_cu(db):
    d = _dung_mo_coi(db, None)
    assert profile_theo_job.quet_profile_mo_coi(db)["da_xoa"] == 1
    assert not d.exists()


def test_lock_host_khac_pid_song_thi_giu_bo_qua(db):
    """ĐỘT BIẾN: bỏ so host ⇒ ĐỎ (pid của máy khác bị đem đi hỏi `os.kill` ở máy này)."""
    # pid chết ở máy này: nếu bỏ so host thì sẽ bị xoá; host đúng cho pid sống thì ra
    # `giu_dang_mo` — hai đột biến cùng bị bắt bởi hai ca dưới đây.
    d = _dung_mo_coi(db, f"may-khac-hoan-toan-{os.getpid()}", "41")
    d2 = _dung_mo_coi(db, f"may-khac-hoan-toan-{_pid_da_chet()}", "42")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 2 and dem["da_xoa"] == 0 and "giu_dang_mo" not in dem
    assert (d / "Cookies").exists() and (d2 / "Cookies").exists()


def test_lock_hostname_co_dau_gach_tach_o_dau_gach_cuoi(monkeypatch, db):
    monkeypatch.setattr(socket, "gethostname", lambda: "may-co-nhieu-gach")
    d = _dung_mo_coi(db, f"may-co-nhieu-gach-{os.getpid()}")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["giu_dang_mo"] == 1 and (d / "Cookies").exists()


@pytest.mark.parametrize("dich", [
    "/khong/co/duoi-so",             # symlink treo, đích lạ, pid không phải số
    "khong-co-pid-",                 # pid rỗng
    "khongcodaugach",                # sai định dạng
    f"-{os.getpid()}",               # host rỗng
    "host-0",                        # pid 0
    "host-12abc",                    # pid không thuần số
    "host-" + "9" * 40,              # pid tràn
])
def test_lock_sai_dinh_dang_thi_giu_bo_qua(db, dich):
    d = _dung_mo_coi(db, dich)
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 1 and dem["da_xoa"] == 0
    assert (d / "Cookies").exists()


def test_lock_khong_phai_symlink_thi_giu_bo_qua(db):
    d = _dung_mo_coi(db, None)
    (d / "SingletonLock").write_text("tep thuong")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 1 and dem["da_xoa"] == 0 and d.exists()


def test_lock_khong_di_theo_symlink_dich(db, tmp_path):
    """Đích của SingletonLock là thư mục thật: vẫn chỉ đọc chuỗi đích, không đi vào đó."""
    ngoai = tmp_path / f"{socket.gethostname()}-{_pid_da_chet()}"
    ngoai.mkdir()
    d = _dung_mo_coi(db, str(ngoai))
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 1 and d.exists() and ngoai.is_dir()


def test_giu_dang_mo_log_dem_duoc_o_worker(monkeypatch, db, tmp_path, caplog):
    _bat_co(monkeypatch)
    _dung_mo_coi(db, f"{socket.gethostname()}-{os.getpid()}")
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        dem = _worker(db, tmp_path)._quet_profile_dinh_ky(buoc_ep=True)
    assert dem["giu_dang_mo"] == 1
    assert any("Chromium đang mở 1" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Khoá riêng của worker — Chromium HEADLESS không tạo `SingletonLock` (đo 02/10)
# ---------------------------------------------------------------------------

def test_chuan_bi_ghi_khoa_worker_host_va_pid_tien_trinh_nay(db):
    """ĐỘT BIẾN: bỏ `ghi_khoa_worker` trong `chuan_bi_profile_job` ⇒ ĐỎ."""
    d = profile_theo_job.chuan_bi_profile_job(db, 77)
    assert (d / ".videodl-worker").read_text() == f"{socket.gethostname()}-{os.getpid()}"
    assert not (d / ".videodl-worker.tam").exists()


def test_headless_khong_singletonlock_khoa_worker_song_thi_giu(db):
    """Thư mục mồ côi (job không có trong DB) KHÔNG có `SingletonLock` — đúng như
    Chromium headless — nhưng khoá worker trỏ tiến trình còn sống ⇒ GIỮ.
    ĐỘT BIẾN: bộ quét chỉ đọc `SingletonLock` (bỏ khoá worker) ⇒ ĐỎ."""
    cu = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        d = _dung_mo_coi(db, None)
        (d / ".videodl-worker").write_text(f"{socket.gethostname()}-{cu.pid}")
        dem = profile_theo_job.quet_profile_mo_coi(db)
        assert dem.get("giu_dang_mo") == 1 and dem["da_xoa"] == 0
        assert (d / "Cookies").exists()
    finally:
        cu.kill()
        cu.wait()


def test_khoa_worker_cua_chinh_tien_trinh_hoi_registry(db):
    """Khoá do CHÍNH tiến trình này ghi: pid sống là đương nhiên ⇒ hỏi registry.
    Không giữ context ⇒ xoá (job đã kết thúc); đang giữ ⇒ giữ.
    ĐỘT BIẾN: bỏ nhánh pid-của-mình (để `os.kill` phân định) ⇒ ĐỎ (thư mục xoá trượt
    của job đã xong không bao giờ được dọn tới lần khởi động sau)."""
    d = _dung_mo_coi(db, None, ten="44")
    (d / ".videodl-worker").write_text(f"{socket.gethostname()}-{os.getpid()}")
    khoa = scraper_mod._giu_profile_dir(d)
    try:
        assert profile_theo_job.quet_profile_mo_coi(db).get("giu_dang_mo") == 1
        assert d.exists()
    finally:
        scraper_mod._nha_profile_dir(d)
    assert profile_theo_job.quet_profile_mo_coi(db)["da_xoa"] == 1
    assert not d.exists()


def test_khoa_worker_pid_chet_thi_xoa(db):
    d = _dung_mo_coi(db, None)
    (d / ".videodl-worker").write_text(f"{socket.gethostname()}-{_pid_da_chet()}")
    assert profile_theo_job.quet_profile_mo_coi(db)["da_xoa"] == 1
    assert not d.exists()


def test_khoa_worker_la_symlink_hoac_sai_dinh_dang_thi_giu(db, tmp_path):
    d = _dung_mo_coi(db, None, ten="42")
    (d / ".videodl-worker").write_text("rac-khong-co-so")
    ngoai = tmp_path / "ngoai.txt"
    ngoai.write_text(f"{socket.gethostname()}-{_pid_da_chet()}")
    d2 = _dung_mo_coi(db, None, ten="43")
    os.symlink(ngoai, d2 / ".videodl-worker")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert dem["bo_qua"] == 2 and dem["da_xoa"] == 0
    assert d.exists() and d2.exists() and ngoai.exists()


def test_dung_som_khong_gan_feed_rong_khi_luot_da_du_video(monkeypatch):
    """Lượt 1 lấy ĐỦ `max_videos` mà feed đếm rỗng ⇒ xong thật (STOP_COMPLETE),
    không gắn `feed_rong` cho job đã đủ.
    ĐỘT BIẾN: bỏ `len(moi) < max_videos` khỏi cổng dừng sớm ⇒ ĐỎ."""
    _dung_multi(monkeypatch, [(1, 0, ["1", "2", "3", "4", "5"])])
    ly_do: list[str] = []
    out = scraper_mod.scrape_music_page_multi(
        URL_PROFILE, passes=3, max_videos=5, dung_som_khi_feed_rong=True,
        on_stop=ly_do.append)
    assert len(out) == 5
    assert STOP_FEED_RONG not in ly_do
