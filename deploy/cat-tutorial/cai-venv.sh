#!/usr/bin/env bash
# Cài lần đầu / cập nhật môi trường tool Cắt tutorial — chạy TRÊN MÁY ĐÍCH (ca-n), bằng tài khoản dịch vụ, KHÔNG sudo.
#
#   Từ máy dev:  rsync -a deploy/cat-tutorial/ <host>:cat-tutorial/cai-dat/
#   Trên đích:   CAT_TUTORIAL_PY=<python ≥3.10> bash ~/cat-tutorial/cai-dat/cai-venv.sh
#   Rồi:         bash deploy/cap-nhat-cat-tutorial.sh <sha> --yes  (từ máy dev — đưa mã vào ~/cat-tutorial/app)
#   Nạp lần đầu: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.astronex.cat-tutorial.plist
#
# Script này KHÔNG nạp launchd và không đụng label nào khác. Python: ca-n không có /opt/homebrew/bin/python3
# (deploy/may-dich.sh, đo 19/10) ⇒ khai CAT_TUTORIAL_PY (micromamba). Gói đúng theo kế hoạch: torch bản CPU, open_clip_torch,
# rapidocr-onnxruntime, pillow, numpy (KHÔNG anthropic — không bật backend Claude). Model CLIP ViT-B-32 (~600MB) tải ở lần
# nhận diện đầu; tên bản pretrained nằm trong cat_tutorial.py (chưa đọc) nên script không tải trước.
set -euo pipefail

LABEL="com.astronex.cat-tutorial"
GOC="$HOME/cat-tutorial"
DAY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # thư mục chứa plist + wrapper
PY="${CAT_TUTORIAL_PY:-python3}"

"$PY" -c 'import sys; assert sys.version_info >= (3, 10), sys.version' \
  || { echo "DỪNG: cần Python ≥ 3.10 (CAT_TUTORIAL_PY=$PY)" >&2; exit 2; }
[ -f "$DAY/$LABEL.plist" ] && [ -f "$DAY/run-cat-tutorial.sh" ] \
  || { echo "DỪNG: thiếu $LABEL.plist / run-cat-tutorial.sh cạnh script ($DAY)" >&2; exit 2; }

mkdir -p "$GOC/app" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$HOME/.cat-tutorial"
chmod 700 "$HOME/.cat-tutorial"

echo "== 1. venv $GOC/venv"
[ -x "$GOC/venv/bin/python" ] || "$PY" -m venv "$GOC/venv"
V="$GOC/venv/bin/python"
"$V" -m pip install --upgrade pip
# macOS arm64: bánh xe torch trên PyPI là bản CPU (+MPS, không CUDA). Máy khác: lấy bản CPU từ index riêng của PyTorch.
if [ "$(uname -s)" = "Darwin" ]; then
  "$V" -m pip install torch
else
  "$V" -m pip install --index-url https://download.pytorch.org/whl/cpu torch
fi
"$V" -m pip install open_clip_torch rapidocr-onnxruntime pillow numpy
"$V" -c 'import torch, open_clip, rapidocr_onnxruntime, PIL, numpy; print("venv OK — torch", torch.__version__)'

echo "== 2. ffmpeg (cùng PATH với plist)"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" command -v ffmpeg \
  || { echo "DỪNG: không thấy ffmpeg trong PATH của plist — cài ffmpeg hoặc sửa PATH trong $LABEL.plist" >&2; exit 3; }

echo "== 3. wrapper + plist"
install -m 700 "$DAY/run-cat-tutorial.sh" "$GOC/run-cat-tutorial.sh"
sed "s#__HOME__#$HOME#g" "$DAY/$LABEL.plist" > "$HOME/Library/LaunchAgents/$LABEL.plist"
plutil -lint "$HOME/Library/LaunchAgents/$LABEL.plist"

echo
echo "XONG phần cài. Chưa nạp launchd. Lần đầu: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$LABEL.plist"
echo "Đã nạp rồi mà đổi plist: launchctl bootout gui/$(id -u)/$LABEL && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$LABEL.plist"
