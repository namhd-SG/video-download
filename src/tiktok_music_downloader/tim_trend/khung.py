"""Trích khung ẢNH từ video đầu vào để agy bóc trường — chỉ ảnh, không tiếng.

GĐ1: agy nhận cả video (hình + tiếng) đã nghe lời Hindi rồi bịa "chữ lyrics Devanagari chạy trên hình" cho một video
không có chữ nào. Đưa ảnh tĩnh thì agy không còn kênh tiếng để suy sang hình.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

VI_TRI = (0.1, 0.5, 0.9)   # đầu / giữa / cuối: dạng ghép bung pose sau giây 0 vẫn được bắt ở khung giữa
RONG = 360                 # cỡ agy đã dùng ở GĐ1 và ở `thay_logo/hoc_mau_agy.py`
DANH_DAU = ".tim-trend-khung"   # file đánh dấu: chỉ thư mục có file này mới được công cụ dọn (không xoá `khung/` của người dùng)


def _ff(ten: str) -> str:
    duong = shutil.which(ten)
    if duong is None:
        raise RuntimeError(f"không tìm thấy {ten} trên PATH")
    return duong


def thoi_luong(video: Path) -> float:
    ra = subprocess.run([_ff("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                        capture_output=True, text=True, check=True)
    giay = float(json.loads(ra.stdout)["format"]["duration"])
    if giay <= 0:
        raise ValueError(f"thời lượng không hợp lệ: {giay}")
    return giay


def trich_khung(video: Path, thu_muc: Path, tien_to: str = "dau-vao") -> list[Path]:
    """Ghi các khung `<tien_to>-<i>.jpg` vào `thu_muc`; trả danh sách file đã ghi được (khung lỗi bị bỏ, không đoán)."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    (thu_muc / DANH_DAU).write_text("tạo bởi tim_trend; xoá được\n")
    giay = thoi_luong(video)
    ra: list[Path] = []
    for i, vt in enumerate(VI_TRI):
        dich = thu_muc / f"{tien_to}-{i}.jpg"
        kq = subprocess.run([_ff("ffmpeg"), "-v", "error", "-y", "-ss", f"{giay * vt:.3f}", "-i", str(video),
                             "-frames:v", "1", "-vf", f"scale={RONG}:-2", "-an", str(dich)],
                            capture_output=True, text=True)
        if kq.returncode == 0 and dich.exists() and dich.stat().st_size > 0:
            ra.append(dich)
    return ra
