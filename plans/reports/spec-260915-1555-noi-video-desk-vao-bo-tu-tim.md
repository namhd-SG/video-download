# Nối Video Desk vào "bộ tự tìm" — spec cho người trực meta-auto

**Viết bởi:** phiên làm `video-download` · 15/09/2026
**Cho:** người bảo trì `meta-ads-automation`
**Trạng thái:** đề xuất, **chưa thi công**. Không có dòng nào của meta-auto bị sửa.

---

## 1. Việc cần làm, một câu

Cho phép Video Desk (`video.nobidigital.asia`) tạo một **bộ tự tìm** đứng tên **đúng
người đang bấm**, với video đã chọn sẵn — mà không dựng lại hệ đăng nhập, không sao chép
taxonomy, và không nới quyền cho một tài khoản máy.

## 2. Vì sao không dùng các đường rẻ hơn

| đường | vì sao loại |
|---|---|
| CORS cho `video.*` gọi thẳng meta-auto bằng phiên trình duyệt | **Cấu tạo không chạy.** meta-auto nhận danh tính **chỉ** qua `Authorization: Bearer` (`backend/app/core/dependencies.py:75` `HTTPBearer`; không chỗ nào đọc cookie), token nằm trong `localStorage` của origin `automation.*`. Trang ở origin `video.*` không đọc được. CORS cho phép **gửi**, không **cấp** danh tính |
| Token máy (MCP) đứng tên bot | Order gắn `requester_id = assignee_id = finder`. Bot tạo bộ ⇒ **sai attribution** ở mọi bộ |
| Video Desk ký HMAC "người này là X" | meta-auto phải **tin Video Desk không nói dối**. Video Desk thủng = mạo danh bất kỳ ai, vô thời hạn |
| Đồng bộ taxonomy định kỳ sang Video Desk | Lệch âm thầm — đúng thứ chốt #12 sinh ra để tránh |

## 3. Đường đề xuất — hai lớp, tách bạch

**Lớp vận chuyển — Access application path-scoped.**
Tạo một Access app cho `automation.nobidigital.asia/api/videodesk/*`, policy **Service
Auth**. Video Desk gửi `CF-Access-Client-Id` / `CF-Access-Client-Secret` (service token,
sống trong `~/.config/videodl/env`, thư mục `700`, file `600`).
⇒ Route mới **không tới được từ internet**. Đây là lớp chính, vì
`automation.nobidigital.asia` hiện **KHÔNG nằm sau Access** (đo 15/09, 3/3 lượt trả
`200`; đối chứng cùng lúc: `video.*` → 302 Access, `promax.*` → 302). Lưu ý:
`docs/deployment-guide.md:304,490` nói host này ở sau Access — **tài liệu lệch thực tế**,
đáng tìm hiểu riêng, không thuộc spec này.

**Lớp danh tính — chuyển tiếp JWT Access của người dùng.**
Video Desk gửi thêm header **`X-Videodesk-User-Jwt`**.

⚠ **KHÔNG đặt tên header là `Cf-Access-Jwt-Assertion`.** Nếu route đi qua một Access app
(chính là lớp trên), Cloudflare **ghi đè** header đó bằng token của chính nó ⇒ danh tính
người dùng biến mất **im lặng**. Cũng không dùng `Authorization: Bearer` — nó rơi vào
`get_current_user` (`dependencies.py:113-124`) và trả 401 khó hiểu.

## 4. Cần thêm gì trong meta-auto

Một dependency, dùng cho **đúng các route bộ tự tìm**, không đụng đường đăng nhập đang chạy:

1. Đọc `X-Videodesk-User-Jwt`.
2. Xác minh chữ ký theo bộ khoá công khai của team:
   `https://nobidigital.cloudflareaccess.com/cdn-cgi/access/certs` → lấy `public_certs`
   (PEM), **không** phải `keys` (JWKS).
3. Kiểm `aud` **khớp AUD tag của application `video.nobidigital.asia`**. Đây là thứ làm
   token chuyển tiếp vô dụng ở nơi khác.
4. **Từ chối token chỉ có `common_name`** — đó là service token, không phải người.
5. Tra `User` theo email, **so lowercase**: `func.lower(User.email) == email.lower()`.
   Đường login Google ở **`backend/app/api/auth.py`**: `:200` so allowlist bằng lowercase,
   `:209` tra `User.email == email` **nguyên chuỗi**, `:218` tạo user với `email=email`.
   Nên so nguyên chuỗi sẽ tự tạo ra ca "có tài khoản mà không thấy".
6. Giữ nguyên `is_locked` (`dependencies.py:270-274`).
7. **Nhận `project_id` tường minh** từ Video Desk, rồi gọi **`resolve_project_read` của
   `backend/app/api/_project_access.py:129`** (trả `tuple[Project, str]` — `(project, role)`)
   và **tự từ chối `role == "client"`**.
   ⚠ Hai bẫy: (a) helper `_require_access` (`creative_orders.py:100-102`) có kwarg
   `allow_client` nhưng nó **đọc project từ claim JWT** (`:109-112`) nên **không tái dùng
   được** cho đường relay; (b) có **hàm trùng tên** `resolve_project_read` ở
   `api/cutoff.py:49` với chữ ký và kiểu trả khác — lấy nhầm là sai im lặng.
   ⚠ Đây là **cố ý đi ngược** quy ước của `creative_orders.py:19,109-114` (*"clients
   cannot set it"* — project lấy từ claim `proj`). JWT Access **không có** `proj`. Phải
   khai rõ trong docstring, không để người sau tưởng là sơ suất.

**Mã xác minh đã có sẵn, đã chạy, đã test:** `web/auth.py` trong repo `video-download`
(nhánh `feat/tiktok-tag-page-support`). Nó xử đúng ba thứ tài liệu không nói và đã đo:
`audience=` của `google-auth` **từ chối** `aud` dạng list (shape thật của Cloudflare) nên
phải tự kiểm; `decode` **không ghim `kid`**; đầu vào rác ném nhiều loại exception. Có
test + đột biến 4/4 ĐỎ. Lấy dùng được, **nhưng đừng copy nguyên `_identity_from`** — nó
nhận cả `common_name` (xem mục 4.4).

## 5. Hợp đồng lỗi — không ca nào được thành 500

| ca | mã | thông điệp |
|---|---|---|
| JWT hỏng / sai `aud` / hết hạn | **401** | — |
| không lấy được certs Cloudflare | **503** | "chưa kiểm được danh tính" — **tách khỏi 401**: dịch vụ hỏng và người bị chặn là hai sự việc |
| email không có `User` | **403** | "Chưa có tài khoản Creative Desk — đăng nhập automation.nobidigital.asia bằng Google một lần" |
| `User.is_locked` | **403** | "Tài khoản đang chờ admin duyệt" |
| có `User`, không có grant project | **403** | từ `resolve_project_read` |
| token chỉ có `common_name` | **401** | không ánh xạ bot thành người |
| **Access edge từ chối** (service token hết hạn, path app sai) | **503** | "lớp vận chuyển từ chối". Cloudflare trả **302/403 HTML**, không phải JSON của FastAPI — Video Desk phải nhận ra và map, đừng để thành 401 cho người dùng hay 500 vì parse JSON thất bại |

Bọc mọi lookup DB trong `try` → 503.

**Yêu cầu với phía Video Desk:** JWT của người dùng **chỉ tồn tại trong request đang bay** —
không ghi ra đĩa, không vào log, không vào bảng nào. Đây là thứ biến "tin có giới hạn thời
gian" ở §6 từ lời hứa thành tính chất kiểm được.

## 6. Tính chất an toàn — và cái KHÔNG có

**Giữ được:**
- Route không tới được từ internet (lớp Access).
- Danh tính do **Cloudflare** chứng minh, không phải Video Desk tự khai.
- **meta-auto chỉ nhận `aud` của application `video.nobidigital.asia`** ⇒ token của
  application khác không dùng được ở đây. (Chiều ngược lại — token của app video có dùng
  được ở nơi khác không — phụ thuộc nơi đó có kiểm `aud` hay không, ngoài tầm spec này.)
- **Hai lớp là hai yếu tố ĐỘC LẬP.** Kẻ có JWT user rò vẫn không vào được (thiếu service
  token); kẻ có service token vẫn không đứng tên ai được (thiếu JWT). Chỉ khi **chiếm được
  mini** mới có cả hai — và đó đúng là ranh giới của key Drive ở §8.
- Khoá tài khoản, grant project, cấm vai client đều còn nguyên hiệu lực.

**KHÔNG có, phải khai là rủi ro chấp nhận:**
- **Tin có giới hạn thời gian, không phải zero-trust.** Backend Video Desk nhìn thấy JWT
  của **mọi** user ở **mọi** request, nên nó replay được token bất kỳ ai tới các route
  này **cho tới khi token hết hạn**. Tốt hơn HMAC (giả mạo vô hạn), kém hơn không-cần-tin.
- **Độ dài cửa sổ replay = Session Duration của Access app `video.nobidigital.asia`.**
  **CHƯA ĐO.** Xem ở Zero Trust → app video → Session Duration. Đây là con số quyết định
  mức rủi ro ở gạch trên; đặt ngắn thì cửa sổ ngắn.
- **Service token nằm trên mini** — máy có tài khoản thứ hai (`autotest`). Rò nó thì mất
  lớp edge; lớp JWT vẫn còn.
- **Cả hai bên verify JWT OFFLINE** (chữ ký + `exp`). Nên *Revoke user session* của
  Cloudflare, hay rút người khỏi Access policy, **không ai nhìn thấy** cho tới khi token
  hết hạn. Kill-switch **chạy live mỗi request** trên đường này chỉ có một: **`is_locked`**
  (`dependencies.py:270`).
  ⇒ **Runbook nghỉ việc:** khoá user trong meta-auto (**tức thì**) *rồi* rút khỏi Access
  policy (hiệu lực khi hết phiên). Làm ngược thứ tự là để hở đúng một cửa sổ phiên.
  ⇒ `token_epoch` **không phải** vấn đề ở đây: đo được là **không có writer nào** trong
  `backend/app` bấm nó (chỉ cột model + chỗ đọc lúc mint, `api/auth.py:73`). Vấn đề là
  verify offline.
  ⇒ Video Desk **không có bảng user**, nên nó **không có kill-switch riêng** — mọi việc
  khoá người phải làm ở meta-auto.

## 7. Nghiệm thu — đột biến, không phải "chạy thử thấy được"

### 7a. Probe hạ tầng — test code KHÔNG bắt được cái này

Lớp Access nằm ngoài ứng dụng, nên không dòng test nào biết nó có tồn tại hay không. Cấu
hình sai path là ca hỏng-im-lặng nguy hiểm nhất trong cả spec: code chạy đúng hoàn toàn,
chỉ lớp chặn là không có. Ba lệnh, chạy sau khi dựng Access app:

```bash
# 1. không service token  → Access phải chặn ở EDGE
curl -si https://automation.nobidigital.asia/api/videodesk/<route>
#    mong đợi: 302/403 từ Cloudflare (KHÔNG phải JSON của FastAPI)

# 2. có service token, thiếu user JWT → tới được app, app từ chối
curl -si ... -H "CF-Access-Client-Id: …" -H "CF-Access-Client-Secret: …"
#    mong đợi: 401 từ APP

# 3. ĐỐI CHỨNG — Access app không được phủ nhầm sang hàng xóm
curl -si https://automation.nobidigital.asia/api/creative-taxonomy/categories
#    mong đợi: vẫn 401 từ app, KHÔNG phải 302
#    (302 ở đây = path app quét rộng quá ⇒ bridge/PWA/webhook chết theo)
```

Lệnh 3 là lệnh quan trọng nhất và dễ bị bỏ: nó bắt ca "chặn được route mới nhưng chặn
luôn cả những thứ đang chạy".

### 7b. Đột biến trong test code

- Bỏ kiểm `aud` ⇒ token của **application Access khác** phải được nhận ⇒ **ĐỎ**.
- Đổi header thành `Cf-Access-Jwt-Assertion` ⇒ khi đi qua Access app, danh tính phải biến
  thành service token ⇒ **ĐỎ**. Không có test thì đây là lỗi hỏng-im-lặng.
- Gỡ `resolve_project_read` ⇒ user không có grant tạo được order ⇒ **ĐỎ**.
- Bỏ bước từ chối `common_name` ⇒ service token tạo được order đứng tên người ⇒ **ĐỎ**.
- Gộp "không lấy được certs" vào 401 thay vì 503 ⇒ **ĐỎ**.
- `is_locked` ⇒ 403, và `role == "client"` **có grant** ⇒ 403 — hai ca riêng, không gộp.
- **JWT hết hạn** (mint `exp` ở quá khứ) ⇒ 401. `google-auth` có kiểm, nhưng phải khoá lại
  bằng test của chính mình.
- **`aud` dạng LIST được NHẬN** — shape thật của Cloudflare. Chép `test_aud_as_a_LIST_is_accepted`
  từ `video-download/tests/test_web_auth.py`. Bỏ ca này là ship một bug im lặng: test với
  `aud` dạng chuỗi vẫn xanh.
- **Hai header cùng lúc:** `Authorization: Bearer <token hợp lệ của A>` + `X-Videodesk-User-Jwt`
  của B ⇒ phải định nghĩa ai thắng. Khuyến nghị: route videodesk **từ chối** nếu có
  `Authorization`. Bỏ kiểm ⇒ **ĐỎ**.
- **Cách ly dependency:** duyệt `app.routes`, khẳng định *chỉ* route dưới `/api/videodesk/`
  dùng dependency mới, và **không** route nào trong đó còn dùng `AuthUser`.

**Ca dương bắt buộc:** một JWT **hợp lệ** của user có tài khoản + có grant ⇒ tạo được bộ,
`requester_id` đúng người đó. Thiếu ca này thì mọi ca 401/403 ở trên không chứng minh gì —
chúng có thể xanh chỉ vì route luôn từ chối.

## 8. Ngoài phạm vi spec này

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

## Câu hỏi chưa giải

1. **Session Duration của Access app `video.nobidigital.asia`** — chưa đo, và nó là độ
   dài cửa sổ replay ở mục 6.
2. **Có ai dùng SA Drive đó ngoài code không** (tay, script, repo khác)? Chặn việc hạ vai
   Manager → Content manager.
3. `automation.nobidigital.asia` không nằm sau Access trong khi tài liệu deploy nói có —
   cố ý (bridge/PWA/webhook) hay đã rơi mất? Ảnh hưởng tới việc lớp Access ở mục 3 có
   phải là lớp chặn duy nhất hay không.
