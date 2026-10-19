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
 *   window.WOMEN_DAY_GREETINGS cũng có thể mang `button` (chữ trên nút) và `qr_file`
 *   (ảnh QR đặt cạnh file dữ liệu — bấm nút sẽ hiện màn trêu "xin 50k").
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
    "media-buyer": { bg: "#fff8f1,#ffe6d1 55%,#ffd2b3", ink: "#7a2e05", accent: "#e8590c", btn: "#f76707,#ff922b", icon: "🌷", petals: ["🌼", "🧡", "🌸", "✨", "🌷"] },
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
    "background:var(--wd-bg);box-shadow:0 24px 60px rgba(40,20,40,.35)}" +
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
    ".wd-qr-body{padding:4px 26px 26px}.wd-qr-body p{margin:10px 0 0;font-size:15px;line-height:1.55;color:var(--wd-ink)}" +
    ".wd-qr-img{display:block;margin:14px auto 0;width:min(220px,70vw);height:auto;border-radius:12px;background:#fff;padding:8px;box-shadow:0 6px 16px rgba(40,20,40,.18)}" +
    ".wd-qr-note{font-size:12.5px!important;opacity:.75}" +
    // Hiệu ứng: thiệp nảy lên + ánh hồng, chùm tim bung, chữ hiện dần, icon đập nhịp,
    // tim bay lên, nút phập phồng, lật thiệp khi sang màn QR
    ".wd-card{animation:wd-rise .8s cubic-bezier(.2,1.5,.4,1) both,wd-glow 2.6s ease-in-out .8s infinite}" +
    ".wd-flower{animation:wd-beat 1.4s ease-in-out .6s infinite}" +
    ".wd-date,.wd-hello,.wd-msg,.wd-sign,.wd-actions{animation:wd-up .6s ease-out both}" +
    ".wd-date{animation-delay:.35s}.wd-hello{animation-delay:.5s}.wd-msg{animation-delay:.75s}.wd-sign{animation-delay:1s}.wd-actions{animation-delay:1.15s}" +
    ".wd-btn{animation:wd-pulse 1.8s ease-in-out 2s infinite}" +
    ".wd-burst{position:absolute;left:50%;top:50%;z-index:2;pointer-events:none}" +
    ".wd-burst span{position:absolute;left:0;top:0;font-size:20px;opacity:0;animation:wd-pop-heart 1.3s cubic-bezier(.1,.8,.3,1) forwards}" +
    ".wd-float{position:absolute;bottom:-40px;z-index:0;pointer-events:none;opacity:0;animation:wd-floatup linear infinite}" +
    ".wd-card.wd-flip{animation:wd-flip .7s ease-in-out both}" +
    "@keyframes wd-rise{0%{transform:translateY(60px) scale(.7) rotate(-4deg);opacity:0}60%{opacity:1}100%{transform:none}}" +
    "@keyframes wd-glow{0%,100%{box-shadow:0 24px 60px rgba(40,20,40,.35),0 0 0 0 rgba(255,105,150,0)}50%{box-shadow:0 24px 60px rgba(40,20,40,.35),0 0 36px 8px rgba(255,105,150,.45)}}" +
    "@keyframes wd-beat{0%,100%{transform:scale(1)}15%{transform:scale(1.18)}30%{transform:scale(1)}45%{transform:scale(1.12)}60%{transform:scale(1)}}" +
    "@keyframes wd-up{from{transform:translateY(14px);opacity:0}}" +
    "@keyframes wd-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}" +
    "@keyframes wd-pop-heart{0%{transform:translate(-50%,-50%) scale(.2);opacity:1}70%{opacity:1}100%{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy))) scale(1.1) rotate(var(--rot));opacity:0}}" +
    "@keyframes wd-floatup{0%{transform:translateY(0);opacity:0}10%{opacity:.85}50%{transform:translateY(-55vh) translateX(var(--sway))}100%{transform:translateY(-110vh);opacity:0}}" +
    "@keyframes wd-flip{0%{transform:perspective(900px) rotateY(0)}50%{transform:perspective(900px) rotateY(90deg)}100%{transform:perspective(900px) rotateY(0)}}" +
    "@keyframes wd-fade{from{opacity:0}}" +
    "@keyframes wd-fall{to{transform:translateY(110vh) rotate(540deg);opacity:.2}}" +
    "@media (prefers-reduced-motion:reduce){.wd-overlay,.wd-card,.wd-flower,.wd-btn,.wd-date,.wd-hello,.wd-msg,.wd-sign,.wd-actions{animation:none}.wd-petals,.wd-burst,.wd-float{display:none}}";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function render(person, sign, button, qrUrl) {
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
    // Mỗi người có thể có biểu tượng riêng (person.icon), không thì theo theme
    top.appendChild(el("div", "wd-flower", person.icon || theme.icon));
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

    // Chùm tim bung từ giữa thiệp lúc vừa hiện
    var burst = el("div", "wd-burst");
    var hearts = ["💗", "💖", "💕", "🌸", "💞", "✨"];
    for (var b = 0; b < 18; b++) {
      var h = el("span", null, hearts[b % hearts.length]);
      var ang = (b / 18) * Math.PI * 2, dist = 150 + Math.random() * 110;
      h.style.setProperty("--dx", Math.cos(ang) * dist + "px");
      h.style.setProperty("--dy", Math.sin(ang) * dist + "px");
      h.style.setProperty("--rot", (Math.random() * 120 - 60) + "deg");
      h.style.animationDelay = 0.35 + Math.random() * 0.25 + "s";
      burst.appendChild(h);
    }
    overlay.appendChild(burst);
    // Tim bay lên lơ lửng phía sau thiệp
    for (var f = 0; f < 12; f++) {
      var fh = el("span", "wd-float", f % 3 ? "💗" : "💕");
      fh.style.left = 4 + Math.random() * 92 + "%";
      fh.style.fontSize = 14 + Math.random() * 16 + "px";
      fh.style.setProperty("--sway", (Math.random() * 60 - 30) + "px");
      fh.style.animationDuration = 6 + Math.random() * 5 + "s";
      fh.style.animationDelay = 0.8 + Math.random() * 6 + "s";
      overlay.appendChild(fh);
    }

    function close() {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    x.onclick = close;
    // Nút "Cảm ơn" có màn trêu: hiện mã QR "xin 50k". Ảnh nạp trước; nạp hỏng
    // (chưa đặt file) thì nút chỉ đóng thiệp như bình thường.
    var qrImg = null;
    if (qrUrl) {
      qrImg = el("img", "wd-qr-img");
      qrImg.alt = "Mã QR chuyển khoản";
      qrImg.onerror = function () { qrImg = null; };
      qrImg.src = qrUrl;
    }
    function showQr() {
      // Lật thiệp: đổi nội dung ở giữa cú lật (lúc thiệp quay 90°, không thấy mặt)
      card.classList.remove("wd-flip");
      void card.offsetWidth;
      card.classList.add("wd-flip");
      setTimeout(fillQr, 350);
    }
    function fillQr() {
      while (card.lastChild !== top) card.removeChild(card.lastChild);
      top.querySelector(".wd-flower").textContent = "🧋";
      hello.textContent = "Khoan đã… 🤭";
      var body = el("div", "wd-qr-body");
      body.appendChild(el("p", null, "Cảm ơn bằng lời thì Nobi nhận rồi nha 😌 Còn cảm ơn bằng hành động thì… quét giúp Nobi 50k mua ly trà sữa nhé!"));
      body.appendChild(qrImg);
      body.appendChild(el("p", "wd-qr-note", "Đùa đó 😆 Chúc 20/10 thật vui, thật nhiều quà!"));
      card.appendChild(body);
      // Màn QR không có nút: đóng bằng ×, bấm ra ngoài hoặc Esc
      x.focus();
    }
    ok.onclick = function () { if (qrImg) showQr(); else close(); };
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
    ok.focus();
    setTimeout(function () { petals.remove(); burst.remove(); }, 11000);
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
      // Ảnh QR nằm cạnh file dữ liệu: tính đường dẫn theo dataUrl để chạy đúng ở cả 3 tool
      var qrUrl = data.qr_file ? new URL(data.qr_file, new URL(opts.dataUrl, location.href)).href : null;
      render(person, data.sign || opts.sign || "", data.button || opts.button, qrUrl);
    }).catch(function () { /* thiệp là phần phụ: lỗi gì cũng không được làm hỏng trang */ });
  }

  window.WomenDayGreeting = { start: start };
})();
