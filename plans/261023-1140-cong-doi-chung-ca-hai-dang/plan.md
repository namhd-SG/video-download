# Plan: sửa cổng đối chứng (ctrl) theo "cả 2" · 23/10/2026 (tk3)

Status: THIẾT KẾ ĐÃ KHÉP (agy R1b + R2b `KHÉP [argon chưa kiểm]`, `~/agy-ws/exchange/tiktok-cong-ctrl-*`) — chờ ĐP duyệt
⇒ thi công. Nền code: `7a7f315`. Bản chốt nằm ở mục "Luật thi công" cuối file; mục "Đề xuất" giữ làm lịch sử.

## Đã chốt (không bàn lại)
- USER 23/10 11:04 (pane ĐP d1bd356f, qua ĐP): video dạng "cách làm hiệu ứng" ⇒ tìm **cả 2**: bản kết quả (cảnh concert)
  **và** bản hướng dẫn. ⇒ "2A" (tutorial cùng trend) tính **đúng dạng**; kết quả in 2 nhóm "kết quả" / "hướng dẫn".
- Ngưỡng giữ mặc định đã là {3, 2A} (`cham.NGUONG_MAC_DINH`, thước người 22/10 P 0,95 / R 0,90) ⇒ "cả 2" KHỚP ngưỡng
  giữ; chỗ lệch nằm ở **cổng ctrl**: ctrl phải ra đúng "3" (`luong._cham_lo`: `tin = h_ctrl == "3"`).

## Số đo gốc (kho `~/kho/tim-trend-du-lieu-261023/`, file `ca3-*/bia/agy-truong-ctrl-*-0.json`)
Chữ ký ca 3 (cả A' và B): 1 bản sao · người · nền san_dien · hành động khac · không lưới.

| lượt/lô | agy đọc ctrl | hạng ctrl | cơ chế trượt |
|---|---|---|---|
| A' lô 0 | san_dien · tao_dang · **la_tutorial=True** (OCR thấy chữ "cómo hacer un video…") | **2A** | cờ tutorial bật vì chữ hướng dẫn in trên chính khung concert |
| A' lô 1 | san_dien · tao_dang · tutorial=False | 3 | — (hành động bỏ qua vì chữ ký "khac") |
| B lô 0 | **studio** · tao_dang · tutorial=False | **2B** | đọc **nền lệch**; cả lô B 0/36 đạt, gần hết 2B ⇒ lệch theo lô, không theo ảnh |

⇒ Hai lỗi KHÁC loại: (1) A' lô 0 là **cổng chặt hơn ngưỡng giữ** (2A được giữ nhưng ctrl 2A bị coi trượt) — lỗi thiết
kế, sửa tất định được; (2) B lô 0 là **agy đọc lệch cả lô** — cổng bắt ĐÚNG, đây là bằng chứng cổng có tác dụng.

## Đề xuất (theo thứ tự, mỗi vế tách test riêng)
1. **Ctrl đạt ⟺ hạng ctrl ∈ ngưỡng giữ** (mặc định {3, 2A}) thay vì `== "3"`. Lý do: cổng hỏi "máy chấm có giữ được
   chính video mẫu không" — hạng được giữ là đủ. Sửa ca A' lô 0. Không nới cho ca B (2B ∉ ngưỡng).
   ⚠ Ràng buộc: `chon_khung_doi_chung` chọn ctrl theo hạng ∈ ngưỡng (hiện `== "3"`) ⇒ video chỉ có cảnh hướng dẫn cũng
   có ctrl ⇒ mã 6 / `VideoHuongDan` (7a7f315) chỉ còn cho ca thật sự không khung nào ∈ ngưỡng. Cần agy soi: ctrl 2A có
   làm cổng mất sức phân định với video không phải dạng hướng dẫn không?
2. **Nhiều ctrl mỗi lô**: mọi khung đầu vào có hạng ∈ ngưỡng (tối đa 3), tên số + vị trí ngẫu nhiên (đã có từ 7a7f315).
   Lô tin được ⟺ **đa số** ctrl ∈ ngưỡng (2/2, 2/3, 3/3; 1 ctrl thì 1/1). Tăng sức bắt lệch lô; giảm trượt do 1 khung
   bị đọc lệch riêng lẻ.
3. **Chấm lại lô trượt đúng 1 lần** (lượt agy riêng, ctrl đổi tên + đổi vị trí). Lần 2 đạt ⇒ dùng kết quả lần 2; vẫn
   trượt ⇒ lô đó không tin. Trần: +1 lượt agy mỗi lô trượt; ghi cả 2 lượt vào `lo_ctrl`.
4. **Tin theo lô, không theo cả lần chạy** — ĐP QUYẾT 23/10 ~11:2x (ĐP d1bd356f, tin cross-session; ĐP giữ quyền
   quyết, không cần user): bảo đảm **theo TỪNG LINK** giữ nguyên — mọi link xuất ra phải đến từ một lô có ctrl đạt.
   Lô ctrl vẫn trượt sau 1 lần chấm lại ⇒ bỏ cả lô (ảnh hiện "Chưa chấm được"); số lô bỏ ghi vào `ket-qua.json` và
   trang. **Chặn thêm:** số lô bị bỏ > 50% tổng số lô ⇒ cả lượt không tin (mã 7) — bộ chấm đang lệch hệ thống.
   ⚠ Ngưỡng 50% là **hằng số tạm, CHƯA HIỆU CHỈNH** (chưa có dữ liệu nhiều lô để đặt). Không yếu hơn ĐK5 cũ ("thà
   không ra link"), chỉ bớt hạt thô: ĐK5 bảo đảm ở mức cả lượt, bản này bảo đảm ở mức từng link.
5. **Hai nhóm đầu ra**: trang tách "Kết quả (3)" / "Hướng dẫn (2A)" (đã nhóm theo hạng, đổi nhãn); `links.txt` giữ cả
   hai (Video Desk tải cả 2) + thêm `links-ket-qua.txt`, `links-huong-dan.txt`.

## Không làm
- So ctrl chỉ theo trường cấu trúc (bản sao/chủ thể): làm lô lệch nền (ca B) **lọt cổng** trong khi ảnh của lô vẫn bị
  chấm lệch thành 2B ⇒ mất recall âm thầm. Ngược mục đích cổng.
- Đổi thước chấm `cham.hang` (luật hạng) — ngoài phạm vi; thước người 22/10 vẫn là chuẩn.

## Nghiệm thu
- Test tất định tái hiện đúng 3 dòng bảng trên từ JSON thật (A' lô 0 ⇒ đạt; A' lô 1 ⇒ đạt; B lô 0 ⇒ trượt → chấm lại).
- Đột biến: trả cổng về `== "3"` ⇒ ĐỎ; bỏ chấm lại ⇒ ĐỎ; bỏ đa số (lấy 1 ctrl bất kỳ) ⇒ ĐỎ.
- Chạy lại ca 3 thật (xin ĐP ngân sách lượt mở TikTok; gặp captcha dừng) ⇒ đo % đúng dạng theo 2 nhóm, kiểm mắt.

## Câu hỏi đã hỏi agy (R1 — đã trả lời, xem Luật thi công)
1. Vế 1: ctrl ∈ ngưỡng giữ thay vì == 3 — có ca nào cổng mất sức phân định?
2. Vế 4: tin theo lô — chấp nhận hay giữ nguyên "1 lô trượt ⇒ 0 link"?
3. Đa số với 2 ctrl = cần 2/2 — quá chặt hay vừa?

## Câu chưa giải
- Vế 4: ĐP đã quyết hướng; agy phán ở R2 (R1 đã gửi trước khi có quyết định của ĐP): có ca nào một link lọt ra từ lô
  không có ctrl đạt không; và ngưỡng 50% có hợp lý không khi số lô nhỏ (1–2 lô ⇒ bỏ 1 lô đã là ≥50%).

## Luật thi công (bản chốt sau R1b + R2b; số ca 3 đã kiểm lại tại nguồn bằng code repo)
- **ĐK1a** — `nguong` (từ `--nguong`) truyền xuyên `chay` ⇒ `chon_khung_doi_chung` ⇒ `_cham_lo`; mọi chỗ cứng
  `("3","2A")` (gồm hạt giống hop 2) đổi sang `nguong`. Test: ctrl 2A với `{3,2A}` ⇒ đạt; với `{3}` ⇒ trượt.
- **ĐK1b** — `chon_khung_doi_chung`: (1) mọi khung đọc được đều `la_tutorial` ⇒ `VideoHuongDan` NGAY, trước vòng chọn;
  (2) phải có ≥1 khung hạng "3" (neo), không có ⇒ `ChuKyKhongOnDinh`; (3) trả DANH SÁCH ctrl = mọi khung có hạng ∈
  `nguong`, khung "3" gần giữa nhất đứng đầu (`ds_ctrl[0]`). Test: 3 khung tutorial trong nhà ⇒ VideoHuongDan;
  1 khung concert + 2 khung tutorial trong nhà ⇒ ChuKyKhongOnDinh.
- **ĐK2** — lần 1: đạt ⟺ `dat1*2 > n`. Chưa đạt ⇒ chấm lại (lượt agy riêng, tên + vị trí ctrl mới). Lần 2:
  `tin_lan2 = (dat2*2 > n) or (n == 2 and c0_lan1 and c0_lan2)`; hạng ứng viên lấy từ lần 2.
  Test (n=2): (0,0)→(1,1) đạt · (1,0)→(1,0) đạt · (0,0)→(1,0) trượt · (1,0)→(0,1) trượt · B lô 0 (2B,2B)×2 trượt.
- **ĐK3a** — `co = LO_TOI_DA - len(ds_ctrl)`; ctrl tạm xoá sau mỗi lượt (`finally`), tên vẫn ghi trong `lo_ctrl`.
- **ĐK3b** — `so_lo` đếm lô logic xuyên các hop; file agy `agy-truong-lo-{so_lo}` / `…-lan2`; `lo_ctrl` mỗi phần tử
  `{lo, lan, ten_ctrl:[…], hang_ctrl:[…], tin}`.
- **ĐK4 + ĐP** — sau khi gộp xong ứng viên: `tin_duoc = (so_lo_bo*2 <= so_lo) and (so_lo_bo == 0 or len(giu(nguong)) > 0)`.
  50% = hằng tạm CHƯA HIỆU CHỈNH. `ket-qua.json` + trang ghi `so_lo`, `so_lo_bo`. Bảng: (1,1,0)⇒7 · (2,1,11)⇒0 ·
  (2,1,0)⇒7 · (3,2,5)⇒7 · (2,0,0)⇒0 · (4,2,8)⇒0 · (4,3,8)⇒7.
- **ĐK5** — `links-ket-qua.txt` (hạng "3") + `links-huong-dan.txt` (hạng "2A"), mỗi tập tách `-NN` khi > 50;
  `_TEP_LINK` khớp cả hai tập mới; `links-cua-toi.txt` vẫn giữ.
- Đột biến bắt buộc ĐỎ: cổng về `== "3"` · bỏ chấm lại · bỏ đa số (1 ctrl bất kỳ) · bỏ kiểm toàn-tutorial trước vòng ·
  `<` thay `<=` ở 50% · bỏ vế `giu > 0` · regex cũ.
