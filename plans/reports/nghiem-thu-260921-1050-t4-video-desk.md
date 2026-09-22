# T4 — nghiệm thu đóng Video Desk, 21/09/2026

Chạy trên mini `autos-mac-mini` 10:32–10:51. Hai người thật: `namhd@astronex.ai` và
`namduchoang10@gmail.com`. Dụng cụ: `scripts/do-nghiem-thu-t4.sh` (chỉ đọc).

## Kết quả

| mục | kết quả | ngưỡng |
|---|---|---|
| hai job chồng thời gian | **không có cặp nào** | phải không |
| jar cookie lẫn chủ | **không** | phải không |
| `rss` cao nhất khi tải | **267 MB** | <1536 MB |
| thư mục tải cao nhất | **31 MB** | ≤50 MB |
| job 50 video | **50/50 done**, 5 phút 17 giây | chạy trọn |
| danh sách label launchd trước/sau | **khớp từng tên**, 5/5 | không mất |
| `promax` hàng xóm | **302** trước và sau | sống |
| `healthz` | **200** trước và sau | sống |

## Hai người bấm cùng lúc — phép phân định nằm ở đâu

```
job 7 | namduchoang10@gmail.com | 10:44:57.673742 → 10:45:25.708265 | 0/0
job 8 | namhd@astronex.ai       | 10:45:25.709665 → 10:50:42.567431 | 50/50
```

Job 8 bắt đầu **1,4 mili giây** sau khi job 7 kết thúc. Worker một luồng, tuần tự khít.

Phép "có cặp nào chồng giờ không" trả **rỗng**, và rỗng đó **có nghĩa** vì đối chứng đi
kèm: **8** job mang `bat_dau_luc`. Trước khi tin phép này, nó đã được thử trên dữ liệu
dựng tay — ca tuần tự trả rỗng, ca chồng trả `3 chồng 4`, ca hai job `running` trả
`5 chồng 6`. Một phép thử chưa từng bắt được ca xấu thì kết quả rỗng của nó không nói
lên điều gì.

## Jar cookie — bằng chứng mạnh nhất trong buổi

```
sha256("namduchoang10@gmail.com") = 620fa805cfccd23d…
sha256("namhd@astronex.ai")       = 0c073b48e6414fc0…

10:44:57  loaded 26 cookies from 620fa805…   ← đúng giây job 7 bắt đầu
10:44:59  loaded 26 cookies from 620fa805…
10:45:25  loaded 21 cookies from 0c073b48…   ← đúng giây job 8 bắt đầu
10:45:42  loaded 21 cookies from 0c073b48…
```

Không dừng ở "có hai tệp khác tên". Điều chứng minh được là **tệp nào được nạp vào lúc
nào**, và nó đổi **chính xác tại mốc job đổi chủ**.

Đọc được các dòng này là nhờ bản vá dấu thời gian lên mini sáng nay (`b550a1b`). Trước
đó log không có giờ, và phép đo này **cấu tạo không thể thực hiện**.

## Đĩa — cột không dùng làm tiêu chí, và vì sao

Ngưỡng cũ *"đĩa không tụt >100MB"* đã bị bỏ (`4e140bc`). Buổi này cho thêm hai bằng chứng:

- Lượt lấy mẫu 600s lúc 10:33 với `job_running = 0` **suốt 120 mẫu**: đĩa tụt **2 236 MB**.
  Tool không chạy gì.
- Lượt lấy mẫu trong lúc job 8 tải 50 video: đĩa **đứng yên 3.2Gi**, `tai_MB` đỉnh 31 rồi
  về **0 MB** khi xong.

Đĩa trên máy này là tài nguyên dùng chung với Promax. Cột đọc được là `tai_MB`.

⚠ Trong buổi này tôi đã **báo động sai một lần**: từ bốn mốc đĩa cùng chiều giảm, tôi
ngoại suy *"đầy trong 15 phút"* và việc nghiệm thu bị hoãn vì nó. Đo tiếp thì đĩa **tăng**
lên 4,3Gi rồi về 3,2Gi — dao động ±1 GB trong một phút. **Bốn điểm cùng chiều không phải
một xu hướng.** Tình trạng thật là *tồn kho thấp* (85% đã dùng, `/Users/autotest` 51 G),
đáng nhắc chủ máy dọn khi tiện — không phải rò rỉ đang chảy.

## Chưa đạt / chưa đo

- **Job 7 ra `0/0`.** Nguồn `/search` chập chờn, đã có trong sổ (16/09: 0/5 lượt · 18/09:
  1/1) và câu chữ trên trang nói đúng điều đó. ⇒ Mục "job ~50 video" được nghiệm thu bằng
  **một** job, không phải hai. Đừng ghi thành hai.
- **Ba mục mắt người** — chờ user tick: mở link "Mở thư mục Drive" · Thùng rác Drive có 5
  video xoá 18/09 không · đứng ở project `aldenesk-01` bấm "Tạo bộ tự tìm" để xem câu báo
  lỗi **có bảo đổi project** không (bản vá `f89bb9aa`, tới giờ mới chỉ kiểm được bằng cấu
  tạo trên prod, chưa bằng hành vi).

## Câu chưa giải

1. Ba lỗi 500 (`disk I/O error`) trên mini: **giờ mới đo được theo giờ** nhờ log có dấu
   thời gian, nhưng **chưa có sự kiện mới** để đo. Mốc soát lại: **24/09**.
2. `/Users/autotest` 51 G trên đĩa 245 G, còn 3,4 G. Ngoài tầm lane (không sudo) —
   quyết định của chủ máy.
