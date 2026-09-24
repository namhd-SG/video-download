"""Gỡ tệp đã xoá khỏi git trên mini — `deploy/prune-git-deleted-files.sh`.

Chạy hàm bash THẬT trên một repo git THẬT (hai commit dựng trong tmp) và một
rsync THẬT (openrsync máy dev) sang thư mục cục bộ đóng vai repo trên mini. Chỉ
`ssh` là giả: bỏ tham số host rồi chạy lệnh trong home giả.

Các ca đột biến là yêu cầu của điều phối (tin ĐP-2, 24/09): giả một tệp thừa trên
đích ⇒ hàm phải bắt được; bỏ vế gỡ (`mv` không làm gì) ⇒ đo lại phải ĐỎ.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "deploy" / "prune-git-deleted-files.sh"
REMOTE_REPO = "Projects/video-download"
BAN_LUI = "../video-download-truoc-kiem-thu"
# Cùng hình dạng với EXCLUDES của deploy-to-mini.sh cho các mục test chạm tới.
EXCLUDES = ["--exclude=.git", "--exclude=assets/ffmpeg-static", "--exclude=/.deployed-sha"]

TEP_A = {
    "web/app.py": "print('giữ')\n",
    "web/cu.js": "// sẽ xoá\n",
    "web/có dấu cách.txt": "sẽ xoá, tên khó\n",
    "web/doi_ten.py": "x = 1\n",
    "assets/ffmpeg-static/ffmpeg": "nhị phân giả — mini cấp riêng bằng scp\n",
}


def _g(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def _ghi(goc: Path, tep: dict[str, str]) -> None:
    for duong, noi_dung in tep.items():
        p = goc / duong
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(noi_dung, encoding="utf-8")


@pytest.fixture
def san(tmp_path: Path):
    for c in ("bash", "git", "rsync"):
        if shutil.which(c) is None:
            pytest.skip(f"cần {c} — không có thì test này KHÔNG chạy")
    dev, home, bin_ = tmp_path / "dev", tmp_path / "home-mini", tmp_path / "bin"
    dev.mkdir()
    _g(dev, "init", "-q")
    _ghi(dev, TEP_A)
    _g(dev, "add", "-A")
    _g(dev, "commit", "-qm", "A")
    moc = _g(dev, "rev-parse", "HEAD")
    # B: xoá 2 tệp, ĐỔI TÊN 1 tệp (bẫy `--diff-filter=D` không kèm `--no-renames`),
    # và xoá ffmpeg khỏi git (bị exclude ⇒ mini vẫn cần, không được gỡ).
    _g(dev, "rm", "-q", "web/cu.js", "web/có dấu cách.txt", "assets/ffmpeg-static/ffmpeg")
    _g(dev, "mv", "web/doi_ten.py", "web/ten_moi.py")
    _g(dev, "commit", "-qm", "B")
    head = _g(dev, "rev-parse", "HEAD")

    # Đích = cây A (như sau lần deploy trước) + cây B (rsync không xoá gì) + một
    # tệp git chưa từng biết.
    xa = home / REMOTE_REPO
    _ghi(xa, TEP_A)
    _ghi(xa, {"web/ten_moi.py": "x = 1\n", "web/tu-sinh-tren-mini.txt": "không ai biết\n"})
    (xa / ".deployed-sha").write_text(moc + "\n", encoding="utf-8")

    bin_.mkdir()
    ssh = bin_ / "ssh"
    # SSH_GIA_HONG=1 ⇒ ssh chết như mất mạng · SSH_GIA_BO_MV=1 ⇒ `mv` phía xa
    # thành no-op (đột biến "gỡ không xảy ra" mà vòng lặp vẫn đếm).
    ssh.write_text(
        '#!/usr/bin/env bash\n'
        'shift\n'
        '[ "${SSH_GIA_HONG:-}" = 1 ] && { echo "ssh: connect timed out" >&2; exit 255; }\n'
        f'cd "{home}" || exit 255\n'
        'if [ "${SSH_GIA_BO_MV:-}" = 1 ]; then\n'
        f'  HOME="{home}" exec bash -c "mv() {{ :; }}; $*"\n'
        'fi\n'
        f'HOME="{home}" exec bash -c "$*"\n', encoding="utf-8")
    ssh.chmod(0o755)
    return {"dev": dev, "xa": xa, "home": home, "bin": bin_, "moc": moc, "head": head}


def _chay(san, ham: str, *args: str, **env_them) -> subprocess.CompletedProcess:
    """`set -euo pipefail` như script deploy: bash 3.2 nổ với mảng rỗng dưới `-u`."""
    env = {"PATH": f"{san['bin']}:/usr/bin:/bin", **env_them}
    return subprocess.run(["/bin/bash", "-c", f'set -euo pipefail; . "{LIB}"; {ham} "$@"', "_", *args],
                          cwd=san["dev"], env=env, capture_output=True, text=True, timeout=60)


def _don(san, that: str, moc: str | None = None, **env):
    return _chay(san, "don_tep_xoa_theo_git", moc or san["moc"], san["head"],
                 f"{san['xa']}/", "gia-host", REMOTE_REPO, BAN_LUI, that, *EXCLUDES, **env)


def test_go_dung_tep_xoa_khoi_git_va_dem_lai_bang_0(san):
    r = _don(san, "1")
    assert r.returncode == 0, (r.stdout, r.stderr)
    # 4 = cu.js + có dấu cách + doi_ten.py (đổi tên) + ffmpeg
    assert "tệp xoá khỏi git" in r.stdout and ": 4" in r.stdout, r.stdout
    assert "cần gỡ trên đích: 3 · bỏ qua (đã vắng hoặc bị loại trừ khỏi rsync): 1" in r.stdout
    assert "đã gỡ (mv vào video-download-truoc-kiem-thu): 3" in r.stdout
    assert "còn lại trên đích (đo lại): 0 / 3" in r.stdout
    xa, lui = san["xa"], san["home"] / "Projects/video-download-truoc-kiem-thu"
    for f in ("web/cu.js", "web/có dấu cách.txt", "web/doi_ten.py"):
        assert not (xa / f).exists(), f
        assert (lui / f).exists(), f"{f} phải nằm trong bản lui để rollback đưa về"
    # Không được đụng: thứ mini cấp riêng, thứ git chưa từng biết, thứ còn dùng.
    assert (xa / "assets/ffmpeg-static/ffmpeg").exists()
    assert (xa / "web/tu-sinh-tren-mini.txt").exists()
    assert (xa / "web/ten_moi.py").exists() and (xa / "web/app.py").exists()


def test_thu_kho_liet_ra_ma_khong_go(san):
    """Đột biến "giả một tệp thừa": thử khô phải NHÌN THẤY nó, và không đụng."""
    r = _don(san, "0")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "cần gỡ trên đích: 3" in r.stdout
    assert "- web/cu.js" in r.stdout and "- web/có dấu cách.txt" in r.stdout
    assert "chưa gỡ tệp nào" in r.stdout
    assert (san["xa"] / "web/cu.js").exists()


def test_doi_ten_khong_bi_bo_sot(san):
    """Không `--no-renames` thì git gộp xoá+thêm thành R và tệp cũ lọt khỏi D."""
    r = _don(san, "1")
    assert "- web/doi_ten.py" in r.stdout, r.stdout
    assert not (san["xa"] / "web/doi_ten.py").exists()


def test_dot_bien_mv_khong_lam_gi_thi_do_lai_do(san):
    """Vòng mv tự đếm 3 (nó không biết mv là no-op) — chỉ phép đo lại phía đích
    mới thấy tệp còn nguyên. Không có phép đo lại thì ca này xanh giả."""
    r = _don(san, "1", SSH_GIA_BO_MV="1")
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "còn lại trên đích (đo lại): 3 / 3" in r.stdout
    assert (san["xa"] / "web/cu.js").exists()


def test_tep_xoa_da_vang_tren_dich_thi_0_can_go(san):
    for f in ("web/cu.js", "web/có dấu cách.txt", "web/doi_ten.py"):
        (san["xa"] / f).unlink()
    r = _don(san, "1")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "cần gỡ trên đích: 0 · bỏ qua (đã vắng hoặc bị loại trừ khỏi rsync): 4" in r.stdout


def test_moc_bang_head_thi_0_tep(san):
    r = _don(san, "1", moc=san["head"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert ": 0" in r.stdout and "còn lại: 0" in r.stdout


def test_moc_khong_co_trong_repo_la_chua_ket_luan(san):
    r = _don(san, "1", moc="1" * 40)
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "CHƯA KẾT LUẬN" in r.stderr
    assert (san["xa"] / "web/cu.js").exists()


def test_ssh_chet_khi_go_la_chua_ket_luan(san):
    r = _don(san, "1", SSH_GIA_HONG="1")
    assert r.returncode == 5, (r.stdout, r.stderr)
    assert "CHƯA KẾT LUẬN" in r.stderr


# ---- đọc / ghi mốc

def test_doc_moc_co_san(san):
    r = _chay(san, "doc_moc_da_deploy", "gia-host", REMOTE_REPO)
    assert r.returncode == 0 and r.stdout.strip() == san["moc"], (r.stdout, r.stderr)


def test_doc_moc_chua_co_la_6_khong_phai_0_tep(san):
    (san["xa"] / ".deployed-sha").unlink()
    r = _chay(san, "doc_moc_da_deploy", "gia-host", REMOTE_REPO)
    assert r.returncode == 6 and r.stdout == "", (r.returncode, r.stdout)


def test_doc_moc_rac_la_do_hong(san):
    (san["xa"] / ".deployed-sha").write_text("không phải sha\n", encoding="utf-8")
    r = _chay(san, "doc_moc_da_deploy", "gia-host", REMOTE_REPO)
    assert r.returncode == 5, (r.returncode, r.stdout)


def test_doc_moc_ssh_chet_la_do_hong(san):
    r = _chay(san, "doc_moc_da_deploy", "gia-host", REMOTE_REPO, SSH_GIA_HONG="1")
    assert r.returncode == 5


def test_ghi_moc_roi_doc_lai(san):
    r = _chay(san, "ghi_moc_da_deploy", "gia-host", REMOTE_REPO, san["head"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (san["xa"] / ".deployed-sha").read_text(encoding="utf-8").strip() == san["head"]
    assert not (san["xa"] / ".deployed-sha.tmp").exists()


def test_rollback_dua_tep_da_go_ve(san):
    """Lệnh chép ngược của `rollback-on-mini.sh` (`cp -R <bản lui>/. <repo>/`)
    phải đưa tệp đã gỡ về chỗ cũ."""
    assert _don(san, "1").returncode == 0
    lui = san["home"] / "Projects/video-download-truoc-kiem-thu"
    subprocess.run(["cp", "-R", f"{lui}/.", f"{san['xa']}/"], check=True)
    assert (san["xa"] / "web/có dấu cách.txt").read_text(encoding="utf-8") == "sẽ xoá, tên khó\n"
