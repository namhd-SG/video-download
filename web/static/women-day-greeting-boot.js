// Mở thiệp 20/10 (women-day-greeting.js) cho người đang đăng nhập.
// Email lấy từ `/me` — trang không có đường nào khác, vì danh tính nằm trong
// header Cloudflare Access mà JavaScript không đọc được. Danh sách người nhận
// (women-day-greetings.js) đặt lúc deploy, không có trong repo.
(function () {
  "use strict";
  if (!window.WomenDayGreeting) return;
  fetch("/me", { redirect: "manual" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (me) {
      if (me && me.email) {
        window.WomenDayGreeting.start({ email: me.email, dataUrl: "/women-day-greetings.js" });
      }
    })
    .catch(function () { /* thiệp là phần phụ: phiên hết hạn hay mạng lỗi thì thôi */ });
})();
