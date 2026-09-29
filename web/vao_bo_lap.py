"""Thread nền chạy định kỳ bộ kiểm "đã vào bộ" (ẩn) — sống trong `_lifespan`.

Chọn thread trong tiến trình thay vì một LaunchAgent riêng: không thêm dịch vụ phải
`launchctl list` sau mỗi lần deploy, và nó chạy lại theo deploy. Đổi lại nó chết cùng
tiến trình — vô hại: mọi mốc ghi bằng `UPDATE … WHERE … IS NULL` nên lượt sau nhặt lại.

LƯỢT ĐẦU TRỄ ~60 giây, có chủ đích: `uvicorn` chạy `lifespan.startup()` TRƯỚC khi bind
cổng (đo 26/09, uvicorn 0.53), nên một tiến trình thứ hai sắp chết vì cổng bận VẪN kịp
khởi thread này. Trễ để nó chết trước khi chạm Drive hay DB.

`stop_event` để thoát sạch: `stop()` đánh thức thread đang ngủ ngay, và các lượt hỏi
`dung()` giữa hai video.

Không có cờ khoá "đang chạy" (kẹt vĩnh viễn nếu `kickstart -k` giết giữa lượt) — chống
ghi đôi là việc của các câu UPDATE có điều kiện `IS NULL` trong `BEGIN IMMEDIATE`.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from web import vao_bo_kiem
from web.vao_bo_drive import DriveThat, DriveVaoBo

log = logging.getLogger("videodl.web.vao_bo")

TRE_LUOT_DAU_GIAY = 60.0
CHU_KY_GIAY = 900.0


class LapVaoBo:
    def __init__(self, db_path: Path, tao_drive: Callable[[], DriveVaoBo] = DriveThat, *,
                 tre_dau: float = TRE_LUOT_DAU_GIAY, chu_ky: float = CHU_KY_GIAY):
        self._db_path = db_path
        self._tao_drive = tao_drive
        self._tre_dau = tre_dau
        self._chu_ky = chu_ky
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._da_bao_chua_cau_hinh = False

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="videodl-vao-bo", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def chay_mot_luot(self) -> bool:
        """Một lượt trọn (ẩn). Trả False nếu bỏ qua vì Drive chưa cấu hình."""
        drive = self._tao_drive()
        if not drive.dang_cau_hinh():
            if not self._da_bao_chua_cau_hinh:
                log.info("bộ kiểm đã-vào-bộ: Drive chưa cấu hình — bỏ qua các lượt")
                self._da_bao_chua_cau_hinh = True
            return False
        vao_bo_kiem.chay_luot_kiem(self._db_path, drive, dung=self._stop.is_set)
        return True

    def _loop(self) -> None:
        if self._stop.wait(self._tre_dau):
            return
        while not self._stop.is_set():
            try:
                self.chay_mot_luot()
            except Exception:  # noqa: BLE001 — một lượt hỏng không được giết thread
                log.exception("lượt kiểm đã-vào-bộ hỏng — thử lại ở chu kỳ sau")
            if self._stop.wait(self._chu_ky):
                return
