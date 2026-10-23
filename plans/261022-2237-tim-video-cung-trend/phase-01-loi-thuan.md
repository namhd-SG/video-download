# Pha 1 — Lõi thuần (không mạng, test đầy đủ)

Gói mới `src/tiktok_music_downloader/tim_trend/` (tên snake_case tiếng Việt như `thay_logo/`).

## File
| File | Việc |
|---|---|
| `tim_trend/__init__.py` | rỗng |
| `tim_trend/truong.py` | `TruongAnh` (dataclass): `so_ban_sao`, `chu_the`, `loai_nen`, `hanh_dong`, `la_luoi`, `la_tutorial`, `chu_ocr`, `mo_ta`; `tu_json()` kiểm enum, giá trị lạ ⇒ `"khac"` (không đoán) |
| `tim_trend/cham.py` | `chu_ky(truong_khung_mau) -> ChuKy` (gộp các khung video đầu vào: bản sao lấy trung vị, nền/chủ thể/hành động lấy đa số); `hang(truong, chu_ky) -> "3"/"2A"/"2B"/"1"/"0"` tất định |
| `tim_trend/khu_trung.py` | khử trùng theo `video_id` rồi `dHash` ảnh bìa (Pillow, khoảng Hamming ≤ 4 = trùng) |
| `tim_trend/truy_van.py` | sinh truy vấn hop 1 từ chữ ký + nhãn dạng agy: nhóm (a) cấu trúc đếm được ("{N} pose", "collage", "lookbook", "multi pose"…), (b) chủ đề AI, (c) sản phẩm; mỗi nhóm EN/ES/PT (+ ngôn ngữ caption gốc nếu biết) |
| `tim_trend/mo_rong.py` | hop 2: từ caption + hashtag của link hạng `3`/`2A` ⇒ n-gram lặp ≥2 lần, bỏ từ dừng (`tutorial, cara, buat, membuat, gratis, how to, prompt, fyp, viral, capcut…`) ⇒ truy vấn mới; trần số vòng |

## Luật hạng (tham chiếu GĐ1 `tinh_diem.py` + agy R3b ĐK1/ĐK4)
1. `la_luoi` ≠ của chữ ký ⇒ tối đa `1` (xét TRƯỚC bản sao — ĐK1).
2. Bậc bản sao (`1` / `2` / `≥3`) ≠ chữ ký ⇒ tối đa `1`.
3. Đếm sai lệch giữa {chủ thể, nhóm nền, hành động}: 0 ⇒ `3`; nếu chỉ dính `la_tutorial` ⇒ `2A`; lệch đúng 1 ⇒ `2B`; còn lại ⇒ `1`.
4. Không có người khi chữ ký có người ⇒ `0`.
Nhóm nền: {trang_tron, mau_tron, studio} = "trơn"; còn lại theo giá trị.

## Test (`tests/test_tim_trend_cham.py`, `…_khu_trung.py`, `…_truy_van.py`, `…_mo_rong.py`)
- Bảng ca từ GĐ1 thật (`cham-may-v2.json`, chép 12 mục làm fixture): s6-7 ⇒ 3, s7-1 ⇒ 2A, s5-5 (lưới) ⇒ 1, s1-7 (1 người) ⇒ 1, s3-4 (chó) ⇒ 0, ctrl ⇒ 3.
- Chữ ký video 2 (1 người catwalk): s3-1 ⇒ 3, s6-7 (collage) ⇒ 1 — chứng minh không hằng cứng.
- Đột biến (bắt buộc ĐỎ): bỏ luật lưới; bỏ cổng bậc bản sao; xét chủ thể SAU các luật khác; bỏ cổng hành động. (Bản đầu ghi "đảo xét lưới sau bản sao" — đo 22/10 ra XANH vì hai luật cùng trả "1", đổi thứ tự không đổi kết quả ⇒ không phải đột biến có nghĩa; lỗi GĐ1 thật là luật lưới bị BỎ QUA khi n≥3.)
- dHash: 2 ảnh md5 trùng ⇒ trùng; ảnh khác ⇒ không.
- mo_rong: caption GĐ1 S5-0 "lookbook ai kolase multi pose foto potret" ⇒ sinh "kolase multi pose"; "Tutorial Pembuatan Gratis" ⇒ bị lọc.

## Nghiệm thu pha
Test xanh + 2 đột biến đỏ (ghi lệnh + output).
