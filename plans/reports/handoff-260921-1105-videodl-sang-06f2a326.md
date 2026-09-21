# Bàn giao — Video Desk, 21/09 11:05

**Từ** `ed93f4c8` (tk3, pid 31888) · **Sang** `06f2a326` (tk3, pid 22660, socket `uds:/tmp/cc-socks/22660.sock`)
**Repo** `/Users/macos/Projects/video-download` · **nhánh** `fix/log-path-and-name-list`
**Điều phối hạm**: `uds:/tmp/cc-socks/38251.sock` (macos-36). Lane cổng: `9325.sock`.

> ⏱ Mọi số đo 21/09 09:40–11:00. Đọc lúc khác thì số về mini, đĩa, job **phải đo lại**.

---

## 0. BA THỨ DỄ SAI NHẤT

**a) `tail`/`head` khi soi bằng chứng là tự bịt mắt.** Tôi dẫm **hai lần** hôm nay:
đếm label launchd ra 4 rồi suýt báo động mất dịch vụ đội khác (thật ra 5); và `WHERE id>=7`
tưởng mất job 7 (thật ra `tail -12` cắt). Đếm xong thì **liệt tên**, đừng tin con số.

**b) `git status` sau `regen.sh` KHÔNG đo được "map có khớp HEAD không".** Nó trả lời
*"lệnh vừa rồi có ghi gì không"*. Phép đo đúng là `bash scripts/repo-hygiene-check.sh`.
Tôi suýt lặp vô hạn reset-regen-commit vì đọc sai dụng cụ này.

**c) `${1^^}` là bash 4+; mini chạy bash 3.2.** `timeout`/`gtimeout` **không có** trên máy
dev. zsh **không có** `${PIPESTATUS[0]}`. Cần mã thoát thì bỏ pipe, `rc=$?` ngay sau lệnh.

---

## 1. ĐANG CHẠY

| | |
|---|---|
| mini | `nobi_auto@100.109.39.103`, dịch vụ `com.astronex.videodl`, `127.0.0.1:7870` |
| bản trên mini | `b550a1b6` (deploy 21/09 09:56, rc=0) |
| `origin/main` repo này | `b2eb6e2` (PR #1 merged 21/09, 87 commit) |
| meta-ads prod | `a883b183` — PR #202 đã merge + deploy, nút "Tạo bộ tự tìm" **chạy thật hai đầu** |

⚠ Mini **dùng chung với Promax của đội khác**. Không `bootout`, không `chmod`, không dừng
dịch vụ nào. Mọi chuyến deploy phải kiểm `promax = 302` **trước và sau**, và so **danh sách
TÊN** label, không so số đếm.

---

## 2. VIỆC KẾ TIẾP — 3 vấn đề user giao 11:05, CẦN BRAINSTORM TRƯỚC KHI GÕ

User nói rõ: *"cần ak/brainstorm"*. Đừng nhảy vào code.

### 2.1 `tong` bị ghi đè bằng số SAU khi lọc trùng ⇒ hiển thị nói dối về mục tiêu

`web/queue.py:352` → `models.set_job_total(db_path, job_id, len(refs))`, mà `refs` là
danh sách **đã lọc trùng**. Hệ quả: user xin 50, 30 trùng ⇒ job hiện **`20/20`**, trông
như "xong đủ", trong khi mục tiêu 50 **không đạt**. Thông tin "user xin bao nhiêu" **bị mất
khỏi DB** ngay tại dòng đó.

`jobs.so_luong` (cột) giữ số user xin — kiểm lại xem nó có còn đúng không, và vì sao UI
không dùng nó.

### 2.2 Nhánh không-hashtag KHÔNG đào sâu để bù video trùng — gốc của "mục tiêu 50 bị sai"

Đây là yêu cầu chính của user: **xin 50 thì phải tải đủ 50 video MỚI**, trùng thì bỏ qua
và quét tiếp, thiếu thì **báo rõ vì sao**.

Hiện trạng đo được, hai nhánh xử lý **khác hẳn nhau**:

- **Hashtag** (`hashtag_enumerator.py:236,244`): *"`added` (chưa có trong thư viện) mới
  đếm về `max_videos`"* ⇒ **đã đào sâu đúng ý user**, lật trang tới khi đủ N mới.
- **Search / music / profile** (`web/queue.py:173-190`): `scrape_music_page` trả **một
  danh sách đã hoàn tất**, lọc trùng **một lần ở cuối**. Không có vòng lật trang ⇒ không
  bù được.

Comment ngay tại chỗ đã nói thẳng: *"The hashtag path filters page by page, so 'go deeper
until N new' works; the scrapers below hand back one finished list, so they are filtered
once at the end."* ⇒ **Biết từ đầu, chưa ai sửa.**

**Câu brainstorm thật sự khó** (đừng bỏ qua): `scrape_music_page` có phân trang được
không? Nếu nó là Playwright cuộn tới hết thì "đào sâu" nghĩa là cuộn thêm — tốn thời gian
và **chạm rate-limit TikTok**, thứ đã gây ra `/search` chập chờn. Cân nhắc trần thời gian
+ trần số vòng, và **báo user hiện trạng** thay vì im lặng.

User đã nêu sẵn ba ca cần phân biệt khi thiếu:
1. link đó không đủ video;
2. đã tải hết video của thị trường đó;
3. quét trùng quá nhiều / quá thời gian.
Và muốn **popup + đề xuất**, không phải một dòng chữ lặng lẽ.

⚠ Liên quan trực tiếp tới bản vá tôi vừa làm (`8c38650`): nó mới chỉ **nói ra lý do**
(`already_owned` / `source_empty`) chứ **chưa bù cho đủ N**. Đừng coi nó là xong việc 2.2.

### 2.3 UI cookie không cho biết đang dùng cookie nào, còn sống không

User: *"nhìn vô không biết là có cookie chưa, chán lắm"*. Muốn: hiện **đang dùng cookie
tài khoản nào**, **trạng thái** (active/hết hạn), và **nút xoá để thay cookie mới**.

Nền có sẵn: `GET /me/cookie` → `_trang_thai_cookie(nguoi_tao)` (`web/app.py:377`) đã trả
trạng thái bằng **mã đóng + mốc thời gian**, cố ý **không** trả byte nào của jar. Bốn mã
cookie đã có câu chữ tiếng Việt trong `app.js` (`cookie_khong_doc_duoc`, `cookie_rong`,
`cookie_chua_dang_nhap`, `cookie_het_han`) — **dùng lại, đừng viết mới**.
Trang Cài đặt là `web/static/settings.html` + `settings.js`.

⚠ Tên tệp jar là `sha256(danh tính THÔ)` — **đừng** thêm `.lower()` vào `_identity_from`,
sẽ mồ côi mọi jar đang sống trên mini.

---

## 3. VỪA LÀM XONG HÔM NAY (chưa deploy: `8c38650`)

| commit | việc |
|---|---|
| `b550a1b` | log có dấu thời gian — **đã lên mini**, vá lần 2 mới ăn (xem §4) |
| `5ca32ae` | `scripts/do-nghiem-thu-t4.sh` — bộ đo T4, chỉ đọc, 3 nhánh đã chạy thật |
| `4e140bc` | bỏ ngưỡng đĩa "<100MB" khỏi plan + nguồn phase-03 |
| `a479522` | so **danh sách tên** label thay vì đếm số (phase-02 + plan) |
| `9e4ecf7` | ghi nợ log-644 **BỊ BÁC** vào plan |
| `06e51bb` | report nghiệm thu T4 |
| `8c38650` | **CHƯA DEPLOY** — search/music/profile nói lý do khi ra 0 video |

**PR #2** (`fix/log-path-and-name-list` → main) đang **draft**, chứa 6 commit trên.

---

## 4. BÀI HỌC ĐẮT NHẤT HÔM NAY — đọc trước khi sửa gì

**Vá `190ee74` ship ra mà KHÔNG ĂN, và test XANH.** Dấu thời gian log: tôi đặt format ở
**root logger**, test dựng "root đã có handler" rồi gọi hàm vá ⇒ xanh. Nhưng thực tế
**uvicorn dựng log config SAU khi module app được import**, cấp cho `uvicorn.access` handler
riêng + `propagate=False` ⇒ format ở root **không bao giờ chạm tới** nơi sinh ra gần như
mọi dòng. Đo sau deploy: **0/6800 dòng** có giờ.
Test diễn **đúng cơ chế, sai THỨ TỰ**. Vá thật (`b550a1b`) chạy trong `_lifespan` — điểm
đầu tiên chắc chắn sau cấu hình của uvicorn.
⇒ **Marker file chỉ chứng minh MÃ CÓ MẶT, không chứng minh HÀNH VI ĐỔI.** Nghiệm thu phải
là chính thứ cần thay đổi.

**Tôi báo động sai một lần và nó làm hoãn cả buổi nghiệm thu.** Bốn mốc đĩa cùng chiều
giảm ⇒ tôi ngoại suy *"đầy trong 15 phút"*. Đo tiếp: đĩa **tăng** 4,3Gi rồi về 3,2Gi, dao
động ±1GB/phút. **Bốn điểm cùng chiều không phải một xu hướng.**

**Commit system-map (repo meta-ads)** — ba vế: không amend/squash được · phải là commit
**CUỐI** · kiểm bằng `repo-hygiene-check.sh`, **không** bằng `git status`.

---

## 5. CHỜ USER

1. **Ba mục mắt của T4** (chưa tick): mở link "Mở thư mục Drive" · Thùng rác Drive có 5
   video xoá 18/09 không · đứng ở project `aldenesk-01` bấm "Tạo bộ tự tìm" xem câu báo
   lỗi **có bảo đổi project** không. Mục 3 là cách **duy nhất** kiểm bản vá `f89bb9aa`
   bằng **hành vi**; tới giờ mới kiểm được bằng cấu tạo.
2. **Deploy `8c38650`** lên mini — chưa xin.
3. **Merge PR #2** — đang draft.
4. **Trần 20/1000/800**: **hoãn có chủ đích** (đã ghi sổ). Điều kiện mở lại: có số TikTok
   chặn ở ngưỡng nào. Đừng hỏi lại user khi chưa có số đó.

## 6. NỢ ĐÃ BỊ BÁC — ĐỪNG LÀM LẠI (đã ghi trong plan tổng)

- `COLLATE NOCASE` cho email: **thừa**, 7 chỗ `.lower()` phủ mọi đường ghi/đọc.
- "dừng dịch vụ trước rsync": **sai cơ chế**, `deploy-to-mini.sh:42` `--exclude='web/data'`
  ⇒ rsync không chạm DB lần nào.
- `videodl.log` 644 "rò liên đội": **sai cơ chế**, `~/Library/Logs` và `~/Library` đều
  **700**. Rủi ro thật là `autotest` **là admin** ⇒ `chmod`/đổi đường log không đổi bit
  nào. Chữa thật = lọc nội dung nhạy cảm tại nguồn, hoặc bàn quyền admin — **user/chủ máy**.

## 7. CÂU CHƯA GIẢI

1. **Ba lỗi 500 (`disk I/O error`)** trên mini: nay đo được theo giờ nhờ log có dấu thời
   gian, nhưng **chưa có sự kiện mới**. Mốc soát lại **24/09**.
2. **Đĩa mini**: còn ~3,4 Gi / 85% dùng; `/Users/autotest` **51 G**. Tồn kho thấp, **không
   phải** rò rỉ đang chảy. Ngoài tầm lane (không sudo) — chủ máy quyết.
3. `/search` chập chờn: 16/09 **0/5** lượt · 18/09 **1/1** · 21/09 job 7 ra 0 (trùng, không
   phải trượt). Câu chữ trên trang nói "chập chờn" kèm cả hai số — **đừng** gỡ thành "đã khỏi".
