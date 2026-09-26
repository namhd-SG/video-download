"""Hai cách với tới DB Video Desk cho tầng hình: qua ssh (mini thật) hoặc
một DB cục bộ (thử khô / test). Cả hai đi qua CÙNG CLI `web.nhap_cum_cli` —
không cách nào đọc/ghi DB trực tiếp từ máy dev.

Người chạy lệnh (`ChayLenh`) tiêm được: test đưa bản giả, nên không test nào
chạm ssh thật.
"""
from __future__ import annotations

import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# `(argv, stdin) -> (rc, stdout, stderr)`.
ChayLenh = Callable[[list[str], "bytes | None"], "tuple[int, bytes, bytes]"]

GOC_REPO = Path(__file__).resolve().parents[2]

# Ảnh mà CLI `liet` trả: `thumbs/<id>.webp` hoặc `thumbs/khung/<id>-<pt>.webp`.
# Kiểm hình dạng TRƯỚC khi đặt vào một lệnh shell phía xa hay một đường dẫn
# cục bộ — chuỗi này đi từ DB ra, không phải hằng số.
_ANH_HOP_LE = re.compile(r"thumbs/(?:khung/)?[A-Za-z0-9_]+(?:-[0-9]{1,3})?\.webp")
_REPO_HOP_LE = re.compile(r"[~A-Za-z0-9_./-]+")


class LoiMini(Exception):
    """Không với tới / không đọc được mini — phép đo hỏng."""


def chay_that(argv: list[str], stdin: bytes | None, timeout: float = 600,
              env: dict | None = None, cwd: Path | None = None) -> tuple[int, bytes, bytes]:
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout,
                           env=env, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LoiMini(f"{argv[0]}: {type(exc).__name__}: {exc}") from exc
    return r.returncode, r.stdout, r.stderr


def kiem_duong_anh(duong: list[str]) -> None:
    sai = [d for d in duong if not _ANH_HOP_LE.fullmatch(d)]
    if sai:
        raise LoiMini(f"{len(sai)} đường dẫn ảnh sai hình dạng: {sai[:3]}")


@dataclass
class MiniSsh:
    host: str
    repo: str
    chay: ChayLenh
    ssh_bin: str = "ssh"

    def __post_init__(self):
        if not _REPO_HOP_LE.fullmatch(self.repo):
            raise ValueError(f"đường repo trên mini có ký tự lạ: {self.repo!r}")

    def cli(self, args: list[str], stdin: bytes | None = None) -> tuple[int, str, str]:
        lenh = f"cd {self.repo} && .venv/bin/python -m web.nhap_cum_cli {shlex.join(args)}"
        rc, ra, loi = self.chay([self.ssh_bin, self.host, lenh], stdin)
        return rc, ra.decode("utf-8", "replace"), loi.decode("utf-8", "replace")

    def keo_anh(self, duong: list[str], dich: Path) -> None:
        kiem_duong_anh(duong)
        if not duong:
            return
        # COPYFILE_DISABLE: tar của macOS tự chèn mục `._<tên>` cho tệp có
        # xattr — mục ngoài danh sách đã xin, bị chặn ở dưới.
        lenh = f"cd {self.repo}/web/data && COPYFILE_DISABLE=1 tar -cf - -- {shlex.join(duong)}"
        rc, ra, loi = self.chay([self.ssh_bin, self.host, lenh], None)
        if rc != 0:
            raise LoiMini(f"tar trên mini rc={rc}: {loi.decode('utf-8', 'replace')[:300]}")
        dich.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(fileobj=io.BytesIO(ra)) as tar:
                cho_phep = set(duong)
                for m in tar.getmembers():
                    if not m.isfile() or m.name not in cho_phep:
                        raise LoiMini(f"tar trả mục ngoài danh sách đã xin: {m.name!r}")
                tar.extractall(dich, filter="data")
        except tarfile.TarError as exc:
            raise LoiMini(f"tar từ mini hỏng: {exc}") from exc


@dataclass
class MiniCucBo:
    """DB cục bộ — chạy CLI bằng python hiện tại với mã của CHÍNH repo này."""
    db: Path

    def cli(self, args: list[str], stdin: bytes | None = None) -> tuple[int, str, str]:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(GOC_REPO), str(GOC_REPO / "src")))}
        rc, ra, loi = chay_that([sys.executable, "-m", "web.nhap_cum_cli", "--db", str(self.db),
                                 *args], stdin, env=env, cwd=GOC_REPO)
        return rc, ra.decode("utf-8", "replace"), loi.decode("utf-8", "replace")

    def keo_anh(self, duong: list[str], dich: Path) -> None:
        kiem_duong_anh(duong)
        for d in duong:
            nguon = self.db.parent / d
            if nguon.is_file():
                (dich / d).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(nguon, dich / d)
