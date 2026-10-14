"""Chỉ số NHÁY bằng máy: trong khoảng sống của một vết, bao nhiêu khung KHÔNG được che, và che/lộ đổi chiều bao nhiêu lần.

Khoảng sống = các đoạn [đầu, cuối] mà `lam_muot_vet` trả (lỗ ≤ 60 khung đã nằm trong đoạn). Khung trong đoạn mà không có trong
danh sách render (bị cổng chặn, hoặc vết không được phép render) tính là LỘ — đó chính là cái người xem thấy nháy.
Đích nghiệm thu: `pct_nhay` ≤ 2.
"""
from __future__ import annotations


def do_nhay(doan: list[tuple[int, int]], khung_che: set[int]) -> dict:
    tong = lo = doi = 0
    for a, b in doan:
        truoc = None
        for t in range(a, b + 1):
            che = t in khung_che
            tong += 1
            lo += 0 if che else 1
            if truoc is not None and che != truoc:
                doi += 1
            truoc = che
    return {"khung_song": tong, "khung_lo": lo, "pct_nhay": round(100.0 * lo / tong, 2) if tong else 0.0,
            "so_lan_doi": doi, "so_doan": len(doan)}
