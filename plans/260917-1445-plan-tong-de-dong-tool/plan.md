---
title: "Plan tổng để ĐÓNG tool Video Desk"
description: "Một plan duy nhất từ hiện trạng 17/09 tới 'tool xong' — xếp theo giá trị cho user, kèm phép nghiệm thu có sức phân định, cái không làm, và quy trình cắt bỏ"
status: pending
priority: P0
effort: "2,5 ngày làm việc (không tính bộ tự tìm)"
tags: [video-download, dong-tool, plan-tong]
created: 2026-09-17
---

# Plan tổng để đóng tool — viết bởi kongming, 17/09 14:50

Kiểm kê + đề bài gốc + mức hoàn thành: [`kiem-ke-3-ngay.md`](./kiem-ke-3-ngay.md). Tóm một dòng:
**đề bài 14/09 ≈ 80% (phần thiếu là nghiệm thu cần người) · đề bài mở rộng tới 17/09 ≈ 55% · ~19% commit là dư thừa (1 380 dòng) · dòng plan/report thêm vào = 81% dòng code thêm vào.**

Sự thật đắng nhất không nằm ở code: **3 ngày, 4 job, 10 video, `PUT /me/cookie` = 0 lần**, 2 IP ngoài chủ yếu là trình duyệt tự poll `GET /jobs`. Tool được xây nhiều, **gần như chưa ai dùng**. Nên việc giá trị nhất hôm nay không phải thêm tính năng — là **đưa một người thứ hai vào dùng** và mở đường cho họ tìm thấy tool (link nav).

## Định nghĩa "tool xong" (đo được)

1. Một thành viên **không phải user** tự dán cookie → tạo job → video lên Drive → thấy đúng video mình, loại được video không cần, không thấy gì của người khác.
2. User (admin) xem được toàn hàng đợi + đặt trần từng người và trần chung qua trang Cài đặt.
3. Tool tìm thấy được từ nav meta-auto.
4. 6 Success Criteria của `plan.md` 14/09 đều có phép đo kèm giờ.
5. Cái gì hiện trên UI thì có backend — **không còn nút "chưa làm"** (user đã chụp ảnh `anh-user-2-tinh-nang-chet.png`).

Bộ tự tìm (C3) **không** nằm trong định nghĩa này — nó phụ thuộc repo khác, có kongming riêng, và không chặn 5 điểm trên.

## Thứ tự — theo giá trị cho user, không theo độ dễ

```
T0 (hôm nay, 0 code) ─► T1 (Deploy 3, có migration) ─► T2 (Deploy 4) ─► T4 nghiệm thu đóng
                                    │
                                    └─► T3 bộ tự tìm (kongming khác; repo meta-auto; không chặn T1/T2/T4)
```

### T0 — HÔM NAY, không gõ code (≈1h, phần lớn là việc user)

| # | việc | ai | phép nghiệm thu (phân định) | chặn |
|---|---|---|---|---|
| 0.1 | Đặt `VIDEODL_ADMIN_EMAILS=<email user>` vào `~/.config/videodl/env` trên mini, `launchctl kickstart -k gui/$(id -u)/com.astronex.videodl` | user/điều phối | `grep -c ADMIN ~/.config/videodl/env` 0→1; gọi `models.list_jobs(DB, None if is_admin(email) else email)` trên mini → **4** (trước: 1) | không gì |
| 0.2 | **Người thứ hai thật**: dán cookie ở "Cookie của tôi", tạo 1 job **hashtag** ≤5 video | user nhờ 1 thành viên | log `grep -c "PUT /me/cookie"` 0→≥1 · `ls web/data/cookies` 1→2 tệp `-rw-------` · job `done` · `SELECT count(*) FROM videos WHERE title IS NOT NULL` 0→≥1 (**đồng thời là control cho nợ metadata**) · người đó `GET /jobs` chỉ thấy job mình | 0.1 không bắt buộc |
| 0.3 | Merge PR #192 (link nav) + deploy meta-auto theo luật repo đó. Merge **không cần CI**: branch protection trả `403 Upgrade to GitHub Pro` (đo 17/09). Cổng cục bộ `scripts/ci-local/merge-pr.sh` nằm trên nhánh `feat/ci-local-gate`, **chưa có trên `origin/main`** (đo `git ls-tree origin/main` = 0 file) — dùng nó thì checkout nhánh đó, không tìm ở main | điều phối, **cần user gật** | mở `automation.*` thấy link; bấm → `video.*`; `curl` `automation.*` vẫn 200 | user gật; lane meta-auto rảnh (điều phối đo: `backend/app/`, `frontend/src/` không ai giữ) |
| 0.4 | Kiểm policy Cloudflare Access `video.nobidigital.asia`: ai vào được, Session Duration | user | ảnh chụp policy + ghi 1 dòng vào CHECKLIST | không gì |

### T1 — Những gì user dùng hằng ngày còn thiếu (≈7-9h gõ+test ⇒ 1 ngày; **một** Deploy 3, có migration)

| # | hạng mục | file:dòng phải chạm | phép nghiệm thu | ước lượng |
|---|---|---|---|---|
| 1.1 | **Bỏ khỏi thư viện** (= trash Drive + nhớ đã loại) — thiết kế đã xong ở `plans/260917-1115-team-dung-that-hom-nay/phase-03-loai-khoi-kho-trash-va-nho.md`, dùng nguyên | `web/models.py:126-165` (`_add_column_if_missing`: +`da_loai_luc`,`loai_boi`) · `models.py:396-411` `known_video_ids` **giữ SQL**, thêm comment cấm lọc · `list_videos/count_videos` +`da_loai_luc IS NULL` · `web/lifecycle.py` hoặc `gdrive_upload.py` +`trash_file()` (`files().update trashed=true, supportsAllDrives`) · `web/app.py` +`POST /videos/loai` (≤50 id, 422 nếu hơn) · `web/static/index.html:118-122` nút · `app.js:530-545` | 4 đột biến phải ĐỎ (phase-03 §Nghiệm thu): hoist UPDATE trước trash · thêm `WHERE da_loai_luc IS NULL` vào `known_video_ids` · đổi `update`→`delete` · B loại id của A → 404. Trên mini: loại 1 video thật → Drive web thấy trong Thùng rác, `/videos` 10→9, `known_video_ids` vẫn có id | 2-2,5h |
| 1.2 | **Metadata cho mọi nguồn** qua yt-dlp `info_dict` (title/uploader/duration) | `src/tiktok_music_downloader/downloader.py:137-143` `_download_one` → `ydl.extract_info(url, download=True)` trả dict · đường về `web/queue.py` `_JobProgress` (mang ref) · `web/lifecycle.py:497-503` `record_video(title=ref.title or info.title …)` | dev: 1 job music page, `videos.title` non-null; **hàng cũ giữ NULL** (không backfill — đối chứng); đột biến: bỏ gán title → test đỏ. Mini sau deploy: job mới bất kỳ nguồn → title non-null | 1,5-2h |
| 1.3 | **Trang Cài đặt — tab "Của tôi"** theo `mock-settings-v2.html`: cookie dán **hoặc chọn tệp** + trạng thái/hạn/cập nhật + hạn mức hôm nay | UI: tách khối cookie khỏi `index.html` sang trang `/settings` (file mới `settings.html`/`settings.js`, dùng lại `app.css`) · chọn tệp = `FileReader` → **cùng** `PUT /me/cookie` (không endpoint mới) · `web/app.py` +`GET /me/quota` đọc 3 bộ đếm đã có trong `lifecycle.py:54,67,80` (`MAX_*_PER_COOKIE_PER_DAY`) · hạn cookie đã có ở `cookies.py:147,204` | `PUT` qua chọn tệp → `ls cookies` +1, `mode & 0o077 == 0` · `/me/quota` = `SELECT count(*) FROM jobs WHERE nguoi_tao=? AND tao_luc ≥ 00:00 VN hôm nay` (so bằng SQL độc lập) · render đúng mock: **điều phối tự mở ảnh chụp**, không đọc mô tả | 2,5-3h |
| 1.4 | **Drive upload trượt tự thử lại** (user chốt 16/09) | `web/lifecycle.py::on_video_verified` / `_note_upload_outcome` — 3 lần, giãn 2/4/8s, tổng ≤14s **ghi trong comment**, đếm số lần retry vào log + `ly_do_dung` khi hết | fake uploader trượt 2 lần rồi thành công → 1 file Drive, counter=2 · trượt 3 lần → file giữ, job có lý do, backpressure tăng · đột biến: bỏ vòng retry → test đỏ | 1h |
| 1.5 | Selection bar còn **Tạo bộ tự tìm · Phân tích · Xoá** theo mock — nhưng xem "Không làm" bên dưới: **chỉ ship nút có backend** | `index.html:118-122`, `app.js:542-545` xoá toast "chưa làm" | không còn chuỗi `"Chưa làm"` trong `app.js` (`grep -c` = 0) | 15' |
| — | **Deploy 3** (sao lưu DB bắt buộc — có migration): `PRAGMA wal_checkpoint(TRUNCATE)` → `cp jobs.db jobs.db.bak-…` → `deploy-to-mini.sh --yes` | điều phối, user gật | `PRAGMA table_info(videos)` 11→13 cột · 4 phép grep lật (như 2 chuyến trước) · promax 302 · job/video không đổi | 45' |

### T2 — Quản trị + hàng đợi (≈8h ⇒ 1 ngày; Deploy 4)

| # | hạng mục | file:dòng | phép nghiệm thu | ước lượng |
|---|---|---|---|---|
| 2.1 | **Tab Quản trị**: bảng người dùng · trần lượt/video từng người · trần chung công ty · cho/bỏ admin | `models.py` +bảng `nguoi_dung(email PK, tran_luot, tran_video, la_admin, thay_lan_dau)` + `cai_dat(khoa, gia_tri)`; ghi hàng `nguoi_dung` lần đầu ở `require_user` (`web/auth.py`) — **bắt buộc**, vì jar cookie tên `sha256(email)` không lật ngược được, và `jobs.nguoi_tao` chỉ có người đã tải · `auth.py:235-243` `is_admin` = env **HOẶC** bảng (env là bootstrap) · `lifecycle.py:54-80` đọc trần từ bảng, fallback hằng · `app.py` +`GET/PUT /admin/users`, `PUT /admin/settings` (`Depends(require_admin)`) | đặt trần user X = 2 → job thứ 3 của X bị chặn với lý do; trần chung = tổng video/ngày → job vượt bị chặn dù trần riêng còn; người thường gọi `/admin/*` → 403; đột biến: bỏ đọc bảng trong lifecycle → test đỏ (trần về hằng) · "Chạy song song" **KHÔNG có nút sửa** (mock ghi "chưa mở") | 4-5h |
| 2.2 | **Hàng đợi: vị trí + huỷ pending** (không hứa ETA) | `models.py` +`vi_tri(job_id)` = `count(pending, id<mine)` · `app.py` +`DELETE /jobs/{id}` chỉ khi `trang_thai='pending'` và là chủ · `queue.py` worker bỏ qua job `cancelled` · `app.js` hiển thị "thứ N trong hàng", nút Huỷ chỉ ở pending | 2 job pending, huỷ #2 → `cancelled`, worker **không** chạy nó (đột biến: bỏ kiểm trạng thái → test đỏ) · huỷ job running → 409 · huỷ job của người khác → 404 | 2-3h |
| — | **Deploy 4** (có migration) | như Deploy 3 | `table_info` có `nguoi_dung`, `cai_dat` | 45' |
| — | **T2.2 XONG + Deploy 5 XONG** 18/09 15:15, commit `4090e51` | — | `328 passed rc=0` · 2 đột biến ĐỎ (bỏ đếm `running` · bỏ `AND trang_thai='pending'`) · app thật: bấm → `cancelled`, job `running` → 409 và **vẫn** `running`, id lạ → 404 · **marker lật 0→1** trên mini (`vi_tri_hang_doi`, `queue-cancel`) · đối chứng `PATCH` cùng path → 405 nên 401 của `DELETE` là "route CÓ, auth chặn" · promax 302 trước **và** sau · label astronex 5→5 · DB `6\|16\|3` không đổi · lui: `bash deploy/rollback-on-mini.sh ../video-download-truoc-260918-151457` | — |
| — | Cùng chuyến: vá 2 lỗi UI user báo (`7cd92f3`) — cột lưới thứ ba mồ côi thành mảng đen · bộ lọc "Khung" là nút chết. **Chưa đo:** bố cục khổ hẹp (`--viewport` không đổi khổ render, iframe trả trang trắng) | — | — | — |
| — | **Light mode: dải điều khiển theo theme** (`3f809bd`) — USER BÁC quyết định cũ "dải giữ nền tối ở cả hai theme" (mock 15/09); 5 màu cứng bên trong thành token. **Đừng sửa lại cho khớp mock — mock cũ hơn.** | — | nhìn ảnh cả light lẫn dark, dark không hồi quy | — |
| — | **T3 phía Video Desk XONG** (`de55fce`) — nút "Tạo bộ tự tìm", bàn giao qua THANH ĐỊA CHỈ, không gọi API Creative Desk | — | trình duyệt thật: chặn `window.open`, bấm → 3 item cho 3 video có Drive, video thứ 4 bị loại kèm thông báo, tiêu đề tiếng Việt + emoji qua `TextEncoder` nguyên vẹn · ⛔ **KHÔNG deploy một mình**: trang nhận (meta-auto PR #202, draft) chưa đọc query param | — |
| — | **Dấu thời gian log** (`190ee74`) — đặt ở `web/app.py` vì `run-service.sh` sinh trên mini, không trong git | — | đột biến bỏ `force=True` → ĐỎ (`basicConfig` im lặng không làm gì khi root logger đã có handler của uvicorn); `331 passed rc=0` | — |
| — | **HAI NỢ BỊ BÁC 18/09 — đừng làm lại** | — | **(a) `COLLATE NOCASE` cho email: KHÔNG phải nợ.** 7 chỗ `email.strip().lower()` ở `auth.py:257` `app.py:452` `models.py:271,311,346,356,377` phủ **mọi** đường ghi và đọc ⇒ đã không phân biệt hoa/thường ở tầng ứng dụng. Nợ THẬT nằm ở jar cookie `sha256(danh tính THÔ)` — DB không cứu được, và `.lower()` vào `_identity_from` chính là thứ gây mồ côi jar. **(b) "dừng dịch vụ trước rsync": SAI CƠ CHẾ.** `deploy-to-mini.sh:42` `--exclude='web/data'` ⇒ rsync không chạm DB lần nào. Đĩa cũng bị loại: 10 thư mục bản-lui vài trăm KB mỗi cái, `~/Projects` 616M, đĩa còn 12Gi. 5 lỗi nằm ở dòng 2241/2347 (trước khởi động 2355) và 5181/5274/5366 (trước 5383), **0 lỗi** sau khởi động gần nhất. Có mẫu quanh deploy nhưng **cơ chế chưa ai chứng minh**; `KeepAlive=true` nên "dừng trước rsync" đòi `bootout` — thứ `deploy-to-mini.sh:13-15` cấm đích danh. ⇒ **chờ một chuyến deploy có timestamp rồi mới đo** | — |

### T3 — Tạo bộ tự tìm (đường nối Creative Desk) — **kongming song song đang lo, không lặp ở đây**

Chỗ đứng trong plan: **sau T1, song song T2**, worktree riêng từ `origin/main` meta-auto, không chạm `scripts/deploy.sh`, regen `system-map.json` + `docs/system-map/overview.md`. Plan riêng: `plans/260917-1436-noi-bo-tu-tim/plan.md` (kongming song song, 14:36). Điểm đã đảo so với spec 15/09 (memory `videodesk-handoff-same-drive-no-ci-gate-260917`): **cùng SA + cùng Shared Drive `0AASy4v5CJAkfUk9PVA`** ⇒ chuyển file = `copy_file` sẵn có (`creative_drive_client.py:176`); danh tính = **mở tab `automation.*/creative-order/self-bundles?videodesk=<payload>`**, frontend meta-auto tạo order bằng Bearer của chính user ⇒ **không cần service token Access, không cần relay JWT**. Phụ thuộc còn lại: 1 route copy Drive ở backend meta-auto + frontend nhận payload; phía Video Desk chỉ là nút sinh payload. **Không chặn** T0/T1/T2/T4; T4 "tool xong" **không đợi** nó. Nút "Tạo bộ tự tìm" trên selection bar chỉ ship **cùng** với backend của T3 (mục 1.5).

### T4 — Nghiệm thu ĐÓNG (0,5 ngày, phải hẹn giờ với user vì máy chung Promax)

| phép | trước/sau | nguồn |
|---|---|---|
| **Reboot mini** → dịch vụ tự lên | chụp mốc 30s trước: `launchctl list \| grep -c astronex` = 5 · promax 302 · 0 job dở; sau reboot đo lại **đúng 3 thứ** | phase-06:119; handoff 16/09 §B2 |
| **Job ~50 video**: `du -sm` thư mục tải lấy mẫu 5s **≤50MB** · `ps -o rss` **<1,5GB**. ⚠ Ngưỡng *"đĩa không tụt >100MB"* **BỎ 21/09**: đĩa mini dùng chung với Promax, đo được **185MB tụt trong 10s với `job_running=0`** ⇒ ĐỎ GIẢ. Cột đĩa giữ làm **thông tin**. Dụng cụ: `scripts/do-nghiem-thu-t4.sh mau <giây>` | ghép vào một job thật của người dùng, không dựng riêng | phase-03:96-106, phase-02:74 |
| **Hai người bấm cùng lúc** → tuần tự, jar không lẫn | log worker: 2 job `running` không bao giờ chồng thời gian; `cookies_path` đi vào `download_all` đúng chủ (test đã có `0fa50a0`) | phase-06:126 |
| Link Drive **mở được bằng mắt** | 1 lần | handoff 16/09 |
| Đổi `status: completed` cho `plans/260914-1412-…/plan.md`; CHECKLIST mục B2 tick kèm giờ | | |

## KHÔNG LÀM — và vì sao (cắt là một phần của plan)

| không làm | vì sao |
|---|---|
| **Phân tích nội dung** (tầng 3, agy vision) | user xếp "làm sau" (CHECKLIST §E); ~16k token/ảnh; không nằm trong định nghĩa "tool xong". **Nút "Phân tích" KHÔNG ship** tới khi có backend — mock v2 có nút này, nhưng ship nút chết là đúng thứ user vừa chụp ảnh phàn nàn. Ngã rẽ cần user: nếu user cần Phân tích trong tuần này ⇒ thêm T2.3 ≈ 4-6h (agy `gemini-3.7-flash-low`, theo lô ≤10, ghi `mo_ta`,`the` vào `videos`) |
| "Tìm thêm giống cái này" | chốt #13 chỉ là đề xuất chờ duyệt; chưa ai cần |
| Copy sang Shared Drive Creative Desk (mục riêng) | **Vô nghĩa như một việc riêng**: đo 17/09 Video Desk và Creative Desk dùng **cùng** Shared Drive `0AASy4v5CJAkfUk9PVA` (root "video-tool" và folder "Tự tìm" cùng `driveId`). Việc chuyển file vào folder bộ tự tìm là **một bước bên trong T3** (`copy_file` sẵn có), không phải hạng mục |
| ETA hàng đợi | không có nền đo thời lượng/video theo nguồn; hứa số sai tệ hơn không hứa. Chỉ hiện vị trí |
| Chạy song song >1 | R6 IP văn phòng; mock ghi "chưa mở" |
| TTL cookie 14 ngày | hạn đã đọc từ jar (`cookies.py:147,204`), hiện "Hạn đến" là đủ; ép TTL là thêm một ca hỏng |
| Backfill video cũ | user huỷ 16/09; **xoá** `scripts/backfill-videos-from-drive.py` (159 dòng chết) + 9 dòng model đi kèm |
| Log có timestamp / logging đầy đủ | không user-facing; 2 lỗi log là tạm thời lúc deploy (kiểm kê §5) |
| Sửa thứ tự rsync/kickstart | 2 lỗi/3 994 dòng, không user thấy. Làm khi tiện, không xếp lịch |
| Đổi dải nhập tối ở light mode | app khớp mock từng giá trị ⇒ là đổi thiết kế, cần user muốn |

## CẮT QUY TRÌNH — user đang trả bằng giờ cho những thứ này

Số đo ở kiểm kê §2d: 26/63 commit là docs, 9 trong đó là docs sửa docs; 4 handoff/748 dòng cho một mạch việc; trạng thái ghi ở ≥4 chỗ; khoảng trống 285' ngày 16/09 kết bằng một handoff 277 dòng.

1. **Một nơi duy nhất ghi trạng thái: `CHECKLIST-VAN-HANH.md`.** Bảng Phases trong `plan.md`, phase file, handoff, deploy report **không** lặp lại trạng thái nữa. Phase file chỉ được sửa khi **thiết kế** đổi, không phải để tick.
2. **Bàn giao ≤ 15 dòng**: HEAD · nhánh · cây sạch? · 3 việc kế tiếp (trỏ vào CHECKLIST) · cái đang dở duy nhất. Mọi thứ khác đã có trong commit message và CHECKLIST. Không viết "sự thật bị bác", "luật rút ra", "giả thuyết treo" vào handoff — cái đáng giữ thì vào memory/rules, còn lại bỏ.
3. **Bỏ report `fullstack-*`** của subagent thi công (678 dòng/3 ngày): subagent trả `Status/Summary/Concerns` 5 dòng trong tin nhắn là đủ; bằng chứng nằm ở test và commit.
4. **Deploy report giữ, nhưng ≤ 25 dòng** (chỉ: lui bằng gì · 4 phép lật · ai gật · ngắt ai). Nó là hồ sơ rollback, có giá trị thật.
5. **Không ghi con số vào docs trước khi đo** — 9 commit đính chính sinh ra từ đúng chỗ này (1 074 vs 4; vai SA đảo trong 1 phút). Chưa đo ⇒ viết `CHƯA ĐO`, không viết ước lượng như số.
6. **Không xây cho một con số chưa đếm** (backfill 183 dòng cho 1 074 video thật ra là 4). Đếm trước, 1 lệnh SQL/Drive list, rồi mới xây.
7. **Review ngoài (`code-reviewer`) chỉ cho đường quyền/xoá/cookie/Drive** — hai vòng vừa rồi bắt lỗi thật ở đúng lớp đó. UI, docstring, style: không review, không agy, không kongming (luật `coordinator-plan-review.md` đã cho phép bỏ cửa với việc cơ học một lane).
8. **Ngân sách đo được:** mỗi ngày `git log --since=<hôm nay> --numstat` — dòng `plans/` thêm vào **≤ 20%** dòng `web/`+`src/` thêm vào. Vượt ⇒ dừng viết, quay lại gõ. Đo cuối ngày, 1 lệnh awk (có sẵn trong kiểm kê §1).
9. **Gộp deploy**: T1 một chuyến, T2 một chuyến. 7 chuyến trong 2 ngày (7 thư mục `video-download-truoc-*` trên mini) là 7 lần checklist + 7 lần ngắt người dùng.

Kỳ vọng nếu áp 9 điều trên: T1+T2+T4 ≈ **2,5 ngày làm việc**. Giữ quy trình hiện tại: ≈ 4 ngày (tỉ lệ docs/code đo được 81%).

## Cái gì chặn cái gì

- T0.1, T0.2, T0.4 **không phụ thuộc gì** — làm ngay.
- T0.3 chờ user gật merge + deploy meta-auto.
- T1 không chờ T0 (nhưng T0.2 nên xảy ra trước Deploy 3 để có control metadata).
- T2.1 phụ thuộc T1 Deploy 3 chỉ vì gộp migration; về file thì độc lập.
- T3 phụ thuộc lane meta-auto (1 route + frontend nhận payload), **không** phụ thuộc service token; **không chặn** T1/T2/T4.
- T4 cần hẹn giờ reboot với user; các phép còn lại làm nhân tiện trong T1/T2.

## Câu cần user trả lời (trình một lần, không đợi)

1. **Phân tích nội dung** có cần trong tuần này không? Mặc định plan: **không**, nút không ship. Bằng chứng đảo: user nói cần cho việc chọn creative tuần này.
2. Ngày/giờ **reboot mini** (máy chung Promax) — đề nghị ngoài giờ làm.
3. Số trần mặc định cho người mới trong tab Quản trị — plan dùng **20/1000/800** hiện có làm mặc định; đổi thì là đổi 1 hàng `cai_dat`.
4. Gật Deploy 3 (T1, có migration) và Deploy 4 (T2, có migration).

## Assumptions (thay cho câu hỏi)

- Mini đang chạy đúng HEAD `1415293` (deploy 12:39) — **tin điều phối**, mini không có `.git` (`HEAD=no-git`) nên không tự đối chiếu được. Độ tin: cao (4 phép grep đã lật trong `deploy-260917-1033`).
- `PUT /me/cookie = 0` nghĩa là chưa ai dùng trang cookie — log không có timestamp, có thể thiếu nếu log bị xoay; `ls -la videodl.log` 227KB liên tục từ 14/09 ⇒ độ tin: cao.
- yt-dlp `extract_info` trả `title/uploader/duration` cho TikTok — kiến thức chung về yt-dlp, **chưa probe trên máy này** (không chạy live TikTok theo luật lane). Độ tin: trung bình-cao; nếu sai thì 1.2 rơi về đọc index hashtag như hiện tại, mất 1,5h.
- Merge PR #192 không cần CI — protection 403 đo 17/09 (memory kongming song song). `scripts/ci-local/merge-pr.sh` chỉ có trên nhánh `feat/ci-local-gate` (đo `git ls-tree origin/main` = 0) — điều phối nói PR #198 merge qua nó, tức lane meta-auto đang đứng trên nhánh đó. Độ tin: cao về "không cần CI", trung bình về "script ở đâu lúc điều phối chạy".
- Ước lượng T1 mục 1.1 dựa trên `phase-03` của plan 11:15 (thiết kế đã đầy đủ, chưa gõ); mục 2.1 chưa có thiết kế trước ⇒ sai số lớn nhất nằm ở 2.1 (4-5h có thể thành 6h).
- Ước lượng giờ dựa trên tốc độ đo được 15-17/09 (P1+P2+P3 kongming ước 5h15 → gõ xong 11:22→11:52 sau khi bắt đầu ~11:15, tức nhanh hơn ước) ⇒ ước lượng ở đây **thiên về dư**, không thiên về thiếu.


---

# TRẠNG THÁI — cập nhật tại chỗ, không sinh file mới

## T1 — XONG cả 5 hạng mục (17/09 chiều → 18/09), CHƯA DEPLOY

| | commit | đột biến ĐỎ |
|---|---|---|
| 1.1 Bỏ khỏi thư viện (trash Drive + nhớ đã loại theo TỪNG NGƯỜI) | `7dc93f7` | hoist mốc trước trash · thêm lọc vào `known_video_ids` · bỏ kiểm chủ |
| 1.2 Metadata mọi nguồn (`extract_info` thay `download`) | `8e6bf2d` | bỏ gán title · cho yt-dlp đè index · **lùi về `download()`** (ban đầu XANH = lưới giả, đã bịt bằng test chạy qua `download_all` thật) |
| 1.3 Trang Cài đặt `/settings.html` (cookie dán **hoặc chọn tệp**, `GET /me/quota`) | `1830262` | — (đo bằng SQL độc lập + ảnh chụp thật) |
| 1.4 Drive trượt tự thử lại | `259319b` | bỏ vòng thử lại · bỏ trần · thử lại cả lỗi quyền |
| 1.5 Thanh chọn chỉ còn nút CÓ backend | `7dc93f7` | `grep "Chưa làm"` = 0 |

`302 passed rc=0`, cây sạch, đã đẩy origin.

Ba lỗi tự bắt được trong T1, ghi vì chúng là lớp lỗi sẽ tái phát:
1. **Lưới giả** ở 1.2 — test phủ hàm gộp, không phủ dây nối; lùi một dòng trong
   `downloader.py` là metadata biến mất mà suite xanh trọn.
2. **Suýt giết trang chính** ở 1.3 — gỡ phần tử khỏi `index.html` mà để code trong
   `app.js`; `noiCookie()` ném trên `null`.
3. **`timeout` không có trên macOS** — một đột biến báo `rc=127` (lệnh không tồn tại),
   tức phép đo đó **chưa từng chạy**. Đã đo lại đúng cách.

## Đề xuất trần mặc định cho người mới — user chốt số, không đặt vào code

Đề xuất **giữ nguyên 20 lượt / 1000 video / 800 trang**, nền:
- Trần hiện tại là trần user tự đặt cho chính mình và **chưa lần nào chạm**: đo 4 lượt
  tải / 10 video trong 3 ngày. Không có bằng chứng nó chật.
- Kích thước thật: trung vị **1,67 MB**, lớn nhất **4,07 MB** (10/10 file, hỏi Drive API).
  1000 video/ngày ≈ **1,7 GB/ngày/người** — mini còn trống 11 GB, nhưng tệp bị **xoá
  ngay sau khi lên Drive** nên đĩa không phải cái chặn.
- Cái chặn thật là **IP văn phòng** (TikTok đánh theo IP, không theo người). Trần từng
  người cộng lại mới là con số đáng lo ⇒ **số cần thêm là trần TOÀN CÔNG TY**, không phải
  hạ trần từng người. Xếp ở T2.
- ⚠ **CHƯA ĐO:** ngưỡng TikTok thật sự chặn ở đâu. Không ai trong hạm có số đó, nên mọi
  con số ở đây là **suy từ lưu lượng**, không phải từ một lần bị chặn.

## Danh sách 30 giây trước Deploy 3 — chỉ việc bấm

```
# 1. Mốc trước (chạy nguyên khối, dán output vào report)
ssh nobi_auto@100.109.39.103 'cd ~/Projects/video-download
  launchctl list | grep -c astronex                      # phải 5
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://127.0.0.1:7870/healthz
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 https://promax.nobidigital.asia
  ./.venv/bin/python -c "import sqlite3;print(sqlite3.connect(\"web/data/jobs.db\").execute(
    \"SELECT COUNT(*) FROM jobs WHERE trang_thai NOT IN (\x27done\x27,\x27failed\x27,\x27interrupted\x27)\"
    ).fetchone()[0])"                                    # phải 0
  grep -c "def video_nay_cua_toi" web/models.py          # phải 0 TRƯỚC deploy
  ./.venv/bin/python -c "import sqlite3;print(len(sqlite3.connect(\"web/data/jobs.db\").execute(
    \"PRAGMA table_info(videos)\").fetchall()))"        # phải 11 TRƯỚC, 13 SAU'

# 2. SAO LƯU DB — bắt buộc, chuyến này CÓ migration
ssh nobi_auto@100.109.39.103 'cd ~/Projects/video-download
  ./.venv/bin/python -c "import sqlite3;sqlite3.connect(\"web/data/jobs.db\").execute(
    \"PRAGMA wal_checkpoint(TRUNCATE)\")"
  cp web/data/jobs.db web/data/jobs.db.bak-260918-<hhmm>'

# 3. Deploy
bash deploy/deploy-to-mini.sh          # thử khô
bash deploy/deploy-to-mini.sh --yes    # thật, đo rc TRỰC TIẾP, không pipe

# 4. Mốc sau — 4 phép phải LẬT
#    PRAGMA table_info(videos)          11 → 13
#    grep -c "da_loai_luc" web/models.py  0 → ≥1
#    grep -c "/me/quota" web/app.py       0 → ≥1
#    ls web/static/settings.html          không có → có
#    GIỮ NGUYÊN: astronex 5 · promax 302 · số job/video không đổi
```

⚠ `healthz 200` **không** nằm trong danh sách nghiệm thu: nó trả 200 cả trước lẫn sau.
