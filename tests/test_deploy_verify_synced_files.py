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
    # SSH_GIA_HONG=1 ⇒ ssh chết như mất mạng; SSH_GIA_CHET_TU=N ⇒ lượt 1..N-1
    # chạy, từ lượt N chết; SSH_GIA_CUT=1 ⇒ trả thiếu dòng; SSH_GIA_RONG=1 ⇒ rc 0
    # mà không in gì.
    dem = tmp_path / "so-luot-ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\n'
        'shift\n'
        f'n=$(( $(cat "{dem}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{dem}"\n'
        '[ "${SSH_GIA_HONG:-}" = 1 ] && { echo "ssh: connect timed out" >&2; exit 255; }\n'
        '[ -n "${SSH_GIA_CHET_TU:-}" ] && [ "$n" -ge "$SSH_GIA_CHET_TU" ] && '
        '{ echo "ssh: connect timed out" >&2; exit 255; }\n'
        '[ "${SSH_GIA_RONG:-}" = 1 ] && exit 0\n'
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


def test_ssh_chet_o_vong_kiem_xoa_la_phep_do_hong(san):
    """Lượt 1 (sha các tệp gửi) chạy; lượt 2 (tệp xoá còn không) ssh chết. Bản đầu
    đọc 255 thành "vắng" ⇒ rc 0 xanh giả trong khi tệp vẫn nằm trên đích."""
    (san["xa"] / "web/static/cu-bi-xoa.js").write_text("vẫn còn\n", encoding="utf-8")
    r = _chay(san, SSH_GIA_CHET_TU="2")
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "PHÉP ĐO HỎNG" in r.stderr
    assert "vắng  web/static/cu-bi-xoa.js" not in r.stdout


def test_dich_tra_rong_cho_mot_tep_la_phep_do_hong(san):
    """`<<< ""` sinh một dòng rỗng ⇒ với đúng 1 tệp, đếm dòng khớp và ca này
    thành "LỆCH" (4). Đích không trả gì là phép đo hỏng (5)."""
    san["log"].write_text("<f.st.... web/static/settings.js\n", encoding="utf-8")
    r = _chay(san, SSH_GIA_RONG="1")
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "không trả dòng nào" in r.stderr


def test_rsync_khong_gui_gi_thi_noi_ra_so_khong(san):
    san["log"].write_text(".d..t.... web/static/\n", encoding="utf-8")
    r = _chay(san)
    assert r.returncode == 0, r.stderr
    assert "rsync đã gửi 0 tệp, xoá 0 tệp" in r.stdout


def test_script_deploy_goi_ham_nghiem_thu():
    """Cấu trúc: bước 5 gọi hàm, và rsync thật ghi itemize cho hàm đọc. Mã thoát
    thì đo bằng CHẠY script (`test_deploy_script_exit_codes.py`), không grep chữ —
    grep `exit 1` không thấy được lối thoát ngầm của `set -e`."""
    nguon = (REPO / "deploy" / "deploy-to-mini.sh").read_text(encoding="utf-8")
    assert "kiem_tep_da_dong_bo" in nguon, "bước 5 phải gọi hàm nghiệm thu mọi tệp"
    assert "liet_mo_coi" in nguon.split("# --- 4.")[0].split("# --- 3.")[1], \
        "bước 3 phải đo mồ côi — rsync kèm --backup-dir không xoá nên tự nó khai 0"
    assert "--itemize-changes" in nguon.split("# --- 3.")[1].split("# --- 4.")[0], \
        "rsync THẬT (bước 3) phải ghi itemize — không thì hàm nghiệm thu không có gì để đọc"


def _mo_coi(nguon: Path, dich: str, env_path: str) -> subprocess.CompletedProcess:
    lenh = (f'set -euo pipefail; . "{LIB}"; '
            f'liet_mo_coi "$1" --exclude="*.egg-info/"')
    return subprocess.run(["/bin/bash", "-c", lenh, "_", dich], cwd=nguon,
                          env={"PATH": env_path}, capture_output=True, text=True, timeout=30)


def test_mo_coi_duoc_bao_du_rsync_that_khai_xoa_0(san, tmp_path):
    """Bước 3 chạy kèm `--backup-dir` ⇒ openrsync không xoá, khai "xoá 0". Đích
    vẫn có tệp thừa ⇒ lượt đo riêng phải in cảnh báo, chỉ ra đúng tệp đó; tệp bị
    loại trừ (egg-info) thì không phải mồ côi."""
    nguon, dich = san["dev"], tmp_path / "dich"
    shutil.copytree(nguon, dich)
    (dich / "web/static/cu-da-xoa-khoi-git.js").write_text("sót\n", encoding="utf-8")
    (dich / "src/x.egg-info").mkdir(parents=True)
    (dich / "src/x.egg-info/PKG-INFO").write_text("mini cần\n", encoding="utf-8")
    r = _mo_coi(nguon, f"{dich}/", "/usr/bin:/bin")
    assert r.returncode == 0, r.stderr
    assert "mồ côi ở đích: 1 mục" in r.stderr
    assert "web/static/cu-da-xoa-khoi-git.js" in r.stderr
    assert "egg-info" not in r.stderr


def test_mo_coi_bang_0_khi_dich_sach(san, tmp_path):
    nguon, dich = san["dev"], tmp_path / "dich"
    shutil.copytree(nguon, dich)
    r = _mo_coi(nguon, f"{dich}/", "/usr/bin:/bin")
    assert r.returncode == 0, r.stderr
    assert "mồ côi ở đích: 0 tệp" in r.stdout


def test_mo_coi_khong_do_duoc_khong_in_thanh_0(san):
    """rsync trượt (ssh giả chết) ⇒ "CHƯA KẾT LUẬN", mã 5 — không phải "0 tệp"."""
    r = subprocess.run(
        ["/bin/bash", "-c", f'set -euo pipefail; . "{LIB}"; liet_mo_coi "gia-host:~/x/"'],
        cwd=san["dev"], env={"PATH": f"{san['bin']}:/usr/bin:/bin", "SSH_GIA_HONG": "1"},
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "CHƯA KẾT LUẬN" in r.stderr and "0 tệp" not in r.stdout
