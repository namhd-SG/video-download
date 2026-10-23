"""Điều phối một lần chạy: video ⇒ chữ ký ⇒ tìm theo hop ⇒ ảnh bìa ⇒ hạng ⇒ mở rộng ⇒ kết quả.

Đối chứng dương KHÔNG tự chấm (agy plan-R1b ĐK5): chữ ký tính từ lượt bóc RIÊNG của khung đầu vào; mỗi lô ảnh bìa gửi agy
kèm bản sao các khung khớp chữ ký (ctrl) — luật cổng nằm ở `doi_chung.py`. Mọi link xuất ra phải đến từ một lô có ctrl
đạt (lọc sai là hỏng âm thầm: thà không ra link còn hơn ra link sai mà trông như đúng).
"""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import agy_boc, anh_bia, khung
from .cham import NGUONG_MAC_DINH, ChuKy, chu_ky
# ChuKyKhongOnDinh / VideoHuongDan / chon_khung_doi_chung nhập lại ở đây cho CLI và test (trước nằm trong file này).
from .doi_chung import ChuKyKhongOnDinh, VideoHuongDan, cham_lo, chon_khung_doi_chung, tin_ca_luot  # noqa: F401
from .khu_trung import MucKhuTrung, khu_trung
from .mo_rong import sinh_mo_rong
from .nguon_tim import BiCaptcha, HetLuot, LoiMoTrang, UngVien
from .truong import TruongAnh
from .truy_van import TruyVan, sinh_truy_van


def bao_ngay(chu: str) -> None:
    """In và đẩy ra ngay: chạy với stdout chuyển hướng thì print bị gom, người ngồi máy tưởng công cụ treo (23/10)."""
    print(chu, flush=True)


LINK_MOI_KHOI = 50   # trần link/job của Video Desk (`web/app.py` MAX_LINK_MOT_JOB)
_DANG_CAU_TRUC = re.compile(r"\b\d+\s*poses?\b|kolase|collage", re.I)


@dataclass
class KetQua:
    chu_ky: ChuKy | None = None
    truy_van: list[dict] = field(default_factory=list)       # {text, nhom, lang, loai, hop, so_link, ghi_chu}
    ung_vien: list[dict] = field(default_factory=list)       # UngVien + hang + truong + co
    bo: dict[str, str] = field(default_factory=dict)         # video_id ⇒ lý do bị bỏ
    lo_ctrl: list[dict] = field(default_factory=list)        # mỗi lượt agy: {lo, lan, ten_ctrl[], hang_ctrl[], tin}
    so_lo: int = 0                                            # lô logic xuyên các hop
    so_lo_bo: int = 0                                         # lô ctrl vẫn trượt sau chấm lại ⇒ ảnh không có hạng
    so_lan_mo_trang: int = 0
    dung_vi: str = ""                                         # lý do dừng sớm, nếu có
    bi_captcha: bool = False
    loi_trang: bool = False
    tin_duoc: bool = True

    @property
    def rong(self) -> bool:
        """Không có ứng viên nào: KHÔNG phải "chạy xong, 0 kết quả" — thường là feed bị chặn/rỗng (Pha 4 22/10: 12/12)."""
        return not self.ung_vien

    def giu(self, nguong: frozenset[str]) -> list[dict]:
        return [u for u in self.ung_vien if u["hang"] in nguong]


def _bo_truong(t: TruongAnh | None) -> dict | None:
    return None if t is None else asdict(t)


def chay(video: Path, ra: Path, *, tao_nguon: Callable[[], object], so_truy_van: int = 6, so_hop: int = 2,
         truy_van_tay: list[str] | None = None, nguong: frozenset[str] = NGUONG_MAC_DINH,
         gian_cach_anh: float = 4.0, model: str = agy_boc.MODEL_MAC_DINH,
         bao: Callable[[str], None] = bao_ngay) -> KetQua:
    kq = KetQua()
    ra.mkdir(parents=True, exist_ok=True)
    thu_khung, thu_bia = ra / "khung", ra / "bia"
    don_dau_ra_cu(ra)
    bao("Đang trích khung video và nhờ agy đọc (≈1 phút)…")
    ds_khung = khung.trich_khung(video, thu_khung)
    if not ds_khung:
        raise RuntimeError("không trích được khung nào từ video đầu vào")
    truong_khung = agy_boc.boc_truong(ds_khung, ra, model, ten="agy-truong-dau-vao")
    kq.chu_ky = ck = chu_ky(list(truong_khung.values()))
    bao(f"Chữ ký dạng: {ck}")
    ds_ctrl = chon_khung_doi_chung(ds_khung, truong_khung, ck, nguong)

    if truy_van_tay:
        # Người chạy tự đưa key hop 1 (vd từ hồ sơ trend): thay HẲN key tự sinh — để so A/B chỉ đổi 1 biến.
        khong_trung = list(dict.fromkeys(truy_van_tay))
        if len(khong_trung) > so_truy_van:
            bao(f"Chỉ chạy {so_truy_van}/{len(khong_trung)} key đưa tay (--so-truy-van); bỏ: {khong_trung[so_truy_van:]}")
        hang_doi = [TruyVan(t, "tay", "goc") for t in khong_trung[:so_truy_van]]
    else:
        hang_doi = sinh_truy_van(ck, agy_boc.goi_y_tu_khoa(ds_khung, ra, model), so_truy_van)
    da_dung: set[str] = set()
    theo_id: dict[str, UngVien] = {}
    with tao_nguon() as nguon:
        for hop in range(1, so_hop + 1):
            moi: list[UngVien] = []
            for tv in hang_doi:
                da_dung.add(tv.text)
                try:
                    tim_duoc, ghi_chu = nguon.tim(tv)
                except HetLuot as exc:
                    kq.dung_vi = str(exc)
                    kq.bi_captcha = isinstance(exc, BiCaptcha)
                    kq.loi_trang = isinstance(exc, LoiMoTrang)
                    break
                kq.truy_van.append({**asdict(tv), "hop": hop, "so_link": len(tim_duoc), "ghi_chu": ghi_chu})
                bao(f"[hop {hop}] tìm '{tv.text}': {len(tim_duoc)} link {('(' + ghi_chu + ')') if ghi_chu else ''}")
                for u in tim_duoc:
                    if u.video_id not in theo_id:
                        theo_id[u.video_id] = u
                        moi.append(u)
            kq.so_lan_mo_trang = getattr(nguon, "da_mo", 0)
            bao(f"[hop {hop}] tải {len(moi)} ảnh bìa mới (≈{len(moi) * gian_cach_anh:.0f} giây; cửa sổ Chrome đứng yên lúc này)…")
            bia, loi = anh_bia.tai_anh_bia([(u.video_id, u.cover_url) for u in moi], thu_bia, gian_cach_anh)
            kq.bo.update(loi)
            giu, bo = khu_trung([MucKhuTrung(u.video_id, bia[u.video_id]) for u in moi if u.video_id in bia])
            kq.bo.update(bo)
            cham = (cham_lo({m.video_id: bia[m.video_id] for m in giu}, ds_ctrl, thu_bia, ck, kq, model, nguong)
                    if giu else {})
            for m in giu:
                u = theo_id[m.video_id]
                h, t = cham[m.video_id]
                co = []
                if h == "1" and ck.bac == ">=3" and t is not None and t.so_ban_sao == 1 and _DANG_CAU_TRUC.search(u.caption):
                    co.append("nghi bung pose sau giay 0")
                kq.ung_vien.append({**asdict(u), "hang": h, "truong": _bo_truong(t), "co": co, "hop": hop})
            if kq.dung_vi or hop == so_hop:
                break
            dat = [u["caption"] for u in kq.ung_vien if u["hang"] in nguong]
            hang_doi = sinh_mo_rong(dat, da_dung, so_truy_van)
            if not hang_doi:
                break
    # Tính SAU khi đã gộp mọi ứng viên: vế "còn link" cần danh sách đầy đủ (agy R2b).
    kq.tin_duoc = tin_ca_luot(kq.so_lo, kq.so_lo_bo, len(kq.giu(nguong)))
    return kq


_TEP_LINK = re.compile(r"^links(-ket-qua|-huong-dan)?(-\d\d)?\.txt$")


def _xoa_tep_link(ra: Path) -> None:
    """Chỉ xoá ĐÚNG file công cụ ghi (`links.txt`, `links-NN.txt`) và chỉ file thường — `links-cua-toi.txt` hay thư mục
    trùng tên là của người dùng (review 23/10 H-a)."""
    for p in ra.iterdir():
        if _TEP_LINK.match(p.name) and p.is_file() and not p.is_symlink():
            p.unlink()


TIEU_DE_TRANG = "<title>Tìm video cùng dạng</title>"   # `trang.render` ghi; nhận diện index.html của công cụ


def _cua_cong_cu(p: Path) -> bool:
    """`ket-qua.json`/`index.html` do công cụ ghi? Nhận theo NỘI DUNG — file trùng tên của người dùng không bị xoá."""
    if not p.is_file() or p.is_symlink():
        return False
    try:
        chu = p.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    if p.suffix == ".html":
        return TIEU_DE_TRANG in chu
    try:
        du_lieu = json.loads(chu)
    except json.JSONDecodeError:
        return False
    return isinstance(du_lieu, dict) and {"chu_ky", "lo_ctrl", "ung_vien"} <= du_lieu.keys()


def don_dau_ra_cu(ra: Path) -> None:
    """Xoá link, ket-qua.json, index.html và khung của lần chạy trước trong cùng `--ra`: lần này thoát lỗi (vd mã 6 thoát
    trước khi ghi gì) thì file cũ KHÔNG được nằm lại trông như kết quả mới (review 23/10 H1, M4). `khung/` chỉ bị xoá khi
    có file đánh dấu do công cụ tạo (`--ra ~/Downloads` không mất `~/Downloads/khung/` của người dùng)."""
    _xoa_tep_link(ra)
    for ten in ("ket-qua.json", "index.html"):
        if _cua_cong_cu(ra / ten):
            (ra / ten).unlink()
    if (ra / "khung" / khung.DANH_DAU).is_file():
        shutil.rmtree(ra / "khung", ignore_errors=True)


def _ghi_tap(ra: Path, goc: str, links: list[str]) -> list[Path]:
    """`<goc>.txt` + `<goc>-NN.txt` mỗi file ≤50 khi vượt trần job của Video Desk."""
    tep = [ra / f"{goc}.txt"]
    tep[0].write_text("\n".join(links) + ("\n" if links else ""))
    if len(links) > LINK_MOI_KHOI:
        for i in range(0, len(links), LINK_MOI_KHOI):
            p = ra / f"{goc}-{i // LINK_MOI_KHOI + 1:02d}.txt"
            p.write_text("\n".join(links[i:i + LINK_MOI_KHOI]) + "\n")
            tep.append(p)
    return tep


def ghi_links(kq: KetQua, ra: Path, nguong: frozenset[str] = NGUONG_MAC_DINH) -> list[Path]:
    """`links.txt` (mọi link đạt) + `links-ket-qua.txt` (hạng 3) + `links-huong-dan.txt` (hạng 2A) — user chốt 23/10 tìm
    "cả 2" — nhóm rỗng thì không ghi. KHÔNG ghi gì nếu chạy không tin được."""
    _xoa_tep_link(ra)
    if not kq.tin_duoc or kq.rong or kq.bi_captcha or kq.loi_trang:
        return []
    giu = kq.giu(nguong)
    tep = _ghi_tap(ra, "links", [u["url"] for u in giu])
    for goc, h in (("links-ket-qua", "3"), ("links-huong-dan", "2A")):
        nhom = [u["url"] for u in giu if u["hang"] == h]
        if nhom:
            tep += _ghi_tap(ra, goc, nhom)
    return tep
