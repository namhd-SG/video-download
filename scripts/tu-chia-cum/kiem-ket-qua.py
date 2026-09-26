#!/usr/bin/env python3
"""Phép kiểm MÁY cho đầu ra tầng hình — chạy TRƯỚC khi ghi bất cứ gì lên mini.

    kiem-ket-qua.py nhan    <nhan.jsonl>  --ids <tệp id>
    kiem-ket-qua.py caption <caption.json> --ids <tệp id>
    kiem-ket-qua.py chia    <chia.json>   --ids <tệp id>

`--ids`: tập id MONG ĐỢI (một id mỗi dòng) = video của job SAU khi lọc và SAU
khi bỏ k video không có ảnh nào. Mã thoát: 0 đạt · 3 đo hỏng (tệp không có /
không parse được) · 4 kết quả không đạt. Mỗi hàm `kiem_*` trả DANH SÁCH lỗi
(rỗng = đạt), không raise, để người gọi in đủ mọi lỗi một lần.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TRUONG_NHAN = ("video_id", "so_khung", "the_chu", "trang_phuc_dam_dong",
               "trang_phuc_nguoi_chinh", "boi_canh")
TRUONG_CHU_NHAN = ("trang_phuc_dam_dong", "trang_phuc_nguoi_chinh", "boi_canh")
CO_CAPTION = (True, False, "khong_ro")
LAN_KHONG_KIEU = ("huong_dan", "nghi")


def khoa_ten(s: str) -> str:
    return " ".join(s.split()).casefold()


def kiem_tap_id(thay: list[str], mong_doi: set[str], ten: str) -> list[str]:
    """Đủ id · mỗi id một lần · không id lạ — ba lỗi riêng, kèm số."""
    loi = []
    thieu = sorted(mong_doi - set(thay))
    if thieu:
        loi.append(f"{ten}: thiếu {len(thieu)}/{len(mong_doi)} id: {', '.join(thieu[:10])}")
    trung = sorted({v for v in thay if thay.count(v) > 1})
    if trung:
        loi.append(f"{ten}: {len(trung)} id xuất hiện hơn một lần: {', '.join(trung[:10])}")
    la = sorted(set(thay) - mong_doi)
    if la:
        loi.append(f"{ten}: {len(la)} id ngoài tập mong đợi: {', '.join(la[:10])}")
    return loi


def kiem_nhan(hang: list, mong_doi: set[str], so_khung: dict[str, int] | None = None,
              truong: tuple[str, ...] = TRUONG_NHAN) -> list[str]:
    """Nhãn vision (JSON Lines). `so_khung`: số ảnh đã cấp cho từng id — nhãn
    phải khai đúng số đó (agy khai số khác ⇒ nó đã không xem đủ ảnh)."""
    loi = []
    ids = []
    for i, h in enumerate(hang):
        if not isinstance(h, dict) or not isinstance(h.get("video_id"), str):
            loi.append(f"nhãn dòng {i + 1}: không phải object có video_id")
            continue
        vid = h["video_id"]
        ids.append(vid)
        thieu = [t for t in truong if t not in h]
        if thieu:
            loi.append(f"nhãn {vid}: thiếu trường {', '.join(thieu)}")
        if "the_chu" in h and not isinstance(h["the_chu"], bool):
            loi.append(f"nhãn {vid}: the_chu ngoài danh sách (true/false): {h['the_chu']!r}")
        for t in TRUONG_CHU_NHAN:
            if t in h and (not isinstance(h[t], str) or not h[t].strip()):
                loi.append(f"nhãn {vid}: {t} phải là chuỗi khác rỗng")
        if "so_khung" in truong and "so_khung" in h:
            sk = h["so_khung"]
            if not isinstance(sk, int) or isinstance(sk, bool) or not 1 <= sk <= 3:
                loi.append(f"nhãn {vid}: so_khung phải là số 1..3: {sk!r}")
            elif so_khung is not None and vid in so_khung and sk != so_khung[vid]:
                loi.append(f"nhãn {vid}: so_khung={sk} nhưng đã cấp {so_khung[vid]} ảnh")
    return kiem_tap_id(ids, mong_doi, "nhãn") + loi


def kiem_caption(obj, mong_doi: set[str], khoa_trung: list[str]) -> list[str]:
    if not isinstance(obj, dict):
        return ["caption: tệp phải là một object {video_id: cờ}"]
    loi = kiem_tap_id(list(obj) + khoa_trung, mong_doi, "caption")
    for vid, co in obj.items():
        if not any(co is c if isinstance(c, bool) else co == c for c in CO_CAPTION):
            loi.append(f"caption {vid}: cờ ngoài danh sách (true/false/\"khong_ro\"): {co!r}")
    return loi


def kiem_chia(obj, mong_doi: set[str], khoa_trung: list[str]) -> list[str]:
    """Chuẩn hoá 2 tầng: `{"nhom": {nhóm: [kiểu]}, "gan": {id: {nhom, kieu} | {lan}}}`.
    Mỗi kiểu thuộc ĐÚNG MỘT nhóm (so casefold + chuẩn hoá khoảng trắng); mọi
    gán trỏ vào một cặp nhóm/kiểu ĐÃ khai, hoặc một làn trong `LAN_KHONG_KIEU`."""
    if not isinstance(obj, dict) or not isinstance(obj.get("nhom"), dict) \
            or not isinstance(obj.get("gan"), dict):
        return ["chia: tệp phải là object có 'nhom' (object) và 'gan' (object)"]
    loi = []
    kieu_cua: dict[str, list[str]] = {}
    khai: set[tuple[str, str]] = set()
    for nhom, ds in obj["nhom"].items():
        if not isinstance(ds, list) or not all(isinstance(k, str) and k.strip() for k in ds):
            loi.append(f"chia: nhóm '{nhom}' phải là danh sách tên kiểu")
            continue
        for k in dict.fromkeys(khoa_ten(k) for k in ds):
            kieu_cua.setdefault(k, []).append(nhom)
            khai.add((khoa_ten(nhom), k))
    for k, cac_nhom in kieu_cua.items():
        if len(cac_nhom) > 1:
            loi.append(f"chia: kiểu '{k}' thuộc {len(cac_nhom)} nhóm: {', '.join(cac_nhom)}")
    for vid, g in obj["gan"].items():
        if isinstance(g, dict) and set(g) == {"lan"}:
            if g["lan"] not in LAN_KHONG_KIEU:
                loi.append(f"chia {vid}: làn ngoài danh sách: {g['lan']!r}")
        elif isinstance(g, dict) and isinstance(g.get("nhom"), str) \
                and isinstance(g.get("kieu"), str):
            if (khoa_ten(g["nhom"]), khoa_ten(g["kieu"])) not in khai:
                loi.append(f"chia {vid}: '{g['nhom']}/{g['kieu']}' ngoài danh sách nhóm/kiểu đã khai")
        else:
            loi.append(f"chia {vid}: gán phải là {{nhom, kieu}} hoặc {{lan}}: {g!r}")
    return kiem_tap_id(list(obj["gan"]) + khoa_trung, mong_doi, "chia") + loi


def _doc_json(tep: Path):
    trung: list[str] = []

    def gom(cap):
        ra = {}
        for k, v in cap:
            if k in ra:
                trung.append(k)
            ra[k] = v
        return ra

    return json.loads(tep.read_text(encoding="utf-8"), object_pairs_hook=gom), trung


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("loai", choices=("nhan", "caption", "chia"))
    p.add_argument("tep", type=Path)
    p.add_argument("--ids", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        mong_doi = {d.strip() for d in a.ids.read_text(encoding="utf-8").splitlines() if d.strip()}
        if a.loai == "nhan":
            hang = [json.loads(d) for d in a.tep.read_text(encoding="utf-8").splitlines()
                    if d.strip()]
            loi = kiem_nhan(hang, mong_doi)
        else:
            obj, trung = _doc_json(a.tep)
            loi = (kiem_caption if a.loai == "caption" else kiem_chia)(obj, mong_doi, trung)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ĐO HỎNG: {exc}", file=sys.stderr)
        return 3
    print(f"{a.loai}: mong đợi {len(mong_doi)} id · {len(loi)} lỗi")
    for dong in loi:
        print(f"  - {dong}")
    return 4 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
