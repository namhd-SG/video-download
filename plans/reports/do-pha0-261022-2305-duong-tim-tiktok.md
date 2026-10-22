# Pha 0 GĐ2 — đường tìm TikTok nào sống (máy dev, 22/10 ~23:0x)

Script: scratchpad `pha0/do_pha0.py` (Playwright 1.64, `launch_persistent_context(channel="chrome")`, profile tạm mới mỗi lượt, không cookie, không đăng nhập; đọc DOM `a[href*="/video/"]` + `img`; hâm phiên = goto lần 2 cùng context khi ≤1 link, như `scraper.py:509`).

| # | Chế độ | Trang | Lượt 1 | Lượt 2 (hâm phiên) | Ảnh bìa | Tải 1 ảnh bìa |
|---|---|---|---|---|---|---|
| 0b | headless | search "7 pose ai trend" | 0 | 0 | 0 | — |
| 0a | có cửa sổ | search "7 pose ai trend" | **24** | — | 24/24 | 200, 44 575 B |
| 0d | có cửa sổ | `/tag/aicatwalk` | **53** | — | 53/53 | 200, 49 240 B |
| 0f-1 | có cửa sổ (+30 s) | search "kolase 7 pose" | 0 | **17** | 17/17 | 200, 61 364 B |
| 0f-2 | có cửa sổ (+30 s) | search "ai catwalk" | **24** | — | 24/24 | 200, 32 184 B |
| 0c | connect_over_cdp | — | không đo (0a đã sống) | | | |
| 0e | tikwm feed/search | (ca-n, lane Logo) | 403 Cloudflare — theo endpoint | | | |

**Request TikTok đã dùng: 7 / ngân sách 6 — VƯỢT 1.** Cơ chế: hâm phiên tự thêm 1 goto khi lượt đầu rỗng (0b, 0f-1); đếm ngân sách theo "kịch bản" chứ không theo goto. Không bị chặn/captcha ở lượt nào.

## Quyết định
- Đường chính: **Chrome có cửa sổ (`channel="chrome"`, `headless=False`) + hâm phiên** — 4/4 lượt có cửa sổ ra link (24/53/17/24), lặp 3 lượt giãn 30 s không bị chặn.
- **Headless = 0 kể cả hâm phiên** ⇒ công cụ BẮT BUỘC chạy trên máy có màn hình (máy dev), mở cửa sổ Chrome trong lúc chạy. Ghi trong `--help`.
- Hâm phiên CẦN (0f-1: 0 → 17). Ngân sách công cụ phải đếm theo goto (gồm lượt hâm).
- Từ khoá chỉ qua Chrome (0e loại tikwm). Hashtag: Chrome `/tag/` sống (53 link) ⇒ dùng Chrome cho cả hai, `hashtag_enumerator` (tikwm) để dự phòng.
