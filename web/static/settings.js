// Trang Cài đặt — tách hẳn khỏi trang tải video.
//
// Cố ý KHÔNG dùng lại `app.js`: trang đó nạp hàng đợi, thư viện, SSE và một
// vòng poll 5 giây. Trang này chỉ cần hai lời gọi. Chia sẻ tệp đồng nghĩa với
// chia sẻ cả vòng poll — trang Cài đặt sẽ gọi `/jobs` mãi mà không ai dùng.
// Thứ dùng chung thật sự là `app.css`, và đó là thứ đáng dùng chung.
(() => {
  "use strict";

  // Bốn mã cookie: người dùng TỰ CHỮA ĐƯỢC cả bốn, nên câu chữ phải nói cách
  // chữa. Giữ đồng bộ với bảng cùng tên trong `app.js` — thêm mã ở
  // `web/cookies.py::MA_LOI_COOKIE` thì phải thêm câu ở CẢ HAI nơi.
  const MA_COOKIE = {
    cookie_khong_doc_duoc: "Tệp không đọc được — xuất lại dạng JSON (không phải RTF).",
    cookie_rong: "Tệp không có cookie nào — xuất lại khi đang mở tiktok.com.",
    cookie_chua_dang_nhap: "Cookie không có phiên đăng nhập — đăng nhập TikTok rồi xuất lại.",
    cookie_het_han: "Cookie đăng nhập đã hết hạn — đăng nhập lại rồi xuất lại.",
  };

  class PhienHetHan extends Error {}

  function baoPhienHetHan() {
    const el = document.getElementById("session-expired");
    if (el) el.hidden = false;
  }

  async function apiGet(path) {
    // `redirect: "manual"` — xem ghi chú dài trong app.js: phiên Access hết hạn
    // trả 302 sang trang đăng nhập, `fetch` đi theo rồi chết vì CORS.
    const res = await fetch(path, { redirect: "manual" });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
    return res.json();
  }

  async function apiSend(method, path, body) {
    const res = await fetch(path, {
      method,
      redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) {
      let ma = null;
      try { ma = (await res.json()).detail; } catch (e) { ma = null; }
      const err = new Error(`${method} ${path} -> ${res.status}`);
      err.ma = ma;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------------------------------------------------------------- cookie
  function veCookie(tt) {
    const chip = document.getElementById("cookie-chip");
    const set = (id, text) => { document.getElementById(id).textContent = text; };

    if (!tt.co_jar) {
      chip.textContent = "Chưa có";
      chip.className = "chip chip-warn";
      set("ck-trang-thai", "Chưa dán cookie — lượt tải chạy ẩn danh");
      set("ck-han", "—");
      set("ck-luc", "—");
      return;
    }
    const tot = tt.trang_thai === "dung_duoc";
    chip.textContent = tot ? "Đang dùng được" : "Cần dán lại";
    chip.className = "chip " + (tot ? "chip-ok" : "chip-warn");
    set("ck-trang-thai", tot ? "Dùng được" : (MA_COOKIE[tt.trang_thai] || tt.trang_thai));
    set("ck-han", tt.het_han ? new Date(tt.het_han).toLocaleDateString("vi-VN") : "Không có hạn");
    set("ck-luc", tt.cap_nhat_luc ? new Date(tt.cap_nhat_luc).toLocaleString("vi-VN") : "—");
  }

  async function loadCookie() {
    try {
      veCookie(await apiGet("/me/cookie"));
    } catch (err) {
      const chip = document.getElementById("cookie-chip");
      chip.textContent = "Không đọc được";
      chip.className = "chip chip-warn";
      throw err;
    }
  }

  // ----------------------------------------------------------------- quota
  function veQuota(q) {
    document.getElementById("quota-theo").textContent = q.an_danh
      ? "Bạn chưa dán cookie — đang dùng chung túi hạn mức với mọi người chưa dán."
      : "Trần tính theo tài khoản TikTok của bạn.";

    const hang = [
      ["Lượt tải", q.luot_tai],
      ["Số video", q.video],
      ["Trang đã quét", q.trang_index],
    ];
    document.getElementById("quota-list").innerHTML = hang.map(([ten, o]) => {
      const pct = o.tran > 0 ? Math.min(100, Math.round(o.da_dung / o.tran * 100)) : 0;
      // >75% thì đổi màu: con số thì luôn đúng, nhưng người ta đọc màu trước.
      return `<div class="quota-row">
        <span class="quota-ten">${ten}</span>
        <span class="quota-so"><strong>${o.da_dung}</strong> / ${o.tran}</span>
        <span class="quota-bar${pct >= 75 ? " hot" : ""}"><i style="width:${pct}%"></i></span>
      </div>`;
    }).join("");
  }

  async function loadQuota() {
    veQuota(await apiGet("/me/quota"));
  }

  // --------------------------------------------------------------- sự kiện
  function noiCookie() {
    const o = document.getElementById("cookie-json");
    const loi = document.getElementById("cookie-error");
    const luu = document.getElementById("cookie-luu");
    const file = document.getElementById("cookie-file");
    const tenTep = document.getElementById("cookie-ten-tep");
    const drop = document.getElementById("cookie-drop");

    // Tệp đọc ở trình duyệt rồi đổ vào chính ô dán: người dùng THẤY thứ sắp
    // gửi trước khi bấm Lưu, và backend chỉ có một đường vào để mà canh.
    function nhanTep(f) {
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        o.value = String(reader.result || "");
        tenTep.textContent = f.name;
        loi.textContent = "";
      };
      reader.onerror = () => { loi.textContent = "Không đọc được tệp."; };
      reader.readAsText(f);
    }

    document.getElementById("cookie-chon-tep").addEventListener("click", () => file.click());
    file.addEventListener("change", () => nhanTep(file.files[0]));
    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dang-keo"); }));
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dang-keo"); }));
    drop.addEventListener("drop", (e) => nhanTep(e.dataTransfer?.files?.[0]));

    luu.addEventListener("click", async () => {
      loi.textContent = "";
      luu.disabled = true;
      try {
        veCookie(await apiSend("PUT", "/me/cookie", { json: o.value }));
        o.value = "";           // không giữ cookie trong DOM lâu hơn mức cần
        tenTep.textContent = "tệp xuất từ Cookie-Editor";
        await loadQuota();      // dán xong thì hết ẩn danh — số phải đổi theo
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        loi.textContent = MA_COOKIE[err.ma] || ("Không lưu được cookie: " + err.message);
      } finally {
        luu.disabled = false;
      }
    });

    document.getElementById("cookie-xoa").addEventListener("click", async () => {
      if (!window.confirm("Xoá cookie của bạn? Lượt tải sau sẽ chạy ẩn danh.")) return;
      loi.textContent = "";
      try {
        await apiSend("DELETE", "/me/cookie");
        await Promise.all([loadCookie(), loadQuota()]);
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        loi.textContent = "Không xoá được: " + err.message;
      }
    });
  }

  // -------------------------------------------------------------- quản trị
  function escapeHtml(x) {
    return String(x ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function veNguoiDung(data) {
    const tbody = document.querySelector("#bang-nguoi-dung tbody");
    const md = data.tran_mac_dinh;
    tbody.innerHTML = data.nguoi_dung.map((u) => {
      const e = escapeHtml(u.email);
      // `placeholder` là số mặc định đang áp, `value` rỗng khi chưa đặt riêng:
      // ô trống nghĩa là "theo mặc định", KHÔNG phải "không giới hạn".
      return `<tr data-email="${e}">
        <td><span class="email">${e}</span>${u.la_admin ? '<span class="me">quản trị</span>' : ""}</td>
        <td><span class="chip ${u.co_cookie ? "chip-ok" : "chip-off"}">${u.co_cookie ? "có" : "chưa có"}</span></td>
        <td><input class="num" data-f="tran_luot" value="${u.tran_luot ?? ""}" placeholder="${md.luot}"></td>
        <td><input class="num" data-f="tran_video" value="${u.tran_video ?? ""}" placeholder="${md.video}"></td>
        <td class="fig">${u.da_dung_luot} lượt · ${u.da_dung_video} video${
          u.dung_chung ? ' <span class="muted" title="Chưa dán cookie nên dùng chung túi hạn mức với mọi người chưa dán — đây là số của cả túi, không phải của riêng người này.">(túi chung)</span>' : ""}</td>
        <td>
          <button type="button" class="ghost sm" data-act="quyen" data-to="${u.la_admin ? 0 : 1}">
            ${u.la_admin ? "Bỏ quyền admin" : "Cho làm admin"}
          </button>
          <button type="button" class="ghost sm" data-act="luu">Lưu trần</button>
        </td>
      </tr>`;
    }).join("");
  }

  async function loadNguoiDung() {
    veNguoiDung(await apiGet("/admin/nguoi-dung"));
  }

  async function guiCapNhat(email, body) {
    const loi = document.getElementById("admin-error");
    loi.textContent = "";
    try {
      await apiSend("PUT", "/admin/nguoi-dung/" + encodeURIComponent(email), body);
      await loadNguoiDung();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      // 409 = khoá "admin cuối cùng". Nói ra lý do, đừng để người dùng bấm lại
      // mãi một nút sẽ không bao giờ chạy.
      loi.textContent = err.ma || ("Không lưu được: " + err.message);
    }
  }

  function noiQuanTri() {
    document.querySelector("#bang-nguoi-dung tbody").addEventListener("click", (ev) => {
      const nut = ev.target.closest("button[data-act]");
      if (!nut) return;
      const tr = nut.closest("tr");
      const email = tr.dataset.email;
      if (nut.dataset.act === "quyen") {
        const bo = nut.dataset.to === "0";
        if (bo && !window.confirm(`Bỏ quyền quản trị của ${email}?`)) return;
        guiCapNhat(email, { la_admin: !bo });
      } else {
        const so = (f) => {
          const v = tr.querySelector(`input[data-f="${f}"]`).value.trim();
          return v === "" ? null : Number(v);
        };
        guiCapNhat(email, { tran_luot: so("tran_luot"), tran_video: so("tran_video") });
      }
    });
  }

  function noiTab(laAdmin) {
    const tabQT = document.getElementById("tab-quan-tri");
    const tabCT = document.getElementById("tab-cua-toi");
    const vungQT = document.getElementById("vung-quan-tri");
    const vungCT = document.getElementById("vung-cua-toi");
    // Ẩn tab cho người thường là chuyện ĐỠ RỐI MẮT, không phải phân quyền —
    // cửa thật là `require_admin` ở server, trả 403 kể cả khi gọi thẳng API.
    tabQT.hidden = !laAdmin;
    if (!laAdmin) return;

    const doi = (sangQT) => {
      tabQT.classList.toggle("on", sangQT);
      tabCT.classList.toggle("on", !sangQT);
      tabQT.setAttribute("aria-selected", String(sangQT));
      tabCT.setAttribute("aria-selected", String(!sangQT));
      vungQT.hidden = !sangQT;
      vungCT.hidden = sangQT;
      if (sangQT) loadNguoiDung().catch(() => {});
    };
    tabQT.addEventListener("click", () => doi(true));
    tabCT.addEventListener("click", () => doi(false));
    noiQuanTri();
  }

  // ----------------------------------------------------------------- theme
  const THEME_KEY = "videodl-theme";
  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }
  try { applyTheme(localStorage.getItem(THEME_KEY)); } catch (e) { /* private mode */ }
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
    applyTheme(next);
  });

  // ------------------------------------------------------------------ init
  noiCookie();
  apiGet("/me")
    .then((me) => noiTab(me.la_admin))
    .catch(() => { /* không biết mình là ai thì cứ coi như người thường */ });
  Promise.all([loadCookie(), loadQuota()]).catch((err) => {
    if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
    document.getElementById("cookie-error").textContent =
      "Không tải được dữ liệu: " + err.message;
  });
})();
