#!/usr/bin/env bash
# Đổi tool Cắt tutorial (của chị Linh, github.com/linhpl-xinh/video-tools) trên máy đích sang MỘT sha đã ghim.
#
# Chạy TRÊN MÁY DEV, từ checkout video-download:
#     bash deploy/cap-nhat-cat-tutorial.sh <sha>          # thử khô: kéo + kiểm hợp đồng + hỏi máy đích + in sẽ rsync gì
#     bash deploy/cap-nhat-cat-tutorial.sh <sha> --yes    # làm thật: rsync scripts/ → ~/cat-tutorial/app, ghi SHA, kickstart
#
# Code chị Linh đổi hằng ngày ⇒ ghim
# sha, cập nhật chủ động, KHÔNG tự kéo. Trang `/cat-tutorial/` của Video Desk viết lại đường dẫn tuyệt đối trong
# ui/index.html (web/cat_tutorial_duong_dan.py) — bản mới có đường lạ thì script DỪNG ở bước 2, máy đích chưa bị đụng.
#
# Lần ĐẦU (venv + wrapper + plist) đi deploy/cat-tutorial/cai-venv.sh trên máy đích; script này dừng nếu chưa có.
# Chỉ đụng ~/cat-tutorial/{app,SHA} và đúng label của mình; KHÔNG bootout gì, KHÔNG đụng dịch vụ Video Desk.
set -euo pipefail

RC_SAI_MAY=1        # hostname máy đích không khớp bảng (deploy/may-dich.sh)
RC_THAM_SO=2        # thiếu/sai sha, hoặc sha không có trong repo nguồn
RC_HOP_DONG=3       # bản mới vỡ hợp đồng (đường lạ trong index.html / ui_server đổi cookie, cổng, chế độ web, bind)
RC_NGHIEM_THU=4     # đã rsync + kickstart nhưng /api/ping không lên
RC_DO_HONG=5        # không ssh được / máy đích chưa cài lần đầu — phép đo hỏng, KHÁC sai máy
# RC 7 = tên máy lạ trong bảng máy đích (đặt trong chính deploy/may-dich.sh)

REPO_GOC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# shellcheck source=deploy/may-dich.sh
source "$REPO_GOC/deploy/may-dich.sh"
NGUON="https://github.com/linhpl-xinh/video-tools.git"
DUONG_SCRIPTS="plugins/cat-tutorial/skills/cat-tutorial/scripts"
LABEL="com.astronex.cat-tutorial"
CONG=8790
DICH="cat-tutorial"                       # ~/cat-tutorial/{app,venv,SHA} trên máy đích
PY_KIEM="${CAT_TUTORIAL_PY_KIEM:-python3}" # kiểm hợp đồng chỉ cần stdlib

say() { printf '\n== %s\n' "$*"; }
dung() { local rc="$1"; shift; echo "DỪNG: $*" >&2; exit "$rc"; }

SHA_XIN="${1:-}"
LAM_THAT=0
[ "${2:-}" = "--yes" ] && LAM_THAT=1
[[ "$SHA_XIN" =~ ^[0-9a-f]{7,40}$ ]] || dung "$RC_THAM_SO" "cách dùng: bash deploy/cap-nhat-cat-tutorial.sh <sha 7-40 hex> [--yes]"

TAM="$(mktemp -d "${TMPDIR:-/tmp}/cat-tutorial-XXXXXX")"
trap 'rm -rf "$TAM"' EXIT

# --- 1. Kéo đúng sha vào thư mục tạm ---------------------------------------
say "1. Kéo $NGUON @ $SHA_XIN"
git clone --quiet --filter=blob:none --no-checkout "$NGUON" "$TAM/src" || dung "$RC_DO_HONG" "không clone được $NGUON"
git -C "$TAM/src" -c advice.detachedHead=false checkout --quiet "$SHA_XIN" 2>/dev/null \
  || dung "$RC_THAM_SO" "sha $SHA_XIN không có trong $NGUON"
SHA_DU="$(git -C "$TAM/src" rev-parse HEAD)"
SCRIPTS="$TAM/src/$DUONG_SCRIPTS"
for f in ui_server.py cat_tutorial.py ui/index.html; do
  [ -f "$SCRIPTS/$f" ] || dung "$RC_HOP_DONG" "bản $SHA_DU thiếu $DUONG_SCRIPTS/$f"
done
echo "   sha đầy đủ: $SHA_DU"

# --- 2. Hợp đồng: thứ proxy Video Desk dựa vào -------------------------------
say "2. Kiểm hợp đồng"
(cd "$REPO_GOC" && "$PY_KIEM" -m web.cat_tutorial_duong_dan "$SCRIPTS/ui/index.html") \
  || dung "$RC_HOP_DONG" "index.html bản mới có đường dẫn ngoài danh sách — sửa web/cat_tutorial_duong_dan.py (+ test) trước"
# Mỗi mốc là một giả định của web/cat_tutorial_routes.py: cookie khu 32 hex tên ct_ws, chế độ web + cổng qua env,
# server web CHỈ bind 127.0.0.1 (tool không có đăng nhập), số luồng nhận diện kẹp được qua env.
while IFS='|' read -r tep moc; do
  grep -qF -- "$moc" "$SCRIPTS/$tep" || dung "$RC_HOP_DONG" "$tep không còn chứa: $moc"
done <<'MOC'
ui_server.py|ct_ws=([0-9a-f]{32})
ui_server.py|CAT_TUTORIAL_WEB
ui_server.py|CAT_TUTORIAL_PORT
ui_server.py|ThreadingHTTPServer(("127.0.0.1", port), H)
cat_tutorial.py|CAT_TUTORIAL_WORKERS
MOC
echo "   ui_server: cookie ct_ws, CAT_TUTORIAL_WEB/PORT, bind 127.0.0.1 — còn nguyên"

# --- 3. Cổng máy đích ---------------------------------------------------------
say "3. Kiểm máy đích"
echo "   máy đích: $HOST (VIDEODL_MAY_DICH=$MAY_DICH, mong hostname: $EXPECT_HOST)"
remote_host="$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$HOST" 'hostname' 2>&1 | tail -1)" \
  || dung "$RC_DO_HONG" "không ssh được tới $HOST (nhận: '$remote_host')"
norm="$(printf '%s' "$remote_host" | tr '[:upper:]' '[:lower:]' | sed 's/\.local$//')"
[ "$norm" = "$EXPECT_HOST" ] || dung "$RC_SAI_MAY" "máy đích là '$remote_host', không phải $EXPECT_HOST"
ssh "$HOST" "test -x ~/$DICH/venv/bin/python && test -x ~/$DICH/run-cat-tutorial.sh && launchctl print gui/\$(id -u)/$LABEL >/dev/null 2>&1" \
  || dung "$RC_DO_HONG" "máy đích chưa cài lần đầu (venv / wrapper / label $LABEL) — chạy deploy/cat-tutorial/cai-venv.sh trên đó"
SHA_CU="$(ssh "$HOST" "cat ~/$DICH/SHA 2>/dev/null || true")"
echo "   đang chạy: ${SHA_CU:-<chưa có SHA>}  →  sẽ chạy: $SHA_DU"

# --- 4. rsync scripts/ → ~/cat-tutorial/app -----------------------------------
RSYNC_CO=(-a --delete --exclude '__pycache__/' --exclude '*.pyc')
if [ "$LAM_THAT" -ne 1 ]; then
  say "4. THỬ KHÔ — sẽ đổi trên máy đích:"
  ssh "$HOST" "mkdir -p ~/$DICH/app"
  rsync "${RSYNC_CO[@]}" --dry-run --itemize-changes "$SCRIPTS/" "$HOST:$DICH/app/"
  echo; echo "Thử khô xong, máy đích chưa đổi gì. Làm thật: bash deploy/cap-nhat-cat-tutorial.sh $SHA_XIN --yes"
  exit 0
fi
say "4. rsync"
ssh "$HOST" "mkdir -p ~/$DICH/app"
rsync "${RSYNC_CO[@]}" "$SCRIPTS/" "$HOST:$DICH/app/"
ssh "$HOST" "printf '%s\n' '$SHA_DU' > ~/$DICH/SHA"

# --- 5. Khởi động lại đúng label + nghiệm thu --------------------------------
say "5. kickstart $LABEL + chờ /api/ping"
ssh "$HOST" "launchctl kickstart -k gui/\$(id -u)/$LABEL"
ssh "$HOST" "for i in \$(seq 1 30); do curl -fsS --max-time 3 http://127.0.0.1:$CONG/api/ping && exit 0; sleep 2; done; exit 1" \
  || { echo "DỪNG: $LABEL không trả /api/ping sau ~60s — xem ~/Library/Logs/$LABEL.log trên máy đích." >&2
       [ -n "$SHA_CU" ] && echo "      Lui: bash deploy/cap-nhat-cat-tutorial.sh $SHA_CU --yes" >&2
       exit "$RC_NGHIEM_THU"; }
echo; echo "XONG: $LABEL chạy $SHA_DU (trước: ${SHA_CU:-<chưa có>})."
