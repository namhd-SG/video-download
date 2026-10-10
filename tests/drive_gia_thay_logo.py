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
        # Đợt áp vào bộ: `loi_sau` ném SAU KHI thao tác GHI đã có hiệu lực (giả tiến trình chết ngay sau khi Drive trả 200, trước khi
        # kịp ghi DB). `sau_thao_tac`: hàm gọi sau MỖI thao tác ghi (test cài bộ kiểm bất biến vết). `copy_mang_properties`: bản copy
        # mang theo `properties` của file nguồn (Drive thật CHƯA đo — code phải kiểm sau copy).
        self.loi_sau: dict[tuple[str, str], Exception] = {}
        self.sau_thao_tac: list = []
        self.copy_mang_properties = False
        # Chỉ mục tìm kiếm TRỄ (như Drive thật ngay sau một lần copy): `tim_theo_the` (truy vấn `appProperties has`) KHÔNG thấy bản vừa
        # copy; `liet_ke_con` (liệt theo thư mục) và `lay_muc` thì thấy.
        self.tre_chi_muc = False
        self._chua_vao_chi_muc: set[str] = set()
        self._so = 0

    # --- dựng kho ---
    def them_thu_muc(self, fid, ten, cha=None, *, drive="D1", trashed=False):
        """`cha=None` ⇒ thư mục gốc của Shared Drive: `parents` = [driveId] như Drive thật."""
        self.muc[fid] = {"id": fid, "name": ten, "parents": [cha or drive], "driveId": drive,
                         "mimeType": MIME_THU_MUC, "trashed": trashed}
        return self.muc[fid]

    def them_file(self, fid, ten, cha=None, *, size=1000, mime="video/mp4", md5="MD5A", drive="D1", trashed=False,
                  properties=None, app_properties=None):
        """File trong thư mục `cha` (None ⇒ gốc Shared Drive). `size=None` ⇒ không có trường size (như file Google-native);
        `md5=None` ⇒ không có `md5Checksum`. Drive trả size là CHUỖI."""
        m = {"id": fid, "name": ten, "parents": [cha or drive], "driveId": drive, "mimeType": mime, "trashed": trashed}
        if size is not None:
            m["size"] = str(size)
        if md5 is not None:
            m["md5Checksum"] = md5
        if properties:
            m["properties"] = dict(properties)
        if app_properties:
            m["appProperties"] = dict(app_properties)
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

    # --- đợt áp vào bộ (thao tác GHI) ---
    def _xong_ghi(self, ten, arg):
        for f in self.sau_thao_tac:
            f(self, ten, arg)
        for khoa in ((ten, arg), (ten, "*")):
            if khoa in self.loi_sau:
                raise self.loi_sau.pop(khoa)  # một lần: lần chạy lại không chết ở cùng chỗ

    def _can(self, fid):
        if fid in self.khong_quyen:
            raise DriveTLKhongQuyen(fid)
        if fid not in self.muc:
            raise DriveTLKhongThay(fid)
        return self.muc[fid]

    def doi_cha(self, file_id, them, bo):
        """Như Drive thật nhưng KHẮT KHE: `bo` không phải cha hiện tại ⇒ NÉM (Drive thật có thể trả 200 — bản giả dễ dãi sẽ cho xanh
        giả khi người gọi quên probe `parents`)."""
        self.goi.append(("doi_cha", file_id))
        self._loi("doi_cha", file_id)
        m = self._can(file_id)
        if bo not in m["parents"]:
            raise RuntimeError(f"doi_cha: {bo} không phải cha hiện tại của {file_id} ({m['parents']})")
        m["parents"] = [them] + [p for p in m["parents"] if p not in (bo, them)]
        self._xong_ghi("doi_cha", file_id)

    def doi_ten(self, file_id, ten):
        self.goi.append(("doi_ten", file_id))
        self._loi("doi_ten", file_id)
        self._can(file_id)["name"] = ten
        self._xong_ghi("doi_ten", file_id)

    def sao_chep(self, file_id, cha_id, ten, the):
        self.goi.append(("sao_chep", file_id))
        self._loi("sao_chep", file_id)
        nguon = self._can(file_id)
        self._so += 1
        moi = f"COPY{self._so:04d}" + "c" * 10
        cha = self.muc.get(cha_id) or {}
        self.them_file(moi, ten, cha_id, size=nguon.get("size"), md5=nguon.get("md5Checksum"), mime=nguon.get("mimeType", "video/mp4"),
                       drive=cha.get("driveId", "D1"), app_properties=dict(the),
                       properties=nguon.get("properties") if self.copy_mang_properties else None)
        if self.tre_chi_muc:
            self._chua_vao_chi_muc.add(moi)
        self._xong_ghi("sao_chep", file_id)
        return moi

    def tim_theo_the(self, cha_id, khoa, gia_tri):
        self.goi.append(("tim_theo_the", cha_id))
        self._loi("tim_theo_the", cha_id)
        return [copy.deepcopy(m) for m in self.muc.values()
                if cha_id in m["parents"] and not m["trashed"] and (m.get("appProperties") or {}).get(khoa) == gia_tri
                and m["id"] not in self._chua_vao_chi_muc]

    def vao_thung_rac(self, file_id):
        self.goi.append(("vao_thung_rac", file_id))
        self._loi("vao_thung_rac", file_id)
        self._can(file_id)["trashed"] = True
        self._xong_ghi("vao_thung_rac", file_id)
