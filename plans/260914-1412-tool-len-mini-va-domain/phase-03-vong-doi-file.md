---
phase: 3
title: "Đẩy thẳng Drive, không giữ bản local"
status: in-progress
priority: P1
effort: "1-2d"
dependencies: [2]
---

# Phase 3: Đẩy thẳng Drive, không giữ bản local

# PHẢI XONG TRƯỚC KHI MỞ CHO TEAM

## ✅ USER CHỐT 14/09 (lần 2) — bỏ hẳn bản local

Bản đầu của phase này giữ file local 24h rồi mới dọn theo TTL. **Sai tiền đề.**

Đo lúc 14:11: đĩa trống 11 GB. Đo lại 14:50: **5,1 GB**. Mất 5,9 GB trong 40 phút,
mà phần của tôi chỉ 180 MB. Thủ phạm: **swap** — `/System/Volumes/VM` có 5 file
`swapfile` × 1 GB, `vm.swapusage` dùng 4,1/5,1 GB. Máy 16 GB RAM và người đang ngồi
máy chạy Android Studio (14,6% RAM) + Chrome.

⇒ Con số 11 GB chỉ là **ảnh chụp lúc máy vừa reboot, swap chưa phình**. Đĩa trống
thật **dao động theo việc người khác dùng máy** — không kiểm soát được, không đoán
trước được. Thiết kế nào dựa vào "còn X GB" đều mong manh.

**Thiết kế mới:** tải xong **một file** thì đẩy Drive ngay, upload xác nhận xong thì
**xoá bản local ngay**. Không TTL, không kho local.

## Requirements

- Functional: job xong → mọi file nằm trên Drive, đĩa mini sạch, người dùng nhận link.
- Non-functional: **đỉnh dung lượng ≈ một video đang xử lý**, không phải cả job.

## Architecture

```
vòng lặp mỗi video:
  tải 1 video → xác minh có luồng video (ffmpeg -i)
              → upload Shared Drive
              → upload TRẢ VỀ THÀNH CÔNG?
                    có  → xoá bản local NGAY
                    không → GIỮ file, tăng bộ đếm trượt
  bộ đếm trượt >= 3  → DỪNG NHẬN JOB MỚI, báo lên UI
```

Đỉnh đĩa: **một video** (trung vị 0,83 MB, lớn nhất đo được 22 MB) + phần Chromium
đang chạy — thay vì ~306 MB/job của bản cũ. Đĩa máy này đo được đi **11 → 5,1 → 8,39
→ 7,18 → 2,24 GB trong một buổi** theo swap của người dùng khác; đây là khác biệt
giữa dùng được và không.

**Backpressure là phần không được bỏ.** Không giữ local + Drive trượt = file tích lại
im lặng cho tới khi đầy đĩa, và lúc đó Promax của người khác chết theo. Trượt 3 lần
liên tiếp thì dừng nhận job mới — thà đứng còn hơn làm đầy đĩa máy người khác.

## Trần 15 GB vẫn là chuyện thật

Chốt Drive công ty ngày 14/09 bắt buộc **Shared Drive**, không phải "My Drive" của
service account: service account có trần **15 GB riêng**, với 1,53 GB/1000 video thì
~10.000 video là 403 cứng. Mọi lời gọi API phải mang `supportsAllDrives=true` —
thiếu cờ này là **lỗi im lặng**: upload trông như chạy, file rơi vào 15 GB riêng của
service account, xanh hết cho tới lúc chết cứng.

Credential Google là **secret thứ hai** trên máy công ty (ngoài cookie TikTok, R7
trong `plan.md`). Cùng kỷ luật: quyền `0700`, không vào log, không vào git.

## Related Code Files

- Create: `src/tiktok_music_downloader/gdrive_upload.py` — đường upload **mới hoàn
  toàn**. `gdrive.py` hiện tại dùng `gdown`, chỉ tải xuống, cố ý không OAuth ⇒ không
  tái dùng được cho việc này (đã kiểm tại nguồn)
- Create: `web/lifecycle.py` — upload-rồi-xoá theo từng file, backpressure, guard đĩa
- Modify: `web/queue.py` — gọi lifecycle sau **mỗi video**, không phải sau mỗi job

## Implementation Steps

1. Tạo service account + cấp quyền ghi vào **Shared Drive** công ty; tạo thư mục gốc
   cho tool. Cất khoá như secret.
2. `gdrive_upload.py`: upload một file, **trả trạng thái**. Phân biệt rõ ba ca:
   *thành công* · *chưa cấu hình* · *đã cấu hình mà trượt*. Trả cùng giá trị cho hai
   ca sau là biến việc dọn thành ồn vô hạn.
3. `lifecycle.py`: sau mỗi video — xác minh luồng video, upload, **chỉ xoá khi upload
   trả thành công**. Mốc ghi SAU việc, không trước.
4. Backpressure: đếm trượt liên tiếp; chạm 3 thì đặt cờ `tam_dung`, từ chối job mới,
   hiện lý do trên UI. Đếm về 0 khi có một upload thành công.
5. Guard đĩa: ngưỡng **300 MB** (`DEFAULT_MIN_FREE_BYTES`), hợp với đỉnh mới ≈ một
   video (lớn nhất đo được 22 MB). **Đọc đĩa thật mỗi lần**, không cache.
   ✅ Đã nghiệm thu trên mini 14/09 19:10: đĩa 2,40 GB → `check_disk_guard` trả
   `ok=True` (đúng, còn xa ngưỡng), job mới được nhận. Gọi từ `app.py:78` có truyền
   `downloads_dir` — thiếu tham số đó thì gate đĩa bị bỏ qua im lặng.
6. UI: trả link Drive của từng video + link thư mục job. Nói rõ file **không** nằm
   trên máy chủ, tải từ Drive.

## Success Criteria

- [ ] Chạy job 50 video: `du -sh` thư mục làm việc **không bao giờ vượt 50 MB** ở bất
      kỳ mốc nào (lấy mẫu mỗi 5s trong lúc chạy). Đây là phép đo có sức phân định
      thật — bản cũ *"200 video ⇒ đĩa không dưới 8 GB"* **cấu tạo không thể ĐỎ**
- [x] Job thật xong → thư mục làm việc **0 file**, link Drive trả trong API. Job xong → thư mục rỗng, mọi video có trên Drive, đếm khớp
- [x] **`driveId` trả về khớp Shared Drive công ty** — kiểm bằng driveId, không bằng 'không báo lỗi'. File nằm trong Shared Drive — kiểm bằng `driveId` trả về, KHÔNG kiểm bằng
      "upload không báo lỗi"
- [ ] **Đột biến:** bỏ điều kiện "upload trả thành công" trước khi xoá ⇒ test phải ĐỎ
- [ ] **Đột biến:** bỏ backpressure ⇒ test phải ĐỎ (ép Drive trượt, file phải tích
      lại **và** job mới phải bị từ chối)
- [ ] Ép Drive trượt 3 lần ⇒ file **vẫn còn**, job mới **bị từ chối**, UI nói rõ lý do
- [ ] ~~Trong suốt lượt thử, đĩa mini **không tụt** quá 100 MB~~ — **BỎ 21/09,
      cùng lý do đã bỏ bản *"200 video ⇒ đĩa không dưới 8 GB"* ở dòng trên, chỉ
      ngược chiều: bản đó cấu tạo không thể ĐỎ, bản này ĐỎ GIẢ.** Đĩa mini là tài
      nguyên **dùng chung với Promax của đội khác**. Đo 21/09 10:05 bằng
      `scripts/do-nghiem-thu-t4.sh mau 10`: đĩa tụt **185 MB trong 10 giây** trong
      khi cột `job_running = 0` suốt — tức tụt do hàng xóm, tool không chạy gì.
      Ngưỡng tuyệt đối trên máy dùng chung không phân định được ai gây ra.
      **Thay bằng** `du -sm` thư mục tải ≤ 50 MB (thứ tool thật sự kiểm soát) +
      `ps -o rss` < 1,5 GB. Cột đĩa vẫn in ra nhưng là **thông tin**, không phải
      tiêu chí. Muốn con số đĩa có nghĩa thì phải so hai lượt cùng độ dài, một
      lượt có job và một lượt không — hiệu số mới là phần của tool.

## Risk Assessment

**Xoá file chưa kịp lên Drive.** Hỏng âm thầm — người dùng chỉ biết khi cần file.
*Phản ứng:* điều kiện xoá là `upload_trả_thành_công`, khoá bằng test đột biến.

**Drive trượt liên tục ⇒ file tích lại ⇒ đầy đĩa ⇒ Promax chết.** Đây là ca đắt nhất
vì nó hỏng việc người khác. *Tín hiệu:* bộ đếm trượt tăng. *Phản ứng:* backpressure ở
bước 4, và guard đĩa đọc lại mỗi lần.

**Đĩa tụt vì swap của người khác, không phải vì tool.** Đã xảy ra: 5,9 GB trong 40
phút. *Phản ứng:* guard đọc đĩa thật mỗi lần, không cache; và vì đỉnh của tool giờ
chỉ ~50 MB nên tool không còn là bên đẩy đĩa xuống.

**Thiếu `supportsAllDrives=true`.** Lỗi im lặng, chết ở mốc ~10.000 video khi không
ai còn nhớ. *Phản ứng:* kiểm `driveId` trong tiêu chí nghiệm thu.
