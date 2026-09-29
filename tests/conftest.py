"""Cấu hình test dùng chung.

`VIDEODL_TAT_LAP_VAO_BO=1` đặt NGAY từ lúc pytest khởi động (không phải fixture theo
test): các fixture phạm vi module của test trình duyệt dựng app thật và chạy
`_lifespan` TRƯỚC mọi fixture theo hàm. Thiếu dòng này, mỗi app thật trong suite khởi
một thread bộ kiểm "đã vào bộ" (trễ 60 giây rồi chạm Drive nếu máy dev có `GDRIVE_*`).
Test nào cần thread thật tự `monkeypatch.delenv`.
"""
import os


def pytest_configure(config):
    os.environ["VIDEODL_TAT_LAP_VAO_BO"] = "1"
