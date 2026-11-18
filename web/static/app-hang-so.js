// Hằng số: Creative Desk, nhãn trạng thái, câu mã dừng.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

// Helper dùng chung (`chung-tien-ich.js`, nạp TRƯỚC tệp này).
const { escapeHtml, PhienHetHan, apiSend, baoPhienHetHan, THEME_KEY, applyTheme } = window.VDChung;

  // ========================================================================
  // CONSTANTS
  // ========================================================================
  const UNKNOWN = "__unknown__"; // khoá bucket dùng chung cho mọi trường thiếu dữ liệu

  // Creative Desk — cùng đội, URL công khai, người dùng đã đăng nhập sẵn ở đó.
  const CREATIVE_DESK_URL = "https://automation.nobidigital.asia";
  // Trần số video một bộ. Lý do là ĐỘ DÀI URL, không phải giới hạn nghiệp vụ:
  // payload đi trong query string, và trình duyệt/proxy bắt đầu cắt quanh 8KB.
  // 30 item giữ URL dưới ~6KB kể cả khi tiêu đề dài và có dấu.
  const HANDOFF_MAX = 30;
  // Chọn tay đi đường KHÁC: `postMessage` sang tab Creative Desk, không qua URL
  // ⇒ không vướng trần 8KB, Creative Desk tự chia thành nhiều bộ. Trần dưới đây
  // chỉ là phanh an toàn, khớp `MAX_PM_ITEMS` phía nhận
  // (meta-ads `frontend/src/lib/videodesk-postmessage.ts`).
  const CREATIVE_DESK_ORIGIN = new URL(CREATIVE_DESK_URL).origin;
  const MAX_PM_ITEMS = 500;
  // Gửi lặp tới khi có ack: tab mới cần vài giây để tải và gắn bộ nghe, tin gửi
  // trước đó rơi mất. Creative Desk KHÔNG đứng sau Cloudflare Access; cổng của nó
  // là trang `/login` của app, và sau khi đăng nhập tab không quay lại trang này
  // — chờ lâu hơn không cứu được ca đó, chỉ khoá nút lâu hơn. 30 s đủ cho tải trang.
  const PM_CHU_KY_MS = 500;
  const PM_HAN_MS = 30000;

  const STATUS_LABEL = {
    pending: "Chờ lượt", running: "Đang tải", done: "Xong",
    failed: "Lỗi", interrupted: "Bị ngắt", cancelled: "Đã rút",
    // Bốn bước giải xác minh trong popup (`giai-captcha-the-job.js::NHAN`; chỉ xuất hiện khi
    // máy chủ bật `VIDEODL_PROFILE_CAPTCHA`).
    cho_xac_minh: "Cần xác minh", cho_giai: "Chờ mở trang giải",
    dang_mo: "Đang mở trang giải", dang_giai: "Đang giải",
  };

  // Job còn SỐNG ở máy chủ ⇒ giữ luồng tiến độ SSE. Bốn bước giải không phải trạng thái kết
  // thúc: job ở đó vẫn có thể quay về `running`, và `cho_xac_minh` ⇄ `cho_giai` đổi liên tục.
  const TRANG_THAI_SONG = new Set(["pending", "running", "cho_xac_minh", "cho_giai", "dang_mo", "dang_giai"]);

  // Ba lý do dừng sớm KHÁC NHAU (hashtag_enumerator.py) trông giống hệt nhau
  // từ ngoài nhìn vào nếu không dịch riêng — xem `guard-marker` và spec: đừng
  // gộp thành "không lấy được video".
  // Trần IP giờ/ngày: job DỪNG giữa chừng (không chờ), nên người đọc cần biết ĐÃ được bao nhiêu và chạy lại thì tải
// tiếp phần còn lại. Mã khác giữ nguyên câu.
function cauDungTranIp(job, cau) {
  if (!cau || (job.ly_do_dung !== "tran_gio" && job.ly_do_dung !== "tran_ngay")) return cau;
  return `Đã tải ${Number(job.xong) || 0}/${Number(job.tong) || 0} video. ` + cau;
}

// Bảng câu mã dừng ở `stop-reason-text.js` (nạp trước tệp này). `|| {}`: sau một chuyến deploy, trình
// duyệt có thể còn `index.html` CŨ trong cache (không có thẻ nạp tệp đó) mà tải `app.js` MỚI — thiếu bảng thì
// thẻ dừng chỉ mất câu riêng (hiện câu chung `CAU_MA_CHUA_DICH`), còn ném TypeError thì mất cả hàng đợi.
const BANG_CAU_DUNG = window.STOP_REASON_TEXT || {};

// Câu cho mã dừng KHÔNG có trong bảng (mã cũ còn trong DB, hoặc bảng thiếu vì index.html cũ trong cache):
// người dùng chỉ đọc tiếng Việt — KHÔNG in mã thô (vd `het_trang`) ra thẻ/popup. Mã lượt (#id) đã có ở popup.
const CAU_MA_CHUA_DICH = "Tool dừng vì một lý do chưa có câu giải thích riêng. Thử lại một lần; " +
  "lặp lại thì báo người phát triển kèm mã lượt.";
// Một chỗ dịch mã dừng cho cả popup chi tiết lượt tải (`ctxThe`) và cửa sổ giải (`GiaiCaptcha.cauLyDo`).
function cauMaDung(ma) {
  return ma ? (BANG_CAU_DUNG[ma] || CAU_MA_CHUA_DICH) : "";
}
