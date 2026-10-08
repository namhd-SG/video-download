"""Listener relay riêng (ĐP-1513): bind chỉ Tailscale/loopback (hai chiều), IP nguồn, trần sai token, không rò lỗi, tắt cùng worker."""
import asyncio
import json
import socket
import urllib.error
import urllib.request

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from tiktok_music_downloader.thay_logo.hop_thu import HopThu  # noqa: E402
from web import thay_logo_relay_server as rs  # noqa: E402
from web import thay_logo_routes  # noqa: E402

TOKEN = "t" * 40
H = {"Authorization": f"Bearer {TOKEN}"}
R = thay_logo_routes.TIEN_TO


@pytest.mark.parametrize("bind", ["100.64.0.1:9000", "100.127.255.255:65535", "100.109.39.103:7999", "127.0.0.1:1024"])
def test_bind_hop_le(bind):
    assert rs.doc_bind(bind)[1] == int(bind.rsplit(":", 1)[1])


@pytest.mark.parametrize("bind", ["", "0.0.0.0:9000", ":::9000", "[::]:9000", "::1:9000", "::ffff:100.64.0.1:9000",
                                  "localhost:9000", "100.128.0.1:9000", "100.63.255.255:9000", "10.0.0.1:9000",
                                  "192.168.1.5:9000", "100.064.0.1:9000", "100.64.0.1", "100.64.0.1:80", "100.64.0.1:70000",
                                  "127.0.0.2:9000", "100.64.0.1:9000x"])
def test_bind_bi_tu_choi(bind):
    with pytest.raises(ValueError):
        rs.doc_bind(bind)


def _goi_asgi(app, ip, path, headers=None):
    """Gọi ASGI trực tiếp để giả IP nguồn (không giả được qua socket thật)."""
    out = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        if m["type"] == "http.response.start":
            out["status"] = m["status"]
            out["headers"] = {k.decode().lower(): v.decode() for k, v in m["headers"]}
        elif m["type"] == "http.response.body":
            out["body"] = out.get("body", b"") + m.get("body", b"")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()], "client": (ip, 5555),
             "server": ("127.0.0.1", 9000)}
    asyncio.run(app(scope, receive, send))
    return out


@pytest.fixture
def app_relay(tmp_path, monkeypatch):
    monkeypatch.setenv(thay_logo_routes.ENV_TOKEN, TOKEN)
    gio = {"t": 1000.0}
    hop = HopThu(tmp_path / "hop")
    app = rs.dung_app(lambda: hop, dong_ho=lambda: gio["t"])
    return app, gio, hop


@pytest.mark.parametrize("ip,ma", [("100.100.1.2", 200), ("127.0.0.1", 200), ("8.8.8.8", 403), ("192.168.1.2", 403),
                                   ("::ffff:100.64.0.1", 403), ("", 403)])
def test_ip_nguon_ngoai_dai_bi_403(app_relay, ip, ma):
    app, _, _ = app_relay
    assert _goi_asgi(app, ip, R + "/viec", H)["status"] == ma


def test_tran_sai_token_khoa_ca_token_dung_roi_tu_mo(app_relay):
    app, gio, _ = app_relay
    for _ in range(rs.SAI_TOI_DA):
        assert _goi_asgi(app, "100.100.1.2", R + "/viec", {"Authorization": "Bearer sai"})["status"] == 401
    assert _goi_asgi(app, "100.100.1.2", R + "/viec", H)["status"] == 429
    assert _goi_asgi(app, "100.100.1.3", R + "/viec", H)["status"] == 200  # IP khác không bị vạ lây
    gio["t"] += rs.KHOA_GIAY + 1
    assert _goi_asgi(app, "100.100.1.2", R + "/viec", H)["status"] == 200


def test_sai_rai_rac_ngoai_cua_so_khong_khoa(app_relay):
    app, gio, _ = app_relay
    for _ in range(rs.SAI_TOI_DA * 2):
        _goi_asgi(app, "100.100.1.2", R + "/viec", {"Authorization": "Bearer sai"})
        gio["t"] += rs.CUA_SO_GIAY / (rs.SAI_TOI_DA - 1) + 1
    assert _goi_asgi(app, "100.100.1.2", R + "/viec", H)["status"] == 200


def test_bo_dem_co_tran_so_ip(app_relay):
    app, _, _ = app_relay
    for i in range(rs.SO_IP_THEO_DOI + 50):
        _goi_asgi(app, f"100.100.{i // 250}.{i % 250 + 1}", R + "/viec", {"Authorization": "Bearer sai"})
    assert len(app.state.tran_sai._sai) <= rs.SO_IP_THEO_DOI


def test_khong_docs_va_loi_khong_ro_chi_tiet(app_relay, monkeypatch):
    app, _, hop = app_relay
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert _goi_asgi(app, "127.0.0.1", p)["status"] == 404

    def no(*a):
        raise RuntimeError("/Users/nobi_auto/Projects/video-download/web/data/bi-mat")
    monkeypatch.setattr(hop, "viec_cho", no)
    r = _goi_asgi(app, "127.0.0.1", R + "/viec", H)
    assert r["status"] == 500 and json.loads(r["body"]) == {"loi": 500}


def test_vuot_thu_muc_hop_thu_bi_chan(app_relay):
    app, _, _ = app_relay
    for p in ("/anh/..%2F..%2Fjobs.db", "/anh/" + "../" * 3 + "x", "/anh/*", "/anh/" + "a" * 31 + "*"):
        assert _goi_asgi(app, "127.0.0.1", R + p, H)["status"] in (400, 404)


def _cong_trong():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_listener_that_khong_header_server_va_tat_cung_worker(tmp_path, monkeypatch):
    monkeypatch.setenv(thay_logo_routes.ENV_TOKEN, TOKEN)
    cong = _cong_trong()
    srv = rs.RelayServer(f"127.0.0.1:{cong}", lambda: HopThu(tmp_path / "hop"))
    assert srv.start()
    req = urllib.request.Request(f"http://127.0.0.1:{cong}{R}/viec", headers=H)
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200 and "server" not in {k.lower() for k in r.headers.keys()}
    srv.stop()
    assert not srv.thread.is_alive()
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(req, timeout=2)


def test_worker_bind_sai_thi_khong_mo_relay_nhung_worker_van_chay(tmp_path):
    pytest.importorskip("cv2")
    from web.thay_logo_worker import ThayLogoWorker
    w = ThayLogoWorker(tmp_path / "log.db", tmp_path / "jobs.db", tmp_path / "data", tai_ve=None, tai_len=None, ffmpeg="ffmpeg",
                       nghi_giay=0.05, relay_bind="0.0.0.0:9000")
    w.start()
    try:
        assert w.relay is None and w.trang_thai()["song"] and not w.trang_thai()["relay_mo"]
    finally:
        w.stop(timeout=5)
