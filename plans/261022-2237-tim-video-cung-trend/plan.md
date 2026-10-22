# GĐ2 — Quét 1 video → tìm thêm video CÙNG DẠNG trên TikTok

22/10/2026 · lane TikTok (tk3) · nhánh `feat/tim-video-cung-trend` từ `origin/main 061417c` · worktree `video-download-wt-tim-trend`
Trạng thái: **BẢN NHÁP — chờ agy phản biện, chờ ĐP duyệt. Chưa code.**

Nguồn: GĐ1 `~/plans/reports/de-xuat-261022-1850-quet-video-goi-y-keyword-hashtag-nhac-tiktok.md` §5–§7 (agy R3b KHÉP [argon chưa kiểm]) · đề bài ĐP 22:39.

## Kết quả mong muốn
Đưa 1 file video ⇒ công cụ ra **danh sách link TikTok cùng DẠNG** (không chỉ cùng chủ đề), mỗi link có ảnh bìa + hạng khớp, kèm `links.txt` dán thẳng vào Video Desk (nguồn `LinkLe` đã nhận nhiều link `/video/`, trần 50 link/job — `web/app.py:379`).

## Ràng buộc
- Không đụng prod/Video Desk ở GĐ2: công cụ là **lệnh CLI chạy ở máy dev** (agy + Chrome thật chỉ có ở đây). Đưa vào hàng tải = user dán `links.txt` (KISS; nút gửi thẳng `/jobs` để sau nếu user cần).
- Ngưỡng hạng là **tham số**, mặc định `3` + `2A` — **đã hiệu chỉnh bằng thước người** (user chấm 70 ảnh GĐ1, 22/10 22:40, `~/plans/reports/tiktok-quet-video-261022/cham-tay-ket-qua.json`): giữ 20, user nói đúng 19 ⇒ precision **0,95**, recall **0,90** (19/21). Chỉ `3`: 0,88 / 0,33. Thêm `2B`: 0,83 / 0,90. User tính cả 12/12 ảnh "2A" (đúng dạng + chữ Tutorial) là đúng dạng.
- 3 ca lệch thước người (ghi để không quên, CHƯA đổi luật vì mỗi ca 1 mẫu): `s2-1` poster "Clone Potion" 5 bản sao — máy 3, user KHÔNG (poster quảng cáo ≠ lookbook); `s5-5` lưới 4 ô CÙNG 1 cô gái — máy 1 (luật lưới ĐK1), user ĐÚNG; `s5-9` nhiều pose 1 cầu thủ — agy đếm "3 người khác nhau" ⇒ máy 1, user ĐÚNG (lỗi đếm bản sao của agy).
- Không proxy/VPN (chưa duyệt) ⇒ kết quả theo IP VN — giới hạn đã biết, in ra trong trang.
- Giãn cách mọi lượt gọi TikTok/tikwm; trần lượt/lần chạy là tham số.
- Không đưa dữ liệu khách lên agy: chỉ dùng cho creative social công khai (user xác nhận 22/10).

## Phi mục tiêu
Tải video (Video Desk làm) · proxy theo thị trường · tích hợp GUI/web · nhận dạng nhạc bắt buộc (shazamio chỉ là phụ, cờ bật).

## Pha
| # | Pha | File | Trạng thái |
|---|---|---|---|
| 0 | Đo chặn đường: Playwright mở Chrome thật có ra link `/search/video` không; tikwm `feed/search` từ ca-n | `phase-00-do-chan-duong.md` | chờ |
| 1 | Lõi thuần: chữ ký dạng, chấm tất định, khử trùng, sinh truy vấn, mở rộng 2-hop | `phase-01-loi-thuan.md` | chờ |
| 2 | Nối ngoài: trích khung + agy bóc trường, nguồn tìm (Chrome/tikwm), tải ảnh bìa | `phase-02-noi-ngoai.md` | chờ |
| 3 | Lệnh CLI + trang HTML local + `links.txt` | `phase-03-cli-va-trang.md` | chờ |
| 4 | Nghiệm thu trên 2 video mẫu | `phase-04-nghiem-thu.md` | chờ |

Phụ thuộc: 0 → (1 ∥ 2) → 3 → 4. Pha 1 không cần mạng, làm song song pha 0.

## Nghiệm thu (đo, không cảm nhận)
1. **Video mẫu 1** (`~/Downloads/video test.mp4`, trend collage 7 pose): trong các link công cụ GIỮ (hạng ≥ ngưỡng), **≥ 70% có ≥3 bản sao cùng người trên nền trơn** — kiểm bằng mắt toàn bộ link giữ (≤ 30). Mốc GĐ1: truy vấn tên trend thủ công = 9/10.
2. **Video mẫu 2 KHÁC trend** (đề xuất: 1 video catwalk AI 1 người từ nguồn `#aicatwalk` GĐ1, vd `@harry_gunawan999/video/7619141013801667861`): link giữ **≥ 60% cùng dạng của nó** (1 người, catwalk) và **0 link dạng collage 7 pose** ⇒ chứng minh chữ ký dạng sinh TỪ video đầu vào, không hằng cứng.
3. **Đối chứng dương mỗi lần chạy**: khung của chính video đầu vào phải ra hạng 3; trượt ⇒ lần chạy báo "máy chấm không tin được", không xuất link.
4. Test tự động xanh: `pytest tests/test_tim_trend_*.py` + toàn suite không đỏ thêm.
5. Đột biến (luật `guard-marker…` vế 5, vì lọc sai là hỏng âm thầm): bỏ luật lưới / bỏ cổng bậc bản sao / xét chủ thể sau / bỏ cổng hành động ⇒ test PHẢI đỏ.

## Rủi ro chính
- Playwright-Chrome bị TikTok trả rỗng như README ghi (đo 09/09) ⇒ pha 0 gác; trượt thì `connect_over_cdp` vào Chrome user tự mở. tikwm `feed/search` đã loại (403 Cloudflare theo endpoint, đo từ cả máy dev lẫn ca-n 22/10) ⇒ từ khoá chỉ còn đường Chrome — **điểm hỏng đơn**; tất cả = 0 ⇒ dừng, báo ĐP.
- agy bịa trường (đã thấy 2 lần GĐ1) ⇒ đối chứng dương + điểm tất định + kiểm mắt khi nghiệm thu.
- Trend sống ngắn (collage 7 pose mới 1–4 ngày) ⇒ nghiệm thu chạy sớm; kết quả ngày khác có thể khác.

## Câu hỏi chưa giải quyết
- User tính nhóm "2A" (đúng dạng + chữ Tutorial) là đúng dạng không — chờ `cham-tay.html`.
- Video mẫu 2: ĐP/user có muốn chỉ định video khác không.

## Chốt từ agy R1b (KHÉP [argon chưa kiểm], 22/10 22:49) — bắt buộc khi thi công
- **ĐK1 `links.txt`**: mọi dòng khớp `parse_video_url` (`https://www.tiktok.com/@<handle>/video/<id>`), không dòng chú thích, chia khối ≤50.
- **ĐK2 thứ tự luật hạng** (`cham.py`): (1) không người khi chữ ký có người ⇒ `0` — xét ĐẦU TIÊN; (2) lưới; (3) bậc bản sao; (4) sai lệch. `chu_the` gom nhóm người {người mẫu thời trang, người thường}. Sai lệch 1 KÈM tutorial ⇒ `1` (không lên `2B`).
- **ĐK3 cổng hành động**: khi chữ ký 1 người (`bac_ban_sao="1"`) và `hanh_dong` ∉ {khac, tao_dang} ⇒ `hanh_dong` là cổng cứng; nền chỉ còn là tiêu chí phụ (catwalk thật ở sàn diễn/ngoài trời/studio đều tính). Test: s1-1 (meme Elon+robot) KHÔNG được hạng 3 với chữ ký video 2.
- **ĐK4 truy vấn theo chữ ký**: nhóm (a) chỉ sinh "{N} pose/collage/multi pose" khi bản sao ≥3; chữ ký 1 người ⇒ từ vựng hành động ("ai catwalk", "runway walk"…). `mo_rong`: đếm n-gram trên TẬP caption (≥2 caption chứa), test bằng ≥2 caption thật; từ dừng thêm `pembuatan`.
- **ĐK5 đối chứng dương không tự chấm**: 1 khung chuẩn của video đầu vào (`khung_ctrl`) nhét vào MỖI lô ảnh bìa gửi agy; chữ ký tính từ lượt bóc RIÊNG của các khung còn lại ⇒ ctrl phải ra `3` trong lô. Pha 0: dùng cơ chế "hâm phiên" (`scraper.py:510-550`, goto lần 2 khi feed rỗng) trước khi kết luận 0; đếm cả thẻ có `img.src` + tải thử 1 ảnh bìa.
- **ĐK6 sàn mẫu số nghiệm thu**: video 1 giữ **≥8 URL duy nhất** và ≥70% đúng dạng; video 2 giữ **≥5 URL duy nhất**, ≥60% đúng catwalk (kiểm bằng 3 khung/preview, không chỉ ảnh bìa giây 0), **0** link collage.
- **Không làm** (lệch chỉ đạo ĐP): đo tikwm bằng `curl_cffi impersonate` để vượt 403 — ĐP cấm lách Cloudflare; 0e đã đo đủ (chặn theo endpoint).
