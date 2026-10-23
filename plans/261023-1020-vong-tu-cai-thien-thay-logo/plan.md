# Vòng tự cải thiện thay logo — plan (CHƯA thi công)

Ngày: 23/10/2026 · Người viết: lane logo tk3 · Trạng thái: **NHÁP — chờ agy phản biện + ĐP + user duyệt**.
Nguồn yêu cầu (user 23/10 10:20, qua ĐP 25509, nguyên văn): *"quan trọng là phải xây dựng được loop máy học, làm sao để tool tự học
và fix được và ngon dần lên … thay logo là lane mà tôi đã làm mấy tuần để fix và test nên know how và tự cải thiện là rất cần thiết"*.

## 0. Kết quả mong muốn · ràng buộc · không làm · nghiệm thu

- **Kết quả:** mỗi lỗi user/người dùng gặp ở job thật ⇒ trở thành một ca kiểm tra vĩnh viễn ⇒ mọi thay đổi lõi (PR, tham số) phải
  qua bộ ca đó ⇒ máy tự đề xuất chỉnh tham số từ cụm lỗi ⇒ user duyệt bằng số. Tool "ngon dần" mà không làm hỏng cái đang đạt.
- **Ràng buộc:**
  - KHÔNG tự lên prod (deploy vẫn qua ĐP);
  - không gửi video khách lên dịch vụ ngoài mới;
  - đo nặng chạy trên ca-n theo cổng tài nguyên (không chồng Creative Tracker);
  - thao tác của người chấm phải ÍT (1–2 click/job).
- **Không làm (giai đoạn này):**
  - không huấn luyện mạng nơ-ron (dữ liệu quá ít — 40 video + vài ca/tuần); "học" = **tinh chỉnh tham số + quy tắc có bằng chứng**,
    không phải train model;
  - không đổi luật user đã chốt (đè đúng chỗ cũ; thiếu 1 vết không xuất; đè lên chữ được).
- **Nghiệm thu:**
  - (a) có ≥ 1 ca lỗi thật đi trọn vòng: chấm → thành ca → đề xuất sửa → bộ đề đo → user duyệt;
  - (b) bộ đề chạy 1 lệnh, ra bảng % đạt theo loại lỗi + danh sách "main đúng mà nhánh sai";
  - (c) sổ know-how có ≥ 1 dòng nhật ký ca mới sinh từ vòng.

## 1. THU phản hồi (job thật → nhãn) — gắn vào cái ĐÃ CÓ, không làm màn mới

Đã kiểm tại nguồn (origin/main 061417c):
- **UI:** trang Thay logo đã có ô "chờ duyệt" với nút **✓ Đạt (phím D)** / **✕ Hỏng (phím H)**; Hỏng mở panel chọn lý do + ghi chú
  (`web/static/thay-logo-hop-duyet.js:121-132`).
- **API:** `POST /api/thay-logo/videos/{vid}/danh-gia` (`web/thay_logo_routes.py:522-529`); chỉ cho chấm khi video `xong`.
- **Lưu:** `tl_danh_gia(video_id, member, ket_qua dat|hong, loai_loi, ghi_chu, luc)` — append-only (`nhat_ky.py:36-38`).
  - Enum `LOAI_LOI = (sot_watermark, sai_cho, che_phu_de, pha_noi_dung, khac)` (`nhat_ky.py:19`); SQL không CHECK loai_loi ⇒ thêm mã chỉ cần đổi Python + JS.
  - **Chưa có cột khung / vị trí.**
- Ảnh trước / sau + sheet đã phục vụ (`/khung/{truoc|sau}.jpg`, `sheet.jpg`).
- `track.json.gz` được ghi nhưng **chưa có endpoint** phục vụ.

Đề xuất (ít thao tác nhất):
1. **Giữ 2 cú bấm sẵn có** (Đạt; hoặc Hỏng → chọn lỗi → Gửi).
2. **Bổ sung mã lỗi** theo yêu cầu: `lo_logo` (lộ logo cũ), `lo_mep` (lộ mép chữ / lệch mép), `che_nham` (che nhầm nội dung),
   `nen_lech` (nền lệch). Ánh xạ / giữ mã cũ: xem §7 Q1.
3. **Vị trí lỗi (tuỳ chọn, 1 cú bấm thêm):** trong panel Hỏng, bấm vào ảnh "sau" đã hiện ⇒ ghi `(khung, x, y)` (khung = khung của ảnh đang
   xem). Thêm cột `khung INTEGER NULL, x REAL NULL, y REAL NULL` vào `tl_danh_gia` theo mẫu ALTER sẵn có (`hang_doi.py:34`). Không bấm
   ⇒ vẫn ghi được (mức video).
4. **Tự chuyển thành ca** (§2): chấm "Hỏng" ⇒ worker ghi một dòng `kho-ca/ca.jsonl` (video_id, đường video gốc, box agy đã dùng từ
   `tl_box_moi`, loại lỗi, khung / vị trí nếu có). Chấm "Đạt" ⇒ đánh dấu video đó là ca vàng mới (md5 bản ra + track).

## 2. KHO CA (bộ đề hồi quy)

**Đơn vị = một CA:** `(video gốc, box mồi đã dùng, kỳ vọng)`. Kỳ vọng ở 2 mức:
- **mức video:** trạng thái mong đợi (render / cho_nguoi) + md5 bản ra đã được người duyệt (nếu có);
- **mức khung (nhãn người):** danh sách `(khung, loại: dung | lo_logo | lo_mep | che_nham | nen_lech, box tuỳ chọn)`.

**Bộ đề gốc:**
- 40 video Test3 (`~/Downloads/Test3`) + box `plans/261020-1606-gd1-do-lai-co-track/box-agymoi/`.
- Đầu ra bản C (061417c), user chấm 40/40 chỗ đè ⇒ **mốc vàng** (md5 từng video, track).
- Ca lỗi đã biết đầu tiên: **v13#63** (ring, lệch trái, lộ "AI"), **v22#407** (net, lệch phải 3–4 px), v5#1008/1010 (kiểm hình — đang bị chặn, đúng; giữ làm ca canh "không được đè").

**Lưu ở đâu:**
- `kho-ca/` trên ca-n (video + kết quả, máy công ty đã được user cho đặt video Test3);
- chỉ mục `kho-ca/ca.jsonl` + nhãn trong repo (`tests/kho_ca/`, không có video).
- Ca từ job thật: chép video gốc + box agy của job vào `kho-ca/`. Cần user duyệt chuyện giữ video job thật — ghi ở §7.

**Tự thêm ca:** khi người chấm đánh "lỗi" ở §1 ⇒ worker ghi một dòng `ca.jsonl` (đường video, box, khung, loại) ⇒ lần chạy bộ đề kế tiếp tự có ca đó.

## 3. THƯỚC ĐO tự động (cổng cho mọi thay đổi lõi)

Một lệnh (`scripts/bo-de-thay-logo.sh <sha|thư mục mã> [biến thể env]`), chạy trên ca-n, 2 luồng, cổng tài nguyên + không chồng CT
(dùng lại `mot-video.sh` đã kiểm 2 chiều — bản luật cũ, thư mục mã chọn bằng biến + chặn cứng; bài học bash 3.2 / zsh / sửa script đang chạy).

Ra **bảng so với mốc vàng (bản đang chạy prod)**:

| chỉ số | cách đo |
|---|---|
| video đổi trạng thái | `kq.json.trang_thai` nhánh vs prod |
| khung lộ có toạ độ (trong vết) | đếm từ track (như phan-tich.py) |
| % đạt theo loại lỗi trên khung có nhãn người | so state/box nhánh với nhãn |
| **"main đúng mà nhánh sai"** | khung có nhãn `dung` ở prod mà nhánh không đè / lệch / đổi box > 3 px |
| md5 video không có khung đổi | phải trùng prod (đối chứng có sức phân định — đã làm ở #100) |

**Luật lên:** chỉ đề xuất merge khi
- "main đúng mà nhánh sai" = 0;
- và ít nhất 1 ca lỗi được sửa;
- và đối chứng md5 sạch.

Luật này là CỔNG CƠ HỌC, chạy trước agy / ĐP; không thay agy.

## 4. TỰ ĐỀ XUẤT sửa (cụm lỗi → tham số → đo → user duyệt)

- **Gom cụm:** ca lỗi cùng loại + cùng cổng gây ra (`chan_cu`) + cùng "dò thật / lấp" ⇒ một cụm.
- **Bảng "lỗi → tham số nghi"** lấy từ sổ know-how (§5), ví dụ:
  - `lo_mep` ở khung dò thật dưới sàn ⇒ sàn điểm cho khung đích (F1);
  - lỗi trong đoạn chặn dài ⇒ GAP_MAX;
  - lệch pad ⇒ PAD_CHAT (F3).
- **Quét có giới hạn:** mỗi tham số nghi thử 2–3 giá trị ⇒ chạy bộ đề (§3) ⇒ bảng so.
  - Máy KHÔNG tự chọn. Nó trình bảng + ảnh lớn toàn khung của các khung đổi kết quả.
  - Người chấm / user duyệt.
- **Chặn tự lừa** (bài học 20–22/10):
  - chấm bằng ảnh lớn có toàn khung;
  - mẫu chỉ lấy video đã render;
  - mỗi đề xuất có đối chứng phải-lệch;
  - không tin số agy chấm (±2/35) làm thước.

**Ca thử đầu tiên — F1:**
- *Hiện:* khung DÒ THẬT bị cổng nội dung chặn được đè lại không cần đạt sàn hình (chỉ neo cần).
- *Câu hỏi:* siết sàn cho khung đích có sửa v13#63 mà không làm mất khung đúng?
- *Cách:* chạy bộ đề với sàn khung đích ∈ {không, sàn vết, sàn vết − 0,1}.
  - Báo: số khung đè mất đi, ca v13#63 / v22#407 có hết lệch, "main đúng mà nhánh sai".
  - User quyết từ bảng + ảnh.

## 5. KNOW-HOW (sổ tự giàu lên)

`~/plans/kien-thuc/knowhow-thay-logo.md`:
- bài toán & tiêu chí user;
- kiến trúc lõi;
- bảng loại lỗi;
- bảng tham số + vì sao;
- hướng đã bỏ (kèm số);
- bẫy đo;
- bộ đề;
- **Nhật ký ca**.

Mỗi vòng §4 kết thúc ⇒ thêm 1 dòng nhật ký ca (ngày · video · khung · loại · ai phát hiện · trạng thái · PR) + cập nhật bảng tham số nếu đổi.

## 6. Thứ tự thi công đề xuất (mỗi bước có nghiệm thu riêng, lane mới làm)

| bước | việc | nghiệm thu | ước |
|---|---|---|---|
| B0 | Sổ know-how (§5) + nhật ký ca 2 ca đầu | file có đủ 8 mục, mỗi khẳng định có nguồn | đang làm (subagent) |
| B1 | Bộ đề 1 lệnh (§3) trên 40 video + mốc vàng 061417c | chạy prod vs prod ⇒ 0 khác biệt; chạy bản trước #100 (39f7174) ⇒ đúng 11 video khác (đối chứng phân định) | ½–1 ngày |
| B2 | Mã lỗi mới + cột khung / vị trí (§1) | test API (400 sai enum, lưu khung); UI bấm ảnh ra toạ độ; md5 job không đổi | ½ ngày |
| B3 | Chấm Hỏng ⇒ tự thành ca (`ca.jsonl`) | chấm thử 1 video ⇒ có dòng ca + bộ đề lần sau chạy cả ca đó | ½ ngày |
| B4 | Vòng thử F1 (§4) bằng bộ đề | bảng 3 mức sàn + ảnh lớn toàn khung các khung đổi ⇒ trình user | ½ ngày |
| B5 | Báo cáo tuần tự động: số ca mới, % đạt theo loại, đề xuất | 1 trang md / tuần trong `plans/reports/` | sau B4 |

Mỗi bước code: test + đột biến + agy + ĐP gật như #97–#100. Không bước nào tự deploy.

## 7. Câu hỏi cho user (ĐP gom hỏi)
- **Q1 mã lỗi:** dùng 4 loại anh nêu (lộ logo cũ / lộ mép chữ / che nhầm nội dung / nền lệch) THAY cho 5 mã cũ, hay GỘP (giữ mã cũ
  `sot_watermark` = lộ logo cũ, `sai_cho`, thêm `lo_mep`, `nen_lech`)? Đề xuất: gộp — giữ dữ liệu cũ đọc được.
- **Q2 giữ video job thật làm ca:** khi chấm Hỏng, cho phép giữ bản sao video gốc của job đó trên ca-n để làm ca kiểm tra vĩnh viễn?
  (video khách / đối thủ nằm lại máy công ty lâu dài.)
- **Q3 F1** (ca thử đầu tiên): đồng ý chạy thử 3 mức sàn trên bộ đề và xem bảng + ảnh trước khi quyết?

---

## SỬA sau agy R1b (MỞ) — đè lên các mục trên; điểm nào claude đã kiểm tại nguồn ghi rõ

**Tự lừa — khoá:**
- **"40/40" là 40 CHỖ ĐÈ của bản C, không phải 40 video chuẩn vàng.** 23 video đối thủ đã render vẫn còn 740 khung lộ có toạ độ, 717 khung mất dấu, cùng v13#63 và v22#407.
  - ⇒ Mốc prod (061417c) chỉ là **mốc ĐỐI CHIẾU**, không phải "đúng".
  - Tách hai tệp: `khung_vang.json` (khung có nhãn người: `dung` / loại lỗi / `khong_duoc_de`) và `video_moc.json` (md5 + track prod).
  - Bấm "Đạt" chỉ ghi "user không thấy lỗi ở khung đã xem". KHÔNG biến mọi khung của video thành vàng.
- **Luật lên (§3) có 3 vế:**
  - (a) khung nhãn `dung`: nhánh không được hỏng (không đè, lệch > 3 px);
  - (b) khung canh âm `khong_duoc_de`: nhánh KHÔNG được đè — v5#1008/1010 (kiểm hình, đè ra 2 logo), v26 (không logo), v35–37 (logo nhà);
  - (c) khung KHÔNG nhãn mà nhánh đổi kết quả: bắt buộc soi ảnh lớn toàn khung một mẫu ≥ 20 (rải đều video) trước khi lên.
- **F1 đổi cách hiểu (agy, claude chưa tự kiểm):** v13#63 là khung LẤP bị ghim toạ độ cũ ở nửa đầu bước nhảy (`lam_muot_vet`). Siết sàn chỉ BẬT / TẮT đè, không sửa toạ độ.
  - ⇒ F1 tách hai giả thuyết: (F1a) siết sàn khung đích; (F1b) sửa nội suy ở bước nhảy.
  - **Nghiệm thu cấm "sửa" v13#63 bằng cách bỏ đè.** Phải còn đè VÀ che hết "AI".
- **Quá khít bộ đề:** tách 40 video thành 30 thiết kế + 10 giữ kín (chọn rải thương hiệu, cố định seed). Tham số chọn trên 30, báo số trên 10. Thêm video mới vào tập giữ kín khi có ca thật.

**Lỗ dữ liệu §1 — vá:**
- **Video gốc bị xoá khi job `xong`** (đã kiểm: `web/thay_logo_worker.py:363-367` `_ket_thuc` xoá thư mục scratch).
  - ⇒ Tạo ca KHÔNG chép từ scratch. Worker tải lại từ nguồn `tl_job_video.nguon` (`{"kieu":"drive","file_id":…}`, đã kiểm `hang_doi.py:59`) trong luồng nền, không trong HTTP handler.
  - Nguồn tải lên tay (không Drive): giữ `goc.mp4` thêm N ngày khi job `xong` — câu hỏi Q2.
- **Không lưu khung của `sau.jpg`** (đã kiểm: `xu_ly_video.py:114` `chi_so` không ghi DB).
  - ⇒ Thêm cột `tl_video.khung_anh` + trả qua API.
  - Cho người chấm chọn "giây" khác (ô số / thanh trượt) khi lỗi thấy ở chỗ khác trong video.
- **Toạ độ click:** ghi dạng tỉ lệ 0–1 theo ảnh hiển thị; quy đổi về WxH gốc (`tl_video.kho`) khi tạo ca. Có test quy đổi.
- **`ca.jsonl` phải đủ để chạy lại y hệt:**
  - sha256 video gốc;
  - box agy (`tl_box_moi` kèm `nhan_agy` / `cum`);
  - `man_ket_agy`;
  - sha mã lúc chạy;
  - cờ env (`THAY_LOGO_DE_KHI_BIET` …).
- **Video `cho_nguoi`:** route chấm chỉ nhận `xong`.
  - ⇒ Giai đoạn này chỉ chấm video đã xuất (giữ đúng phạm vi).
  - Ca `cho_nguoi` lấy từ "Bỏ qua" sẵn có: ghi nhận, chưa thành ca kiểm.

**Thứ tự mới (agy):** `B0 → B1 → B4 → B2 → B3 → B5`. B4 (thử F1a / F1b trên bộ đề) chỉ cần B1, nên học sớm xem vòng có tác dụng không trước khi sửa DB / FE / worker.
Nghiệm thu thêm:
- **B1:** đột biến làm `bo-de-thay-logo.sh` phải trả rc ≠ 0 khi vi phạm luật lên.
- **B2:** test quy đổi toạ độ 0–1 → WxH + đọc được dữ liệu cũ.
- **B3:** tạo ca bằng tải lại từ Drive rồi chạy bộ đề trên ca đó.
- **B4:** v13#63 còn đè và che hết "AI".

**Câu hỏi user thêm:** Q4 — giữ `goc.mp4` của job tải lên tay thêm N ngày (đề xuất 7) để kịp chấm Hỏng → thành ca?

**Agy nói sai (claude kiểm, bác):** "sổ know-how ghi `relay_agy.py` + lọc skai / storyfy" — grep `relay_agy|skai|storyfy` trong sổ = 0 dòng; dòng 74 của sổ ghi đúng `_la_logo_nha` (#98) lọc "astronex".
