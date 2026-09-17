# Tool tải video TikTok — checklist vận hành

Cập nhật 16/09/2026 11:59. Viết cho người dùng, không phải cho lập trình viên.
Mỗi dòng trả lời một câu: **team làm được gì rồi, và còn thiếu gì.**

---

## Hiện trạng — đo lúc 11:59 ngày 16/09

| | |
|---|---|
| Địa chỉ | `https://video.nobidigital.asia` |
| Đang chạy | ✅ dịch vụ sống, trả `200`, tự bật lại sau khi tắt |
| Chạy ở đâu | mac mini công ty, 24/7 |
| Ai vào được | người có tài khoản công ty (phải đăng nhập mới thấy) |
| Video lưu ở | Drive công ty (Shared Drive), mỗi lượt tải một thư mục riêng |
| Đã có trong thư viện | 10 video |
| Hàng xóm Promax | ✅ không bị ảnh hưởng |

---

## A. DÙNG ĐƯỢC RỒI — không cần làm gì thêm

- [x] Mở bằng trình duyệt, không phải cài gì trên máy cá nhân
- [x] Dán link TikTok (music / hashtag / tìm kiếm / trang cá nhân) → nhận video
- [x] Xem tiến độ từng lượt tải, biết lượt nào xong lượt nào lỗi
- [x] Bấm mở thẳng thư mục Drive của lượt tải đó
- [x] Máy mini không bị đầy đĩa — tải xong đẩy Drive rồi xoá ngay
- [x] Tắt máy / mất điện → dịch vụ tự lên lại
- [x] Vào được từ ngoài văn phòng (4G), vẫn phải đăng nhập
- [x] Người lạ không có tài khoản công ty → bị chặn ở cửa
- [x] Thư viện creative: xem lại mọi video đã tải, có ảnh xem trước
- [x] Lọc thư viện theo 6 tiêu chí (nguồn, khung hình, độ dài, thị trường, ngày tải, người tải)
- [x] Chặn tải quá 20 lượt / người / ngày (giờ Việt Nam)
- [x] Cùng một video xuất hiện ở hai lượt tìm khác nhau → không bị đếm trùng

---

## ⚠ ĐANG LỖI TRÊN BẢN THẬT — người dùng đang nhìn thấy

- [x] **Chữ gợi ý trong ô nhập quá mờ** — ĐÃ SỬA VÀ ĐÃ LÊN MINI lúc 12:14 ngày 16/09.
      Gốc: màu chữ gợi ý chưa bao giờ được đặt, nên nó rơi về xám mặc định của
      trình duyệt — màu đó tính cho nền sáng, còn ô nhập ở đây nền gần đen.
      Đo: trước 4,13:1 (dưới ngưỡng dễ đọc 4,5), sau **6,27:1**.
      Kiểm trên bản THẬT đang chạy, không phải bản trên máy dev: mã nguồn ba tệp
      giao diện lấy từ mini khớp y máy dev, Promax của người khác vẫn sống (302),
      dịch vụ vẫn trả 200. Ảnh: `/tmp/claude-502/anh/mini-sau-deploy-sang.png`

---

## B. ĐANG THIẾU — cản team dùng thật

### B1. Mỗi người một cookie TikTok *(quan trọng nhất)*

Hiện chưa tách cookie theo người. Chưa xong nghĩa là **chưa mở cho cả team dùng được**.

- [ ] Mỗi người tự dán cookie TikTok của mình, không dùng chung tài khoản — **CHƯA**, và đây là phần duy nhất còn lại của mục B1. Nó là trang 'Cookie của tôi', nằm ngoài phạm vi MVP theo chính kế hoạch (P05b). Hiện MVP dùng cookie của anh
- [x] Cookie của người A không lọt sang lượt tải của người B — XONG 16/09. Đo bằng cách bắt đúng tệp cookie đi vào lúc tải, không phải bằng cách tìm cookie trong nhật ký (tìm ở đó luôn rỗng, kể cả khi code sai)
- [x] Cookie hỏng / hết hạn → báo lỗi rõ ràng, không âm thầm tải ra kết quả rỗng — XONG 16/09. Phân biệt 4 ca: tệp đọc không được · không có cookie nào · **chưa đăng nhập** · hết hạn. Lượt tải DỪNG và ghi lý do, thay vì chạy tiếp như khách rồi báo 'xong' với ít video hơn hẳn
- [x] Cookie không bị ghi vào nhật ký hệ thống — XONG 16/09, đo trên nhật ký thật của mini (1 787 dòng): không có tên hay giá trị cookie nào. Kèm phép thử đối chứng để chắc là cách tìm có hiệu lực
- [x] Tắt đột ngột giữa chừng → không để sót cookie trên đĩa — XONG 16/09. Trước đây mỗi lần bị tắt cứng là để lại một bản cookie đọc được nằm vĩnh viễn; giờ dịch vụ dọn sạch mỗi lần khởi động

### B2. Nghiệm thu toàn hệ *(làm sau B1)*

- [ ] Hai người chạy cùng lúc → chạy tuần tự, không lẫn cookie
- [ ] Tải thật từ ngoài văn phòng, nhận được video thật
- [ ] Khởi động lại máy mini → dịch vụ tự lên *(máy này của người khác dùng chung — phải hẹn giờ)*
- [ ] Tải xong → đĩa mini sạch, link Drive mở được, số lượng khớp
- [ ] Promax của người khác không hề hấn gì trong suốt quá trình

### B3. Nối vào meta-auto

- [ ] Thêm một link trong thanh điều hướng meta-auto để người dùng tìm thấy tool

---

## C. ANH ĐÃ QUYẾT — 17/09 sáng

Bốn việc dưới đây trước đó đứng im vì thiếu câu trả lời. Anh đã trả lời cả bốn.
Ghi lại **nguyên ý anh chốt** + **cái giá kèm theo**, để không ai diễn giải lại.

### C1. Nút "Xoá" — ✅ ĐÃ CHỐT

**Anh chốt:** tải một mẻ về xong thì lọc lại, xoá những video không đúng insight mình cần.
Video nào mình nhấn tải là của mình, xoá không ảnh hưởng ai.

**Đã kiểm — cách hiểu này ĐÚNG với hệ thống:** thư viện chỉ hiện video **tải về thật**;
video bị bỏ qua vì trùng thì không vào thư viện của ai. Cộng với việc thư viện lọc theo
người ⇒ **mỗi video đúng một chủ**. Không có chuyện xoá của mình làm mất của người khác.

**Hai điều kèm theo, anh đã gật:**
- **Xoá = đưa vào Thùng rác Drive** (30 ngày, khôi phục được). Tài khoản máy chỉ có quyền
  tới đó, **không xoá vĩnh viễn được** — và không nâng quyền cho nó, vì khoá đó quản cả
  kho creative công ty.
- **Xoá rồi thì lần quét sau KHÔNG tải về lại.** Hệ thống phải nhớ "người này đã loại
  video này", nếu không thì tuần sau quét cùng hashtag là nó quay lại.

*(Bản cũ của mục này hỏi "xoá khỏi giỏ hay xoá trên Drive" — câu hỏi đó đặt sai, vì nó
giả định thư viện dùng chung. Giữ lại đây để không ai hỏi lại vòng nữa.)*

### C2. Trần tải — ✅ ĐÃ CHỐT

**Anh chốt:** tạm giữ **chặn theo lượt**, và **thêm trang Setting để anh tự đổi trần**.

**Ghi chú đo được:** hiện thực ra có **ba** trần cùng chạy — 20 lượt/ngày, 1000 video/ngày,
800 trang liệt kê/ngày — nên không phải chọn "lượt hay video", giữ cả ba.

⚠ **Một chỗ cần anh biết khi làm trang Setting:** trần mà người bị chặn tự nâng được thì
không còn là trần. Rủi ro thật là **TikTok chặn IP cả văn phòng**, mà cái đó không ai trong
team tự nới được. Nên chia hai tầng: trần chung toàn công ty (chỉ quản trị đổi) và trần
từng người (quản trị đặt, người dùng **xem** chứ không sửa).

### C3. Form "Thêm bộ tự tìm" — ✅ ĐÃ CHỐT

**Anh chốt:** **đồng bộ với Creative Desk** — form bên tool phải cho ra đúng bộ tự tìm như
bên meta-auto, chỉ khác là bên này có sẵn video.

**Không mâu thuẫn với quyết định cũ.** Bản cũ loại phương án *"chép danh mục theo lịch"*
vì nó lệch âm thầm. Anh nói "đồng bộ" theo nghĩa **luôn khớp**, không phải theo nghĩa
chép định kỳ. Hai điều này hợp nhau nếu tool **đọc sống** danh mục từ Creative Desk.

⚠ **Sửa một khuyến nghị sai trong chính tài liệu này:** bản cũ khuyên *"để trình duyệt gọi
thẳng meta-auto"*. Đường đó **cấu tạo không chạy** — meta-auto chỉ nhận danh tính qua
token nằm trong bộ nhớ của trang `automation.*`, trang `video.*` không đọc được. Đã có
bản thiết kế đường đúng (dùng service token qua Cloudflare Access) từ 15/09.

⏳ **Việc này về thời gian là dài nhất**: nó phải sửa cả repo meta-auto, mà cửa duyệt bên đó
hết lượt chạy tới khoảng 01/10.

### C4. Ai được xem toàn bộ hàng đợi? — ⏳ CÒN CHỜ ANH MỘT THỨ

**Anh chốt:** ai xem lượt của người đó. ✅ **Đã có hiệu lực trên máy thật lúc 10:33 ngày 17/09.**
Đo sau khi đưa lên: quản trị thấy 4 lượt, người dùng thật thấy đúng 1 lượt của chính họ.

⏳ **Còn thiếu đúng một thứ — cần anh:** danh sách email được xem **toàn bộ** hàng đợi
(vai quản trị). Hiện để trống nghĩa là **chưa ai xem được hàng đợi cả team, kể cả anh**.
Đặt vào tệp cấu hình trên mini rồi khởi động lại dịch vụ. Phần mã đọc danh sách này giờ
**đã nằm trên máy thật rồi**, chỉ thiếu giá trị.

⚠ **Còn một cửa hở chưa vá, không cần anh quyết:** danh sách hàng đợi đã lọc, nhưng trang
**chi tiết một lượt** thì chưa — ai đăng nhập cũng mở được lượt của người khác bằng cách
đổi số trên đường dẫn. Đã xác minh tại nguồn, đang xếp vào việc làm ngay.

### C5. Thư viện riêng từng người — ✅ ĐÃ CHỐT 17/09

**Anh chốt:** ai nhấn tải thì video đó của người đó; trên tool mỗi người **chỉ thấy video
mình đã tải**, cho đỡ rối. Nhưng **kho vẫn là một** (vẫn cùng Shared Drive), và khi đẩy
sang bộ tự tìm thì mọi người vẫn thấy bình thường.

**Lọc trùng giữ nguyên toàn kho:** video nào người trước đã tải thì lượt sau tự động bỏ qua,
không tải lại.

⚠ **Cái giá, anh đã biết:** người tìm sau sẽ nhận **ít video hơn** vì phần lớn đã có người
tải trước — và những video đó **không hiện ở đâu** trong thư viện của họ. Phải báo thẳng
trên lượt tải (*"bỏ qua N video đã có trong kho"*), nếu không họ sẽ tưởng nguồn cạn.

---

## D. ĐÃ BỎ — ghi lại để không ai làm lại

- [x] ~~Bổ sung video cũ vào thư viện~~ — **anh hủy 16/09**. Số thật là **4 video**, không phải 1074 như ba lần bàn giao trước ghi. File vẫn trên Drive, chỉ không hiện trong thư viện.

---

## E. Làm sau, chưa gấp

- [ ] Chép video sang Shared Drive của Creative Desk
- [ ] Phân tích nội dung video theo lô đã chọn
- [ ] Nút "Tìm thêm video giống cái này"

---

## Thứ tự đề nghị

1. **B1** — cookie từng người. Đây là thứ duy nhất chặn việc mở cho cả team.
2. **B2** — nghiệm thu toàn hệ, cần hẹn giờ vì phải khởi động lại máy dùng chung.
3. **B3** — thêm link trong meta-auto (nhanh).
4. **C1 · C2 · C3 · C4** — làm ngay khi anh trả lời, không phụ thuộc nhau.
   Riêng **C4** có ràng buộc thứ tự: đưa mã lên mini **trước**, đặt biến **sau**.
