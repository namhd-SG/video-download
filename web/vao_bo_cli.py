"""Lệnh quản trị cho tính năng "đã vào bộ".

    python -m web.vao_bo_cli backfill [--that] [--db PATH] [--env-file PATH]

`backfill` MẶC ĐỊNH là DRY-RUN (chỉ đọc, in bảng số đo). Ghi thật CHỈ khi có `--that`.
Chạy ở nơi có biến `GDRIVE_*` (hoặc chỉ `--env-file` trỏ tới tệp KEY=VALUE, như
`~/.config/videodl/env` trên mini).

Mã thoát: 0 xong · 2 sai cú pháp · 3 Drive chưa cấu hình · 6 lỗi khi đọc Drive/DB ·
7 dry-run không mở được DB chỉ-đọc hoặc DB thiếu bảng (dry-run không tự tạo bảng).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from web import models
from web.vao_bo_backfill import ThieuBang, chay_backfill, in_bang
from web.vao_bo_drive import DriveThat, DriveVaoBo

MA_OK, MA_CHUA_CAU_HINH, MA_LOI, MA_THIEU_BANG = 0, 3, 6, 7
DB_MAC_DINH = Path(__file__).resolve().parent / "data" / "jobs.db"


def _nap_env(tep: Path) -> None:
    for dong in tep.read_text().splitlines():
        if "=" in dong and not dong.lstrip().startswith("#"):
            k, v = dong.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main(argv: list[str] | None = None, *,
         tao_drive: Callable[[], DriveVaoBo] = DriveThat) -> int:
    ap = argparse.ArgumentParser(prog="python -m web.vao_bo_cli")
    sub = ap.add_subparsers(dest="lenh", required=True)
    bf = sub.add_parser("backfill", help="đánh dấu một lần video đã vào bộ bằng md5 (mặc định dry-run)")
    bf.add_argument("--that", action="store_true", default=False,
                    help="GHI thật; không có cờ này chỉ đọc và in bảng")
    bf.add_argument("--db", type=Path, default=DB_MAC_DINH)
    bf.add_argument("--env-file", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.env_file is not None:
        _nap_env(args.env_file)
    drive = tao_drive()
    if not drive.dang_cau_hinh():
        print("Drive chưa cấu hình (GDRIVE_* thiếu) — không làm gì", file=sys.stderr)
        return MA_CHUA_CAU_HINH
    try:
        # DRY-RUN không đụng DB: không `init_db` (sẽ tạo bảng/ghi WAL), mở `mode=ro`.
        # Chỉ `--that` dựng lược đồ, vì nó sắp ghi.
        if args.that:
            models.init_db(args.db)
        bc = chay_backfill(args.db, drive, that=args.that)
    except ThieuBang as exc:
        print(f"backfill dừng: {exc}", file=sys.stderr)
        return MA_THIEU_BANG
    except Exception as exc:  # noqa: BLE001 — báo loại lỗi
        # Đọc Drive xong toàn bộ rồi mới ghi, và ghi có điều kiện `IS NULL` ⇒ chạy lại
        # sau lỗi là an toàn (không ghi trùng); dry-run cho biết còn lại bao nhiêu.
        print(f"backfill trượt ({type(exc).__name__}) — chạy lại dry-run để xem còn gì; "
              "chạy lại --that không ghi trùng", file=sys.stderr)
        return MA_LOI
    print("\n".join(in_bang(bc)))
    return MA_OK


if __name__ == "__main__":
    sys.exit(main())
