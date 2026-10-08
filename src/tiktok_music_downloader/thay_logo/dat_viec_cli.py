"""Điểm vào TIẾN TRÌNH CON cho pha 1 (trích khung đặt việc agy). Giải mã video bằng OpenCV/FFmpeg là mã native: một file hỏng có thể
segfault — chạy trong tiến trình uvicorn thì sập cả Video Desk và 2 lane tải, khởi động lại nhặt đúng file đó, sập tiếp (code-reviewer
09/10). Tách tiến trình ⇒ hỏng chỉ là một dòng `loi`.

In đúng MỘT dòng JSON: {"n", "rong", "cao", "fps", "so_khung"} — các thông số pha 2 cần, để tiến trình chính khỏi mở video lần nào.
"""
from __future__ import annotations

import argparse
import json
import sys

from .hoc_mau_agy import dat_viec
from .hop_thu import HopThu
from .nguon_khung import NguonKhungVideo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--hop", required=True)
    ap.add_argument("--job-id", type=int, required=True)
    a = ap.parse_args(argv)
    nguon = NguonKhungVideo(a.video)
    n = dat_viec(nguon, HopThu(a.hop), a.job_id)
    print(json.dumps({"n": n, "rong": nguon.rong, "cao": nguon.cao, "fps": nguon.fps, "so_khung": nguon.so_khung()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
