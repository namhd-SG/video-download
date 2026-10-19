/*
 * Thiệp chúc mừng 20/10 — file tĩnh dùng chung, không phụ thuộc thư viện nào.
 *
 * Dữ liệu người nhận KHÔNG nằm trong repo: lúc deploy đặt cạnh file này một file
 * `women-day-greetings.js` (đã gitignore) gán
 *   window.WOMEN_DAY_GREETINGS = { sign: "...", entries: { "<sha256(email thường)>": { name, message } } }
 * Khoá là băm email nên mở file dữ liệu chỉ thấy tên + lời chúc, không thấy email.
 *
 * Cách gọi: WomenDayGreeting.start({ email, dataUrl, fallback })
 *   - email:    email người đang đăng nhập (null nếu không biết)
 *   - dataUrl:  đường dẫn file dữ liệu
 *   - fallback: { name, message } dùng khi không tra được người (bỏ trống = không hiện)
 * Chỉ hiện trong ngày 20/10/2026 giờ Việt Nam, mỗi trình duyệt/người một lần.
 *   window.WOMEN_DAY_GREETINGS cũng có thể mang `button` (chữ trên nút đóng).
 * `?wd-preview=1` trên URL bỏ qua cổng ngày và cổng "đã xem" để nghiệm thu trước.
 */
(function () {
  "use strict";
  if (window.WomenDayGreeting) return;

  var DAY = "2026-10-20";
  var SEEN_PREFIX = "wd-2026-seen:";
  var STYLE_ID = "wd-greeting-style";

  function todayInVietnam() {
    // en-CA cho dạng YYYY-MM-DD, không phụ thuộc múi giờ máy người xem
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }).format(new Date());
  }

  function isPreview() {
    try { return new URLSearchParams(location.search).get("wd-preview") === "1"; } catch (e) { return false; }
  }

  function sha256Hex(text) {
    if (!window.crypto || !crypto.subtle) return Promise.resolve(null);
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function (b) {
        return ("0" + b.toString(16)).slice(-2);
      }).join("");
    });
  }

  function loadData(url) {
    if (window.WOMEN_DAY_GREETINGS) return Promise.resolve(window.WOMEN_DAY_GREETINGS);
    return new Promise(function (resolve) {
      var s = document.createElement("script");
      s.src = url;
      s.async = true;
      s.onload = function () { resolve(window.WOMEN_DAY_GREETINGS || null); };
      // Thiếu file dữ liệu (chưa đặt lúc deploy) là ca bình thường ⇒ im lặng, không hiện
      s.onerror = function () { resolve(null); };
      document.head.appendChild(s);
    });
  }

  function readSeen(key) {
    try { return localStorage.getItem(SEEN_PREFIX + key) === "1"; } catch (e) { return false; }
  }

  function markSeen(key) {
    try { localStorage.setItem(SEEN_PREFIX + key, "1"); } catch (e) { /* trình duyệt chặn storage: chấp nhận hiện lại */ }
  }

  // Theme theo vị trí: màu thiệp + biểu tượng + cánh hoa. Người không có theme
  // (hoặc theme gõ sai) dùng "mac-dinh".
  var THEMES = {
    "mac-dinh":    { bg: "#fff7f9,#ffe3ec 55%,#ffd0de", ink: "#6a0f37", accent: "#c2185b", btn: "#e91e63,#ff5c8a", icon: "💐", petals: ["🌸", "🌷", "💗", "🌹", "✨"] },
    "media-buyer": { bg: "#fff8f1,#ffe6d1 55%,#ffd2b3", ink: "#7a2e05", accent: "#e8590c", btn: "#f76707,#ff922b", icon: "🚀", petals: ["🌼", "🧡", "📈", "✨", "🌸"] },
    "creative":    { bg: "#fbf6ff,#f0e1ff 55%,#e3ccff", ink: "#4b1a7a", accent: "#8e44d6", btn: "#9c36b5,#cc5de8", icon: "🎨", petals: ["🌸", "💜", "🖌️", "✨", "🌷"] },
    "data":        { bg: "#f2fbfa,#d8f3ef 55%,#bfe9e2", ink: "#0b4f4a", accent: "#0f8f83", btn: "#0ca678,#20c997", icon: "📊", petals: ["🌿", "💚", "✨", "🌸", "🔢"] },
    "editor":      { bg: "#fff5f5,#ffe0e0 55%,#ffc9c9", ink: "#7a1020", accent: "#e03131", btn: "#e03131,#ff6b6b", icon: "🎬", petals: ["🌹", "🎞️", "❤️", "✨", "🌸"] },
    "aso":         { bg: "#f1f9ff,#d9efff 55%,#bfe3ff", ink: "#0b3d66", accent: "#1c7ed6", btn: "#1971c2,#4dabf7", icon: "🌟", petals: ["⭐", "💙", "✨", "🌸", "📱"] },
    "dev":         { bg: "#f4f6ff,#e1e7ff 55%,#cbd5ff", ink: "#1e2a78", accent: "#4263eb", btn: "#3b5bdb,#5c7cfa", icon: "💻", petals: ["💙", "✨", "🌸", "⭐", "🌷"] },
    "quan-ly":     { bg: "#fffcf0,#fff1c7 55%,#ffe39a", ink: "#6b4a00", accent: "#c08a00", btn: "#e0a800,#f5c242", icon: "👑", petals: ["🌻", "💛", "✨", "🌸", "⭐"] }
  };

  function themeVars(name) {
    var t = THEMES[name] || THEMES["mac-dinh"];
    return "--wd-bg:linear-gradient(160deg," + t.bg + " 100%);--wd-ink:" + t.ink +
      ";--wd-accent:" + t.accent + ";--wd-btn:linear-gradient(90deg," + t.btn + ")";
  }

  var CSS =
    ".wd-overlay{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;" +
    "background:rgba(40,10,30,.45);backdrop-filter:blur(3px);animation:wd-fade .35s ease-out;padding:16px;overflow:hidden;" +
    "font-family:-apple-system,'Segoe UI',Roboto,sans-serif}" +
    ".wd-card{position:relative;z-index:1;box-sizing:border-box;width:min(440px,100%);border-radius:22px;overflow:hidden;text-align:center;" +
    "background:var(--wd-bg);box-shadow:0 24px 60px rgba(40,20,40,.35);" +
    "animation:wd-pop .45s cubic-bezier(.2,1.4,.4,1)}" +
    ".wd-top{padding:30px 28px 6px}" +
    ".wd-flower{font-size:54px;line-height:1;filter:drop-shadow(0 4px 8px rgba(200,40,90,.25))}" +
    ".wd-date{margin-top:10px;font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--wd-accent);font-weight:700}" +
    ".wd-hello{margin:8px 0 0;font-size:26px;font-weight:800;color:var(--wd-ink);line-height:1.25}" +
    ".wd-msg{margin:14px 28px 0;font-size:15.5px;line-height:1.6;color:var(--wd-ink);opacity:.9;white-space:pre-line}" +
    ".wd-sign{margin:14px 0 0;font-size:13px;color:var(--wd-accent);font-style:italic}" +
    ".wd-actions{padding:22px 28px 26px}" +
    ".wd-btn{border:0;cursor:pointer;font:inherit;font-weight:700;font-size:15px;color:#fff;padding:12px 26px;border-radius:999px;" +
    "background:var(--wd-btn);box-shadow:0 8px 18px rgba(40,20,40,.25)}" +
    ".wd-btn:focus-visible,.wd-x:focus-visible{outline:3px solid var(--wd-ink);outline-offset:2px}" +
    ".wd-x{position:absolute;top:10px;right:12px;width:34px;height:34px;border:0;border-radius:50%;cursor:pointer;" +
    "background:rgba(255,255,255,.7);color:var(--wd-ink);font-size:20px;line-height:34px;padding:0}" +
    ".wd-petals{position:absolute;inset:0;z-index:0;pointer-events:none}" +
    ".wd-petal{position:absolute;top:-40px;animation:wd-fall linear forwards;opacity:.9}" +
    "@keyframes wd-fade{from{opacity:0}}" +
    "@keyframes wd-pop{from{transform:scale(.85);opacity:0}}" +
    "@keyframes wd-fall{to{transform:translateY(110vh) rotate(540deg);opacity:.2}}" +
    "@media (prefers-reduced-motion:reduce){.wd-overlay,.wd-card{animation:none}.wd-petals{display:none}}";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function render(person, sign, button) {
    if (!document.getElementById(STYLE_ID)) {
      var st = el("style");
      st.id = STYLE_ID;
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    var overlay = el("div", "wd-overlay");
    overlay.setAttribute("style", themeVars(person.theme));

    // Cánh hoa nằm DƯỚI thiệp (z-index 0 < 1) để không đè chữ
    var petals = el("div", "wd-petals");
    var theme = THEMES[person.theme] || THEMES["mac-dinh"];
    var icons = theme.petals;
    for (var i = 0; i < 28; i++) {
      var p = el("span", "wd-petal", icons[i % icons.length]);
      p.style.left = Math.random() * 100 + "%";
      p.style.animationDuration = 4 + Math.random() * 4 + "s";
      p.style.animationDelay = Math.random() * 2.5 + "s";
      p.style.fontSize = 16 + Math.random() * 14 + "px";
      petals.appendChild(p);
    }
    overlay.appendChild(petals);

    var card = el("div", "wd-card");
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "wd-hello");
    var x = el("button", "wd-x", "×");
    x.type = "button";
    x.setAttribute("aria-label", "Đóng");
    var top = el("div", "wd-top");
    top.appendChild(el("div", "wd-flower", theme.icon));
    top.appendChild(el("div", "wd-date", "20 · 10 · Ngày Phụ nữ Việt Nam"));
    var hello = el("h2", "wd-hello", person.name ? "Chúc mừng " + person.name + "!" : "Chúc mừng 20/10!");
    hello.id = "wd-hello";
    top.appendChild(hello);
    var actions = el("div", "wd-actions");
    var ok = el("button", "wd-btn", button || "Cảm ơn Nobi 💖");
    ok.type = "button";
    actions.appendChild(ok);
    card.appendChild(x);
    card.appendChild(top);
    card.appendChild(el("p", "wd-msg", person.message || ""));
    if (sign) card.appendChild(el("p", "wd-sign", sign));
    card.appendChild(actions);
    overlay.appendChild(card);

    function close() {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    x.onclick = close;
    ok.onclick = close;
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
    ok.focus();
    setTimeout(function () { petals.remove(); }, 11000);
  }

  var started = false;

  function start(opts) {
    if (started) return;
    var preview = isPreview();
    if (!preview && todayInVietnam() !== DAY) return;
    started = true;
    var email = opts && opts.email ? String(opts.email).trim().toLowerCase() : "";
    Promise.all([loadData(opts.dataUrl), email ? sha256Hex(email) : Promise.resolve(null)]).then(function (r) {
      var data = r[0] || {};
      var hash = r[1];
      var person = hash && data.entries ? data.entries[hash] : null;
      var seenKey = hash || "chung";
      if (!person) person = opts.fallback || null;
      if (!person) return;
      if (!preview && readSeen(seenKey)) return;
      markSeen(seenKey);
      render(person, data.sign || opts.sign || "", data.button || opts.button);
    }).catch(function () { /* thiệp là phần phụ: lỗi gì cũng không được làm hỏng trang */ });
  }

  window.WomenDayGreeting = { start: start };
})();
