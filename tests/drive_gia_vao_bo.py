"""Drive GIẢ cho bộ kiểm "đã vào bộ" — hiện thực `web.vao_bo_drive.DriveVaoBo`.

Test KHÔNG BAO GIỜ gọi Drive thật. Bản giả giữ một kho tệp trong RAM, phân trang
thật (kể cả trang rỗng kèm token), ghi lại mọi lời gọi để test khẳng định "không
gọi Drive ở ca này", và cho tiêm lỗi theo (phương thức, id).
"""
from __future__ import annotations

import copy

from web.vao_bo_drive import KHOA_DAU_NGUON, DriveKhongThay


class DriveGia:
    def __init__(self, *, trang: int = 100, trang_rong_dau: bool = False):
        self.tep: dict[str, dict] = {}
        self.ten: dict[str, str] = {}
        self.cau_hinh = True
        self.trang = trang
        self.trang_rong_dau = trang_rong_dau
        self.loi: dict[tuple[str, str], Exception] = {}
        self.trash_ket_qua: dict[str, bool] = {}
        self.goi: list[tuple[str, str]] = []

    # --- dựng kho ---
    def them_nguon(self, fid, *, md5="M1", size="1000", parents=("SRC",), drive="D1",
                   trashed=False):
        self.tep[fid] = {"id": fid, "md5Checksum": md5, "size": size, "parents": list(parents),
                         "trashed": trashed, "driveId": drive, "properties": {}}
        return self.tep[fid]

    def them_ban(self, fid, nguon_id, *, folder="BO1", md5=None, size=None, trashed=False,
                 dau=True, parents=None, drive="D1"):
        n = self.tep.get(nguon_id, {})
        self.tep[fid] = {
            "id": fid, "md5Checksum": md5 if md5 is not None else n.get("md5Checksum"),
            "size": size if size is not None else n.get("size"),
            "parents": list(parents) if parents is not None else [folder],
            "trashed": trashed, "driveId": drive,
            "properties": {KHOA_DAU_NGUON: nguon_id} if dau else {}}
        return self.tep[fid]

    def dat_ten_thu_muc(self, folder, ten):
        self.ten[folder] = ten

    def so_lan(self, ten: str) -> int:
        return sum(1 for t, _ in self.goi if t == ten)

    # --- DriveVaoBo ---
    def dang_cau_hinh(self):
        return self.cau_hinh

    def _loi(self, ten, arg):
        if (ten, arg) in self.loi:
            raise self.loi[(ten, arg)]

    def lay_tep(self, file_id):
        self.goi.append(("lay_tep", file_id))
        self._loi("lay_tep", file_id)
        if file_id not in self.tep:
            raise DriveKhongThay(file_id)
        return copy.deepcopy(self.tep[file_id])

    def liet_ke_ban_sao_theo_dau(self, nguon_id, page_token):
        self.goi.append(("liet_ke_ban_sao", nguon_id))
        self._loi("liet_ke_ban_sao", nguon_id)
        khop = [copy.deepcopy(t) for t in self.tep.values()
                if t["properties"].get(KHOA_DAU_NGUON) == nguon_id and not t["trashed"]]
        return self._trang(khop, page_token)

    def liet_ke_video_shared_drive(self, drive_id, page_token):
        self.goi.append(("liet_ke_drive", drive_id))
        self._loi("liet_ke_drive", drive_id)
        khop = [copy.deepcopy(t) for t in self.tep.values()
                if t.get("driveId") == drive_id and not t["trashed"] and t.get("md5Checksum")]
        return self._trang(khop, page_token)

    def _trang(self, khop, token):
        """Trang giả; token = số thứ tự trang. `trang_rong_dau`: trang đầu RỖNG mà vẫn
        có token (Drive được phép làm vậy) — bộ đọc không được coi đó là hết."""
        chunks = [khop[i:i + self.trang] for i in range(0, len(khop), self.trang)] or [[]]
        if self.trang_rong_dau:
            chunks = [[]] + chunks
        k = 0 if token is None else int(token)
        return chunks[k], (str(k + 1) if k + 1 < len(chunks) else None)

    def ten_thu_muc(self, folder_id):
        self.goi.append(("ten_thu_muc", folder_id))
        self._loi("ten_thu_muc", folder_id)
        return self.ten[folder_id]

    def bo_vao_thung_rac(self, file_id):
        self.goi.append(("bo_vao_thung_rac", file_id))
        self._loi("bo_vao_thung_rac", file_id)
        ok = self.trash_ket_qua.get(file_id, True)
        if ok and file_id in self.tep:
            self.tep[file_id]["trashed"] = True
        return ok
