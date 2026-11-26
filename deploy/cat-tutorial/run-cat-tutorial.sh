#!/bin/bash
# Khởi động tool Cắt tutorial (chế độ web) dưới launchd `com.astronex.cat-tutorial` (plist cùng thư mục, env nằm trong plist).
# deploy/cat-tutorial/cai-venv.sh chép file này tới ~/cat-tutorial/run-cat-tutorial.sh.
set -euo pipefail

GOC="$HOME/cat-tutorial"           # app/ = scripts/ của repo chị Linh @ sha ghim (deploy/cap-nhat-cat-tutorial.sh), venv/
DU_LIEU="$HOME/.cat-tutorial"      # HOME dữ liệu mặc định của ui_server.py: cache/, web/<khu>/, web_session.json

# thư mục chứa video người dùng tải lên — máy có nhiều tài khoản, umask 022 sẽ để nó 755.
mkdir -p "$DU_LIEU"
chmod 700 "$DU_LIEU"

# ảnh thu nhỏ / bản xem trước / zip tạm cũ hơn 24 giờ. `-mmin +1440` (không phải `-mtime +1`): find làm tròn ngày
# xuống nên `-mtime +1` chỉ bắt file ≥ 48 giờ. Chỉ xoá FILE, giữ thư mục cache. Dọn hỏng không được chặn khởi động.
if [ -d "$DU_LIEU/cache" ]; then
  find "$DU_LIEU/cache" -type f -mmin +1440 -delete || true
fi

cd "$GOC/app"
exec "$GOC/venv/bin/python" "$GOC/app/ui_server.py"
