"""Bốn route giải captcha trong popup (hợp đồng đầy đủ: docstring `web/giai_captcha.py`).

Đăng ký bằng `dang_ky_route(app, ...)` — nhận `lay_db` (hàm trả đường dẫn DB TẠI LÚC GỌI, vì
test đổi `web.app.DB_PATH`), `la_admin`, `require_user`; không import `web.app` (vòng import).

Quyền: cờ → job tồn tại (404) → chủ job TRƯỚC `la_admin` → 403 → trạng thái (409, thông điệp riêng).
Cờ TẮT ⇒ 409 ngay ở dòng đầu, KHÔNG đụng DB.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, StrictInt
from sse_starlette.sse import EventSourceResponse

from web import giai_captcha as gc
from web import models, profile_theo_job
from web import models_giai_captcha as mgc

log = logging.getLogger("videodl.web")

THONG_DIEP_TAT = "Tính năng giải captcha trong popup đang tắt."
SSE_NHIP_GIAY = 0.05          # nhịp kiểm đổi của luồng SSE khung
SSE_KIEM_QUYEN_GIAY = 1.0     # kiểm lại chủ job/admin + trạng thái job
SSE_NHAC_LAI_GIAY = 5.0       # nhắc lại `trang_thai` (chỉnh đồng hồ phía popup)
SSE_PING_GIAY = 15

_THONG_DIEP_SAI_TRANG_THAI = {
    "cho_xac_minh": "Lượt này đang chờ người giải xác minh.",
    "cho_giai": "Lượt này đang chờ tới lượt mở trang giải xác minh.",
    "dang_mo": "Máy chủ đang mở trang để giải xác minh.",
    "dang_giai": "Lượt này đang được giải xác minh.",
    "running": "Lượt này đang tải video, không có xác minh nào cần giải.",
    "pending": "Lượt này chưa chạy nên chưa có xác minh nào để giải.",
}


class ChuotBody(BaseModel):
    token: str
    ky: StrictInt | None = None     # bắt buộc (thiếu ⇒ 400 "popup cũ"); Optional để báo lỗi rõ thay vì 422
    seq: StrictInt
    khung_w: float
    khung_seq: StrictInt | None = None
    su_kien: list[dict]


class LenhBody(BaseModel):
    token: str
    lenh: str
    ky: StrictInt | None = None   # bắt buộc với `huy_gesture`: kỳ popup đang biết lúc gửi
    den_seq: int | None = None    # giao thức cũ — nhận nhưng bỏ qua (popup vẫn gửi để nói được với máy chủ cũ)


_THONG_DIEP_POPUP_CU = "Popup phiên bản cũ — tải lại trang rồi mở lại lượt giải."
# Thiếu `ky` = JS popup CŨ (trước giao thức kỳ) còn sống trong một tab mở từ trước lần deploy (popup là hộp thoại trong
# trang chính, JS nạp một lần mỗi lần tải trang). Trả 401 chứ không 400: JS cũ hiểu 401 là mất phiên và hiện nút "Tải lại
# trang" (400 thì nó im lặng bỏ cú kéo, mọi lần kéo chết tới khi người tự tải lại). Đánh đổi: chữ nói "phiên đăng nhập đã
# hết" dù phiên còn — nhưng tải lại đúng là cách chữa. Popup mới luôn gửi `ky` nên không bao giờ gặp mã này.
_MA_POPUP_CU = 401


def _http_tu_loi(loi: "gc.LoiGiai") -> HTTPException:
    """`LoiKyCu` ⇒ 409 kèm `{"ma": "ky_cu", "ky": <kỳ hiện tại>}` để popup biết đồng bộ lại; lỗi khác ⇒ chuỗi."""
    if isinstance(loi, gc.LoiKyCu):
        return HTTPException(status_code=409, detail={"ma": "ky_cu", "ky": loi.ky, "thong_diep": loi.thong_diep})
    return HTTPException(status_code=loi.ma, detail=loi.thong_diep)


def _thong_diep_trang_thai(trang_thai: str, can: str) -> str:
    goc = _THONG_DIEP_SAI_TRANG_THAI.get(trang_thai)
    if trang_thai in ("done", "failed", "interrupted", "cancelled"):
        goc = "Lượt này đã kết thúc."
    return f"{goc or 'Lượt này không ở bước phù hợp.'} ({can})"


def dang_ky_route(app: FastAPI, *, lay_db: Callable[[], Path],
                  la_admin: Callable[[str], bool], require_user) -> None:

    def _job_cua_nguoi_goi(job_id: int, email: str) -> dict:
        """Cờ → 404 → chủ job trước admin → 403. Trả hàng job."""
        if not profile_theo_job.profile_captcha_dang_bat():
            raise HTTPException(status_code=409, detail=THONG_DIEP_TAT)
        job = models.get_job(lay_db(), job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job không tồn tại")
        # Chủ job TRƯỚC `la_admin`: người thường tới đây không tốn một SELECT bảng người dùng.
        if job["nguoi_tao"] != email and not la_admin(email):
            raise HTTPException(status_code=403, detail="Chỉ chủ lượt tải hoặc admin giải được xác minh.")
        return job

    @app.post("/jobs/{job_id}/giai")
    def giai_ngay(job_id: int, nguoi_tao: str = Depends(require_user)) -> dict:
        """"Tôi giải ngay": `cho_xac_minh` → `cho_giai`. Trần `TRAN_GIAI_NGAY` lần mỗi job."""
        job = _job_cua_nguoi_goi(job_id, nguoi_tao)
        ket_qua = mgc.yeu_cau_giai_ngay(lay_db(), job_id)
        if ket_qua == "het_luot":
            raise HTTPException(status_code=409, detail=(
                f"Đã dùng đủ {gc.TRAN_GIAI_NGAY} lần 'Tôi giải ngay' cho lượt này. "
                "Rút lượt để trả hạn mức, hoặc chờ tự kết thúc sau "
                f"{gc.CHO_XAC_MINH_QUA_HAN_GIO} giờ."))
        if ket_qua != "ok":
            moi = models.get_job(lay_db(), job_id) or job
            raise HTTPException(status_code=409, detail=_thong_diep_trang_thai(
                moi["trang_thai"], "chỉ lượt đang chờ xác minh mới giải được"))
        moi = models.get_job(lay_db(), job_id) or job
        return {"trang_thai": "cho_giai", "giai_con_luot": mgc.giai_con_luot(moi)}

    @app.get("/jobs/{job_id}/giai/khung")
    async def giai_khung(job_id: int, request: Request, token: str = Query(...),
                         nguoi_tao: str = Depends(require_user)) -> EventSourceResponse:
        """SSE: trạng thái + khung ảnh trang TikTok. Xem docstring `web/giai_captcha.py`."""
        job = _job_cua_nguoi_goi(job_id, nguoi_tao)
        if not gc.token_hop_le(token):
            raise HTTPException(status_code=400, detail="`token` phải là chuỗi 8–64 ký tự [A-Za-z0-9_-].")
        if job["trang_thai"] not in gc.TRANG_THAI_CO_PHIEN:
            raise HTTPException(status_code=409, detail=_thong_diep_trang_thai(
                job["trang_thai"], "chỉ xem được khi đang chờ/đang giải"))
        phien = gc.lay_hoac_tao_phien(job_id, job["nguoi_tao"], job["trang_thai"])
        return EventSourceResponse(
            _luong_khung(request, job_id, phien, token, nguoi_tao, job["nguoi_tao"]),
            ping=SSE_PING_GIAY)

    async def _luong_khung(request: Request, job_id: int, phien: gc.PhienGiai, token: str,
                           email: str, chu: str):
        da_gui_khung = 0
        so_tb = 0
        cuoi_gui = ""
        luc_gui = 0.0
        luc_kiem = 0.0
        phien_ban_cu = -1
        # Lấy khoá NGAY khi luồng bắt đầu chạy (đồng bộ, không `await` trước đó) và gắn với `finally`
        # bên dưới: generator chưa chạy thì không có gì để nhả, đã chạy thì `finally` luôn nhả.
        with phien.khoa:
            phien.so_sse += 1
            phien.nhan_khoa(token, email)
        try:
            while True:
                bay_gio = asyncio.get_running_loop().time()
                # Kiểm quyền + trạng thái job mỗi giây: chủ job TRƯỚC admin (đã đổi chủ sau khôi phục DB ⇒ dừng).
                if bay_gio - luc_kiem >= SSE_KIEM_QUYEN_GIAY:
                    luc_kiem = bay_gio
                    job = models.get_job(lay_db(), job_id)
                    if job is None or (job["nguoi_tao"] != email and not la_admin(email)):
                        break
                    if job["trang_thai"] not in gc.TRANG_THAI_CO_PHIEN or phien.da_dong:
                        yield {"event": "ket_thuc", "data": json.dumps({
                            "trang_thai": phien.trang_thai_cuoi or job["trang_thai"],
                            "ly_do": phien.ly_do_dong or job.get("ly_do_dung")})}
                        break
                if phien.da_dong:
                    yield {"event": "ket_thuc", "data": json.dumps({
                        "trang_thai": phien.trang_thai_cuoi, "ly_do": phien.ly_do_dong})}
                    break
                if phien.phien_ban != phien_ban_cu or bay_gio - luc_gui >= SSE_NHAC_LAI_GIAY:
                    phien_ban_cu = phien.phien_ban
                    anh = phien.anh_chup(token, email)
                    if anh["trang_thai"] == "cho_giai":
                        vt = models.vi_tri_hang_doi(lay_db(), [job_id]).get(job_id)
                        if vt is not None:
                            anh["vi_tri"] = vt
                    # Gửi khi đổi (bỏ `con_lai_giay` khỏi so sánh: nó đổi từng giây) hoặc tới nhịp nhắc.
                    so_sanh = json.dumps({k: v for k, v in anh.items() if k != "con_lai_giay"})
                    if so_sanh != cuoi_gui or bay_gio - luc_gui >= SSE_NHAC_LAI_GIAY:
                        cuoi_gui, luc_gui = so_sanh, bay_gio
                        yield {"event": "trang_thai", "data": json.dumps(anh)}
                for so, tb in phien.thong_bao_moi(so_tb):
                    so_tb = so
                    if tb.get("loai") == "bi_ngat":
                        yield {"event": "bi_ngat", "data": json.dumps({
                            "ly_do": tb.get("ly_do"), "so_lan_tai_lai": tb.get("so_lan_tai_lai", 0)})}
                khung = phien.lay_khung()
                if khung is not None and khung["seq"] > da_gui_khung:
                    da_gui_khung = khung["seq"]
                    yield {"event": "khung", "data": json.dumps(khung)}
                await asyncio.sleep(SSE_NHIP_GIAY)
        finally:
            # Nhả khoá khi CHÍNH kết nối này ngắt (đóng popup, mất mạng, CancelledError).
            with phien.khoa:
                phien.so_sse -= 1
                phien.nha_khoa(token, email)
            gc.don_phien_roi(job_id, phien)

    @app.post("/jobs/{job_id}/giai/chuot")
    def giai_chuot(job_id: int, body: ChuotBody, nguoi_tao: str = Depends(require_user)) -> dict:
        """Chuyển một lô chuột của người. Xem hợp đồng ở `web/giai_captcha.py`."""
        job = _job_cua_nguoi_goi(job_id, nguoi_tao)
        if job["trang_thai"] != "dang_giai":
            raise HTTPException(status_code=409, detail=_thong_diep_trang_thai(
                job["trang_thai"], "chỉ nhận chuột khi đang giải"))
        phien = gc.lay_phien(job_id)
        if phien is None or phien.da_dong:
            raise HTTPException(status_code=409, detail="Lượt giải không còn mở.")
        if not gc.token_hop_le(body.token) or body.seq < 0:
            raise HTTPException(status_code=400, detail="`token`/`seq` không hợp lệ.")
        if body.ky is None:
            raise HTTPException(status_code=_MA_POPUP_CU, detail=_THONG_DIEP_POPUP_CU)
        if not phien.la_giu(body.token, nguoi_tao):
            raise HTTPException(status_code=409,
                                detail="Bạn không giữ quyền điều khiển (người/tab khác đang giải).")
        try:
            phien.kiem_tan_suat(gc.dong_ho())
            phien.kiem_ky(body.ky)          # lô kỳ cũ ⇒ 409 `ky_cu` trước mọi 400 về nội dung
            if not 1 <= len(body.su_kien) <= gc.LO_TOI_DA_SU_KIEN:
                raise gc.LoiGiai(400, f"Mỗi lô cần 1–{gc.LO_TOI_DA_SU_KIEN} sự kiện.", True)
            if not (isinstance(body.khung_w, float) and 0 < body.khung_w < 1e6
                    and body.khung_w == body.khung_w):
                raise gc.LoiGiai(400, "`khung_w` phải là số dương hữu hạn.", True)
            kich_thuoc = phien.kich_thuoc_thiet_bi(body.khung_seq)
            if kich_thuoc is None:
                raise HTTPException(status_code=409, detail="Chưa có khung ảnh nào — chờ khung đầu.")
            device_w, device_h = kich_thuoc
            khung_h = body.khung_w * device_h / device_w
            events = []
            for raw in body.su_kien:
                ev = gc.kiem_su_kien(raw, body.khung_w, khung_h, device_w)
                if ev is not None:
                    events.append(ev)
            ket_qua = phien.nhan_lo(body.token, nguoi_tao, body.seq, events, ky=body.ky)
        except gc.LoiGiai as loi:
            if loi.huy_gesture:
                # Lô bị từ chối: `seq` của nó coi như đã dùng và thành MỐC HUỶ gesture dở — áp khi các
                # lô trước nó đã tới (không huỷ ngay: lô `down` trước nó có thể còn đang bay).
                phien.bo_lo(body.token, nguoi_tao, body.seq, ky=body.ky)
            raise _http_tu_loi(loi) from loi
        return {"ok": True, "trung": ket_qua == "trung"}

    @app.post("/jobs/{job_id}/giai/lenh")
    def giai_lenh(job_id: int, body: LenhBody, nguoi_tao: str = Depends(require_user)) -> dict:
        """`da_giai` | `dung` | `huy_gesture` — chỉ người đang giữ khoá, chỉ khi `dang_giai`."""
        job = _job_cua_nguoi_goi(job_id, nguoi_tao)
        if body.lenh not in ("da_giai", "dung", "huy_gesture"):
            raise HTTPException(status_code=400,
                                detail="`lenh` phải là da_giai, dung hoặc huy_gesture.")
        if job["trang_thai"] != "dang_giai":
            raise HTTPException(status_code=409, detail=_thong_diep_trang_thai(
                job["trang_thai"], "chỉ ra lệnh khi đang giải"))
        phien = gc.lay_phien(job_id)
        if phien is None or phien.da_dong:
            raise HTTPException(status_code=409, detail="Lượt giải không còn mở.")
        if not gc.token_hop_le(body.token):
            raise HTTPException(status_code=400, detail="`token` không hợp lệ.")
        try:
            if body.lenh == "huy_gesture":
                # Không vào hàng `_lenh` (worker tiêu hàng đó như lệnh kết thúc lượt): huỷ ngay.
                if body.ky is None:
                    raise HTTPException(status_code=_MA_POPUP_CU, detail=_THONG_DIEP_POPUP_CU)
                ky_moi, ky_mat_nut = phien.huy_gesture_cua_nguoi_giu(body.token, nguoi_tao, ky=body.ky)
                # Trả luôn kỳ MỚI: popup học ngay, không phải chờ `trang_thai` (≤ 1 nhịp SSE) — khoảng chờ đó
                # là khe mà cú kéo bắt đầu ngay sau khi huỷ xong bị `ky_cu` (mất cú kéo).
                return {"ok": True, "ky": ky_moi, "ky_mat_nut": ky_mat_nut}
            else:
                phien.dat_lenh(body.token, nguoi_tao, body.lenh)
        except gc.LoiGiai as loi:
            raise _http_tu_loi(loi) from loi
        return {"ok": True}
