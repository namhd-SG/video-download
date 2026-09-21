---
title: "Đẩy video-download lên mac mini công ty, chạy 24/7, ra domain"
description: "Biến tool desktop Tkinter thành dịch vụ web chạy thường trực trên autos-mac-mini, ra internet qua cloudflared tunnel sẵn có, nối vào meta-auto"
status: pending
priority: P1
effort: "5-8d"
tags: [infra, deploy, video-download, mac-mini]
created: 2026-09-14
---

# Đẩy video-download lên mac mini công ty + ra domain

## Overview

Tool hiện là ứng dụng desktop Tkinter chạy trên máy từng người. Mục tiêu: cả team
dùng qua trình duyệt, không ai phải cài gì. Chạy thường trực trên
`autos-mac-mini` (Tailscale `100.109.39.103`, user `nobi_auto`), ra internet qua
cloudflared tunnel **đã có sẵn** trên chính máy đó.

**Tkinter không serve được qua web** — nó là cửa sổ chạy trên máy người dùng. Phải
viết lớp web mới. Lõi thì tái dùng gần trọn: `scraper.py`, `downloader.py`,
`hashtag_enumerator.py`, `gdrive.py`, `watermark.py` đều chạy headless.

## Ràng buộc đã ĐO trên máy (14/09/2026)

| | Số đo | Hệ quả thiết kế |
|---|---|---|
| đĩa trống | **~5 GB, BIẾN ĐỘNG** — đo 14:11 là 11 GB, 14:50 còn 5,1 GB vì swap phình 5 GB khi người khác dùng máy nặng | không giữ bản local: tải xong 1 file → đẩy Drive → xoá ngay |
| sudo | **KHÔNG** (`sudo: a password is required`) | chỉ LaunchAgent cấp user, **không** LaunchDaemon |
| ffmpeg hệ thống | **KHÔNG có** | phải `scp` binary từ LFS sang — `git bundle` chỉ mang pointer |
| ffprobe | **KHÔNG có, kể cả trong repo** | LFS chỉ track `ffmpeg` + `ffmpeg.exe`; xác minh video phải dùng `ffmpeg -i` |
| python | 3.9.6 (hệ thống) · **3.14.7** (`/opt/homebrew/bin/python3`) | dùng bản brew; tool cần ≥3.10 |
| Tk | 8.5 | không dùng GUI trên máy này — càng đúng hướng web |
| cloudflared | **đang chạy**, `~/.cloudflared/config.yml`, 1 hostname | thêm hostname = sửa 1 file YAML + 1 DNS record |
| port đang bận | 7860 (promax) · 11434 (ollama) · 61208 (glances) · 20241 | tool lấy **7870** |
| giữ máy thức | `caffeinate -s -i` qua LaunchAgent `com.astronex.promax-awake` | 24/7 **đã có sẵn**, không phải dựng |
| pmset | `sleep 0` · `autorestart 1` · `womp 1` | máy không ngủ, tự bật lại sau mất điện |
| Tailscale | **Tailscale.app** (GUI app, không phải system daemon) | xem Rủi ro R1 |

## Hai điều số đo làm đổi so với chốt ngày 10/09

**1. Không nhúng UI vào app meta-auto.** Ngày 10/09 anh chốt *"một trang trong app
sẵn có"*. Nhưng meta-auto chạy trên **VPS**, còn worker phải chạy trên **mini** (nơi
có Chromium + băng thông + không dính nhịp deploy của meta-auto). Hai máy khác nhau
⇒ nhúng UI nghĩa là phải dựng hàng đợi xuyên máy, thêm một thứ để hỏng.

**Tiền lệ ngay trên chính máy đó:** Promax chạy service riêng + hostname riêng
(`promax.nobidigital.asia` → `localhost:7860`), **không** có dòng nào trong frontend
meta-auto. Đã chạy ổn định nhiều tháng — đo hôm nay: HTTP 302, 3/3 lần, ~0,2s.

⇒ **Anh đã chốt 14/09: service riêng + hostname riêng**, nối vào meta-auto bằng một
link trong nav, tiêu chí *"an toàn là được"*. Chi tiết + hồ sơ quyết định ở Phase 06.

⚠ Lập luận ban đầu của tôi cho chỗ này **sai một ô**: tôi viết "nhúng UI ⇒ phải có
hàng đợi xuyên máy", đó là **nhị nguyên giả** (kongming bắt). Trang meta-auto hoàn
toàn có thể là thin-client gọi API trên mini. Chi phí thật của đường đó là **cầu
danh tính**, không phải queue. Kết luận giữ nguyên, lý lẽ đã sửa.

**2. Đường quản trị mong manh hơn đường dịch vụ.** Tailscale cài dạng app GUI nên
nó sống theo phiên đăng nhập của một user — đo 11/09: node **offline 12 ngày**, ssh
timeout, trong khi `promax.nobidigital.asia` vẫn trả 302 suốt. Máy sống, chỉ Tailscale
chết. Không sudo ⇒ không chuyển sang system daemon được.

⇒ **Không đặt đường sống của dịch vụ lên Tailscale.** cloudflared chạy LaunchAgent
riêng và đã chứng minh bền. Tailscale chỉ dùng để ssh quản trị, và phải chấp nhận
nó thỉnh thoảng đứt.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Tool chạy thường trực trên mini, tự bật lại sau reboot/crash | P1 |
| 2 | Team dùng qua trình duyệt, không cài gì trên máy cá nhân | P1 |
| 3 | Đĩa mini gần như không bị đụng — đỉnh ≈ một video đang xử lý | P1 |
| 4 | Cookie TikTok là của **từng người**, không dùng account chung | P1 |
| 5 | Ra domain qua cloudflared sẵn có, không dựng hạ tầng mới | P2 |
| 6 | Nối vào meta-auto để người dùng tìm thấy | P2 |

## Non-goals

- Không viết lại lõi tải (`downloader.py`, `scraper.py`, `hashtag_enumerator.py`).
- Không làm phần phân nhóm creative theo taxonomy (việc riêng, đã chốt 10/09 R4).
- Không chuyển Tailscale sang system daemon (không có sudo).
- Không đụng vào Promax hay bất kỳ LaunchAgent production nào đang chạy trên máy.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Chỗ chạy trên mini](./phase-01-cho-chay-tren-mini.md) | ✅ Completed |
| 2 | [Lớp web thay Tkinter](./phase-02-lop-web-va-hang-doi.md) | 🔶 Code xong, CHƯA nghiệm thu trên mini |
| 3 | [Đẩy thẳng Drive, không giữ local](./phase-03-vong-doi-file.md) | 🔶 Code xong, CHƯA chạy với Drive thật |
| 4 | [Ra domain qua cloudflared](./phase-04-ra-domain.md) | Pending |
| 5a | [Danh tính JWT](./phase-05-cookie-va-phan-quyen.md) — **trong MVP, trước Phase 4** | Pending |
| 5b | [Mỗi người tự dán cookie](./phase-05-cookie-va-phan-quyen.md) — sau MVP | Pending |
| 6 | [Nối meta-auto + nghiệm thu](./phase-06-noi-meta-auto-va-nghiem-thu.md) | Pending |

## Success Criteria

- [ ] Mở `https://<hostname>` từ máy bất kỳ, dán link TikTok, nhận được video
- [ ] Reboot mini → dịch vụ tự lên, đo bằng `launchctl list` + HTTP 200
- [ ] Chạy 50 video: thư mục làm việc **không bao giờ vượt 50 MB**, lấy mẫu mỗi 5s
- [ ] Job xong → thư mục làm việc **rỗng**, mọi video có trên Drive, đếm khớp
- [ ] Hai người dùng cùng lúc, cookie của A không lọt sang job của B
- [ ] `promax.nobidigital.asia` vẫn 200/302 suốt quá trình — **không làm hỏng hàng xóm**

## Nhật ký nghiệm thu

**14/09 17:45 — MVP CHẠY TRỌN VÒNG trên mini.** Đo thật, không phải test:
`POST /jobs` → **done 3/3, 0 lỗi, 18 giây** · `drive_folder_link` trả về trong API ·
thư mục làm việc **0 file** còn lại · `healthz` **200** · **SIGKILL → tự lên lại**
(pid 10171→46348) · `promax` **302 suốt** · label astronex **4→5**, không mất cái nào ·
suite **127 passed** chạy ngay trên mini.

Ba chỗ suýt hỏng âm thầm, bắt được nhờ kiểm tại nguồn: **tên biến môi trường tôi đặt
sai cả hai** (`GDRIVE_SERVICE_ACCOUNT_FILE` / `GDRIVE_SHARED_DRIVE_FOLDER_ID`, code
dùng hằng số `ENV_*` nên grep chuỗi không ra) — nghiệm thu bằng `is_configured()` True
+ đối chứng bỏ biến → False · `pytest rc=1` trên mini là **thiếu pytest**, không phải
code sai · đĩa nhảy 4,0→8,39→5,88 GB giữa các lần đo, xác nhận lần ba là nó dao động
theo người dùng khác.

**14/09 16:48 — chuỗi 7 lỗ HIGH đã sửa.** `pytest` **127 passed, rc=0** (107→127).
Traversal bịt bằng **cấu tạo** (tên file = sha256) chứ không bằng regex lọc: đo
`'../../../x'` → None, ca dương `'namhd'` → trong vùng. `nguoi_tao` bỏ khỏi body HTTP ·
cổng chặn job đã nối · hook trả `UploadResult` · cột `drive_folder_link` + thư mục
Drive mỗi job · cache credential thay vì cache service (bài học Broken pipe của
`creative_drive_client.py:3-10`).

⚠ **Phase 02/03 là CODE XONG, KHÔNG phải HOÀN THÀNH.** Mọi tiêu chí nghiệm thu của
chúng đều cần chạy **trên mini**: `curl healthz`, job thật qua HTTP, LaunchAgent bật
lại sau SIGKILL, `promax` vẫn 302, upload Drive thật. Hiện mới có code chạy local +
127 test. Tôi đã lỡ đánh dấu `completed` rồi tự bắt và sửa lại — đúng lớp lỗi "ghi
XONG khi acceptance chưa đo".

Nợ khai rõ: `tests/test_web_app.py` gọi thẳng hàm route, chưa qua `TestClient` — venv
thiếu `httpx`, agent không tự cài phụ thuộc khi chưa hỏi. Tầng HTTP chưa được test thật.

## Rủi ro xuyên suốt

**R1 — Tailscale đứt thì mất đường quản trị** (đã xảy ra 12 ngày). *Tín hiệu:* ssh
timeout mà hostname vẫn trả HTTP. *Phản ứng đã định:* không chữa gấp — dịch vụ vẫn
sống; nhờ người tại máy đăng nhập lại, hoặc thêm route SSH qua cloudflared (Phase 04
mục phụ). **Không** để dịch vụ phụ thuộc Tailscale.

**R2 — Đĩa đầy làm chết cả máy**, kéo theo Promax của người khác. Đĩa ở đây **không
ổn định**: đo được tụt 5,9 GB trong 40 phút do swap của người dùng khác, không phải
do tool. *Tín hiệu:* bộ đếm upload-trượt tăng, hoặc đĩa < **300 MB** (ngưỡng thật trong code). *Phản ứng:* Phase
03 (đẩy thẳng Drive, không giữ local) phải xong **trước** khi mở cho team; guard đọc
đĩa thật mỗi lần, không cache; trượt 3 lần liên tiếp thì dừng nhận job mới.

**R3 — Làm hỏng dịch vụ hàng xóm.** Máy đang chạy Promax production + ollama +
glances. *Phản ứng:* dùng port riêng 7870, label LaunchAgent riêng
`com.astronex.videodl`, **cấm** `launchctl bootout` bất kỳ label nào không phải của
mình (đã có tiền lệ: 27/08 một tác nhân bootout nhầm `promax-repo-guard`, lưới an
toàn tắt 32 phút).

**R4 — Cookie nhân viên nằm trên máy công ty** đụng luật *"secret: local only"*
trong `model-routing-ladder.md`. Anh đã chốt đè ngày 10/09. Phase 05 phải **ghi rõ
đang tạm đè luật nào**, không im lặng.

**R5 — `/search` ĐÃ GIẢI QUYẾT 14/09.** Đo không cookie: ăn **1/12 lượt**. Đo **có
cookie**: ăn ngay lượt đầu, **19/20 video thật**. Cookie là biến số quyết định, không
phải headless/headful như tôi từng kết luận. UI nói được sự thật về nguồn này.

**R6 — IP egress của công ty gom hết tải TikTok** *(kongming bắt, 14/09)*. Tool
desktop rải tải theo IP từng người; dồn về một mini nghĩa là TikTok/tikwm rate-limit
đánh **cả văn phòng**, và có thể đụng cả Promax nếu nó chạm TikTok. *Tín hiệu:* tỉ lệ
lỗi tải tăng vọt, hoặc người trong văn phòng báo TikTok chậm. *Phản ứng:* cap số job
toàn cục theo ngày; `--proxy` đã có sẵn trong CLI nếu cần tách IP.

**R7 — credential Drive là secret THỨ HAI** trên máy công ty, ngoài cookie TikTok ở
R4. Chưa chốt ai sở hữu (xem Phase 03). Cùng luật `secret: local only` đang bị đè.

## ✅ Ba chốt của user, ngày 14/09/2026

| | Chốt | Hệ quả trong kế hoạch |
|---|---|---|
| chỗ chứa file | **Drive công ty (Shared Drive)** | Phase 03 hết chặn. Bắt buộc `supportsAllDrives=true` — service account có trần riêng 15 GB, Shared Drive thì không |
| nối meta-auto | **(a) link trong nav**, tiêu chí *"an toàn là được"* | Phase 06 hết chặn. Tool hỏng không kéo meta-auto |
| phạm vi dùng | **nội bộ, không kinh doanh** — để team dùng online, khỏi cài trên máy | xem dưới |

**Phạm vi nội bộ đổi hai thứ, không chỉ là ghi chú:**

1. **Không bao giờ để hostname mở công khai.** Mục đích là cho người trong công ty
   dùng — nên Cloudflare Access không phải tính năng phụ mà là **điều kiện của chính
   mục đích**. Củng cố việc đưa Access vào Phase 04 thay vì Phase 05.
2. **Không quảng bá ra ngoài, không bán, không đưa cho khách.** README của repo ghi
   phạm vi *personal-use, creator-owned content* và nói bulk-scrape vi phạm ToS
   TikTok. Dùng nội bộ với số lượng có kiểm soát là mức phơi sáng thấp nhất còn đạt
   mục đích. Gắn với R6: cap số job/ngày không chỉ để tránh rate-limit, mà còn để giữ
   quy mô đúng như đã chốt.
