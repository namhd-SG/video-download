"""`deploy/cai-relay-du-phong.sh` — gỡ phải báo trượt, nghiệm thu không xanh cho relay chết, so hàng xóm không nuốt lỗi.

Chạy script THẬT với `ssh` giả: ssh giả chạy lệnh "từ xa" ngay tại chỗ với HOME = thư mục tạm, cùng `launchctl` và `hostname`
giả trên PATH. Không lệnh nào ra mạng hay đụng launchd thật.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "cai-relay-du-phong.sh"
LABEL = "com.astronex.thay-logo-relay-du-phong"

SSH_GIA = '#!/bin/bash\nprintf "%s\\n" "$*" >> "${SSH_LOG:-/dev/null}"\nexec /bin/bash -c "${@: -1}"\n'
# rsync giả: `rsync -a --relative -e <ssh> tệp… host:đích/` ⇒ chép giữ đường dẫn tương đối vào $HOME/<đích>.
RSYNC_GIA = r'''#!/bin/bash
printf '%s\n' "$*" >> "${SSH_LOG:-/dev/null}"
args=(); while [ $# -gt 0 ]; do case "$1" in -e) shift 2 ;; -*) shift ;; *) args+=("$1"); shift ;; esac; done
dich="${args[${#args[@]}-1]#*:}"; unset 'args[${#args[@]}-1]'
for f in "${args[@]}"; do mkdir -p "$HOME/$dich/$(dirname "$f")"; cp "$f" "$HOME/$dich/$f"; done
'''
HOSTNAME_GIA = '#!/bin/bash\necho Mac-mini-cua-N.local\n'
# Label "đang nạp" ⟺ có tệp $HOME/.nap. GIA_BOOTOUT_HONG=1 ⇒ bootout không gỡ được. GIA_GUI_RC≠0 ⇒ không đọc được domain gui.
LAUNCHCTL_GIA = r'''#!/bin/bash
case "$1 $2" in
  "print gui/"*/*) [ -e "$HOME/.nap" ] || exit 113; printf '%s' "${GIA_LABEL_OUT:-}" ;;
  "print gui/"*) [ "${GIA_GUI_RC:-0}" = 0 ] || exit "$GIA_GUI_RC"; printf '%s' "${GIA_GUI_OUT:-}" ;;
  "bootout "*) [ "${GIA_BOOTOUT_HONG:-0}" = 1 ] || rm -f "$HOME/.nap" ;;
  "bootstrap "*) touch "$HOME/.nap"; printf '%s' "${GIA_LOG_KHI_CHAY:-}" >> "$HOME/Library/Logs/com.astronex.thay-logo-relay-du-phong.log" ;;
esac
'''
GUI_OUT = ("gui/501 = {\n\tservices = {\n"
           "\t\t   51633      - \tcom.astronex.ollama-ca-n\n"
           "\t\t       0      9 \tcom.astronex.creative-tracker.daily-bo-ca-n\n"
           f"\t\t     777      - \t{LABEL}\n\t}}\n}}\n")


def _label_out(state: str, pid: str | None) -> str:
    """Hình dạng `launchctl print gui/<uid>/<label>`: dòng cấp ngoài một tab, khối lồng cũng có 'state = active'."""
    dong = [f"gui/501/{LABEL} = {{", "\tactive count = 1", f"\tstate = {state}"]
    if pid:
        dong.append(f"\tpid = {pid}")
    dong += ["\tendpoints = {", "\t\tstate = active", "\t}", "}"]
    return "\n".join(dong) + "\n"


@pytest.fixture
def san(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    for ten, noi_dung in (("ssh", SSH_GIA), ("hostname", HOSTNAME_GIA), ("launchctl", LAUNCHCTL_GIA), ("rsync", RSYNC_GIA),
                          ("sleep", "#!/bin/bash\nexit 0\n")):
        (b / ten).write_text(noi_dung, encoding="utf-8")
        (b / ten).chmod(0o755)
    nha = tmp_path / "home"
    (nha / "Library" / "LaunchAgents").mkdir(parents=True)
    (nha / "Library" / "Logs").mkdir(parents=True)
    env = {"PATH": f"{b}:/usr/bin:/bin", "HOME": str(nha), "GIA_GUI_OUT": GUI_OUT}
    return nha, env


def _go(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(SCRIPT), "--go"], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=30)


def _ham(env: dict, lenh: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", "-c", f'f="$1"; shift; source "$f"; {lenh}', "_", str(SCRIPT)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=30)


def test_go_thanh_cong_thi_bao_da_go(san):
    nha, env = san
    (nha / ".nap").touch()
    (nha / "Library" / "LaunchAgents" / f"{LABEL}.plist").touch()
    r = _go(env)
    assert r.returncode == 0, r.stderr
    assert "đã gỡ" in r.stdout
    assert not (nha / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()


def test_go_con_thu_muc_ma_thi_bao_truot(san):
    """Label + plist đã đi mà thư mục mã còn (rm trượt) ⇒ không được báo "đã gỡ". ĐỘT BIẾN bỏ `test -e ~/$DICH_MA` ⇒ ĐỎ."""
    nha, env = san
    (nha / ".nap").touch()
    lnk = nha / "thay-logo-relay-du-phong"
    lnk.mkdir()
    (lnk / "khoa").touch()
    lnk.chmod(0o500)  # rm -rf không xoá được tệp bên trong ⇒ thư mục còn
    try:
        r = _go(env)
    finally:
        lnk.chmod(0o700)
    assert r.returncode == 4 and "vẫn còn" in r.stderr, (r.returncode, r.stdout, r.stderr)


def test_go_truot_thi_bao_va_thoat_khac_0(san):
    """ĐỘT BIẾN bản cũ (`grep -c … | grep -qx 0 && echo`, rồi `exit 0`): gỡ trượt vẫn rc 0, im lặng ⇒ ĐỎ."""
    nha, env = san
    (nha / ".nap").touch()
    r = _go({**env, "GIA_BOOTOUT_HONG": "1"})
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
    assert "vẫn còn" in r.stderr and "đã gỡ" not in r.stdout


def test_khong_doc_duoc_domain_gui_thi_dung_khong_so_rong_voi_rong(san):
    """ĐỘT BIẾN bản cũ (`… | sort || true`): ssh/launchctl trượt ⇒ trước = sau = rỗng ⇒ so hàng xóm xanh vô nghĩa ⇒ ĐỎ."""
    _, env = san
    r = _go({**env, "GIA_GUI_RC": "113"})
    assert r.returncode == 5, (r.returncode, r.stdout, r.stderr)
    assert "không đọc được launchctl" in r.stderr


def test_hang_xom_lay_tu_domain_gui_bo_label_cua_minh(san):
    _, env = san
    r = _ham(env, "nhan_hang_xom")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["com.astronex.creative-tracker.daily-bo-ca-n", "com.astronex.ollama-ca-n"]


def _ghi_log(nha: Path, cu: str, moi: str) -> int:
    f = nha / "Library" / "Logs" / f"{LABEL}.log"
    f.write_text(cu, encoding="utf-8")
    moc = f.stat().st_size
    with f.open("a", encoding="utf-8") as h:
        h.write(moi)
    return moc


def test_nghiem_thu_xanh_khi_chay_va_log_moi_co_du_phong(san):
    nha, env = san
    (nha / ".nap").touch()
    moc = _ghi_log(nha, "dòng cũ\n", "INFO chạy ở chế độ DỰ PHÒNG\n")
    r = _ham({**env, "GIA_LABEL_OUT": _label_out("running", "4242")}, f"kiem_dang_chay {moc}")
    assert r.returncode == 0, r.stderr
    assert "pid 4242" in r.stdout


def test_nghiem_thu_truot_khi_relay_khong_chay_du_khoi_long_ghi_active(san):
    """ĐỘT BIẾN bản cũ (`launchctl list | grep LABEL`): label còn trong danh sách dù tiến trình đã thoát ⇒ ĐỎ.
    Output thật có khối lồng mang 'state = active' SAU dòng cấp ngoài (đo trên ca-n) — giữ hình dạng đó ở đây."""
    nha, env = san
    (nha / ".nap").touch()
    moc = _ghi_log(nha, "", "INFO chạy ở chế độ DỰ PHÒNG\n")
    r = _ham({**env, "GIA_LABEL_OUT": _label_out("not running", None)}, f"kiem_dang_chay {moc}")
    assert r.returncode == 4 and "không chạy" in r.stderr, (r.returncode, r.stderr)


def test_nghiem_thu_chi_doc_log_sau_moc(san):
    """ĐỘT BIẾN bản cũ (grep cả tệp log): dòng 'DỰ PHÒNG' của lần cài TRƯỚC làm xanh relay đang báo chưa cấu hình ⇒ ĐỎ."""
    nha, env = san
    (nha / ".nap").touch()
    moc = _ghi_log(nha, "INFO chạy ở chế độ DỰ PHÒNG\n", "relay chưa cấu hình: THAY_LOGO_RELAY_TOKEN\n")
    r = _ham({**env, "GIA_LABEL_OUT": _label_out("running", "4242")}, f"kiem_dang_chay {moc}")
    assert r.returncode == 4 and "chưa cấu hình" in r.stderr, (r.returncode, r.stderr)
    moc = _ghi_log(nha, "INFO chạy ở chế độ DỰ PHÒNG\n", "INFO đang chờ việc\n")
    r = _ham({**env, "GIA_LABEL_OUT": _label_out("running", "4242")}, f"kiem_dang_chay {moc}")
    assert r.returncode == 4 and "chưa có dòng" in r.stderr, (r.returncode, r.stderr)


def test_nghiem_thu_truot_khi_relay_song_ma_mini_tu_choi(san):
    """Relay bắt lỗi gọi mini (401/403/503) rồi chạy tiếp ⇒ launchd vẫn running ⇒ phải TRƯỢT nhờ dòng 'vòng lỗi'.
    ĐỘT BIẾN bỏ khối kiểm 'vòng lỗi' ⇒ ĐỎ."""
    nha, env = san
    (nha / ".nap").touch()
    moc = _ghi_log(nha, "", "INFO chạy ở chế độ DỰ PHÒNG\nWARNING vòng lỗi: mini trả HTTP 401\n")
    r = _ham({**env, "GIA_LABEL_OUT": _label_out("running", "4242")}, f"kiem_dang_chay {moc}")
    assert r.returncode == 4 and "HTTP 401" in r.stderr, (r.returncode, r.stderr)


def _repo_sach(tmp_path: Path) -> Path:
    """Repo git TỐI THIỂU chỉ chứa các tệp script cần (bản ĐANG SỬA), cây sạch và HEAD 'có trên origin' (bước 1 đòi vậy).
    Không clone cả repo: tệp LFS lớn (assets/ffmpeg-static) + HOME giả không có filter lfs ⇒ `git status` thỉnh thoảng báo bẩn (racy)."""
    rp = tmp_path / "repo"
    tep = ["deploy/cai-relay-du-phong.sh", "deploy/may-dich.sh", "src/tiktok_music_downloader/__init__.py",
           "src/tiktok_music_downloader/thay_logo/__init__.py", "src/tiktok_music_downloader/thay_logo/hop_thu.py",
           "src/tiktok_music_downloader/thay_logo/relay_may_dev.py"]
    for t in tep:
        (rp / t).parent.mkdir(parents=True, exist_ok=True)
        (rp / t).write_bytes((REPO / t).read_bytes())
    g = ["git", "-C", str(rp), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(rp)], check=True)
    subprocess.run(g + ["add", *tep], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "test"], check=True)
    subprocess.run(g + ["update-ref", "refs/remotes/origin/thu", "HEAD"], check=True)
    return rp


def _cai(san, tmp_path, log_khi_chay: str) -> tuple[subprocess.CompletedProcess, Path, str]:
    nha, env = san
    token = "t" * 40
    cfg = nha / ".config" / "thay-logo-relay"
    cfg.mkdir(parents=True)
    (cfg / "env").write_text(f"THAY_LOGO_RELAY_TOKEN={token}\nKHAC=1\n", encoding="utf-8")
    agy = nha / ".local" / "bin" / "agy"
    agy.parent.mkdir(parents=True)
    agy.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    agy.chmod(0o755)
    rp = _repo_sach(tmp_path)
    ssh_log = tmp_path / "ssh.log"
    env2 = {**env, "SSH_LOG": str(ssh_log), "GIA_LOG_KHI_CHAY": log_khi_chay, "GIA_LABEL_OUT": _label_out("running", "4242")}
    r = subprocess.run(["/bin/bash", str(rp / "deploy" / "cai-relay-du-phong.sh"), "--yes"], cwd=rp, env=env2,
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 2:  # bước 1 "cây chưa sạch": in kèm tệp bẩn để không phải đoán
        r.stderr += subprocess.run(["git", "-C", str(rp), "status", "--porcelain"], capture_output=True, text=True).stdout
    return r, nha, ssh_log.read_text(encoding="utf-8") if ssh_log.exists() else ""


def test_cai_that_tron_duong_yes(san, tmp_path):
    """Đường --yes chạy hết bước 0→7 với ssh/rsync/launchctl giả: env 600 chỉ có biến relay, run-relay.sh hợp lệ và gọi đúng mini
    từ bảng máy đích, plist hợp lệ, token KHÔNG xuất hiện trong đối số ssh/rsync."""
    r, nha, argv = _cai(san, tmp_path, "INFO chạy ở chế độ DỰ PHÒNG\n")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "OK: relay dự phòng chạy" in r.stdout
    envf = nha / ".config" / "thay-logo-relay-du-phong" / "env"
    assert oct(envf.stat().st_mode & 0o777) == "0o600"
    assert envf.read_text(encoding="utf-8").splitlines() == ["THAY_LOGO_RELAY_TOKEN=" + "t" * 40]
    run = nha / ".config" / "thay-logo-relay-du-phong" / "run-relay.sh"
    assert subprocess.run(["/bin/bash", "-n", str(run)]).returncode == 0
    ip = _ham(san[1], "mini_ip").stdout
    assert f"--mini http://{ip}:7871 --du-phong" in run.read_text(encoding="utf-8")
    plist = nha / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert subprocess.run(["plutil", "-lint", str(plist)], capture_output=True).returncode == 0
    assert (nha / "thay-logo-relay-du-phong" / "src" / "tiktok_music_downloader" / "thay_logo" / "relay_may_dev.py").exists()
    assert "t" * 40 not in argv and argv


def test_cai_that_truot_khi_relay_bi_mini_tu_choi(san, tmp_path):
    r, _, _ = _cai(san, tmp_path, "INFO chạy ở chế độ DỰ PHÒNG\nWARNING vòng lỗi: mini trả HTTP 403\n")
    assert r.returncode == 4 and "HTTP 403" in r.stderr, (r.returncode, r.stdout, r.stderr)


def test_moc_log_0_khi_chua_co_tep_va_bang_kich_thuoc_khi_co(san):
    nha, env = san
    assert _ham(env, "moc_log").stdout.strip() == "0"
    moc = _ghi_log(nha, "abc\n", "")
    assert _ham(env, "moc_log").stdout.strip() == str(moc)


def test_dia_chi_mini_lay_tu_bang_may_dich(san):
    _, env = san
    bang = subprocess.run(["/bin/bash", "-c", 'source deploy/may-dich.sh && printf "%s" "${HOST#*@}"'], cwd=REPO,
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}).stdout
    assert bang and _ham(env, "mini_ip").stdout == bang
    assert _ham({**env, "VIDEODL_MINI_HOST": "svc@100.64.0.9"}, "mini_ip").stdout == "100.64.0.9"
