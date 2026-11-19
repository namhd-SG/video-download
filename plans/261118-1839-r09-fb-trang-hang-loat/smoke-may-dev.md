# R-09 #3 FB page — smoke máy dev + kiểm lại (18/11/2026 19:0x–19:3x)

Lane kế nhiệm tự đo; không cookie, không agy, không ca-n. Gọi thẳng `FacebookTrang().liet_ke` (patchright Chrome thật, headless), `cong=None`.

## Smoke nguồn (Facebook thật, ẩn danh)
| Lượt | N | Mới | Đã có (skip) | Trùng | ly_do | Dấu DOM mỗi lượt (hộp thoại, có Close) | XHR (dòng/thân) |
|---|---|---|---|---|---|---|---|
| TheOnion /videos lần 1 | 10 | 10 | 0 | 0 | complete | — (đủ từ HTML) | 0 |
| TheOnion /videos chạy lại | 10 | 6 | 10 | 0 | `fb_chan_dang_nhap` | (có,có) ⇒ bấm Close · (không) · (có,KHÔNG) ⇒ tường | 1 (1 dòng, 43 KB) |
| TheOnion /reels lần 1 | 10 | 10 | 0 | 0 | complete | — | 0 |
| TheOnion /reels chạy lại | 10 | 10 | 10 | 0 | complete | (có,có) ⇒ Close · (không) | 2 (81 dòng, ~16 MB mỗi thân) |
| TheOnion /reels lần 3 | 20 | 20 | 20 | 0 | complete (2 quá dài bị lọc) | (có,có) · (không) ×2 | 5 (81 dòng) |
| NASA /reels | 10 | 0 | 0 | 0 | `source_empty` | (có,có) · (không) ×5 | 0 |

- Hộp thoại ĐẦU (có Close) không bị nhận nhầm là tường: 5/5 lượt cuộn đều bấm Close rồi đi tiếp; tường thật (không Close) chỉ ở TheOnion /videos sau 16 mã = khớp đo bước 0 (16).
- `eval_on_selector_all` đọc được `script[type=application/json]` (10 mã/lượt đầu từ HTML). `page.on("response")` thấy đủ thân XHR nhiều dòng (81 dòng).
- 2 reel "quá dài" = thời lượng thật 1204 s / 1252 s (đồng nhất `length_in_second` và `playable_duration_in_ms` ở chính nút media) ⇒ lọc trần 900 s đúng.
- Log `ttmd` 6 dòng: 0 URL, 0 tên page, 0/31 mã video, 0 `fbv-` (grep + so khớp từng mã).

## Tải thật
`download_all(nen_tang="facebook")` 2 ref /videos + 2 ref /reels: 3 tải (0,9 / 5,8 / 6,5 MB mp4), 1 skip = cùng video có ở cả /videos lẫn /reels ⇒ cùng id `fbv-<mã>` (khử trùng đúng). Lần 2: 0 tải, 4 skip, 0 lỗi.

## Suite đầy đủ (venv có Chromium)
`1 failed, 3671 passed, 1 skipped in 720 s`. Ca đỏ duy nhất `test_thay_logo_kiem_hinh.py::test_logo_mo_troi_qua_doan_kho_duoc_bam_lai_hai_chieu` cũng đỏ trên `git archive c7b722c` (cùng venv) ⇒ có sẵn trên main. Test browser `/huong-dan` chạy (không skip).

## Đột biến (tự chạy lại, tập 5 file test_fb_*, 141 test)
i bỏ `already_have` 6 đỏ · ii bỏ phát hiện tường 12 · iii-a thiếu ở `NHAN_THEO_LY_DO` 2 · iii-b thiếu ở `_LY_DO_RONG_LA_LOI` 4 · iv rò URL/mã vào log 2 · v bỏ `cong.truoc_goi()` 2. Hoàn nguyên: `shasum -c` 4 file OK, git diff trùng byte.

## Ảnh UI (server dev thật, DB tạm, job giả `fb_chan_dang_nhap`)
8 tấm: thẻ job (lỗi 0/20 + xong 16/16, chip "Facebook đòi đăng nhập") và `/huong-dan.html` (ô `data-tran=video_trang_facebook` = 20) × 1440/390 × sáng/tối, 0 lỗi JS. Không commit ảnh (đường dẫn gửi ĐP).
