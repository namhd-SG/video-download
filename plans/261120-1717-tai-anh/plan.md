---
title: "Video Desk: tải ẢNH (TikTok photo/slideshow, IG ảnh+carousel, FB page photos) — bản R3"
description: "Chế độ tải ảnh theo job (Video/Ảnh/Cả hai); mỗi FILE ảnh là một hàng `videos` nên đi đúng đường vào bộ, Creative Desk, dọn ngày 7; ship tối bằng cờ."
status: pending
priority: P2
effort: 50h
branch: nhánh riêng từ origin/main (snapshot prod 8778685)
tags: [video-desk, anh, tiktok, instagram, facebook, drive, feature-flag, vao-bo]
created: 2026-11-20
---

Nguồn đọc: snapshot `/Users/macos/Projects/deploy-8778685` (= origin/main 8778685); mọi `file:dòng` là của snapshot. `docs/` không tồn tại; README cũ. Nguồn thật = code + trang Hướng dẫn.
File con: `probes.md` (đo bài thật TRƯỚC khi code) · `phases.md` (file/AC/test/đột biến từng phase). R3 = R2 (USER-QUYET 20/11 17:4x `~/plans/USER-QUYET.md:1799`, agy R1b) + agy R2b (bảng cuối).

## 1. Quyết định của user (cố định)
1. Nền tảng: TikTok photo/slideshow · IG ảnh đơn + carousel (có thể có video con) · FB page photos. Prod đã bật `VIDEODL_NEN_TANG_BAT=youtube,tiktok,instagram,facebook`, smoke IG #142 / FB #143 5/5 (ĐP báo; chưa tự đọc env mini).
2. Slideshow TikTok chỉ lưu ẢNH GỐC theo thứ tự — KHÔNG tải nhạc (đè ý "ảnh + nhạc", `USER-QUYET.md:1799`). Bỏ hết nhạc/`co_nhac`/kiểm nhạc.
3. Công tắc job Video/Ảnh/Cả hai, mặc định Video = hôm nay; bật ảnh: 1 bài = 1 item tính vào N. Lọc = nhóm "Loại" trong Thư viện + nhãn Ảnh/Video trên thẻ lượt.
4. Ảnh đi đường NHƯ VIDEO: vào bộ gửi Creative Desk + dọn Thùng rác ngày 7 (đè plan R1 "loại hẳn").

## 2. Hợp đồng Creative Desk / vào bộ đã tra (căn cứ chọn lại D1)
- Đơn vị gửi = **một FILE Drive**: payload `{"v":1,"items":[{"f":<drive_file_id>,"n":<tên>,"u":<link gốc http(s)>}],"nhan":…}` (`plans/260923-1558-tai-theo-cum/hop-dong-nhan.md`; dựng ở `web/models_chia.py:1742` cho cụm; chọn tay dựng ở client `web/static/app-ban-giao-creative-desk.js:34-60` từ `v.drive_file_id`, trần chọn tay `MAX_PM_ITEMS=500` `app-hang-so.js:29`, trần cụm `HANDOFF_MAX=30` `:23`). Hợp lệ bên nhận chỉ đòi `f` đúng hình id Drive + `u` http(s) (`models_chia.py:1672-1675`) — KHÔNG đòi mime.
- Vào bộ = bằng chứng trên Drive cho MỘT tệp nguồn: có ≥1 bản copy mang `properties.videodesk_src=<id nguồn>`, md5+size trùng, cha khác (`web/vao_bo_drive.py:84-120`, KHÔNG xét mime). Sổ `video_vao_bo` khoá `video_id`, nối `videos.drive_file_id` (`models_vao_bo.py:194,305`; `vao_bo_backfill.py:108`). Dọn ngày 7 = `trash_file(drive_file_id nguồn)` từng tệp (`vao_bo_don.py` đầu file).
- Chỗ DUY NHẤT hard-code video: 2 truy vấn Drive `mimeType contains 'video/'` (`vao_bo_drive.py:179` quét backfill, `:198` danh sách Thùng rác; gọi ở `vao_bo_backfill.py:138`, `vao_bo_kiem.py:184`) ⇒ ảnh không bị thấy ở đó (hở ≤24h như `vao_bo_kiem.py:22` đã khai) ⇒ phải thêm `image/`.
- Phía Creative Desk = app **meta-ads** (`vao_bo_drive.py:23`). ĐÃ KIỂM (ĐP + agy R2b, đọc tại `/Users/macos/meta-ads-automation`): backend nhận `video/*` HOẶC `image/*` (`backend/app/api/creative_self_bundle_import.py:32-34,214-218`), copy bằng `copy_file` có `properties.videodesk_src` ⇒ ảnh vào bộ đúng hợp đồng. Giữ item `{f,n,u}` KHÔNG kèm `k`: `k:"image"` chỉ dành cho item `url`, frontend từ chối nếu có cả `f` (`frontend/src/lib/videodesk-handoff.ts:160`). Không cần sửa meta-ads.

## 3. Quyết định thiết kế R2
- **D1 (đổi so R1): mỗi FILE ảnh = một hàng `videos`**, thêm cột cộng thêm `loai TEXT NOT NULL DEFAULT 'video'`, `bai_id TEXT`, `thu_tu INTEGER`, `bai_thu_muc_id TEXT` (`_add_column_if_missing` `models.py:383`, mẫu `:545`). Lý do: toàn bộ máy vào bộ/Creative Desk/dọn/thumbs vận hành trên 1 hàng = 1 tệp (mục 2) ⇒ dùng lại NGUYÊN; bảng riêng buộc nhân đôi ≥9 chỗ của máy có hậu quả im lặng và huỷ dữ liệu (trash). Giá phải trả: loại ảnh khỏi chức năng CHỈ-VIDEO (D2). Thumb + nút Bỏ + gửi Creative Desk đều theo `video_id` của FILE (D12).
- **D2 Loại ảnh khỏi cụm/chia kiểu/thay logo BẰNG CẤU TRÚC**: thêm vị từ `LA_VIDEO = "v.loai = 'video'"` vào `web/vi_tu_con_song.py` (nơi duy nhất viết vị từ "còn sống", docstring `:1-22`) và dùng ở MỌI truy vấn `videos` của 4 module chỉ-video — 19 câu `videos` + 1 câu `jobs`: `models_cum.py:88,100,280` · `models_chia.py:273,280,320,412,761,851,1135,1694` · `nhap_cum_cli.py:80,237` và `_cho_chia` trên `jobs` `:58-60` (thêm `AND EXISTS (SELECT 1 FROM videos v WHERE v.job_id=j.id AND <LA_VIDEO>)`, job chỉ-ảnh không bao giờ vào hàng chờ chia) · `thay_logo_routes.py:115,134,848,881,934,1005`. Cách viết (kiểm từng câu tại nguồn): câu không bí danh (`models_chia.py:320`, `nhap_cum_cli.py:80,237`: `FROM videos WHERE job_id=?`) đổi thành `FROM videos v … AND v.loai='video'`; `models_chia.py:280` thêm `AND {LA_VIDEO}` NGOÀI từng điều kiện (KHÔNG thêm khoá thứ 5 vào `DIEU_KIEN_VAO_LUOT_CHIA`: `tests/test_vi_tu_con_song.py:129` assert cứng 4 khoá); câu phủ định `NOT ({CON_SONG_CHUNG})` (`models_chia.py:412-413,1135`) viết `NOT ({CON_SONG_CHUNG} AND {LA_VIDEO})` (ảnh lọt vào nháp thì bị tính là "đã loại", không sống). Test cấu trúc quét mã nguồn (mẫu `tests/test_vi_tu_con_song.py`): mỗi `FROM|JOIN videos` phải có bí danh `v` VÀ kèm `LA_VIDEO` (hoặc nằm trong danh sách cho phép có lý do: thư viện, vào bộ, dọn); câu thiếu bí danh ⇒ ĐỎ.
- **D3 Danh tính**: hàng = FILE: `video_id = anh-<nt>-<id bài>-<NN>` (`nt`=`tt|ig|fbp`; vd `anh-tt-7123…-01`); `bai_id = anh-<nt>-<id bài>`; VideoRef của bài mang `video_id=bai_id`. Dedupe theo bài: `known_video_ids` (`models.py:1240`) mở rộng `UNION SELECT bai_id FROM videos WHERE bai_id IN (…)` — id ảnh mang tiền tố `anh-` không bao giờ trùng id video nên KHÔNG cần tham số theo chế độ. Thêm `anh` vào `_MAU_VIDEO_ID_TIEN_TO` (`app.py:180`) và CHỈ `fbp` vào mẫu che id log (`utils.py:135`: `anh-ig-<mã>` đã bị che nhờ `ig-`, `anh-fbp-<id>` che nhờ `fbp-`, `anh-tt-…` giữ nguyên vì TikTok không che, cố ý `utils.py:138`; KHÔNG thêm `anh` vào mẫu này; giữ `app.py:65`).
- **D4 Bố cục Drive**: `job-<id>/<bai_id>/01.<ext>…NN.<ext>` (+ con-video IG `NN.mp4`); tạo thư mục tổng quát (hiện chỉ `create_job_folder` `gdrive_upload.py:213`, tên `job-<id>` `:230`). Thư mục rỗng còn lại sau dọn ngày 7 (chỉ tệp bị trash): chấp nhận, ghi chú.
- **D5 Tách khỏi `download_all`** (hợp đồng 1 ref = `<id>.mp4`, `utils.py:107-109`, `downloader.py:475`): `_hoan_tat_tu_refs` (`queue.py:763`) tách `video_refs` (đi `download_all` y hệt `:809`) và `anh_refs` (`queue_anh.py`). Thứ tự: video → các kiểm dừng sẵn có (`:810-833`: `het_dia`, `cong.ly_do_dung`) → CHỈ KHI chưa dừng mới chạy ảnh → kiểm chung `:836-841`.
- **D6 Bài = tất cả hoặc không gì**: tải đủ K ảnh, kiểm từng tệp, đẩy hết lên Drive, rồi MỚI ghi K hàng `videos` trong MỘT giao dịch + `xong+1` (mốc sau việc; mẫu `queue.py:688-707`). Hụt bất kỳ tệp: `loi+1`, 0 hàng, trash thư mục Drive dở, XOÁ local (chạy lại tải lại; URL CDN ký hết hạn). Mỗi upload gọi `_note_upload_outcome` (`lifecycle.py:254`); thư mục job không tạo được ⇒ bài FAILED VÀ vẫn gọi `_note_upload_outcome` cho lỗi tạo thư mục (`_ensure_job_folder` `lifecycle.py:219-251` không tự gọi) để cầu dao đếm đủ (khác video: video rơi về gốc).
- **D7 Cờ**: `VIDEODL_TAI_ANH_BAT` (mặc định TẮT, đọc lúc chạy như `profile_theo_job.py:43-45`) cho TẠO + CHẠY ảnh + nút gửi ảnh (không còn cờ phụ cho Creative Desk — đã kiểm meta-ads nhận ảnh). Tắt: `POST /jobs` `loai_tai!=video` ⇒ 400; job ảnh đã có lọt tới `process_job` ⇒ `failed`+`tai_anh_tat` ở ĐẦU hàm (trước mọi việc), không chạy như video.
- **D8 Một cửa nhận nguồn**: `chon_nguon(url, loai="video")` (`nguon.py:931`) + `la_link_le(url, loai)` (`queue.py:178`) + `_chon_nguon_cho_o_nhap(links, loai)` (`app.py:395`); `LinkLe.liet_ke` (`nguon.py:511,528,557`) nay nhận `cookies_path` (hiện nuốt vào `**_chua_dung`, `_extract_info` không cookie `:399-409`) và tính `id_tam` (`:528`) ở chế độ ảnh thành `bai_id` (`anh-tt-<id>`, `anh-ig-<mã>`) để bỏ bài đã có TRƯỚC lời gọi mạng; gọi không tham số ≡ hôm nay (2 test khoá `test_nguon_dinh_tuyen.py:28`, `test_link_le_nhan_dang.py:49` giữ xanh). Mỗi nguồn khai `loai_ho_tro(url)`; nguồn/tab không hỗ trợ loại ⇒ 400 lúc tạo (YouTube, Ads Library, Drive: chỉ video; FB page: `anh`=tab photos, `ca_hai` ⇒ 400; IG `/<user>/reels/`, audio: chỉ video).
- **D9 Loại bài PHẢI phân định NGAY trong `liet_ke`** (bỏ `khong_ro`): ref ra khỏi nguồn chỉ là `video|anh`; nguồn không phân biệt được (profile yt-dlp flat) ở chế độ ảnh/cả hai đi nhánh browser. Nên N đếm đúng, `tim_thay` đúng, `already_have` lọc đúng.
- **D10 Throttle**: `pacer.TRAN` loại tiktok (`web/pacer.py:41-44`) ⇒ `cong=None` cho job TikTok (`queue.py:806`). Thăm bài TikTok dùng `JitterThrottle`+nghỉ lô như `download_all` (`downloader.py:43-44,447,489-494`); IG/FB dùng `cong.truoc_goi()` (`pacer.py:135-156`).
- **D11 Phân loại lỗi** (`queue.py:599` cho ép `loai`): phía nguồn (bài gỡ, cần đăng nhập, quá nặng) ⇒ `tiktok` (WARNING, xám); thiếu/hỏng tệp, Drive ⇒ `he_thong` (ERROR, đỏ). KHÔNG đưa "thiếu ảnh/ảnh hỏng" vào whitelist `phan_loai_loi.py:22-27`.
- **D12 Thumb dùng lại** `thumbs/<video_id>.webp` + `GET /thumbs/{id}` (`app.py:1357`; chỉ thêm tiền tố `anh`), cắt từ ảnh 01 và đặt tên theo `video_id` của FILE 01 (`anh-<nt>-<id>-01`) — `video_nay_cua_toi` (`models.py:1232`) khớp `v.video_id`, nên KHÔNG dùng `bai_id` làm id thumb. `GET /anh` trả mỗi bài kèm `thumb_id` và `file_ids[]` để UI không tự dựng id; nút Bỏ (`POST /videos/loai`, `models.py:1194`) và gửi Creative Desk gửi `file_ids`. Sightings dùng lại `video_sightings` (không FK, `models.py:109-118`; `sources_for_videos` `:1147` không JOIN videos) với id = `bai_id`.

## 4. Hiện trạng ảnh bị loại ở đâu (đã mở từng chỗ)
| Chỗ | file:dòng | Hành vi |
|---|---|---|
| Cổng luồng hình | `queue.py:129-153` (gọi `:688`, lỗi `:709`) | cần `Stream.*Video:`; slideshow = file chỉ-tiếng ⇒ lỗi; đo 151/259 (`queue.py:136-138`) |
| Format yt-dlp TikTok | `downloader.py:83-93` | mọi nhánh `vcodec!=none`; đo #trendanos80 (hashtag) |
| Nhãn lỗi | `phan_loai_loi.py:17-27` | xếp `tiktok`; giữ cho job video |
| Link lẻ TikTok | `nguon.py:485-490`, `utils.py:13` | chỉ `/video/<số>` |
| Music page | `scraper.py:46,130-147,164-175` | chỉ anchor `/video/`; feed XHR chỉ đếm |
| Giải captcha profile | `giai_captcha_worker.py:338-340` | gọi `quet_tren_trang` KHÔNG truyền loại (dòng `:50` chỉ là nhãn log) |
| IG | `ig_xhr_phan_tich.py:117-135`, `ig_quet_cuon.py:97,112`, `nguon_instagram.py:73,131` | giữ `media_type==2`; profile ép `/reels/` |
| IG link lẻ | `queue.py:868-877`, `nguon.py:399-409`; yt-dlp `instagram.py:528-530` | link lẻ chạy KHÔNG cookie; yt-dlp ném "no video" cho ảnh đơn |
| FB | `fb_xhr_phan_tich.py:124-133`, `nguon_facebook_trang.py:39,59-62`, test `test_fb_xhr_phan_tich.py:85,95` | bỏ `Photo`; chỉ tab videos/reels |
**P0 ĐÃ ĐO 20/11 (`probe-results.md`)**: TikTok HTML `/photo/` BÁC ⇒ thăm `/video/<id>` (có `imagePost` ẩn danh); tikwm `images` ĐO; music `/photo/`+feed `imagePost` ĐO; IG lưới `PolarisProfilePostsTabContentQuery`, link lẻ = script JSON trang `/p/` (yt-dlp hỏng); FB `/photos` ẩn danh TRẦN 8 ảnh/page, nút Photo không `owner`; hạn CDN 34–107h; trần TikTok 35, IG 20.
ĐO: slideshow qua yt-dlp = 1 format chỉ-tiếng (`downloader.py:83-90`); IG XHR đã đo 18/11 có node `media_type` 1/2/8 (`ig_xhr_phan_tich.py:3-10`). ĐỌC NGUỒN yt-dlp 2026.08.19 (`video-download/.venv`; bản mini [UNVERIFIED]): TikTok không đọc `imagePost` (`tiktok.py:328,645`); IG carousel = playlist, ảnh đơn raise. **GIẢ ĐỊNH chờ `probes.md`**: HTML `/photo/<id>` có `imagePost.images[].imageURL.urlList` không cookie · tikwm `images` · anchor `/photo/` ở music page · IG `image_versions2`/`carousel_media` + tên XHR lưới bài · FB `/photos` ẩn danh + container · hạn URL CDN · trần ảnh/bài.

## 5. Luồng dữ liệu (chế độ ảnh)
`POST /jobs{url,so_luong,loai_tai}` → cổng cờ + `chon_nguon(url,loai)`+`loai_ho_tro` → `create_job(loai_tai)` → `process_job` (cờ ở đầu; IG cần cookie khi `loai_tai!=video`, mở rộng `queue.py:871`) → `_fetch_refs(loai)` (nguồn trả ref đã phân loại; captcha-worker truyền `loai`) → tách → ảnh: thăm bài (throttle) → tải K ảnh về `downloads/<job>/<bai_id>/` → kiểm Pillow → `lifecycle_anh` (thư mục Drive, đẩy từng tệp thử lại + `_note_upload_outcome`, thumb 01, K hàng `videos`, xoá local) → `xong+1`+sighting. Sau đó MÁY CŨ: vào bộ/dọn/Creative Desk chạy per hàng. Ra: `GET /videos?loai=anh…` (hoặc `GET /anh` gom theo `bai_id`).

## 6. Phase (chi tiết `phases.md`; mỗi file một chủ)
| P | Việc | File sở hữu | Phụ thuộc | Giờ |
|---|---|---|---|---|
| P0 | Probe bài thật → `probe-results.md` | thư mục plan | — | 3 |
| P1 | Hợp đồng chung + dữ liệu + cổng | `web/models.py`, `web/models_anh.py`(mới), `web/vi_tu_con_song.py`, `web/app.py`, `src/…/utils.py`, `src/…/nguon.py`, `src/…/tai_anh_cau_hinh.py`(mới), `web/static/{stop-reason-text,bao-thieu}.js` (mục STOP), sửa khai báo 3 test khoá-cứng | P0 | 6 |
| P2 | Lõi tải/kiểm/Drive | `src/…/tai_anh.py`, `src/…/gdrive_upload.py`, `web/lifecycle_anh.py` | P1 | 6 |
| P3 | Nối dây queue | `web/queue.py`, `web/queue_anh.py`(mới), `web/giai_captcha_worker.py`, `src/…/phan_loai_loi.py` | P1,P2 | 5 |
| P4 | Loại trừ chỉ-video + vào bộ/dọn/mime | `web/models_cum.py`, `web/models_chia.py`, `web/nhap_cum_cli.py`, `web/thay_logo_routes.py`, `web/vao_bo_drive.py`, test cấu trúc (`POST /cum/{id}/video` thuộc `app.py` ⇒ P1) | P1 | 5 |
| P5 | TikTok liệt kê | `scraper.py`, `hashtag_enumerator.py`, `nguon_profile_yt_dlp.py`, `src/…/tiktok_anh.py`(mới) | P0,P1 | 6 |
| P6 | Instagram | `ig_xhr_phan_tich.py`, `ig_quet_cuon.py`, `nguon_instagram.py` | P0,P1 | 5 |
| P7 | Facebook photos | `fb_xhr_phan_tich.py`, `fb_quet_cuon.py`, `nguon_facebook_trang.py` | P0,P1 | 5 |
| P8 | UI | `web/static/{index.html,app.js,app-tien-ich-api-va-state.js,app-ve-luoi-the.js,app-ve-hang-doi-bo-loc.js,app-su-kien-hang-doi-bo-loc.js,the-luot-gon.js,app-nap-du-lieu.js,app-ban-giao-creative-desk.js,app-cum-cua-toi-gan-va-loai.js,app.css,huong-dan.html,huong-dan.js}` | P1 | 7 |
| P9 | Nghiệm thu E2E + deploy tối | `tests/`, `deploy/` (đọc) | tất cả | 3 |
Song song: P4‖P5‖P6‖P7‖P8 sau khi P1 đóng băng hợp đồng (`VideoRef.loai/anh_urls`, `liet_ke(..., loai)`, `loai_ho_tro`, cột DB). P3 cần P2.

## 7. Rủi ro (K×T)
| Rủi ro | Giảm thiểu |
|---|---|
| Ảnh lọt cụm/chia/thay logo (thấp×CAO) | D2 + test cấu trúc + đột biến M12 |
| Creative Desk từ chối/bỏ cả lô vì item ảnh (thấp×CAO) | meta-ads nhận `image/*` (mục 2); giữ `{f,n,u}` không `k`; smoke gửi 1 bộ có ảnh sang Creative Desk THẬT ở P9 |
| Ảnh vào bộ/dọn hỏng im lặng (thấp×CAO) | mime `image/` + test DriveGia có ảnh; M13; công tắc dọn `VIDEODL_BAT_DON_NGAY7` mặc định TẮT giữ nguyên |
| Bài hụt ảnh vẫn "xong" / tệp HTML đặt tên .jpg (TB×CAO) | D6 K==K, Pillow `verify`, M1,M2 |
| Chế độ video đổi hành vi (thấp×CAO) | D8 mặc định, test khoá cũ, M5-M8 |
| URL CDN ký hết hạn (TB×TB) | thăm bài ngay trước tải; 403/410 thăm lại 1 lần |
| Chặn nền tảng vì tải ảnh dồn (TB×CAO) | D10; ảnh qua HTTP CDN không gọi API |
| Log lộ id (TB×CAO) | `fbp`/`anh` vào mẫu che, M14; giữ `app.py:65` |
| Migration hỏng DB (thấp×CAO) | sao lưu `jobs.db.truoc-tai-anh-<giờ>` mẫu `models.py:400-417` + `.backup` tay; chỉ CỘNG cột |
| Đĩa mini đầy (TB×TB) | `check_disk_guard` trước mỗi bài (`queue.py:788-795`), xoá local theo bài |
Rollback: cờ tắt (tức thì) → revert commit; cột thừa vô hại. **Trước khi lùi bản prod**: `UPDATE jobs SET trang_thai='failed', ly_do_dung='lui_ban' WHERE loai_tai!='video' AND trang_thai IN ('pending','running','cho_xac_minh','cho_giai','dang_mo','dang_giai')` (`models.py:1374`; deploy cho phép `cho_xac_minh` tồn tại `deploy-to-mini.sh:228`) + xoá `profiles/<job_id>` của chúng; hàng `videos` `loai='anh'` giữ — code cũ sẽ HIỆN chúng như video ⇒ ẩn bằng cột loại có sẵn: `UPDATE videos SET da_loai_luc=<now>, loai_boi='lui_ban' WHERE loai='anh' AND da_loai_luc IS NULL AND video_id NOT IN (SELECT video_id FROM video_vao_bo WHERE an_luc IS NOT NULL AND drive_don_luc IS NULL)`. Hai điều kiện thêm là BẮT BUỘC: (a) giữ dấu Bỏ tay của user; (b) `vao_bo_don.py:105-108` thấy `da_loai` thì ghi mốc dọn `da_loai` mà KHÔNG gọi `trash_file` (`models_vao_bo.py:304`) ⇒ ảnh đã ẩn chờ ngày 7 mà bị đánh `da_loai` sẽ không bao giờ bị trash nguồn; nên loại chúng khỏi câu UPDATE (chúng đã ẩn khỏi lưới, ngày 7 chạy bình thường). **Hoàn nguyên khi bật lại**: kiểm `SELECT COUNT(*) FROM video_vao_bo WHERE ly_do_don='da_loai' AND video_id IN (SELECT video_id FROM videos WHERE loai='anh' AND loai_boi='lui_ban')` = 0 rồi `UPDATE videos SET da_loai_luc=NULL, loai_boi=NULL WHERE loai='anh' AND loai_boi='lui_ban'` (không hoàn nguyên thì ảnh bị ẩn nhưng `known_video_ids` `models.py:1240` vẫn chặn tải lại).

## 8. Tiêu chí hoàn thành
1. Cờ TẮT: toàn suite cũ xanh; chỉ SỬA khai báo 3 test khoá-cứng (thêm route/khoá/mã mới) — KHÔNG nới/bỏ assert; `POST /jobs` thiếu `loai_tai` ≡ hôm nay.
2. P0 có ≥3 bài thật/loại với ĐO/KHÔNG-ĐO từng giả định.
3. Mỗi nền tảng 3/3 bài thật trên máy chạy thật: đủ K ảnh đúng thứ tự trên Drive, `xong==N`; gửi 1 bộ có ảnh sang Creative Desk thật ⇒ bản copy có `videodesk_src` ⇒ hàng tự ẩn; dọn ngày 7 chạy thử trên 1 tệp ảnh với cờ dọn bật tạm.
4. 19 đột biến M1-M19 (`phases.md`) đều ĐỎ khi áp, XANH khi hoàn nguyên.
5. Hướng dẫn hiện đúng nền tảng/ảnh đang bật.

## 9. Câu hỏi còn lại cho USER
- ~~Q-A~~ ĐÃ GIẢI: meta-ads nhận ảnh (mục 2); bỏ cờ phụ; P9 thêm smoke Creative Desk thật.
- **Q-B (chờ USER)** FB page chế độ "Cả hai" ⇒ 400 (một lượt chỉ mở một tab) hay chạy lần lượt `/videos` rồi `/photos` chia N? Khuyến nghị 400 (KISS, N không mơ hồ); lật nếu user cần một lượt lấy cả hai. Thi công P7 theo 400 cho tới khi user đổi.

## 10. Phản hồi agy R1b (`~/agy-ws/exchange/videodesk-tai-anh-plan-R1b-agy.md`; mỗi điểm tự kiểm tại nguồn)
| Điểm | N/B | Bằng chứng / xử lý |
|---|---|---|
| (1)1 3 test khoá cứng đỏ | NHẬN | `test_web_app.py:731-757` (route mới phải khai), `test_trang_huong_dan.py:90` (`set(tn)` cứng), `test_nguon_fb_ads_va_drive.py:909-927` + `test_web_queue.py:647-663` (mọi `STOP_*` cần ở `bao-thieu.js`/`stop-reason-text.js`). Sửa AC: chỉ khai báo thêm, P1 làm cùng commit |
| (1)2 `UploaderLike` thiếu `create_folder` | NHẬN | `lifecycle.py:134-139` chỉ 4 hàm; fake thật = `tests/test_lifecycle.py:35`; `drive_gia_*` là `DriveVaoBo`. P2: Protocol mới trong `lifecycle_anh.py` + fake mới |
| (1)3 IG link lẻ không cookie, yt-dlp raise | NHẬN | `queue.py:868,871` (cookie chỉ khi hàng loạt), `nguon.py:399-409` không cookie, `instagram.py:528-530`. Sửa: cookie khi `loai_tai!=video`; ảnh đơn lấy qua `PhienIG`, probe I1 quyết |
| (1)4 `pacer.py` sai đường dẫn | NHẬN | file là `web/pacer.py` (`:41-47`, `:135-156`); đã sửa |
| (1)5 captcha worker `:338` | NHẬN | `giai_captcha_worker.py:338-340` gọi `quet_tren_trang` không `loai`; P3 truyền; thêm `_loc_trung_mot_lan` (`queue.py:720`); M16 |
| (2)1 `khong_ro` | NHẬN | D9; nguồn phân loại trong `liet_ke`, profile flat ⇒ browser |
| (2)2 FB/IG ca_hai, nguồn chỉ-video | NHẬN | D8 `loai_ho_tro` ⇒ 400; FB `ca_hai` ⇒ Q-B |
| (2)3 captcha + `la_link_le` | NHẬN | gộp vào D8 (một cửa `chon_nguon(url,loai)`), `queue.py:178,798,211` |
| (2)4 TikTok không có `cong` | NHẬN | `pacer.py:41-44`, `queue.py:806`; D10 |
| (2)5 backpressure/fallback/giữ-xoá local | NHẬN | `lifecycle.py:254,733,219-251`; D6; sửa mâu thuẫn: xoá local mọi nhánh lỗi |
| (2)6 phân loại lỗi + thứ tự dừng | NHẬN | D11 (`queue.py:599` ép `loai`), D5 thứ tự `:810-833` |
| (2)7 SQL rollback thiếu 4 trạng thái | NHẬN (1 phần) | mục 7 phủ đủ; BÁC phần "sửa `quet_khoi_dong`": mọi lối thoát `cho_*` đi qua `process_job` (cờ ở đầu) và có mốc 24h (`models.py:553`) |
| (2)8 đánh số đột biến | NHẬN | M1-M19 duy nhất trong `phases.md`; thêm IG con-video, log mask, captcha |
| (3)1 phụ thuộc P1/P3 đảo | NHẬN | P1 giữ app/nguon/utils/models (hợp đồng); P3 chỉ queue/captcha/phan_loai |
| (3)2 P7 thiếu file | NHẬN | `the-luot-gon.js:127-158`, `app-nap-du-lieu.js`, `app-su-kien-hang-doi-bo-loc.js:132,166` vào P8; `bao-thieu.js` vào P1 |
| (3)3 `tiktok_anh.py` lệch ranh | NHẬN | chuyển sang P5; `parse_photo_url` regex nhỏ ở `utils.py` (P1) |
| (3)4 thêm T9/I7/F6 (T4b) | NHẬN T9,I7,F6; T4b HẾT HIỆU LỰC | nhạc đã bỏ |
| (4)1 dùng lại `/thumbs` | NHẬN | D12; ảnh nay là hàng `videos` nên route nguyên vẹn |
| (4)2 dùng lại `video_sightings` | NHẬN | `models.py:109-118` không FK, `:1147` không JOIN videos |
| (4)3 bỏ `khong_ro` | NHẬN | D9 |
| (4)4 `chon_nguon(url, loai=)` | NHẬN | D8; 2 test khoá giữ xanh vì mặc định |

## 11. Phản hồi agy R2b (`~/agy-ws/exchange/videodesk-tai-anh-plan-R2b-agy.md`; từng điểm tự kiểm tại nguồn)
| Điểm | N/B | Bằng chứng / xử lý |
|---|---|---|
| 21 dòng bảng R1b khớp nguồn | GHI NHẬN | agy tự kiểm; tôi lấy mẫu `models_chia.py:1742`, `queue.py:868-871`, `pacer.py:41-44` đúng |
| `models_chia.py:280` sót `LA_VIDEO` | NHẬN | `:280` = `SELECT COUNT(*) FROM videos v WHERE v.job_id=? AND NOT (d)`; D2 thêm ngoài `DIEU_KIEN_VAO_LUOT_CHIA` (test `:129` cứng 4 khoá) |
| `nhap_cum_cli.py:58-60` `_cho_chia` | NHẬN | truy vấn `jobs` `done` không chia; thêm EXISTS `LA_VIDEO` |
| 3 câu thiếu bí danh `v` | NHẬN | `models_chia.py:320`, `nhap_cum_cli.py:80,237` là `FROM videos WHERE job_id=?` ⇒ thêm `v`; test cấu trúc bắt thiếu bí danh |
| `NOT(CON_SONG_CHUNG)` ở `:412,1135` | NHẬN | viết `NOT (CON_SONG_CHUNG AND LA_VIDEO)`; `AND LA_VIDEO` ngoài sẽ để ảnh "sống" trong nháp |
| Rollback `da_loai_luc IS NULL` + tương tác dọn | NHẬN | `vao_bo_don.py:105-108`, `models_vao_bo.py:304`; mục 7 có điều kiện loại ảnh đã ẩn chờ dọn + SQL hoàn nguyên + kiểm 0 |
| Thumb id vs `video_nay_cua_toi` | NHẬN | `models.py:1232` khớp `v.video_id`; D12 đặt thumb theo `video_id` file 01, `GET /anh` trả `thumb_id` |
| Nút Bỏ `loaiDaChon` + file JS | NHẬN | `app-cum-cua-toi-gan-va-loai.js` vào P8; gửi `file_ids` (chia lô sẵn có); `video_de_loai` giữ nguyên `models.py:1194` |
| FILTER_GROUPS client vs nạp server | NHẬN | chọn (ii): "Loại" = công tắc Video/Ảnh kiểu chip vào bộ gọi `napLaiThuVien()` (nạp `/videos` hoặc `/anh`), KHÔNG là bucket `FILTER_GROUPS` (bucket chỉ lọc `state.videos` đã nạp) |
| `LinkLe.liet_ke` cookies + `id_tam` `anh-` | NHẬN | D8; `nguon.py:511,528,557` thuộc P1 (chủ `nguon.py`) |
| `_note_upload_outcome` khi tạo thư mục trượt | NHẬN | `lifecycle.py:219-251` không gọi; D6/P2 |
| Thay logo: 422 trước `:274` cho admin lẫn member | NHẬN | `thay_logo_routes.py:275` `ids and not la_admin(...)` bỏ qua admin ⇒ kiểm `loai='anh'` riêng, trước dòng đó, cho `ids` và `vao_bo` |
| `POST /cum/{id}/video` thuộc `app.py` | NHẬN | `app.py:1173` ⇒ chuyển sang P1 |
| M14 `fbp` vs `anh` mâu thuẫn | NHẬN | chỉ `fbp` vào `utils.py:135` (mục D3); M14 = bỏ `fbp` |
| Q-A (meta-ads nhận ảnh) | NHẬN, ĐÃ GIẢI | `creative_self_bundle_import.py:32-34` (tự đọc), `:214-218` (ĐP), `videodesk-handoff.ts:160`; bỏ cờ phụ; smoke thật ở P9 |
