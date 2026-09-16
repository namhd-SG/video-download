#!/usr/bin/env python3
"""Dựng lại hàng `videos` cho các video đã nằm trên Drive mà chưa có chỉ mục.

Vì sao cần: lớp chỉ mục (`videos` + ảnh) lên ngày 15/09. Video tải TRƯỚC đó
vẫn ở trên Drive nhưng không có hàng nào, nên thư viện không thấy chúng và
lớp chống-trùng cũng mù với chúng.

Chạy TRÊN MINI (nơi có credential Drive), từ thư mục repo:
    ./.venv/bin/python scripts/backfill-videos-from-drive.py            # thử khô
    ./.venv/bin/python scripts/backfill-videos-from-drive.py --apply    # ghi thật

Những gì KHÔNG khôi phục được, và vì sao để trống thay vì đoán:
  * `url` — quy ước là https://www.tiktok.com/@<tác giả>/video/<id>, mà tên
    file trên Drive chỉ có <id>. Dạng chỉ-có-id đã ĐO: tiktok.com/video/<id>
    trả 302 về /404, nên viết nó vào là tạo một link chết trông như thật.
    Để rỗng; UI hiện "chưa rõ link gốc" thay vì một nút bấm vào không đi đâu.
  * `music_id`, `title`, `author`, `region`, `duration`, `play_count` — chỉ có
    trong response index lúc chạy, không lấy lại được từ đĩa.

Những gì khôi phục ĐÚNG: `video_id` (tên file), `job_id` (tên thư mục job-N),
`drive_file_id` (id thật của file), `tao_luc` (lấy theo `jobs.tao_luc` của
đúng job đó — KHÔNG phải thời điểm chạy script, nếu không bộ lọc "Ngày tải"
sẽ báo video cũ là tải hôm nay), và `nguon` cho sighting (lấy `jobs.url`).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.oauth2 import service_account          # noqa: E402
from googleapiclient.discovery import build        # noqa: E402

from web import models                             # noqa: E402


def liet_ke(svc, parent_id: str) -> list[dict]:
    """Mọi mục con trực tiếp của một thư mục Drive, đã gộp hết các trang."""
    ra: list[dict] = []
    token = None
    while True:
        res = svc.files().list(
            q=f'"{parent_id}" in parents and trashed=false',
            fields="nextPageToken, files(id,name,mimeType)",
            pageSize=1000, supportsAllDrives=True,
            includeItemsFromAllDrives=True, pageToken=token,
        ).execute()
        ra += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            return ra


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="web/data/jobs.db")
    ap.add_argument("--apply", action="store_true",
                    help="ghi thật; không có cờ này thì chỉ in ra dự định")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"không thấy DB: {db}", file=sys.stderr)
        return 1

    cred_file = os.environ.get("GDRIVE_SERVICE_ACCOUNT_FILE")
    root = os.environ.get("GDRIVE_SHARED_DRIVE_FOLDER_ID")
    if not cred_file or not root:
        print("thiếu GDRIVE_SERVICE_ACCOUNT_FILE / GDRIVE_SHARED_DRIVE_FOLDER_ID "
              "— nạp ~/.config/videodl/env trước", file=sys.stderr)
        return 1

    cred = service_account.Credentials.from_service_account_file(
        cred_file, scopes=["https://www.googleapis.com/auth/drive"])
    svc = build("drive", "v3", credentials=cred, cache_discovery=False)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    jobs = {r["id"]: r for r in conn.execute("SELECT id, url, tao_luc FROM jobs")}
    da_co = {r["video_id"] for r in conn.execute("SELECT video_id FROM videos")}
    truoc = len(da_co)
    conn.close()

    them: list[tuple] = []
    bo_qua_khong_co_job: list[str] = []

    for muc in liet_ke(svc, root):
        if "folder" not in muc["mimeType"] or not muc["name"].startswith("job-"):
            continue
        try:
            job_id = int(muc["name"].split("-", 1)[1])
        except ValueError:
            bo_qua_khong_co_job.append(muc["name"])
            continue
        job = jobs.get(job_id)
        if job is None:
            # Thư mục có mà hàng job không còn: không đoán thời điểm hay nguồn.
            bo_qua_khong_co_job.append(muc["name"])
            continue
        for tep in liet_ke(svc, muc["id"]):
            if not tep["name"].endswith(".mp4"):
                continue
            video_id = tep["name"][:-4]
            if video_id in da_co:
                continue
            them.append((video_id, job_id, tep["id"], job["tao_luc"], job["url"]))

    print(f"videos đang có: {truoc}")
    print(f"sẽ thêm       : {len(them)}")
    for video_id, job_id, file_id, tao_luc, nguon in them:
        print(f"   + {video_id}  job={job_id}  tao_luc={tao_luc}  nguon={nguon}")
    if bo_qua_khong_co_job:
        print(f"bỏ qua (không có hàng job tương ứng): {bo_qua_khong_co_job}")

    if not args.apply:
        print("\nTHỬ KHÔ — chưa ghi gì. Thêm --apply để ghi thật.")
        return 0

    for video_id, job_id, file_id, tao_luc, nguon in them:
        models.record_video(db, job_id=job_id, video_id=video_id, url="",
                            drive_file_id=file_id, tao_luc=tao_luc)
        models.record_sighting(db, video_id=video_id, job_id=job_id,
                               nguon=nguon, da_tai=True, thay_luc=tao_luc)

    conn = sqlite3.connect(db)
    sau = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()
    print(f"\nvideos sau khi ghi: {sau} (trước {truoc}, thêm {len(them)})")
    if sau != truoc + len(them):
        print("LỆCH — số hàng thêm được không khớp dự định", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
