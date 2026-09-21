#!/bin/bash
# Sáu phép kiểm cho web/static/index.html mà PYTEST KHÔNG BẮT ĐƯỢC.
#
# Vì sao tồn tại: ngày 15/09, hai lỗi tương phản lọt qua 220 test xanh —
# chữ tối trên nền tối ở MỘT theme, rồi chữ sáng trên nền sáng của huy hiệu.
# Cả hai chỉ lộ khi mở trang ra nhìn. Phép kiểm 1 dưới đây biến đúng hai lỗi
# đó thành thứ máy đếm được, thay vì một lời dặn "nhớ nhìn kỹ".
#
# Dùng: bash scripts/kiem-ui.sh
# Cần: agent-browser (CLI cục bộ). Không có thì script NÓI RÕ là chưa kiểm,
# chứ không im lặng bỏ qua rồi trông như đã đạt.
set -u
PORT=8941
URL="http://127.0.0.1:${PORT}/index.html"

if ! command -v agent-browser >/dev/null 2>&1; then
  echo "CHƯA KIỂM ĐƯỢC: không có agent-browser trên máy này."
  echo "Sáu mục dưới vẫn phải làm bằng tay trước khi nhận UI."
fi

cat <<'CHECKS'
=== Sáu phép kiểm thủ công, làm trước khi nhận UI ===

1. TƯƠNG PHẢN, CẢ HAI THEME — máy kiểm được, đừng kiểm bằng mắt

     agent-browser open "$URL"
     agent-browser eval "(async()=>{const s=document.createElement('script');
       s.src='https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js';
       document.head.appendChild(s); await new Promise(r=>{s.onload=r;s.onerror=r});
       return typeof axe;})()"

   Rồi cho MỖI theme (light, dark):

     agent-browser eval "document.documentElement.setAttribute('data-theme','light')"
     agent-browser eval "(async()=>{const r=await axe.run(document,
       {runOnly:['color-contrast'],resultTypes:['violations','incomplete']});
       return JSON.stringify({vi:r.violations.flatMap(v=>v.nodes.map(n=>n.target.join(' '))),
         chua_ro:r.incomplete.flatMap(v=>v.nodes.map(n=>n.target.join(' ')))});})()"

   ⚠ PHẢI ĐỌC CẢ `incomplete`, KHÔNG CHỈ `violations`.
   Đây là bẫy đã sập ngày 15/09: một phần tử bị đặt màu chữ TRÙNG Y nền, và
   axe xếp nó vào `incomplete` chứ không phải `violations` — cổng chỉ đọc
   `violations` nên báo SẠCH cho một trang đang hỏng thật. Cổng trả lời một
   câu hẹp hơn câu được hỏi.

   ĐẠT = `vi` RỖNG, và mọi mục trong `chua_ro` đã được người soi một lượt.
   `incomplete` nghĩa là "axe không quyết được", không phải "đạt": nền trong
   suốt, glyph nhỏ, chồng lớp đều rơi vào đó. Soi bằng cách đo tay:

     agent-browser eval "(()=>{const e=document.querySelector('<selector>');
       const c=getComputedStyle(e);
       return c.color+' tren '+getComputedStyle(e.parentElement).backgroundColor;})()"

   CA ÂM BẮT BUỘC, chạy TRƯỚC khi tin bất kỳ kết quả sạch nào:

     agent-browser eval "document.getElementById('library-count').style.color=
       getComputedStyle(document.body).backgroundColor; 'da lam hong'"

   Chạy lại phép kiểm — phải thấy `#library-count`. Không thấy thì cổng hỏng,
   và mọi chữ "SẠCH" trước đó vô nghĩa. Trả màu về bằng `style.color=''`.

2. [hidden] THẬT SỰ ẨN
     agent-browser eval "[...document.querySelectorAll('[hidden]')]
       .filter(e=>getComputedStyle(e).display!=='none').length"
   ĐẠT = 0. (Từng hỏng: ba lớp tự đặt `display` hoà specificity với
   `[hidden]{display:none}` của trình duyệt.)

3. PHIÊN ACCESS HẾT HẠN
   Xoá cookie CF_Authorization khi trang đang mở, đợi ≤10 giây.
   ĐẠT = băng "Phiên đăng nhập đã hết hạn" hiện ra.
   KHÔNG ĐẠT = hàng đợi đứng im không lời nào — đó là hình dạng cũ của lỗi.

4. THƯ VIỆN LỚN HƠN MỘT TRANG
   Sau backfill, mở trang với thư viện > 500 video.
   ĐẠT = nhãn nói cả hai số, ví dụ "2000 video (đang hiện 2000 trong 2500)".
   KHÔNG ĐẠT = một con số trơn — đó là cách thư viện tự cắt mà không nói.

5. ẢNH THIẾU
   Xoá một file web/data/thumbs/<id>.webp rồi tải lại.
   ĐẠT = thẻ hiện "Chưa cắt được ảnh". KHÔNG ĐẠT = icon ảnh vỡ.

6. BÀN PHÍM
   Tab tới một thẻ, bấm Space hoặc Enter.
   ĐẠT = thẻ được chọn, thanh thao tác hiện ra.

=== Và một phép kiểm bằng mắt không thay thế được ===
Chụp hai theme × hai bề rộng (390 và 1280), đặt CẠNH
plans/260914-1412-tool-len-mini-va-domain/mock-thu-vien-260915.html.
Duyệt bằng hình, không bằng chữ — đọc mô tả rồi gật là cách đã làm sai
trọn một vòng ngày 15/09.
CHECKS
