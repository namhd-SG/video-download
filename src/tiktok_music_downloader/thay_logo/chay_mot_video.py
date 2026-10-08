"""Điểm vào TIẾN TRÌNH CON xử lý một video (worker gọi với `nice -n 10`). Tách tiến trình để: trần thời gian cứng (TERM/KILL được),
RAM của OpenCV trả lại hệ điều hành khi xong, và lỗi native không kéo sập uvicorn.

In đúng MỘT dòng JSON ra stdout: kết quả `xu_ly_video.xu_ly` hoặc {"trang_thai": "loi", "loi": "..."}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import nhat_ky
from .box_moi import BoxMoi
from .xu_ly_video import xu_ly


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for a in ("--video", "--boxes", "--out", "--db", "--files", "--nguon-video", "--ffmpeg"):
        ap.add_argument(a, required=True)
    ap.add_argument("--job-id", type=int)
    ap.add_argument("--man-ket", choices=("0", "1"))
    a = ap.parse_args(argv)
    boxes = [BoxMoi(**b) for b in json.loads(Path(a.boxes).read_text())]
    conn = nhat_ky.mo(a.db)
    try:
        kq = xu_ly(a.video, boxes, a.out, conn, Path(a.files), nguon_video=a.nguon_video, ffmpeg=a.ffmpeg, job_id=a.job_id,
                   man_ket_agy=None if a.man_ket is None else a.man_ket == "1")
    except Exception as e:  # đã ghi `loi` vào nhật ký trong xu_ly; ở đây chỉ báo cho worker
        print(json.dumps({"trang_thai": "loi", "loi": f"{type(e).__name__}: {e}"[:500]}))
        return 1
    finally:
        conn.close()
    print(json.dumps(kq))
    return 0


if __name__ == "__main__":
    sys.exit(main())
