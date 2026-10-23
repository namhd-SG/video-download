"""Pha 0(b): thử Apple Vision OCR dò chữ logo theo từng khung trên video bộ đề (chỉ đọc). In JSON kết quả.

argv: <thư mục Test3> <khung_vang.json> <ra.json>
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import cv2
import Quartz  # noqa: F401  (nạp CoreGraphics cho Vision)
import Vision
from Foundation import NSURL

TEST3, NHAN, RA = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
CHUOI = {4: "learna", 5: "learna", 13: "learna", 16: "learna", 22: "barry", 29: "co"}
DAY_DU = {"learna": "learnaai", "barry": "barry", "co": "co"}
TMP = Path(tempfile.mkdtemp())


def ocr(anh_bgr, muc="accurate"):
    """[(chuỗi thường bỏ khoảng trắng, (x, y, w, h) px gốc, độ tin)] — Vision trả box chuẩn hoá, gốc dưới-trái."""
    H, W = anh_bgr.shape[:2]
    p = TMP / "k.png"
    cv2.imwrite(str(p), anh_bgr)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate if muc == "accurate" else Vision.VNRequestTextRecognitionLevelFast)
    req.setUsesLanguageCorrection_(False)
    req.setMinimumTextHeight_(0.0)
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(p)), None)
    ok, err = h.performRequests_error_([req], None)
    out = []
    for o in (req.results() or []):
        c = o.topCandidates_(1)
        if not c:
            continue
        bb = o.boundingBox()
        x, y, w, hh = bb.origin.x * W, (1 - bb.origin.y - bb.size.height) * H, bb.size.width * W, bb.size.height * H
        out.append(("".join(str(c[0].string()).lower().split()), (round(x), round(y), round(w), round(hh)), round(float(c[0].confidence()), 3)))
    return out


def khop(chuoi_doc, logo):
    return logo in chuoi_doc


def doc_khung(n, f):
    cap = cv2.VideoCapture(str(TEST3 / f"Test 03_{n}.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, g = cap.read()
    cap.release()
    return g if ok else None


def trung(a, b):
    """Tỉ lệ phần box nhãn b nằm trong box a."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return round(ix * iy / max(1, bw * bh), 2)


kq = {"khung_nhan": [], "mau_deu": {}}
nhan = [x for x in json.loads(NHAN.read_text())["nhan"] if x["v"] in CHUOI and x.get("frame") is not None]
t0 = time.time()
for x in nhan:
    g = doc_khung(x["v"], x["frame"])
    logo = CHUOI[x["v"]]
    doc = ocr(g)
    hit = [d for d in doc if khop(d[0], logo)]
    box = x.get("box") or x.get("box_moc")
    kq["khung_nhan"].append({"v": x["v"], "frame": x["frame"], "loai": x["loai"], "box_nhan": box, "doc_thay": [d[0] for d in doc][:8],
                             "khop_logo": [{"chuoi": d[0], "box": d[1], "tin": d[2], "phu_box_nhan": trung(d[1], box) if box else None,
                                            "du_chuoi": DAY_DU[logo] in d[0]} for d in hit]})
kq["giay_khung_nhan"] = round(time.time() - t0, 1)

# Mẫu đều: 60 khung rải đều mỗi video ⇒ tỉ lệ khung dò được chuỗi logo, và tỉ lệ đọc đủ chuỗi
for n, logo in CHUOI.items():
    cap = cv2.VideoCapture(str(TEST3 / f"Test 03_{n}.mp4"))
    tong = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    ds = [int(i * (tong - 1) / 59) for i in range(60)]
    t1 = time.time()
    co = du = 0
    vd = []
    for f in ds:
        hit = [d for d in ocr(doc_khung(n, f)) if khop(d[0], logo)]
        co += bool(hit)
        du += any(DAY_DU[logo] in d[0] for d in hit)
        if hit and len(vd) < 3:
            vd.append({"frame": f, "hit": hit})
    kq["mau_deu"][n] = {"logo": logo, "so_khung": len(ds), "do_thay": co, "doc_du_chuoi": du, "giay": round(time.time() - t1, 1),
                        "ms_khung": round((time.time() - t1) / len(ds) * 1000), "vi_du": vd}
RA.write_text(json.dumps(kq, ensure_ascii=False, indent=1))
print("xong", RA)
