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
- [ ] Lượt 1 (job 10): làn Hướng dẫn 9, làn nghi 4; lượt 2 (job 17): 6 / 3 — khớp nháp thật trên mini (đo 27/09), không theo mock (12/3).
- [ ] Đột biến: cho caption gỡ nghi ⇒ test ĐỎ.
- [ ] Luật "cờ caption `true` ⇒ nghi": CHƯA ĐO được trên dữ liệu thật (0 video `true` ở cả hai lượt) — nghiệm thu CHỈ bằng test + đột biến; báo cáo phải ghi rõ nhãn này.

## Risk Assessment
- Âm tính giả (video lạc nằm trong kiểu 15 video) là lỗ im lặng thật ⇒ chữa bằng lưới thumb đầy đủ ở phase 3, không bằng ngưỡng.

## Bổ sung trước thi công (27/09 09:0x, lane V) — chờ vòng agy `tuchiacum-p34-plan`

- **Bước 1 (phân làn) ĐÃ LÀM ở phase 2**, nhưng khác chỗ: thẻ chữ ⇒ `huong_dan` quyết ở MÁY DEV (`phan_tich_hinh.py:186-187`, theo nhãn `the_chu`), `nghi` do agy chuẩn hoá trả `{"lan":"nghi"}`; `ghi_de_xuat` chỉ nhận danh sách. Không có kiểu "Khác" — prompt chuẩn hoá cho ra `nghi` trực tiếp.
- **Bước 3 (cờ caption ⇒ làn nghi) CHƯA LÀM:** cờ `caption_lech_chu_de` được chấm và lưu (`video_dac_diem`, hàng `caption:<v>`) nhưng không chỗ nào đọc cờ để đưa video vào `nghi` (grep `caption` trong `models_chia.py`: chỉ một docstring). Dữ liệu thật: job 10 = 54 `khong_ro`, job 17 = 20 `false` ⇒ **0 video `true`**, nên luật này chưa đổi được nháp nào đang có. Đề xuất đặt luật ở MÁY DEV (cùng chỗ `huong_dan`): `true` và video đang ở kiểu ⇒ chuyển sang `nghi` trước khi ghi, lý do lưu trong nhật ký/nháp; không bao giờ rút video khỏi `nghi`. Cần chốt: lý do "caption lệch chủ đề" lưu ở đâu (nháp chưa có cột lý do theo video).
- **Tiêu chí "Job 10: làn Hướng dẫn 12, làn nghi 3" đã lệch với nhãn mới:** đo 27/09 = hướng dẫn **9**, nghi **4** (54 video, không phải 59 như mock, vì 5 video đã ở cụm + 1 đã loại). Sửa tiêu chí thành "khớp nháp thật đang có trên mini", không theo mock.
