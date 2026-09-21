# Review 3 commit `fix/log-path-and-name-list` — 21/09/2026

## 0. Phạm vi ĐÃ LỆCH so với đề bài — đọc trước

Đề bài giao `e99e730~1..HEAD` với `HEAD = 8b72c93` (3 commit). **Giữa lúc review, cây
nhảy sang `f102452`** (commit thứ 4, `fix(queue): stop warning about a database that was
never configured`). Đo được:

```
lúc bắt đầu : git rev-parse --short HEAD -> 8b72c93   (345 passed)
lúc đang đo : git rev-parse --short HEAD -> f102452   (346 passed)
git status --porcelain -> rỗng ở cả hai thời điểm
```

`f102452` **đã vá đúng 2 trong số các lỗ tôi đang viết**:

| lỗ | trạng thái |
|---|---|
| `_note_pages` thiếu cửa `db_path is None` (khác hẳn `_note_skip`/`_note_stop`) ⇒ ~1 dòng WARNING/lời-gọi-feed trên đường CLI/GUI | ĐÃ VÁ (`web/queue.py:164-176`) |
| `i + 1` ở dòng log cuối `scrape_music_page_multi` khai dư một lượt chưa từng cào (ca trần-thời-gian cắt trước khi `scrape_music_page` chạy) | ĐÃ VÁ (`da_cao`, `scraper.py:525-528, 566, 626-627`) |

Báo cáo dưới đây soi **`e99e730~1..f102452`**. Con số nghiệm thu: `346 passed`, `rc=0`
(đo không pipe, `rc=$?` ngay sau lệnh).

**Bẫy phép đo đã dẫm và đã sửa — ghi lại để người sau khỏi dẫm:** vá `src/` trong một bản
sao rồi chạy pytest ở đó **KHÔNG có tác dụng** — `tiktok_music_downloader` cài editable, trỏ
thẳng về `/Users/macos/Projects/video-download/src`. Vòng đột biến đầu của tôi báo "sống"
cho 2 đột biến mà thật ra chưa bao giờ được áp. Phải `PYTHONPATH=<bản-sao>/src` mới che được;
kiểm bằng `python -c "import tiktok_music_downloader.scraper as s; print(s.__file__)"`.
(`web/` thì che được ngay vì nó resolve theo cwd.) Control của bộ đột biến hợp lệ:
`--ignore=tests/test_lifecycle.py` (2 test đó cần `assets/ffmpeg-static`, không copy) ⇒
**283 passed, rc=0**.

---

## 1. CRITICAL — trần video/ngày giờ trừ theo SỐ XIN, vĩnh viễn; lật một quyết định đã khai

### Ca hỏng (đo được, không suy diễn)

```
2 job, mỗi job user xin 500, thực tế mỗi job chỉ tìm được 1 video mới
HÀNH VI MỚI  — trần video đã tiêu: 1000   (thực tải: 2 video)
   job thứ 3 xin 10 video -> 'cookie này đã lấy 1000/1000 video trong hôm nay …
                              Còn lại hôm nay: 0 video.'
HÀNH VI CŨ   — trần video đã tiêu: 2
   job thứ 3 xin 10 video -> None
```

### Cơ chế

- `e99e730` đổi `set_job_total` → `set_job_found`: `web/models.py:542-547` giờ ghi vào
  `tim_thay`, **không đụng `tong`**; `web/queue.py:395` gọi nó.
- `web/models.py:405-418` `sum_videos_since_by_creator` vẫn `SUM(tong)`.
- `web/lifecycle.py:381-386` là cổng chặn: `spent + so_luong > max_videos_per_day` ⇒ 429.

### Vì sao đây là CRITICAL chứ không phải "đánh đổi của bản vá"

`web/lifecycle.py:316-326` **khai thẳng cơ chế vừa bị gỡ như phần chịu lực**:

> `trần VIDEO dùng SUM(tong)` ⇒ đúng 2 job đó **tính 0 video**, vì `process_job` ghi đè
> `tong` bằng số ref THẬT sau khi lọc trùng. […] Giữ như vậy **có chủ đích**: xin 2000 mà
> nhận 3 rồi bị trừ 2000 là **phạt người dùng vì thứ họ không điều khiển được**.

Và `web/models.py:398-404` (`count_jobs_since_by_creator`) ghi *"`already_owned` KHÔNG tính:
người dùng không làm gì sai khi quét một hashtag team đã tải hết (**user chốt 16/09**)"*.

⇒ Kết cục hiện tại: **đúng ca `already_owned` được miễn trần JOB thì nay bị trần VIDEO phạt
nặng nhất.** Hai cổng nói ngược nhau về cùng một ca, và vế nói ngược là vế mới.
`web/models.py:410-413` (docstring `sum_videos_since_by_creator`: *"Sums `tong`, which is the
requested count **until `process_job` replaces it**…"*) nay là một câu **SAI**.

### Vì sao không test nào đỏ

Đột biến M10 (cho `set_job_found` ghi đè cả `tong`, tức trả về hành vi cũ) ⇒ **1 failed**
(`test_process_job_with_zero_refs_keeps_the_number_the_user_asked_for`). Tức bộ test canh
đúng chiều *"đừng đè `tong`"* và **không có test nào canh chiều còn lại** — hệ quả của việc
đè lên kế toán hạn mức. Cổng hạn mức và cột `tong` chưa bao giờ được đo chung.

### Khuyến nghị — đây là QUYẾT ĐỊNH CỦA USER, không tự chọn hộ

Trình cả ba, để user chốt (`review-audit-self-decision.md`):

1. Trần video đọc `COALESCE(NULLIF(tim_thay,0), tong)` — job xong thì tính số thật, job
   đang chạy tính số xin. Giữ nguyên tinh thần 16/09, thêm một nhánh `COALESCE`.
2. Giữ nguyên hiện trạng và **khai lại** quyết định 16/09 là đã đổi (phải sửa cả hai
   docstring `lifecycle.py:316-326` và `models.py:410-413`, nếu không chúng là bẫy cho lane sau).
3. Tách hẳn một cột `da_tai` do `_JobProgress` ghi, trần video đọc cột đó.

Kèm test đột biến hai chiều: đổi cột mà cổng đọc ⇒ phải ĐỎ.

---

## 2. HIGH — "đào sâu" KHÔNG đào sâu: độ sâu mỗi lượt vẫn đúng bằng `max_videos`

### Ca hỏng (mô phỏng chạy thật trên `scrape_music_page_multi`, không phải đọc code)

```
trang music có 100 video, thứ tự ổn định; thư viện đã có 5 video ĐẦU; user xin 5
số lượt cào thật : 2
video MỚI trả về : []
mã dừng          : already_owned
sự thật          : trang còn 95 video (v005..v099) chưa ai có
```

`already_owned` là mã bảo người dùng **"ĐỔI NGUỒN, chạy lại chắc chắn vô ích"**
(`web/static/app.js` + `utils.py:244-245`). Câu đó **SAI** ở ca này. Đúng lớp lỗi mà cả bộ
mã dừng sinh ra để chặn — chỉ là lần này nó nói sai theo hướng ngược lại.

### Cơ chế

- `src/tiktok_music_downloader/scraper.py:329`
  `if len(seen) >= max_videos: log.info("reached --max=%d, stopping scroll"); break`
  ⇒ `_auto_scroll` **ngừng cuộn ngay khi gom đủ `max_videos`**.
- `src/tiktok_music_downloader/scraper.py:553`
  `batch = scrape_music_page(music_url, max_videos=max_videos, **kwargs)`
  ⇒ **mọi lượt đều xin cùng một `max_videos`**, không ai nâng nó theo `bo_qua`.

⇒ Lượt 2..5 quét **lại đúng cửa sổ cũ**, không phải quét sâu hơn. Tập ứng viên cả lượt chạy
bị chặn trong "top `max_videos` qua ≤5 lần render", không bao giờ với tới vị trí
`max_videos + k`.

Đối chiếu nhánh hashtag — nơi docstring nói là đang chép nguyên tắc: `enumerate_hashtag`
**dời con trỏ trang** (`_PAGE_SIZE`, `max_pages`), nên nó đào thật. Nhánh này thì không.

### Cái CHƯA ĐO

Docstring `scrape_music_page_multi` nói trang music render *"a randomized ~30-60 video
slice per visit"*. Nếu TikTok xáo đủ mạnh thì lượt sau **có thể** rơi vào video sâu hơn. Tôi
**không đo được mức xáo đó** (cần chạy thật, có mạng). Mô phỏng trên là ca xấu nhất (thứ tự
ổn định) và nó là ca thực tế khi `max_videos` nhỏ. ⇒ **Đừng đọc số "0 video" của tôi thành
số của production**; thứ chắc chắn là **cơ chế**: độ sâu không đổi giữa các lượt.

### Khuyến nghị

Nâng `max_videos` truyền xuống theo số đã bỏ, ví dụ
`scrape_music_page(music_url, max_videos=max_videos + bo_qua, **kwargs)`; và nếu giữ nguyên
thì **phải đổi lời của `already_owned`** cho nhánh này, vì mã đó hiện khẳng định một thứ
công cụ không có cơ sở để biết.

---

## 3. HIGH — PHANTOM TEST: điểm nối duy nhất của bộ đếm trang KHÔNG có test nào canh

### Phép đo

| | kết quả |
|---|---|
| CONTROL (không vá) | **283 passed, rc=0** |
| **M1**: xoá đúng hai dòng gọi `dem_trang()` trong `_watch_feed_api` (`scraper.py:210-211`) | **283 passed, rc=0** — SỐNG |

Đối chứng cùng bộ: M5/M6/M7/M8 (các đột biến mà chính docstring test khai) đều **ĐỎ**, nên
harness có sức phân định; riêng M1 lọt.

### Vì sao lọt

Hai test "phủ" nó đều **tự gọi `dem_trang()` từ scraper giả**:

- `tests/test_web_queue.py:1416-1423` (`test_so_trang_ghi_TANG_DAN…`)
- `tests/test_web_queue.py:1507-1510` (`test_khong_co_db_thi_dem_trang_IM_LANG…`)

Chúng đo **mọi thứ ở hạ lưu** điểm gọi (`_dem_mot_trang` → `_note_pages` → `set_job_pages`,
ghi tăng dần, cửa `db_path is None`) và **không đo điểm gọi**. Đúng mẫu
*"đo đúng cái máy"*: `queue → multi → page` được nối thật, còn `page → _watch_feed_api →
dem_trang` thì chưa ai chạm.

### Hậu quả nếu nó hồi quy

`so_trang = 0` trở lại cho music/search/profile — tức **đúng trạng thái mà commit `8b72c93`
nói là đang chữa** (*"Until 21/09 it paid NOTHING … The cap was not loose here, it was
blind"*). Và trần trang là **thứ duy nhất còn bó** những job được miễn trần JOB vì
`already_owned` (`web/lifecycle.py:369-374`, `models.py:398-404`). Lỗ này hỏng **âm thầm**:
không exception, không test đỏ, chỉ là một cột về 0.

### Khuyến nghị (rẻ)

`tests/test_feed_watch.py` đã có sẵn `FakeResponse`/`FakePage` và helper `_fire` (dòng 67-71)
gọi `_watch_feed_api(page)` **không truyền `dem_trang`**. Thêm một test bắn `FakeResponse`
2xx GET vào `_watch_feed_api(page, dem_trang=đếm)` và khẳng định `đếm == 1`; kèm ca âm:
HTTP 302 / method POST ⇒ `đếm == 0` (nhánh `scraper.py:203-206`). Nghiệm thu bằng M1 phải ĐỎ.

---

## 4. MEDIUM

### 4.1 `tim_thay` là cột CHỈ-GHI — người dùng không bao giờ thấy nó

- Ghi: `web/queue.py:395`.
- Đọc: **chỉ test** (`tests/test_web_queue.py:512, 902`).
- Nó có đi ra API (`models.py:440, 444` dùng `SELECT *`), nhưng
  `web/static/app.js:290` vẫn in `${job.xong}/${job.tong}`.

Commit message của `e99e730` nói *"The count actually found now lands in `tim_thay`"* — như
một lời hứa rằng thông tin bị `set_job_total` xoá mất nay được giữ. Nó **được giữ trong DB**
nhưng **không tới mắt ai**. Người dùng đọc "Xong · 3/50" vẫn phải đoán 47 kia đi đâu; chỉ có
`ly_do_dung` đỡ được một phần (và chỉ khi có mã).

Đột biến M13 (ghi hằng `0` thay vì `tim_thay`) ⇒ 1 failed — tức test canh được giá trị, nhưng
không có gì canh việc nó được **hiển thị**.

### 4.2 Trần 5 vòng / 10 phút phần lớn không với tới được, vì `min_new_rate` chặn trước

`scraper.py:469` `min_new_rate: float = 0.30`; `web/queue.py:207-219` **không truyền** tham số
này. `rate` tính trên `fresh` = "chưa thấy ở LƯỢT CHẠY NÀY" (`scraper.py:568-570`), nên nguồn
lặp lại chính nó ⇒ lượt 2 có `rate ≈ 0` ⇒ `stalled` ⇒ dừng.

Trong mô phỏng §2: **dừng ở lượt 2**, không chạm 5 vòng, không chạm 600s.

Không đề xuất đổi con số nào (đã chốt, ngoài phạm vi). Nêu vì: **hằng số user chốt 21/09 và
hằng số cũ `0.30` đánh nhau, và cái cũ thắng trong ca thường gặp nhất** — nếu user hình dung
"10 phút đào" thì hình dung đó lệch với hành vi thật. Ít nhất nên ghi tương tác này vào khối
comment ở `web/queue.py:38-50`, nơi hiện chỉ giải thích 600s và 5 vòng.

### 4.3 Cửa sổ "job không huỷ được" giãn từ ~1 lượt lên tới ~10 phút

- `web/models.py:527-529`: `huy_job_dang_cho` chỉ khớp `trang_thai = 'pending'` ⇒ job **đang
  chạy thì không rút được** (trả `"dang_chay"`).
- `web/queue.py` không có điểm kiểm huỷ nào bên trong `_fetch_refs` (grep `cancel|huy|stop_event`
  ⇒ không có).
- `web/queue.py:1-6`: **một worker duy nhất**, tuần tự.

⇒ Một job music/search/profile nay giữ hàng đợi tới `600s` + tối đa 4 giấc `time.sleep(60..180)`.
Cơ chế có sẵn từ trước, **bản vá này khuếch đại nó**. CHƯA ĐO: thời lượng job thật trên máy mini.

---

## 5. LOW

### 5.1 Hai bên dùng file mới tách ra phòng thủ KHÁC nhau

- `web/static/app.js:844`: `(window.MA_COOKIE_TRANG_THAI || {})[tt.trang_thai]` — có lưới.
- `web/static/settings.js:11`: `const MA_COOKIE = window.MA_COOKIE_TRANG_THAI;` — **không có**.

`cookie-status-text.js` không nạp được (HTML cũ còn trong cache sau deploy, file không lên
được đĩa) ⇒ trang chính suy biến êm, trang Cài đặt ném `TypeError` ở `MA_COOKIE[tt.trang_thai]`
và **mất cả bảng trạng thái cookie** — đúng trang người dùng vào để chữa cookie.

Hai file HTML còn tham chiếu khác nhau (`index.html:121` tương đối, `settings.html:120`
tuyệt đối); cả hai đều giải về `/cookie-status-text.js` và `app.mount("/", StaticFiles(...))`
tại `web/app.py:783` phục vụ được — không phải lỗi, chỉ là không nhất quán.

### 5.2 `.stat()` trần ngay cạnh một `_van_tay_jar` có bắt `OSError`

`web/app.py:363-364` gọi `Path(duong_dan).stat()` **không bọc**, trong khi `_van_tay_jar`
(`web/app.py:377-380`) bắt `OSError` và trả `None`. Jar biến mất giữa `cookies_path_for_user`
và `.stat()` (user bấm `DELETE /me/cookie` ở tab khác) ⇒ `GET /me/cookie` **500**. Lời hứa
trong docstring `_van_tay_jar` (*"trang Cài đặt phải hiện được trạng thái của một jar hỏng"*)
đúng cho **nội dung hỏng**, không đúng cho **tệp biến mất**.

### 5.3 `gia_lap_scraper` vá `time` TOÀN TIẾN TRÌNH, không phải của riêng module

`tests/test_web_queue.py:48` `monkeypatch.setattr(scraper_mod.time, "sleep", …)` —
`scraper_mod.time` **chính là** module `time` của stdlib, nên đây là vá toàn cục
(và `test_tran_thoi_gian_cat_luot_chay…:1472` làm tương tự với `time.monotonic`).
`monkeypatch` gỡ lại sau test nên hôm nay không sao; chạy song song (`pytest-xdist`) thì đây
là nguồn lỗi chéo rất khó truy. Muốn cục bộ thì vá `scraper_mod` chứ không vá `scraper_mod.time`
(cần `from time import sleep` phía nguồn) — hoặc cứ giữ và **ghi cảnh báo "đừng bật xdist"**.

### 5.4 Khoá lọc trùng đổi từ `VideoRef` đầy đủ sang `video_id` — hợp đồng GUI đổi ngầm

Cũ: `all_refs: set[VideoRef]`. Mới: `moi: dict[str, VideoRef]` (`scraper.py:521`), khoá
`video_id`. Với `gui.py:759` (`already_have=None`) thì:

- hai ref cùng `video_id` khác metadata: cũ tính **2** về `max_videos`, mới tính **1**;
- metadata **gặp lần đầu thắng**, lượt sau giàu hơn bị bỏ;
- `rate` cũng đổi mẫu: id lặp với metadata mới **không còn tính là "novel"** ⇒ `stalled`
  sớm hơn một nhịp.

Thực tế ít cắn: `VideoRef` có 7 ô metadata (`utils.py:84-95`) mà **đường Playwright để trống
hết** (`parse_video_url` chỉ dựng `video_id` + `url`), nên hai khoá trùng nhau trên đúng
đường GUI. Nêu vì commit message khẳng định *"phải trả về ĐÚNG như trước, kể cả thứ tự"* —
thứ tự thì đúng, **khoá thì không**.

---

## 6. Trả lời từng câu hỏi trong đề bài

### 6.1 Ca biên vòng lặp multipass

| ca | kết quả |
|---|---|
| `passes=1` | vòng chạy trọn ⇒ nhánh `else` ⇒ `ly_do = STOP_HET_VONG` nếu hụt. GUI/CLI truyền `on_stop=None` nên không ghi đi đâu. **Đúng.** |
| batch rỗng lượt ĐẦU vs lượt SAU | tách đúng (`scraper.py:555-565`); đột biến M8 (gộp về `source_empty`) ⇒ **ĐỎ**. |
| `max_videos=0` | `len(moi) >= 0` đúng ngay sau lượt 1 ⇒ trả `[]`, `STOP_COMPLETE`; `_auto_scroll` cũng thoát tức thì. Web **không tới được** (`app.py:245 Field(gt=0)`); CLI/GUI tới được. Vô hại. |
| `already_have` trả NHIỀU hơn `fresh` | vô hại — vòng `for ref in fresh` (`scraper.py:573`) chỉ duyệt `fresh`; phần thừa của `owned` không ai đọc. |
| `moi` vượt `max_videos` | xảy ra được trong MỘT lượt; cắt ở `scraper.py:628`. Ref bị cắt **không** có hàng `video_sightings` — giống hệt bản cũ, không phải hồi quy. |
| rò biến giữa các lượt | `fresh`/`owned`/`rate`/`delay` gán lại mỗi vòng; `da_thay`/`moi`/`bo_qua`/`ly_do` tích luỹ **có chủ đích**. Không tìm thấy rò. |
| `i` khi vòng không chạy | **là lỗ thật ở `8b72c93`** (`i+1` khai dư một lượt chưa cào). **`f102452` đã vá** bằng `da_cao`; `i` nay chỉ còn dùng **trong** thân vòng (`if i > 0`) nên không có `NameError`. |

### 6.2 Hợp đồng `gui.py:759` / `cli.py:76`

- **`cli.py:76` → `scrape_music_page`**: chỉ thêm keyword `dem_trang: … | None = None`
  (`scraper.py:404`) có mặc định. CLI không truyền ⇒ `_watch_feed_api(page, None)` ⇒
  nhánh đếm không chạy. **Không đổi hành vi, không đổi thứ tự.** ✓
- **`gui.py:759` → `scrape_music_page_multi`**: GUI không truyền `already_have`/`on_skip`/
  `on_stop`/`max_seconds`. Kiểm từng vế:
  - `already_have=None` ⇒ `owned = set()` luôn (`scraper.py:571`) ⇒ `moi` = toàn bộ `fresh`,
    đúng tập `all_refs` cũ.
  - `max_seconds=None` ⇒ `_con_lai()` trả `None` ⇒ **mọi** cửa thời gian short-circuit.
  - `on_stop=None` ⇒ `scraper.py:617` không gọi gì; `ly_do` chỉ đi vào log.
  - trả về: vẫn `sorted(..., key=video_id, reverse=True)[:max_videos]` (`scraper.py:628`).
    **Thứ tự giữ nguyên.** ✓
  - Vế duy nhất lệch: **khoá lọc trùng** — xem §5.4.

### 6.3 Rò dữ liệu qua `van_tay` / `_trang_thai_cookie`

**Không tìm thấy rò.** Bằng chứng:

- `van_tay` chỉ ra qua `GET /me/cookie` (`app.py:399-401`) và phản hồi `POST /me/cookie`
  (`app.py:480`) — **cả hai `Depends(require_user)` và chỉ đọc jar CỦA CHÍNH người gọi**
  (`cookies_path_for_user(COOKIES_DIR, nguoi_tao)`). `/admin/nguoi-dung` **không** gọi
  `_trang_thai_cookie` (grep: chỉ 2 điểm gọi).
- Đột biến M12 (`_van_tay_jar` trả nguyên `read_text()`) ⇒ **2 failed**
  (`test_no_byte_of_the_jar_comes_back_out`, `test_van_tay_doi_khi_thay_cookie_va_khong_mang_byte_nao_cua_jar`).
  Lưới có thật, không phải lời hứa.
- Lời hứa *"không byte nào của jar đi ra"* vẫn đứng: 8 hex của SHA-256 không phải byte của
  tệp và không nghịch được.

**Ràng buộc phải GIỮ, nêu ra vì nó không nằm ở đâu trong code:** `van_tay` băm **byte thô**,
nên nó là một **oracle so-sánh-bằng ổn định cho "cùng một tệp jar"**. Hai người dán cùng một
bản xuất ⇒ cùng 8 ký tự. Hôm nay vô hại vì không ai thấy `van_tay` của người khác. **Đừng bao
giờ** đưa `van_tay` vào bảng Quản trị hay bất kỳ chỗ nào hiển thị nhiều người cạnh nhau —
lúc đó nó tiết lộ "A và B đang dùng chung một tài khoản TikTok", thứ hiện không ai suy ra được.

### 6.4 Test có sức phân định không — `gia_lap_scraper`

**Vá đúng lớp trong.** `monkeypatch.setattr(scraper_mod, "scrape_music_page", …)`
(`tests/test_web_queue.py:46`) ⇒ `scrape_music_page_multi` chạy **thật**. Không tìm thấy chỗ
nào vô tình vá lớp ngoài (`queue_mod.scrape_music_page_multi` không bị vá ở đâu).
Chứng minh bằng đột biến, không bằng đọc (control 283 passed / rc=0):

| đột biến | kết quả |
|---|---|
| M2 bỏ `max_seconds=TRAN_GIAY_MOT_LUOT` | ĐỎ (1) |
| M3 bỏ `passes=SO_VONG_DAO_SAU` (về 1 lượt) | ĐỎ (4) |
| M4 bỏ `already_have=_already_have` | ĐỎ (7) |
| M5 đếm `max_videos` theo `da_thay` thay vì `moi` | ĐỎ (1) |
| M6 bỏ khối nâng cấp `already_owned` | ĐỎ (2) |
| M7 bỏ nhánh `else: STOP_HET_VONG` | ĐỎ (2) |
| M8 gộp lượt-sau-rỗng về `source_empty` | ĐỎ (1) |
| M9 rò `profile_dir` ra đường web | ĐỎ (1) |
| M10 `set_job_found` ghi đè `tong` | ĐỎ (1) |
| M11 bỏ `on_skip=_note_skip` | ĐỎ (3) |
| M12 `van_tay` trả nội dung jar | ĐỎ (2) |
| M13 `tim_thay` ghi hằng 0 | ĐỎ (1) |
| **M1 `_watch_feed_api` thôi gọi `dem_trang()`** | **XANH — xem §3** |

⇒ Một lỗ duy nhất, và nó nằm đúng ở điểm nối mà commit `8b72c93` coi là phần vá chính.

### 6.5 Đồng thời / thứ tự ghi quanh `_dem_mot_trang`

- **Luồng:** `_dem_mot_trang` chạy trong listener `page.on("response", …)` của Playwright
  **sync** ⇒ cùng thread với worker, không phải thread khác. `_connect`
  (`models.py:113-124`) dùng `check_same_thread=False` + WAL. Không thấy vấn đề thread.
- **Thoát ngoại lệ:** hai lớp chặn — `_note_pages` có `try/except Exception`
  (`queue.py:178-182`), và `on_response` có `except Exception` bọc ngoài
  (`scraper.py:247-248`, kèm comment giải thích Playwright sẽ ném lại ở lời gọi kênh kế tiếp).
  **Không thoát ra được.** ✓
- **`db_path`/`job_id` là None:** từng là lỗ thật (mỗi lời gọi feed đẻ một dòng WARNING) —
  **`f102452` đã vá** bằng cửa `if db_path is None or job_id is None: return`
  (`queue.py:175-176`), đúng kiểu `_note_skip`/`_note_stop`, và có test canh
  (`test_khong_co_db_thi_dem_trang_IM_LANG_khong_canh_bao`).
- **Ghi quá dày:** mỗi lời gọi feed = `sqlite3.connect` + `PRAGMA journal_mode=WAL` +
  `UPDATE` + `commit` + `close`. **CHƯA ĐO** số lời gọi feed thật trong một lượt cuộn (con số
  "3 lời gọi/lượt" trong test là do scraper giả tự bịa ra, không phải phép đo trên TikTok) —
  nên tôi **không** khẳng định nó nặng hay nhẹ. Nếu muốn biết: đếm
  `_FEED_API_MARKERS` khớp trong một lần chạy `--verbose` thật rồi nhân 5 lượt.
- **`set_job_pages` ghi GIÁ TRỊ TUYỆT ĐỐI** (`models.py:367`), còn `_da_doc["trang"]` tích luỹ
  trong bao đóng ⇒ hai nhánh hashtag (ghi 1 lần) và scraper (ghi tăng dần) **không đá nhau**.
  Nhưng chú ý: một job chỉ đi **một** trong hai nhánh, nếu sau này có job đi cả hai thì nhánh
  sau sẽ **đè**, không cộng. Hiện `_fetch_refs` `return` ngay sau nhánh hashtag
  (`queue.py:200-205`) nên chưa thành vấn đề.

---

## 7. Điểm hữu ích cho hiệu chỉnh rủi ro (không phải khen)

- 12/13 đột biến bị giết, gồm cả những cái tinh (thứ tự ưu tiên mã dừng, hai bộ đếm không
  gộp, `profile_dir=None`, `van_tay` không mang byte). Bộ test này **không** thuộc loại
  "chạy code mà không chứng minh hành vi" — nên §3 đáng sửa chứ không đáng nghi cả bộ.
- Docstring ở repo này **có tải trọng**: hai phát hiện nặng nhất (§1, §3) đều tìm ra bằng
  cách **đối chiếu docstring cũ với code mới**, không phải bằng đọc diff. Giữ thói quen đó,
  nhưng kèm kỷ luật: **sửa cơ chế thì phải đi soát mọi docstring đang đứng trên cơ chế đó**
  (`lifecycle.py:316-326` và `models.py:410-413` hiện là hai câu sai).

---

## 8. Việc nên làm, theo thứ tự

1. **§1** — trình user 3 phương án kế toán trần video. Chặn merge cho tới khi có chốt:
   đây là hồi quy người dùng nhìn thấy (429 sai) **và** là lật một quyết định đã khai.
2. **§3** — thêm test `_watch_feed_api(page, dem_trang)` vào `tests/test_feed_watch.py`
   (harness có sẵn). Nghiệm thu: M1 phải ĐỎ.
3. **§2** — hoặc nâng `max_videos` truyền xuống theo `bo_qua`, hoặc sửa lời `already_owned`
   cho nhánh này. Không được để nguyên cả hai.
4. **§4.1** — hiện `tim_thay` ra UI, hoặc bỏ cột nếu không định hiện (cột chỉ-ghi là nợ).
5. **§1 phụ** — sửa hai docstring sai (`lifecycle.py:316-326`, `models.py:410-413`) dù chọn
   phương án nào.
6. **§5.1 / §5.2** — hai sửa một dòng.
7. **§4.2 / §4.3 / §5.3 / §5.4** — ghi vào comment/nợ kỹ thuật; không chặn merge.

## 9. Metrics

| | |
|---|---|
| Test | **346 passed, rc=0** (đo trên repo, không pipe) |
| Đột biến chạy | 13; **12 bị giết, 1 sống** (M1) |
| Control bộ đột biến | 283 passed, rc=0 (`--ignore=tests/test_lifecycle.py`, PYTHONPATH che `src`) |
| Lint / type | **N/A** — `pyproject.toml` không cấu hình ruff/mypy/flake8; `.venv/bin` không có binary nào |
| LOC diff (`e99e730~1..f102452`) | ~713 thêm / ~122 bớt, 15 tệp |

## 10. Câu chưa có lời

1. **Trần video: tính theo số XIN hay số TẢI THẬT?** (§1) — user đã chốt "số tải thật" ngày
   16/09; `e99e730` đảo nó mà không khai. Cần chốt lại.
2. **Nhánh music/search/profile có được phép đào sâu hơn `max_videos` không?** (§2) — nâng
   độ sâu là tăng lưu lượng TikTok, mà trần 800 trang/ngày neo vào số cũ. Đây là đánh đổi
   chống-chặn, không phải lựa chọn kỹ thuật.
3. **`tim_thay` định hiện ở đâu trên UI?** (§4.1) — hay chỉ để phục vụ điều tra sau này?
4. **CHƯA ĐO:** mức xáo trộn thật của cửa sổ đầu trang music giữa hai lần render (§2), và số
   lời gọi feed thật trong một lượt cuộn (§6.5). Cả hai cần một lần chạy có mạng.
