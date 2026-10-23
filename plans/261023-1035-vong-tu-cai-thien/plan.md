# GĐ3 — Vòng tự cải thiện cho công cụ tìm video cùng dạng

23/10/2026 · lane TikTok (tk3) · **BẢN NHÁP — chưa code, chờ agy + ĐP.** Nguồn: user 23/10 10:20 (qua ĐP); sổ `~/plans/kien-thuc/knowhow-tim-video-tuong-tu.md` mục 7.

## Kết quả mong muốn
Mỗi lần user chấm link ⇒ công cụ có thêm dữ liệu có nhãn ⇒ lần sau **tự đề xuất** chạy tín hiệu mạnh trước, ngưỡng hợp hơn, bỏ từ khoá chết. % đúng dạng tăng dần theo tuần, đo được.

## Ràng buộc
- **Không tự áp**: mọi thay đổi là đề xuất + số; người duyệt mới áp (ghi ngày + người duyệt).
- Sàn mẫu: đổi thứ tự tín hiệu cần ≥20 link đã chấm/tín hiệu/loại; đổi ngưỡng cần ≥50 nhãn/loại. Dưới sàn ⇒ giữ cũ + cảnh báo.
- Dữ liệu ở máy dev (file JSON/SQLite trong thư mục người dùng), không lên prod ở GĐ3.
- "Phân vân" không dùng để học.

## Phi mục tiêu
Học sâu/huấn luyện model · tự sửa luật chấm · chia sẻ dữ liệu giữa máy.

## Pha (dự kiến)
| # | Pha | Việc |
|---|---|---|
| 1 | Lưu ca có nhãn | Trang kết quả có nút Đúng/Sai/Phân vân (lấy từ `cham-tay.html`); `tim_trend nhan <thư mục ra> <file chấm>` ⇒ nạp vào kho ca (`~/.tim-trend/ca.jsonl`): seed, LOẠI video, truy vấn→link, hạng máy, nhãn người |
| 2 | LOẠI video | Gắn loại từ chữ ký (bản sao ≥3 ⇒ "ghep-nhieu-dang"; 1 người + catwalk ⇒ "catwalk"; …) — tất định, không để LLM tự đặt tên loại |
| 3 | Bảng tín hiệu tự cập nhật | `tim_trend bao-cao` ⇒ bảng nhóm truy vấn × loại × (link đã chấm, % đúng) + đề xuất thứ tự, có sàn mẫu |
| 4 | Ngưỡng + từ khoá chết | precision/recall theo ngưỡng/loại ⇒ đề xuất; truy vấn 0 đúng ≥3 lần liền ⇒ đề xuất hạ hạng 14 ngày |
| 5 | Áp có duyệt | file `de-xuat.json` + lệnh `tim_trend ap <id> --nguoi-duyet <tên>` ghi vào `cau-hinh.json`; lần chạy đọc cấu hình đã duyệt |
| 6 | Đo vòng học | báo cáo tuần: % đúng dạng lần chạy mới theo loại, so tuần trước |

## Nghiệm thu
- Test: dữ liệu giả 3 loại × nhiều ca ⇒ đề xuất đúng; dưới sàn ⇒ không đề xuất + cảnh báo; "phân vân" không ảnh hưởng; không có đề xuất nào tự áp (đột biến: cho tự áp ⇒ test đỏ).
- Thật: sau ≥3 ca có nhãn cùng loại, đề xuất thứ tự tín hiệu khớp bảng sổ mục 2 (tên trend trước chủ đề).

## Câu hỏi chưa giải quyết
- Ai được duyệt áp (user / ĐP / cả hai)?
- User chấm trên trang local hay cần trong Video Desk?
- Sàn 20/50 là đề xuất ban đầu, chưa có nền — hiệu chỉnh sau vài tuần.
