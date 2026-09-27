#!/usr/bin/env bash
# Tầng hình tự chia cụm — chạy trên MÁY DEV (không phải mini), người dùng bấm tay.
#
#     scripts/phan-tich-hinh.sh                    # thử khô: mọi lượt tải chưa có nháp
#     scripts/phan-tich-hinh.sh --luot 10          # thử khô: một lượt
#     scripts/phan-tich-hinh.sh --luot 10 --yes    # làm thật: kéo ảnh, gọi agy, ghi nháp
#     scripts/phan-tich-hinh.sh --luot 10 --mini-db /đường/jobs.db   # DB cục bộ, không ssh
#
# Không có --yes thì KHÔNG kéo ảnh, KHÔNG gọi agy, KHÔNG ghi gì — chỉ in kế
# hoạch (lượt, số video, k video không có ảnh + id, số lượt gọi agy ước tính).
#
# Mã thoát: 0 xong · 2 sai cú pháp · 3 ĐO HỎNG (chưa biết kết quả) ·
# 4 KẾT QUẢ KHÔNG ĐẠT phép kiểm (không ghi gì) · 5 TỪ CHỐI (nguồn không phải
# TikTok công khai / nháp đang có sửa tay).
#
# Mọi logic nằm ở tu-chia-cum/phan_tich_hinh.py (test được); tệp này chỉ chọn
# python và chuyển tham số. Ghi đè: PYTHON, AGY_BIN, SSH_BIN, VIDEODL_MINI_HOST (cùng tên với
# deploy/rollback-on-mini.sh), VIDEODL_MINI_REPO.
set -uo pipefail
DAY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$DAY/tu-chia-cum/phan_tich_hinh.py" "$@"
