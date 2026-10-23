#!/bin/bash
# Bộ đề hồi quy thay logo — chạy từ máy dev, đo trên ca-n (40 video Test3 + box agy cố định), so với lượt MỐC (bản prod).
#
#   scripts/bo-de-thay-logo.sh <sha> [KEY=VAL ...]        một lệnh: gửi mã → chạy 40 video → chờ → so với mốc → kéo báo cáo về
#   scripts/bo-de-thay-logo.sh chay <sha> [KEY=VAL ...]   chỉ khởi động lượt (nền trên ca-n), in tên lượt
#   scripts/bo-de-thay-logo.sh cho <lượt>                 chờ lượt xong (đếm kq.json)
#   scripts/bo-de-thay-logo.sh dung <lượt>                dừng lượt (giết cả nhóm tiến trình, kiểm 0 python còn sống)
#   scripts/bo-de-thay-logo.sh so <lượt mốc> <lượt nhánh> [--soi <soi.json trên ca-n>]
#
# Mốc mặc định: lượt `$BO_DE_MOC` (mặc định 061417c — bản deploy ca-n 22/10). Mã thoát = mã của bước so (scripts/bo_de_thay_logo.py):
# 0 đề xuất lên · 1 vi phạm · 2 chờ soi / chưa sửa ca lỗi · 3 lượt hỏng. Lỗi của chính script này (ssh, mã thiếu…) ⇒ 4.
# Tốn ~70 phút/lượt (2 luồng, cổng tài nguyên chờ Creative Tracker). Không deploy, không đụng thư mục prod trên ca-n.
set -euo pipefail
CA_N=mktmini@100.101.112.88
K=/Users/mktmini/kho-ca/thay-logo
PY=/Users/mktmini/Projects/video-download/.venv/bin/python
GOC=$(cd "$(dirname "$0")/.." && pwd)
MOC=${BO_DE_MOC:-061417c}
BAO_CAO="$GOC/plans/reports/bo-de-thay-logo"
loi() { echo "bo-de: $*" >&2; exit 4; }
r() { ssh -o ConnectTimeout=15 "$CA_N" "/bin/bash -c $(printf '%q' "$1")"; }

ten_luot() {  # <sha7> [KEY=VAL ...] → sha7 hoặc sha7__KEY=VAL__... (ký tự lạ ⇒ _)
  local t="$1"; shift
  for kv in "$@"; do t="${t}__${kv}"; done
  printf '%s' "$t" | tr -c 'A-Za-z0-9_.=-' '_'
}

gui_cong_cu() {  # chép script + nhãn lên ca-n qua tệp tạm rồi mv (không ghi đè script bash đang chạy)
  r "mkdir -p $K/cong-cu/scripts $K/cong-cu/tests/kho_ca/thay_logo $K/ra $K/ma"
  for f in scripts/bo_de_thay_logo.py scripts/bo_de_thay_logo_anh_soi.py scripts/bo-de-thay-logo-mot-video.sh scripts/bo-de-thay-logo-luot.sh \
           tests/kho_ca/thay_logo/bo_de.json tests/kho_ca/thay_logo/khung_vang.json; do
    scp -q "$GOC/$f" "$CA_N:$K/cong-cu/$f.moi" && r "mv $K/cong-cu/$f.moi $K/cong-cu/$f"
  done
}

chuan_bi_video() {  # liên kết cứng 40 video + box từ thư mục đo cũ (đọc, không sửa) — chỉ lần đầu
  r "[ -d $K/v ] || { for d in /Users/mktmini/do-dkb-261021/v/*/; do n=\$(basename \$d); mkdir -p $K/v/\$n; ln \$d/goc.mp4 \$d/boxes-agymoi.json $K/v/\$n/; done; }; ls $K/v | wc -l | tr -d ' '"
}

gui_ma() {  # <sha đầy đủ> → $K/ma/<sha7>/src bằng git archive (không cần repo trên ca-n)
  local sha="$1" s7="${1:0:7}"
  if r "[ -f $K/ma/$s7/.xong ]"; then return; fi
  git -C "$GOC" archive "$sha" src | ssh "$CA_N" "/bin/bash -c 'rm -rf $K/ma/$s7 && mkdir -p $K/ma/$s7 && tar -x -C $K/ma/$s7 && echo $sha > $K/ma/$s7/.xong'"
}

chay() {
  local sha s7 luot env_dong
  sha=$(git -C "$GOC" rev-parse --verify "$1^{commit}") || loi "không có commit $1"; shift
  s7=${sha:0:7}; luot=$(ten_luot "$s7" "$@")
  gui_cong_cu
  [ "$(chuan_bi_video)" = 40 ] || loi "ca-n không đủ 40 video ở $K/v"
  gui_ma "$sha"
  env_dong=$(printf '%s\n' "$@")
  r "mkdir -p $K/ra/$luot && echo $s7 > $K/ra/$luot/sha && printf '%s' $(printf '%q' "$env_dong") > $K/ra/$luot/env"
  # KHÔNG `cd … && nohup … &`: `&` áp cho cả danh sách ⇒ subshell giữ stdout của ssh ⇒ ssh treo tới khi lượt xong (đã dẫm 23/10).
  r "nohup /bin/bash $K/cong-cu/scripts/bo-de-thay-logo-luot.sh $luot > /dev/null 2>&1 < /dev/null &"
  echo "$luot"
}

cho() {
  local luot="$1" n
  while ! r "[ -f $K/ra/$luot/xong ]"; do
    n=$(r "ls $K/ra/$luot/*/kq.json 2>/dev/null | wc -l | tr -d ' '")
    if ! r "pgrep -f '[b]o-de-thay-logo-luot.sh $luot' >/dev/null"; then loi "lượt $luot dừng ở $n/40 mà chưa xong — xem $K/ra/$luot/luot.log"; fi
    echo "$(date +%T) $luot: $n/40" >&2; sleep 300
  done
}

dung() {  # dừng lượt theo NHÓM tiến trình: kill bash cha không giết python con (đã dẫm 23/10: python mồ côi ppid 1 chạy tiếp)
  r "g=\$(pgrep -f '[b]o-de-thay-logo-luot.sh $1\$' | head -1); [ -n \"\$g\" ] && kill -TERM -- -\$(ps -o pgid= -p \$g | tr -d ' '); sleep 5
     ps ax -o command | grep -e '[c]hay_mot_video' | grep -e 'kho-ca/thay-logo/ra/$1/' | grep -v grep | wc -l | tr -d ' '" \
    | { read -r con; [ "$con" = 0 ] || loi "còn $con tiến trình python của lượt $1"; echo "đã dừng $1" >&2; }
}

so() {  # <mốc> <nhánh> [--soi <tệp soi ĐÃ ĐIỀN trên máy dev>]
  local moc="$1" nhanh="$2"; shift 2
  local soi="" rc=0 ra="$K/so/${moc}__vs__${nhanh}" dich
  dich="$BAO_CAO/$(basename "$ra")"
  if [ "${1:-}" = --soi ]; then  # tệp người điền nằm trên máy dev ⇒ đẩy lên ca-n; thiếu thì dừng, không lặng lẽ bỏ qua
    [ -f "${2:-}" ] || loi "không có tệp soi ${2:-}"
    r "mkdir -p $ra"; scp -q "$2" "$CA_N:$ra/soi-nguoi.json" || loi "không đẩy được tệp soi"
    soi="--soi $ra/soi-nguoi.json"
  fi
  r "$PY -I $K/cong-cu/scripts/bo_de_thay_logo.py so $K/ra/$moc $K/ra/$nhanh $soi --ra $ra" || rc=$?
  # Có mẫu soi (vế c) mà chưa có kết quả người ⇒ dựng ảnh toàn khung + soi-mau.json để người điền
  if [ "$rc" = 2 ] && [ -z "$soi" ] && r "grep -q '\"frame\"' $ra/mau-soi.json"; then
    r "$PY -I $K/cong-cu/scripts/bo_de_thay_logo_anh_soi.py $ra $K/v" || loi "không dựng được ảnh soi"
  fi
  # Kéo về KHÔNG đè tệp người đang điền dở (soi-mau.json đã có ở máy dev thì giữ bản máy dev)
  mkdir -p "$dich"
  rsync -a $( [ -f "$dich/soi-mau.json" ] && echo "--exclude soi-mau.json" ) "$CA_N:$ra/" "$dich/" || loi "không kéo được báo cáo $ra"
  echo "báo cáo: $dich/bao-cao.md (rc $rc)" >&2
  return "$rc"
}

case "${1:-}" in
  chay) shift; chay "$@" ;;
  cho) cho "$2" ;;
  dung) dung "$2" ;;
  so) shift; so "$@" ;;
  ""|-h|--help) sed -n '2,13p' "$0"; exit 0 ;;
  *) luot=$(chay "$@"); cho "$luot"; so "$MOC" "$luot" ;;
esac
