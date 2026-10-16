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

SSH_GIA = '#!/bin/bash\nexec /bin/bash -c "${@: -1}"\n'
HOSTNAME_GIA = '#!/bin/bash\necho Mac-mini-cua-N.local\n'
# Label "đang nạp" ⟺ có tệp $HOME/.nap. GIA_BOOTOUT_HONG=1 ⇒ bootout không gỡ được. GIA_GUI_RC≠0 ⇒ không đọc được domain gui.
LAUNCHCTL_GIA = r'''#!/bin/bash
case "$1 $2" in
  "print gui/"*/*) [ -e "$HOME/.nap" ] || exit 113; printf '%s' "${GIA_LABEL_OUT:-}" ;;
  "print gui/"*) [ "${GIA_GUI_RC:-0}" = 0 ] || exit "$GIA_GUI_RC"; printf '%s' "${GIA_GUI_OUT:-}" ;;
  "bootout "*) [ "${GIA_BOOTOUT_HONG:-0}" = 1 ] || rm -f "$HOME/.nap" ;;
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
    for ten, noi_dung in (("ssh", SSH_GIA), ("hostname", HOSTNAME_GIA), ("launchctl", LAUNCHCTL_GIA)):
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


def test_moc_log_0_khi_chua_co_tep_va_bang_kich_thuoc_khi_co(san):
    nha, env = san
    assert _ham(env, "moc_log").stdout.strip() == "0"
    moc = _ghi_log(nha, "abc\n", "")
    assert _ham(env, "moc_log").stdout.strip() == str(moc)


def test_dia_chi_mini_lay_tu_bang_may_dich(san):
    _, env = san
    assert _ham(env, "mini_ip").stdout == "100.109.39.103"
    assert _ham({**env, "VIDEODL_MINI_HOST": "svc@100.64.0.9"}, "mini_ip").stdout == "100.64.0.9"
