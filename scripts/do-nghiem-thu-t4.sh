#!/usr/bin/env bash
# Bộ đo cho nghiệm thu T4 — CHẠY TRÊN MINI, CHỈ ĐỌC.
#
#     ssh nobi_auto@100.109.39.103 'bash -s' < scripts/do-nghiem-thu-t4.sh truoc
#     ssh nobi_auto@100.109.39.103 'bash -s' < scripts/do-nghiem-thu-t4.sh mau 300
#     ssh nobi_auto@100.109.39.103 'bash -s' < scripts/do-nghiem-thu-t4.sh sau
#
# Vì sao script thay vì gõ tay từng lệnh: T4 hẹn giờ với hai người thật trên
# một máy dùng chung với Promax. Khung 30 phút không phải lúc để dò cú pháp,
# và một phép đo gõ vội thường là phép đo không có ĐỐI CHỨNG.
#
# KHÔNG ghi gì. Không `chmod`, không `launchctl` trừ `list`, không đụng
# Promax. Mọi thứ ở đây đọc file, đọc DB, đọc `ps`.
set -uo pipefail   # KHÔNG -e: một phép đo trượt không được giết cả loạt đo
                   # còn lại — mất một số còn hơn mất cả bảng.

REPO="$HOME/Projects/video-download"
DB="$REPO/web/data/jobs.db"
LOG="$HOME/Library/Logs/videodl.log"
TAI="$REPO/web/data/downloads"

sq() { sqlite3 "$DB" "$1" 2>/dev/null; }

# --- ảnh chụp trạng thái: dùng CHUNG cho 'truoc' và 'sau' -------------------
# Một hàm, hai lần gọi. Hai khối chép tay sẽ lệch nhau ngay lần đầu ai đó sửa
# một bên — và lúc đó "trước/sau" so hai thứ khác nhau mà không ai thấy.
anh_chup() {
  echo "### $1 — $(date '+%Y-%m-%d %H:%M:%S')"
  # DANH SÁCH TÊN, không phải số đếm: số 5→4 không nói mất CÁI NÀO, và
  # câu cần trả lời là "mình có làm hỏng hàng xóm không".
  echo "-- launchd (tên, đã sắp xếp):"
  launchctl list | grep astronex | awk '{print "   " $3}' | sort
  echo "-- promax (302 = sống):"
  echo "   $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://promax.nobidigital.asia)"
  echo "-- healthz:"
  echo "   $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:7870/healthz)"
  echo "-- DB jobs/videos/nguoi_dung:"
  echo "   $(sq 'SELECT (SELECT COUNT(*) FROM jobs)||"/"||(SELECT COUNT(*) FROM videos)||"/"||(SELECT COUNT(*) FROM nguoi_dung);')"
  echo "-- đĩa còn:"
  df -h / | tail -1 | awk '{print "   " $4}'
}

case "${1:-}" in

truoc|sau)
  # `${1^^}` là bash 4+; mini chạy bash 3.2 nên phải dùng `tr`.
  anh_chup "ẢNH CHỤP $(echo "$1" | tr "[:lower:]" "[:upper:]")"
  ;;

# --- lấy mẫu trong lúc một job đang chạy -----------------------------------
mau)
  GIAY="${2:-300}"
  echo "### LẤY MẪU ${GIAY}s, nhịp 5s — $(date '+%H:%M:%S')"
  echo "t     rss_MB  tai_MB  dia_con  job_running"
  dia_dau=$(df -k / | tail -1 | awk '{print $4}')
  t=0
  while [ "$t" -lt "$GIAY" ]; do
    pid=$(launchctl list | awk '$3=="com.astronex.videodl"{print $1}')
    rss=$([ -n "${pid:-}" ] && [ "$pid" != "-" ] \
          && ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0f", $1/1024}' || echo "-")
    tai=$(du -sm "$TAI" 2>/dev/null | awk '{print $1}')
    dia=$(df -h / | tail -1 | awk '{print $4}')
    dang=$(sq "SELECT COUNT(*) FROM jobs WHERE trang_thai='running';")
    printf "%-5s %-7s %-7s %-8s %s\n" "${t}s" "${rss:--}" "${tai:--}" "$dia" "${dang:--}"
    sleep 5; t=$((t+5))
  done
  dia_cuoi=$(df -k / | tail -1 | awk '{print $4}')
  echo "-- đĩa toàn máy tụt trong cả lượt: $(( (dia_dau - dia_cuoi) / 1024 )) MB"
  echo
  echo "⚠ ĐỪNG đọc con số đĩa trên thành 'tool ăn đĩa'. Máy này DÙNG CHUNG với"
  echo "  Promax của đội khác. Đo 21/09 lúc thử script: đĩa tụt 185 MB trong 10"
  echo "  giây trong khi cột job_running = 0 suốt — tức tụt do HÀNG XÓM, không"
  echo "  phải do tool. Ngưỡng '<100MB' trong plan cấu tạo KHÔNG phân định được"
  echo "  trên máy dùng chung."
  echo "  Thứ tool THẬT SỰ kiểm soát là cột tai_MB (thư mục tải). Dùng cột đó."
  echo "  Muốn con số đĩa có nghĩa thì phải so hai lượt: một lượt job_running>0"
  echo "  và một lượt job_running=0 cùng độ dài — hiệu số mới là phần của tool."
  echo
  echo "-- NGƯỠNG dùng được: rss < 1536 MB · tai_MB ≤ 50 tại MỌI mẫu"
  ;;

# --- hai người bấm cùng lúc ------------------------------------------------
haiNguoi|hai-nguoi)
  echo "### HAI NGƯỜI BẤM CÙNG LÚC — $(date '+%H:%M:%S')"
  echo
  echo "-- [A] job gần đây, kèm chủ và mốc thời gian:"
  sq "SELECT id||' | '||nguoi_tao||' | '||trang_thai||' | bat_dau='||COALESCE(bat_dau_luc,'-')||' | xong='||COALESCE(xong_luc,'-')
      FROM jobs ORDER BY id DESC LIMIT 8;" | sed 's/^/   /'
  echo
  echo "-- [B] CÓ CẶP NÀO CHỒNG THỜI GIAN KHÔNG? (rỗng = tuần tự, ĐẠT)"
  # Worker một luồng ⇒ hai job không bao giờ được cùng 'running'. Phép này so
  # từng CẶP: A bắt đầu trước khi B xong VÀ B bắt đầu trước khi A xong.
  sq "SELECT a.id||' chồng '||b.id||'  ('||a.bat_dau_luc||'..'||COALESCE(a.xong_luc,'đang chạy')||'  vs  '||b.bat_dau_luc||'..'||COALESCE(b.xong_luc,'đang chạy')||')'
      FROM jobs a JOIN jobs b ON a.id < b.id
      WHERE a.bat_dau_luc IS NOT NULL AND b.bat_dau_luc IS NOT NULL
        AND a.bat_dau_luc < COALESCE(b.xong_luc, '9999')
        AND b.bat_dau_luc < COALESCE(a.xong_luc, '9999');" | sed 's/^/   /'
  echo
  echo "-- [C] ĐỐI CHỨNG: phép [B] có sức phân định không?"
  # Nếu không có đối chứng, một kết quả rỗng cũng có thể nghĩa là câu SQL sai
  # hoặc cột rỗng — chứ không phải 'không chồng'. Đếm job CÓ mốc bắt đầu:
  # rỗng ở [B] chỉ có nghĩa khi số này ≥ 2.
  echo "   job có bat_dau_luc: $(sq "SELECT COUNT(*) FROM jobs WHERE bat_dau_luc IS NOT NULL;")  (cần ≥2 thì [B] mới nói được gì)"
  echo
  echo "-- [D] jar cookie: mỗi người một tệp, tên là sha256(danh tính thô)"
  ls -l "$REPO/web/data/cookies" 2>/dev/null | tail -n +2 | awk '{print "   " $5 " B  " $9}'
  echo "   → hai người bấm ⇒ phải thấy HAI tệp khác tên. Cùng một tệp = jar lẫn."
  echo
  echo "-- [E] log: dòng có giờ, quanh lúc hai job chạy"
  grep -E "^2026-" "$LOG" | tail -20 | sed 's/^/   /'
  ;;

*)
  cat <<'HD'
Dùng:
  truoc          ảnh chụp trước khung nghiệm thu
  mau [giây]     lấy mẫu rss/đĩa/thư mục tải trong lúc job chạy (mặc định 300)
  hai-nguoi      kiểm hai job không chồng thời gian + jar không lẫn
  sau            ảnh chụp sau, so từng dòng với 'truoc'

Mắt người (script KHÔNG đo được, phải có người nhìn):
  1. mở một link "Mở thư mục Drive" từ hàng đợi → thư mục mở ra, có file
  2. Thùng rác Drive → 5 video đã xoá hôm 18/09 có nằm trong đó không
  3. đứng ở project 'aldenesk-01' bấm "Tạo bộ tự tìm" → câu báo lỗi phải
     BẢO ĐỔI PROJECT, không chỉ nói "file không nằm trong Shared Drive"
HD
  ;;
esac
