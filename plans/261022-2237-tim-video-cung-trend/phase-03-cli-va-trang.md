# Pha 3 — Lệnh CLI + trang HTML local

## Lệnh
`python -m tiktok_music_downloader.tim_trend <video> [--ra <thư mục>] [--nguong 3,2A] [--so-truy-van 6] [--hop 2] [--tran-luot 12] [--gian-cach 12] [--hashtag-qua-tikwm] [--nhan-nhac]`
- Thêm `tim_trend/__main__.py` (typer, như `cli.py`). Không sửa `cli.py` hiện có (tránh đụng lệnh tải đang dùng).
- Luồng: khung ⇒ agy bóc (khung đầu vào) ⇒ chữ ký + **đối chứng dương** (khung đầu vào phải ra hạng 3; trượt ⇒ dừng, báo) ⇒ truy vấn hop 1 ⇒ tìm ⇒ khử trùng ⇒ tải ảnh bìa ⇒ agy bóc ⇒ hạng ⇒ hop 2 từ hạng 3/2A ⇒ lặp tới trần ⇒ xuất.
- Mặc định `--nguong 3,2A` (hiệu chỉnh bằng thước người 22/10: precision 0,95 / recall 0,90 trên 70 ảnh; ghi số này trong trang).

## Ra (`<ra>/`)
- `ket-qua.json` (mọi ứng viên + trường + hạng + truy vấn sinh ra nó + nhật ký lượt gọi).
- `links.txt` — link hạng ≥ ngưỡng, ≤50/dòng-khối (trần job Video Desk), mỗi dòng 1 link.
- `index.html` — khối "Video đầu vào" (khung + chữ ký), bảng truy vấn → số link/số đạt, lưới ảnh bìa tách tab `3` / `2A` / `2B` / còn lại (ĐK4), cờ "nghi bung pose sau giây 0" (caption khớp dạng mà ảnh bìa 1 người), nút copy `links.txt`. Dùng lại khung trang GĐ1 (`~/plans/reports/tiktok-quet-video-261022/index.html`), không thư viện ngoài.

## Test
- `tests/test_tim_trend_luong.py`: chạy trọn luồng với agy giả + nguồn tìm giả (fixture GĐ1) ⇒ `links.txt` chỉ chứa hạng ≥ ngưỡng; đối chứng dương trượt ⇒ không xuất `links.txt`, mã thoát ≠0.
- Kiểm trang: render, mở bằng Chrome, chụp màn hình, **ĐP tự mở ảnh** (luật cửa 1b).
