---
title: "R-08 M3 — Instagram tải hàng loạt (profile reels / keyword / hashtag / audio)"
status: in-progress
branch: feat/instagram-hang-loat (worktree /Volumes/DevSSD/offload/Projects/video-download-lane-c, từ origin/main cf4ca32)
---

# Nguồn sự thật
- Đề lane C: `/Users/macos/plans/261117-1603-video-desk-bigupdate-roadmap/task-lane-c-instagram.md` (mục "M3 code — AC").
- Số đo bước 0: `video-download/plans/reports/do-261118-1610-r08-m3-buoc0-ig-xhr.md` (checkout chính).
- Phase cũ: `~/plans/261007-1112-video-desk-da-nen-tang/phase-05-instagram-facebook-x-profile-hashtag.md` (bỏ phần gallery-dl: ĐÃ CHỐT không dùng).
- Chốt ĐP 18/11 16:1x: cuộn theo has_next_page/more_available tới đủ N MỚI + trần lượt cuộn; dấu mất phiên theo loại trang, mỗi dấu 1 test + đột biến; bóc `for (;;);` có test; carousel KHÔNG tải (chỉ đếm số vào log dạng số); hashtag nghiệm thu bằng hashtag khác ≥20 video.

# Đường (đã chốt)
patchright + cookie IG của người tạo job (tài khoản phụ) ⇒ mở trang ⇒ bắt XHR ⇒ lọc `media_type == 2` ⇒ `yt-dlp --cookies` tải lẻ (qua `download_all`, nền tảng khác).
| loại URL | mẫu | XHR đích | phân trang |
|---|---|---|---|
| profile reels | `instagram.com/<user>/reels/` (cả `/<user>/` ⇒ ép `/reels/`) | POST `/graphql/query` hoặc `/api/graphql`, `fb_api_req_friendly_name` chứa `ProfileReelsTab` | `page_info.end_cursor` / `has_next_page` |
| keyword | `instagram.com/explore/search/keyword/?q=<từ>` | friendly chứa `KeywordSearchExplorePage` | như trên |
| hashtag | `…/explore/search/keyword/?q=%23tag` và `…/explore/tags/<tag>/` (ép sang keyword `?q=%23tag`) | như keyword | như trên |
| audio | `instagram.com/reels/audio/<id>/` | POST `/api/v1/clips/music/` — body có tiền tố `for (;;);` | `paging_info.max_id` / `more_available` |
Node media: dict có `code` (str) + `media_type` (1 ảnh, 2 video, 8 carousel). Chỉ lấy 2. Video id = `ig-<code>` (tiền tố `BANG_LINK_LE["Instagram"]`), link tải `https://www.instagram.com/reel/<code>/`.

# Dấu mất phiên (mỗi dấu ⇒ dừng job, nhãn "Cookie IG hết hạn / bị IG chặn", KHÔNG "xong" rỗng)
1. URL cuối chứa `/accounts/login` hoặc `challenge` / `checkpoint`.
2. XHR đích < 1024 B hoặc JSON có `errors` (ví dụ code 1675002 "Unauthorized logged out query.").
3. DOM: có `input[name=username]` hoặc chữ "Log in"/"Đăng nhập" ở nút đăng nhập, hoặc title "Page couldn't load"/chữ "Something went wrong".
4. Trang không phải audio: sau tải + cuộn mà 0 XHR đích.
5. HTTP 429 trên XHR đích.
(Trang audio KHÔNG cookie vẫn ra dữ liệu ⇒ chỉ dấu 1/3 bắt được — có test riêng.)

# Phạm vi file (gợi ý, tách module ≤ ~200 dòng mỗi file)
- Tạo `src/tiktok_music_downloader/ig_xhr_phan_tich.py`: hàm THUẦN (không mạng): bóc tiền tố, duyệt node media, lọc video, đọc phân trang, phân loại dấu mất phiên từ (url cuối, danh sách XHR {kind,status,size,body}, dấu DOM). Đếm carousel có con video (chỉ số).
- Tạo `src/tiktok_music_downloader/ig_trinh_duyet.py`: phiên patchright (dùng lại khung khởi chạy có sẵn trong `trinh_duyet_patchright.py` nếu hợp), nạp cookie JSON, mở URL, bắt XHR, cuộn 2,5–4 s/lần tới khi đủ N mới hoặc hết trang hoặc chạm trần cuộn; headless/headful theo số đo (bước 0: headless ở profile ra ít XHR hơn cùng số cuộn ⇒ vì cuộn tới đủ N nên headless chấp nhận được; ghi lựa chọn vào PR). Lọc trùng `already_have` từng đợt XHR để "đào qua" bài đã có.
- Tạo `src/tiktok_music_downloader/nguon_instagram.py`: lớp `InstagramHangLoat` (giao thức `Nguon`, `nen_tang()=="instagram"`, `loai_log` = "instagram:profile|keyword|hashtag|audio"), đứng TRƯỚC `LinkLe` trong `NGUON`, vào `NGUON_YT_DLP_NEN_TANG_KHAC` (cổng pacer: mỗi lượt MỞ URL IG = 1 `cong.truoc_goi()`; yt-dlp tải đã qua cổng ở `download_all`). Nghỉ 2–4 s giữa lượt yt-dlp (kiểm `pacer.nghi_giua_luot` có đúng khoảng không).
- Sửa `web/cookies.py`: jar theo nền tảng `<sha256(nguoi_tao)>.instagram.json`; TikTok giữ NGUYÊN đường `<sha>.json` (không đổi byte). Hàm kiểm jar IG: không cookie nào domain instagram.com ⇒ mã lỗi (400 khi nạp, giữ jar cũ); thiếu `sessionid` ⇒ chưa đăng nhập; hết hạn ⇒ hết hạn.
- Sửa `web/app.py`: GET/PUT/DELETE cookie IG (theo khuôn `/me/cookie`, ví dụ `/me/cookie/instagram`), trạng thái thẻ đỏ khi job IG gần nhất dừng vì mất phiên hoặc jar hết hạn.
- Sửa `web/static/settings.html` (+ js nếu có): thẻ "Cookie Instagram — dùng tài khoản PHỤ", cùng khuôn thẻ TikTok.
- Sửa `web/queue.py::process_job`: job `nen_tang == "instagram"` ⇒ `cookies_path` = jar IG; không có jar ⇒ dừng nhãn rõ (không chạy ẩn danh); tiền kiểm jar. Mất phiên ⇒ `set_job_stop_reason` mã mới + `failed`.
- Sửa `nguon.py` / `utils.py` (STOP mới + nhãn hiện), `web/lifecycle.py` nếu cần trần ngày theo nền tảng (đã có `pacer.TRAN_KHAC=(30,100)` cho "instagram"? KIỂM, thêm nếu thiếu).
- Cờ: `instagram` chỉ chạy khi có trong `VIDEODL_NEN_TANG_BAT` (mặc định `youtube,tiktok` ⇒ TẮT). Cổng `POST /jobs` từ chối URL IG hàng loạt khi cờ tắt (như link lẻ).

# AC (từ đề, giữ nguyên)
- Cookie `<sha256>.instagram.json`; nạp jar không có cookie instagram.com ⇒ 400 giữ jar cũ; cookie TikTok cùng người KHÔNG đổi byte (test so byte).
- Nhịp: ≤30 lượt mở URL IG/giờ/cookie (pacer); 2,5–4 s giữa cuộn; 2–4 s giữa yt-dlp. Trần ngày theo nền tảng + `luot_tai` / `nen_tang_tat`.
- Mất phiên / 429 / challenge ⇒ dừng job nhãn "Cookie IG hết hạn / bị IG chặn", thẻ Cài đặt đỏ; KHÔNG "xong" rỗng.
- Đủ N MỚI: profile N=10 ⇒ ≥8 mới; hashtag (≥20 video) N=20 ⇒ ≥16 mới; link 3 (#emiuquan2) ra đúng 6 video; chạy lại ⇒ 0 trùng.
- Log: 0 cookie, 0 URL, 0 handle/shortcode (test đếm trên log thật của một lượt giả lập).
- ĐỘT BIẾN phải ĐỎ (mỗi cái chạy, ghi lệnh + test đỏ): bỏ lọc video · bỏ dừng-khi-mất-phiên (từng dấu) · ghi cookie/URL vào log · nạp IG đổi byte TikTok · bỏ trần · bỏ bóc `for (;;);`.
- FULL suite, dán dòng tổng.

# Fixture
Payload thật bước 0 ở `/private/tmp/claude-502/-Volumes-DevSSD-offload-Projects-video-download/fe32089e-f109-4a23-aa3e-27aa6a81480e/scratchpad/m3b0/*.xhr.jsonl` (mỗi dòng {kind, friendly, status, size, body}). Dùng để HIỂU cấu trúc; fixture vào repo phải TỰ DỰNG nhỏ (vài node, mã giả, bỏ object `user`/tên/caption), không chép payload thật vào repo.

# Ghi vào PR (ĐP đọc trên ca-n 18/11, lane C không ssh)
- yt-dlp venv prod ca-n = 2026.08.19 (cùng bản máy dev; 7/7 mp4 IG tải được bằng bản này ở bước 0).
- curl_cffi trên ca-n: chưa cài (ModuleNotFoundError). Nâng yt-dlp/curl_cffi KHÔNG thuộc PR này (R-09).
