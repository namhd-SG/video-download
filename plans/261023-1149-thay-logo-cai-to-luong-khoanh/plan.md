# Plan thi công — Thay logo cải tổ: luồng Lô + khoanh chỗ lộ + ca tự học (H1)

Ngày 23/10/2026 · lane logo tk3 d8c695a4 · Trạng thái: **NHÁP — chờ agy PHÁN → ĐP duyệt → code**.
Nguồn quyết định: user duyệt mock v2 23/10 11:49 (pane ĐP): *"nhớ phải lưu và tạo bài học để tool tự thông minh lên nhé, như này bàn, okie
duyệt mockup nhé dùng đã rồi tính"*; user 11:44 (pane lane logo): sửa tay = *khoanh chỗ logo bị lộ để tool tiếp tục fix*; "thử đã".
Vật liệu: `plans/reports/brainstorm-261023-thay-logo-cai-to/` (brainstorm, mock `mock-tool-tong-quan.html`, Pha 0 `pha0-*`).

## 0. Kết quả · ràng buộc · không làm · nghiệm thu

- **Kết quả:** người dùng thấy ngay chỗ nào trong lô cần mình, khoanh chỗ logo cũ còn lộ bằng chuột, mỗi lần khoanh được LƯU thành ca kiểm
  tra + sinh bài học trong sổ know-how; bản cải tiến nào cũng phải chạy qua bộ ca (bộ đề B1 + ca từ khoanh) trước khi lên.
- **Ràng buộc:** không đổi lõi đã được user chấm (bản C, 061417c) ở pha 1; không gửi video ra ngoài; không deploy ca-n khi chưa báo ĐP, tránh
  khung tk1 (12:12–13:25, 00:50–09:00 VN); thao tác người ít (1 kéo chuột + 1 nút / chỗ).
- **Không làm (giai đoạn này):** OCR làm lõi (Pha 0(b): chỉ thấy logo ở 2/18 khung khó, 0/60 với "CO", dò nhầm phụ đề); SAM/inpainting;
  phương án B "kéo khung" và C "bấm 1 điểm" (chỉ làm nếu dùng thật thấy cần — ĐP 11:49).
- **Nghiệm thu chung:** mỗi pha: test + đột biến + ảnh trang thật (ĐP tự xem) + agy + ĐP gật + PR; bộ đề B1 trên nhánh phải ra
  **0 khác** so với 061417c ở mọi pha KHÔNG đổi lõi (pha 1).

## 1. Sự thật đã đo, làm nền thiết kế (mọi số có nguồn)

| sự thật | nguồn |
|---|---|
| Đỏ (máy biết lộ) 81 đoạn / 26 video xuất; 10/26 video 0 đoạn đỏ; đỏ + vàng 'đè dù chặn' = 117 đoạn, trung vị 2/video, max 23 (v15), 9/26 video 0 đoạn | Pha 0(a), `pha0-dem-doan-C.json` |
| Vàng "đè dù cổng chặn" 36 đoạn; bắt 2/2 ca lỗi biết; báo cả 40/40 khung user chấm đúng (tập nhãn lấy mẫu từ chính loại khung này ⇒ tỉ lệ báo oan thật CHƯA ĐO) | như trên |
| Nội suy 789 đoạn (cộng vào thì trung vị 20/video, max 188 ở v14) ⇒ KHÔNG tô màu nội suy | như trên |
| Khả năng tự phát hiện đè lệch kiểu v13#63 ngoài lớp vàng: **CHƯA ĐO** | — |
| Video gốc + bản ra bị xoá khi job xong (`_ket_thuc` xoá scratch) | `web/thay_logo_worker.py:363-367` (origin/main 061417c) |
| track.json.gz + truoc/sau/sheet giữ 60 ngày (180 nếu đánh giá cuối là hỏng), có trần dung lượng | `nhat_ky.py:18, 157-185` |
| Chưa có endpoint phục vụ track; ảnh khung chỉ có `truoc.jpg`/`sau.jpg` | `web/thay_logo_routes.py:642-662` |
| Nguồn video tải lại được từ Drive (cả "Tải từ máy") trong 60/180 ngày | `tai_len_phien.py:450-460`, worker:536-537 |

## 2. Các pha (mỗi pha một PR; pha 1 không đổi kết quả lõi)

### Chốt cơ học từ agy R3b (KHÉP, đã kiểm tại nguồn 23/10) — áp vào pha 1a/1b/1c
- **ĐK1 — giữ file KHÔNG sửa `_ket_thuc`** (gọi ở ~10 nhánh, có nhánh lỗi): chỉ ở 2 nhánh thành công của `_ket_thuc_con`
  (`web/thay_logo_worker.py:487-490`, `xong` / `cho_nguoi`) dời `goc.mp4` (+ `ra.mp4`) bằng `os.replace` sang **`data/thay_logo_video/<video_log_id>/`**
  — TÁCH khỏi `data/thay_logo/<video_log_id>/` vì `don_dep` có trần `TRAN_FILE_BYTE = 1_000_000_000` (`nhat_ky.py:17, 157`) sẽ xoá luôn
  track/ảnh nếu video nằm chung. Dọn bằng hàm riêng: `NGAY_GIU_VIDEO_SUA = 7` + cổng đĩa + xoá ngay khi Đúng/bỏ qua mà không còn khoanh chờ;
  đã dọn mà cần ⇒ tải lại từ Drive.
- **ĐK2 — ca từ khoanh không lấy vùng khoanh làm `box_dung`**: lưu `vung_khoanh` + `box_may_luc_do`; chỉ hợp hai hộp khi `lo_mep`.
  Nhánh là ỨNG VIÊN sửa (chờ soi) khi: (i) không hở lại phần máy đã đè đúng (`ho_mep(b, box_may) ≤ 3`, nếu `lo_mep`); (ii) phủ lõi 60%
  của vùng khoanh; (iii) không phình quá vùng mục tiêu > 12 px. Chỉ sau khi người soi ghi "sửa" lần đầu, box của nhánh đó mới thành
  `box_dung` cho hồi quy về sau.
- **ĐK3 — tự gán loại lỗi 5 nhánh tất định** (người vẫn 0 chọn mã): `may_khong_thay` (video cho_nguoi) · `che_nham` (bấm "Giữ hình
  gốc đoạn này") · `lo_mep` (khoanh giao/cách mép box máy ≤ max(0,5·w_máy, 24 px)) · `de_lech_cho` (box máy cùng khung nằm xa) ·
  không có box máy: track có `hidden_*` giao vùng khoanh ⇒ `lo_do_cong_chan` (lưu `chan_cu`), ngược lại `lo_mat_dau`.
- **ĐK4 — nối dây**: `tl_ca_khoanh` lưu cả `video_log_id` (tl_video) lẫn `job_video_id` (route dùng `tl_job_video.id`); video có khoanh
  được giữ 180 ngày như video chấm hỏng (`don_dep` + `_het_han_giu`); `khung-tai` dùng `ffmpeg -ss` trước `-i` + dựng sẵn 3 ảnh soi nhanh
  mỗi video (không bắn hàng trăm tiến trình ffmpeg khi mở Lô).

### Pha 1a — Dữ liệu cho trang mới (backend, không đổi lõi)
- **Giữ file video cho người sửa:** đổi `_ket_thuc` để GIỮ `goc.mp4` + `ra.mp4` của video `xong`/`cho_nguoi` tới khi người đóng video
  (Đúng / bỏ) hoặc quá N ngày (đề xuất 7, hằng số có tên), có cổng đĩa (`TRAN_DIA_GB` sẵn có); hết hạn mà cần ⇒ tải lại từ Drive (§1).
- **Endpoint dải thời gian** `GET /api/thay-logo/videos/{vid}/dai`: từ track tính đoạn đỏ / vàng (đúng định nghĩa Pha 0, dùng chung 1 hàm
  với script đo để không lệch), trả theo giây + khung.
- **Endpoint khung bất kỳ** `GET /api/thay-logo/videos/{vid}/khung-tai/{frame}?ban=goc|ra`: trích 1 khung bằng ffmpeg từ file đã giữ.
- **Bảng ca:** `tl_ca_khoanh(id, video_id, member, khung, x, y, w, h (px gốc), mau_loi, luc, sha_ma, box_may_luc_do JSON, trang_thai)`
  + `POST /api/thay-logo/videos/{vid}/khoanh` (toạ độ tỉ lệ 0–1 theo ảnh hiển thị ⇒ quy đổi WxH gốc `tl_video.kho`).
  `mau_loi` máy tự gán theo vị trí khoanh so với box máy: `lo_mep` (khoanh sát box), `lo_logo` (vùng máy không đè), `may_khong_thay`
  (video cho_nguoi). Người không phải chọn mã.
- Nghiệm thu: test API (quyền chủ lượt/admin, 400 toạ độ sai, quy đổi toạ độ, đọc dữ liệu cũ không có cột mới); đột biến: bỏ giữ file ⇒
  test đỏ; bỏ quy đổi ⇒ test đỏ; bộ đề B1 = 0 khác.

### Pha 1b — Trang mới (FE) theo mock v2
- Màn **Lô**: sắp theo việc cần người; dải màu (đỏ/vàng/xanh/xám); nhóm "máy chắc" có **soi nhanh 3 ảnh phóng to cho TẤT CẢ video**;
  nhóm "máy cho là không có logo" để người xác nhận.
- Màn **Sửa** phương án A: khung + ô phóng to, khoanh nhiều chỗ, nhảy chỗ cần xem (Shift+J/L), "Đúng" / "Giữ hình gốc đoạn này".
  Pha 1b CHƯA có "máy sửa tiếp" — nút ghi "Lưu chỗ khoanh" (máy sửa ở pha 2).
- Màn **Tổng quan** + chú thích khi rê chuột như mock.
- Nghiệm thu: test trình duyệt (khoanh ⇒ POST đúng toạ độ; phím tắt; dải màu khớp `/dai`), ảnh chụp trang thật trên dữ liệu thật
  (ĐP tự mở ảnh), trang cũ vẫn chạy song song tới khi user đổi hẳn.

### Pha 1c — Ca kiểm tra + bài học (vòng tự học, phần lưu)
- Mỗi `tl_ca_khoanh` ⇒ xuất `kho-ca/ca.jsonl` trên ca-n đủ để chạy lại y hệt: sha256 video gốc, nguồn Drive, box agy (`tl_box_moi`),
  `man_ket_agy`, sha mã, cờ env, khung + vùng khoanh + box máy lúc đó.
- **Bộ đề đọc thêm ca từ khoanh**: vùng khoanh ⇒ nhãn `lo_mep`/`lo_logo` có `box_dung = vùng khoanh ∪ box máy` ⇒ máy-kiểm-được
  "ca đã sửa" (bộ đề B1 vế "≥1 ca lỗi được sửa").
- **Bài học tự sinh** (`scripts/thay_logo_bai_hoc.py`, chạy trên máy dev, đọc ca-n CHỈ ĐỌC): gom ca theo `mau_loi` + video + đặc điểm
  (cổng đã chặn `chan_cu`, có phụ đề chồng, logo trôi) ⇒ cập nhật mục "Bài học tự sinh" trong `~/plans/kien-thuc/knowhow-thay-logo.md`:
  mỗi nhóm 1 dòng, **ca lặp lại ⇒ tăng đếm, không thêm dòng trùng** (khoá nhóm cố định), kèm ví dụ (video#khung) và ảnh.
- Nghiệm thu: chạy 2 lần liền ⇒ sổ không đổi (idempotent); thêm 1 ca cùng nhóm ⇒ đếm +1; đột biến bỏ khoá nhóm ⇒ test đỏ.

### Pha 2 — Máy sửa tiếp từ chỗ khoanh (ĐỔI LÕI — qua bộ đề)
- Vùng khoanh thành mốc tay (`moc_tay`) ⇒ chạy lại đoạn quanh khung đó (tới khi gặp lại đoạn xanh) từ file đã giữ ⇒ bản nháp 2 giây ⇒ Đúng.
- Nghiệm thu: bộ đề + ca từ khoanh: "prod đúng mà nhánh sai" = 0, ≥ 1 ca được sửa, đối chứng md5; đo giờ người/lô trên 10 video giữ kín
  (user: "thử đã").

### Pha 3 — Tự đề xuất chỉnh tham số từ cụm ca + báo cáo tuần (plan vòng tự cải thiện cũ §4, §B5).

## 3. Câu hỏi còn mở (ĐP gom, không hỏi lúc này)
- N ngày giữ file video cho người sửa (đề xuất 7) — cần ĐP/user khi chạm dung lượng.
- Câu gửi video ra dịch vụ ngoài: đã giải thích, user chưa trả lời ⇒ mặc định không.

## 4. Rủi ro
- Vàng báo oan nhiều (chưa đo) ⇒ người mệt: đo ngay khi pha 1b có dữ liệu thật; điều chỉnh bằng số.
- Giữ file video làm đầy đĩa ca-n (302 GB trống, đo `df -h` 23/10 10:54 VN) ⇒ có cổng đĩa + hạn N ngày.
- Đổi `_ket_thuc` chạm worker prod ⇒ test đột biến + deploy ngoài khung tk1, báo ĐP.
