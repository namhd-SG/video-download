"""Nghiệm thu sau rsync của `deploy/deploy-to-mini.sh` — mọi tệp, không phải ba tên cứng.

Chạy hàm bash THẬT `kiem_tep_da_dong_bo` (`deploy/verify-synced-files.sh`), với
`ssh` là một bản giả trên PATH: nó bỏ tham số host rồi chạy lệnh trong một thư
mục cục bộ đóng vai home của máy đích.

Các dòng itemize dưới đây CHÉP NGUYÊN VĂN từ output thật, không tự dựng:
`<f…` từ lần thử khô deploy lên mini ngày 23/09 (openrsync protocol 29, đẩy lên
máy xa); `*deleting ` từ openrsync chạy cục bộ cùng ngày. Fixture tự dựng chỉ
chứa thứ người viết NGHĨ là định dạng — và bản thử khô đã cho thấy cột cờ dài 9
ký tự chứ không phải 11 như rsync GNU.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "deploy" / "verify-synced-files.sh"
REMOTE_REPO = "Projects/video-download"

ITEMIZE_THAT = """\
.d..t.... plans/
cd+++++++ plans/260923-1023-cookie-ui/
<f+++++++ plans/260923-1023-cookie-ui/baseline/baseline.md
<f.st.... tests/test_web_app.py
.d..t.... web/static/
<f.st.... web/static/settings.js
<f+++++++ web/static/co cach.txt
*deleting web/static/cu-bi-xoa.js
"""

TEP = {
    "plans/260923-1023-cookie-ui/baseline/baseline.md": "# baseline\n",
    "tests/test_web_app.py": "def test_x(): pass\n",
    "web/static/settings.js": "// settings mới\n",
    "web/static/co cach.txt": "tên có dấu cách\n",
}


def _ghi(goc: Path, tep: dict[str, str]) -> None:
    for duong, noi_dung in tep.items():
        p = goc / duong
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(noi_dung, encoding="utf-8")


@pytest.fixture
def san(tmp_path: Path):
    """dev/ = cây máy dev · xa/ = home máy đích · bin/ssh = ssh giả."""
    if shutil.which("bash") is None or shutil.which("shasum") is None:
        pytest.skip("cần bash + shasum — không có thì test này KHÔNG chạy")
    dev, xa, bin_ = tmp_path / "dev", tmp_path / "xa", tmp_path / "bin"
    _ghi(dev, TEP)
    _ghi(xa / REMOTE_REPO, TEP)  # đích khớp dev — ca lành
    bin_.mkdir()
    ssh = bin_ / "ssh"
    # SSH_GIA_HONG=1 ⇒ ssh chết như mất mạng; SSH_GIA_CUT=1 ⇒ trả thiếu dòng.
    ssh.write_text(
        '#!/usr/bin/env bash\n'
        'shift\n'
        '[ "${SSH_GIA_HONG:-}" = 1 ] && { echo "ssh: connect timed out" >&2; exit 255; }\n'
        f'cd "{xa}" || exit 255\n'
        f'if [ "${{SSH_GIA_CUT:-}}" = 1 ]; then HOME="{xa}" bash -c "$*" | head -1; '
        f'else HOME="{xa}" exec bash -c "$*"; fi\n',
        encoding="utf-8")
    ssh.chmod(0o755)
    log = tmp_path / "itemize.txt"
    log.write_text(ITEMIZE_THAT, encoding="utf-8")
    return {"dev": dev, "xa": xa / REMOTE_REPO, "bin": bin_, "log": log}


def _chay(san, **env_them) -> subprocess.CompletedProcess:
    """`/bin/bash` + `set -euo pipefail`: ĐÚNG môi trường script deploy gọi hàm.
    Bash 3.2 của macOS nổ "unbound variable" với mảng rỗng dưới `set -u` —
    chạy thiếu hai thứ này thì test xanh cho một hàm chết trên đường thật."""
    env = {"PATH": f"{san['bin']}:/usr/bin:/bin", **env_them}
    return subprocess.run(
        ["/bin/bash", "-c", f'set -euo pipefail; . "{LIB}"; kiem_tep_da_dong_bo "$1" gia-host {REMOTE_REPO}',
         "_", str(san["log"])],
        cwd=san["dev"], env=env, capture_output=True, text=True, timeout=30)


def test_khop_het_va_tep_xoa_da_vang(san):
    r = _chay(san)
    assert r.returncode == 0, r.stderr
    # Đếm từ đúng các dòng `<f` và `*deleting` — `cd`/`.d` là thư mục, bỏ qua.
    assert "rsync đã gửi 4 tệp, xoá 1 tệp" in r.stdout
    for duong in TEP:
        assert f"khớp  {duong}" in r.stdout, duong
    assert "vắng  web/static/cu-bi-xoa.js" in r.stdout


def test_tep_ngoai_ba_ten_cung_lech_thi_do(san):
    """Ca thật 23/09: chỉ settings.js đổi. Vòng cũ (index/app.js/app.css) mù với nó."""
    (san["xa"] / "web/static/settings.js").write_text("// settings CŨ\n", encoding="utf-8")
    r = _chay(san)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "LỆCH  web/static/settings.js" in r.stderr


def test_tep_gui_ma_dich_khong_co_thi_do(san):
    (san["xa"] / "web/static/co cach.txt").unlink()
    r = _chay(san)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "LỆCH  web/static/co cach.txt" in r.stderr


def test_tep_rsync_bao_xoa_ma_con_thi_do(san):
    (san["xa"] / "web/static/cu-bi-xoa.js").write_text("sót\n", encoding="utf-8")
    r = _chay(san)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "CÒN   web/static/cu-bi-xoa.js" in r.stderr


def test_ssh_chet_la_phep_do_hong_khong_phai_lech(san):
    r = _chay(san, SSH_GIA_HONG="1")
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "PHÉP ĐO HỎNG" in r.stderr
    assert "LỆCH" not in r.stderr


def test_dich_tra_thieu_dong_la_phep_do_hong(san):
    """Không bắt thì các tệp cuối danh sách được coi như chưa từng hỏi — và xanh."""
    r = _chay(san, SSH_GIA_CUT="1")
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "đích trả 1 dòng" in r.stderr


def test_rsync_khong_gui_gi_thi_noi_ra_so_khong(san):
    san["log"].write_text(".d..t.... web/static/\n", encoding="utf-8")
    r = _chay(san)
    assert r.returncode == 0, r.stderr
    assert "rsync đã gửi 0 tệp, xoá 0 tệp" in r.stdout


def test_script_deploy_khong_con_exit_1_tran():
    """Mỗi kết cục một mã. `exit 1` trần làm "cây bẩn" trùng mã với "sai máy"."""
    nguon = (REPO / "deploy" / "deploy-to-mini.sh").read_text(encoding="utf-8")
    dong = [d.strip() for d in nguon.splitlines() if not d.lstrip().startswith("#")]
    assert not [d for d in dong if d.endswith("exit 1") or "exit 1;" in d]
    assert "kiem_tep_da_dong_bo" in nguon, "bước 5 phải gọi hàm nghiệm thu mọi tệp"
    assert "--itemize-changes" in nguon.split("# --- 3.")[1].split("# --- 4.")[0], \
        "rsync THẬT (bước 3) phải ghi itemize — không thì hàm nghiệm thu không có gì để đọc"
