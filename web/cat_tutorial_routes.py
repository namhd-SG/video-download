"""Trang "Cắt tutorial": chuyển tiếp `/cat-tutorial/*` tới tool của chị Linh (ui_server.py, chế độ web) chạy ở 127.0.0.1.

Bật bằng `CAT_TUTORIAL_BAT=1` (tắt ⇒ 404 JSON); dịch vụ đích `CAT_TUTORIAL_UPSTREAM` (mặc định http://127.0.0.1:8790).
Route LUÔN được đăng ký, cờ đọc lúc gọi (như `TL_TAI_TU_MAY`): lưới "mọi route đòi require_user" trong tests thấy nó cả
khi cờ tắt.

Ranh giới an toàn:
  - ui_server KHÔNG có đăng nhập; cửa duy nhất là `require_user` ở đây (Cloudflare Access JWT).
  - Khu của mỗi người = cookie `ct_ws` do PROXY đặt từ email: header Cookie của trình duyệt KHÔNG BAO GIỜ đi tới
    ui_server, Set-Cookie của ui_server KHÔNG BAO GIỜ về trình duyệt ⇒ tự gửi `ct_ws=<của người khác>` vô tác dụng.
  - Chỉ GET/POST trên danh sách đường của ui_server; `api/open|pick|reveal` bị chặn (404).
  - Lỗi của proxy dưới `/cat-tutorial/*` (401/404/503…) trả `{"error", "videos": []}`: vòng `poll()` của iframe đọc
    `j.error` để báo và vẫn còn `S.videos` (index.html:338, :887) — dạng `{"detail"}` mặc định không có hai khoá đó.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from web.cat_tutorial_duong_dan import DUONG_GET, DUONG_POST, TIEN_TO, viet_lai_index

log = logging.getLogger("videodl.cat_tutorial")

ENV_BAT = "CAT_TUTORIAL_BAT"
ENV_UPSTREAM = "CAT_TUTORIAL_UPSTREAM"
# Bí mật ký khoá khu (chuỗi ngẫu nhiên, giữ ngoài git như các env khác của service). Thiếu ⇒ không phục vụ.
ENV_KHOA_KHU = "CAT_TUTORIAL_KHOA_KHU"
UPSTREAM_MAC_DINH = "http://127.0.0.1:8790"

DUONG_TRANG = frozenset({"", "index.html"})
# Byte đã nén sẵn / file lớn: stream thẳng (không đệm vào RAM), giữ Content-Length + Range, KHÔNG gzip.
DUONG_MEDIA = frozenset({"video", "output", "preview", "sprite", "api/zip"})
# ffmpeg dựng bản xem trước 720p / cắt khung quanh điểm cắt / gói zip: có thể mất vài phút.
DUONG_CHAM = frozenset({"preview", "api/edge", "api/zip"})
# ui_server.upload_chunk từ chối mảnh > 64MB; trình duyệt gửi mảnh 32MB (index.html:807). Trần này chặn đọc body khổng lồ
# vào RAM trước khi ui_server kịp từ chối.
TRAN_THAN_BYTE = 64 * 2**20
# Mỗi upload đệm trọn mảnh vào RAM (tới ~2×64MB) ⇒ giới hạn số mảnh đang đệm cùng lúc trên cả tiến trình.
TOI_DA_UPLOAD_SONG_SONG = 2

HAN_THUONG = httpx.Timeout(60.0, connect=5.0)
HAN_DAI = httpx.Timeout(600.0, connect=5.0)

# Danh sách TRẮNG theo hai chiều: header nào không có tên ở đây thì không đi qua (Cookie, Set-Cookie, JWT Access…).
HEADER_GUI_DI = ("range", "if-range", "content-type", "accept")
HEADER_TRA_VE = ("content-type", "content-range", "accept-ranges", "content-disposition", "cache-control",
                 "last-modified", "etag")

CAU_CHUA_DANG_NHAP = "Phiên đăng nhập đã hết hạn — tải lại trang để đăng nhập lại."
CAU_TINH_NANG_TAT = "Tính năng Cắt tutorial đang tắt trên máy chủ."
CAU_KHONG_CO_DUONG = "Không có chức năng này trong Cắt tutorial bản web."
CAU_DICH_VU_TAT = "Công cụ Cắt tutorial đang tắt hoặc đang khởi động lại — đợi 1–2 phút rồi tải lại trang."
CAU_QUA_LAU = "Công cụ Cắt tutorial trả lời quá lâu — thử lại sau ít phút."
CAU_CHUA_CAU_HINH_KHOA = "Cắt tutorial chưa được cấu hình xong trên máy chủ (thiếu khoá khu) — báo quản trị."
CAU_KHAC_NGUON = "Yêu cầu không đến từ trang Video Desk — đã chặn."
CAU_THAN_QUA_LON = "Mảnh tải lên quá lớn (tối đa 64MB mỗi lần gửi)."


def dang_bat() -> bool:
    return os.environ.get(ENV_BAT) == "1"


def upstream() -> str:
    return (os.environ.get(ENV_UPSTREAM) or UPSTREAM_MAC_DINH).rstrip("/")


def khoa_khu() -> str | None:
    return os.environ.get(ENV_KHOA_KHU) or None


def cookie_khu(email: str, khoa: str) -> str:
    """Cookie gửi ui_server: `ct_ws` = 32 hex đầu của HMAC-SHA256(khoa, email chữ thường) — khớp `_WS_RE` (ui_server.py:52).
    Cố định theo người ⇒ đổi máy / xoá cookie trình duyệt vẫn về đúng khu của mình. Có khoá bí mật vì ui_server không
    đăng nhập và nghe 127.0.0.1 trên máy dùng chung: sha256(email) trần thì ai chạy được lệnh trên máy và biết email
    là tự tính ra cookie, đọc/xoá khu người khác mà không qua proxy."""
    mac = hmac.new(khoa.encode("utf-8"), email.strip().lower().encode("utf-8"), hashlib.sha256)
    return "ct_ws=" + mac.hexdigest()[:32]


def _loi(ma: int, cau: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": cau, "videos": []}, status_code=ma, headers=headers)


def _thuoc_cat_tutorial(path: str) -> bool:
    return path.startswith(TIEN_TO + "/")


def la_media(path: str) -> bool:
    return _thuoc_cat_tutorial(path) and path[len(TIEN_TO) + 1:] in DUONG_MEDIA


class GZipTruMedia(GZipMiddleware):
    """GZip của app, trừ video/ảnh/zip của Cắt tutorial — theo ĐƯỜNG, không dựa vào Content-Type ui_server gửi.
    Nén lại byte đã nén chỉ tốn CPU máy chủ (dùng chung với thay logo, ollama) và bỏ mất Content-Length."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and la_media(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


async def _xu_ly_loi_http(request: Request, exc: StarletteHTTPException):
    """Chỉ đổi DẠNG lỗi dưới `/cat-tutorial/`; đường khác giữ nguyên `{"detail"}` của FastAPI (hợp đồng FE cũ)."""
    if not _thuoc_cat_tutorial(request.url.path):
        return await http_exception_handler(request, exc)
    if exc.status_code == 401:
        cau = CAU_CHUA_DANG_NHAP
    else:
        cau = exc.detail if isinstance(exc.detail, str) and exc.detail else "Không thực hiện được yêu cầu."
    return _loi(exc.status_code, cau, getattr(exc, "headers", None))


async def _doc_than(request: Request) -> bytes:
    """Đọc ĐỦ body rồi mới gửi: ui_server đọc độ dài từ `Content-Length` (ui_server.py:733) — gửi chunked ⇒ "File rỗng"."""
    khai = request.headers.get("content-length", "")
    if khai.isdigit() and int(khai) > TRAN_THAN_BYTE:
        raise HTTPException(413, CAU_THAN_QUA_LON)
    than = bytearray()
    async for manh in request.stream():
        than += manh
        if len(than) > TRAN_THAN_BYTE:
            raise HTTPException(413, CAU_THAN_QUA_LON)
    return bytes(than)


async def _chay_tung_manh(r: httpx.Response):
    try:
        async for manh in r.aiter_bytes():
            yield manh
    finally:
        await r.aclose()


def dang_ky(app: FastAPI, *, require_user: Callable, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """`transport`: test tiêm `httpx.MockTransport` làm ui_server giả; None ⇒ mạng thật tới `upstream()`."""
    app.add_exception_handler(StarletteHTTPException, _xu_ly_loi_http)
    cho_upload = asyncio.Semaphore(TOI_DA_UPLOAD_SONG_SONG)
    khach: list[httpx.AsyncClient] = []  # một client cho cả tiến trình, dựng lúc gọi đầu (không tốn gì khi cờ tắt)

    def _khach() -> httpx.AsyncClient:
        if not khach:
            # trust_env=False: proxy hệ thống (HTTP_PROXY…) không được chen vào đường 127.0.0.1.
            khach.append(httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False))
        return khach[0]

    @app.api_route(TIEN_TO + "/{path:path}", methods=["GET", "POST"], include_in_schema=False)
    async def cat_tutorial_chuyen_tiep(path: str, request: Request, email: str = Depends(require_user)) -> Response:
        if not dang_bat():
            raise HTTPException(404, CAU_TINH_NANG_TAT)
        khoa = khoa_khu()
        if not khoa:  # "đã bật mà chưa cấu hình" khác "đang tắt": báo rõ, không rơi về khoá mặc định đoán được
            return _loi(503, CAU_CHUA_CAU_HINH_KHOA)
        if path not in (DUONG_GET if request.method == "GET" else DUONG_POST):
            raise HTTPException(404, CAU_KHONG_CO_DUONG)
        # Chống trang lạ gửi POST hộ (xoá/xuất video) bằng cookie Access của nạn nhân: trình duyệt luôn gửi
        # `Sec-Fetch-Site`; iframe của Video Desk là "same-origin". Vắng header (client không phải trình duyệt) ⇒ qua.
        if request.method == "POST" and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            raise HTTPException(403, CAU_KHAC_NGUON)
        la_trang = path in DUONG_TRANG
        gui = {k: v for k in HEADER_GUI_DI if (v := request.headers.get(k)) is not None
               and not (la_trang and k in ("range", "if-range"))}  # trang gốc phải nhận TRỌN để viết lại
        gui["cookie"] = cookie_khu(email, khoa)  # THAY hẳn — không ghép với Cookie của trình duyệt
        than = None
        if request.method == "POST":
            async with cho_upload:
                than = await _doc_than(request)
        url = upstream() + "/" + ("" if la_trang else path) + (f"?{request.url.query}" if request.url.query else "")
        k = _khach()
        yeu_cau = k.build_request(request.method, url, headers=gui, content=than,
                                  timeout=HAN_DAI if path in DUONG_CHAM else HAN_THUONG)
        try:
            r = await k.send(yeu_cau, stream=True)
        except httpx.TimeoutException:
            return _loi(504, CAU_QUA_LAU)
        except httpx.TransportError as exc:
            log.warning("Cắt tutorial: không gọi được %s (%s)", upstream(), type(exc).__name__)
            return _loi(503, CAU_DICH_VU_TAT)
        tra = {h: v for h in HEADER_TRA_VE if (v := r.headers.get(h)) is not None}
        if path in DUONG_MEDIA:
            # `aiter_bytes` giải nén nếu đích có gửi Content-Encoding (ui_server không gửi) ⇒ khi đó độ dài cũ sai, bỏ đi.
            if "content-length" in r.headers and "content-encoding" not in r.headers:
                tra["content-length"] = r.headers["content-length"]
            return StreamingResponse(_chay_tung_manh(r), status_code=r.status_code, headers=tra,
                                     background=BackgroundTask(r.aclose))
        try:
            noi_dung = await r.aread()
        except httpx.TimeoutException:
            return _loi(504, CAU_QUA_LAU)
        except httpx.TransportError:
            return _loi(503, CAU_DICH_VU_TAT)
        finally:
            await r.aclose()
        if la_trang and r.status_code == 200:
            noi_dung = viet_lai_index(noi_dung.decode("utf-8")).encode("utf-8")
        return Response(noi_dung, status_code=r.status_code, headers=tra)  # Content-Length tính lại từ nội dung mới
