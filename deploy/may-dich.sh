# Máy đích của deploy / lui — MỘT chỗ duy nhất ghi cứng địa chỉ máy (bảng dưới).
# `source` từ deploy-to-mini.sh và rollback-on-mini.sh; `scripts/tu-chia-cum/phan_tich_hinh.py`
# đọc cùng bảng này (đừng chép địa chỉ sang chỗ khác).
#
# Chọn máy:   VIDEODL_MAY_DICH=<tên trong bảng>        (mặc định: cu)
# Ghi đè:     VIDEODL_MINI_HOST=<user@host>  VIDEODL_MINI_EXPECT_HOST=<hostname chuẩn hoá>
#
# Vì sao EXPECT_HOST đi cùng máy: cổng `hostname` ở bước 0 của deploy/lui là thứ chặn
# rsync nhầm máy. Ghi đè riêng HOST mà giữ EXPECT_HOST của máy cũ thì cổng sẽ DỪNG
# (đúng ý) — muốn trỏ máy khác phải khai cả hai, hoặc thêm một hàng vào bảng.
# Hàng cho máy mới chỉ thêm khi đã đo được user dịch vụ + `hostname` thật của nó.

case "${VIDEODL_MAY_DICH:-cu}" in
  # EXPECT_HOST là `hostname` đã chuẩn hoá: chữ thường, bỏ đuôi `.local`.
  cu) _may_host="nobi_auto@100.109.39.103"; _may_expect="autos-mac-mini" ;;
  *)
    echo "DỪNG: VIDEODL_MAY_DICH='${VIDEODL_MAY_DICH}' không có trong bảng máy đích (deploy/may-dich.sh)." >&2
    exit 1 ;;
esac
HOST="${VIDEODL_MINI_HOST:-$_may_host}"
EXPECT_HOST="${VIDEODL_MINI_EXPECT_HOST:-$_may_expect}"
unset _may_host _may_expect
