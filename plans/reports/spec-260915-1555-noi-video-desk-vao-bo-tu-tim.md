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
`get_current_user` (`dependencies.py:116`) và trả 401 khó hiểu.

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
   meta-auto lưu email nguyên chuỗi (`core/auth.py:214,223`) nhưng so allowlist bằng
   lowercase (`:200`) — so nguyên chuỗi sẽ tự tạo ra ca "có tài khoản mà không thấy".
6. Giữ nguyên `is_locked` (`dependencies.py:270-274`).
7. **Nhận `project_id` tường minh** từ Video Desk rồi kiểm bằng `resolve_project_read`
   (`api/_project_access.py:129`) và **cấm vai client** (`allow_client=False`).
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

Bọc mọi lookup DB trong `try` → 503.

## 6. Tính chất an toàn — và cái KHÔNG có

**Giữ được:**
- Route không tới được từ internet (lớp Access).
- Danh tính do **Cloudflare** chứng minh, không phải Video Desk tự khai.
- `aud` khoá theo application ⇒ token chuyển tiếp không replay được sang Access app khác.
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
- **Thu hồi `token_epoch` không áp** cho đường này (`dependencies.py:257-268`). Access có
  cơ chế thu hồi phiên riêng, nhưng hai cơ chế **không nối với nhau**.

## 7. Nghiệm thu — đột biến, không phải "chạy thử thấy được"

- Bỏ bước kiểm `aud` ⇒ token của **application Access khác** phải bị nhận ⇒ test **ĐỎ**.
- Đổi header thành `Cf-Access-Jwt-Assertion` ⇒ khi đi qua Access app, danh tính phải biến
  thành service token ⇒ test **ĐỎ**. (Đây là lỗi hỏng-im-lặng, không có test thì không
  thấy.)
- Gỡ `resolve_project_read` ⇒ user không có grant tạo được order ⇒ **ĐỎ**.
- Bỏ bước từ chối `common_name` ⇒ service token tạo được order đứng tên người ⇒ **ĐỎ**.
- Ca dương bắt buộc: một JWT **hợp lệ** của user có tài khoản + có grant ⇒ tạo được bộ,
  `requester_id` đúng người. Thiếu ca này thì mọi 401 ở trên không chứng minh gì.

## 8. Ngoài phạm vi spec này

- **SA Drive đang ở vai Manager.** Đo 15/09: `canDeleteDrive`, `canManageMembers`,
  `canDeleteChildren`, `canRenameDrive` đều `True` trên Shared Drive `Creative Astronex`,
  và đó là SA **của Creative Desk** dùng lại, key nằm trên mini. Đếm toàn bộ lời gọi Drive
  API trong `backend/app/`: `files().list|create|get|update|copy|get_media` +
  `permissions().create` — **không** `files().delete`, **không** `drives().delete`,
  **không** `permissions().delete` ⇒ **code Creative Desk chưa bao giờ cần Manager**.
  Ranh giới phép đo: chỉ đếm code trong repo, không thấy ai dùng SA bằng tay / script ngoài.
- Gắn video vào thư mục bộ: làm bằng **shortcut**, không `files().copy` — sync của
  Creative Desk đã hiểu shortcut (`creative_set_sync_service.py:30-32,186`), và copy thì
  tốn gấp đôi dung lượng, đồng thời làm thư viện hết là nguồn sự thật.

## Câu hỏi chưa giải

1. **Session Duration của Access app `video.nobidigital.asia`** — chưa đo, và nó là độ
   dài cửa sổ replay ở mục 6.
2. **Có ai dùng SA Drive đó ngoài code không** (tay, script, repo khác)? Chặn việc hạ vai
   Manager → Content manager.
3. `automation.nobidigital.asia` không nằm sau Access trong khi tài liệu deploy nói có —
   cố ý (bridge/PWA/webhook) hay đã rơi mất? Ảnh hưởng tới việc lớp Access ở mục 3 có
   phải là lớp chặn duy nhất hay không.
