# Bàn giao — Video Desk, 23/09 09:50

**Lane** `e58361ea` (tk3, pid 4825, ttys003) · **điều phối** `uds:/tmp/cc-socks/26888.sock`
**Repo** `/Users/macos/Projects/video-download` · **nhánh `main`**

> ⛔ Thay thế `handoff-260922-1025-videodl-deploy-1-3-utc.md` — file đó **lạc hậu từ 23/09**.
> ⏱ Mọi số đo 22/09 10:00 → 23/09 09:50. Đọc lúc khác thì số về mini, đĩa, job **phải đo lại**.

---

## 1. MỐC

```
main  = 71333fa        mini = 71333fa        (KHỚP)
PRAGMA table_info(jobs) = 15 cột     healthz 200     0 job treo
```

| PR | merge sha | việc |
|---|---|---|
| #2 | `73a2b76` | mẫu số thật · UI cookie · giờ VN · `SO_VONG_DAO_SAU=1` |
| #3 | `2c47634` | **cột `bo_qua`** — báo "bỏ qua N video đã có trong kho" |
| #4 | `25e12e5` | bỏ chọn sau khi bàn giao bộ tự tìm |
| #5 | `71333fa` | **cổng deploy** `2b` + so TÊN label + 5 mã thoát |

**Đường lui từng chuyến** (`bash deploy/rollback-on-mini.sh <thư mục>`):

| mã trên mini | thư mục lui |
|---|---|
| `74e5af3` | `../video-download-truoc-260922-102203` |
| `2c47634` | `../video-download-truoc-260922-174710` |
| `25e12e5` | `../video-download-truoc-260922-180307` |
| `71333fa` | `../video-download-truoc-260923-094816` |

**Bản sao DB:** `web/data/jobs.db.bak-260922-173728` (98304 B, sha `76bfbbb34e0ccfb6…`, đã mở ra
query được 9 job / 86 video). Đó là bản sao **trước** migration `bo_qua`.

---

## 2. MỚI TRONG BỐN PR — thứ người sau dễ không biết là có

### 2.1 Cột `jobs.bo_qua` (#3)

Lọc trùng chạy trên **toàn kho**, nên người tìm sau nhận ít video hơn người tìm trước, và những
video bị bỏ **không hiện ở đâu** trong thư viện của họ. `CHECKLIST-VAN-HANH.md:153-155` đòi báo
thẳng; trước #3 con số chỉ là **biến cục bộ** trong `scraper.py`, không rời khỏi hàm.

- `models.py`: cột + `_add_column_if_missing` + `set_job_skipped()`
- `queue.py::_note_skip`: đếm, ghi **TĂNG DẦN** mỗi lần bỏ (job chết giữa chừng vẫn giữ số)
- `app.js`: `.skip-note`, **nền trung tính** `--surface-alt` — cố ý **không** dùng `--warn-bg`:
  lọc trùng là tính năng chạy đúng, tô vàng dạy người dùng rằng đó là sự cố.

⚠ `already_owned` (mã cũ) chỉ bắn khi bỏ qua **HẾT**. Hai thứ khác nhau, đừng gộp.

### 2.2 Bỏ chọn sau khi bàn giao bộ tự tìm (#4)

Bấm "Tạo bộ tự tìm" xong lựa chọn còn nguyên ⇒ bấm lần nữa mở thêm tab **cùng danh sách cũ** ⇒ nhìn
từ Creative Desk thành "bộ gỡ không được".

**Quyết định có lý do, đừng lật:** chỉ bỏ chọn khi `window.open` trả về tab thật. Popup bị chặn ⇒
**giữ** lựa chọn, vì chưa bàn giao gì cả. Hai đường mẫu trong file **không cùng khuôn** — nút
"Bỏ chọn" clear vô điều kiện, `loaiDaChon` clear **sau khi API thành công**; bàn giao thuộc nhóm
thứ hai. Helper `boChonTatCa()` dùng chung, xoá state **và** gỡ dấu trên thẻ (`loaiDaChon` thoát
được vế hai chỉ vì nó `loadVideos()` dựng lại lưới).

### 2.3 Cổng deploy `2b` (#5)

`kickstart -k` giết tiến trình rồi dựng lại ⇒ job đang chạy chết giữa chừng.

**Cổng này KHÔNG phải để giữ DB đúng** — repo đã lo: `JobWorker.start()` quét `running` →
`interrupted` (`queue.py`), `quet_jar_tam` dọn jar (`app.py:164`). Nó bảo vệ **công của người
dùng**: job 10 chạy **44 phút** và đã đọc **10 trang** index — trang bị trừ vào trần 800/ngày
**ngay khi đọc**, nên cắt ngang là mất cả thời gian lẫn khẩu phần.

Đứng **trước rsync** và **trước lối thoát thử khô**. Hai vị trí đó đều có lý do, xem §5.

Mã thoát: `1` sai máy · `2` cây bẩn · `3` đang tải · `4` nghiệm thu trượt · `5` **phép đo hỏng**.

### 2.4 So TÊN label thay vì đếm (#5)

Trước: `grep -c astronex` rồi chấp nhận `sau >= truoc` ⇒ **mất `videodl` mà mọc label khác thì
XANH**. Nay `ten_label()` trả danh sách sắp xếp, khác thì in `diff` rồi `exit 4`.

---

## 3. ⛔ MẮT USER — CHƯA ĐO, không phải "đã đạt"

User **chưa báo** tới 09:50 ngày 23/09. Bốn mục, chỉ họ trả được:

1. thẻ job có hiện **"Bỏ qua N video đã có trong kho."** không;
2. bấm "Tạo bộ tự tìm" xong lựa chọn có **tự sạch** không —
   ⚠ `window.open` **không sinh request server-side**, log **cấu tạo không thể** trả lời. Đừng ai
   đọc "log không thấy" thành "user chưa bấm";
3. giờ trên thẻ có đúng **giờ VN** không;
4. ba trạng thái **cookie** ở trang Cài đặt.

**Và ca MASS-SKIP vẫn CHƯA ĐO.** Job 10 ra `bo_qua=1` vì user chạy **nguồn mới**
(`tim_thay=60=tong`). Con số 1 chứng minh **bộ đếm chạy**, **không** chứng minh ca đau thật
(*nhận ít hơn hẳn mà không hiểu vì sao*). Ca đó cần chạy lại **cùng một link**. **Đừng giục user** —
họ dùng tool để làm việc, không phải để phục vụ phép đo.

**Cổng deploy cũng mới nghiệm thu MỘT NỬA:** nhánh **CHO QUA** đã chạy trên prod (23/09 09:48,
`job đang chạy/chờ: 0`, label không đổi). Nhánh **CHẶN** (`rc=3`/`4`/`5`) mới chạy ở **bàn thí
nghiệm**, **chưa gặp ca thật**. Lần đầu `rc=3` là **cổng làm việc**, không phải sự cố.

---

## 4. §8.3 — BA SỐ LƯỢT CHẠY THẬT **KHÔNG SINH RA**

Giữ nguyên chữ này từ bàn giao trước, **vẫn đúng**. Vì `SO_VONG_DAO_SAU = 1`, cơ chế đào sâu
**không chạy**, nên vẫn **CHƯA CÓ**: (1) một job music/search ăn bao nhiêu trong trần 800/ngày ·
(2) số lượt cào thật + lý do dừng · (3) có chạm rate-limit TikTok không.

⇒ Hai trần `600s` / `5 vòng` vẫn là **LỰA CHỌN**, chưa phải **hiệu chỉnh**. Mở lại = đổi hằng số
về 5 rồi deploy, và **chỉ khi có người ngồi soi lượt chạy thật đầu tiên**.

⚠ `main` **CÓ** mã vấn đề 2 và nó **KHÔNG chạy**. Đọc code thấy nó đừng tưởng đang bật.

---

## 5. BẪY ĐO — đã trả giá, đừng dẫm lại

- **`sqlite3 -readonly` KHÔNG mở được DB WAL** → `unable to open database file (14)` (cần ghi
  `-shm`). ⚠ **Control giả:** `sqlite3 -readonly <db> 'SELECT 1'` **CHẠY ĐƯỢC** vì `SELECT 1`
  không chạm bảng — dùng nó để "chứng minh cờ ổn" là chứng minh ngược.
- **Truy vấn trượt trả RỖNG, và `[ "" != "0" ]` cũng ĐÚNG** ⇒ cổng chặn **đúng hướng** nhưng
  **phát ngôn sai** ("N job đang chạy" trong khi phép đo hỏng). ⇒ mã `5` riêng.
- **Thử khô phải đi CÙNG ĐƯỜNG với lần thật.** Bản đầu đặt cổng **sau** lối thoát thử khô
  (`:102` vs `:138`) ⇒ thử khô **báo xanh cho một lần chạy thật đáng lẽ bị chặn**, và `rc` **đúng
  bằng 0** ở lần trượt đó. Lộ ra chỉ vì cổng nghiệm thu là *"đi hết tới `2b` và in số"*, không phải
  *"rc=0"*.
- **`${PIPESTATUS[0]}` là bash; zsh dùng `$pipestatus`.** Cần mã thoát thì **bỏ pipe**, `rc=$?`
  ngay sau lệnh.
- **`curl :7870/jobs` từ chính mini trả 401** (Cloudflare Access) ⇒ `grep -c bo_qua` ra 0 cho **cả
  mẫu lành lẫn mẫu hỏng**. Phân định bằng một cột **chắc chắn có** (`tim_thay` cũng ra 0). Đo đúng:
  `models.list_jobs()` qua venv. *(Khe này đã đóng 22/09 18:12: log có `GET /jobs 200` từ trình
  duyệt user.)*
- **Đo `SO_VONG_DAO_SAU` trên mini phải dùng venv:** `./.venv/bin/python`. `python3` hệ thống →
  `ModuleNotFoundError`. Venv là đúng thông dịch vì `run-service.sh:7` gọi chính nó.
- **Đột biến bị bắt bởi assert KHÁC với assert nó nhắm là đột biến CHƯA ĐO XONG.** Ca thật: 3 đột
  biến cùng in `assert returncode == 0` ⇒ có thể node chết cú pháp chứ không phải hành vi sai. Thêm
  `node --check` + đọc dòng `E` thật.

---

## 6. NỢ

**ĐÃ TRẢ 23/09** (giữ lại để thấy nó từng là nợ): ~~`deploy-to-mini.sh` đếm label thay vì so tên~~
→ vá ở `869e5f7`. Luật chốt ở `a479522` từ 21/09 nhưng **chỉ sửa plan**, script vẫn đếm tới
22/09 — ba chuyến deploy hôm đó qua cổng **bằng tay**.

**CÒN NGUYÊN — đừng làm lại** (đã bị bác, có phép đo):
- `COLLATE NOCASE` cho email: **thừa** (7 chỗ `.lower()`).
- "dừng dịch vụ trước rsync": **sai cơ chế** — `deploy-to-mini.sh` `--exclude='web/data'`.
- `videodl.log` 644 "rò liên đội": **sai cơ chế** — `~/Library/Logs` và `~/Library` đều **700**.
- Trần `20/1000/800`: hoãn có chủ đích, điều kiện mở lại = có số TikTok chặn ở đâu (xem §4).
- `tim_thay` chưa tới mắt người dùng: nợ **có chủ đích**, nhãn "Thiếu" đã phủ ca user nêu.

**PHÉP ĐO ĐÃ GHIM, CHỜ CA THẬT — Chromium mồ côi.** `scraper.py:389 pw.chromium.launch()` sinh
tiến trình con; `with sync_playwright()` dọn trong context manager mà **SIGKILL không chạy context
manager**, và `grep` toàn repo + `deploy/` ra **0 chỗ** dọn Chromium mồ côi. **CHƯA ĐO** nó có sống
sót sau `kickstart -k` hay không. Lần tới **bất kỳ** job nào đang chạy trên mini, chạy read-only:

```bash
ps -o pid,ppid,pgid,sess,comm -p <pid uvicorn> $(pgrep -f chrom)
```

Cùng `pgid`/`sess` với uvicorn ⇒ launchd kéo Chromium theo ⇒ **giả thuyết bác**. Khác ⇒ nó **đứng**,
và lúc đó mới đáng bàn cách dọn.

⚠ Bản ghi `DECISIONS.md` 26/08 (*"`kickstart -k` giết child nếu không tách session"*) **KHÔNG áp**
theo hướng "phải tách session": repo này **muốn** con chết cùng cha. Và `start_new_session` **không
xuất hiện** ở đâu trong repo (đo 23/09).

---

## 7. CÂU CHƯA GIẢI

1. **Ca mass-skip** — §3. Câu lớn nhất còn mở.
2. **Nhánh CHẶN của cổng deploy** chưa gặp ca thật — §3.
3. **Ba lỗi 500 `disk I/O error`** trên mini: **0 lỗi mới** từ 22/09 18:12 → 23/09 09:49 (đo: tổng
   dòng log 13536→13736, `ERROR|WARNING` 5→5, `Traceback` 5→5). Mốc soát lại **24/09**.
4. **Đĩa mini** ~3,4 Gi / 85%; `/Users/autotest` 51 G. Ngoài tầm lane (không sudo) — chủ máy quyết.
5. `/search` chập chờn: 16/09 **0/5** · 18/09 **1/1** · 21/09 job 7 ra 0 (trùng, không phải trượt).
   Câu chữ trên trang nói "chập chờn" kèm cả hai số — **đừng** gỡ thành "đã khỏi".
6. **Reboot mini** + **job 50 video ≤50MB** — hai phép T4 chưa chạy, cần hẹn giờ (máy chung Promax).
7. **PR #192 meta-ads** (`feat/videodl-nav-link`, nối Video Desk vào sidebar) — mở từ 15/09, **chưa
   merge**, điều phối đo 22/09 là `CONFLICTING`/`DIRTY`, nhánh tụt 132 commit. **Không thuộc repo
   này**, ghi vì nó là mục 3 trong "định nghĩa tool xong".
