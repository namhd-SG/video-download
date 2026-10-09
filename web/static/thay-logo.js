// Trang "Thay logo" (M2 khung theo bộ). Khởi động: theme, kiểm tính năng bật/tắt, poll danh sách. Poll 15 giây, không SSE.
(() => {
  "use strict";
  const T = window.TL, { $ } = T;
  const POLL_MS = 15000;

  const THEME_KEY = "videodl-theme";
  const apTheme = (t) => (t === "light" || t === "dark") ? document.documentElement.setAttribute("data-theme", t)
                                                        : document.documentElement.removeAttribute("data-theme");
  try { apTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* trình duyệt chặn lưu trữ: theo hệ điều hành */ }
  $("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* bỏ qua */ }
    apTheme(next);
  });

  function veTomTat() {
    const dem = {}; for (const v of T.videos) dem[T.nhomCua(v)] = (dem[T.nhomCua(v)] || 0) + 1;
    const soi = T.videos.filter((v) => T.nhomCua(v) === "cho_duyet" && T.soiKy(v)).length;
    const p = $("tl-tom-tat"); p.replaceChildren();
    const b = document.createElement("b"); b.textContent = `${dem.cho_duyet || 0} video chờ duyệt`;
    p.append("Việc của bạn: ", b, ` · ${soi} cần bạn xem kỹ · ${dem.dang_xu_ly || 0} video máy đang làm, bạn không cần chờ.`);
  }
  T.ve.tomTat = veTomTat;

  async function taiLai() {
    try {
      const r = await T.goi("/api/thay-logo/videos");
      if (!r.ok) return;
      T.videos = (await r.json()).videos || [];
      T.capNhatLuc = Date.now();
      T.veLai();
    } catch (_) { /* hết phiên đã báo ở trên */ }
  }
  window.TL_taiLai = taiLai;

  async function kiemBat() {
    try {
      const r = await T.goi("/tinh-nang");
      if (r.ok && !(await r.json()).thay_logo_bat) {  // máy chủ không nhận lượt mới (409) ⇒ đừng để nút trông bấm được
        T.tat = true; $("tat").hidden = false;
        document.querySelectorAll("#tl-nhap input, #tl-nhap button.btn").forEach((e) => { if (e.id !== "tl-thu-gon") e.disabled = true; });
        T.veLai();
      }
    } catch (_) { /* bỏ qua */ }
  }

  T.veLai();
  kiemBat();
  taiLai();
  setInterval(taiLai, POLL_MS);
})();
