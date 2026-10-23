# Plan: trường nhận dạng TREND cho máy chấm · 23/10/2026 (tk3)

Status: NHÁP — số đo offline xong; chờ ĐP ⇒ (nếu cần) agy phán ⇒ thi công. Nền code: `94a7e22`.

## Vấn đề (đo, có thước người)
Bộ đề `tests/kho_ca/tim_trend/ca3-coldplay-kiss-cam.json`: 57 thẻ, nhãn user (23/10 14:37, 57/57, 0 ranh giới).
Máy hiện tại (giữ ⟺ hạng ∈ {3, 2A}) khớp user **38/57**: 14 dương tính giả (idol K-pop/LED, sân khấu phông xanh,
đám đông, "xoay tròn") + 5 âm tính giả. Gốc: chữ ký dạng "1 người · sân khấu · hành động khác" không mang gì về TREND —
mọi ảnh concert có người đều khớp.
Định nghĩa user (sổ know-how mục 6): đúng trend = MÀN HÌNH CONCERT (thật hoặc AI dựng) chiếu người vào.

## Số đo offline (0 quota: chỉ dùng caption + trường agy đã có trong bộ đề)
Tên trend lấy từ hồ sơ trend lập TRƯỚC lần chạy (`~/plans/kien-thuc/ho-so-trend-ca3-coldplay-kiss-cam.md`, 10:32:
"kiss cam", "Coldplay") ⇒ không phải chọn sau khi xem nhãn.

| luật | khớp user | B giữ (17 thẻ user 17/17 đúng) |
|---|---|---|
| R0 máy hiện tại | 38/57 | 17/17 |
| caption chứa tên trend (một mình) | 51/57 | 17/17 |
| **R1 caption chứa tên trend VÀ agy đọc nền `san_dien`** | **52/57** | **17/17** |
| máy giữ VÀ caption chứa tên trend | 50/57 | 17/17 |
| máy giữ HOẶC (caption VÀ sân diễn) | 40/57 | 17/17 |
| mô tả agy chứa "tròn/circle" (một mình) | 48/57 | — |

R1 còn sai 5: dương tính giả 1 (template tròn phông xanh — agy đọc nền sân diễn); âm tính giả 4 (Trump–Putin và "how to
do this" agy đọc nền studio; 2 caption không có tên trend, 1 là ES "pantalla gigante del concierto").

## Đề xuất thi công (chưa làm)
1. **Trường mới `ten_trend`** cho mỗi lần chạy: danh sách cụm tên trend (đa ngôn ngữ) lấy từ (a) `--ten-trend` người đưa
   (từ hồ sơ trend) hoặc (b) caption của ứng viên hạng 3 lượt đầu (vòng 2 — đúng ý user "key thành công ⇒ AI phân tích").
2. **Cổng trend**: khi có `ten_trend`, ứng viên chỉ được giữ khi caption (hoặc chữ OCR) chứa ≥1 cụm VÀ ảnh qua cổng bối
   cảnh của chữ ký (nền). Không có `ten_trend` ⇒ hành vi cũ (Ca 1/Ca 2 dạng cấu trúc vẫn chạy như trước).
3. Giữ nguyên cổng ctrl; ghi lý do loại "không có tên trend trong caption" vào `ket-qua.json` + trang (để user chấm lại).
4. Nghiệm thu: script chấm lại bộ đề offline ⇒ ≥ 52/57 và B 17/17; test đột biến (bỏ cổng trend ⇒ về 38/57).

## Rủi ro / chưa đo
- **1 video, trong mẫu (in-sample)**: luật đo trên chính bộ đề nó sẽ được chấm ⇒ cần ca thứ 2 trước khi coi là luật.
- Caption là chữ người đăng tự viết: trend không có tên rõ (hoặc caption trống) ⇒ recall tụt. Ca 1 (7 pose) tên trend
  bản địa "kolase" ⇒ cần đa ngôn ngữ, đúng như bài học Ca 1.
- 12 ứng viên B bị máy loại chưa đưa user chấm ⇒ recall thật chưa đo.
- Cổng nền dựa trên agy đọc `loai_nen` — đã thấy agy lệch nền theo lô (ca B sáng 23/10) ⇒ lỗi lệch lô giờ ảnh hưởng thêm
  cổng trend; cổng ctrl vẫn bắt lô lệch.

## Câu cho agy (chỉ khi ĐP thấy cần)
- R1 dựa vào caption: có cách nào phá được "bảo đảm theo từng link" của cổng ctrl không (ctrl là khung video mẫu, không có
  caption ⇒ cổng trend phải bỏ qua ctrl)?
- Nguồn `ten_trend` tự động (caption hạng 3 lượt đầu) có tự khuếch đại sai (vòng phản hồi) không?

## ĐĂNG KÝ TRƯỚC phép thử ngoài mẫu (ghi 23/10 ~14:5x, TRƯỚC khi user chấm ca 1 + ca 2)
ĐP chọn (b): kiểm R1 trên ca 1 (7 pose, `pha4b-v1`, 80 ứng viên) + ca 2 (catwalk, `pha4b-v2`, 103 ứng viên) — dữ liệu Pha 4
sẵn có, 0 lượt TikTok. User chấm TOÀN BỘ ứng viên (không chỉ link giữ) để đo được cả recall.

Luật cố định, không sửa sau khi thấy nhãn:
- **R0** giữ ⟺ hạng máy ∈ {3, 2A}.
- **R1** giữ ⟺ caption (bỏ dấu, chữ thường) khớp regex tên trend VÀ `nhom_nen(loai_nen) == chu_ky.nen` (nền khớp chữ ký).
- Tên trend (lấy từ sổ know-how §2/§4 + truy vấn đã chạy ở Pha 4, có từ 22–23/10, KHÔNG từ nhãn):
  - ca 1: `pose|kolase|collage`
  - ca 2: `catwalk|runway|pasarela|passarela|desfile`
  - ca 3 (đã đo trong mẫu): `kiss ?cam|coldplay`

Dự đoán ghi trước (để không tự chấm): R1 có thể **gãy ở ca 2** vì luật hạng hiện tại coi catwalk là cổng cứng còn nền chỉ
phụ (sàn diễn/phố/studio đều tính) — R1 lại bắt nền khớp chữ ký. Nếu gãy đúng chỗ này ⇒ cổng nền phải theo luật của chữ
ký (bỏ nền khi chữ ký có hành động cổng), không phải bỏ R1.
Tiêu chí đạt: R1 khớp user ≥ R0 ở CẢ ca 1 và ca 2, và không giảm số link đúng (TP) quá 10% so với R0 ở ca nào.

## Kết quả ca 1 (user chấm 23/10 14:43, 80/80) + ĐĂNG KÝ TRƯỚC R2 cho ca 2 (ghi ~14:5x, TRƯỚC khi có nhãn ca 2)
- **R1 TRƯỢT tiêu chí ở ca 1**: khớp 71/80 < R0 77/80 (R1: TP 38 FP 8 FN 1 · R0: TP 37 FP 1 FN 2). Gốc: R1 BỎ cổng cấu trúc
  của máy; từ "pose" chung chung kéo vào video dạy vẽ dáng / anime / JoJo pose mà cổng bản sao vốn loại đúng.
  ⇒ R1 bị loại. Không sửa regex ca 1 sau khi thấy nhãn.
- Giả thuyết mới (sinh SAU khi thấy nhãn ca 1 ⇒ số ca 1 và ca 3 dưới đây là TRONG MẪU):
  **R2** giữ ⟺ R0 (hạng ∈ {3, 2A}) **VÀ** caption khớp regex tên trend — tên trend là cổng THÊM, không thay cổng ảnh.
  ca 1: 77/80 (TP 36 FP 0 FN 3) = R0 · ca 3: 50/57 (TP 32 FP 0 FN 7) vs R0 38/57.
- **Đăng ký cho ca 2** (ngoài mẫu thật, chưa có nhãn): R2 với regex ca 2 đã ghi ở trên (`catwalk|runway|pasarela|passarela|desfile`),
  không đổi. Tiêu chí đạt như cũ: khớp ≥ R0 và TP không giảm quá 10%.
- Dự đoán ghi trước: R2 giảm FP ở ca 2 (người thật/meme có caption không chứa "catwalk/runway") nhưng có thể mất TP ở
  caption chỉ ghi "AI model"/"fashion" — nếu TP giảm > 10% thì R2 trượt ở ca 2.
