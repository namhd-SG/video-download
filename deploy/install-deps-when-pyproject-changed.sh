# Thư viện cho deploy-to-mini.sh: cài lại phụ thuộc Python trên mini khi `pyproject.toml` đổi.
#
# Vì sao: rsync chỉ đẩy MÃ. Deploy b2984a7 (18/11) thêm `patchright` vào pyproject nhưng venv prod
# không có gói đó ⇒ bật VIDEODL_PATCHRIGHT=1 sẽ âm thầm lùi về Playwright (trinh_duyet_patchright.py
# chỉ log cảnh báo). ĐP phải `pip install` tay. Bước này làm việc đó trong chuyến deploy, TRƯỚC
# kickstart, để tiến trình mới khởi động trên venv đã đủ gói.
#
# Lệnh cài giống `mini-setup.sh` bước 4 (`pip install -e .[web,thay-logo]`): pip KHÔNG nâng gói đã
# thoả ràng buộc, nên gói đang ghim tay (vd playwright 1.64.0) giữ nguyên.

# cai_phu_thuoc_neu_pyproject_doi <mã đọc mốc 0|6> <mốc> <HEAD> <host> <repo> <làm thật 0|1>
# Chạy từ gốc repo trên máy dev. Trả:
#   0  không đổi / đã cài xong / thử khô
#   9  lệnh cài trên mini trượt (chưa kickstart — tiến trình cũ vẫn chạy)
#   5  mã đọc mốc lạ (PHÉP ĐO HỎNG) — người gọi đã lọc, đây là lưới cuối
cai_phu_thuoc_neu_pyproject_doi() {
  local moc_rc="$1" moc="$2" sha="$3" host="$4" repo="$5" that="$6" diff_rc=0
  case "$moc_rc" in
    0)
      git diff --quiet "$moc" "$sha" -- pyproject.toml 2>/dev/null || diff_rc=$?
      case "$diff_rc" in
        0) echo "   pyproject.toml không đổi từ mốc ${moc:0:7} — không cài"; return 0 ;;
        1) echo "   pyproject.toml ĐỔI từ mốc ${moc:0:7} ⇒ cần cài lại phụ thuộc" ;;
        # Không so được (mốc không có trong repo dev): KHÔNG kết luận "không đổi" — cài cho chắc.
        *) echo "   ⚠ không so được pyproject.toml với mốc ${moc:0:7} (git rc=$diff_rc) — CHƯA PHÂN ĐỊNH ⇒ cài" >&2 ;;
      esac ;;
    6) echo "   ⚠ chưa có mốc .deployed-sha — không biết pyproject.toml có đổi không ⇒ cài" >&2 ;;
    *) echo "   ⚠ mã đọc mốc lạ ($moc_rc) — PHÉP ĐO HỎNG, không cài" >&2; return 5 ;;
  esac
  local lenh="cd ~/$repo && .venv/bin/pip install -q -e '.[web,thay-logo]'"
  if [ "$that" -ne 1 ]; then
    echo "   (thử khô) lần thật sẽ chạy trên $host: $lenh"
    return 0
  fi
  ssh "$host" "$lenh" || return 9
  echo "   đã cài phụ thuộc trên $host"
}
