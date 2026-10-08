"""Lõi job "Thay logo": tự định vị watermark trôi trong video, chặn mọi khung chưa chắc, trả track an toàn để render.

Chép từ bench P0b/P1a (`~/plans/261007-2254-video-desk-thay-logo/p0/`), giữ nguyên hằng số đã đo. Module này CHƯA nối
vào Video Desk: không worker, không endpoint, không render — chỉ phần quyết định "khung nào được thay".

Luật an toàn cứng (đọc trước khi sửa bất kỳ cổng nào): khung không qua đủ mọi cổng ⇒ KHÔNG render, giữ nguyên watermark.
Thà để sót watermark còn hơn tô lấp + dán logo lên nội dung sạch.

Hai công tắc agy RIÊNG, đều mặc định TẮT ở giai đoạn này:
- `AGY_HOC_MAU` — agy định vị thưa mỗi video để lấy box mồi (đường chính khi tính năng bật; kéo khung tay là đường lui).
- `AGY_BU` — agy bù đoạn C trượt; user quyết sau pilot.
"""
import os

AGY_HOC_MAU = os.environ.get("THAY_LOGO_AGY_HOC_MAU") == "1"
AGY_BU = os.environ.get("THAY_LOGO_AGY_BU") == "1"
