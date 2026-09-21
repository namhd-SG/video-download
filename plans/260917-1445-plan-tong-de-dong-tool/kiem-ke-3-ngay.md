# Kiểm kê 3 ngày (14–17/09) — ra được gì, dư cái gì

Đo lúc 17/09 ~14:50 trên `/Users/macos/Projects/video-download` HEAD `358aef8` (cây sạch, 1 file untracked)
và trên mini `nobi_auto@100.109.39.103` (dịch vụ pid 5910, `healthz 200`, đĩa trống 11Gi).
Mọi số dưới đây là **số đo** trừ chỗ ghi `CHƯA ĐO`.

## 1. 63 commit — phân theo loại và theo dòng thêm

| loại commit | số | dòng thêm | ghi chú |
|---|---|---|---|
| feat | 16 | 7 118 | gồm cả test đi kèm |
| fix | 16 | 2 277 | 14/16 là sửa code viết trong CÙNG 3 ngày (review tự bắt) |
| refactor | 1 | 1 011 | `1d338ac` tách js/css khỏi html — dòng **di chuyển**, không phải dòng mới |
| docs | **26** | **3 693** | 41% số commit · 25% số dòng thêm |
| chore/style/test | 4 | 393 | |

Theo nhóm đường dẫn (thêm/xoá): `code +5 642/−1 417` · `test +3 765/−74` · `plans +4 577/−167` · `deploy +487`.
⇒ **Dòng plan/report thêm vào = 81% dòng code thêm vào** (4 577 / 5 642). Giả thuyết của điều phối đúng, còn nặng hơn số 63% đã nêu.

## 2. Phân loại (a)(b)(c)(d)

| | nội dung | số đo |
|---|---|---|
| **(a) tính năng user dùng được** | web+hàng đợi, JWT Access, Drive lifecycle, cookie từng người (jar riêng, tiền-kiểm 4 mã, dọn SIGKILL), 3 trần/ngày, thư viện + thumb + 6 bộ lọc, lọc trùng toàn kho, `/jobs` `/videos` `/thumbs` `/jobs/{id}` theo chủ, trang "Cookie của tôi", deploy script + rollback | 16 feat + phần lớn 16 fix ≈ **9 000 dòng** code+test |
| **(b) sửa lỗi thật** (lỗi user nhìn thấy hoặc rò dữ liệu) | placeholder mờ `fa0b84d` · thư viện cắt 200 `ce0d749` · rò cookie qua `raw[:80]` `9ba8cac` · `/jobs/{id}` đọc của người khác `780c409` · thumb 0 byte `2e5f31e` · deploy xoá file launchd `9c37b12` | 6 commit |
| **(c) hạ tầng cần** | 255 hàm test (`grep def test_`), 3 script deploy (389 dòng), `kiem-ui.sh` contrast gate (91) | test = 40% dòng code+test |
| **(d) DƯ THỪA** | xem bảng dưới | **≈ 1 400 dòng + 12 commit** |

### (d) — dư thừa, từng khoản

| khoản | số | bằng chứng |
|---|---|---|
| Backfill "1 074 video cũ" — viết xong, user huỷ vì số thật là **4** | **+183 dòng** (`4eb28c6`: script 140 + test 30 + model 9), 1 commit docs rút `25420c8` | `scripts/backfill-videos-from-drive.py` còn 159 dòng, **chưa từng chạy vào DB sống** (handoff 16/09 §5b). Nguyên nhân: xây trước khi đếm |
| Docs sửa docs (đính chính con số/tick ghi sớm) | **9 commit, +448 dòng** | `d33e97f` rồi `2b3e20c` **1 phút sau** đảo ngược chính nó (vai SA) · `139c81f` · `25420c8` · `b3697ee` · `c1e4367` · `53000a6` · `7139720` · `c5ba8b9` |
| 4 file bàn giao cho **một** mạch việc | **748 dòng** | `handoff-260915-1019` (167) · `-1105` (213) · `-1750` (91) · `-260916-2135` (277). Cùng mục "chờ user" (`VIDEODL_ADMIN_EMAILS`) xuất hiện ở **4 file**; "Content manager" ở **5 file** |
| Trạng thái ghi ở ≥4 chỗ: `plan.md` bảng Phases · `CHECKLIST-VAN-HANH.md` · handoff · `deploy-*.md` | `phase-05` bị sửa **7 lần**, `phase-07` **6 lần**, CHECKLIST **5 lần** trong 3 ngày | `git log --name-only -- plans` |
| 4 report `fullstack-*` | 678 dòng | report của subagent thi công, nội dung lặp lại commit message + phase file |
| Code chết nhỏ | cột `da_tai` chỉ ghi không đọc (`models.py:79,374`) · `VIDEOS_PAGE_SIZE` hằng chết | handoff 16/09 §4 đã ghi, chưa dọn |

**Tổng (d):** ≈ 183 (code) + 448 (docs sửa docs) + 748 (handoff) ≈ **1 380 dòng** và **≥12 commit** = ~19% commit không sinh giá trị cho user.
**Không tính vào (d) nhưng đắt:** hai vòng `code-reviewer` (phase-05, phase-07) — chúng bắt được lỗi thật (lưới giả rò cookie, thumb 0 byte) ⇒ là (c), giữ cho code quyền/xoá; bỏ cho UI.

### Khoảng trống trong ngày (theo mốc commit — CHƯA ĐO việc gì diễn ra bên trong)
- 15/09 11:30→14:25 (176'), 16/09 12:15→14:18 (123'), **16/09 17:03→21:47 (285')** kết bằng handoff 277 dòng, 17/09 11:59→14:14 (136') kết bằng docs deploy.
- 3/4 khoảng trống dài kết thúc bằng một commit **docs**. Khớp giả thuyết: thời gian sau khi code xanh đi vào viết bàn giao/report.

## 3. Đề bài gốc và mức hoàn thành

### Đề bài 14/09 (`plans/260914-1412-tool-len-mini-va-domain/plan.md` — 6 Goals, 6 Success Criteria)

| # | goal | trạng thái | bằng chứng |
|---|---|---|---|
| 1 | chạy thường trực, tự bật lại | **XONG** (SIGKILL) / **CHƯA ĐO** (reboot) | `launchctl list` có `com.astronex.videodl` pid 5910; SIGKILL→tự lên đo 14/09 (plan.md nhật ký); reboot cần hẹn giờ (phase-06:119) |
| 2 | team dùng qua trình duyệt | **XONG** | log mini: 3 IP ngoài, 5 `POST /jobs`, 4 job `done` |
| 3 | đĩa mini không bị đụng | **XONG cơ chế** / tiêu chí 50 video ≤50MB **CHƯA ĐO** | phase-03:96-106 còn 5 ô trống; 14/09 job 3/3 thư mục 0 file |
| 4 | cookie từng người | **CODE XONG, CHƯA AI DÙNG** | routes `/me/cookie` (`app.py:257-310`) lên mini 12:39; log: `PUT /me/cookie` = **0 lần**; `web/data/cookies` = 1 jar |
| 5 | ra domain cloudflared | **XONG** | phase-04 6/6 tick; `video.nobidigital.asia` sau Access |
| 6 | nối meta-auto (link nav) | **DỞ — KHÔNG còn bị chặn** | PR #192 MERGEABLE; điều phối đo: branch protection 403 Free, meta-auto merge qua `scripts/ci-local/merge-pr.sh` (PR #198 hôm nay) ⇒ chỉ thiếu user gật |

Success criteria: 3/6 đo xong (thư mục rỗng+đếm khớp · promax 302 · mở hostname tải được), 3/6 chưa (reboot · 50 video ≤50MB · hai người thật).
**⇒ Đề bài 14/09: ≈ 80%.** Phần thiếu toàn là **nghiệm thu cần người/giờ**, không phải code.

### Đề bài MỞ RỘNG do user chốt thêm (15→17/09)

| ngày | thêm gì | trạng thái |
|---|---|---|
| 15/09 | thư viện creative, 13 chốt (phase-07) | lõi XONG (thumb, 6 lọc, lọc trùng); **CHƯA**: Xoá · bộ tự tìm · phân tích · tìm giống · copy Drive |
| 16/09 | 4 quyết định | 3/4 XONG; **CHƯA**: Drive retry |
| 17/09 sáng | C1 Xoá · C2 Setting trần · C3 bộ tự tìm đồng bộ · C4 admin · C5 thư viện riêng | C5 XONG · C4 code xong **biến chưa đặt** · C1 C2 C3 **CHƯA** |
| 17/09 14:28 | trang Cài đặt 2 tab (mock v2 duyệt) | **CHƯA gõ** |

**⇒ Đề bài mở rộng: ≈ 55%.** Ba ngày không "làm 1 tool nhỏ" — đề bài lớn dần **mỗi ngày một lớp** (14/09: 6 goal · 15/09: +13 chốt · 17/09: +5 chốt + 1 trang). Đó là nguyên nhân thứ nhất. Nguyên nhân thứ hai là quy trình (mục 2d).

## 4. Nợ "metadata 0/10" — ĐÃ PHÂN ĐỊNH: không phải lỗi code

- `src/tiktok_music_downloader/utils.py:72-95` (docstring `VideoRef`): metadata **chỉ** có từ index hashtag (`hashtag_enumerator.py:172-185` đọc `title/author/region/duration`); scraper music page trả `VideoRef(video_id, url)` trần (`utils.py:107`).
- Trên mini: **10/10 hàng `videos` thuộc job 4 = music page**; job 1-2 (hashtag) chạy **trước** khi lớp chỉ mục lên (15/09 14:25) nên không có hàng.
- ⇒ 0/10 là **đúng cấu tạo**. Control đúng không phải DB dev — là **một job hashtag mới trên mini** (đồng thời là ca "người thứ hai"). Cách lấp: yt-dlp đã tải từng video, `info_dict` có `title/uploader/duration` miễn phí cho **mọi** nguồn (`downloader.py:142` hiện chỉ `ydl.download`, không giữ info). Xếp vào plan Tầng 1.

## 5. Hai lỗi trên log mini — CHƯA PHÂN ĐỊNH, tạm xếp "tạm thời lúc deploy"
`videodl.log` 3 994 dòng, 2 dòng `OperationalError` (2241 `disk I/O error`, 2347 `unable to open database file`), **cả hai nằm giữa hai mốc khởi động 1953→2353** = cửa sổ rsync deploy 10:33 (rsync thay file khi dịch vụ còn chạy, `kickstart` sau). Sau 2353: 0 lỗi. Không user-facing hiện tại. Nếu muốn triệt: dừng dịch vụ **trước** rsync trong `deploy-to-mini.sh:104-110` (đổi thứ tự 2 dòng).
