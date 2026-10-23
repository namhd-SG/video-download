#!/bin/bash
# Một video của một lượt bộ đề thay logo — chạy TRÊN ca-n, cách ly prod (gọi từ bo-de-thay-logo-luot.sh).
# Đối số: <số video N> <tên lượt>. Mã: $K/ma/<sha>/src (theo $K/ra/<lượt>/sha); env thêm: $K/ra/<lượt>/env (KEY=VAL mỗi dòng).
# Không đọc env prod, không ghi web/data, không đụng launchctl/videodl. Chạy lại được: video đã có kq.json thì bỏ qua.
# Bẫy đã dẫm (giữ nguyên lý do): bash 3.2 parse sai `case` trong $(…) ⇒ PYTHONPATH rác ⇒ python lặng lẽ dùng mã prod đã cài mà rc 0
# ⇒ KHÔNG đặt case trong $(…), và kiểm thư mục mã tồn tại trước khi chạy. Shell mặc định ca-n là zsh ⇒ luôn gọi bằng /bin/bash.
set -u
N="$1"; LUOT="$2"
K=/Users/mktmini/kho-ca/thay-logo
L="$K/ra/$LUOT"; D="$K/v/$N"; O="$L/$N"
SHA=$(cat "$L/sha")
MA="$K/ma/$SHA"
mkdir -p "$O"
[ -f "$O/kq.json" ] && exit 0

# Gác cổng (luật cũ, ĐP 22/10): RAM trống ≥ 30%, không job thay logo prod đang chạy, không chồng BẤT KỲ tiến trình Creative Tracker /
# chay-thu / vn-slot / daily-bo. Mẫu [c]… + awk bỏ dòng grep: cổng không được tự khớp chính mình (đã dẫm 20/10, 21/10).
while :; do
  ram=$(memory_pressure | awk -F': ' '/free percentage/{gsub("%","",$2); print $2}')
  prod=$(sqlite3 'file:/Users/mktmini/Projects/video-download/web/data/thay_logo_log.db?immutable=1' \
         "select count(*) from tl_job_video where trang_thai in ('dang_chay','cho_agy','cho')" 2>/dev/null || echo 0)
  ct=$(pgrep -fl "[c]hay-thu|[c]reative_tracker|[v]n-slot|[d]aily.bo" | awk '$2 != "grep"' | wc -l | tr -d " ")
  if [ "${ram:-0}" -ge 30 ] && [ "$ct" = 0 ] && [ "${prod:-0}" = 0 ]; then break; fi
  echo "$(date +%T) $LUOT v$N chờ: ram=$ram prod=$prod ct=$ct" >> "$K/ra/gac-cong.log"; sleep 60
done

[ -f "$MA/src/tiktok_music_downloader/thay_logo/cong.py" ] || { echo "thiếu mã $MA" >&2; exit 3; }
THEM=()
if [ -s "$L/env" ]; then while IFS= read -r dong; do [ -n "$dong" ] && THEM+=("$dong"); done < "$L/env"; fi
PY=/Users/mktmini/Projects/video-download/.venv/bin/python
# Mã nạp được phải là $MA, không phải gói prod đã cài vào venv (đối chứng bẫy PYTHONPATH): lệch ⇒ dừng, không ghi kq.json.
nap=$(env -i PYTHONPATH="$MA/src" PYTHONDONTWRITEBYTECODE=1 "$PY" -c 'import tiktok_music_downloader.thay_logo.cong as c; print(c.__file__)')
case "$nap" in "$MA/src/"*) ;; *) echo "mã nạp nhầm: $nap (cần $MA/src)" >&2; exit 4 ;; esac
t0=$(date +%s)
env -i HOME=/Users/mktmini PATH=/Users/mktmini/micromamba/envs/work/bin:/usr/bin:/bin \
  PYTHONPATH="$MA/src" PYTHONDONTWRITEBYTECODE=1 ${THEM[@]+"${THEM[@]}"} \
  nice -n 15 "$PY" -m tiktok_music_downloader.thay_logo.chay_mot_video \
  --video "$D/goc.mp4" --boxes "$D/boxes-agymoi.json" --out "$O/ra.mp4" --db "$O/log.db" --files "$O/files" \
  --nguon-video "bo-de-$LUOT" --ffmpeg /Users/mktmini/micromamba/envs/work/bin/ffmpeg --job-id 1 \
  > "$O/kq.tmp" 2> "$O/stderr.log"
rc=$?
if [ -f "$O/ra.mp4" ]; then md5 -q "$O/ra.mp4" > "$O/md5"; fi
printf '{"v":%s,"luot":"%s","sha":"%s","rc":%s,"giay":%s,"kq":%s}\n' "$N" "$LUOT" "$SHA" "$rc" "$(( $(date +%s) - t0 ))" \
  "$(tail -1 "$O/kq.tmp" 2>/dev/null || echo null)" > "$O/kq.json.tmp" && mv "$O/kq.json.tmp" "$O/kq.json"
