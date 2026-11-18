# R-09 #3 Facebook page hàng loạt, Đường A — báo cáo code (18/11/2026)

Nhánh `feat/fb-trang-hang-loat`, KHÔNG commit/push. Không mạng, không facebook.com, không cookie, không phụ thuộc mới, không đổi pacer.

## File
Mới (src, đều < 200 dòng): `fb_xhr_phan_tich.py` 186 · `fb_quet_cuon.py` 163 · `fb_trinh_duyet.py` 146 · `nguon_facebook_trang.py` 118 (tất cả `src/tiktok_music_downloader/`).
Mới (test): `tests/fb_khung_gia.py` 152 · `test_fb_xhr_phan_tich.py` 154 · `test_fb_quet_cuon.py` 206 · `test_fb_trinh_duyet.py` 264 · `test_fb_nguon_va_job.py` 353 · `test_fb_bang_ma_dung.py` 71 · `tests/js/nhan-thieu-fb.js` 16.
Sửa (+46/-10 ở 9 file + 1 test): `nguon.py` (NGUON, NGUON_YT_DLP_NEN_TANG_KHAC), `utils.py` (STOP_FB_CHAN_DANG_NHAP), `web/app.py` (MAX_VIDEO_TRANG_FB=20, cổng 400, /tinh-nang), `web/queue.py` (`_LY_DO_RONG_LA_LOI`, `la_facebook_trang`, max_filesize), `web/static/{bao-thieu,stop-reason-text,the-luot-gon,huong-dan}.js`, `huong-dan.html` (ô `data-tran="video_trang_facebook"`), `tests/test_nguon_dinh_tuyen.py` (bảng NGUON + câu 400 có thêm FacebookTrang — test cũ guard bảng, sửa theo thiết kế).

## AC → test
| Điểm plan | Test |
|---|---|
| 1 nhận URL (accept/reject, ép /videos, host www/m/web/trần, đứng trước LinkLe, trong NGUON_YT_DLP, cờ OFF) | `test_fb_nguon_va_job.py`: `test_nhan_dang_va_ep_url` (11 ca nhận), `test_khong_nhan_link_le_va_trang_he_thong` (~40 ca loại), `test_link_le_va_ads_library_van_di_dung_nguon_cu`, `test_dung_truoc_linkle_…`, `test_co_tat_mac_dinh_post_jobs_tu_choi…`, `test_co_bat_post_jobs_nhan…` |
| 2 PhienFB (headless, HEADFUL env, cookies_path=None ẩn danh, có ⇒ add_cookies, dọn profile) | `test_fb_trinh_duyet.py` (16 test); Đường A luôn None: `test_job_videos_n3_…` (không `cookiefile`), `_mo_phien(proxy)` chỉ nhận proxy |
| 3 mã dừng + 4 chỗ nối, không MA_CHAY_LAI_DUOC | `test_fb_bang_ma_dung.py`; JS bắt buộc `nhanThieu({done,30,16,16,fb_chan_dang_nhap}) !== null` = `test_nhan_thieu_ca_bat_buoc_16_tren_30_tuong_dang_nhap_khac_null` (node thật, `tests/js/nhan-thieu-fb.js`); guard cũ `test_moi_ma_dung_deu_duoc_phan_loai…` + `test_web_queue` vẫn xanh |
| 3 pytest 16 mã đã có + tường ⇒ `fb_chan_dang_nhap` + job `failed` | `test_16_ma_deu_da_co_cong_tuong_job_failed_…` (job) + `test_16_ma_deu_da_co_cong_tuong_la_fb_chan_dang_nhap_khong_phai_already_owned` (quét); thêm tường+0 mã, tường+vài mã (done), hộp thoại Close bấm 1 lần, Close hiện lại ⇒ tường sau 3 lần |
| 4 MAX_VIDEO_TRANG_FB=20 | `test_tran_20_chan_o_post_jobs_21_la_400_20_la_nhan`, `test_tran_20_co_trong_tinh_nang`, `test_tran_20_chi_ap_cho_fb_page…`; pacer 30 không đổi: `test_cong_pacer_tran_gio_…` |
| 5 bóc mã (whitelist, loại `useInstreamAdsHaloFetcherQuery`, nhiều dòng, container, popular, reels, không regex phẳng, owner, page_info) | `test_fb_xhr_phan_tich.py` (23 test); owner filter: `test_owner_la_bi_bo_va_dem_so_la…` |
| 6 vòng cuộn (wheel/nghỉ 6s + 2,5–4s, already_have+on_skip, N mới / has_next=false / 6 lượt / trần cuộn / trần giờ, source_empty) | `test_fb_quet_cuon.py` (24 test) |
| 7 tải `fbv-<mã>`, URL reel/watch, max_filesize, thời lượng | `test_job_reels_tai_bang_url_reel`, `test_job_dat_tran_dung_luong…`, `test_nut_khong_co_thoi_luong_do_sau_tai…`, `test_nut_co_thoi_luong_vuot_tran_bi_loai…` |
| 8 log sạch + VI_DU | `test_log_mot_luot_gia_lap_dem_0_url_ten_page_ma_video_va_fbv`, `test_log_luot_bi_tuong_cung_sach`, `test_log_cua_phien_…`; `test_vi_du_nguon_facebook_trang_o_trang_huong_dan` |
| 9 truoc_goi + xu_ly_loi | `test_cong_pacer_…`, `test_loi_trinh_duyet_job_failed_thong_diep_khong_chua_url_va_goi_xu_ly_loi`, 429 ⇒ `bi_chan` + tắt nền tảng |

## Đột biến (script `…/scratchpad/dotbien/dotbien.sh`, bash; tập test = 5 file test_fb_*, 141 test)
| # | Đột biến | Đỏ |
|---|---|---|
| i | `da_co = set()` (bỏ lọc already_have) | 6: 4 `test_fb_quet_cuon` (`already_have_loc_tung_dot…`, `chay_lai_0_trung…`, `het_trang_ma_chi_co_bai_da_co…`, `16_ma_deu_da_co…`) + 2 `test_fb_nguon_va_job` (`chay_lai_cung_nguon_0_trung`, `16_ma_deu_da_co…`) |
| ii | `if False:` thay nhánh phát hiện hộp thoại | 12: 5 tường/Close ở quet + 6 ở job (`16_ma…`, `tuong_sau_khi…`, `tuong_0_ma…`, `hop_thoai_dau…`, 2 log) |
| iii-a | bỏ `fb_chan_dang_nhap` khỏi `NHAN_THEO_LY_DO` | 2: `test_nhan_thieu_ca_bat_buoc_16_tren_30…` (nhanThieu → null), `test_khong_co_trong_ma_chay_lai_duoc_va_co_trong_nhan…` |
| iii-b | bỏ khỏi `_LY_DO_RONG_LA_LOI` | 4: `16_ma…` job (done thay failed), `tuong_0_ma_job_failed`, `ly_do_rong_la_loi_co_ma…`, `test_ma_dung_trong_utils_va_ly_do_rong_la_loi` |
| iv | `log.info(url, ids)` ở `liet_ke` | 2: 2 test log ở `test_fb_nguon_va_job` |
| v | `dung = None` thay `cong.truoc_goi()` | 2: `test_cong_pacer_tran_gio_…`, `test_job_videos_n3_…` (đếm 1+3 lượt) |
Mỗi đột biến ≥ 1 đỏ, không cần thêm test. Hoàn nguyên: `shasum -c` 4 file OK + `git diff -- web/queue.py web/static/bao-thieu.js` trùng byte với trước đột biến; sau đó chạy lại 5 file test xanh (141). Lưu ý trung thực: lần thử đột biến (i)(ii) đầu tiên hỏng do script zsh (backup không tạo được) ⇒ `fb_quet_cuon.py` bị hoàn nguyên TAY, sau đó viết lại script bash có backup và chạy lại cả 5 đột biến từ đầu — kết quả trên là của lần chạy bash.

## Suite đầy đủ
`7 failed, 3230 passed, 427 skipped, 1 warning, 9 errors in 352.47s` (lần đầu). 5 failed trong đó là `tests/test_nguon_dinh_tuyen.py` (bảng NGUON + câu 400) = hồi quy do tôi thêm nguồn ⇒ đã sửa test (22 xanh) + chạy lại 248 test liên quan (test_fb_*, nguon_dinh_tuyen, ig, link_le_nhan_dang, trang_huong_dan) xanh; KHÔNG chạy lại toàn suite lần 2 (chỉ đổi 1 file test).
Còn lại đều đã biết: `test_giai_captcha_chromium.py` 1 failed + 9 errors (không Playwright Chromium), `test_thay_logo_kiem_hinh.py::test_logo_mo_troi_qua_doan_kho_duoc_bam_lai_hai_chieu`. 427 skipped gồm test trình duyệt (chromium thiếu), gồm cả `test_trang_huong_dan` browser (nên ô `video_trang_facebook` ở trang /huong-dan CHƯA được kiểm bằng trình duyệt thật).
JS: `tests/js/*.js` là harness gọi qua pytest (không có `node --test`/package.json); harness mới chạy qua `test_fb_bang_ma_dung.py` (node v24) xanh; các test JS cũ nằm trong suite ở trên.

## Đối chứng dữ liệu thật (chạy parser trên raw capture, read-only, không copy vào repo)
TheOnion/videos: 10 HTML + 6 XHR = 16 mã; NASA/videos: 21 (HTML); TheOnion/reels: 10 HTML + 40 XHR = 50. 100% owner = chủ page (1 owner/trang); 0 mã nào của regex phẳng nằm ngoài tập tách được (kể cả `channel_tab_popular_video`, nay được nhận trực tiếp); 0 nút thiếu thời lượng. Khớp bảng bước 0 (16 / 21 / 50). Plan §5 ghi TheOnion/videos 15 — thực tế 16 theo bảng bước 0.

## Lệch so với plan / quyết định
1. `liet_ke` nhận `cookies_path` nhưng bỏ qua (Đường A luôn `PhienFB(None, …)`); `_mo_phien(proxy)` không có tham số cookie.
2. Chủ page = owner đa số tích luỹ qua các lượt (Counter); nút trong container có owner khác ⇒ bỏ + `so_la`. Hoà 1–1 lấy owner đến trước.
3. Thời lượng: nút có ⇒ lọc >900s ngay lúc liệt kê (không tốn lượt tải); không có ⇒ `VideoRef.la_short=True` (tái dùng kiểm sau tải ở `web/queue.py`). `TRAN_THOI_LUONG_GIAY` nhập muộn trong `liet_ke` (tránh vòng nhập `nguon` ↔ `nguon_facebook_trang`).
4. Tường được xét TRƯỚC `has_next_page=false`: tường + chưa đủ N luôn `fb_chan_dang_nhap` (đúng §3). Nếu đủ N thì COMPLETE dù có tường.
5. Hộp thoại có Close: bấm tối đa 3 lần (`TRAN_LAN_BAM_DONG`); hiện lại nữa ⇒ coi là tường (chống vòng vô hạn; plan nói "bấm 1 lần" cho hộp thoại đầu).
6. HTTP 429 (điều hướng/XHR) ⇒ `bi_chan` + `cong.xu_ly_loi(RuntimeError("HTTP Error 429"))` tắt nền tảng; không dùng mã mất phiên như IG (không có cookie để mất).
7. `khoi_dong_patchright` tái dùng của `ig_trinh_duyet` (thông điệp thiếu gói nhắc "Instagram" — chỉ vào thông báo lỗi nội bộ, đã bị `RuntimeError` che lại ở `liet_ke`).
8. Thêm nhãn `fb_chan_dang_nhap` ở `the-luot-gon.js` và ô `data-tran` ở `huong-dan.html` (không có trong plan, nhỏ; cần cho UI đủ bảng).

## Lo ngại mở
- Bộ chọn DOM `_CHON_HOP_THOAI` (`div[role=dialog]:has(input[name=pass])`) và `_CHON_NUT_DONG` (`aria-label` Close/Đóng trong dialog đó) CHƯA smoke thật — lane smoke trực tiếp phải kiểm: (a) hộp thoại đầu có bị nhận nhầm là tường không, (b) `eval_on_selector_all` đọc được `script[type=application/json]`, (c) `page.on("response")` có thấy thân XHR nhiều dòng đầy đủ.
- `lay_script_json` đọc MỘT lần ở lượt đầu ("HTML lúc tải"); nếu Facebook nạp thêm script JSON khi cuộn (không phải qua XHR) sẽ bị bỏ sót — đo bước 0 không thấy.
- Chủ page suy ra từ đa số owner: nếu lượt đầu chỉ có 1–2 nút và nút lạ đến trước, có thể chọn nhầm. Dữ liệu thật 3/3 trang không gặp.
- Ba test browser `/huong-dan` bị skip trên máy này nên chưa chạy thật.
