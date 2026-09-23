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

# Mã thoát riêng cho từng kết cục, để người gọi (và người đọc log) phân biệt
# được "sai máy" với "có người đang tải" — hai ca đòi hai việc khác nhau.
RC_SAI_MAY=1        # máy đích không phải mini
RC_CAY_BAN=2        # cây chưa commit / chưa đẩy
RC_DANG_TAI=3       # có job đang chạy hoặc đang chờ
RC_NGHIEM_THU=4     # đẩy xong nhưng nghiệm thu trượt
RC_DO_HONG=5        # không đọc được số job — phép đo hỏng, KHÁC "đang bận"

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
  # Ghim TƯỜNG MINH, không trông vào `.gitignore` bên dưới — đổi tệp đó thì ba
  # dòng này vẫn giữ:
  # - `.claude/`: ghi chú nội bộ của agent. Trước 23/09 rsync đẩy nó lên máy
  #   DÙNG CHUNG (`~` là 750, nhóm staff đọc được). Không thuộc về prod.
  # - `.pytest_cache/`: rác của pytest trên máy dev.
  # - `*.egg-info/`: mini CẦN `src/tiktok_music_downloader.egg-info` cho bản cài
  #   editable trong venv. Bị loại trừ nghĩa là `--delete` KHÔNG BAO GIỜ chạm nó
  #   ở phía nhận — đó là lý do chính của dòng này, không phải để bớt tệp gửi.
  --exclude='.claude/'
  --exclude='.pytest_cache/'
  --exclude='*.egg-info/'
  # Mọi thứ git bỏ qua cũng không thuộc về prod: cây "sạch" ở bước 1 là theo
  # `git status`, mà `git status` không nhìn tệp ignore — thiếu dòng này thì rác
  # ignore trên máy dev đi thẳng lên mini (đo 23/09: 25 tệp). Đo cùng ngày:
  # `git ls-files -ci --exclude-standard` = 0 (không tệp tracked nào khớp mẫu
  # ignore) và tập nguồn mới thiếu 0 tệp so với `git ls-files`.
  --exclude-from='.gitignore'
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
# So DANH SÁCH TÊN, không so SỐ ĐẾM. Đếm không phân định được ca xấu nhất:
# mất `com.astronex.videodl` mà mọc thêm một label khác thì tổng vẫn bằng nhau
# và cổng dưới báo xanh. Luật này chốt ở commit a479522 nhưng chỉ sửa plan —
# script vẫn đếm tới tận 22/09, và ba chuyến deploy hôm đó qua cổng bằng tay.
say "2. Ghi TÊN label astronex trước khi đụng"
ten_label() { ssh "$HOST" "launchctl list | awk 'NR>1 {print \$3}' | grep -i astronex | sort" || true; }
truoc="$(ten_label)"
echo "$truoc" | sed 's/^/   /'


# --- 2b. CỔNG: có ai đang tải không? -----------------------------------------
# `kickstart -k` ở bước 4 giết tiến trình rồi dựng lại, nên một job đang chạy
# chết giữa chừng.
#
# Cổng này KHÔNG phải để giữ DB đúng — repo đã lo: `JobWorker.start()` quét
# `running` thành `interrupted` ở lượt khởi động kế tiếp (`web/queue.py`), và
# `quet_jar_tam` dọn jar cookie tạm (`web/app.py`). Thứ nó bảo vệ là CÔNG CỦA
# NGƯỜI DÙNG: job 10 ngày 22/09 chạy 44 phút và đã đọc 10 trang index. Cắt
# ngang thì người tạo mất cả thời gian LẪN khẩu phần — `so_trang` ghi tăng dần
# ngay khi tiêu, nên trần 800 trang/ngày đã trừ rồi; chạy lại là trừ lần nữa.
#
# Đứng TRƯỚC rsync, không phải giữa rsync và kickstart: chặn ở đây thì máy đích
# không bị đụng một byte nào. Chặn sau rsync sẽ để lại trạng thái lệch — tệp MỚI
# nằm trên đĩa trong khi tiến trình CŨ đang phục vụ, và `KeepAlive=true` nghĩa là
# một lần crash bất kỳ sau đó sẽ dựng lên bản mới vào lúc không ai định.
#
# ⚠ Còn một khe không bịt: job được tạo TRONG lúc rsync chạy (vài giây) vẫn bị
# bước 4 cắt. Chấp nhận — job đó mới chạy vài giây, mất gần như không gì, còn
# đóng khe thì phải kiểm hai lần và vẫn không kín.
#
# Và đứng TRƯỚC lối thoát của thử khô: nếu nó nằm sau, `--dry-run` sẽ báo
# xanh cho một lần chạy thật mà đáng lẽ bị chặn — thử khô khi đó không còn
# diễn tập cùng đường với lần chạy thật, tức là một lời hứa nó không giữ được.
# (Đo 23/09: bản đầu đặt sau, thử khô nhảy thẳng từ bước 2 sang "THỬ KHÔ".)
#
# Câu SELECT lấy từ `plans/260917-1445-plan-tong-de-dong-tool/plan.md`, mục
# "30 giây trước Deploy".
#
# KHÔNG dùng `sqlite3 -readonly`: DB này chạy WAL, mở read-only trượt với
# "unable to open database file (14)" vì nó cần ghi được `-shm`.
# ⚠ `sqlite3 -readonly <db> 'SELECT 1'` thì LẠI CHẠY — `SELECT 1` không chạm
# bảng nên không cần WAL. Dùng nó làm đối chứng là tự cấp chứng nhận.
say "2b. Kiểm có job đang chạy không"
dang_tai="$(ssh "$HOST" "sqlite3 ~/$REMOTE_REPO/web/data/jobs.db \"SELECT COUNT(*) FROM jobs WHERE trang_thai NOT IN ('done','failed','interrupted')\"")"

# Truy vấn trượt trả chuỗi RỖNG, và `[ "" != "0" ]` cũng đúng ⇒ cổng vẫn chặn.
# Chặn là hướng an toàn, nhưng thông điệp khi đó nói "N job đang chạy" trong khi
# sự thật là PHÉP ĐO HỎNG — một kết luận dụng cụ không có bằng chứng để nói.
# Tách hẳn hai ca ra, đúng vế 1 của `guard-marker-and-claim-write-ordering`.
case "$dang_tai" in
  ''|*[!0-9]*)
    echo "DỪNG: không đọc được số job đang chạy (nhận: '$dang_tai')." >&2
    echo "      Đây là PHÉP ĐO HỎNG, không phải 'đang có người tải'." >&2
    echo "      Kiểm ssh và đường dẫn jobs.db trên máy đích rồi chạy lại." >&2
    exit "$RC_DO_HONG" ;;
esac
echo "   job đang chạy/chờ: $dang_tai"
if [ "$dang_tai" != "0" ]; then
  echo "DỪNG: $dang_tai job đang chạy hoặc đang chờ — khởi động lại sẽ cắt ngang." >&2
  echo "      Chưa đụng gì tới máy đích. Đợi job xong rồi chạy lại script này." >&2
  exit "$RC_DANG_TAI"
fi

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

sau="$(ten_label)"
if [ "$sau" = "$truoc" ]; then
  echo "   label astronex: danh sách TÊN không đổi"
else
  echo "   label astronex ĐỔI — kiểm ngay:" >&2
  diff <(printf '%s\n' "$truoc") <(printf '%s\n' "$sau") >&2 || true
  exit "$RC_NGHIEM_THU"
fi

px="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://promax.nobidigital.asia || true)"
echo "   promax hàng xóm: HTTP $px (chết là do mình, phải kiểm)"

say "XONG — $SHA đang chạy trên $EXPECT_HOST"
echo "   Lui: bash deploy/rollback-on-mini.sh $BACKUP_DIR"
