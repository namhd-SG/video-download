"""Relay dự phòng + canh relay (plan P6, chốt L2 agy R2b): mini chỉ giao việc cho relay dự phòng khi relay chính im quá 5 phút; relay dự
phòng không bao giờ nộp lỗi; relay chính có nhịp sống trong lúc chờ agy; canh Discord theo TUỔI việc chưa có kết quả, mốc ghi SAU khi gửi."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from fastapi import FastAPI  # noqa: E402
from test_thay_logo_relay import H, JPEG, TOKEN, _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo import canh_relay, hang_doi, nhat_ky, nhip_relay, relay_may_dev  # noqa: E402
from tiktok_music_downloader.thay_logo.hop_thu import HopThu  # noqa: E402
from web import thay_logo_routes  # noqa: E402

R = thay_logo_routes.TIEN_TO


class _DongHo:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ nhịp sống phía mini + cổng /viec?du_phong=1
def test_nhip_relay_du_phong_chi_tiep_quan_khi_chinh_im_qua_5_phut():
    dh = _DongHo()
    n = nhip_relay.NhipRelay(dh)
    assert not n.chinh_con_song()  # chính chưa từng hỏi ⇒ dự phòng được nhận việc
    n.ghi(du_phong=False)
    dh.t += 299
    assert n.chinh_con_song()
    dh.t += 2
    assert not n.chinh_con_song()
    n.ghi(du_phong=True)
    assert n.tuoi()["du_phong"] == 0 and n.tuoi()["chinh"] == pytest.approx(301)


@pytest.fixture
def relay(tmp_path, monkeypatch):
    monkeypatch.setenv(thay_logo_routes.ENV_TOKEN, TOKEN)
    dh = _DongHo()
    monkeypatch.setattr(nhip_relay, "NHIP", nhip_relay.NhipRelay(dh))
    hop = HopThu(tmp_path / "hop_thu")
    hop.tao_viec(7, [JPEG])
    app = FastAPI()
    thay_logo_routes.dang_ky_route(app, lambda: hop)
    mc = MayChu(app)
    yield _Client(mc), dh
    mc.dung()


def _so_viec(c, du_phong):
    r = c.get(f"{R}/viec" + ("?du_phong=1" if du_phong else ""), headers=H)
    assert r.status_code == 200
    return len(r.json()["viec"])


def test_route_viec_du_phong_nhan_rong_khi_chinh_vua_hoi(relay):
    """ĐỘT BIẾN: bỏ cổng `chinh_con_song()` ⇒ dự phòng nhận việc khi chính còn sống (đốt trùng quota) ⇒ ĐỎ."""
    c, dh = relay
    assert _so_viec(c, du_phong=True) == 1  # chính chưa hỏi lần nào (mini vừa chạy)
    assert _so_viec(c, du_phong=False) == 1  # chính hỏi ⇒ ghi nhịp
    dh.t += 100
    assert _so_viec(c, du_phong=True) == 0
    dh.t += 201
    assert _so_viec(c, du_phong=True) == 1  # chính im 301 s ⇒ dự phòng nhận ĐỦ danh sách (gom lô như thường)


def test_route_viec_du_phong_gia_tri_la_tra_422(relay):
    c, _ = relay
    assert c.get(f"{R}/viec?du_phong=2", headers=H).status_code == 422


# ------------------------------------------------------------------ phía relay
class _MiniGhi(relay_may_dev._Mini):
    def __init__(self, du_phong):
        super().__init__("http://mini.invalid", "x" * 40, du_phong=du_phong)
        self.goi = []

    def _req(self, path, data=None, tran=1_000_000):
        self.goi.append(path)
        if path.startswith("/viec"):
            return b'{"viec": []}'
        return b""


def test_mini_du_phong_hoi_viec_co_co_va_khong_bao_gio_nop_loi():
    """ĐỘT BIẾN: bỏ chặn trong `nop_loi` ⇒ dự phòng gửi /loi/… ⇒ ĐỎ."""
    m = _MiniGhi(du_phong=True)
    m.viec()
    m.nop_loi(5, "model_khong_nhan")
    m.nop_loi(5, "thieu_anh")
    assert m.goi == ["/viec?du_phong=1"]


def test_mini_chinh_van_nop_loi_nhu_cu():
    m = _MiniGhi(du_phong=False)
    m.viec()
    m.nop_loi(5, "thieu_anh")
    assert m.goi[0] == "/viec" and m.goi[1].startswith("/loi/5")


def test_relay_chinh_co_nhip_song_trong_luc_cho_agy_va_dung_khi_xong(monkeypatch):
    """Nhịp chỉ sống TRONG lời gọi agy (try/finally): xong agy là thôi hỏi. ĐỘT BIẾN: không dừng luồng nhịp ⇒ còn hỏi sau khi xong ⇒ ĐỎ."""
    monkeypatch.setattr(relay_may_dev, "NHIP_GIAY", 0.02)
    m = _MiniGhi(du_phong=False)

    def agy_cham(anh):
        time.sleep(0.15)
        return {"items": []}
    relay_may_dev._goi_agy_co_nhip(m, agy_cham, [])
    sau_agy = len(m.goi)
    assert sau_agy >= 3 and all(p == "/viec" for p in m.goi)
    time.sleep(0.1)
    assert len(m.goi) == sau_agy
    assert not [t for t in threading.enumerate() if t.name == "relay-nhip"]


def test_relay_du_phong_khong_co_nhip_song(monkeypatch):
    monkeypatch.setattr(relay_may_dev, "NHIP_GIAY", 0.02)
    m = _MiniGhi(du_phong=True)
    relay_may_dev._goi_agy_co_nhip(m, lambda anh: (time.sleep(0.1), {"items": []})[1], [])
    assert m.goi == []


def test_nhip_loi_mang_khong_lam_hong_loi_goi_agy(monkeypatch):
    monkeypatch.setattr(relay_may_dev, "NHIP_GIAY", 0.02)
    m = _MiniGhi(du_phong=False)

    def hong(*a, **k):
        raise OSError("mạng chớp")
    monkeypatch.setattr(m, "viec", hong)
    assert relay_may_dev._goi_agy_co_nhip(m, lambda anh: (time.sleep(0.08), {"ok": 1})[1], []) == {"ok": 1}


# ------------------------------------------------------------------ canh relay (Discord)
class _HopGia:
    def __init__(self, co=()):
        self.co = set(co)

    def doc_ket_qua(self, vid, luot=1):
        return {"x": 1} if vid in self.co else None


@pytest.fixture
def ctx(tmp_path):
    import types
    c = nhat_ky.mo(tmp_path / "tl.db")
    hang_doi.khoi_tao(c)
    j = hang_doi.tao_job(c, "a@x", [{"kieu": "drive", "file_id": "F" * 20}, {"kieu": "drive", "file_id": "G" * 20}])
    yield types.SimpleNamespace(conn=c, vids=[r[0] for r in c.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (j,))])
    c.close()


def _cho(conn, vid, phut):
    hang_doi.dat(conn, vid, "cho_agy", cho_agy_tu=time.time() - phut * 60)


def _gui_ghi(kq):
    ghi = []

    def gui(chu):
        ghi.append(chu)
        return kq
    gui.ghi = ghi
    return gui


def test_canh_bao_video_cho_qua_15_phut_chua_co_ket_qua(ctx):
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 20)
    _cho(conn, vids[1], 5)  # chưa tới ngưỡng
    gui = _gui_ghi(True)
    assert canh_relay.thu_canh(conn, _HopGia(), {"chinh": 1200.0, "du_phong": None}, gui) is True
    assert len(gui.ghi) == 1 and "1 video" in gui.ghi[0] and "Relay chính hỏi việc 20 phút trước" in gui.ghi[0]
    assert canh_relay.thu_canh(conn, _HopGia(), {}, gui) is None  # đã báo ⇒ không báo lại trong 1 giờ
    assert len(gui.ghi) == 1


def test_canh_khong_bao_video_da_co_ket_qua_dang_xep_hang_render(ctx):
    """ĐỘT BIẾN: bỏ kiểm `doc_ket_qua` ⇒ báo động giả ⇒ ĐỎ."""
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 60)
    gui = _gui_ghi(True)
    assert canh_relay.thu_canh(conn, _HopGia([vids[0]]), {}, gui) is None and gui.ghi == []


def test_canh_van_bao_khi_relay_con_hoi_viec_moi_20_giay(ctx):
    """L2: relay sống, hỏi /viec liên tục (tuổi 20 s) mà video vẫn kẹt ⇒ PHẢI báo (không dựa vào "relay có hỏi không")."""
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 30)
    gui = _gui_ghi(True)
    assert canh_relay.thu_canh(conn, _HopGia(), {"chinh": 20.0, "du_phong": 15.0}, gui) is True


def test_gui_truot_khong_ghi_moc_vong_sau_bao_lai(ctx):
    """Mốc SAU khi gửi được. ĐỘT BIẾN: ghi mốc trước khi gửi ⇒ vòng sau im ⇒ ĐỎ."""
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 30)
    truot = _gui_ghi(False)
    assert canh_relay.thu_canh(conn, _HopGia(), {}, truot) is False
    duoc = _gui_ghi(True)
    assert canh_relay.thu_canh(conn, _HopGia(), {}, duoc) is True and len(duoc.ghi) == 1


def test_chua_cau_hinh_webhook_khac_gui_truot(ctx, monkeypatch):
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 30)
    monkeypatch.delenv(canh_relay.ENV_WEBHOOK, raising=False)
    assert canh_relay.gui_webhook("x") is None
    assert canh_relay.thu_canh(conn, _HopGia(), {}, canh_relay.gui_webhook) is None
    assert conn.execute("SELECT count(*) FROM tl_canh_relay").fetchone()[0] == 0  # chưa cấu hình ⇒ không ghi mốc


def test_van_ket_sau_1_gio_thi_bao_lai(ctx):
    conn, vids = ctx.conn, ctx.vids
    _cho(conn, vids[0], 30)
    gui = _gui_ghi(True)
    bay_gio = time.time()
    canh_relay.thu_canh(conn, _HopGia(), {}, gui, bay_gio=bay_gio)
    canh_relay.thu_canh(conn, _HopGia(), {}, gui, bay_gio=bay_gio + 1800)
    canh_relay.thu_canh(conn, _HopGia(), {}, gui, bay_gio=bay_gio + 3601)
    assert len(gui.ghi) == 2


def test_worker_canh_ca_khi_dia_day(tmp_path, monkeypatch):
    """Canh chạy ở đầu vòng, TRƯỚC cổng đĩa / nhường tải. ĐỘT BIẾN: dời `_canh_relay()` ra sau cổng ⇒ đĩa đầy thì câm ⇒ ĐỎ."""
    from web import thay_logo_worker as tw
    jobs = tmp_path / "jobs.db"
    jobs.touch()
    w = tw.ThayLogoWorker(tmp_path / "tl.db", jobs, tmp_path / "data", tai_ve=lambda n, d: d, tai_len=lambda p, j: "x",
                          ffmpeg="ffmpeg", nghi_giay=0.01, relay_bind="100.64.0.1:7871")
    goi = []
    monkeypatch.setattr(canh_relay, "thu_canh", lambda *a, **k: goi.append(1))
    monkeypatch.setattr(w, "dia_trong_gb", lambda: 0.0)
    goc = w.mot_luot

    def mot_luot_roi_dung():
        try:
            return goc()
        finally:
            w._dung.set()
    monkeypatch.setattr(w, "mot_luot", mot_luot_roi_dung)
    w._chay()
    assert w._lan_cuoi == "cho_dia" and goi == [1]
