# Baseline trang Cài đặt — cookie (đo 23/09 10:25, `main 700d572`, dev)

Lệnh: `.venv/bin/python plans/260923-1023-cookie-ui/baseline/chup-baseline.py` · rc=0.
Thư mục tạm, worker tắt, danh tính giả, jar GIẢ (giá trị = `GIA-KHONG-THAT`). 0 jar thật chạm tới.
Số thô: `ket-qua.json`. Ảnh: `A*.png` (jar đang lưu), `B*.png` (lúc dán, bắt đầu từ chưa có jar).

## Bảng

| ca | mã `cookies.py` | A — jar đang lưu: chip / dòng trạng thái / Hạn | B — dán: dòng lỗi · jar có được ghi? |
|---|---|---|---|
| 0 chưa có | — | `Chưa có` / "Chưa dán cookie — lượt tải chạy ẩn danh" / — | — |
| 1 ổn (control) | `dung_duoc` | `Đang dùng được` / "Dùng được" / 23/10/2026 | không lỗi · **có** |
| 2 RTF | `cookie_khong_doc_duoc` | `Cần dán lại` / "Tệp không đọc được…" / **"Không có hạn"** | "Tệp không đọc được…" · không |
| 3 `[]` | `cookie_rong` | `Cần dán lại` / "Tệp không có cookie nào…" / **"Không có hạn"** | "Tệp không có cookie nào…" · không |
| 4 không sessionid | `cookie_chua_dang_nhap` | `Cần dán lại` / "Cookie không có phiên đăng nhập…" / **"Không có hạn"** | "Cookie không có phiên…" · không |
| 5 hết hạn | `cookie_het_han` | `Cần dán lại` / "Cookie đăng nhập đã hết hạn…" / 22/9/2026 | "Cookie đăng nhập đã hết hạn…" · không |

Control: ca 1 ra "Dùng được" ✓ · ca 5 ≠ ca 3 trên màn hình ✓ · 4 mã ra 4 câu khác nhau ✓.

## Phát hiện

1. **"Ba vs bốn" — phân định.** Không mã nào *thiếu nhánh* trên UI. Nhưng qua đường dán, jar hỏng **không bao giờ
   được ghi** (`put_my_cookie` kiểm trước, 400). ⇒ Ở khối trạng thái, chỉ **`cookie_het_han`** tự tới được (dán lúc
   còn hạn, hết hạn sau). Ba mã kia chỉ hiện ở **dòng lỗi lúc dán** (hoặc jar đặt tay). Hai chỗ hiện, hai ngữ cảnh.
2. **Không có gì nói tài khoản nào.** Thứ duy nhất phân biệt jar là `Vân tay jar` 8 hex (vd `627c468f`).
3. **"Không có hạn" cho jar hỏng** (ca 2-4): đọc như *tốt* (không bao giờ hết hạn), thật ra là *không đọc được hạn*.
4. **Bốn trạng thái hỏng cùng một chip `Cần dán lại`.** Phân biệt chỉ nằm ở dòng chữ.
5. **Dán hỏng thì cookie vẫn nằm nguyên trong ô dán** (ảnh `B5-het-han.png`). Nhánh thành công xoá ô
   (`settings.js:151`), nhánh lỗi thì không. Với cookie thật, **nguyên giá trị phiên** hiện trên màn hình.
6. Dòng lỗi đỏ nằm **dưới** dòng hướng dẫn Cookie-Editor, xa nút Lưu; chip lúc đó ghi `Chưa có` (đúng, nhưng
   không nói "cookie vừa dán bị từ chối").

## Câu (a) — danh tính trong cookie, đo trên jar THẬT (mini, read-only, điều phối gật V105)

Lệnh: `ssh nobi_auto@100.109.39.103 'python3 - <jar>'` với script chỉ in tên + độ dài + lớp ký tự,
rồi lượt hai chỉ in boolean + độ dài. Không in giá trị, không copy jar, không ghi gì.

- Jar 10196 B: **26 cookie**. Không cookie nào tên kiểu `username`/`uniqueId`. Có `uid_tt`/`uid_tt_ss` (64 hex —
  dạng băm, không phải id số).
- **`multi_sids`** (54 ký tự): trên **cả 2 jar** khớp mẫu `<19 chữ số>:<hex>`, phần hex **trùng `sessionid`** (True ×2),
  số 19 chữ số **không** lặp lại ở cookie nào khác, **hai jar ra hai số khác nhau** (`False` cho "cùng id").
- ⇒ ĐO ĐƯỢC: mỗi jar mang OFFLINE một **số định danh 19 chữ số gắn với phiên**, khác nhau giữa 2 tài khoản.
- ⇒ SUY LUẬN (chưa đo): số đó là **user id TikTok**. Đổi số → `@username` **cần hỏi TikTok** (không làm, V105).

## CHƯA ĐO
- Dán hỏng khi **đang có** jar tốt: trang có nói rõ "vẫn đang dùng cookie cũ" không (chỉ có dòng note tĩnh).
- Chế độ tối, bề rộng điện thoại.
