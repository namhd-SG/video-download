"""Nguồn khung xám cho lõi thay logo.

Video dài 172s ở 1080×1920 là ~10GB khung xám ⇒ KHÔNG nạp hết vào RAM: lõi chỉ đọc tuần tự hoặc theo chỉ số.
`NguonKhungVideo` đọc file thật bằng OpenCV; `NguonKhungMang` bọc danh sách mảng có sẵn (test tổng hợp).
"""
from __future__ import annotations

from typing import Iterator, Protocol, Sequence

import cv2
import numpy as np


class NguonKhung(Protocol):
    fps: float
    rong: int
    cao: int

    def so_khung(self) -> int: ...

    def doc_tuan_tu(self) -> Iterator[np.ndarray]: ...

    def doc(self, i: int) -> np.ndarray | None: ...


class NguonKhungMang:
    """Danh sách khung xám uint8 cùng cỡ — dùng cho test và clip ngắn đã giải mã sẵn."""

    def __init__(self, khung: Sequence[np.ndarray], fps: float = 30.0):
        if not khung:
            raise ValueError("cần ít nhất 1 khung")
        self._khung = list(khung)
        self.fps = fps
        self.cao, self.rong = self._khung[0].shape[:2]

    def so_khung(self) -> int:
        return len(self._khung)

    def doc_tuan_tu(self) -> Iterator[np.ndarray]:
        return iter(self._khung)

    def doc(self, i: int) -> np.ndarray | None:
        return self._khung[i] if 0 <= i < len(self._khung) else None


class NguonKhungVideo:
    """Đọc khung xám từ file video. Mỗi lần duyệt mở một VideoCapture mới để các lượt không giẫm vị trí nhau."""

    def __init__(self, duong_dan: str):
        cap = cv2.VideoCapture(duong_dan)
        if not cap.isOpened():
            raise ValueError(f"không mở được video: {duong_dan}")
        self._duong_dan = duong_dan
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.rong = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.cao = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

    def so_khung(self) -> int:
        return self._n

    def doc_tuan_tu(self) -> Iterator[np.ndarray]:
        cap = cv2.VideoCapture(self._duong_dan)
        try:
            while True:
                ok, fr = cap.read()
                if not ok:
                    return
                yield cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        finally:
            cap.release()

    def doc(self, i: int) -> np.ndarray | None:
        cap = cv2.VideoCapture(self._duong_dan)
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            return cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY) if ok else None
        finally:
            cap.release()
