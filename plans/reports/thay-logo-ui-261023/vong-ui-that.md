# Vòng UI thật — trang Thay logo prod (23/10/2026 11:25 VN)

Cách đi: Chrome đã đăng nhập của user, tab RIÊNG chạy nền (không giành tiêu điểm), `https://video.nobidigital.asia/thay-logo.html`.
CHỈ XEM: không tạo lượt, không bấm Đạt/Hỏng/Bỏ qua/Áp vào bộ. Mở panel Hỏng để chụp rồi đóng lại, không gửi.
Số liệu DB đọc `?immutable=1` trên ca-n (`web/data/thay_logo_log.db`).

## Số vận hành thật (prod, tới 23/10 11:2x)
| chỉ số | giá trị | nguồn |
|---|---|---|
| số lượt (tl_job) | **3** — 19/10 22:59, 20/10 10:23, 23/10 10:52; cả 3 tên "Test"/"Test2", 1 video/lượt | `select … from tl_job` |
| kết quả video | render **1** · cho_nguoi (máy không chắc) **2** ⇒ **2/3 không ra gì** | `tl_video.trang_thai` |
| thời gian máy | 8,6 s video ⇒ 91,9 s · 18,4 s ⇒ 14,8 s · 51,2 s ⇒ 61,1 s | `tl_video.giay_video, giay_xu_ly` |
| chờ trước khi xử lý | lượt 19/10 22:59 ⇒ bắt đầu 20/10 09:09 (**~10 giờ**); 2 lượt sau ~1 phút | `tl_job.tao_luc` vs `tl_video.bat_dau` |
| số lượt chấm Đạt/Hỏng | **0** | `tl_danh_gia` rỗng |
| Bộ đề 40 video (bản C ≈ prod) | render 26/40; 14/40 cho_nguoi; 23 video đối thủ đã render vẫn còn 740 khung lộ có toạ độ + 717 khung mất dấu | plan vòng tự cải thiện, khối SỬA R1b; `~/do-dkb-261021/ra/C` |

⇒ **LUỒNG UI duyệt/chấm trên prod chưa được dùng** (3 lượt Test, 0 chấm). Việc thử nghiệm nhiều tuần của user đi qua đường khác: bộ Test3 40 video, chấm bản C 40/40 chỗ đè (USER-QUYET 22/10), chạy thử trên ca-n, sổ USER-QUYET 16–22/10.

## Luồng hiện tại, từng bước (ảnh trong thư mục này)
| # | bước | ảnh | chỗ gây khó (quan sát) |
|---|---|---|---|
| 1 | Vào trang | `01-trang-dau-toan-trang.png` | MỘT trang rất dài gộp: chọn nguồn + giỏ + danh sách lượt + bộ lọc + hàng duyệt + 4 cột trạng thái. Thanh 3 bước ở đầu chỉ là nhãn, trang không chia bước. Dòng "Việc của bạn" có 4 số + chữ — phải đọc mới hiểu. |
| 2a | Chọn video — Bộ tự tìm | `01-…` (khối "Đưa video vào") | Nạp CẢ BỘ (30–40 video) bằng 1 nút; "bỏ bớt / xem video" ẩn. Không biết trước video nào có logo đối thủ. |
| 2b | Thư viện của bạn | `04-tab-thu-vien.png` | Ô xem trước **xám trống**, chỉ có tên (vd "#CapCut", "how to make my ride…") ⇒ không nhận ra video. |
| 2c | Tải từ máy | `02-tab-tai-tu-may.png` | Rõ ràng (kéo thả, ≤ 500 MB). |
| 2d | Dán link Drive | `03-tab-dan-link-drive.png` | Phải bấm "Kiểm link" riêng trước khi vào giỏ. |
| 3 | Chọn nơi nhận | giỏ bên phải `01-…` | "Thành phẩm đi đâu?" chỉ hiện sau khi chọn video; 3 kiểu đích (bộ gốc / bộ tự tìm mới / thư mục Drive). |
| 4 | Chờ máy | khối "Lượt của bạn" | Có chuỗi Nhận → Máy xong → Chờ duyệt (tốt). Nhưng không báo ĐANG CHỜ GÌ: lượt 19/10 chờ ~10 giờ (nguyên nhân CHƯA ĐO — nghi relay agy trên máy dev tắt qua đêm). |
| 5 | Duyệt | `05-the-duyet.png` | Chấm theo **1 khung** (trước/sau kéo vạch) + 1 crop phóng to. "Logo mới có ở khoảng 4/5 video" — không chỉ ra 1/5 còn lại nằm ở đâu. Muốn xem cả video phải mở Drive tab khác. |
| 6 | Hỏng | `06-panel-hong.png` | Chọn 1 trong 5 mã + ô ghi chú gõ tay "giây thứ mấy". Không đánh dấu được chỗ lỗi trên hình/thời gian. |
| 7 | Sửa | — | **KHÔNG CÓ đường sửa**: không kéo/vẽ lại box, không chỉ cho máy chỗ logo, không chọn đoạn. Chỉ Đạt / Hỏng / Bỏ qua. |
| 8 | Máy không chắc | `01-…` cột phải | Ảnh "khung máy đã xem" của Test 03_12 gần như **trắng** — người không thấy máy đã nhìn gì. Lời giải thích chung chung ("logo mờ… dễ nhận nhầm"). Hành động duy nhất: "Bỏ qua video này". Không có "chỉ cho máy logo ở đây". |
| 9 | Xuất | — | Đạt ⇒ máy tự đưa tới nơi nhận. Chưa ai dùng tới bước này (0 lượt chấm). |

## Chỗ gây khó — gom
1. **Máy bỏ cuộc mà người không cứu được**: 2/3 video prod và 14/40 bộ đề ra "máy không chắc". Người không có cách nào chỉ cho máy.
2. **Duyệt thiếu bằng chứng**: chấm cả video từ 1 khung + 1 crop; phần lộ/không đè không được chỉ ra theo thời gian.
3. **Không sửa được tại chỗ**: Hỏng = bỏ, không có vòng "sửa box ⇒ chạy lại đoạn".
4. **Trang quá tải**: 1 trang làm 4 việc (nạp, theo dõi, duyệt, xử lý ngoại lệ); thanh 3 bước chỉ là trang trí.
5. **Chờ không rõ lý do**: lượt đầu chờ ~10 giờ, giao diện không nói lý do (nguyên nhân CHƯA ĐO; nghi relay agy).
6. **Nhận diện video kém** ở Thư viện (không có ảnh xem trước).
