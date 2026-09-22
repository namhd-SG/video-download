# Bàn giao — Video Desk, 22/09 10:25

**Từ** `e58361ea` (tk3, pid 4825, ttys003) · **Điều phối hạm** `uds:/tmp/cc-socks/4387.sock`
**Repo** `/Users/macos/Projects/video-download` · **nhánh** `fix/log-path-and-name-list` · **HEAD `74e5af3`**

> ⏱ Mọi số đo 22/09 10:07–10:25. Đọc lúc khác thì số về mini, đĩa, job **phải đo lại**.

---

## 1. ĐÃ DEPLOY HÔM NAY — `74e5af3`, rc=0

Trên mini trước đó là `b550a1b6` (21/09). Nay là `74e5af3`.

| commit | việc |
|---|---|
| `033d83c` | vá giờ thẻ job — `app.js::fmtDateTime` dùng `toLocaleString("vi-VN")` |
| `74e5af3` | `SO_VONG_DAO_SAU` 5 → **1** — giữ vấn đề 2 ở một lượt |

Kèm theo là toàn bộ nhánh: vấn đề 1 (`e99e730` bỏ ghi đè `tong`), vấn đề 3 (`2640c32` UI cookie),
vá CRITICAL hạn mức (`eff86de`), nhãn "Thiếu" (`4724694`), và **mã** vấn đề 2 (`8b72c93` + `b0397ad`).

**Đường lui:** `bash deploy/rollback-on-mini.sh ../video-download-truoc-260922-102203`
**Bản sao DB trước rsync:** `~/Projects/video-download/web/data/jobs.db.bak-260922-102147` — 94208 B,
sha256 `2188cc14…e97a84` **khớp gốc** (đối chứng bằng hash, không chỉ kích thước).

---

## 2. VÌ SAO `SO_VONG_DAO_SAU=1` — ĐỌC TRƯỚC KHI ĐỔI NÓ

User chốt "deploy 1+3, vấn đề 2 đi chuyến riêng". **Bất khả trên nhánh này**: `8b72c93` (vấn đề 2) đã
nằm sẵn dưới HEAD, và **hai commit trộn hai vấn đề trong cùng một commit** —
`eff86de` vá hạn mức (vđ1) nhưng đụng `scraper.py` (vđ2); `b0397ad` vá cửa sổ quét (vđ2) nhưng đụng
`settings.js` (vđ3). Mổ tay 4 commit ⇒ tổ hợp chưa ai review chưa ai chạy ⇒ rủi ro lớn hơn cái nó tránh.

User chọn đường (c): deploy cả nhánh, hạ hằng số. **Xác nhận lại lúc 10:20** sau khi lane đính chính
(xem §5).

**Đo hai chiều, cùng đầu vào, vá LỚP TRONG (`scrape_music_page`) như sân test thật:**

```
trang 200 video · thư viện đã có 40 cái ĐẦU · user xin 10
  hành vi CŨ (trước 8b72c93):  0 mới · 1 lượt cào · cửa sổ xin=[10]
  SO_VONG_DAO_SAU=1         :  0 mới · 1 lượt cào · cửa sổ xin=[20]
  SO_VONG_DAO_SAU=5         : 10 mới · 2 lượt cào · cửa sổ xin=[20, 60]
```

- `=5` làm vấn đề 2 **XUẤT HIỆN** ⇒ dụng cụ có sức phân định, `=1` chứng minh được thật.
- `=1` ra **đúng con số hành vi cũ**, không phải "nhỏ hơn".
- ⚠ **`=1` KHÔNG tương đương bản cũ**: cửa sổ xin **20 vs 10**, vì `scraper.py:577-579` nới gấp đôi
  **ngay từ lượt 0**. Chữ đúng: *"một lượt, cửa sổ rộng gấp đôi bản cũ"* — **không phải "nằm im"**.

**Mở lại = đổi số về 5 rồi deploy.** Chỉ làm khi sẵn sàng soi lượt chạy thật.

---

## 3. §8.3 — BA SỐ LƯỢT CHẠY THẬT **KHÔNG SINH RA** TRONG CHUYẾN NÀY

Viết đúng chữ này, đừng để người sau đọc thành đã đo.

Vì `SO_VONG_DAO_SAU=1`, cơ chế đào sâu **không chạy**, nên ba số `§8.3` vẫn **CHƯA CÓ**:
1. `so_trang` — một job music/search ăn bao nhiêu trong trần 800/ngày;
2. số lượt thật đã cào + lý do dừng thật (log `multipass: … qua N lượt đã cào`);
3. có chạm rate-limit TikTok không.

⇒ Hai trần `600s` / `5 vòng` vẫn là **LỰA CHỌN**, chưa phải **hiệu chỉnh**. Mọi cơ chế đào sâu tới giờ
chỉ chạy với **scraper giả**, chưa lần nào chạm TikTok thật, và đã **hai lần** "đúng trên giả, sai nếu
chạy thật".

---

## 4. PHÉP ĐO — LỆNH CHẠY LẠI ĐƯỢC

**`SO_VONG_DAO_SAU` runtime trên mini** — phải dùng **venv**, `python3` hệ thống hỏng:

```bash
ssh nobi_auto@100.109.39.103 'cd ~/Projects/video-download && ./.venv/bin/python -c "import web.queue as q; print(q.SO_VONG_DAO_SAU)"'
# → 1
```

Đối chứng: `python3` hệ thống → `ModuleNotFoundError: No module named 'tiktok_music_downloader'`.
Venv là **đúng** thông dịch vì launchd gọi chính nó: `deploy/run-service.sh:7` =
`exec ./.venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 7870`.

**Vá giờ** — đo trên `app.js` mini **đang phục vụ** (tải qua HTTP `:7870`, sha `8c607fe6…` khớp dev),
trích hàm từ file đó, chạy trên mốc thật trong `jobs.db` mini:

```
job 8  thô UTC 2026-09-21T03:44:59.046630+00:00 · kỳ vọng VN 10:44:59 21/9 · hàm mini "10:44:59 21/9/2026"
job 7  thô UTC 2026-09-21T03:44:57.619468+00:00 · kỳ vọng VN 10:44:57 21/9 · hàm mini "10:44:57 21/9/2026"
```

Kỳ vọng tính **độc lập** với hàm đang đo (cộng 7h trên `Date` thô) — không lấy đầu ra của nó làm chuẩn
cho chính nó.

**Control ép múi giờ** — thứ phân định *vá đúng* vs *cộng-tay-7h* (hai cái đó **trùng số** tại Asia/Saigon):

```
TZ=Asia/Saigon        cũ: 07:30:00 | cộng-tay-7h: 14:30:00 | VÁ: 14:30:00 21/9/2026
TZ=America/New_York   cũ: 07:30:00 | cộng-tay-7h: 14:30:00 | VÁ: 03:30:00 21/9/2026
TZ=UTC                cũ: 07:30:00 | cộng-tay-7h: 14:30:00 | VÁ: 07:30:00 21/9/2026
```

Hai mẫu hỏng **đứng yên theo múi**, bản vá **đổi theo múi**.

**Smoke sau deploy:** label astronex theo **TÊN** trước/sau y hệt 5 tên
(`cloudflared · glances · promax · promax-awake · videodl`) · promax `https://promax.nobidigital.asia`
**302** hai đầu · healthz **200** · bind `127.0.0.1` ×1 · sha `index.html`/`app.js`/`app.css` khớp dev ·
`app.js` cache-control `no-cache`.

---

## 5. HAI CHỖ LANE NÀY TỰ BÁC MÌNH — GIỮ LẠI VÌ SẼ TÁI PHÁT

**a) "Nằm im" là nói quá.** Lane trình (c) cho user bằng chữ *"vấn đề 2 nằm im"*, user bấm chọn lúc
10:16 **dựa trên chữ đó**. Đo lại thì sai (§2). Lane đính chính và **hỏi lại user**; user giữ (c) lúc
10:20. ⇒ **Quyết định của user không được đứng trên tiền đề đã biết là sai**, kể cả khi tin kết luận
không đổi — "kết luận không đổi" là phán đoán của lane về ý muốn của user, và chỉ user phán được.

**b) Hai lần "xanh mà rỗng nghĩa".** `357 passed, rc=0` **không chứng minh gì** cho cả hai bản vá:
không test nào chạm `web/static/app.js`, còn `tests/test_web_queue.py:46` **monkeypatch** chính
`SO_VONG_DAO_SAU` nên suite không nhìn giá trị thật. Bằng chứng là hai phép đo riêng ở §4, không phải
357.

**c) `${PIPESTATUS[0]}` là bash — zsh dùng `$pipestatus` (1-indexed).** Lane đo pytest lần đầu ra
**RỖNG**. Cần mã thoát thì **bỏ pipe**, `rc=$?` ngay sau lệnh.

**d) Đo sai đích đọc thành dịch vụ chết.** Lane thử promax ở `:8000` → `000`. Đúng URL là
`https://promax.nobidigital.asia` (`deploy-to-mini.sh:147`) → **302**. `000` là *sai đích*, không phải
*chết*.

---

## 6. NỢ MỚI — `deploy-to-mini.sh` VẪN ĐẾM LABEL, CHƯA SO TÊN

Commit `a479522` (*"compare launchd labels by name, not by count"*) sửa **plan + phase-02**, **không
chạm script**. Thực tế `deploy/deploy-to-mini.sh:117,147`:

```bash
truoc="$(ssh "$HOST" "launchctl list | grep -c astronex || true")"
...
[ "$sau" -ge "$truoc" ] || { echo "MẤT label hàng xóm — kiểm ngay" >&2; exit 1; }
```

⇒ **Mất `videodl` mà mọc thêm một label khác thì cổng vẫn XANH.** Đúng lớp lỗi luật sinh ra để chặn.
Hôm nay không cắn vì lane so **tên** bằng tay ở hai đầu và ra y hệt. **Luật đã ghi, dụng cụ chưa theo.**
Không sửa trong chuyến này — ngoài phạm vi user gật. Điều phối đã xếp hàng đợi.

---

## 7. MINI KHÔNG PHẢI REPO GIT — ĐỪNG ĐI TÌM `.git`

`git -C ~/Projects/video-download log -1` trên mini → **"not a git repository"**. Hợp lý: deploy bằng
`rsync` (`--exclude='.git'`), prod không phải checkout.

⇒ **Không có cách xác nhận sha đang chạy bằng git trên mini.** Đường duy nhất là **so sha256 tệp tĩnh**
với bản dev, đúng như bước 5 của `deploy-to-mini.sh`. Cộng thêm: `.deployed-sha` ở repo meta-ads là
chuyện khác, repo này không có.

---

## 8. CHỜ USER

1. **Đo mắt trên mini** (lane không tự chấm): thẻ job hiện giờ VN chưa · mẫu số `20/50` có nói đúng số
   user xin không · ba trạng thái cookie ở trang Cài đặt.
2. **Mắt T4 #3** — user hứa **chép nguyên văn** câu báo lỗi khi đứng ở project `aldenesk-01` bấm
   "Tạo bộ tự tìm". Đây là đường **duy nhất** kiểm `f89bb9aa` bằng **hành vi**. Hỏi **MỞ**
   (*"câu báo lỗi hiện ra là gì"*), **đừng** hỏi *"nó có bảo đổi project không"* — hỏi bằng giả thuyết
   của mình thì nhận lại chính giả thuyết của mình.
3. **Hai mục mắt T4 còn lại** user đã tick "đã xem" 10:13 nhưng **chưa nói thấy gì**: link "Mở thư mục
   Drive" · Thùng rác Drive có 5 video xoá 18/09 không. *Tick = ĐÃ LÀM, không phải THẤY GÌ.*
4. **Merge PR #2** — đang **draft**, `headRefOid=74e5af3`. **Chưa ai xin, chưa merge.**
5. **§9.1 đã CHỐT (a) giữ nguyên** (user 10:13) — job chạy tới 10 phút khoá hàng đợi cả nhóm, chấp
   nhận. Không còn treo.

---

## 9. NỢ CŨ CÒN NGUYÊN — ĐỪNG LÀM LẠI

- `COLLATE NOCASE` cho email: **thừa** (7 chỗ `.lower()` phủ hết).
- "dừng dịch vụ trước rsync": **sai cơ chế** — `deploy-to-mini.sh:42` `--exclude='web/data'`.
- `videodl.log` 644 "rò liên đội": **sai cơ chế** — `~/Library/Logs` và `~/Library` đều **700**.
- **Trần 20/1000/800**: hoãn có chủ đích. Điều kiện mở lại = có số TikTok chặn ở ngưỡng nào (xem §3).
- `tim_thay` chưa tới mắt user: nợ **có chủ đích**, nhãn "Thiếu" đã phủ ca user nêu.

---

## 10. CÂU CHƯA GIẢI

1. **Ba lỗi 500 (`disk I/O error`)** trên mini — chưa có sự kiện mới. Mốc soát lại **24/09**.
2. **Đĩa mini** ~3,4 Gi / 85% dùng; `/Users/autotest` 51 G. Tồn kho thấp, **không phải** rò rỉ đang
   chảy. Ngoài tầm lane (không sudo) — chủ máy quyết.
3. `/search` chập chờn: 16/09 **0/5** · 18/09 **1/1** · 21/09 job 7 ra 0 (trùng, không phải trượt).
   Câu chữ trên trang nói "chập chờn" kèm cả hai số — **đừng** gỡ thành "đã khỏi".
4. **Vấn đề 2 chưa lần nào chạm TikTok thật** — xem §3. Đây là câu lớn nhất còn mở.
