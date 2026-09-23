# Bàn giao — lane V (tkgiang), Video Desk, 23/09 15:05

**Lane** `0460ddfc` (tkgiang, pid 17794, ttys001) · **điều phối** lane R `uds:/tmp/cc-socks/20916.sock` · chữ tin `V`, số cuối **V158**
**Repo** `~/Projects/video-download` · `main` = `42dfcf8` = **mini** (deploy 15:02, 38/38 sha khớp)

> ⏱ Số đo 23/09 10:20 → 15:05. Đọc lúc khác thì mini/job/đĩa phải đo lại.
> Thay thế ghi chú trong `handoff-260923-0950-*` cho các mục nó chạm; phần còn lại của file đó vẫn đúng.

## 1. Đã LIVE trên mini hôm nay (mỗi dòng có cặp control sha trước/sau)

| PR | merge | việc |
|---|---|---|
| #6 | `40f5293` | ô dán cookie xoá ở MỌI nhánh (cookie hỏng không còn nằm trên màn hình) |
| #8 | `de42807` | bỏ video chia lô ≤50 — sửa 422 "Không bỏ được" (user chọn >50). **User nghiệm thu mắt ĐẠT** 14:29 |
| #9 | `d50e089` | rsync loại tệp git-ignore + ghim `*.egg-info/` (mini CẦN nó); đã `rm` tay `.claude/agent-memory` + `.pytest_cache` trên mini |
| #10 | `cd2c3d9` | thẻ cookie theo nền tảng (bước 1/3 brainstorm): khối trạng thái, "Không đọc được hạn", phản hồi dán ngay dưới nút |
| #7 | `9b54883` | script deploy: so sha MỌI tệp rsync gửi · mã thoát 1-5 đúng nghĩa · ssh chết = "đo hỏng" · liệt mồ côi · cổng label không xanh giả |
| #11 | `1d1fb81` | test script deploy đi QUA bước 4-5 (cổng healthz); `cc=`/`bind=` không thoát im lặng |
| #12 | `42dfcf8` | thư viện: "Chọn tất cả trang này" + phân trang 10/20/40/100 (mặc định 40), nút trang trên + dưới |

Đường lui chuyến cuối: `bash deploy/rollback-on-mini.sh ../video-download-truoc-260923-150204`.

## 2. Treo — CHỜ USER (đừng tự làm)

- **UI cookie bước 3 (đọc @username)** — USER CHỐT Q4=C 10:33 (đọc kè ở trang liệt kê music/search/profile), chấp nhận hashtag không có tên + tên lưu trên máy chung (10:54). **Phép đo (i′) user "bỏ qua", (ii) "chưa làm" (14:29)** ⇒ treo. Script đo sẵn: `plans/260923-1023-cookie-ui/do-truong-nguoi-xem.py` (nhánh `docs/cookie-ui-brainstorm` `838eb4e`, chưa PR). FE đã sẵn câu chữ; ô "Tài khoản" tự hiện khi backend trả khoá `tai_khoan`.
- **Mắt user**: thẻ cookie (dán hỏng khi đang có cookie tốt ⇒ "Cookie cũ vẫn đang dùng") · phân trang (86 video ⇒ 40/40/6).

## 3. Nợ đã ghi (không làm hôm nay)

- `.deployed-sha` + `git diff --diff-filter=D` để dọn tệp xoá khỏi git: openrsync + `--backup-dir` **không xoá** (đo trên mini) ⇒ tệp xoá sẽ nằm lại; `liet_mo_coi` cảnh báo mỗi chuyến.
- `renderFilterBar` dựng lại thanh lọc NGAY TRONG sự kiện `change` ⇒ Playwright `check()` treo (test dùng `click`). Nợ UI, không sửa hôm nay (điều phối).
- Parser itemize gắn openrsync; rsync 3.x chưa đo. Tên tệp non-ASCII ⇒ LỆCH giả (hỏng ồn).

## 4. Bẫy đã trả giá — đọc trước khi đụng

- **Merge PR bị classifier chặn** ⇒ hỏi user bằng `AskUserQuestion` trong pane này. Duyệt của điều phối là THÔNG TIN, không phải quyền.
- **Deploy từ nhánh tách trước PR khác sẽ LÙI PR đó** (thấy ở #7 tách trước #10). Merge `main` vào nhánh trước; nghiệm thu bằng cờ `.s` trong thử khô.
- **Checkout gốc dùng chung**: tệp untracked của lane khác làm cổng "cây sạch" chặn ⇒ nhờ chủ dời, KHÔNG xoá/commit hộ. Worktree sạch làm thử khô khác xa (gửi lại mọi tệp, liệt `*deleting` egg-info).
- **Jar hỏng/hết hạn ⇒ job DỪNG** (`queue.py:408-418`), không chạy ẩn danh.
- **openrsync in `*deleting` HAI LẦN** cho cùng mục ⇒ `sort -u`.
- Hook chặn chuỗi `.git` và `__pycache__` trong lệnh Bash ⇒ lọc phía dev.
- `autotest` (đội khác) thuộc nhóm `staff`, `~nobi_auto` = 750 ⇒ đọc được mọi thứ 755 trong repo mini.

## 5. Kiểm khi nhận (lane mới trả SỐ)

`git -C ~/Projects/video-download rev-parse --short origin/main` (= `42dfcf8`) · `status --porcelain` = 0 ·
`ssh nobi_auto@100.109.39.103 'curl -s http://127.0.0.1:7870/app.js | shasum -a 256 | cut -c1-12'` (= `3e4b7c88`) ·
`.venv/bin/python -m pytest -q` (= 401 passed, cần node + Chromium của Playwright).
