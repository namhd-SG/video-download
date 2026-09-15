---
phase: 2
title: "Lớp web thay Tkinter"
status: in-progress
priority: P1
effort: "2-3d"
dependencies: [1]
---

# Phase 2: Lớp web thay Tkinter

## Overview

Viết lớp web mỏng bọc quanh lõi sẵn có: một trang nhập link + hàng đợi job + trang
xem tiến độ. Tkinter **không serve được qua web** nên đây là phần bắt buộc viết mới.

## Requirements

- Functional: dán URL → tạo job → xem tiến độ trực tiếp → lấy kết quả.
- Non-functional: một job chạy tại một thời điểm (mỗi job mở một Chromium); job
  không chết theo request; tiến trình sống qua reboot.

## Architecture

```
web/app.py           FastAPI: POST /jobs · GET /jobs/{id} · GET /jobs · SSE tiến độ
web/queue.py         hàng đợi tuần tự, ghi trạng thái ra SQLite (sống qua restart)
web/static/          một trang HTML, không build step
src/tiktok_music_downloader/   LÕI — KHÔNG sửa
```

Cổng **7870**. 7860 là Promax, 11434 ollama, 61208 glances — đã đo.

**Hàng đợi tuần tự, không song song.** Mỗi job mở một Chromium; máy 16 GB đã chạy
Promax + ollama. Song song là đường ngắn nhất tới OOM — chính lỗi đã làm chết job
search hôm 11/09.

Trạng thái job ghi **SQLite**, không giữ trong RAM: tiến trình chết giữa chừng thì
lượt sau còn biết job nào dở.

## Related Code Files

- Create: `web/app.py`, `web/queue.py`, `web/models.py`, `web/static/index.html`
- Modify: `pyproject.toml` — thêm extra `[web]`: fastapi, uvicorn, sse-starlette
- Modify: `com.astronex.videodl.plist` — trỏ vào uvicorn, `KeepAlive`

## Implementation Steps

1. `web/models.py`: bảng `jobs(id, url, trang_thai, tong, xong, loi, tao_luc, xong_luc, nguoi_tao)`.
2. `web/queue.py`: worker một luồng, đọc job `pending` cũ nhất. **Sau MỖI video** gọi
   `lifecycle` của Phase 03 (đẩy Drive rồi xoá local) — không tích file tới cuối job,
   vì đĩa mini biến động và đỉnh phải giữ ở mức một video. Gọi thẳng
   `enumerate_hashtag` / `scrape_music_page` rồi `download_all`, cập nhật tiến độ
   qua callback `progress` mà `download_all` đã nhận sẵn.
3. `web/app.py`: các endpoint trên + SSE đẩy tiến độ.
4. `web/static/index.html`: ô URL, ô số lượng, danh sách job, thanh tiến độ. Một file,
   không build step — giống tinh thần bundle sẵn của repo.
5. Cắm bước **xác minh có luồng video** vào cuối mỗi job — dùng đường đã chốt ở
   Phase 01 bước 4 (`ffmpeg -i`, **không phải ffprobe**: repo không có binary đó).
   File không có luồng video thì **không đếm là thành công** (đo 10/09: 151/259
   "downloads" là .mp3/.m4a, và thêm 11 file `.mp4` không có luồng video nào).
6. Trỏ LaunchAgent vào `uvicorn web.app:app --port 7870 --host 127.0.0.1`. Bind
   **127.0.0.1**, không `0.0.0.0` — ra ngoài chỉ qua cloudflared.
7. `launchctl load` và kiểm nó tự lên sau `launchctl kickstart -k`.

## Success Criteria

- [x] `curl 127.0.0.1:7870/healthz` → **HTTP 200 · 0,03s** trên mini (14/09 17:40)
- [x] Tạo job qua HTTP → **done 3/3, 0 lỗi, 18 giây**; đếm bằng ffmpeg. Tạo job qua HTTP → nhận file thật, đếm bằng **phép xác minh luồng video**
      (`ffmpeg -i`) chứ không đọc log
- [x] **SIGKILL → pid 10171→46348, healthz 200, job cũ vẫn `done` không treo**. Giết tiến trình giữa job → LaunchAgent bật lại, job dở hiện trạng thái đúng
      trong SQLite (không biến mất, không báo "xong" giả)
- [x] Hai job gửi cùng lúc → chạy **tuần tự**, đo bằng mốc thời gian trong DB
- [ ] RAM lúc chạy job: `ps -o rss` của tiến trình < 1,5 GB
- [x] `promax.nobidigital.asia` **302 suốt**, label astronex 4→5 không mất cái nào

## Risk Assessment

**Chromium ngốn RAM, đụng Promax + ollama.** *Tín hiệu:* job bị hệ thống giết, hoặc
`memory_pressure` báo free < 15%. *Phản ứng:* hạ xuống một job tại một thời điểm
(đã là mặc định), và nếu vẫn chết thì thêm guard từ chối job mới khi RAM thấp.

**Báo "xong" cho job thật ra hỏng.** Lớp lỗi đã trả giá nhiều lần. *Phản ứng:* mốc
"đã xong" chỉ ghi **SAU** khi phép xác minh luồng video chạy xong; hàm tải phải
**trả trạng thái**, không `except: pass`. Đột biến: bỏ bước xác minh ⇒ test phải ĐỎ.

**Job chết giữa chừng để lại row `running` vĩnh viễn** *(kongming bắt)*. `KeepAlive`
restart bằng SIGKILL nên không có cơ hội dọn. *Phản ứng:* lúc khởi động, quét mọi row
`running` và chuyển sang `interrupted` — không để nó treo mãi, cũng không đánh dấu
"xong" giả. **Đột biến:** bỏ bước quét lúc boot ⇒ test phải ĐỎ.

**SSE rớt khi tunnel đứt** → UI treo ở "đang chạy" mãi. *Phản ứng:* UI poll
`GET /jobs/{id}` làm đường lùi, không chỉ dựa vào SSE.
