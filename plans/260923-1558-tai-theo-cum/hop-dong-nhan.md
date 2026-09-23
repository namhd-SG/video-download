# Hợp đồng payload `?videodesk=` — thêm khoá `nhan` (chủ hình dạng: lane V, 23/09 16:05)

Người đọc: lane V (Video Desk, bên GỬI) · lane Y (meta-ads, bên NHẬN, viết parser) · reviewer.

## Hình dạng

```json
{"v":1,
 "items":[{"f":"1AbCdEfGhIjKlMnOpQrStUvWxYz012345","n":"Nhảy đôi Badaboum 💃 #dance","u":"https://www.tiktok.com/@a/video/7687702661428235538"},
          {"f":"1ZyXwVuTsRqPoNmLkJiHgFeDcBa543210","n":"Badaboum couple ver 2","u":"https://www.tiktok.com/@b/video/7687685379742272789"}],
 "nhan":{"usecase":"Dance","insight":"Badaboum couple","template":"Goc","cum_id":12,"lo":{"thu":1,"tong":2}}}
```
Mã hoá: JSON → UTF-8 (`TextEncoder`) → `btoa` → base64url (`+`→`-`, `/`→`_`, bỏ `=`) — y như hôm nay (`web/static/app.js::moBoTuTim`).

## Quy tắc

1. **`v` giữ `1`.** `nhan` là khoá THÊM, không đổi phiên bản. Thiếu `nhan` ⇒ bàn giao kiểu cũ (chọn tay), bên nhận làm như hôm nay.
2. **`nhan` CHỈ có khi bàn giao từ một cụm** (nút "Tạo bộ tự tìm từ cụm này"). Bàn giao từ lựa chọn tay: KHÔNG có `nhan`.
3. **`usecase`**: chuỗi, đã `trim`, 1–80 ký tự — usecase bên Creative Desk (vd `Dance`).
4. **`insight`** = insight gốc + `" "` + kiểu, đã `trim`, khoảng trắng gộp về 1 dấu cách, 1–120 ký tự (vd `Badaboum couple`). Đây là **insight con** (user chốt 14:29 + 15:58). Video Desk gửi NGUYÊN chữ người gõ; bên nhận so khớp term có sẵn **không phân biệt hoa/thường + strip** (quy tắc của Y).
5. **`template`** luôn đúng chuỗi `"Goc"` với video tải về. (`Genmoi` là của video làm trong Creative Desk — Video Desk không bao giờ gửi.)
6. **`cum_id`**: số nguyên dương, id cụm TRONG Video Desk. Chỉ để truy vết; bên nhận KHÔNG được dùng nó làm khoá bên đó.
7. **`lo`**: `{thu, tong}` số nguyên, `1 ≤ thu ≤ tong`. Cụm > 30 video tách thành lô 30/30/… (trần `items` là 30 ở CẢ hai bên: `HANDOFF_MAX` Video Desk, `MAX_ITEMS` meta-ads). Cụm ≤ 30 ⇒ `{thu:1, tong:1}`. Bên nhận có thể ghép vào tiêu đề ("… (1/2)") hoặc bỏ qua.
8. **`nhan` sai hình dạng ⇒ bên nhận BỎ `nhan`, VẪN nhận `items`.** Không bao giờ từ chối cả bàn giao vì `nhan` — đó là điều kiện để hai bên deploy độc lập.

## Đã đo (16:05)

Mẫu trên, mã hoá đúng như `moBoTuTim`, đưa vào **parser thật** `meta-ads frontend/src/lib/videodesk-handoff.ts` (bản `d0595bba`, chạy `node --experimental-strip-types`):
- bản CÓ `nhan` ⇒ nhận, 2 items;
- control bản KHÔNG `nhan` ⇒ kết quả **giống hệt** (`JSON.stringify` bằng nhau) ⇒ bản meta-ads hiện có bỏ qua `nhan` đúng như M6.
