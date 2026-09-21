# Video Desk UI — báo cáo

Nhánh `feat/tiktok-tag-page-support`, không commit (theo yêu cầu).

## ⚠️ Chưa xem được mock đã duyệt — đọc trước khi review

`WebFetch` và `curl` vào `https://claude.ai/artifact/DGEg9wiqJb3ufR7Ki98Qpp` đều trả
**403 Forbidden / Cloudflare "Just a moment..."** (artifact claude.ai đòi đăng nhập,
subagent không có phiên đó):

```
$ curl -sS -o /tmp/artifact.html -w "%{http_code}\n" "https://claude.ai/artifact/DGEg9wiqJb3ufR7Ki98Qpp"
403
```

Tôi KHÔNG bịa là đã xem mock. Toàn bộ layout/màu/chữ dưới đây dựng từ đặc tả CHỮ rất
chi tiết trong yêu cầu (6 hộp lọc cụ thể, quy tắc "không rõ · N", hình dạng thẻ thiếu
ảnh, trạng thái rỗng, thanh thao tác, dịch `ly_do_dung`...) — đặc tả đó đủ chặt để dựng
một trang tự nhất quán, nhưng **màu/khoảng cách/chi tiết pixel có thể lệch bản mock
thật**. Đề nghị user tự mở `web/static/index.html` so với mock và chỉ điểm lệch cụ thể;
sửa theo diff cụ thể sẽ nhanh hơn tôi đoán lại từ đầu.

## Việc đã làm

### 1. Backend: `/videos` trả `nguon` (File Ownership: `web/app.py`)

`web/app.py::list_videos` gọi `models.sources_for_videos` **một lần cho cả trang**
(không N+1), gắn `video["nguon"] = [...]` cho mỗi video (`[]` nếu chưa có sighting nào).

```python
videos = models.list_videos(DB_PATH, limit=limit, offset=offset)
sources = models.sources_for_videos(DB_PATH, [v["video_id"] for v in videos])
for video in videos:
    video["nguon"] = sources.get(video["video_id"], [])
```

### 2. Tests mới (`tests/test_web_app.py`, +61 dòng, 3 test)

- `test_videos_endpoint_includes_sources_from_sightings` — ca dương, video có 2 sighting
  → `nguon` chứa đúng 2 URL.
- `test_videos_endpoint_reports_empty_sources_for_a_video_with_no_sightings` — ca âm,
  video chưa từng có sighting → `nguon == []`, không KeyError/500.
- `test_videos_endpoint_queries_sources_once_for_the_whole_page` — chặn N+1: đếm số lần
  gọi `models.sources_for_videos`, phải đúng 1 cho 5 video.

**Đột biến tay** (yêu cầu "bỏ `sources_for_videos` khỏi `/videos` ⇒ test phải ĐỎ"):
tạm thay đoạn nối `nguon` bằng bản cũ (không nối gì), chạy lại 3 test trên:

```
$ .venv/bin/python -m pytest tests/test_web_app.py -k "sources or videos_endpoint" -q
.FFF....
3 failed, 5 passed, 25 deselected in 0.33s
RC=1
```

Cả 3 test mới ĐỎ đúng như kỳ vọng (2 `KeyError: 'nguon'`, 1 `assert 0 == 1` cho phép đếm
N+1). Đã khôi phục bản đúng ngay sau đó và chạy lại toàn suite — xem mục Nghiệm thu.

### 3. Frontend: `web/static/index.html` viết lại hoàn toàn (145 → 960 dòng)

Một file tĩnh, không build step, không framework (đúng constraint 8) — đây là lý do
file này vượt ngưỡng 200 dòng thường lệ của repo: tách ra `.css`/`.js` riêng vẫn "không
build step" về mặt kỹ thuật, nhưng yêu cầu nói rõ "một file tĩnh", nên giữ nguyên một
file, có chia section bằng comment rõ ràng (THEME TOKENS / STATE / HELPERS / API /
RENDER / EVENTS / INIT) thay cho việc chia file.

Bố cục: dải điều khiển (form tạo job + hàng đợi) ở trên, thư viện creative (bộ lọc +
lưới thẻ) ở dưới — đúng yêu cầu.

**6 hộp lọc** (hộp xổ popover checkbox nhiều-chọn, không phải chip ngang):
- **Nguồn** — bucket theo từng URL trong `video.nguon`; rỗng → "Không rõ".
- **Khung** — **disabled**, có ghi chú "Chưa có dữ liệu tỉ lệ khung (chưa đọc từ
  ffmpeg)". Đã đọc `src/tiktok_music_downloader/utils.py:71-95` (docstring `VideoRef`):
  không có nơi nào trong codebase tính tỉ lệ khung — đúng constraint 7, không bịa.
- **Dài** — bucket theo giây (`<15s`/`15-60s`/`1-3 phút`/`>3 phút`), `null` → "Không rõ".
  *Lưu ý lệch với câu tóm tắt trong yêu cầu ("duration có trong DB")*: đọc
  `VideoRef` docstring cho thấy `duration` cũng `None` với nguồn music/profile/search,
  y hệt `region`/`play_count` — nên tôi áp `"không rõ · N"` cho cả trường này, đúng
  quy tắc CỨNG số 2 (rule 2 chi phối câu tóm tắt khi hai cái xung đột).
- **Thị trường** — bucket theo `region`, `null` → "Không rõ".
- **Ngày tải** — bucket theo `tao_luc` (Hôm nay/Hôm qua/7 ngày/30 ngày/Cũ hơn) — luôn có
  dữ liệu (`tao_luc NOT NULL`), không cần "không rõ".
- **Người tải** — join CLIENT-SIDE qua `job_id → nguoi_tao` dựng từ `GET /jobs` (đã có
  sẵn, không cần sửa backend thêm ngoài phần "Cần THÊM" đã nêu); job không còn trong
  danh sách jobs → "Không rõ".

Dòng "đang lọc": pill `Nhóm: Giá trị ✕` + pill "Xoá hết ✕", gỡ đúng 1 điều kiện khi bấm
✕ trên pill đó.

Thẻ thiếu ảnh: `<img>` gắn `onerror` bằng JS (không nhúng inline để khỏi escape lồng),
đổi sang khối gạch chéo + chữ "Chưa cắt được ảnh" — không phải icon ảnh vỡ mặc định.

Trạng thái rỗng (`state.videos.length === 0`): minh hoạ SVG + tiêu đề + hướng dẫn.

Chọn thẻ → thanh thao tác cố định đáy: *Gồm vào giỏ* / *Phân tích nội dung* (cả hai chỉ
`showToast("Chưa làm...")`, KHÔNG gọi endpoint nào) / *Bỏ chọn*.

Dịch `ly_do_dung` — 3 câu khác nhau cho 3 mã (`stalled`/`page_cap`/`index_failed`, đọc
đúng từ `src/tiktok_music_downloader/hashtag_enumerator.py:51-53,219,260,265`), mã lạ
không rơi vào im lặng: hiện câu trung thực kèm mã gốc trong ngoặc thay vì giấu.

Theme sáng/tối: theo `prefers-color-scheme` mặc định, nút 🌓 ghi đè + nhớ trong
`localStorage`. Chạy được ở 400px (kiểm bằng trình duyệt thật, xem mục Nghiệm thu).

### Một lỗi CSS thật bắt được khi kiểm bằng trình duyệt (đã sửa)

`.selection-bar` / `.empty-state` / `.card-grid` tự đặt `display: flex|grid` — trùng độ
đặc hiệu với luật UA `[hidden]{display:none}`, và stylesheet của trang load SAU UA sheet
nên `el.hidden = true` **không hề ẩn** các phần tử đó (đo bằng
`getComputedStyle(...).display === "flex"` dù `.hidden === true`). Vá bằng một luật
toàn cục `[hidden] { display: none !important; }` — cách sửa chuẩn cho đúng collision
này, có giải thích trong comment tại chỗ.

## Nghiệm thu

### pytest — 220 passed, rc bắt trực tiếp (không pipe)

```
$ .venv/bin/python -m pytest tests/ -q; rc=$?; echo "RC=$rc"
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 98%]
....                                                                     [100%]
220 passed in 3.00s
RC=0
```
(217 cũ + 3 mới, không test nào bị sửa/xoá để né đỏ.)

### JS/HTML syntax

```
$ node --check /tmp/.../index-inline.js   →  JS SYNTAX OK
$ python3 - <<EOF   # HTMLParser đối chiếu open/close tag
  remaining stack: []
```

### Kiểm THẬT bằng trình duyệt — `agent-browser` (Chrome headless thật, không đoán)

Không có tool chụp màn hình trình duyệt sẵn trong bộ công cụ subagent, nhưng máy có
`agent-browser` (CLI cài global, dùng CDP) — dùng nó để mở **thật** `index.html` qua
`python3 -m http.server 8934` tại `web/static/`, chặn `network route` để giả `/jobs`,
`/videos`, `/thumbs/*` (abort → mô phỏng 404), rồi bấm/kiểm DOM thật:

| Kiểm | Lệnh / bằng chứng | Kết quả |
|---|---|---|
| Trạng thái rỗng | `get text "#empty-state h3"` | "Thư viện chưa có video nào", `is visible` = true |
| 6 hộp lọc dựng đủ | `get count ".filter-box"` | 6 |
| Không lỗi console/page | `errors` sau mỗi load | rỗng mọi lần |
| **Bug `hidden` bị CSS đè** | `eval "getComputedStyle(#selection-bar).display"` trước/sau vá | `"flex"` (sai) → `"none"` (đúng) |
| Dịch 3 mã dừng sớm + mã lạ | `get text "#queue-list"` | 3 câu khác nhau đúng nội dung + câu fallback "(mã chưa dịch: mot-ma-la)" cho mã không có trong bảng |
| Bucket "Thị trường" đúng + có "Không rõ" | mở panel, `get text` | VN 2 · BR 1 · US 1 · Không rõ 2 (khớp 6 video giả) |
| Lọc áp đúng + pill + đếm | check "Không rõ", `get count ".card"` | 2 thẻ, pill "Thị trường: Không rõ ✕", "2/6 video" |
| Bucket "Nguồn" đa giá trị + "Không rõ" | mở panel Nguồn | `#xuhuong 2 · #daxaydung 1 · #tainhieulan 1 · 🎵 nhac-hot-123 1 · Tìm kiếm: trend 1 · Không rõ 1` |
| Bucket "Dài" có "Không rõ" | mở panel Dài | 5 bucket đúng số, có "Không rõ: 1" cho video `duration=null` |
| "Người tải" fallback khi job không còn trong `/jobs` | mở panel Người tải | video có `job_id: 999` (không có trong mock `/jobs`) rơi vào "Không rõ: 1" |
| Thẻ thiếu ảnh có hình dạng riêng | screenshot + `errors` | khối gạch chéo + "Chưa cắt được ảnh", không phải icon vỡ |
| Chọn thẻ → thanh thao tác + toast "chưa làm" | click card ×2, click nút "Gồm vào giỏ" | `#selection-bar` visible, "2 đã chọn", toast = `Chưa làm — tính năng "gồm vào giỏ" chưa có ở backend.` |
| Bàn phím: Enter chọn thẻ | `focus`, `press Enter` | `aria-checked` false→true |
| "Xem gốc" KHÔNG chọn thẻ, mở tab mới | dispatch click trên link | tab mới mở tới URL TikTok thật; `aria-checked` thẻ đó vẫn `false` |
| Đóng popover khi bấm ra ngoài / Esc | click ngoài, `press Escape` | cả hai đều đóng đúng |
| Chạy ở 400px | `set viewport 400 750` | `scrollWidth <= 400` = true, screenshot không tràn ngang, form/hàng đợi/hộp lọc xếp dọc, lưới 2 cột |
| Sáng/tối | toggle nút 🌓 | cả hai theme render sạch, tương phản đủ đọc (xem ảnh) |

Toàn bộ lệnh + đường dẫn screenshot nằm trong lịch sử phiên; không khai "chắc là chạy" —
mọi khẳng định ở trên đều đo bằng `get text`/`get count`/`eval`/screenshot thật, không
đoán từ đọc code.

Đã dọn: đóng browser (`agent-browser close`), tắt `python3 -m http.server 8934`
(`pkill -f "http.server 8934"`).

## File Ownership — chỉ 3 file, đúng phạm vi giao

- `web/app.py` (+10/-2)
- `tests/test_web_app.py` (+61)
- `web/static/index.html` (viết lại, 145 → 960 dòng)

Không đụng `web/models.py` (hàm `sources_for_videos` đã có sẵn, dùng nguyên), không đụng
`web/lifecycle.py`, không deploy.

## Status: DONE_WITH_CONCERNS
## Summary
Backend nối `nguon` vào `/videos` (1 truy vấn, có test dương/âm/N+1, đột biến tay xác
nhận ĐỎ đúng chỗ). Frontend dựng lại hoàn toàn theo đặc tả chữ, kiểm THẬT bằng
`agent-browser` (Chrome headless) chứ không đoán — bắt và vá được 1 bug CSS thật (`hidden`
bị `display` của class đè). 220 test xanh, rc=0.

## Concerns/Blockers
1. **Chưa xem được mock đã duyệt** (`claude.ai/artifact/...` trả 403 cho cả `WebFetch`
   và `curl`) — màu sắc/khoảng cách/chi tiết pixel trong `index.html` là suy từ đặc tả
   chữ, CHƯA đối chiếu trực tiếp với bản user đã duyệt. Cần user tự so và chỉ điểm lệch.
2. Số đếm trong hộp lọc tính trên TOÀN BỘ thư viện (không trừ theo các lọc khác đang
   bật) — đơn giản hoá có chủ đích (KISS), không phải facet-search đầy đủ. Nói rõ trong
   comment code; nếu user cần facet đúng nghĩa (đếm theo phần giao với lọc khác) thì đó
   là việc thêm, chưa nằm trong yêu cầu gốc.
