"""Pha 0(a): đếm đoạn đỏ/vàng mỗi video từ một lượt bộ đề (chỉ đọc). argv: <thư mục lượt> <khung_vang.json>

Đỏ   = khung trong đời sống vết (giữa khung đè đầu và cuối) mà KHÔNG được đè (state ngoài detected/filled) — máy biết lộ.
Vàng = khung được đè nhưng máy không chắc: `de_khi_biet` (cổng nội dung chặn mà vẫn đè) hoặc `filled` (nội suy).
Chỉ tính vết `render` của video `render` (cùng định nghĩa khung đè với bộ đề).
"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

RA, NHAN = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())["nhan"]
DA = ("detected", "filled")


def doan(fs):
    """Số đoạn liên tiếp (hở ≤ 2 khung coi là cùng đoạn)."""
    fs = sorted(fs)
    return sum(1 for i, f in enumerate(fs) if i == 0 or f - fs[i - 1] > 3)


tong, chi_tiet, kv = {"video_render": 0}, {}, {}
for n in range(1, 41):
    d = RA / str(n)
    kq = json.loads((d / "kq.json").read_text())["kq"]
    if kq.get("trang_thai") != "render":
        continue
    tong["video_render"] += 1
    vid = kq["video_log_id"]
    track = json.load(gzip.open(d / f"files/{vid}/track.json.gz"))
    with sqlite3.connect(f"file:{d / 'log.db'}?mode=ro", uri=True) as c:
        tt = dict(c.execute("SELECT vet, trang_thai FROM tl_vet WHERE video_id=?", (vid,)))
    do, vang_dkb, vang_fill = set(), set(), set()
    for k, vet in enumerate(track):
        if tt.get(k) != "render":
            continue
        ok = [e["frame"] for e in vet if e.get("state") in DA]
        if not ok:
            continue
        a, b = min(ok), max(ok)
        for e in vet:
            f = e["frame"]
            if e.get("state") in DA:
                if e.get("de_khi_biet"):
                    vang_dkb.add(f)
                elif e.get("state") == "filled":
                    vang_fill.add(f)
                kv[(n, f)] = "vang_dkb" if e.get("de_khi_biet") else ("vang_fill" if e.get("state") == "filled" else "xanh")
            elif a <= f <= b:
                do.add(f)
    do -= {f for (v, f), m in kv.items() if v == n}  # khung có vết khác đè thì không đỏ
    chi_tiet[n] = {"doan_do": doan(do), "khung_do": len(do), "doan_vang_dkb": doan(vang_dkb), "khung_vang_dkb": len(vang_dkb),
                   "doan_vang_fill": doan(vang_fill), "khung_vang_fill": len(vang_fill)}

ds = list(chi_tiet.values())
tong.update({k: sum(x[k] for x in ds) for k in ds[0]})
phan_bo = sorted((x["doan_do"] + x["doan_vang_dkb"] + x["doan_vang_fill"]) for x in ds)
tong["doan_can_xem_moi_video_trung_vi"] = phan_bo[len(phan_bo) // 2]
tong["doan_can_xem_moi_video_max"] = phan_bo[-1]
tong["video_0_doan"] = sum(1 for p in phan_bo if p == 0)
# Phép kiểm lớp cảnh báo trên khung có nhãn người
nh = {}
for x in NHAN:
    if x.get("frame") is None:
        continue
    nh.setdefault(x["loai"], []).append(kv.get((x["v"], x["frame"]), "khong_de"))
kiem = {loai: {m: ms.count(m) for m in sorted(set(ms))} for loai, ms in nh.items()}
print(json.dumps({"tong": tong, "kiem_nhan": kiem, "chi_tiet": chi_tiet}, ensure_ascii=False, indent=1))
