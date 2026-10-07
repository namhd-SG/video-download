# Plan — log lý do huỷ gesture + lý do lô bị 400 (ĐP-1155, chỉ log)

Trạng thái: **agy KHÉP R3b 10:33 (R2b MỞ → R3a bác); ĐP-1155 gật; đã code (1647 passed, 5/5 đột biến ĐỎ).** Lane V 9b0abf0b, worktree
`~/Projects/video-download-wt-ly-do-huy`, nhánh `feat/giai-log-ly-do-huy` từ origin/main `fc10aae`.

## 1. Đo (job 54 lượt 1, 07/10 10:20-10:21, mini 5b21567→fc10aae)
- Dòng `[giai]`: `gesture_nop=0`, `huy_khac=6`, `popup_huy=0`, `tre_qua_D=0`, trễ phát p50 529 / p95 1479 ms (D=120), `ket_qua=van_chan`.
- Access log `POST /jobs/54/giai/chuot` phút 10:20: 200×41 · **400×6** · 409×14 ⇒ 6×400 = `huy_khac` 6 (khớp SỐ, CHƯA 1-1:
  log không gắn lý do cho từng lần huỷ; 10:21 lẫn lượt 2).
- Lý do 400 KHÔNG được log ở đâu (`giai_captcha_api.py:224-229` chỉ `bo_lo` + trả HTTP).

## 2. Nguồn sinh huỷ (fc10aae `web/giai_captcha.py`) — mọi lần qua `_huy_gesture_unlocked`
`qua_nhieu_lo_cho` :640, :668 · `lo_bi_tu_choi` :680 (mốc của lô 400) · `lo_khong_hop_le` :686 (lịch lệch > 10 s) ·
`thieu_lo` :696 (hụt seq > 2 s theo giờ TỚI) · `doi_token` :575 (không tính) · `popup_huy` (lệnh popup).
Nguồn 400 có `huy_gesture=True`: `kiem_su_kien` :288-317 (8 nhánh) + API :208-212 (số sự kiện, `khung_w`).

## 3. Thiết kế (KHÔNG đổi hành vi giải)
D1. `LoiGiai` thêm tham số tuỳ chọn `nhan: str | None` — nhãn CỐ ĐỊNH cho từng nhánh 400 `huy_gesture=True`:
    `dang_su_kien` · `loai_su_kien` · `so_khong_huu_han` · `t_am` · `buttons` · `ngoai_khung` · `wheel_che_do` · `wheel_dxdy` (8 nhánh
    `kiem_su_kien`) · `so_su_kien` · `khung_w` (API). Không đổi mã HTTP, thông điệp, `huy_gesture`.
D2. `PhienGiai.dem_tu_choi(nhan)` (dưới `khoa`): bộ đếm theo nhãn, gọi ở API ngay trong nhánh `if loi.huy_gesture:` TRƯỚC `bo_lo`;
    nhãn thiếu ⇒ `"khac"`. Không giữ toạ độ, giá trị, body, token — chỉ chuỗi nhãn + số.
D3. `so_do_luot()` thêm 2 trường cố định, mỗi trường đủ mọi nhãn (kể cả 0) theo thứ tự cố định:
    `huy=qua_nhieu_lo_cho:a,lo_bi_tu_choi:b,lo_khong_hop_le:c,thieu_lo:d,khac:e` (đếm sẵn ở `huy_theo_ly_do`; `huy_khac` giữ =
    tổng như cũ) và `tu_choi=<nhãn>:n,...`. Dòng log "vòng giải kết thúc" in hai trường đó.
D4. Không đổi DB, API, SSE, FE, hành vi phát/huỷ.
D5. (agy R2b) Lệch đồng hồ popup (`BoPhatLai.nhan_lo` :464, `raise` DUY NHẤT của `BoPhatLai`) KHÔNG ra API — bị bắt DUY NHẤT ở
    `_xa_cho_lo` :684-686 thành `lo_khong_hop_le` (chỗ DUY NHẤT sinh lý do này). ⇒ `huy.lo_khong_hop_le` = số lô lệch đồng hồ, 1-1;
    không phải 400 nên không thuộc `tu_choi`. Ghi rõ trong docstring `so_do_luot`.
D6. Bộ đếm theo LƯỢT, không cần reset: `lay_hoac_tao_phien` tạo `PhienGiai` mới khi phiên cũ `da_dong` (:929-930); worker
    `bo_phien` khi xong lượt (worker :484).

## 4. Kiểm (bắt buộc ĐỎ được)
- Lô có điểm ngoài khung qua API thật ⇒ `tu_choi` có `ngoai_khung:1`, `huy` có `lo_bi_tu_choi:1` sau khi xả; dòng `[giai]` có hai
  trường, KHÔNG `http`/`/@`/`token=`, không toạ độ.
- Từng nhãn của `kiem_su_kien` (parametrize 8 nhánh, gọi THẲNG hàm) ⇒ đúng nhãn. Qua API: 10 ca (dict sai dạng bị Pydantic chặn
  422 trước `kiem_su_kien` ⇒ nhãn `dang_su_kien` chỉ với tới được khi gọi hàm trực tiếp). `thieu_lo` / `qua_nhieu_lo_cho` ⇒ đếm đúng lý do.
- Đột biến: bỏ đếm 1 lý do ⇒ ĐỎ; gộp lại như cũ (chỉ tổng) ⇒ ĐỎ; nhãn sai nhánh ⇒ ĐỎ.
- Suite đầy đủ rc=0; code-reviewer độc lập.

## 5. Câu hỏi mở (KHÔNG làm trong PR này)
1. Trễ phát phía WORKER p50 529 ms (4,4 × D) ở job 54 lượt 1 — đo sau khi biết lý do 400 (ĐP-1155).
