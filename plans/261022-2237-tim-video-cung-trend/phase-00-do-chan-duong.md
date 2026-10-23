# Pha 0 — Đo chặn đường (trước khi code nguồn tìm)

## Vì sao
README repo (đo 08–09/09): Playwright headless/headful/cookie đều nhận feed search/hashtag RỖNG. GĐ1 (22/10): Chrome thật qua chrome-devtools MCP ra 24/23 link `/search/video`, 114 link `/tag/`. Chưa tách 4 biến (route, DOM vs XHR, ngày/IP, cách điều khiển) — agy R1b. Code nguồn tìm mà chưa biết đường nào sống = đặt cược.

## Phép đo (ngân sách: ≤6 lượt TikTok, 0 lượt tikwm (0e đã đo), giãn ≥10 s)
| # | Đo | Kết quả cần ghi |
|---|---|---|
| 0a | Playwright `chromium.launch_persistent_context(channel="chrome", headless=False)` mở `/search/video?q=7 pose ai trend`, đếm `a[href*="/video/"]` sau 8 s | số link |
| 0b | Như 0a nhưng `headless=True` | số link |
| 0c | `connect_over_cdp` vào Chrome user tự mở (`--remote-debugging-port`, profile riêng) | số link |
| 0d | Như đường thắng ở 0a–0c, với `/tag/<x>` | số link |
| 0e | ~~tikwm `api/feed/search` từ ca-n~~ **ĐÃ ĐO 22/10 22:5x** (lane Logo, ca-n, UA repo): **403 Cloudflare**; cùng IP/UA `api/challenge/posts` = 200 ⇒ chặn theo ENDPOINT. Không lách Cloudflare (ĐP). | xong |
| 0f | Lặp đường thắng 3 lượt liên tiếp (giãn 30 s) | link lượt 1/2/3 — có bị chặn khi lặp không |

## Quyết định sau đo
- 0b > 0 ⇒ mặc định headless (chạy được cả trên máy không ngồi).
- chỉ 0a/0c > 0 ⇒ mặc định Chrome có cửa sổ trên máy dev.
- Từ khoá: CHỈ qua Chrome thật (0e đã loại tikwm `feed/search`). Hashtag: Chrome `/tag/` hoặc `hashtag_enumerator` sẵn có của repo (tikwm `challenge/posts`, đang sống).
- Tất cả = 0 ⇒ DỪNG, báo ĐP (B: API trả phí).

## Ra
Bảng số đo vào `plans/reports/` + 1 dòng nhật ký. Không code sản phẩm ở pha này (script đo để trong scratchpad).
