# Pha 4 — Nghiệm thu trên 2 video mẫu

## Chuẩn bị
- Video 1: `~/Downloads/video test.mp4` (collage 7 pose).
- Video 2 (khác trend): tải 1 video catwalk AI 1 người bằng `yt-dlp --impersonate chrome` (đề xuất `@harry_gunawan999/video/7619141013801667861` từ GĐ1) vào scratchpad. ĐP/user đổi được.

## Đo
| # | Lệnh | Đạt khi |
|---|---|---|
| 1 | chạy công cụ trên video 1, mặc định | đối chứng dương = 3; link giữ ≥70% có ≥3 bản sao cùng người, nền trơn — **kiểm mắt toàn bộ link giữ**, ghi bảng |
| 2 | chạy trên video 2 | đối chứng dương = 3; link giữ ≥60% 1 người catwalk; **0** link collage |
| 3 | `pytest tests/test_tim_trend_*.py` + toàn suite | xanh; không đỏ thêm so với `061417c` |
| 4 | 2 đột biến (pha 1) | đỏ |
| 5 | đếm lượt gọi TikTok/agy trong `ket-qua.json` | ≤ trần đặt |

Sai số đã biết, ghi kèm: chấm theo ảnh bìa giây 0; IP VN; trend sống ngắn.

## Sau nghiệm thu
- Báo ĐP kèm bảng + ảnh chụp trang (ĐP tự mở ảnh).
- Có thước người ⇒ đổi mặc định `--nguong` theo số đo (1 commit riêng).
- Cổng merge repo này (ĐP 22/10, tiền lệ #97–#100; repo KHÔNG có gate.sh): toàn suite pytest xanh trên ĐÚNG head PR + code-reviewer độc lập do ĐP gọi + agy KHÉP + mục "ca nào main đúng mà nhánh sai" trong PR ⇒ ĐP gật ⇒ `gh pr merge --merge --match-head-commit <sha>`.
