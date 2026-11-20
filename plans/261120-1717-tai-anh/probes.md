# P0 — Probe trên bài THẬT (làm TRƯỚC khi code; kết quả ghi `probe-results.md` cùng thư mục)

Nguyên tắc: mỗi dòng kết quả = `ĐO` (kèm lệnh + đầu ra thô ≤30 dòng, đường dẫn tệp) hoặc `KHÔNG ĐO ĐƯỢC` (lý do). Không có dòng "chắc là". Probe CHỈ-ĐỌC, không ghi `jobs.db`, không đụng Drive prod.
Chạy trên MÁY CHẠY THẬT (mini; IP quyết định chuyện chặn) — đo RAM/đĩa trước theo luật chọn máy. Dùng cookie của TÀI KHOẢN PHỤ IG (jar của người tạo job; không in ra, không chép ra ngoài máy). Log/ghi chú KHÔNG chứa URL/handle/id bài (chỉ mã nhãn `T1,T2…` ánh xạ ở một tệp riêng ngoài repo).
Bài mẫu: lấy từ thư viện/job hiện có hoặc user đưa; tối thiểu 3 bài/loại, trong đó bắt buộc: TikTok slideshow ≥10 ảnh · TikTok slideshow KHÔNG nhạc nền (nếu tồn tại) · TikTok ảnh đơn 1 tấm · IG ảnh đơn · IG carousel toàn ảnh · IG carousel có video con · FB photo công khai của page.
Prod `VIDEODL_NEN_TANG_BAT` hiện = ? [UNVERIFIED] (mặc định `nguon.py:291` = `youtube,tiktok`; IG/FB link lẻ cần có tên trong cờ) — đọc env launchd trên mini, KHÔNG suy.
Bản yt-dlp trên mini: `python -c "import yt_dlp;print(yt_dlp.version.__version__)"` trong venv chạy dịch vụ (bản đọc nguồn = 2026.08.19 ở checkout dev, có thể lệch).

## TikTok
| # | Câu hỏi | Cách đo | Đạt khi | Quyết định phụ thuộc |
|---|---|---|---|---|
| T1 | `/@u/photo/<id>` và `/@u/video/<id>` của bài ảnh: HTML có `__UNIVERSAL_DATA_FOR_REHYDRATION__` chứa `imagePost.images[].imageURL.urlList`? thứ tự mảng = thứ tự xem? | `requests` UA trình duyệt (như `hashtag_enumerator._fetch`) không cookie; in KHOÁ (không in URL) + số phần tử | có đủ, ẩn danh | P2 `tiktok_anh.py` parse; nếu cần cookie ⇒ dùng jar TikTok của người tạo như video (`queue.py:868`) |
| T2 | Không ẩn danh được thì có cookie được không; Playwright có cần? | thử có cookie jar; nếu vẫn rỗng thử Playwright như `scraper.py` | ghi rõ đường nào chạy | độ nặng P2/P4 |
| T3 | URL ảnh: đuôi/định dạng (webp? jpeg? heic?), kích thước thật, có hạn (`x-expires`), tải thẳng được (HTTP 200, Content-Type image/*)? hết hạn sau bao lâu | tải 1 ảnh, `file`/Pillow mở, đo `Content-Length`, thử lại sau 30 phút | số liệu | trần hạn URL, tên tệp `NN.<ext>` |
| T5 | Số ảnh tối đa/bài, tổng MB điển hình/bài (n≥10 bài) | đo | min/trung vị/max | trần ảnh/bài, trần dung lượng/bài, `check_disk_guard` |
| T6 | Phát hiện LOẠI bài trước khi tải: (i) tikwm `data.videos[].images`? (ii) music page: anchor bài ảnh là `/photo/` hay `/video/`? (iii) feed XHR `/api/music/item_list` có `imagePost`? (iv) profile `TikTokUserIE` (`nguon_profile_yt_dlp.py:75`) trả mục ảnh hay bỏ? | (i) 1 trang tikwm hashtag; (ii)(iii) chạy `scraper.py` headless 1 lượt trên music page có bài ảnh, đếm anchor theo mẫu href + dò thân feed; (iv) gọi yt-dlp flat trên profile có ảnh | bảng nguồn × có/không biết loại | D9 (nguồn nào gắn `loai` ngay lúc liệt kê; nguồn không phân loại được rơi nhánh browser) |
| T7 | Bài ảnh bị gỡ/riêng tư/giới hạn tuổi: HTML trả gì (mã lỗi)? | 1 mẫu mỗi loại | nhãn lỗi | `phan_loai_loi` mới |
| T8 | Link `vm.tiktok.com` / `/photo/` của link lẻ: chuẩn hoá thế nào (hiện KHÔNG nhận `tests/test_link_le_nhan_dang.py:49`) | đo redirect | quyết định có nhận `vm.` ở chế độ ảnh không | `nguon.py` P3 |

## Instagram (cookie tài khoản phụ bắt buộc; `queue.py:870-877` chỉ chặn ẩn danh cho nguồn HÀNG LOẠT; link lẻ `/p/` hôm nay chạy KHÔNG cookie, `queue.py:868,871`, `nguon.py:399-409`)
| # | Câu hỏi | Cách đo | Đạt khi |
|---|---|---|---|
| I1 | Link lẻ `/p/<code>/`: yt-dlp `extract_info(download=False)` ảnh đơn (nguồn `instagram.py:528-530` đoán sẽ ném "no video"), carousel (entries, `thumbnails`)? Nếu ném: lấy qua `PhienIG` (cookie) mở trang + XHR; có cần cookie? | chạy với/không `--cookies` | bảng; chọn: yt-dlp hay XHR của chính ta |
| I2 | XHR lưới bài (profile `/<user>/`, hashtag, keyword): node ảnh có `image_versions2.candidates[].url`, carousel có `carousel_media[]` (con có `media_type`, `video_versions[].url`)? Tên `fb_api_req_friendly_name` của lưới BÀI profile (khác `ProfileReelsTab`, `ig_xhr_phan_tich.py:34`)? | bắt XHR bằng `PhienIG` (`ig_trinh_duyet.py`) trên 1 profile có ảnh+carousel; dump KHOÁ cấu trúc, không dump nội dung | có tên + đường dẫn khoá; nếu node XHR thiếu `carousel_media` ⇒ phải mở từng bài (tốn lượt pacer ×N) |
| I3 | Carousel có video con: URL video con tải được trực tiếp? codec/ext; cần ghép tiếng? | tải 1 con | quyết định dùng `verify_video_stream` (`queue.py:129`) trên con-video |
| I4 | Hạn URL CDN `cdninstagram`/`fbcdn` (tham số `oe=`), tải không cần header đặc biệt? | đo như T3 | trần hạn |
| I5 | Số ảnh tối đa carousel (10 hay 20), kích thước | đo n≥10 | trần |
| I6 | Hashtag/keyword/audio trong chế độ ảnh: audio là reels ⇒ bỏ khỏi chế độ ảnh? | đo | bảng nguồn IG × hỗ trợ ảnh |

## Facebook (không cookie là đường hiện có, `nguon_facebook_trang.py:3-6`)
| # | Câu hỏi | Cách đo | Đạt khi |
|---|---|---|---|
| F1 | `/<page>/photos` (hoặc `photos_by`/`photos_albums`) mở ẩn danh được không; tới đâu thì gặp hộp thoại đăng nhập (video: ≈16–22 ở /videos, ≈50 ở /reels, `nguon_facebook_trang.py:5-6`) | `PhienFB` (`fb_trinh_duyet.py`) 1 lượt trên 2 page | số ảnh tối đa thấy được ẩn danh |
| F2 | Tên XHR GraphQL của tab ảnh (so whitelist `fb_xhr_phan_tich.py:23-28`), container, nút `__typename:"Photo"` có `id`, `owner.id`, `image.uri`/`photo_image.uri`? ảnh gốc hay thu nhỏ | bắt XHR | tên + đường dẫn khoá |
| F3 | "1 photo = 1 item" hay album? Một post nhiều ảnh trên page: node là từng Photo hay post? | đo | chốt đơn vị item FB (kế hoạch giả định: mỗi Photo = 1 item) |
| F4 | URL ảnh FB hạn/403 (video đã gặp 410/403, `downloader.py:322-340`) | đo như T3 | trần hạn |
| F5 | Mở 1 ảnh lẻ `/photo/?fbid=` / `/<page>/photos/<id>`: có link lẻ ảnh không (hiện `photo` nằm trong `_DUONG_RIENG` `nguon_facebook_trang.py:32`, FB link lẻ qua `FacebookIE` chỉ video) | đo | có nhận link lẻ ảnh FB hay chỉ tab photos |

## Bổ sung R2 (theo phản biện agy)
| # | Câu hỏi | Cách đo | Đạt khi |
|---|---|---|---|
| T9 | TikTok `/search?q=` (thuộc `TikTokCollection`): DOM/XHR `/api/search/general/full` (`scraper.py:169`) trả bài ảnh là `/photo/` hay `/video/`, có `imagePost`? | như T6 trên 1 từ khoá | bảng; quyết định search có hỗ trợ ảnh không (`loai_ho_tro`) |
| T10 | Phân định loại ngay trong `liet_ke` (không còn `khong_ro`): với nguồn KHÔNG tự phân loại được (profile yt-dlp flat) chế độ ảnh rơi về browser có ra bài ảnh không? | chạy nhánh browser 1 profile có ảnh | có/không |
| I7 | Lưới bài IG `/<user>/` có trả reel (2) + ảnh (1) + carousel (8) cùng luồng XHR (cho `ca_hai`)? | bắt XHR | có/không + tên XHR |
| F6 | FB `/<page>/photos` có chứa video không (chốt `ca_hai` FB = 400, Q-B)? | đo | có/không |
| V1 | Với MỘT tệp ảnh đã lên Drive: copy tay vào một thư mục bộ trên Shared Drive ⇒ `ban_hop_le` (`vao_bo_drive.py:84-120`) đạt (md5+size+cha khác)? `trash_file` hoạt động trên tệp ảnh? | thao tác trên thư mục thử, KHÔNG đụng dữ liệu thật | đạt/không |
Nhạc: đã bỏ (USER-QUYET 20/11 17:4x) — không probe `music.playUrl`.

## Kết thúc P0
Ra `probe-results.md` + bảng cập nhật mục 4 của `plan.md` (đổi mỗi GIẢ ĐỊNH thành ĐO/BÁC). Giả định (a) hoặc (f) bị BÁC ⇒ dừng, báo user trước khi làm phase liên quan (nền tảng đó rơi khỏi phạm vi hoặc cần đường khác — đó là đổi phạm vi user chốt, không tự cắt).
