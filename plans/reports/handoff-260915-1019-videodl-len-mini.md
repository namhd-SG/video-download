# Bàn giao — video-download lên mac mini công ty, ra domain

**Từ:** `macos-cb` · **Ngày:** 15/09/2026 10:19 · **Kế hoạch:** `plans/260914-1412-tool-len-mini-va-domain/` (12/39 việc)

---

## 1. Đang ở đâu

MVP **đã chạy trọn vòng trên mini**, đo thật không phải test:

```
POST /jobs → done 3/3, 0 lỗi, 18 giây
drive_folder_link trả về trong API
thư mục làm việc: 0 file còn lại
healthz 200 · SIGKILL → tự lên lại (pid 10171→46348)
promax hàng xóm 302 suốt · label astronex 4→5, không mất cái nào
pytest 127 passed rc=0 — chạy NGAY TRÊN MINI
```

Còn đúng **4 việc** là xong, và **không còn gì chờ user**.

## 2. Hạ tầng đã dựng (đừng dựng lại)

| | |
|---|---|
| máy | `nobi_auto@100.109.39.103` (Tailscale, ssh vào được) |
| repo | `~/Projects/video-download` · venv `.venv` · python `/opt/homebrew/bin/python3` (3.14.7) |
| dịch vụ | LaunchAgent `com.astronex.videodl`, `KeepAlive`, cổng **7870** bind **127.0.0.1** |
| khởi động | `deploy/run-service.sh` (nạp env rồi exec uvicorn) |
| dựng lại từ đầu | `deploy/mini-setup.sh` — **đã chạy thật**, idempotent |
| cấu hình | `~/.config/videodl/env` (600) + `drive-key.json` (600), thư mục 700 |
| dữ liệu chạy | `~/.local/share/videodl/{downloads,cookies}` (700) |
| log | `~/Library/Logs/videodl.log` |

**Bốn biến trong `~/.config/videodl/env`** (tên phải khớp hằng số `ENV_*` trong code):
`GDRIVE_SERVICE_ACCOUNT_FILE` · `GDRIVE_SHARED_DRIVE_FOLDER_ID` · `CF_ACCESS_TEAM_DOMAIN` · `CF_ACCESS_AUD`

**Drive:** dùng **chung service account của Creative Desk** (user chốt 14/09, đã ghi
`~/agy-ws/DECISIONS.md` kèm luật đang đè). Thư mục riêng `video-tool`
id `1FJdIrKkezvHle7MbQ3pjKa7fCysjDE5t` trong Shared Drive `0AASy4v5CJAkfUk9PVA`.
Upload thật đã nghiệm thu: `driveId` trả về **khớp** Shared Drive.

**Access:** team domain `nobidigital.cloudflareaccess.com`, AUD tag đã nằm trong env.
Bộ khoá công khai lấy được: **2 khoá RS256** từ `/cdn-cgi/access/certs`.

## 3. Bốn việc còn lại — theo ĐÚNG thứ tự này

**(1) `web/auth.py` — kiểm JWT.** Xác thực chữ ký + `aud` của header
`Cf-Access-Jwt-Assertion` theo bộ khoá team. `nguoi_tao` lấy từ JWT, **không** từ body
(body đã bỏ field này rồi). Đột biến bắt buộc: gửi header email giả không kèm JWT hợp
lệ ⇒ phải **401**; bỏ bước kiểm JWT ⇒ test **ĐỎ**.

**(2) Thêm hostname vào tunnel.** Sửa `~/.cloudflared/config.yml` trên mini — chèn
`video.nobidigital.asia → http://localhost:7870` **TRƯỚC** nhánh `http_status:404`
(thứ tự ingress có nghĩa; đặt sau nhánh 404 thì không bao giờ khớp, và đó là lỗi im lặng).
- `cp config.yml config.yml.bak-<ngày>` trước khi sửa — file này đang giữ Promax của người khác
- `cloudflared tunnel ingress validate` trước khi nạp
- **Thử KHÔNG restart trước**: cloudflared tự nạp lại khi file đổi. Ăn rồi thì bỏ hẳn bước restart
- Nếu buộc phải restart: `launchctl kickstart -k gui/$(id -u)/com.astronex.cloudflared`. **TUYỆT ĐỐI KHÔNG `bootout`**

⚠ **Thứ tự bắt buộc: Access phải xanh TRƯỚC khi hostname chạm cổng 7870.** Đây là lỗ
kongming bắt ở vòng thẩm định — Certificate Transparency công bố hostname mới trong
vài phút, nên "chưa ai biết link" không phải biện pháp bảo vệ.

**(3) Nghiệm thu toàn hệ.** Chưa đăng nhập → phải bị Access chặn (302 về
cloudflareaccess.com), **không** phải 200 từ tool · đăng nhập rồi → vào được, 3/3 lần ·
từ 4G (ngoài LAN) vẫn được · `promax` vẫn 302 trong suốt · `launchctl list | grep -c
astronex` không giảm.

**(4) Nối link vào nav meta-auto.** User chốt đường (a): **link trong nav**, không nhúng
UI. Ba chỗ theo mẫu đã biết: sidebar + `isGuestAllowed` + guard route. Tiền lệ: Promax
cũng là service riêng + hostname riêng, 0 dòng trong frontend meta-auto.

## 4. Ranh giới an toàn — user đặt ra, đã giữ cả ngày

- **Không đụng label launchctl của người khác.** Máy chạy production của người khác:
  `com.astronex.promax`, `promax-awake`, `cloudflared`, `glances` + ollama. Đếm
  `launchctl list | grep -c astronex` **trước và sau** mỗi lần đụng launchctl.
- **Không sửa gì của Creative Desk** — chỉ đọc biến môi trường từ container.
- **Không in credential/token/JWT** ra chat. AUD tag và team domain thì được (không phải
  secret, nằm trong mọi JWT).
- **Không chạy job lớn** — IP văn phòng dồn về một chỗ, rủi ro khoá nick TikTok (R6).

## 5. Bẫy đã trả giá — đừng dẫm lại

**`launchctl bootout` là BẤT ĐỒNG BỘ.** Nó trả về trước khi label được gỡ xong;
`bootstrap` ngay dòng sau gặp `Bootstrap failed: 5` ⇒ **dịch vụ chết**. Đã xảy ra
14/09, gián đoạn 90 giây. `mini-setup.sh` giờ poll `launchctl print` cho tới khi label
biến mất thật. Và `|| true` sau bootout từng nuốt luôn mọi lỗi khác.

**zsh, không phải bash.** `rc=$?` NGAY SAU lệnh, **không pipe** qua `tail` (pipe trả mã
của `tail`); `${PIPESTATUS[0]}` là cú pháp bash, zsh không có. Quote mọi
`--include="*.py"` khi grep — zsh nuốt glob không quote.

**Repo KHÔNG có `ffprobe`.** LFS chỉ track `ffmpeg` + `ffmpeg.exe`. Xác minh luồng
video bằng `ffmpeg -i <file>` rồi đếm dòng khớp `Stream.*Video:`. Binary ở
`assets/ffmpeg-static/ffmpeg`. Và `git bundle` **không mang LFS object** — chuyển binary
bằng `scp` riêng rồi đối chiếu sha256.

**Đĩa mini do NGƯỜI KHÁC quyết định.** Đo trong một buổi: 11 → 5,1 → 8,39 → 7,18 →
2,24 → 4,24 GB, theo swap của Android Studio + emulator. Ngưỡng guard thật là
**300 MB** (`DEFAULT_MIN_FREE_BYTES`), không phải 5 GB — số 5 GB là của bản kế hoạch cũ
hồi còn giữ file local. Thiết kế hiện tại không giữ bản local nên đỉnh ≈ một video.

**`should_reject_new_job()` phải truyền `downloads_dir`** — thiếu tham số đó thì gate
đĩa bị bỏ qua **im lặng**. `app.py:78` gọi đúng.

**Tên biến môi trường nằm trong hằng số `ENV_*`**, không phải chuỗi trực tiếp — grep
chuỗi không ra. Nghiệm thu cấu hình bằng `DriveUploader().is_configured()` trả True,
kèm đối chứng bỏ biến → False.

**`pytest` trên mini phải cài riêng** (không nằm trong nhóm `[web]`). `rc=1` vì thiếu
pytest ≠ code sai.

## 6. Chỗ tôi (macos-cb) đã sai — nói để không lặp

- **Đánh dấu Phase 02/03 `completed` khi chưa đo tiêu chí nào trên mini.** `ak plan
  status` bắt được vì nó đếm checkbox, không đọc frontmatter tôi tự khai. Đã sửa thành
  "code xong, chưa nghiệm thu" rồi mới tick từng cái kèm bằng chứng.
- **Chạy code-reviewer và fullstack-developer SONG SONG trên cùng worktree.** Reviewer
  soi một cây đang đổi dưới chân; suite nhảy 90→107 giữa lượt soi. Từ đó: **một agent
  một lúc**.
- **Nói "suite xanh nhờ thứ tự alphabet"** — sai, có `autouse` fixture reset ở
  `test_lifecycle.py:62`. Tôi lấy nhận định của reviewer rồi nói lại như sự thật mà
  không tự kiểm.
- **Ba báo động nhầm trong một vòng loop:** đĩa tụt (do swap người khác) · guard không
  chặn (tôi gọi hàm **khác cách production gọi**) · ngưỡng 5 GB (số cũ trong plan). Cái
  giữa đáng ngại nhất — suýt đi sửa một thứ đang đúng.
- **Grep bỏ comment bằng `tokenize` không thấy dict key** — `"supportsAllDrives": True`
  là STRING token nên bị lọc. Cùng dụng cụ, câu hỏi khác, kết quả vô nghĩa.

**Kỷ luật đã dùng và nên giữ:** mọi phép đo rỗng phải kèm **ca dương**; kiểm tại nguồn
thay vì tin báo cáo subagent; nghiệm thu bằng **đột biến** (bỏ cơ chế ⇒ phải ĐỎ) cho
mọi ca hỏng-âm-thầm.

## 7. Việc treo ngoài MVP (không chặn)

- **Giao diện:** artifact 3 hướng — https://claude.ai/code/artifact/36df6152-ca5e-49c2-9c75-e44962691375
  User chốt **A trên + C dưới**, "cần brainstorm thêm", **không vội làm**. Còn treo:
  "xoá" = xoá thật trên Drive (cần bước xác nhận vì khó lui) · "tìm thêm giống cái này"
  = **điền sẵn rồi user bấm**, không tự chạy · trục kiểu-creative qua agy = **tùy chọn**,
  ngoài MVP.
- **Instagram:** 100 video ở `~/Downloads/instagram-1980s/` tải bằng `yt-dlp` trực tiếp.
  Khả thi (yt-dlp có extractor IG) nhưng ngoài MVP.
- **Nợ kỹ thuật:** `tests/test_web_app.py` gọi thẳng hàm route, chưa qua `TestClient`
  (venv thiếu `httpx`) · cap job/ngày (~10 dòng, user đã chốt, giảm rủi ro khoá nick) ·
  quy tắc lọc photo-post vào code (đã xác thực 2 bộ, âm tính giả 0).
- **Bỏ qua theo lệnh user:** sắp xếp cây `80s-creative/` · thư mục `300 copy/`.

## 8. Lệnh kiểm nhanh khi vào việc

```bash
ssh nobi_auto@100.109.39.103 'launchctl list | grep astronex; \
  curl -s -o /dev/null -w "healthz %{http_code}\n" http://127.0.0.1:7870/healthz; \
  df -k / | tail -1 | awk "{printf \"đĩa %.2f GB\n\", \$4/1048576}"'
curl -s -o /dev/null -w "promax %{http_code}\n" https://promax.nobidigital.asia
cd ~/Projects/video-download && ak plan status plans/260914-1412-tool-len-mini-va-domain
```

## Câu hỏi chưa giải

1. Hostname `video.nobidigital.asia` — user đã xác nhận, nhưng **phải khớp đúng
   subdomain user đã tạo trong Access application**. Lệch một chữ là Access không áp
   lên hostname ⇒ dịch vụ mở trần. Kiểm trước khi sửa `config.yml`.
2. `/search` với cookie đo được **19/20 ở một lượt**; chưa đo nhiều lượt để biết tỉ lệ
   ổn định. Cookie của user nằm ở `~/.local/share/videodl/cookies` trên mini (MVP dùng
   cookie của user, P05b mới mở cho từng người tự dán).
