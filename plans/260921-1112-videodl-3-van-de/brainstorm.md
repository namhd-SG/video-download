# Brainstorm — Video Desk, 3 vấn đề user giao 21/09 11:05

**Lane** `06f2a326` (tk3) · **nhánh** `fix/log-path-and-name-list` · **HEAD lúc soạn** `03d8354`
**Trạng thái**: CHƯA CODE. Chờ user chốt 4 ngưỡng ở §6.

---

## 0. Ba phát hiện đổi hình dạng bài toán

Cả ba đều **bác một tiền đề** trong bàn giao hoặc trong đề bài. Đo tại nguồn, có `file:dòng`.

**a) Cột `so_luong` KHÔNG TỒN TẠI.** Schema `jobs` (`web/models.py:26-40`) không có nó. `so_luong`
chỉ là **tham số** của `create_job`. Docstring `models.py:337-340` khai thẳng hành vi đè — *và tự
biện hộ cho nó*: *"that is the real progress-bar denominator, not the ceiling the user asked for"*.
⇒ Đây **không phải bug quên**, là **quyết định thiết kế cũ** mà user vừa bác bằng trải nghiệm.
Sửa mà để nguyên docstring ⇒ người sau đọc nó rồi "sửa lại cho đúng ý ban đầu".

**b) Cơ chế "đào sâu" ĐÃ CÓ SẴN và đã chạy thật — chỉ không được nối vào web.**
`scrape_music_page_multi` (`scraper.py:429-501`) đã có đủ: nhiều lượt, đóng hẳn context giữa các
lượt, nghỉ jitter 60-180s, dừng khi lượt ra 0 (đoán soft-block), dừng khi độ mới < 30%, trần cứng
5 lượt. **GUI desktop đã dùng nó cho đúng ba nhánh music/search/profile** (`gui.py:754-767`).
Web queue thì gọi bản **một lượt** `scrape_music_page` (`queue.py:176`).
⇒ Việc (2) không phải "viết phân trang mới", mà là **nối cái đã có + dạy nó đếm đúng thứ**.

**c) Trần 800 trang/cookie/ngày hiện chỉ đo MỘT nhánh.** `on_pages=_note_pages` chỉ được truyền ở
nhánh hashtag (`queue.py:174`); nhánh music/search/profile **không báo trang nào** ⇒ ghi
`so_trang = 0`. Hôm nay nhánh đó tiêu tài nguyên **vô hình** với bộ đếm trần.
⇒ Nối multipass vào mà không đếm thì trần 800 thành **lời nói dối theo chiều ngược lại**.

**d) Cái user muốn ở (3) có thể KHÔNG lấy được offline.** User hỏi *"đang dùng cookie tài khoản
nào"*. Jar chỉ có `sessionid/sessionid_ss/sid_tt` (`cookies.py:95`); **tên tài khoản TikTok không
nằm trong jar**. Lấy được tên = phải **gọi sang TikTok** — tốn một lượt request, đúng thứ đang gây
rate-limit, và kéo dữ liệu tài khoản vào máy dùng chung. Offline thì trả lời được: *ai dán*, *dán
lúc nào*, *hết hạn lúc nào*, *dấu vân tay ngắn của jar*, *trạng thái*. Đây là **câu hỏi cho user**,
không phải chi tiết kỹ thuật.

---

## 1. Hợp đồng

**Outcome.** User xin N video thì (i) hệ thống **đào tới khi đủ N video MỚI** trên mọi loại link,
không chỉ hashtag; (ii) không đủ thì **nói rõ vì sao** bằng một trong các ca phân biệt được, kèm
đề xuất; (iii) màn hình luôn đo theo **N user xin**, không theo số còn lại sau lọc; (iv) trang Cài
đặt trả lời được *"tôi đã có cookie chưa, của ai, còn sống không"* và cho **xoá để thay**.

**Constraints** (đo được, không phải phỏng đoán):
- 4 trần: `MAX_JOBS_PER_COOKIE_PER_DAY=20` (`lifecycle.py:55`) · `MAX_VIDEOS_PER_COOKIE_PER_DAY=1000`
  (`:68`) · `MAX_INDEX_PAGES_PER_COOKIE_PER_DAY=800` (`:81`) · `MAX_SO_LUONG=2000` (`app.py:119`).
  **Không nâng trần nào** — hoãn có chủ đích, điều kiện mở lại là có số TikTok chặn ở ngưỡng nào.
- Rate-limit TikTok là **ràng buộc sống**: `/search` 16/09 **0/5** lượt · 18/09 **1/1**. Đào sâu
  làm tăng số request ⇒ tăng rủi ro, phải có trần thời gian + trần vòng.
- `profile_dir` **luôn None** trên đường web (`queue.py:126-131`) — persistent context rò session
  người này sang người kia. Có test canh.
- Tên tệp jar = `sha256(danh tính THÔ)`. **Không** thêm `.lower()` vào `_identity_from` ⇒ mồ côi
  mọi jar đang sống trên mini.
- DB đang sống trên mini ⇒ mọi cột mới phải đi qua `_add_column_if_missing` (`models.py:194-196`),
  và **sao lưu DB trước khi đổi schema**.
- Mini dùng chung với Promax đội khác: không dừng dịch vụ, không sudo, không xoá.
- Lưới nghiệm thu **duy nhất** = 336 test local. CI GitHub đang chết vì billing.

**Non-goals.**
- Không đụng repo `meta-ads-automation` (T4 mục `aldenesk-01` là địa phận lane khác).
- Không sửa nhánh **hashtag** — nó đang đúng, nó là **bản mẫu** để chép sang.
- Không đụng GUI desktop (`gui.py`).
- Không nâng/nới trần nào. Không sửa CI/billing.
- Không lấy tên tài khoản TikTok bằng cách gọi sang TikTok, **trừ khi user chọn** (§6 Q4).

**Acceptance — đo bằng HÀNH VI, không bằng marker.**
Bài học `190ee74` hôm qua: vá ship ra, grep thấy mã, **0/6800 dòng log** đổi. Nên:
1. Một job `/music/` xin N, thư viện đã có sẵn k video của nguồn đó ⇒ job kết thúc với **N video
   mới** (hoặc nêu lý do), **không phải N−k**. Đo bằng đếm hàng trong `videos` trước/sau, không
   bằng test có mock trả sẵn.
2. Màn hình job hiện mẫu số = **số user xin**, kiểm bằng đọc DB + xem trang thật.
3. `so_trang` của một job music/search/profile phải **khớp với một phép đếm ĐỘC LẬP** — số response
   feed quan sát được trong log của chính lượt chạy đó. ⚠ *Bản đầu viết `so_trang > 0`; agy R2 bắt
   đúng: **hardcode `1` là qua** — đó là marker trá hình, đo cái CÓ MẶT thay vì cái ĐỔI.*
3b. Job bị **huỷ giữa chừng** vẫn phải để lại `so_trang` > 0 tương ứng phần đã chạy (kiểm bằng cách
   huỷ một job thật rồi đọc DB). Đây là phép đo chiều ngược cho mục 4 của §3.
4. Bốn ca dừng phân biệt được **ở tầng DB** (`ly_do_dung`) trước khi bàn tới popup.
5. Trang Cài đặt: chưa dán cookie / đã dán còn hạn / đã hết hạn ⇒ **ba màn hình khác nhau**; nút
   xoá làm jar biến mất thật và trạng thái đổi ngay.
6. `pytest -q` → `336 passed` + số test mới, đo `rc=$?` **không pipe**.

---

## 2. Vấn đề 1 — mẫu số nói dối

**Gốc**: `queue.py:352` `set_job_total(..., len(refs))` với `refs` đã lọc trùng. Số user xin đã
seed vào `tong` lúc tạo job rồi bị đè ⇒ **mất khỏi DB**.

| | Phương án | Dựa vào giả định nào nhất | Hỏng trước ở đâu |
|---|---|---|---|
| A | Thêm cột `so_luong_yeu_cau`, giữ nguyên nghĩa `tong` = số tìm thấy | mọi chỗ đọc `tong` hôm nay đang đọc đúng ý nó | UI **vẫn in `20/20`** cho tới khi sửa tay 2 chỗ; quên chỗ nào thì chỗ đó vẫn nói dối |
| **B ✅** | Thôi đè `tong` (để nó = số user xin), thêm cột `tim_thay` | ý định của `queue.py:364` không phụ thuộc `tong` = số thực | nếu còn chỗ nào ngầm coi `tong` = số thực mà chưa tìm ra |
| C | Suy lại từ `video_sightings` | số bị bỏ qua đủ để tái dựng ý định | sai hẳn: sighting đếm cái **thấy**, không đếm cái **user xin** |

**Khuyến nghị B** *(R1 chọn A — đã đổi sau phản biện R2-R4; xem `~/agy-ws/exchange/videodl-3vd-R3-claude.md`)*.

Vì sao đổi — hai phép đo:
1. **UI sửa 0 dòng.** `app.js` có 7 lần chữ `tong`, nhưng chỉ **2** là tiến trình job (`:257`,
   `:274`); `:744` là comment; `:750/:752/:759` là **`tong` đồng âm** = tổng video thư viện từ
   `GET /videos` (`app.py:571`). Dưới B, hai chỗ job **tự thành `20/50`**. Dưới A chúng vẫn nói dối
   tới khi sửa tay.
2. **Rủi ro tôi gán cho B ở `queue.py:364` là thổi phồng.** Ý định dòng đó = *"xin được mà không
   tải nổi cái nào"*. `refs` rỗng thì **thoát sớm ở `:353-355`**, không tới `:364`. Tìm 20/50 hỏng
   cả 20 ⇒ `tong=50>0, xong=0` ⇒ `failed`, **đúng**. Tìm 20 tải được 20 ⇒ `done`, **đúng**.
3. Thêm: `queue.py:350` đã gọi `max_videos=job["tong"]` — **tại đó `tong` đang là số user xin**.
   B chỉ giữ nguyên nghĩa đó suốt vòng đời. **B là bỏ một phép ghi; A là thêm một cột.**

Cộng thêm (không đổi): **sửa docstring `models.py:337-340`** — nó đang biện hộ cho hành vi vừa bị
bác; dưới B nó còn sai nặng hơn. Để nguyên là gài mìn cho người sau.

---

## 3. Vấn đề 2 — nhánh không-hashtag không đào sâu (việc chính)

**Gốc**: `queue.py:176-193` lấy một danh sách hoàn tất rồi lọc trùng **một lần ở cuối**. Trùng bao
nhiêu, hụt bấy nhiêu. Comment tại chỗ đã khai từ đầu; vá dừng ở ranh giới nhánh.

**Nhánh hashtag đã giải xong bài này** và đáng chép nguyên tắc, không chép code:
`hashtag_enumerator.py:230-240` tách **hai** khái niệm mà gộp lại là hỏng cả hai —
*`fresh`* (chưa thấy ở lượt này) nuôi bộ đếm đứng máy, *`added`* (chưa có trong **thư viện**) mới
đếm về `max_videos`. Và nó đã có sẵn **từ vựng lý do dừng**: `STOP_INDEX_FAILED` · `STOP_STALLED` ·
`STOP_PAGE_CAP` · `STOP_ALREADY_OWNED`, kèm luật nâng cấp lý do (`:280-287`): page_cap/stalled mà
lượt này toàn video đã có ⇒ lý do thật là `already_owned`, vì hai ca đó bảo user làm hai việc ngược
nhau (*đổi nguồn* vs *thử lại*).

| | Phương án | Dựa vào giả định nào nhất | Hỏng trước ở đâu |
|---|---|---|---|
| **A ✅** | Nối `scrape_music_page_multi` vào web queue, truyền `already_have` xuống để đếm theo **video mới**, cộng đếm trang | multipass đã chạy thật trong GUI ⇒ hành vi đã biết | mỗi lượt nghỉ 60-180s ⇒ job **dài hàng chục phút**; phải có trần thời gian, và user phải thấy tiến trình |
| B | Viết vòng lật trang mới trong `queue.py`, gọi `scrape_music_page` nhiều lần với `max` tăng dần | mỗi lần gọi trả lát cắt khác nhau | **dựng lại thứ đã có**, và bỏ mất phần chống chặn đã đo (jitter, đóng context, dừng khi soft-block) |
| C | Chỉ xin dư một lần (`max_videos = N × hệ số`) rồi lọc | tỉ lệ trùng đoán trước được | **không đảm bảo gì**: trùng 90% thì hệ số nào cũng hụt; và bản chất vẫn là "một danh sách hoàn tất" |

**Khuyến nghị A**, kèm **năm** thứ không có sẵn, phải làm *(mục 1b, 2b, 4 đến từ phản biện R2-R4)*:

1. **Dạy multipass đếm "mới với thư viện"**: hiện nó chỉ dedupe trong phạm vi lượt chạy
   (`scraper.py:463-490`). Không truyền `already_have` xuống thì nó dừng ở "đủ N **thấy được**",
   đúng cái lỗi đang sửa.
1b. ⚠ **Hai bộ đếm sẽ đánh nhau nếu gộp.** `scraper.py:482` `rate = added / len(batch)` đo *nguồn
   còn trả thứ mới không*. Nhét "mới với thư viện" vào đó thì: chia cho batch **gốc** ⇒ một lượt
   toàn video đã có cho `rate` thấp giả ⇒ **dừng sớm sai** đúng lúc cần đào tiếp; chia cho batch
   **đã lọc** ⇒ mẫu số co theo tử số ⇒ `rate` không bao giờ xuống ⇒ **chạy tới kịch trần**.
   ⇒ Luật (chép nguyên tắc của hashtag, `hashtag_enumerator.py:230-240`): **novelty giữ mẫu số
   gốc** (câu hỏi chống chặn), **mục tiêu N đếm theo `added`** (câu hỏi của user). Hai câu khác
   nhau ⇒ hai bộ đếm, không gộp.
2. **Đếm trang cho nhánh này** (phát hiện §0c). Đơn vị **kiểm được** đã có sẵn: `_watch_feed_api`
   (`scraper.py:403`) đang theo dõi response feed ⇒ **đếm số response feed**. Cùng đơn vị với
   "trang index" của hashtag — cả hai đều là *1 request → 1 mảng video*, nên cộng chung vào trần
   800 là chuẩn (agy R4 phán, tôi nhận).
2b. ⚠ **`scrape_music_page` phải ĐỔI CHỮ KÝ** để nhận `on_pages` — hiện `scraper.py:370-379` không
   có tham số nào như vậy. Không làm được mục 2 và mục 4 nếu bỏ qua việc này.
3. **Trần thời gian + trần vòng** → §6 Q1, Q2. Không có trần thì job dài vô định và đâm vào
   rate-limit — đúng thứ làm `/search` chập chờn.
4. ⚠ **GHI SỐ TRANG TĂNG DẦN TRONG LÚC CHẠY, không phải một lần ở cuối.** Đo:
   `hashtag_enumerator.py:289-290` gọi `on_pages(pages_read)` **một lần, ở cuối**; cửa chặn trần
   đọc `SUM(so_trang)` đã commit (`app.py:284` → `lifecycle.py:370`). Hai hậu quả, cả hai **hỏng
   âm thầm**: (i) job **huỷ/crash giữa chừng ⇒ ghi 0 trang** dù đã tiêu request thật với TikTok;
   (ii) job **đang chạy chưa ghi gì** ⇒ job xếp hàng kế tiếp được duyệt trên sổ cũ.
   `JobWorker` (`queue.py:373-380`) tuần tự theo cấu tạo nên **không phải TOCTOU song song**, nhưng
   job 5-15 phút làm cửa sổ này rộng ra — **chính bản vá 2.2 làm lỗ này to hơn**.
   Đây là `guard-marker-and-claim-write-ordering.md` vế 3: mốc *"đã tiêu"* ≠ mốc *"đã xong"*.

**Bốn ca dừng, phân biệt ở tầng DB trước, popup sau** (user nêu 3, bằng chứng cho thấy là 4):
`source_empty` (link không đưa ra video nào — link sai/hết hạn) · `already_owned` (thư viện đã có
hết — **đổi nguồn**, chạy lại vô ích) · `het_thoi_gian`/`het_vong` (tốn quá — **chạy lại được**,
có thể ra thêm) · `nghi_bi_chan` (một lượt trả 0 giữa chừng — **nghỉ rồi hãy chạy lại**).
Ca cuối `scraper.py:476-478` đã phát hiện được nhưng hiện chỉ ghi log, không nổi lên DB.
Ba ca đầu bảo user ba việc khác nhau; gộp lại là quay về "một dòng chữ lặng lẽ" mà user đang chê.

⚠ **Bốn ca này CHỒNG LẤN, nên phải có THỨ TỰ ƯU TIÊN** *(agy R2 bắt, tôi nhận)*: một job vừa hết
giờ **vừa** toàn video đã có thì ghi mã nào? Tiền lệ đã có ở nhánh hashtag
(`hashtag_enumerator.py:280-287`): page_cap/stalled mà lượt này toàn video đã có ⇒ **nâng thành**
`already_owned`, *"vì hai ca đó bảo user làm hai việc ngược nhau"*. Áp cùng thứ tự:
**`nghi_bi_chan` > `already_owned` > `het_thoi_gian`/`het_vong` > `source_empty`**.
Lý do `already_owned` đứng trên trần thời gian: chạy lại khi thư viện đã có hết là **vô ích chắc
chắn**; chạy lại khi hết giờ **có thể ra thêm**. Liệt kê mà không xếp thứ tự là xúi user chạy lại
vô ích.

⚠ `8c38650` (chưa deploy) mới làm phần **nói lý do khi ra 0**. Nó **không** phải phần bù cho đủ N.

---

## 4. Vấn đề 3 — UI cookie

**Nền có sẵn, dùng lại, đừng viết mới**: `GET /me/cookie` → `_trang_thai_cookie` (`app.py:376-378`)
trả **mã đóng + mốc thời gian**, cố ý không trả byte nào của jar (`cookies.py:161-166` giải thích
vì sao: câu chữ thuộc giao diện, và tập mã đóng là an toàn **theo cấu tạo**). Bốn mã đã có câu
tiếng Việt trong `app.js`. Trang: `web/static/settings.html` + `settings.js`.

| | Phương án | Trả lời được "tài khoản nào"? | Giá |
|---|---|---|---|
| **A ✅** | Chip trạng thái + *ai dán* (email) + *dán lúc nào* + *hết hạn lúc nào* + vân tay ngắn jar + nút xoá | **Không** tên TikTok — nhưng phân biệt được "jar này khác jar kia" | 0 request ra ngoài, 0 dữ liệu tài khoản mới |
| B | A + gọi TikTok lấy tên tài khoản | Có | tốn 1 request đúng lúc đang tránh rate-limit; kéo danh tính TikTok vào máy **dùng chung với đội khác** |

**Khuyến nghị A**, và **hỏi user** (§6 Q4) vì chính user đòi chữ *"tài khoản nào"* — A không cho
đúng chữ đó, nên đây là user chốt, không phải lane tự quyết.

Nút xoá cần endpoint `DELETE /me/cookie`. Xoá jar = **việc khó lui** (user phải đi lấy cookie
lại) ⇒ phải có xác nhận, và chỉ xoá jar của **chính người đang đăng nhập**.

---

## 5. Thứ tự đề xuất

1. **Vấn đề 1** — nhỏ, độc lập, sửa ngay được cái user nhìn thấy mỗi ngày. Không chờ ngưỡng nào.
2. **Vấn đề 3** — độc lập, không đụng đường quét, không tốn quota TikTok.
3. **Vấn đề 2** — chờ user chốt §6 Q1-Q3; là việc dài nhất và là việc duy nhất có rủi ro bị TikTok
   chặn.

Không gộp làm một PR: (1) và (3) lui được rẻ, (2) thì không.

---

## 6. CÂU HỎI CHO USER — bốn cái, phải chốt trước khi code vấn đề 2

**Q1. Trần THỜI GIAN cho một job đào sâu?** Mỗi lượt quét lại phải nghỉ 60-180s để không bị TikTok
nhận mặt. Xin 50 mà trùng nhiều ⇒ có thể 4-5 lượt ⇒ **5-15 phút một job**. Anh muốn trần bao
nhiêu — 5 phút, 10 phút, hay để anh nhập lúc tạo job?

**Q2. Trần SỐ VÒNG?** Code hiện chặn cứng 5 lượt. Giữ 5, hạ xuống 3 (an toàn hơn), hay theo Q1 và
bỏ trần vòng?

**Q3. Chấp nhận nhánh music/search/profile từ nay TIÊU trần 800 thật không?** Hôm nay nó ghi **0**
trang — tiêu tài nguyên mà bộ đếm không thấy. *(Bản đầu tôi đề xuất "1 lượt = 1 trang"; agy bắt
đúng là **bịa** — một lượt cuộn nhiều vòng, mỗi vòng thêm request, đếm 1 là hụt trầm trọng.)*
Đơn vị đúng, kiểm được, đã có sẵn trong mã: **đếm số response feed** (`_watch_feed_api`), cùng đơn
vị với "trang index" của hashtag. Hệ quả anh cần biết trước: một job music từ nay có thể ăn **hàng
chục** trang thay vì 0 ⇒ trần 800/ngày sẽ **chạm sớm hơn nhiều** so với hôm nay. Anh chấp nhận, hay
muốn tôi tách trần riêng cho nhánh này?

**Q4. "Đang dùng cookie tài khoản nào" — chấp nhận bản offline không?** Tên tài khoản TikTok
**không nằm trong cookie**; muốn có tên thì phải gọi sang TikTok mỗi lần mở trang Cài đặt. Bản
offline nói được: *ai dán · dán lúc nào · hết hạn lúc nào · còn sống không · vân tay ngắn để phân
biệt jar*. Đủ chưa, hay anh cần đúng tên tài khoản và chấp nhận thêm một request?

---

---

## 6b. Đã qua cửa ngoài — 5 vòng phản biện với agy

Hồ sơ: `~/agy-ws/exchange/videodl-3vd-R{1..5}-*.md` (`gemini-3.1-pro-high`, tầng PHÁN, không hạ
tầng). Khép ở R5 bằng **nhượng**, không bên nào phủ quyết bên nào.

| vòng | kết quả |
|---|---|
| R2 (agy) | `MỞ` — 6 lỗ |
| R3 (claude) | nhận 5/6; **bác vế 1** (agy đếm nhầm `tong` đồng âm: 2 chỗ chứ không phải 5) và **bác nửa vế 6** (`JobWorker` tuần tự ⇒ không TOCTOU song song). Tự bác R1 của mình ở §2 ⇒ **đổi khuyến nghị A→B** |
| R4 (agy) | `MỞ` — nhận cả hai chỗ bị bác; giải câu đơn vị trần; bác rủi ro xoá-cookie của tôi; thêm 1 việc (đổi chữ ký `scrape_music_page`) |
| R5 (claude) | **KHÉP** — nhận hết. Kiểm `downloader.py:223-226`: mất jar giữa chừng ⇒ `except Exception` ⇒ rơi về tải ẩn danh, job không chết ⇒ agy đúng |

**Phản biện đổi thật 4 thứ**, không phải đóng dấu: khuyến nghị §2 lật A→B · thêm luật hai-bộ-đếm
(1b) · thêm thứ tự ưu tiên 4 ca dừng · thay acceptance `so_trang > 0` (marker trá hình) bằng đối
chiếu độc lập · thêm việc ghi-trang-tăng-dần (§3 mục 4).

---

## 7. Chưa giải / rủi ro còn treo

1. **Chưa đo tỉ lệ trùng thật.** Không có số "xin 50 thì thường trùng bao nhiêu" ⇒ mọi ước lượng
   thời gian ở Q1 là **suy ra từ cấu tạo** (60-180s × số lượt), **chưa phải số đo**. Đo được sau
   khi có 1-2 job thật chạy với đếm trang.
2. **Không biết TikTok chặn ở ngưỡng nào.** Cả 4 trần vẫn là số chọn tay. Điều kiện mở lại đã ghi
   sổ: có số thật thì mới bàn.
3. **`/search` chập chờn chưa rõ gốc** (16/09 0/5 · 18/09 1/1). Đào sâu trên `/search` có thể làm
   nặng thêm. Nếu Q1-Q3 chốt xong mà `/search` vẫn chập chờn, cân nhắc **bật đào sâu cho
   music/profile trước, `/search` sau**.
4. **Ba mục mắt T4 và deploy `8c38650`** vẫn chờ user, không nằm trong brainstorm này.
5. **Xoá cookie giữa lúc job đang chạy** — *không còn là ẩn số*: `downloader.py:223-226` nuốt lỗi
   và rơi về tải ẩn danh, job không chết. Còn lại chỉ là **một dòng cảnh báo** trong hộp xác nhận
   xoá, không phải rủi ro thiết kế.
6. **Đơn vị trần** — *đã đóng* ở R4: "trang index" và "response feed" đều là *1 request → 1 mảng
   video*, cộng chung vào 800 là chuẩn.
