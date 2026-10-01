"""Bảng máy đích dùng chung (`deploy/may-dich.sh`) — deploy, lui và phan_tich_hinh.py
phải trỏ CÙNG một máy theo cùng tham số, và địa chỉ máy chỉ ghi cứng ở bảng đó.

Chạy script THẬT với ssh giả trên PATH (ghi lại đối số); không có lệnh nào ra mạng.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BANG = REPO / "deploy" / "may-dich.sh"

SSH_GIA = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$SSH_LOG"
case "${@: -1}" in hostname) echo "${HOSTNAME_GIA:-Autos-Mac-mini.local}" ;; *) exit 0 ;; esac
"""


def _bang(**env_them) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", **env_them}
    return subprocess.run(["bash", "-c", 'source "$1" && printf "%s|%s" "$HOST" "$EXPECT_HOST"',
                           "_", str(BANG)], capture_output=True, text=True, env=env)


def test_mac_dinh_la_may_cu():
    r = _bang()
    assert r.returncode == 0, r.stderr
    host, expect = r.stdout.split("|")
    assert expect == "autos-mac-mini" and host.startswith("nobi_auto@")


def test_ghi_de_tung_truong():
    r = _bang(VIDEODL_MINI_HOST="svc@100.64.0.9", VIDEODL_MINI_EXPECT_HOST="may-moi")
    assert r.stdout == "svc@100.64.0.9|may-moi"


def test_ghi_de_rieng_host_giu_expect_cu_de_cong_hostname_chan():
    """Chỉ đổi HOST ⇒ EXPECT_HOST vẫn là máy cũ ⇒ cổng hostname sẽ DỪNG nếu trỏ máy khác."""
    assert _bang(VIDEODL_MINI_HOST="svc@x").stdout.endswith("|autos-mac-mini")


def test_ten_may_khong_co_trong_bang_thi_dung():
    r = _bang(VIDEODL_MAY_DICH="khong-co")
    assert r.returncode == 7 and "không có trong bảng máy đích" in r.stderr


@pytest.fixture
def bin_gia(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "ssh").write_text(SSH_GIA, encoding="utf-8")
    (b / "ssh").chmod(0o755)
    (b / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (b / "sleep").chmod(0o755)
    return b


def _lui(bin_gia, tmp_path, **env_them):
    log = tmp_path / "ssh.log"
    env = {"PATH": f"{bin_gia}:/usr/bin:/bin", "HOME": str(tmp_path), "SSH_LOG": str(log), **env_them}
    r = subprocess.run(["/bin/bash", "deploy/rollback-on-mini.sh", "../video-download-truoc-x"],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    return r, (log.read_text().splitlines() if log.exists() else [])


def test_lui_tro_dung_may_theo_tham_so_va_sai_may_thi_dung_truoc_moi_lenh_ghi(bin_gia, tmp_path):
    """Máy đích qua tham số ⇒ MỌI lệnh ssh của lui đi tới đúng host đó; hostname bên kia
    không khớp ⇒ DỪNG ở bước 0, chỉ đúng 1 lệnh ssh (hỏi tên) — không cp/kickstart nào."""
    r, lenh = _lui(bin_gia, tmp_path, VIDEODL_MINI_HOST="svc@m4.invalid",
                   VIDEODL_MINI_EXPECT_HOST="may-moi", HOSTNAME_GIA="Autos-Mac-mini.local")
    assert r.returncode == 1 and "không phải may-moi" in r.stderr
    assert "máy đích: svc@m4.invalid" in r.stdout
    assert len(lenh) == 1 and "svc@m4.invalid" in lenh[0] and lenh[0].endswith("hostname")


def test_lui_dung_may_thi_moi_lenh_ssh_deu_toi_may_do(bin_gia, tmp_path):
    r, lenh = _lui(bin_gia, tmp_path, VIDEODL_MINI_HOST="svc@m4.invalid",
                   VIDEODL_MINI_EXPECT_HOST="may-moi", HOSTNAME_GIA="May-Moi.local")
    assert len(lenh) > 3, (r.returncode, r.stdout, r.stderr)
    assert all("svc@m4.invalid" in d for d in lenh)


def test_deploy_ten_may_la_dung_truoc_khi_ssh(bin_gia, tmp_path):
    log = tmp_path / "ssh.log"
    env = {"PATH": f"{bin_gia}:/usr/bin:/bin", "HOME": str(tmp_path), "SSH_LOG": str(log),
           "VIDEODL_MAY_DICH": "khong-co"}
    r = subprocess.run(["/bin/bash", "deploy/deploy-to-mini.sh"], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 7 and "không có trong bảng máy đích" in r.stderr
    assert not log.exists(), "không được ssh đi đâu khi tên máy sai"


def test_phan_tich_hinh_dung_cung_bang():
    spec = importlib.util.spec_from_file_location(
        "pth", REPO / "scripts" / "tu-chia-cum" / "phan_tich_hinh.py")
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "tu-chia-cum"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    goc = {k: v for k, v in os.environ.items() if not k.startswith("VIDEODL_")}
    assert mod.host_mac_dinh(goc) == _bang().stdout.split("|")[0]
    assert mod.host_mac_dinh({**goc, "VIDEODL_MINI_HOST": "svc@y"}) == "svc@y"
    with pytest.raises(ValueError):
        mod.host_mac_dinh({**goc, "VIDEODL_MAY_DICH": "khong-co"})


def test_dia_chi_may_chi_ghi_cung_o_bang():
    r = subprocess.run(["git", "-C", str(REPO), "grep", "-nE", r"100\.109\.39\.103|autos-mac-mini",
                        "--", "deploy/", "scripts/", "src/", "web/"], capture_output=True, text=True)
    dong = [d for d in r.stdout.splitlines() if d]
    assert dong and all(d.startswith("deploy/may-dich.sh:") for d in dong), dong


def test_lui_va_deploy_goi_qua_symlink_van_thay_bang(bin_gia, tmp_path):
    """Symlink đặt NGOÀI `deploy/` vẫn tìm thấy bảng (theo tệp thật), và lui đi tới máy
    theo tham số. Đột biến `$(dirname "$0")` ⇒ 'may-dich.sh: No such file' ⇒ ĐỎ."""
    lnk = tmp_path / "lnk"
    lnk.mkdir()
    (lnk / "lui.sh").symlink_to(REPO / "deploy" / "rollback-on-mini.sh")
    log = tmp_path / "ssh.log"
    env = {"PATH": f"{bin_gia}:/usr/bin:/bin", "HOME": str(tmp_path), "SSH_LOG": str(log),
           "VIDEODL_MINI_HOST": "svc@m4.invalid", "VIDEODL_MINI_EXPECT_HOST": "may-moi"}
    r = subprocess.run(["/bin/bash", str(lnk / "lui.sh"), "../x"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=30)
    assert "may-dich.sh" not in r.stderr, r.stderr
    assert "máy đích: svc@m4.invalid" in r.stdout
    lenh = log.read_text().splitlines()
    assert lenh and all("svc@m4.invalid" in d for d in lenh), lenh


def test_phan_tich_hinh_bien_rong_van_bi_tu_choi_va_thieu_bash_la_valueerror():
    spec = importlib.util.spec_from_file_location(
        "pth2", REPO / "scripts" / "tu-chia-cum" / "phan_tich_hinh.py")
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "tu-chia-cum"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    goc = {k: v for k, v in os.environ.items() if not k.startswith("VIDEODL_")}
    assert mod.host_mac_dinh({**goc, "VIDEODL_MINI_HOST": ""}) == "", \
        "biến rỗng không được rơi về máy thật — MiniSsh sẽ từ chối chuỗi rỗng"
    with pytest.raises(ValueError):
        mod.host_mac_dinh({**goc, "PATH": "/khong-co-bash"})
