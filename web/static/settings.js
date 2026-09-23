// Trang Cài đặt — tách hẳn khỏi trang tải video.
//
// Cố ý KHÔNG dùng lại `app.js`: trang đó nạp hàng đợi, thư viện, SSE và một
// vòng poll 5 giây. Trang này chỉ cần hai lời gọi. Chia sẻ tệp đồng nghĩa với
// chia sẻ cả vòng poll — trang Cài đặt sẽ gọi `/jobs` mãi mà không ai dùng.
// Thứ dùng chung thật sự là `app.css`, và đó là thứ đáng dùng chung.
(() => {
  "use strict";

  // Bốn mã cookie: người dùng TỰ CHỮA ĐƯỢC cả bốn, nên câu chữ phải nói cách
  // chữa. Bảng đã chuyển sang `cookie-status-text.js` để dải nhắc trên trang
  // chính dùng CÙNG một câu thay vì chép bản thứ hai.
  // `|| {}`: nếu `cookie-status-text.js` không nạp được (HTML cũ còn trong
  // cache trình duyệt sau một chuyến deploy, hoặc tệp 404) thì thiếu bảng chữ
  // là phiền — nhưng ném `TypeError` ở đây giết CẢ khối cookie, đúng cái trang
  // người ta mở ra để CHỮA cookie. Mất câu hướng dẫn còn hơn mất cả trang.
  const MA_COOKIE = window.MA_COOKIE_TRANG_THAI || {};

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
  // Trạng thái đang vẽ — phản hồi dán cần biết "đang có cookie tốt không" để nói
  // "cookie cũ vẫn đang dùng" thay vì để người dùng tưởng vừa mất nó.
  let ttHienTai = null;

  const ngay = (iso) => new Date(iso).toLocaleDateString("vi-VN");
  const gio = (iso) => new Date(iso).toLocaleString("vi-VN");

  // Một trạng thái = một khối màu + tiêu đề + một câu. Bốn mã hỏng từng dùng
  // chung một chip "Cần dán lại"; giờ mỗi cái có tiêu đề riêng.
  // Câu "hết hạn" nói việc THẬT xảy ra: `web/queue.py` DỪNG job khi jar hỏng
  // (không chạy ẩn danh) — đo 23/09, mock ban đầu viết sai chỗ này.
  function khoiTrangThai(tt) {
    if (!tt.co_jar) {
      return ["tt-trong", "–", "Chưa có cookie",
              "Lượt tải đang chạy ẩn danh và chia chung hạn mức với mọi người chưa dán."];
    }
    if (tt.trang_thai === "dung_duoc") {
      const ten = tt.tai_khoan && tt.tai_khoan.ten;
      return ["tt-ok", "✓", ten ? `Đang dùng được — @${ten}` : "Đang dùng được",
              "Lượt tải của bạn chạy bằng cookie này, hạn mức tính riêng cho tài khoản của nó."];
    }
    if (tt.trang_thai === "cookie_het_han") {
      return ["tt-loi", "!",
              tt.het_han ? `Cookie đã hết hạn ngày ${ngay(tt.het_han)}` : "Cookie đã hết hạn",
              "Lượt tải mới sẽ dừng ngay cho tới khi bạn dán cookie mới — đăng nhập lại TikTok rồi xuất lại."];
    }
    return ["tt-loi", "!", "Cookie đang lưu không dùng được",
            MA_COOKIE[tt.trang_thai] || tt.trang_thai];
  }

  // "Hạn đến" từng hiện "Không có hạn" cho jar HỎNG — đọc như tốt mãi, thật ra
  // là không đọc được hạn. `het_han` null có hai nghĩa; mã trạng thái phân định.
  function oHan(tt) {
    if (!tt.co_jar) return ["", "—"];
    if (tt.het_han) {
      return tt.trang_thai === "cookie_het_han"
        ? ["o-do", `${ngay(tt.het_han)} — đã qua`] : ["", ngay(tt.het_han)];
    }
    if (tt.trang_thai === "dung_duoc") return ["", "Phiên không ghi hạn"];
    if (tt.trang_thai === "cookie_khong_doc_duoc") return ["o-mo", "Không đọc được hạn"];
    return ["o-mo", "—"];  // rỗng / chưa đăng nhập: không có cookie đăng nhập nào để có hạn
  }

  function veCookie(tt) {
    ttHienTai = tt;
    const set = (id, text) => { document.getElementById(id).textContent = text; };
    const [lop, icon, tieuDe, cau] = khoiTrangThai(tt);
    document.getElementById("ck-tt").className = "tt " + lop;
    set("ck-tt-icon", icon);
    set("ck-tt-tieu-de", tieuDe);
    set("ck-tt-cau", cau);

    const [lopHan, han] = oHan(tt);
    document.getElementById("ck-o-han").className = "o" + (lopHan ? " " + lopHan : "");
    set("ck-han", han);
    set("ck-luc", tt.cap_nhat_luc ? gio(tt.cap_nhat_luc) : "—");
    // `null` = không đọc được tệp. "—" chứ không rỗng: ô trống trông như chưa nạp.
    set("ck-van-tay", tt.van_tay || "—");
    // Không có gì để xoá thì không bày nút xoá.
    document.getElementById("cookie-xoa").hidden = !tt.co_jar;

    // Ô Tài khoản chỉ hiện khi backend CÓ trả khoá `tai_khoan` — tức là khi có cơ
    // chế đọc tên. Chưa có thì không hứa "sẽ xác định".
    const oTk = document.getElementById("ck-o-tai-khoan");
    oTk.hidden = !("tai_khoan" in tt);
    if (!oTk.hidden) {
      set("ck-tai-khoan", tt.tai_khoan && tt.tai_khoan.ten ? "@" + tt.tai_khoan.ten
        : "Sẽ xác định — sau lượt tải nhạc, tìm kiếm hoặc trang cá nhân đầu tiên; lượt hashtag không đọc được tên");
    }
  }

  function baoPhanHoi(tieuDe, chiTiet, phu) {
    const el = document.getElementById("cookie-error");
    el.textContent = "";
    if (!tieuDe) { el.hidden = true; return; }
    const b = document.createElement("b");
    b.textContent = tieuDe;
    el.append(b, document.createTextNode(chiTiet || ""));
    if (phu) {
      const sp = document.createElement("span");
      sp.textContent = phu;
      el.append(sp);
    }
    el.hidden = false;
  }

  async function loadCookie() {
    try {
      veCookie(await apiGet("/me/cookie"));
    } catch (err) {
      document.getElementById("ck-tt").className = "tt tt-loi";
      document.getElementById("ck-tt-icon").textContent = "!";
      document.getElementById("ck-tt-tieu-de").textContent = "Không đọc được trạng thái cookie";
      document.getElementById("ck-tt-cau").textContent = "Tải lại trang; vẫn lỗi thì báo người phát triển.";
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
        tenTep.textContent = "Tệp: " + f.name;
        baoPhanHoi(null);
      };
      reader.onerror = () => { baoPhanHoi("Không đọc được tệp.", "", ""); };
      reader.readAsText(f);
    }

    document.getElementById("cookie-chon-tep").addEventListener("click", () => file.click());
    file.addEventListener("change", () => nhanTep(file.files[0]));
    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dang-keo"); }));
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dang-keo"); }));
    drop.addEventListener("drop", (e) => nhanTep(e.dataTransfer?.files?.[0]));

    // Cookie đang lưu sau một lần dán bị từ chối — `put_my_cookie` kiểm TRƯỚC khi
    // ghi, nên jar cũ còn nguyên. Nói ra, vì chip "Chưa có"/khối đỏ ngay sau một
    // lần bấm Lưu dễ đọc thành "vừa mất cookie".
    function cauJarCu() {
      if (!ttHienTai || !ttHienTai.co_jar) return "Chưa có cookie nào được lưu.";
      if (ttHienTai.trang_thai === "dung_duoc") {
        const ten = ttHienTai.tai_khoan && ttHienTai.tai_khoan.ten;
        return `Cookie cũ${ten ? ` (@${ten})` : ""} vẫn đang dùng — không có gì bị ghi đè.`;
      }
      return "Cookie đang lưu giữ nguyên (nó cũng đang không dùng được).";
    }

    luu.addEventListener("click", async () => {
      baoPhanHoi(null);
      luu.disabled = true;
      try {
        veCookie(await apiSend("PUT", "/me/cookie", { json: o.value }));
        await loadQuota();      // dán xong thì hết ẩn danh — số phải đổi theo
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        if (MA_COOKIE[err.ma]) baoPhanHoi("Cookie vừa dán bị từ chối.", " " + MA_COOKIE[err.ma], cauJarCu());
        else baoPhanHoi("Không lưu được cookie.", " " + err.message, cauJarCu());
      } finally {
        // Xoá ô ở MỌI nhánh, không chỉ nhánh thành công: bản trước chỉ xoá khi
        // lưu được, nên cookie bị TỪ CHỐI — đúng lúc nó là cookie thật đầy đủ
        // phiên đăng nhập — nằm nguyên trên màn hình. Cả bốn mã từ chối đều bảo
        // người dùng xuất lại, nên giữ bản dán hỏng không giúp gì cho họ.
        o.value = "";
        tenTep.textContent = "";
        luu.disabled = false;
      }
    });

    document.getElementById("cookie-xoa").addEventListener("click", async () => {
      if (!window.confirm("Xoá cookie của bạn? Lượt tải sau sẽ chạy ẩn danh.")) return;
      baoPhanHoi(null);
      try {
        await apiSend("DELETE", "/me/cookie");
        await Promise.all([loadCookie(), loadQuota()]);
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        baoPhanHoi("Không xoá được.", " " + err.message, "");
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
    baoPhanHoi("Không tải được dữ liệu.", " " + err.message, "");
  });
})();
