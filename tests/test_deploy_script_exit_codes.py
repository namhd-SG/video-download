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
da_kickstart() { [ -n "${SSH_LOG:-}" ] && grep -q "launchctl kickstart" "$SSH_LOG"; }
case "$cmd" in
  hostname) echo "Autos-Mac-mini.local" ;;
  *"launchctl kickstart"*) exit 0 ;;
  *"launchctl list"*)
    case "$KICH_BAN" in
      launchctl_chet) exit 255 ;;
      thieu_label_minh) printf 'PID\tStatus\tLabel\n1\t0\tcom.astronex.promax\n' ;;
      label_doi) printf 'PID\tStatus\tLabel\n1\t0\tcom.astronex.videodl\n'
                 if da_kickstart; then printf '2\t0\tcom.astronex.la\n'; fi ;;
      *) printf 'PID\tStatus\tLabel\n1\t0\tcom.astronex.videodl\n' ;;
    esac ;;
  *sqlite3*)
    case "$KICH_BAN" in
      sqlite_loi) echo "Error: unable to open database file" >&2; exit 1 ;;
      ssh_chet_o_2b) exit 255 ;;
      ban) echo 2 ;;
      *) echo 0 ;;
    esac ;;
  *"/healthz"*) echo "${HEALTHZ_GIA:-200}" ;;
  *"curl -s -D -"*) [ "$KICH_BAN" = cc_chet ] && exit 255; echo "cache-control: no-cache" ;;
  *lsof*) [ "$KICH_BAN" = cc_chet ] && exit 255; echo 1 ;;
  *"| shasum"*)
    # sha của tệp tĩnh "đang phục vụ" = sha của chính tệp trong bản clone (cwd).
    f="$(printf '%s' "$cmd" | sed -E 's|.*127\.0\.0\.1:[0-9]+/([^ ]+) .*|\1|')"
    if [ "$KICH_BAN" = static_lech ]; then echo 0000000000; else shasum -a 256 "web/static/$f" | cut -d' ' -f1; fi ;;
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
    # RSYNC_GIA=thanh_cong ⇒ chạy thật cũng thành công (gửi 0 tệp) để đi tới bước 4-5.
    (bin_ / "rsync").write_text(
        '#!/usr/bin/env bash\n'
        'for a in "$@"; do [ "$a" = --dry-run ] && exit 0; done\n'
        '[ "${RSYNC_GIA:-}" = thanh_cong ] && exit 0\n'
        'echo "rsync: connection unexpectedly closed" >&2; exit 23\n', encoding="utf-8")
    (bin_ / "rsync").chmod(0o755)
    # `sleep` giả: vòng healthz 10 × 2 giây không làm test chậm 24 giây.
    (bin_ / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_ / "sleep").chmod(0o755)
    return ban, bin_


def _chay(clone, kich_ban: str, *args: str, ssh_log: Path | None = None,
          **env_them: str) -> subprocess.CompletedProcess:
    ban, bin_ = clone
    # `VIDEODL_MINI_HOST` là hàng rào THỨ HAI, ngoài ssh/rsync giả trên PATH: nếu
    # một ngày PATH bị đổi và lệnh thật lọt qua, nó trỏ tới một tên miền không
    # bao giờ phân giải được (`.invalid`, RFC 2606) chứ không phải mini.
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(ban.parent), "KICH_BAN": kich_ban,
           "TMPDIR": str(ban.parent), "VIDEODL_MINI_HOST": "kiem-thu.invalid"}
    if ssh_log is not None:
        env["SSH_LOG"] = str(ssh_log)
    env.update(env_them)
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



# ---- Bước 4-5: đi QUA kickstart. Trước đây không test nào tới đây: bỏ cổng
# healthz đi thì bộ test vẫn xanh (reviewer 23/09, lần soát 2).

def _yes(clone, tmp_path, kich_ban="lanh", **env):
    log = tmp_path / "ssh.log"
    r = _chay(clone, kich_ban, "--yes", ssh_log=log, RSYNC_GIA="thanh_cong", **env)
    return r, log.read_text(encoding="utf-8")


def test_di_het_buoc_5_lanh_la_xong(clone, tmp_path):
    """Control cho các ca dưới: mọi thứ lành ⇒ rc 0, có kickstart, in XONG."""
    r, log = _yes(clone, tmp_path)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert "launchctl kickstart" in log and "== XONG" in r.stdout


def test_healthz_khong_len_la_4_va_in_duong_lui(clone, tmp_path):
    r, log = _yes(clone, tmp_path, HEALTHZ_GIA="000")
    assert r.returncode == 4, (r.returncode, r.stderr)
    assert "healthz không lên" in r.stderr and "rollback-on-mini.sh" in r.stderr
    assert "launchctl kickstart" in log, "ca này phải đi qua kickstart mới có nghĩa"


def test_tep_tinh_phuc_vu_lech_la_4(clone, tmp_path):
    r, _ = _yes(clone, tmp_path, "static_lech")
    assert r.returncode == 4, (r.returncode, r.stderr)
    assert "LỆCH" in r.stderr


def test_label_doi_sau_deploy_la_4(clone, tmp_path):
    r, _ = _yes(clone, tmp_path, "label_doi")
    assert r.returncode == 4, (r.returncode, r.stderr)
    assert "label astronex ĐỔI" in r.stderr


def test_doc_cache_control_truot_khong_thoat_im_lang(clone, tmp_path):
    """Bản trước: `cc=$(ssh …)` chết ⇒ `set -e` thoát 255 ngay sau kickstart,
    không in gì. Hai dòng đó là thông tin: đo hỏng thì nói ra rồi đi tiếp."""
    r, _ = _yes(clone, tmp_path, "cc_chet")
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert "cache-control: không đọc được" in r.stderr
    assert "bind 127.0.0.1: không đọc được" in r.stderr
