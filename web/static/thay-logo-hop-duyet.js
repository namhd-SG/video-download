// Hộp "Chờ bạn duyệt" (trước/sau, Đạt/Hỏng) + cột phải (máy đang làm / không chắc / không làm được).
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const LOAI_LOI = [["sot_watermark", "Sót watermark"], ["sai_cho", "Đè sai chỗ"], ["che_phu_de", "Che phụ đề"], ["pha_noi_dung", "Phá nội dung"], ["khac", "Khác"]];
  let vi = 0, moHong = false;

  // Chip tên bộ + ảnh bìa nhỏ; ảnh không tải được thì tự gỡ (không để ô vỡ).
  const chipBo = (v) => el("span", "tl-chip-bo", v.ten_bo || `Lượt #${v.job_id}`);
  function anhBia(v, cls) {
    const img = el("img", cls); img.alt = ""; img.loading = "lazy"; img.src = v.anh_bia;
    img.addEventListener("error", () => img.remove(), { once: true });
    return img;
  }

  // ---- Cặp ảnh trước/sau: vạch kéo (ảnh SAU hiện từ vạch sang phải), giữ Space xem bản gốc, phím [ ] nhích vạch.
  let pos = 50, giuGoc = false;
  const urlKhung = (v, ten) => `/api/thay-logo/videos/${v.id}/khung/${ten}.jpg`;
  const datVach = (cmp) => cmp.style.setProperty("--pos", (giuGoc ? 100 : pos) + "%");
  function veSoSanh(v) {
    const cmp = el("div", "tl-cmp"); cmp.id = "tl-cmp";
    const t = el("img", "tl-cmp-t"), sau = el("div", "tl-cmp-sau"), s = el("img");
    t.alt = "Trước"; s.alt = "Sau"; t.src = urlKhung(v, "truoc"); s.src = urlKhung(v, "sau"); sau.append(s);
    const vach = el("div", "tl-cmp-vach"), num = el("div", "tl-cmp-num", "⇆"); num.setAttribute("aria-hidden", "true");
    const range = el("input"); range.type = "range"; range.min = "0"; range.max = "100"; range.value = String(pos); range.id = "tl-truot";
    range.setAttribute("aria-label", "Kéo để so trước và sau (phím [ và ])");
    range.addEventListener("input", () => { pos = Number(range.value); datVach(cmp); });
    range.addEventListener("change", () => range.blur());  // thả chuột xong trả phím ← → về việc chuyển video
    cmp.append(t, sau, el("span", "tl-cmp-nhan t", "TRƯỚC"), el("span", "tl-cmp-nhan s", "SAU"), vach, num, range);
    datVach(cmp);
    return cmp;
  }
  // Phóng to vùng logo: cắt đúng vùng `box_logo` (tỉ lệ 0–1) bằng định vị ảnh trong ô tỉ lệ 2:1, không thêm thư viện.
  function veOZoom(v, ten, nhan, cls) {
    const fig = el("figure"), o = el("div", "tl-zoom-o"), img = el("img"); img.alt = nhan; img.hidden = true;
    img.addEventListener("load", () => {
      const W = img.naturalWidth, H = img.naturalHeight, b = v.box_logo; if (!W || !H) return;
      const rong = Math.min(1, Math.max(b.w * 2.2, 0.18)), cao = Math.min(1, rong * W / H / 2);  // vùng hiển thị (tỉ lệ ảnh), ô 2:1
      const rx = Math.min(1 - rong, Math.max(0, b.x + b.w / 2 - rong / 2)), ry = Math.min(1 - cao, Math.max(0, b.y + b.h / 2 - cao / 2));
      img.style.width = (100 / rong) + "%"; img.style.left = (-rx / rong * 100) + "%"; img.style.top = (-ry / cao * 100) + "%"; img.hidden = false;
    }, { once: true });
    img.addEventListener("error", () => o.classList.add("hong"), { once: true });
    img.src = urlKhung(v, ten); o.append(img);
    const cap = el("figcaption"); cap.append(el("i", cls), nhan); fig.append(o, cap);
    return fig;
  }
  function veZoom(v) {
    const z = el("div", "tl-zoom"); z.append(veOZoom(v, "truoc", "Trước — logo cũ", "dot-t"), veOZoom(v, "sau", "Sau — logo của bạn", "dot-s"));
    const w = el("div", "tl-zoom-hop"); w.append(el("div", "tl-zoom-lbl", "Phóng to vùng logo"), z);
    return w;
  }

  const hangDuyet = () => T.locDuoc().filter((v) => T.nhomCua(v) === "cho_duyet");

  const LOI_GUI = { 403: "Bạn không đánh giá được video này.", 409: "Video này chưa thay xong nên chưa đánh giá được.", 400: "Đánh giá chưa hợp lệ — chọn lý do rồi gửi lại." };
  let dangDanhGia = false;  // đang gửi một đánh giá ⇒ phím D/H lặp và bấm nút lặp KHÔNG được gửi thêm (cùng video bị chấm hai lần)
  async function danhGia(v, body) {
    if (dangDanhGia) return;
    dangDanhGia = true; T.loi("");
    try {
      const r = await T.goi(`/api/thay-logo/videos/${v.id}/danh-gia`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) { T.loi(LOI_GUI[r.status] || "Chưa gửi được đánh giá. Thử lại sau ít phút."); return; }
      // Bỏ video khỏi hàng chờ NGAY (không đợi tải lại): `daCham` giữ kết quả để một phản hồi tải đã bay trước lúc chấm không đưa nó về.
      T.daCham.set(v.id, body.ket_qua); v.danh_gia = body.ket_qua;
      const x = T.videos.find((a) => a.id === v.id); if (x) x.danh_gia = body.ket_qua;
      moHong = false; T.veLai();
      window.TL_taiLai();
    } catch (e) {
      if (!e || e.message !== "het_phien") T.loi("Chưa gửi được đánh giá — kiểm tra mạng rồi bấm lại.");  // hết phiên đã có thông báo riêng
    } finally { dangDanhGia = false; }
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
    if (!ds.length) { hop.append(el("p", "tl-rong", T.dangTaiLoc ? "Đang tải…" : "Không có video nào chờ bạn duyệt.")); return; }
    const v = ds[vi];
    const body = el("div", "tl-duyet-body");
    const trai = el("div", "tl-so-sanh");
    const coCap = !!v.co_truoc_sau;
    if (coCap) { trai.append(veSoSanh(v), el("p", "tl-goi-y", "Kéo vạch để so · giữ Space xem bản gốc · [ ] nhích vạch")); }
    else if (v.co_sheet) { const img = el("img"); img.alt = "Ảnh soi trước / sau"; img.src = `/api/thay-logo/videos/${v.id}/sheet.jpg`; trai.append(img, el("p", "tl-goi-y", "Ảnh soi ghép trước/sau của máy.")); }
    else trai.append(el("div", "tl-o-trong", "Chưa có ảnh soi"));
    const ct = el("div", "tl-chi-tiet");
    const tieu = el("div", "tl-duyet-tieu"), chu = el("div", "tl-duyet-tieu-chu");
    chu.append(chipBo(v), el("h3", "", T.tenVideo(v)));
    if (v.anh_bia) tieu.append(anhBia(v, "tl-bia-nho"));
    tieu.append(chu); ct.append(tieu);
    const meta = el("div", "tl-meta");
    if (v.giay_xu_ly != null) meta.append(el("span", "", `máy làm ${T.phut(v.giay_xu_ly)} phút`));
    ct.append(meta);
    if (coCap && v.box_logo) ct.append(veZoom(v));
    if (v.pct_render != null) {
      const pct = Math.max(0, Math.min(100, Math.round(v.pct_render)));
      const bar = el("div", "tl-phu-bar"); const i = el("i"); i.style.width = pct + "%"; bar.append(i);
      const p = el("p", "tl-phu"); const b = el("b", "", T.phanSo(pct));
      p.append("Logo mới có ở ", b, ". Đoạn còn lại giữ hình gốc vì máy không thấy logo cũ ở đó hoặc có phụ đề/chữ chồng lên.");
      ct.append(bar, p);
    }
    if (T.soiKy(v)) { const c = el("div", "tl-canh-bao"); c.append(el("b", "", "⚠ Nên xem kỹ cả video trước khi dùng"), "Gần chỗ logo có chữ hoặc hình lạ, máy có thể đã che nhầm hoặc sót. Bấm “Xem cả video”."); ct.append(c); }
    const cham = el("div", "tl-cham");
    const dat = el("button", "btn tl-dat"); dat.type = "button"; dat.disabled = T.tat; dat.append("✓ Đạt ", el("kbd", "", "D"));
    const hong = el("button", "btn tl-hong-nut"); hong.type = "button"; hong.setAttribute("aria-expanded", String(moHong)); hong.append("✕ Hỏng ", el("kbd", "", "H"));
    cham.append(dat, hong); ct.append(cham);
    const ly = el("div", "tl-ly-do"); ly.hidden = !moHong;
    const sel = el("select"); sel.setAttribute("aria-label", "Hỏng vì");
    for (const [k, t] of LOAI_LOI) { const o = el("option", "", t); o.value = k; sel.append(o); }
    const note = el("input"); note.type = "text"; note.placeholder = "Ghi chú (giây thứ mấy…)"; note.maxLength = 2000;
    const gui = el("button", "btn danger", "Gửi đánh giá hỏng"); gui.type = "button";
    ly.append(sel, note, gui); ct.append(ly);
    dat.addEventListener("click", () => { if (!T.tat) danhGia(v, { ket_qua: "dat" }); });  // tính năng tắt: chuột bị chặn như phím D
    hong.addEventListener("click", () => { moHong = !moHong; hong.setAttribute("aria-expanded", String(moHong)); ly.hidden = !moHong; });
    gui.addEventListener("click", () => danhGia(v, { ket_qua: "hong", loai_loi: sel.value, ghi_chu: note.value }));
    const lk = el("div", "tl-link-phu");
    if (v.drive_file_id_ra) lk.append(T.linkDrive(v.drive_file_id_ra, "▶ Xem cả video đã thay"));
    try { const ng = v.nguon && JSON.parse(v.nguon), g = ng && ng.file_id; if (g) lk.append(T.linkDrive(g, ng.kieu === "vao_bo" ? "Bản trong bộ" : "Bản gốc")); } catch (_) { /* nguồn không phải JSON: bỏ link gốc */ }
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
    if (!ds.length) { k.append(el("p", "tl-rong", T.dangTaiLoc ? "Đang tải…" : "Không có video nào.")); return; }
    for (const v of ds) {
      const m = el("div", "tl-muc");
      if (v.anh_bia) m.append(anhBia(v, "tl-bia-nho"));
      const than = el("div", "tl-muc-than"); than.append(el("div", "ten", T.tenVideo(v)), chipBo(v), el("div", "tl-tt", dong(v)));
      m.append(than);
      k.append(m);
    }
  }

  T.ve.duyet = () => {
    veDuyet();
    khoiPhai("tl-dang-lam", "Máy đang làm", "Bạn không cần làm gì. Xong sẽ tự sang “Chờ bạn duyệt”.", "dang_xu_ly", (v) =>
      v.trang_thai === "cho_agy" && v.cho_agy_tu ? `Máy đang tìm chỗ logo cũ · đã ${T.phut(Date.now() / 1000 - v.cho_agy_tu)} phút` : v.trang_thai === "dang_chay" ? "Đang thay logo" : "Đang xếp hàng");
    khoiPhai("tl-khong-chac", "Máy không chắc", "Máy không tìm ra logo cũ đủ chắc nên giữ nguyên video.", "khong_chac", (v) =>
      (v.so_box > 0 ? "Máy không chắc vị trí" : "Máy không thấy logo") + " — chưa thay gì, video gốc vẫn dùng được.", "warn");
    khoiPhai("tl-khong-lam", "Không làm được", "Video gốc không bị ảnh hưởng.", "loi", (v) => T.loiText(v.loi_text), "bad");  // tiêu đề khối đã nói "video gốc không bị ảnh hưởng"
  };

  // Space giữ = xem bản gốc (nhả = trả vạch); [ ] nhích vạch 5%. Không chặn khi đang gõ chữ / bấm nút / chọn trong ô chọn.
  const dangNhapChu = (t) => /^(TEXTAREA|SELECT|BUTTON|A)$/.test(t.tagName || "") || (t.tagName === "INPUT" && t.type !== "range");
  const capNhatVach = () => { const c = $("tl-cmp"); if (c) { datVach(c); const r = $("tl-truot"); if (r) r.value = String(pos); } };
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || dangNhapChu(e.target) || !$("tl-cmp")) return;
    if (e.key === " ") { e.preventDefault(); if (!giuGoc) { giuGoc = true; capNhatVach(); } }
    else if (e.key === "[" || e.key === "]") { pos = Math.min(100, Math.max(0, pos + (e.key === "]" ? 5 : -5))); capNhatVach(); }
  });
  document.addEventListener("keyup", (e) => { if (e.key === " " && giuGoc) { giuGoc = false; capNhatVach(); } });
  window.addEventListener("blur", () => { if (giuGoc) { giuGoc = false; capNhatVach(); } });  // đổi cửa sổ khi đang giữ Space ⇒ không kẹt ở bản gốc

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
    const ds = hangDuyet(); if (!ds.length) return;
    if (e.key === "ArrowRight") { vi = (vi + 1) % ds.length; moHong = false; veDuyet(); }
    else if (e.key === "ArrowLeft") { vi = (vi - 1 + ds.length) % ds.length; moHong = false; veDuyet(); }
    else if (e.key.toLowerCase() === "d" && !T.tat) danhGia(ds[vi], { ket_qua: "dat" });
    else if (e.key.toLowerCase() === "h") { moHong = true; veDuyet(); }
  });
})();
