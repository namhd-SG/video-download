# Brainstorm cải tổ "Thay logo" — UX/UI + hướng lõi (23/10/2026)

Lane logo tk3 d8c695a4. Theo ĐP 23/10 11:2x, từ câu user 11:21: *"chỗ lane thay logo tôi cần research, brainstorm để cải tổ lại UX/UI và
hướng mới chứ hiện tại còn nhiều lỗi quá và cảm giác chưa thực sự ổn để đưa vào vận hành"*. **Chưa code.** Chờ agy PHÁN → ĐP → user.

Vật liệu (đều trong `plans/reports/`):
- Hiện trạng lỗi từ nguồn: `hien-trang-261023-1125-thay-logo-loi-va-phan-nan.md` — 78 vấn đề (A thuật toán 31 · B luồng/UX 23 · C vận hành 24), mọi dòng có file:dòng; bảng thước đạt gắn phiên bản.
- Vòng UI thật trên prod: `thay-logo-ui-261023/vong-ui-that.md` + 6 ảnh.
- Research ngoài: `researcher-261023-1135-thay-logo-cai-to-cong-cu-va-ux.md`.
- Mock luồng đề xuất: `brainstorm-261023-thay-logo-cai-to/mock-luong-moi.html` (mở: `open <đường>`), ảnh chụp `mock-1-lo.png`, `mock-2-sua.png`, `mock-3-hoi.png`.

## 1. Bức tranh (đã đo — số nào cũng có phiên bản)

- **Bản đang chạy prod = C (#100, 061417c)**: user chấm 40/40 chỗ đè thêm đúng (UQ:1403). Tỉ lệ đạt CẢ VIDEO của bản C: **chưa đo** (lượt bộ đề B1 đang chạy là nền). Trên 23 video đối thủ đã xuất của bộ đề: còn 740 khung lộ có toạ độ + 717 khung máy mất dấu; 14/40 video không xuất (gồm v26 không có logo — đúng; v20 badge Google Play).
- **Luồng UI duyệt/chấm trên prod chưa được dùng** (3 lượt Test, 0 chấm); việc thử của user đi qua bộ đề và chạy thử.
- Gốc rễ nhóm B (UX), quan sát được trên prod: (1) máy bỏ cuộc thì người không cứu được — chỉ có "Bỏ qua"; (2) duyệt cả video bằng 1 khung; (3) **không có đường sửa** (không kéo/vẽ box, không chỉ chỗ logo); (4) 1 trang làm 4 việc; (5) không báo máy đang tắt/chờ (lượt 19/10 chờ ~10 giờ — đo ra là cửa sổ dời máy, worker cố ý tắt); (6) Thư viện không ảnh xem trước.
- Gốc rễ nhóm A (thuật toán): bám vết bằng NCC trên logo **chữ mờ, trong suốt, trôi, chồng phụ đề** ⇒ mất dấu, lệch mép (vd v13 khung 63 lộ chữ "AI" bên phải ô ASTRONEX — ảnh thật trong mock màn 2). Research ngoài: **không có số đo độc lập** nào của công cụ ngoài cho đúng loại logo này; SAM2 đo nội bộ 21/10: Learna thật 0/16.
- Cách trình quyết định cho user cũng là vấn đề: user hỏi lại "là sao?" 4 lần (UQ:1317, 1335, 1347, 1410).

## 2. Ba hướng

| | H1 — Giữ lõi, làm lại UX "người trong vòng" | H2 — H1 + đổi BỘ DÒ cho logo chữ (dò từng khung) | H3 — Đổi lõi sang mask (SAM) + inpainting |
|---|---|---|---|
| Ý chính | Máy làm như nay; mọi chỗ máy không chắc / lệch hiện ra theo thời gian để người sửa bằng 1–2 thao tác, máy chạy lại đoạn đó | Logo dạng chữ (Learna, Barry…) dò lại MỖI khung bằng nhận dạng chữ chạy tại máy (Apple Vision / PaddleOCR) ⇒ không còn "mất dấu"; icon giữ NCC | Người click logo, SAM bám mask, model inpaint xoá hẳn logo cũ, rồi đè logo mới |
| Sửa loại lỗi nào (mục 1) | B: (1)(2)(3)(4)(5)(6). A: gián tiếp — người sửa đoạn lệch/lộ; không giảm lỗi máy | A: mất dấu, trôi, lệch mép chữ (box OCR ôm đúng chiều dài chuỗi) — **nếu** OCR đọc được chữ mờ. Cộng toàn bộ B của H1 | A về lý thuyết; thực tế SAM2 đã 0/16 trên Learna ⇒ mask sai thì **xoá nhầm nội dung** |
| Công sức (ƯỚC) | ~1,5–2 tuần: trang Lô + dải thời gian (dữ liệu có sẵn trong `track.json.gz`: detected/filled/hidden) + màn Sửa (kéo box, chạy lại đoạn) + xem 2 giây trong trang. Kongming 20/10 ước riêng phần canvas 3–4 ngày | Thử ½ ngày trên 4 video Learna (4/5/13/16) trước; đạt thì thay phần định vị ~1 tuần | Không ước được: chưa có số MPS cho inpainting; DiffuEraser cần 12–33 GB VRAM CUDA; giấy phép ProPainter/DiffuEraser/CoTracker là phi thương mại |
| Rủi ro lớn nhất | Giờ người mỗi lô CHƯA ĐO — logo trôi liên tục có thể cần nhiều lần sửa/video | Chữ mờ/trong suốt dưới ngưỡng OCR (chưa có số); phụ đề bị dò nhầm; không áp cho icon | Xoá nhầm nội dung; nhấp nháy; API (Bria $0,14/giây, < 5 giây/lần) phải **gửi video ra ngoài** |
| Đo bằng bộ đề B1 | Lõi không đổi ⇒ bộ đề phải ra 0 khác (đối chứng). Đo thêm: thời gian người / 10 video giữ kín | Chạy nhánh OCR qua bộ đề: khung lộ có toạ độ, khung mất dấu, "prod đúng mà nhánh sai" = 0, 40 khung nhãn `dung` không hỏng | Như H2, nhưng render đổi ⇒ toàn bộ là khung đổi ⇒ phải soi người ≥ 20 mẫu |
| Vòng tự cải thiện nằm ở | Mỗi lần người KÉO BOX = 1 nhãn khung có toạ độ (thay cho "Hỏng + ghi chú gõ tay") ⇒ tự vào kho ca ⇒ bộ đề lần sau có ca đó | Như H1 + nhãn người dùng để chỉnh ngưỡng OCR / danh sách chuỗi logo | Như H1, nhưng nhãn là mask — đắt hơn để tạo |

## 3. Đề xuất (để agy phán, chưa phải quyết)

**H1 làm trước, song song một phép thử ½ ngày của H2; H3 không làm lúc này.**
- H1 giải đúng chỗ user đang kẹt (luồng chưa dùng được), không đụng lõi đã được user chấm 40/40, và biến mỗi lần người sửa thành dữ liệu cho vòng tự cải thiện — đây là cách "tool tự học" có thật với lượng dữ liệu ít.
- H2 là đòn bẩy cho nhóm A nhưng là **giả thuyết** — quyết bằng số trên bộ đề sau ½ ngày, không bằng lập luận.
- H3: bằng chứng hiện có đều ngược (SAM2 0/16 Learna, giấy phép NC, không số MPS, API gửi video ra ngoài). Giữ trong danh sách theo dõi.

## 4. Yêu cầu UX rút ra (áp cho mọi hướng)

1. **Trình theo việc cần làm**: trang Lô sắp video theo số đoạn cần người; video máy chắc gom một nhóm, soi nhanh 3 ảnh phóng to cho TẤT CẢ video trong nhóm (không chọn mẫu) rồi duyệt cả nhóm.
2. **Dải thời gian theo độ chắc** (xanh/vàng/đỏ/xám) cho mỗi video; bấm đoạn đỏ nhảy tới khung. (Research: chưa sản phẩm nào có — thiết kế của ta.)
3. **Sửa tại khung lệch đầu tiên**: kéo/kéo góc box ⇒ "Máy làm lại từ đây" ⇒ xem 2 giây ⇒ Đúng (mẫu Premiere / DaVinci Magic Mask).
4. **Máy không chắc ⇒ "Chỉ chỗ logo"**: người vẽ 1 box trên 1 khung, máy làm phần còn lại — thay ngõ cụt "Bỏ qua".
5. **Ô phóng to vùng logo** luôn hiện cạnh khung (khung nhỏ không đủ để thấy lộ mép — chính mock đã gặp).
6. **Xem 2 giây trong trang**, không bắt mở Drive.
7. **Trạng thái máy nói lý do**: "máy đang tắt / đang chờ máy khác / đang làm video 3/40".
8. **Mọi lựa chọn trình user phải có ảnh thật trước/sau + 1 câu hệ quả + số đếm, KHÔNG dùng mã nội bộ** (F1, L2, B4…) — từ 4 lần "là sao?" (ĐP 23/10).

## 5. User đã trả lời (23/10 11:44, gõ thẳng pane lane logo d8c695a4; ĐP đã ghi USER-QUYET)
1. Sửa tay = **khoanh chỗ logo bị lộ để tool tiếp tục fix** ⇒ phương án A "Khoanh chỗ lộ" là mặc định của màn Sửa.
2. Phút duyệt/lô: **"thử đã"** ⇒ đo thật trên 10 video giữ kín khi có nguyên mẫu, rồi mới hỏi con số.
3. Gửi video ra dịch vụ ngoài: user chưa hiểu ⇒ đã giải thích bằng 2 phương án (mặc định chỉ trên máy công ty / Bria ~$0,14/giây ⇒ 30 giây ≈ $4,2, video rời công ty, chưa ai đo trên logo chữ mờ). Chưa có câu trả lời; mặc định A.
User xin thêm: vài phương án + tổng quan cả tool ⇒ `mock-tool-tong-quan.html` (5 màn, 3 phương án sửa, chú thích khi rê chuột).

## 5b. Sửa sau agy R1b (MỞ) — `~/agy-ws/exchange/thay-logo-cai-to-R1b-agy.md`
- **ĐK4 — mock tô sai**: v13 khung 63 máy ghi `detected` ⇒ dải độ chắc hiện XANH, không phải đỏ. Mock v1 vẽ đỏ = tô hồng khả năng tự phát hiện. Đã sửa mock v2: v13 ghi "vàng — máy cảnh báo vì ô đè chồng phụ đề" (đề xuất lớp 1, CHƯA ĐO có bắt được thật không). Thêm 2 lớp bắt lỗi "xanh giả": dải 3 ảnh phóng to cho TẤT CẢ video máy chắc (không chọn mẫu 6/31), và dòng "6 video máy cho là không có logo" để người xác nhận (máy từng bỏ sót chữ "CO" mờ).
- **ĐK2 — video gốc bị xoá khi job xong** (`web/thay_logo_worker.py:363-367` `_ket_thuc`, đã kiểm 23/10) ⇒ "máy sửa tiếp" cần giữ `goc.mp4` trên ca-n tới khi đóng lô + bản nháp 2 giây. Đưa vào thiết kế H1.
- **ĐK1 — Pha 0 trước khi khoá màn Sửa** (≤ ½ ngày, chờ ĐP gật): (a) đếm phân phối số đoạn đỏ/vàng mỗi video từ `track.json.gz` của lượt bộ đề (đo được ngay khi lượt 061417c xong); (b) thử OCR Apple Vision trên v4/v5/v13/v16 (+ v22, v29).
- **ĐK3 — OCR đọc hụt chữ**: trong phép thử đo cả tỉ lệ đọc "Learna" mà rớt "AI" (đúng kiểu lỗi v13#63) và lọc vùng phụ đề.
- **ĐK5 — câu hỏi user**: mock v1 màn 3 hỏi lại việc đè phụ đề user đã chốt ⇒ đã BỎ ở mock v2; màn 4 chỉ còn câu đang mở (gửi video ra ngoài) có số tiền + hệ quả. Câu 1 cũ trùng việc khoanh tay user đã chốt ⇒ user vừa trả lời lại cùng hướng (khoanh).

## 5c. Kết quả Pha 0 (ĐP gật 11:5x; đo 23/10, script + JSON cùng thư mục: `pha0-*`)

**(a) Đếm đoạn trên lượt C** (= 061417c: so 0 khác, md5 0/40) — 26 video xuất:
- Đỏ (máy biết lộ): 81 đoạn / 1457 khung; 10/26 video 0 đoạn đỏ (9/26 nếu tính cả vàng 'đè dù chặn' — agy R3b bắt, đã kiểm); v4 riêng 585 khung, v15 19 đoạn.
- Vàng "đè dù cổng nội dung chặn": 36 đoạn / 336 khung — bắt được 2/2 ca lỗi biết (v13#63, v22#407) nhưng báo cả 40/40 khung user chấm đúng (tập nhãn lấy mẫu từ chính loại khung này ⇒ tỉ lệ báo oan thật CHƯA ĐO).
- Nội suy (filled): 789 đoạn / 3942 khung ⇒ nếu tô vàng: trung vị 20 đoạn/video, max 188 ⇒ **KHÔNG tô vàng nội suy**.
⇒ Dải màu pha 1: đỏ = máy biết lộ; vàng = "đè dù bị chặn — nên liếc"; không có màu cho nội suy. Khả năng phát hiện đè lệch: CHƯA ĐO ngoài 2 ca.

**(b) OCR Apple Vision trên máy dev** (venv riêng trong scratch, không cài toàn máy; 60 khung rải đều/video + 18 khung có nhãn):
- Khung thường: thấy chữ logo ở Learna v4 29/60 · v5 22/60 · v13 42/60 · v16 50/60; Barry v22 15/60; **"CO" v29 0/60**. Đọc "AI" thành "al"/"aa" (vd `learnaal`). Tốc độ 138–339 ms/khung trên máy dev.
- **Khung khó (khung có nhãn — chính là khung cổng nội dung chặn): thấy 2/18** (v13#7347 chỉ "learna", v22#407 đủ "barry"). v13#63 (ca lộ "AI"): KHÔNG thấy. v4 6 khung nhãn: 0/6.
- **Dò nhầm phụ đề**: v5#1008/1010 (khung KHÔNG được đè) OCR khớp "learna" trong câu phụ đề "i'm on learna al, and i'm" ⇒ cần lọc phụ đề, nếu không sẽ đè nhầm.
- (Lỗi đo của tôi: tiêu chí "đọc đủ chuỗi" dùng `learnaai` nên đếm sai; đã thay bằng ví dụ chuỗi. Không đổi kết luận.)
⇒ **OCR không cứu được đúng những khung khó** (2/18), không đọc được logo mờ "CO", và dễ dò nhầm phụ đề nói tên app. H2 KHÔNG làm lõi thay thế. Có thể dùng sau làm tín hiệu PHỤ để bắt lại vết (khung thường 37–83% Learna) — chưa cần ở pha 1.

## 6. Chưa xác minh / câu hỏi mở
- Công sức H1/H2 là ƯỚC; giờ người/lô chưa đo.
- OCR trên chữ mờ trong suốt: chưa có số (thử ½ ngày mới biết).
- `tl_video.bat_dau` của job 19/10 là 20/10 09:09 trong khi worker ca-n chỉ bật 10:18 — chưa truy (có thể chạy tay).
- Dải màu trên mock là MINH HOẠ; dữ liệu thật lấy từ `track.json.gz` (cần dựng lại endpoint — hiện chưa có endpoint phục vụ track).
