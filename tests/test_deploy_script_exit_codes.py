"""Mã thoát của `deploy/deploy-to-mini.sh` — đo bằng CHẠY script, không grep chữ.

Bản trước canh bằng grep `exit 1` trong nguồn. Reviewer 23/09 chỉ ra grep đó mù
với lối thoát NGẦM: dưới `set -euo pipefail`, một `$(ssh …)` chết thoát bằng mã
của chính nó (255, hoặc 1 — trùng "sai máy") trước khi tới dòng `exit` nào.

Mỗi ca: clone repo sạch (không LFS), chép script ĐANG SỬA vào, commit, gắn một
ref origin cho commit đó (để qua cổng "đã đẩy"), rồi chạy với `ssh` giả trên PATH.
Không ca nào tới được rsync/kickstart — ssh giả không bao giờ chạm máy thật.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = ("deploy/deploy-to-mini.sh", "deploy/verify-synced-files.sh")

# ssh giả: đối số cuối là lệnh xa. `KICH_BAN` chọn cách nó hỏng.
SSH_GIA = r'''#!/usr/bin/env bash
cmd="${@: -1}"
[ -n "${SSH_LOG:-}" ] && printf '%s\n' "$*" >> "$SSH_LOG"
case "$KICH_BAN" in
  chet) echo "ssh: connect to host x port 22: Operation timed out" >&2; exit 255 ;;
esac
case "$cmd" in
  hostname) echo "Autos-Mac-mini.local" ;;
  *"launchctl list"*)
    case "$KICH_BAN" in
      launchctl_chet) exit 255 ;;
      thieu_label_minh) printf 'PID\tStatus\tLabel\n1\t0\tcom.astronex.promax\n' ;;
      *) printf 'PID\tStatus\tLabel\n1\t0\tcom.astronex.videodl\n' ;;
    esac ;;
  *sqlite3*)
    case "$KICH_BAN" in
      sqlite_loi) echo "Error: unable to open database file" >&2; exit 1 ;;
      ssh_chet_o_2b) exit 255 ;;
      ban) echo 2 ;;
      *) echo 0 ;;
    esac ;;
  *) exit 0 ;;
esac
'''


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    if shutil.which("git") is None:
        pytest.skip("cần git")
    goc = tmp_path_factory.mktemp("deploy-clone")
    ban = goc / "repo"
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
    subprocess.run(["git", "clone", "-q", "--no-local", str(REPO), str(ban)],
                   check=True, env=env, capture_output=True)
    for s in SCRIPTS:
        shutil.copy(REPO / s, ban / s)
    g = lambda *a: subprocess.run(["git", "-C", str(ban), *a], check=True,  # noqa: E731
                                   capture_output=True, text=True, env=env)
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "script đang sửa",
      "--allow-empty")
    g("update-ref", "refs/remotes/origin/kiem-thu", "HEAD")
    assert g("status", "--porcelain").stdout == "", "clone phải sạch"
    bin_ = goc / "bin"
    bin_.mkdir()
    (bin_ / "ssh").write_text(SSH_GIA, encoding="utf-8")
    (bin_ / "ssh").chmod(0o755)
    # rsync giả: thử khô thì im lặng thành công; chạy thật thì trượt (mã 23, như
    # rsync thật khi truyền dở). Không có nó thì rsync THẬT đi qua ssh giả và
    # trượt cả ở thử khô ⇒ ca "lành" không assert được rc.
    (bin_ / "rsync").write_text(
        '#!/usr/bin/env bash\n'
        'for a in "$@"; do [ "$a" = --dry-run ] && exit 0; done\n'
        'echo "rsync: connection unexpectedly closed" >&2; exit 23\n', encoding="utf-8")
    (bin_ / "rsync").chmod(0o755)
    return ban, bin_


def _chay(clone, kich_ban: str, *args: str, ssh_log: Path | None = None
          ) -> subprocess.CompletedProcess:
    ban, bin_ = clone
    # `VIDEODL_MINI_HOST` là hàng rào THỨ HAI, ngoài ssh/rsync giả trên PATH: nếu
    # một ngày PATH bị đổi và lệnh thật lọt qua, nó trỏ tới một tên miền không
    # bao giờ phân giải được (`.invalid`, RFC 2606) chứ không phải mini.
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(ban.parent), "KICH_BAN": kich_ban,
           "TMPDIR": str(ban.parent), "VIDEODL_MINI_HOST": "kiem-thu.invalid"}
    if ssh_log is not None:
        env["SSH_LOG"] = str(ssh_log)
    return subprocess.run(["/bin/bash", "deploy/deploy-to-mini.sh", *args], cwd=ban, env=env,
                          capture_output=True, text=True, timeout=60)


def test_ssh_chet_o_buoc_0_la_do_hong_khong_phai_sai_may(clone):
    r = _chay(clone, "chet")
    assert r.returncode == 5, (r.returncode, r.stderr)
    assert "PHÉP ĐO HỎNG" in r.stderr


def test_sqlite_truot_o_2b_la_do_hong_khong_phai_sai_may(clone):
    """Ca hay gặp nhất: DB chưa có / không mở được. Bản trước ra mã 1 = "sai máy"."""
    r = _chay(clone, "sqlite_loi")
    assert r.returncode == 5, (r.returncode, r.stderr)
    assert "không đọc được số job" in r.stderr


def test_ssh_chet_o_2b_la_do_hong(clone):
    r = _chay(clone, "ssh_chet_o_2b")
    assert r.returncode == 5, (r.returncode, r.stderr)


def test_co_job_dang_chay_la_3(clone):
    r = _chay(clone, "ban")
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "2 job đang chạy" in r.stderr


def test_thu_kho_lanh_di_toi_2b_va_rc_0(clone):
    """Control: ssh giả lành ⇒ đi hết cổng tới 2b rồi thử khô (rsync giả lập: ssh
    giả trả 0 cho mọi lệnh khác, nên rsync --dry-run sang nó không chạm gì thật)."""
    r = _chay(clone, "lanh")
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert "job đang chạy/chờ: 0" in r.stdout, (r.stdout, r.stderr)
    assert "THỬ KHÔ" in r.stdout


def test_rsync_truot_giua_chung_giu_log_va_in_duong_lui(clone, tmp_path):
    """`--yes`, mọi cổng lành, rsync trượt (ssh giả không nói giao thức rsync).
    Bản trước: `set -e` thoát bằng mã rsync, trap XOÁ log itemize, không in cách lui.
    An toàn: mọi ssh — kể cả vận chuyển của rsync — đi vào ssh giả; test khẳng định
    kickstart không bao giờ được gọi."""
    log = tmp_path / "ssh.log"
    r = _chay(clone, "lanh", "--yes", ssh_log=log)
    assert r.returncode == 4, (r.returncode, r.stderr)
    assert "rsync trượt (rc=23)" in r.stderr and "rollback-on-mini.sh" in r.stderr
    duong = next(d.split(": ", 1)[1] for d in r.stderr.splitlines() if "Tệp đã gửi:" in d)
    assert Path(duong.strip()).exists(), "log itemize phải còn để biết tệp nào đã lên"
    assert "kickstart" not in log.read_text(encoding="utf-8"), "không được tới bước 4"
    Path(duong.strip()).unlink()


def test_ssh_chet_o_buoc_label_la_do_hong(clone):
    """Bản trước: `ten_label … || true` ⇒ ssh chết ra danh sách rỗng, trước = sau =
    rỗng ⇒ cổng label in "không đổi". Giờ không đọc được là mã 5."""
    r = _chay(clone, "launchctl_chet")
    assert r.returncode == 5, (r.returncode, r.stderr)
    assert "không đọc được launchctl" in r.stderr


def test_danh_sach_label_khong_co_chinh_minh_la_do_hong(clone):
    """Control của phép đo: danh sách thật phải thấy `com.astronex.videodl`."""
    r = _chay(clone, "thieu_label_minh")
    assert r.returncode == 5, (r.returncode, r.stderr)
    assert "không có com.astronex.videodl" in r.stderr
