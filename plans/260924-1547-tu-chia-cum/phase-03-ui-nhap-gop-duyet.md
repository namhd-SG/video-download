---
phase: 3
title: "UI nháp: nhóm/kiểu, gộp, đổi tên inline, duyệt tất cả"
status: pending
priority: P1
effort: "1d"
dependencies: [1, 2]
---

# Phase 3: UI nháp (ship CÙNG phase 4 — một PR)

## Overview
Dựng màn nháp đúng mock `~/plans/260924-1031-tu-chia-cum-video-desk/mock-tu-chia-cum-v1.html` (poster thật, trạng thái đề xuất/đã duyệt/chưa phân tích hình/gộp vào cụm có sẵn), dùng route phase 1.

## Requirements
- Functional:
  - Thẻ lượt tải: tiêu đề đếm ĐÚNG thứ đang hiện ("N nhóm · M kiểu + làn riêng …"), chip trạng thái, ô usecase/insight gốc, "Chia theo" (đổi trục ⇒ yêu cầu chia lại), "Duyệt tất cả còn lại", "Chia lại", bộ đếm thao tác sửa.
  - Nhóm gập → kiểu → lưới thumb ĐẦY ĐỦ (không lấy mẫu); badge "ghép N".
  - Thao tác: gộp cả nhóm thành 1 cụm · gộp vào cụm có sẵn (popover liệt cụm cùng insight gốc) · đổi tên inline (thay `window.prompt` — ít nhất ở màn nháp) · tách (chọn video → kiểu mới) · xoá kiểu · chuyển video.
  - Nút "Tạo bộ tự tìm" của kiểu nháp: `disabled` + title nói lý do; chỉ bật sau duyệt (nó thành cụm #13 thật).
  - "Chưa phân tích hình": KHÔNG liệt nhóm nào, chỉ "Chưa vào cụm N" + dòng lệnh máy dev in sẵn, copy được (`bash scripts/phan-tich-hinh.sh --luot <id>`). **KHÔNG nút** "Chạy phân tích hình ngay" — mock v1 có nút đó, ĐP bỏ (D12).
- Non-functional: token màu/font của app.css; sáng/tối; 390 px không tràn ngang; một video một chỗ.

## Related Code Files
- Create: `web/static/chia-cum.js` (tách khỏi `app.js` 1 600 dòng), `tests/test_chia_cum_browser.py`, `tests/js/chia-cum-dem.js`
- Modify: `web/static/index.html`, `web/static/app.css`, `web/static/app.js` (điểm vào)

## Implementation Steps
1. Render từ `GET /chia/{job_id}`; mọi thao tác gọi `POST /chia/{id}/thao-tac` rồi vẽ lại từ server (không giữ trạng thái song song ở client).
2. Test trình duyệt (Playwright, mẫu `test_library_pagination_browser.py`): đếm DOM khớp tiêu đề · 0 video trùng · nút "Tạo bộ" của nháp disabled · trạng thái chưa-hình 0 nhóm.
3. Chụp PNG 6 trạng thái như mock; **lane tự mở từng ảnh** trước khi báo (cửa 1b), gửi đường dẫn PNG.

## Success Criteria
- [ ] Ảnh thật khớp mock (cùng bố cục, token, trạng thái); ĐP mở ảnh duyệt.
- [ ] Đột biến: bật nút "Tạo bộ" cho nháp ⇒ test ĐỎ; bỏ lọc trùng video ⇒ test ĐỎ.

## Risk Assessment
- `renderFilterBar` dựng lại trong sự kiện `change` làm Playwright `check()` treo (nợ cũ) ⇒ test dùng `click`.
- Đổi trục = chia lại (tốn một lượt agy) ⇒ hỏi xác nhận nếu đã có thao tác sửa (mất nhật ký của lượt cũ? — KHÔNG: lượt cũ `huy`, nhật ký giữ).

## Bổ sung trước thi công (27/09 09:0x, lane V) — chờ vòng agy `tuchiacum-p34-plan`

### A. Hiện trạng đo (main `1935ddb`, mini chỉ đọc)

- **Mock:** `~/plans/260924-1031-tu-chia-cum-video-desk/mock-tu-chia-cum-v1.html` + 6 PNG `mock-v1/{de-xuat-sang,de-xuat-toi,da-duyet-sang,chua-phan-tich-hinh,gop-vao-cum-co-san,dien-thoai}.png` — đã commit trong repo `~/plans` (`3db42fd`). Thư mục `posters/` (552K, poster TikTok) KHÔNG được track ⇒ muốn mở mock HTML thì cần bản ở máy này. Không chép 5,1 MB PNG vào repo này; lane dựng UI mở mock từ đường dẫn trên.
- **Backend phase 1 có sẵn:** `GET /chia/{job_id}` (`lay_chia`: `kieu[]` gồm `cum_nhap_id/nhom/kieu/ten_cum/video_ids`, cộng `huong_dan`, `nghi`, `bi_bo`), `POST /chia/{id}/thao-tac` (11 loại: `chap_nhan duyet_het duyet_kieu gop doi_ten chuyen ngoai_chu_de tra_ve hoan_tac xoa_kieu doi_insight`), `POST /chia/{id}/duyet` (`cum_nhap_id` trống = duyệt hết; `xac_nhan_gop`). `web/static/` chưa có `chia-cum.js`; `app.js` chưa có dòng nào gọi `/chia`.
- **Dữ liệu thật để nghiệm thu:** 2 nháp `de_xuat` — lượt 1 (job 10: 8 kiểu / 41 + 9 hướng dẫn + 4 nghi) và lượt 2 (job 17: 3 kiểu / 11 + 6 + 3). CẢ HAI lượt có `usecase`/`insight_goc` trống ⇒ theo D18, bấm duyệt sẽ trả 400 cho tới khi user điền (qua `doi_insight`).

### B. Lỗ giữa phase 3 và backend đang có (cần agy phán)

1. **"Tách (chọn video → kiểu mới)" không có thao tác backend.** `_op_chuyen` chỉ chuyển sang `cum_nhap` ĐÃ CÓ trong lượt (`models_chia.py:927-945`), không có loại nào tạo `cum_nhap` mới. Đề xuất: thêm loại `tach` = tạo `cum_nhap` (nhóm, kiểu) + chuyển video, **một** dòng nhật ký, `hoan_tac` được (xoá hàng mới, trả video về `truoc`). Phương án khác: bỏ "tách" khỏi v1.
2. **"Gộp vào cụm có sẵn (popover liệt cụm cùng insight gốc)" chỉ chạy được khi TRÙNG TÊN.** Duyệt chỉ hỏi gộp khi `ten_cum` trùng cụm thật (D13); `ten_cum` = "<insight gốc> <kiểu>" (D16), nên chọn một cụm có sẵn tên khác thì không có đường. Đề xuất: `POST /chia/{id}/duyet` nhận thêm `gop_vao_cum_id` cho MỘT kiểu (bắt buộc cụm đó là của `chu`, kiểm `da_o_cum` như D14), mock `gop-vao-cum-co-san.png` là màn này. Phương án khác: v1 chỉ hiện popover khi server trả `trung_cum_co_san`.
3. **"Chia lại" sau khi đã sửa là ngõ cụt.** `nhap_de_xuat` chặn nháp mới khi lượt `de_xuat` đã có nhật ký (`NhapBiChan`) và mở lượt mới chỉ khi lượt cũ `da_duyet`/`huy`; KHÔNG loại thao tác nào đưa lượt sang `huy`. Mục Rủi ro phía trên viết "lượt cũ `huy`, nhật ký giữ" — chưa có đường. Đề xuất: thêm loại `huy_luot` (ghi nhật ký, không `hoan_tac`), UI hỏi xác nhận khi đã có thao tác, rồi hiện lệnh máy dev `bash scripts/phan-tich-hinh.sh --luot <id> --truc <trục> --yes` (D12: không nút chạy agy). Trục hợp lệ: `trang_phuc_dam_dong`, `trang_phuc_nguoi_chinh`, `boi_canh` (`phan_tich_hinh.py:52`).
4. **Tên NHÓM không ổn định giữa lượt** (chạy thật 27/09: cùng kiểu có sẵn "Mặc vest" ra nhóm "Âu phục" ở job 10, "Áo vest" ở job 17). Nhóm chỉ để gom trên màn nháp; tên cụm thật = "<insight gốc> <kiểu>" nên không vào taxonomy, TRỪ ca D16 ghép nhóm khi trùng tên cuối. Câu hỏi: ghim tên nhóm có sẵn giống ghim kiểu (prompt chuẩn hoá nhận thêm cặp nhóm→kiểu đã duyệt), hay chấp nhận và để user sửa (`doi_ten` đã nhận `nhom`)? Đề xuất: chấp nhận ở v1, vì cụm thật không lưu nhóm (`cum` không có cột nhóm), và ghim nhóm cần đổi prompt ⇒ đổi hash phiên bản ⇒ mất cache chuẩn hoá. Chỉ ghi là đã biết.
5. **Scratch sau lượt thành công** giữ prompt + kết quả (`phan_tich_hinh.py:237` chỉ dọn `anh/`). Đề xuất: giữ (để soát khi user hỏi "vì sao video X vào kiểu Y"), thêm comment nói là cố ý, và in đường dẫn scratch ở dòng cuối. Không phải việc UI — đưa vào PR phase 3+4 vì là thay đổi một dòng.

### C. Nghiệm thu bổ sung

- Render nháp THẬT của lượt 1 và lượt 2 (DB sao từ mini, không ghi mini) ngoài 6 trạng thái như mock; ĐP mở PNG.
- **Insight trống (ĐP-163, bắt buộc):** màn duyệt có ô điền/sửa `usecase` + `insight_goc` NGAY trên thẻ lượt, lưu qua `doi_insight` có sẵn. Khi còn trống: nút "Duyệt"/"Duyệt tất cả" `disabled` kèm dòng nói lý do ("Điền insight gốc để duyệt — tên cụm = <insight gốc> <kiểu>"); user KHÔNG phải bấm rồi mới nhận 400. 400 của server (D18) vẫn giữ làm lưới.
- Test trình duyệt: lượt insight trống ⇒ nút duyệt disabled + dòng lý do hiện; gõ insight ⇒ `doi_insight` ghi 1 dòng nhật ký ⇒ nút bật ⇒ duyệt được. Đột biến bỏ `disabled` ⇒ ĐỎ.
