// Màn Sửa (pha 1b bước 3, phương án A "khoanh chỗ lộ") — mở trong trang Lô khi URL có `?sua=<vid>&khung=<k>`.
// Người kéo chuột khoanh phần logo cũ còn lộ (trên ảnh lớn HOẶC ô phóng to) ⇒ `POST /khoanh` mỗi ô; máy tự gán mã lỗi.
// Mọi ô giữ theo toạ độ khung GỐC (px của video); hai lớp vẽ chỉ quy đổi để hiển thị ⇒ khoanh ở đâu cũng ra cùng một vùng.
// Thiết kế + chốt của ĐP: plans/261023-1149-thay-logo-cai-to-luong-khoanh/phase-1b-3-man-sua.md. Chữ dữ liệu vào bằng textContent.
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const CANH_TOI_THIEU_PX = 4;      // = khoanh.CANH_TOI_THIEU_PX: ô nhỏ hơn máy chủ coi là bấm nhầm (400)
  const NOI_TOI_THIEU_PX = 24;      // = soi_nhanh.NOI_TOI_THIEU_PX
  const TI_LE_XAM = [0.1, 0.5, 0.9]; // = soi_nhanh.TI_LE_KHUNG_XAM: chỗ cần xem của video máy chưa đè gì
  const MAU_LOI = {  // mã máy tự gán (khoanh.MAU_LOI) ⇒ lời thường; người không chọn mã
    may_khong_thay: "máy chưa thấy logo này", che_nham: "máy đè nhầm — giữ hình gốc", lo_mep: "lộ mép ô máy đè",
    de_lech_cho: "máy đè lệch chỗ", lo_do_cong_chan: "chỗ này máy cố ý không đè (cổng an toàn chặn)", lo_mat_dau: "máy mất dấu logo ở đây",
  };

  // Vùng phóng to 4:3 quanh box, trượt vào trong khung — CÙNG công thức soi_nhanh.cat_quanh để ô phóng to giống ảnh soi ở màn Lô.
  function catQuanh(box, W, H) {
    const [x, y, w, h] = box.map((v) => Math.trunc(v));
    let cw = w + 2 * Math.max(Math.floor(w / 2), NOI_TOI_THIEU_PX), ch = h + 2 * Math.max(Math.floor(h / 2), NOI_TOI_THIEU_PX);
    if (cw * 3 >= ch * 4) ch = Math.ceil(cw * 3 / 4); else cw = Math.ceil(ch * 4 / 3);
    if (cw > W) { cw = W; ch = Math.floor(W * 3 / 4); }
    if (ch > H) { cw = Math.floor(H * 4 / 3); ch = H; }
    const x0 = Math.min(Math.max(0, x + Math.floor(w / 2) - Math.floor(cw / 2)), W - cw);
    const y0 = Math.min(Math.max(0, y + Math.floor(h / 2) - Math.floor(ch / 2)), H - ch);
    return [x0, y0, cw, ch];
  }

  let S = null;  // trạng thái màn Sửa của MỘT video
  const L = () => window.TL_LO;

  function choCanXem(v, dai) {
    if (v.trang_thai === "xong" && dai && !dai.loi) return dai.doan.map((d) => ({ khung: d.tu, den: d.den, loai: d.loai }));
    const n = (dai && dai.so_khung) || 0;
    return TI_LE_XAM.map((t) => ({ khung: Math.min(n - 1, Math.floor(n * t)), den: null, loai: "xam" })).filter((c) => c.khung >= 0);
  }

  // ---------------------------------------------------------------- vẽ ô
  function oTrai(vung) {  // vung px gốc ⇒ phần trăm trên ảnh lớn
    const [x, y, w, h] = vung, s = el("span");
    Object.assign(s.style, { left: `${(x / S.W) * 100}%`, top: `${(y / S.H) * 100}%`, width: `${(w / S.W) * 100}%`, height: `${(h / S.H) * 100}%` });
    return s;
  }
  function phepZoom() {  // vùng gốc đang phóng ⇒ hệ số + lề để quy đổi hai chiều
    const r = $("sua-zoom").getBoundingClientRect(), [cx, cy, cw, ch] = S.zoom;
    const s = Math.min(r.width / cw, r.height / ch);
    return { r, s, ox: (r.width - cw * s) / 2 - cx * s, oy: (r.height - ch * s) / 2 - cy * s };
  }
  function oZoom(vung, z) {
    const [x, y, w, h] = vung, s = el("span");
    Object.assign(s.style, { left: `${x * z.s + z.ox}px`, top: `${y * z.s + z.oy}px`, width: `${w * z.s}px`, height: `${h * z.s}px` });
    return s;
  }
  function veLop() {
    const trai = $("sua-lop-trai"), zoom = $("sua-lop-zoom"), z = phepZoom();
    trai.replaceChildren(); zoom.replaceChildren();
    const them = (vung, lop) => { const a = oTrai(vung), b = oZoom(vung, z); a.className = b.className = lop; trai.append(a); zoom.append(b); };
    if (S.box) them(S.box, "sua-o sua-o-may");
    for (const o of S.daLuu) if (o.khung === S.khung && o.vung) them(o.vung, "sua-o sua-o-luu");
    for (const o of S.cho) them(o, "sua-o sua-o-cho");
    if (S.dang) them(S.dang, "sua-o sua-o-cho");
    const img = $("sua-zoom-anh");
    Object.assign(img.style, { width: `${S.W * z.s}px`, left: `${z.ox}px`, top: `${z.oy}px` });
    capNhatNut();
  }

  // ---------------------------------------------------------------- kéo chuột khoanh (trên ảnh lớn hoặc ô phóng to)
  function nghe(lop, quyDoi) {
    lop.addEventListener("pointerdown", (e) => {
      e.preventDefault(); lop.setPointerCapture(e.pointerId);
      const a = quyDoi(e);
      const keo = (ev) => { const b = quyDoi(ev); S.dang = chuNhat(a, b); veLop(); };
      const tha = (ev) => {
        lop.removeEventListener("pointermove", keo); lop.removeEventListener("pointerup", tha);
        const o = chuNhat(a, quyDoi(ev)); S.dang = null;
        if (o[2] >= CANH_TOI_THIEU_PX && o[3] >= CANH_TOI_THIEU_PX) S.cho.push(o);
        veLop();
      };
      lop.addEventListener("pointermove", keo); lop.addEventListener("pointerup", tha);
    });
  }
  const kep = (v, max) => Math.min(max, Math.max(0, v));
  function chuNhat([x1, y1], [x2, y2]) {
    const x = kep(Math.min(x1, x2), S.W), y = kep(Math.min(y1, y2), S.H);
    return [Math.round(x), Math.round(y), Math.round(kep(Math.max(x1, x2), S.W) - x), Math.round(kep(Math.max(y1, y2), S.H) - y)];
  }
  const tuTrai = (e) => { const r = $("sua-lop-trai").getBoundingClientRect(); return [((e.clientX - r.left) / r.width) * S.W, ((e.clientY - r.top) / r.height) * S.H]; };
  const tuZoom = (e) => { const z = phepZoom(); return [(e.clientX - z.r.left - z.ox) / z.s, (e.clientY - z.r.top - z.oy) / z.s]; };

  // ---------------------------------------------------------------- tới một khung
  async function denKhung(k) {
    const n = S.dai.so_khung || 1;
    S.khung = kep(Math.round(k), n - 1);
    const u = new URL(location.href); u.searchParams.set("khung", S.khung); history.replaceState(null, "", u);
    veAnh(); veTieuDe();  // tiêu đề theo khung mới NGAY — không chờ box
    const lan = ++S.lan;  // J/L bấm liên tục: chỉ nhận box của lần gọi MỚI nhất
    let box = null;
    try { box = (await L().json(L().api(S.v.id, `box/${S.khung}`))).box_may; } catch (e) { box = null; }
    if (lan !== S.lan) return;
    S.box = box;
    S.zoom = box ? catQuanh(box, S.W, S.H) : [0, 0, S.W, S.H];
    $("sua-zoom-chu").textContent = box ? "Phóng to quanh chỗ cần sửa — vàng đứt = ô máy đã đè · đỏ = chỗ bạn khoanh"
      : "Ở khung này máy không đè gì — khoanh logo cũ trên ảnh lớn hoặc trong ô này.";
    veTieuDe(); veLop();
  }
  function veAnh() {
    const ban = S.xemGoc || S.v.trang_thai !== "xong" ? "goc" : "ra";
    const src = L().api(S.v.id, `khung-tai/${S.khung}?ban=${ban}`);
    $("sua-anh").src = src; $("sua-zoom-anh").src = src;
    $("sua-ban").textContent = ban === "goc" ? "đang xem: BẢN GỐC" : "đang xem: bản đã thay";
    const kim = $("sua-kim"); kim.style.left = `${(S.khung / (S.dai.so_khung || 1)) * 100}%`;
    $("sua-gio").textContent = `khung ${S.khung} · ${L().mmss(L().giayCua(S.dai, S.khung))}`;
  }
  function choHienTai() { return S.choXem.find((c) => S.khung >= c.khung && S.khung <= (c.den == null ? c.khung : c.den)); }
  function veTieuDe() {
    const c = choHienTai(), ten = T.tenVideo(S.v), gio = L().mmss(L().giayCua(S.dai, S.khung));
    const loai = c ? { do: "chỗ đỏ", vang: "chỗ vàng", xam: "chỗ cần xem" }[c.loai] : `khung ${S.khung}`;
    $("sua-tieu-de").textContent = `${ten} — ${loai} ${gio}`;
    $("sua-goi-y").textContent = !c ? "Không nằm trong chỗ máy đánh dấu. Shift+L sang chỗ kế."
      : c.loai === "do" ? "Máy biết logo cũ còn lộ ở đoạn này. Khoanh phần còn lộ ở ảnh trái (hoặc trong ô phóng to)."
      : c.loai === "vang" ? "Máy cảnh báo ở đoạn này (đè khi cổng an toàn chặn). Còn thấy logo cũ thì khoanh; máy đè nhầm thì Giữ hình gốc."
      : (T.lyDoDeHieu(S.v.ly_do_may) || "Máy chưa thay gì ở video này.") + " Thấy logo cũ thì khoanh — mỗi chỗ một ô.";
  }
  function sangCho(huong) {
    const ds = S.choXem.map((c) => c.khung);
    const k = huong > 0 ? ds.find((x) => x > S.khung) : [...ds].reverse().find((x) => x < S.khung);
    if (k == null) { if (huong > 0) { $("sua-xong").focus(); $("sua-trang").textContent = "Hết chỗ cần xem — bấm nút Xong bên dưới."; } return; }
    denKhung(k);
  }

  // ---------------------------------------------------------------- lưu
  async function luu(than) {
    L().baoLoi("");
    const r = await L().json(L().api(S.v.id, "khoanh"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(than) });
    return r;
  }
  async function luuKhoanh() {
    const nut = $("sua-luu"); nut.disabled = true;
    try {
      while (S.cho.length) {
        const o = S.cho[0];
        const r = await luu({ khung: S.khung, vung: { x: o[0] / S.W, y: o[1] / S.H, w: o[2] / S.W, h: o[3] / S.H } });
        S.daLuu.push({ khung: S.khung, vung: o, mau_loi: r.mau_loi }); S.cho.shift();
      }
      veTrang();
    } catch (e) { L().baoLoi("Không lưu được chỗ khoanh, thử lại."); }
    veLop();
  }
  async function giuGoc() {
    try { const r = await luu({ khung: S.khung, vung: null, giu_goc: true }); S.daLuu.push({ khung: S.khung, vung: null, mau_loi: r.mau_loi }); veTrang(); }
    catch (e) { L().baoLoi("Không lưu được, thử lại."); }
    veLop();
  }
  function veTrang() {
    const p = $("sua-trang");
    const truoc = S.dai.so_ca_cho > 0 ? `Video này đã có ${S.dai.so_ca_cho} chỗ khoanh từ trước, đang chờ sửa. ` : "";
    if (!S.daLuu.length) { p.textContent = truoc + "Lượt này chưa khoanh chỗ nào."; return; }
    const cuoi = S.daLuu[S.daLuu.length - 1];
    p.textContent = `Đã lưu ${S.daLuu.length} chỗ. Chỗ vừa lưu (khung ${cuoi.khung}): máy ghi "${MAU_LOI[cuoi.mau_loi] || cuoi.mau_loi}".`;
  }
  function capNhatNut() {
    $("sua-luu").disabled = !S.cho.length;
    $("sua-giu-goc").disabled = !S.box || S.v.trang_thai !== "xong";
    const x = $("sua-xong");
    // Nút cuối GHI RÕ hành động (ĐP chốt): chỉ "đánh Đạt" khi video máy đã xong, KHÔNG còn ca khoanh chờ sửa từ lượt mở trước
    // (`/dai` so_ca_cho — mở lại trang sau khi khoanh) và lượt này cũng chưa lưu ô nào.
    S.danhDat = S.v.trang_thai === "xong" && !S.daLuu.length && !(S.dai.so_ca_cho > 0);
    x.textContent = S.danhDat ? "Xong — đánh Đạt" : "Xong — về Lô";
    x.disabled = S.cho.length > 0;
    x.title = S.cho.length ? "Còn ô chưa lưu: bấm Lưu chỗ khoanh hoặc Esc để bỏ." : "";
  }
  async function xong() {
    const ve = () => { const u = new URL(location.href); u.searchParams.delete("sua"); u.searchParams.delete("khung"); location.assign(u); };
    if (!S.danhDat) { ve(); return; }
    try {
      await L().json(L().api(S.v.id, "danh-gia"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ket_qua: "dat" }) });
      ve();
    } catch (e) { L().baoLoi("Không ghi được Đạt, thử lại."); }
  }

  // ---------------------------------------------------------------- phím tắt
  function phim(e) {
    if (!S || e.target.closest("input, select, textarea")) return;
    if (e.code === "KeyJ" || e.code === "KeyL") {
      e.preventDefault();
      const h = e.code === "KeyL" ? 1 : -1;
      if (e.shiftKey) sangCho(h); else denKhung(S.khung + h);
    } else if (e.code === "Space") {
      e.preventDefault();
      if (!e.repeat && S.v.trang_thai === "xong" && !S.xemGoc) { S.xemGoc = true; veAnh(); }
    } else if (e.code === "Escape") { S.cho = []; S.dang = null; veLop(); }
    else if (e.code === "Enter" && !e.target.closest("button")) { e.preventDefault(); sangCho(1); }  // sang chỗ kế, KHÔNG lưu
  }
  function thaPhim(e) { if (S && e.code === "Space" && S.xemGoc) { S.xemGoc = false; veAnh(); } }

  // ---------------------------------------------------------------- dựng màn
  function nut(id, chu, lop) { const b = el("button", lop || "lo-nut", chu); b.type = "button"; b.id = id; return b; }

  async function mo(v, dai, jobId) {
    const hop = $("lo-sua");
    if (!dai || dai.loi || !dai.so_khung || !dai.kho) { hop.hidden = false; hop.replaceChildren(el("p", "lo-phu", "Không đọc được dữ liệu video này để sửa.")); return; }
    const [W, H] = dai.kho.split("x").map(Number);
    S = { v, dai, jobId, W, H, khung: 0, box: null, zoom: [0, 0, W, H], cho: [], daLuu: [], dang: null, lan: 0, xemGoc: false, danhDat: false };
    S.choXem = choCanXem(v, dai);
    const ve = el("a", "sua-ve", "← Về Lô"); const u = new URL(location.href); u.searchParams.delete("sua"); u.searchParams.delete("khung"); ve.href = u;

    const anh = el("img"); anh.id = "sua-anh"; anh.alt = "khung video";
    // Không trích được khung (video đã dọn / khung hỏng) ⇒ nói ra, đừng để ô ảnh trống không lời.
    anh.addEventListener("error", () => L().baoLoi("Không lấy được ảnh khung này (video có thể đã dọn khỏi máy)."));
    anh.addEventListener("load", () => { if ($("lo-loi").textContent.startsWith("Không lấy được ảnh")) L().baoLoi(""); });
    const lopTrai = el("div", "sua-lop"); lopTrai.id = "sua-lop-trai";
    const khung = el("div", "sua-khung"); khung.append(anh, lopTrai);
    const dai2 = L().veDai(v, dai); dai2.classList.add("sua-dai");
    const kim = el("span", "sua-kim"); kim.id = "sua-kim"; dai2.append(kim);
    dai2.addEventListener("click", (e) => { const r = dai2.getBoundingClientRect(); denKhung(((e.clientX - r.left) / r.width) * dai.so_khung); });
    const gio = el("p", "lo-phu"); gio.id = "sua-gio";
    const ban = el("p", "lo-phu"); ban.id = "sua-ban";
    const trai = el("div", "sua-trai"); trai.append(khung, dai2, gio, ban);

    const zAnh = el("img"); zAnh.id = "sua-zoom-anh"; zAnh.alt = "";
    const lopZ = el("div", "sua-lop"); lopZ.id = "sua-lop-zoom";
    const zoom = el("div", "sua-zoom"); zoom.id = "sua-zoom"; zoom.append(zAnh, lopZ);
    const zChu = el("p", "lo-phu"); zChu.id = "sua-zoom-chu";
    const buoc = el("ol", "sua-buoc");
    for (const s of ["Kéo chuột trên ảnh để khoanh phần logo cũ còn lộ (có thể khoanh nhiều chỗ).", "Bấm \"Lưu chỗ khoanh\" — máy ghi lại để học và sửa ở bước sau.",
      "Sang chỗ kế (Shift+L), hết chỗ thì bấm Xong."]) buoc.append(el("li", "", s));
    const hang = el("div", "sua-nut");
    const xem2 = nut("sua-xem-2", "Xem 2 giây"); xem2.disabled = true; xem2.title = "Có ở bước sau (phát video) — hiện dùng J/L để xem từng khung.";
    hang.append(nut("sua-luu", "Lưu chỗ khoanh", "lo-nut lo-nut-chinh"), xem2, nut("sua-giu-goc", "Giữ hình gốc đoạn này"), nut("sua-khoanh-lai", "Khoanh lại"));
    const trang = el("p", "sua-trang"); trang.id = "sua-trang";
    const tieu = el("h2", "sua-tieu-de"); tieu.id = "sua-tieu-de";
    const goiY = el("p", "lo-phu"); goiY.id = "sua-goi-y";
    const phai = el("div", "sua-phai"); phai.append(tieu, goiY, zoom, zChu, buoc, hang, trang);
    const than = el("div", "sua-than"); than.append(trai, phai);
    const phimTat = el("p", "sua-phim");
    phimTat.append(el("strong", "", "Phím tắt "), "J/L lùi/tới 1 khung · Shift+J/L chỗ cần xem trước/sau · Space giữ để xem bản gốc · Enter sang chỗ kế · Esc khoanh lại");
    const cuoi = el("div", "sua-cuoi"); cuoi.append(nut("sua-xong", "Xong — về Lô", "lo-nut"));
    hop.replaceChildren(ve, than, phimTat, cuoi); hop.hidden = false;

    nghe(lopTrai, tuTrai); nghe(lopZ, tuZoom);
    $("sua-luu").addEventListener("click", luuKhoanh);
    $("sua-giu-goc").addEventListener("click", giuGoc);
    $("sua-khoanh-lai").addEventListener("click", () => { S.cho = []; veLop(); });
    $("sua-xong").addEventListener("click", xong);
    document.addEventListener("keydown", phim); document.addEventListener("keyup", thaPhim);
    window.addEventListener("resize", () => S && veLop());
    veTrang();
    const q = new URLSearchParams(location.search).get("khung"), k = q === null || q === "" ? NaN : Number(q);
    await denKhung(Number.isFinite(k) ? k : (S.choXem[0] ? S.choXem[0].khung : 0));
  }

  window.TL_SUA = { mo, catQuanh, trangThai: () => S };
})();
