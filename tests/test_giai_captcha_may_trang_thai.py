"""Máy trạng thái giải captcha — đi qua tầng THẬT của models/queue/worker, Playwright giả thuần Python
(`giai_captcha_gia.py`), đồng hồ giả. Mỗi cạnh của máy có một test; cờ TẮT ⇒ không sinh trạng thái mới.
"""
from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from giai_captcha_gia import (CdpGia, CtxGia, Nguoi, PwGia, RespFeed, TOKEN, TrangGia, dung_dong_ho, dung_pw,
                              la_day_con)
from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader.utils import VideoRef
from web import app as app_mod
from web import giai_captcha as gc
from web import giai_captcha_worker as worker
from web import models, profile_theo_job
from web import models_giai_captcha as mgc
from web import queue as queue_mod
from web.queue import JobWorker, process_job

URL_PROFILE = "https://www.tiktok.com/@nguoi.dung"
URL_MUSIC = "https://www.tiktok.com/music/bai-hat-123"
CHU = "a@x.vn"


def _ref(vid: str) -> VideoRef:
    return VideoRef(video_id=vid, url=f"https://www.tiktok.com/@a/video/{vid}")


@pytest.fixture(autouse=True)
def _moi_truong(monkeypatch):
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA, raising=False)
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_HEADFUL, raising=False)
    monkeypatch.delenv(gc.ENV_D_MS, raising=False)
    monkeypatch.delenv(gc.ENV_DIEU_HUONG, raising=False)
    gc._PHIEN.clear()
    scraper_mod._PROFILE_DANG_MO.clear()
    yield
    gc._PHIEN.clear()
    scraper_mod._PROFILE_DANG_MO.clear()


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "data" / "jobs.db"
    models.init_db(db_path)
    return db_path


def _bat_co(monkeypatch):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")


def _trang_thai(db, jid):
    return models.get_job(db, jid)["trang_thai"]


def _job_cho_xac_minh(db, url=URL_PROFILE, nguoi=CHU, ly_do="feed_rong", tong=10):
    jid = models.create_job(db, url, tong, nguoi)
    # Như thật thì job đi pending → running → cho_xac_minh; ở đây lật thẳng để không phụ thuộc thứ tự claim.
    assert mgc.chuyen_trang_thai(db, jid, "pending", "cho_xac_minh", ly_do=ly_do)
    return jid


# ---------------------------------------------------------------------------
# Hạ tầng cho một lượt giải: worker thật + Playwright giả
# ---------------------------------------------------------------------------

class Hien:
    def __init__(self, monkeypatch, db, *, giu_khoa=True, phat_khung=True, hong_mo=False,
                 cua_so_giay=None, url=URL_PROFILE, tong=10):
        _bat_co(monkeypatch)
        if cua_so_giay is not None:
            monkeypatch.setattr(gc, "CUA_SO_GIAI_GIAY", cua_so_giay)
        self.db = db
        self.dong = dung_dong_ho(monkeypatch)
        self.trang = TrangGia(self.dong, url, phat_khung=phat_khung)
        self.ctx = CtxGia(self.trang)
        self.pw = PwGia(self.ctx, hong_mo)
        dung_pw(monkeypatch, self.pw)
        self.jid = _job_cho_xac_minh(db, url=url, tong=tong)
        assert mgc.yeu_cau_giai_ngay(db, self.jid) == "ok"
        self.job = models.claim_next_pending_job(db, uu_tien_cho_giai=True)
        assert self.job["id"] == self.jid and self.job["trang_thai"] == "dang_mo"
        self.phien = gc.lay_hoac_tao_phien(self.jid, CHU, "cho_giai")
        self.trang.phien_fn = lambda: self.phien
        if giu_khoa:
            assert self.phien.nhan_khoa(TOKEN, CHU)
        self.nguoi = Nguoi(self.phien, self.dong)

    def chay(self):
        return worker.chay_luot_giai(self.db, self.job, None, headless=True, user_agent="UA-test")

    def tt(self):
        return _trang_thai(self.db, self.jid)

    def lenh(self, lenh, token=TOKEN):
        return lambda: self.phien.dat_lenh(token, CHU, lenh)

    def input_da_phat(self):
        return self.trang.cdp.cac_goi("Input.dispatchMouseEvent")


@pytest.fixture
def hien(monkeypatch, db):
    return Hien(monkeypatch, db)


# ---------------------------------------------------------------------------
# running → cho_xac_minh (L3, 0/0, link lạc) và cờ TẮT
# ---------------------------------------------------------------------------

def _quet_gia(rong=0, co_du_lieu=0, refs=()):
    def quet(url, **kw):
        tk = kw["thong_ke_feed"]
        tk["rong"] = tk.get("rong", 0) + rong
        tk["co_du_lieu"] = tk.get("co_du_lieu", 0) + co_du_lieu
        return list(refs)
    return quet


def _xe_tai_khong_duoc_goi(monkeypatch):
    monkeypatch.setattr(queue_mod, "download_all",
                        lambda *a, **k: pytest.fail("job đòi xác minh mà vẫn đi tải"))


def _chay_thuong(monkeypatch, db, tmp_path, url, quet, tong=10):
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod, "scrape_music_page", quet)
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda _s: None)
    jid = models.create_job(db, url, tong, CHU)
    job = models.claim_next_pending_job(db)
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)
    return jid


def test_profile_feed_rong_co_mot_link_lac_moi_vao_cho_xac_minh(monkeypatch, db, tmp_path):
    """Trang bị chặn vẫn lộ 1 link `/video/` lạc ⇒ `moi ≠ ∅`; cũng PHẢI vào cho_xac_minh, không tải link lạc."""
    _bat_co(monkeypatch)
    _xe_tai_khong_duoc_goi(monkeypatch)
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE, _quet_gia(rong=1, refs=[_ref("111")]))
    job = models.get_job(db, jid)
    assert job["trang_thai"] == "cho_xac_minh" and job["ly_do_dung"] == "feed_rong"
    assert job["vao_trang_thai_luc"] is not None
    assert (db.parent / "profiles" / str(jid)).is_dir(), "profile phải còn cho lượt giải"


@pytest.mark.parametrize("refs", [[], [_ref("111")]], ids=["0 link", "1 link lạc"])
def test_profile_khong_do_duoc_feed_0_0_bat_ke_so_link_vao_cho_xac_minh(monkeypatch, db, tmp_path, refs):
    _bat_co(monkeypatch)
    _xe_tai_khong_duoc_goi(monkeypatch)
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE, _quet_gia(refs=refs))
    job = models.get_job(db, jid)
    assert job["trang_thai"] == "cho_xac_minh" and job["ly_do_dung"] == "khong_do_duoc_feed"


def test_music_0_0_giu_nhanh_cu_khong_vao_cho_xac_minh(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_MUSIC, _quet_gia())
    job = models.get_job(db, jid)
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "source_empty"


def test_profile_feed_co_du_lieu_di_duong_cu(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    monkeypatch.setattr(queue_mod, "download_all", lambda *a, **k: None)
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE,
                       _quet_gia(co_du_lieu=1, refs=[_ref("111")]))
    assert _trang_thai(db, jid) != "cho_xac_minh"


def test_profile_0_0_nhung_du_link_khong_phai_bi_chan(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    monkeypatch.setattr(queue_mod, "download_all", lambda *a, **k: None)
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE,
                       _quet_gia(refs=[_ref("111"), _ref("112")]), tong=2)
    assert _trang_thai(db, jid) != "cho_xac_minh"


def test_co_tat_feed_rong_la_failed_va_khong_sinh_trang_thai_moi(monkeypatch, db, tmp_path):
    """Cờ TẮT ⇒ lỗi "Xong giả" cũ được sửa (failed feed_rong), TUYỆT ĐỐI không có `cho_xac_minh`.
    ĐỘT BIẾN: cờ TẮT mà vẫn xét cần-xác-minh ⇒ job sang `cho_xac_minh` ⇒ ĐỎ."""
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE, _quet_gia(rong=1))
    job = models.get_job(db, jid)
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "feed_rong"
    assert job["vao_trang_thai_luc"] is None
    assert not (db.parent / "profiles").exists()


def test_co_tat_0_0_khong_vao_cho_xac_minh(monkeypatch, db, tmp_path):
    jid = _chay_thuong(monkeypatch, db, tmp_path, URL_PROFILE, _quet_gia())
    assert _trang_thai(db, jid) == "failed"


# ---------------------------------------------------------------------------
# cho_xac_minh → cho_giai → dang_mo (claim TRƯỚC pending), trần 3 lần
# ---------------------------------------------------------------------------

def test_cho_giai_duoc_nhat_truoc_pending_cu_hon(db):
    """ĐỘT BIẾN: claim `pending` trước `cho_giai` ⇒ ĐỎ."""
    cu = models.create_job(db, URL_MUSIC, 5, CHU)             # pending, cũ hơn
    jid = _job_cho_xac_minh(db)                                # tạo SAU
    assert mgc.yeu_cau_giai_ngay(db, jid) == "ok"
    assert _trang_thai(db, jid) == "cho_giai"
    nhat = models.claim_next_pending_job(db, uu_tien_cho_giai=True)
    assert nhat["id"] == jid and nhat["trang_thai"] == "dang_mo"
    assert _trang_thai(db, jid) == "dang_mo" and _trang_thai(db, cu) == "pending"
    assert models.claim_next_pending_job(db, uu_tien_cho_giai=True)["id"] == cu


def test_claim_khong_co_co_khong_dung_den_cho_giai(db):
    cu = models.create_job(db, URL_MUSIC, 5, CHU)
    jid = _job_cho_xac_minh(db)
    mgc.yeu_cau_giai_ngay(db, jid)
    assert models.claim_next_pending_job(db)["id"] == cu
    assert _trang_thai(db, jid) == "cho_giai"


def test_cho_xac_minh_sang_cho_giai_chi_tu_cho_xac_minh_va_dem_lan(db):
    jid = _job_cho_xac_minh(db)
    assert mgc.yeu_cau_giai_ngay(db, jid) == "ok"
    assert mgc.yeu_cau_giai_ngay(db, jid) == "sai_trang_thai"   # đã cho_giai
    assert mgc.yeu_cau_giai_ngay(db, 99999) == "khong_co"
    pend = models.create_job(db, URL_PROFILE, 1, CHU)
    assert mgc.yeu_cau_giai_ngay(db, pend) == "sai_trang_thai"
    assert models.get_job(db, jid)["so_lan_giai_ngay"] == 1


def test_tran_3_lan_toi_gia_ngay(db):
    jid = _job_cho_xac_minh(db)
    for lan in range(gc.TRAN_GIAI_NGAY):
        assert mgc.yeu_cau_giai_ngay(db, jid) == "ok", lan
        assert mgc.giai_con_luot(models.get_job(db, jid)) == gc.TRAN_GIAI_NGAY - lan - 1
        assert mgc.chuyen_trang_thai(db, jid, "cho_giai", "cho_xac_minh", ly_do="het_gio_giai")
    assert mgc.yeu_cau_giai_ngay(db, jid) == "het_luot"
    assert _trang_thai(db, jid) == "cho_xac_minh"
    assert mgc.giai_con_luot(models.get_job(db, jid)) == 0


def test_vi_tri_hang_doi_tinh_ca_dang_mo_dang_giai_va_cho_giai_dung_dau(db):
    dang = _job_cho_xac_minh(db)
    mgc.yeu_cau_giai_ngay(db, dang)
    models.claim_next_pending_job(db, uu_tien_cho_giai=True)       # `dang` → dang_mo
    mgc.chuyen_trang_thai(db, dang, "dang_mo", "dang_giai")
    pend = models.create_job(db, URL_MUSIC, 1, CHU)                 # pending, sớm hơn cho_giai bên dưới
    cg = _job_cho_xac_minh(db)
    mgc.yeu_cau_giai_ngay(db, cg)
    vt = models.vi_tri_hang_doi(db, [pend, cg])
    assert vt[cg] == 2, "1 job dang_giai đang chiếm worker + cho_giai đứng đầu hàng"
    assert vt[pend] == 3


# ---------------------------------------------------------------------------
# dang_mo → dang_giai / cho_xac_minh
# ---------------------------------------------------------------------------

def test_dang_mo_sang_dang_giai_khi_co_khung_dau_roi_dung_thi_failed(monkeypatch, db):
    h = Hien(monkeypatch, db)
    thay = {}

    def xem():
        thay["tt"], thay["con_lai"] = h.tt(), h.phien.con_lai_giay()

    h.trang.kich_ban = [(0.1, xem), (0.2, h.lenh("dung"))]
    kq = h.chay()
    assert thay["tt"] == "dang_giai" and 290 <= thay["con_lai"] <= 300
    job = models.get_job(db, h.jid)
    assert kq.loai == "failed" and job["trang_thai"] == "failed"
    assert job["ly_do_dung"] == "feed_rong_khong_captcha"
    assert h.ctx.closed and not scraper_mod.profile_dir_dang_mo(
        profile_theo_job.thu_muc_profile_job(db, h.jid))
    assert h.phien.da_dong and gc.lay_phien(h.jid) is None
    assert h.input_da_phat() == [], "người không làm gì ⇒ tool không phát sự kiện chuột nào"


def test_ong_bat_fetch_truoc_screencast_va_chi_cho_document(monkeypatch, db):
    """ĐỘT BIẾN: bỏ `Fetch.enable` ⇒ ĐỎ (không còn gì chặn điều hướng)."""
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.1, h.lenh("dung"))]
    h.chay()
    ten = [m for m, _ in h.trang.cdp.goi]
    assert ten.index("Fetch.enable") < ten.index("Page.startScreencast")
    assert h.trang.cdp.cac_goi("Fetch.enable")[0] == {
        "patterns": [{"resourceType": "Document", "requestStage": "Request"}]}
    assert h.trang.cdp.cac_goi("Page.startScreencast")[0]["maxWidth"] == 800
    assert h.trang.cdp.cac_goi("Page.startScreencast")[0]["format"] == "jpeg"


def test_dung_trang_chinh_cua_context_de_chi_co_mot_trang(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.1, h.lenh("dung"))]
    h.chay()
    assert len(h.ctx.pages) == 1


def test_mo_trinh_duyet_trat_dang_mo_ve_cho_xac_minh(monkeypatch, db):
    h = Hien(monkeypatch, db, hong_mo=True)
    kq = h.chay()
    job = models.get_job(db, h.jid)
    assert kq.loai == "cho_xac_minh" and job["trang_thai"] == "cho_xac_minh"
    assert job["ly_do_dung"] == gc.LD_LOI_TRINH_DUYET
    assert not scraper_mod.profile_dir_dang_mo(profile_theo_job.thu_muc_profile_job(db, h.jid))


def test_goto_qua_gio_ve_cho_xac_minh_mo_trang_truot(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.goto_loi = scraper_mod.PWTimeout("30000ms")
    h.chay()
    assert h.tt() == "cho_xac_minh"
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_MO_TRANG_TRUOT and h.ctx.closed


def test_khong_ai_giu_khoa_thi_khong_mo_trinh_duyet(monkeypatch, db):
    monkeypatch.setattr(gc, "CHO_NGUOI_XEM_GIAY", 1.0)
    h = Hien(monkeypatch, db, giu_khoa=False)
    h.chay()
    assert h.pw.so_lan_mo == 0
    assert h.tt() == "cho_xac_minh"
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_KHONG_AI_XEM


def test_khung_dau_khong_ve_ve_cho_xac_minh(monkeypatch, db):
    monkeypatch.setattr(gc, "CHO_KHUNG_DAU_GIAY", 1.0)
    h = Hien(monkeypatch, db, phat_khung=False)
    h.chay()
    assert h.tt() == "cho_xac_minh" and h.ctx.closed
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_KHONG_CO_KHUNG


# ---------------------------------------------------------------------------
# dang_giai → cho_xac_minh (hết giờ, lỗi, rời miền, gesture dở)
# ---------------------------------------------------------------------------

def test_het_5_phut_ve_cho_xac_minh_va_dong_context(monkeypatch, db):
    h = Hien(monkeypatch, db, cua_so_giay=5)
    h.chay()
    assert h.tt() == "cho_xac_minh" and h.ctx.closed
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_HET_GIO
    assert h.dong.t - 1000.0 >= 5, "chạy hết cửa sổ theo đồng hồ"


def test_loi_playwright_trong_dang_giai_ve_cho_xac_minh_khong_nem(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.2, lambda: setattr(h.trang, "wait_loi", RuntimeError("Target closed")))]
    kq = h.chay()                                   # KHÔNG ném
    assert kq.loai == "cho_xac_minh" and h.tt() == "cho_xac_minh" and h.ctx.closed
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_LOI_TRINH_DUYET


def test_loi_gui_cdp_trong_dang_giai_ve_cho_xac_minh(monkeypatch, db):
    h = Hien(monkeypatch, db)

    def gui():
        h.trang.cdp.loi_khi_gui["Input.dispatchMouseEvent"] = RuntimeError("Session closed")
        h.nguoi.gui(("move", 100, 100, 0))
    h.trang.kich_ban = [(0.1, gui)]
    h.chay()
    assert h.tt() == "cho_xac_minh" and h.ctx.closed


def test_roi_mien_ve_cho_xac_minh(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.2, lambda: h.trang.cdp.phat(
        "Page.frameNavigated", {"frame": {"id": "F1", "url": "https://evil.example/x"}}))]
    h.chay()
    assert h.tt() == "cho_xac_minh" and models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_ROI_MIEN


def test_trang_moi_bi_dong_ngay_va_dem(monkeypatch, db, caplog):
    h = Hien(monkeypatch, db)
    moi = {}

    def mo():
        moi["p"] = h.ctx.mo_trang_moi("https://other.example/path?token=BIMAT")

    h.trang.kich_ban = [(0.1, mo), (0.2, h.lenh("dung"))]
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        h.chay()
    assert moi["p"].dong_roi is True
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "other.example" in log_text and "BIMAT" not in log_text, "log host+path, KHÔNG query"
    assert "trang_moi_dong=1" in log_text


def test_khung_chi_ra_khi_chua_roi_mien(monkeypatch, db):
    h = Hien(monkeypatch, db)

    def roi():
        h.trang.cdp.phat("Page.frameNavigated", {"frame": {"id": "F1", "url": "https://evil.example/"}})
        h.trang.cdp.phat("Page.screencastFrame", {"data": "TRANGLA", "sessionId": 2,
                                                 "metadata": {"deviceWidth": 1280, "deviceHeight": 900}})
    h.trang.kich_ban = [(0.1, roi)]
    h.chay()
    assert h.phien.lay_khung()["jpeg"] != "TRANGLA", "khung của trang lạ không bao giờ lên popup"
    assert {"sessionId": 2} in h.trang.cdp.cac_goi("Page.screencastFrameAck"), "vẫn ack để Chromium không kẹt"


def test_popup_dong_giua_chung_trang_may_chu_van_mo_nguoi_mo_lai_lay_lai_quyen(monkeypatch, db):
    """Popup đóng/phiên hết hạn: khoá nhả theo kết nối SSE, nhưng trang trên máy chủ VẪN MỞ tới hết cửa
    sổ; người mở lại popup (token mới) lấy lại quyền điều khiển và kết thúc được."""
    h = Hien(monkeypatch, db)
    thay = {}

    def kiem():
        thay.update(tt=h.tt(), ctx_dong=h.ctx.closed, giu=h.phien.co_nguoi_giu())

    def mo_lai():
        assert h.phien.nhan_khoa("token-bbbbbbbb", CHU)
        h.phien.dat_lenh("token-bbbbbbbb", CHU, "dung")

    h.trang.kich_ban = [(0.2, lambda: h.phien.nha_khoa(TOKEN, CHU)), (60.0, kiem), (120.0, mo_lai)]
    h.chay()
    assert thay == {"tt": "dang_giai", "ctx_dong": False, "giu": False}
    assert h.tt() == "failed" and h.dong.t - 1000.0 < gc.CUA_SO_GIAI_GIAY


def test_log_cuoi_luot_giai_co_so_dem_tre_qua_D_va_D(monkeypatch, db, caplog):
    monkeypatch.setenv(gc.ENV_D_MS, "250")
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.1, lambda: h.nguoi.gui(("move", 10, 10, 0))), (1.0, h.lenh("dung"))]
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        h.chay()
    dong = [r.getMessage() for r in caplog.records if "vòng giải kết thúc" in r.getMessage()]
    assert len(dong) == 1 and "tre_qua_D=0" in dong[0] and "D=250 ms" in dong[0]


# ---------------------------------------------------------------------------
# Bất biến phát lại / ĐP-606: tool KHÔNG phát gì người không tạo
# ---------------------------------------------------------------------------

def _keo(h, nguoi, x0=100, y0=200):
    nguoi.gui(("move", x0, y0, 0))
    nguoi.gui(("down", x0, y0, 1))
    nguoi.gui(("move", x0 + 30, y0, 1))


def test_gesture_do_khong_phat_mouseup_reload_dung_mot_lan_va_token_moi_duoc_nhan(monkeypatch, db):
    """ĐỘT BIẾN: phát `mouseReleased` khi gesture dở ⇒ ĐỎ."""
    h = Hien(monkeypatch, db)
    nb = {}

    def popup_tai_lai():
        # Popup đóng (SSE ngắt) rồi mở lại với token MỚI: seq về 0, gesture dở của token cũ bị huỷ.
        h.phien.nha_khoa(TOKEN, CHU)
        assert h.phien.nhan_khoa("token-bbbbbbbb", CHU)
        nb["n"] = Nguoi(h.phien, h.dong, token="token-bbbbbbbb")
        assert nb["n"].gui(("move", 300, 300, 0), seq=0) == "ok"       # seq=0 của token mới được nhận

    def keo_moi():
        n = nb["n"]
        n.gui(("down", 310, 300, 1))
        n.gui(("move", 340, 300, 1))
        n.gui(("up", 340, 300, 0))

    h.trang.kich_ban = [
        (0.10, lambda: _keo(h, h.nguoi)),
        (0.50, popup_tai_lai),
        (1.20, keo_moi),
        (1.80, h.lenh("dung", "token-bbbbbbbb")),
    ]
    h.chay()
    phat = h.input_da_phat()
    assert [p["type"] for p in phat].count("mouseReleased") == 1, \
        "chỉ MỘT mouseReleased: cái của NGƯỜI ở lần kéo mới — tool không tự nhả cho gesture dở"
    nguoi_cu, nguoi_moi = h.nguoi.tham_so_nguoi(), nb["n"].tham_so_nguoi()
    assert la_day_con(phat, nguoi_cu + nguoi_moi), "mọi sự kiện trang nhận đều có bản gốc của người, đúng thứ tự"
    assert h.trang.so_reload == 1 and h.phien.so_gesture_bo_do == 1 and h.phien.so_lan_tai_lai == 1
    assert [n for n in h.phien.thong_bao_moi(0) if n[1]["loai"] == "bi_ngat"], "popup được báo thao tác bị ngắt"
    assert h.tt() == "failed"        # kết thúc bằng lệnh `dung` của người


def test_gesture_do_lan_thu_ba_ve_cho_xac_minh_khong_tai_lai_lan_ba(monkeypatch, db):
    h = Hien(monkeypatch, db)

    def do_dang():
        h.nguoi.gui(("down", 100, 100, 1))
        h.nguoi.gui(("move", 130, 100, 1))

    def huy():
        h.phien.huy_gesture("lo_bi_tu_choi")

    h.trang.kich_ban = [(0.10, do_dang), (0.40, huy), (0.70, do_dang), (1.00, huy),
                        (1.30, do_dang), (1.60, huy)]
    h.chay()
    assert h.trang.so_reload == gc.TRAN_TAI_LAI_MOI_LUOT == 2
    assert h.tt() == "cho_xac_minh"
    assert models.get_job(db, h.jid)["ly_do_dung"] == gc.LD_GESTURE_QUA_NHIEU
    assert h.phien.so_gesture_bo_do == 3
    assert "mouseReleased" not in [p["type"] for p in h.input_da_phat()]


def test_huy_khi_nut_chua_nhan_khong_reload(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.1, lambda: h.nguoi.gui(("move", 50, 50, 0))),
                        (0.4, lambda: h.phien.huy_gesture("ngoai_khung")),
                        (0.7, h.lenh("dung"))]
    h.chay()
    assert h.trang.so_reload == 0 and h.phien.so_gesture_bo_do == 0


def test_lenh_huy_gesture_khi_nut_dang_nhan_reload_khong_phat_mouseup(monkeypatch, db):
    """R15b: popup tự bỏ gesture (pointercancel/blur) và báo `huy_gesture` ⇒ đúng đường ĐP-606 (a):
    0 `mouseReleased`, tải lại trang 1 lần, tính vào trần tải lại. Thiếu lệnh này nút kẹt nhấn vì máy
    chủ chỉ tự huỷ khi HỤT `seq`. ĐỘT BIẾN: phát `mouseReleased` ở nhánh huỷ ⇒ ĐỎ."""
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [
        (0.10, lambda: _keo(h, h.nguoi)),
        (0.50, lambda: h.phien.huy_gesture_cua_nguoi_giu(TOKEN, CHU)),
        (0.90, h.lenh("dung")),
    ]
    h.chay()
    phat = h.input_da_phat()
    assert "mouseReleased" not in [p["type"] for p in phat]
    assert h.trang.so_reload == 1 and h.phien.so_gesture_bo_do == 1 and h.phien.so_lan_tai_lai == 1
    bi_ngat = [n for n in h.phien.thong_bao_moi(0) if n[1]["loai"] == "bi_ngat"]
    assert bi_ngat and bi_ngat[0][1]["ly_do"] == gc.LY_DO_HUY_POPUP


def test_lenh_huy_gesture_gui_lap_chi_reload_mot_lan(monkeypatch, db):
    """Popup thử lại `huy_gesture` sau timeout ⇒ máy chủ có thể nhận lệnh 2 lần cho CÙNG một gesture:
    idempotent — một lần tải lại, không phát sự kiện nào."""
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [
        (0.10, lambda: _keo(h, h.nguoi)),
        (0.50, lambda: h.phien.huy_gesture_cua_nguoi_giu(TOKEN, CHU)),
        (0.52, lambda: h.phien.huy_gesture_cua_nguoi_giu(TOKEN, CHU)),
        (0.90, lambda: h.phien.huy_gesture_cua_nguoi_giu(TOKEN, CHU)),   # tới SAU khi worker đã xử lý lần đầu
        (1.30, h.lenh("dung")),
    ]
    h.chay()
    assert "mouseReleased" not in [p["type"] for p in h.input_da_phat()]
    assert h.trang.so_reload == 1 and h.phien.so_gesture_bo_do == 1


def test_lenh_huy_gesture_nguoi_khong_giu_khoa_bi_409_khong_huy(monkeypatch, db):
    h = Hien(monkeypatch, db)
    ma = []

    def nguoi_khac_huy():
        try:
            h.phien.huy_gesture_cua_nguoi_giu("token-khac-xxxx", CHU)
            ma.append(200)
        except gc.LoiGiai as loi:
            ma.append(loi.ma)

    h.trang.kich_ban = [
        (0.10, lambda: _keo(h, h.nguoi)),
        (0.50, nguoi_khac_huy),
        (0.90, h.lenh("dung")),
    ]
    h.chay()
    assert ma == [409]
    assert h.trang.so_reload == 0 and h.phien.so_gesture_bo_do == 0


def test_phat_lai_dung_toa_do_va_buttons_cua_nguoi_khong_them_khong_bot(monkeypatch, db):
    h = Hien(monkeypatch, db)
    tg = h.trang.kich_ban
    cac_buoc = [("move", 3, 7, 0), ("down", 3, 7, 1), ("move", 4, 9, 1), ("move", 5.5, 9.5, 1),
                ("up", 5.5, 9.5, 0), ("move", 600, 400, 0), ("wheel", 600, 400, 0, 0, 120)]
    for i, b in enumerate(cac_buoc):
        tg.append((0.1 + i * 0.05, (lambda b=b: h.nguoi.gui(b))))
    tg.append((1.5, h.lenh("dung")))
    h.chay()
    phat = h.input_da_phat()
    assert phat == h.nguoi.tham_so_nguoi(), "đúng từng sự kiện, đúng thứ tự, không thêm/bớt"
    assert phat[0]["buttons"] == 0 and phat[0]["button"] == "none"          # hover
    assert phat[2]["x"] == 4 * 1.6 and phat[2]["y"] == 9 * 1.6              # đổi đơn vị, KHÔNG làm tròn
    assert phat[3]["x"] == 5.5 * 1.6 and phat[3]["x"] != round(phat[3]["x"])
    assert phat[-1]["type"] == "mouseWheel" and phat[-1]["deltaY"] == 120.0


def test_nut_phai_bi_bo_khong_toi_trang(monkeypatch, db):
    h = Hien(monkeypatch, db)
    h.trang.kich_ban = [(0.1, lambda: h.nguoi.gui(("down", 10, 10, 2))),
                        (0.2, lambda: h.nguoi.gui(("up", 10, 10, 0))),
                        (0.5, h.lenh("dung"))]
    h.chay()
    assert h.input_da_phat() == []


# ---------------------------------------------------------------------------
# da_giai: ranh giới ĐP-606, thứ tự đóng, vẫn bị chặn ⇒ không cuộn
# ---------------------------------------------------------------------------

class _RecAutoScroll:
    def __init__(self, h, ra=()):
        self.h, self.ra, self.goi = h, set(ra), []

    def __call__(self, page, max_videos, scroll_pause, idle_rounds):
        h = self.h
        self.goi.append({
            "phien_da_dong": h.phien.da_dong,
            "co_nguoi_giu": h.phien.co_nguoi_giu(),
            "so_sse": h.phien.so_sse,
            "da_tat_screencast": h.trang.cdp.da_goi("Page.stopScreencast"),
            "da_tat_fetch": h.trang.cdp.da_goi("Fetch.disable"),
            "db": h.tt(),
            "mouse_cua_tool_truoc": list(h.trang.mouse_cua_tool),
            "reload": h.trang.so_reload,
        })
        return self.ra


def _da_giai_harness(monkeypatch, db, phan_hoi, ra=()):
    h = Hien(monkeypatch, db)
    rec = _RecAutoScroll(h, ra)
    monkeypatch.setattr(scraper_mod, "_auto_scroll", rec)
    h.trang.phan_hoi_khi_tai = [phan_hoi]
    h.phien.so_sse = 1
    # Luồng SSE (bên web) đóng khi phiên báo `da_dong`.
    h.trang.moi_tick = lambda: setattr(h.phien, "so_sse", 0) if h.phien.da_dong else None
    h.trang.kich_ban = [(0.1, lambda: h.nguoi.gui(("move", 100, 100, 0))),
                        (0.2, h.lenh("da_giai"))]
    return h, rec


def test_da_giai_thong_tat_screencast_nha_khoa_dong_sse_truoc_auto_scroll(monkeypatch, db):
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=False)], ra=[_ref("111"), _ref("112")])
    kq = h.chay()
    assert len(rec.goi) == 1
    g = rec.goi[0]
    assert g["phien_da_dong"] and not g["co_nguoi_giu"] and g["so_sse"] == 0
    assert g["da_tat_screencast"] and g["da_tat_fetch"]
    assert g["db"] == "running", "đã sang `running` trước khi quét"
    assert g["mouse_cua_tool_truoc"] == [] and g["reload"] == 1
    assert kq.loai == "refs" and [r.video_id for r in kq.refs] == ["112", "111"]
    assert len(h.input_da_phat()) == 1, "sự kiện cuối tool phát là của người (move ở 0.1)"
    ten = [m for m, _ in h.trang.cdp.goi]
    assert ten.index("Page.stopScreencast") < ten.index("Fetch.disable")


def test_da_giai_van_bi_chan_khong_auto_scroll_ve_cho_xac_minh_captcha_chua_xong(monkeypatch, db):
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=True)])
    kq = h.chay()
    assert rec.goi == [], "vẫn thấy dấu hiệu bị chặn ⇒ KHÔNG `_auto_scroll`"
    assert h.trang.mouse_cua_tool == []
    assert kq.loai == "cho_xac_minh"
    job = models.get_job(db, h.jid)
    assert job["trang_thai"] == "cho_xac_minh" and job["ly_do_dung"] == gc.LD_CAPTCHA_CHUA_XONG
    assert h.ctx.closed


def test_da_giai_khong_do_duoc_feed_cung_la_van_bi_chan(monkeypatch, db):
    h, rec = _da_giai_harness(monkeypatch, db, [])
    h.chay()
    assert rec.goi == [] and h.tt() == "cho_xac_minh"


def test_da_giai_phat_not_su_kien_da_nhan_truoc_khi_lam_theo_lenh(monkeypatch, db):
    """Lệnh tới khi hàng đợi (trễ D) còn sự kiện ⇒ phát nốt rồi mới tắt screencast."""
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=False)])
    h.trang.kich_ban = [(0.1, lambda: (h.nguoi.gui(("down", 10, 10, 1)), h.nguoi.gui(("up", 10, 10, 0)),
                                       h.lenh("da_giai")()))]
    h.chay()
    assert [p["type"] for p in h.input_da_phat()] == ["mousePressed", "mouseReleased"]
    ten = [m for m, _ in h.trang.cdp.goi]
    assert max(i for i, m in enumerate(ten) if m == "Input.dispatchMouseEvent") < ten.index("Page.stopScreencast")


def test_da_giai_ghi_so_trang_va_xoa_ly_do_cu(monkeypatch, db):
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=False)])
    h.chay()
    job = models.get_job(db, h.jid)
    assert job["so_trang"] == 1, "lượt tải lại sau khi giải cũng tiêu trần liệt kê"
    assert job["ly_do_dung"] is None, "`feed_rong` của lần quét trước không được dính vào job đang chạy"


def test_process_job_luot_giai_den_het_duong(monkeypatch, db, tmp_path):
    """dang_mo → … → running → tải → kết thúc, qua `process_job` thật (lọc trùng MỘT lần ở cuối)."""
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=False)],
                              ra=[_ref("111"), _ref("112"), _ref("113")])
    models.record_video(db, job_id=1, video_id="112", url="https://t/112", tao_luc="2026-01-01T00:00:00+00:00")
    daxuong = {}
    monkeypatch.setattr(queue_mod, "download_all",
                        lambda refs, out, cookies_path=None, progress=None: daxuong.setdefault("refs", refs))
    process_job(db, tmp_path / "dl", tmp_path / "ck", h.job)
    job = models.get_job(db, h.jid)
    assert [r.video_id for r in daxuong["refs"]] == ["113", "111"], "112 thư viện đã có ⇒ bỏ"
    assert job["bo_qua"] == 1 and job["tim_thay"] == 2
    assert job["trang_thai"] in ("done", "failed")
    assert not (db.parent / "profiles" / str(h.jid)).exists(), "job đã kết thúc ⇒ xoá profile"


def test_process_job_luot_giai_chua_xong_giu_profile_cho_lan_sau(monkeypatch, db, tmp_path):
    h, rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=True)])
    process_job(db, tmp_path / "dl", tmp_path / "ck", h.job)
    assert h.tt() == "cho_xac_minh"
    assert (db.parent / "profiles" / str(h.jid)).is_dir()


def test_process_job_loi_he_thong_trong_luot_giai_ve_cho_xac_minh(monkeypatch, db, tmp_path):
    h = Hien(monkeypatch, db)

    def hong(*a, **k):
        raise RuntimeError("hỏng ngoài dự kiến")

    monkeypatch.setattr(worker, "chay_luot_giai", hong)
    process_job(db, tmp_path / "dl", tmp_path / "ck", h.job)
    assert h.tt() == "cho_xac_minh", "lỗi lúc đang giải ≠ job hỏng"


def test_luong_worker_song_sau_loi_trong_dang_giai_va_nhan_job_ke(monkeypatch, db, tmp_path):
    h = Hien(monkeypatch, db)
    # Đưa job về cho_giai để chính `JobWorker` nhặt nó.
    assert mgc.chuyen_trang_thai(db, h.jid, "dang_mo", "cho_giai")
    h.trang.wait_loi = RuntimeError("Target closed")
    ke = models.create_job(db, URL_MUSIC, 3, CHU)
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod, "scrape_music_page", lambda url, **kw: [])
    w = JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  disk_guard_fn=lambda p: SimpleNamespace(ok=True, reason=""))
    w.start()
    try:
        han = time.monotonic() + 15
        while time.monotonic() < han and _trang_thai(db, ke) in ("pending", "running"):
            time.sleep(0.02)
        assert _trang_thai(db, h.jid) == "cho_xac_minh"
        assert _trang_thai(db, ke) in ("done", "failed"), "job kế vẫn được xử lý"
        assert w.trang_thai()["song"] is True
    finally:
        w.stop()


# ---------------------------------------------------------------------------
# Ngăn điều hướng (đơn vị: CDP giả)
# ---------------------------------------------------------------------------

def _guard(che_do, ref="https://www.tiktok.com/@nguoi.dung"):
    phien = gc.PhienGiai(1, CHU)
    cdp = CdpGia(None)
    return worker.GacDieuHuong(cdp, phien, ref, "F1", che_do), cdp


def _tam_dung(guard, url, frame="F1", loai="Document", rid="r1"):
    guard._khi_tam_dung({"requestId": rid, "frameId": frame, "resourceType": loai,
                         "request": {"url": url}})


def test_guard_chan_che_do_chan_ca_duong_dan_khac_va_host_khac(caplog):
    g, cdp = _guard(gc.DIEU_HUONG_CHAN)
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        _tam_dung(g, "https://www.tiktok.com/@nguoi.dung?lang=vi")               # cùng đích ⇒ qua
        _tam_dung(g, "https://www.tiktok.com/@nguoi.khac?token=BIMAT", rid="r2")   # đường dẫn khác ⇒ chặn
        _tam_dung(g, "https://evil.example/@nguoi.dung", rid="r3")                 # host khác ⇒ chặn
    ten = [(m, p["requestId"]) for m, p in cdp.goi]
    assert ten == [("Fetch.continueRequest", "r1"), ("Fetch.fulfillRequest", "r2"),
                   ("Fetch.fulfillRequest", "r3")]
    ful = [p for m, p in cdp.goi if m == "Fetch.fulfillRequest"]
    assert all(p["responseCode"] == 204 for p in ful)
    assert g.so_chan == 2
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "BIMAT" not in texto and "path=/@nguoi.khac" in texto


def test_guard_che_do_log_cho_qua_duong_dan_khac_cung_mien_nhung_ghi_log_va_chan_khac_mien(caplog):
    g, cdp = _guard(gc.DIEU_HUONG_LOG)
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        _tam_dung(g, "https://www.tiktok.com/verify/page?x=SECRET")
        _tam_dung(g, "https://evil.example/", rid="r2")
    assert [m for m, _ in cdp.goi] == ["Fetch.continueRequest", "Fetch.fulfillRequest"]
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "host=www.tiktok.com path=/verify/page" in texto and "SECRET" not in texto


def test_guard_iframe_va_request_khong_phai_document_luon_continue_khong_bo_sot():
    g, cdp = _guard(gc.DIEU_HUONG_CHAN)
    _tam_dung(g, "https://evil.example/ads", frame="IFRAME-9")
    _tam_dung(g, "https://evil.example/x.js", loai="Script", rid="r2")
    assert [m for m, _ in cdp.goi] == ["Fetch.continueRequest", "Fetch.continueRequest"]


def test_guard_loi_khi_xu_ly_thi_van_giai_quyet_request_bang_failRequest():
    g, cdp = _guard(gc.DIEU_HUONG_CHAN)
    cdp.loi_khi_gui["Fetch.continueRequest"] = RuntimeError("boom")
    _tam_dung(g, "https://www.tiktok.com/@nguoi.dung")
    assert cdp.goi[-1][0] == "Fetch.failRequest", "không để request treo ⇒ trang treo"


def test_guard_frame_navigated_danh_dau_trang_la_theo_che_do():
    g, _ = _guard(gc.DIEU_HUONG_LOG)
    g._khi_dieu_huong({"frame": {"id": "F1", "url": "https://www.tiktok.com/verify"}})
    assert g.trang_la is False                    # chế độ log: cùng miền không phải "lạ"
    g._khi_dieu_huong({"frame": {"id": "F2", "parentId": "F1", "url": "https://evil.example/"}})
    assert g.trang_la is False                    # iframe không tính
    g._khi_dieu_huong({"frame": {"id": "F1", "url": "https://evil.example/"}})
    assert g.trang_la is True
    g2, _ = _guard(gc.DIEU_HUONG_CHAN)
    g2._khi_dieu_huong({"frame": {"id": "F1", "url": "https://www.tiktok.com/verify"}})
    assert g2.trang_la is True


# ---------------------------------------------------------------------------
# Quá hạn 24 giờ, boot sweep, bộ quét, huỷ
# ---------------------------------------------------------------------------

def _lui_moc(db, jid, gio):
    from datetime import datetime, timedelta, timezone
    moc = (datetime.now(timezone.utc) - timedelta(hours=gio)).isoformat(timespec="microseconds")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET vao_trang_thai_luc = ? WHERE id = ?", (moc, jid))


def test_cho_xac_minh_qua_24_gio_failed_xac_minh_qua_han_con_23_gio_thi_giu(db):
    cu = _job_cho_xac_minh(db)
    moi = _job_cho_xac_minh(db)
    _lui_moc(db, cu, 25)
    _lui_moc(db, moi, 23)
    assert mgc.quet_qua_han(db) == 1
    j = models.get_job(db, cu)
    assert j["trang_thai"] == "failed" and j["ly_do_dung"] == "xac_minh_qua_han" and j["xong_luc"]
    assert _trang_thai(db, moi) == "cho_xac_minh"


def test_bo_quet_het_han_va_don_thu_muc_cung_nhip_chi_khi_co_bat(monkeypatch, db, tmp_path):
    jid = _job_cho_xac_minh(db)
    _lui_moc(db, jid, 30)
    profile_theo_job.chuan_bi_profile_job(db, jid)
    w = JobWorker(db, tmp_path / "dl", tmp_path / "ck")
    assert w._quet_profile_dinh_ky(buoc_ep=True) is None          # cờ TẮT: không đụng gì
    assert _trang_thai(db, jid) == "cho_xac_minh"
    _bat_co(monkeypatch)
    dem = w._quet_profile_dinh_ky(buoc_ep=True)
    assert dem["het_han"] == 1 and dem["da_xoa"] == 1
    assert _trang_thai(db, jid) == "failed"
    assert not (db.parent / "profiles" / str(jid)).exists()


def test_bo_quet_khong_xoa_profile_cua_cho_xac_minh_va_cho_giai(monkeypatch, db, tmp_path):
    _bat_co(monkeypatch)
    a = _job_cho_xac_minh(db)
    b = _job_cho_xac_minh(db)
    mgc.yeu_cau_giai_ngay(db, b)
    for j in (a, b):
        profile_theo_job.chuan_bi_profile_job(db, j)
    dem = JobWorker(db, tmp_path / "dl", tmp_path / "ck")._quet_profile_dinh_ky(buoc_ep=True)
    assert dem["giu"] == 2 and dem["da_xoa"] == 0


@pytest.mark.parametrize("trang_thai", ["cho_giai", "dang_mo", "dang_giai"])
def test_boot_sweep_dua_trang_thai_giai_ve_cho_xac_minh(db, trang_thai):
    """ĐỘT BIẾN: bỏ sweep `cho_giai` ⇒ ĐỎ ở tham số `cho_giai` (sau crash worker mở Chromium chờ 5′ không ai xem)."""
    jid = _job_cho_xac_minh(db)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (trang_thai, jid))
    run = models.create_job(db, URL_MUSIC, 1, CHU)
    models.claim_next_pending_job(db)
    assert models.mark_running_as_interrupted(db, co_giai=True) == 1   # chỉ đếm `running`
    j = models.get_job(db, jid)
    assert j["trang_thai"] == "cho_xac_minh" and j["vao_trang_thai_luc"]
    assert j["ly_do_dung"] == gc.LD_KHOI_DONG_LAI
    assert _trang_thai(db, run) == "interrupted"


def test_boot_sweep_co_bat_giu_nguyen_cho_xac_minh(db):
    """ĐỘT BIẾN: áp nhánh cờ TẮT cả khi cờ BẬT ⇒ ĐỎ (job chờ người giải bị kết thúc oan sau mỗi lần restart)."""
    jid = _job_cho_xac_minh(db, ly_do="feed_rong")
    assert models.mark_running_as_interrupted(db, co_giai=True) == 0
    j = models.get_job(db, jid)
    assert j["trang_thai"] == "cho_xac_minh" and j["ly_do_dung"] == "feed_rong"


@pytest.mark.parametrize("trang_thai", gc.TRANG_THAI_GIAI)
def test_boot_sweep_co_tat_ket_thuc_trang_thai_giai_la_interrupted(db, trang_thai):
    """ĐP-706: cờ TẮT thì không còn lối ra tự động nào (không nhặt `cho_giai`, không quét quá hạn) ⇒
    boot kết thúc mọi trạng thái giải là `interrupted` + `tinh_nang_giai_tat`, không để treo vô hạn.
    ĐỘT BIẾN: bỏ nhánh cờ TẮT ⇒ ĐỎ ở cả 4 tham số."""
    jid = _job_cho_xac_minh(db)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (trang_thai, jid))
    run = models.create_job(db, URL_MUSIC, 1, CHU)
    models.claim_next_pending_job(db)
    assert models.mark_running_as_interrupted(db) == 1          # mặc định = cờ TẮT; vẫn chỉ đếm `running`
    j = models.get_job(db, jid)
    assert j["trang_thai"] == "interrupted"
    assert j["ly_do_dung"] == gc.LD_TINH_NANG_GIAI_TAT and j["xong_luc"]
    assert _trang_thai(db, run) == "interrupted"


@pytest.mark.parametrize("bat", [False, True], ids=["co_tat", "co_bat"])
def test_worker_start_truyen_co_cho_boot_sweep(monkeypatch, db, tmp_path, bat):
    """Người gọi duy nhất (`JobWorker.start`) phải truyền cờ THẬT — truyền cứng một giá trị là một
    trong hai nhánh không bao giờ chạy trên prod."""
    if bat:
        _bat_co(monkeypatch)
    nhan = []
    that = models.mark_running_as_interrupted
    monkeypatch.setattr(models, "mark_running_as_interrupted",
                        lambda p, **kw: nhan.append(kw) or that(p, **kw))
    w = JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=lambda *a: None)
    w.start()
    w.stop()
    assert nhan == [{"co_giai": bat}]


@pytest.mark.parametrize("trang_thai", ["cho_xac_minh", "cho_giai"])
def test_co_tat_van_huy_duoc_job_dang_cho_giai(db, trang_thai):
    """ĐP-705: tắt cờ sau khi đã bật mà còn job chờ giải ⇒ chủ job VẪN rút được (không kẹt).
    ĐỘT BIẾN: bỏ `cho_giai`/`cho_xac_minh` khỏi `huy_job_dang_cho` ⇒ ĐỎ."""
    jid = _job_cho_xac_minh(db)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (trang_thai, jid))
    assert models.huy_job_dang_cho(db, jid, CHU) == "da_huy"
    assert _trang_thai(db, jid) == "cancelled"


def test_co_tat_db_chua_tung_bat_ket_qua_y_ban_truoc(db):
    """ĐP-705 (i): cờ TẮT + DB chưa từng có trạng thái giải ⇒ dữ liệu ra của 4 hàm đổi SQL
    (`vi_tri_hang_doi`, `huy_job_dang_cho`, `mark_running_as_interrupted`, `mark_job_interrupted`)
    đúng như 984cfb0 — so DỮ LIỆU, không so câu SQL."""
    a, b, c = (models.create_job(db, URL_MUSIC, 1, CHU) for _ in range(3))
    models.claim_next_pending_job(db)                            # a: running; b, c: pending
    assert models.vi_tri_hang_doi(db, [a, b, c]) == {b: 2, c: 3}
    assert models.huy_job_dang_cho(db, a, CHU) == "dang_chay"
    assert models.huy_job_dang_cho(db, c, CHU) == "da_huy"
    assert models.mark_job_interrupted(db, b) is False           # pending: không đổi
    assert models.mark_running_as_interrupted(db) == 1
    trang = {j: _trang_thai(db, j) for j in (a, b, c)}
    assert trang == {a: "interrupted", b: "pending", c: "cancelled"}
    assert models.get_job(db, a)["ly_do_dung"] is None           # nhánh cờ TẮT không chạm job thường
    assert models.mark_job_interrupted(db, a) is False           # đã interrupted: không đổi


def test_mark_job_interrupted_dua_dang_x_ve_cho_xac_minh_con_running_thanh_interrupted(db):
    jid = _job_cho_xac_minh(db)
    mgc.yeu_cau_giai_ngay(db, jid)
    assert models.mark_job_interrupted(db, jid) is True
    assert _trang_thai(db, jid) == "cho_xac_minh"
    run = models.create_job(db, URL_MUSIC, 1, CHU)
    models.claim_next_pending_job(db)
    assert models.mark_job_interrupted(db, run) is True and _trang_thai(db, run) == "interrupted"


def _huy(monkeypatch, db, jid, nguoi=CHU):
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    return app_mod.huy_job(jid, nguoi_tao=nguoi)


@pytest.mark.parametrize("sang", ["cho_xac_minh", "cho_giai"])
def test_huy_cho_xac_minh_va_cho_giai_cancelled_va_thu_muc_mat(monkeypatch, db, sang):
    """ĐỘT BIẾN: bỏ xoá thư mục ở đường huỷ ⇒ ĐỎ."""
    _bat_co(monkeypatch)
    jid = _job_cho_xac_minh(db)
    if sang == "cho_giai":
        mgc.yeu_cau_giai_ngay(db, jid)
    thu_muc = profile_theo_job.chuan_bi_profile_job(db, jid)
    (thu_muc / "Cookies").write_text("x")
    assert _huy(monkeypatch, db, jid) == {"trang_thai": "cancelled"}
    assert _trang_thai(db, jid) == "cancelled"
    assert not thu_muc.exists()


@pytest.mark.parametrize("dang", ["dang_mo", "dang_giai"])
def test_huy_dang_mo_dang_giai_la_dang_chay_409_thong_diep_rieng(monkeypatch, db, dang):
    _bat_co(monkeypatch)
    jid = _job_cho_xac_minh(db)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (dang, jid))
    assert models.huy_job_dang_cho(db, jid, CHU) == "dang_chay"
    with pytest.raises(HTTPException) as e:
        _huy(monkeypatch, db, jid)
    assert e.value.status_code == 409
    assert "giải xác minh" in e.value.detail and "bắt đầu tải" not in e.value.detail
    assert _trang_thai(db, jid) == dang


def test_huy_pending_co_tat_khong_dung_den_profiles(monkeypatch, db):
    jid = models.create_job(db, URL_PROFILE, 1, CHU)
    mo_coi = db.parent / "profiles" / str(jid)
    mo_coi.mkdir(parents=True)
    assert _huy(monkeypatch, db, jid) == {"trang_thai": "cancelled"}
    assert mo_coi.is_dir(), "cờ TẮT: không stat/xoá `profiles/`"


def test_trang_thai_moi_khong_la_trang_thai_ket_thuc():
    for t in ("cho_xac_minh", "cho_giai", "dang_mo", "dang_giai"):
        assert t not in models.VALID_END_STATES and t not in app_mod._END_STATES
        assert t not in profile_theo_job.TRANG_THAI_KET_THUC
    assert models.VALID_END_STATES == ("done", "failed") and app_mod._END_STATES == ("done", "failed", "interrupted")
    with pytest.raises(ValueError):
        models.finish_job(__import__("pathlib").Path("/nonexistent/x.db"), 1, "cho_xac_minh")


def test_api_job_khong_lo_cot_noi_bo_va_chi_job_giai_co_giai_con_luot(monkeypatch, db):
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    jid = _job_cho_xac_minh(db)
    ra = app_mod._job_ra_api(models.get_job(db, jid))
    assert "vao_trang_thai_luc" not in ra and "so_lan_giai_ngay" not in ra and "ua_job" not in ra
    assert ra["giai_con_luot"] == gc.TRAN_GIAI_NGAY
    thuong = models.create_job(db, URL_MUSIC, 1, CHU)
    ra2 = app_mod._job_ra_api(models.get_job(db, thuong))
    assert "giai_con_luot" not in ra2 and "vao_trang_thai_luc" not in ra2


@pytest.mark.parametrize("loi", [KeyboardInterrupt, SystemExit])
def test_base_exception_trong_luot_giai_job_ve_cho_xac_minh_roi_nem_lai(monkeypatch, db, tmp_path, loi):
    """Cờ BẬT, job `dang_mo`: BaseException trong lượt giải ⇒ ném ra NHƯNG job đã về
    `cho_xac_minh` (người bấm "Tôi giải ngay" lại được). Đột biến bỏ `except BaseException` của
    `process_job` ⇒ kẹt `dang_mo` ⇒ ĐỎ."""
    h = Hien(monkeypatch, db)

    def thoat(*a, **k):
        raise loi("mô phỏng")

    monkeypatch.setattr(worker, "chay_luot_giai", thoat)
    with pytest.raises(loi):
        process_job(db, tmp_path / "dl", tmp_path / "ck", h.job)
    assert h.tt() == "cho_xac_minh"


@pytest.mark.parametrize("loi", [KeyboardInterrupt, SystemExit])
def test_base_exception_xuyen_chay_van_dong_phien_va_bo_khoi_so(monkeypatch, db, loi):
    """BaseException đi xuyên `_chay` (đã đóng ctx + nhả khoá profile ở đó) ⇒ `chay_luot_giai` ném
    lại NHƯNG phiên đã đóng (popup nhận `ket_thuc`) và đã rời sổ. Trạng thái DB KHÔNG do hàm này
    ghi (`process_job` ghi). Đột biến bỏ nhánh `kq is None` ⇒ phiên còn mở, còn trong sổ ⇒ ĐỎ."""
    h = Hien(monkeypatch, db)
    phien = gc.lay_phien(h.jid)

    def thoat(*a, **k):
        raise loi("mô phỏng")

    monkeypatch.setattr(worker, "_chay", thoat)
    with pytest.raises(loi):
        h.chay()
    assert gc.lay_phien(h.jid) is None
    assert phien.da_dong and phien.trang_thai_cuoi == worker.LOAI_CHO_XAC_MINH
    assert h.tt() == "dang_mo"


def test_dong_ctx_loi_sau_khi_da_quet_ra_link_giu_ket_qua_va_running(monkeypatch, db, caplog):
    """Đã giải, đã sang `running`, đã quét ra link — rồi `ctx.close()` nổ. Kết quả phải được GIỮ
    (job tải tiếp), không bị kéo về `cho_xac_minh`; khoá profile vẫn nhả; lỗi đóng có một dòng
    WARNING. Đột biến cho `_dong_ctx` ném lại khi không có lỗi gốc ⇒ `cho_xac_minh` ⇒ ĐỎ."""
    h, _rec = _da_giai_harness(monkeypatch, db, [RespFeed(rong=False)], ra=[_ref("111"), _ref("112")])

    def close_no():
        raise OSError("Target closed")

    h.ctx.close = close_no
    with caplog.at_level(logging.WARNING, logger="videodl.web"):
        kq = h.chay()
    assert kq.loai == worker.LOAI_REFS and {r.video_id for r in kq.refs} == {"111", "112"}
    assert h.tt() == "running"
    assert not scraper_mod._PROFILE_DANG_MO, "khoá profile vẫn phải nhả"
    assert any("sau khi đã có kết quả" in r.getMessage() for r in caplog.records)


class _KhoaChen:
    """Thay `_KHOA_PHIEN`: lần NHẢ khoá đầu tiên sau khi gài thì gọi `don_phien_roi` — mô phỏng
    luồng SSE (SSE cuối vừa ngắt) chen vào đúng khe giữa "worker lấy phiên" và việc sau đó."""

    def __init__(self, jid):
        self._that = threading.Lock()
        self.jid, self.gai, self.con_trong_so = jid, False, None

    def __enter__(self):
        self._that.acquire()
        return self

    def __exit__(self, *_exc):
        self._that.release()
        if self.gai:
            self.gai = False
            p = gc._PHIEN.get(self.jid)
            if p is not None:
                gc.don_phien_roi(self.jid, p)
            self.con_trong_so = self.jid in gc._PHIEN
        return False


def test_worker_nhan_phien_khong_bi_don_phien_roi_chen_vao_bo_khoi_so(monkeypatch, db):
    """Đua F5: SSE cuối ngắt NGAY sau khi worker lấy phiên. Cờ `worker_giu` phải được đặt TRONG
    khoá sổ phiên ⇒ `don_phien_roi` thấy worker đang giữ ⇒ không bỏ. Đột biến gán `worker_giu`
    sau `lay_hoac_tao_phien` (như trước) ⇒ phiên bị bỏ khỏi sổ ⇒ ĐỎ."""
    h = Hien(monkeypatch, db, giu_khoa=False)
    assert h.phien.so_sse <= 0 and not h.phien.worker_giu
    khoa = _KhoaChen(h.jid)
    monkeypatch.setattr(gc, "_KHOA_PHIEN", khoa)
    monkeypatch.setattr(worker, "_chay", lambda *a, **k: worker._cho_xac_minh(gc.LD_KHONG_AI_XEM))
    khoa.gai = True
    h.chay()
    assert khoa.con_trong_so is True, "phiên worker vừa nhận đã bị don_phien_roi bỏ khỏi sổ"
