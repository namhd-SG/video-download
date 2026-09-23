# ĐỀ BÀI LANE V (kế nhiệm) — UI COOKIE của tool video-download

Điều phối `577b340e` viết 23/09 10:20. Lane V mới: **tkgiang · Opus · pid 17794 · ttys001**. Chữ tin `V`, **tiếp từ V101**
(V cũ `4825` đóng 10:00 ở V100). Báo về `uds:/tmp/cc-socks/26888.sock`.
⚠ Bạn ở **tkgiang** ⇒ memory tk3 của lane V cũ **không tự nạp**. Đọc file bàn giao dưới đây thay memory.

## 0. Đọc trước — KIỂM, không đọc
`plans/reports/handoff-260923-0950-videodl-sau-4-pr.md` (`6ce27e3`, md5 `6f843fbbae4803b9412471d0d3200697`, 188 dòng).
§1 mốc · §2 ba thứ mới · §3 mắt user ĐẠT 3/3 · §5 bẫy đã đo · §6 nợ. **Bàn giao cũ `handoff-260922-1025` có banner ⛔ — không tin nó.**

## 1. User nói gì (10:17, nguyên văn)
> "còn về tool video download thì **dừng ở việc báo N khi tải** thôi, tuy nhiên tôi cần fix thêm chỗ **UI khi thêm cookie**
> như tôi có nói với bạn trước đó là khi add cookie vào thì **đang không biết cookie đó là của account nào**; thứ 2 **UI hiện tại
> trang cookie đang hơi khó nhìn** và phán đoán — cần **brainstorm tiếp để cải tiến** nhé, vì sau đó còn cần rất nhiều các **nền tảng
> khác cần cookie như Instagram, Facebook**."

⇒ Ba yêu cầu, một hướng:
1. **Cookie thuộc account nào** — sau khi dán cookie, trang phải nói *"cookie này của tài khoản TikTok @xxx"* (hoặc *"không đọc được
   danh tính"*). Không để user đoán.
2. **Trang cookie dễ nhìn, dễ phán đoán** — trạng thái cookie (còn hạn / hết hạn / rỗng / chưa đăng nhập / không đọc được) phải
   **nhìn là biết**, không phải suy.
3. **Thiết kế cho nhiều nền tảng** — mô hình cookie theo `platform` (TikTok hôm nay; Instagram, Facebook sắp tới), **không** hard-code TikTok.
   Nhưng **chỉ THI CÔNG TikTok** — nền tảng khác là thiết kế mở đường, không làm.

**Không làm:** ô tra cứu "link đã có trong kho chưa" (user chốt dừng ở báo N) · bất kỳ tính năng tải mới nào.

## 2. Hiện trạng đã đo (từ bàn giao `6ce27e3`)
- Cookie **từng người một jar**: `web/data/cookies/` = 2 jar (`-rw-------`), `PUT /me/cookie` = 5 lần. G4 = XONG.
- **3-4 trạng thái cookie** (`cookie_khong_doc_duoc` · `cookie_rong` · `cookie_chua_dang_nhap` · `cookie_het_han`) — **user gật gộp "đạt hết",
  chưa thử từng trạng thái** ⇒ CHƯA ĐO. Đo lại là bước đầu của bạn.
- `app.py:164` `quet_jar_tam` dọn jar tạm lúc khởi động; `SO_VONG_DAO_SAU=1` — mã vấn đề 2 có nhưng không chạy (§4 bàn giao, giữ nguyên).
- Deploy mini: `deploy/deploy-to-mini.sh` có **cổng 0-job + so tên label** (PR #5, `71333fa`), 5 mã thoát; đường lui `rollback-on-mini.sh`.
- `sqlite3 -readonly` **không mở được WAL**; `curl :7870/jobs` trả **401** sau Cloudflare Access ⇒ nghiệm thu bằng `models.*` trên DB.

## 3. Cách làm — theo thứ tự, không nhảy bước
1. **KIỂM bàn giao** (danh tính · md5 · cây `main`=`origin/main`=`6ce27e3`? · `ssh nobi_auto@…` tới mini được không · **liệt việc treo §6 kèm trạng thái**).
2. **Đo 4 trạng thái cookie hiện tại** trên DB **dev** (không đụng mini): mỗi trạng thái một jar giả → UI hiện gì. Đây là baseline **trước** khi vẽ.
3. **Brainstorm 1 trang** (`plans/260923-*-cookie-ui/plan.md`): (a) làm sao biết cookie thuộc account nào — đọc từ cookie? gọi endpoint
   `me` của TikTok? có tốn request/trần không? (b) mô hình `platform` cho IG/FB; (c) UX trang cookie. **Khai điểm mù + hai hình dạng hỏng.**
4. **Mock HTML ra file** trong repo (`plans/<kế-hoạch>/mock-*.html`) — **luật**: việc có giao diện phải có file mock trên đĩa, subagent trả
   **ảnh chụp**; điều phối **tự mở ảnh**. Trình user duyệt mock **qua điều phối** (luật 16:30), không hỏi thẳng.
5. Thi công sau khi mock duyệt → test có **control** (bản chưa vá phải ĐỔ) → PR → user merge trong pane bạn (bắn điều phối trước) →
   deploy mini theo khuôn V93/V95 (thử khô đi tới `2b`, lệnh + đường lui trước khi bấm).

## 4. Ràng buộc
- `git add <đường dẫn>`, **cấm `-A`/`.`/`stash`**, đọc `git log --oneline origin/main..HEAD` từng dòng trước push.
- Cookie là **dữ liệu nhạy cảm**: không in giá trị cookie ra log/report/tin nhắn — `[redacted]`, đếm, tên trường.
- Không deploy khi chưa được điều phối gật. Không đụng jar thật của 2 người đang dùng.
- Phân vân ⇒ trình điều phối trước. Khuôn báo: `Status` · `Summary` · **`NHẸ ĐI:`** · Concerns.
- Mỗi bước có **thứ nhìn được** (ảnh/số), không đo 3 ngày rồi mới báo.
