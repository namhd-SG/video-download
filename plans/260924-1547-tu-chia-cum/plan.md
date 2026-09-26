---
title: "Tự chia cụm sau lượt tải + lọc ngoài chủ đề"
description: "Hệ đề xuất nhóm→kiểu cho mỗi lượt tải dưới dạng NHÁP; user gộp/đổi tên/duyệt; duyệt xong mới thành cụm thật (#13)."
status: pending
priority: P1
effort: "~4 ngày, 5 PR"
tags: [video-desk, cum, vision, agy]
created: 2026-09-24
---

# Tự chia cụm sau lượt tải + lọc ngoài chủ đề

## Overview

Đề bài user 24/09 10:31 (`~/plans/USER-QUYET.md`): *"bạn tự phân tích và chia ra cụm … tôi vẫn sẽ sửa được … lọc luôn được những video không liên quan"*.
Thiết kế đã chốt, KHÔNG mở lại ở đây: `~/plans/260924-1031-tu-chia-cum-video-desk/brainstorm.md` + `mock-tu-chia-cum-v1.html` (vòng agy `tu-chia-cum` KHÉP R8, kongming `~/plans/reports/kongming-260924-1212-tu-chia-cum-video-desk.md`, ĐP duyệt mock 15:39 kèm 3 điều kiện).

Nền đã LIVE: #13 (cụm + bàn giao lô 30, hợp đồng `nhan`) · #15 (lúc tải lưu khung 50/90 % + `description`/`track`/`artist`).

## Quyết định đã chốt (nguồn)

| # | quyết định | nguồn |
|---|---|---|
| D1 | Chia 2 tầng nhóm → kiểu, sinh THEO LƯỢT (không enum toàn cục) | R5-R8, lượt mù 5/5 cùng nhóm |
| D2 | Mặc định trục = trang phục ĐÁM ĐÔNG; user đổi được | R7 (10) |
| D3 | Ảnh ghép 2–3 khung ⇒ theo khung trội, thẻ vẫn gắn "ghép N" | user Q2 15:26 |
| D4 | Thẻ chữ hướng dẫn ⇒ kiểu riêng "Hướng dẫn" | user Q3 |
| D5 | Usecase/insight gốc hỏi lúc tạo job, không bắt buộc; trống ⇒ hỏi lúc duyệt | user Q4 |
| D6 | Tầng hình chạy NGOÀI mini (máy dev, agy vision), user bấm tay; KHÔNG 24/7 | user Q5; phép đo qwen mini (swap +3 169 MiB) |
| D7 | Nháp chặn ở SERVER **thật**: `nhan` (thứ mang tên kiểu sang taxonomy) chuyển sang dựng ở SERVER — `GET /cum/{id}/lo/{thu}/payload` chỉ nhận cụm thật; JS chỉ `window.open` chuỗi server trả. Bàn giao chọn tay (không `nhan`) giữ nguyên — không ghi tên nào vào taxonomy | ĐP điều kiện (i); agy kehoach-R2 câu 2 (payload + `nhanTuCum` dựng ở client, `app.js:910,919,1133`) |
| D8 | Nhật ký thao tác sửa từ lượt đầu (= phép nghiệm thu) | ĐP điều kiện (ii) |
| D9 | "Chưa phân tích hình" ⇒ KHÔNG tạo cụm giả, kể cả từ caption | ĐP điều kiện (iii) |
| D10 | Hợp đồng `nhan` sang Creative Desk KHÔNG đổi | kongming Q4-Q5 |
| D11 | Duyệt = `models_cum.tao_cum` (trùng tên ⇒ trả cụm có sẵn) + `gan_video` (chuyển) ⇒ "gộp vào cụm có sẵn" không cần API mới | đọc nguồn `models_cum.py:161-229`; ĐP-16 |
| D13 | Duyệt mà tên trùng một cụm CÓ SẴN ⇒ server trả danh sách `trung_cum_co_san` và KHÔNG gộp, trừ khi request mang `xac_nhan_gop: [cum_id…]` | agy kehoach-R2 câu 1 |
| D14 | Video đã nằm trong một cụm thật của người đó KHÔNG bị chuyển bởi DUYỆT, ở CẢ HAI chỗ: (a) `ghi_de_xuat` không đề xuất lại nó; (b) `duyet_kieu`/`duyet_het` kiểm LẠI ngay trong transaction duyệt và bỏ qua video đã có cụm (trả `da_o_cum`), vì hai nháp song song có thể cùng chứa một video lúc sinh. Chỉ thao tác kéo tay mới chuyển (luật "một video một cụm") | agy kehoach-R2 câu 5 + R4 lỗ mới 1; `models_cum.py:226` |
| D15 | Nghiệm thu = **số dòng nhật ký** (mỗi bấm = 1) so với mốc chia tay = số video phải gán tay; báo kèm `SUM(so_video)` riêng, không cộng hai số | agy kehoach-R2 câu 3 |
| D16 | Tên cụm khi duyệt = "<insight gốc> <kiểu>" (user chốt 23/09 15:58). CHỈ khi hai kiểu trong CÙNG lượt trùng TÊN CUỐI (casefold+strip, tên sau khi đã ghép nhóm) mới chèn nhóm: "<insight gốc> <nhóm> <kiểu>"; tên vừa ghép trùng tên cuối của kiểu thứ ba ⇒ kiểu đó cũng ghép, lặp tới khi hết (có trần). Va chạm còn lại khi mọi kiểu dính vào đã ghép nhóm (biến thể hoa/thường cùng nhóm; hai tên ghép trùng nhau) ⇒ giữ nguyên, lúc duyệt tự gộp một cụm. Không bao giờ hỏi gộp vào cụm vừa tạo trong cùng lượt duyệt | QUYẾT ĐP 18:51 (ĐP-21), user bác được; review M1; điều phối 26/09: so tên cuối |
| D17 | Chỉ NGƯỜI TẠO job được chia/sửa/duyệt nháp; admin chỉ XEM | QUYẾT ĐP 18:51 (ĐP-21), nối user chốt 23/09 14:29 "cụm riêng từng người"; review M2 |
| D18 | Duyệt khi `usecase`/`insight_goc` trống (cả body lẫn lượt) ⇒ 400 cho CẢ `duyet_kieu` lẫn `duyet_het`, cùng mã lỗi — insight thuộc cả lượt, không dồn vào `loi_ten` | QUYẾT ĐP 00:24 25/09 (ĐP-23), user bác được; review lượt 2 N2 |
| D19 | Tên cụm (kể cả luật chèn nhóm, so casefold + chuẩn hoá khoảng trắng) tính cho mọi kiểu MỘT lần lúc `ghi_de_xuat` và lưu trong nháp (`ten_cum`). Sau đó CHỈ `doi_ten` tính lại, và chỉ cho hàng bị đổi + hàng va chạm tên với nó; duyệt/gộp/xoá/chuyển chỉ đọc; `hoan_tac` trả lại đúng tên cũ lưu trong nhật ký. Lúc duyệt KIỂM LẠI va chạm với bảng cụm THẬT ⇒ trùng thì trả hỏi gộp như D13, KHÔNG tự đổi tên | QUYẾT ĐP 00:24 25/09 (ĐP-23); review lượt 2 N6; điều phối 26/09: chỉ tính lại khi đổi tên |
| D12 | v1 KHÔNG có nút "Chạy phân tích hình" trên UI: trạng thái hiện lệnh máy dev in sẵn (copy được); script mặc định xử MỌI lượt chưa phân tích, `--luot <id>` để chọn. Hàng đợi yêu cầu để v2 | QUYẾT ĐP 15:52 (ĐP-16), user bác được: "nút không tự chạy được gì là nút nói dối" |

## Phases

| # | Phase | PR | Phụ thuộc | Status |
|---|-------|----|-----------|--------|
Thứ tự THI CÔNG (sửa theo agy kehoach-R2 câu 4, 6): **1 → 5 → 2 → 3+4**. Số phase giữ để khỏi đổi tên tệp.

| # | Phase | PR | Phụ thuộc | Status |
|---|-------|----|-----------|--------|
| 1 | [Bảng nháp + nhật ký + đường duyệt duy nhất + payload `nhan` ở server](./phase-01-nhap-nhat-ky-chan-server.md) | p1 | — | Pending |
| 5 | [Ô usecase/insight gốc lúc tạo job](./phase-05-o-insight-luc-tao-job.md) | p2 | 1 | Pending |
| 2 | [Tầng hình: nhãn vision + chuẩn hoá 2 tầng (máy dev) → ghi nháp qua ssh](./phase-02-tang-hinh-nhan-va-chuan-hoa.md) | p3 | 1, 5 | Pending |
| 3+4 | [UI nháp](./phase-03-ui-nhap-gop-duyet.md) **cùng** [làn thẻ chữ + làn nghi](./phase-04-lan-the-chu-va-nghi-ngoai-chu-de.md) — một PR | p4 | 1, 2 | Pending |

Vì sao: phase 2 đọc `insight_goc` của lượt (phase 5 tạo); UI ship thiếu hai làn thì video ở làn `huong_dan`/`nghi` nằm trong DB mà không hiện, và "Duyệt tất cả" xử lý mù.

## Success Criteria (của cả kế hoạch)

- [ ] Lượt tải thật kế tiếp (~100 video): hệ đề xuất nháp; user duyệt xong; báo **số dòng nhật ký** (D15) so với số video phải gán nếu chia tay, kèm `SUM(so_video)` tách riêng. Không có ngưỡng đặt trước.
- [ ] Không đường nào đưa một video của nháp sang Creative Desk khi chưa duyệt (test đột biến ở server).
- [ ] Tầng hình vắng ⇒ UI "Chưa chia cụm", 0 hàng nháp.
- [ ] #13 và hợp đồng `nhan` không đổi hành vi (toàn bộ test cụm cũ xanh).

## Rủi ro chung

- **agy báo rc=0 cả khi trượt** (luật đã đo): mọi lượt agy nghiệm thu bằng tệp đích + đếm id, không bằng mã thoát.
- **n=1 lượt dữ liệu**: chuẩn hoá có thể tệ ở lượt khác ⇒ đó là lý do nháp + nhật ký; không tối ưu prompt theo 5 mẫu.
- **Taxonomy prod**: chỉ cụm đã duyệt mới có `cum_id`; Creative Desk còn cổng 2 (term tạo lúc submit).

## Câu chưa chốt

- Trình duyệt user dùng cho Video Desk: CHƯA ĐO (hỏi khi user nghiệm thu mắt). Bàn giao đã đổi sang mở tab đồng bộ nên không phụ thuộc trình duyệt (ĐP-21).

- Không còn. (Câu nút tầng hình ⇒ D12.) Ghi nhận: poster/khung gửi agy rời máy (Google) — chỉ video TikTok công khai, không data khách (ranh giới R1).

<!-- slug: tu-chia-cum -->
