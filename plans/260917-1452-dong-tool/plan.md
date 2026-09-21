# Plan đóng tool Video Desk — 17/09

**Một file. Không sinh thêm bàn giao, không sinh thêm report cho từng phase.**
3 ngày qua đẻ 31 file plan / 4 744 dòng cho 7 574 dòng code — đó là chỗ đang ăn thời gian,
nên plan này cố ý ngắn và là file duy nhất được cập nhật tại chỗ.

## Đang chạy thật trên mini (12:39 hôm nay)

Tải hashtag/music/profile → Drive · thư viện có lọc 5 tiêu chí · hàng đợi chỉ thấy lượt
mình · thư viện + ảnh xem trước chỉ thấy của mình · trang Cookie của tôi (dán) · trần
20 lượt / 1000 video / 800 trang theo cookie · 285 test xanh.

## Còn lại — 6 việc, xếp theo GIÁ TRỊ CHO USER

| # | việc | vì sao ở vị trí này | ước |
|---|---|---|---|
| 1 | **Nút Xoá** (loại khỏi kho) | User bực nhất: chọn video xong không làm được gì. Nằm trọn bên này, không chờ ai | 2h |
| 2 | **Trang Cài đặt riêng** | Mockup đã duyệt. Gỡ khối cookie chật chội khỏi trang chính + cho admin đặt trần | 3h |
| 3 | **Tạo bộ tự tìm** → Creative Desk | Giá trị cao nhất nhưng đụng repo thứ hai ⇒ không để nó chặn 1-2 | 3-4h |
| 4 | **Metadata 0/10** | Thẻ nào cũng "chưa có tiêu đề" — xấu, nhưng không chặn ai dùng | 1-2h |
| 5 | **Phân tích nội dung** | Tính năng mới, chưa ai cần gấp | 3h |
| 6 | **Drive trượt tự thử lại** | Lỗi chưa từng xảy ra thật (0 ca đo được) | 1h |

---

## 1. Nút Xoá — loại khỏi kho

**User chốt:** loại là **việc riêng**; người khác vẫn quét và tải lại được. Xoá = đưa vào
**Thùng rác Drive** (SA chỉ có quyền Content manager, không xoá vĩnh viễn được — và không
nâng quyền, vì khoá đó quản cả kho creative công ty).

**Chạm:**
- `src/tiktok_music_downloader/gdrive_upload.py` — thêm `trash_file(file_id)` =
  `files().update(fileId=…, body={"trashed": True}, supportsAllDrives=True)`.
- `web/models.py` — migration: bảng `video_da_loai(video_id, nguoi_loai, loai_luc)`.
  **Theo người**, không phải cờ chung trên `videos` — đó là điều kiện để "loại là việc riêng".
- `web/models.py::known_video_ids` — **giữ nguyên, không xét bảng mới**. Người khác quét
  trúng vẫn bỏ qua như cũ vì file vẫn còn; chỉ khi chủ đã loại thì *của chủ* mới biến mất.
  ⚠ Ca cần quyết lúc gõ: chủ loại xong rồi tự quét lại tag đó — có tải lại không? Theo user
  ("loại rồi thì đừng mang về nữa") ⇒ **không**, và đó chính là việc của bảng `video_da_loai`.
- `web/app.py` — `POST /videos/loai` nhận ≤50 id, kiểm chủ qua JOIN jobs (404 cho id không
  phải của mình), trả `{da_loai, khong_phai_cua_ban, drive_truot}`.
- `web/static/app.js` + `index.html` — nút **Xoá** ở thanh chọn.

**Thứ tự bắt buộc:** trash Drive **trước**, ghi mốc **sau**. Trash trượt mà đã ghi mốc thì
video biến khỏi thư viện trong khi file còn nguyên, và không ai phát hiện.

**Nghiệm thu (phải phân định):**
- A loại video X → thư viện A không còn X · thư viện B **không đổi** · Drive: X ở Thùng rác.
- A quét lại tag chứa X → **không** tải lại X.
- B quét trúng X → B vẫn nhận được X.
- **Đột biến phải ĐỎ:** hoist mốc lên trước lời gọi trash · đổi `update(trashed)` thành
  `delete()` · bỏ điều kiện `nguoi_loai` (biến loại-riêng thành loại-chung).

**Sao lưu trước migration:** `PRAGMA wal_checkpoint(TRUNCATE)` rồi
`cp jobs.db jobs.db.bak-260917-hhmm` trên mini.

---

## 2. Trang Cài đặt riêng

Mockup đã duyệt: `plans/260917-1424-settings-page/mock-settings-v2.html`
(bản đăng: https://claude.ai/artifact/TkNZvMxi4Qat6mKAmVeJuU).

**Tab Của tôi**
- Cookie: **dán HOẶC chọn tệp `.json`** (user chốt). Tệp đọc ở trình duyệt rồi gửi cùng
  một đường `PUT /me/cookie` — không thêm route, không upload multipart.
- Hạn mức hôm nay: 3 thanh lượt / video / trang. Chỉ đọc.

**Tab Quản trị** (chỉ `is_admin`, kiểm ở **server mỗi request**, không ẩn ở UI)
- Bảng người dùng: email · có cookie chưa · trần lượt/video từng người · đã dùng hôm nay ·
  cho/bỏ quyền admin.
- Trần chung toàn công ty (tổng video/ngày, trần mỗi lượt cho thành viên).
- **Không có nút "thêm người"** — ai vào được là do cửa Cloudflare Access quyết.

**Chạm:** bảng `settings(khoa, gia_tri, doi_boi, doi_luc)` + `members(email, la_admin,
tran_luot, tran_video, lan_dau_thay)`; `web/settings.py` mới; `GET /settings`,
`PUT /settings`; trang tĩnh `/settings` riêng (`settings.html` + `settings.js`), **không**
nhét vào `index.html`.

⚠ **Trần cứng trong code** (vd không quá 3× mặc định) để trang Setting không thành cửa tắt
lưới. Và mọi thay đổi ghi `settings_audit`.

**Nghiệm thu:** thành viên gọi `PUT /settings` → **403** (không phải ẩn nút) · admin đổi
trần → lượt tải tiếp theo áp số mới · `GET /settings/effective` in giá trị đang áp **kèm
nguồn** (DB / env / mặc định) — luật "rơi về mặc định phải BÁO".
**Đột biến ĐỎ:** bỏ kiểm `is_admin` ở server ⇒ test 403 đỏ.

---

## 3. Tạo bộ tự tìm → Creative Desk

**Không có bức tường nào.** Đo: branch protection `403 Free plan` ⇒ chưa bao giờ bật ⇒ merge
không đòi CI; meta-auto vẫn merge qua cổng cục bộ `scripts/ci-local/merge-pr.sh` (PR #198
merge 04:39Z hôm nay). `backend/app/` và `frontend/src/` **không lane nào giữ**.

**Đường (agy R2 + spec 15/09):** Video Desk chuyển tiếp **JWT Cloudflare Access của chính
người bấm** sang meta-auto qua header; meta-auto tự bóc email → map ra `User` → gọi thẳng
`_create_self_bundle` (`creative_order_service.py:84`, **đã có sẵn, không viết mới**).
Video Desk **không thể mạo danh** vì không giữ khoá ký của Cloudflare.

**Lát cắt chiều nay:** bỏ lớp service token ở Edge, gọi thẳng. Đánh đổi khai rõ: route mới
phơi ra internet, nhưng JWT chỉ cho tạo bộ **cho chính người cầm nó** ⇒ rủi ro nhỏ.
Lớp Edge bổ sung sau.

**Ràng buộc khi chạm meta-auto:** worktree riêng từ `origin/main` (KHÔNG dùng checkout
chính đang ở `feat/ci-local-gate`) · **không** chạm `scripts/deploy.sh` (lane khác đang vá) ·
`system-map.json` + `docs/system-map/overview.md` phải **regen**, không sửa tay.

**Nghiệm thu:** bấm nút với 3 video → bộ hiện bên Creative Desk, `requester_id` = **đúng
email người bấm**, không phải bot. Đó là phép phân định; "API trả 200" thì không.

---

## 4. Metadata 0/10

⚠ **CHƯA PHÂN ĐỊNH ĐƯỢC LỖI Ở ĐÂU.** Control trên DB dev **vô hiệu** — dev có 0 video.
`title · author · region · duration` cùng rỗng cả bốn ⇒ nghi một nguyên nhân chung ở đầu
nguồn, nhưng đó là **giả thuyết**.

**Phép phân định phải chạy TRƯỚC khi sửa:** chạy một job hashtag nhỏ (≤5 video) trên mini,
bắt `VideoRef` ngay sau bước liệt kê — nếu `ref.title` đã rỗng từ đó ⇒ lỗi ở extractor;
nếu có mà DB rỗng ⇒ lỗi ở đường ghi. **Không vá trước khi có số này.**

Sau khi vá: script vá ngược 10 video cũ (đọc lại metadata theo `video_id`).

---

## 5. Phân tích nội dung · 6. Drive tự thử lại

**5** — gọi AI mô tả video đã chọn, trả mô tả + thẻ chủ đề. Chưa có ràng buộc user đặt ⇒
hỏi trước khi gõ.

**6** — `web/lifecycle.py::on_video_verified`: `@retry(stop=stop_after_attempt(3),
wait=wait_exponential(multiplier=2, min=2, max=20))`, neo theo tiền lệ `downloader.py:136`.
Comment **phải khai giới hạn phép đo**: trung vị 1,67 MB / lớn nhất 4,07 MB, n=10, video
TikTok ngắn, `duration` toàn NULL nên không có đường đối chiếu thứ hai — người sau gặp file
500 MB biết trần này chưa từng đo ở cỡ đó. Chỉ retry 429/5xx/lỗi mạng, **không** retry
403/404. Đếm số lần thử lại và in ra.
Và comment khoá bẫy hai lớp tại `gdrive_upload.py:208`: `.execute()` để `num_retries=0`
**có chủ đích** vì lớp thử-lại nằm ngoài.

---

## Cắt bỏ — phần này cũng là plan

- **Không bàn giao giữa phiên nữa cho mạch việc này.** File này là trạng thái.
- **Không review agent cho việc < 100 dòng.** Đột biến + test là đủ.
- **Không report riêng cho từng phase.** Cập nhật bảng trên tại chỗ.
- **Không làm:** vị trí hàng đợi / ETA / huỷ job · chạy song song nhiều lượt · TTL cookie ·
  tab "Đã loại" + khôi phục. Đều là tiện nghi, không ai đang bị chặn vì thiếu chúng.

## Deploy

Gộp, không deploy từng việc: **1+4** một chuyến (có migration ⇒ sao lưu DB), **2+3** chuyến
sau. Mỗi chuyến cần user gật, và phép nghiệm thu phải **lật**, không nhận `healthz 200`.
