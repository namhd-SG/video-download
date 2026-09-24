---
phase: 5
title: "Ô usecase/insight gốc lúc tạo job"
status: pending
priority: P1   # thi công ngay sau phase 1 — phase 2 đọc insight_goc
effort: "0.5d"
dependencies: [1]
---

# Phase 5: Ô usecase/insight gốc lúc tạo job

## Overview
User Q4: hỏi usecase + insight gốc lúc tạo lượt tải, KHÔNG bắt buộc; bỏ trống thì hỏi lúc duyệt nháp (phase 3 đã có ô).

## Requirements
- Functional: form "Tạo lượt tải mới" thêm 2 ô tuỳ chọn; lưu vào `jobs` (2 cột đã có từ phase 1); màn nháp điền sẵn; duyệt khi còn trống ⇒ đòi điền (400 có câu rõ).
- Non-functional: cùng luật chuẩn hoá/độ dài của `models_cum.kiem_nhan` (80/120 ký tự); không đổi `POST /jobs` với client cũ (hai trường tuỳ chọn).

## Related Code Files
- Modify: `web/models.py`, `web/app.py` (`POST /jobs`), `web/static/index.html`, `web/static/app.js`
- Create: test trong `tests/test_web_app.py`

## Implementation Steps
1. Pydantic tuỳ chọn + kiểm bằng `kiem_nhan` (cột đã tạo ở phase 1).
2. UI form + điền sẵn màn nháp.
3. Test: bỏ trống vẫn tạo job · điền sai độ dài ⇒ 400 · duyệt nháp trống insight ⇒ 400.

## Success Criteria
- [ ] Test xanh; client cũ (không gửi 2 trường) vẫn tạo job.

## Risk Assessment
- Gợi ý tên từ taxonomy Creative Desk (datalist) cần đọc taxonomy prod — NGOÀI phạm vi phase này; ghi nợ nếu user cần.
