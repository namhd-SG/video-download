---
phase: 2
title: "Tầng hình: nhãn vision + chuẩn hoá 2 tầng (máy dev) → ghi nháp qua ssh"
status: pending
priority: P1
effort: "1d"
dependencies: [1, 5]
---

# Phase 2: Tầng hình

## Overview
Script chạy trên MÁY DEV (không 24/7): kéo poster + khung 50/90 % của một job từ mini, gọi agy vision gán nhãn, chuẩn hoá theo lượt thành 2 tầng nhóm→kiểu, rồi ghi nháp về mini qua ssh + một lệnh CLI dùng chung `models_chia` (không đi HTTP: route mini sau Cloudflare Access JWT).

## Requirements
- Functional:
  - `scripts/phan-tich-hinh.sh` (máy dev): mặc định xử MỌI lượt tải chưa có nháp (job `done`, chưa có `chia_lan` ở `de_xuat`/`da_duyet`); `--luot <job_id>` để chọn một lượt (D12 — không có nút UI, không hàng đợi).
  - Bước 1 — nhãn: schema cố định `{video_id, so_khung, the_chu, trang_phuc_dam_dong, trang_phuc_nguoi_chinh, boi_canh}` (định nghĩa `the_chu` = "dòng chữ TIÊU ĐỀ lớn đè lên" — bản đã đo 12/12 ở R7). Cache `video_dac_diem` theo `phien_ban_prompt`.
  - Bước 2b — lệch chủ đề theo caption: prompt chuẩn hoá nhận thêm `description` (#15) + chuỗi nguồn của job, trả `caption_lech_chu_de ∈ {true, false, khong_ro}` cho từng video (caption rỗng ⇒ `khong_ro`). Mini chỉ LƯU cờ, không suy luận. Caption đi vào agy bằng TỆP trong scratch (không qua argv — luật agy: argv cắt prompt lớn). Cờ cache trong `video_dac_diem` theo `(video_id, phien_ban_prompt)` ⇒ "chia lại"/đổi trục KHÔNG chấm lại caption.
  - Bước 2 — chuẩn hoá theo lượt: 2 tầng, tên ≤3 từ, không nêu màu trừ khi màu là thứ duy nhất phân biệt; `the_chu` ⇒ làn `huong_dan`; không đám đông / "Khác" ⇒ làn `nghi` (phase 4 hiển thị). Đưa `cum.kieu` user đã duyệt trong cùng `insight_goc` vào prompt làm "tên ưu tiên nếu khớp" (từ vựng, không huấn luyện).
  - `python -m web.nhap_cum_cli ghi <job_id> <tệp.json>` trên mini: kiểm schema, ghi `ghi_de_xuat`.
  - `python -m web.nhap_cum_cli ten-co-san <job_id>` trên mini: in JSON các `cum.kieu` đã duyệt của người tạo job, cùng `usecase`+`insight_goc` của job (phase 5) — nạp vào prompt chuẩn hoá làm "tên ưu tiên nếu khớp". Job chưa có insight gốc (user Q4: không bắt buộc) ⇒ gợi ý = MỌI `cum.kieu` user đã duyệt, không lọc theo insight (in rõ "không lọc theo insight"). Chưa có cụm nào ⇒ rỗng.
- Non-functional:
  - agy: `--model gemini-3.7-flash-low` (làn vision) cho nhãn, `gemini-3.8-flash-high` cho chuẩn hoá (cơ học); **nghiệm thu bằng tệp đích + đếm**, không bằng rc; lệnh cấm đổi toolchain/env trong prompt.
  - Kiểm máy được, TRƯỚC khi ghi mini: đủ N id = số video của job · mỗi id một lần · mọi kiểu thuộc đúng một nhóm · 0 nhãn ngoài danh sách. Trượt ⇒ không ghi gì, in số.
  - Không chạy model nào trên mini.

## Architecture
```
máy dev: phan-tich-hinh.sh
  ssh mini: liệt video của job + tar poster/khung ──► scratch
  ssh mini: python -m web.nhap_cum_cli ten-co-san <job> ──► ten-co-san.json
  agy vision (nhãn)  ──► nhan.jsonl   ── kiểm 59/59 ──┐
  agy (chuẩn hoá + ten-co-san.json) ──► chia.json ── kiểm 2 tầng ─┤
  ssh mini: python -m web.nhap_cum_cli ghi <job> ◄────┘
mini: models_chia.ghi_de_xuat ──► chia_lan(de_xuat) + cum_nhap + video_cum_nhap
```

## Related Code Files
- Create: `scripts/phan-tich-hinh.sh`, `scripts/tu-chia-cum/prompt-nhan.txt`, `scripts/tu-chia-cum/prompt-chuan-hoa.txt`, `scripts/tu-chia-cum/kiem-ket-qua.py`, `web/nhap_cum_cli.py`, `tests/test_nhap_cum_cli.py`, `tests/test_kiem_ket_qua.py`
- Modify: `web/models_chia.py` (nếu cần hàm đọc cho CLI)

## Implementation Steps
1. `kiem-ket-qua.py` + test trên đúng tệp R7/R8 thật (`~/agy-ws/exchange/tu-chia-cum-R7-data-*`, `R8-data-agy-2tang-mu.json`) làm fixture dương; fixture âm: thiếu id, trùng id, kiểu lạc nhóm.
2. `nhap_cum_cli.py` + test (DB tạm).
3. `phan-tich-hinh.sh`: ssh/tar, gọi agy, kiểm, ghi; in số ở mọi bước; mã thoát riêng cho "đo hỏng" vs "kết quả không đạt".
4. Chạy thật trên job 10 (59 video) ⇒ nháp ghi vào mini (trạng thái `de_xuat`, CHƯA duyệt, không đụng cụm "Mặc vest" có sẵn).

## Success Criteria
- [ ] Job 10: nháp trên mini có 59 video, 0 trùng; so với lượt mù R8 (6 nhóm/12 kiểu, 5 vest cùng nhóm) — báo lệch, không ép khớp.
- [ ] Đột biến: bỏ phép kiểm "đủ id" ⇒ test âm ĐỎ.
- [ ] Log agy (`transcript_full.jsonl`) soát: chỉ đọc đúng thư mục scratch, không lệnh đổi môi trường.

## Risk Assessment
- agy quota/503 (đã gặp 24/09) ⇒ rơi tầng theo luật; vế chuẩn hoá rơi dưới flash-high thì ghi nhãn tầng vào `phien_ban_prompt`.
- Ảnh rời máy sang Google: chỉ video TikTok công khai (ranh giới R1). Job nào nguồn không phải TikTok công khai ⇒ script từ chối.
- ssh chết giữa chừng ⇒ ghi nháp là một transaction trên mini, không nửa vời.
