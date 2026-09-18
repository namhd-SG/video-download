# Bàn giao — Video Desk, ngày 16/09

**Từ:** phiên `ad6008ff` (tk3) · **21:35** · **Nhận từ:** `macos-aa` chiều 15/09
**Nhánh:** `feat/tiktok-tag-page-support` · **HEAD `1c9c630`** · cây sạch · đã đẩy
**Test:** `265 passed, rc=0` (đo không pipe, `.venv/bin/python -m pytest -q`)

> ⏱ **MỌI SỐ TRONG FILE NÀY ĐO LÚC 21:33–21:35 ngày 16/09.** Không có mốc tương đối
> nào ("vừa nãy", "~16 phút") — nếu bạn đọc file này lúc khác, mọi số về mini, đĩa,
> IP đang dùng đều **phải đo lại**. Đĩa mini đi 11GB→6,6→6,4→11Gi trong một ngày.

## HAI CÂY — mỗi cây một dòng

| cây | đường dẫn tuyệt đối | nhánh | sha | status |
|---|---|---|---|---|
| tool | `/Users/macos/Projects/video-download` | `feat/tiktok-tag-page-support` | `1c9c630` | sạch, đã đẩy |
| nav | `/Users/macos/meta-ads-wt-videodlnav` | `feat/videodl-nav-link` | `91904bc2` | sạch, đã đẩy, PR #192 |

⚠ Cây thứ hai là **worktree của repo meta-ads-automation**, KHÔNG phải repo tool.
Repo chính `~/meta-ads-automation` có lane khác làm dở — **đừng đụng git ở đó**.

---

## 0. ĐỌC TRƯỚC KHI GÕ — ba thứ dễ sai nhất

**a) MINI ĐANG ĐI SAU DEV 3 COMMIT CODE.** (deploy cuối là **`9ba8cac` lúc 14:58**,
KHÔNG phải `9c37b12b` — cái đó là chuyến 11:23, đã bị hai chuyến sau thay.) Đo 21:33:
`app.js` sha dev `7e2c8cb2` ≠ mini `6b3fcf92`; `grep -c already_owned web/models.py`
trên mini = **0**. Lần deploy cuối là **14:58 = `9ba8cac`**. Chưa lên mini:
`2e5f31e` (ảnh 0 byte) · `13000cc` (`/jobs` riêng tư) · `eafb2bf` (docstring) ·
`1c9c630` (nguồn đã cạn + trần liệt kê).
⇒ Người dùng thật **đang chạy bản cũ**. Ba thay đổi về quyền và trần **chưa có hiệu lực**.

**b) DEPLOY PHẢI XIN USER.** Luật lập 16:57: commit/push/PR nháp thì tự do;
**merge và deploy phải xin user**. Cộng cửa riêng của lane này lập lúc ~14:20:
trước mỗi lần deploy **grep log 15 phút gần nhất xem có ai đang dùng** — có người
thì **dừng, hỏi điều phối**. Đã áp đúng hai lần (12:14 dừng vì 2 IP; 14:58 kiểm
0 job rồi mới bấm).

**c) CÁCH VÀO MINI.** `ssh nobi_auto@100.109.39.103` — **KHÔNG phải** alias `mini`
(alias đó trỏ về chính máy dev `nam-mini-m4`, suýt rsync đè lên worktree đang gõ).
Tên user đúng nằm ở `deploy/mini-setup.sh:45`. Deploy: `bash deploy/deploy-to-mini.sh`
(thử khô) rồi `--yes`. Lui: `bash deploy/rollback-on-mini.sh <thư-mục-truoc-...>`.

---

## 1. Trạng thái đo được lúc 21:33

```
DEV   : 265 passed rc=0 · cây sạch · HEAD 1c9c630 đã lên origin
MINI  : healthz 200 · astronex 5 · đĩa 11Gi (SÁNG NAY 6,4Gi — ai đó đã dọn)
        1 jar cookie thật (0600) · 0 job đang chạy · 2 IP ngoài đang mở trang
        app.js LỆCH dev (xem mục 0a)
```

⚠ **Đừng trích số đĩa từ tài liệu.** Nó đi 11GB → 6,6 → 6,4 → 11Gi trong một ngày.
Đo lại mỗi lần.

---

## 2. Đã làm hôm nay — 21 commit

### Phase 05 (cookie từng người) — **9/9 tiêu chí, đã qua review ngoài**
| sha | việc |
|---|---|
| `0fa50a0` | cookie của B đi đúng job của B (bắt giá trị tới `download_all`, không phải grep log) |
| `602a4de` | tiền-kiểm cookie hỏng ⇒ job FAIL, 4 ca phân biệt |
| `e5df58e` | jar tạm không sống sót qua SIGKILL (thư mục riêng 0700 + quét lúc khởi động) |
| `9ba8cac` | **sửa những gì review tìm ra** — xem mục 3 |

### Phase 06 (link nav meta-auto) — thi công xong, **PR #192 chưa merge được**
- Code ở repo **meta-ads-automation**, worktree `~/meta-ads-wt-videodlnav`, nhánh
  `feat/videodl-nav-link`, PR #192 `MERGEABLE`.
- `c642290f` test khoá **hình dạng** chỗ vẽ (đột biến `<a>`→`<Link>` ⇒ ĐỎ) + `91904bc2` bản đồ.
- **Chặn:** hết hạn mức GitHub Actions, chờ reset ~01/10. Mọi CI trong account đó
  chết cùng kiểu (job 0 bước, ~3 giây). **Đừng dò CI** — phiên điều phối giữ việc đó.

### Phase 07 (thư viện) — đã qua review, sửa 2 lỗi CAO
`2e5f31e` ảnh 0 byte + id 300 chữ số. Chi tiết ở mục 3.

### Bốn quyết định user chốt 16/09 — đã thi công 3/4
| | quyết định | sha |
|---|---|---|
| (iii) | `/jobs` **chỉ thấy lượt của mình**, admin thấy hết | `13000cc` |
| (ii) | docstring trần: mỗi cổng nói đúng thứ nó đếm | `eafb2bf` |
| (i) | "nguồn đã cạn" không trừ trần job **+ trần liệt kê 800 trang** | `1c9c630` |
| (iv) | **upload trượt tự thử lại** | ⛔ **CHƯA LÀM — việc tiếp theo** |

---

## 3. Những gì REVIEW tìm ra — đọc kỹ, đây là phần đắt nhất

Hai vòng `code-reviewer` (phase-05 và phase-07). Cả hai đều tìm ra lỗi thật mà
**251 test xanh không bắt được**.

**Lỗi nặng nhất: một test canh đường rò credential là LƯỚI GIẢ.**
`test_the_failure_reason_never_quotes_the_cookie_file` tìm một cụm bí mật trong
`ly_do_dung`. Fixture của nó rơi vào nhánh `raw[:20]` của `scraper.py`, cắt đúng
giữa cụm đang tìm ⇒ **khôi phục lỗ rò mà suite vẫn XANH**. Nhánh `raw[:80]`
(JSON dán thiếu — dạng hỏng phổ biến nhất) **không test nào chạm**, và ở đó
nguyên token ra hết.
⇒ Đã thay bằng khẳng định **cấu tạo**: `ly_do_dung` chỉ nhận **tập mã đóng**
(`web/cookies.py::MA_LOI_COOKIE`). Một cột chỉ nhận tập mã đóng thì **cấu tạo
không thể** cõng byte của tệp cookie — không phụ thuộc ai nhớ viết test.

**Các lỗi thật khác, đều đã sửa + đột biến chứng minh:**
- `expires` dạng ISO ⇒ `int()` ném ⇒ job `failed` với `ly_do_dung = NULL` (job chết
  không một chữ — đúng thứ phase-05 sinh ra để diệt).
- `scraper.py:82,91` nhúng `raw[:20]`/`raw[:80]`; bịt một consumer là chưa đủ, hai
  đường khác (`downloader` log.warning, `queue` log.exception) vẫn rò. **Đã bịt gốc.**
- Cookie chứa TAB ⇒ yt-dlp in **nguyên dòng có `sessionid`** ra stderr → log máy dùng chung.
- `pytest` **xoá jar thật** trong `web/data/tmp` vì `prepare_data_dir` nhận 4 đường dẫn
  rồi tự lấy cái thứ 5 từ module. Nay tham số **bắt buộc**.
- Ảnh: `ffmpeg -y` tạo tệp ra **trước** rồi mới hỏng ⇒ webp 0 byte ⇒ `/thumbs` trả
  **200 kèm thân rỗng vĩnh viễn**, mọi lượt cắt lại bỏ qua mãi.
- `/thumbs` id 300 chữ số ⇒ `OSError` ném ra khỏi endpoint đã xác thực.

**Bốn lỗi của CHÍNH TÔI, đột biến bắt được — đừng lặp lại:**
1. Bản vá đầu cho `prepare_data_dir` cho tham số **mặc định trỏ vào production** ⇒ ba
   chỗ gọi cũ vẫn quét nhầm prod. **Cùng lớp lỗi đang đi sửa, lùi một tầng.**
2. Test ảnh đầu chỉ phủ nhánh `rc != 0`; đột biến M6 **vẫn xanh** ⇒ chưa phủ đúng
   nhánh vừa vá. Phải thêm test giả lập "ffmpeg báo rc=0 mà tệp rỗng".
3. Test id dài **đo sai điều kiện** — thư mục `thumbs/` chưa tồn tại nên hệ tệp trả
   `ENOENT` trước, test đi qua **đường khác đường của máy thật**.
4. Ca dương cho grep dùng **mẫu khác** với mẫu đã trả rỗng ⇒ control sai điều kiện.

---

## 4. CHƯA LÀM — việc tiếp theo, theo thứ tự

### BA VIỆC "ĐANG LÀM" theo bàn giao cũ — trạng thái THẬT lúc 21:35
| việc | trạng thái | file đang sửa |
|---|---|---|
| (i) trần liệt kê | ✅ **XONG** `1c9c630`, 4 test + 2 đột biến ĐỎ | — không còn dở |
| (ii) docstring trần video | ✅ **XONG** `eafb2bf` | — không còn dở |
| (iv) upload tự thử lại | ⛔ **CHƯA GÕ DÒNG NÀO** | sẽ sửa `web/lifecycle.py` |

**Không có file nào đang sửa dở.** Cây sạch, mọi thứ đã commit và đẩy.

### (iv) Upload Drive trượt ⇒ TỰ THỬ LẠI — user đã chốt, chưa gõ dòng nào
Ràng buộc user/điều phối đặt:
- Thử lại vài lần **có giãn cách**; hết thì **báo rõ trên lượt đó** để người dùng biết mình mất gì.
- **Trần số lần và tổng thời gian chờ phải NHỎ và khai trong comment**, neo vào một
  phép đo (mạng chớp thì bao lâu thì khỏi?). Trần rộng biến một lỗi thành một khoảng
  chờ không ai thấy.
- Hết trần ⇒ **văng kèm lý do thật**, không nuốt.
- **Đếm số lần phải thử lại và in ra** — con số đó cho biết tình trạng tệ đi hay đỡ đi.
- Chỗ sửa: `web/lifecycle.py::on_video_verified` / `_note_upload_outcome`.

### B2 — nghiệm thu toàn hệ (`phase-06`), còn 3/5
- ✅ thư mục làm việc rỗng sau job · ✅ đếm khớp · ✅ promax 302 (lấy mẫu 5 lần) · ✅ label astronex
- ⛔ **hai người chạy cùng lúc** — cần hai người thật. Hai nửa đã có bằng chứng riêng
  (chạy tuần tự: test + worker một luồng · cookie không lẫn: test + đột biến).
  **Thiếu đúng phép đo hai người cùng bấm.**
- ⛔ **reboot mini → dịch vụ tự lên** — máy đội khác dùng chung (**Promax production
  của người khác**), **KHÔNG tự bấm**, phải qua điều phối hẹn giờ với user.
  **QUY TRÌNH BẮT BUỘC — chụp mốc ~30 giây TRƯỚC khi bấm, đừng để lane sau tự đoán:**
  ```
  ssh nobi_auto@100.109.39.103 'launchctl list | grep astronex'      # phải là 5 label
  curl -s -o /dev/null -w "%{http_code}" https://promax.nobidigital.asia   # phải 302
  # và 0 job đang tải dở:
  ssh ... 'cd ~/Projects/video-download && ./.venv/bin/python -c "
  import sqlite3;print(sqlite3.connect(\"web/data/jobs.db\").execute(
  \"SELECT COUNT(*) FROM jobs WHERE trang_thai NOT IN (\x27done\x27,\x27failed\x27,\x27interrupted\x27)\"
  ).fetchone()[0])"'
  ```
  Sau reboot đo lại **đúng ba thứ đó** rồi so. Thiếu mốc trước thì không phân định được
  "reboot làm hỏng" với "vốn đã hỏng".
- ⛔ **link Drive MỞ ĐƯỢC** — mới đo là link **tồn tại**, chưa mở bằng mắt. Rẻ, làm khi tiện.

### Ba tính năng phase-07 đã chốt — làm SAU CÙNG
chép sang Shared Drive Creative Desk · phân tích nội dung tầng 3 theo lô · "tìm thêm
giống cái này".
⚠ **Báo điều phối TRƯỚC khi bắt đầu cái chép-sang-Drive**: nếu đường chép tải về đĩa
mini rồi mới đẩy đi thì đó là rủi ro thật. Phải đi **copy server-side của Drive API**
(`files.copy`), không qua đĩa. `phase-07` đã đo: SA nhìn thấy đúng 1 Shared Drive,
`canAddChildren=True` trên cả 5 thư mục gốc.

### Ba lỗ lưới nhỏ review tìm ra, chưa bịt (không cần ai quyết)
- `da_tai` là cột **chỉ-ghi** — không nơi nào đọc; docstring nói nó "is the whole point".
- `list_videos` **không có test nào canh `ORDER BY`** — bỏ đi thì lưới lộn ngược, không ai kêu.
- `VIDEOS_PAGE_SIZE = 200` là **hằng chết** — UI luôn gửi `limit=500`.

---

## 5. CHỜ USER — không việc nào chặn ở lane

1. **`VIDEODL_ADMIN_EMAILS` đang RỖNG** ⇒ **chưa ai xem được toàn bộ hàng đợi**, kể cả
   user. Hành vi đúng (mặc định an toàn) nhưng là **việc vận hành**: đặt biến trong
   `~/.config/videodl/env` trên mini rồi khởi động lại dịch vụ.
   → Cần ghi một dòng vào `CHECKLIST-VAN-HANH.md` phần chờ-user. **Tôi chưa kịp ghi.**
2. **Nút "Xoá"** — đã hỏi 5 lần chưa có đáp. Xoá giỏ hay xoá Drive? Thư viện dùng chung
   nên xoá Drive của một người là xoá của cả team. **Không có đường xoá nào trong `models.py`.**
3. **Dải nhập tối ở light mode** — app **khớp mock từng giá trị**, nên đổi là **đổi
   thiết kế**, không phải sửa lỗi.
4. **Đường lấy taxonomy sống** (a: token máy · b: trình duyệt gọi thẳng + CORS ·
   c: đồng bộ — đã loại). Khuyến nghị **(b)**. Chưa ai chốt.
5. **Deploy 4 commit đang treo** (mục 0a) — cần user gật.

---

## 5b. Đã THỬ rồi BỎ — kèm lý do, để lane mới khỏi làm lại

- **Đột biến runtime cho link nav** (trỏ hostname vào cổng chết, đo trang meta-auto có
  chậm không): **BỎ**. Lý do: cần dựng cả frontend meta-auto. Thay bằng chứng minh
  **cấu tạo** (thẻ `<a>` thuần ⇒ trình duyệt không chạm hostname tới khi bấm) + test
  khoá hình dạng nguồn `c642290f`. Điều phối cũ đã **chấp nhận** cách thay thế này.
- **Render test cho sidebar meta-auto**: **BỎ**. Cần mock 4 context
  (`usePathname`/`useRouter`/`useAuth`/`useProject`) — giòn, hỏng mỗi lần sidebar thêm
  dependency. Không phải vì RAM.
- **Backfill 1074 video**: **USER HUỶ**. Số thật là 4. Script `4eb28c6` giữ lại nhưng
  **chưa từng chạy vào DB sống**; bản sao thử đã xoá (`ls` trả "No such file").
- **Chạy `ak plan status`**: **HỎNG trên máy này** ("Error: Command failed"). Đếm
  checkbox bằng `grep -c` thay thế.
- **Giả thuyết "không có đường vào mini"**: **BỊ BÁC** — chỉ là sai tên user.

## 5c. Giả thuyết còn TREO, chưa ai đo

- `/search` chết là do **phía TikTok đổi** hay do **IP/headless bị nhận diện**? Chưa
  phân định. Đã loại: cookie hỏng, tool hỏng.
- Cookie **không tạo khác biệt** ở music page hôm nay (10 video dù có hay không) — đúng
  cho mọi nguồn hay chỉ nguồn đó? `/search` giờ chết nên **không kiểm được nữa**.

## 6. Sự thật bị bác trong ngày — đừng để sống lại

- **"1074 video cũ cần backfill"** → **SAI, số thật là 4**. Đo: Drive có 14 mp4, DB có
  10 hàng. Lời giải khớp từng con số: lớp chỉ mục lên 15/09 14:25; job-1(3)+job-2(1)
  chạy trước mốc; job-3 `tong=0` nên không sinh thư mục Drive ⇒ đúng 3 thư mục.
  **User đã huỷ backfill 16/09.** Script `4eb28c6` **chưa từng chạy vào DB sống** —
  đừng thấy nó mà tưởng có việc treo.
- **`/search` CHẾT** — 0/5 lượt có cookie thật, cả 5 lần HTTP 200 **body 0 byte**.
  Đối chứng cùng lúc: music page 10 video (có và không cookie), hashtag 3 video.
  ⇒ Không phải cookie hỏng, không phải tool hỏng. Đã ghi lên trang.
- **"cookie ăn 19/20 vs không cookie 1/12"** là đo **14/09**, không phải hiện tại.
  Hôm nay music page ra **10 video dù có hay không cookie**.
- **Cả tôi lẫn điều phối từng kết luận "không có đường vào mini"** — sai, chỉ là **sai
  tên user**. Đáp án nằm trong `deploy/mini-setup.sh:45` suốt thời gian đó.

---

## 7. Luật rút ra hôm nay — áp cho mọi việc sau

1. **Một tick nói "đột biến" phải nêu PHÉP BIẾN ĐỔI CỤ THỂ và TÊN TEST phải đỏ.**
   Không nêu thì là **lời khai**, không phải bằng chứng. Xếp hạng: *grep/đo trực tiếp*
   > *đột biến có nêu rõ* > *"đột biến N/N ĐỎ" trơn*.
2. **Mọi ca dương phải dùng CHÍNH mẫu/lệnh đã trả rỗng.** Control sai điều kiện không
   chứng minh được gì.
3. **Bằng chứng của một tick phải kiểm TẠI THỜI ĐIỂM nó khẳng định**, không phải tại HEAD.
4. **Thông điệp lỗi của thư viện nội bộ an toàn cho người chạy dòng lệnh với tệp của
   chính mình; KHÔNG an toàn khi nó vào DB/UI của dịch vụ dùng chung.** Đừng chuyển tiếp
   nguyên văn — phân loại bằng **hình dạng**, đừng cắt/che chuỗi (cắt vẫn là chuyển tiếp).
5. **Thêm nhánh vào một hàm thì phải soát lại mọi khẳng định đang đứng trên hàm đó** —
   câu cũ không tự biết phạm vi nó vừa bị nới ra.
6. **Siết quyền trên một nguồn dùng chung thì phải truy MỌI nơi tiêu thụ nó.** Thu hẹp
   `/jobs` suýt làm gãy chốt #7 (bộ lọc "Người tải") — không lỗi, không test đỏ, chỉ là
   một cột bỗng rỗng.
7. **Hàm quyết định "ai thấy gì" hoặc "xoá cái gì" KHÔNG được có mặc định im lặng.**
   Thiếu tham số phải là `TypeError`.
8. **Đo đúng CÁI MÁY và ĐÚNG ĐIỀU KIỆN.** `tail -1` nuốt dòng trước; `pgrep -f` khớp
   chính nó; zsh nở `--include=*.md` nếu không quote; `${PIPESTATUS}` là cú pháp bash.
9. **Phân biệt "có lỗ" với "đang chảy".** Hai lỗi CAO của phase-07 **chưa kích hoạt**
   trên máy thật (0/10 ảnh rỗng, 0/10 video <1s) — bịt trước, và **không báo là đang hỏng**.

---

## Câu chưa giải

1. `~/Library/Logs/videodl.log` trên mini đang ở chế độ quyền nào? Nếu `644` trên máy có
   account đội khác thì mọi thứ chạm stderr là đọc được liên đội.
2. Log **không có dấu thời gian** (uvicorn access logger, `web/app.py` không gọi
   `logging.basicConfig`). Mọi dòng `log.info` **bị vứt hoàn toàn**. Nên đếm lỗi bị nuốt
   bằng bộ đếm trong tiến trình + phơi qua `/healthz`, rẻ hơn dựng logging đầy đủ.
3. Có ai chạy `pytest` **trên mini** không? Nếu có thì lỗ "xoá jar thật" từng là sự cố
   thật chứ không phải giả định.
4. Video TikTok **ngắn hơn 1 giây** chiếm bao nhiêu trong dữ liệu thật? Quyết định độ
   ưu tiên của lỗi ảnh 0 byte.
</content>
</invoke>
