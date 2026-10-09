"""Drive GIẢ cho luồng Thay logo — hiện thực `thay_logo.drive_tl.DriveTL` (mẫu: `tests/drive_gia_vao_bo.py`).

Test KHÔNG BAO GIỜ gọi Drive thật. Giữ một kho mục (thư mục + file) trong RAM, ghi lại mọi lời gọi (`goi`) để test khẳng định
"không gọi Drive ở ca này", và cho tiêm lỗi theo (phương thức, id | "*"). Đợt sau thêm phương thức vào `DriveTL` thì thêm vào đây.
"""
from __future__ import annotations

import copy
from pathlib import Path

from tiktok_music_downloader.thay_logo.drive_tl import MIME_THU_MUC, DriveTLKhongThay


class DriveGiaTL:
    def __init__(self):
        self.muc: dict[str, dict] = {}
        self.cau_hinh = True
        self.loi: dict[tuple[str, str], Exception] = {}
        self.goi: list[tuple[str, str]] = []
        self.da_tai_len: list[tuple[str, str]] = []  # (tên file, id thư mục cha)
        self._so = 0

    # --- dựng kho ---
    def them_thu_muc(self, fid, ten, cha=None, *, drive="D1", trashed=False):
        """`cha=None` ⇒ thư mục gốc của Shared Drive: `parents` = [driveId] như Drive thật."""
        self.muc[fid] = {"id": fid, "name": ten, "parents": [cha or drive], "driveId": drive,
                         "mimeType": MIME_THU_MUC, "trashed": trashed}
        return self.muc[fid]

    def so_lan(self, ten: str) -> int:
        return sum(1 for t, _ in self.goi if t == ten)

    def _loi(self, ten, arg):
        for khoa in ((ten, arg), (ten, "*")):
            if khoa in self.loi:
                raise self.loi[khoa]

    # --- DriveTL ---
    def dang_cau_hinh(self):
        return self.cau_hinh

    def lay_muc(self, file_id):
        self.goi.append(("lay_muc", file_id))
        self._loi("lay_muc", file_id)
        if file_id not in self.muc:
            raise DriveTLKhongThay(file_id)
        return copy.deepcopy(self.muc[file_id])

    def tim_con_theo_ten(self, cha_id, ten):
        self.goi.append(("tim_con_theo_ten", cha_id))
        self._loi("tim_con_theo_ten", cha_id)
        return [copy.deepcopy(m) for m in self.muc.values()
                if cha_id in m["parents"] and m["name"] == ten and m["mimeType"] == MIME_THU_MUC and not m["trashed"]]

    def tao_thu_muc(self, ten, cha_id):
        self.goi.append(("tao_thu_muc", cha_id))
        self._loi("tao_thu_muc", cha_id)
        self._so += 1
        cha = self.muc.get(cha_id)
        self.them_thu_muc(f"NEW{self._so}", ten, cha_id, drive=(cha or {}).get("driveId", "D1"))
        return f"NEW{self._so}"

    def tai_len(self, duong_dan, cha_id):
        self.goi.append(("tai_len", cha_id))
        self._loi("tai_len", cha_id)
        self._so += 1
        self.da_tai_len.append((Path(duong_dan).name, cha_id))
        return f"FILE{self._so}"
