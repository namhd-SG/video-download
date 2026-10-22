"""Điều phối một lần chạy: video ⇒ chữ ký ⇒ tìm theo hop ⇒ ảnh bìa ⇒ hạng ⇒ mở rộng ⇒ kết quả.

Đối chứng dương KHÔNG tự chấm (agy plan-R1b ĐK5): chữ ký tính từ lượt bóc RIÊNG của khung đầu vào; mỗi lô ảnh bìa gửi agy
có thêm 1 bản sao khung giữa của video đầu vào (`ctrl-*`). ctrl trong lô không ra hạng 3 ⇒ lô đó không tin được ⇒ cả lần
chạy KHÔNG xuất `links.txt` (lọc sai là hỏng âm thầm: thà không ra link còn hơn ra link sai mà trông như đúng).
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import agy_boc, anh_bia, khung
from .cham import NGUONG_MAC_DINH, ChuKy, chu_ky, hang
from .khu_trung import MucKhuTrung, khu_trung
from .mo_rong import sinh_mo_rong
from .nguon_tim import BiCaptcha, HetLuot, UngVien
from .truong import TruongAnh
from .truy_van import TruyVan, sinh_truy_van

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
    tin_duoc: bool = True

    @property
    def rong(self) -> bool:
        """Không có ứng viên nào: KHÔNG phải "chạy xong, 0 kết quả" — thường là feed bị chặn/rỗng (Pha 4 22/10: 12/12)."""
        return not self.ung_vien

    def giu(self, nguong: frozenset[str]) -> list[dict]:
        return [u for u in self.ung_vien if u["hang"] in nguong]


def _bo_truong(t: TruongAnh | None) -> dict | None:
    return None if t is None else asdict(t)


def _cham_lo(bia: dict[str, Path], ctrl_goc: Path, thu_muc: Path, ck: ChuKy, kq: KetQua,
             model: str) -> dict[str, tuple[str | None, TruongAnh | None]]:
    """Chấm ảnh bìa theo lô ≤ LO_TOI_DA-1, mỗi lô kèm 1 ctrl. Trả {video_id: (hạng, trường)}."""
    ra: dict[str, tuple[str | None, TruongAnh | None]] = {}
    ids = list(bia)
    co = agy_boc.LO_TOI_DA - 1
    for k in range(0, len(ids), co):
        nhom = ids[k:k + co]
        ctrl = thu_muc / f"ctrl-{len(kq.lo_ctrl)}.jpg"
        shutil.copyfile(ctrl_goc, ctrl)
        truong = agy_boc.boc_truong([bia[i] for i in nhom] + [ctrl], thu_muc, model, ten=f"agy-truong-{ctrl.stem}")
        h_ctrl = hang(truong[ctrl.stem], ck) if ctrl.stem in truong else None
        kq.lo_ctrl.append({"lo": len(kq.lo_ctrl), "hang_ctrl": h_ctrl})
        tin = h_ctrl == "3"
        kq.tin_duoc = kq.tin_duoc and tin
        for vid in nhom:
            t = truong.get(bia[vid].stem)
            ra[vid] = ((hang(t, ck) if (t is not None and tin) else None), t)
    return ra


def chay(video: Path, ra: Path, *, tao_nguon: Callable[[], object], so_truy_van: int = 6, so_hop: int = 2,
         gian_cach_anh: float = 2.0, model: str = agy_boc.MODEL_MAC_DINH,
         bao: Callable[[str], None] = print) -> KetQua:
    kq = KetQua()
    ra.mkdir(parents=True, exist_ok=True)
    thu_khung, thu_bia = ra / "khung", ra / "bia"
    ds_khung = khung.trich_khung(video, thu_khung)
    if not ds_khung:
        raise RuntimeError("không trích được khung nào từ video đầu vào")
    truong_khung = agy_boc.boc_truong(ds_khung, ra, model, ten="agy-truong-dau-vao")
    kq.chu_ky = ck = chu_ky(list(truong_khung.values()))
    bao(f"Chữ ký dạng: {ck}")
    ctrl_goc = ds_khung[len(ds_khung) // 2]

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
                    break
                kq.truy_van.append({**asdict(tv), "hop": hop, "so_link": len(tim_duoc), "ghi_chu": ghi_chu})
                for u in tim_duoc:
                    if u.video_id not in theo_id:
                        theo_id[u.video_id] = u
                        moi.append(u)
            kq.so_lan_mo_trang = getattr(nguon, "da_mo", 0)
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


def ghi_links(kq: KetQua, ra: Path, nguong: frozenset[str] = NGUONG_MAC_DINH) -> list[Path]:
    """`links.txt` (mọi link đạt) + `links-NN.txt` mỗi file ≤50 khi vượt trần job. KHÔNG ghi gì nếu chạy không tin được."""
    if not kq.tin_duoc or kq.rong or kq.bi_captcha:
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
