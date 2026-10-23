# Pha 1b · bước 3 — Màn Sửa (phương án A "khoanh chỗ lộ")

Mock bám theo: `plans/reports/brainstorm-261023-thay-logo-cai-to/v2-3-sua-khoanh.png` (+ mục `#sua` của `mock-tool-tong-quan.html`).
Nền đã có trên prod/main: `/dai`, `/khung-tai/{k}?ban=goc|ra`, `/soi`, `POST /khoanh`, `POST /danh-gia`, `POST /bo-qua`. Màn Lô (#105) đã có
nút sang Sửa đang MỜ.

## Phạm vi
- Màn Sửa nằm TRONG trang Lô (`thay-logo-lo.html?lo=X&sua=<vid>&khung=<k>`), không thêm trang thứ ba; nút ở màn Lô bật lên và mở màn này.
- Trái: ảnh khung (`/khung-tai`, mặc định bản `ra`; Space giữ = xem `goc`) + lớp vẽ: khung VÀNG ĐỨT = ô máy đè ở khung đó, khung ĐỎ = chỗ
  người khoanh (nhiều chỗ). Dưới ảnh: dải màu như màn Lô + kim vị trí + giờ.
- Phải: tiêu đề "tên — chỗ vàng/đỏ m:ss (lý do)", ô PHÓNG TO quanh ô máy (4:3, cùng công thức `soi_nhanh.cat_quanh`), khoanh được cả trên
  ô phóng to (quy đổi về toạ độ khung gốc), danh sách chỗ đã khoanh.
- Nút: **"Lưu chỗ khoanh"** (thay "Máy sửa tiếp đoạn này" — máy sửa là pha 2, plan §1b) ⇒ `POST /khoanh` mỗi ô · **"Giữ hình gốc đoạn này"** ⇒
  `POST /khoanh {giu_goc:true}` · **"Khoanh lại"** (Esc) = xoá ô chưa lưu · ("Xem 2 giây" — xem câu hỏi 2).
- Phím: J/L ±1 khung · Shift+J/L chỗ cần xem trước/sau · Space giữ = xem gốc · Esc khoanh lại · Enter (xem câu hỏi 3).
- "Chỗ cần xem":
  · video `xong` (A): các đoạn đỏ/vàng của `/dai`, mỗi đoạn mở ở khung `tu`;
  · video `cho_nguoi` (B, D-"Có logo"): máy không đè gì ⇒ dùng 3 khung ảnh soi (`/soi`: 10/50/90%) — dữ liệu sẵn có, không đoán.
- Mỗi lần lưu: hiện mã máy tự gán (`mau_loi`) bằng lời thường ("lộ mép ô máy", "máy đè lệch chỗ", …) — người không chọn mã.
- Yêu cầu user (Pha 1c sẽ dùng): MỌI lần khoanh thành một ca — route `POST /khoanh` đã ghi `tl_ca_khoanh`; bước này không thêm gì.

## ĐP CHỐT 24/10 00:10 (pane ĐP 15012)
1. GẬT route ĐỌC `GET /videos/{vid}/box/{khung}` — không ffmpeg. `khoanh.khung_tai` vốn thuần (chỉ đọc track) ⇒ không cần tách; route và
   `POST /khoanh` cùng đi qua MỘT hàm `_box_tai` (gồm cả nhánh `cho_nguoi` ⇒ không box). Test: box route = box ca khoanh ghi; đột biến route tự tính ⇒ đỏ.
2. "Xem 2 giây" KHÔNG bỏ (mock user duyệt): nút MỜ + chú thích "có ở bước sau". Nợ đặt tên: **bước 1b-4 "Phát video có Range"** —
   route `GET /videos/{vid}/video?ban=goc|ra` (`FileResponse`, Range) + nút "Xem 2 giây" tua `<video>` tới đoạn.
3. Enter = sang chỗ kế, không lưu. Nút cuối GHI RÕ hành động: **"Xong — đánh Đạt"** (video `xong`, chưa lưu ô khoanh nào) ⇒ `POST /danh-gia dat`;
   **"Xong — về Lô"** khi đã có ô khoanh hoặc video `cho_nguoi` ⇒ không ghi gì. Test cả 2 nhánh.
Nút chính giữ chữ "Lưu chỗ khoanh" (bàn giao 67543).

## ĐP CHỐT 24/10 00:24 — chặn "đánh Đạt" khi còn ca khoanh chờ sửa
- `/dai` thêm `so_ca_cho`; màn Sửa chỉ mời "Xong — đánh Đạt" khi `so_ca_cho == 0` và lượt này chưa lưu ô nào; NGAY trước khi gửi Đạt đọc lại
  `/dai` (ca có thể vừa lưu ở tab khác) — còn ca ⇒ không gửi, đổi nút "Xong — về Lô".
- KHÔNG chặn phía máy chủ ở PR này (phương án c): Đạt/phím D ở trang cũ là hành động tường minh của người duyệt; chặn cứng là quyết định sản phẩm.

## Câu chờ user
- **Khi video còn chỗ khoanh chờ sửa, trang cũ có được đánh Đạt cả video không?**
  · (a) Không: máy chủ trả mã riêng 423 "Video còn N chỗ khoanh chờ sửa — chưa đánh Đạt được", trang cũ thêm 1 dòng câu báo. Hệ quả: không ai
    ghi Đạt được video còn chỗ lộ đã khoanh; mất lựa chọn "chỗ khoanh nhỏ, vẫn cho Đạt" cho tới khi ca được sửa/huỷ.
  · (c) Có (hiện trạng): chỉ màn Sửa tránh mời Đạt. Hệ quả: người duyệt ở trang cũ (hoặc tab khác) vẫn ghi Đạt được video còn ca khoanh chờ —
    tường minh, nhưng ca khoanh vẫn nằm chờ trong khi video đã "Đạt".

## (Câu hỏi gốc gửi ĐP — đã chốt ở trên)
1. **Box máy theo khung — THIẾU nguồn.** Khung vàng đứt + ô phóng to cần box máy ở khung đang xem; khi bấm J/L khung đổi ⇒ cần tra theo khung.
   Hiện KHÔNG route nào trả box (chỉ `POST /khoanh` trả `box_may` SAU khi lưu). Đề xuất: route ĐỌC mới
   `GET /api/thay-logo/videos/{vid}/box/{khung}` ⇒ `{box_may, chan}` dùng lại NGUYÊN `khoanh.khung_tai(track, tt, khung)` (cùng hàm mà
   `POST /khoanh` dùng ⇒ không lệch), cùng cổng quyền `_nap`. Phương án khác (không route): phóng to quanh tâm khung — mất ý nghĩa "quanh ô máy".
2. **"Xem 2 giây" — THIẾU nguồn.** Không có route phát video. (a) bỏ nút này ở 1b (J/L thay thế) · (b) route mới phát `goc/ra.mp4` có Range
   (`FileResponse`), trình duyệt dùng thẻ `<video>` tua tới đoạn. Tôi nghiêng về (a) cho 1b — ít bề mặt mới; (b) để khi user dùng thật thấy cần.
3. **Enter "Đúng"** — mock ghi "Enter Đúng" nhưng không có chỗ lưu "chỗ này ổn". Đề xuất: Enter = "chỗ này ổn, sang chỗ kế" (KHÔNG lưu gì);
   ở chỗ cuối hiện nút "Xong video này" ⇒ video `xong`: `POST /danh-gia {ket_qua:"dat"}` CHỈ khi 0 ô khoanh nào được lưu trong lượt xem này,
   có ô khoanh ⇒ không đánh Đạt (video còn lộ) mà quay về Lô. Video `cho_nguoi` ⇒ quay về Lô.

## Nghiệm thu (theo khuôn bước 2)
- Test trình duyệt: kéo chuột vẽ ô ⇒ `POST /khoanh` đúng toạ độ tỉ lệ (vẽ trên ảnh lớn VÀ trên ô phóng to ⇒ cùng toạ độ khung gốc); nhiều ô;
  Esc xoá ô chưa lưu; "Giữ hình gốc" ⇒ `giu_goc:true`; J/L đổi khung (`/khung-tai/k±1`); Shift+J/L nhảy đúng đoạn kế/trước theo `/dai`;
  Space giữ ⇒ ảnh `ban=goc`, thả ⇒ `ra`; nút ở màn Lô hết mờ và mở đúng `sua=<vid>&khung=<tu đoạn đầu>`.
- Đột biến: bỏ quy đổi toạ độ ô phóng to · đảo J/L · Shift+L nhảy 1 khung thay vì 1 đoạn · Esc xoá cả ô đã lưu · Enter đánh Đạt dù có ô khoanh.
- Ảnh 1280 trên dữ liệu thật (bản sao job 4, 5) sáng/tối ⇒ ĐP mở, đặt cạnh mock. agy 2 vòng như bước 2. Không đổi lõi ⇒ không bộ đề
  (nếu thêm route câu 1: route chỉ đọc, test route + quyền như 1a).
