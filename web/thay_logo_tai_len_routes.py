"""Route nguồn "Tải từ máy" (đợt 4): phiên resumable thẳng Google Drive. Đăng ký ở KHỐI CUỐI `thay_logo_routes.dang_ky_route_member`.

Ba route, cùng cờ `TL_TAI_TU_MAY` (TẮT ⇒ 404 như route không tồn tại; FE dùng `GET /tai-len/bat` để ẩn tab):
  GET  /api/thay-logo/tai-len/bat             200 {} khi bật
  POST /api/thay-logo/tai-len/phien           201 {token, url_phien} — URL phiên trả MỘT lần, không lưu, không log
  POST /api/thay-logo/tai-len/{token}/xong    200 {file_id} — đối chiếu file trên Drive rồi chốt phiên
Logic (DB, Google, dọn) nằm ở `thay_logo/tai_len_phien.py`; file này chỉ xác thực, đổi lỗi nghiệp vụ thành mã HTTP.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky, tai_len_phien

log = logging.getLogger(__name__)

_MAU_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


class KhaiPhien(BaseModel):
    """Kiểu lỏng (`Any`) có chủ đích: kiểm tay để sai kiểu/giá trị đều trả 400 cùng một khuôn (hợp đồng API), không 422."""
    ten: Any = None
    size: Any = None
    mime: Any = None


class ChotPhien(BaseModel):
    file_id: Any = None


def _http(e: tai_len_phien.LoiPhien) -> HTTPException:
    return HTTPException(e.ma, str(e))


def dang_ky(app: FastAPI, *, lay_log_db: Callable[[], object], require_user, lay_worker: Callable[[], object | None],
            lay_tran_cho: Callable[[], int], mau_file_id: re.Pattern, lay_session: Callable[[object], object] | None = None) -> None:
    """`lay_tran_cho()` đọc LÚC GỌI trần chờ chung của người dùng (`thay_logo_routes.TRAN_CHO_MOI_NGUOI`). `lay_session(drive)` trả session HTTP
    có `post(...)` (mặc định: `AuthorizedSession` của service account; test tiêm bản giả)."""
    tao_session = lay_session or tai_len_phien.session_that
    if tai_len_phien.dang_bat():  # cờ BẬT mà `THAY_LOGO_ORIGIN` thiếu/sai khuôn ⇒ báo ngay lúc khởi động (route vẫn 503, không đoán)
        try:
            tai_len_phien.origin_cau_hinh()
        except tai_len_phien.LoiPhien:
            pass  # `origin_cau_hinh` đã log lỗi

    def _cong() -> None:
        if not tai_len_phien.dang_bat():
            raise HTTPException(404, "Not Found")

    def _mo():
        conn = nhat_ky.mo(lay_log_db())
        hang_doi.khoi_tao(conn)
        tai_len_phien.khoi_tao(conn)
        return conn

    def _drive():
        w = lay_worker()
        if w is None:
            raise HTTPException(409, "Tính năng thay logo đang tắt trên máy chủ.")
        if getattr(w, "ly_do_khong_nhan", None):  # cùng cổng với POST /jobs; chi tiết thư mục chỉ admin thấy
            raise HTTPException(409, "Tính năng thay logo tạm tắt do cấu hình máy chủ — báo quản trị.")
        drive = getattr(w, "drive_tl", None)
        if drive is None or not drive.dang_cau_hinh():
            raise HTTPException(503, "Máy chủ chưa nối được Google Drive — báo quản trị.")
        return drive

    @app.get("/api/thay-logo/tai-len/bat")
    def tai_len_bat(email: str = Depends(require_user)) -> dict:
        _cong()
        return {}

    @app.post("/api/thay-logo/tai-len/phien", status_code=201)
    def tai_len_phien_moi(body: KhaiPhien, email: str = Depends(require_user), origin: str | None = Header(default=None)) -> dict:
        _cong()
        try:
            origin_chuan = tai_len_phien.origin_cau_hinh()  # thiếu/sai khuôn ⇒ 503
            tai_len_phien.kiem_origin_request(origin_chuan, origin)  # có mà khác ⇒ 403; vắng ⇒ qua
        except tai_len_phien.LoiPhien as e:
            raise _http(e) from None
        drive = _drive()
        thu_muc_ra = os.environ.get(tai_len_phien.ENV_THU_MUC_RA, "")
        if not thu_muc_ra:
            raise HTTPException(503, "Máy chủ chưa cấu hình thư mục Drive — báo quản trị.")
        conn = _mo()
        try:
            return tai_len_phien.mo_phien(conn, drive, tao_session, email, body.ten, body.size, body.mime, thu_muc_ra, origin_chuan,
                                          lay_tran_cho())
        except tai_len_phien.LoiPhien as e:
            raise _http(e) from None
        finally:
            conn.close()

    @app.post("/api/thay-logo/tai-len/{token}/xong")
    def tai_len_xong(body: ChotPhien, token: str = PathParam(max_length=200), email: str = Depends(require_user)) -> dict:
        _cong()
        if not _MAU_TOKEN.match(token):
            raise HTTPException(404, "Không có phiên tải này.")
        if not isinstance(body.file_id, str) or not mau_file_id.match(body.file_id):
            raise HTTPException(400, "mã file Drive sai khuôn")
        drive = _drive()
        conn = _mo()
        try:
            return {"file_id": tai_len_phien.xac_nhan_xong(conn, drive, email, token, body.file_id)}
        except tai_len_phien.LoiPhien as e:
            raise _http(e) from None
        finally:
            conn.close()
