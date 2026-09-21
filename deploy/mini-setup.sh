#!/bin/bash
# Dựng lại dịch vụ video-download trên mac mini công ty từ con số không.
#
# Chạy TRÊN MINI, bằng tài khoản sở hữu dịch vụ:
#     bash ~/Projects/video-download/deploy/mini-setup.sh
#
# Chạy lại được nhiều lần — mỗi bước tự kiểm trước khi làm.
#
# Vì sao script này tồn tại: máy đích không có sudo, không có ffmpeg hệ thống,
# không fetch được GitHub, và đang chạy dịch vụ production của người khác
# (Promax + ollama + glances). Dựng bằng tay là quên bước, và quên bước ở đây
# nghĩa là hỏng việc người khác.
set -euo pipefail

REPO="$HOME/Projects/video-download"
CFG="$HOME/.config/videodl"
DATA="$HOME/.local/share/videodl"
LABEL="com.astronex.videodl"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT=7870

say() { printf '  %s\n' "$*"; }

# --- 0. Đếm label hàng xóm TRƯỚC khi đụng launchctl -------------------------
# Tiền lệ 27/08: một tác nhân `bootout` nhầm label làm tắt lưới an toàn Promax
# 32 phút. Từ đó: đếm trước, đếm sau, và chỉ thao tác trên đúng label của mình.
truoc=$(launchctl list | grep -c astronex || true)
say "label astronex trước khi chạy: $truoc"

# --- 1. Python -------------------------------------------------------------
# Bản hệ thống là 3.9.6, tool cần >= 3.10. Homebrew có 3.14.
PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || { echo "THIẾU $PY — cài python qua homebrew trước"; exit 1; }
say "python: $($PY -V)"

# --- 2. Mã nguồn -----------------------------------------------------------
# KHÔNG dùng `git clone`: máy này không có credential GitHub (đo được:
# `could not read Username` cả trong SSH lẫn launchd). Và `git bundle` cũng
# không cứu được vì nó chỉ mang pointer LFS, không mang binary ffmpeg.
# Đường đúng: rsync mã nguồn + scp riêng ffmpeg từ máy dev.
[ -f "$REPO/pyproject.toml" ] || {
  echo "THIẾU mã nguồn ở $REPO"
  echo "Từ máy dev chạy:"
  echo "  rsync -a --exclude='.venv' --exclude='.git' --exclude='web/data' \\"
  echo "        ./ nobi_auto@100.109.39.103:~/Projects/video-download/"
  exit 1
}

# --- 3. ffmpeg -------------------------------------------------------------
# Máy KHÔNG có ffmpeg hệ thống. Repo mang theo bản bundle qua Git LFS, nhưng
# rsync từ máy dev có thể bỏ sót nó (file lớn) nên kiểm bằng cách CHẠY THẬT,
# không chỉ kiểm file tồn tại — pointer LFS trông y hệt file thật.
FF="$REPO/assets/ffmpeg-static/ffmpeg"
[ -x "$FF" ] && "$FF" -version >/dev/null 2>&1 || {
  echo "ffmpeg không chạy được: $FF"
  echo "Từ máy dev: scp assets/ffmpeg-static/ffmpeg nobi_auto@<mini>:$FF"
  echo "Rồi đối chiếu sha256 với: git lfs ls-files -l"
  exit 1
}
say "ffmpeg: $("$FF" -version 2>&1 | head -1 | cut -c1-40)"
# Lưu ý: repo KHÔNG có ffprobe (.gitattributes chỉ track ffmpeg + ffmpeg.exe).
# Việc xác minh luồng video dùng `ffmpeg -i` rồi đếm dòng khớp 'Stream.*Video:'.

# --- 4. venv + phụ thuộc ---------------------------------------------------
[ -d "$REPO/.venv" ] || { say "tạo venv"; "$PY" -m venv "$REPO/.venv"; }
"$REPO/.venv/bin/pip" install -q -e "$REPO[web]"
"$REPO/.venv/bin/pip" install -q "google-api-python-client>=2.100" "google-auth>=2.30" pytest
say "phụ thuộc: đã cài"

# Chromium cho Playwright — ~1,1 GB trên máy này (README ghi 150 MB là sai).
if [ ! -d "$HOME/Library/Caches/ms-playwright" ]; then
  say "tải Chromium (~1,1 GB, một lần)"
  "$REPO/.venv/bin/playwright" install chromium
fi

# --- 5. Thư mục dữ liệu + quyền -------------------------------------------
# Cookie và khoá Drive là secret. Quyền chặt ngay từ lúc tạo, đừng sửa sau.
mkdir -p "$CFG" "$DATA/downloads" "$DATA/cookies"
chmod 700 "$CFG" "$DATA" "$DATA/cookies"
[ -f "$CFG/drive-key.json" ] && chmod 600 "$CFG/drive-key.json"
[ -f "$CFG/env" ] && chmod 600 "$CFG/env"

# --- 6. Cấu hình -----------------------------------------------------------
# Tên biến phải khớp hằng số ENV_* trong gdrive_upload.py. Đặt sai tên thì tool
# rơi về "chưa cấu hình" và KHÔNG upload gì — mà mọi thứ vẫn xanh.
[ -f "$CFG/env" ] || {
  echo "THIẾU $CFG/env — tạo với hai biến (khớp ENV_* trong gdrive_upload.py):"
  echo "  GDRIVE_SERVICE_ACCOUNT_FILE=$CFG/drive-key.json"
  echo "  GDRIVE_SHARED_DRIVE_FOLDER_ID=<id thư mục trên Shared Drive>"
  exit 1
}

# Nghiệm thu cấu hình bằng hành vi, không bằng sự tồn tại của file.
set -a; . "$CFG/env"; set +a
"$REPO/.venv/bin/python" - <<'PY'
from tiktok_music_downloader.gdrive_upload import DriveUploader
assert DriveUploader().is_configured(), "cấu hình Drive KHÔNG đọc được — kiểm tên biến"
print("  cấu hình Drive: đọc được")
PY

# --- 7. Script khởi động ---------------------------------------------------
cat > "$REPO/deploy/run-service.sh" <<SH
#!/bin/bash
# LaunchAgent không tự nạp file env nên đọc ở đây.
# Bind 127.0.0.1: ra ngoài CHỈ qua cloudflared, không mở cổng trần.
set -euo pipefail
cd "\$HOME/Projects/video-download"
set -a; . "\$HOME/.config/videodl/env"; set +a
exec ./.venv/bin/uvicorn web.app:app --host 127.0.0.1 --port $PORT
SH
chmod +x "$REPO/deploy/run-service.sh"

# --- 8. LaunchAgent --------------------------------------------------------
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$REPO/deploy/run-service.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/videodl.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/videodl.log</string>
</dict></plist>
PL
plutil -lint "$PLIST" >/dev/null

# CHỈ thao tác trên label của mình. TUYỆT ĐỐI không `bootout` label nào khác.
#
# `bootout` là BẤT ĐỒNG BỘ: nó trả về trước khi label thật sự được gỡ. Chạy
# `bootstrap` ngay dòng sau thì gặp "Bootstrap failed: 5: Input/output error",
# và kết cục là bootout thành công + bootstrap thất bại = DỊCH VỤ CHẾT.
# Đã xảy ra thật 14/09 lúc chạy thử script này (gián đoạn ~90 giây).
# Nên: chờ label BIẾN MẤT THẬT, không chờ mù bằng `sleep`.
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  for _ in $(seq 1 30); do
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
    sleep 1
  done
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
    && { echo "bootout không gỡ được $LABEL sau 30s — DỪNG, không bootstrap chồng"; exit 1; }
fi

# KHÔNG nuốt lỗi bootstrap: hỏng ở đây mà đi tiếp thì dịch vụ không tồn tại
# trong khi script vẫn chạy xuống phần nghiệm thu.
launchctl bootstrap "gui/$(id -u)" "$PLIST" || {
  echo "bootstrap THẤT BẠI — dịch vụ hiện KHÔNG chạy. Xem ~/Library/Logs/videodl.log"
  exit 1
}
sleep 4

# --- 9. Nghiệm thu ---------------------------------------------------------
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/healthz" || true)
[ "$code" = "200" ] || { echo "healthz trả $code, mong 200 — xem ~/Library/Logs/videodl.log"; exit 1; }
say "healthz: 200"

# Cổng phải chỉ nghe nội bộ. Nghe 0.0.0.0 là mở trần ra mạng nội bộ trước khi
# có xác thực — đúng lỗ đã bị bắt ở vòng thẩm định.
lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | grep -q '127.0.0.1' \
  || { echo "cổng $PORT KHÔNG bind 127.0.0.1 — dừng"; exit 1; }
say "bind: 127.0.0.1 (đúng)"

sau=$(launchctl list | grep -c astronex || true)
say "label astronex sau khi chạy: $sau (trước: $truoc)"
[ "$sau" -ge "$truoc" ] || { echo "MẤT label hàng xóm — kiểm ngay"; exit 1; }

# Hàng xóm phải còn sống. Dựng dịch vụ của mình mà làm chết Promax của người
# khác thì không phải thành công.
px=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://promax.nobidigital.asia || true)
say "promax hàng xóm: HTTP $px"

echo
echo "XONG. Dịch vụ chạy ở http://127.0.0.1:$PORT (chỉ nội bộ)."
echo "Ra internet cần thêm hostname vào ~/.cloudflared/config.yml — và phải bật"
echo "Cloudflare Access TRƯỚC khi hostname chạm cổng này."
