"""Ảnh soi nhanh cho màn Lô: 3 ảnh mỗi video (đầu · giữa · cuối) để người lướt cả nhóm "máy chắc" / "máy không thấy logo".

Dựng SẴN khi worker giữ video (agy thay-logo-cai-to R3b ĐK4): mở màn Lô chỉ tải ảnh tĩnh, không bắn hàng trăm ffmpeg lên máy render.
  · video `xong`: khung = đầu / giữa / cuối của tập khung máy đang đè; ảnh lấy từ bản RA, cắt quanh box máy ở CHÍNH khung đó
    (box trôi theo thời gian) nới mỗi cạnh — để thấy lộ mép ngay cạnh ô đè.
  · video `cho_nguoi`: máy không đè gì ⇒ 3 khung ở 10/50/90% độ dài, cả khung từ bản GỐC, để người xác nhận "không có logo".
Ảnh nằm cùng thư mục video giữ (`thay_logo_video/<id>/`) ⇒ `khoanh.don_video_sua` dọn chung.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import subprocess
import time
from pathlib import Path

from . import khoanh

log = logging.getLogger("videodl.thay_logo")

SO_ANH = 3
TI_LE_KHUNG_XAM = (0.1, 0.5, 0.9)
NOI_TOI_THIEU_PX = 24  # nới mỗi cạnh max(0,5·cạnh box, 24 px): ô nhỏ vẫn đủ nền xung quanh để thấy lộ mép
RONG_ANH = 480         # rộng ảnh soi: lưới 3 ảnh/dòng trên màn Lô vẫn đọc được mép logo
TEN_MOC = "soi.json"
# Trần cả 3 lệnh ffmpeg (-ss trước -i, 1 khung/lệnh), CHƯA ĐO thời gian thật — quá trần thì bỏ (job vẫn xong, route dựng
# lười lại khi có người mở).
TRAN_GIAY_DUNG = 30


def _box_de(track: list[list[dict]], tt_vet: dict) -> dict[int, tuple]:
    """{khung: box máy đang đè} — cùng điều kiện với `khoanh.khung_tai` (vết render, state detected/filled; vết đầu tiên thắng)."""
    out: dict[int, tuple] = {}
    for k, vet in enumerate(track):
        if tt_vet.get(k) != "render":
            continue
        for e in vet:
            box = (e.get("x"), e.get("y"), e.get("w"), e.get("h"))
            if e.get("state") in khoanh.DA and None not in box and e["frame"] not in out:
                out[e["frame"]] = box
    return out


def cat_quanh(box: tuple, rong: int, cao: int) -> tuple[int, int, int, int]:
    """Vùng cắt (x, y, w, h) quanh box, nới mỗi cạnh, kẹp trong khung rong×cao."""
    x, y, w, h = (int(v) for v in box)
    nx, ny = max(w // 2, NOI_TOI_THIEU_PX), max(h // 2, NOI_TOI_THIEU_PX)
    x0, y0 = max(0, x - nx), max(0, y - ny)
    x1, y1 = min(rong, x + w + nx), min(cao, y + h + ny)
    return x0, y0, x1 - x0, y1 - y0


def chon_khung(track: list[list[dict]] | None, tt_vet: dict, trang_thai: str, so_khung: int | None,
               kho: str | None) -> list[dict]:
    """[{khung, ban, cat}] — `cat` None = cả khung. Rỗng khi không đủ dữ liệu để chọn (video xong mà không có khung đè nào)."""
    if trang_thai == "cho_nguoi":
        if not so_khung:
            return []
        return [{"khung": min(so_khung - 1, int(so_khung * t)), "ban": "goc", "cat": None} for t in TI_LE_KHUNG_XAM]
    de = _box_de(track or [], tt_vet)
    if not de:
        return []
    rong, cao = (int(v) for v in (kho or "").split("x"))
    ks = sorted(de)
    chon = [ks[0], ks[len(ks) // 2], ks[-1]]
    return [{"khung": k, "ban": "ra", "cat": cat_quanh(de[k], rong, cao)} for k in chon]


# ---------------------------------------------------------------- dựng ảnh
def thu_muc(data: Path, video_log_id: int) -> Path:
    return khoanh.duong_video(data, video_log_id, "goc").parent


def da_co(data: Path, video_log_id: int) -> dict | None:
    """Nội dung `soi.json` nếu đã dựng đủ, ngược lại None. `soi.json` là MỐC "đủ ảnh": chỉ ghi sau khi cả 3 jpg đã nằm yên."""
    d = thu_muc(data, video_log_id)
    try:
        meta = json.loads((d / TEN_MOC).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if len(meta.get("anh", [])) != SO_ANH or not all((d / f"soi-{a['i']}.jpg").is_file() for a in meta["anh"]):
        return None  # mốc còn mà ảnh đã mất ⇒ coi như chưa có, không trả 2/3
    return meta


def _ghi_nguyen_khoi(dich: Path, du_lieu: bytes) -> None:
    tam = dich.with_name(f".{dich.name}.tam")
    tam.write_bytes(du_lieu)
    os.replace(tam, dich)  # cùng thư mục ⇒ nguyên khối: route không bao giờ đọc file dở


def dung_anh(data: Path, video_log_id: int, chon: list[dict], ffmpeg: str, fps: float | None) -> bool:
    """Trích + cắt 3 ảnh rồi ghi mốc. Trả True khi đủ ảnh; False (kèm log) khi thiếu video, thiếu khung chọn hay ffmpeg trượt —
    không ném: người gọi (worker) vẫn kết thúc job bình thường."""
    if len(chon) != SO_ANH:
        log.info("thay logo: video %s không đủ khung để dựng ảnh soi (%d)", video_log_id, len(chon))
        return False
    d = thu_muc(data, video_log_id)
    bat_dau = time.monotonic()
    for i, c in enumerate(chon):
        nguon = khoanh.duong_video(data, video_log_id, c["ban"])
        if not nguon.is_file():
            log.warning("thay logo: thiếu %s.mp4 để dựng ảnh soi video %s", c["ban"], video_log_id)
            return False
        loc = f"scale={RONG_ANH}:-2"
        if c["cat"] is not None:
            x, y, w, h = c["cat"]
            loc = f"crop={w}:{h}:{x}:{y},{loc}"
        cmd = ["nice", "-n", "10", ffmpeg, "-v", "error", "-ss", khoanh.giay_cua_khung(c["khung"], fps), "-i", str(nguon),
               "-frames:v", "1", "-vf", loc, "-q:v", "3", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
        con_lai = TRAN_GIAY_DUNG - (time.monotonic() - bat_dau)
        if con_lai <= 0:
            log.warning("thay logo: dựng ảnh soi video %s quá %ss, bỏ", video_log_id, TRAN_GIAY_DUNG)
            return False
        try:
            kq = subprocess.run(cmd, capture_output=True, timeout=con_lai)
        except subprocess.TimeoutExpired:
            log.warning("thay logo: dựng ảnh soi video %s quá %ss, bỏ", video_log_id, TRAN_GIAY_DUNG)
            return False
        if kq.returncode != 0 or not kq.stdout:
            log.warning("thay logo: ffmpeg dựng ảnh soi %s#%s lỗi: %s", video_log_id, c["khung"], kq.stderr[-500:])
            return False
        _ghi_nguyen_khoi(d / f"soi-{i}.jpg", kq.stdout)
    meta = {"anh": [{"i": i, "khung": c["khung"], "ban": c["ban"], "cat": c["cat"]} for i, c in enumerate(chon)]}
    _ghi_nguyen_khoi(d / TEN_MOC, json.dumps(meta).encode("utf-8"))  # mốc ghi SAU CÙNG
    return True


def dung_cho_video(conn, data: Path, video_log_id: int, trang_thai: str, ffmpeg: str) -> bool:
    """Nạp nhật ký của video (kích thước, fps, track, trạng thái vết) rồi dựng — dùng chung cho worker và đường dựng lười của route."""
    t = conn.execute("SELECT kho, fps, so_khung, duong_dan_track FROM tl_video WHERE id=?", (video_log_id,)).fetchone()
    if t is None:
        return False
    track = None
    if trang_thai != "cho_nguoi":
        try:
            with gzip.open(t["duong_dan_track"], "rt", encoding="utf-8") as f:
                track = json.load(f)
        except (OSError, TypeError, ValueError) as e:
            log.warning("thay logo: không đọc được vết để dựng ảnh soi video %s: %s", video_log_id, type(e).__name__)
            return False
    tt = dict(conn.execute("SELECT vet, trang_thai FROM tl_vet WHERE video_id=?", (video_log_id,)).fetchall())
    try:
        chon = chon_khung(track, tt, trang_thai, t["so_khung"], t["kho"])
    except ValueError:
        log.warning("thay logo: video %s thiếu kích thước khung, không dựng ảnh soi", video_log_id)
        return False
    return dung_anh(data, video_log_id, chon, ffmpeg, t["fps"])
