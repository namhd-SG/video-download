---
phase: 4
title: "Làn thẻ chữ + làn nghi ngoài chủ đề"
status: pending
priority: P2
effort: "0.5d"
dependencies: [1, 2]   # ship cùng PR với phase 3
---

# Phase 4: Làn thẻ chữ + làn nghi ngoài chủ đề

## Overview
Hai làn riêng của màn nháp: "Hướng dẫn / thẻ chữ" (user Q3: thành kiểu riêng "Hướng dẫn") và "Nghi ngoài chủ đề" (không xoá, không ẩn, không bao giờ vào bộ).

## Requirements
- Functional:
  - Làn Hướng dẫn: mặc định đề xuất thành kiểu "Hướng dẫn" (duyệt được như kiểu thường); nút "Đánh dấu ngoài chủ đề".
  - Làn nghi: ứng viên = kiểu "Khác" ∪ không có đám đông. Nút "Đúng, bỏ khỏi lượt" (`ngoai_chu_de`, video KHÔNG vào cụm nào; không đụng `da_loai_luc` của thư viện) · "Không, trả về kiểu…" (`tra_ve`).
  - Caption (`description`, #15) chỉ được TĂNG nghi: caption không chứa từ khoá nguồn KHÔNG gỡ nghi; caption rỗng = "không có bằng chứng", không phải "không khớp" (kongming Q3).
- Non-functional: video ở làn nghi không bao giờ có trong payload bàn giao (cấu tạo: nó không có hàng `video_cum`).

## Related Code Files
- Modify: `web/static/chia-cum.js`, `web/models_chia.py`, `scripts/tu-chia-cum/kiem-ket-qua.py`
- Create: test làn trong `tests/test_models_chia.py`, `tests/test_chia_cum_browser.py`

## Implementation Steps
1. Phân làn ở `ghi_de_xuat` từ nhãn (`the_chu`, không đám đông, "Khác").
2. Thao tác `ngoai_chu_de`/`tra_ve` + nhật ký.
3. Tín hiệu caption = cờ `caption_lech_chu_de` do phase 2 (máy dev) trả; `ghi_de_xuat` chỉ đọc cờ: `true` ⇒ đưa vào làn nghi (lý do "caption lệch chủ đề"); `false`/`khong_ro` ⇒ KHÔNG rút video khỏi làn nghi. Không suy luận ngữ nghĩa trên mini.

## Success Criteria
- [ ] Job 10: làn Hướng dẫn 12, làn nghi 3 (khớp mock) — hoặc báo lệch với nhãn mới.
- [ ] Đột biến: cho caption gỡ nghi ⇒ test ĐỎ.

## Risk Assessment
- Âm tính giả (video lạc nằm trong kiểu 15 video) là lỗ im lặng thật ⇒ chữa bằng lưới thumb đầy đủ ở phase 3, không bằng ngưỡng.
