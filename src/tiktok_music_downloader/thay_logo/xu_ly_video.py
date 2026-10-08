"""Xử lý TRỌN một video cho worker: lõi → render (nếu có vết qua cổng) → nhật ký + track + ảnh soi trước/sau.

Video gốc không bị đụng; file ra là file mới. Mọi lỗi được ghi vào nhật ký với trạng thái `loi` rồi ném lại cho worker.
Số luồng OpenCV ghim 2 (mini chạy chung lane tải; bench P0b cũng ghim 2).
"""
from __future__ import annotations

import random
import resource
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import nhat_ky, render
from .box_moi import BoxMoi
from .duong_ong import KetQuaVideo, xu_ly_video as chay_loi
from .nguon_khung import NguonKhungVideo

LUONG_OPENCV = 2
O_SOI = (200, 120)  # cỡ một ô ảnh soi


def _rss_dinh_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1 << 20) if sys.platform == "darwin" else r / 1024, 1)


def _o(g_bgr, e, nhan: str, mau_khung) -> np.ndarray:
    H, W = g_bgr.shape[:2]
    x0, y0 = max(0, e["x"] - e["w"] // 2), max(0, e["y"] - 2 * e["h"])
    cr = g_bgr[y0:min(H, e["y"] + 3 * e["h"]), x0:min(W, e["x"] + e["w"] + e["w"] // 2)].copy()
    cv2.rectangle(cr, (e["x"] - x0, e["y"] - y0), (e["x"] - x0 + e["w"], e["y"] - y0 + e["h"]), mau_khung, 1)
    cr = cv2.resize(cr, O_SOI)
    cv2.putText(cr, nhan, (3, 13), 0, 0.4, (0, 255, 255), 1)
    return cr


def tao_anh_soi(video_goc: str, video_ra: str | None, kq: KetQuaVideo, duong_dan: Path, hat: int = 0) -> str | None:
    """Mỗi hàng 2 ô (trước | sau). Tối đa 2 khung đã thay + 2 khung bị chặn (ghi tên cổng) + 2 khung chắc ngẫu nhiên khác."""
    rnd = random.Random(hat)
    chon: list[tuple[dict, str]] = []
    for v in kq.vet:
        da_thay = v.khung_render
        chan = [e for e in v.track if str(e.get("state", "")).startswith("hidden_")]
        chon += [(e, "thay") for e in rnd.sample(da_thay, min(2, len(da_thay)))]
        chon += [(e, e["state"].removeprefix("hidden_")) for e in rnd.sample(chan, min(2, len(chan)))]
    if not chon:
        return None
    chon = sorted(chon[:6], key=lambda t: t[0]["frame"])
    goc, ra = cv2.VideoCapture(video_goc), cv2.VideoCapture(video_ra) if video_ra else None
    hang = []
    for e, nhan in chon:
        goc.set(cv2.CAP_PROP_POS_FRAMES, e["frame"])
        ok, f = goc.read()
        if not ok:
            continue
        sau = f
        if ra is not None:
            ra.set(cv2.CAP_PROP_POS_FRAMES, e["frame"])
            ok2, f2 = ra.read()
            sau = f2 if ok2 else f
        mau = (0, 200, 0) if nhan == "thay" else (0, 0, 255)
        hang.append(np.hstack([_o(f, e, f"#{e['frame']} {nhan}", mau), _o(sau, e, "sau", mau)]))
    goc.release()
    if ra is not None:
        ra.release()
    if not hang:
        return None
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(duong_dan), np.vstack(hang), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return str(duong_dan)


def xu_ly(video: str, boxes: list[BoxMoi], dau_ra: str, conn, thu_muc_file: Path, *, nguon_video: str,
          ffmpeg: str, job_id: int | None = None, token_agy: int | None = None, man_ket_agy: bool | None = None) -> dict:
    """Trả {"video_log_id", "trang_thai", "dau_ra" | None}. `cho_nguoi` ⇒ KHÔNG ghi file ra (giữ nguyên gốc)."""
    cv2.setNumThreads(LUONG_OPENCV)
    nguon = NguonKhungVideo(video)
    vid = nhat_ky.bat_dau_video(conn, nguon_video=nguon_video, job_id=job_id, sha256_goc=nhat_ky.sha256_file(video),
                                kho=f"{nguon.rong}x{nguon.cao}", fps=nguon.fps, so_khung=nguon.so_khung(),
                                giay_video=round(nguon.so_khung() / (nguon.fps or 30.0), 2), token_agy=token_agy,
                                man_ket_agy=None if man_ket_agy is None else int(man_ket_agy))
    t0 = time.time()
    try:
        nhat_ky.ghi_box_moi(conn, vid, boxes)
        kq = chay_loi(nguon, boxes)
        for k, v in enumerate(kq.vet):
            nhat_ky.ghi_vet(conn, vid, k, v)
        khung = render.gom_khung_render([v.khung_render for v in kq.vet])
        ra = None
        if kq.trang_thai == "render" and khung:
            render.render_video(video, khung, dau_ra, ffmpeg, luong=LUONG_OPENCV)
            ra = dau_ra
        d = Path(thu_muc_file) / str(vid)
        nhat_ky.cap_nhat_video(
            conn, vid, trang_thai=kq.trang_thai, ket_thuc=time.time(), giay_xu_ly=round(time.time() - t0, 1),
            rss_dinh_mb=_rss_dinh_mb(), duong_dan_track=nhat_ky.luu_track(thu_muc_file, vid, [v.track for v in kq.vet]),
            duong_dan_sheet=tao_anh_soi(video, ra, kq, d / "sheet.jpg", hat=vid))
        return {"video_log_id": vid, "trang_thai": kq.trang_thai, "dau_ra": ra}
    except Exception as e:
        nhat_ky.cap_nhat_video(conn, vid, trang_thai="loi", loi_text=f"{type(e).__name__}: {e}"[:2000],
                               ket_thuc=time.time(), giay_xu_ly=round(time.time() - t0, 1))
        raise
