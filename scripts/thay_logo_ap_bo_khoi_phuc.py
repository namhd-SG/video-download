#!/usr/bin/env python3
"""Khôi phục "Áp vào bộ" khi DB (`thay_logo_log.db`) hỏng/mất — dựng danh sách TỪ DRIVE, không từ DB.

Mỗi bản mới M trong bộ mang `appProperties.tl_ap_bo` + `tl_ap_goc=<id bản trong bộ G>` ⇒ ghép cặp G↔M THEO ID (không theo tên). G nằm ở
`Thay logo - bản gốc/<mã bộ> (#folder6)/` (gốc Shared Drive). Khôi phục = hoàn tác: đổi tên M `HOAN-TAC-…` + dời M ra
`…/da-hoan-tac/` RỒI trả G về bộ (cùng thứ tự với hoàn tác qua route: bộ không bao giờ có cả G lẫn M). Mỗi bước probe trước.

Liệt con theo thư mục rồi đọc `appProperties` từng file PHÍA CLIENT (cú pháp `appProperties has {key=…}` chỉ-có-key chưa chắc hợp lệ).
Mặc định CHỈ IN kế hoạch (dry-run); `--thuc-hien` mới dời. Không xoá gì.

    python scripts/thay_logo_ap_bo_khoi_phuc.py --bo <folder_id> [--bo <folder_id> ...] [--thuc-hien]
"""
from __future__ import annotations

import argparse
import sys

from tiktok_music_downloader.thay_logo.ap_vao_bo import (TEN_DA_HOAN_TAC, TEN_THU_MUC_BAN_GOC, THE_AP, THE_GOC, TIEN_TO_HOAN_TAC,
                                                         TRAN_LIET_KE_BO)
from tiktok_music_downloader.thay_logo.drive_tl import MIME_THU_MUC, DriveTLKhongThay


def _thu_muc_ban_goc(drive, folder_id: str) -> list[str]:
    """Mọi thư mục `Thay logo - bản gốc/* (#<folder6>)` của bộ (ghép theo đuôi id, không cần mã bộ)."""
    bo = drive.lay_muc(folder_id)
    out = []
    for goc in drive.tim_con_theo_ten(bo["driveId"], TEN_THU_MUC_BAN_GOC):
        for c in drive.liet_ke_con(goc["id"], TRAN_LIET_KE_BO):
            if c.get("mimeType") == MIME_THU_MUC and not c.get("trashed") and (c.get("name") or "").endswith(f"(#{folder_id[:6]})"):
                out.append(c["id"])
    return out


def lap_ke_hoach(drive, cac_bo: list[str]) -> list[dict]:
    """Mỗi cặp: {bo, ban_moi, ban_goc, ten_moi, g_o: bo|ban_goc|mat, viec: [...]} — `viec` rỗng = không cần làm gì."""
    ke = []
    for bo in cac_bo:
        cac_goc = _thu_muc_ban_goc(drive, bo)
        for c in drive.liet_ke_con(bo, TRAN_LIET_KE_BO):
            if c.get("trashed") or c.get("mimeType") == MIME_THU_MUC:
                continue
            m = drive.lay_muc(c["id"])
            ap = m.get("appProperties") or {}
            if THE_AP not in ap or not ap.get(THE_GOC):
                continue
            g = ap[THE_GOC]
            try:
                gm = drive.lay_muc(g)
                cha = set(gm.get("parents") or [])
                g_o = "mat" if gm.get("trashed") else "bo" if bo in cha else "ban_goc" if cha & set(cac_goc) else "mat"
                g_tu = next((p for p in cha if p in cac_goc), None)
            except DriveTLKhongThay:
                g_o, g_tu = "mat", None
            viec = []
            if g_o == "mat":
                viec.append("CẦN NGƯỜI: bản trong bộ mất/sai chỗ — không tự làm")
            elif not cac_goc:
                viec.append("CẦN NGƯỜI: không thấy thư mục bản gốc của bộ")
            else:
                if not (m.get("name") or "").startswith(TIEN_TO_HOAN_TAC):
                    viec.append("doi_ten_moi")
                viec.append("doi_moi_ra")
                if g_o == "ban_goc":
                    viec.append("tra_goc_ve")
            ke.append({"bo": bo, "ban_moi": c["id"], "ban_goc": g, "ten_moi": m.get("name"), "g_o": g_o, "g_tu": g_tu,
                       "thu_muc_ban_goc": (g_tu or (cac_goc[0] if cac_goc else None)), "viec": viec})
    return ke


def thuc_hien(drive, ke: list[dict]) -> int:
    """Làm theo kế hoạch (probe lại trước từng bước). Trả số cặp đã khôi phục."""
    xong = 0
    for k in ke:
        if not k["viec"] or k["viec"][0].startswith("CẦN NGƯỜI"):
            continue
        dh = next((x["id"] for x in drive.tim_con_theo_ten(k["thu_muc_ban_goc"], TEN_DA_HOAN_TAC)), None) \
            or drive.tao_thu_muc(TEN_DA_HOAN_TAC, k["thu_muc_ban_goc"])
        m = drive.lay_muc(k["ban_moi"])
        if not (m.get("name") or "").startswith(TIEN_TO_HOAN_TAC):
            drive.doi_ten(k["ban_moi"], TIEN_TO_HOAN_TAC + (m.get("name") or ""))
        if k["bo"] in (m.get("parents") or []):
            drive.doi_cha(k["ban_moi"], dh, k["bo"])
        gm = drive.lay_muc(k["ban_goc"])
        if k["bo"] not in (gm.get("parents") or []) and k["g_tu"] in (gm.get("parents") or []):
            drive.doi_cha(k["ban_goc"], k["bo"], k["g_tu"])
        xong += 1
    return xong


def main(argv: list[str] | None = None, drive=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bo", action="append", required=True, help="id thư mục bộ trên Drive (lặp lại được)")
    p.add_argument("--thuc-hien", action="store_true", help="DỜI thật (mặc định chỉ in kế hoạch)")
    a = p.parse_args(argv)
    if drive is None:
        from tiktok_music_downloader.thay_logo.drive_tl import DriveTLThat
        drive = DriveTLThat()
        if not drive.dang_cau_hinh():
            print("Drive chưa cấu hình (service account).", file=sys.stderr)
            return 2
    ke = lap_ke_hoach(drive, a.bo)
    for k in ke:
        print(f"bộ {k['bo']} · bản mới {k['ban_moi']} ({k['ten_moi']}) ↔ bản trong bộ {k['ban_goc']} [{k['g_o']}] · việc: {', '.join(k['viec']) or '—'}")
    print(f"tổng {len(ke)} cặp")
    if not a.thuc_hien:
        print("DRY-RUN: chưa dời gì. Thêm --thuc-hien để làm.")
        return 0
    print(f"đã khôi phục {thuc_hien(drive, ke)} cặp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
