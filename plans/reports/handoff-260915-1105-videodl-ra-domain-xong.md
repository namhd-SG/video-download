# Bàn giao — video-download ra domain: 4 việc XONG, còn 3 phép đo cần người

**Từ:** `macos-aa` · **Ngày:** 15/09/2026 11:05 · **Nhận từ:** `macos-cb`
**Kế hoạch:** `plans/260914-1412-tool-len-mini-va-domain/`

---

## 1. Kết quả

Cả 4 việc trong bàn giao trước đã làm xong. Dịch vụ **đang sống sau Cloudflare Access**.

| # | việc | trạng thái |
|---|---|---|
| 1 | `web/auth.py` — kiểm JWT Access | XONG, đã deploy lên mini, đo trên máy thật |
| 2 | hostname vào tunnel | XONG + DNS đã tạo |
| 3 | nghiệm thu toàn hệ | **3/6 tiêu chí ĐO ĐƯỢC**, 3 tiêu chí còn lại cần người |
| 4 | link vào nav meta-auto | XONG — PR #192 |

Ngoài scope bàn giao nhưng đã làm vì `macos-cb` báo nguy cơ mất trắng: **toàn bộ công
việc 2 ngày đã commit + push**. Trước đó `git branch -r --contains HEAD` rỗng.

## 2. Đo được — lệnh + kết quả

```
# Access chặn người chưa đăng nhập (tiêu chí quan trọng nhất của phase-04)
curl https://video.nobidigital.asia          → 302 (3/3 lượt, HAI mạng)
  redirect: nobidigital.cloudflareaccess.com/cdn-cgi/access/login/video.nobidigital.asia
                                               ^^^ gọi tên đích danh hostname

# API sau khi deploy auth (trên mini, qua loopback)
GET  /jobs   không JWT          → 401     (TRƯỚC deploy: 200 ← ca âm)
POST /jobs   không JWT          → 401
GET  /jobs   header email giả   → 401
GET  /jobs   JWT rác            → 401
GET  /healthz                   → 200     (route duy nhất không cần auth, cố ý)

# Hàng xóm không bị đụng
promax.nobidigital.asia         → 302, >12 lượt tại 4 thời điểm, 0 lượt khác
launchctl list | grep -c astronex → 5 trước và sau mỗi lần đụng launchctl

# Test
pytest tests/ -q  → 163 passed rc=0   (máy dev VÀ trên mini)
đột biến          → 4/4 ĐỎ            (chi tiết mục 4)
```

Commit: `27e7fb4 … e9032ac` (6 commit) trên `feat/tiktok-tag-page-support`,
`git branch -r --contains HEAD` → `origin/feat/tiktok-tag-page-support`.
PR meta-auto: **#192**, nhánh `feat/videodl-nav-link`, worktree
`/Users/macos/meta-ads-wt-videodlnav`.

## 3. CÒN LẠI — chỉ 3 phép đo, đều cần người cầm máy

1. **Đăng nhập rồi mở tool, 3/3 lần.** Không tự động được (OAuth qua trình duyệt).
2. **Từ 4G ngoài LAN.** Cần người cầm điện thoại.
3. **Ép guard đĩa → từ chối job mới.** Chưa đo. ⚠ Tiêu chí này viết từ hồi endpoint
   còn công khai; giờ `POST /jobs` đã đòi JWT nên câu *"không có cửa nào từ internet
   đẩy đĩa máy người khác xuống 0"* đã được **một lớp khác** trả lời. Vẫn nên đo, nhưng
   nó không còn là lỗ hở internet nữa.

Không còn việc code nào chặn.

## 4. Quyết định kỹ thuật — đo trước khi chọn, không đoán

**Không thêm dependency JWT.** `google-auth` đã là core dep (Drive). Đã probe bản cài
đặt trước khi dựa vào, và tìm ra **ba điều tài liệu không nói**:

- **`audience=` của google-auth TỪ CHỐI shape thật của Cloudflare.** Access phát `aud`
  dạng **LIST**; google-auth so cả list với allow-list rồi báo
  `Token has wrong audience ['x'], expected one of ['x']`. ⇒ truyền `audience=None`,
  tự kiểm `aud`, nhận cả str lẫn list. Test `test_aud_as_a_LIST_is_accepted` khoá
  điều này; bỏ đi thì test str vẫn xanh còn list thành đỏ — đúng hình dạng con bug
  sẽ ship nếu tin tài liệu.
- **`decode` KHÔNG ghim `kid`.** Token khai kid vắng mặt trong mapping vẫn qua. Không
  phải lỗ hổng (mọi khoá đều của Cloudflare, kẻ giả vẫn cần khoá riêng của họ) nhưng
  đã ghi comment để người sau đừng đọc code này thành có-ghim.
- **Đầu vào rác ném nhiều loại exception** (`MalformedError`, `binascii.Error`). Bắt
  hẹp là lọt 500. ⇒ bắt rộng, chỉ log **loại** exception, không log token.

**`iss` cố ý không kiểm** — URL bộ khoá đã scope theo team, nên xác thực chữ ký bằng
khoá của team đó cho cùng một ràng buộc; thêm chuỗi `iss` chỉ tạo rủi ro fail-closed
nếu Cloudflare đổi định dạng.

**"Chưa cấu hình" ≠ "token sai".** Thiếu env → **503**; token hỏng → **401**. Gộp hai
cái là một dịch vụ deploy lỗi trông y hệt một kẻ tấn công bị chặn.

**Test bắt được một lỗi đặt-nhầm-chỗ của chính tôi:** guard "không có khoá nào" ban
đầu nằm trong *fetcher mặc định*, nên fetcher khác trả rỗng sẽ rơi xuống 401. Một
service **không có khoá nào** mà trả 401 trông như đang chặn được người — trong khi
thật ra nó không kiểm được gì. Đã chuyển guard vào `_certs_now`.

**Đột biến đã chạy (4/4 ĐỎ), khôi phục có kiểm sha:** gỡ `Depends(require_user)` ·
`verify=False` · bỏ xử lý `aud` list · bỏ tiền-kiểm "chưa cấu hình".

## 5. Thứ tự Access-trước-DNS: hoá ra có một sự thật làm nó dễ hơn

Bàn giao trước cảnh báo "Access phải xanh TRƯỚC khi hostname chạm cổng 7870", viện
Certificate Transparency. Đúng, nhưng đo ra thêm một dữ kiện làm đổi cách thi công:

**`video.nobidigital.asia` lúc đó CHƯA có bản ghi DNS nào** (ca dương: `promax` trả 2
IP). Không DNS ⇒ không request nào mang Host đó tới được tunnel ⇒ **sửa `config.yml`
là thao tác TRƠ**. Công tắc phơi sáng là **DNS**, không phải ingress.

Nên trình tự thực tế an toàn hơn bản kế hoạch: sửa ingress (trơ) → deploy auth (lúc
này service tự nó đã 401) → mới tạo DNS. Khi DNS bật lên thì đã có **hai** lớp chặn,
không phải một.

Cách sửa `config.yml` của Promax — file production của người khác: sao lưu
`config.yml.bak-260915` → sinh **bản nháp** → `ingress validate` trên **bản nháp** →
kiểm `ingress rule` cho cả hostname mới **và** promax (đối chứng hàng xóm vẫn ra
7860) → chỉ khi đó mới `mv` đè file sống. File sống không bao giờ ở trạng thái chưa
kiểm. Không restart (cloudflared tự nạp lại), không `bootout`.

## 6. Tôi đã sai một chỗ

**Probe auth bằng `POST /jobs` → tạo job thật id=3 trên dịch vụ đang chạy.** Đáng lẽ
dùng `GET /jobs`. Hậu quả đo được: `done`, `tong=0 xong=0 loi=0`, không có link Drive,
thư mục làm việc rỗng — URL music giả không ra ref nào, **0 tác động**, không đụng
trần rủi ro TikTok. Nhưng đó là may, không phải thiết kế.

Và **probe đầu tiên của tôi về google-auth có lỗi**: `gjwt.encode` trả `bytes`, tôi
`split(".")` bằng str nên "test chữ ký hỏng" ném `TypeError` — nó chưa hề thử chữ ký
hỏng. Suýt ghi một kết luận sai về thư viện. Phải đo lại mới ra `MalformedError` thật.

## 7. meta-auto — PR #192

Repo đang ở `main` với **42 mục dirty của lane khác** (vùng `cutoff/*`). Không chạm:
dựng `git worktree` sạch từ `origin/main`, sửa ở đó, `git add` từng đường dẫn cụ thể
(3 file), commit, push, PR. Checkout dùng chung **không bị đụng một byte nào**.

`NavItem` thêm 2 cờ, cả hai đều hỏng-âm-thầm nếu bỏ:
- `external` — render `<a target="_blank">`; router của app không đi ra host khác
  được, và href tuyệt đối không bao giờ khớp pathname nên mục không được "active".
- `hideForClient` — **user chốt: member nội bộ thấy, client không.** Mọi mục khác dựa
  vào backend `resolve_project(exclude client)`, nhưng link ngoài **không đi qua
  backend nào của app này**, nên chỗ duy nhất chặn được vai client là ngay trong nav.
  Lọc đặt trong `renderLink` — đường duy nhất mọi mục đều đi qua.

Pre-push hook chặn vì system-map lệch HEAD ⇒ chạy `regen.sh` rồi commit map (đường
chính thống của repo), **không** `SKIP_HYGIENE=1`. Diff map chỉ là con trỏ commit +
hash frontend, không có thay đổi cấu trúc.

`tsc --noEmit` rc=0 · `vitest sidebar-nav-config.test.ts` 6 passed · đột biến 2/2 ĐỎ.

## 8. Lệnh kiểm nhanh khi vào việc

```bash
curl -s -o /dev/null -w "video %{http_code} %{redirect_url}\n" https://video.nobidigital.asia
curl -s -o /dev/null -w "promax %{http_code}\n" https://promax.nobidigital.asia
ssh nobi_auto@100.109.39.103 'launchctl list | grep -c astronex; \
  curl -s -o /dev/null -w "healthz %{http_code}\n" http://127.0.0.1:7870/healthz; \
  curl -s -o /dev/null -w "jobs %{http_code}\n" http://127.0.0.1:7870/jobs'
gh pr view 192 --repo namhd-SG/meta-ads-automation
```

⚠ Resolver của máy dev có thể còn cache NXDOMAIN của `video.nobidigital.asia` từ lần
tra trước khi bản ghi tồn tại. `curl` trả `000` + *"Could not resolve host"* trong khi
`dig +short` ra IP ⇒ **đó là cache của máy, không phải dịch vụ chết**. Đường vòng:
`curl --resolve video.nobidigital.asia:443:$(dig +short video.nobidigital.asia|head -1)`.

## Câu hỏi chưa giải

1. **Ba phép đo ở mục 3 cần người** — đăng nhập trình duyệt 3/3, thử từ 4G, ép guard
   đĩa. Không có đường tự động.
2. **PR #192 chưa merge.** CI đang chạy lúc viết. Merge cần người duyệt.
3. **`/search` với cookie mới đo 19/20 ở MỘT lượt** (di sản từ bàn giao trước) — chưa
   đo nhiều lượt nên chưa biết tỉ lệ ổn định.
4. **Cap job/ngày chưa thi công** (~10 dòng, user đã chốt 14/09). Giảm rủi ro khoá
   nick TikTok khi cả team dồn về một IP. Không chặn MVP nhưng là nợ đã được chốt.
5. **`tests/test_web_app.py` vẫn gọi thẳng hàm route**, chưa qua `TestClient` (venv
   thiếu `httpx`). Test `test_job_routes_require_a_verified_user` đọc cây dependency
   của route để bù chỗ đó, nhưng nó không phải một request HTTP thật.
