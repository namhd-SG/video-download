---
phase: 4
title: "Ra domain qua cloudflared"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: [2, 3]
---

# Phase 4: Ra domain qua cloudflared sẵn có

## Overview

Máy đã chạy cloudflared với một tunnel và một hostname. Thêm hostname mới là **sửa
một file YAML + thêm một DNS record** — không dựng tunnel mới, không cần sudo.

## ⚠ SỬA SAU THẨM ĐỊNH 14/09 — phase này từng có lỗ nghiêm trọng

Bản đầu để `dependencies: [2]` và đặt Cloudflare Access ở tận Phase 05. Nghĩa là sau
phase này, `video.nobidigital.asia` là **endpoint công khai không xác thực**, nhận
`POST /jobs` sinh Chromium và ghi đĩa 11 GB **trên máy chạy production của người
khác**. Và hostname mới không hề "chưa ai biết": Certificate Transparency log công
bố nó trong vài phút. Chính tiêu chí nghiệm thu cũ *"mở từ 4G được"* là bằng chứng
của lỗ đó.

**Đã sửa:** bật Access **trong phase này**, trước khi ingress trỏ vào 7870; và phase
này phụ thuộc guard đĩa của Phase 03.

## Requirements

- Functional: `https://<hostname>` mở được từ máy bất kỳ ngoài mạng, **sau xác thực**.
- Non-functional: **không làm gián đoạn** `promax.nobidigital.asia` đang chạy;
  không có khoảnh khắc nào hostname mở mà chưa có Access.

## Architecture

`~/.cloudflared/config.yml` hiện tại (đã đo, token ẩn):

```yaml
tunnel: <id>
credentials-file: /Users/nobi_auto/.cloudflared/<id>.json
ingress:
  - hostname: promax.nobidigital.asia
    service: http://localhost:7860
  - service: http_status:404
```

Sau khi sửa — **chèn TRƯỚC nhánh 404 cuối cùng**, thứ tự ingress có ý nghĩa:

```yaml
ingress:
  - hostname: promax.nobidigital.asia
    service: http://localhost:7860
  - hostname: <hostname-moi>
    service: http://localhost:7870
  - service: http_status:404
```

Hostname đề xuất: `video.nobidigital.asia` (cùng zone với promax và meta-auto, DNS
đã quản ở đó).

## Related Code Files

- Modify: `~/.cloudflared/config.yml` trên mini — **sao lưu trước khi sửa**
- Create: DNS CNAME record trỏ về tunnel (làm ở Cloudflare dashboard hoặc
  `cloudflared tunnel route dns`)

## Implementation Steps

1. **ĐO TRƯỚC:** cloudflared chạy locally-managed (`--config`) hay remotely-managed
   (`--token`)? `ps -ax | grep cloudflared`. Nếu là `--token` thì `config.yml` **bị
   bỏ qua** và toàn bộ phase này làm ở dashboard, không sửa file. Đây là giả định
   chưa kiểm của bản đầu.
2. **ĐO TRƯỚC:** label thật của LaunchAgent cloudflared. Bản đầu viết
   `com.astronex.cloudflared` từ output `launchctl list`, nhưng mặc định của
   `cloudflared service install` là `com.cloudflare.cloudflared` — phải xác nhận,
   kickstart nhầm label là đụng dịch vụ người khác.
3. `cp ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak-260914`.
4. **Bật Cloudflare Access cho hostname mới TRƯỚC**, khi ingress còn trỏ
   `http_status:404`. Access phải xanh rồi mới cho hostname chạm 7870.
5. Thêm khối hostname mới **phía trên** nhánh `http_status:404`.
6. `cloudflared tunnel ingress validate` — kiểm cú pháp **trước** khi nạp lại.
7. Tạo DNS: `cloudflared tunnel route dns <tunnel> video.nobidigital.asia`.
8. **Thử không restart trước.** cloudflared tự nạp lại `config.yml` khi file đổi —
   sửa file rồi `curl` xem đã ăn chưa. Ăn rồi thì **bỏ hẳn bước restart**, đỡ rớt
   Promax vài giây và đỡ cắt request đang bay.
9. Chỉ khi bước 8 không ăn mới `launchctl kickstart -k gui/$(id -u)/<label-đã-đo>`.
   ⚠ **KHÔNG** `launchctl bootout` — tiền lệ 27/08 làm tắt lưới an toàn 32 phút.
10. Đo cả hai hostname, mỗi cái **3 lần** (một lần trượt không kết luận được gì).

## Success Criteria

- [ ] **Không đăng nhập** → `curl -I https://video.nobidigital.asia` trả **302 về
      trang đăng nhập Access**, KHÔNG phải 200 từ tool. Đây là tiêu chí quan trọng
      nhất của phase; thiếu nó là mở cửa cho cả internet
- [ ] Đăng nhập rồi → mở được tool, **3/3 lần**
- [ ] `curl -I https://promax.nobidigital.asia` vẫn 302, **3/3 lần** — hàng xóm
      không bị đụng
- [ ] Từ máy ngoài mạng LAN (dùng 4G) vẫn mở được sau đăng nhập — chứng minh đi qua
      tunnel thật, không phải nhờ cùng LAN
- [ ] `launchctl list | grep astronex` trả **đúng bộ label như trước**, không thiếu
- [ ] Ép guard đĩa (Phase 03) xuống dưới ngưỡng → endpoint công khai **từ chối** job
      mới. Không có cửa nào từ internet đẩy đĩa máy người khác xuống 0

## Risk Assessment

**Sửa hỏng config làm sập Promax.** Đây là rủi ro lớn nhất của phase này — file dùng
chung. *Tín hiệu:* `promax.nobidigital.asia` không còn 302. *Phản ứng đã định:* khôi
phục `.bak` rồi kickstart lại, **trước** khi tìm hiểu nguyên nhân.

**Đặt hostname mới sau nhánh `404`** ⇒ không bao giờ khớp. Lỗi im lặng: tunnel chạy,
DNS đúng, mà vẫn 404. *Phản ứng:* `ingress validate` + đo thật, không đọc config
rồi tự tin.

## Việc phụ, làm nếu còn thời gian

**Đường SSH dự phòng qua cloudflared** — gỡ được R1 (Tailscale đứt 12 ngày mà không
ai vào được máy). Cloudflare Tunnel mở được route SSH mà không cần Tailscale, cấu
hình từ dashboard, không cần ai bấm tại máy. Không chặn phase nào, nhưng nó biến
một sự cố 12 ngày thành 0.
