---
phase: 7
title: "Thư viện creative + nối sang bộ tự tìm"
status: in-progress
priority: P1
effort: "2-3d"
dependencies: [2, 3, 5]
---

# Phase 7: Thư viện creative + nối sang bộ tự tìm

Ghi lại các quyết định user chốt trong phiên 15/09, kèm phép đo đứng sau mỗi cái.

⚠ Câu cũ ở đây — *"chưa thi công phần nào trừ lớp chụp ảnh"* — **đã sai từ chiều 15/09**:
lớp thư viện, lọc trùng, ghi nguồn và UI đều xong sau đó. Xem mục **Việc** ngay dưới để
biết cái gì xong, bằng chứng nào. Trạng thái cập nhật 15/09 18:35.

## Đã XONG trước file này

Lớp chụp ảnh + chỉ mục (`a326b1b`): bảng `videos`, ảnh cắt bằng ffmpeg tại
`on_video_verified`, endpoint `/videos` và `/thumbs/{id}`. 200 test, đột biến 6/6 ĐỎ,
đã deploy và đo trên mini.

## USER CHỐT 15/09

| # | Chốt | Phép đo / lý do |
|---|---|---|
| 1 | Bố cục: dải điều khiển trên + thư viện dưới | giữ từ 14/09 |
| 2 | **Cả team thấy hết** thư viện | một thư viện chung để không ai tải trùng |
| 3 | Ảnh lưu trên mini cạnh `jobs.db` | 2 KB/video; `thumbs/` cùng hệ thống tệp với chỗ guard đĩa đo (`dev=16777234`) |
| 4 | Ảnh cắt bằng **ffmpeg**, không dùng cover của index | 2 KB / 0,08s / phủ mọi nguồn / không hết hạn — so với 26 KB + 1 request + `x-expires` 24h + chỉ nguồn hashtag |
| 5 | **Tránh trùng ở khâu liệt kê**, duyệt sâu thêm cho đủ N cái MỚI | `download_all` chỉ bỏ qua khi file còn trên đĩa (`downloader.py:202`) mà vòng đời đã xoá ⇒ đang tải lại + upload lại; tốn lượt gọi TikTok = rủi ro khoá nick |
| 6 | Thẻ lọc **theo nguồn** (`#80ssaudi`), không theo nước | |
| 7 | Bộ lọc dạng **hộp xổ**, thêm **Ngày tải** + **Người tải** | |
| 8 | Bộ lọc thiếu dữ liệu ⇒ **luôn có ô "không rõ · N"** | tầng-2 chỉ có với nguồn hashtag; không có ô đó thì lọc âm thầm giấu video |
| 9 | Phân tích nội dung (tầng 3) **chỉ chạy cho lô đã chọn**, không tự chạy | ~16k token/ảnh qua agy |
| 10 | Giỏ = tập video đã chọn, có nút **Xoá** và **Tạo task tự tìm** | |
| 11 | "Thêm bộ tự tìm" = **dựng lại hộp thoại trong Video Desk**, KHÔNG nhảy sang Creative Desk | user: "nhảy qua bên creative desk thì nhìn bị tù quá" |
| 12 | Nhưng form phải **luôn đúng taxonomy** | ⇒ đọc sống từ API, cấm chép cứng danh sách |
| 13 | "Tìm thêm giống cái này" **giữ**, nhưng là **đề xuất cho user duyệt** | agy quét video / đọc text, hashtag, link nhạc → đề xuất → user check. Không tự chạy |

## Việc — bộ đếm đọc mục này

Viết thành checkbox vì `ak plan status` **chỉ đếm checkbox**: phase này viết bằng bảng văn
xuôi nên 6 phase kia góp 39 việc (5+6+7+6+9+6) còn phase-07 góp **0** ⇒ cả lớp thư viện
vô hình với bộ đếm. Mỗi mục đã tick phải kèm bằng chứng; tick trơn thì bỏ tick.

- [x] Lớp chụp ảnh + chỉ mục `videos`, `/videos`, `/thumbs/{id}` — `a326b1b`, đột biến 6/6 ĐỎ
- [x] `music_id` + `drive_file_id` (từ `result.file_id`) — `47e3ee1`; đột biến
      `file_id`→`drive_id` ⇒ test ĐỎ rc=1, hoàn nguyên cây sạch
- [x] `video_sightings` append-only + `ON CONFLICT DO NOTHING` — `47e3ee1`, `5a7782e`;
      không có `UPDATE`/`DELETE` nào trên bảng
- [x] Lọc trùng khâu liệt kê, duyệt sâu cho đủ N cái MỚI — `5a7782e`;
      `test_music_page_results_are_deduped_too`, `test_repeated_sightings_of_the_same_pair_collapse`
- [x] Trang thư viện + 6 hộp xổ lọc — `fa665b2`, `345374f`. ⚠ `scripts/kiem-ui.sh`
      **không phải bằng chứng đã kiểm**: nó là bảng kiểm THỦ CÔNG in ra màn hình, không
      assert gì. Đã chạy: kiểm 1 (tương phản axe + ca âm). Chưa có dấu vết chạy: kiểm 3
      (Access hết hạn), 4 (>500 video), 5 (ảnh thiếu)
- [x] Tách `app.css`/`app.js` khỏi `index.html` (1107→96 dòng) — `1d338ac`; khối CSS/JS
      byte-identical với bản gốc (sha256 khớp, ca âm +1 ký tự ⇒ khác), bản gốc và bản tách
      dựng cạnh nhau cho fingerprint DOM trùng khít.
      ⚠ **CODE XONG, CHƯA LÊN MINI** — phiên này không deploy; bản mini đo lúc 17:50 là
      bản inline, commit này 18:25. Tick này chỉ được đọc là "xong" theo nghĩa code
- [x] Trần job/ngày — `e9e5b2d`; 20 job/cookie/ngày giờ VN (user chốt 15/09 18:40, bốn
      tham số ghi ở `phase-05`). Đột biến: gỡ lời gọi khỏi route ⇒ test mối nối ĐỎ; đổi
      múi giờ VN→UTC ⇒ 2 test biên ĐỎ. 229 passed sau khi hoàn nguyên
- [ ] Nút "Xoá" — **chặn**: user chưa trả lời 4 lần hỏi
- [ ] Trần theo SỐ VIDEO (`SUM(so_luong)`) — trần job không bó được lưu lượng: 1 job xin
      tới `MAX_SO_LUONG=2000` video. Chưa chốt
- [x] Backfill video cũ — **USER HỦY 16/09**, không làm. Số thật là **4**, không phải
      1 074 (đo ở mục dưới); script `4eb28c6` chưa từng chạy vào DB sống
- [ ] Form "Thêm bộ tự tìm" đọc taxonomy sống — **chặn**: chưa chọn đường (a/b/c ở mục CHẶN)
- [ ] Copy sang Shared Drive của Creative Desk
- [ ] Phân tích nội dung tầng 3 theo lô đã chọn (chốt #9)
- [ ] "Tìm thêm giống cái này" — đề xuất chờ user duyệt (chốt #13)

⚠ Các mục *chưa* tick là việc phase này đã nêu nhưng chưa ai làm — để chúng vắng mặt thì
bộ đếm sẽ báo phase xong sớm hơn sự thật. (Không ghi số đếm ở đây: đếm tay sẽ trôi khi
thêm mục.)

## Ba tầng dữ liệu cho bộ lọc — đo được

| tầng | lấy từ đâu | có gì | giá | phủ |
|---|---|---|---|---|
| 1 | chính file mp4 | tỉ lệ khung, thời lượng thật, độ phân giải, fps, có tiếng | **0** — `verify_video_stream` đã chạy `ffmpeg -i` rồi đọc đúng 1 boolean | MỌI nguồn |
| 2 | response index | region, play_count, digg_count, author, title, create_time, **music_info.id** | **0** — response có 31 trường, code đọc 2 | CHỈ hashtag |
| 3 | nhìn nội dung | kiểu creative, hook, chữ trên hình | ~16k token/ảnh | theo lô user chọn |

## Nối sang Creative Desk — đo được 15/09

```
service account của video-download nhìn thấy đúng 1 Shared Drive:
  "Creative Astronex" (0AASy4v5CJAkfUk9PVA)
gốc có 5 thư mục: video-tool · _preview-staging · _style-catalog · Idea · Creative
canAddChildren=True trên CẢ 5, kể cả "Creative"
ca dương: đọc được thư mục của chính tool (video-tool)
```

⇒ **Copy thẳng trong Drive được**: không tải xuống, không upload lại, không đụng trần
*"tối đa 100MB mỗi file"* của hộp thoại, và **không sửa dòng nào của Creative Desk**.

⚠ **Mặt trái:** credential này ghi được vào toàn bộ Shared Drive của Creative Desk (hệ
quả tất yếu của việc là *thành viên* Shared Drive — Google không cho thu hẹp quyền thành
viên theo thư mục). Mọi lệnh ghi phải **chỉ nhận folder id do API trả về**. ⚠ Đây là
**kỷ luật code, KHÔNG phải ranh giới quyền** — bug hay rò key đều đi xuyên qua nó.

**Vai của SA — dòng thời gian, vì nó đổi GIỮA các phép đo.**

```
15:30  capabilities: canDeleteDrive=True,  canManageMembers=True   → organizer (Manager)
16:13  capabilities: canDeleteDrive=True                            → user đang mở dropdown, chưa lưu
16:14  permissions().list: fileOrganizer                            → user lưu ở đây
16:15  capabilities: canDeleteDrive=False, canManageMembers=False   → đã lan
```

⇒ **Cảnh báo ban đầu ĐÚNG**: SA ở vai **Manager**, xoá được Shared Drive và đổi được
thành viên. User đọc phát hiện đó rồi **tự hạ xuống Content manager (`fileOrganizer`)**
lúc ~16:14. Trạng thái hiện tại là **đúng mức cần có** — không còn việc phải làm.

⚠ **Hai lỗi của người viết file này, ghi lại vì lỗi thứ hai nguy hiểm hơn lỗi thứ nhất:**
1. Lúc 16:13 thấy màn hình user (Content manager) ngược với phép đo (Manager), tôi kết
   luận **dụng cụ sai** và đã commit một bản "đính chính" nói SA chưa bao giờ là Manager.
2. Sự thật là **trạng thái đổi giữa hai phép đo** — điều lẽ ra phải là giả thuyết ĐẦU
   TIÊN, vì tôi vừa đưa phát hiện cho một người và người đó nói sẽ vào xem.

Bài học dùng được: hai phép đo lệch nhau trên một hệ **đang có người tác động** thì hỏi
*"trạng thái có đổi không"* trước khi hỏi *"dụng cụ có hỏng không"*. Và mọi phép đo về
quyền phải **ghi kèm giờ**, vì quyền là thứ người ta sửa.

Ghi chú kỹ thuật vẫn đúng: `permissions().list` cho **vai** (`fileOrganizer` = Content
manager); `drives().get(capabilities)` cho **những gì làm được lúc này**. Hai câu hỏi
khác nhau, và capabilities lan chậm hơn ACL vài phút.

Vẫn đáng ghi, độc lập với vai: SA này là **của Creative Desk dùng lại**, key nằm trên
mini — máy có tài khoản thứ hai. Đó là lý do riêng để cân nhắc một SA riêng.

Hình dạng một bộ tự tìm (`SelfBundleCreate`): `category` · `title` · `usecase` ·
`insight` · `template` · `quantity` → trả về `drive_folder_url` + `order` (mã `N.2307`).

## CHẶN — chưa giải, cần user quyết

**Form trong Video Desk phải đọc taxonomy sống, nhưng `GET /creative-taxonomy/categories`
và `/tree` đòi `UserRecord`/`AuthUser` — phiên đăng nhập của meta-auto.** Video Desk là
service khác, hostname khác, không có phiên đó.

| đường | giá |
|---|---|
| a. token máy cho Video Desk | meta-auto có `is_mcp`; phải cấp + giữ một token dài hạn có quyền vào API đội khác |
| b. trình duyệt gọi thẳng meta-auto | cần CORS cho `video.nobidigital.asia`; dữ liệu lấy đúng quyền của chính user |
| c. đồng bộ định kỳ | **loại** — lệch âm thầm, trái chốt #12 |

Khuyến nghị: **(b)** — ít mã hơn, không phải giữ token dài hạn, quyền đúng người dùng.

## Còn treo, chưa có đáp

1. **Nút "Xoá" xoá gì** — hỏi **4 lần** chưa có đáp. Hai nghĩa: xoá *giỏ* (video còn
   nguyên) hay xoá *video trên Drive* (khó lui, cần xác nhận). Thư viện dùng chung ⇒ xoá
   Drive của một người là xoá của cả team. Chưa có đường xoá nào trong `models.py`.
2. **Trần theo số VIDEO** — trần job đã thi công (`e9e5b2d`) nhưng đếm *job*, mà một job
   xin tới 2000 video ⇒ 20 job vẫn là 40 000 video/ngày. Bó lưu lượng thật cần trần trên
   `SUM(so_luong)`. Chưa hỏi user.

### Ba mục từng nằm ở đây — ĐÃ XONG, kiểm lại ở HEAD 15/09 18:30

Ghi lại vì file này đứng "chưa làm" vài giờ sau khi chúng xong; người thứ ba đọc sẽ đi
làm lại. Bằng chứng đo ở **HEAD hiện tại**, không phải "đã từng commit".

- **Id từng video** — cột `drive_file_id` (`models.py:53-54`), ghi từ
  `result.file_id` (`lifecycle.py:361`). ⚠ **`file_id` chứ không phải `drive_id`**: cái
  sau là id Shared Drive, giống hệt nhau cho mọi file ⇒ mọi thẻ sẽ trỏ về cùng một chỗ.
  Đột biến đổi `file_id`→`drive_id` ⇒ `test_drive_file_id_is_the_file_not_the_shared_drive`
  **ĐỎ (rc=1)**; hoàn nguyên, `git status --porcelain` rỗng, 220 passed. (`47e3ee1`)
- **Một video ở hai nguồn** — `INSERT OR REPLACE` đã thay bằng
  `ON CONFLICT(video_id) DO NOTHING` (`models.py:280`) + bảng `video_sightings`
  (`models.py:73`) append-only: `grep` không thấy `UPDATE`/`DELETE` nào trên bảng đó.
  (`47e3ee1`, `5a7782e`)
- **`music_info.id`** — cột `music_id` (`models.py:53`), có migration cho `jobs.db` cũ
  (`models.py:149-152`). (`47e3ee1`)

## Ba thứ "chờ thì mất vĩnh viễn"

Ghi riêng vì chúng khác mọi việc khác trong file này: hoãn không làm chúng rẻ đi.

- ảnh thumbnail — **ĐÃ XONG** `a326b1b`
- `music_info.id` — **ĐÃ XONG** `47e3ee1` (cột `music_id`, `models.py:53`)
- quan hệ video↔nguồn (nhiều-nhiều) — **ĐÃ XONG** `47e3ee1`+`5a7782e` (`video_sightings`,
  append-only, `models.py:73`)

⇒ Cả ba đã chụp. Video tải TRƯỚC mốc chỉ mục thì không có hàng — nhưng số lượng KHÔNG
phải 1 074.

## Con số 1 074 là SAI — đo được 16/09 là **4**. Đừng để nó sống lại.

`[ĐO 16/09 11:20]` Nó đi qua **ba lần bàn giao** mà chưa ai đếm, rồi được đem trình user
như một việc lớn. Đếm tại nguồn:

```
jobs.db sống trên mini : jobs=4 · videos=10 · video_sightings=10 · SUM(tong)=14
Drive, thư mục của tool: job-1 → 3 mp4 · job-2 → 1 · job-4 → 10  = 14 mp4
                         (không có tệp <id>.mp4 rời nào ở gốc)
chênh lệch             : 14 − 10 = 4
```

Lời giải khớp **từng** con số — đây mới là phần làm nó thành kết luận chứ không phải nghi
ngờ: lớp chỉ mục `a326b1b` lên **15/09 14:25**; `job-1`(3) + `job-2`(1) chạy 14/09, trước
mốc ⇒ 4 video không có hàng; `job-4` chạy 16/09, sau mốc ⇒ đủ 10. `job-3` có `tong=0` nên
không sinh thư mục Drive ⇒ khớp đúng việc chỉ thấy **3** thư mục.

**USER HỦY backfill 16/09** (*"không, bỏ đi, lấy cái mới thôi"*). 4 video đó để nguyên
không có bản ghi: file vẫn trên Drive, chỉ không hiện trong thư viện. Từ 15/09 14:25 trở
đi lớp chỉ mục ghi đủ nên **ca này không sinh thêm**.

Script `scripts/backfill-videos-from-drive.py` (commit `4eb28c6`) **chưa từng chạy vào DB
sống** — chỉ chạy trên bản sao, bản sao đã xoá, DB sống vẫn 10 videos/10 sightings. Ai đọc
file này về sau: **đừng chạy nó** vì thấy có việc treo; không còn việc nào.

Ghi thêm, độc lập với việc trên: `music_id` của video cũ `[SUY RA, chưa đo]` không dựng
lại được — nó chỉ có ở response index (tầng 2), mà index không trả lại danh sách đã tải.

Index chỉ trả video *hiện tại* của một hashtag, không trả lại danh sách ta đã tải. Video
tải xong mà chưa chụp ba thứ trên thì không có đường lấy lại.
