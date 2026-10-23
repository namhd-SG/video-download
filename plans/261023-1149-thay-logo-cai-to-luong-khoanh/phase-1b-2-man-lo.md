# Pha 1b · bước 2 — Màn Lô (FE)

Mock bám theo: `plans/reports/brainstorm-261023-thay-logo-cai-to/v2-2-lo.png` (+ `mock-tool-tong-quan.html` mục `#lo`), user duyệt 23/10 11:49.
Nền đã có trên prod (7486a25): `/dai`, `/soi`, `/soi/{i}`, `/khung-tai`, `POST /khoanh`, `GET /videos?job_id=`, `GET /bo`, `POST …/bo-qua`.

## Phạm vi
- Trang MỚI `web/static/thay-logo-lo.html` + `thay-logo-lo.js` (+ css riêng). Trang cũ `thay-logo.html` KHÔNG đổi — chạy song song tới khi
  user đổi hẳn (plan §1b). Từ trang cũ chỉ thêm MỘT link "Màn Lô (thử)" (hoặc không thêm — chờ ĐP).
- Không backend mới, không đổi lõi ⇒ không cần bộ đề.
- KHÔNG làm: màn Sửa (bước 3), Tổng quan (bước 4), "Đạt cả nhóm" (mock không có — chờ ĐP).

## Dữ liệu
1. Chọn lô: `GET /api/thay-logo/bo` ⇒ danh sách lượt (mặc định lượt mới nhất). URL `?lo=<job_id>`.
2. `GET /api/thay-logo/videos?job_id=X` ⇒ video của lô (`id`, `trang_thai`, `ten_video`, `anh_bia`, `so_box`, `bo_qua_luc`, `danh_gia`).
3. Mỗi video `xong`/`cho_nguoi`: `GET …/dai` (dải màu) — tối đa 4 request song song.
4. Nhóm có ảnh soi: `GET …/soi` chỉ khi người BẤM mở nhóm (không tải 3×N ảnh lúc vào trang); ảnh `loading="lazy"`.

## Xếp nhóm (tất định, theo trạng thái máy — không đoán)
| nhóm | điều kiện | dòng hiển thị | nút |
|---|---|---|---|
| A. Cần bạn xem | `xong` có ≥1 đoạn đỏ/vàng trong `/dai` | 1 dòng/video: bìa, tên, thời lượng, "N chỗ vàng · M chỗ đỏ", dải màu | "Xem N chỗ" ⇒ màn Sửa (bước 3) |
| B. Máy không chắc vị trí | `cho_nguoi` và `so_box > 0` | 1 dòng/video, dải XÁM cả dải (handoff mục 5: `/dai` còn trả đoạn từ vết dở) | "Khoanh logo" ⇒ màn Sửa |
| C. Máy chắc | `xong`, 0 đoạn đỏ/vàng | 1 dòng gộp "N video máy chắc", dải xanh | "Soi nhanh N video" ⇒ mở lưới 3 ảnh/video (480×360) |
| D. Máy cho là không có logo | `cho_nguoi` và `so_box == 0` | 1 dòng gộp "N video máy cho là không có logo cũ" | "Xác nhận N video" ⇒ lưới 3 ảnh cả khung; mỗi video: "Đúng là không có logo" (`POST bo-qua`, hoàn tác được) · "Có logo" ⇒ màn Sửa |
| (ẩn) | `cho`, `cho_agy`, `dang_chay`, `loi` | dòng tóm tắt "máy còn làm N · lỗi M" ở đầu | — |
Thứ tự: A (nhiều chỗ trước) → B → C → D. Phân biệt B/D theo `so_box` = đúng tín hiệu trang cũ đang dùng (`thay-logo-hop-duyet.js:215`).
Đầu trang: "Lô <tên> · N video · máy xong X/N · cần bạn: a video, b chỗ · c video máy chắc · d video không có logo cũ" + chú thích màu như mock.

## Dải màu
- Thang theo `so_khung`; đoạn `{loai, tu, den}` tô đỏ/vàng trên nền xanh (`xong`). `cho_nguoi` ⇒ xám cả dải, KHÔNG tô đoạn.
- Đoạn ngắn (< 0,5% chiều dài) vẫn vẽ tối thiểu 3 px để không biến mất (mock: chỗ vàng 1 khung vẫn thấy).
- Rê chuột lên đoạn ⇒ "khung a–b · giây x–y · đỏ = máy biết còn lộ / vàng = máy cảnh báo".

## Nút sang màn Sửa trong bước này
Màn Sửa là bước 3 ⇒ đề xuất: nút đã hiện (đúng mock) nhưng mở `?lo=X&sua=<vid>&khung=<f>` hiện khung từ `/khung-tai` + ghi chú
"Khoanh ở bước sau". CẦN ĐP CHỐT: (a) như trên · (b) ẩn nút tới bước 3 · (c) nút mờ có chú thích.

## Nghiệm thu
- Test trình duyệt (khuôn `tests/test_thay_logo_1b_browser.py`, Chromium chặn mạng ngoài): xếp đúng 4 nhóm từ dữ liệu mồi gồm đủ 4 ca + video
  người khác (không thấy); dải đỏ/vàng đúng vị trí theo `/dai` (đo toạ độ phần tử); `cho_nguoi` xám không tô đoạn; nhóm C mở ra đúng 3N ảnh và
  KHÔNG gọi `/soi` trước khi bấm (đếm request); "Đúng là không có logo" ⇒ POST bo-qua + hoàn tác.
- Đột biến: đảo điều kiện B/D · tô đoạn cho `cho_nguoi` · tải `/soi` lúc vào trang · bỏ lọc trạng thái ẩn ⇒ phải ĐỎ.
- Ảnh chụp 1280 px trên dữ liệu thật (bản sao job 4, 5 + dữ liệu mồi đủ 4 nhóm) ⇒ ĐP tự mở; đặt cạnh `v2-2-lo.png`.
- `node --check` mọi tệp JS mới. Đo 23/10: repo KHÔNG có `package.json` / cấu hình eslint ⇒ không có lint JS; cú pháp bắt bằng
  `node --check` + test trình duyệt (repo đã có khuôn chạy JS bằng node: `tests/test_cum_browser_and_js.py:40`).

## Câu hỏi cho ĐP
1. Nút sang Sửa ở bước này: (a)/(b)/(c)?
2. Link từ trang cũ sang màn Lô: thêm ngay hay chờ user?
3. "Đạt cả nhóm" cho nhóm C: mock không có — giữ ngoài phạm vi?
