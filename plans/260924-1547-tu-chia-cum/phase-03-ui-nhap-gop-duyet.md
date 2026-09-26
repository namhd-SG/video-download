---
phase: 3
title: "UI nháp: nhóm/kiểu, gộp, đổi tên inline, duyệt tất cả"
status: pending
priority: P1
effort: "1d"
dependencies: [1, 2]
---

# Phase 3: UI nháp (ship CÙNG phase 4 — một PR)

## Overview
Dựng màn nháp đúng mock `~/plans/260924-1031-tu-chia-cum-video-desk/mock-tu-chia-cum-v1.html` (poster thật, trạng thái đề xuất/đã duyệt/chưa phân tích hình/gộp vào cụm có sẵn), dùng route phase 1.

## Requirements
- Functional:
  - Thẻ lượt tải: tiêu đề đếm ĐÚNG thứ đang hiện ("N nhóm · M kiểu + làn riêng …"), chip trạng thái, ô usecase/insight gốc, "Chia theo" (đổi trục ⇒ yêu cầu chia lại), "Duyệt tất cả còn lại", "Chia lại", bộ đếm thao tác sửa.
  - Nhóm gập → kiểu → lưới thumb ĐẦY ĐỦ (không lấy mẫu); badge "ghép N".
  - Thao tác: gộp cả nhóm thành 1 cụm · gộp vào cụm có sẵn (popover liệt cụm cùng insight gốc) · đổi tên inline (thay `window.prompt` — ít nhất ở màn nháp) · tách (chọn video → kiểu mới) · xoá kiểu · chuyển video.
  - Nút "Tạo bộ tự tìm" của kiểu nháp: `disabled` + title nói lý do; chỉ bật sau duyệt (nó thành cụm #13 thật).
  - "Chưa phân tích hình": KHÔNG liệt nhóm nào, chỉ "Chưa vào cụm N" + dòng lệnh máy dev in sẵn, copy được (`bash scripts/phan-tich-hinh.sh --luot <id>`). **KHÔNG nút** "Chạy phân tích hình ngay" — mock v1 có nút đó, ĐP bỏ (D12).
- Non-functional: token màu/font của app.css; sáng/tối; 390 px không tràn ngang; một video một chỗ.

## Related Code Files
- Create: `web/static/chia-cum.js` (tách khỏi `app.js` 1 600 dòng), `tests/test_chia_cum_browser.py`, `tests/js/chia-cum-dem.js`
- Modify: `web/static/index.html`, `web/static/app.css`, `web/static/app.js` (điểm vào)

## Implementation Steps
1. Render từ `GET /chia/{job_id}`; mọi thao tác gọi `POST /chia/{id}/thao-tac` rồi vẽ lại từ server (không giữ trạng thái song song ở client).
2. Test trình duyệt (Playwright, mẫu `test_library_pagination_browser.py`): đếm DOM khớp tiêu đề · 0 video trùng · nút "Tạo bộ" của nháp disabled · trạng thái chưa-hình 0 nhóm.
3. Chụp PNG 6 trạng thái như mock; **lane tự mở từng ảnh** trước khi báo (cửa 1b), gửi đường dẫn PNG.

## Success Criteria
- [ ] Ảnh thật khớp mock (cùng bố cục, token, trạng thái); ĐP mở ảnh duyệt.
- [ ] Đột biến: bật nút "Tạo bộ" cho nháp ⇒ test ĐỎ; bỏ lọc trùng video ⇒ test ĐỎ.

## Risk Assessment
- `renderFilterBar` dựng lại trong sự kiện `change` làm Playwright `check()` treo (nợ cũ) ⇒ test dùng `click`.
- Đổi trục = chia lại (tốn một lượt agy) ⇒ hỏi xác nhận nếu đã có thao tác sửa (mất nhật ký của lượt cũ? — KHÔNG: lượt cũ `huy`, nhật ký giữ).
