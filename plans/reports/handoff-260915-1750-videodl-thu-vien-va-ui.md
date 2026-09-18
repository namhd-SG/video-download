# Bàn giao — Video Desk: thư viện + UI xong, còn 3 việc của user

**Từ:** `macos-aa` (session `b5f412e8`) · **15/09/2026 17:50** · **Nhận từ:** `macos-cb` sáng nay
**Nhánh:** `feat/tiktok-tag-page-support` — **22 commit**, cây sạch, đã push, `git branch -r --contains HEAD` ra nhánh.

---

## 1. Trạng thái — đo lúc 17:50, không phải lời khai

```
dev  : pytest 220 passed rc=0
mini : pytest 220 passed          ← đã đồng bộ, KHỚP dev
mini : label astronex 5 trước/sau kickstart
       healthz 200 · /videos không JWT → 401
promax (hàng xóm)                 → 302
video.nobidigital.asia            → 302 về Access (chưa đăng nhập)
```

Tool **đang chạy thật** sau Cloudflare Access. User đã đăng nhập được 3/3 lần và từ 3G.

## 2. Làm được gì hôm nay

**Sáng (nhận từ macos-cb):** `web/auth.py` kiểm JWT Access · hostname vào tunnel + DNS ·
nghiệm thu 6/6 tiêu chí phase-04 · link nav meta-auto (**PR #192, CI xanh, chưa merge**).

**Chiều:** lớp thư viện creative.
- Bảng `videos` + `video_sightings`, ảnh cắt bằng ffmpeg tại `on_video_verified`
- Lọc trùng ở khâu liệt kê, duyệt sâu cho đủ N cái MỚI
- `music_id`, `drive_file_id`, lý do dừng (`ly_do_dung`) lên hàng job
- `/videos`, `/thumbs/{id}` (sau `require_user`)
- `web/static/index.html` — dải điều khiển trên, thư viện dưới, 6 hộp xổ lọc
- `scripts/kiem-ui.sh` — 6 phép kiểm test không bắt được

## 3. CÒN LẠI — ba việc của user, một việc code

| # | việc | chặn ở đâu |
|---|---|---|
| 1 | **Session Duration** của Access app `video.nobidigital.asia` | Tôi **không đo được**: không có Cloudflare API token trên dev lẫn mini (`cert.pem` chỉ cấp tunnel+DNS, không chạm Zero Trust). Con số này **chính là** độ dài cửa sổ replay trong spec #195 |
| 2 | **Merge PR #192** (link nav meta-auto) | CI xanh, `mergeable`, chưa ai review |
| 3 | **Issue #195** — đội meta-auto triển khai | Đã mở + đã comment bổ sung route/payload + cơ chế shortcut |
| 4 | **Tách `app.css`/`app.js`** khỏi `index.html` (1047 dòng) | User đã duyệt, tôi hoãn: file vừa sửa nhiều trong 40', tách lúc đó là trộn hai loại thay đổi. **Làm commit riêng** |

**User đã tự làm xong:** hạ vai service account Drive Manager → Content manager (~16:14).

## 4. BẢY BẪY DỤNG CỤ đo được hôm nay — đọc trước khi đo bất cứ gì

Tất cả cùng một họ: **dụng cụ trả lời câu HẸP HƠN câu được hỏi**, và báo xanh.

1. **`| tail` nuốt mã thoát.** Gọi agy rồi `| tail` ⇒ đọc `rc` của `tail`. Suýt kết luận "agy chạy xong trả rỗng" trong khi nó lỗi ngay từ đầu.
2. **`timeout` không có trên macOS.** Probe dùng nó ⇒ phép đo vô nghĩa.
3. **`grep` phân biệt hoa-thường.** `grep -c "không rõ"` ra 0 trong khi file có `"Không rõ"` ⇒ suýt tố oan subagent.
4. **`drives().get(capabilities)` ≠ vai.** Muốn biết vai của một principal thì đọc `permissions().list`. Nhưng xem bẫy 5.
5. **HAI PHÉP ĐO LỆCH NHAU TRÊN HỆ CÓ NGƯỜI TÁC ĐỘNG** ⇒ hỏi *"trạng thái có đổi không"* TRƯỚC *"dụng cụ có hỏng không"*. Tôi làm ngược, commit một bản "đính chính" SAI, user phải nhắn *"tôi mới sửa"* mới lộ. **Mọi phép đo về quyền phải ghi kèm giờ.**
6. **axe `violations` KHÔNG gồm `incomplete`.** Đặt màu chữ trùng y nền ⇒ axe xếp vào `incomplete` ⇒ cổng chỉ đọc `violations` báo **SẠCH cho trang đang hỏng**. Ca âm là thứ duy nhất phát hiện.
7. **Đột biến phải thử MỐI NỐI, không chỉ lớp vừa viết.** Hai lần liên tiếp: (a) schema không ai gọi — 8 test xanh vì không có lời gọi nào để gỡ; (b) `_fetch_refs` nhận đúng kwargs mà lời gọi trong `process_job` không truyền — xoá kwarg ⇒ dedupe tắt im lặng, 211 test vẫn xanh.

## 5. Bài học giao việc — đã thành luật

Subagent dựng UI từ **mô tả bằng chữ** vì không mở được artifact (403 — trang riêng của
user). Hành vi đúng, **nhận diện sai hoàn toàn**. File mock nằm sẵn trên cùng máy.

⇒ Đã ghi vào `~/.claude/rules/orchestration-protocol.md` mục Delegation Context:
*việc có giao diện thì prompt phải chứa **đường dẫn tuyệt đối tới file mock trên đĩa**;
subagent trả về **đường dẫn ảnh chụp**, không phải câu tả.* Mock đã chép vào repo:
`plans/260914-1412-tool-len-mini-va-domain/mock-thu-vien-260915.html`.

## 6. Ranh giới an toàn — giữ nguyên

- Máy mini chạy production của đội khác. **Chỉ `launchctl kickstart -k` đúng label
  `com.astronex.videodl`**, không `bootout` gì. Đếm `launchctl list | grep -c astronex`
  trước và sau — phải là **5**.
- `cloudflared` **KHÔNG tự nạp lại config** (bàn giao sáng nói ngược — đã đo). Sửa
  `~/.cloudflared/config.yml` xong phải `kickstart -k com.astronex.cloudflared`.
  Sao lưu đã có: `config.yml.bak-260915`.
- Dữ liệu chạy ở `web/data/` (**không** phải `~/.local/share/videodl`, bàn giao sáng ghi
  sai). Quyền 700/600, `prepare_data_dir` tự siết mỗi lần khởi động.
- DB sao lưu trước mọi đổi schema: `jobs.db.bak-260915-1530`, `-1609`.
- Không in credential/token/JWT ra chat.

## Câu hỏi chưa giải

1. **Session Duration** (mục 3.1) — cần dashboard hoặc token đọc Access.
2. **Nút "Xoá"** — hỏi user 4 lần chưa có đáp. Hiện UI chỉ có "Bỏ khỏi giỏ" client-side;
   **không có đường xoá nào trong `models.py`**, và với thư viện dùng chung thì xoá Drive
   của một người là xoá của cả team.
3. **Đếm trong hộp xổ không faceted** theo các bộ lọc đang bật (KISS có chủ ý). Sau
   backfill nên xem lại — số đúng công thức mà sai ngữ cảnh.
4. **Backfill 1 074 video cũ** chưa làm. Chúng ở trên Drive nhưng không có hàng `videos`
   ⇒ thư viện khởi đầu rỗng VÀ chống-trùng mù lịch sử. Tên file là `<video_id>.mp4` nên
   khớp 1-1, dựng lại được.
5. **Trần job/ngày** — user chốt 14/09, chưa thi công.
