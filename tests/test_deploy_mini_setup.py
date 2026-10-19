"""`deploy/mini-setup.sh` chạy TRỌN trong HOME giả với python/pip/launchctl/curl/lsof giả trên PATH — không lệnh nào ra mạng,
không đụng launchd thật. Kiểm hành vi trên máy đích mới: cài đủ extra thay logo, chặn khi thiếu OpenCV, và dịch vụ chạy theo giờ VN
dù giờ máy là giờ khác (ca-n: America/Los_Angeles)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# python giả: `-m venv` dựng .venv giả (pip/python/playwright/uvicorn ghi lại đối số); `-c` theo CV2_CO quyết import cv2 có được không.
PY_GIA = r"""#!/usr/bin/env bash
case "$1" in
  -V) echo "Python 3.12.15" ;;
  -m) [ "$2" = venv ] || exit 2
      v="$3"; mkdir -p "$v/bin"
      printf '#!/usr/bin/env bash\necho "pip $*" >> "$LOG"\n' > "$v/bin/pip"
      printf '#!/usr/bin/env bash\necho "playwright $* PBP=${PLAYWRIGHT_BROWSERS_PATH:-}" >> "$LOG"\n' > "$v/bin/playwright"
      cat > "$v/bin/python" <<'P'
#!/usr/bin/env bash
if [ "$1" = -c ]; then echo "python -c $2" >> "$LOG"; case "$2" in *cv2*) [ "${CV2_CO:-1}" = 1 ] || exit 1 ;; esac; exit 0; fi
cat > /dev/null; echo "python stdin" >> "$LOG"; exit 0
P
      printf '#!/usr/bin/env bash\necho "uvicorn TZ=$TZ $*" >> "$LOG"\n' > "$v/bin/uvicorn"
      chmod +x "$v/bin/"* ;;
esac
"""


def _gia(b: Path, ten: str, noi_dung: str) -> None:
    (b / ten).write_text(noi_dung, encoding="utf-8")
    (b / ten).chmod(0o755)


@pytest.fixture
def san(tmp_path):
    home = tmp_path / "home"
    repo = home / "Projects" / "video-download"
    (repo / "deploy").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    ff = repo / "assets" / "ffmpeg-static"
    ff.mkdir(parents=True)
    _gia(ff, "ffmpeg", "#!/usr/bin/env bash\necho 'ffmpeg version gia'\n")
    (home / "Library" / "Caches" / "ms-playwright").mkdir(parents=True)  # bỏ qua tải Chromium
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    cfg = home / ".config" / "videodl"
    cfg.mkdir(parents=True)
    (cfg / "env").write_text("GDRIVE_SERVICE_ACCOUNT_FILE=/khong-dung\n", encoding="utf-8")
    b = tmp_path / "bin"
    b.mkdir()
    _gia(b, "python-gia", PY_GIA)
    _gia(b, "launchctl", '#!/usr/bin/env bash\ncase "$1" in list) echo "PID Status Label";; print) exit 1;; esac\nexit 0\n')
    # curl giả: lời gọi healthz trả 000 ở CURL_LOI_DAU lần đầu (dịch vụ chưa lên) rồi 200; mọi lời gọi khác trả 200.
    _gia(b, "curl", '#!/usr/bin/env bash\ncase "$*" in *healthz*) d="$LOG.healthz"; n=$(( $(cat "$d" 2>/dev/null || echo 0) + 1 )); '
                    'echo $n > "$d"; [ "$n" -le "${CURL_LOI_DAU:-0}" ] && { echo 000; exit 0; } ;; esac\necho 200\n')
    _gia(b, "lsof", "#!/usr/bin/env bash\necho 'python 1 u 3u IPv4 TCP 127.0.0.1:7870 (LISTEN)'\n")
    _gia(b, "plutil", "#!/usr/bin/env bash\nexit 0\n")
    _gia(b, "sleep", "#!/usr/bin/env bash\nexit 0\n")
    return home, repo, b, tmp_path / "lenh.log"


def _chay(san, **env_them):
    home, repo, b, log = san
    env = {"PATH": f"{b}:/usr/bin:/bin", "HOME": str(home), "LOG": str(log), "VIDEODL_PY": str(b / "python-gia"),
           "TZ": "America/Los_Angeles", **env_them}
    r = subprocess.run(["/bin/bash", str(REPO / "deploy" / "mini-setup.sh")], env=env, capture_output=True, text=True, timeout=60)
    return r, (log.read_text().splitlines() if log.exists() else [])


def test_cai_kem_extra_thay_logo_va_kiem_opencv(san):
    r, lenh = _chay(san)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert any(d.startswith("pip install") and "[web,thay-logo]" in d for d in lenh), lenh
    assert any("import cv2" in d for d in lenh), lenh


def test_thieu_opencv_thi_dung_truoc_khi_dung_dich_vu(san):
    home, repo, *_ = san
    r, _ = _chay(san, CV2_CO="0")
    assert r.returncode == 1 and "THIẾU OpenCV" in r.stdout, (r.stdout, r.stderr)
    assert not (repo / "deploy" / "run-service.sh").exists() and not any((home / "Library" / "LaunchAgents").iterdir())


def test_dich_vu_chay_theo_gio_vn_du_may_o_gio_khac(san):
    """Chạy CHÍNH run-service.sh mà script sinh ra, với TZ máy = Los Angeles ⇒ uvicorn nhận TZ=Asia/Saigon.
    Đột biến bỏ dòng `export TZ` ⇒ uvicorn nhận TZ của máy ⇒ ĐỎ."""
    home, repo, b, log = san
    r, _ = _chay(san)
    assert r.returncode == 0, (r.stdout, r.stderr)
    subprocess.run(["/bin/bash", str(repo / "deploy" / "run-service.sh")], cwd=repo, check=True, timeout=30,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(home), "LOG": str(log), "TZ": "America/Los_Angeles"})
    dong = [d for d in log.read_text().splitlines() if d.startswith("uvicorn")]
    assert dong and dong[-1].startswith("uvicorn TZ=Asia/Saigon ") and "--host 127.0.0.1" in dong[-1], dong


def test_gio_dich_vu_ghi_de_duoc_qua_env(san):
    home, repo, b, log = san
    (home / ".config" / "videodl" / "env").write_text("GDRIVE_SERVICE_ACCOUNT_FILE=/x\nVIDEODL_TZ=UTC\n", encoding="utf-8")
    r, _ = _chay(san)
    assert r.returncode == 0, (r.stdout, r.stderr)
    subprocess.run(["/bin/bash", str(repo / "deploy" / "run-service.sh")], cwd=repo, check=True, timeout=30,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(home), "LOG": str(log)})
    assert [d for d in log.read_text().splitlines() if d.startswith("uvicorn")][-1].startswith("uvicorn TZ=UTC ")


def test_luon_cai_chromium_du_cache_cua_du_an_khac_co_san(san):
    """Fixture có sẵn ~/Library/Caches/ms-playwright (như ca-n: cache của dự án khác, bản cũ). Đột biến quay về "có thư mục thì bỏ
    qua" ⇒ không gọi install ⇒ ĐỎ."""
    r, lenh = _chay(san)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert any(d.startswith("playwright install chromium") for d in lenh), lenh


def test_chromium_cai_vao_thu_muc_rieng_khi_env_khai(san):
    home, *_ = san
    (home / ".config" / "videodl" / "env").write_text(
        "GDRIVE_SERVICE_ACCOUNT_FILE=/x\nPLAYWRIGHT_BROWSERS_PATH=/rieng/ms-playwright\n", encoding="utf-8")
    r, lenh = _chay(san)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert [d for d in lenh if d.startswith("playwright install")] == ["playwright install chromium PBP=/rieng/ms-playwright"]


def test_healthz_cho_co_han_khi_dich_vu_len_cham(san):
    """Dịch vụ chưa lên ở 3 lần hỏi đầu ⇒ vẫn đạt. Đột biến về một lần đo ⇒ 000 ⇒ ĐỎ."""
    r, _ = _chay(san, CURL_LOI_DAU="3")
    assert r.returncode == 0 and "healthz: 200" in r.stdout, (r.stdout, r.stderr)


def test_healthz_qua_han_thi_dung_va_noi_ro_thoi_gian(san):
    r, _ = _chay(san, CURL_LOI_DAU="99", CHO_HEALTHZ_GIAY="2")
    assert r.returncode == 1 and "healthz trả 000 sau 2s" in r.stdout, (r.stdout, r.stderr)
