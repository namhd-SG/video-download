# Plan — log đo mỗi lượt "Tôi giải ngay" (USER CHỐT ~18:0x 06/10, ĐP-1069)

Trạng thái: **v2 — agy KHÉP R2b 18:17 (kèm D1b + cách viết D4); chờ ĐP duyệt + 2 câu §6, chưa code.** Lane V 9b0abf0b, worktree `~/Projects/video-download-wt-giai-log`,
nhánh `feat/giai-captcha-log-moi-luot` từ origin/main `53fad8f`. Deploy mini: gom đợt sau cùng #55.

## 1. Mục tiêu và ranh giới
- GIỮ trần `TRAN_GIAI_NGAY = 3`. Chỉ THÊM số đo, không đổi hành vi giải/phát/kiểm.
- Mỗi lượt có đủ số để bàn đổi trần sau này: (a) số bước captcha nếu đo được, (b) độ trễ phát chuột p50/p95,
  (c) số lần popup huỷ, (d) kết quả kiểm sau giải.
- Log KHÔNG in token khung giải, URL hồ sơ/video, id video, driveId. Chỉ `job_id` + số.

## 2. Hiện trạng (đọc tại 53fad8f)
- `giai_captcha_worker.py:346-350` in một dòng "vòng giải kết thúc" với `tre_qua_D`, `tre_phat_worker`, `D`,
  `gesture_bo_do`, `tai_lai`, `trang_moi_dong`, `chan_dieu_huong`. **`tre_phat_worker` là SỐ sự kiện phát muộn > 50 ms**
  (`giai_captcha.py:114,431`), không phải độ trễ. KHÔNG có tổng số sự kiện đã phát ⇒ không ra được tỉ lệ; KHÔNG có phân phối trễ.
- Kết quả kiểm sau giải (`_quet_sau_giai`, :255-305) chỉ thể hiện gián tiếp qua trạng thái job (`captcha_chua_xong`).
- Lượt thứ mấy: `jobs.so_lan_giai_ngay` (DB), chưa có trong log.
- Số bước captcha: KHÔNG có tín hiệu nào trong code (worker chỉ thấy khung ảnh + feed, không đọc DOM captcha).

## 3. Thiết kế
D1. `BoPhatLai.den_han` (giai_captcha.py): ngoài đếm `tre_phat_worker`, ghi độ trễ phát `bay_gio - lich` (giây) của MỌI sự
    kiện vào một mẫu có trần cố định (giữ ≤ 4 096 giá trị; vượt thì lấy mẫu đều — reservoir có seed cố định để test lặp lại được).
    Đếm `so_phat` = tổng sự kiện đã phát. `PhienGiai.nhan_khoa` (giai_captcha.py:529-531) THAY `bo_phat` khi đổi token ⇒
    trước khi thay, cộng dồn `so_phat` và GỘP mẫu trễ vào `_mau_tre_cu` (cùng trần, reservoir) như `_tre_phat_cu` (agy R1b #2).
D1b. (agy R2b, điều kiện KHÉP) KHÔNG gộp hai reservoir: `PhienGiai` giữ MỘT đối tượng mẫu (`n_seen` + danh sách ≤ 4 096) và
    truyền tham chiếu vào mọi `BoPhatLai` mới khi đổi token ⇒ reservoir liền mạch, phân phối đúng.
D2. Hàm thuần `tom_tat_tre(mau) -> (p50_ms, p95_ms, max_ms)` (nearest-rank, mẫu rỗng ⇒ None). Không thêm thư viện.
D3. Dòng log "vòng giải kết thúc" giữ nguyên trường cũ (ai đang grep không gãy), THÊM:
    `luot=<so_lan_giai_ngay>/<TRAN>` · `mo_s=<giây từ dang_giai tới kết thúc>` · `so_phat=<n>` ·
    `tre_phat_p50_ms` · `tre_phat_p95_ms` · `tre_phat_max_ms` · `popup_huy=<số lệnh huỷ gesture nhận được>` ·
    `gesture_nop=<số cặp down→up đã PHÁT>`.
    - `popup_huy` khác `gesture_bo_do`: cái sau chỉ đếm huỷ khi nút ĐANG nhấn (dẫn tới tải lại); popup có thể huỷ lúc không nhấn.
    - Đếm NGAY KHI HUỶ trong `PhienGiai._huy_gesture_unlocked` (giai_captcha.py:650 — chỗ DUY NHẤT đổi kỳ, mọi lý do đi qua)
      một bộ đếm theo `ly_do` (không xoá khi đổi token); log `popup_huy=<ly_do == LY_DO_HUY_POPUP>` + `huy_khac=<lý do khác, trừ doi_token>` — KHÔNG đếm ở worker: `_co_huy` là ô đơn bị ghi đè (:663) và `_vong_giai` vứt lệnh huỷ khi
      không nhấn (worker :221-226) ⇒ đếm ở worker sẽ thiếu. Huỷ nội bộ `doi_token` không tính (agy R1b #1).
D4. Dòng log MỚI sau kiểm (trong `_quet_sau_giai`, đúng một dòng mỗi lượt đi tới bước kiểm), bọc `try/finally` để MỌI lối ra
    đều ghi: `trang_thai_doi` (worker :280), `van_chan`, `qua`, và ngoại lệ từ `quet_tren_trang` (`loi:<TênLớp>` — chỉ tên lớp,
    KHÔNG thông điệp) (agy R1b #3):
    `[giai] job N: kiểm sau giải luot=k/3 ket_qua=<qua|van_chan|trang_thai_doi|loi:Ten> so_trang=<n>`.
    Cách viết (agy R2b): `ket_qua = "loi_chua_ro"`; gán nhãn NGAY TRƯỚC mỗi `return`; `except Exception as e: ket_qua =
    f"loi:{type(e).__name__}"; raise`; log trong `finally`.
D5. **Số bước captcha: KHÔNG đo trong PR này** — không có tín hiệu (§2). Thay bằng `gesture_nop` (số lần người thực sự nhả
    chuột = số lần nộp thử kéo) — ghi rõ trong log và docstring đây là PROXY, không phải số bước. Đo số bước thật cần đọc DOM
    captcha (đổi phạm vi ⇒ hỏi lại).
D6. Không đổi DB, không đổi API/SSE, không đổi FE.
D7. Mọi dòng log MỚI chỉ mang `job_id` + số + nhãn cố định; ngoại lệ chỉ ghi `type(exc).__name__`. Test regex (§4) quét
    MỌI dòng `[giai]` của một lượt giả — kể cả dòng cũ.
    ⚠ Dòng CŨ đang in `path` (worker :119 điều hướng, :148 rời miền, :182 đóng trang mới — theo ĐP-592 "host + path, không
    query") và `exc_info=True` (:421) có thể mang handle/id video/URL. Đổi chúng là đảo một quyết định ĐP cũ ⇒ KHÔNG tự làm,
    đưa thành câu hỏi §6.2.

## 4. Kiểm (mỗi cái phải ĐỎ được)
- Unit `BoPhatLai`: phát N sự kiện với đồng hồ giả, trễ biết trước ⇒ `so_phat=N`, p50/p95 đúng giá trị nearest-rank; >4 096
  sự kiện ⇒ mẫu giữ đúng 4 096, kết quả lặp lại (seed). Đột biến: bỏ ghi mẫu ⇒ ĐỎ.
- `tom_tat_tre`: rỗng ⇒ None; 1 phần tử; số chẵn/lẻ.
- Log (caplog) cho một lượt giả `da_giai` + kiểm `van_chan`: có đủ trường mới; **regex cấm** `token=`, `http`, chuỗi số ≥ 15
  chữ số (id video), `driveId` trong mọi dòng `[giai]` của lượt. Đột biến: chèn `page.url` vào dòng log ⇒ ĐỎ.
- `popup_huy` vs `gesture_bo_do`: huỷ khi không nhấn ⇒ popup_huy=1, gesture_bo_do=0.
- Suite đầy đủ `rc=0` (không pipe).

## 5. Rủi ro
- Hiệu năng: thêm một `append` mỗi sự kiện trong vòng phát (đã nhạy trễ) — reservoir O(1); đo lại `tre_phat_worker` trên test
  có sẵn không đổi.
- Log dài hơn một dòng/lượt — không đáng kể (≤ 3 lượt/job).

## 6. Câu hỏi mở
1. Chấp nhận `gesture_nop` làm proxy thay "số bước captcha" (D5)? (agy R1b #4 đồng ý: kéo hỏng không bao giờ phát `up`.)
2. Dòng log CŨ in `path` (ĐP-592) + `exc_info`: (a) giữ nguyên, regex test chỉ áp cho dòng mới; (b) che path thành loại
   (`profile|video|khac`) + bỏ `exc_info` ở lượt giải (ghi tên lớp) — đảo ĐP-592. Đề xuất: (b) vì user vừa chốt "log không in
   id video", nhưng cần ĐP quyết.
