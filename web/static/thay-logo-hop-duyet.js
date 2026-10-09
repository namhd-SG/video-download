// Hộp "Chờ bạn duyệt" (trước/sau, Đạt/Hỏng) + cột phải (máy đang làm / không chắc / không làm được).
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const LOAI_LOI = [["sot_watermark", "Sót watermark"], ["sai_cho", "Đè sai chỗ"], ["che_phu_de", "Che phụ đề"], ["pha_noi_dung", "Phá nội dung"], ["khac", "Khác"]];
  let vi = 0, moHong = false;

  const hangDuyet = () => T.locDuoc().filter((v) => T.nhomCua(v) === "cho_duyet");

  async function danhGia(v, body) {
    const r = await T.goi(`/api/thay-logo/videos/${v.id}/danh-gia`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { moHong = false; window.TL_taiLai(); } else T.loi(`Không gửi được đánh giá (${r.status}).`);
  }

  function veDuyet() {
    const hop = $("tl-duyet"); hop.replaceChildren();
    const ds = hangDuyet();
    if (vi >= ds.length) vi = Math.max(0, ds.length - 1);
    const head = el("div", "tl-duyet-head"); head.append(el("h2", "", "Chờ bạn duyệt"), el("span", "tl-dem", ds.length ? `${vi + 1} / ${ds.length}` : "0"));
    head.append(el("span", "grow"));
    const truoc = el("button", "btn tl-nav", "‹"), sau = el("button", "btn tl-nav", "›");
    truoc.type = sau.type = "button"; truoc.setAttribute("aria-label", "Video trước"); sau.setAttribute("aria-label", "Video sau");
    truoc.disabled = sau.disabled = ds.length < 2;
    truoc.addEventListener("click", () => { vi = (vi - 1 + ds.length) % ds.length; moHong = false; veDuyet(); });
    sau.addEventListener("click", () => { vi = (vi + 1) % ds.length; moHong = false; veDuyet(); });
    head.append(truoc, sau); hop.append(head);
    if (!ds.length) { hop.append(el("p", "tl-rong", "Không có video nào chờ bạn duyệt.")); return; }
    const v = ds[vi];
    const body = el("div", "tl-duyet-body");
    const trai = el("div", "tl-so-sanh");
    if (v.co_sheet) { const img = el("img"); img.alt = "Ảnh soi trước / sau"; img.src = `/api/thay-logo/videos/${v.id}/sheet.jpg`; trai.append(img); }
    else trai.append(el("div", "tl-o-trong", "Chưa có ảnh soi"));
    trai.append(el("p", "tl-goi-y", "Kéo vạch so trước/sau từng khung: sắp có — máy chủ mới trả một ảnh soi."));
    const ct = el("div", "tl-chi-tiet");
    ct.append(el("h3", "", T.goc(v)));
    const meta = el("div", "tl-meta");
    meta.append(el("span", "", `Lượt #${v.job_id}`));
    if (v.giay_xu_ly != null) meta.append(el("span", "", `máy làm ${T.phut(v.giay_xu_ly)} phút`));
    ct.append(meta);
    if (v.pct_render != null) {
      const pct = Math.round(v.pct_render);
      const bar = el("div", "tl-phu-bar"); const i = el("i"); i.style.width = pct + "%"; bar.append(i);
      const p = el("p", "tl-phu"); const b = el("b", "", `${pct}% khung`);
      p.append("Logo mới có ở ", b, `. ${100 - pct}% giữ nguyên hình gốc vì máy không chắc vị trí hoặc có phụ đề/chữ chồng lên.`);
      ct.append(bar, p);
    }
    if (T.soiKy(v)) { const c = el("div", "tl-canh-bao"); c.append(el("b", "", "⚠ Nên xem kỹ cả video trước khi dùng"), "Gần chỗ logo có chữ hoặc hình lạ, máy có thể đã che nhầm hoặc sót. Bấm “Xem cả video”."); ct.append(c); }
    const cham = el("div", "tl-cham");
    const dat = el("button", "btn tl-dat"); dat.type = "button"; dat.append("✓ Đạt ", el("kbd", "", "D"));
    const hong = el("button", "btn tl-hong-nut"); hong.type = "button"; hong.setAttribute("aria-expanded", String(moHong)); hong.append("✕ Hỏng ", el("kbd", "", "H"));
    cham.append(dat, hong); ct.append(cham);
    const ly = el("div", "tl-ly-do"); ly.hidden = !moHong;
    const sel = el("select"); sel.setAttribute("aria-label", "Hỏng vì");
    for (const [k, t] of LOAI_LOI) { const o = el("option", "", t); o.value = k; sel.append(o); }
    const note = el("input"); note.type = "text"; note.placeholder = "Ghi chú (giây thứ mấy…)"; note.maxLength = 2000;
    const gui = el("button", "btn danger", "Gửi đánh giá hỏng"); gui.type = "button";
    ly.append(sel, note, gui); ct.append(ly);
    dat.addEventListener("click", () => danhGia(v, { ket_qua: "dat" }));
    hong.addEventListener("click", () => { moHong = !moHong; hong.setAttribute("aria-expanded", String(moHong)); ly.hidden = !moHong; });
    gui.addEventListener("click", () => danhGia(v, { ket_qua: "hong", loai_loi: sel.value, ghi_chu: note.value }));
    const lk = el("div", "tl-link-phu");
    if (v.drive_file_id_ra) lk.append(T.linkDrive(v.drive_file_id_ra, "▶ Xem cả video đã thay"));
    try { const g = v.nguon && JSON.parse(v.nguon).file_id; if (g) lk.append(T.linkDrive(g, "Bản gốc")); } catch (_) { /* nguồn không phải JSON: bỏ link gốc */ }
    ct.append(lk);
    body.append(trai, ct); hop.append(body);
    const phim = el("div", "tl-phim"); phim.append(el("span", "lbl", "Hàng duyệt"));
    ds.forEach((_, i) => { const b = el("button", "tl-phim-o", String(i + 1)); b.type = "button"; b.setAttribute("aria-current", String(i === vi)); b.addEventListener("click", () => { vi = i; moHong = false; veDuyet(); }); phim.append(b); });
    const ph = el("span", "tl-phim-keys"); ph.append(el("kbd", "", "←"), el("kbd", "", "→"), " chuyển ", el("kbd", "", "D"), " Đạt ", el("kbd", "", "H"), " Hỏng");
    phim.append(ph); hop.append(phim);
  }

  function khoiPhai(id, tieuDe, giai, nhom, dong, cls) {
    const k = $(id); k.replaceChildren(); k.className = "panel tl-khoi " + (cls || "");
    const ds = T.locDuoc().filter((v) => T.nhomCua(v) === nhom);
    const h = el("h2", "", tieuDe + " "); h.append(el("span", "so", String(ds.length)));
    k.append(h, el("p", "giai", giai));
    if (!ds.length) { k.append(el("p", "tl-rong", "Không có video nào.")); return; }
    for (const v of ds) {
      const m = el("div", "tl-muc"); m.append(el("div", "ten", T.goc(v)), el("div", "tt", dong(v)));
      k.append(m);
    }
  }

  T.ve.duyet = () => {
    veDuyet();
    khoiPhai("tl-dang-lam", "Máy đang làm", "Bạn không cần làm gì. Xong sẽ tự sang “Chờ bạn duyệt”.", "dang_xu_ly", (v) =>
      v.trang_thai === "cho_agy" && v.cho_agy_tu ? `Chờ agy · ${T.phut(Date.now() / 1000 - v.cho_agy_tu)} phút` : v.trang_thai === "dang_chay" ? "Đang xử lý" : "Đang chuẩn bị");
    khoiPhai("tl-khong-chac", "Máy không chắc", "Máy không tìm ra logo cũ đủ chắc nên giữ nguyên video.", "khong_chac", (v) =>
      "Chưa thay gì — video gốc vẫn dùng được." + (v.so_box != null ? ` agy thấy ${v.so_box} box.` : ""), "warn");
    khoiPhai("tl-khong-lam", "Không làm được", "Video gốc không bị ảnh hưởng.", "loi", (v) => `${v.loi_text || "Lỗi không rõ"} — video gốc không bị ảnh hưởng.`, "bad");
  };

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
    const ds = hangDuyet(); if (!ds.length) return;
    if (e.key === "ArrowRight") { vi = (vi + 1) % ds.length; moHong = false; veDuyet(); }
    else if (e.key === "ArrowLeft") { vi = (vi - 1 + ds.length) % ds.length; moHong = false; veDuyet(); }
    else if (e.key.toLowerCase() === "d" && !T.tat) danhGia(ds[vi], { ket_qua: "dat" });
    else if (e.key.toLowerCase() === "h") { moHong = true; veDuyet(); }
  });
})();
