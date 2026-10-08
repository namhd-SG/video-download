// Trang "Thay logo" (M1). Tự poll danh sách (không SSE — ĐP-1508), mọi chữ của dữ liệu đưa vào bằng textContent, không innerHTML.
(() => {
  "use strict";
  const POLL_MS = 15000;
  const NHAN = {
    xong: ["Đã thay · chờ duyệt", "ok"], cho_nguoi: ["Không thay được", ""], cho_agy: ["Chờ agy", ""],
    cho: ["Đang chuẩn bị", ""], dang_chay: ["Đang xử lý", ""], loi: ["Lỗi", "bad"],
  };
  const LOAI_LOI = [["sot_watermark", "Sót watermark"], ["sai_cho", "Đè sai chỗ"], ["che_phu_de", "Che phụ đề"],
                    ["pha_noi_dung", "Phá nội dung"], ["khac", "Khác"]];
  const $ = (id) => document.getElementById(id);
  let videos = [], loc = "tat_ca", capNhatLuc = 0;

  // ---- theme: cùng khoá với trang chính
  const THEME_KEY = "videodl-theme";
  const apTheme = (t) => (t === "light" || t === "dark") ? document.documentElement.setAttribute("data-theme", t)
                                                        : document.documentElement.removeAttribute("data-theme");
  try { apTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* trình duyệt chặn lưu trữ: theo hệ điều hành */ }
  $("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* bỏ qua */ }
    apTheme(next);
  });

  async function goi(path, opts) {
    const res = await fetch(path, { redirect: "manual", ...opts });
    if (res.type === "opaqueredirect" || res.status === 401) { $("session-expired").hidden = false; throw new Error("het_phien"); }
    return res;
  }
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const chip = (text, cls, title) => { const c = el("span", "tl-chip " + (cls || ""), text); if (title) c.title = title; return c; };
  const driveId = (s) => { const m = String(s).match(/(?:\/d\/|id=)([A-Za-z0-9_-]{10,120})/); return m ? m[1] : String(s).trim(); };
  const phut = (giay) => Math.max(0, Math.round(giay / 60));
  const nhom = (v) => v.trang_thai === "xong" && v.can_soi_ky ? "soi_ky" : v.trang_thai;

  // ---- tạo lượt
  $("tl-mo-thu-vien").addEventListener("click", async () => {
    const hop = $("tl-chon");
    if (hop.classList.toggle("mo") && !hop.childElementCount) {
      const r = await goi("/videos?limit=100");
      const ds = r.ok ? (await r.json()).videos || [] : [];
      for (const v of ds.filter((x) => x.drive_file_id)) {
        const lb = el("label"); const cb = el("input"); cb.type = "checkbox"; cb.value = v.drive_file_id;
        lb.append(cb, " " + (v.video_id || v.drive_file_id)); hop.append(lb);
      }
      if (!hop.childElementCount) hop.append(el("p", "muted", "Thư viện chưa có video nào đã lên Drive."));
    }
  });
  $("tl-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("tl-loi").textContent = "";
    const ids = [...$("tl-link").value.split("\n").map((s) => s.trim()).filter(Boolean).map(driveId),
                 ...[...document.querySelectorAll("#tl-chon input:checked")].map((c) => c.value)];
    if (!ids.length) { $("tl-loi").textContent = "Chưa có video nào."; return; }
    const r = await goi("/api/thay-logo/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ drive_file_ids: [...new Set(ids)] }) });
    if (!r.ok) { const b = await r.json().catch(() => ({})); $("tl-loi").textContent = (b.detail && String(b.detail)) || `Lỗi ${r.status}`; return; }
    $("tl-link").value = ""; document.querySelectorAll("#tl-chon input:checked").forEach((c) => { c.checked = false; });
    taiLai();
  });

  // ---- danh sách
  function veLoc() {
    const dem = { tat_ca: videos.length };
    for (const v of videos) dem[nhom(v)] = (dem[nhom(v)] || 0) + 1;
    const hop = $("tl-loc"); hop.replaceChildren();
    for (const [k, ten, cls] of [["tat_ca", "Tất cả", ""], ["xong", "Chờ duyệt", "ok"], ["soi_ky", "Cần soi kỹ", "warn"],
                                 ["cho_agy", "Chờ agy", ""], ["cho_nguoi", "Không thay được", ""], ["loi", "Lỗi", "bad"]]) {
      const b = el("button", "tl-chip " + cls + (loc === k ? " on" : ""), `${ten} ${dem[k] || 0}`);
      b.type = "button"; b.addEventListener("click", () => { loc = k; ve(); }); hop.append(b);
    }
    hop.append(chip(capNhatLuc ? `⟳ ${Math.round((Date.now() - capNhatLuc) / 1000)} giây trước` : "⟳ …", "", "Lần cập nhật cuối"));
  }

  function nutDanhGia(v) {
    const hang = el("div", "tl-hang");
    const goc = (v.nguon && JSON.parse(v.nguon).file_id) || "";
    if (v.drive_file_id_ra) { const a = el("a", "", "▶ Xem video đã thay"); a.href = `https://drive.google.com/file/d/${encodeURIComponent(v.drive_file_id_ra)}/view`; a.target = "_blank"; a.rel = "noopener"; hang.append(a); }
    if (goc) { const a = el("a", "", "Bản gốc"); a.href = `https://drive.google.com/file/d/${encodeURIComponent(goc)}/view`; a.target = "_blank"; a.rel = "noopener"; hang.append(a); }
    if (v.trang_thai !== "xong") return [hang];
    const dat = el("button", "btn sm", "Đạt"); dat.type = "button";
    const hong = el("button", "btn sm danger-line", "Hỏng…"); hong.type = "button";
    const cap = el("span", "tl-cap");  // Đạt/Hỏng luôn đi cùng nhau, không bị dòng tách đôi (ĐP-1507 #3)
    cap.append(dat, hong);
    hang.append(cap);
    const mo = el("div", "tl-hong");
    const sel = el("select"); sel.setAttribute("aria-label", "Hỏng vì");
    for (const [k, t] of LOAI_LOI) { const o = el("option", "", t); o.value = k; sel.append(o); }
    const note = el("input"); note.type = "text"; note.placeholder = "Ghi chú (giây thứ mấy…)"; note.maxLength = 2000;
    const gui = el("button", "btn sm danger", "Gửi đánh giá hỏng"); gui.type = "button";
    mo.append(sel, note, gui);
    const danhGia = async (body) => {
      const r = await goi(`/api/thay-logo/videos/${v.id}/danh-gia`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (r.ok) taiLai(); else $("tl-loi").textContent = `Không gửi được đánh giá (${r.status}).`;
    };
    dat.addEventListener("click", () => danhGia({ ket_qua: "dat" }));
    hong.addEventListener("click", () => mo.classList.toggle("mo"));
    gui.addEventListener("click", () => danhGia({ ket_qua: "hong", loai_loi: sel.value, ghi_chu: note.value }));
    if (v.danh_gia) hang.append(chip(v.danh_gia === "dat" ? "Đã đánh giá: Đạt" : "Đã đánh giá: Hỏng", v.danh_gia === "dat" ? "ok" : "bad"));
    return [hang, mo];
  }

  function the(v) {
    const card = el("article", "tl-card" + (nhom(v) === "soi_ky" ? " co-co" : ""));
    if (v.co_sheet) { const img = el("img"); img.alt = "Trước / sau"; img.loading = "lazy"; img.src = `/api/thay-logo/videos/${v.id}/sheet.jpg`; card.append(img); }
    else card.append(el("div", "tl-o-trong", v.trang_thai === "cho_agy" ? "Đang chờ máy định vị" : "—"));
    const body = el("div");
    const goc = (v.nguon && JSON.parse(v.nguon).file_id) || `#${v.id}`;
    body.append(el("h3", "", goc));
    const meta = el("div", "tl-meta");
    const [ten, cls] = NHAN[v.trang_thai] || [v.trang_thai, ""];
    meta.append(chip(v.trang_thai === "cho_agy" && v.cho_agy_tu ? `${ten} · ${phut(Date.now() / 1000 - v.cho_agy_tu)} phút` : ten, cls));
    if (nhom(v) === "soi_ky") meta.append(chip("⚠ Cần soi kỹ", "warn"));
    if (v.pct_render != null && v.trang_thai === "xong") {
      meta.append(chip(`${Math.round(v.pct_render)}% khung`),
                  chip(`${100 - Math.round(v.pct_render)}% giữ nguyên`, "", "Khung chưa chắc vị trí hoặc có phụ đề/chữ chồng lên — giữ watermark gốc, không đè."));
    }
    if (v.trang_thai === "cho_nguoi" && v.so_box != null) meta.append(chip(`agy thấy ${v.so_box} box`));
    body.append(meta);
    if (nhom(v) === "soi_ky") body.append(el("p", "tl-co", "Có chữ/hình lạ nằm trong vùng logo ở phần lớn video — máy không tự loại hết được. Xem kỹ cả video trước khi dùng."));
    if (v.trang_thai === "cho_nguoi") body.append(el("p", "muted", "Không tìm ra watermark đủ chắc — video giữ nguyên, không có bản thay."));
    if (v.trang_thai === "cho_agy") body.append(el("p", "muted", "Máy định vị chưa trả kết quả. Lượt sẽ tự chạy tiếp khi có."));
    if (v.trang_thai === "loi") body.append(el("p", "muted", `${v.loi_text || "Lỗi không rõ"} — video gốc không bị ảnh hưởng.`));
    body.append(...nutDanhGia(v));
    card.append(body);
    return card;
  }

  function ve() {
    veLoc();
    const ds = loc === "tat_ca" ? videos : videos.filter((v) => nhom(v) === loc);
    const list = $("tl-list");
    list.replaceChildren(...(ds.length ? ds.map(the) : [el("p", "muted", "Chưa có video nào.")]));
  }

  async function taiLai() {
    try {
      const r = await goi("/api/thay-logo/videos");
      if (!r.ok) return;
      videos = (await r.json()).videos || [];
      capNhatLuc = Date.now();
      ve();
    } catch (_) { /* hết phiên đã báo ở trên */ }
  }

  async function kiemBat() {
    try {
      const r = await goi("/tinh-nang");
      if (r.ok && !(await r.json()).thay_logo_bat) $("tat").hidden = false;
    } catch (_) { /* bỏ qua */ }
  }

  kiemBat();
  taiLai();
  setInterval(taiLai, POLL_MS);
  setInterval(veLoc, 5000);  // chỉ cập nhật chip độ tươi
})();
