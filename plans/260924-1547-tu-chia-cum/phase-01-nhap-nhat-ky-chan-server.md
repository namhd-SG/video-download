---
phase: 1
title: "Bảng nháp + nhật ký + đường duyệt duy nhất"
status: pending
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Bảng nháp + nhật ký + đường duyệt duy nhất

## Overview
Nền dữ liệu cho mọi phase sau: nháp chia cụm sống ở bảng RIÊNG (không phải `cum`), một đường duyệt duy nhất biến nháp thành cụm thật bằng hàm #13 đã có, và nhật ký mọi thao tác sửa. Chưa có UI mới, chưa có tầng hình.

## Requirements
- Functional:
  - Bảng `chia_lan(id, job_id, chu, trang_thai ∈ {cho_hinh, de_xuat, da_duyet, huy}, truc, usecase, insight_goc, phien_ban_prompt NOT NULL, tao_luc, duyet_luc)` — một lượt chia cho một job của một người.
  - Bảng `cum_nhap(id, chia_lan_id, nhom, kieu, thu_tu)` và `video_cum_nhap(video_id, chia_lan_id, cum_nhap_id NULL, lan ∈ {kieu, huong_dan, nghi})` — **một video một chỗ trong một lượt** (khoá `(video_id, chia_lan_id)`).
  - Bảng `video_dac_diem(video_id, phien_ban_prompt, nhan_json, tao_luc)` — nhãn vision, cache theo `(video_id, phien_ban)`.
  - Bảng `thao_tac_duyet(id, chia_lan_id, chu, loai, so_video, chi_tiet_json, luc)`; `loai` ∈ tập đóng: `chap_nhan · duyet_het · gop · doi_ten · chuyen · ngoai_chu_de · tra_ve · hoan_tac · xoa_kieu · doi_insight`.
  - `doi_insight`: lưu `usecase`/`insight_goc` vào `chia_lan` (thêm 2 cột), cùng transaction + nhật ký; `duyet` đọc 2 giá trị này từ `chia_lan` (không từ body) ⇒ F5 không mất, "gộp vào cụm có sẵn" lọc theo giá trị đã lưu. Khởi tạo từ `jobs` (phase 5) khi tạo lượt chia; `doi_insight` ghi CẢ `jobs` (để "chia lại" không mất công gõ). `duyet` nhận `usecase`/`insight_goc` trong body (tuỳ chọn): có ⇒ ghi như một `doi_insight` TRONG CÙNG transaction duyệt rồi dùng (hết race giữa ô nhập và nút duyệt); không có ⇒ đọc `chia_lan`.
  - `duyet_kieu(chia_lan_id, cum_nhap_id, chu, usecase, insight_goc)` = `models_cum.tao_cum` (trùng tên ⇒ trả cụm có sẵn = "gộp vào cụm có sẵn" tự nhiên) + `models_cum.gan_video` (chuyển video). Đây là lối DUY NHẤT từ nháp sang `cum`.
  - Route: `GET /chia/{job_id}` (đọc nháp của người gọi) · `POST /chia/{id}/thao-tac` (một thao tác, ghi nhật ký cùng transaction) · `POST /chia/{id}/duyet` (duyệt một kiểu / tất cả còn lại).
  - **D13:** `duyet` gặp tên trùng cụm có sẵn ⇒ trả `{trung_cum_co_san: [{cum_nhap_id, cum_id, ten, so_video}]}`, KHÔNG gộp, trừ khi request có `xac_nhan_gop: [cum_id…]`.
  - **D14:** (a) `ghi_de_xuat` loại video đã ở một cụm thật của `chu` (trả `da_o_cum`); (b) `duyet_kieu`/`duyet_het` kiểm LẠI trong cùng transaction `BEGIN IMMEDIATE` và chỉ gán video CHƯA có cụm — video đã có cụm (do một nháp song song vừa duyệt) được trả `da_o_cum`, không chuyển. **Thứ tự trong transaction:** lọc video TRƯỚC, chỉ gọi `tao_cum` khi còn ≥1 video lọt — không bao giờ sinh cụm rỗng (tên máy đặt không vào `cum` nếu không có video đi kèm).
  - **D7:** `GET /cum/{id}/lo/{thu}/payload` dựng `{v, items, nhan}` ở SERVER từ cụm thật (cùng hợp đồng `nhan`, 8 quy tắc); `app.js` bỏ `nhanTuCum` và `window.open` chuỗi server trả. Bàn giao chọn tay (không `nhan`) giữ nguyên.
- Non-functional: mọi hàm nhận `chu` không mặc định, lọc trong SQL (luật `models_cum`); migration chỉ thêm bảng (`CREATE TABLE IF NOT EXISTS`); sao lưu DB mini trước deploy.

## Architecture
```
chia_lan ──< cum_nhap ──< video_cum_nhap >── videos
   │                          (lan: kieu | huong_dan | nghi)
   └──< thao_tac_duyet
POST /chia/{id}/duyet ──► models_cum.tao_cum + gan_video ──► cum / video_cum (#13, không đổi)
```
Nháp KHÔNG có `cum_id`, và `nhan` chỉ server dựng từ cụm thật ⇒ tên máy đặt chỉ tới Creative Desk qua duyệt (điều kiện ĐP (i), bản đúng — bản trước khai "do cấu tạo" trong khi `nhan` dựng ở client). Nhật ký ghi CÙNG transaction với thao tác: thao tác không ghi được nhật ký thì không xảy ra (vế 1 luật mốc: nhãn sau việc).

## Related Code Files
- Create: `web/models_chia.py`, `tests/test_models_chia.py`, `tests/test_web_chia.py`
- Modify: `web/models.py` (DDL trong `init_db`), `web/app.py` (3 route + route payload), `web/static/app.js` (bàn giao cụm dùng payload server), `tests/test_cum_browser_and_js.py`
- Không đụng: `web/models_cum.py`, hợp đồng `nhan` (đầu ra byte-y-hệt: test so payload server với bản JS cũ trên cùng cụm)

## Implementation Steps
1. DDL 5 bảng trong `init_db`, `PRAGMA foreign_keys` như `cum`; thêm 2 cột `jobs.usecase`, `jobs.insight_goc` qua `_add_column_if_missing` (chuyển từ phase 5 lên vì `doi_insight` ghi vào đó).
2. `models_chia.py`: `tao_chia_lan`, `ghi_de_xuat` (thay toàn bộ nháp của lượt ở trạng thái `de_xuat`; từ chối nếu `da_duyet`), `lay_chia`, `ap_thao_tac` (+ nhật ký), `duyet_kieu`, `duyet_het`.
3. Route + pydantic; 404 cho lượt không phải của người gọi (không lộ tồn tại).
4. Test: quyền sở hữu · một video một chỗ · duyệt đi qua `tao_cum` (trùng tên ⇒ vào cụm có sẵn) · nhật ký đủ loại · thao tác trượt ⇒ 0 dòng nhật ký.
5. **Đột biến bắt buộc** (hỏng âm thầm): cho `duyet_kieu` ghi thẳng `INSERT INTO cum` bỏ `_cum_trung` ⇒ ĐỎ · ghi nhật ký NGOÀI transaction ⇒ ĐỎ · route payload nhận id nháp ⇒ ĐỎ · bỏ cổng D13 (gộp không cần xác nhận) ⇒ ĐỎ · bỏ lọc D14(a) ⇒ ĐỎ · bỏ kiểm lại D14(b) lúc duyệt ⇒ ĐỎ (ca: hai nháp cùng chứa video X, duyệt nháp 1 rồi nháp 2 ⇒ X phải ở cụm của nháp 1) · gọi `tao_cum` trước khi lọc ⇒ ĐỎ (ca: mọi video của kiểu đã `da_o_cum` ⇒ 0 hàng `cum` mới).
6. **Test đích danh cho vá R10 (ĐP-19):** (i) `doi_insight` rồi "chia lại" (nháp mới) ⇒ insight vẫn còn (đột biến: bỏ ghi `jobs` ⇒ ĐỎ); (ii) `duyet` mang insight trong body mà `chia_lan` còn trống ⇒ cụm tạo với insight của body (đột biến: bỏ nhánh body ⇒ ĐỎ). Vá thứ 3 (caption qua tệp + cache) thuộc phase 2.

## Success Criteria
- [ ] `PYTHONPATH=src pytest -q` xanh, test cụm #13 không đổi.
- [ ] 7 đột biến ở bước 5 + 2 ở bước 6 đều ĐỎ.
- [ ] Payload `nhan` server dựng khớp BYTE với bản JS cũ trên cùng cụm (hợp đồng không đổi).
- [ ] Deploy mini: 5 bảng mới 0 hàng, bảng cũ không đổi số hàng (so với bản sao lưu).

## Risk Assessment
- `_cum_trung` so tên trên mọi hàng `cum` của người đó ⇒ đã chặn bằng D13 (server trả `trung_cum_co_san`, cần `xac_nhan_gop`). Dấu hiệu vẫn sai: user báo "video chạy sang cụm cũ" ⇒ soát nhật ký `gop` của lượt đó.
- Đổi bàn giao cụm sang payload server là đụng code #13 đang LIVE ⇒ test so byte + chạy lại test trình duyệt cụm #13.
- venv editable trỏ checkout gốc ⇒ chạy test với `PYTHONPATH=src`.
