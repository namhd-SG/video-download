# Hợp đồng thao tác nháp chia cụm (chốt TRƯỚC phase 3)

Nguồn: code phase 1 (`web/models_chia.py`, `web/app.py` `ThaoTacChiaRequest` / `DuyetChiaRequest`). UI phase 3 gọi đúng hình dạng này; đổi hình dạng = đổi tệp này trước, rồi mới đổi code. Yêu cầu của ĐP-20: không để UI chép theo một hình dạng subagent tự đặt mà không ai chốt.

**Cập nhật sau review (24/09):** vá H1/H2/M1-M6 — xem từng mục dưới.

**Cập nhật sau review lượt 2 (25/09):** duyệt được BẤT CỨ GÌ giờ CHỐT thế hệ
nháp ngay lập tức (`the_he` tăng lên) — hoàn tác không còn cách nào lùi
XUYÊN QUA một lần duyệt (trước đây có thể ra `IntegrityError`/500 khi thao
tác bị lùi trỏ tới một `cum_nhap` đã bị xoá thật lúc duyệt). Xem thêm D18/D19
ở `plan.md`.

## `POST /chia/{chia_lan_id}/thao-tac`

Thân chung: `{"loai": <một trong 10>, ...trường riêng}`. Trường không liệt kê cho `loai` đó thì bị bỏ qua. Lượt không phải của người gọi (admin GHI/SỬA/DUYỆT cũng tính là "không phải" — admin chỉ XEM được qua `GET /chia/{job_id}`, không sửa/duyệt thay ai) ⇒ 404.

Mã lỗi validate — BA ca khác nhau, ĐỪNG gộp:
- **Sai hình dạng body** (FastAPI/pydantic, trước khi tới model) ⇒ **422** — gồm mọi trường id (`cum_nhap_id`, `tu_cum_nhap_id`, `den_cum_nhap_id`, phần tử `xac_nhan_gop` ở `/duyet`) ngoài khoảng `1..2**63-1` (INTEGER 64-bit của SQLite).
- **Thiếu HẲN một trường bắt buộc** (route lọc `None` khỏi payload trước khi tới model, nên "thiếu" và "gửi `null`" là một) ⇒ **400**, kèm câu nói rõ tên trường.
- **Lượt không đang ở `trang_thai = 'de_xuat'`** (chưa có đề xuất / đã duyệt xong / đã huỷ) ⇒ **400**, kèm câu nói rõ trạng thái hiện tại. Áp cho MỌI `loai`, kể cả `hoan_tac`.
- **Trường có mặt nhưng giá trị không trỏ tới gì thật** trong lượt (id không tồn tại/không thuộc lượt) ⇒ **409** — trừ RIÊNG `hoan_tac` "không còn gì để lùi", ca đó trả **400** (đây là trạng thái bình thường người dùng tự chạm tới bằng cách bấm hoài, không phải xung đột với ai).

Mỗi thao tác thành công ghi đúng MỘT dòng `thao_tac_duyet`, trong cùng transaction, kèm `the_he` (thế hệ nháp hiện tại — xem `hoan_tac`).

| `loai` | trường bắt buộc | trường tuỳ chọn | `so_video` ghi nhật ký | ghi chú |
|---|---|---|---|---|
| `chap_nhan` | `cum_nhap_id` | — | số video của kiểu | đánh dấu kiểu đã xem, không đổi dữ liệu |
| `doi_ten` | `cum_nhap_id`, `kieu` | `nhom` | số video của kiểu | tên chuẩn hoá bằng `chuan_hoa_chu` |
| `gop` | `tu_cum_nhap_id`, `den_cum_nhap_id` | — | số video chuyển | `tu` bị xoá; hai id phải khác nhau |
| `chuyen` | `video_ids` (≥1), `den_cum_nhap_id` | — | số video thật sự chuyển | video không thuộc lượt bị bỏ qua |
| `ngoai_chu_de` | `video_ids` (≥1) | — | số video | vào `lan='nghi'`, `cum_nhap_id=NULL`; không đụng `videos.da_loai_luc` |
| `tra_ve` | `video_ids` (≥1), `den_cum_nhap_id` | — | số video | từ làn nghi/hướng dẫn về một kiểu |
| `xoa_kieu` | `cum_nhap_id` | — | số video của kiểu | video về "chưa vào kiểu" của lượt (không rời lượt) |
| `doi_insight` | — | `usecase`, `insight_goc` | 0 | ghi `chia_lan` VÀ `jobs` **CHỈ khi `jobs.nguoi_tao = chu` gọi request** (M2); cùng luật độ dài `kiem_nhan` |
| `hoan_tac` | — | — | số video của thao tác bị lùi | **là một NGĂN XẾP** (H1): lùi thao tác GẦN NHẤT CHƯA bị lùi (`gop`, `doi_ten`, `xoa_kieu`, `chuyen`, `ngoai_chu_de`, `tra_ve`) trong CÙNG thế hệ nháp hiện tại (H2b — một `ghi_de_xuat` mới mở thế hệ mới, thao tác của thế hệ trước không lùi được nữa); bấm liên tiếp đi lùi qua từng thao tác một, không lặp lại thao tác đã lùi; không còn gì (cùng thế hệ, chưa lùi) ⇒ **400** |
| `duyet_het` | — | — | — | KHÔNG nhận ở route này ⇒ 400; dùng `/duyet` |

## `POST /chia/{chia_lan_id}/duyet`

```json
{ "cum_nhap_id": 12,              // bỏ ⇒ duyệt HẾT phần còn lại
  "usecase": "Motion",            // tuỳ chọn; có ⇒ ghi như doi_insight trong CÙNG transaction duyệt
  "insight_goc": "Strom Ai",      // tuỳ chọn
  "xac_nhan_gop": [7] }           // id cụm có sẵn đã xác nhận gộp; mặc định []
```

Cùng khoá trạng thái với `/thao-tac`: lượt không đang `de_xuat` ⇒ 400.

**Tên cụm lúc duyệt (D16):** mặc định `"<insight gốc> <kiểu>"`. Khi ≥2 kiểu trong CÙNG lượt có cùng TÊN CUỐI (tên sau khi đã ghép nhóm, nếu có; so bằng `chuan_hoa_chu` + casefold — khoá `models_cum._khoa_ten`), mọi kiểu trong nhóm trùng đó ghép thêm `nhom`: `"<insight gốc> <nhom> <kiểu>"`. Tên vừa ghép có thể lại trùng tên cuối của một kiểu khác (vd `Vest`/`couple` ⇒ "Vest couple", trùng kiểu đơn "Vest couple" của nhóm `khác`) ⇒ kiểu đó cũng ghép nhóm ("khác Vest couple"); lặp tới khi mọi nhóm trùng còn lại chỉ gồm kiểu ĐÃ ghép nhóm (mỗi vòng ghép thêm ≥1 kiểu, kiểu đã ghép không đổi nữa ⇒ tối đa số-kiểu + 1 vòng). **Va chạm còn lại** sau đó giữ nguyên, và lúc duyệt các kiểu đó TỰ GỘP vào MỘT cụm, không hỏi: (a) biến thể hoa/thường của cùng một kiểu trong cùng nhóm (`Vest`/`couple` và `Vest`/`Couple` — đúng là một kiểu); (b) hai kiểu khác nhau mà tên ghép trùng nhau (`A`/`B couple` và `A B`/`couple` cùng ra "A B couple") — ca hiếm, luật ghép nhóm không tách được; muốn tách thì `doi_ten` một trong hai. Mục đích: `duyet_het` không bao giờ tự hỏi "gộp vào cụm tôi vừa tạo trong CHÍNH lượt gọi này" — D13 chỉ để bắt trùng với cụm THẬT có từ trước.

**D19 — khi nào tên cụm được tính:** `ten_cum` (cột trên `cum_nhap`, kèm luật ghép nhóm ở trên) được tính cho MỌI kiểu đúng MỘT lần lúc `ghi_de_xuat`. Sau đó nó CHỈ được tính lại khi `doi_ten`, và CHỈ cho hàng bị đổi tên cộng các hàng va chạm tên với nó — trùng kiểu thô với hàng vừa đổi, hoặc trùng tên cuối theo luật lặp ở trên (xuất phát từ tên ĐÃ LƯU của các hàng khác); mọi hàng khác giữ nguyên tên đã lưu. Duyệt (`duyet_kieu`/`duyet_het`), `gop`, `xoa_kieu`, `chuyen`, `ngoai_chu_de`, `tra_ve` CHỈ ĐỌC `ten_cum`, không tính lại tên hàng nào — kể cả khi thao tác đó làm mất "anh em" trùng tên của một kiểu (kiểu còn lại giữ tiền tố nhóm). `hoan_tac` trả lại ĐÚNG `ten_cum` cũ đã lưu trong dòng nhật ký gốc (`doi_ten`: `ten_cum_truoc` của mọi hàng vừa bị ghi; `gop`: `tu_ten_cum`; `xoa_kieu`: `ten_cum`), không tính lại. `GET /chia/{job_id}` trả `ten_cum` cho từng kiểu. Lý do: tính lại trên tập hàng CÒN SỐNG làm tên trôi theo thứ tự thao tác (duyệt riêng "Vest couple" rồi đổi tên một kiểu không liên quan từng biến "Đồng phục couple" thành "couple" trần). Tái kiểm va chạm với `cum` THẬT vẫn diễn ra Ở LÚC DUYỆT — một cụm thật trùng tên xuất hiện SAU khi đề xuất đã ghi vẫn trả `trung_cum_co_san` như bình thường, KHÔNG bao giờ tự đổi tên để né va chạm.

Trả về:
- `{"trung_cum_co_san": [{cum_nhap_id, cum_id, ten, so_video}]}` ⇒ KHÔNG gộp. UI hỏi user, rồi gửi lại với `xac_nhan_gop`.
- Kết quả thường: mỗi kiểu `{cum_nhap_id, cum_id, da_co, gan: [...], da_o_cum: [...], bi_bo: [...]}`. `cum_id: null` + `gan: []` ⇒ mọi video đã ở cụm khác, KHÔNG tạo cụm rỗng. `bi_bo` (M4): video KHÔNG được gán vì đã bị loại khỏi thư viện/đổi chủ/id giả sau khi đề xuất — trước đây rơi mất không dấu vết, giờ luôn có mặt (rỗng nếu không có ca nào).
- `/duyet` (không kèm `cum_nhap_id`, tức "Duyệt tất cả") trả thêm `loi_ten: [{cum_nhap_id, ly_do}]` (M5): kiểu nào có tên (hoặc tên ghép nhóm+kiểu khi trùng, xem trên) không hợp lệ theo `kiem_nhan` (rỗng, quá dài…) bị BỎ QUA — ở nguyên trong nháp để user sửa tên — thay vì làm hỏng cả lượt duyệt; các kiểu còn lại vẫn duyệt bình thường.
- `usecase`/`insight_goc` trống cả ở body lẫn `chia_lan` ⇒ 400, có câu rõ.

## `GET /chia/{job_id}` · `GET /cum/{cum_id}/lo/{thu}/payload`

- `/chia/{job_id}`: nháp mới nhất cho job đó. Người thường: CHỈ nháp của chính mình. **Admin XEM được nháp của người khác** (M2) — sửa/duyệt vẫn khoá theo chủ thật ở `/thao-tac` và `/duyet` (admin gọi hai route đó cho lượt không phải của mình ⇒ 404, y hệt người thường). Không có ⇒ 404 (UI hiện "Chưa chia cụm" + lệnh máy dev). Trả thêm `bi_bo: [video_id...]` (M4) — video còn kẹt ở làn "kieu" nhưng `cum_nhap_id` đã mất (kiểu chứa nó vừa được duyệt, còn chính nó bị lọc bỏ lúc đó); trước đây rơi mất khỏi kết quả, không có cách nào UI biết mà hiện.
- `/cum/{id}/lo/{thu}/payload`: `{v: 1, items, nhan}` theo `plans/260923-1558-tai-theo-cum/hop-dong-nhan.md`. CHỈ cụm thật; id nháp ⇒ 404.

## Ai tạo được một lượt chia (M2)

`tao_chia_lan` (hàm, chưa có route ở phase 1) CHỈ cho chủ job (`jobs.nguoi_tao = chu` gọi hàm) — kể cả admin cũng KHÔNG tạo/sửa/duyệt thay người khác, chỉ xem (mục trên). Job không tồn tại hoặc không phải của người gọi ⇒ hàm trả `None`.

## CHƯA KIỂM

Bảng trên soạn từ đọc code lúc 17:15, cập nhật sau review 24/09. agy sẽ kiểm cơ học từng dòng khớp code (tên trường, bắt buộc/tuỳ chọn, mã lỗi), trước phase 3.
