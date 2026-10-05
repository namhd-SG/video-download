"""4 route giải captcha qua server uvicorn THẬT (http.client, SSE đọc dòng thô) — quyền, khoá điều khiển
theo token, kiểm đầu vào, cờ TẮT. Không Playwright (phần đó ở test_giai_captcha_may_trang_thai /
test_giai_captcha_chromium).
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from giai_captcha_http import Sse, cho as _cho, goi
from web import giai_captcha as gc
from web import models, profile_theo_job
from web import models_giai_captcha as mgc

CHU = "chu@x.vn"
KHAC = "nguoi.la@x.vn"
ADMIN = "admin@x.vn"
TA, TB, TC = "token-aaaaaaaa", "token-bbbbbbbb", "token-cccccccc"
URL = "https://www.tiktok.com/@nguoi.dung"


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp_ctx = tempfile.TemporaryDirectory(prefix="videodl-giai-")
    tmp = Path(tmp_ctx.name)
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    models.init_db(app_mod.DB_PATH)
    for e in (CHU, KHAC, ADMIN):
        models.ghi_nhan_nguoi_dung(app_mod.DB_PATH, e)
    assert models.dat_quyen_admin(app_mod.DB_PATH, ADMIN, True, "test")
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None

    def nguoi(request: Request) -> str:
        u = request.headers.get("x-test-user")
        if not u:
            raise HTTPException(status_code=401, detail="chưa đăng nhập")
        return u

    app_mod.app.dependency_overrides[require_user] = nguoi
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    han = time.monotonic() + 10
    while not server.started:
        assert t.is_alive() and time.monotonic() < han, "uvicorn không khởi động được"
        time.sleep(0.05)
    yield port, app_mod.DB_PATH
    server.should_exit = True
    t.join(timeout=8)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    tmp_ctx.cleanup()


@pytest.fixture(autouse=True)
def _co_bat(monkeypatch):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    gc._PHIEN.clear()
    yield
    gc._PHIEN.clear()


@pytest.fixture
def api(may_chu):
    port, db = may_chu
    return port, db


def tao_job(db, trang_thai="cho_xac_minh", nguoi=CHU, so_lan=0):
    jid = models.create_job(db, URL, 10, nguoi)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ?, vao_trang_thai_luc = ?, so_lan_giai_ngay = ? WHERE id = ?",
                     (trang_thai, models._now(), so_lan, jid))
    return jid


def job_dang_giai_co_khung(api, token=TA, nguoi=CHU):
    """Job `dang_giai` + người `nguoi` mở SSE bằng `token` (đang giữ khoá) + một khung hiện có."""
    port, db = api
    jid = tao_job(db, "dang_giai", nguoi)
    s = Sse(port, jid, token, nguoi)
    assert s.status == 200
    s.doc("trang_thai")
    phien = gc.lay_phien(jid)
    phien.worker_giu = True                       # như worker thật: phiên không bị dọn khi SSE ngắt
    phien.dat_trang_thai("dang_giai", 250)
    phien.dat_khung("QUJD", {"deviceWidth": 1280, "deviceHeight": 900, "pageScaleFactor": 1,
                             "scrollOffsetX": 0, "scrollOffsetY": 400})
    return jid, s, phien


def lo(seq, su_kien, token=TA, khung_w=800, ky=0, **them):
    """Một lô `/giai/chuot`. `ky` mặc định 0 (kỳ đầu của lượt giải); sau một lần huỷ phải truyền kỳ mới."""
    return {"token": token, "ky": ky, "seq": seq, "khung_w": khung_w, "su_kien": su_kien, **them}


def move(x=3, y=7, t=10.5, buttons=0, **them):
    return {"k": "move", "x": x, "y": y, "t": t, "buttons": buttons, **them}


# ---------------------------------------------------------------------------
# Cờ TẮT ⇒ 409 rõ ràng, KHÔNG đụng DB
# ---------------------------------------------------------------------------

def test_co_tat_ca_4_route_tra_409_va_khong_doc_db(api, monkeypatch):
    port, db = api
    jid = tao_job(db)
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA)
    monkeypatch.setattr(models, "get_job", lambda *a, **k: pytest.fail("đọc DB khi cờ TẮT"))
    monkeypatch.setattr(mgc, "yeu_cau_giai_ngay", lambda *a, **k: pytest.fail("ghi DB khi cờ TẮT"))
    cac = [("POST", f"/jobs/{jid}/giai", None),
           ("GET", f"/jobs/{jid}/giai/khung?token={TA}", None),
           ("POST", f"/jobs/{jid}/giai/chuot", lo(0, [move()])),
           ("POST", f"/jobs/{jid}/giai/lenh", {"token": TA, "lenh": "dung"})]
    for method, path, body in cac:
        st, ra = goi(port, method, path, body=body)
        assert st == 409 and "đang tắt" in json.dumps(ra, ensure_ascii=False), (method, path, st, ra)


def test_khong_dang_nhap_401(api):
    port, db = api
    jid = tao_job(db)
    for method, path in [("POST", f"/jobs/{jid}/giai"), ("GET", f"/jobs/{jid}/giai/khung?token={TA}"),
                         ("POST", f"/jobs/{jid}/giai/chuot"), ("POST", f"/jobs/{jid}/giai/lenh")]:
        assert goi(port, method, path, user=None, body={})[0] == 401


# ---------------------------------------------------------------------------
# POST /giai — "Tôi giải ngay"
# ---------------------------------------------------------------------------

def test_giai_ngay_chu_job_ok_chuyen_cho_giai_va_dem_luot(api):
    port, db = api
    jid = tao_job(db)
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai")
    assert st == 200 and ra == {"trang_thai": "cho_giai", "giai_con_luot": gc.TRAN_GIAI_NGAY - 1}
    assert models.get_job(db, jid)["trang_thai"] == "cho_giai"
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai")
    assert st == 409 and "bắt đầu tải" not in ra["detail"] and "chờ" in ra["detail"]


def test_giai_ngay_admin_duoc_nguoi_la_403_job_khong_co_404(api):
    port, db = api
    jid = tao_job(db)
    assert goi(port, "POST", f"/jobs/{jid}/giai", user=KHAC)[0] == 403
    assert models.get_job(db, jid)["trang_thai"] == "cho_xac_minh"
    assert goi(port, "POST", f"/jobs/{jid}/giai", user=ADMIN)[0] == 200
    assert goi(port, "POST", "/jobs/987654/giai")[0] == 404


def test_giai_ngay_tran_3_lan_thong_diep_rieng(api):
    port, db = api
    jid = tao_job(db, so_lan=gc.TRAN_GIAI_NGAY)
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai")
    assert st == 409 and f"{gc.TRAN_GIAI_NGAY} lần" in ra["detail"] and "bắt đầu tải" not in ra["detail"]
    assert models.get_job(db, jid)["trang_thai"] == "cho_xac_minh"


@pytest.mark.parametrize("tt", ["pending", "running", "done", "dang_giai", "cancelled"])
def test_giai_ngay_ngoai_cho_xac_minh_409_khong_noi_da_bat_dau_tai(api, tt):
    port, db = api
    jid = tao_job(db, tt)
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai")
    assert st == 409 and "bắt đầu tải" not in ra["detail"]
    assert models.get_job(db, jid)["trang_thai"] == tt


# ---------------------------------------------------------------------------
# GET /giai/khung — SSE, khoá theo token
# ---------------------------------------------------------------------------

def test_sse_quyen_va_trang_thai(api):
    port, db = api
    jid = tao_job(db, "cho_giai")
    assert Sse(port, jid, TA, KHAC).status == 403
    assert Sse(port, 987654, TA).status == 404
    assert Sse(port, jid, "ngan").status == 400
    cx = tao_job(db, "cho_xac_minh")
    r = Sse(port, cx, TA)
    assert r.status == 409
    assert Sse(port, jid, TA, ADMIN).status == 200


def test_sse_nguoi_dau_dieu_khien_tab_sau_chi_xem_khong_lo_email_tab_ngat_thi_tab_sau_lay_duoc(api):
    port, db = api
    jid = tao_job(db, "dang_giai")
    a = Sse(port, jid, TA)
    gc.lay_phien(jid).worker_giu = True
    gc.lay_phien(jid).dat_trang_thai("dang_giai", 250)
    ev, d = a.doc("trang_thai")
    assert d["vai"] == "dieu_khien" and d["trang_thai"] == "dang_giai" and d["co_nguoi_giu"] is True
    assert d["so_lan_tai_lai"] == 0 and d["con_lai_giay"] in (None, *range(240, 251))
    b = Sse(port, jid, TB, ADMIN)                     # admin xem cùng lúc: chỉ xem
    ev, d = b.doc("trang_thai")
    assert d["vai"] == "chi_xem" and d["co_nguoi_giu"] is True
    assert CHU not in b.tho and "@" not in b.tho, "người chỉ-xem KHÔNG thấy email người điều khiển"
    c = Sse(port, jid, TC)                             # tab 2 cùng chủ: cũng chỉ xem
    assert c.doc("trang_thai")[1]["vai"] == "chi_xem"
    c.dong_ket_noi()
    a.dong_ket_noi()                                   # tab 1 ngắt SSE ⇒ nhả khoá
    phien = gc.lay_phien(jid)
    assert _cho(lambda: not phien.co_nguoi_giu()), "khoá phải nhả khi CHÍNH kết nối giữ nó ngắt"
    d2 = Sse(port, jid, TC)
    assert d2.doc("trang_thai")[1]["vai"] == "dieu_khien"
    for s in (b, d2):
        s.dong_ket_noi()


def test_sse_cung_token_noi_lai_giu_expected_seq(api):
    port, db = api
    jid, a, phien = job_dang_giai_co_khung(api)
    assert goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()]))[0] == 200
    assert phien.expected_seq == 1
    a.dong_ket_noi()
    assert _cho(lambda: not phien.co_nguoi_giu())
    a2 = Sse(port, jid, TA)
    tt2 = a2.doc("trang_thai")[1]
    assert tt2["vai"] == "dieu_khien"
    assert phien.expected_seq == 1, "cùng token nối lại ⇒ giữ nguyên số thứ tự lô"
    assert tt2["ky"] == 0, "cùng token nối lại KHÔNG huỷ ⇒ không đổi kỳ (cú kéo dở vẫn tiếp tục)"
    assert goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(1, [move()]))[0] == 200
    a2.dong_ket_noi()
    assert _cho(lambda: not phien.co_nguoi_giu())
    a3 = Sse(port, jid, TC)                            # popup tải lại ⇒ token mới ⇒ huỷ ⇒ KỲ mới, seq 0
    tt3 = a3.doc("trang_thai")[1]
    assert tt3["vai"] == "dieu_khien" and tt3["ky"] == 1
    st, _ = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(2, [move()], ky=0))   # lô CŨ của token A
    assert st == 409, "token A không còn giữ khoá ⇒ không phát"
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()], token=TC, ky=0))
    assert st == 409 and ra["detail"]["ma"] == "ky_cu" and ra["detail"]["ky"] == 1, ra
    assert goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()], token=TC, ky=1))[0] == 200
    a3.dong_ket_noi()


def test_sse_gui_khung_moi_nhat_bi_ngat_va_ket_thuc(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    ev, d = s.doc("khung")
    assert d["jpeg"] == "QUJD" and d["deviceWidth"] == 1280 and d["deviceHeight"] == 900
    assert d["seq"] == 1 and "scrollOffsetY" not in d
    phien.dat_khung("WFla", {"deviceWidth": 1280, "deviceHeight": 900})
    assert s.doc("khung")[1]["seq"] == 2
    phien.thong_bao("bi_ngat", ly_do="thieu_lo", so_lan_tai_lai=1)
    ev, d = s.doc("bi_ngat")
    assert d == {"ly_do": "thieu_lo", "so_lan_tai_lai": 1}
    phien.dong("cho_xac_minh", "het_gio_giai")
    ev, d = s.doc("ket_thuc")
    assert d == {"trang_thai": "cho_xac_minh", "ly_do": "het_gio_giai"}
    assert s.doc() == (None, None), "luồng đóng sau `ket_thuc`"
    # Kết nối mới vào giữa chừng nhận NGAY khung hiện có.
    s.dong_ket_noi()


def test_sse_nguoi_vao_sau_nhan_ngay_khung_hien_co(api):
    port, db = api
    jid, a, phien = job_dang_giai_co_khung(api)
    b = Sse(port, jid, TB, ADMIN)
    assert b.doc("khung")[1]["jpeg"] == "QUJD"
    a.dong_ket_noi()
    b.dong_ket_noi()


def test_sse_ket_thuc_khi_job_roi_trang_thai_giai_vi_bi_rut(api):
    port, db = api
    jid = tao_job(db, "cho_giai")
    s = Sse(port, jid, TA)
    s.doc("trang_thai")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = 'cancelled' WHERE id = ?", (jid,))
    ev, d = s.doc("ket_thuc")
    assert d["trang_thai"] == "cancelled"
    s.dong_ket_noi()


# ---------------------------------------------------------------------------
# POST /giai/chuot
# ---------------------------------------------------------------------------

def test_chuot_ok_doi_don_vi_khong_lam_tron_khong_cong_scroll(api):
    """ĐỘT BIẾN: cộng `scrollOffset` (khung có `scrollOffsetY: 400`) hoặc làm tròn ⇒ ĐỎ."""
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move(3, 7)]))
    assert (st, ra) == (200, {"ok": True, "trung": False})
    ev = phien.den_han(gc.dong_ho() + 100)[0]
    assert (ev.x, ev.y) == (3 * 1.6, 7 * 1.6)
    s.dong_ket_noi()


def test_chuot_token_khong_giu_khoa_409_tab_hai_khong_dieu_khien_duoc(api):
    """ĐỘT BIẾN: bỏ lọc khoá token ở `/chuot` ⇒ ĐỎ."""
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    b = Sse(port, jid, TB)                                # tab 2 cùng chủ: chỉ xem
    assert b.doc("trang_thai")[1]["vai"] == "chi_xem"
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()], token=TB))
    assert st == 409 and "quyền điều khiển" in ra["detail"]
    st, _ = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()], token="token-zzzzzzzz"))
    assert st == 409
    st, _ = goi(port, "POST", f"/jobs/{jid}/giai/chuot", user=ADMIN, body=lo(0, [move()]))
    assert st == 409, "admin dùng ĐÚNG token của người giữ khoá vẫn bị từ chối (khác email)"
    assert phien.expected_seq == 0 and phien.den_han(gc.dong_ho() + 100) == []
    s.dong_ket_noi()
    b.dong_ket_noi()


def test_chuot_khong_giu_khoa_gui_lo_xau_khong_huy_duoc_gesture_cua_nguoi_dang_giu(api):
    """Người/tab không giữ khoá gửi lô SAI (ngoài khung) phải nhận 409 — KHÔNG được chạm vào gesture của
    người đang điều khiển (nếu không thì ai có quyền xem cũng huỷ được thao tác của người giải).
    ĐỘT BIẾN: chỉ bỏ lọc khoá ở route (lớp trong `PhienGiai.nhan_lo` còn) ⇒ lô xấu đi tới nhánh huỷ ⇒ ĐỎ."""
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/chuot"
    assert goi(port, "POST", p, body=lo(0, [{"k": "down", "x": 5, "y": 5, "t": 1, "buttons": 1}]))[0] == 200
    b = Sse(port, jid, TB, ADMIN)
    assert b.doc("trang_thai")[1]["vai"] == "chi_xem"
    st, ra = goi(port, "POST", p, user=ADMIN, body=lo(1, [move(x=9999)], token=TB))
    assert st == 409, ra
    assert phien.lay_huy() is None, "gesture của người đang giữ khoá không bị huỷ bởi người khác"
    assert phien.expected_seq == 1
    assert goi(port, "POST", p, body=lo(1, [move(buttons=1)]))[0] == 200
    s.dong_ket_noi()
    b.dong_ket_noi()


def test_chuot_quyen_va_trang_thai(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    assert goi(port, "POST", f"/jobs/{jid}/giai/chuot", user=KHAC, body=lo(0, [move()]))[0] == 403
    cg = tao_job(db, "cho_giai")
    st, ra = goi(port, "POST", f"/jobs/{cg}/giai/chuot", body=lo(0, [move()]))
    assert st == 409 and "bắt đầu tải" not in ra["detail"]
    assert goi(port, "POST", "/jobs/987654/giai/chuot", body=lo(0, [move()]))[0] == 404
    s.dong_ket_noi()


def test_chuot_seq_trung_la_ok_trung_true_va_lo_toi_lech_duoc_sap_lai(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/chuot"
    assert goi(port, "POST", p, body=lo(1, [move(2, 2, 20.0)]))[1] == {"ok": True, "trung": False}
    assert phien.expected_seq == 0
    assert goi(port, "POST", p, body=lo(0, [move(1, 1, 10.0)]))[1] == {"ok": True, "trung": False}
    assert phien.expected_seq == 2
    assert goi(port, "POST", p, body=lo(0, [move(1, 1, 10.0)]))[1] == {"ok": True, "trung": True}
    xs = [e.x for e in phien.den_han(gc.dong_ho() + 100)]
    assert xs == [1 * 1.6, 2 * 1.6], "phát đúng thứ tự seq dù lô tới lệch"
    s.dong_ket_noi()


@pytest.mark.parametrize("su_kien", [
    [move(x=801)],                                                    # ngoài khung (ngang)
    [move(y=563)],                                                    # ngoài khung (dọc: 800×900/1280 = 562.5)
    [move(x=-1)],
    [{"k": "wheel", "x": 1, "y": 1, "t": 1, "buttons": 0, "dx": 0, "dy": 40, "delta_mode": 1}],
    [{"k": "wheel", "x": 1, "y": 1, "t": 1, "buttons": 0, "dx": 0}],
    [{"k": "click", "x": 1, "y": 1, "t": 1, "buttons": 0}],
    [move(buttons=64)],
    [],
    [move()] * (gc.LO_TOI_DA_SU_KIEN + 1),
], ids=["ngoai-ngang", "ngoai-doc", "am", "delta_mode", "wheel-thieu-dy", "loai-la", "buttons-la",
        "rong", "qua-lon"])
def test_chuot_400_huy_gesture_va_dung_het_seq(api, su_kien):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/chuot"
    assert goi(port, "POST", p, body=lo(0, [{"k": "down", "x": 5, "y": 5, "t": 1, "buttons": 1}]))[0] == 200
    st, ra = goi(port, "POST", p, body=lo(1, su_kien))
    assert st == 400, ra
    assert phien.lay_huy() == "lo_bi_tu_choi"
    assert phien.ky == 1 and phien.expected_seq == 0, "lô bị từ chối ⇒ huỷ ⇒ kỳ mới, đánh số lại từ 0"
    assert phien.den_han(gc.dong_ho() + 100) == [], "gesture dở bị huỷ ⇒ không phát gì nữa"
    st, ra = goi(port, "POST", p, body=lo(2, [move()]))                  # lô kỳ cũ tới sau
    assert st == 409 and ra["detail"]["ma"] == "ky_cu", ra
    assert goi(port, "POST", p, body=lo(0, [move()], ky=1))[0] == 200, "lô của kỳ mới vẫn chạy"
    s.dong_ket_noi()


def test_chuot_so_khong_huu_han_nan_infinity_bi_400(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/chuot"
    for tho in ('{"k":"move","x":NaN,"y":1,"t":1,"buttons":0}', '{"k":"move","x":1,"y":Infinity,"t":1,"buttons":0}',
                '{"k":"move","x":1,"y":1,"t":-Infinity,"buttons":0}'):
        raw = '{"token":"%s","seq":%d,"khung_w":800,"su_kien":[%s]}' % (TA, phien.expected_seq, tho)
        assert goi(port, "POST", p, raw=raw)[0] == 400, tho
    raw = '{"token":"%s","seq":%d,"khung_w":NaN,"su_kien":[%s]}' % (TA, phien.expected_seq, json.dumps(move()))
    assert goi(port, "POST", p, raw=raw)[0] == 400
    s.dong_ket_noi()


def test_chuot_nut_phai_bi_bo_khong_vao_lich(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    assert goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move(buttons=2)]))[0] == 200
    assert phien.den_han(gc.dong_ho() + 100) == []
    s.dong_ket_noi()


def test_chuot_gioi_han_tan_suat_429(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    ma = [goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(i, [move()]))[0]
          for i in range(gc.LO_TOI_DA_MOI_GIAY + 5)]
    assert ma.count(200) == gc.LO_TOI_DA_MOI_GIAY and ma.count(429) == 5
    s.dong_ket_noi()


def test_chuot_chua_co_khung_409(api):
    port, db = api
    jid = tao_job(db, "dang_giai")
    s = Sse(port, jid, TA)
    s.doc("trang_thai")
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=lo(0, [move()]))
    assert st == 409 and "khung" in ra["detail"]
    s.dong_ket_noi()


# ---------------------------------------------------------------------------
# POST /giai/lenh
# ---------------------------------------------------------------------------

def test_lenh_nguoi_giu_khoa_vao_hang_doi_nguoi_khac_409(api):
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/lenh"
    assert goi(port, "POST", p, body={"token": TB, "lenh": "dung"})[0] == 409
    assert goi(port, "POST", p, user=KHAC, body={"token": TA, "lenh": "dung"})[0] == 403
    assert goi(port, "POST", p, body={"token": TA, "lenh": "xoa-het"})[0] == 400
    assert phien.xem_lenh() is None
    assert goi(port, "POST", p, body={"token": TA, "lenh": "da_giai"}) == (200, {"ok": True})
    assert phien.xem_lenh() == "da_giai"
    s.dong_ket_noi()


def test_lenh_huy_gesture_chi_nguoi_giu_khoa_huy_ngay_khong_vao_hang_lenh(api):
    """R15b: `huy_gesture` huỷ gesture dở NGAY (không xếp hàng `_lenh` — worker tiêu hàng đó như lệnh
    kết thúc lượt). Người không giữ khoá ⇒ 409 và KHÔNG huỷ được gesture của người đang giải.
    ĐỘT BIẾN: bỏ kiểm `la_giu` trong `huy_gesture_cua_nguoi_giu` ⇒ ĐỎ; xếp vào hàng `_lenh` ⇒ ĐỎ."""
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    p = f"/jobs/{jid}/giai/lenh"
    assert goi(port, "POST", p, body={"token": TB, "lenh": "huy_gesture", "ky": 0})[0] == 409
    assert phien.lay_huy() is None
    assert goi(port, "POST", p, user=KHAC, body={"token": TA, "lenh": "huy_gesture", "ky": 0})[0] == 403
    assert phien.lay_huy() is None
    assert goi(port, "POST", p, body={"token": TA, "lenh": "huy_gesture", "den_seq": 0})[0] == 400   # thiếu ky
    assert phien.lay_huy() is None
    assert goi(port, "POST", p, body={"token": TA, "lenh": "huy_gesture", "ky": 0, "den_seq": 0}) == (200, {"ok": True, "ky": 1, "ky_mat_nut": 0})
    assert phien.lay_huy() == gc.LY_DO_HUY_POPUP and phien.ky == 1
    assert phien.xem_lenh() is None
    # Bản sao muộn của chính lệnh đó (kỳ 0) ⇒ 409 ky_cu, KHÔNG huỷ nhầm kỳ mới.
    st, ra = goi(port, "POST", p, body={"token": TA, "lenh": "huy_gesture", "ky": 0})
    assert st == 409 and ra["detail"] == {"ma": "ky_cu", "ky": 1, "thong_diep": ra["detail"]["thong_diep"]}, ra
    assert phien.lay_huy() is None and phien.ky == 1
    s.dong_ket_noi()


def test_lenh_ngoai_dang_giai_409(api):
    port, db = api
    jid = tao_job(db, "cho_giai")
    s = Sse(port, jid, TA)
    s.doc("trang_thai")
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/lenh", body={"token": TA, "lenh": "dung"})
    assert st == 409 and "bắt đầu tải" not in ra["detail"]
    s.dong_ket_noi()


# ---------------------------------------------------------------------------
# Mặt API cũ
# ---------------------------------------------------------------------------

def test_get_job_khong_lo_cot_noi_bo_job_giai_co_giai_con_luot(api):
    port, db = api
    jid = tao_job(db, "cho_xac_minh", so_lan=1)
    st, ra = goi(port, "GET", f"/jobs/{jid}")
    assert st == 200 and ra["giai_con_luot"] == gc.TRAN_GIAI_NGAY - 1
    for cot in ("vao_trang_thai_luc", "so_lan_giai_ngay", "ua_job"):
        assert cot not in ra
    thuong = models.create_job(db, URL, 1, CHU)
    st, ra = goi(port, "GET", f"/jobs/{thuong}")
    assert "giai_con_luot" not in ra


def test_sse_events_cu_giu_mo_cho_trang_thai_moi(api):
    """`/jobs/{id}/events` chỉ dừng ở trạng thái kết thúc — trạng thái giải KHÔNG nằm trong đó."""
    port, db = api
    jid = tao_job(db, "cho_giai")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    c.request("GET", f"/jobs/{jid}/events", headers={"X-Test-User": CHU})
    r = c.getresponse()
    assert r.status == 200
    dong = r.readline() + r.readline()
    assert b"cho_giai" in dong
    c.close()


def test_chuot_thieu_ky_la_popup_cu_400(api):
    """Máy chủ mới + popup cũ (không gửi `ky`) ⇒ 400 với thông điệp "tải lại trang" (không đoán kỳ: popup cũ
    không đặt lại seq nên sau lần huỷ đầu sẽ vào vòng hụt-lô vô tận). ĐỘT BIẾN: chấp nhận thiếu `ky` ⇒ ĐỎ."""
    port, db = api
    jid, s, phien = job_dang_giai_co_khung(api)
    body = lo(0, [move()])
    body.pop("ky")
    st, ra = goi(port, "POST", f"/jobs/{jid}/giai/chuot", body=body)
    assert st == 400 and "tải lại trang" in ra["detail"], ra
    assert phien.expected_seq == 0
    s.dong_ket_noi()
