# Smoke máy dev R-08 M3 — 18/11/2026 16:47–17:15 (lane C tk3)

Code: worktree lane-c (nguồn `InstagramHangLoat` + `download_all(nen_tang="instagram")`), gọi trực tiếp ở mức nguồn (KHÔNG qua web/job/pacer). Cookie tài khoản phụ (user cấp), đã xoá sau smoke. yt-dlp 2026.08.19 (= ca-n). Mặc định headless.
Tổng: 20 lượt mở trang IG / ~30 phút + 36 lượt yt-dlp. 0 lần 429/challenge.

## Liệt kê + tải (cookie đủ)
| link | N | refs mới | lý do dừng | mp4 tải / thử | chạy lại |
|---|---|---|---|---|---|
| 1 profile reels | 10 | 10 | complete | 10/10 | 10 mới, 10 bỏ (đã có), 0 trùng |
| 2 keyword tandoor | 10 | 10 | complete | 2/2 | — |
| 3 #emiuquan2 | 20 | **6** (đúng 6 video trong 51 mã) | stalled | 1/1 | 0 mới, already_owned |
| 4 audio 2830… | 5 | 2 (trang thật 2) | stalled | 1/1 | — |
| 4b audio 1485893805770596 | 20 | 20 | complete | 1/1 | — |
| #foodreels (nghiệm thu hashtag ≥20) | 20 | 20 | complete | **20/20** | 20 mới, 20 bỏ, 0 trùng |
AC: profile N=10 ⇒ 10 mới (≥8 ✔); hashtag N=20 ⇒ 20 mới (≥16 ✔); chạy lại 0 trùng ✔; link 3 ra đúng 6 ✔.

## Mất phiên (cookie bỏ `sessionid`)
| trang | kết quả |
|---|---|
| keyword | dừng `ig_mat_phien` [url_dang_nhap] ✔ |
| audio (lượt 1, code agent) | **KHÔNG bắt** — ra 10 video ẩn danh; nút "Log in" không khớp `text-is` (chữ ở thẻ con) |
| audio (sau sửa: thêm dấu `a[href*='/accounts/login']`) | dừng `ig_mat_phien` [dom_dang_nhap] ✔ |
Đối chứng sau sửa, cookie đủ, N=3: profile / keyword / hashtag / audio đều 3 mới, 0 dừng oan ✔. Đo DOM: thiếu sessionid ⇒ 1 liên kết `/accounts/login`, đủ phiên ⇒ 0. Test mới `test_dau_dom_lien_ket_accounts_login_la_nut_dang_nhap` + đột biến bỏ dấu ⇒ 1 đỏ.

## Log (dòng INFO+ của smoke, 65 dòng)
URL 0 · handle 0 · cookie 0 · mã bài 35 dòng `✓ ig-<mã>.mp4` của `download_all` (dòng chung mọi nền tảng) ⇒ qua `CheUrlFormatter` của prod thành `✓ <id>.mp4` (đã chạy thử) ⇒ log prod 0 mã bài. DEBUG yt-dlp có đường tệp chứa mã, prod chạy INFO.

## Chưa smoke
Luồng web đầy đủ (PUT /me/cookie/instagram → POST /jobs → worker → thẻ đỏ) — chỉ có test tự động; nhịp pacer thật; máy prod ca-n.
