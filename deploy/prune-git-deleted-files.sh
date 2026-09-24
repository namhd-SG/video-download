# shellcheck shell=bash
# Gỡ khỏi mini những tệp đã XOÁ KHỎI GIT kể từ lần deploy trước.
#
# Vì sao tồn tại: rsync ở bước 3 của `deploy-to-mini.sh` chạy kèm `--backup-dir`,
# và openrsync (protocol 29, máy dev lẫn mini) BỎ QUA `--delete` khi có cờ đó —
# đo 23/09. Nên tệp xoá khỏi repo cứ nằm lại trên mini mãi, và `liet_mo_coi` chỉ
# cảnh báo được. Bỏ `--backup-dir` thì xoá được nhưng mất đường lui.
#
# Cách làm: mini giữ `.deployed-sha` = commit của lần deploy nghiệm thu xong gần
# nhất. Danh sách cần gỡ = GIAO của hai tập:
#   (a) `git diff --no-renames --diff-filter=D <mốc> <HEAD>` — tệp git nói đã xoá;
#   (b) mồ côi ở đích theo `rsync --dry-run --delete` CÙNG cờ exclude với deploy.
# Chỉ (a) thì gỡ nhầm thứ mini cấp riêng: `assets/ffmpeg-static/ffmpeg` có trong
# git nhưng bị loại khỏi rsync, mini-setup.sh chép nó bằng scp — xoá nó khỏi git
# không có nghĩa mini hết cần nó. Chỉ (b) thì gỡ cả thứ git chưa từng biết (tệp
# sinh trên mini, không nằm trong exclude) — đó là việc của người, không của máy.
# Mồ côi ngoài (a) vẫn được `liet_mo_coi` cảnh báo như cũ, không ai đụng.
#
# `--no-renames` BẮT BUỘC: mặc định git gộp xoá+thêm thành R, và `--diff-filter=D`
# khi đó bỏ sót đúng tệp cũ của một lần đổi tên — ca phổ biến nhất.
#
# Gỡ = `mv` vào thư mục bản lui của CHÍNH chuyến này, không `rm`: `rollback-on-
# mini.sh` chép ngược thư mục đó đè lên repo, nên lui là tệp quay về.
#
# Giới hạn đã biết: tên tệp chứa ký tự xuống dòng không được hỗ trợ.

# doc_moc_da_deploy <host> <repo tương đối với ~>
# In sha của mốc ra stdout. Trả:
#   0 — đọc được một sha 40 ký tự hex
#   6 — mini CHƯA CÓ mốc (lần đầu dùng cơ chế này) — CHƯA PHÂN ĐỊNH, không phải "0 tệp"
#   5 — ssh trượt hoặc nội dung mốc không phải sha — PHÉP ĐO HỎNG
doc_moc_da_deploy() {
  local host="$1" repo="$2" ra
  ra="$(ssh "$host" "if [ -f ~/$repo/.deployed-sha ]; then cat ~/$repo/.deployed-sha; else echo CHUA_CO_MOC; fi")" || return 5
  ra="$(printf '%s' "$ra" | tr -d '[:space:]')"
  [ "$ra" = "CHUA_CO_MOC" ] && return 6
  case "$ra" in
    *[!0-9a-f]*|'') return 5 ;;
  esac
  [ "${#ra}" -eq 40 ] || return 5
  printf '%s\n' "$ra"
}

# ghi_moc_da_deploy <host> <repo> <sha>
# Ghi qua tệp tạm + mv (không để mốc nửa chừng), rồi ĐỌC LẠI để so. Trả 0 khi
# đọc lại đúng sha, 5 khi không. Chỉ được gọi SAU khi nghiệm thu đã qua: mốc nói
# "mini đang chạy đúng commit này", ghi trước nghiệm thu là khẳng định chưa đo.
ghi_moc_da_deploy() {
  local host="$1" repo="$2" sha="$3" doc_lai
  ssh "$host" "printf '%s\n' $sha > ~/$repo/.deployed-sha.tmp && mv ~/$repo/.deployed-sha.tmp ~/$repo/.deployed-sha" || return 5
  doc_lai="$(doc_moc_da_deploy "$host" "$repo")" || return 5
  [ "$doc_lai" = "$sha" ] || return 5
  echo "   mốc .deployed-sha = $sha (đã đọc lại)"
}

# don_tep_xoa_theo_git <mốc> <HEAD> <đích rsync> <host> <repo> <bản lui> <làm thật 0|1> [cờ exclude…]
# Chạy từ gốc repo trên máy dev. In SỐ ĐẾM ở mọi nhánh. Trả:
#   0 — không còn tệp nào cần gỡ nằm trên đích (đo lại sau khi gỡ, hoặc thử khô)
#   4 — đã gỡ mà đo lại vẫn còn tệp (gỡ trượt)
#   5 — không đo được (git/rsync/ssh trượt) — CHƯA KẾT LUẬN, không phải "0 tệp"
don_tep_xoa_theo_git() {
  local moc="$1" head="$2" dich="$3" host="$4" repo="$5" ban_lui="$6" that="$7"
  shift 7

  if ! git cat-file -e "$moc^{commit}" 2>/dev/null; then
    echo "   ⚠ mốc $moc không có trong repo máy dev — không tính được tệp xoá (CHƯA KẾT LUẬN). Thử 'git fetch'." >&2
    return 5
  fi

  # (a) tệp git nói đã xoá. `-z` + `core.quotePath=false`: giữ nguyên dấu cách
  # và chữ có dấu, không để git bọc tên trong ngoặc kép kèm mã bát phân.
  local git_xoa
  git_xoa="$(git -c core.quotePath=false diff --no-renames --name-only --diff-filter=D -z "$moc" "$head" | tr '\0' '\n')" || {
    echo "   ⚠ git diff trượt — CHƯA KẾT LUẬN" >&2
    return 5
  }
  local n_git=0
  [ -n "$git_xoa" ] && n_git="$(printf '%s\n' "$git_xoa" | wc -l | tr -d ' ')"
  echo "   tệp xoá khỏi git từ ${moc:0:7} tới ${head:0:7}: $n_git"
  if [ "$n_git" -eq 0 ]; then
    echo "   cần gỡ trên đích: 0 · đã gỡ: 0 · còn lại: 0"
    return 0
  fi

  # (b) mồ côi ở đích, cùng cờ exclude với lần deploy. `sort -u`: openrsync có
  # lúc in `*deleting` hai lần cho cùng mục (đo 23/09).
  # `LC_ALL=en_US.UTF-8` BẮT BUỘC: ngoài locale UTF-8 (cron, `env -i`, ssh
  # không mang LANG) openrsync in `ấ` thành `\#341\#272\#245` — đo 24/09 — và
  # tên có dấu trượt khỏi phép giao, im lặng nằm lại trên đích.
  local ra mo_coi
  ra="$(LC_ALL=en_US.UTF-8 rsync -a --dry-run --itemize-changes --delete "$@" ./ "$dich")" || {
    echo "   ⚠ rsync thử khô trượt — không biết đích còn gì (CHƯA KẾT LUẬN)" >&2
    return 5
  }
  mo_coi="$(printf '%s\n' "$ra" | grep '^\*deleting ' | sed 's/^\*deleting //' | sort -u || true)"

  local can_go="" f n_can=0 n_ngoai=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if printf '%s\n' "$mo_coi" | grep -Fxq -- "$f"; then
      can_go="$can_go$f"$'\n'
      n_can=$((n_can + 1))
    else
      n_ngoai=$((n_ngoai + 1))
    fi
  done <<< "$git_xoa"
  # Ngoài giao = đã vắng trên đích, HOẶC bị exclude (vd assets/ffmpeg-static).
  # Cả hai đều là "không đụng", nên gộp số — nhưng in ra, không nuốt.
  echo "   cần gỡ trên đích: $n_can · bỏ qua (đã vắng hoặc bị loại trừ khỏi rsync): $n_ngoai"
  if [ "$n_can" -eq 0 ]; then
    echo "   đã gỡ: 0 · còn lại: 0"
    return 0
  fi
  printf '%s' "$can_go" | sed 's/^/      - /'

  if [ "$that" -ne 1 ]; then
    echo "   (thử khô — chưa gỡ tệp nào)"
    return 0
  fi

  # MỘT lượt ssh để gỡ. `printf %q` giữ dấu cách/chữ có dấu qua shell phía xa.
  local ds_q
  ds_q="$(printf '%s' "$can_go" | while IFS= read -r f; do printf '%q ' "$f"; done)"
  local da_go
  da_go="$(ssh "$host" "cd ~/$repo && n=0 && for f in $ds_q; do
             mkdir -p \"$ban_lui/\$(dirname \"\$f\")\" && mv \"\$f\" \"$ban_lui/\$f\" && n=\$((n+1))
           done; echo \$n")" || {
    echo "   ⚠ ssh trượt khi gỡ — không biết đã gỡ bao nhiêu (CHƯA KẾT LUẬN)" >&2
    return 5
  }
  echo "   đã gỡ (mv vào ${ban_lui#../}): ${da_go:-?}"

  # Đo lại PHÍA ĐÍCH, độc lập với lời khai của vòng mv ở trên: số "đã gỡ" là
  # vòng lặp tự đếm, còn thứ cần biết là tệp có thật sự vắng không.
  local con_lai
  con_lai="$(ssh "$host" "cd ~/$repo && n=0 && for f in $ds_q; do [ -e \"\$f\" ] && n=\$((n+1)); done; echo \$n")" || {
    echo "   ⚠ ssh trượt khi đo lại — CHƯA KẾT LUẬN" >&2
    return 5
  }
  case "$con_lai" in ''|*[!0-9]*)
    echo "   ⚠ đo lại trả '$con_lai' — CHƯA KẾT LUẬN" >&2
    return 5 ;;
  esac
  echo "   còn lại trên đích (đo lại): $con_lai / $n_can"
  [ "$con_lai" -eq 0 ] || return 4
  return 0
}
