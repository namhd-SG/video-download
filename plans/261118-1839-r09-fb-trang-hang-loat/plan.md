# R-09 #3 — Facebook page hàng loạt, Đường A (không cookie) — plan

Nguồn đề: ĐP f7 (18/11 18:39) + agy KHÉP: `~/agy-ws/exchange/vd-r09-fb-page-R1b-agy.md`, `-R2a-claude.md`, `-R2b-agy.md`.
Đo: `video-download/plans/reports/do-261118-r09-fb-page-buoc0.md` (bước 0 + 0b). Nhánh `feat/fb-trang-hang-loat` từ main c7b722c.

## Chốt thiết kế (bắt buộc)
1. Nguồn `FacebookTrang` (`src/tiktok_music_downloader/nguon_facebook_trang.py`): nhận `facebook.com/<page>`, `/<page>/videos`, `/<page>/reels` (host www/m/web/không www). KHÔNG nhận `/ads/library`, `/<page>/videos/<id>`, `/reel/<id>`, `/watch`, `/share`, `/groups`, `/events`, `/profile.php`… `/<page>` ép về `/<page>/videos`. Đứng trước `LinkLe` trong `NGUON`, vào `NGUON_YT_DLP_NEN_TANG_KHAC`. `nen_tang()` = "facebook" ⇒ cờ `facebook` trong `VIDEODL_NEN_TANG_BAT` (mặc định TẮT, dùng cổng sẵn `web/app.py`).
2. `PhienFB` (`fb_trinh_duyet.py`, khuôn `ig_trinh_duyet.PhienIG`): patchright Chrome thật headless (`VIDEODL_FB_HEADFUL=1`), profile tạm xoá mọi lối ra, `cookies_path: str | None = None` (None ⇒ ẩn danh; có ⇒ add_cookies — dành Đường B, Đường A luôn None).
3. Mã dừng `STOP_FB_CHAN_DANG_NHAP = "fb_chan_dang_nhap"`: hộp thoại đăng nhập (dialog có input[name=pass]) KHÔNG đóng được (không có nút Close) mà `len(refs) < max_videos` ⇒ ly_do này, KỂ CẢ refs=[] + so_da_co>0 (không bao giờ already_owned). Hộp thoại đầu có Close ⇒ bấm 1 lần, đi tiếp. Nối: `utils.py`, `web/queue.py::_LY_DO_RONG_LA_LOI`, `web/static/bao-thieu.js::NHAN_THEO_LY_DO` (KHÔNG `MA_CHAY_LAI_DUOC`), `web/static/stop-reason-text.js`.
4. `MAX_VIDEO_TRANG_FB = 20` chặn ở POST /jobs cạnh `MAX_VIDEO_KENH_YOUTUBE`; trả trong `/tinh-nang`. KHÔNG đổi pacer.
5. Bóc mã KHÔNG regex phẳng (`fb_xhr_phan_tich.py`, thuần, không mạng):
   - HTML lúc tải: `json.loads` từng `<script type="application/json">`, duyệt cây.
   - XHR `/api/graphql`: chỉ khi `fb_api_req_friendly_name` ∈ whitelist {`CometProfilePlusVideosRootQuery`, `PagesCometChannelTabAllVideosCardImplPaginationQuery`, `ProfileCometTopAppSectionQuery`, `ProfileCometAppCollectionReelsRendererPaginationQuery`} (loại `useInstreamAdsHaloFetcherQuery`, `CometChannelTabVideoPreviewRootQuery`); thân có thể nhiều dòng JSON (mỗi dòng 1 object).
   - Tab /videos: nút `Video` (`__typename=="Video"`, id số) tại `<c>.edges[].node` với c ∈ {`all_videos`,`latest_videos`,`series_videos`,`video_list_videos`} + nút trực tiếp `channel_tab_popular_video` (thẻ "Most popular", thuộc tab thật).
   - Tab /reels: `aggregated_fb_shorts.edges[].profile_reel_node.node.attachments[].media` (`__typename=="Video"`).
   - Mọi nút phải có `owner.id`; giữ nút có owner.id == owner của page (owner chiếm đa số trong lượt; nút owner khác ⇒ bỏ + đếm `so_la`). `page_info.{end_cursor,has_next_page}` lấy từ container khi có.
   - Đối chứng dữ liệu thật (đã làm, ghi PR): TheOnion/videos 15 mã (10 HTML + XHR), NASA/videos 21, TheOnion/reels 50 — 100% owner = page; regex phẳng thêm đúng 1 mã = `channel_tab_popular_video` (thuộc page) ⇒ 0 mã lạ.
6. Vòng cuộn `fb_quet_cuon.py` (khuôn `ig_quet_cuon.py`): wheel + nghỉ 2,5–4 s, trần cuộn, trần thời gian, `already_have` từng đợt + `on_skip`, dừng đủ N mới / has_next=false ⇒ hết / 6 lượt không thêm mã ⇒ stalled; tường ⇒ (3). 0 mã + không tường ⇒ `source_empty`; câu `STOP_REASON_TEXT.source_empty` thêm vế "hoặc nền tảng ẩn tab này khi chưa đăng nhập".
7. Tải: `download_all(nen_tang="facebook")`, id `fbv-<mã>`, URL tải `https://www.facebook.com/reel/<mã>` (reels) / `https://www.facebook.com/watch/?v=<mã>` (videos). Giữ `FORMAT_NEN_TANG_KHAC`. `max_filesize=TRAN_DUNG_LUONG_BYTE` + trần `TRAN_THOI_LUONG_GIAY` cho job FB page (như kênh YouTube ở `web/queue.py`; dùng `length_in_second`/`playable_duration_in_ms` của nút khi có, không có thì đo sau tải như `la_short`).
8. Log chỉ mã loại trang + con số; 0 URL / tên page / mã video / `fbv-`. `VI_DU` cho nguồn FB page trong `web/static/huong-dan.js`.
9. Mỗi lượt MỞ trang = 1 `cong.truoc_goi()`; lỗi trình duyệt ⇒ `cong.xu_ly_loi(exc)` + RuntimeError không URL (như IG).

## Test + đột biến bắt buộc đỏ
(i) bỏ lọc `already_have`; (ii) bỏ phát hiện tường ⇒ job "Xong"; (iii) thiếu `fb_chan_dang_nhap` trong `NHAN_THEO_LY_DO` hoặc `_LY_DO_RONG_LA_LOI`; (iv) rò URL/handle/`fbv-` vào log; (v) bỏ `cong.truoc_goi()`.
Bắt buộc: JS `nhanThieu({trang_thai:"done",tong:30,tim_thay:16,xong:16,ly_do_dung:"fb_chan_dang_nhap"}) !== null`; pytest 16 mã đều đã có + tường ⇒ `fb_chan_dang_nhap` + job `failed`.

## Ràng buộc
Không cookie thật, không agy, không ca-n, không phụ thuộc mới. Test không gọi mạng (trình duyệt giả như `tests/test_ig_*`). File code < ~200 dòng.
