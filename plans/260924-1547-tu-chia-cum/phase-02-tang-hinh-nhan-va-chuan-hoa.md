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

## Bổ sung trước thi công (26/09 22:2x, lane V) — chờ vòng agy `tuchiacum-p2-plan`

Plan tự chia cụm dừng ở vòng agy `tu-chia-cum-kehoach-R11-TREO` (KHÔNG phải agy KHÉP); ĐP phân xử (a) 24/09 16:33 (`~/agy-ws/DECISIONS.md:3450`), điều kiện: 3 vá R10 thành 3 test đích — 2/3 thuộc phase này (mục B dưới).

### A. Hiện trạng đo trên mini (26/09 22:2x, chỉ đọc)

| job | video còn (chưa loại) | có khung 50/90 | có poster | có usecase |
|---|---|---|---|---|
| 10 | 59 | **0** | 59 | không |
| 15 | 20 | 20 | 20 | không |
| 16 | 175 | 175 | 175 | không |
| 17 | 20 | 20 | 20 | không |
| 4,5,6,8,9 | 0 (đã loại hết) | — | — | — |

- Khung 50/90 chỉ có từ #15 (24/09) ⇒ job 10 CHỈ có poster. Dữ liệu R7/R8 (fixture dương của bước 1) cũng đo trên 59 poster job 10, schema R7 thiếu `so_khung`/`boi_canh`.
- `video_dac_diem` = `(video_id, phien_ban_prompt, nhan_json, tao_luc)`, PK `(video_id, phien_ban_prompt)`; không có cột riêng cho cờ caption.
- `web/nhap_cum_cli.py`, `scripts/phan-tich-hinh.sh`: chưa có.

### B. Hai test đích từ vá R10 (bắt buộc)

1. **Caption qua TỆP:** hàm dựng lệnh agy nhận caption của N video, ghi vào tệp prompt trong scratch, trả argv; test khẳng định KHÔNG chuỗi caption nào (kể cả caption dài 2 000 ký tự) xuất hiện trong argv, và tệp prompt chứa đủ N caption. Đột biến đưa caption vào argv ⇒ ĐỎ.
2. **Cờ caption cache theo `(video_id, phien_ban_prompt)`:** chạy chuẩn hoá hai lần trên cùng lượt (lần 2 đổi trục/chia lại) với agy giả đếm lượt gọi ⇒ lần 2 gọi agy chấm caption **0** lần. Đề xuất lưu cờ caption thành HÀNG RIÊNG trong `video_dac_diem` với `phien_ban_prompt = "caption:<phiên bản prompt caption>"` (không migration) — tách khỏi phiên bản prompt NHÃN, để đổi prompt nhãn/chuẩn hoá không làm mất cache caption. Đột biến dùng chung phiên bản với prompt nhãn ⇒ ĐỎ.

### C. Đề xuất đổi so với bản 24/09 (cần agy phán; D12 là của ĐP)

1. **Nghiệm thu chạy thật:** job 10 CHỈ bằng poster (`so_khung=1`, so với R8 mù cùng dữ liệu) **và** job 17 (20 video, 3 khung) cho đường nhiều khung. KHÔNG chạy job 16 (175 video) ở lượt đầu (quota agy + ảnh rời máy nhiều).
2. **Chế độ mặc định (D12):** vẫn "mọi lượt chưa có nháp", NHƯNG không `--yes` thì chỉ THỬ KHÔ: in danh sách lượt, số video, số lượt gọi agy ước tính rồi dừng. Lý do: với dữ liệu hiện tại "mọi lượt" = 4 job / 274 video.
3. **Khung thiếu:** `so_khung` = số ảnh có thật (1–3); video không có ảnh nào ⇒ KHÔNG gán nhãn, lượt vẫn đi với N−k video, in rõ k id bị bỏ + lý do; phép kiểm "đủ id" so với N−k (tập đã lọc), không phải N (agy R2 — trượt cả lượt vì 1 video thiếu ảnh sẽ kẹt lượt ở `cho_hinh`).
4. **Lọc video vào lượt chia:** bỏ video `da_loai_luc IS NOT NULL` ngay trong script (không đẩy ảnh video đã loại sang agy) — `ghi_de_xuat::loc` vẫn bỏ video đã ở cụm thật (D14). Khi plan dọn video (`~/plans/260926-2110-video-desk-don-video-da-vao-bo/plan.md` §8.2b) lên, plan đó thêm lọc `drive_don_luc` vào CẢ script lẫn `ghi_de_xuat::loc` kèm đột biến — phase này để sẵn một hàm lọc duy nhất để chỗ thêm là một dòng.
5. **Ảnh rời máy (R1):** script từ chối job có nguồn không phải TikTok công khai — kiểm `jobs.url` khớp `https://www.tiktok.com/`; 17/17 job hiện tại khớp tiền tố đó (đo 22:3x, `url LIKE "https://www.tiktok.com/%"`).

## Kết quả chạy thật (27/09, mini `1935ddb`, #23)

| | job 10 | job 17 |
|---|---|---|
| giờ | 08:31 → 08:41 | 08:41 → 08:50 |
| video → vào lượt | 60 → 54 (1 đã loại · 5 đã ở cụm "Mặc vest") | 20 → 20 |
| ảnh | 54 (poster) | 60 (3 khung) |
| lượt agy thật / ước tính | **4 / 4** | **3 / 3** |
| nhãn | 20+20+14, 0 lỗi | 20 trong 1 lượt (62 `view_file`, ~3 phút), 0 lỗi |
| caption | 54 rỗng ⇒ `khong_ro`, 0 chấm | 20 chấm, cả 20 = `false` |
| nháp (`de_xuat`, chưa duyệt) | 5 nhóm / 8 kiểu · 41 kiểu + 9 hướng dẫn + 4 nghi | 2 nhóm / 3 kiểu · 11 kiểu + 6 hướng dẫn + 3 nghi |
| trùng cụm thật | 0 | 0 |

- So R8 mù (6 nhóm / 12 kiểu, cùng 54 poster): 36/54 cùng nhóm tương ứng, 9/9 hướng dẫn khớp; lệch lớn nhất 5 "Trang phục vest" + 5 "Truyền thống" nay vào "Đồng phục".
- Soát transcript agy 7 lượt: mọi đường dẫn và cwd trong scratch; mỗi lượt chỉ ghi tệp kết quả của nó; không lệnh đổi môi trường.
- Thấy khi chạy thật, ĐƯA SANG phase 3+4 (không sửa nóng): (a) tên NHÓM không ổn định giữa lượt — cùng kiểu có sẵn "Mặc vest" ra nhóm "Âu phục" (job 10) và "Áo vest" (job 17), vì tên có sẵn chỉ ghim mức kiểu; (b) thành công chỉ dọn `anh/`, còn giữ prompt + kết quả trong `$TMPDIR/phan-tich-hinh-*` (64K, 612K) — không có ghi chú giữ là cố ý.
