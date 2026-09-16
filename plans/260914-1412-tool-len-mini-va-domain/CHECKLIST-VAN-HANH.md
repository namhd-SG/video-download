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

- [ ] **Chữ gợi ý trong ô nhập quá mờ, khó đọc** ở giao diện sáng. Bản sửa đã viết xong nhưng **chưa đẩy lên mini**, nên người dùng thật vẫn đang nhìn bản chưa sửa. Chỉ cần anh gật là đẩy lên, vài phút.

---

## B. ĐANG THIẾU — cản team dùng thật

### B1. Mỗi người một cookie TikTok *(quan trọng nhất)*

Hiện chưa tách cookie theo người. Chưa xong nghĩa là **chưa mở cho cả team dùng được**.

- [ ] Mỗi người tự dán cookie TikTok của mình, không dùng chung tài khoản
- [ ] Cookie của người A không lọt sang lượt tải của người B
- [ ] Cookie hỏng / hết hạn → báo lỗi rõ ràng, không âm thầm tải ra kết quả rỗng
- [ ] Cookie không bị ghi vào nhật ký hệ thống
- [ ] Tắt đột ngột giữa chừng → không để sót cookie trên đĩa

### B2. Nghiệm thu toàn hệ *(làm sau B1)*

- [ ] Hai người chạy cùng lúc → chạy tuần tự, không lẫn cookie
- [ ] Tải thật từ ngoài văn phòng, nhận được video thật
- [ ] Khởi động lại máy mini → dịch vụ tự lên *(máy này của người khác dùng chung — phải hẹn giờ)*
- [ ] Tải xong → đĩa mini sạch, link Drive mở được, số lượng khớp
- [ ] Promax của người khác không hề hấn gì trong suốt quá trình

### B3. Nối vào meta-auto

- [ ] Thêm một link trong thanh điều hướng meta-auto để người dùng tìm thấy tool

---

## C. CHỜ ANH QUYẾT — 3 việc đang đứng im vì thiếu câu trả lời

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
4. **C1 · C2 · C3** — làm ngay khi anh trả lời, không phụ thuộc nhau.
