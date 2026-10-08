// Link "Thay logo" trên thanh trên: ẨN mặc định (index.html), chỉ hiện khi máy chủ bật tính năng (`/tinh-nang` → thay_logo_bat).
// Ẩn trước rồi mới hiện — không có khoảnh khắc member thấy một link dẫn tới tính năng đang tắt.
(async () => {
  try {
    const r = await fetch("/tinh-nang", { redirect: "manual" });
    if (r.ok && (await r.json()).thay_logo_bat) document.getElementById("link-thay-logo").hidden = false;
  } catch (_) { /* không hỏi được ⇒ giữ ẩn */ }
})();
