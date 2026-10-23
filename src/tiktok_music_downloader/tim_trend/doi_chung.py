"""Cổng đối chứng dương (ctrl): chọn khung đối chứng, chấm lô ảnh bìa kèm ctrl, quyết lô / cả lượt có tin được không.

Thiết kế khép với agy (`~/agy-ws/exchange/tiktok-cong-ctrl-R1b-agy.md`, `-R2b-agy.md`) + quyết định của ĐP 23/10:
- ctrl đạt ⟺ hạng ∈ ngưỡng giữ (`--nguong`): user chốt "cả 2" ⇒ bản hướng dẫn (2A) cũng là đúng dạng.
- Mỗi lô kèm MỌI khung đầu vào có hạng ∈ ngưỡng (neo bắt buộc là khung hạng 3), tên số + vị trí ngẫu nhiên như ảnh bìa.
- Lần 1 đạt ⟺ đa số ctrl đạt; chưa đạt ⇒ chấm lại 1 lần (lượt agy riêng). Vẫn trượt ⇒ bỏ cả lô (ảnh không có hạng).
- Bảo đảm theo TỪNG LINK: link chỉ đến từ lô có ctrl đạt. Bỏ > 50% số lô ⇒ cả lượt không tin (bộ chấm lệch hệ thống).
"""
from __future__ import annotations

import random
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from . import agy_boc
from .cham import ChuKy, hang
from .truong import TruongAnh

if TYPE_CHECKING:
    from .luong import KetQua


class ChuKyKhongOnDinh(RuntimeError):
    """Chữ ký dạng không đại diện được cho video đầu vào (không khung nào tự khớp hạng 3)."""


class VideoHuongDan(ChuKyKhongOnDinh):
    """Video đầu vào chỉ có cảnh hướng dẫn: không có khung kết quả nào làm neo cho chữ ký (review 23/10 M3)."""


def chon_khung_doi_chung(ds_khung: list[Path], truong_khung: dict[str, TruongAnh], ck: ChuKy,
                         nguong: frozenset[str]) -> list[Path]:
    """Danh sách khung đối chứng: khung hạng 3 trước (gần giữa nhất đứng đầu = ctrl chính), rồi khung có hạng ∈ ngưỡng.

    Kiểm "toàn khung hướng dẫn" TRƯỚC khi chọn: video chỉ quay màn hình điện thoại trong nhà cho chữ ký nền trong_nha
    và mọi khung tự ra 2A ⇒ nếu chọn trước thì nhánh này không bao giờ chạy, và công cụ chấm video concert thật bằng
    chữ ký sai (agy R1b ĐK1b). Bắt buộc ≥1 khung hạng 3 làm neo vì cùng lý do.
    Ca 3 (23/10): khung giữa là cảnh điện thoại, 2 khung kia cảnh concert ⇒ ctrl là 2 khung concert.
    """
    doc_duoc = [truong_khung[k.stem] for k in ds_khung if k.stem in truong_khung]
    if doc_duoc and all(t.la_tutorial for t in doc_duoc):
        raise VideoHuongDan("mọi khung của video đầu vào đều là cảnh hướng dẫn — cắt cảnh không giúp được")
    giua = len(ds_khung) // 2
    thu_tu = [ds_khung[giua]] + [k for i, k in enumerate(ds_khung) if i != giua]
    hang_khung = {k: hang(truong_khung[k.stem], ck) for k in thu_tu if k.stem in truong_khung}
    neo = [k for k in thu_tu if hang_khung.get(k) == "3"]
    if not neo:
        raise ChuKyKhongOnDinh("không khung nào của video đầu vào khớp chữ ký của chính nó — video nhiều cảnh khác hẳn nhau")
    return neo + [k for k in thu_tu if k not in neo and hang_khung.get(k) in nguong]


def _so_dat(hang_ctrl: Sequence[str | None], nguong: frozenset[str]) -> int:
    return sum(h in nguong for h in hang_ctrl)


def dat_lan1(hang_ctrl: Sequence[str | None], nguong: frozenset[str]) -> bool:
    """Lần chấm 1: đa số chặt (1/1, 2/2, 2/3, 3/3)."""
    return _so_dat(hang_ctrl, nguong) * 2 > len(hang_ctrl)


def tin_lan2(lan1: Sequence[str | None], lan2: Sequence[str | None], nguong: frozenset[str]) -> bool:
    """Lần chấm lại (chỉ chạy khi lần 1 trượt): lần 2 tự đạt đa số, HOẶC đúng 2 ctrl mà ctrl chính đạt ở cả 2 lần
    (một khung biên bị đọc lệch ổn định không làm trượt lô; mỗi lần đạt một khung khác nhau thì trượt). agy R2b."""
    n = len(lan2)
    return _so_dat(lan2, nguong) * 2 > n or (n == 2 and lan1[0] in nguong and lan2[0] in nguong)


def tin_ca_luot(so_lo: int, so_lo_bo: int, so_link_giu: int) -> bool:
    """Bỏ > 50% số lô ⇒ không tin (50% là hằng TẠM, CHƯA HIỆU CHỈNH — quyết của ĐP 23/10). Có lô bị bỏ mà lô còn lại
    ra 0 link ⇒ không tin: "0 kết quả" lúc đó là giả vì ảnh của lô bỏ chưa chấm được (agy R1b ĐK4)."""
    return so_lo_bo * 2 <= so_lo and (so_lo_bo == 0 or so_link_giu > 0)


def _ten_ctrl(rnd: random.Random, da_co: set[str]) -> str:
    """Tên ctrl cùng mẫu với ảnh bìa (`<19 chữ số>`): tên `ctrl-N` lộ cho agy biết ảnh nào là đối chứng ⇒ chấm không còn mù."""
    while True:
        ten = str(rnd.randrange(7 * 10**18, 8 * 10**18))
        if ten not in da_co:
            da_co.add(ten)
            return ten


def _mot_luot(anh_bia: list[Path], ds_ctrl: list[Path], thu_muc: Path, ck: ChuKy, model: str, rnd: random.Random,
              ten: str) -> tuple[dict[str, TruongAnh], list[str], list[str | None]]:
    """Một lượt agy: chép ctrl sang tên số, chèn vào vị trí ngẫu nhiên, bóc trường, XOÁ bản chép (tên ghi ở `lo_ctrl`)."""
    da_co = {p.stem for p in thu_muc.glob("*.jpg")}
    tam = [thu_muc / f"{_ten_ctrl(rnd, da_co)}.jpg" for _ in ds_ctrl]
    lo = list(anh_bia)
    try:
        for goc, p in zip(ds_ctrl, tam):
            shutil.copyfile(goc, p)
            lo.insert(rnd.randrange(len(lo) + 1), p)
        truong = agy_boc.boc_truong(lo, thu_muc, model, ten=ten)
    finally:
        for p in tam:
            p.unlink(missing_ok=True)
    hang_ctrl = [hang(truong[p.stem], ck) if p.stem in truong else None for p in tam]
    return truong, [p.stem for p in tam], hang_ctrl


def cham_lo(bia: dict[str, Path], ds_ctrl: list[Path], thu_muc: Path, ck: ChuKy, kq: KetQua, model: str,
            nguong: frozenset[str], rnd: random.Random | None = None) -> dict[str, tuple[str | None, TruongAnh | None]]:
    """Chấm ảnh bìa theo lô (cỡ lô trừ chỗ cho ctrl), mỗi lô tối đa 2 lần. Trả {video_id: (hạng, trường)}; lô bị bỏ thì
    hạng None. Số lô đếm theo lô LOGIC xuyên các hop (`kq.so_lo`), không theo số lượt agy."""
    rnd = rnd or random.Random()
    ra: dict[str, tuple[str | None, TruongAnh | None]] = {}
    ids = list(bia)
    co = agy_boc.LO_TOI_DA - len(ds_ctrl)
    for k in range(0, len(ids), co):
        nhom = ids[k:k + co]
        so_lo = kq.so_lo
        kq.so_lo += 1
        cac_lan: list[list[str | None]] = []
        for lan in (1, 2):
            print(f"agy chấm lô {so_lo + 1} lần {lan}: {len(nhom)} ảnh bìa (≈1–2 phút)…", flush=True)
            truong, ten_ctrl, hang_ctrl = _mot_luot([bia[i] for i in nhom], ds_ctrl, thu_muc, ck, model, rnd,
                                                    ten=f"agy-truong-lo-{so_lo}" + ("" if lan == 1 else "-lan2"))
            cac_lan.append(hang_ctrl)
            tin = dat_lan1(hang_ctrl, nguong) if lan == 1 else tin_lan2(cac_lan[0], hang_ctrl, nguong)
            kq.lo_ctrl.append({"lo": so_lo, "lan": lan, "ten_ctrl": ten_ctrl, "hang_ctrl": hang_ctrl, "tin": tin})
            if tin:
                break
        if not tin:
            kq.so_lo_bo += 1
        for vid in nhom:
            t = truong.get(bia[vid].stem)
            ra[vid] = ((hang(t, ck) if (t is not None and tin) else None), t)
    return ra
