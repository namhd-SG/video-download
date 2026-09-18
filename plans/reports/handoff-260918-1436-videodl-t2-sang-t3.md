# Bàn giao — Video Desk, 18/09 14:36

**Từ** phiên `c4cd3541` (tk3, pid 66914) · **Sang** phiên `ed93f4c8`
**Nhánh** `feat/tiktok-tag-page-support` · **HEAD `7138772`** · cây sạch, đã đẩy
**Test** `319 passed, rc=0` (`.venv/bin/python -m pytest -q`, đo `rc=$?` trực tiếp)

> ⏱ **Mọi số trong file này đo 18/09 10:00–14:20.** Không có mốc tương đối. Đọc lúc khác
> thì số về mini, đĩa, ai đang mở trang **phải đo lại**.

## Cây và máy

| | đường dẫn | ghi chú |
|---|---|---|
| repo tool | `/Users/macos/Projects/video-download` | địa phận của bạn |
| worktree nav | `/Users/macos/meta-ads-wt-videodlnav` | nhánh `feat/videodl-nav-link`, PR #192 chưa merge |
| mini (chạy thật) | `ssh nobi_auto@100.109.39.103` | dịch vụ `127.0.0.1:7870`, domain `video.nobidigital.asia` |

⚠ **Alias `mini` trỏ về CHÍNH MÁY DEV** — luôn dùng `nobi_auto@100.109.39.103`.
⚠ Mini còn chạy **Promax production của đội khác**. Chỉ đọc; không restart, không `chmod`,
không đổi cấu hình toàn máy. Mọi deploy phải kiểm `promax = 302` trước và sau.
⚠ `~/meta-ads-automation` có lane khác. Chạm repo đó thì **worktree riêng từ `origin/main`**,
không dùng checkout chính, **không** chạm `scripts/deploy.sh`.

---

## 0. BA THỨ DỄ SAI NHẤT — đọc trước khi gõ

**a) `timeout` / `gtimeout` KHÔNG có trên máy này.** Dùng nó thì lệnh trả `rc=127` và phép
đo của bạn **chưa từng chạy**. Tôi đã dẫm một lần, suýt nhận một đột biến rỗng là ĐỎ.

**b) zsh KHÔNG có `${PIPESTATUS[0]}`.** Nó in ra rỗng. Cần mã thoát thì **bỏ pipe**, dùng
`rc=$?` ngay sau lệnh.

**c) `DATA_DIR` KHÔNG đọc biến môi trường** (`web/app.py:43` = `BASE_DIR / "data"`). Chạy
thử local mà tưởng `VIDEODL_DATA_DIR` có tác dụng là ghi thẳng vào `web/data` của repo.
Cách đúng: một script nhỏ gán `A.DATA_DIR`/`A.DB_PATH`… rồi `uvicorn.run(A.app)` — mẫu ở
`/tmp/…/scratchpad/run_demo.py`, và để xem giao diện cần đăng nhập thì
`A.app.dependency_overrides[require_user] = lambda: "email@..."`.

---

## 1. Đã XONG và ĐANG CHẠY trên mini (deploy 4, 14:19)

| | commit |
|---|---|
| Hàng đợi + chi tiết lượt + luồng tiến độ chỉ thấy của mình | `780c409` `9119f4c` |
| Thư viện + ảnh xem trước chỉ thấy của mình | `8a0975b` `5c4c0a1` |
| Trang Cài đặt `/settings.html` — cookie **dán hoặc chọn tệp**, hạn mức hôm nay | `1830262` |
| Nút **Xoá** — trash Drive + nhớ đã loại **theo từng người** | `7dc93f7` |
| Metadata mọi nguồn (`extract_info` thay `download`) | `8e6bf2d` |
| Drive trượt **tự thử lại** 3 lần, giãn 2→4s | `259319b` |
| **Tab Quản trị** — phong/bỏ admin, trần từng người | `e8d9541` `bfb3d1a` |
| 6 bản vá review (xem §3) | `1580a88` |
| Câu chữ `/search` nói đúng số đo | `7138772` |

**Trạng thái mini đo 14:19:** astronex 5 · promax 302 · healthz 200 · **6 job / 16 video** ·
bảng `nguoi_dung` 3 hàng, **1 admin** (`namduchoang10@gmail.com`, nguồn "mồi từ cấu hình
máy") · jar cookie 2.

**Lui:** `bash deploy/rollback-on-mini.sh ../video-download-truoc-260918-141922`
**Bản sao DB:** `web/data/jobs.db.bak-260918-1419` (đã kiểm `integrity_check ok`, 6/16).

---

## 2. VIỆC TIẾP THEO — T2 còn một mục

Plan tổng: `plans/260917-1445-plan-tong-de-dong-tool/plan.md` (đọc §T2, §T3, §T4).

### 2.1 Vị trí hàng đợi + huỷ job đang chờ ← **làm cái này trước**
- **Vị trí**: `COUNT(*)` job `pending` có `tao_luc` trước job này. Worker **một luồng**
  (`web/queue.py:349`) nên thứ tự là FIFO nghiêm (`models.py` `claim_next_pending_job`,
  `BEGIN IMMEDIATE`, `ORDER BY tao_luc ASC, id ASC`).
- **ETA**: plan ghi *đừng hứa ETA*. Có số đo cũ ≈6,6 s/video (job 4: 10 video / 65,7 s)
  nhưng n=1, đừng dựng lời hứa trên đó.
- **Huỷ**: chỉ job `pending`, chỉ của chính mình —
  `UPDATE jobs SET trang_thai='cancelled' WHERE id=? AND nguoi_tao=? AND trang_thai='pending'`,
  **đọc `rowcount`**. An toàn vì worker chỉ claim `pending`. Huỷ job **đang chạy** thì cần cờ
  kiểm giữa hai video trong `_JobProgress.note` — **để sau**.
- Route mới ⇒ **lưới `test_every_route_that_takes_an_id_checks_who_is_asking` sẽ ĐỎ** cho tới
  khi bạn khai nó vào `KHONG_CAN_KIEM_CHU`. Đó là tính năng, không phải lỗi.

### 2.2 T3 — nút "Tạo bộ tự tìm" → Creative Desk
Plan gõ-được-luôn: `plans/260917-1436-noi-bo-tu-tim/plan.md`. **Chưa chạm repo meta-ads dòng nào.**
- Đường đã chốt: **không S2S, không service token, không relay JWT**. Nút mở tab sang
  `automation.nobidigital.asia/creative-order/self-bundles?videodesk=<base64url JSON>`, nơi
  người dùng **đã đăng nhập**; bộ tạo bằng phiên của chính họ ⇒ **không có bề mặt mạo danh**.
- Phép đo chịu lực **tôi đã tự kiểm**: folder Video Desk nằm trên Shared Drive
  `0AASy4v5CJAkfUk9PVA` "Creative Astronex", và SA chỉ thấy **đúng một** Shared Drive ⇒
  **cùng SA, cùng ổ** ⇒ copy là việc nội bộ.
- ⚠ **Memory trong repo meta-auto ghi "SA riêng" là SAI/CŨ.** Ai tin dòng đó sẽ đi dựng cả
  bộ máy xác thực cho một lệnh copy.
- **CI không chặn**: `gh api …/branches/main/protection` → **403 Free plan** ⇒ chưa bao giờ
  bật được; meta-auto vẫn merge qua cổng cục bộ `scripts/ci-local/merge-pr.sh`.

### 2.3 T4 — nghiệm thu đóng
- ✅ **reboot mini → dịch vụ tự lên**: đã chứng minh, không cần hẹn lại (máy boot
  16/09 17:41, 5 label lên đủ, bàn giao 21:33 cùng ngày ghi healthz 200).
- ⛔ **hai người bấm CÙNG LÚC** — chưa đo. Hai email đã có nhưng là **một con người**.
- ⛔ **link Drive mở bằng mắt** — mới đo là link *tồn tại*.

---

## 3. REVIEW ĐÃ TÌM RA GÌ — phần đắt nhất, đừng để tái phát

Hai vòng `code-reviewer` + hai vòng `kongming`. Cái bắt được nặng nhất **không phải** lỗi
logic, mà là **lưới giả** và **crash chỉ lộ khi chạy thật**.

**LUẬT D8 (đã vào sổ hạm): chạy app thật là một phép nghiệm thu RIÊNG, không thay được
bằng test.** Hai ca liền trong dự án này:
1. **Bố cục vỡ** — thêm panel thứ ba vào lưới 2 cột, "Hàng đợi" mất chỗ. Đọc code không thấy.
2. **Crash khởi động** — `_lifespan` mồi admin **trước** khi `init_db` tạo bảng; `init_db`
   chỉ được gọi trong `worker.start()` (`queue.py:375`), tức **sau**. DB mini có từ trước
   bảng `nguoi_dung` ⇒ `no such table` ⇒ *Application startup failed*, và mini có
   **`KeepAlive=true`** nên **crash vòng lặp**. **311 test xanh trọn.**

**Ba lưới giả tự bắt được (mẫu để soi tiếp):**
- Test canh rò `sources_for_videos`: ca dựng đã bị lọc ở tầng trước nên hàm cần kiểm **không
  bao giờ được gọi** ⇒ đột biến bỏ lọc vẫn XANH. Ca phân định đúng là **video CỦA TÔI mà job
  người khác cũng trông thấy rồi bỏ qua vì trùng**.
- Test metadata phủ hàm gộp mà **không phủ dây nối**: lùi `extract_info` → `download()` vẫn
  xanh trọn. Đã thêm test chạy qua `download_all` thật.
- Helper test `_moi_admin` có docstring *"làm đúng thứ `_lifespan` làm"* nhưng **làm ngược
  thứ tự**. Chính docstring đó làm tôi tin mình đã phủ.

**Khoá "admin cuối cùng" từng thủng HAI đường** (đã vá ở `1580a88`):
- **đua**: hai admin bỏ quyền nhau, cả hai đọc "còn 2" trước khi ai kịp ghi ⇒ 0 admin;
- **fail-open**: `is_admin` trả `False` khi DB lỗi thoáng qua ⇒ điều kiện canh bị
  **short-circuit** ⇒ lượt bỏ đi thẳng. *Một hàm fail-closed dùng làm tiền đề cho một guard
  thì ở guard đó nó fail-OPEN.*
- Bản vá: kiểm-và-ghi gộp vào **một câu UPDATE có điều kiện con** + đọc `rowcount`; trạng
  thái lấy từ hàng đã fetch, **không hỏi lại DB**.

**Bốn lỗ khác review tìm, đã vá:** trần riêng là **nút chết** (ghi DB, cổng chặn không đọc) ·
PUT một trường **xoá trần kia** · thiếu **backfill** người dùng cũ (admin mở tab thấy trống,
404 khi đặt trần) · docstring SSE nói *"no query"* trong khi mỗi nhịp đánh DB.

---

## 4. LUẬT ĐÃ ÁP — giữ, đừng nới

1. **Deploy phải xin user gật từng lần.** Không tự bấm, kể cả khi mọi cổng xanh.
2. **Nghiệm thu phải LẬT.** `healthz 200` trả 200 cả trước lẫn sau ⇒ **không** nằm trong
   danh sách. Và **đo trạng thái TRƯỚC của marker** — marker đã tồn tại sẵn cho dương tính giả.
3. **Chuyến có migration ⇒ sao lưu DB, và kiểm bản sao ĐỌC ĐƯỢC** (`integrity_check` + đếm
   hàng), không chỉ kiểm có file.
4. **Diễn tập `_lifespan` trên bản sao DB của mini trước khi deploy** (D8). Lần này nó đoán
   đúng từng con số máy thật.
5. **Không ship nút chết.** "Phân tích nội dung" **KHÔNG làm** — user chốt để sau.
6. **Mỗi hạng mục phải có đột biến ĐỎ.** Không nêu được phép biến đổi cụ thể thì đó là lời
   khai, không phải bằng chứng.
7. **Cắt quy trình:** một nơi ghi trạng thái (plan tổng), bàn giao ngắn, **không** report
   riêng từng phase, `code-reviewer` **chỉ** cho đường quyền/xoá/cookie/Drive.
   Ngân sách: dòng `plans/` ≤20% dòng code mỗi ngày. *(3 ngày đầu là 81% — đó là thứ user bực.)*

---

## 5. CHỜ USER

1. **Trần mặc định cho người mới** — đề xuất **giữ 20/1000/800**, user chưa chốt. Nền: trần
   chưa lần nào chạm; cái chặn thật là **IP văn phòng** ⇒ số cần thêm là trần **toàn công ty**.
   ⚠ **CHƯA ĐO:** TikTok chặn ở ngưỡng nào — không ai trong hạm có số đó.
2. **Hai người bấm cùng lúc** (T4) — cần hai người thật.
3. **Nút "Xoá"**: user đã dùng thật, 5 hàng đã loại. Chưa ai kiểm **Thùng rác Drive bằng mắt**.

## 6. SỰ THẬT BỊ BÁC TRONG NGÀY — đừng để sống lại

- **"`/search` chết"** → hết đúng. 16/09: 0/5 lượt; 18/09: **1/1**. Câu chữ trên trang đã
  đổi thành *"chập chờn"* kèm cả hai con số — **đừng** gỡ thành "đã khỏi" (n=1).
- **"Metadata trống là lỗi đường ghi"** → SAI. Nguồn **music cấu tạo không mang** metadata;
  chỉ index hashtag có. Nay yt-dlp cấp cho **mọi** nguồn: đo trên mini `tag/tutorial` **5/5**,
  `search` **1/1**, music cũ vẫn 0/10 (đúng).
- **"Phải chờ CI meta-auto tới 01/10"** → SAI, tôi dựng một bức tường không có thật. Hết
  quota CI chặn *merge có cổng xanh*, **không** chặn viết code, không chặn deploy.
- **"env `VIDEODL_ADMIN_EMAILS` rỗng"** → số cũ. User đặt lúc **10:27 ngày 18/09**.

## 7. CÂU CHƯA GIẢI

1. `videodl.log` trên mini là **644** trên máy có account đội khác ⇒ mọi thứ chạm stderr đọc
   được liên đội. Đã ghi nợ, chưa ai sửa. **Đừng `chmod`** — máy có Promax prod.
2. Log **không có dấu thời gian** ⇒ không định vị sự kiện theo giờ được. Cách đã dùng: đếm
   dòng tương đối với `Application startup complete` gần nhất.
3. **3 lần HTTP 500** (`disk I/O error`, `unable to open database file` trên
   `PRAGMA journal_mode=WAL`) — cả 3 nằm **trước** lần khởi động gần nhất, tức bản cũ. Giả
   thuyết: cửa sổ rsync lúc deploy. Cách triệt: **dừng dịch vụ trước khi rsync**
   (`deploy-to-mini.sh:104-110`). Chưa sửa — sửa script deploy giữa lúc đang deploy là tự mở
   thêm một cửa.
4. Cloudflare Access có luôn phát `email` viết **thường** không? Chưa đo. Ảnh hưởng: tên jar
   cookie là `sha256(danh tính thô)`, còn bảng `nguoi_dung` lưu bản thường.
   ⚠ **Đừng sửa bằng cách thêm `.lower()` vào `_identity_from`** — sẽ **mồ côi mọi jar cookie
   đang có trên mini** và cắt mọi người khỏi thư viện cũ của họ. Đường an toàn là
   `COLLATE NOCASE` cho cột `email`.
