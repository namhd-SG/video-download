# Báo cáo code R-08 M3 (Instagram hàng loạt) — worktree video-download-lane-c, 18/11/2026

Chưa commit/push/deploy. Chưa smoke thật (không có cookie; không mở instagram.com). Nền tảng `instagram` mặc định TẮT.

## File
Mới (src): `ig_xhr_phan_tich.py` 192 · `ig_quet_cuon.py` 134 · `ig_trinh_duyet.py` 147 · `nguon_instagram.py` 134.
Mới (web): `web/static/settings-instagram.js` 104.
Mới (test): `tests/ig_khung_gia.py` 116 · `test_ig_xhr_phan_tich.py` 136 · `test_ig_quet_cuon.py` 193 · `test_ig_trinh_duyet.py` 199 · `test_ig_nguon_va_job.py` ~300 · `test_ig_cookie_va_app.py` 230.
Sửa: `nguon.py` (+InstagramHangLoat vào NGUON trước LinkLe và NGUON_YT_DLP_NEN_TANG_KHAC) · `utils.py` (+STOP_IG_MAT_PHIEN, STOP_IG_CHUA_CO_COOKIE) · `web/cookies.py` (jar theo nền tảng, kiểm jar IG) · `web/app.py` (GET/PUT/DELETE `/me/cookie/instagram`, thẻ đỏ) · `web/models.py` (+`job_gan_nhat_cua_nguoi`) · `web/queue.py` (nhánh IG ở process_job, `_LY_DO_RONG_LA_LOI`) · `web/static/{settings.html,cookie-status-text.js,stop-reason-text.js,the-luot-gon.js}`.
Test cũ phải cập nhật (đổi hành vi có chủ đích): `test_nguon_dinh_tuyen.py` (bảng nguồn + câu 400), `test_web_app.py` (khai 3 route mới), `test_nguon_fb_ads_va_drive.py` (mã `ig_*` vào danh sách "không nút"), `test_link_le_nhan_dang.py` (profile IG giờ do nguồn hàng loạt nhận).

## AC → test
| AC | Test |
|---|---|
| Cookie `<sha256>.instagram.json`; TikTok không đổi byte (so byte + mtime) | test_ig_cookie_va_app: `test_ten_tep_jar_theo_nen_tang…`, `test_nap_va_xoa_cookie_ig_khong_doi_byte_cookie_tiktok` |
| Nạp jar không có cookie instagram.com ⇒ 400, jar cũ giữ nguyên byte, không rác ở thư mục tạm | `test_nap_jar_xau_400_va_jar_ig_cu_giu_nguyen_byte` (7 ca: jar TikTok, domain giả, thiếu sessionid, hết hạn, rỗng, không JSON), `test_jar_khong_co_cookie_instagram_com…` |
| Nhịp: 1 lượt pacer/lần mở URL; ≤30/giờ; 2,5–4 s cuộn; nghỉ giữa yt-dlp | `test_cong_pacer_tran_gio_dung_truoc_khi_mo_trinh_duyet`, `test_job_profile_n3…` (1+3 lượt), `test_nhip_job_ig_…`, `test_nghi_cuon_dung_khoang…` |
| Trần ngày + `luot_tai` / `nen_tang_tat` | dùng nguyên pacer (`test_pacer_tran_ip.py` cũ xanh); IG nằm trong TRAN_KHAC (30,100) có sẵn; mất phiên IG KHÔNG tắt nền tảng (assert trong `test_moi_dau_mat_phien…`) |
| Mất phiên ⇒ failed nhãn "Cookie IG hết hạn / bị IG chặn", thẻ Cài đặt đỏ, không "xong" rỗng | `test_moi_dau_mat_phien_job_failed_nhan_ig_khong_xong_rong[6 dấu]`, `test_mat_phien_audio_chi_bat_bang_dom`, `test_the_do_khi_job_ig_gan_nhat…`, `test_the_khong_do…`, `test_jar_ig_het_han_the_do…`, `test_trang_cai_dat_co_the…` |
| Từng dấu 1–5 (+ audio chỉ dấu 1/3) | test_ig_xhr_phan_tich `test_dau_1…`…`test_dau_5…`, `test_audio_khong_bi_bat_nham…`; test_ig_quet_cuon `test_mat_phien_dau_*` |
| Bóc `for (;;);` | `test_bo_tien_to_for_hijack…`, `test_audio_phan_trang_max_id_tien_to_for_hijack_bi_boc` (84 video/7 trang, 0 trùng) |
| Đủ N MỚI: profile N=10; hashtag N=20; link 3 = 6 video | `test_profile_n10_du_moi…`, `test_hashtag_n20_du_moi_khi_nhieu_anh`, `test_link_3_hashtag_ra_dung_6_video_trong_51_ma` |
| Chạy lại 0 trùng; đào qua bài đã có | `test_chay_lai_0_trung_nho_already_have`, `test_chay_lai_cung_nguon_0_trung` (cấp job), `test_dao_qua_bai_da_co_toi_khi_du_n_moi` |
| Carousel không tải, chỉ đếm | `test_carousel_khong_tai_chi_dem_so…`, `test_loc_video_chi_giu_media_type_2…` |
| Log 0 cookie / URL / handle / mã bài | `test_log_mot_luot_gia_lap_dem_0…` (thô của module IG + toàn log qua CheUrlFormatter), `test_loi_trinh_duyet_job_failed_va_thong_diep_khong_chua_url`, `test_log_cua_phien_khong_chua_cookie_url` |
| Cờ TẮT ⇒ POST /jobs từ chối URL IG hàng loạt, không ghi job | `test_co_tat_mac_dinh_post_jobs_tu_choi…` (4 loại URL), `test_co_bat_…`, `test_nhieu_link_ig…` |
| yt-dlp đọc được jar Cookie-Editor | `test_write_netscape_cookies_doc_duoc_json_cookie_editor_cua_ig`; cookiefile có mặt ở opts tải |
| Trình duyệt: nạp cookie `no_restriction`→None, bắt XHR theo tên, dọn profile tạm mọi lối ra | test_ig_trinh_duyet (8 test, trình duyệt giả) |

## Đột biến (chạy bằng scratchpad `dotbien/chay.py`: sửa tạm → pytest → hoàn lại, so byte; `git status` không còn tệp .bak)
| Đột biến | Lệnh (pytest -q) | Test đỏ (ví dụ) |
|---|---|---|
| Bỏ lọc video (giữ ảnh/carousel) | `tests/test_ig_xhr_phan_tich.py tests/test_ig_quet_cuon.py` | 4 đỏ: `test_loc_video_chi_giu_media_type_2…`, `test_hashtag_n20…`, `test_carousel_khong_tai…` |
| Bỏ dấu 1 (URL login/challenge) | + `tests/test_ig_nguon_va_job.py` | 6 đỏ: `test_dau_1…[3 URL]`, `test_mat_phien_dau_1…` |
| Bỏ dấu 2a (<1 KB) | như trên | 3 đỏ: `test_dau_2_xhr_dich_nho…`, `…[dau2_nho]` |
| Bỏ dấu 2b (errors) | như trên | 3 đỏ: `test_dau_2_xhr_json_co_errors…`, `…[dau2_errors]` |
| Bỏ dấu 3 (DOM) | như trên | 8 đỏ: `test_dau_3_dom…[4]`, `test_mat_phien_dau_3…` |
| Bỏ dấu 4 (0 XHR) | như trên | 3 đỏ: `test_dau_4…`, `…[dau4_khong_xhr]` |
| Bỏ dấu 5 (429) | như trên | 2 đỏ: `test_dau_5…`, `test_mat_phien_dau_5…` |
| Bỏ `return mat_phien` ở vòng cuộn | `test_ig_quet_cuon.py test_ig_nguon_va_job.py` | 16 đỏ |
| Bỏ `on_stop(IG_MAT_PHIEN)/return []` ở nguồn | `test_ig_nguon_va_job.py` | 7 đỏ (cả 6 dấu cấp job) |
| Ghi URL vào log ở `liet_ke` | `test_ig_nguon_va_job.py` | 2 đỏ: `test_log_mot_luot_gia_lap…`, `test_loi_trinh_duyet…` |
| Ghi cookie vào log ở `PhienIG` | `test_ig_trinh_duyet.py` | `test_log_cua_phien_khong_chua_cookie_url` |
| Nạp IG ghi vào `<sha>.json` (đổi byte TikTok) | `test_ig_cookie_va_app.py` | 3 đỏ: `test_nap_va_xoa_cookie_ig_khong_doi_byte_cookie_tiktok`… |
| Bỏ trần cuộn (vòng không dừng) | `test_ig_quet_cuon.py::test_tran_cuon_dung_dung_so_lan_va_bao_het_vong` | đỏ |
| Bỏ trần pacer (`cong.truoc_goi`) | `test_ig_nguon_va_job.py` | 2 đỏ: `test_cong_pacer_tran_gio…` |
| Bỏ bóc `for (;;);` | `test_ig_xhr_phan_tich.py test_ig_quet_cuon.py` | 3 đỏ: `test_bo_tien_to…`, `test_audio_phan_trang…` |
| (thêm) Jar không cookie instagram.com vẫn nhận | `test_ig_cookie_va_app.py test_ig_nguon_va_job.py` | 6 đỏ |

Một bug thật do test bắt: kiểm jar chung ở `process_job` ban đầu kiểm jar IG bằng luật TikTok ⇒ mọi job IG dừng `cookie_khong_phai_tiktok`; đã sửa (`and la_tiktok`).

## Full suite
`2 failed, 3051 passed, 425 skipped, 1 warning, 9 errors in 506.67s (0:08:26)`
Toàn bộ 2 failed + 9 errors KHÔNG do code này, xác nhận có sẵn: `test_giai_captcha_chromium.py` (10; máy này không có Chromium cho Playwright, lỗi cả trước khi sửa) và `test_thay_logo_kiem_hinh.py::test_logo_mo_troi_…` (đỏ y hệt khi `git stash -u`).

## Headless hay headful
Headless mặc định (`VIDEODL_IG_HEADFUL=1` bật headful). Lý do: bước 0 — 3/4 loại trang headless = headful (cùng số XHR/mã); riêng profile headless ra ít XHR hơn (10 vs 16 / 6 cuộn) nhưng vòng cuộn dừng theo "đủ N mới / hết trang (has_next_page, more_available)", không theo số cuộn cố định, nên chỉ cuộn nhiều hơn (trần 40 lần). Máy dịch vụ không cần cửa sổ. Viewport 1280×900 (CHƯA đo ảnh hưởng tới số XHR). Chrome thật qua patchright (`channel=chrome`), profile Chrome TẠM xoá khi đóng phiên.

## Lệch / chưa làm / còn lo
1. **Nghỉ giữa yt-dlp**: AC ghi 2–4 s nhưng `pacer.NGHI_GIUA_LUOT` = (10, 20) s dùng chung cho mọi nền tảng và có test khóa. Giữ 10–20 (dài hơn = an toàn hơn, bước 0 chỉ đo 2–4 s với 7 lượt). Có test nhịp thật. Muốn đúng 2–4 s cho IG ⇒ cần hằng riêng theo nền tảng (không làm vì đụng pacer chung).
2. **Chưa smoke thật**: bộ chọn DOM nút "Log in" (`_CHON_NUT_DANG_NHAP`: thẻ a/button/role=button, chữ đúng "Log in"/"Đăng nhập") chỉ có test với trang giả; rủi ro bắt nhầm (trang đăng nhập rồi mà có nút khớp) chưa đo ⇒ smoke đầu tiên nên xem job có dừng oan `ig_mat_phien` không. Cấu trúc `user.username`/`caption.text` (title/author của ref) lấy theo kiểu phòng thủ, chưa xác minh trên payload thật (thiếu thì None).
3. **Job vẫn dùng 1+N lượt pacer** (1 mở trang + N tải) trên trần IG 30/giờ ⇒ N>~29 chắc chạm `tran_gio` giữa chừng. Không thêm trần `so_luong` riêng cho IG (như YouTube có `MAX_VIDEO_KENH_YOUTUBE`) vì đề không nêu; nên cân nhắc.
4. **429 không tắt nền tảng** (khác tín hiệu chặn của yt-dlp ở pacer): mất phiên IG chỉ dừng job + thẻ đỏ. Lỗi trình duyệt (Chrome thiếu, timeout) vẫn đi qua `cong.xu_ly_loi` và là job `failed` với thông điệp chỉ có tên lớp lỗi.
5. Mất phiên giữa chừng ⇒ vứt hết video đã gom (job failed, lượt sau gom lại) thay vì tải nửa vời. Link lẻ IG (`/reel/…`) giữ nguyên: vẫn không dùng jar IG (đề chỉ nói job IG hàng loạt).
6. Thẻ đỏ = job IG gần nhất của người đó có `ly_do_dung=ig_mat_phien` tạo SAU lần dán jar gần nhất; dán lại jar ⇒ hết đỏ. Test JS chỉ kiểm cú pháp (`node --check`) + sự có mặt id/chuỗi, không chạy trình duyệt (máy không có Chromium).
7. Hashtag URL dạng `?q=#tag` (chưa mã hoá) bị trình duyệt cắt thành fragment ⇒ không nhận (cần `%23`).
