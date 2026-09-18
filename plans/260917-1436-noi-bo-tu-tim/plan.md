# Nút "Tạo bộ tự tìm" ở Thư viện Video Desk → Creative Desk, đứng tên người bấm — LÀM HÔM NAY

**Kongming · 17/09/2026 14:40 · tư vấn, không thi công.** Mọi số/dòng đo lúc 14:00-14:40; quyền và
trạng thái repo là thứ người ta sửa — kiểm lại trước khi gõ.

## 0. TL;DR

**Không cần chờ CI, không cần Access app, không cần relay JWT.** Đường nhanh nhất và an toàn nhất:
**nút ở Video Desk mở tab `automation.nobidigital.asia/creative-order/self-bundles?videodesk=<payload>`;
frontend meta-auto (đang đăng nhập bằng chính người đó) mở sẵn dialog "Thêm bộ tự tìm", tạo order bằng
Bearer CỦA NGƯỜI ĐÓ, rồi gọi 1 route backend mới copy file Drive vào folder của bộ.** Danh tính = phiên
meta-auto của chính user ⇒ Video Desk **không có** quyền mạo danh ai (không có token, không có S2S).

Spec 15/09 **sai do bỏ sót**: §2 chỉ xét "trang ở origin `video.*` gọi meta-auto" (đúng là chết) rồi nhảy
sang S2S; không xét "đưa TRÌNH DUYỆT sang origin `automation.*`". Toàn bộ §3-§7 (Access app path-scoped,
service token, verify JWT Cloudflare, hợp đồng lỗi 8 ca) là **không cần** cho tính năng này.

Merge meta-auto **không cần CI**: `gh api repos/namhd-SG/meta-ads-automation/branches/main/protection`
→ **403 "Upgrade to GitHub Pro"** (rulesets cũng 403) ⇒ repo Free private **không thể** có branch
protection ⇒ chưa bao giờ có cổng cứng; CI đỏ 3s là hết quota Actions, không chặn merge/deploy.

## 1. Phép đo nền (14:00-14:40, 17/09)

| # | phép đo | kết quả | hệ quả |
|---|---|---|---|
| 1 | `gh api .../branches/main/protection` và `/rulesets` | **403 Pro** | merge không cần CI xanh |
| 2 | `gh run list` meta-auto | CI `failure` 3-5s liên tiếp (quota) | đúng memory `github-actions-quota`; bỏ qua |
| 3 | `curl automation.nobidigital.asia/{/,/health}` | **200** (không 302 Access); control `video.*` → 302 | frontend meta-auto tới được thẳng từ tab mới |
| 4 | mini `~/.config/videodl/env` (chỉ tên biến) | comment: *"Khoá Drive DÙNG CHUNG với Creative Desk (user chốt 14/09)"*; SA = `creative-astronex-drive@intraday-astrodata` | **cùng SA** với meta-auto ⇒ memory kongming 14/09 "SA riêng" đã bị user đảo — memory STALE |
| 5 | Drive API read-only bằng SA trên mini | root Video Desk `1FJdIrKkezvHle7MbQ3pjKa7fCysjDE5t` "video-tool" **driveId `0AASy4v5CJAkfUk9PVA`**; folder "Tự tìm" `1vY0Hh95GVDPAsoBmS21xW7Kslxs7rVsU` **cùng driveId**; SA thấy đúng 1 Shared Drive "Creative Astronex" | `files().copy` trong cùng Shared Drive, cùng SA — một lệnh, đã có sẵn `copy_file` |
| 6 | meta-auto `backend/app/services/creative_drive_client.py:176` | `copy_file(file_id, dest_folder_id, name)` `supportsAllDrives=True` | không viết Drive code mới |
| 7 | `creative_order_service.py:229-301` `_create_self_bundle` | `requester_id=assignee_id=requester.id`; nhận `link_sources`; tạo folder dưới `Creative/Tự tìm/...`; enqueue sync | tạo bằng Bearer của user ⇒ đứng tên đúng người, **không sửa** |
| 8 | `frontend/src/app/creative-order/self-bundles/page.tsx` | có dialog "＋ Thêm bộ tự tìm" dùng `SelfBundleCreateForm` | chỉ thêm đọc query param + prefill |
| 9 | `frontend/src/app/creative-order/create/page.tsx:8-15,39-45` | mẫu `useSearchParams` + `Suspense` đã có (`?from=`) | copy mẫu |
| 10 | `frontend/src/lib/auth-context.tsx:110-119` | sau login `router.push("/projects")`/`"/"` — **mất query** | nếu chưa đăng nhập, user bấm lại nút; fix tuỳ chọn §4.3 |
| 11 | Video Desk `web/static/app.js:70,375-425,505-540`, `index.html:118-125` | đã có `state.selected`, thanh `#selection-bar` với `data-action` `cart`/`analyze` (toast "Chưa làm") | nút chèn vào đúng chỗ đã có |
| 12 | Video Desk `web/models.py:45-57,450-479` | `videos.drive_file_id`, `url`, `title`; `/videos` trả `SELECT v.*` | payload có sẵn ở client, không cần endpoint mới |
| 13 | meta-auto repo: 19 worktree; scan `git diff --name-only origin/main...HEAD` mọi nhánh + dirty theo mẫu `self-bundle|creative_orders.py|main.py|automate-creative` | **0 hit** | không đụng lane khác (§6) |
| 14 | checkout chính `/Users/macos/meta-ads-automation` = `feat/ci-local-gate` `e2727491`, 36 sau / 14 trước origin/main; dirty = 9 file **untracked** (memory + report) | lane kia ở đó | **không làm việc trong checkout đó** — mở worktree mới từ `origin/main` `4783e63c` |
| 15 | `scripts/deploy.sh` (origin/main) | cổng: A base∈tổ tiên, B HEAD đã push, 4 cây sạch, 5 system-map, D đĩa=cây; **không có** cổng "phải ở main" | deploy từ worktree riêng đã `checkout --detach origin/main` sau merge |
| 16 | `feat/videodl-nav-link` (`meta-ads-wt-videodlnav`) | đã push, `branch -r --contains` chỉ ra chính nó ⇒ **chưa merge** | link nav meta-auto→Video Desk cũng chưa live; độc lập, không chặn |
| 17 | DB prod `select count(*) from projects` | **BỊ CHẶN** (classifier Production Reads) | caller tự chạy — lệnh ở §7 |

## 2. Bài toán thật

- **Cần:** người dùng Video Desk chọn N video → có một order `kind="self"` trên Creative Desk với
  `requester_id` = chính họ, folder Drive chứa N file, CreativeSet `source='self'` xuất hiện.
- **Không cần:** Video Desk biết taxonomy/project; Video Desk giữ token của ai; route mới lộ ra internet.
- **Ràng buộc:** hôm nay; không đụng lane khác trong meta-auto; mini chỉ `kickstart -k` label của mình.

## 3. Thiết kế — 3 mảnh, thứ tự gõ

```
Video Desk (app.js)          meta-auto frontend                   meta-auto backend
─────────────────            ────────────────────────────────     ─────────────────────────────────
[Tạo bộ tự tìm] ──open tab──▶ /creative-order/self-bundles        POST /api/creative-orders (kind=self)
 payload = base64url JSON      ?videodesk=<payload>                 ← Bearer của USER (đã có) → requester=user
 {v:1, items:[{f,n,u}]}        → mở dialog, prefill title +        POST /{id}/self-bundle-import-drive  ★MỚI
                                 link_sources; sau khi tạo →         copy_file(f → order.drive_folder_id)
                                 gọi import ─────────────────────▶   guard: driveId == project drive; mime video/image
                                                                     enqueue_project_set_sync(force=True)
```

★ = duy nhất thứ mới ở backend. Không sửa `dependencies.py`, không sửa `_create_self_bundle`.

### 3.1 Video Desk — `web/static/index.html:121-122`, `web/static/app.js:~505-540`

`index.html` — thay/đứng cạnh hai nút "Chưa làm":
```html
<button type="button" data-action="self-bundle">Tạo bộ tự tìm</button>
```
`app.js` — trong handler `#selection-bar` (dòng ~525), thêm nhánh:
```js
const CREATIVE_DESK_URL = "https://automation.nobidigital.asia";   // cùng team, URL công khai
const HANDOFF_MAX = 30;                                             // giữ URL < ~6KB
if (action === "self-bundle") {
  const picked = <mảng video trong state>.filter(v => state.selected.has(v.video_id));
  const missing = picked.filter(v => !v.drive_file_id);
  const items = picked.filter(v => v.drive_file_id)
                      .map(v => ({ f: v.drive_file_id, n: v.title || v.video_id, u: v.url }));
  if (!items.length) return showToast("Video chưa lên Drive — không có gì để gửi.");
  if (items.length > HANDOFF_MAX) return showToast(`Chọn tối đa ${HANDOFF_MAX} video một bộ.`);
  if (missing.length) showToast(`${missing.length} video chưa lên Drive, bỏ qua.`);
  const json = JSON.stringify({ v: 1, items });
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
                .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  window.open(`${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk=${b64}`, "_blank", "noopener");
}
```
Test (pytest hiện có 285): thêm 1 test JS-free — nếu repo không test JS thì test HTML có nút
`data-action="self-bundle"` và app.js chứa `self-bundle-import` **không** (Video Desk không gọi API meta-auto).
Deploy: `bash deploy/deploy-to-mini.sh` (khô) → `--yes`. Script đã có cổng hostname + chỉ `kickstart -k`
label `com.astronex.videodl`.

### 3.2 meta-auto frontend (worktree MỚI, xem §5)

**a. `frontend/src/lib/api-creative-self-bundles.ts:41-53`** — `SelfBundleCreate` thêm
`link_sources?: {url: string; note?: string}[]`; body thêm `...(input.link_sources && { link_sources })`.
Thêm:
```ts
export async function importSelfBundleDriveFiles(orderId: string, files: {drive_file_id: string; name?: string}[]) {
  const { data } = await apiClient.post(`/api/creative-orders/${orderId}/self-bundle-import-drive`, { files });
  return data as { files: {id?: string; name: string; error?: string}[]; enqueued_sync: boolean };
}
```
**b. `frontend/src/lib/videodesk-handoff.ts` (MỚI, ~40 dòng, có vitest)** — `parseVideodeskHandoff(param: string|null)`:
base64url → JSON → kiểm `v===1`, `items` ≤30, mỗi `f` khớp `/^[A-Za-z0-9_-]{10,128}$/`, `u` là http(s),
`n` cắt 200 ký tự. Rác ⇒ `null`, không throw. Test: 1 ca hợp lệ, 4 ca rác (không base64, v≠1, f rác, >30).

**c. `frontend/src/app/creative-order/self-bundles/page.tsx`** — bọc `Suspense` như `create/page.tsx:39-45`;
`const handoff = useMemo(() => parseVideodeskHandoff(useSearchParams().get("videodesk")), ...)`;
`useEffect(() => { if (handoff) setCreateOpen(true); }, [handoff])`; truyền `handoff` xuống form;
trong `onCreated` của ca handoff: `router.replace("/creative-order/self-bundles")` để F5 không tạo bộ thứ hai.

**d. `frontend/src/components/automate-creative/self-bundle-create-form.tsx:41-71`** — prop
`handoff?: VideodeskHandoff`; hiển thị danh sách N item (tên + link) phía trên dropzone kèm dòng
*"N video từ Video Desk sẽ được copy vào folder sau khi tạo"*; **mirror đúng mẫu `autoUploadedRef` dòng
62-71**: khi `orderId` có và `handoff` có → gọi `importSelfBundleDriveFiles(orderId, items)` một lần,
rồi `setTimeout(onCreated, SYNC_REFRESH_DELAY_MS)`; lỗi từng file hiện inline như upload.

**e. `use-self-bundle-form-state.ts:35-52,150-175`** — nhận `initial?: {title?: string; link_sources?: ...}`;
`INITIAL_FORM.title` lấy từ `initial.title` (= `items[0].n` khi N=1, hoặc `"Video Desk · N video"`);
`createSelfBundle({..., link_sources: initial?.link_sources})` — link TikTok vào `link_sources` để bộ tự ghi nguồn.

### 3.3 meta-auto backend — `backend/app/api/creative_self_bundle_import.py` (MỚI, ~90 dòng)

Chép khung `creative_self_bundle_files.py:1-60,75-100` (router prefix, `_require_project`, `_fetch_order`,
409 khi `kind != "self"` / thiếu `drive_folder_id`). Khác ở thân:
```python
class DriveImportItem(BaseModel):
    drive_file_id: str = Field(min_length=10, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, max_length=200)

class DriveImportBody(BaseModel):
    files: list[DriveImportItem] = Field(min_length=1, max_length=30)

@router.post("/{order_id}/self-bundle-import-drive", summary="Copy Drive files (same Shared Drive) into a self-bundle folder")
async def import_self_bundle_drive_files(order_id: uuid.UUID, body: DriveImportBody, auth: AuthUser, user: UserRecord, db: DBSession) -> dict:
    ...  # project_id, order, project như files route
    dest_drive = project.creative_drive_id or settings.CREATIVE_DRIVE_SHARED_DRIVE_ID
    for item in body.files:
        meta = await asyncio.to_thread(get_file_drive_meta, item.drive_file_id)   # files().get fields=id,name,mimeType,driveId
        if meta["drive_id"] != dest_drive:            # guard: chỉ copy trong CHÍNH Shared Drive của project
            results.append({...,"error": "nguồn không nằm trong Shared Drive của project"}); continue
        if not meta["mime_type"].startswith(("video/", "image/")):
            results.append({...,"error": "không phải video/ảnh"}); continue
        try:
            copied = await asyncio.to_thread(copy_file, item.drive_file_id, order.drive_folder_id, item.name or meta["name"])
            results.append({"id": copied["id"], "name": copied["name"]})
        except DriveAPIError as exc:
            results.append({"name": ..., "error": str(exc)}); failures.append(...)
            await log_upload_failure(db, order=order, actor=user, filename=..., error=str(exc))
    await notify_upload_failures(db, project_id, order, failures)
    enqueued = await enqueue_project_set_sync(project_id, order_id=order.id, force=True)
    return {"files": results, "enqueued_sync": enqueued}
```
- `get_file_drive_meta`: thêm vào `creative_drive_client.py` cạnh `get_media_metadata` (`:219`) — cùng
  `files().get(..., fields="id,name,mimeType,driveId", supportsAllDrives=True)`; hoặc mở rộng
  `get_media_metadata` thêm `driveId` nếu chữ ký cho phép (kiểm `:219-247` trước).
- `copy_file` là sync (`build_drive_service()` blocking) ⇒ `asyncio.to_thread`, đừng gọi thẳng trong
  handler async (files route dùng wrapper `upload_bytes` async — kiểm `creative_drive_service.upload_bytes`
  xem nó wrap thế nào và làm y hệt).
- **Vì sao guard `driveId`**: user gửi id tuỳ ý; SA đọc được toàn Shared Drive. Không guard ⇒ ai có tài
  khoản Creative Desk copy được **bất kỳ** file SA thấy vào folder mình. Guard `driveId == drive của
  project` giới hạn về đúng phạm vi họ vốn đã được cấp qua Creative Desk. Đột biến: bỏ guard ⇒ test ĐỎ.
- **Đăng ký** `backend/app/main.py:87` (import) và `:387` (include, cạnh
  `creative_self_bundle_files_router`, TRƯỚC `creative_orders_router`).
- Test `backend/tests/.../test_creative_self_bundle_import.py`, mock `get_file_drive_meta` + `copy_file`:
  (1) dương: 2 file cùng drive ⇒ 2 copy, `enqueue` gọi `force=True`; (2) drive khác ⇒ error inline,
  **0** copy; (3) order `kind="desk"` ⇒ 409; (4) 31 file ⇒ 422; (5) `DriveAPIError` ⇒ 200 với error +
  `log_upload_failure` gọi; (6) đột biến: xoá guard drive ⇒ (2) ĐỎ.

## 4. Đường deploy — đo, không đoán

### 4.1 meta-auto
1. **Worktree mới từ origin/main** (ghi duy nhất vào `.git/worktrees/`, không đụng cây nào khác — vẫn
   NHẮN lane `feat/ci-local-gate` một dòng trước):
   `git -C /Users/macos/meta-ads-automation fetch origin && git -C /Users/macos/meta-ads-automation worktree add /Users/macos/meta-ads-wt-videodesk -b feat/videodesk-self-bundle-handoff origin/main`
2. Gõ §3.2 + §3.3. Chạy hẹp trước: `pytest <file test mới>`; `npx vitest run videodesk-handoff self-bundle`;
   rồi `npm run build` (Next) — 4 lệnh CI cũ là hygiene/pytest/vitest/next build (`scripts/ci-local/README.md`).
   `gate.sh`/`merge-pr.sh` **chỉ có trên `feat/ci-local-gate`**, chưa lên main — dùng được nếu lane kia
   đồng ý (khoá máy 45', dùng Postgres chung); không thì chạy tay 4 lệnh.
3. `git push -u origin feat/videodesk-self-bundle-handoff` → `gh pr create` → `gh pr merge <n> --merge`.
   **Không cần** `--admin`, không cần chờ check: protection 403 ⇒ GitHub không chặn. CI sẽ hiện
   `failure 3s` — là quota, đã ghi ở memory `github-actions-quota-exhausts-monthly`.
4. Deploy từ chính worktree đó: `git fetch origin && git checkout --detach origin/main` →
   `bash scripts/system-map/regen.sh` (cổng 5; map đổi thì commit lên main rồi push — quy trình cũ) →
   `./scripts/deploy.sh --skip-migrate` (base tự đọc `.deployed-sha`; services mặc định gồm
   api+frontend+worker×5+beat — **backend đổi ⇒ phải đủ bộ**, GOTCHA 1). Bước 6.5 drain có thể chờ tới 20'.
5. Nghiệm thu §7.

### 4.2 Video Desk
`bash deploy/deploy-to-mini.sh` → đọc danh sách file → `--yes`. Sau đó `curl -s 127.0.0.1:7870/healthz` **không**
đủ; nghiệm thu là §7.

### 4.3 Tuỳ chọn, không chặn hôm nay
- Giữ deep link qua login: `creative-order/layout.tsx:78` trước `router.push("/login")` ghi
  `sessionStorage.setItem("post_login_path", location.pathname + location.search)`; `auth-context.tsx:110`
  ưu tiên đọc key đó. ~8 dòng. Không làm thì user bấm lại nút sau khi đăng nhập — chấp nhận được.
- `CREATIVE_DESK_URL` đọc từ `/me` (env `VIDEODL_CREATIVE_DESK_URL`) thay vì hằng — cần sửa env trên mini; để sau.

## 5. Lát cắt nếu hết giờ

| tầng | có gì | thiếu gì so với đủ | giá |
|---|---|---|---|
| **A** (≈2h) | nút Video Desk + frontend meta-auto prefill + tạo order đứng tên đúng người + `link_sources` TikTok | file KHÔNG tự vào folder | user mở link folder ở result panel, kéo file trong Drive (cùng Shared Drive ⇒ "Move to" được). Deploy meta-auto chỉ `--services frontend` |
| **B** (= §3 đủ, ≈5-6h) | A + route import + sync | — | deploy đủ bộ api+workers (drain gate) |
| ~~C~~ tạo bằng tài khoản dịch vụ rồi gán lại | **BỎ**: sai attribution ở mọi bộ (spec §2 dòng 20 đúng chỗ này) + phải sửa `finder_id` tay qua PATCH `/self-bundle` từng bộ | | |

Khuyến nghị: gõ theo thứ tự **3.1 → 3.2 → 3.3**; nếu 17:30 chưa xong 3.3 thì ship A (frontend-only), 3.3 mai.

## 6. Chạm lane khác — đo

- Scan 19 worktree (`git diff --name-only origin/main...HEAD` + `status --porcelain`) theo mẫu
  `self-bundle|self_bundle|creative_orders\.py|main\.py|api-creative|creative-order/self-bundles|automate-creative`
  → **0 hit**. Checkout chính (`feat/ci-local-gate`) dirty 9 file, toàn untracked ngoài `backend/`,`frontend/`.
- Điểm va duy nhất có thể: `backend/app/system_map/system-map.json` + `docs/system-map/overview.md` khi regen
  (mọi nhánh đều đụng; memory: xung đột ở đây là **stamp-only**).
- **Không** dùng `/Users/macos/meta-ads-wt-deploy-main` (của người khác, detached) — deploy từ worktree §4.1.

## 7. Nghiệm thu — có sức phân định

```bash
# (a) DANH TÍNH — chạy sau khi user X bấm nút và tạo bộ; caller chạy (kongming bị chặn Production Reads):
ssh ua-vps 'cd /opt/meta-ads/app && docker compose -f docker-compose.prod.yml exec -T postgres sh -c \
 "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"select co.task_code, u.email, co.kind, co.link_sources::text \
  from creative_orders co join users u on u.id=co.requester_id where co.kind=\\$\\$self\\$\\$ order by co.created_at desc limit 3\""'
#   ĐẠT: email = người BẤM (không phải admin/bot); link_sources chứa URL TikTok đã chọn.
#   PHÂN ĐỊNH: user Y làm lại ⇒ dòng mới mang email Y. Hai dòng khác email = đứng tên đúng người.

# (b) FILE — so md5 nguồn và đích (SA trên mini, read-only):
#   files().get(<drive_file_id nguồn>, fields=md5Checksum) == files().list(q="'<order.drive_folder_id>' in parents").md5Checksum
#   ĐẠT: N/N khớp. Sau ≤2' sync: creative_sets có 1 row source='self' cho order đó, files = N.

# (c) ÂM — route import:
#   id rác 'AAAAAAAAAAAA' ⇒ 200 + error inline (không 500); order kind='desk' ⇒ 409; 31 file ⇒ 422.
#   Bỏ guard driveId trong code ⇒ test (2) ĐỎ.

# (d) HÀNH VI URL: F5 trang self-bundles sau khi tạo ⇒ KHÔNG mở dialog lần hai (router.replace đã xoá query).

# (e) Q5 — số project (caller chạy, read-only):
ssh ua-vps 'cd /opt/meta-ads/app && docker compose -f docker-compose.prod.yml exec -T postgres sh -c \
 "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"select p.name, p.slug, p.creative_drive_id, \
  (select count(*) from user_project_permissions upp where upp.project_id=p.id) from projects p order by p.created_at\""'
#   Project nào có creative_drive_id ≠ 0AASy4v5CJAkfUk9PVA ⇒ import trả lỗi "không nằm trong Shared Drive" — ĐÚNG THIẾT KẾ,
#   thông điệp phải bảo user đổi project trong meta-auto rồi bấm lại.
```

## 8. Tránh

- **Đừng** làm theo spec 15/09 §3-§4 cho việc này (Access app, service token, verify JWT, header relay).
  Đó là lời giải cho bài "Video Desk gọi meta-auto server-to-server" — bài hôm nay không cần S2S.
- **Đừng** dùng token MCP hay tài khoản dịch vụ để tạo bộ (tầng C). `requester_id` sai ở mọi bộ, và
  cột "Người tìm" là thứ đội dùng để chia việc.
- **Đừng** gõ trong `/Users/macos/meta-ads-automation` (lane khác, `feat/ci-local-gate`).
- **Đừng** deploy `--services frontend` khi đã đổi backend (GOTCHA 1 deploy.sh) — tầng A mới được thế.
- **Đừng** bỏ guard `driveId` để "cho nhanh": không có nó, route là máy copy toàn Shared Drive theo id.
- **Đừng** để `?videodesk=` sống sau khi tạo (F5 = bộ thứ hai).

## 9. Giả định

| giả định | tin | đổi khi |
|---|---|---|
| Người bấm ở Video Desk **đã có** tài khoản Creative Desk (login Google một lần) và grant project | cao — user chốt 15/09 "danh tính bên video = bên creative desk" | có người chỉ dùng Video Desk ⇒ họ phải login automation một lần; layout `:78` đưa về /login |
| Project đích là project **đang chọn** trong meta-auto (`active_project_slug` localStorage) | cao | có nhiều project trên nhiều Shared Drive ⇒ hiện tên project trong dialog + lỗi rõ khi driveId lệch |
| `creative_drive_id` của project Creative = `0AASy4v5CJAkfUk9PVA` | trung — chỉ đo được phía SA thấy 1 drive; DB chưa đọc | §7(e) ra khác ⇒ guard đổi thành "driveId ∈ {drive project, drive của Video Desk root}" |
| chốt #11 (nếu là "form nằm TRONG Video Desk") không bắt buộc bằng "có nút chạy thật hôm nay" | trung — không tìm thấy văn bản chốt #11 trong `plans/` (grep rỗng) | user muốn form ở lại Video Desk ⇒ chỉ khi đó mới quay lại spec 15/09 (S2S) |
| SA có `drive` scope đầy đủ (không chỉ readonly) trên VPS | cao — nó tạo folder/upload hằng ngày | — |
