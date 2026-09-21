// Câu chữ cho TRẠNG THÁI cookie đang có — dùng ở trang Cài đặt và ở dải nhắc
// trên trang chính.
//
// Cố ý tách khỏi `app.js::STOP_REASON_TEXT`: bảng kia nói về một LƯỢT TẢI đã
// dừng ("Dừng: tệp cookie của bạn…"), bảng này nói về cookie ĐANG nằm đó. Cùng
// một bộ mã (`web/cookies.py::MA_LOI_COOKIE`), hai ngữ cảnh, nên hai câu — cùng
// một câu cho cả hai chỗ sẽ sai giọng ở một trong hai.
//
// Trước đây bảng này nằm trong `settings.js`, và trang chính không có bảng nào
// nên nó không nói được gì ngoài "chưa có cookie". Tách ra để chỗ thứ hai dùng
// lại thay vì chép — bản chép thứ ba là bản sẽ lệch.
//
// Thêm mã vào `MA_LOI_COOKIE` ⇒ thêm câu ở ĐÂY và ở `STOP_REASON_TEXT`.
window.MA_COOKIE_TRANG_THAI = Object.freeze({
  cookie_khong_doc_duoc: "Tệp không đọc được — xuất lại dạng JSON (không phải RTF).",
  cookie_rong: "Tệp không có cookie nào — xuất lại khi đang mở tiktok.com.",
  cookie_chua_dang_nhap: "Cookie không có phiên đăng nhập — đăng nhập TikTok rồi xuất lại.",
  cookie_het_han: "Cookie đăng nhập đã hết hạn — đăng nhập lại rồi xuất lại.",
});
