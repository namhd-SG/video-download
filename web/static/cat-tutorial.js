// Trang "Cắt tutorial": hỏi `/tinh-nang` rồi mới mở iframe `/cat-tutorial/` (tool chị Linh qua proxy web/cat_tutorial_routes.py).
// Theme: cùng khoá `videodl-theme` với các trang khác; iframe cùng origin nên áp thẳng `data-theme` vào trong khung —
// index.html của tool tự đọc khoá này lúc nạp (proxy đã đổi "studio-theme"), còn khi CHƯA chọn thì nó mặc định sáng,
// nên trang này đẩy theme ĐANG HIỆU LỰC (kể cả theo hệ điều hành) vào khung sau mỗi lần nạp và mỗi lần bấm đổi.
(() => {
  "use strict";
  const THEME_KEY = "videodl-theme";
  const khung = document.getElementById("ct-khung");
  const bao = document.getElementById("ct-bao");

  const apTheme = (t) => (t === "light" || t === "dark") ? document.documentElement.setAttribute("data-theme", t)
                                                       : document.documentElement.removeAttribute("data-theme");
  const hieuLuc = () => document.documentElement.getAttribute("data-theme")
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const dongBoKhung = () => {
    try { khung.contentDocument.documentElement.dataset.theme = hieuLuc(); } catch (_) { /* khung chưa nạp / khác origin */ }
  };

  try { apTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* không có storage: theo hệ thống */ }
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const moi = hieuLuc() === "dark" ? "light" : "dark";
    apTheme(moi);
    try { localStorage.setItem(THEME_KEY, moi); } catch (_) { /* bỏ qua */ }
    dongBoKhung();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", dongBoKhung);
  khung.addEventListener("load", dongBoKhung);

  const baoLoi = (chu) => { bao.textContent = chu; bao.classList.add("loi"); bao.hidden = false; };

  (async () => {
    try {
      const r = await fetch("/tinh-nang", { redirect: "manual" });
      if (r.status === 401 || r.type === "opaqueredirect") return baoLoi("Phiên đăng nhập đã hết hạn — tải lại trang để đăng nhập lại.");
      if (!r.ok) return baoLoi(`Không hỏi được máy chủ (mã ${r.status}) — thử tải lại trang.`);
      if (!(await r.json()).cat_tutorial_bat) return baoLoi("Tính năng Cắt tutorial đang tắt trên máy chủ.");
      bao.hidden = true;
      khung.hidden = false;
      khung.src = "/cat-tutorial/";
    } catch (_) {
      baoLoi("Không kết nối được máy chủ — kiểm tra mạng rồi tải lại trang.");
    }
  })();
})();
