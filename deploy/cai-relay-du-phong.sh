#!/usr/bin/env bash
# Cài / gỡ relay agy DỰ PHÒNG trên máy ca-n (LaunchAgent trong domain gui/<uid> của mktmini).
#
# Chạy TRÊN MÁY DEV, từ một checkout SẠCH đã đẩy lên origin:
#     bash deploy/cai-relay-du-phong.sh            # thử khô: chỉ in sẽ làm gì, không đụng ca-n
#     bash deploy/cai-relay-du-phong.sh --yes      # cài / cập nhật thật
#     bash deploy/cai-relay-du-phong.sh --go       # gỡ: bootout đúng label + xoá plist, mã, env
#
# Vì sao LaunchAgent gui/<uid> mà không cron / ssh: agy cất thông tin đăng nhập trong login Keychain; phiên ssh KHÔNG mở được Keychain
# ("User interaction is not allowed"), LaunchAgent trong domain gui thì mở được — đo 16/10 trên ca-n (agy models: ssh ⇒ "Please sign in",
# LaunchAgent gui ⇒ rc=0). Rủi ro đã biết: ca-n khởi động lại mà chưa ai đăng nhập console ⇒ không có domain gui ⇒ dự phòng không chạy;
# canh Discord phía mini (`canh_relay`) báo khi video kẹt.
#
# Máy ca-n là của lane thuật toán (thư mục ~/thay-logo-loi-moi, ~/suite-pr80) + Ollama, daily-bo của lane CT: CHỈ đụng đúng label và
# thư mục của mình, đếm label hàng xóm trước/sau. Token relay chép từ cấu hình relay chính trên máy dev qua stdin — không in ra.
set -euo pipefail

HOST="mktmini@100.101.112.88"
EXPECT_HOST="mac-mini-ca-n"
LABEL="com.astronex.thay-logo-relay-du-phong"
MINI_URL="http://100.109.39.103:7871"           # cùng địa chỉ relay chính dùng (listener relay của mini, chỉ nhận IP Tailscale)
DICH_MA="thay-logo-relay-du-phong"             # ~/thay-logo-relay-du-phong/src trên ca-n
DICH_CFG=".config/thay-logo-relay-du-phong"    # env (600) + run-relay.sh
ENV_CHINH="$HOME/.config/thay-logo-relay/env"  # cấu hình relay CHÍNH trên máy dev — nguồn token
TEP_MA=(src/tiktok_music_downloader/__init__.py src/tiktok_music_downloader/thay_logo/__init__.py
        src/tiktok_music_downloader/thay_logo/hop_thu.py src/tiktok_music_downloader/thay_logo/relay_may_dev.py)

CHE_DO="kho"
case "${1:-}" in --yes) CHE_DO="that" ;; --go) CHE_DO="go" ;; "") ;; *) echo "tham số lạ: $1" >&2; exit 64 ;; esac
say() { printf '\n== %s\n' "$*"; }
ssh_ca() { ssh -o ConnectTimeout=10 -o BatchMode=yes "$HOST" "$@"; }

cd "$(git rev-parse --show-toplevel)"

say "0. Kiểm máy đích"
ten="$(ssh_ca hostname 2>&1 | tail -1)" || { echo "DỪNG: không ssh được $HOST (nhận: '$ten')." >&2; exit 5; }
norm="$(printf '%s' "$ten" | tr '[:upper:]' '[:lower:]' | sed 's/\.local$//')"
echo "   hostname: $ten (chuẩn hoá: $norm)"
[ "$norm" = "$EXPECT_HOST" ] || { echo "DỪNG: máy đích không phải $EXPECT_HOST." >&2; exit 1; }

nhan_hang_xom() { ssh_ca 'launchctl list' | awk 'NR>1{print $3}' | grep -i astronex | grep -v "^${LABEL}\$" | sort || true; }

if [ "$CHE_DO" = "go" ]; then
  say "GỠ relay dự phòng"
  truoc="$(nhan_hang_xom)"
  ssh_ca "U=\$(id -u); launchctl bootout gui/\$U/$LABEL 2>/dev/null || true; rm -f ~/Library/LaunchAgents/$LABEL.plist; rm -rf ~/$DICH_MA ~/$DICH_CFG"
  sau="$(nhan_hang_xom)"
  [ "$truoc" = "$sau" ] || { echo "CẢNH BÁO: label hàng xóm đổi sau khi gỡ!" >&2; diff <(echo "$truoc") <(echo "$sau") >&2 || true; exit 4; }
  ssh_ca "launchctl list | grep -c '$LABEL'" | grep -qx 0 && echo "   đã gỡ: label không còn, hàng xóm giữ nguyên"
  exit 0
fi

say "1. Kiểm cây mã nguồn"
[ -z "$(git status --porcelain)" ] || { echo "DỪNG: cây còn thay đổi chưa commit." >&2; exit 2; }
SHA="$(git rev-parse HEAD)"
[ -n "$(git branch -r --contains HEAD)" ] || { echo "DỪNG: $SHA chưa có trên origin." >&2; exit 2; }
grep -q -- '--du-phong' src/tiktok_music_downloader/thay_logo/relay_may_dev.py || { echo "DỪNG: mã chưa có chế độ --du-phong." >&2; exit 2; }
echo "   HEAD $SHA"

say "2. Kiểm token relay trên máy dev (không in giá trị)"
grep -q '^THAY_LOGO_RELAY_TOKEN=' "$ENV_CHINH" || { echo "DỪNG: $ENV_CHINH không có THAY_LOGO_RELAY_TOKEN." >&2; exit 2; }
echo "   có THAY_LOGO_RELAY_TOKEN (độ dài $(grep '^THAY_LOGO_RELAY_TOKEN=' "$ENV_CHINH" | cut -d= -f2- | tr -d '\n' | wc -c | tr -d ' ') ký tự)"

say "3. Kiểm ca-n: agy + python3"
ssh_ca 'test -x ~/.local/bin/agy && echo "   agy: có" || { echo "DỪNG: ca-n chưa có ~/.local/bin/agy" >&2; exit 3; }
        for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x "$p" ] && { echo "   python3: $p ($("$p" --version 2>&1))"; break; }; done'
truoc="$(nhan_hang_xom)"
echo "   label hàng xóm TRƯỚC: $(echo "$truoc" | tr '\n' ' ')"

if [ "$CHE_DO" = "kho" ]; then
  say "THỬ KHÔ — sẽ làm khi chạy --yes:"
  echo "   - rsync ${#TEP_MA[@]} tệp mã (chỉ thư viện chuẩn) → $HOST:~/$DICH_MA/ ; ghi ~/$DICH_MA/.sha = $SHA"
  echo "   - ghi ~/$DICH_CFG/env (chmod 600: THAY_LOGO_RELAY_TOKEN [+ THAY_LOGO_AGY_MODEL nếu relay chính có]) + run-relay.sh"
  echo "   - ghi ~/Library/LaunchAgents/$LABEL.plist (RunAtLoad, KeepAlive) rồi bootout(nếu có)+bootstrap gui/<uid>"
  echo "   - nghiệm thu: label đang chạy, log có 'DỰ PHÒNG', hàng xóm không đổi"
  exit 0
fi

say "4. Đẩy mã"
rsync -a --relative "${TEP_MA[@]}" "$HOST:$DICH_MA/"
ssh_ca "printf '%s\n' '$SHA' > ~/$DICH_MA/.sha"

say "5. Cấu hình (token qua stdin, không in)"
grep -E '^(THAY_LOGO_RELAY_TOKEN|THAY_LOGO_AGY_MODEL)=' "$ENV_CHINH" |
  ssh_ca "mkdir -p ~/$DICH_CFG && umask 077 && cat > ~/$DICH_CFG/env && chmod 600 ~/$DICH_CFG/env"
ssh_ca "cat > ~/$DICH_CFG/run-relay.sh" <<EOF
#!/bin/bash
# Relay agy DỰ PHÒNG trên ca-n (LaunchAgent $LABEL). Sinh bởi deploy/cai-relay-du-phong.sh — sửa ở đó, đừng sửa tay.
set -euo pipefail
cd "\$HOME/$DICH_CFG"          # cwd không phải repo: agy chỉ được --add-dir thư mục ảnh tạm
set -a; . "\$HOME/$DICH_CFG/env"; set +a
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="\$HOME/$DICH_MA/src"
PY=\$(for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x "\$p" ] && { echo "\$p"; break; }; done)
exec "\$PY" -m tiktok_music_downloader.thay_logo.relay_may_dev --mini $MINI_URL --du-phong
EOF
ssh_ca "chmod 700 ~/$DICH_CFG/run-relay.sh"

say "6. LaunchAgent"
ssh_ca "cat > ~/Library/LaunchAgents/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-c</string><string>exec "\$HOME/$DICH_CFG/run-relay.sh"</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>/Users/mktmini/Library/Logs/$LABEL.log</string>
  <key>StandardErrorPath</key><string>/Users/mktmini/Library/Logs/$LABEL.log</string>
</dict></plist>
EOF
ssh_ca "U=\$(id -u); launchctl bootout gui/\$U/$LABEL 2>/dev/null || true; launchctl bootstrap gui/\$U ~/Library/LaunchAgents/$LABEL.plist"

say "7. Nghiệm thu"
sleep 8
ssh_ca "launchctl list | grep '$LABEL'" || { echo "TRƯỢT: label không có trong launchctl list." >&2; exit 4; }
ssh_ca "tail -5 ~/Library/Logs/$LABEL.log" | sed 's/^/   log: /'
ssh_ca "grep -q 'DỰ PHÒNG' ~/Library/Logs/$LABEL.log" || { echo "TRƯỢT: log chưa có dòng 'chạy ở chế độ DỰ PHÒNG'." >&2; exit 4; }
sau="$(nhan_hang_xom)"
[ "$truoc" = "$sau" ] || { echo "TRƯỢT: label hàng xóm đổi!" >&2; diff <(echo "$truoc") <(echo "$sau") >&2 || true; exit 4; }
echo "   OK: relay dự phòng chạy ($SHA), hàng xóm giữ nguyên. Gỡ: bash deploy/cai-relay-du-phong.sh --go"
