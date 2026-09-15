---
phase: 7
title: "Thư viện creative + nối sang bộ tự tìm"
status: pending
priority: P1
effort: "2-3d"
dependencies: [2, 3, 5]
---

# Phase 7: Thư viện creative + nối sang bộ tự tìm

Ghi lại các quyết định user chốt trong phiên 15/09, kèm phép đo đứng sau mỗi cái.
Chưa thi công phần nào trong file này trừ lớp chụp ảnh (đã xong, commit `a326b1b`).

## Đã XONG trước file này

Lớp chụp ảnh + chỉ mục (`a326b1b`): bảng `videos`, ảnh cắt bằng ffmpeg tại
`on_video_verified`, endpoint `/videos` và `/thumbs/{id}`. 200 test, đột biến 6/6 ĐỎ,
đã deploy và đo trên mini.

## USER CHỐT 15/09

| # | Chốt | Phép đo / lý do |
|---|---|---|
| 1 | Bố cục: dải điều khiển trên + thư viện dưới | giữ từ 14/09 |
| 2 | **Cả team thấy hết** thư viện | một thư viện chung để không ai tải trùng |
| 3 | Ảnh lưu trên mini cạnh `jobs.db` | 2 KB/video; `thumbs/` cùng hệ thống tệp với chỗ guard đĩa đo (`dev=16777234`) |
| 4 | Ảnh cắt bằng **ffmpeg**, không dùng cover của index | 2 KB / 0,08s / phủ mọi nguồn / không hết hạn — so với 26 KB + 1 request + `x-expires` 24h + chỉ nguồn hashtag |
| 5 | **Tránh trùng ở khâu liệt kê**, duyệt sâu thêm cho đủ N cái MỚI | `download_all` chỉ bỏ qua khi file còn trên đĩa (`downloader.py:202`) mà vòng đời đã xoá ⇒ đang tải lại + upload lại; tốn lượt gọi TikTok = rủi ro khoá nick |
| 6 | Thẻ lọc **theo nguồn** (`#80ssaudi`), không theo nước | |
| 7 | Bộ lọc dạng **hộp xổ**, thêm **Ngày tải** + **Người tải** | |
| 8 | Bộ lọc thiếu dữ liệu ⇒ **luôn có ô "không rõ · N"** | tầng-2 chỉ có với nguồn hashtag; không có ô đó thì lọc âm thầm giấu video |
| 9 | Phân tích nội dung (tầng 3) **chỉ chạy cho lô đã chọn**, không tự chạy | ~16k token/ảnh qua agy |
| 10 | Giỏ = tập video đã chọn, có nút **Xoá** và **Tạo task tự tìm** | |
| 11 | "Thêm bộ tự tìm" = **dựng lại hộp thoại trong Video Desk**, KHÔNG nhảy sang Creative Desk | user: "nhảy qua bên creative desk thì nhìn bị tù quá" |
| 12 | Nhưng form phải **luôn đúng taxonomy** | ⇒ đọc sống từ API, cấm chép cứng danh sách |
| 13 | "Tìm thêm giống cái này" **giữ**, nhưng là **đề xuất cho user duyệt** | agy quét video / đọc text, hashtag, link nhạc → đề xuất → user check. Không tự chạy |

## Ba tầng dữ liệu cho bộ lọc — đo được

| tầng | lấy từ đâu | có gì | giá | phủ |
|---|---|---|---|---|
| 1 | chính file mp4 | tỉ lệ khung, thời lượng thật, độ phân giải, fps, có tiếng | **0** — `verify_video_stream` đã chạy `ffmpeg -i` rồi đọc đúng 1 boolean | MỌI nguồn |
| 2 | response index | region, play_count, digg_count, author, title, create_time, **music_info.id** | **0** — response có 31 trường, code đọc 2 | CHỈ hashtag |
| 3 | nhìn nội dung | kiểu creative, hook, chữ trên hình | ~16k token/ảnh | theo lô user chọn |

## Nối sang Creative Desk — đo được 15/09

```
service account của video-download nhìn thấy đúng 1 Shared Drive:
  "Creative Astronex" (0AASy4v5CJAkfUk9PVA)
gốc có 5 thư mục: video-tool · _preview-staging · _style-catalog · Idea · Creative
canAddChildren=True trên CẢ 5, kể cả "Creative"
ca dương: đọc được thư mục của chính tool (video-tool)
```

⇒ **Copy thẳng trong Drive được**: không tải xuống, không upload lại, không đụng trần
*"tối đa 100MB mỗi file"* của hộp thoại, và **không sửa dòng nào của Creative Desk**.

⚠ **Mặt trái của cùng phát hiện đó:** credential này ghi được vào TOÀN BỘ Shared Drive
của Creative Desk. Mọi lệnh ghi phải **chỉ nhận folder id do API trả về**, không bao giờ
tự chọn thư mục đích. Đây là ràng buộc an toàn, không phải gợi ý.

Hình dạng một bộ tự tìm (`SelfBundleCreate`): `category` · `title` · `usecase` ·
`insight` · `template` · `quantity` → trả về `drive_folder_url` + `order` (mã `N.2307`).

## CHẶN — chưa giải, cần user quyết

**Form trong Video Desk phải đọc taxonomy sống, nhưng `GET /creative-taxonomy/categories`
và `/tree` đòi `UserRecord`/`AuthUser` — phiên đăng nhập của meta-auto.** Video Desk là
service khác, hostname khác, không có phiên đó.

| đường | giá |
|---|---|
| a. token máy cho Video Desk | meta-auto có `is_mcp`; phải cấp + giữ một token dài hạn có quyền vào API đội khác |
| b. trình duyệt gọi thẳng meta-auto | cần CORS cho `video.nobidigital.asia`; dữ liệu lấy đúng quyền của chính user |
| c. đồng bộ định kỳ | **loại** — lệch âm thầm, trái chốt #12 |

Khuyến nghị: **(b)** — ít mã hơn, không phải giữ token dài hạn, quyền đúng người dùng.

## Còn treo, chưa có đáp

1. **Nút "Xoá" xoá gì** — hỏi 3 lần chưa có đáp. Giờ có hai nghĩa: xoá *giỏ* (video còn
   nguyên) hay xoá *video trên Drive* (khó lui, cần xác nhận).
2. **Bấm vào thẻ mở gì** — chỉ lưu link thư mục job, không lưu id từng video.
   `upload_file` đã trả về id đó, đang vứt đi.
3. **Một video ở hai hashtag** — `INSERT OR REPLACE` ghi đè, mất hashtag đầu. Thẻ lọc
   "theo nguồn" (chốt #6) cần quan hệ nhiều-nhiều. Làm sau thì dữ liệu cũ đã mất.
4. **`music_info.id`** — cần cho chốt #13 (tìm theo nhạc). Chưa lưu. Chờ thì mất vĩnh viễn.
5. **Trần job/ngày** — user chốt 14/09, chưa thi công.

## Ba thứ "chờ thì mất vĩnh viễn"

Ghi riêng vì chúng khác mọi việc khác trong file này: hoãn không làm chúng rẻ đi.

- ảnh thumbnail — **ĐÃ XONG** `a326b1b`
- `music_info.id` — chưa
- quan hệ video↔nguồn (nhiều-nhiều) — chưa

Index chỉ trả video *hiện tại* của một hashtag, không trả lại danh sách ta đã tải. Video
tải xong mà chưa chụp ba thứ trên thì không có đường lấy lại.
