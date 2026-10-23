#!/usr/bin/env python3
"""Ảnh soi cho vế (c) của bộ đề thay logo: mỗi mẫu trong `mau-soi.json` ⇒ một ảnh TOÀN KHUNG cỡ gốc (không crop — bài học 20–22/10:
soi crop nhỏ đã cho kết luận sai) gồm 3 tấm cạnh nhau: khung GỐC có box mốc (đỏ) và box nhánh (xanh), bản ra MỐC, bản ra NHÁNH.
Kèm `soi-mau.json` để người soi điền `ket_qua` ∈ {dung, sai, sua}, rồi đưa vào `bo-de-thay-logo.sh so … --soi <tệp>`.

    python scripts/bo_de_thay_logo_anh_soi.py <thư mục so (có mau-soi.json)> <thư mục video gốc: <N>/goc.mp4>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bo_de_thay_logo as bd  # noqa: E402

DO, XANH = (0, 0, 255), (0, 200, 0)


def doc_khung(p: Path, f: int):
    cap = cv2.VideoCapture(str(p))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, g = cap.read()
    cap.release()
    return g if ok else None


def ve(g, box, mau, nhan):
    if box is not None:
        x, y, w, h = box
        cv2.rectangle(g, (x, y), (x + w, y + h), mau, 2)
    cv2.putText(g, nhan, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    return g


def main(argv=None) -> int:
    so, v_goc = Path((argv or sys.argv[1:])[0]), Path((argv or sys.argv[1:])[1])
    m = json.loads((so / "mau-soi.json").read_text())
    moc, nhanh = Path(m["moc"]), Path(m["nhanh"])
    anh = so / "anh"
    anh.mkdir(exist_ok=True)
    mau_ra = []
    for x in m["mau"]:
        v, f = x["v"], x["frame"]
        a, b = bd.doc_video(moc / str(v))["de"].get(f), bd.doc_video(nhanh / str(v))["de"].get(f)
        g = doc_khung(v_goc / str(v) / "goc.mp4", f)
        if g is None:
            raise SystemExit(f"không đọc được v{v}#{f}")
        tam = [ve(g.copy(), a, DO, f"v{v}#{f} goc: do=moc xanh=nhanh"), None, None]
        ve(tam[0], b, XANH, "")
        for k, (luot, box, ten) in enumerate(((moc, a, "MOC"), (nhanh, b, "NHANH")), start=1):
            r = doc_khung(luot / str(v) / "ra.mp4", f) if (luot / str(v) / "ra.mp4").exists() else None
            tam[k] = ve(r if r is not None else np.zeros_like(g), None, DO, ten + ("" if r is not None else " (khong xuat)"))
        ten_anh = f"v{v}-{f}.jpg"
        cv2.imwrite(str(anh / ten_anh), np.hstack(tam), [cv2.IMWRITE_JPEG_QUALITY, 92])
        mau_ra.append({**x, "anh": f"anh/{ten_anh}", "box_moc": a, "box_nhanh": b, "ket_qua": None})
    (so / "soi-mau.json").write_text(json.dumps({"huong_dan": "ket_qua: dung (nhánh đúng) | sai (nhánh sai) | sua (ca lỗi đã sửa: "
                                             "còn đè VÀ che hết logo cũ)", "mau": mau_ra}, ensure_ascii=False, indent=1))
    print(f"{len(mau_ra)} ảnh → {anh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
