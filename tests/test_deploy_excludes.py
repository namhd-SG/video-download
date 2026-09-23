"""`deploy/deploy-to-mini.sh` không được đẩy tệp git-ignore lên mini.

Chạy rsync THẬT (`/usr/bin/rsync`, cùng bản với lúc deploy) với ĐÚNG mảng
`EXCLUDES` trích từ script, trên một cây giả có đủ loại rác đã gặp trên mini
ngày 23/09 (`.claude/agent-memory`, `.pytest_cache`, `*.egg-info`). Không đọc
chuỗi trong script để "tin" là có exclude — đo xem rsync gửi gì.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "deploy-to-mini.sh"
RSYNC = "/usr/bin/rsync"


def _excludes() -> str:
    """Khối `EXCLUDES=( … )` nguyên văn của script, để bash dựng lại mảng."""
    m = re.search(r"^EXCLUDES=\(\n.*?^\)$", SCRIPT.read_text(encoding="utf-8"),
                  re.S | re.M)
    assert m, "không tìm thấy khối EXCLUDES trong deploy-to-mini.sh"
    return m.group(0)


def _gui(nguon: Path, dich: Path) -> list[str]:
    """Tệp rsync SẼ gửi từ `nguon` sang `dich` với EXCLUDES của script."""
    lenh = (_excludes() + "\n"
            f'"{RSYNC}" -a --dry-run --itemize-changes --delete "${{EXCLUDES[@]}}" ./ "{dich}/"')
    r = subprocess.run(["/bin/bash", "-c", lenh], cwd=nguon,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


@pytest.fixture
def cay(tmp_path: Path):
    if not Path(RSYNC).exists() or shutil.which("bash") is None:
        pytest.skip("cần /usr/bin/rsync + bash — không có thì test này KHÔNG chạy")
    nguon, dich = tmp_path / "dev", tmp_path / "mini"
    for duong in ("web/static/app.js",
                  ".claude/agent-memory/kongming/MEMORY.md",
                  ".pytest_cache/v/cache/nodeids",
                  "src/tiktok_music_downloader.egg-info/PKG-INFO",
                  ".DS_Store"):
        p = nguon / duong
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    # `.gitignore` THẬT của repo: exclude-from đọc nó, nên fixture dùng đúng nó.
    shutil.copy(REPO / ".gitignore", nguon / ".gitignore")
    dich.mkdir()
    return nguon, dich


def test_chi_gui_tep_that_khong_gui_rac_ignore(cay):
    nguon, dich = cay
    gui = [d.split(" ", 1)[1] for d in _gui(nguon, dich) if d[1:2] == "f"]
    assert "web/static/app.js" in gui, "control: tệp code phải được gửi"
    for rac in (".claude/", ".pytest_cache/", ".egg-info/", ".DS_Store"):
        assert not [g for g in gui if rac in g], f"{rac} bị đẩy lên mini: {gui}"


def test_egg_info_tren_mini_khong_bi_delete_cham(cay):
    """Mini cần egg-info cho bản cài editable. Nó chỉ có ở phía nhận; bị loại trừ
    thì `--delete` phải để yên. Control: tệp thừa KHÔNG bị loại vẫn bị xoá."""
    nguon, dich = cay
    # CHỈ ở phía nhận — như khi deploy từ một checkout sạch không có egg-info.
    # Để nó ở cả nguồn thì rsync GỬI nó chứ không xoá, và test xanh cho mọi bản.
    shutil.rmtree(nguon / "src" / "tiktok_music_downloader.egg-info")
    for duong in ("src/tiktok_music_downloader.egg-info/PKG-INFO", "thua-tren-mini.txt"):
        p = dich / duong
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("mini\n", encoding="utf-8")
    xoa = [d for d in _gui(nguon, dich) if d.startswith("*deleting")]
    assert any("thua-tren-mini.txt" in d for d in xoa), \
        f"control: --delete phải còn xoá tệp thừa không bị loại trừ: {xoa}"
    assert not any("egg-info" in d for d in xoa), f"--delete chạm egg-info: {xoa}"
