# Deploy 17/09 10:33 — 4 commit lên mini

Ghi ra đĩa vì **việc này không lùi được bằng cách quên đi**. Tin nhắn báo deploy lúc
10:38 đã bị nuốt (auto-mode từ chối, lý do `[Production Deploy]`) và **không bên nào
được báo** — điều phối tưởng lane im, lane tưởng đã báo, 93 phút. File thì không bị nuốt.

## Lui bằng gì

```
bash deploy/rollback-on-mini.sh ../video-download-truoc-260917-103319
```

Bản lui nằm trên mini ở `~/Projects/video-download-truoc-260917-103319`, do
`deploy-to-mini.sh` tự giữ (`rsync --backup --backup-dir`). Không đổi schema ở chuyến
này ⇒ lui chỉ là đổi file, không phải lùi dữ liệu.

## Ai gật

User, qua phiên điều phối `macos-63`, 10:20. Phạm vi được gật: **đúng 4 commit dưới
đây**, không kèm reboot, không kèm `chmod` log, không đổi gì khác trên máy đó.

## Deploy cái gì

`2e5f31e` ảnh hỏng không để lại tệp giả · `13000cc` hàng đợi chỉ thấy lượt của mình ·
`eafb2bf` docstring trần · `1c9c630` nguồn đã cạn + trần liệt kê.
HEAD lúc bấm: `e1066c31cd173e73fd3b41e38822be4d43be39d2`.

## Mốc TRƯỚC (10:23)

```
astronex labels : 5          promax hàng xóm : 302
healthz:7870    : 200        đĩa / trống     : 11Gi
job đang chạy   : 0          tổng job        : 4
is_admin        : 0          ENV_ADMIN_EMAILS: 0
app.js sha      : 6b3fcf92   list_jobs có lọc: 0
IP ngoài đang mở trang: 118.69.66.139 · 222.253.80.187
```

## Mốc SAU (10:34) — phép đo có sức phân định

`healthz 200` **không** nằm trong danh sách này: nó trả 200 cả trước lẫn sau, tức không
phân định được gì. Bốn phép dưới đây phải **lật**, và đã lật:

| phép | trước | sau |
|---|---|---|
| `grep -c "def is_admin" web/auth.py` | 0 | **1** |
| `grep -c ENV_ADMIN_EMAILS web/auth.py` | 0 | **2** |
| `shasum -a 256 web/static/app.js` | `6b3fcf92` | **`7e2c8cb2`** = dev |
| `list_jobs` có `WHERE nguoi_tao = ?` | 0 | **1** |

Không đổi (phải giữ nguyên, và đã giữ): astronex **5**, promax **302**, tổng job **4**,
`web/data/cookies/` vẫn **1 tệp**. `web/data` nằm trong `EXCLUDES` nên `--delete` không
chạm DB lẫn cookie.

`rc=0` đo trực tiếp (`rc=$?` ngay sau lệnh). Lần đầu tôi viết `| tail` rồi đọc
`${PIPESTATUS[0]}` — biến đó **không tồn tại trong zsh**, in ra `rc=` rỗng; đã bỏ pipe
và đo lại, không đọc cái rỗng đó thành gì cả.

## Chứng minh CHỨC NĂNG, không chỉ chứng minh mã đã tới

Gọi thẳng hàm đã deploy, trên máy thật, trên dữ liệu thật, chỉ đọc:

```
admin (chi_cua=None) thấy : 4 job
người thật thấy           : 1 job   (nguoi_tao trong kết quả: chỉ chính họ)
tài khoản 'khach' thấy    : 3 job
```

và dây HTTP→model trên mini: `web/app.py:208`
`models.list_jobs(DB_PATH, None if is_admin(nguoi_tao) else nguoi_tao)`.

## Còn hở — khai để không ai tưởng đã trọn

- **Chưa ai mở `/jobs` bằng trình duyệt thật.** Tôi không đăng nhập được qua Cloudflare
  Access và không mượn phiên của user để giả làm họ. Cần một người bấm thử.
- **`VIDEODL_ADMIN_EMAILS` vẫn rỗng** ⇒ chưa ai là admin. Mã đọc biến đã có trên máy từ
  chuyến này, nên thứ tự đúng còn lại là: **đặt biến → khởi động lại dịch vụ**.
- Ngắt nhịp: 0 job đang chạy lúc bấm ⇒ không ai mất việc đang tải. Hai IP ngoài đang
  *xem trang* bị ngắt một nhịp lúc `kickstart`.

## Chưa deploy — chuyến 2

6 commit của hôm nay (`780c409` → `5c4c0a1`: vá `/jobs/{id}`, thư viện riêng, trang
Cookie của tôi, kiểm chủ mỗi nhịp SSE, `/thumbs` kiểm chủ) **đã đẩy origin, chưa lên
mini**. Chờ user gật.
