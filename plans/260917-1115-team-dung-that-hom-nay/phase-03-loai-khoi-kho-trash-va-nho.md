---
phase: 3
title: "P4 'Loại khỏi kho' = Thùng rác Drive + nhớ đã loại (ăn khớp lọc trùng)"
status: pending
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 3 — P4 (Deploy 2; CÓ migration ⇒ sao lưu `jobs.db` trước)

## Thiết kế dứt khoát: nhớ-đã-loại ↔ lọc trùng

**Nguyên tắc:** hàng `videos` là **sổ "kho đã từng có video này"**, không phải "video đang hiện". Xoá là **đổi trạng thái**, không xoá hàng.

| thứ | quyết |
|---|---|
| schema | `videos` + `da_loai_luc TEXT NULL` + `loai_boi TEXT NULL` (qua `_add_column_if_missing`, `models.py:126-165`; mẫu `music_id`) |
| Drive | `files().update(fileId=drive_file_id, body={"trashed": True}, supportsAllDrives=True, fields="id,trashed")` — SA Content manager làm được; `files.delete` **không** (đòi organizer). Hàm mới `DriveUploader.trash_file(file_id) -> UploadResult` trong `gdrive_upload.py`, đi qua cùng lối `try/HttpError` như `_create_drive_object:184-240`, **service dựng mới mỗi lần** (`_build_service`) |
| thứ tự ghi | **trash trước, mốc sau** (`guard-marker-and-claim-write-ordering.md` vế 1). Drive trả `trashed=true` ⇒ mới `UPDATE videos SET da_loai_luc=?, loai_boi=? WHERE video_id=?`. Trượt ⇒ không ghi gì, trả lỗi cho người bấm |
| lọc trùng | `known_video_ids` (`models.py:396-411`) **giữ nguyên câu SQL** — không thêm `WHERE da_loai_luc IS NULL`. ⇒ video đã loại **không bao giờ tải lại, với bất kỳ ai** (quyết định 2 + 5 cùng thoả). Đây là cả một dòng comment trong hàm: *"cột `da_loai_luc` cố ý KHÔNG xét ở đây"* — ai thêm sau sẽ mở lại lỗ "tải lại rác" |
| thư viện | `list_videos`/`count_videos` thêm `AND v.da_loai_luc IS NULL` |
| thumb | **giữ** (2 KB, chỉ chủ thấy qua tab "Đã loại" sau này). Không unlink |
| `drive_file_id` | giữ nguyên — trỏ vào thùng rác; tab "Đã loại" (mai) dùng nó để khôi phục `trashed=false` trong 30 ngày. Sau 30 ngày Drive tự huỷ, hàng vẫn còn với `da_loai_luc` ⇒ vẫn không tải lại — đúng ý user |
| `video_sightings` | không đụng (append-only) |

**Ca biên:**
1. **B quét trúng video A đã loại** ⇒ bỏ qua như video đang có (sighting `da_tai=0` vẫn ghi cho job B). B **không có đường lấy** video đó — hệ quả trực tiếp của quyết định 2+5; ghi vào CHECKLIST để user biết. Nếu sau này muốn "B vẫn được", đường rẻ là khôi phục từ thùng rác + đổi chủ, không phải tải lại.
2. **A bấm loại video của B** (bỏ lọc thì không thấy — nhưng API nhận `video_ids` tự do) ⇒ server kiểm chủ: `JOIN jobs WHERE j.nguoi_tao = me` (admin: bỏ điều kiện). Không phải chủ ⇒ **404** cho id đó, không 403. Trả về từng id: `{"da_loai": [...], "khong_phai_cua_ban": [...], "drive_truot": [...]}` — không nuốt.
3. **Video đã ở thùng rác rồi** (ai đó trash tay trên Drive) ⇒ `files.update trashed=true` idempotent, 200 ⇒ ghi mốc bình thường.
4. **File đã bị xoá vĩnh viễn trên Drive** (404 từ API) ⇒ coi là "đã không còn trên Drive": **vẫn ghi mốc** với `loai_boi`, và log `WARNING` riêng — đây là ca duy nhất mốc ghi mà không có `trashed=true`; khai rõ trong code. Không ghi mốc ⇒ video ma hiện mãi với ảnh vỡ.
5. **`drive_file_id IS NULL`** (không có ở dữ liệu hiện tại — 10/10 có) ⇒ không gọi Drive, chỉ ghi mốc; log WARNING.
6. **Job đang chạy đúng lúc bị loại**: video đã lên Drive rồi mới có hàng ⇒ không có xung đột với upload; `_job_folders` không liên quan.
7. **Loại hàng loạt 500 id**: vòng gọi Drive tuần tự, mỗi lần dựng service mới ~0,3-0,5 s ⇒ 500 id ≈ vài phút trong request HTTP. Hôm nay: giới hạn **≤ 50 id/lượt** (`422` nếu hơn), UI gửi theo lô. Không đưa vào worker (worker là một luồng đang tải).

## Endpoint + UI
- `POST /videos/loai` body `{"video_ids": [..]}` (`Depends(require_user)`), kiểm shape id như `/thumbs` (`app.py:250`: `isdigit`, `≤32`).
- UI: nút trong `selection-bar` (`index.html:92-99`) **"Loại khỏi kho"** — không dùng chữ "Xoá" trần; modal xác nhận: *"Đưa N video vào Thùng rác Drive (khôi phục được trong 30 ngày). Tool sẽ KHÔNG tải lại các video này cho bất kỳ ai."* Câu thứ hai là hậu quả quyết định 5 — người bấm phải đọc nó.
- Nút "Gồm vào giỏ"/"Phân tích" giữ nguyên toast "chưa làm".

## Nghiệm thu (`tests/test_lifecycle.py` mẫu `FakeUploader:35`, `tests/test_web_app.py`)
- Fake `trash_file` thành công ⇒ hàng có `da_loai_luc`, `/videos` của chủ không còn id đó, `count_videos` giảm 1, **`known_video_ids` vẫn trả id đó** (test tên `test_a_removed_video_is_still_known_to_the_dedup` — đây là test bảo vệ quyết định 5).
- Fake trượt (`FAILED`) ⇒ **không** có `da_loai_luc`, response liệt id trong `drive_truot`.
- B gọi loại id của A ⇒ 404 cho id đó, hàng không đổi; admin ⇒ được.
- 404 từ Drive (`HttpError` status 404 trong fake) ⇒ mốc ghi + WARNING.
- Ca dương cho `known_video_ids`: id chưa từng có ⇒ không trả (để test trên có sức phân định).
- **Đột biến phải ĐỎ** (lớp hỏng-âm-thầm — mất dữ liệu / tải lại rác):
  (i) hoist `UPDATE videos` lên trước `trash_file` ⇒ test "trượt không ghi mốc" đỏ;
  (ii) thêm `WHERE da_loai_luc IS NULL` vào `known_video_ids` ⇒ `test_a_removed_video_is_still_known_to_the_dedup` đỏ;
  (iii) đổi `files().update` thành `files().delete` ⇒ fake ghi nhận phương thức ⇒ đỏ (vai SA không cho delete; test khoá đúng lời gọi).
- Trên mini (Deploy 2): **trước khi gõ**, kiểm vai SA kèm giờ: `drives().get(driveId="0AASy4v5CJAkfUk9PVA", fields="capabilities")` → `canDeleteDrive=False` mong đợi (Content manager). Sau deploy, loại **1 video thật của user** rồi kiểm trên Drive web: file trong Thùng rác của Shared Drive; `sqlite3 ... "SELECT video_id,da_loai_luc,loai_boi FROM videos WHERE da_loai_luc IS NOT NULL"` → 1 hàng; `/videos` của user → 9. Khôi phục bằng tay trên Drive web nếu cần (mốc trong DB vẫn còn — đúng thiết kế; tab khôi phục là việc mai).

## Migration + sao lưu (Deploy 2)
1. Trên mini: `cp web/data/jobs.db web/data/jobs.db.bak-260917-<hhmm>` (mẫu `.bak-260915-*` đã có). WAL: chạy `sqlite3 jobs.db "PRAGMA wal_checkpoint(TRUNCATE)"` **trước** `cp`, khi 0 job chạy — không thì bản sao thiếu trang WAL.
2. Deploy ⇒ boot chạy `init_db` ⇒ `ALTER TABLE videos ADD COLUMN` ×2. Nghiệm thu: `PRAGMA table_info(videos)` có 13 cột.
3. Lui: `rollback-on-mini.sh` về mã cũ; cột thừa vô hại với mã cũ (`SELECT v.*` chỉ thêm khoá vào dict).
