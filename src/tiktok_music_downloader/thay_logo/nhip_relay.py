"""Nhịp sống của relay agy, phía MINI — để relay DỰ PHÒNG (ca-n) chỉ nhận việc khi relay CHÍNH (máy dev) đã im.

Relay chính hỏi `GET …/relay/viec` (không cờ) mỗi vòng, và trong lúc chờ agy (tới 900 s) vẫn hỏi lại mỗi `NHIP_GIAY` làm nhịp sống.
Relay dự phòng hỏi `GET …/relay/viec?du_phong=1`: nếu relay chính vừa hỏi trong `DU_PHONG_SAU_GIAY` thì mini trả danh sách RỖNG ⇒ dự
phòng không cướp việc, không đốt trùng quota agy (hai relay dùng CHUNG tài khoản agy — USER CHỐT 16/10). Relay chính im quá mốc ⇒ dự
phòng nhận nguyên danh sách và gom lô như thường.

Lưu ở BỘ NHỚ tiến trình (relay server chạy trong cùng tiến trình với worker): mini khởi động lại ⇒ quên nhịp ⇒ dự phòng có thể nhận việc
ngay vòng đầu. Cái giá: tối đa một lượt agy trùng (lần nộp sau bị 409, mini nuốt an toàn) — chấp nhận, không ghi đĩa cho việc này.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

DU_PHONG_SAU_GIAY = 300.0  # relay chính im quá 5 phút ⇒ dự phòng tiếp quản (plan P6 R2, agy KHÉP R2b)


class NhipRelay:
    def __init__(self, dong_ho: Callable[[], float] = time.monotonic):
        self._dong_ho, self._khoa = dong_ho, threading.Lock()
        self._chinh: float | None = None
        self._du_phong: float | None = None

    def ghi(self, du_phong: bool) -> None:
        with self._khoa:
            if du_phong:
                self._du_phong = self._dong_ho()
            else:
                self._chinh = self._dong_ho()

    def chinh_con_song(self, trong_giay: float = DU_PHONG_SAU_GIAY) -> bool:
        with self._khoa:
            return self._chinh is not None and self._dong_ho() - self._chinh < trong_giay

    def tuoi(self) -> dict[str, float | None]:
        """Số giây kể từ lần hỏi gần nhất của từng relay (None = chưa từng hỏi từ lúc mini chạy) — đính vào tin báo động."""
        with self._khoa:
            bay_gio = self._dong_ho()
            return {"chinh": None if self._chinh is None else bay_gio - self._chinh,
                    "du_phong": None if self._du_phong is None else bay_gio - self._du_phong}


NHIP = NhipRelay()  # một bản cho cả tiến trình mini (route relay ghi, worker đọc khi báo động)
