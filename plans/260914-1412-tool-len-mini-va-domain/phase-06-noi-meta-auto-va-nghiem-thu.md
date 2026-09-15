---
phase: 6
title: "Nối meta-auto + nghiệm thu"
status: pending
priority: P2
effort: "0.5-1d"
dependencies: [3, 4, 5]
---

# Phase 6: Nối meta-auto + nghiệm thu

## Overview

Nối tool vào meta-auto để người dùng tìm thấy, rồi nghiệm thu toàn hệ bằng phép đo
chứ không bằng cảm giác.

## ✅ USER CHỐT 14/09 — đường (a): link trong nav

Tiêu chí anh đưa ra là **"an toàn là được"**, và (a) đúng là đường an toàn nhất
trong ba: tool hỏng **không** kéo meta-auto theo, không dính nhịp deploy của nhau,
không cần cầu danh tính giữa hai hệ. Trùng luôn với tiền lệ Promax đang chạy.

Phần dưới giữ lại làm hồ sơ quyết định — để sau này ai hỏi *"sao không nhúng vào
app?"* thì có câu trả lời kèm số đo, không phải kể lại từ trí nhớ.

## Hồ sơ quyết định (đã chốt, không cần làm lại)

Ngày 10/09 anh chốt *"một trang trong app sẵn có"*. Ngày 14/09 tôi đề xuất đổi, và
thẩm định bắt được rằng **lý lẽ tôi dùng để đề xuất là sai**:

**Bản đầu của tôi trình sai — đã sửa sau thẩm định 14/09.** Tôi viết *"nhúng UI ⇒
phải có hàng đợi xuyên máy"* và dùng đó để biện minh việc đổi chốt của anh. Đó là
**nhị nguyên giả**: trang meta-auto hoàn toàn có thể là thin-client gọi thẳng API
trên mini, không queue, không iframe. Tôi đã dựng một lựa chọn giả để lựa chọn của
mình trông tất yếu.

Ba đường thật, anh chọn:

| | (a) link trong nav | (b) trang meta-auto gọi API mini | (c) nhúng thật + queue xuyên máy |
|---|---|---|---|
| thoả chốt 10/09 của anh | không hẳn | **có, nguyên văn** | có |
| worker ở | mini | mini | mini |
| chi phí thêm | ~0 | **+1-2 ngày**: CORS + cầu danh tính | cao, nhiều thứ để hỏng |
| dính nhịp deploy meta-auto | không | có | có |
| tool hỏng có kéo meta-auto? | không | không | có thể |
| tiền lệ | **Promax** trên chính máy đó: hostname riêng, 0 dòng trong frontend meta-auto, chạy nhiều tháng | — | — |

**Đề xuất (a)** làm mặc định vì rẻ nhất và có tiền lệ đang chạy. **(c) bỏ hẳn.**

**Chọn (b) nếu** một trong hai điều sau đúng — và chỉ anh biết: người dùng cần thấy
trạng thái job **ngay trong dashboard meta-auto**, hoặc danh tính meta-auto phải là
danh tính gắn với cookie TikTok.

Chi phí thật của (b) không phải queue, mà là **cầu danh tính**: session meta-auto ≠
session Cloudflare Access, nên cần service token hoặc cho cả hai dùng chung một IdP
Google (có thể dùng lại danh sách email đã có của meta-auto).

## Requirements

- Functional: từ meta-auto bấm một cái là sang tool.
- Non-functional: tool hỏng **không** kéo meta-auto theo.

## Architecture

```
meta-auto (VPS)  --link--> video.nobidigital.asia (mini, cloudflared)
                            └── Cloudflare Access dùng chung danh sách người dùng
```

Một link, không nhúng iframe: iframe kéo theo bài toán cookie bên thứ ba và CSP,
đổi lấy đúng một chút tiện.

## Related Code Files

- Modify: `frontend/src/…` trong repo meta-ads-automation — thêm mục nav
  *(đúng 3 chỗ theo memory: sidebar + `isGuestAllowed` + guard route)*
- Create: `docs/video-download-service.md` — chỗ chạy, cách restart, cách xem log

## Implementation Steps

1. Thêm mục nav trong meta-auto trỏ `https://video.nobidigital.asia` — đúng 3 chỗ
   theo mẫu đã biết: sidebar + `isGuestAllowed` + guard route.
2. Viết tài liệu vận hành: label LaunchAgent, port, đường log, cách restart,
   cách dựng lại từ đầu (`deploy/mini-setup.sh` từ Phase 01).
4. Chạy nghiệm thu toàn hệ ở dưới.
5. Ghi một dòng vào `~/agy-ws/BOARD.md` — **chỉ được mang chữ XONG khi kèm được
   lệnh + output**, nếu không thì ghi *"ĐÃ DỰNG, chưa nghiệm thu"*.

## Success Criteria — nghiệm thu toàn hệ

- [ ] Từ máy ngoài LAN (4G): mở hostname, dán link hashtag, nhận video thật
- [ ] **Tự lên sau reboot.** ⚠ Đây là reboot **máy production của người khác** —
      không tự bấm. Đường rẻ hơn theo thứ tự: (1) lấy bằng chứng Promax đã sống qua
      lần reboot trước (máy vừa `up 4:19` sáng 14/09 mà Promax vẫn 302 ⇒ đã có sẵn
      một ca dương); (2) `launchctl kickstart -k` để thử vòng đời mà không reboot;
      (3) nếu vẫn phải reboot thật thì **hẹn trước với chủ Promax**.
      Điều kiện tiên quyết đã kiểm ở Phase 01 bước 8: không có auto-login thì
      LaunchAgent **không** tự lên, và mọi thứ vẫn xanh cho tới lần mất điện đầu tiên
- [ ] Hai người dùng khác nhau chạy job song song → job tuần tự, cookie không lẫn
- [ ] Job xong → thư mục làm việc trên mini **rỗng**, link Drive mở được, đếm khớp
      (thiết kế đổi 14/09: không còn bản local, không còn TTL file)
- [ ] `promax.nobidigital.asia` 200/302 **trong suốt** quá trình nghiệm thu, lấy mẫu
      đầu và cuối
- [ ] `launchctl list | grep astronex` đúng bộ label như trước khi bắt đầu, cộng
      thêm đúng label của mình

## Risk Assessment

**Ghi "XONG" khi chưa đo.** Đã xảy ra: board ghi *"gộp 5 nguồn XONG"* mà nghiệm thu
hôm sau ra **1/6**, và user phát hiện sau 2 ngày. *Phản ứng:* dòng board phải kèm
lệnh + output, hoặc ghi *"ĐÃ DỰNG, chưa nghiệm thu"*.

**Tool chết lặng lẽ, không ai biết.** *Tín hiệu:* hostname không trả 200.
*Phản ứng:* thêm một phép canh nhẹ — cron curl hostname, trượt 3 lần liên tiếp thì
báo Telegram. Mốc "đã báo động" phải **tách khỏi** mốc "đã xong": gộp hai cái làm bộ
canh tự tắt sau lần phán đầu, đúng lúc cần nhất.

**Người dùng trông đợi `/search`** rồi tưởng tool hỏng. *Phản ứng:* UI ghi rõ nguồn
nào chạy được (hashtag ✓ · music ✓ · FB Ads ✓ · Drive ✓ · search ✗/tuỳ Phase 05).
