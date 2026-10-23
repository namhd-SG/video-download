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
# Chỉ bỏ qua video đã chạy THÀNH CÔNG; kq.json với rc ≠ 0 (lỗi hạ tầng) thì chạy lại.
grep -q '"rc":0,' "$O/kq.json" 2>/dev/null && exit 0
# Chưa có kq.json rc 0 ⇒ mọi thứ trong $O là của lần chạy bị cắt: xoá. Dùng lại log.db cũ ⇒ tl_video id 2 ⇒ track nằm ở files/2 và
# tl_vet trộn hai lần (đã dẫm 23/10: python mồ côi sau kill bash cha vẫn ghi vào log.db).
rm -rf "$O"; mkdir -p "$O"

# Gác cổng (luật cũ, ĐP 22/10): RAM trống ≥ 30%, không job thay logo prod đang chạy, không chồng BẤT KỲ tiến trình Creative Tracker /
# chay-thu / vn-slot / daily-bo. Mẫu [c]… + awk bỏ dòng grep: cổng không được tự khớp chính mình (đã dẫm 20/10, 21/10).
# Khung cấm (Creative Tracker ưu tiên, ĐP 23/10): $K/khung-cam, mỗi dòng `HH:MM-HH:MM` giờ VN. Cổng chỉ kiểm lúc BẮT ĐẦU video
# (video đang chạy không bị cắt) ⇒ hai lớp, không bắt đầu khi:
#   lớp 1: giờ hiện tại + ƯỚC × 1,5 vượt quá đầu một khung (kể cả khung của ngày hôm sau);
#   lớp 2: giờ hiện tại nằm trong [đầu − DU_PHUT, cuối).
# ƯỚC = thời gian chạy LỚN NHẤT đã đo của chính video này (mọi kq.json cũ trong $K/ra/*/N và $K/uoc-giay); chưa đo bao giờ
# ⇒ độ dài video × HE_SO_UOC. HE_SO_UOC = 16 ≥ hệ số lớn nhất đo được 15,7 (v6, 1080p 17 s, 9 lượt 21–22/10); trung vị 1,7.
DU_PHUT=10
HE_SO_UOC=16
phut() { echo $(( 10#${1%:*} * 60 + 10#${1#*:} )); }
uoc_giay() {  # <N> → giây ước (số nguyên)
  local g
  g=$( { grep -h '"rc":0,' "$K"/ra/*/"$1"/kq.json 2>/dev/null | grep -o '"giay":[0-9]*' | cut -d: -f2
         awk -v n="$1" '$1 == n {print $2}' "$K/uoc-giay" 2>/dev/null; } | sort -n | tail -1)
  if [ -z "$g" ]; then
    g=$(/Users/mktmini/micromamba/envs/work/bin/ffprobe -v error -show_entries format=duration -of csv=p=0 "$K/v/$1/goc.mp4" \
        | awk -v h="$HE_SO_UOC" '{printf "%d", $1 * h + 1}')
  fi
  echo "${g:-3600}"
}
trong_khung_cam() {  # <N> [giờ VN HH:MM, để thử giả giờ] → in lý do và trả 0 nếu KHÔNG được bắt đầu
  [ -s "$K/khung-cam" ] || return 1
  local bay can dong a b
  bay=$(phut "${2:-$(TZ=Asia/Ho_Chi_Minh date +%H:%M)}")
  can=$(( ( $(uoc_giay "$1") * 3 / 2 + 59 ) / 60 ))  # phút, làm tròn lên
  while IFS= read -r dong; do
    case "$dong" in [0-9][0-9]:[0-9][0-9]-[0-9][0-9]:[0-9][0-9]) ;; *) continue ;; esac
    a=$(phut "${dong%-*}"); b=$(phut "${dong#*-}")
    if { [ "$bay" -lt "$a" ] && [ $(( bay + can )) -gt "$a" ]; } || [ $(( bay + can )) -gt $(( a + 1440 )) ]; then
      echo "$dong (ước ${can} phút, chạy sẽ chồng)"; return 0
    fi
    if [ "$bay" -ge $(( a - DU_PHUT )) ] && [ "$bay" -lt "$b" ]; then echo "$dong"; return 0; fi
  done < "$K/khung-cam"
  return 1
}
# Tiến trình CT được phép chạy CHỒNG (ĐP d1bd356f 23/10 11:1x, theo tiền lệ ĐP 7740 22/10 07:5x): đúng cặp job thumbs-backlog —
# wrapper `vn-slot.sh thumbs-backlog` + `creative_tracker.collect --live --thumbs-only` (tải ảnh bìa: nặng mạng, nhẹ CPU).
# Vẫn chặn collect thường, collect-chain, daily-bo, chay-thu, probe. Đầu vào: dòng `pgrep -fl`; đầu ra: số tiến trình phải nhường.
BO_QUA_CT='^[0-9]+ /bin/bash [^ ]*/vn-slot\.sh thumbs-backlog |^[0-9]+ [^ ]*python[^ ]* -m creative_tracker\.collect --live --thumbs-only$'
dem_ct() { awk '$2 != "grep"' | grep -v -E "$BO_QUA_CT" | wc -l | tr -d " "; }
while :; do
  if cam=$(trong_khung_cam "$N"); then
    echo "$(date +%T) $LUOT v$N chờ: khung cấm $cam (VN)" >> "$K/ra/gac-cong.log"; sleep 60; continue
  fi
  ram=$(memory_pressure | awk -F': ' '/free percentage/{gsub("%","",$2); print $2}')
  prod=$(sqlite3 'file:/Users/mktmini/Projects/video-download/web/data/thay_logo_log.db?immutable=1' \
         "select count(*) from tl_job_video where trang_thai in ('dang_chay','cho_agy','cho')" 2>/dev/null || echo 0)
  ct=$(pgrep -fl "[c]hay-thu|[c]reative_tracker|[v]n-slot|[d]aily.bo|ct-checks-[0-9]*/[p]robe" | dem_ct)
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
kq_dong=$(tail -1 "$O/kq.tmp" 2>/dev/null); [ -n "$kq_dong" ] || kq_dong=null  # tiến trình chết không in gì ⇒ "kq":null, không phải JSON hỏng
printf '{"v":%s,"luot":"%s","sha":"%s","rc":%s,"giay":%s,"kq":%s}\n' "$N" "$LUOT" "$SHA" "$rc" "$(( $(date +%s) - t0 ))" "$kq_dong" \
  > "$O/kq.json.tmp" && mv "$O/kq.json.tmp" "$O/kq.json"
