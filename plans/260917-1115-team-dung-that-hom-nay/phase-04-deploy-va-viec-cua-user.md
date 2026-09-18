---
phase: 4
title: "Hai chuyến deploy, nghiệm thu bằng người thứ hai, danh sách việc user tự làm"
status: pending
priority: P0
effort: "1h15 tổng cho hai chuyến"
dependencies: [1, 2, 3]
---

# Phase 4 — Deploy + việc của user

## Deploy 1 (P1 + P2 + P3) — mục tiêu 16:30–17:00

Trước khi bấm (luật lane 16/09 + máy chung Promax):
```bash
ssh nobi_auto@100.109.39.103 'tail -200 ~/Library/Logs/videodl.log | grep -c "POST /jobs\|GET /videos"'   # có người 15' gần đây? có ⇒ hỏi điều phối
ssh nobi_auto@100.109.39.103 'cd ~/Projects/video-download && ./.venv/bin/python -c "import sqlite3;print(sqlite3.connect(\"web/data/jobs.db\").execute(\"SELECT COUNT(*) FROM jobs WHERE trang_thai IN (\x27pending\x27,\x27running\x27)\").fetchone()[0])"'   # phải 0
ssh nobi_auto@100.109.39.103 'launchctl list | grep -c astronex'   # 5
curl -s -o /dev/null -w "%{http_code}\n" https://promax.nobidigital.asia   # 302
ssh nobi_auto@100.109.39.103 'cd ~/Projects/video-download/web/data && sqlite3 jobs.db "PRAGMA wal_checkpoint(TRUNCATE)" && cp jobs.db jobs.db.bak-260917-$(date +%H%M)'
bash deploy/deploy-to-mini.sh          # thử khô
bash deploy/deploy-to-mini.sh --yes    # cần user gật
```
Sau khi bấm — phép phân định (không phải `healthz`):
- `grep -c "def _job_cua_toi_hoac_404" web/app.py` trên mini = 1; `grep -c "chi_cua" web/models.py` ≥ 3; `grep -c "/me/cookie" web/app.py` ≥ 3.
- Gọi hàm đã deploy trên dữ liệu thật: `list_videos(P, '<email user>', 500, 0)` → 10; `list_videos(P, 'ai-do@x', 500, 0)` → 0; `count_videos(P, None)` → 10.
- Offline `127.0.0.1:7870`: `GET /jobs/4` **không JWT** → 401 (cửa còn); không có cách giả A/B qua HTTP không JWT — đó là lý do phép trên gọi hàm.
- **Người thứ hai thật** (việc user, mục E): dán cookie ⇒ `ls -la web/data/cookies` = 2 tệp `-rw-------`; tạo job hashtag nhỏ (≤5) ⇒ job `done`, thư mục `job-<id>` trên Drive; người đó thấy đúng video mình, **không** thấy job của user trong hàng đợi; user không thấy video của người đó (cho tới khi admin). Đây là tiêu chí B2 "hai người" mà handoff 16/09 ghi thiếu.
- Promax vẫn 302 (lấy mẫu 3 lần).

## Deploy 2 (P4 + P5, tối — "nếu còn giờ", không hứa)
Cùng checklist; **sao lưu DB là bắt buộc** (đổi schema). Nghiệm thu theo phase-03.

## E. Việc USER tự làm — trình một lần, theo thứ tự

| # | khi | việc | vì sao / bằng chứng |
|---|---|---|---|
| 1 | **bây giờ** | Kiểm policy Cloudflare Access của `video.nobidigital.asia`: ai được vào? Nếu là cả domain ⇒ thu về **danh sách email thành viên Creative Desk** (quyết định 6 thi hành ở đây, 0 dòng code). Ghi lại Session Duration luôn (spec-260915 §6 chưa đo) | Video Desk không có bảng user; Access là cổng duy nhất |
| 2 | bây giờ | Xác nhận vai SA Drive vẫn là **Content manager** (Drive web → Shared Drive "Creative Astronex" → Quản lý thành viên). **Không nâng** | P4 dựa vào trash; đo lần cuối 15/09 16:15 |
| 3 | ~16:30 | **Gật Deploy 1** (điều phối trình checklist trên) | máy chung Promax prod |
| 4 | ngay sau Deploy 1 | Vào tool → "Cookie TikTok của tôi" → dán lại cookie của mình (tệp cũ sẽ được thay nguyên tử) | kiểm đường PUT thật |
| 5 | ngay sau | Nhờ **một thành viên Creative Desk** làm ca "người thứ hai" ở trên (dán cookie + 1 job hashtag ≤5 video) | tiêu chí "hoạt động hôm nay" |
| 6 | sau khi 5 xong | Đặt `VIDEODL_ADMIN_EMAILS=<email user>` vào `~/.config/videodl/env` trên mini (tệp `-rw-------`, đã có 2 biến Drive + Access) rồi `launchctl kickstart -k gui/$(id -u)/com.astronex.videodl`. Mã đã lên từ 10:33 ⇒ **đặt biến sau mã** đúng thứ tự CHECKLIST C4 | không đặt ⇒ user cũng không thấy hàng đợi/thư viện của team |
| 7 | tối, nếu P4 xong | **Gật Deploy 2** (có migration; điều phối đưa mã sao lưu `jobs.db.bak-260917-hhmm`) | đổi schema |
| 8 | sau Deploy 2 | Loại thử **1** video của mình, mở Drive web kiểm Thùng rác của Shared Drive có file | nghiệm thu P4 bằng mắt |
| 9 | mai | Chốt: (a) có 1 hay nhiều project Creative Desk (taxonomy theo `project_id`); (b) số trần riêng từng người muốn đặt (admin zone mai); (c) B quét trúng video A đã loại ⇒ bỏ qua vĩnh viễn — đồng ý? (hệ quả quyết định 2+5) | việc mai không chặn hôm nay |

## Cập nhật tài liệu trong cùng PR
- `CHECKLIST-VAN-HANH.md`: C1 → chốt (Loại khỏi kho = Thùng rác + không tải lại); C2 → 3 trần đã có, trần riêng từng người là việc mai; C3 → (b) **đã chết cấu tạo** (spec-260915 §2), đường sống là relay/MCP-read, "đồng bộ" của user = đọc sống; C4 → **đã lên mini 10:33**, còn việc đặt biến (mục E6). B1 → tick khi Deploy 1 xong kèm `ls` 2 tệp.
- `phase-07:29` chốt #2 "cả team thấy hết" → ghi **đổi 17/09**: Drive vẫn một kho, thư viện hiện theo chủ; #7 bộ lọc "Người tải" → bỏ.
