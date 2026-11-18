// Helper dùng chung cho các trang Video Desk. Trước đây mỗi tệp tự định nghĩa một bản riêng
// (escapeHtml có 4 bản: app.js, chia-cum.js, settings.js, giai-captcha-popup.js).
//
// NẠP TRƯỚC mọi tệp dùng tới (index.html: trước `app-*.js` + `chia-cum.js`; settings.html: trước
// `settings.js`). Thiếu thẻ <script> này ⇒ `window.VDChung` undefined ⇒ tệp dùng nó ném TypeError
// ngay dòng đầu — test `test_tach_app_js.py` bắt ca đó.
//
// `giai-captcha-popup.js` (vùng lane A) VẪN giữ bản `escapeHtml` riêng — không sửa tệp đó ở đợt
// tách R-03; đợt sau có thể chuyển sang `VDChung.escapeHtml`.
(() => {
  "use strict";

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Ném khi phiên Cloudflare Access đã hết hạn. Tách thành lớp riêng vì nó
  // cần một phản ứng khác hẳn mọi lỗi mạng: tải lại trang thì đăng nhập lại
  // được, còn thử lại ngầm thì không bao giờ khỏi.
  // Tên lớp phải giữ đúng `PhienHetHan`: `giai-captcha-popup.js` nhận ra lỗi này qua
  // `e.constructor.name`.
  class PhienHetHan extends Error {}

  function baoPhienHetHan() {
    const el = document.getElementById("session-expired");
    if (el) el.hidden = false;
  }

  // Gửi một request ghi (POST/PUT/DELETE…). Lỗi HTTP ⇒ Error mang `ma` (`detail` của backend) và `status`.
  async function apiSend(method, path, body) {
    // `redirect: "manual"` là phần quan trọng. Khi phiên Access hết hạn,
    // Cloudflare trả 302 sang trang đăng nhập; `fetch` mặc định đi theo, gặp
    // CORS và ném `TypeError` — một phiên Access hết hạn giữa lúc đang thao tác
    // mà im lặng thì người dùng bấm lại mãi.
    const res = await fetch(path, {
      method,
      redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) {
      // `detail` của backend là một MÃ đóng, không phải câu chữ, và không
      // mang byte nào của tệp cookie — nên đưa thẳng vào bảng dịch được.
      let ma = null;
      try { ma = (await res.json()).detail; } catch (e) { ma = null; }
      const err = new Error(`${method} ${path} -> ${res.status}`);
      err.ma = ma;
      err.status = res.status;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  // Theme sáng/tối: khoá localStorage + áp lên <html>. Mỗi trang tự gắn nút đổi theme.
  const THEME_KEY = "videodl-theme";
  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }

  window.VDChung = Object.freeze({ escapeHtml, PhienHetHan, baoPhienHetHan, apiSend, THEME_KEY, applyTheme });
})();
