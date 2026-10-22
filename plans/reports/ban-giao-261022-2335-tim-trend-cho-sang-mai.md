# Bàn giao — tìm video cùng dạng (GĐ2), dừng 22/10 23:35 chờ IP nguội

Nhánh `feat/tim-video-cung-trend` (worktree `~/Projects/video-download-wt-tim-trend`, venv `.venv` playwright **1.62.0** — đừng nâng, 1.64 cần chromium-1248 chưa có). Chưa push.
Commit: c3cad36 plan · 5b9db72 Pha 0 · 36b3275 Pha 1 · 25b30a1 Pha 2 · 07e4195 Pha 3 · ea6a66b vá captcha/0 ứng viên.

## Trạng thái
- Pha 0–3 xong. Test công cụ 55/55; đột biến có nghĩa 7/7 đỏ. Toàn suite (07e4195): 3043 pass, 1 fail chập chờn `test_giai_captcha_popup_browser::…dang_chan` (riêng 3/3 xanh).
- **Pha 4 CHƯA ĐẠT**: video 1 chạy 22/10 23:2x ⇒ 12/12 lần mở trang rỗng vì **TikTok hỏi captcha** (ảnh `scratchpad/pha0/do1-chan-doan/lan1.png`). Video 2 chưa chạy.
- **CẤM request TikTok từ máy dev tới ≥ 07:30 23/10** (ĐP).

## Việc sáng mai (theo thứ tự, ĐP đã duyệt)
1. Đo phân định Playwright: `scratchpad/pha0/do_chan_doan.py` 1 lượt với venv 1.62, 1 lượt với venv tạm 1.64 (scratchpad, không đụng venv worktree). Mỗi lượt ≤2 lần mở trang + ảnh chụp. Báo ĐP trước khi chạy (cửa sổ Chrome bật lên).
2. Không captcha ⇒ Pha 4: `.venv/bin/python -m tiktok_music_downloader.tim_trend "/Users/macos/Downloads/video test.mp4" --ra <dir>`; rồi video 2 (tải `@harry_gunawan999/video/7619141013801667861` bằng `yt-dlp --impersonate chrome`). Tuần tự. Ngân sách ≤12 lần mở trang/video.
3. Nghiệm thu: kiểm mắt TOÀN BỘ link giữ; video 1 ≥8 URL & ≥70% đúng dạng; video 2 ≥5 URL & ≥60% catwalk & 0 collage; đối chứng dương 3 mọi lô.
4. Captcha lại ⇒ dừng, báo ĐP. Câu "tạm dừng chờ user tự giải captcha trong cửa sổ" — ĐP đang hỏi user, CHƯA làm.

## Hoãn (ghi trong PR)
HashtagTim (tikwm `challenge/posts`: không có ảnh bìa; Chrome `/tag/` đủ) · `nhac.py` (shazamio).

## Cổng merge
Toàn suite xanh trên đúng head PR + code-reviewer do ĐP gọi + agy KHÉP + mục "ca nào main đúng mà nhánh sai" ⇒ ĐP gật ⇒ `gh pr merge --merge --match-head-commit <sha>`.
