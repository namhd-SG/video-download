# shellcheck shell=bash
# Nghiệm thu "thứ rsync vừa đẩy có thật sự nằm trên máy đích không" — MỌI tệp,
# lấy danh sách từ chính output `--itemize-changes` của lần rsync đó.
#
# Vì sao tách tệp: `deploy-to-mini.sh` chạy thẳng tới ssh/rsync/kickstart nên
# không test được; hàm ở đây chỉ cần `ssh`, và test thay `ssh` bằng một bản giả
# chạy lệnh trên một thư mục cục bộ.
#
# Vì sao tồn tại: vòng nghiệm thu cũ so sha của đúng BA tên cứng (index.html,
# app.js, app.css). Deploy ngày 23/09 chỉ đổi `settings.js` — thứ vòng đó CẤU
# TẠO KHÔNG THỂ nhìn — và script vẫn in "khớp" ba lần. Phải so tay qua curl mới
# biết tệp đã lên. Danh sách lấy từ rsync thì không có tệp nào lọt ngoài vòng.
#
# Định dạng itemize đo trên openrsync (máy dev lẫn mini, protocol 29):
#   `<f+++++++ đường/dẫn`  tệp gửi đi (đẩy lên máy xa)
#   `>f.s..... đường/dẫn`  tệp nhận (chép cục bộ — chấp nhận luôn, cùng nghĩa)
#   `*deleting đường/dẫn`  tệp bị xoá ở đích
#   `cd+++++++ thư/mục/`   thư mục — bỏ qua
# Đường dẫn có thể chứa dấu cách: chỉ bóc TRƯỜNG ĐẦU, giữ nguyên phần còn lại.

# kiem_tep_da_dong_bo <tệp itemize> <host> <repo tương đối với ~ trên đích>
# In một dòng mỗi tệp. Trả:
#   0 — mọi tệp gửi đi khớp sha, mọi tệp xoá đã vắng
#   4 — có tệp lệch hoặc tệp xoá vẫn còn (nghiệm thu trượt)
#   5 — không đọc được sha trên đích (phép đo hỏng — KHÁC "lệch")
kiem_tep_da_dong_bo() {
  local log="$1" host="$2" repo="$3"
  local gui=() xoa=() line
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '<f'*|'>f'*) gui+=("${line#* }") ;;
      '*deleting '*) xoa+=("${line#\*deleting }") ;;
    esac
  done < "$log"

  echo "   rsync đã gửi ${#gui[@]} tệp, xoá ${#xoa[@]} tệp"

  local lech=0 f
  if [ "${#gui[@]}" -gt 0 ]; then
    # MỘT lượt ssh cho cả danh sách. `printf %q` giữ nguyên dấu cách trong tên.
    local tu_xa
    tu_xa="$(ssh "$host" "cd ~/$repo && for f in $(printf '%q ' "${gui[@]}"); do
               if [ -f \"\$f\" ]; then shasum -a 256 \"\$f\" | cut -d' ' -f1; else echo VANG; fi
             done")" || {
      echo "DỪNG: không đọc được sha trên máy đích — PHÉP ĐO HỎNG, không phải lệch." >&2
      return 5
    }
    # Rỗng hẳn: `<<< ""` vẫn sinh MỘT dòng, nên với đúng 1 tệp thì phép đếm dòng
    # bên dưới khớp và ca này thành "LỆCH" (4) thay vì "đo hỏng" (5).
    if [ -z "$tu_xa" ]; then
      echo "DỪNG: đích không trả dòng nào cho ${#gui[@]} tệp — PHÉP ĐO HỎNG." >&2
      return 5
    fi
    local i=0 sha_xa sha_dev
    while IFS= read -r sha_xa; do
      f="${gui[$i]}"
      sha_dev="$(shasum -a 256 "$f" | cut -d' ' -f1)"
      if [ "$sha_xa" = "$sha_dev" ]; then
        echo "   khớp  $f"
      else
        echo "   LỆCH  $f (dev=${sha_dev:0:12} đích=${sha_xa:0:12})" >&2
        lech=1
      fi
      i=$((i + 1))
    done <<< "$tu_xa"
    # Số dòng trả về phải bằng số tệp. Thiếu dòng = lệnh xa chết giữa chừng;
    # không bắt thì các tệp cuối danh sách được coi như chưa từng hỏi.
    if [ "$i" -ne "${#gui[@]}" ]; then
      echo "DỪNG: hỏi ${#gui[@]} tệp, đích trả $i dòng — PHÉP ĐO HỎNG." >&2
      return 5
    fi
  fi

  # `${xoa[@]+…}`: bash 3.2 của macOS coi mảng RỖNG là "unbound" dưới `set -u`,
  # mà script deploy chạy `set -euo pipefail` — không có dòng này thì MỌI chuyến
  # không xoá tệp nào chết ngay sau rsync (đo 23/09: rc=1, "xoa[@]: unbound").
  local r
  for f in ${xoa[@]+"${xoa[@]}"}; do
    # Ba kết cục, không phải hai: `test -e` trả 0 (còn) hoặc 1 (vắng), còn ssh
    # chết trả 255. Gộp 255 vào "vắng" là xanh giả đúng lúc mạng rớt — bản đầu
    # làm đúng thế, reviewer bắt 23/09.
    r=0
    ssh "$host" "test -e ~/$repo/$(printf '%q' "$f")" || r=$?
    case "$r" in
      0) echo "   CÒN   $f (rsync báo đã xoá)" >&2; lech=1 ;;
      1) echo "   vắng  $f" ;;
      *) echo "DỪNG: hỏi \"$f còn không\" mà ssh trả $r — PHÉP ĐO HỎNG." >&2
         return 5 ;;
    esac
  done

  [ "$lech" -eq 0 ] || return 4
  return 0
}

# liet_mo_coi <đích rsync> [cờ exclude…]
# Tệp CÓ ở đích mà KHÔNG có ở nguồn (trừ tệp bị loại trừ) — thứ `--delete` lẽ
# ra đã xoá. Vì sao cần: rsync thật ở bước 3 chạy kèm `--backup-dir`, và openrsync
# BỎ QUA `--delete` khi có cờ đó (đo 23/09 trên mini) ⇒ bước 3 luôn khai "xoá 0
# tệp" dù đích có tệp thừa. Lượt này chạy `--dry-run --delete` KHÔNG
# `--backup-dir`: chỉ đọc, nên nó nói ĐÚNG những gì một lần xoá thật sẽ chạm.
# Chỉ CẢNH BÁO, không chặn: mã mới đã lên; tệp thừa không làm hỏng tệp mới.
# Trả 0 khi đo được (kể cả khi có mồ côi), 5 khi rsync trượt — "không đo được"
# không được in thành "0 mồ côi".
liet_mo_coi() {
  local dich="$1"; shift
  local ra
  ra="$(rsync -a --dry-run --itemize-changes --delete "$@" ./ "$dich")" || {
    echo "   ⚠ không đo được tệp mồ côi ở đích (rsync trượt) — CHƯA KẾT LUẬN" >&2
    return 5
  }
  local mo_coi
  # `sort -u`: openrsync in `*deleting` HAI LẦN cho cùng một mục (đo 23/09, cả
  # thư mục cục bộ lẫn lên mini) — đếm thẳng là nhân đôi số mồ côi.
  mo_coi="$(printf '%s\n' "$ra" | grep '^\*deleting ' | sed 's/^\*deleting //' | sort -u || true)"
  if [ -z "$mo_coi" ]; then
    echo "   mồ côi ở đích: 0 tệp"
    return 0
  fi
  echo "   ⚠ mồ côi ở đích: $(printf '%s\n' "$mo_coi" | wc -l | tr -d ' ') mục — có ở mini, không có ở commit này" >&2
  printf '%s\n' "$mo_coi" | head -20 | sed 's/^/      /' >&2
  echo "      (rsync kèm --backup-dir không xoá chúng; dọn tay nếu đúng là rác)" >&2
  return 0
}
