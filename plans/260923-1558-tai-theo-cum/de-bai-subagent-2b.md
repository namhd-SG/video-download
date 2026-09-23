# Đề bài subagent — 2b "Tải theo CỤM → sub-insight", phía Video Desk

Giao bởi lane V (tkgiang) 23/09. **Làm TRONG WORKTREE** `/Users/macos/Projects/video-download-wt-cum`, nhánh `feat/library-clusters`
(đã tạo từ `origin/main` = `42dfcf8`). KHÔNG đụng checkout gốc `/Users/macos/Projects/video-download`.
Python: `/Users/macos/Projects/video-download/.venv/bin/python`, chạy TỪ worktree với `PYTHONPATH=$PWD/src:$PWD`
(⚠ bản cài editable `tiktok_music_downloader` trỏ về `src/` của checkout gốc; không sửa `src/` trong việc này).
Node có sẵn. Playwright + Chromium có sẵn trong venv.

**CHIA 2 LƯỢT.** Lượt 1 = schema + model + API + test pytest (KHÔNG UI). Lượt 2 = UI theo mock + test trình duyệt + ảnh.
Mỗi lượt kết thúc bằng commit + báo cáo theo khuôn cuối tệp.

## Đọc TRƯỚC (đường dẫn tuyệt đối)
1. Hợp đồng payload (THẨM QUYỀN, không đổi): `plans/260923-1558-tai-theo-cum/hop-dong-nhan.md` (trong worktree). Phía nhận (lane Y) đã nhận đủ 8 quy tắc.
2. Mock v2 (HTML — mở bằng Playwright rồi chụp để xem): `/Users/macos/plans/260923-1103-tai-theo-cum-sub-insight/mock-tai-theo-cum-v2.html`
   Ảnh: `/Users/macos/plans/260923-1103-tai-theo-cum-sub-insight/mock-v2/{nhieu-cum-sang,nhieu-cum-toi,chua-co-cum-sang,dien-thoai-nhieu-cum}.png`
   ⚠ PNG (14:53) có thể CŨ hơn HTML (14:56): tên cụm theo HTML + hợp đồng (`"<insight gốc> <kiểu>"`, vd "Badaboum couple", hiển thị "Dance › Badaboum couple"), KHÔNG lặp usecase.
3. Brainstorm §3A (schema/API/UI/mốc "đã gửi"): `/Users/macos/plans/260923-1103-tai-theo-cum-sub-insight/brainstorm.md` dòng 77-104.
4. Code hiện có: `web/models.py` (`_SCHEMA*`, `init_db`, `_add_column_if_missing` dòng 143, `video_de_loai` dòng 699 — mẫu lọc quyền sở hữu trong SQL), `web/app.py` (route `/videos`, `/videos/loai`), `web/static/app.js` (`moBoTuTim` = bàn giao hôm nay; phân trang PR #12: `catTrang`, `vePhanTrang`, `state.idTrang`), `web/static/index.html`, `web/static/app.css`.
5. Test mẫu: `tests/test_library_pagination_browser.py` (trình duyệt thật, `/videos` giả qua `page.route`), `tests/js/loai-theo-lo.js` (harness node trích hàm thật).

## Làm
- **Schema** (SQLite, `web/models.py`, qua `init_db` — idempotent như bảng hiện có): `cum(id INTEGER PK, chu TEXT NOT NULL, usecase TEXT NOT NULL, insight_goc TEXT NOT NULL, kieu TEXT NOT NULL, tao_luc TEXT NOT NULL)` và `video_cum(video_id TEXT NOT NULL, chu TEXT NOT NULL, cum_id INTEGER NOT NULL REFERENCES cum(id) ON DELETE CASCADE, PRIMARY KEY(video_id, chu))` ⇒ 1 video 1 cụm MỖI NGƯỜI. Mốc "đã mở" theo LÔ: `cum_lo_mo(cum_id, thu, mo_luc, PRIMARY KEY(cum_id, thu))` (mock v2 hiện mốc riêng từng "Bộ i/n"). Tên insight con = `insight_goc + " " + kieu` (trim + gộp khoảng trắng) — MỘT hàm, dùng chung cho hiển thị và payload.
- **API** (`web/app.py`, mọi route `Depends(require_user)`, lọc theo `chu` TRONG SQL): `GET /cum` (kèm số video), `POST /cum` (tạo), `PATCH /cum/{id}` (đổi kiểu), `DELETE /cum/{id}`, `POST /cum/{id}/video` `{video_ids, bo?:bool}` gán/gỡ (id không phải của mình ⇒ bỏ, trả số), `POST /cum/{id}/lo/{thu}/da-mo` ghi mốc. `/videos` trả thêm `cum_id`.
- **UI** theo mock v2: sidebar "Cụm của tôi" (Tất cả · Chưa vào cụm · nhóm theo insight gốc, số đếm, "+ Cụm mới") · đầu cụm (chip Usecase/Insight/Template Goc 🔒, "Đổi kiểu", "Tạo bộ tự tìm từ cụm này (N)" hoặc "Tạo k bộ tự tìm (30+30+…)" với danh sách "Bộ i/n · x video · đã mở lúc… / chưa mở · Mở Creative Desk / Mở lại") · chip cụm trên thẻ · thanh chọn thêm "Đưa vào cụm ▾" (popover: insight gốc + usecase + kiểu ⇒ xem trước tên con). Sống CÙNG phân trang #12 (lọc theo cụm là một bộ lọc nữa ⇒ về trang 1).
- **Bàn giao**: nút lô ⇒ `window.open` payload đúng hợp đồng (`nhan` + `lo`). Mốc `da-mo` CHỈ ghi SAU khi `window.open` trả tab khác null. Câu chữ "đã mở Creative Desk lúc …", KHÔNG "đã tạo". Bàn giao từ lựa chọn tay (nút cũ) KHÔNG có `nhan`.
- Cụm > 30 ⇒ lô 30/30/…/dư (hàm thuần, test được).

## Test (bắt buộc) + đột biến (phải ĐỎ, có control không đột biến)
- Hàm thuần qua node: tách lô (64 ⇒ 30/30/4; 30 ⇒ 1 lô; 0 ⇒ 0 lô) · tên con · dựng payload (có cụm ⇒ có `nhan` đủ khoá; tay ⇒ không `nhan`).
- Model/API qua pytest: gán video vào cụm B khi đã ở cụm A ⇒ chuyển (không nằm 2 cụm) · người khác không thấy/không gán được cụm của mình · xoá cụm ⇒ video về "chưa vào cụm".
- Trình duyệt thật (khuôn `test_library_pagination_browser.py`): tạo cụm, đưa 3 video vào, sidebar đếm đúng, nút lô mở tab với URL giải mã ra đúng `nhan` (bắt `page.context.expect_page` hoặc stub `window.open`), mốc "đã mở" hiện sau khi mở.
- Đột biến: video vào 2 cụm ⇒ ĐỎ · >30 không tách ⇒ ĐỎ · payload thiếu `nhan` khi bàn giao từ cụm ⇒ ĐỎ · ghi mốc TRƯỚC `window.open` (khi popup bị chặn vẫn ghi) ⇒ ĐỎ. Mỗi đột biến ghi test nào đỏ + dòng `E`.
- Toàn suite phải xanh (`.venv/bin/python -m pytest -q`; nền hiện 401 passed).
- **Ảnh code THẬT** (không chèn DOM): sáng/tối/điện thoại 390px, dữ liệu giả ~86 video + 3-5 cụm (1 cụm >30), lưu `plans/260923-1558-tai-theo-cum/sau-thi-cong/*.png` + script chụp chạy lại được. TRẢ VỀ đường dẫn tuyệt đối từng ảnh.

## Cấm
`git add -A` / `git add .` · `git stash` · lệnh git ghi ở checkout gốc · `push --force` · `git push` (lane V tự push) · deploy · đụng `~/meta-ads-automation` (chỉ ĐỌC) · đụng DB trên mini · đổi hợp đồng payload (thấy cần đổi ⇒ DỪNG, báo).
Commit bằng `git add <đường dẫn cụ thể>`; kiểm `git diff --cached --name-only` trước mỗi commit; conventional commit, không nhắc AI.
Không bịa số: mọi "đã chạy/đã kiểm" phải kèm lệnh + output.

## Trả về (khuôn)
```
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
Summary: 1-2 câu
Commits: <sha — tiêu đề> (git log --oneline origin/main..HEAD)
Test: <N passed> + đột biến (bảng: đột biến · test đỏ · dòng E)
Ảnh: <đường dẫn tuyệt đối> (lượt 2)
Worktree: <git status --porcelain>  (phải rỗng sau commit)
NHẸ ĐI: <…> | "đã soát, không có"
Concerns: lệch mock/hợp đồng, chỗ không làm được
```
