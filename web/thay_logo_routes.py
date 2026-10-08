"""Route hộp thư relay agy cho job "Thay logo" (plan.md §3e; ĐP-1495: route TRỌN trong file này, ráp vào `app.py` bằng
`dang_ky_route(app, ...)` lúc tích hợp).

Máy dev KÉO việc qua ba route, xác thực bằng token RIÊNG của relay (biến môi trường `THAY_LOGO_RELAY_TOKEN`, KHÔNG có giá trị mặc
định). Thiếu token ⇒ mọi route trả 503 (đóng, không mở). Route này không dùng phiên đăng nhập member và không cấp quyền gì khác.
"""
from __future__ import annotations

import hmac
import os
import re as _re
import sqlite3 as _sqlite3
from typing import Callable

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky
from tiktok_music_downloader.thay_logo.hop_thu import HopThu, LoiHopThu

ENV_TOKEN = "THAY_LOGO_RELAY_TOKEN"
TIEN_TO = "/api/thay-logo/relay"


TOKEN_TOI_THIEU = 32


def _kiem_token(authorization: str | None = Header(default=None)) -> None:
    dung = os.environ.get(ENV_TOKEN, "")  # đọc LÚC GỌI: đổi/xoá token có hiệu lực không cần khởi động lại
    if len(dung) < TOKEN_TOI_THIEU:  # thiếu HOẶC quá ngắn ⇒ coi như chưa cấu hình: đóng, không mở với token yếu
        raise HTTPException(503, "relay chưa cấu hình token")
    gui = (authorization or "").removeprefix("Bearer ").strip()
    if not gui or not hmac.compare_digest(gui.encode(), dung.encode()):
        raise HTTPException(401, "sai token relay")


def _http(loi: LoiHopThu) -> HTTPException:
    return HTTPException(loi.ma, str(loi))


def dang_ky_route(app: FastAPI, lay_hop_thu: Callable[[], HopThu]) -> None:
    """`lay_hop_thu` trả hộp thư LÚC GỌI (test và app có thể đổi thư mục dữ liệu)."""

    @app.get(f"{TIEN_TO}/viec", dependencies=[Depends(_kiem_token)])
    def relay_viec() -> dict:
        return {"viec": lay_hop_thu().viec_cho()}

    @app.get(f"{TIEN_TO}/anh/{{anh}}", dependencies=[Depends(_kiem_token)])
    def relay_anh(anh: str) -> Response:
        try:
            du_lieu = lay_hop_thu().doc_anh(anh)
        except LoiHopThu as e:
            raise _http(e) from None
        if du_lieu is None:
            raise HTTPException(404, "không có ảnh")
        return Response(du_lieu, media_type="image/jpeg")

    @app.post(f"{TIEN_TO}/ket-qua/{{job_id}}", status_code=204, response_model=None, dependencies=[Depends(_kiem_token)])
    def relay_ket_qua(job_id: int, du_lieu=Body(...)) -> None:
        try:
            lay_hop_thu().nop_ket_qua(job_id, du_lieu)
        except LoiHopThu as e:
            raise _http(e) from None


# ============================================================================ route cho MEMBER (trang Thay logo)
# Xác thực bằng `require_user` có sẵn (JWT Cloudflare Access, cùng nguồn với `jobs.nguoi_tao`). Mỗi video chỉ NGƯỜI TẠO job hoặc admin
# được xem / đánh giá (USER §0: "người tạo job tự duyệt").

TRAN_VIDEO_MOT_JOB = 50
_DRIVE_ID = _re.compile(r"^[A-Za-z0-9_-]{10,120}$")


class TaoJobThayLogo(BaseModel):
    drive_file_ids: list[str] = Field(min_length=1, max_length=TRAN_VIDEO_MOT_JOB)
    ghi_chu: str = Field(default="", max_length=500)


class DanhGia(BaseModel):
    ket_qua: str
    loai_loi: str | None = None
    ghi_chu: str = Field(default="", max_length=2000)


_SQL_DANH_SACH = """
SELECT v.id, v.job_id, v.nguon, v.trang_thai, v.cho_agy_tu, v.cap_nhat_luc, v.loi_text, v.drive_file_id_ra, j.nguoi_tao,
       t.giay_xu_ly, t.man_ket_agy,
       (SELECT max(net_la_pho_bien) FROM tl_vet x WHERE x.video_id = v.video_log_id) AS can_soi_ky,
       (SELECT max(pct_render) FROM tl_vet x WHERE x.video_id = v.video_log_id) AS pct_render,
       (SELECT count(*) FROM tl_box_moi b WHERE b.video_id = v.video_log_id) AS so_box,
       (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) AS danh_gia,
       t.duong_dan_sheet IS NOT NULL AS co_sheet
FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id LEFT JOIN tl_video t ON t.id = v.video_log_id
"""


def dang_ky_route_member(app: FastAPI, lay_log_db: Callable[[], object], require_user, la_admin,
                         lay_worker: Callable[[], object | None]) -> None:
    """`lay_log_db` trả đường dẫn `thay_logo_log.db` LÚC GỌI; mỗi request mở kết nối mới và tự đóng. `lay_worker` trả None khi
    tính năng TẮT ⇒ không nhận lượt mới (409), vẫn xem/đánh giá được kết quả cũ."""

    def _mo() -> _sqlite3.Connection:
        conn = nhat_ky.mo(lay_log_db())
        hang_doi.khoi_tao(conn)
        return conn

    def _video_cua(conn, vid: int, email: str):
        r = conn.execute(_SQL_DANH_SACH + " WHERE v.id = ?", (vid,)).fetchone()
        if r is None:
            raise HTTPException(404, "không có video này")
        if r["nguoi_tao"] != email and not la_admin(email):
            raise HTTPException(403, "chỉ người tạo lượt hoặc quản trị")
        return r

    @app.post("/api/thay-logo/jobs", status_code=201)
    def tao_job(body: TaoJobThayLogo, email: str = Depends(require_user)) -> dict:
        if lay_worker() is None:
            raise HTTPException(409, "Tính năng thay logo đang tắt trên máy chủ.")
        if not all(_DRIVE_ID.match(f) for f in body.drive_file_ids):
            raise HTTPException(400, "mã file Drive sai khuôn")
        conn = _mo()
        try:
            jid = hang_doi.tao_job(conn, email, [{"kieu": "drive", "file_id": f} for f in dict.fromkeys(body.drive_file_ids)],
                                   body.ghi_chu)
        finally:
            conn.close()
        return {"job_id": jid}

    @app.get("/api/thay-logo/videos")
    def danh_sach(email: str = Depends(require_user)) -> dict:
        conn = _mo()
        try:
            if la_admin(email):
                rows = conn.execute(_SQL_DANH_SACH + " ORDER BY v.id DESC LIMIT 300").fetchall()
            else:
                rows = conn.execute(_SQL_DANH_SACH + " WHERE j.nguoi_tao = ? ORDER BY v.id DESC LIMIT 300", (email,)).fetchall()
        finally:
            conn.close()
        return {"videos": [{k: r[k] for k in r.keys()} for r in rows]}

    @app.post("/api/thay-logo/videos/{vid}/danh-gia", status_code=204, response_model=None)
    def danh_gia(vid: int, body: DanhGia, email: str = Depends(require_user)) -> None:
        conn = _mo()
        try:
            r = _video_cua(conn, vid, email)
            if r["trang_thai"] != "xong":
                raise HTTPException(409, "chỉ đánh giá video đã thay xong")
            log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (vid,)).fetchone()[0]
            try:
                nhat_ky.ghi_danh_gia(conn, log_id, email, body.ket_qua, body.loai_loi, body.ghi_chu)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
        finally:
            conn.close()

    @app.get("/api/thay-logo/videos/{vid}/sheet.jpg")
    def anh_soi(vid: int, email: str = Depends(require_user)) -> Response:
        conn = _mo()
        try:
            _video_cua(conn, vid, email)
            p = conn.execute("SELECT t.duong_dan_sheet FROM tl_job_video v JOIN tl_video t ON t.id = v.video_log_id "
                             "WHERE v.id=?", (vid,)).fetchone()
        finally:
            conn.close()
        if not p or not p[0] or not os.path.isfile(p[0]):
            raise HTTPException(404, "chưa có ảnh soi")
        with open(p[0], "rb") as f:
            return Response(f.read(), media_type="image/jpeg")

    @app.get("/api/thay-logo/admin/worker")
    def trang_thai_worker(email: str = Depends(require_user)) -> dict:
        if not la_admin(email):
            raise HTTPException(403, "chỉ quản trị")
        w = lay_worker()
        return w.trang_thai() if w is not None else {"song": False, "luot_cuoi": "tinh_nang_tat"}
