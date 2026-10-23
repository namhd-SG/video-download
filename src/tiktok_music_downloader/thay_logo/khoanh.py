"""Khoanh chỗ lộ: người khoanh vùng logo cũ còn thấy trên một khung ⇒ một CA KIỂM TRA (bảng `tl_ca_khoanh`) để vòng tự học dùng lại.

Cũng gồm hai việc dữ liệu cho trang khoanh:
  · dải thời gian đỏ / vàng theo track — CÙNG định nghĩa với phép đếm Pha 0 (plans/reports/brainstorm-261023-thay-logo-cai-to/pha0-dem-doan.py):
    đỏ = khung trong đời sống một vết render mà KHÔNG được đè (máy biết còn lộ); vàng = khung được đè dù cổng nội dung chặn
    (`de_khi_biet`). Khung nội suy KHÔNG tô (Pha 0: 789 đoạn/26 video — tô thì dải ngập vàng).
  · giữ video gốc + bản ra cho người xem lại / khoanh, ở thư mục RIÊNG `thay_logo_video/<video_log_id>/` — không chung
    `thay_logo/<video_log_id>/` vì `nhat_ky.don_dep` có trần `TRAN_FILE_BYTE` sẽ xoá luôn track/ảnh soi khi video nằm chung.

Người không chọn mã lỗi: `gan_mau_loi` suy tất định từ vị trí khoanh so với box máy và track tại khung đó.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from . import nhat_ky

THU_MUC_VIDEO = "thay_logo_video"
NGAY_GIU_VIDEO_SUA = 7                     # video không có khoanh: đủ để người duyệt xong một lô
NGAY_GIU_VIDEO_CO_KHOANH = nhat_ky.NGAY_GIU_FILE_HONG  # video có khoanh: dữ liệu tune quý như video chấm hỏng
DIA_TRONG_TOI_THIEU_GB = 20.0              # dưới mức này dọn video cũ nhất trước (video có khoanh dọn sau cùng)
CANH_TOI_THIEU_PX = 4                      # vùng khoanh nhỏ hơn ⇒ coi là bấm nhầm
GAN_MEP_TOI_THIEU_PX = 24                  # khoanh cách mép box máy ≤ max(0,5·w_máy, 24 px) ⇒ cùng một chỗ đè (lộ mép)
DA = ("detected", "filled")
MAU_LOI = ("may_khong_thay", "che_nham", "lo_mep", "de_lech_cho", "lo_do_cong_chan", "lo_mat_dau")
TRANG_THAI_CA = ("cho", "da_sua", "huy")

# Bảng `tl_ca_khoanh` nằm trong `nhat_ky._SCHEMA` (cùng DB, tạo khi mở nhật ký).


# ---------------------------------------------------------------- toạ độ
def quy_doi(vung: dict, rong: int, cao: int) -> tuple[int, int, int, int]:
    """Vùng tỉ lệ 0–1 theo ảnh hiển thị ⇒ px của khung gốc `rong`×`cao`, kẹp trong khung. Sai dạng / quá nhỏ ⇒ ValueError."""
    try:
        x, y, w, h = (float(vung[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("vùng khoanh cần x, y, w, h là số") from None
    if not all(0.0 <= v <= 1.0 for v in (x, y, w, h)) or x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
        raise ValueError("vùng khoanh phải nằm trong ảnh (tỉ lệ 0–1)")
    px = (round(x * rong), round(y * cao), round(w * rong), round(h * cao))
    if px[2] < CANH_TOI_THIEU_PX or px[3] < CANH_TOI_THIEU_PX:
        raise ValueError("vùng khoanh quá nhỏ")
    return px


def _cach_mep(a: tuple, b: tuple) -> float:
    """Khoảng cách giữa hai hộp (0 khi giao nhau)."""
    dx = max(0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return (dx * dx + dy * dy) ** 0.5


def _giao(a: tuple, b: tuple) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


# ---------------------------------------------------------------- track
def khung_tai(track: list[list[dict]], tt_vet: dict, khung: int) -> tuple[tuple | None, list[tuple[str, tuple]]]:
    """(box máy ĐANG ĐÈ ở `khung` — vết render, state detected/filled; các (state, box) bị cổng chặn `hidden_*` có toạ độ ở khung đó)."""
    may, chan = None, []
    for k, vet in enumerate(track):
        for e in vet:
            if e.get("frame") != khung:
                continue
            box = (e.get("x"), e.get("y"), e.get("w"), e.get("h"))
            if tt_vet.get(k) == "render" and e.get("state") in DA and may is None:
                may = box
            elif str(e.get("state", "")).startswith("hidden_") and None not in box:
                chan.append((e["state"], box))
    return may, chan


def dai_thoi_gian(track: list[list[dict]], tt_vet: dict) -> list[dict]:
    """Các đoạn {loai: do|vang, tu, den} (khung, gồm hai đầu) — hở ≤ 3 khung coi là cùng đoạn (như Pha 0)."""
    de, do, vang = set(), set(), set()
    for k, vet in enumerate(track):
        if tt_vet.get(k) != "render":
            continue
        ok = [e["frame"] for e in vet if e.get("state") in DA]
        if not ok:
            continue
        a, b = min(ok), max(ok)
        for e in vet:
            if e.get("state") in DA:
                de.add(e["frame"])
                if e.get("de_khi_biet"):
                    vang.add(e["frame"])
            elif a <= e["frame"] <= b:
                do.add(e["frame"])
    out = []
    for loai, fs in (("do", do - de), ("vang", vang)):
        for f in sorted(fs):
            if out and out[-1]["loai"] == loai and f - out[-1]["den"] <= 3:
                out[-1]["den"] = f
            else:
                out.append({"loai": loai, "tu": f, "den": f})
    return sorted(out, key=lambda d: (d["tu"], d["loai"]))


def gan_mau_loi(cho_nguoi: bool, giu_goc: bool, vung: tuple | None, box_may: tuple | None,
                chan: list[tuple[str, tuple]]) -> tuple[str, str | None]:
    """(mã lỗi, cổng đã chặn) — cây 5 nhánh tất định (agy thay-logo-cai-to R3b ĐK3). Người không phải chọn mã."""
    if cho_nguoi:
        return "may_khong_thay", None
    if giu_goc:
        return "che_nham", None
    if vung is None:
        raise ValueError("cần vùng khoanh")
    if box_may is not None:
        gan = _cach_mep(vung, box_may) <= max(0.5 * box_may[2], GAN_MEP_TOI_THIEU_PX)
        return ("lo_mep" if gan else "de_lech_cho"), None
    for state, box in chan:
        if _giao(vung, box):
            return "lo_do_cong_chan", state
    return "lo_mat_dau", None


def ghi_ca(conn, *, video_log_id: int, job_video_id: int, member: str, khung: int, vung: tuple | None, mau_loi: str,
           chan_cu: str | None, box_may: tuple | None) -> int:
    if mau_loi not in MAU_LOI:
        raise ValueError(f"mã lỗi lạ: {mau_loi}")
    x, y, w, h = vung if vung else (box_may or (None,) * 4)
    cu = conn.execute("SELECT id FROM tl_ca_khoanh WHERE video_log_id=? AND member=? AND khung=? AND mau_loi=? AND x IS ? AND y IS ? "
                      "AND w IS ? AND h IS ? AND trang_thai='cho'", (video_log_id, member, khung, mau_loi, x, y, w, h)).fetchone()
    if cu:  # bấm lưu hai lần cùng một chỗ ⇒ một ca
        return cu[0]
    cur = conn.execute(
        "INSERT INTO tl_ca_khoanh (video_log_id, job_video_id, member, khung, x, y, w, h, mau_loi, chan_cu, box_may, phien_ban, luc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (video_log_id, job_video_id, member, khung, x, y, w, h, mau_loi, chan_cu, json.dumps(box_may) if box_may else None,
         nhat_ky.phien_ban_thuat_toan(), time.time()))
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- giữ / dọn video cho người sửa
def giu_video(data: Path, video_log_id: int, goc: Path, ra: Path | None) -> Path:
    """Dời (`os.replace`, cùng ổ ⇒ không chép) video gốc và bản ra sang `thay_logo_video/<video_log_id>/` TRƯỚC khi scratch bị dọn."""
    d = Path(data) / THU_MUC_VIDEO / str(video_log_id)
    d.mkdir(parents=True, exist_ok=True)
    os.replace(goc, d / "goc.mp4")
    if ra is not None and Path(ra).exists():
        os.replace(ra, d / "ra.mp4")
    return d


def lay_lai_goc(conn, data: Path, job_id: int, nguon_video: str, dich: Path) -> bool:
    """Tiến trình chết giữa `giu_video` và `_ket_thuc` ⇒ gốc đã rời scratch mà hàng đợi chưa biết `video_log_id`. Tìm theo
    `tl_video(job_id, nguon_video)` (tiến trình con ghi) và dời gốc về `dich` để chạy lại. Không thấy ⇒ False."""
    for (vid,) in conn.execute("SELECT id FROM tl_video WHERE job_id=? AND nguon_video=? ORDER BY id DESC", (job_id, nguon_video)):
        p = duong_video(data, vid, "goc")
        if p.is_file():
            Path(dich).parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, dich)
            return True
    return False


def duong_video(data: Path, video_log_id: int, ban: str) -> Path:
    if ban not in ("goc", "ra"):
        raise ValueError("ban phải là goc hoặc ra")
    return Path(data) / THU_MUC_VIDEO / str(video_log_id) / f"{ban}.mp4"


def don_video_sua(conn, data: Path, bay_gio: float | None = None, dia_trong_gb=None) -> dict:
    """Xoá thư mục video giữ để sửa khi: quá hạn (7 ngày; có khoanh 180 ngày), hoặc video KHÔNG khoanh đã chấm Đạt / bỏ qua.
    Video có khoanh luôn giữ đủ hạn (dữ liệu tự học — ĐP 23/10). Đĩa trống < DIA_TRONG_TOI_THIEU_GB ⇒ xoá thêm cũ nhất trước, video có
    khoanh sau cùng. Video quá hạn bị xoá TRƯỚC khi đo đĩa: đo lúc chúng còn nằm đó sẽ xoá oan video còn hạn."""
    goc = Path(data) / THU_MUC_VIDEO
    if not goc.exists():
        return {"xoa": 0}
    bay_gio = bay_gio or time.time()
    dia = dia_trong_gb or (lambda: shutil.disk_usage(goc).free / 1e9)
    hang = []
    for d in goc.iterdir():
        if not d.name.isdigit():
            continue
        vid = int(d.name)
        r = conn.execute("""SELECT v.ket_thuc, v.bat_dau,
              (SELECT ket_qua FROM tl_danh_gia g WHERE g.video_id = v.id ORDER BY luc DESC LIMIT 1) AS danh_gia,
              (SELECT count(*) FROM tl_ca_khoanh c WHERE c.video_log_id = v.id) AS so_ca,
              (SELECT max(j.bo_qua_luc) FROM tl_job_video j WHERE j.video_log_id = v.id) AS bo_qua
            FROM tl_video v WHERE v.id = ?""", (vid,)).fetchone()
        hang.append((vid, d, r))
    xoa = []
    for vid, d, r in hang:
        if r is None:
            xoa.append(d)  # không còn hàng nhật ký ⇒ không ai mở được
            continue
        tuoi = bay_gio - (r["ket_thuc"] or r["bat_dau"])
        han = (NGAY_GIU_VIDEO_CO_KHOANH if r["so_ca"] else NGAY_GIU_VIDEO_SUA) * 86400
        xong_viec = (r["danh_gia"] == "dat" or r["bo_qua"]) and not r["so_ca"]
        if tuoi > han or xong_viec:
            xoa.append(d)
    for d in xoa:
        shutil.rmtree(d, ignore_errors=True)
    for uu_tien_khoanh in (False, True):
        for vid, d, r in sorted(hang, key=lambda t: (t[2]["ket_thuc"] or 0) if t[2] else 0):
            if d in xoa or dia() >= DIA_TRONG_TOI_THIEU_GB:
                continue
            if bool(r and r["so_ca"]) == uu_tien_khoanh:
                shutil.rmtree(d, ignore_errors=True)
                xoa.append(d)
    return {"xoa": len(xoa)}
