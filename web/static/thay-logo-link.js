// Link "Thay logo" trên thanh trên: ẨN mặc định (index.html), chỉ hiện khi máy chủ bật tính năng (`/tinh-nang` → thay_logo_bat).
// Ẩn trước rồi mới hiện — không có khoảnh khắc member thấy một link dẫn tới tính năng đang tắt.
(async () => {
  try {
    const r = await fetch("/tinh-nang", { redirect: "manual" });
    if (r.ok && (await r.json()).thay_logo_bat) document.getElementById("link-thay-logo").hidden = false;
  } catch (_) { /* không hỏi được ⇒ giữ ẩn */ }
})();

// Email người đang dùng ở góc phải thanh trên (mock B). Nguồn SẴN CÓ: `GET /me` (không thêm API). Lỗi/không hỏi được ⇒ giữ ẩn.
(async () => {
  try {
    const r = await fetch("/me", { redirect: "manual" });
    if (!r.ok) return;
    const { email } = await r.json();
    const el = document.getElementById("topbar-email");
    if (el && typeof email === "string" && email) { el.textContent = email; el.title = email; el.hidden = false; }
  } catch (_) { /* không hỏi được ⇒ giữ ẩn */ }
})();

// ⓘ (`.ti`): chạm / Enter / Space mở khung giải thích (không chỉ dựa vào title — điện thoại không có hover).
// Một khung dùng chung `#ti-pop` (role=tooltip), `.ti` đang mở có aria-expanded=true + aria-describedby. Đóng khi bấm ra ngoài, Esc,
// hoặc khi ⓘ biến mất (hàng đợi vẽ lại). Nghe ở pha bắt (capture) để ⓘ nằm trong nút/link không kích hoạt hành động của nút/link.
(() => {
  let pop = null, moDen = null, giuTitle = "", theo = 0;
  const dong = () => {
    if (!moDen) return;
    moDen.setAttribute("aria-expanded", "false"); moDen.removeAttribute("aria-describedby");
    if (giuTitle) moDen.setAttribute("title", giuTitle);   // trả title (hover chuột vẫn có tooltip gốc khi đóng)
    moDen = null; giuTitle = ""; clearInterval(theo);
    if (pop) pop.hidden = true;
  };
  const dat = () => {
    if (!moDen || !pop) return;
    const r = moDen.getBoundingClientRect(), w = Math.min(320, innerWidth - 16);
    pop.style.width = w + "px";
    pop.style.left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8)) + "px";
    const duoi = r.bottom + 8 + pop.offsetHeight <= innerHeight || r.top < pop.offsetHeight + 16;
    pop.style.top = (duoi ? r.bottom + 8 : r.top - 8 - pop.offsetHeight) + "px";
  };
  const mo = (ti) => {
    const chu = ti.getAttribute("title") || ti.getAttribute("aria-label") || "";
    if (!chu) return;
    if (moDen === ti) return dong();
    dong();
    if (!pop) {
      pop = document.createElement("div");
      pop.id = "ti-pop"; pop.className = "ti-pop"; pop.setAttribute("role", "tooltip");
      document.body.appendChild(pop);
    }
    giuTitle = ti.getAttribute("title") || ""; ti.removeAttribute("title");  // tránh tooltip gốc chồng lên khung
    pop.textContent = chu; pop.hidden = false;
    moDen = ti; ti.setAttribute("aria-expanded", "true"); ti.setAttribute("aria-describedby", "ti-pop");
    dat();
    theo = setInterval(() => { if (!moDen || !document.contains(moDen)) { moDen = null; giuTitle = ""; clearInterval(theo); if (pop) pop.hidden = true; } else dat(); }, 500);
  };
  document.addEventListener("click", (ev) => {
    const ti = ev.target.closest && ev.target.closest(".ti");
    if (ti) { ev.preventDefault(); ev.stopPropagation(); mo(ti); return; }
    if (!(pop && pop.contains(ev.target))) dong();
  }, true);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") return dong();
    const ti = ev.target.closest && ev.target.closest(".ti");
    if (ti && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); ev.stopPropagation(); mo(ti); }
  }, true);
  addEventListener("resize", dat);
})();
