"""Cấu hình test dùng chung.

`VIDEODL_TAT_LAP_VAO_BO=1` đặt NGAY từ lúc pytest khởi động (không phải fixture theo
test): các fixture phạm vi module của test trình duyệt dựng app thật và chạy
`_lifespan` TRƯỚC mọi fixture theo hàm. Thiếu dòng này, mỗi app thật trong suite khởi
một thread bộ kiểm "đã vào bộ" (trễ 60 giây rồi chạm Drive nếu máy dev có `GDRIVE_*`).
Test nào cần thread thật tự `monkeypatch.delenv`.
"""
import itertools
import os

import pytest


def pytest_configure(config):
    os.environ["VIDEODL_TAT_LAP_VAO_BO"] = "1"


@pytest.fixture(autouse=True)
def _dem_ky_moi_moi_test(monkeypatch):
    """Bộ đếm kỳ của máy chủ giải captcha là TOÀN TIẾN TRÌNH, hạt giống theo thời gian (chỉ cần tăng ngặt): đặt lại về 0
    ở đầu mỗi test để kỳ đầu của phiên đầu là 0 và các test so số kỳ tuyệt đối không phụ thuộc thứ tự chạy."""
    from web import giai_captcha
    monkeypatch.setattr(giai_captcha, "_DEM_KY", itertools.count())


@pytest.fixture(autouse=True)
def _tat_profile_yt_dlp(monkeypatch):
    """Nhánh @profile qua yt-dlp (`nguon_profile_yt_dlp`) gọi mạng thật: TẮT mặc định cho mọi test để test cũ
    của nhánh trình duyệt (vá `scrape_music_page`) chạy y như trước. Test của nhánh yt-dlp tự `setenv` "1"."""
    monkeypatch.setenv("VIDEODL_PROFILE_YT_DLP", "0")
