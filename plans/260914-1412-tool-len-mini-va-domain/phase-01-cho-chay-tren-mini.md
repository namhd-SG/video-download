---
phase: 1
title: "Chỗ chạy trên mini"
status: completed
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Chỗ chạy trên mini

## ✅ HOÀN THÀNH 14/09 15:00 — nghiệm thu bằng phép đo

```
tải thật trên mini: downloaded 3 · failed 0
xác minh ffmpeg -i:  file .mp4 = 3 · CÓ luồng video = 3
```

| tiêu chí | kết quả |
|---|---|
| ffmpeg bundle chạy trên mini | ✓ 8.1.2 |
| sha256 khớp `git lfs ls-files` | ✓ `47121807fe79…` |
| mã nguồn sang đủ | ✓ 15 `.py` · 4 test · pyproject |
| import THẬT (không py_compile) | ✓ |
| Chromium khởi động thật | ✓ launch + goto |
| đĩa sau khi dựng | 4,29 GB |
| LaunchAgent hàng xóm | chưa đụng |

**Số đo bất ngờ:** Chromium thật **1,1 GB** — README nói 150 MB, thẩm định đo 554 MB
trên máy dev. Ba ước đều nhẹ hơn thực tế. Số đo ở máy khác không thay được số đo ở
đúng máy.

**Bốn điều kiện hỏng-âm-thầm đã gỡ trước khi tốn công:** auto-login = `nobi_auto`
+ FileVault Off (LaunchAgent SẼ tự lên sau reboot) · playwright có wheel cho Python
3.14 (không phải compile) · cloudflared chạy `tunnel run promax` **không** `--token`
(locally-managed ⇒ Phase 04 sửa config.yml được) · `/opt/homebrew` ghi được.

**Nợ đã TRẢ 14/09 18:20:** `com.astronex.videodl.plist` + `deploy/mini-setup.sh`,
chạy thật trên mini (rc=0, healthz 200, label astronex 5→5, promax 302).

⚠ **Script làm chết chính dịch vụ ở lần chạy đầu.** `launchctl bootout` là BẤT ĐỒNG
BỘ — nó trả về trước khi label được gỡ xong, nên `bootstrap` ngay dòng sau gặp
`Bootstrap failed: 5: Input/output error`; kết cục bootout thành công + bootstrap
thất bại = dịch vụ không còn. Gián đoạn ~90 giây. Hàng xóm KHÔNG bị đụng (4 label
Promax/cloudflared/glances/promax-awake nguyên vẹn, promax 302 suốt).
Hai lỗi trong một: (1) đua bất đồng bộ, (2) `|| true` sau bootout nuốt luôn mọi lỗi
khác — đúng lớp `except: pass`. Đã sửa: chờ label **biến mất thật** (poll `launchctl
print`, không `sleep` mù) và bootstrap hỏng thì script ĐỎ, không đi tiếp.
**Bài học chung:** script dựng-lại-từ-đầu mà chưa từng chạy thì không phải script,
chỉ là ghi chú — lỗi này sẽ nằm im tới đúng lúc có sự cố thật và cần nó nhất.

## Overview

Dựng runtime cho tool trên `nobi_auto@100.109.39.103`: repo, venv, ffmpeg, Chromium,
LaunchAgent tự khởi động. Chưa có web — chỉ cần CLI chạy được một lượt tải thật.

## Requirements

- Functional: chạy được `tiktok-music-dl <tag-url>` trên máy đó, ra video thật.
- Non-functional: tự lên sau reboot; không đụng LaunchAgent nào đang chạy.

## Architecture

```
~/Projects/video-download/          repo
  .venv/                            /opt/homebrew/bin/python3 -m venv
  assets/ffmpeg-static/ffmpeg       CHỈ có ffmpeg. KHÔNG có ffprobe (xem dưới)
~/Library/LaunchAgents/
  com.astronex.videodl.plist        label RIÊNG, không trùng promax
~/Library/Caches/ms-playwright/     Chromium — 1,1 GB đo TRÊN MINI (README: 150 MB)
```

Python: `/opt/homebrew/bin/python3` (3.14.7). Bản hệ thống 3.9.6 **không đủ** — tool
cần ≥3.10.

## ⚠ SỬA SAU THẨM ĐỊNH 14/09 — hai tiền đề sai của bản đầu

**1. Repo KHÔNG có `ffprobe`.** Đã kiểm: `.gitattributes` đúng hai dòng
(`assets/ffmpeg-static/ffmpeg` và `ffmpeg.exe`), `git lfs ls-files` trả đúng hai
file đó. Bản đầu viết `assets/<platform>/ffprobe` — sai cả **tên binary** lẫn
**đường dẫn thư mục**. Mọi chỗ trong kế hoạch dùng ffprobe để xác minh video phải
đổi sang **`ffmpeg -i <file>`** (đọc stream từ stderr), hoặc thêm ffprobe vào LFS.
Chọn đường nào cũng được, nhưng phải chọn — không được để nguyên.

**2. `git bundle` KHÔNG mang LFS object**, chỉ mang pointer. Mà `git lfs pull` thì
cần credential GitHub — chính máy này đã đo là **không có** (`could not read
Username` cả trong SSH lẫn launchd). Bản đầu đề xuất bundle làm đường lùi ⇒ cả hai
đường tới ffmpeg đều chết. **Đường đúng:** `scp` thẳng binary sang, rồi đối chiếu
`sha256` với `git lfs ls-files -l` trên máy này.

## Related Code Files

- Create: `~/Library/LaunchAgents/com.astronex.videodl.plist` (trên mini)
- Create: `deploy/mini-setup.sh` — script dựng lại từ đầu, chạy lại được nhiều lần
- Modify: không sửa gì trong `src/` ở phase này

## Implementation Steps

1. Chuyển code sang mini. `git clone` chỉ dùng được nếu có credential GitHub — máy
   này đo là **không có**. Đường chắc chắn: `rsync` mã nguồn + **`scp` riêng binary
   `assets/ffmpeg-static/ffmpeg`** (LFS object, ~146 MB).
2. Đối chiếu `sha256` của ffmpeg vừa chuyển với `git lfs ls-files -l` trên máy này.
   Khớp mới đi tiếp — pointer LFS trông giống file thật, chỉ khác kích thước.
3. Xác minh binary chạy được trên mini: `assets/ffmpeg-static/ffmpeg -version`.
   Máy không có ffmpeg hệ thống nên đây là đường duy nhất.
4. **Chốt cách xác minh video** (thay cho ffprobe không tồn tại): dùng
   `ffmpeg -i <file>` đọc stream, hoặc bổ sung ffprobe vào LFS. Ghi lựa chọn vào
   README để Phase 02/03 dùng đúng một đường.
5. Tạo venv bằng python brew, `pip install -e .`, `playwright install chromium`
   (**1,1 GB** trên mini, một lần — README ghi ~150 MB, máy dev đo 554 MB; cả hai đều sai).
6. **Kiểm wheel cho Python 3.14 TRƯỚC khi cài:**
   `pip download --only-binary=:all: -d /tmp/wheeltest .` — playwright/greenlet và
   pydantic-core có thể chưa có wheel 3.14, phải compile (cần Xcode CLT). Thiếu wheel
   thì `brew install python@3.12` và dùng bản đó.
7. Chạy thử một lượt tải thật với hashtag nhỏ, `--max 5`, đích là thư mục scratch.
8. **Kiểm điều kiện tự-khởi-động TRƯỚC khi tin `RunAtLoad`:** LaunchAgent trong
   gui-domain chỉ chạy **sau khi có người đăng nhập**. Đọc (không cần sudo):
   `defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser` và
   `fdesetup status`. Không auto-login hoặc FileVault bật ⇒ máy reboot là dịch vụ
   nằm im tới khi có người đăng nhập. Promax cũng chịu ràng buộc này — hỏi cách nó
   sống qua reboot, đừng phát minh lại.
9. Viết `com.astronex.videodl.plist`: `RunAtLoad`, `KeepAlive`, log ra
   `~/Library/Logs/videodl.log`. **Chưa load** — phase 02 mới có service để chạy.
10. Ghi `deploy/mini-setup.sh` gộp các bước trên để dựng lại được khi máy hỏng.

## Success Criteria

- [x] `assets/ffmpeg-static/ffmpeg -version` chạy được trên mini
- [x] `sha256` của ffmpeg trên mini **khớp** `git lfs ls-files -l` trên máy này
- [x] Một lượt tải thật ra ≥1 file, xác minh **có luồng video** bằng đường đã chốt ở
      bước 4 (`ffmpeg -i`, không phải ffprobe)
- [x] Đĩa đo bằng **delta `df`** trước/sau, KHÔNG bằng `du -sh` trên repo (Chromium
      nằm ở `~/Library/Caches/ms-playwright`, `du` repo không bao giờ thấy nó).
      ⚠ Ngưỡng "> 9 GB" của bản đầu **bỏ**: nền 11 GB lúc viết plan là ảnh chụp lúc
      máy vừa reboot; đĩa thật dao động theo swap của người khác
- [x] `launchctl list | grep -c astronex` **không giảm** so với trước khi bắt đầu

## Risk Assessment

**Chromium 1,1 GB.** Lớn gấp 7 lần README ghi, gấp 2 lần số đo ở máy dev. Đã cài,
đĩa còn 4,29 GB. *Bài học:* số đo ở máy khác không thay được số đo ở đúng máy.

**Không có credential GitHub, và `git bundle` không cứu được.** Máy này đã đo là
**không fetch được GitHub** (`could not read Username`) trong cả SSH lẫn launchd.
Bundle chỉ mang pointer LFS, không mang binary ⇒ đường lùi của bản đầu là **đường
cụt**. *Phản ứng đã định:* `rsync` mã nguồn + `scp` riêng binary ffmpeg + đối chiếu
sha256. Đừng mất thời gian gỡ credential.

**LaunchAgent không tự lên sau reboot nếu không có auto-login.** Hỏng âm thầm: mọi
thứ xanh cho tới lần mất điện đầu tiên. *Tín hiệu:* `autoLoginUser` rỗng hoặc
FileVault bật. *Phản ứng:* hỏi cách Promax sống qua reboot trước khi tự dựng cơ chế.

**Bootout nhầm label người khác** → tắt lưới an toàn Promax (đã xảy ra 27/08, mất
32 phút). *Phản ứng:* chỉ thao tác trên đúng `com.astronex.videodl`; trước và sau
mỗi lần đụng launchctl đều chạy `launchctl list | grep astronex` và so danh sách.
