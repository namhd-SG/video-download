#!/usr/bin/env bash
# Lui bản deploy gần nhất trên mac mini công ty.
#
# Chạy TRÊN MÁY DEV:
#     bash deploy/rollback-on-mini.sh ../video-download-truoc-260916-1050
#
# Tham số là đúng cái tên mà deploy-to-mini.sh in ra ở dòng cuối.
#
# ⚠ GIỚI HẠN, khai trước để không ai tưởng đây là lui sạch:
# `--backup-dir` của rsync chỉ giữ những file bị THAY. (Về lý thuyết nó giữ cả
# file bị XOÁ — nhưng openrsync bỏ qua `--delete` khi có `--backup-dir`, đo
# 23/09 trên mini, nên deploy KHÔNG xoá gì và bản lui không bao giờ chứa file bị
# xoá. Xem comment bước 3 của deploy-to-mini.sh.) File mà lần
# deploy đó THÊM MỚI thì không nằm trong bản lui, nên sau khi lui chúng vẫn còn
# trên đĩa. Thường vô hại (không ai trỏ tới chúng nữa), nhưng nếu cần sạch
# tuyệt đối thì deploy lại từ commit cũ, đừng dựa vào script này.
set -euo pipefail

HOST="${VIDEODL_MINI_HOST:-nobi_auto@100.109.39.103}"
EXPECT_HOST="autos-mac-mini"
REMOTE_REPO="Projects/video-download"
LABEL="com.astronex.videodl"
PORT=7870

BACKUP="${1:-}"
[ -n "$BACKUP" ] || { echo "Thiếu tham số: tên thư mục bản lui (deploy in ra ở dòng cuối)" >&2; exit 1; }
BACKUP_NAME="${BACKUP#../}"

say() { printf '\n== %s\n' "$*"; }

# Cùng cổng như lúc deploy: lui nhầm máy cũng hỏng như deploy nhầm máy.
say "0. Kiểm máy đích"
remote_host="$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$HOST" 'hostname' 2>&1 | tail -1)"
norm="$(printf '%s' "$remote_host" | tr '[:upper:]' '[:lower:]' | sed 's/\.local$//')"
echo "   hostname bên kia: $remote_host"
[ "$norm" = "$EXPECT_HOST" ] || { echo "DỪNG: không phải $EXPECT_HOST" >&2; exit 1; }

say "1. Kiểm bản lui có thật không"
ssh "$HOST" "test -d ~/Projects/$BACKUP_NAME" \
  || { echo "DỪNG: không thấy ~/Projects/$BACKUP_NAME bên kia" >&2; exit 1; }
so_file="$(ssh "$HOST" "find ~/Projects/$BACKUP_NAME -type f | wc -l | tr -d ' '")"
echo "   ~/Projects/$BACKUP_NAME — $so_file file"

say "2. Chép ngược đè lên repo"
ssh "$HOST" "cp -R ~/Projects/$BACKUP_NAME/. ~/$REMOTE_REPO/"

say "3. kickstart -k $LABEL"
ssh "$HOST" "launchctl kickstart -k gui/\$(id -u)/$LABEL"

say "4. Nghiệm thu"
sleep 4
code=""
for i in 1 2 3 4 5 6 7 8 9 10; do
  code="$(ssh "$HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$PORT/healthz || true")"
  [ "$code" = "200" ] && break
  sleep 2
done
echo "   healthz: HTTP $code"
[ "$code" = "200" ] || { echo "healthz KHÔNG lên sau khi lui — cần người vào xem" >&2; exit 1; }

sau="$(ssh "$HOST" "launchctl list | grep -c astronex || true")"
echo "   label astronex: $sau (phải là 5)"

say "ĐÃ LUI. Nhớ: file mà bản deploy hỏng THÊM MỚI vẫn còn trên đĩa (xem đầu file)."
