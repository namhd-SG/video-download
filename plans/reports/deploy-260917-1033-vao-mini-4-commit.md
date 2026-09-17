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

---

# Chuyến 2 — 17/09 12:39

User gật thẳng trong phiên thi công lúc 12:01 (*"okie deploy nào"*), không qua trung gian.

## Lui bằng gì

```
bash deploy/rollback-on-mini.sh ../video-download-truoc-260917-123920
```

Vẫn **không đổi schema** ⇒ lui chỉ đổi file. HEAD đã lên:
`1415293d189d53d09a40c177e24af0a435ca3ebd`.

## Deploy cái gì

`780c409` lượt tải không đọc được bằng cách đếm id · `8a0975b` thư viện chỉ hiện của
mình · `28adb24`+`cd019a1` trang "Cookie của tôi" · `9119f4c` kiểm chủ mỗi nhịp trên
luồng tiến độ + sửa bố cục 3 cột · `5c4c0a1` ảnh xem trước cũng kiểm chủ.

## Bốn phép phải LẬT — và đã lật

| phép (trên mini) | trước 12:01 | sau 12:39 |
|---|---|---|
| `grep -c "_job_cua_toi_hoac_404" web/app.py` | 0 | **3** |
| `grep -c "video_nay_cua_toi" web/app.py` | 0 | **1** |
| `grep -c "me/cookie" web/app.py` | 0 | **5** |
| `grep -c "def list_videos(db_path: Path, chi_cua" web/models.py` | 0 | **1** |

Giữ nguyên đúng như phải: astronex **5**, healthz **200**, promax **302**, job/video
**4 / 10**, jar cookie **1**. `rc=0` đo trực tiếp.

## Chứng minh CHỨC NĂNG trên dữ liệu thật

```
THƯ VIỆN     admin 10/10 · người thật 10/10 · người lạ 0/0
ẢNH XEM TRƯỚC chủ True · người lạ False · admin True
HÀNG ĐỢI     admin 4 · người thật 1
trang Cookie của tôi: có trong HTML đang phục vụ
```
(Người thật thấy đủ 10 vì cả 10 video đều từ lượt tải của họ; 3 lượt `khach` cũ có
trước khi nối chỉ mục nên không sinh hàng `videos`.)

## Ngắt ai

**0 lượt tải đang chạy** lúc bấm ⇒ không ai mất việc dở. **1 địa chỉ ngoài** đang mở
trang (97/100 dòng log cuối) bị ngắt một nhịp lúc `kickstart`, F5 là xong. Cửa riêng của
lane ("có người đang dùng thì dừng, hỏi") đã báo cho user trước khi bấm; user gật đi tiếp.

## Còn hở — vẫn chưa đóng

- **Chưa ai mở bằng trình duyệt thật.** Không đăng nhập hộ được qua Cloudflare Access.
  Cần một người bấm thử — và cần **người thứ hai** dán cookie + chạy một lượt, đó là
  phép đo duy nhất chứng minh tool dùng được cho nhiều người.
- **`VIDEODL_ADMIN_EMAILS` vẫn rỗng.** Mã đọc biến đã trên máy từ chuyến 1; còn lại là
  đặt giá trị rồi `launchctl kickstart -k gui/$(id -u)/com.astronex.videodl`.
- **Nút "Loại khỏi kho" chưa làm** — user chốt loại là việc riêng (người khác vẫn tải
  được), bản đó cần đổi cấu trúc dữ liệu nên sang mai, không ép vào hôm nay.
