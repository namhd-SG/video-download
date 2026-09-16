---
phase: 5
title: "Cookie từng người + phân quyền"
status: pending
priority: P1
effort: "1-2d"
dependencies: [2, 4]
---

# Phase 5: Cookie từng người + phân quyền

## ✅ TÁCH LÀM HAI, USER CHỐT 14/09

| | vào MVP? | nội dung |
|---|---|---|
| **P05a — danh tính** | **CÓ** | `nguoi_tao` lấy từ JWT Cloudflare Access, không từ body HTTP. Tên file cookie = `sha256(user_id)` — chặn traversal bằng **cấu tạo**, không bằng regex lọc |
| **P05b — mỗi người tự dán cookie** | sau MVP | trang "Cookie của tôi", TTL, dọn jar tạm, tiền-kiểm |

**MVP dùng cookie của user (đã đưa 14/09).** `[ĐO 14/09 — KHÔNG phải số hiện tại]`
cookie phiên còn hạn tới **14/11/2026**; `/search` với cookie **ăn ngay lượt đầu,
19/20 video thật** — so với **1/12 lượt** khi không cookie.

⚠ Ba con số đó là ảnh chụp ngày 14/09 và **chưa đo lại lần nào**. Tính tới 16/09 thư
mục cookie trên mini **rỗng** — không có cookie thật nào để đo, nên tiêu chí *"/search
5 lượt có cookie"* ở dưới vẫn mở. Ai đọc mục này về sau: **đừng dẫn 19/20 như tình
trạng hôm nay**; nó nói về một cookie đã đưa vào máy ngày 14/09.

⚠ Cookie đó sẽ **nằm trên máy công ty** trong suốt MVP. Quyền `0600`, không vào log,
không vào git (`web/data/` đã ignore — đo: `git check-ignore` 3/3 ✓). Đổi sang account
phụ lúc nào cũng được, chỉ là thay file.

## Overview

Anh chốt 10/09: **mỗi người tự dán cookie của mình**, không dùng account chung. Điều
đó biến server thành nơi chứa credential của nhân viên — phải xử lý cẩn thận, và
phải khai rõ đang tạm đè luật nào.

## LUẬT ĐANG TẠM ĐÈ — khai rõ, không im lặng

`model-routing-ladder.md` ghi: *"Dữ liệu khách / PII / **secret**: LOCAL ONLY"*.
`resource-routing-ladder.md` ghi máy công ty *"chỉ nhận synthetic + code/repo của
user; không data khách"*.

Cookie đăng nhập TikTok của từng nhân viên **là secret**. Đặt nó trên
`autos-mac-mini` vi phạm cả hai điều trên.

**Anh đã chốt đè ngày 10/09 qua `AskUserQuestion`**, sau khi tôi nêu rõ xung đột.
Phase này ghi lại để người sau đọc code không tưởng đây là sơ suất. Cần ghi một dòng
vào `~/agy-ws/DECISIONS.md` kèm ngày và lý do.

## Requirements

- Functional: mỗi người dán cookie của mình; job của A dùng cookie của A.
- Non-functional: cookie không lọt sang người khác; không ghi cookie ra log; xoá
  được; có hạn.

## Architecture

```
cookie lưu theo người dùng, KHÔNG phải biến toàn cục
  - đặt trong thư mục 0700, tên theo user-id
  - job mang theo user-id, lấy đúng cookie của người đó
  - TTL 14 ngày rồi buộc dán lại (cookie TikTok tự hết hạn trước đó)
```

## ⚠ SỬA SAU THẨM ĐỊNH 14/09 — ba lỗ của bản đầu

**1. Không được tin header danh tính.** Bản đầu viết *"đọc danh tính từ header
Access"*. Header **giả được** bởi bất kỳ tiến trình nào trên máy — mà máy này có ≥2
user, Promax, ollama, và một account khác giữ 194 GB. Phải **kiểm JWT**
`Cf-Access-Jwt-Assertion` theo bộ khoá công khai của team Cloudflare, và kiểm cả
trường AUD. Bind 127.0.0.1 **không** phải biện pháp bảo vệ khi máy có nhiều người dùng.

**2. Cookie hỏng thì job rơi về anonymous IM LẶNG.** Đã kiểm tại nguồn
(`downloader.py:183-184`): exception khi đọc cookie bị nuốt thành `log.warning`, rồi
job chạy tiếp **không cookie** — trần guest ~28 video, và người dùng không hề biết vì
sao thiếu. Đúng lớp *"dụng cụ rơi về mặc định phải BÁO"*. Lớp web phải **tiền-kiểm**
file cookie và **FAIL job**, không để nó âm thầm chạy tiếp.

**3. `profile_dir` là kênh rò cookie chéo thứ hai.** `scraper.py` dùng
`launch_persistent_context` — profile đó giữ cookie qua các lượt. Test trên file
cookie **không nhìn thấy** kênh này. Lớp web phải **luôn** truyền `profile_dir=None`,
và khoá bằng test.

**4. Jar cookie tạm sống sót qua SIGKILL.** `downloader.py` xoá file Netscape tạm
trong `finally`, nhưng `KeepAlive` restart bằng SIGKILL thì `finally` **không chạy**
⇒ credential nằm lại trong thư mục tạm. Phải dọn theo glob lúc khởi động.

**Bẫy đã đo và phải tránh:** trong `claude_bridge.py` từng có ca biến môi trường
toàn cục **đè** cấu hình per-lane, làm hai lane chạy chung một credential mà **hỏng
IM LẶNG** — mất 7 ngày mới tìm ra. Ở đây cũng vậy: nếu có bất kỳ đường nào đọc
cookie từ biến toàn cục hay file dùng chung, nó sẽ thắng và không ai biết.

Phân quyền: cloudflared hỗ trợ Cloudflare Access đặt trước hostname — dùng nó thay
vì tự viết đăng nhập. Nếu meta-auto đã có nhóm người dùng thì dùng lại danh sách đó.

## Related Code Files

- Create: `web/auth.py` — nhận diện người dùng (Cloudflare Access header)
- Create: `web/cookies.py` — lưu/đọc/xoá cookie theo người dùng
- Modify: `web/queue.py` — job mang `nguoi_tao`, lấy đúng cookie của họ
- Modify: `src/tiktok_music_downloader/downloader.py` — **KHÔNG sửa**; nó đã nhận
  `cookies_path`, chỉ cần truyền đúng đường dẫn

## Implementation Steps

1. Access đã bật từ Phase 04. Ở đây **kiểm JWT**: lấy bộ khoá công khai của team,
   xác thực chữ ký và AUD của `Cf-Access-Jwt-Assertion`. Từ chối request không có
   JWT hợp lệ, **kể cả khi header email trông đúng**.
2. `web/cookies.py`: ghi file `0700`, tên theo hash của user-id, kèm mốc hết hạn.
   Dọn jar tạm còn sót lúc khởi động (glob theo tiền tố tạm của `downloader.py`).
3. Trang "Cookie của tôi": dán JSON, xem hạn, xoá. Kèm hướng dẫn Cookie-Editor
   (repo đã có nội dung này trong README).
4. Job mang `nguoi_tao`; `download_all` nhận `cookies_path` của đúng người.
5. **Rà soát mọi đường đọc cookie**: grep toàn bộ codebase xem có chỗ nào đọc từ
   biến môi trường hay đường dẫn cố định. Có thì bịt — đó là chỗ credential lọt.
6. Soát log: cookie **không được** xuất hiện trong log hay thông điệp lỗi. Đã có
   tiền lệ thông điệp lỗi nhúng nguyên đầu vào rồi rò 16 tên khách thật.

## Success Criteria

- [x] A và B cùng chạy job → bắt **tham số `cookies_path` thật sự truyền vào
      `download_all`** của job B, khẳng định nó là file của B.
      — XONG 16/09 `0fa50a0`. `test_job_of_b_downloads_with_bs_cookie_not_as`
      bắt giá trị tới `download_all` trong lúc job của B chạy. Ca âm:
      `test_a_user_with_no_jar_downloads_anonymous_never_someone_elses` —
      người chưa có jar phải chạy ẩn danh, KHÔNG rơi sang jar đang có.
      ⚠ Tiêu chí cũ *"grep log/DB không thấy cookie của A trong job B"* là **xanh trá
      hình**: theo thiết kế cookie **không bao giờ** vào DB, nên grep luôn rỗng dù
      code có lẫn cookie hay không
- [x] **Đột biến:** bỏ tham số `nguoi_tao` khỏi job ⇒ test phải ĐỎ
      — XONG 16/09. Ghim cứng `cookies_path_for_user(cookies_dir, "khach")`
      thay `job["nguoi_tao"]` ⇒ ĐỎ đúng `test_job_of_b_downloads_with_bs_cookie_not_as`,
      56 test còn lại xanh; hoàn nguyên, cây trùng khít HEAD.
- [x] **Đột biến:** gửi header `Cf-Access-Authenticated-User-Email` **giả**, không
      kèm JWT hợp lệ ⇒ phải **401**. Bỏ bước kiểm JWT ⇒ test phải ĐỎ
      — XONG 15/09, `web/auth.py`. Đo hai tầng:
      (a) test `test_forged_email_header_without_jwt_is_401` + ca dương
      `test_same_request_WITH_a_valid_jwt_passes` (cùng request, chỉ khác JWT);
      (b) trên MINI sau khi deploy: header email giả → **401**, JWT rác → **401**,
      không header → **401**, `healthz` vẫn **200**. Trước deploy cùng endpoint
      trả **200** — đó là ca âm chứng minh phép đo có sức phân định.
      Đột biến đã chạy, 4/4 ĐỎ: gỡ `Depends(require_user)` · `verify=False` ·
      bỏ xử lý `aud` dạng list · bỏ tiền-kiểm "chưa cấu hình".
- [x] **Đột biến:** đưa file cookie hỏng/hết hạn ⇒ job phải **FAIL**, không được
      chạy anonymous. Bỏ tiền-kiểm ⇒ test phải ĐỎ
      — XONG 16/09 `602a4de`. Gốc: `download_all` nuốt lỗi cookie thành một
      dòng log rồi chạy tiếp KHÔNG cookie. Tiền-kiểm ở `process_job` phân biệt
      **bốn** ca vì bốn cách chữa khác nhau: đọc không được · không có cookie
      nào · **không có cookie đăng nhập** (phiên khách — ca âm thầm nhất) ·
      hết hạn. Cookie phiên (`expires=0`) vẫn hợp lệ. Không có jar thì KHÔNG
      phải lỗi (ẩn danh có chủ đích) — có ca âm khoá.
      ⚠ Lý do hỏng **không được trích nội dung tệp**: `_load_cookies` nhúng
      `raw[:80]` (`scraper.py:82,91`), mà với bản xuất Header String thì 80 ký
      tự đầu CHÍNH LÀ token, và chuỗi đó đi vào `ly_do_dung` rồi lên UI.
      `test_the_failure_reason_never_quotes_the_cookie_file` khoá ca này.
      Đột biến gỡ khối tiền-kiểm ⇒ **4 test ĐỎ**, 58 xanh.
- [x] **Đột biến:** mọi lời gọi scraper từ lớp web phải có `profile_dir=None`;
      truyền một giá trị khác ⇒ test phải ĐỎ
      — XONG 16/09. Test đã có sẵn nhưng tên test không phải bằng chứng: đã
      đổi `profile_dir=None` → `"/tmp/hoso-dung-chung"` ⇒ ĐỎ đúng
      `test_scraper_call_always_passes_profile_dir_none`; hoàn nguyên.
- [x] `grep -ri "sessionid\|sid_tt\|cookie" ~/Library/Logs/videodl.log` → **rỗng**,
      và kèm **ca dương** chứng minh grep hoạt động (thử với chuỗi có thật)
      — XONG 16/09, đo trên MINI, log thật 1 787 dòng
      (`/Users/nobi_auto/Library/Logs/videodl.log`):
      `sessionid` 0 · `sid_tt` 0 · `sessionid=` 0 · `Set-Cookie` 0 ·
      `tt_csrf_token` 0 · `msToken` 0. Chữ "cookie" có **1** dòng — đã đọc
      tận nơi: đó là tên cờ `--cookies` trong một câu hướng dẫn, không phải
      tên/giá trị cookie. **Ca dương cùng lệnh cùng mẫu** trên tệp chắc chắn
      có ⇒ 1/1, nên các số 0 kia là rỗng thật.
- [x] File cookie quyền `0700`, người dùng khác trên máy đọc không được
      — ĐÃ SỬA 15/09, và nó **đang hỏng** trước đó. Đo trên mini:
      `web/data` `web/data/cookies` `web/data/downloads` = **755**,
      `jobs.db` = **644**, trên máy có tài khoản thứ hai (`autotest`).
      Chưa có file cookie nào nên chưa rò gì, nhưng MVP đặt cookie đúng vào
      thư mục đó.
      ⚠ **Bàn giao 260915-1019 ghi SAI chỗ để dữ liệu**: nó bảo dữ liệu chạy
      nằm ở `~/.local/share/videodl/{downloads,cookies}` quyền 700 — thư mục
      đó **rỗng, không dùng**. `app.py` hardcode `web/data/`.
      Sửa ở CẢ HAI đầu, vì chmod tay thì lần deploy sau lại 755:
      `app.py::prepare_data_dir` mkdir **rồi `os.chmod` tường minh**
      (`mkdir(mode=)` bị umask 022 che, và bị bỏ qua hoàn toàn khi thư mục đã
      tồn tại — đúng ca gặp trên mini).
      Sau deploy + restart: **700/700/700/600**. Đột biến bỏ `chmod` ⇒ ĐỎ.
      Còn nợ: quyền của **từng file cookie** (0600) — chưa đo được vì chưa có
      file nào; thuộc P05b khi mở cho từng người dán.
- [x] Giết tiến trình bằng SIGKILL giữa job ⇒ khởi động lại **không còn** jar cookie
      tạm nào sót trong thư mục tạm
      — XONG 16/09 `e5df58e`. Gốc: jar Netscape tạm mang cookie dạng văn bản
      thuần, xoá trong `finally` — mà SIGKILL không chạy `finally`, và launchd
      `KeepAlive=true` dựng lại ngay, nên mỗi lần bị giết để lại thêm một bản
      đọc được, vĩnh viễn. Lớp web giờ sinh jar trong thư mục 0700 của CHÍNH
      nó (`web/data/tmp`) rồi quét sạch lúc khởi động, trước khi worker chạy.
      Để jar ngoài thư mục tạm hệ thống mới khiến việc quét an toàn: công cụ
      dòng lệnh dùng cùng tiền tố trên cùng máy. Ca âm: bộ quét chỉ lấy jar
      cookie, tệp khác còn nguyên. Đột biến gỡ lời gọi quét ⇒ ĐỎ.
- [ ] `/search` đo lại **với cookies, 5 lượt** — báo tỉ lệ thật, không hứa trước

## Cap số job mỗi ngày — USER CHỐT 14/09

Không phải để tiết kiệm băng thông, mà để **giảm rủi ro khoá account**. Đưa tool lên
mini nghĩa là mọi lượt của cả team dồn về **một IP**; TikTok thấy cùng một IP + nhiều
account + chạy đều đặn = chữ ký trang trại bot. Rủi ro không phải một nick bị khoá mà
là **cả nhóm account cùng IP bị đánh dấu một lượt**.

Cách làm: một câu `COUNT` trên `jobs` theo `tao_luc` + `nguoi_tao`, chặn ở `POST /jobs`
cùng chỗ với `should_reject_new_job()`. ~10 dòng.

### Bốn tham số — USER CHỐT 15/09 18:40, THI CÔNG XONG `e9e5b2d`

Chốt 14/09 nói **có** trần nhưng không nói số, đơn vị, phạm vi hay cửa sổ; bốn ô trống đó
đứng nguyên tới 15/09. Điền im lặng ô nào cũng là tự đặt ngưỡng hộ user, nên đã hỏi.

| tham số | chốt | ghi chú |
|---|---|---|
| số | **20** | **KHÔNG có nhịp dùng thật đứng sau**: `jobs.db` máy dev đếm được **0** job lúc chọn. Đây là vạch xuất phát, xem lại khi mini có vài tuần dữ liệu |
| phạm vi | **mỗi cookie** ("tạm thời 1 cookie trước") | không phải mỗi người, không phải cả máy |
| cửa sổ | **ngày giờ VN**, reset nửa đêm | |
| đơn vị | **job** | ⚠ chưa bó số VIDEO — xem dưới |

**Vì sao khoá vào cookie chứ không phải `nguoi_tao` như câu 14/09 viết:** hôm nay
`nguoi_tao` **luôn** là `"khach"` (`web/cookies.py`, client không gửi được trường này nữa
từ khi nó bị gỡ làm véc-tơ path-traversal) ⇒ đếm theo người hay theo cookie **ra cùng một
số**. Nhưng ngày phase-05 nối danh tính thật, bản đếm-theo-người sẽ **âm thầm đổi nghĩa**
thành trần mỗi người, trong khi thứ TikTok khoá là cái nick sau cookie. Cùng con số, khác
mệnh đề.

**Mã trả về 429, không dùng lại 503.** 503 của `should_reject_new_job` nghĩa "máy đang
kẹt, lát nữa thử lại"; trần ngày chỉ hết vào nửa đêm. Chung mã là chỉ sai cách chữa.

**Job hỏng vẫn tính** — nó đã tiêu lượt gọi TikTok, thứ đang được chia khẩu phần.

⚠ **Lỗ đã biết, CHƯA bịt:** trần đếm **job**, mà một job xin tới `MAX_SO_LUONG = 2000`
video (`web/app.py:48`). 20 job × 2000 = 40 000 video/ngày vẫn lọt trần. Muốn bó lưu lượng
thật thì phải trần trên `SUM(so_luong)`. Chưa chốt, chưa làm.

Ba biện pháp khác đã cân, xếp theo hiệu quả/công:
1. cap job/ngày — **làm trong MVP**
2. dùng account phụ thay account chính — **0 dòng code**, hiệu quả nhất; user chọn
   dùng account của mình cho MVP, đổi sau chỉ là thay file
3. `--proxy` cho nguồn cần cookie — CLI đã hỗ trợ; chỉ làm nếu (1)+(2) chưa đủ

Thứ **không** giảm rủi ro dù nghe có vẻ: chạy chậm hơn nữa. Tool đã jitter 2-4s + nghỉ
60s mỗi 50 video; chậm thêm chỉ kéo dài phiên, không đổi chữ ký hành vi.

## Risk Assessment

**Cookie lọt chéo giữa người dùng.** Hỏng âm thầm và hậu quả nặng (account nhân viên
bị khoá, hoặc hành vi của A bị gán cho B). *Phản ứng:* test đột biến ở trên, cộng
rà soát đường đọc ở bước 5.

**Cookie rò vào log.** *Phản ứng:* soát chủ động + ca dương cho phép grep.

**`/search` vẫn không chạy dù có cookies.** Đo 11/09 không cookies: ăn **1/12**.
Chưa ai đo có cookies. *Tín hiệu:* 5 lượt đều 0. *Phản ứng đã định:* ghi thẳng lên
UI là nguồn `/search` không dùng được, **đừng** để người dùng thử rồi tưởng tool hỏng.
Hashtag và music page vẫn chạy tốt.
