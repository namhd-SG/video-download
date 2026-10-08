"""Listener RIÊNG cho 3 route relay agy (ĐP-1513, agy `video-thay-logo-relay-listener-R1b`): uvicorn thứ hai trong tiến trình
Video Desk, CHỈ bind IP Tailscale (100.64.0.0/10) hoặc 127.0.0.1 — máy dev kéo việc qua Tailscale đúng `plan.md` §3e. App chính (sau
Cloudflare Access) không có route relay nào.

Các lớp, theo thứ tự một request đi qua:
  1. bind: không có địa chỉ mặc định; địa chỉ ngoài hai dải trên ⇒ KHÔNG mở (không rơi về 0.0.0.0).
  2. IP nguồn: ngoài hai dải ⇒ 403 (lớp 2, phòng bind bị nới về sau).
  3. trần sai token: ≥ SAI_TOI_DA lần 401 trong CUA_SO_GIAY từ một IP ⇒ 429 cho IP đó trong KHOA_GIAY, kể cả token đúng.
  4. token kiểm NGAY trong middleware, TRƯỚC khi đọc một byte thân request (kongming 09/10: kiểm ở dependency thì FastAPI đã
     đọc + parse trọn thân — đo 50 MB thân, token sai ⇒ 472 MB RSS): thiếu/ngắn hơn 32 ký tự ⇒ 503; sai ⇒ 401; `hmac.compare_digest`.
     Route vẫn kiểm lại (`web/thay_logo_routes._kiem_token`).
  5. thân POST: phải có Content-Length ≤ TRAN_THAN_BYTE, không thì 413 — cũng trước khi đọc.
  6. lỗi bất kỳ ⇒ thân cố định `{"loi": <mã>}`, không stack trace; không /docs, /redoc, /openapi.json; không header Server.
  7. KHÔNG proxy headers (X-Forwarded-For bị bỏ qua: client.host là IP socket thật).
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import threading
import time
from collections import OrderedDict, deque
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tiktok_music_downloader.thay_logo.hop_thu import HopThu
from web import thay_logo_routes

log = logging.getLogger("videodl.thay_logo")
ENV_BIND = "THAY_LOGO_RELAY_BIND"
_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
_LOOPBACK = ipaddress.ip_address("127.0.0.1")
SAI_TOI_DA, CUA_SO_GIAY, KHOA_GIAY, SO_IP_THEO_DOI = 5, 60, 300, 256
TRAN_THAN_BYTE = 64 * 1024  # kết quả relay là toạ độ của ≤ 64 ảnh × ≤ 8 box — vài KB


def ip_duoc_phep(chuoi: str) -> bool:
    try:
        ip = ipaddress.ip_address(chuoi)
    except ValueError:
        return False
    return ip.version == 4 and (ip in _TAILSCALE or ip == _LOOPBACK)


def doc_bind(chuoi: str) -> tuple[str, int]:
    """`"<ipv4>:<cổng>"` ⇒ (ip, cổng). Mọi thứ khác ⇒ ValueError (người gọi KHÔNG mở listener)."""
    host, sep, cong = (chuoi or "").strip().rpartition(":")
    if not sep or not ip_duoc_phep(host) or str(ipaddress.ip_address(host)) != host:
        raise ValueError("bind phải là IPv4 Tailscale (100.64.0.0/10) hoặc 127.0.0.1, dạng ip:cổng")
    if not cong.isdigit() or not 1024 <= int(cong) <= 65535:
        raise ValueError("cổng phải 1024–65535")
    return host, int(cong)


class _TranSai:
    """Đếm 401 theo IP trong cửa sổ trượt; có trần số IP theo dõi để không thành chỗ rò bộ nhớ."""

    def __init__(self, dong_ho: Callable[[], float] = time.monotonic):
        self._sai: OrderedDict[str, deque] = OrderedDict()
        self._khoa: dict[str, float] = {}
        self._now = dong_ho
        self._lock = threading.Lock()

    def dang_khoa(self, ip: str) -> bool:
        with self._lock:
            het = self._khoa.get(ip)
            if het is not None and self._now() < het:
                return True
            self._khoa.pop(ip, None)
            return False

    def ghi_sai(self, ip: str) -> None:
        with self._lock:
            now = self._now()
            q = self._sai.setdefault(ip, deque())
            self._sai.move_to_end(ip)
            q.append(now)
            while q and now - q[0] > CUA_SO_GIAY:
                q.popleft()
            if len(q) >= SAI_TOI_DA:
                self._khoa[ip] = now + KHOA_GIAY
                q.clear()
                log.warning("thay logo relay: khoá %s %ds vì sai token liên tiếp", ip, KHOA_GIAY)
            while len(self._sai) > SO_IP_THEO_DOI:
                self._sai.popitem(last=False)
            for k in [k for k, het in self._khoa.items() if het <= now]:  # dọn khoá hết hạn
                del self._khoa[k]
            while len(self._khoa) > SO_IP_THEO_DOI:  # vẫn quá trần ⇒ bỏ khoá sắp hết hạn nhất
                del self._khoa[min(self._khoa, key=self._khoa.get)]


def dung_app(lay_hop_thu: Callable[[], HopThu], dong_ho: Callable[[], float] = time.monotonic) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    tran = _TranSai(dong_ho)
    app.state.tran_sai = tran

    @app.middleware("http")
    async def _cac_lop(request: Request, call_next):
        ip = request.client.host if request.client else ""
        if not ip_duoc_phep(ip):
            return JSONResponse({"loi": 403}, status_code=403)
        if tran.dang_khoa(ip):
            return JSONResponse({"loi": 429}, status_code=429)
        dung = os.environ.get(thay_logo_routes.ENV_TOKEN, "")
        if len(dung) < thay_logo_routes.TOKEN_TOI_THIEU:
            return JSONResponse({"loi": 503}, status_code=503)
        gui = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not gui or not hmac.compare_digest(gui.encode(), dung.encode()):
            tran.ghi_sai(ip)
            return JSONResponse({"loi": 401}, status_code=401)
        if request.method == "POST":
            cl = request.headers.get("content-length", "")
            if not cl.isdigit() or int(cl) > TRAN_THAN_BYTE:
                return JSONResponse({"loi": 413}, status_code=413)
        try:
            return await call_next(request)
        except Exception:  # không để stack trace / đường dẫn file rò ra máy kia
            log.exception("thay logo relay: lỗi xử lý")
            return JSONResponse({"loi": 500}, status_code=500)

    thay_logo_routes.dang_ky_route(app, lay_hop_thu)
    return app


class RelayServer:
    """uvicorn thứ hai chạy trong luồng nền; start/stop cùng worker thay logo."""

    def __init__(self, bind: str, lay_hop_thu: Callable[[], HopThu]):
        import uvicorn

        host, cong = doc_bind(bind)
        # log_config=None + log_level=None: KHÔNG dựng lại cấu hình log — logger `uvicorn.*` là TOÀN TIẾN TRÌNH; Config mặc định
        # đã tắt access log + hạ level của uvicorn CHÍNH Video Desk (kongming đo 09/10). Dòng relay đi chung `uvicorn.access`
        # (đã có bộ lọc che token của app chính) để còn vết audit. proxy_headers=False: X-Forwarded-For không đổi được IP nguồn.
        self.server = uvicorn.Server(uvicorn.Config(dung_app(lay_hop_thu), host=host, port=cong, log_config=None, log_level=None,
                                                    access_log=True, proxy_headers=False, server_header=False,
                                                    date_header=False))
        self.thread = threading.Thread(target=self.server.run, name="thay-logo-relay", daemon=True)

    def start(self, cho_giay: float = 5.0) -> bool:
        self.thread.start()
        het = time.monotonic() + cho_giay
        while time.monotonic() < het:
            if self.server.started:
                return True
            if not self.thread.is_alive():  # bind hỏng (cổng bận…) — uvicorn tự thoát
                break
            time.sleep(0.02)
        log.warning("thay logo relay: listener không khởi động được — job sẽ đứng chờ agy")
        self.stop()  # khởi động chậm hơn hạn ⇒ vẫn phải tắt, kẻo listener mồ côi mở cổng mà worker tưởng đã tắt
        return False

    def stop(self, timeout: float = 5.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=timeout)
