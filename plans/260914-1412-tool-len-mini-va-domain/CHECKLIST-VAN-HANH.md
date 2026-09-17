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

## C. CHỜ ANH QUYẾT — 4 việc đang đứng im vì thiếu câu trả lời

### C1. Nút "Xoá" xoá cái gì? *(đã hỏi 4 lần, chưa có đáp)*

Thư viện dùng chung cả team. Hai nghĩa khác hẳn nhau:

- **Xoá khỏi giỏ** — chỉ bỏ khỏi danh sách đang chọn, video còn nguyên trên Drive
- **Xoá video trên Drive** — mất thật, và **mất của cả team** chứ không riêng người bấm

Chưa chọn thì chưa làm nút này được.

### C2. Chặn theo số lượt tải hay theo số video?

Hiện chặn **20 lượt/người/ngày**. Nhưng một lượt có thể xin tới 2000 video ⇒ **20 lượt vẫn là 40.000 video/ngày**.

Muốn bó lưu lượng thật thì phải chặn theo **tổng số video**, không phải số lượt. Cần anh cho một con số trần/người/ngày.

Lý do không tự chọn hộ: tải nhiều quá thì TikTok chặn **IP cả văn phòng**, không riêng tool.

### C3. Form "Thêm bộ tự tìm" lấy danh mục từ đâu?

Tool chạy ở địa chỉ riêng, không có phiên đăng nhập của meta-auto, nên chưa đọc được danh mục creative bên đó.

- **(a)** cấp một token máy dài hạn cho tool — phải giữ và bảo vệ token
- **(b)** để trình duyệt gọi thẳng meta-auto — *khuyến nghị*: ít mã hơn, không giữ token, và mỗi người chỉ thấy đúng phần mình có quyền
- **(c)** đồng bộ định kỳ — **đã loại**, vì dữ liệu sẽ lệch âm thầm

### C4. Ai được xem toàn bộ hàng đợi? *(cần anh cho danh sách email)*

Hiện danh sách admin trên mini (`VIDEODL_ADMIN_EMAILS`) đang **rỗng** ⇒ **chưa ai xem được
hàng đợi của cả team**, kể cả anh. Mỗi người chỉ thấy lượt của chính mình. Đây là mặc định
an toàn có chủ đích, không phải lỗi.

Cần anh: **danh sách email được xem hết**, để đặt vào `~/.config/videodl/env` trên mini rồi
khởi động lại dịch vụ.

⚠ **THỨ TỰ BẮT BUỘC — ĐƯA MÃ LÊN MINI TRƯỚC, ĐẶT BIẾN SAU.**
Đặt biến trước thì **không có tác dụng gì**, mà lại **trông y như đang hỏng** — sẽ mất công
đi tìm một lỗi không tồn tại.

Lý do, đo lúc **17/09 10:09**: đoạn mã đọc biến này nằm trong đúng bản **chưa** đưa lên mini.

```
grep -c ENV_ADMIN_EMAILS web/auth.py    →  máy dev: 2   ·   mini: 0
grep -c "def is_admin"   web/auth.py    →  máy dev: 1   ·   mini: 0
```

Bốn commit chưa lên mini: `2e5f31e` · `13000cc` · `eafb2bf` · `1c9c630`. Trong đó `13000cc`
mang **cả** quyền admin **lẫn** việc "hàng đợi chỉ thấy lượt của mình".

⇒ **Hệ quả thứ hai, đáng biết:** quyết định anh chốt 16/09 — *"/jobs chỉ thấy lượt của
mình"* — **chưa có hiệu lực trên máy thật**. Bản đang chạy vẫn liệt kê mọi lượt của mọi
người: hàm liệt kê trên mini **không có tham số lọc** (`SELECT * FROM jobs` trơn), trong khi
bản ở máy dev lọc theo người tạo. Đo 10:10 có **2 địa chỉ ngoài** đang mở trang.

Bán kính thật **nhỏ**: cả kho có **4 lượt tải**, mang **2 tên người tạo** — nhưng chỉ **một**
là người đã đăng nhập (1 lượt, 16/09); 3 lượt còn lại mang tên `khach`, tức từ trước khi nối
đăng nhập vào tool. Hai địa chỉ ngoài kia **chưa phân định** là hai người hay một người ở
hai mạng, và **không cần phân định để quyết**: trang này phơi dữ liệu cho **bất kỳ ai đăng
nhập được**, nên cái chặn là số người có tài khoản, không phải số người đang mở trang.

Đưa mã lên mini cần anh gật (luật 16/09: commit/push tự do, **deploy phải xin anh**).

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
