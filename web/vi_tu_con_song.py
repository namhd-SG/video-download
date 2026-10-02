"""Vị từ SQL "video còn sống" — MỘT nơi duy nhất viết chúng.

Mọi câu SQL trên `videos` (bí danh `v`) hỏi "video này còn trong thư viện không"
phải dùng các hằng ở đây, KHÔNG tự viết lại `da_loai_luc IS NULL`. Trước đây
điều kiện đó lặp ở ~11 chỗ; thêm một cách video biến khỏi thư viện (tệp nguồn đã
dọn khỏi Drive) mà quên một chỗ là một video "bốc hơi" ở màn này mà còn ở màn
khác. `tests/test_vi_tu_con_song.py` quét mã nguồn: còn `da_loai_luc IS [NOT]
NULL` nào ngoài tệp này là ĐỎ.

Ba khái niệm khác nhau, cố ý KHÔNG gộp:
  * `CHUA_LOAI`        — người dùng chưa bỏ video (`da_loai_luc`). Dùng riêng cho
                         cách cắt lô của cụm (`models_chia._video_trong_lo`): ranh
                         giới lô phải ổn định khi một video được dọn khỏi Drive.
  * `CON_SONG_CHUNG`   — chưa loại VÀ chưa dọn khỏi Drive (`video_vao_bo.
                         drive_don_luc`). Là "video còn ở thư viện" cho lưới,
                         đếm, gán cụm, gửi Creative Desk.
  * `CHUA_AN`          — chưa bị ẩn vì đã vào bộ (`video_vao_bo.an_luc`). Hai
                         nơi dùng: lượt CHIA (video đã vào bộ tự tìm không vào
                         một lượt chia mới) và chip "Đã vào bộ" của lưới
                         (`models.list_videos`/`count_videos`, `vao_bo=0|1`) —
                         lọc ở server để video ẩn không chiếm suất nạp của lưới.
"""
from __future__ import annotations

CHUA_LOAI = "v.da_loai_luc IS NULL"

_DA_DON = ("EXISTS (SELECT 1 FROM video_vao_bo b_don "
           "WHERE b_don.video_id = v.video_id AND b_don.drive_don_luc IS NOT NULL)")

# Dạng khẳng định — để đánh dấu item đã dọn (không gửi sang Creative Desk).
DA_DON_DRIVE = _DA_DON
CHUA_DON_DRIVE = f"NOT {_DA_DON}"

CHUA_AN = ("NOT EXISTS (SELECT 1 FROM video_vao_bo b_an "
           "WHERE b_an.video_id = v.video_id AND b_an.an_luc IS NOT NULL)")

CON_SONG_CHUNG = f"{CHUA_LOAI} AND {CHUA_DON_DRIVE}"
