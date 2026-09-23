# Brainstorm — UI cookie: biết tài khoản nào, nhìn là biết trạng thái, mở đường nhiều nền tảng

Lane V `0460ddfc` · 23/09 · nền: `baseline/baseline.md` (đo 10:25) · mock: `mock-cookie-ui.html` + `mock/*.png`.

## 0. Quyết định user đang áp

**USER CHỐT 23/09 10:33 — Q4 = C** (nguyên văn *"C đi"*), qua điều phối `577b340e` (pane điều phối). **Đảo có ý thức**
quyết định 21/09 11:31 (`plans/260921-1112-videodl-3-van-de/brainstorm.md:221`, "bản OFFLINE, không hiện tên").
Lý do đổi: (1) đo 23/09 — cookie **có** mang offline một định danh số 19 chữ số (`multi_sids`) — điều 21/09 không ai biết.
⚠ 2 jar đo được là của **2 người dán** và ra 2 số khác nhau: CHƯA phân định *"2 tài khoản"* với *"số đổi theo phiên"*; (2) C **không** thêm request TikTok nào — đọc kè trang mà job vốn đã mở.

C = đọc `@username` từ HTML trang TikTok **trong lượt tải có cookie**, 0 request thêm, không trừ trần.
Hệ quả phải hiện trên UI: **lúc dán chưa biết tên** ⇒ ô tài khoản ghi *"sẽ xác định sau lượt tải đầu"*, không trống, không đoán.

## 1. Câu mở — bốn mã, HAI chỗ hiện (baseline)

Không mã nào thiếu nhánh UI. Nhưng `PUT /me/cookie` kiểm **trước** khi ghi ⇒ jar hỏng không bao giờ được lưu ⇒
- **khối trạng thái** (cookie đang dùng) chỉ gặp tự nhiên: *chưa có* · *dùng được* · *hết hạn* (dán lúc còn hạn, hết sau);
- **ba mã còn lại** (không đọc được · rỗng · chưa đăng nhập) chỉ là **phản hồi lúc dán**.

⇒ Thiết kế tách hai thứ: **thẻ trạng thái** (cái đang chạy) và **phản hồi dán** (cái vừa gửi). Hôm nay chúng
trộn một chỗ: dán hỏng khi đang có jar tốt thì chỉ hiện dòng đỏ ở cuối panel, không nói *"cookie cũ vẫn đang dùng"*.

## 2. Hàng đầu — nhãn sai chiều

| hôm nay | vì sao sai | đổi thành |
|---|---|---|
| jar hỏng ⇒ **"Hạn đến: Không có hạn"** | đọc như *tốt mãi*, thật là *không đọc được hạn* | *"Không đọc được hạn"* (jar hỏng) / *"Phiên không ghi hạn"* (cookie phiên `expires=0`) |
| 4 lỗi chung chip **"Cần dán lại"** | phân biệt dồn hết vào dòng chữ nhỏ | thẻ trạng thái có **tiêu đề riêng** mỗi trạng thái + màu + một câu cách chữa |
| dòng lỗi dưới hướng dẫn, xa nút Lưu | người ta nhìn nút vừa bấm | phản hồi dán nằm **ngay dưới nút Lưu** |
| chip **"Chưa có"** sau khi dán hỏng | đúng nhưng không nói vừa có gì xảy ra | *"Cookie vừa dán bị từ chối — …"* + trạng thái jar cũ nguyên vẹn |

## 3. (a) Tài khoản nào — cơ chế C

**Đo 23/09 (chỉ đếm):** trên mini 10 job = search 4 · music 3 · hashtag 3.
⚠ **SỬA 10:50** — bản trước ghi *"hashtag không dùng cookie"*: **SAI** (điều phối R bắt). Cookie đi vào **cả hai** bước:
- **Liệt kê:** chỉ music/search/profile mở trình duyệt có cookie (`scraper.py:430-436`). Hashtag liệt kê không cookie (`queue.py:240`).
- **Tải:** MỌI job, kể cả hashtag: `queue.py:428 download_all(…, cookies_path)` → yt-dlp `cookiefile` (`downloader.py:70-73`)
  → `extract_info` (`:150-151`). yt-dlp 2026.08.19 tự tải HTML trang video bằng cookie (`yt_dlp/extractor/tiktok.py:280`) và
  đọc đúng khối `__UNIVERSAL_DATA_FOR_REHYDRATION__` (`:115-119`). Nhưng HTML **ở trong yt-dlp**; code mình chỉ nhận info dict,
  mà `uploader` trong đó (`:663`) là **tác giả video**, không phải người xem — đúng bẫy *Hỏng 1*.
⇒ Điểm đọc hôm nay chỉ có ở **bước liệt kê music/search/profile**. Muốn job hashtag cũng có tên thì phải móc vào nội bộ yt-dlp
(bọc `_download_webpage_handle`), vẫn 0 request thêm nhưng **gãy theo mỗi bản yt-dlp** — đánh đổi độ bền, chưa chọn.

Luồng: `goto` xong (đã có sẵn) ⇒ `page.evaluate` đọc khối JSON nhúng ⇒ lấy **đúng** trường người-đang-xem ⇒ ghi
vào bảng danh tính, khoá theo jar ⇒ trang Cài đặt đọc bảng đó. Không đọc được ⇒ ghi trạng thái *"không đọc được
tên"*, không đoán.

**CHƯA ĐO (ii):** trang đã đăng nhập có nhúng `@uniqueId` người xem không, ở trường nào, và có còn khi
`wait_until="domcontentloaded"` + headless. Đo trên **jar của chính user trong một job thật kế tiếp** (kè, không
thêm request) — xin user qua điều phối trước khi thi công phần đọc. `DECISIONS.md:179` chỉ chứng minh khối đó tồn
tại trên trang video **không** đăng nhập.

**ĐỀ XUẤT (không trong phạm vi user chọn, chờ duyệt):** dùng số 19 chữ số trong `multi_sids` làm **khoá nội bộ**
(không hiển thị) thay vì vân tay jar. Lý do (**GIẢ ĐỊNH, chưa đo** — điều phối R gật có điều kiện: đo 1 tài khoản xuất 2 lần trước khi ghi code): xuất lại cookie
**cùng tài khoản** đổi vân tay (nội dung khác) nhưng giữ số ⇒ tên đã xác định không bị mất mỗi lần dán lại; dán cookie **khác tài khoản** thì số đổi ⇒ tên cũ bị gỡ ngay,
không chờ job. Khoá theo vân tay thì cả hai ca đều về *"chưa xác định"*. Đọc offline, 0 request.

## 4. (b) Mô hình `platform`

- Mã hoá nền tảng thành một hằng: `NEN_TANG = {"tiktok": {...}}` — tên hiển thị, tên cookie đăng nhập
  (`COOKIE_DANG_NHAP` hôm nay), miền, hàm đọc danh tính. `COOKIE_DANG_NHAP` chuyển vào mục `tiktok`.
- Jar: `<sha256(email)>.json` → `<sha256(email)>.<nen_tang>.json`. **Đổi tên jar thật trên mini = di trú**:
  đọc tên cũ làm dự phòng cho `tiktok`, không đổi tên tệp đang chạy. Chỉ thêm tên mới cho nền tảng mới.
- API: `GET/PUT/DELETE /me/cookie` giữ nguyên (= tiktok) để không vỡ trang cũ trong cache; thêm
  `/me/cookie/{nen_tang}` khi có nền tảng thứ hai. **Không thi công** phần thứ hai lúc này.
- Bảng danh tính có cột `nen_tang` ngay từ đầu (rẻ bây giờ, đắt khi di trú sau).
- Trang: mỗi nền tảng một **thẻ**; hôm nay một thẻ TikTok. Mock có một thẻ mờ "Instagram — chưa hỗ trợ" chỉ để
  thấy bố cục chứa được — **câu hỏi mở** có đưa nó lên trang thật không (mặc định: không).

## 5. (c) Thẻ TikTok — nhìn là biết

Một khối **trạng thái lớn** (màu + tiêu đề + một câu), bên dưới lưới 4 ô: **Tài khoản** · **Hạn đến** · **Dán lúc** ·
**Vân tay**. Năm trạng thái của khối (mock vẽ đủ):

| trạng thái | tiêu đề | màu |
|---|---|---|
| chưa có | *Chưa có cookie — lượt tải đang chạy ẩn danh, chung hạn mức* | trung tính |
| dùng được, chưa biết tên | *Đang dùng được* · Tài khoản: *sẽ xác định sau lượt tải đầu* | xanh |
| dùng được, đã biết tên | *Đang dùng được* · Tài khoản: **@xxx** (xác định lúc …) | xanh |
| hết hạn | *Cookie đã hết hạn ngày …* — đăng nhập lại rồi xuất lại | đỏ |
| không đọc được tên | *Đang dùng được* · Tài khoản: *không đọc được tên từ TikTok* | xanh, ô tài khoản vàng |

Phản hồi dán: ngay dưới nút Lưu; từ chối ⇒ đỏ + cách chữa + *"cookie cũ (@xxx) vẫn đang dùng"* nếu có jar.

## 6. Điểm mù + hình dạng hỏng

**Hỏng 1 — TÊN SAI, IM LẶNG (đắt nhất).** Trang `/@nguoi-khac` nhúng cả thông tin **chủ trang** lẫn **người xem**.
Đọc nhầm trường ⇒ UI khẳng định sai *"cookie của @nguoi-khac"* — đúng lớp *nhãn tự tin sai*. Chặn: chỉ đọc trường
người-xem; test bắt buộc có fixture trang profile mà **chủ trang ≠ người xem**, và đột biến đổi trường phải ĐỎ.
**Hỏng 2 — TÊN CŨ SỐNG SAU KHI ĐỔI COOKIE.** Dán cookie tài khoản khác, ô vẫn ghi tên cũ tới job sau. Chặn: `PUT`
gỡ danh tính khi khoá jar đổi (xem đề xuất khoá số ở §3). Test: dán jar B sau jar A ⇒ ô về *"sẽ xác định"*.
**Hỏng 3 — KHÔNG BAO GIỜ ĐIỀN.** Người chỉ chạy hashtag (nếu chỉ đọc ở bước liệt kê — §3), hoặc HTML không có trường. Chặn: trạng thái riêng, câu chữ
nói lý do; không để *"sẽ xác định"* treo mãi mà không giải thích.

**Điểm mù:** (ii) chưa đo · đánh đổi 21/09 vế (2) *"kéo danh tính TikTok vào máy dùng chung"* **vẫn còn** với C
(tên lưu trong DB mini) — user chọn C với điều đó; điều phối xác nhận user đã thấy vế này · chưa kiểm dark mode /
điện thoại của mock · ngưỡng *"sắp hết hạn"* **không** đặt (không có số để hiệu chỉnh — không bịa hằng).

## 7. Thứ tự thi công (sau khi mock duyệt)

1. Nhãn + bố cục + phản hồi dán (chỉ frontend + `het_han` phân biệt *không đọc được* vs *không ghi hạn*). Lùi rẻ.
2. Mô hình `nen_tang` + bảng danh tính (backend, chưa đọc TikTok). Có migration ⇒ sao lưu DB trước.
3. Đo (ii) trên job thật của user ⇒ rồi mới viết phần đọc kè + test hỏng 1/2/3.

## Câu hỏi — điều phối R trả 10:47
1. Khoá theo `multi_sids`: **GẬT có điều kiện** — đo 1 tài khoản xuất 2 lần giữ số trước khi ghi code; vân tay vẫn hiện.
2. Thẻ "chưa hỗ trợ": **KHÔNG** lên trang thật ở PR này; giữ trong mock.
3. Vế *"tên TikTok lưu trên máy dùng chung"*: user **chưa thấy** — R trình cùng vế hashtag.
4. MỞ: đọc tên ở bước tải (móc yt-dlp, gãy theo phiên bản) hay chỉ ở bước liệt kê.
