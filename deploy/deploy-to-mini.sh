#!/usr/bin/env bash
# Đưa mã nguồn từ máy dev lên mac mini công ty rồi khởi động lại dịch vụ.
#
# Chạy TRÊN MÁY DEV:
#     bash deploy/deploy-to-mini.sh            # thử khô, không đụng gì
#     bash deploy/deploy-to-mini.sh --yes      # làm thật
#
# Vì sao script này tồn tại thay vì gõ rsync bằng tay: ngày 16/09 một phiên
# suýt rsync vào alias `mini`, mà alias đó trỏ về CHÍNH MÁY DEV
# (nam-mini-m4.local) — tức là đè lên worktree đang gõ dở. Cổng `hostname` ở
# bước 0 biến cái suýt đó thành thứ máy chặn được.
#
# Máy đích chạy production của đội khác (Promax, ollama, glances), không sudo,
# đĩa còn hẹp. Vì thế: CHỈ `kickstart -k` đúng label của mình, KHÔNG `bootout`
# bất cứ thứ gì, và đếm label hàng xóm trước/sau.
set -euo pipefail

HOST="${VIDEODL_MINI_HOST:-nobi_auto@100.109.39.103}"
# Tên máy đích sau khi chuẩn hoá. `hostname` thật trả về "Autos-Mac-mini.local"
# — hoa đầu, có đuôi .local — nên so khớp đúng chữ sẽ chặn nhầm chính mình.
EXPECT_HOST="autos-mac-mini"
REMOTE_REPO="Projects/video-download"
LABEL="com.astronex.videodl"
PORT=7870
STAMP="$(date +%y%m%d-%H%M%S)"
# Đường TƯƠNG ĐỐI có chủ ý: rsync tính --backup-dir theo thư mục ĐÍCH, còn
# "$HOME/..." sẽ nở ở máy dev (/Users/macos) chứ không phải home của nobi_auto
# bên kia — bản lui sẽ nằm sai chỗ, hoặc không ghi được.
BACKUP_DIR="../video-download-truoc-$STAMP"

# Một danh sách DUY NHẤT cho cả thử khô lẫn lần chạy thật. Hai danh sách rời
# nhau thì thử khô thành lời nói dối ngay lần đầu ai đó sửa một bên.
#
# `deploy/run-service.sh` là thứ launchd THỰC SỰ gọi
# (ProgramArguments trong com.astronex.videodl.plist), nhưng nó do
# mini-setup.sh SINH RA TRÊN MINI và không có trong git. Không loại nó ra thì
# --delete xoá đúng file đang chạy dịch vụ; KeepAlive=true nên nó chết và
# không dựng lại được. Thử khô ngày 16/09 bắt được đúng ca này.
EXCLUDES=(
  --exclude='.venv'
  --exclude='.git'
  --exclude='web/data'
  --exclude='assets/ffmpeg-static'
  --exclude='deploy/run-service.sh'
  --exclude='__pycache__'
)

THAT=0
[ "${1:-}" = "--yes" ] && THAT=1

cd "$(git rev-parse --show-toplevel)"
say() { printf '\n== %s\n' "$*"; }

# --- 0. CỔNG: máy bên kia có đúng là mini công ty không? ---------------------
# Đây là cổng quan trọng nhất trong script. Không có nó, một alias trỏ sai là
# đủ để rsync đè lên máy dev.
say "0. Kiểm máy đích"
remote_host="$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$HOST" 'hostname' 2>&1 | tail -1)"
norm="$(printf '%s' "$remote_host" | tr '[:upper:]' '[:lower:]' | sed 's/\.local$//')"
echo "   hostname bên kia: $remote_host  (chuẩn hoá: $norm)"
if [ "$norm" != "$EXPECT_HOST" ]; then
  echo "DỪNG: máy đích không phải $EXPECT_HOST." >&2
  echo "      Nếu nó ra nam-mini-m4 thì bạn đang trỏ về chính máy dev." >&2
  exit 1
fi

# --- 1. CỔNG: mã nguồn đã commit và đã đẩy chưa? -----------------------------
# Deploy một cây dirty thì cái đang chạy trên mini không còn tương ứng với bất
# kỳ commit nào — không ai lui được, và không ai nói được "prod đang chạy gì".
say "1. Kiểm cây mã nguồn"
if [ -n "$(git status --porcelain)" ]; then
  echo "DỪNG: cây còn thay đổi chưa commit. Commit hoặc dọn trước." >&2
  git status --porcelain >&2
  exit 1
fi
SHA="$(git rev-parse HEAD)"
if [ -z "$(git branch -r --contains HEAD)" ]; then
  echo "DỪNG: commit $SHA chưa có trên origin. Đẩy trước đã." >&2
  exit 1
fi
echo "   HEAD $SHA — sạch, đã có trên origin"

# --- 2. Đếm hàng xóm TRƯỚC ---------------------------------------------------
say "2. Đếm label astronex trước khi đụng"
truoc="$(ssh "$HOST" "launchctl list | grep -c astronex || true")"
echo "   trước: $truoc"

if [ "$THAT" -eq 0 ]; then
  say "THỬ KHÔ — dừng ở đây. Chạy lại với --yes để làm thật."
  echo "   sẽ rsync vào : $HOST:~/$REMOTE_REPO/"
  echo "   bản lui giữ ở: $HOST:~/Projects/${BACKUP_DIR#../}/"
  rsync -a --dry-run --itemize-changes --delete "${EXCLUDES[@]}" \
        ./ "$HOST:~/$REMOTE_REPO/"
  exit 0
fi

# --- 3. Đẩy mã, giữ bản cũ để lui -------------------------------------------
# --backup-dir giữ ĐÚNG những file bị thay/xoá, không phải cả cây: đĩa bên đó
# chỉ còn ~11GB và 194GB là của account khác.
# --delete để cây bên kia đúng bằng cây ở đây; không có nó thì file cũ nằm lại
# và "đang chạy gì" thành câu không ai trả lời được.
# assets/ffmpeg-static loại ra: file lớn, mini-setup.sh cấp riêng bằng scp.
say "3. rsync (giữ bản lui ở ~/Projects/${BACKUP_DIR#../})"
rsync -a --delete --backup --backup-dir="$BACKUP_DIR" "${EXCLUDES[@]}" \
      ./ "$HOST:~/$REMOTE_REPO/"
echo "   xong"

# --- 4. Khởi động lại ĐÚNG label của mình ------------------------------------
say "4. kickstart -k $LABEL"
ssh "$HOST" "launchctl kickstart -k gui/\$(id -u)/$LABEL"

# --- 5. Nghiệm thu ----------------------------------------------------------
# Không hỏi "lệnh có chạy không" mà hỏi "thứ vừa đẩy có đang phục vụ không":
# so sha256 của ba tệp tĩnh với bản ở máy dev.
say "5. Nghiệm thu"
sleep 4
for i in 1 2 3 4 5 6 7 8 9 10; do
  code="$(ssh "$HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$PORT/healthz || true")"
  [ "$code" = "200" ] && break
  sleep 2
done
echo "   healthz: HTTP $code"
[ "$code" = "200" ] || { echo "DỪNG: healthz không lên. Lui bằng deploy/rollback-on-mini.sh $BACKUP_DIR" >&2; exit 1; }

for f in index.html app.js app.css; do
  local_sha="$(shasum -a 256 "web/static/$f" | cut -d' ' -f1)"
  remote_sha="$(ssh "$HOST" "curl -s --max-time 10 http://127.0.0.1:$PORT/$f | shasum -a 256 | cut -d' ' -f1")"
  if [ "$local_sha" = "$remote_sha" ]; then
    echo "   $f: khớp"
  else
    echo "   $f: LỆCH (dev=$local_sha mini=$remote_sha)" >&2
    echo "   Lui bằng: bash deploy/rollback-on-mini.sh $BACKUP_DIR" >&2
    exit 1
  fi
done

cc="$(ssh "$HOST" "curl -s -D - -o /dev/null --max-time 10 http://127.0.0.1:$PORT/app.js | grep -i '^cache-control' || true")"
echo "   app.js ${cc:-KHÔNG CÓ cache-control — bản cũ còn đang chạy?}"

bind="$(ssh "$HOST" "lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | grep -c '127.0.0.1' || true")"
echo "   bind 127.0.0.1: $bind (phải ≥1 — không được nghe 0.0.0.0)"

sau="$(ssh "$HOST" "launchctl list | grep -c astronex || true")"
echo "   label astronex sau: $sau (trước: $truoc)"
[ "$sau" -ge "$truoc" ] || { echo "MẤT label hàng xóm — kiểm ngay" >&2; exit 1; }

px="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://promax.nobidigital.asia || true)"
echo "   promax hàng xóm: HTTP $px (chết là do mình, phải kiểm)"

say "XONG — $SHA đang chạy trên $EXPECT_HOST"
echo "   Lui: bash deploy/rollback-on-mini.sh $BACKUP_DIR"
