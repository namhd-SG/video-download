"""Chỗ DUY NHẤT luồng "Thay logo" nói chuyện với Drive (mẫu: `web/vao_bo_drive.py`).

`DriveTL` là giao diện nhỏ mà test thay bằng bản giả (`tests/drive_gia_thay_logo.py`) — KHÔNG test nào gọi Drive thật. `DriveTLThat`
bọc `DriveUploader` (cùng credential, cùng cờ `supportsAllDrives`). Các đợt sau (link Drive, áp vào bộ, ...) MỞ RỘNG giao diện này
bằng cách THÊM phương thức ở CẢ HAI nơi (giao diện + bản thật) và ở bản giả — không tạo đường Drive thứ hai.

Không có hàm nào xoá vĩnh viễn: service account chỉ là Content manager.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

MIME_THU_MUC = "application/vnd.google-apps.folder"
TRUONG_MUC = "id,name,parents,driveId,mimeType,trashed,md5Checksum,size"  # md5/size: chỉ file có (thư mục không có)
TEN_CAY_CAM = "Creative"  # cây Creative Desk quét: thư mục có video trong đó bị biến thành bộ chạy quảng cáo
TOI_DA_DO_SAU = 50
TIMEOUT_LAY_MUC_GIAY = 10  # mỗi lời gọi đọc siêu dữ liệu (cổng cấu hình): Drive treo ⇒ lỗi sau 10 s, không treo mãi


class DriveTLKhongThay(Exception):
    """Drive trả HTTP 404 ĐÍCH DANH. Lỗi khác (403/5xx/timeout) KHÔNG phải lỗi này — là "chưa đo được"."""


class DriveTL(Protocol):
    def dang_cau_hinh(self) -> bool: ...

    def lay_muc(self, file_id: str) -> dict:
        """Siêu dữ liệu `TRUONG_MUC` của file/thư mục. 404 ⇒ `DriveTLKhongThay`; lỗi khác ném nguyên."""

    def tim_con_theo_ten(self, cha_id: str, ten: str) -> list[dict]:
        # Không đặt timeout ngắn cho tìm/tạo thư mục (chạy trong lượt upload của worker, không ở lifespan): cố ý để mặc định.
        """THƯ MỤC con trực tiếp của `cha_id` mang đúng tên `ten`, chưa vào thùng rác (mỗi phần tử có `TRUONG_MUC`)."""

    def tao_thu_muc(self, ten: str, cha_id: str) -> str:
        """Tạo thư mục, trả id. Không nằm trong Shared Drive ⇒ `RuntimeError`."""

    def tai_len(self, duong_dan: Path, cha_id: str) -> str:
        """Tải file vào thư mục `cha_id`, trả id file. Trượt ⇒ `RuntimeError` (không im lặng)."""


def duong_dan_ten(drive: DriveTL, file_id: str) -> list[str]:
    """Tên từ `file_id` đi ngược lên gốc Shared Drive (phần tử đầu = chính nó). Lỗi Drive ném lên — người gọi quyết định."""
    ten: list[str] = []
    hien = file_id
    for _ in range(TOI_DA_DO_SAU):
        m = drive.lay_muc(hien)
        ten.append(m.get("name") or "")
        cha = (m.get("parents") or [None])[0]
        if not cha or cha == m.get("driveId"):  # gốc của Shared Drive (id gốc = driveId, không phải một "file")
            return ten
        hien = cha
    raise RuntimeError(f"cây thư mục sâu quá {TOI_DA_DO_SAU} cấp")


def ly_do_creative(drive: DriveTL, thu_muc_ra_id: str) -> str | None:
    """None = thư mục ra KHÔNG nằm trong cây `Creative`; chuỗi = lý do (nằm trong cây đó). Lỗi Drive (mạng/403/404/vòng cha) ném
    LÊN: người gọi phải phân biệt "chưa kiểm được, thử lại" với "kiểm xong và bị cấm"."""
    ten = duong_dan_ten(drive, thu_muc_ra_id)
    if any(t.strip().casefold() == TEN_CAY_CAM.casefold() for t in ten):
        return f"thư mục đầu ra nằm trong cây '{TEN_CAY_CAM}' ({' <- '.join(ten)})"
    return None


class DriveTLThat:
    """Bản chạy thật trên `DriveUploader`. Mỗi lần gọi dựng service MỚI (kết nối cũ chết vì Broken pipe sau khoảng nghỉ dài)."""

    def __init__(self, uploader=None):
        if uploader is None:
            from tiktok_music_downloader.gdrive_upload import DriveUploader
            uploader = DriveUploader()
        self._up = uploader

    def dang_cau_hinh(self) -> bool:
        return self._up.is_configured()

    def _svc(self):
        return self._up._build_service()

    def _svc_ngan(self):
        """Service có timeout socket ngắn (httplib2) — dùng cho lời gọi chạy ở cổng cấu hình."""
        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build

        # LƯU Ý: timeout httplib2 không bao trùm phân giải DNS (có thể treo lâu hơn 10 s) — chấp nhận, cổng chạy ở thread nền.
        http = google_auth_httplib2.AuthorizedHttp(self._up._get_credentials(), http=httplib2.Http(timeout=TIMEOUT_LAY_MUC_GIAY))
        return build("drive", "v3", http=http, cache_discovery=False)

    def lay_muc(self, file_id: str) -> dict:
        from googleapiclient.errors import HttpError
        try:
            return self._svc_ngan().files().get(fileId=file_id, fields=TRUONG_MUC, supportsAllDrives=True).execute()
        except HttpError as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                raise DriveTLKhongThay(file_id) from exc
            raise

    def tim_con_theo_ten(self, cha_id: str, ten: str) -> list[dict]:
        esc = ten.replace("\\", "\\\\").replace("'", "\\'")
        r = self._svc().files().list(
            q=f"name = '{esc}' and '{cha_id}' in parents and mimeType = '{MIME_THU_MUC}' and trashed = false",
            fields=f"files({TRUONG_MUC})", pageSize=10, corpora="allDrives",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        fs = r.get("files") or []
        if len(fs) > 1:  # hai thư mục cùng tên dưới một cha: ta lấy cái đầu — báo để người vận hành biết có bản trùng
            log.warning("thay logo: %d thư mục trùng tên dưới %s — dùng cái đầu tiên", len(fs), cha_id)
        return fs

    def tao_thu_muc(self, ten: str, cha_id: str) -> str:
        r = self._svc().files().create(body={"name": ten, "mimeType": MIME_THU_MUC, "parents": [cha_id]},
                                       fields="id,driveId", supportsAllDrives=True).execute()
        if not r.get("driveId") or not r.get("id"):  # rơi vào "My Drive" của service account
            raise RuntimeError("thư mục tạo xong nhưng không thuộc Shared Drive")
        return r["id"]

    def tai_len(self, duong_dan: Path, cha_id: str) -> str:
        kq = self._up.upload_file(duong_dan, parent_folder_id=cha_id)
        if not kq.ok:
            raise RuntimeError(kq.reason or str(kq.outcome))
        return kq.file_id
