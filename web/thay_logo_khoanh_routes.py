"""Route trang "khoanh chỗ lộ" (plan 261023-1149 pha 1a): dải thời gian đỏ/vàng, ảnh khung bất kỳ, lưu một chỗ khoanh.

Cùng cổng quyền với trang Thay logo (`_video_cua`: chủ lượt hoặc quản trị); `vid` trên URL là `tl_job_video.id` như mọi route khác,
dữ liệu nhật ký đi theo `video_log_id` (= `tl_video.id`).
"""
from __future__ import annotations

import gzip
import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from tiktok_music_downloader.thay_logo import khoanh

log = logging.getLogger("videodl.thay_logo")

TRANG_THAI_KHOANH_DUOC = ("xong", "cho_nguoi")
TRAN_GIAY_TRICH_KHUNG = 20
TRAN_FFMPEG_CUNG_LUC = 2  # trích khung chung máy với worker render: không để trang bắn hàng loạt ffmpeg
_KHE_FFMPEG = threading.BoundedSemaphore(TRAN_FFMPEG_CUNG_LUC)


class Khoanh(BaseModel):
    khung: int = Field(ge=0, le=10_000_000)
    vung: dict | None = None  # {x, y, w, h} tỉ lệ 0–1 theo ảnh hiển thị; bỏ trống chỉ khi giu_goc
    giu_goc: bool = False     # "Giữ hình gốc đoạn này": máy đè nhầm ⇒ ca che_nham, vùng = ô máy ở khung đó


def _dem_khung(p: Path) -> int:
    import cv2  # extra `thay-logo` (worker cũng cần) — chỉ nạp khi nhật ký thiếu số khung
    cap = cv2.VideoCapture(str(p))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def dang_ky(app: FastAPI, *, mo: Callable, video_cua: Callable, lay_log_db: Callable[[], object], require_user,
            lay_worker: Callable[[], object | None]) -> None:
    """`mo()` mở nhật ký + hàng đợi; `video_cua(conn, vid, email)` trả hàng video hoặc ném 404/403."""

    def _data() -> Path:
        return Path(lay_log_db()).parent

    def _nap(conn, vid: int, email: str):
        r = video_cua(conn, vid, email)
        log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (vid,)).fetchone()[0]
        t = conn.execute("SELECT id, kho, fps, so_khung, duong_dan_track FROM tl_video WHERE id=?", (log_id,)).fetchone() if log_id else None
        if t is None:
            raise HTTPException(404, "video chưa có kết quả máy")
        return r, t

    def _track(conn, t) -> tuple[list, dict]:
        if not t["duong_dan_track"]:
            raise HTTPException(404, "không còn dữ liệu vết của video này")
        try:
            with gzip.open(t["duong_dan_track"], "rt", encoding="utf-8") as f:
                track = json.load(f)
        except (OSError, ValueError):
            raise HTTPException(404, "không còn dữ liệu vết của video này") from None
        tt = dict(conn.execute("SELECT vet, trang_thai FROM tl_vet WHERE video_id=?", (t["id"],)).fetchall())
        return track, tt

    @app.get("/api/thay-logo/videos/{vid}/dai")
    def dai(vid: int = PathParam(ge=1, le=2**63 - 1), email: str = Depends(require_user)) -> dict:
        conn = mo()
        try:
            r, t = _nap(conn, vid, email)
            track, tt = _track(conn, t)
            doan = khoanh.dai_thoi_gian(track, tt)
        finally:
            conn.close()
        co = {b: khoanh.duong_video(_data(), t["id"], b).exists() for b in ("goc", "ra")}
        return {"fps": t["fps"], "so_khung": t["so_khung"], "kho": t["kho"], "trang_thai": r["trang_thai"], "doan": doan, "co_video": co}

    @app.get("/api/thay-logo/videos/{vid}/khung-tai/{khung}")
    def khung_tai(vid: int = PathParam(ge=1, le=2**63 - 1), khung: int = PathParam(ge=0, le=10_000_000),
                  ban: str = Query("ra", pattern="^(goc|ra)$"), email: str = Depends(require_user)) -> Response:
        conn = mo()
        try:
            _, t = _nap(conn, vid, email)
        finally:
            conn.close()
        if t["so_khung"] is not None and khung >= t["so_khung"]:
            raise HTTPException(400, "khung ngoài video")
        p = khoanh.duong_video(_data(), t["id"], ban)
        if not p.exists():
            raise HTTPException(404, "video đã dọn khỏi máy")
        if t["so_khung"] is None and khung >= _dem_khung(p):  # nhật ký thiếu số khung ⇒ đếm của chính file, không để ffmpeg lỗi 500
            raise HTTPException(400, "khung ngoài video")
        w = lay_worker()
        ffmpeg = getattr(w, "ffmpeg", None)
        if not ffmpeg:
            from tiktok_music_downloader.watermark import find_ffmpeg
            ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise HTTPException(503, "máy chủ thiếu ffmpeg")
        giay = khung / (t["fps"] or 30.0)
        # -ss TRƯỚC -i: nhảy theo keyframe (nhanh) — trích khung ở phút thứ 4 không phải giải mã từ đầu
        cmd = ["nice", "-n", "10", ffmpeg, "-v", "error", "-ss", f"{giay:.3f}", "-i", str(p), "-frames:v", "1", "-q:v", "3", "-f", "image2pipe",
               "-vcodec", "mjpeg", "pipe:1"]
        if not _KHE_FFMPEG.acquire(timeout=TRAN_GIAY_TRICH_KHUNG):
            raise HTTPException(503, "máy đang bận trích khung, thử lại sau")
        try:
            kq = subprocess.run(cmd, capture_output=True, timeout=TRAN_GIAY_TRICH_KHUNG)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "trích khung quá lâu") from None
        finally:
            _KHE_FFMPEG.release()
        if kq.returncode != 0 or not kq.stdout:
            log.warning("thay logo: trích khung %s#%s lỗi: %s", vid, khung, kq.stderr[-500:])
            raise HTTPException(500, "không trích được khung")
        return Response(kq.stdout, media_type="image/jpeg")

    @app.post("/api/thay-logo/videos/{vid}/khoanh", status_code=201)
    def tao_khoanh(body: Khoanh, vid: int = PathParam(ge=1, le=2**63 - 1), email: str = Depends(require_user)) -> dict:
        conn = mo()
        try:
            r, t = _nap(conn, vid, email)
            if r["trang_thai"] not in TRANG_THAI_KHOANH_DUOC:
                raise HTTPException(409, "chỉ khoanh video máy đã xong hoặc máy không chắc")
            if t["so_khung"] is not None and body.khung >= t["so_khung"]:
                raise HTTPException(400, "khung ngoài video")
            cho_nguoi = r["trang_thai"] == "cho_nguoi"
            if body.giu_goc and cho_nguoi:
                raise HTTPException(400, "video máy không chắc chưa đè gì để giữ hình gốc")
            try:
                rong, cao = (int(v) for v in (t["kho"] or "").split("x"))
                vung = khoanh.quy_doi(body.vung, rong, cao) if body.vung is not None else None
            except ValueError as e:
                raise HTTPException(400, str(e) if "vùng" in str(e) else "video thiếu kích thước khung") from None
            if vung is None and not body.giu_goc:
                raise HTTPException(400, "cần vùng khoanh")
            box_may, chan = (None, [])
            if not cho_nguoi:
                track, tt = _track(conn, t)
                box_may, chan = khoanh.khung_tai(track, tt, body.khung)
            if body.giu_goc and box_may is None:
                raise HTTPException(409, "ở khung này máy không đè gì")
            mau, chan_cu = khoanh.gan_mau_loi(cho_nguoi, body.giu_goc, vung, box_may, chan)
            ca = khoanh.ghi_ca(conn, video_log_id=t["id"], job_video_id=vid, member=email, khung=body.khung, vung=vung,
                               mau_loi=mau, chan_cu=chan_cu, box_may=box_may)
        finally:
            conn.close()
        return {"id": ca, "mau_loi": mau, "chan_cu": chan_cu}
