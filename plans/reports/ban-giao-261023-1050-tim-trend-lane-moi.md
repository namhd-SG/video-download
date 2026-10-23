# Bàn giao lane TikTok → lane mới · 23/10/2026 ~10:50 (tk3)

Nhánh `feat/tim-video-cung-trend` · worktree `~/Projects/video-download-wt-tim-trend` · venv `.venv` (playwright **1.62.0**, ĐỪNG nâng — 1.64 cần chromium-1248 chưa có). **Chưa push.**
Chạy test luôn kèm `PYTHONPYCACHEPREFIX=<thư mục mới>` (bẫy .pyc cũ khi chạy đột biến — xem nhật ký 23/10). Hook chặn lệnh có chữ `__pycache__`.

## Commit (cũ → mới)
c3cad36 plan GĐ2 · 5b9db72 Pha 0 · 36b3275 lõi · 25b30a1 nối ngoài · 07e4195 luồng+CLI+trang · ea6a66b captcha/0 ứng viên · 8a7fad7 bàn giao đêm · 1ad126d profile bền + chờ giải captcha · da21a6f từ dừng hop 2 + tiến độ · f77824d plan GĐ3 nháp · **06ece5c** sửa review 1 + lazy-load ảnh bìa · **b94ae0a** ctrl khớp chữ ký + `--truy-van` + review 2 · **c36643c** lưu DOM trang thường (chẩn đoán).

## Trạng thái đo
- Pha 4 ĐẠT: video 1 (collage 7 pose) 36/38 = 95% · video 2 (catwalk) 32/41 = 78%, 0 collage — dùng `--profile-ben ~/.tim-trend-chrome`, 0 captcha. Ghi chép: scratchpad `pha4b-v1/`, `pha4b-v2/` (`kiem-mat.md`).
- Toàn suite: 06ece5c ⇒ `3091 passed, 1 skipped, 1 warning in 569.96s`. b94ae0a: (điền khi xong — log `scratchpad/full-suite4.log`).
- Ca 3 (`~/Downloads/Download.mp4`, kiss cam Coldplay, 2 cảnh): lượt A cũ LOẠI. A'/B chạy trên c36643c, `--hop 1 --tran-luot 6`, A' key agy vs B key hồ sơ trend (`--truy-van`). Kết quả: scratchpad `ca3-A2/`, `ca3-B/` (điền số).

## Việc treo (theo thứ tự)
1. **Sửa review vòng 3 (ĐP chuyển 10:4x)** — commit riêng: HIGH `khung.py:37` ghi file đánh dấu vào cả `khung/` có sẵn của user ⇒ chỉ đánh dấu khi thư mục mới/rỗng (hoặc đổi tên `khung-tim-trend/`), test chạy 2 lần với trich_khung thật (ffmpeg giả) · M11 fixture luong tự ghi đánh dấu ⇒ bỏ dòng trong khung.py vẫn xanh · M12 thêm mã 6 vào test_ma_thoat · M3 tutorial 1 cảnh (cả 3 khung 2A) ⇒ thông điệp riêng, không khuyên "cắt cảnh" · M4 dọn ket-qua.json + index.html cũ đầu lượt · LOW: `--truy-van` bỏ trùng + báo khi cắt; docstring test_cli; tên ctrl ngẫu nhiên lẫn ảnh bìa (chấm mù thật).
2. Sau sửa: toàn suite trên đúng head ⇒ báo ĐP dòng cuối ⇒ ĐP soát ⇒ cổng merge (suite + code-reviewer + agy KHÉP + mục "main đúng nhánh sai" trong PR) ⇒ ĐP gật ⇒ `gh pr merge --merge --match-head-commit <sha>`.
3. PR ghi: hoãn HashtagTim/nhac.py; đột biến tương đương "lưới sau bản sao"; các giới hạn đã biết (IP VN, ảnh bìa giây 0, AI vs người thật chưa phân biệt).
4. Sổ know-how `~/plans/kien-thuc/knowhow-tim-video-tuong-tu.md` (agy R1b KHÉP đã sửa) — còn: thêm số Ca 3 A'/B, mục 7 + plan GĐ3 (`~/plans/kien-thuc/nhap-plan-gd3-vong-tu-cai-thien.md`, "là AI" là ca đầu) ⇒ agy R2 ⇒ bản HTML cho user ⇒ báo ĐP.
5. **YouTube Shorts (ĐP duyệt 10:5x)**: SAU A'/B, trên ca 3, nhịp người, ≤10 truy vấn, đo % đúng dạng như TikTok; dùng yt-dlp trong venv (kiểm `which` trước), không cài toàn cục. Exa: chờ user (API key). Endpoint nội bộ TikTok (OpenCLI): KHÔNG dùng.
6. agent-reach: xong (`~/plans/reports/research-261023-agent-reach-hoc-hoi.md`), đã báo ĐP; đề xuất doctor/dự phòng/cooldown cho GĐ3.

## Câu chờ user (qua ĐP)
- Ca 3 nhiều cảnh: tìm bản kết quả hay bản hướng dẫn? (nếu cả hướng dẫn ⇒ cổng ctrl phải nhận "2A").

## Ràng buộc đang áp
Không vượt captcha/Cloudflare, không giả vân tay, không proxy xoay · creative nội bộ/dữ liệu khách KHÔNG gửi agy · báo ĐP 1 câu trước mỗi lần mở Chrome thật khi user ngồi máy · `git add <đường dẫn>` cụ thể, không `-A`, không stash · không đụng checkout chính (lane Logo).
