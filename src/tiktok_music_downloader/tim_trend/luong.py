"""Điều phối một lần chạy: video ⇒ chữ ký ⇒ tìm theo hop ⇒ ảnh bìa ⇒ hạng ⇒ mở rộng ⇒ kết quả.

Đối chứng dương KHÔNG tự chấm (agy plan-R1b ĐK5): chữ ký tính từ lượt bóc RIÊNG của khung đầu vào; mỗi lô ảnh bìa gửi agy
có thêm 1 bản sao khung khớp chữ ký của video đầu vào (ctrl, tên số và vị trí ngẫu nhiên như ảnh bìa; tên ghi ở
`lo_ctrl`). ctrl trong lô không ra hạng 3 ⇒ lô đó không tin được ⇒ cả lần
chạy KHÔNG xuất `links.txt` (lọc sai là hỏng âm thầm: thà không ra link còn hơn ra link sai mà trông như đúng).
"""
from __future__ import annotations

import json
import random
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import agy_boc, anh_bia, khung
from .cham import NGUONG_MAC_DINH, ChuKy, chu_ky, hang
from .khu_trung import MucKhuTrung, khu_trung
from .mo_rong import sinh_mo_rong
from .nguon_tim import BiCaptcha, HetLuot, LoiMoTrang, UngVien
from .truong import TruongAnh
from .truy_van import TruyVan, sinh_truy_van

def chon_khung_doi_chung(ds_khung: list[Path], truong_khung: dict[str, TruongAnh], ck: ChuKy) -> Path:
    """Khung đối chứng phải là khung ĐÃ khớp chữ ký (hạng 3), ưu tiên khung giữa.

    Ca 3 (23/10): video 2 cảnh (màn hình concert + hướng dẫn trên điện thoại) ⇒ chữ ký theo đa số = cảnh concert, nhưng
    khung giữa là cảnh điện thoại ⇒ ctrl ra hạng 1/0 ở mọi lô ⇒ cả lần chạy bị chặn dù agy đọc đúng.
    Không khung nào khớp ⇒ chữ ký không ổn định (video nhiều cảnh khác hẳn nhau) ⇒ dừng, không chấm với thước hỏng.
    """
    giua = len(ds_khung) // 2
    thu_tu = [ds_khung[giua]] + [k for i, k in enumerate(ds_khung) if i != giua]
    for k in thu_tu:
        t = truong_khung.get(k.stem)
        if t is not None and hang(t, ck) == "3":
            return k
    doc_duoc = [truong_khung[k.stem] for k in ds_khung if k.stem in truong_khung]
    if doc_duoc and all(t.la_tutorial for t in doc_duoc):
        raise VideoHuongDan("mọi khung của video đầu vào đều là cảnh hướng dẫn — cắt cảnh không giúp được")
    raise ChuKyKhongOnDinh("không khung nào của video đầu vào khớp chữ ký của chính nó — video nhiều cảnh khác hẳn nhau")


class ChuKyKhongOnDinh(RuntimeError):
    """Chữ ký dạng không đại diện được cho video đầu vào (không khung nào tự khớp)."""


class VideoHuongDan(ChuKyKhongOnDinh):
    """Video đầu vào chỉ có cảnh hướng dẫn: khung nào cũng ra 2A nên không có khung đối chứng hạng 3 (review 23/10 M3)."""


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
    lo_ctrl: list[dict] = field(default_factory=list)        # {lo, hang_ctrl}
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


def _ten_ctrl(rnd: random.Random, da_co: set[str]) -> str:
    """Tên ctrl cùng mẫu với ảnh bìa (`<19 chữ số>`): tên `ctrl-N` lộ cho agy biết ảnh nào là đối chứng ⇒ chấm không còn mù."""
    while True:
        ten = str(rnd.randrange(7 * 10**18, 8 * 10**18))
        if ten not in da_co:
            return ten


def _cham_lo(bia: dict[str, Path], ctrl_goc: Path, thu_muc: Path, ck: ChuKy, kq: KetQua,
             model: str, rnd: random.Random | None = None) -> dict[str, tuple[str | None, TruongAnh | None]]:
    """Chấm ảnh bìa theo lô ≤ LO_TOI_DA-1, mỗi lô kèm 1 ctrl đặt tên và vị trí ngẫu nhiên. Trả {video_id: (hạng, trường)}."""
    rnd = rnd or random.Random()
    ra: dict[str, tuple[str | None, TruongAnh | None]] = {}
    ids = list(bia)
    co = agy_boc.LO_TOI_DA - 1
    for k in range(0, len(ids), co):
        nhom = ids[k:k + co]
        ctrl = thu_muc / f"{_ten_ctrl(rnd, {p.stem for p in thu_muc.glob('*.jpg')})}.jpg"
        shutil.copyfile(ctrl_goc, ctrl)
        lo = [bia[i] for i in nhom]
        lo.insert(rnd.randrange(len(lo) + 1), ctrl)
        print(f"agy chấm lô {len(kq.lo_ctrl) + 1}: {len(nhom)} ảnh bìa (≈1–2 phút)…", flush=True)
        truong = agy_boc.boc_truong(lo, thu_muc, model, ten=f"agy-truong-lo-{len(kq.lo_ctrl)}")
        h_ctrl = hang(truong[ctrl.stem], ck) if ctrl.stem in truong else None
        kq.lo_ctrl.append({"lo": len(kq.lo_ctrl), "ten_ctrl": ctrl.stem, "hang_ctrl": h_ctrl})
        tin = h_ctrl == "3"
        kq.tin_duoc = kq.tin_duoc and tin
        for vid in nhom:
            t = truong.get(bia[vid].stem)
            ra[vid] = ((hang(t, ck) if (t is not None and tin) else None), t)
    return ra


def chay(video: Path, ra: Path, *, tao_nguon: Callable[[], object], so_truy_van: int = 6, so_hop: int = 2,
         truy_van_tay: list[str] | None = None,
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
    ctrl_goc = chon_khung_doi_chung(ds_khung, truong_khung, ck)

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
            cham = _cham_lo({m.video_id: bia[m.video_id] for m in giu}, ctrl_goc, thu_bia, ck, kq, model) if giu else {}
            for m in giu:
                u = theo_id[m.video_id]
                h, t = cham[m.video_id]
                co = []
                if h == "1" and ck.bac == ">=3" and t is not None and t.so_ban_sao == 1 and _DANG_CAU_TRUC.search(u.caption):
                    co.append("nghi bung pose sau giay 0")
                kq.ung_vien.append({**asdict(u), "hang": h, "truong": _bo_truong(t), "co": co, "hop": hop})
            if kq.dung_vi or hop == so_hop:
                break
            dat = [u["caption"] for u in kq.ung_vien if u["hang"] in ("3", "2A")]
            hang_doi = sinh_mo_rong(dat, da_dung, so_truy_van)
            if not hang_doi:
                break
    return kq


_TEP_LINK = re.compile(r"^links(-\d\d)?\.txt$")


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


def ghi_links(kq: KetQua, ra: Path, nguong: frozenset[str] = NGUONG_MAC_DINH) -> list[Path]:
    """`links.txt` (mọi link đạt) + `links-NN.txt` mỗi file ≤50 khi vượt trần job. KHÔNG ghi gì nếu chạy không tin được."""
    _xoa_tep_link(ra)
    if not kq.tin_duoc or kq.rong or kq.bi_captcha or kq.loi_trang:
        return []
    links = [u["url"] for u in kq.giu(nguong)]
    tep = [ra / "links.txt"]
    tep[0].write_text("\n".join(links) + ("\n" if links else ""))
    if len(links) > LINK_MOI_KHOI:
        for i in range(0, len(links), LINK_MOI_KHOI):
            p = ra / f"links-{i // LINK_MOI_KHOI + 1:02d}.txt"
            p.write_text("\n".join(links[i:i + LINK_MOI_KHOI]) + "\n")
            tep.append(p)
    return tep
