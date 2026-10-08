"""Phía MINI của "agy học mẫu" (job 2 pha, ĐP-1495): pha 1 trích khung thưa ⇒ đặt vào hộp thư ⇒ job đứng `cho_agy`;
pha 2 đọc toạ độ máy dev nộp ⇒ box mồi cho lõi.

Bảng UUID ↔ chỉ số khung chỉ nằm ở mini (`khung.json`, KHÔNG phục vụ qua route) — máy dev chỉ thấy job_id + UUID (§3e).
Khung trích: 6 khung trải đều (vai học mẫu, như bench P1a) + 1 khung gần cuối (vai cờ màn kết, idx 6 của bench).
"""
from __future__ import annotations

import json

import cv2

from .box_moi import BoxMoi, box_tu_box_2d
from .hop_thu import HopThu
from .nguon_khung import NguonKhung

SO_KHUNG_HOC = 6
RONG_ANH_AGY = 360  # cỡ ảnh agy đo ở P0b (KF 360px); box chuẩn hoá 0–1000 nên không phụ thuộc cỡ
GIAY_TRUOC_CUOI = 0.3


def chon_khung(so_khung: int, fps: float) -> list[tuple[int, str]]:
    hoc = [int((k + 0.5) * so_khung / SO_KHUNG_HOC) for k in range(SO_KHUNG_HOC)]
    cuoi = max(0, so_khung - 1 - int(GIAY_TRUOC_CUOI * fps))
    return [(i, "hoc_mau") for i in hoc] + [(cuoi, "man_ket")]


def dat_viec(nguon: NguonKhung, hop: HopThu, job_id: int) -> int:
    """Pha 1. Trả số ảnh đã đặt. Khung đọc trượt (video hỏng đoạn cuối) bị bỏ, không đoán."""
    khung, anh = [], []
    for i, vai in chon_khung(nguon.so_khung(), nguon.fps):
        g = nguon.doc(i)
        if g is None:
            continue
        s = RONG_ANH_AGY / g.shape[1]
        nho = cv2.resize(g, (RONG_ANH_AGY, max(1, round(g.shape[0] * s))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", nho, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            khung.append((i, vai))
            anh.append(buf.tobytes())
    if not anh:
        return 0
    ids = hop.tao_viec(job_id, anh)
    (hop.goc / str(job_id) / "khung.json").write_text(
        json.dumps({u: {"khung": i, "vai": vai} for u, (i, vai) in zip(ids, khung)}))
    return len(ids)


def doc_ket_qua(nguon: NguonKhung, hop: HopThu, job_id: int) -> tuple[list[BoxMoi], bool | None] | None:
    """Pha 2. None ⇒ máy dev chưa nộp (job vẫn `cho_agy`). Trả (box mồi, cờ màn kết agy | None nếu không có ảnh cuối)."""
    kq = hop.doc_ket_qua(job_id)
    if kq is None:
        return None
    bang = json.loads((hop.goc / str(job_id) / "khung.json").read_text())
    boxes, man_ket = [], None
    for it in kq["items"]:
        k = bang.get(it["anh"])
        if k is None:
            continue
        if k["vai"] == "man_ket":
            man_ket = bool(it["man_ket"])
            continue
        if it["man_ket"]:  # agy nói khung này là màn kết ⇒ box trên đó không phải watermark trên nội dung
            continue
        for wm in it["watermarks"]:
            b = box_tu_box_2d(wm["box_2d"], k["khung"], nguon.rong, nguon.cao, "agy")
            if b:
                boxes.append(b)
    return boxes, man_ket
