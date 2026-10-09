"""Drive GIẢ cho luồng Thay logo — hiện thực `thay_logo.drive_tl.DriveTL` (mẫu: `tests/drive_gia_vao_bo.py`).

Test KHÔNG BAO GIỜ gọi Drive thật. Giữ một kho mục (thư mục + file) trong RAM, ghi lại mọi lời gọi (`goi`) để test khẳng định
"không gọi Drive ở ca này", và cho tiêm lỗi theo (phương thức, id | "*"). Đợt sau thêm phương thức vào `DriveTL` thì thêm vào đây.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from tiktok_music_downloader.thay_logo.drive_tl import MIME_THU_MUC, DriveTLKhongQuyen, DriveTLKhongThay


class DriveGiaTL:
    def __init__(self):
        self.muc: dict[str, dict] = {}
        self.cau_hinh = True
        self.loi: dict[tuple[str, str], Exception] = {}
        self.goi: list[tuple[str, str]] = []
        self.da_tai_len: list[tuple[str, str]] = []  # (tên file, id thư mục cha)
        self.khong_quyen: set[str] = set()  # id mà tài khoản máy KHÔNG được chia sẻ ⇒ 403 như Drive thật
        self.email = "may@du-an.iam.gserviceaccount.com"
        self.cham: dict[str, float] = {}  # id ⇒ số giây `lay_muc_day_du` ngủ trước khi trả (giả Drive chậm)
        self._so = 0

    # --- dựng kho ---
    def them_thu_muc(self, fid, ten, cha=None, *, drive="D1", trashed=False):
        """`cha=None` ⇒ thư mục gốc của Shared Drive: `parents` = [driveId] như Drive thật."""
        self.muc[fid] = {"id": fid, "name": ten, "parents": [cha or drive], "driveId": drive,
                         "mimeType": MIME_THU_MUC, "trashed": trashed}
        return self.muc[fid]

    def them_file(self, fid, ten, cha=None, *, size=1000, mime="video/mp4", drive="D1", trashed=False):
        """File trong thư mục `cha` (None ⇒ gốc Shared Drive). `size=None` ⇒ không có trường size (như file Google-native)."""
        m = {"id": fid, "name": ten, "parents": [cha or drive], "driveId": drive, "mimeType": mime, "trashed": trashed}
        if size is not None:
            m["size"] = str(size)  # Drive trả size là CHUỖI
        self.muc[fid] = m
        return m

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

    def lay_muc_day_du(self, file_id):
        self.goi.append(("lay_muc_day_du", file_id))
        if file_id in self.cham:
            time.sleep(self.cham[file_id])
        self._loi("lay_muc_day_du", file_id)
        if file_id in self.khong_quyen:
            raise DriveTLKhongQuyen(file_id)
        if file_id not in self.muc:
            raise DriveTLKhongThay(file_id)
        return copy.deepcopy(self.muc[file_id])

    def liet_ke_con(self, cha_id, toi_da):
        """Chỉ con TRỰC TIẾP. Trả cả mục đã vào thùng rác (Drive thật lọc bằng `q`; ở đây để test bộ lọc của người gọi)."""
        self.goi.append(("liet_ke_con", cha_id))
        self._loi("liet_ke_con", cha_id)
        if cha_id in self.khong_quyen:
            raise DriveTLKhongQuyen(cha_id)
        if cha_id not in self.muc:
            raise DriveTLKhongThay(cha_id)
        return [copy.deepcopy(m) for m in self.muc.values() if cha_id in m["parents"]][:toi_da]

    def email_dich_vu(self):
        return self.email
