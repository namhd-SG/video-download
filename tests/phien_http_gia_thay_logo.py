"""Session HTTP GIẢ cho `tai_len_phien` (thay `AuthorizedSession`): ghi lại mọi lời gọi tạo phiên resumable, trả `Location` giả.

`URL_BI_MAT` mô phỏng URL phiên thật của Google — là QUYỀN GHI vào thư mục đầu vào; test khẳng định nó không lọt DB/log/stderr.
Không test nào gọi mạng thật."""
from __future__ import annotations

SO_BI_MAT = "SECRETSESSION123XYZ"
URL_BI_MAT = f"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true&upload_id={SO_BI_MAT}"


class PhanHoiGia:
    def __init__(self, status_code=200, headers=None):
        self.status_code, self.headers = status_code, headers if headers is not None else {}


class SessionGia:
    def __init__(self):
        self.goi: list[dict] = []
        self.phan_hoi = PhanHoiGia(200, {"Location": URL_BI_MAT})
        self.loi: Exception | None = None  # ném thay vì trả (mô phỏng lỗi mạng của `requests`, thông điệp chứa URL)
        self.da_dong = 0

    def post(self, url, timeout=None, json=None, headers=None, **kw):
        self.goi.append({"url": url, "timeout": timeout, "json": json, "headers": dict(headers or {})})
        if self.loi is not None:
            raise self.loi
        return self.phan_hoi

    def close(self):
        self.da_dong += 1
