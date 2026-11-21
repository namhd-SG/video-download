# Kết quả P0 — probe bài thật (20/11/2026, máy DEV, lane tk3)

Máy: máy dev (KHÔNG phải mini — lệnh giao M1 ghi "máy dev"; không ssh prod). yt-dlp dev = 2026.08.19, Pillow 12.3.0.
Script probe + bảng nhãn→URL nằm ngoài repo (scratchpad phiên, sẽ mất): nhãn `T#` (TikTok), `I#` (IG), `F#`/`fb#` (FB). Không URL/handle/id bài nào trong tệp này.
Cookie IG (tài khoản phụ, từ user) chỉ chép vào scratchpad 0600, đã XOÁ sau probe; không in/log.

## Tóm tắt: giả định → ĐO / BÁC
| Giả định (plan.md mục 4) | Kết quả |
|---|---|
| HTML `/photo/<id>` có `imagePost` không cookie | **BÁC MỘT PHẦN**: HTML `/photo/<id>` KHÔNG có scope `webapp.video-detail` (0/7). HTML `/video/<id>` của CÙNG bài CÓ `itemStruct.imagePost.images[].imageURL.urlList` ẩn danh (6/7; bài thứ 7 `statusCode=10204`). ⇒ `tiktok_anh.py` luôn thăm `/@u/video/<id>` (đổi `/photo/`→`/video/`). URL ảnh vẫn lấy được ⇒ không dừng. |
| tikwm có `images` | **ĐO**: hashtag (`challenge/posts`) trả khoá `images` cho bài ảnh (7/46 ở 1 tag; bài ảnh có `duration=0`). Ở 2 tag khác 0/100 (tag đó không có bài ảnh). tikwm `feed/search` = HTTP 403 (không dùng). |
| anchor `/photo/` ở music page | **ĐO**: music page 1 bài ảnh: 72 anchor `/photo/` + 88 `/video/`; feed `/api/music/item_list/` có `imagePost` (72 bài/160) ẩn danh, headless. |
| IG `image_versions2`/`carousel_media` + tên XHR lưới bài | **ĐO**: profile `/<user>/` = `PolarisProfilePostsQuery` (lượt đầu) + `PolarisProfilePostsTabContentQuery_connection` (cuộn); trộn 1/2/8; mọi node có `image_versions2.candidates`, carousel có `carousel_media[]` (con có `media_type`, ảnh có candidates, video có `video_versions`). |
| FB `/photos` ẩn danh + container | **ĐO, TRẦN THẤP**: 8 ảnh/page (2 page; cả `/photos_by`), hộp đăng nhập ngay lượt cuộn đầu, không XHR phân trang ⇒ chỉ `<script type="application/json">`. Nút `Photo` KHÔNG có `owner` (khác video). |
| hạn URL CDN | **ĐO**: TikTok `x-expires` ≈47h; IG ảnh `oe` ≈105h, IG video con ≈34h; FB ảnh `oe` ≈105h. Đều ≫ thời gian từ thăm bài tới tải. |
| trần ảnh/bài | **ĐO**: TikTok tới 35 ảnh/bài (music page); IG carousel tới 20 (n=121, trung vị 9). |

## TikTok
| # | Lệnh/cách | Kết quả thô (rút gọn) |
|---|---|---|
| T1 | `requests` UA Chrome, không cookie, GET `/@u/photo/<id>` và `/@u/video/<id>`, đọc `__UNIVERSAL_DATA_FOR_REHYDRATION__` | `photo`: scopes `[app-context,biz-context,i18n-translation,a-b]`, imagePost False (7/7). `video`: `webapp.video-detail` statusCode 0, imagePost True, n = tikwm n (11,2,1,15,1,1); khoá ảnh `[imageHeight,imageURL,imageWidth]`, `urlList` 2 phần tử. T7: statusCode 10204, không imagePost. Thứ tự mảng = thứ tự tikwm (đối chiếu số; thứ tự xem thật: KHÔNG ĐO bằng mắt). |
| T2 | — | Không cần cookie/Playwright cho thăm bài (T1 đạt ẩn danh). |
| T3 | tải `urlList[0]` và `[1]` ảnh 01 của 6 bài, Pillow open+verify | 6/6: HTTP 200, `image/jpeg`, JPEG, cỡ = `imageWidth/Height` (856–1536 px), path đuôi `.jpeg`, host `*.tiktokcdn.com`, `x-expires` còn ≈47.3h; `urlList[0]` và `[1]` cùng byte. ⇒ tên tệp `NN.jpg`. |
| T5 | 10 bài nhiều ảnh nhất ở music page, thăm `/video/<id>` rồi tải đủ | số ảnh 8–35; 170/170 ảnh JPEG hợp lệ; MB/bài min 1.16 · trung vị 3.15 · max 11.92. **1 lần `ConnectTimeout` ở host `urlList[0]`** ⇒ `urlList[1]` thành công (`url_dung_idx {0:169, 1:1}`) ⇒ tải PHẢI thử lần lượt `urlList`. |
| T6 (i) tikwm | hashtag page | có `images` (xem bảng trên) ⇒ tikwm phân loại được ngay khi liệt kê. |
| T6 (ii)(iii) music | Playwright headless như `scraper._open_context`, cuộn 8 lần | anchor `/photo/` 72, feed `music/item_list` 6 trang: items 27/28/29/26/24/26, có imagePost 9/10/15/10/14/14; khoá `imagePost` `[cover,images,shareCover,title]`. ⇒ music page phân loại được (anchor `/photo/` HOẶC `imagePost` feed). |
| T6 (iv) yt-dlp profile flat | `extract_flat`, `playlistend=60`, 3 profile có bài ảnh | 60/60 entry URL `/video/`, 0 entry chỉ-tiếng, 0 `duration=0`; bài ảnh đã biết của profile KHÔNG có trong 30 đầu. ⇒ flat không phân loại / không thấy ảnh ⇒ giữ D9 (chế độ ảnh rơi nhánh browser). yt-dlp 1 bài ảnh: 1 format `vcodec=none` (khớp `queue.py:136`). |
| T7 | bài trong tikwm nhưng HTML statusCode 10204 | 1 mẫu (gỡ/riêng tư — chưa phân biệt). Nhãn đề xuất: statusCode≠0 ⇒ lỗi phía nguồn (`tiktok`, xám). |
| T8 | — | KHÔNG ĐO `vm.tiktok.com` (không có mẫu). `/photo/<id>` link lẻ: chuẩn hoá về `/video/<id>` khi thăm (T1). |
| T9 search | Playwright `/search?q=` | `/api/search/general/full/` trả thân không JSON (bị chặn ẩn danh, như video). KHÔNG ĐO được imagePost ở search; quyết định thi công: search đi cùng nhánh browser như music (anchor `/photo/`), không chặn 400. |
| T10 browser profile | Playwright ẩn danh `/@u` | `post/item_list` không JSON, 0 anchor (giống video ẩn danh; prod dùng phiên/captcha). KHÔNG ĐO được trên dev. |

## Instagram (cookie tài khoản phụ, patchright Chrome thật headless)
| # | Kết quả |
|---|---|
| I1 | yt-dlp `/p/` (dev 2026.08.19): ảnh đơn ẩn danh ⇒ `There is no video in this post`; ảnh đơn có cookie + carousel toàn ảnh (có/không cookie) ⇒ DownloadError; carousel toàn video ⇒ playlist 6 entries. ⇒ KHÔNG dùng yt-dlp cho ảnh. Mở `/p/<mã>/` bằng `PhienIG`: node đúng mã nằm trong `<script type="application/json">` lúc tải (6/6 có cookie, 3/3 ẩn danh); XHR lúc mở bài chỉ là feed (`PolarisFeedTimelineRootV2Query`, không phải bài). `requests` thường: HTML 540 KB nhưng KHÔNG có node (0/2) ⇒ phải trình duyệt. |
| I2/I7 | profile `/<user>/` (không ép `/reels/`), 6 lượt cuộn: XHR có node `PolarisProfilePostsQuery` (12), `PolarisProfilePostsTabContentQuery_connection` (72); 88 mã: mt2 55, mt1 17, mt8 16 ⇒ một luồng XHR cho `ca_hai`. Tên cần thêm vào `TEN_GRAPHQL_DICH` khi `loai!=video`: `PolarisProfilePostsTabContentQuery` (khớp chứa-chuỗi phủ cả `_connection`) + `PolarisProfilePostsQuery`. |
| I3 | con-video carousel `video_versions[0].url`: HTTP 200 `video/mp4`, ffprobe `h264,video` + `aac,audio` ⇒ có tiếng sẵn, không cần ghép; `verify_video_stream` dùng được. |
| I4 | ảnh `image_versions2.candidates` lớn nhất: HTTP 200 `image/jpeg` JPEG, không header đặc biệt; `oe` ≈104–107h; video con ≈34h. Lưu ý: candidate lớn nhất có thể nhỏ hơn `original_*` (1080×1440 vs 3072×4096) — IG không phát gốc. |
| I5 | 121 carousel (profile+hashtag+keyword): min 2 · trung vị 9 · max 20. 10 bài tải thử: 37/37 tệp OK, 0.18–8.76 MB/bài. |
| I6 | hashtag (`?q=%23…`) và keyword: `PolarisKeywordSearchExplorePageRelayQuery` + `…RelayPaginationQuery` (tên hiện có `KeywordSearchExplorePage` đã khớp); 100 mã/trang-cuộn: hashtag mt8 49 · mt2 37 · mt1 14; keyword mt8 56 · mt2 32 · mt1 12 ⇒ hashtag/keyword HỖ TRỢ ảnh. Audio: KHÔNG ĐO (là reels; giữ quyết định chỉ-video). |

## Facebook (ẩn danh, patchright)
| # | Kết quả |
|---|---|
| F1 | 2 page lớn, `/photos` (và `/photos_by`): HTTP 200, hộp đăng nhập ngay lượt cuộn 0, 12 lượt cuộn vẫn **8 ảnh/page**; không XHR phân trang (1 page có 1 `ProfileCometTopAppSectionQuery` lặp lại đúng 8 nút đó). |
| F2 | nút ở `…data.node.all_collections.nodes[].style_renderer.collection.pageItems.edges[].node.node`, `__typename=Photo`, `id` số; khoá `[id, accessibility_caption, immersive_photo_encodings, viewer_image, photo_cix_screen]`; **KHÔNG có `owner`** ⇒ lọc chủ page theo owner (như video) không làm được; ràng buộc bằng ĐƯỜNG DẪN container `all_collections…pageItems` (trên trang `/<page>/photos` của chính page). `viewer_image.uri` cỡ tới 2048 px. |
| F3 | mỗi nút = 1 Photo (`fbid`) ⇒ 1 ảnh = 1 item (giữ giả định plan). |
| F4 | `viewer_image.uri`: 8/8 HTTP 200 `image/jpeg` JPEG, cỡ = width/height nút; `oe` ≈104–107h. |
| F5 | mở `/photo/?fbid=` ẩn danh: có nút Photo với `image` + `owner` (3 nút đầy đủ). Có thể làm link lẻ ảnh FB, nhưng user chốt "FB page ảnh" ⇒ KHÔNG làm link lẻ ảnh FB trong R-30 (giữ `photo` trong `_DUONG_RIENG`). |
| F6 | tab `/photos`: 0 nút `Video` ⇒ `ca_hai` FB = 400 giữ nguyên (Q-B). |

## Không đo / để P9
- Env prod `VIDEODL_NEN_TANG_BAT`, bản yt-dlp mini: KHÔNG ĐO (cấm ssh prod).
- V1 (copy ảnh trên Drive ⇒ `ban_hop_le`, `trash_file` ảnh): KHÔNG ĐO trên dev (không Drive thử); đọc mã `vao_bo_drive.py:84-120` không xét mime ⇒ P4 test DriveGia + P9 smoke thật.
- T8 `vm.tiktok.com`, T9 imagePost ở search, T10 profile browser có phiên: KHÔNG ĐO được ẩn danh trên dev.

## Hệ quả thi công (khác plan R3)
1. `tiktok_anh`: thăm `/@u/video/<id>` (kể cả khi URL nguồn là `/photo/`), đọc `webapp.video-detail.itemInfo.itemStruct.imagePost.images[].imageURL.urlList`; statusCode≠0 ⇒ lỗi phía nguồn.
2. Tải ảnh: thử lần lượt từng URL trong `urlList`/ứng viên khi lỗi kết nối (đã gặp ConnectTimeout thật).
3. IG link lẻ ảnh: `PhienIG` mở `/p/<mã>/`, bóc node đúng mã từ `<script type="application/json">` (không phải yt-dlp, không phải XHR).
4. IG profile chế độ ảnh/cả hai: mở `/<user>/` (không `/reels/`), thêm `PolarisProfilePostsTabContentQuery` + `PolarisProfilePostsQuery` vào XHR đích CHỈ khi `loai!=video`; hashtag/keyword hỗ trợ ảnh; audio chỉ video.
5. FB photos: chỉ đọc script JSON lúc tải, container `all_collections…pageItems`, không lọc owner (không có); trần ẩn danh 8 ⇒ xin N>8 sẽ dừng `fb_chan_dang_nhap` (mã có sẵn).
6. Trần: TikTok ≤35 ảnh/bài (đặt trần 50), IG ≤20; dung lượng bài ≤12 MB đo được.
