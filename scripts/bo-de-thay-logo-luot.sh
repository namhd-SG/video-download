#!/bin/bash
# Một LƯỢT bộ đề thay logo trên ca-n: 40 video, 2 luồng, video dài chạy trước. Đối số: <tên lượt>.
# Gọi nền từ bo-de-thay-logo.sh (nohup). Ghi $K/ra/<lượt>/xong khi MỌI video có kq.json rc 0 — mốc ghi SAU việc nó khẳng định.
set -u
LUOT="$1"
K=/Users/mktmini/kho-ca/thay-logo
L="$K/ra/$LUOT"
# Một lượt tại một thời điểm (2 luồng đã là trần cổng tài nguyên): khoá bằng mkdir (nguyên tử), nhả khi thoát.
until mkdir "$K/ra/.khoa" 2>/dev/null; do echo "$(date +%T) $LUOT chờ khoá ($(cat "$K/ra/.khoa/luot" 2>/dev/null))" >> "$L/luot.log"; sleep 60; done
echo "$LUOT" > "$K/ra/.khoa/luot"
trap 'rm -rf "$K/ra/.khoa"' EXIT
rm -f "$L/xong"  # mốc cũ của lần chạy trước không được làm `cho` thoát sớm
echo "$(date '+%F %T') bắt đầu $LUOT sha=$(cat "$L/sha")" >> "$L/luot.log"
ls -S "$K/v"/*/goc.mp4 | awk -F/ '{print $(NF-1)}' \
  | xargs -P 2 -I{} /bin/bash "$K/cong-cu/scripts/bo-de-thay-logo-mot-video.sh" {} "$LUOT" >> "$L/luot.log" 2>&1
du=$(grep -l '"rc":0,' "$L"/*/kq.json 2>/dev/null | wc -l | tr -d ' ')
can=$(ls -d "$K/v"/*/ | wc -l | tr -d ' ')
echo "$(date '+%F %T') kết thúc $LUOT: $du/$can kq.json" >> "$L/luot.log"
[ "$du" = "$can" ] && date '+%F %T' > "$L/xong"
