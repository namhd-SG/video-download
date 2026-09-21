# Team dùng thật trong hôm nay — 17/09/2026

**Viết bởi:** kongming (tư vấn, không thi công) · 11:15 · **cho:** lane điều phối (người gõ)
**Nhánh:** `feat/tiktok-tag-page-support` · HEAD `e1066c3` · mini đang chạy đúng HEAD này (deploy 10:33, đã nghiệm thu).
**Trạng thái:** đề xuất, chưa gõ dòng nào.

## 7 quyết định user ĐÃ KHOÁ (không mở lại)

1. Sở hữu video = **ai nhấn tải** (`jobs.nguoi_tao` của job đã tải về thật).
2. Lọc trùng **toàn kho** giữ nguyên (`known_video_ids` đọc cả bảng `videos`).
3. Mỗi video đúng một chủ ⇒ không claim, không refcount.
4. Xoá = **đưa vào Thùng rác Drive** (`files.update trashed=true`), không nâng vai SA.
5. Xoá phải **nhớ đã loại**: lần quét sau không tải về lại.
6. Setting: cookie riêng từng người + trần; thành viên = thành viên Creative Desk.
7. Không chạy song song.

## (a) Cắt phạm vi — mốc cuối ngày là KHẢ THI cho lát cắt dưới, KHÔNG khả thi cho trọn 6 việc

"Hoạt động được hôm nay" định nghĩa đo được: **một thành viên khác user, chưa từng dùng tool, dán cookie của mình → tạo job → video lên Drive → thấy đúng video của mình trong thư viện, không thấy job/URL của người khác.** Đó là Deploy 1.

| tầng | việc | vì sao ở tầng này | ước lượng (gõ + test) |
|---|---|---|---|
| **BẮT BUỘC hôm nay — Deploy 1** | P1 vá `GET /jobs/{id}` + `/events` theo người | đang rò URL + mã cookie của người khác cho mọi người đăng nhập; 2 dòng | 30' |
| | P2 thư viện lọc theo chủ (`list_videos`/`count_videos`/`sources_for_videos` nhận `chi_cua` bắt buộc) + bỏ hộp lọc "Người tải" | quyết định 1; **không đổi schema** | 1h30 |
| | P3 trang "Cookie của tôi" (`GET/PUT/DELETE /me/cookie`, `GET /me`) + banner ẩn danh | **B1 — thứ duy nhất chặn mở team**; không đổi schema | 2h30–3h |
| | Deploy 1 + nghiệm thu bằng người thứ hai | | 45' |
| **NẾU CÒN GIỜ — Deploy 2 (tối)** | P4 "Loại khỏi kho" = trash + cột `da_loai_luc/loai_boi` | quyết định 4-5; **có migration** ⇒ sao lưu DB trước; không chặn team tải | 2h |
| | P5 `GET /me/quota` hiện hạn mức đã dùng (đọc-chỉ) | rẻ; trần vẫn là hằng | 45' |
| **MAI trở đi — không ai bị chặn** | P6 Drive retry (user chốt 16/09) · admin đặt trần riêng từng người + trần toàn cục (bảng `settings`, env admin) · tab "Đã loại" + khôi phục · vị trí hàng/ETA/huỷ pending · TTL cookie 14 ngày · taxonomy/bộ tự tìm (chờ meta-auto, CI hết quota tới ~01/10) | | |

Tổng tầng bắt buộc ≈ **5h15–5h45** ⇒ Deploy 1 khoảng **16:30–17:00** nếu bắt đầu 11:30 và không vướng. P4 ≈ 2h nữa ⇒ Deploy 2 ~19:30 là "nếu còn giờ" thật, không hứa. **Nói thẳng:** nếu tới 17:30 P3 chưa xanh, deploy P1+P2 trước — team vẫn dùng được **ẩn danh** (hashtag không cần cookie, xem phase-02 §Onboarding) và không rò gì; P3 lên sáng mai.

## (b) Thứ tự + cái nào chặn cái nào

```
P1 ──┐
P2 ──┼──► Deploy 1 (cần user gật) ──► nghiệm thu 2 người ──► P4 ──┐
P3 ──┘                                                   P5 ──┼──► Deploy 2 (cần user gật)
                                                          P6 ──┘  (hoặc mai)
```
- P1, P2, P3 độc lập về file (P1: `app.py` 2 route; P2: `models.py` + `app.py` `/videos` + `app.js`; P3: `app.py` route mới + `cookies.py` + `index.html`/`app.js` panel). Gõ tuần tự P1→P2→P3 để `app.py` không xung đột với chính mình.
- P4 phụ thuộc Deploy 1 **chỉ vì** migration: gộp migration vào một deploy riêng để nếu lỗi thì lui đúng một thứ.
- Deploy nào cũng: grep log 15' xem có ai đang dùng (luật lane 16/09) · 0 job `pending/running` · sao lưu `jobs.db` (bắt buộc với Deploy 2 vì đổi schema; rẻ nên làm cả Deploy 1).

## (c) Từng hạng mục — xem phase file

- `phase-01-va-quyen-va-thu-vien-rieng.md` — P1 + P2
- `phase-02-cookie-cua-toi.md` — P3 (+ khuyến nghị onboarding)
- `phase-03-loai-khoi-kho-trash-va-nho.md` — P4 (+ thiết kế nhớ-đã-loại ↔ lọc trùng)
- `phase-04-deploy-va-viec-cua-user.md` — hai chuyến deploy, nghiệm thu, danh sách việc user làm

## Ba câu thiết kế (tóm; chi tiết trong phase)

**Nhớ-đã-loại ↔ lọc trùng:** GIỮ hàng `videos`, thêm `da_loai_luc`, `loai_boi`. `known_video_ids` **không lọc theo cột này** ⇒ mọi người, kể cả người khác, quét trúng video đã loại đều bỏ qua (khớp quyết định 2 và 5 cùng lúc). Thư viện lọc `da_loai_luc IS NULL`. Ảnh thumb giữ (2 KB). Mốc chỉ ghi **SAU** khi Drive trả `trashed=true`. Ca biên trong phase-03.

**Thư viện riêng — lỗ nào hôm nay:** `count_videos` (bắt buộc — `tong` điều khiển vòng nạp trang `app.js:605-614`, sai là nạp lệch) · `sources_for_videos` lọc theo chủ (bắt buộc — rò URL search của người khác, cùng hạng `jobs.url`) · bỏ hộp "Người tải" (bắt buộc — vô nghĩa và lộ email) · `LEFT JOIN` mồ côi → admin thấy, thành viên không (chấp nhận, ghi) · `/thumbs` kiểm chủ (**ĐÃ LÀM `5c4c0a1`** — lý do hoãn cũ *"id 19 chữ số không đoán được"* **SAI về cơ chế**: kẻ hỏi không đoán, `hashtag_enumerator.py:165` của chính repo này trích `video_id` cho mọi item của một feed, nên ai cũng cầm được id thật hàng loạt. Cặp 200/404 khi đó trả lời *"team đã tải video này chưa"* — đúng thứ tổng hợp mà `sources_for_videos` vừa được lọc để giấu. Vá rồi: cùng câu chữ 404 cho "không có" và "của người khác".)

**Onboarding cookie — khuyến nghị dứt khoát: CHO chạy ẩn danh + banner, KHÔNG chặn.** Lý do đo: hashtag không dùng cookie (`queue.py:161-169` `enumerate_hashtag` không nhận `cookies_path`); music page ra **10 video dù có hay không cookie** (handoff 16/09 §6); `/search` chết cả khi có cookie (0/5). Chặn là chặn đường không cần cookie, thêm một nhánh phải test hôm nay, và buộc người mới dán cookie trước khi thấy tool có ích. Cái giá phải khai: người chưa dán **chia chung pool `khong-cookie` 20 job/ngày** (`cookies.py:22`) — banner nói đúng điều đó là đủ tạo động lực.

## Câu chưa giải (trình user cùng lúc, phase-04 §E)
1. Policy Access của `video.nobidigital.asia` hiện cho ai vào — cả domain hay danh sách? (quyết định 6 "thành viên = Creative Desk" thi hành ở đây, 0 dòng code). **CHƯA ĐO.**
2. Vai SA hiện tại — kiểm `drives().get(capabilities)` kèm giờ trước khi gõ P4.
3. Có 1 project Creative Desk hay nhiều? (ảnh hưởng taxonomy mai, không ảnh hưởng hôm nay.)
