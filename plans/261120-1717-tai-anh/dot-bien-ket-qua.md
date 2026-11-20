# Kết quả nghiệm thu đột biến (HEAD b6c5b55, 2026-11-20)

Mỗi dòng: áp phép sửa tối thiểu (1 chỗ, xác nhận `git diff --stat`) → chạy test đích → `git checkout --` → chạy lại. "ĐỎ" = số FAILED+ERROR khi áp.

| M# | File áp | Phép sửa | Test đích | ĐỎ khi áp | XANH khi hoàn nguyên | Ghi chú |
|---|---|---|---|---|---|---|
| M1 | src/.../tai_anh.py | `zip(urls_moi_tep[:-1], kieu)` + bỏ `len(tep) != k` | tests/test_tai_anh_loi.py | 10 | xanh | |
| M2 | src/.../tai_anh.py | `_kiem_anh_bang_pillow` trả `"jpg"` ngay | test_tai_anh_loi.py | 3 | xanh | |
| M3 | web/lifecycle_anh.py | `ghi_bai_anh` (file_id tạm) lên trước vòng upload | test_lifecycle_anh.py | 5 (gồm 1 ERROR) | xanh | |
| M4 | web/lifecycle_anh.py | `_bo_thu_muc_dang` `return` ngay | test_lifecycle_anh.py | 4 (gồm 1 ERROR) | xanh | |
| M5a | web/queue.py | `_chon_nguon_theo_loai` bỏ đối số loại | test_queue_anh.py | 2 | xanh | |
| M5b | web/queue.py | `kw_loai_job = {}` (liet_ke không nhận loai) | test_queue_anh.py | 1 | xanh | |
| M6 | src/.../hashtag_enumerator.py | `kw_loai = {}` | test_tiktok_anh.py | 4 | xanh | |
| M7 | src/.../nguon_instagram.py | bỏ `loai=loai` ở `ig_quet_cuon.quet` | test_ig_anh.py | 2 | xanh | |
| M8 | src/.../nguon_facebook_trang.py | `if loai == "anh":` (16 cách) -> `if False:` | test_fb_anh_page.py | 1 | xanh | |
| M9 | web/queue.py | cổng cờ `process_job` -> `if False:` | test_queue_anh.py | 2 | xanh | |
| M10 | web/queue.py | `if verify_video_stream(path):` -> `if True:` | test_web_queue.py + test_queue_anh.py | 3 | xanh | |
| M11 | src/.../tai_anh.py | `if not kiem_video(part):` -> `if False:` | test_ig_anh.py + test_tai_anh_loi.py | 2 | xanh | |
| M12 | models_cum / models_chia / nhap_cum_cli / thay_logo_routes | bỏ `{LA_VIDEO}` ở TỪNG câu (3+8+3+6 = 20 lần, riêng từng lần) | test_anh_khong_lot_vao_tinh_nang_video.py | >=1 mỗi lần | xanh | Trước khi bổ sung: 7 câu chỉ đỏ test cấu trúc (models_cum:102, models_chia:762/852/1135, thay_logo_routes:963/1033). Nay cả 7 có test hành vi đỏ (mục dưới). |
| M12v | web/nhap_cum_cli.py | `FROM videos v` -> `FROM videos` (bỏ bí danh) | cùng file | 2 | xanh | |
| M12b | web/thay_logo_routes.py::_ban_vao_bo_cua | bỏ `{LA_VIDEO}` ở câu :963 | `test_ban_vao_bo_cua_khong_nhan_ban_cua_anh` | 2 (thành viên + admin) | xanh | MỚI, test hành vi |
| M12c | web/thay_logo_routes.py::chu_video_vao_bo | bỏ `{LA_VIDEO}` ở :1033 | `test_chu_video_vao_bo_khong_tra_chu_cua_anh` | 1 | xanh | MỚI |
| M12d | web/models_cum.py::_VIDEO_TRONG_LO_CAT | bỏ `{LA_VIDEO}` ở :102 | `test_khung_cum_khong_tra_anh_nhet_thang_vao_cum` | 1 | xanh | MỚI |
| M12e | web/models_chia.py::_giai_quyet_kieu | bỏ `{LA_VIDEO}` ở :762 | `test_duyet_kieu_tao_cum_moi_khong_nhan_anh_nhet_vao_kieu` | 1 | xanh | MỚI |
| M12f | web/models_chia.py::_giai_quyet_kieu_vao_cum | bỏ `{LA_VIDEO}` ở :852 | `test_duyet_kieu_gop_vao_cum_co_san_khong_nhan_anh_nhet_vao_kieu` | 1 | xanh | MỚI |
| M12g | web/models_chia.py::_kiem_video_ids_thao_tac | bỏ `{LA_VIDEO}` ở :1135 | `test_thao_tac_theo_id_tu_choi_anh_nhu_video_da_loai` | 1 | xanh | MỚI |
| M13a | web/vao_bo_drive.py | bỏ `or mimeType contains 'image/'` ở truy vấn Shared Drive | test_anh_vao_bo_va_don.py + test_vao_bo_drive_that.py | 2 | xanh | |
| M13b | web/vao_bo_drive.py | cùng, ở truy vấn Thùng rác | cùng | 2 | xanh | |
| M14 | src/.../utils.py | bỏ `fbp` khỏi `_MAU_ID_NEN_TANG` | test_log_khong_in_url_token.py + test_tai_anh_du_lieu.py | 1 | xanh | đỏ ở `test_che_id_log_che_id_anh_facebook_va_instagram_giu_id_tiktok` |
| M15 | web/queue_anh.py | `increment_job_counts(xong_delta=1)` lên trước `hook(...)` | test_queue_anh.py | 3 (gồm 1 ERROR) | xanh | |
| M16 | web/giai_captcha_worker.py | bỏ `**kw_loai(...)` ở `quet_tren_trang` | test_queue_anh.py | 3 | xanh | |
| M17 | web/static/app-su-kien-hang-doi-bo-loc.js | `taoJobBody(..., job.insight_goc)` bỏ `job.loai_tai` (2 chỗ) | test_tai_anh_giao_dien_browser.py | 1 | xanh | trình duyệt thật chạy được (5 test khác skip theo điều kiện riêng) |
| M18 | web/lifecycle_anh.py | 3 lời gọi `_note_upload_outcome` -> no-op | test_lifecycle_anh.py | 2 | xanh | |
| M19 | web/queue_anh.py | `loai=LOAI_LOI_NGUON` cho mọi lỗi | test_queue_anh.py | 2 | xanh | |

Lỗ hổng phát hiện: 7 câu `{LA_VIDEO}` (M12b-g) chỉ đỏ test cấu trúc — đã bổ sung 7 test hành vi cuối `tests/test_anh_khong_lot_vao_tinh_nang_video.py` (lệnh áp ghi ở docstring đầu file).
Không có lỗ hổng ở M1-M11, M13-M19.
