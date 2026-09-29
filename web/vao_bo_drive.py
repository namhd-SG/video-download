"""Chỗ DUY NHẤT bộ kiểm "đã vào bộ" nói chuyện với Drive, và luật bằng chứng.

`DriveVaoBo` là giao diện nhỏ mà test thay bằng bản giả — KHÔNG test nào gọi Drive
thật. `DriveThat` là bản chạy thật, bọc `DriveUploader` (cùng credential và cùng
`trash_file` mà nút Loại đang dùng; hợp đồng 3 trạng thái của `trash_file` không
bị đụng).

Không có hàm nào ở đây xoá vĩnh viễn (`files().delete()`): service account chỉ
là Content manager, và dọn = bỏ vào Thùng rác.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol

from tiktok_music_downloader.gdrive_upload import DriveUploader, UploadOutcome

log = logging.getLogger("videodl.web.vao_bo")

# Dấu nguồn do Creative Desk gắn vào `properties` của bản copy (meta-ads #254).
# `properties` (thấy xuyên app), không phải `appProperties` (riêng tư theo app).
KHOA_DAU_NGUON = "videodesk_src"
TRUONG_TEP = "id,name,md5Checksum,size,parents,trashed,driveId,properties"
_ID_DRIVE = re.compile(r"[A-Za-z0-9_-]{10,128}")
# Trần an toàn cho vòng đọc trang: chống một `nextPageToken` lặp mãi.
TOI_DA_TRANG = 500
# Số id nguồn tối đa trong MỘT truy vấn `properties has … or …` (đo trên prod: N=200 ⇒
# đếm chính xác, 0,7 giây, độ dài q 17 196).
TOI_DA_ID_MOI_LO = 200


class DriveKhongThay(Exception):
    """Drive trả HTTP 404 ĐÍCH DANH cho tệp này. Mọi lỗi khác (403/5xx/timeout)
    KHÔNG phải lỗi này — chúng là "chưa đo được", không phải "không còn"."""


class DriveVaoBo(Protocol):
    def dang_cau_hinh(self) -> bool: ...
    def lay_tep(self, file_id: str) -> dict:
        """Siêu dữ liệu `TRUONG_TEP`. 404 ⇒ `DriveKhongThay`; lỗi khác ném nguyên."""
    def liet_ke_ban_sao_theo_dau(self, nguon_id: str,
                                 page_token: str | None) -> tuple[list[dict], str | None]:
        """MỘT trang bản copy chưa vào thùng rác mang `properties.videodesk_src =
        nguon_id`. Trả `(tệp, nextPageToken hoặc None)`."""
    def liet_ke_video_shared_drive(self, drive_id: str,
                                   page_token: str | None) -> tuple[list[dict], str | None]:
        """MỘT trang file video chưa vào thùng rác trên Shared Drive `drive_id`."""
    def liet_ke_ban_sao_theo_lo(self, nguon_ids: list[str],
                                page_token: str | None) -> tuple[list[dict], str | None]:
        """MỘT trang bản copy chưa vào thùng rác mang dấu nguồn thuộc BẤT KỲ id nào trong
        `nguon_ids` (≤ `TOI_DA_ID_MOI_LO`). Mỗi tệp trả kèm `properties.videodesk_src`."""
    def liet_ke_video_thung_rac(self, page_token: str | None) -> tuple[list[dict], str | None]:
        """MỘT trang file video ĐANG Ở Thùng rác (`trashed = true`) trên Shared Drive."""
    def ten_thu_muc(self, folder_id: str) -> str: ...
    def bo_vao_thung_rac(self, file_id: str) -> bool:
        """True CHỈ khi Drive báo ok. Chưa cấu hình / trượt ⇒ False."""


def id_drive_hop_le(file_id: object) -> bool:
    return isinstance(file_id, str) and _ID_DRIVE.fullmatch(file_id) is not None


def doc_het_trang(lay_trang, *, toi_da_trang: int = TOI_DA_TRANG) -> list[dict]:
    """Đọc MỌI trang của một truy vấn. `lay_trang(token) -> (tệp, token_tiếp)`.

    Dừng CHỈ khi hết token. Một trang RỖNG kèm `nextPageToken` KHÔNG phải là
    hết — Drive được phép trả trang rỗng giữa chừng. Token lặp lại hoặc quá trần
    trang ⇒ ném `RuntimeError` (= "chưa đo được"), không im lặng cắt ngang.
    """
    ra: list[dict] = []
    token: str | None = None
    da_thay: set[str] = set()
    for _ in range(toi_da_trang):
        tep, tiep = lay_trang(token)
        ra.extend(tep)
        if not tiep:
            return ra
        if tiep in da_thay:
            raise RuntimeError("nextPageToken lặp lại — đọc trang không kết thúc")
        da_thay.add(tiep)
        token = tiep
    raise RuntimeError(f"quá {toi_da_trang} trang — không đọc hết")


def ban_hop_le(nguon_id: str, nguon: dict | None, ban: dict, *,
               can_dau_nguon: bool) -> bool:
    """Bản `ban` có phải bằng chứng "video `nguon_id` đã được copy vào một bộ"?

    Đủ NĂM vế (thiếu vế nào cũng không đạt):
      1. `trashed = false` (bản đã vào thùng rác không còn trong bộ);
      2. `md5Checksum` trùng nguồn (không rỗng);
      3. `size` trùng nguồn (không rỗng);
      4. `parents` khác `parents` của nguồn (một "bản sao" nằm CÙNG folder với nguồn
         hay chính nguồn không phải bản trong bộ);
      5. `id` khác id nguồn.
    `can_dau_nguon`: bản tìm qua truy vấn `properties` còn phải mang đúng dấu
    `videodesk_src = nguon_id` (kiểm lại ở đây thay vì tin truy vấn).

    `nguon is None` (nguồn đã mất, 404) ⇒ không có gì để so md5/size/parents với,
    chỉ còn các vế 1, 5 và (nếu `can_dau_nguon`) dấu nguồn, cộng đòi bản có md5/size.
    """
    if ban.get("trashed") is not False:
        return False
    if ban.get("id") in (None, "", nguon_id):
        return False
    if can_dau_nguon and (ban.get("properties") or {}).get(KHOA_DAU_NGUON) != nguon_id:
        return False
    md5, size = ban.get("md5Checksum"), ban.get("size")
    if not md5 or not size:
        return False
    if nguon is None:
        return bool(ban.get("parents"))
    if md5 != nguon.get("md5Checksum") or str(size) != str(nguon.get("size")):
        return False
    cha_ban = set(ban.get("parents") or [])
    return bool(cha_ban) and cha_ban != set(nguon.get("parents") or [])


_MA_BO = re.compile(r"P?N\.\d{4}[A-Z]?")


def ma_bo_tu_ten(ten_folder: str) -> str:
    """Mã bộ để HIỆN: phần tên folder trước `" - "` nếu nó có dạng `N.2809C` /
    `PN.2209E`; ngược lại lấy CẢ tên. Nguồn sự thật vẫn là `folder_id`."""
    dau = ten_folder.split(" - ", 1)[0].strip()
    return dau if _MA_BO.fullmatch(dau) else ten_folder


def chon_folder(ban: dict, nguon: dict | None) -> str | None:
    """Folder chứa bản sao (ưu tiên cha KHÔNG phải cha của nguồn)."""
    cha = list(ban.get("parents") or [])
    if not cha:
        return None
    cha_nguon = set((nguon or {}).get("parents") or [])
    return next((p for p in cha if p not in cha_nguon), cha[0])


class DriveThat:
    """Bản chạy thật. Lỗi Drive ném nguyên (trừ 404 ⇒ `DriveKhongThay`)."""

    def __init__(self, uploader: DriveUploader | None = None):
        self._up = uploader or DriveUploader()

    def dang_cau_hinh(self) -> bool:
        return self._up.is_configured()

    def _svc(self):
        # Dựng lại dịch vụ MỖI lần (`_build_service` cố ý không cache: kết nối
        # cũ chết vì Broken pipe sau khoảng nghỉ dài giữa hai lượt kiểm).
        return self._up._build_service()

    def lay_tep(self, file_id: str) -> dict:
        from googleapiclient.errors import HttpError
        try:
            return self._svc().files().get(
                fileId=file_id, fields=TRUONG_TEP, supportsAllDrives=True).execute()
        except HttpError as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                raise DriveKhongThay(file_id) from exc
            raise

    def liet_ke_ban_sao_theo_dau(self, nguon_id: str, page_token: str | None):
        if not id_drive_hop_le(nguon_id):
            # Id đi vào chuỗi truy vấn: chỉ nhận đúng hình dạng id Drive.
            raise ValueError("id nguồn sai hình dạng — không dựng truy vấn")
        q = (f"properties has {{key='{KHOA_DAU_NGUON}' and value='{nguon_id}'}} "
             "and trashed = false")
        r = self._svc().files().list(
            q=q, corpora="allDrives", includeItemsFromAllDrives=True,
            supportsAllDrives=True, pageSize=100, pageToken=page_token,
            fields=f"nextPageToken,files({TRUONG_TEP})").execute()
        return r.get("files", []), r.get("nextPageToken")

    def liet_ke_video_shared_drive(self, drive_id: str, page_token: str | None):
        r = self._svc().files().list(
            corpora="drive", driveId=drive_id, includeItemsFromAllDrives=True,
            supportsAllDrives=True, pageSize=1000, pageToken=page_token,
            q="trashed = false and mimeType contains 'video/'",
            fields=f"nextPageToken,files({TRUONG_TEP})").execute()
        return r.get("files", []), r.get("nextPageToken")

    def liet_ke_ban_sao_theo_lo(self, nguon_ids: list[str], page_token: str | None):
        if not nguon_ids or len(nguon_ids) > TOI_DA_ID_MOI_LO:
            raise ValueError(f"lô id nguồn phải 1..{TOI_DA_ID_MOI_LO}")
        if not all(id_drive_hop_le(i) for i in nguon_ids):
            raise ValueError("id nguồn sai hình dạng — không dựng truy vấn")
        dieu_kien = " or ".join(
            f"properties has {{key='{KHOA_DAU_NGUON}' and value='{i}'}}" for i in nguon_ids)
        r = self._svc().files().list(
            q=f"({dieu_kien}) and trashed = false", corpora="allDrives",
            includeItemsFromAllDrives=True, supportsAllDrives=True, pageSize=1000,
            pageToken=page_token, fields="nextPageToken,files(id,properties)").execute()
        return r.get("files", []), r.get("nextPageToken")

    def liet_ke_video_thung_rac(self, page_token: str | None):
        r = self._svc().files().list(
            q="trashed = true and mimeType contains 'video/'", corpora="allDrives",
            includeItemsFromAllDrives=True, supportsAllDrives=True, pageSize=1000,
            pageToken=page_token, fields="nextPageToken,files(id)").execute()
        return r.get("files", []), r.get("nextPageToken")

    def ten_thu_muc(self, folder_id: str) -> str:
        return self._svc().files().get(
            fileId=folder_id, fields="name", supportsAllDrives=True).execute()["name"]

    def bo_vao_thung_rac(self, file_id: str) -> bool:
        return self._up.trash_file(file_id).outcome is UploadOutcome.SUCCESS
