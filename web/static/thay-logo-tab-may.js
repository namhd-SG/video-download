// Tab "Tải từ máy": chọn / kéo-thả video → máy chủ cấp URL phiên resumable của Google Drive → trình duyệt PUT thẳng từng khúc 8 MiB lên Google
// (KHÔNG gửi Authorization/cookie) → máy chủ đối chiếu file (…/xong) → file được tick sẵn; "Thay logo" gửi `may_file_ids`.
// Đăng ký vào window.TL_TAB_NGUON theo hợp đồng ở thay-logo-chung.js: `ve(hop, T)` idempotent, tự đọc T.tat. Cờ tính năng: GET /tai-len/bat —
// 404 ⇒ tab ẩn hẳn (giống cách tab "Đã vào bộ" đọc cờ ở thay-logo-the-bo.js); lỗi tạm ⇒ hỏi lại sau.
// URL phiên = quyền ghi vào thư mục đầu vào ⇒ chỉ nằm trong biến của closure này: không storage, không console, không vào chữ hiện cho người dùng.
// Mọi chữ từ máy chủ / tên file vào bằng textContent — không innerHTML.
(() => {
  "use strict";
  const T = window.TL;
  if (!T) return;
  const { el } = T;

  const MB = 1048576;
  const TRAN_BYTE = 500 * MB;            // 524288000 — khớp trần của máy chủ
  const KHUC = 8 * MB;                   // bội của 256 KiB (luật của Google)
  const SONG_SONG = 3;
  const THU_TOI_DA = 5;                  // số lần thử liên tiếp (mỗi khúc / mỗi bước) trước khi báo lỗi cho người dùng
  const MIME_TU_DUOI = { mp4: "video/mp4", mov: "video/quicktime" };  // trình duyệt đôi khi để trống `file.type`
  const lui = (n) => new Promise((xong) => setTimeout(xong, Math.min(8000, 250 * 2 ** n)));  // 500ms, 1s, 2s, 4s, 8s

  let hop = null, vungDs = null, hen = null;
  let co = null;                         // null = chưa biết · true = bật · false = tắt (404)
  let tran = 100;                        // số video tối đa một lượt (từ /tinh-nang)
  let thongBao = "", tuSo = 0;
  const muc = [];                        // các file người dùng đã đưa vào (giữ khi đổi tab)
  let daGui = new Set();                 // file_id đã đưa vào POST /jobs gần nhất (thành công ⇒ khối nhập xoá chọn ⇒ ta bỏ dòng)

  // ---------------------------------------------------------------- cờ + trần
  T.goi("/tinh-nang").then((r) => (r.ok ? r.json() : null)).then((j) => { if (j && j.thay_logo_video_mot_luot > 0) tran = j.thay_logo_video_mot_luot; }).catch(() => {});

  function datCo(v) {
    co = v;
    document.body.classList.toggle("tl-co-may", v === true);   // CSS ẩn nhãn tab khi chưa bật (khối nhập vẽ lại nhãn tab nên không tự gắn thuộc tính lên nút)
    veTat();
  }
  async function hoiCo(lan = 0) {
    try {
      const r = await T.goi("/api/thay-logo/tai-len/bat");
      if (r.ok) return datCo(true);
      if (r.status === 404) return datCo(false);
    } catch (e) { if (e && e.message === "het_phien") return; }
    if (lan < 6) setTimeout(() => hoiCo(lan + 1), 5000 * (lan + 1));   // lỗi tạm ⇒ thử lại sau (tab vẫn ẩn)
  }
  hoiCo();

  // ---------------------------------------------------------------- kiểm file ở trình duyệt (máy chủ vẫn là cổng thật)
  const duoiTen = (ten) => (String(ten).split(".").pop() || "").toLowerCase();
  const mimeCua = (f) => (f.type && f.type.startsWith("video/") ? f.type : MIME_TU_DUOI[duoiTen(f.name)] || "");
  const mb = (n) => (n >= MB ? `${Math.round(n / MB)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  // Trả câu lỗi (chuỗi, "" = hợp lệ). Nhận bất kỳ vật có {name, size, type} nên test gọi được với file giả khai size lớn.
  function kiemFile(f) {
    if (!mimeCua(f)) return "Không phải video. Chỉ nhận file mp4 hoặc mov.";
    if (!(f.size > 0)) return "File rỗng — chọn lại file khác.";
    if (f.size > TRAN_BYTE) return `File ${mb(f.size)} — quá 500 MB. Hãy cắt ngắn hoặc nén lại rồi tải lại.`;
    return "";
  }
  T.tabMay = { kiemFile };

  // ---------------------------------------------------------------- một lỗi có chữ cho người dùng; `thuLai` = bấm "Thử lại" có ích
  class LoiHien extends Error { constructor(chu, thuLai, phienMoi) { super(chu); this.thuLai = !!thuLai; this.phienMoi = !!phienMoi; } }
  class LoiMang extends Error {}          // đứt mạng / quá giờ / bị chặn đọc phản hồi — hỏi lại Google trước khi kết luận
  class LoiHuy extends Error {}

  const chiTiet = async (r) => { try { const d = (await r.json()).detail; return typeof d === "string" ? d : ""; } catch (_) { return ""; } };

  // PUT một khúc (hoặc câu hỏi `*/size`) thẳng Google. XHR vì cần tiến độ; mặc định không gửi cookie/Authorization chéo miền.
  function put(m, dauRange, than) {
    return new Promise((xong, hong) => {
      const x = new XMLHttpRequest();
      m.xhr = x;
      x.open("PUT", m.url);
      x.setRequestHeader("Content-Range", dauRange);
      x.timeout = 180000;
      if (than && than.size) x.upload.onprogress = (e) => { m.dangGui = Math.min(e.loaded, than.size); dat(); };
      x.onload = () => { m.xhr = null; m.dangGui = 0; xong({ status: x.status, range: x.getResponseHeader("Range"), text: x.responseText }); };
      x.onerror = x.ontimeout = () => { m.xhr = null; m.dangGui = 0; hong(new LoiMang()); };
      x.onabort = () => { m.xhr = null; m.dangGui = 0; hong(new LoiHuy()); };
      x.send(than || null);
    });
  }

  const docId = (r) => { try { const id = JSON.parse(r.text).id; if (typeof id === "string" && T.IDRE.test(id)) return id; } catch (_) { /* thân không phải JSON */ } throw new LoiHien("Google không trả mã file — thử tải lại file này.", true); };
  // Byte kế tiếp sau một 308: ĐỌC header `Range` (bytes=0-N ⇒ N+1); không có `Range` ⇒ Google chưa nhận byte nào ⇒ 0. Không tự cộng offset.
  function byteKe(r) {
    if (!r.range) return 0;
    const k = /^bytes=0-(\d+)$/.exec(r.range.trim());
    if (!k) throw new LoiHien("Google trả tiến độ lạ — thử tải lại file này.", true);
    return Number(k[1]) + 1;
  }
  const loiCung = (status) => (status === 404 || status === 410
    ? new LoiHien("Phiên tải đã hết hạn — bấm Thử lại để tải lại từ đầu.", true, true)   // phiên chết ⇒ Thử lại phải mở phiên mới
    : new LoiHien("Google từ chối file này — thử tải lại.", true));

  // Mất kết nối / 5xx giữa khúc: hỏi Google đã nhận tới đâu (`bytes */size`). 200/201 = ĐÃ XONG (đọc id), 308 = còn dở theo luật byteKe.
  async function hoiTiep(m) {
    for (let lan = 1; lan <= THU_TOI_DA; lan++) {
      await lui(lan);
      if (m.huy) throw new LoiHuy();
      try {
        const r = await put(m, `bytes */${m.size}`, null);
        if (r.status === 200 || r.status === 201) return { id: docId(r) };
        if (r.status === 308) return { ke: byteKe(r) };
        if (r.status >= 400 && r.status < 500 && r.status !== 429 && r.status !== 408) throw loiCung(r.status);
      } catch (e) { if (!(e instanceof LoiMang)) throw e; }
    }
    throw new LoiHien("Mất kết nối khi đang tải. Kiểm tra mạng rồi bấm Thử lại — máy sẽ tải tiếp phần còn lại.", true);
  }

  // Đẩy dữ liệu tới khi Google trả 200/201 (trả id). `m.ke` = byte kế; `m.canHoi` = lần trước bị ngắt giữa chừng ⇒ hỏi Google trước.
  async function dayLen(m) {
    let khongTien = 0;
    if (m.canHoi) { const h = await hoiTiep(m); m.canHoi = false; if (h.id) return h.id; m.ke = h.ke; }
    while (true) {
      if (m.huy) throw new LoiHuy();
      const dau = m.ke, cuoi = Math.min(dau + KHUC, m.size) - 1;
      let r;
      try { r = await put(m, `bytes ${dau}-${cuoi}/${m.size}`, m.file.slice(dau, cuoi + 1)); }
      catch (e) {
        if (!(e instanceof LoiMang)) throw e;
        const h = await hoiTiep(m);
        if (h.id) return h.id;
        m.ke = h.ke; dat(); continue;
      }
      if (r.status === 200 || r.status === 201) return docId(r);
      if (r.status === 308) {
        const ke = byteKe(r);
        khongTien = ke <= dau ? khongTien + 1 : 0;   // Google không nhận thêm byte nào nhiều lần liền ⇒ dừng, không lặp vô hạn
        if (khongTien >= THU_TOI_DA) throw new LoiHien("Google không nhận thêm dữ liệu — bấm Thử lại.", true);
        m.ke = ke; dat(); continue;
      }
      if (r.status >= 500 || r.status === 429 || r.status === 408) {   // lỗi tạm của Google: hỏi tiếp rồi nối
        const h = await hoiTiep(m);
        if (h.id) return h.id;
        m.ke = h.ke; dat(); continue;
      }
      throw loiCung(r.status);
    }
  }

  async function taoPhien(m) {
    let r;
    try {
      r = await T.goi("/api/thay-logo/tai-len/phien", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ten: m.file.name.slice(0, 200), size: m.size, mime: m.mime }) });
    } catch (e) { if (e && e.message === "het_phien") throw new LoiHuy(); throw new LoiHien("Chưa gửi được yêu cầu tải — kiểm tra mạng rồi bấm Thử lại.", true); }
    if (r.status === 201) {
      const j = await r.json();
      if (typeof j.token !== "string" || typeof j.url_phien !== "string") throw new LoiHien("Máy chủ trả dữ liệu lạ — bấm Thử lại.", true);
      m.token = j.token; m.url = j.url_phien; m.ke = 0; m.canHoi = false;
      return;
    }
    const ct = await chiTiet(r);
    if (r.status === 404) throw new LoiHien("Tính năng tải từ máy đang tắt trên máy chủ.", false);
    if (r.status === 400 || r.status === 403) throw new LoiHien(ct || "Máy chủ không nhận file này.", false);
    throw new LoiHien(ct || "Máy chủ chưa tạo được phiên tải — thử lại sau ít phút.", true);
  }

  async function chot(m) {
    for (let lan = 1; lan <= THU_TOI_DA; lan++) {
      if (m.huy) throw new LoiHuy();
      let r;
      try { r = await T.goi(`/api/thay-logo/tai-len/${encodeURIComponent(m.token)}/xong`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_id: m.fileId }) }); }
      catch (e) { if (e && e.message === "het_phien") throw new LoiHuy(); await lui(lan); continue; }
      if (r.ok) return;
      const ct = await chiTiet(r);
      if (r.status >= 400 && r.status < 500 && r.status !== 429) throw new LoiHien(ct || "Máy chủ không xác nhận được file này.", false);
      await lui(lan);
    }
    throw new LoiHien("File đã lên Drive nhưng chưa xác nhận được với máy chủ — bấm Thử lại (không phải tải lại).", true);
  }

  // Một lần chạy của một file: tiếp từ chỗ dở (chưa có phiên ⇒ tạo; có url ⇒ hỏi Google tiếp; đã có fileId ⇒ chỉ xác nhận).
  async function chay(m) {
    m.tt = "dang"; m.loi = ""; m.thuLai = false; dat();
    try {
      if (!m.fileId) {
        if (!m.url) await taoPhien(m);
        if (m.huy) throw new LoiHuy();
        m.fileId = await dayLen(m);
        m.url = null;   // xong dữ liệu: không giữ quyền ghi lâu hơn cần thiết
      }
      await chot(m);
      m.tt = "xong"; tick(m);
    } catch (e) {
      if (e instanceof LoiHuy || m.huy) { m.tt = "huy"; }
      else {
        const hien = e instanceof LoiHien;
        m.tt = "loi"; m.thuLai = hien ? e.thuLai : true;
        m.loi = hien ? e.message : "Chưa tải được file này — bấm Thử lại.";
        if (hien && e.phienMoi) { m.url = null; m.canHoi = false; m.ke = 0; }
        else if (hien && !e.thuLai) m.url = null;
        else if (!m.fileId && m.url) m.canHoi = true;   // dở giữa chừng ⇒ lần sau hỏi Google đã nhận tới đâu
      }
    } finally { m.xhr = null; dat(); kich(); }
  }

  function thuLai(m) { m.tt = "cho"; dat(); kich(); }

  // ---------------------------------------------------------------- hàng chờ: tối đa 3 file chạy cùng lúc
  const dangChay = () => muc.filter((m) => m.tt === "dang").length;
  function kich() { for (const m of muc) { if (dangChay() >= SONG_SONG) break; if (m.tt === "cho") chay(m); } }

  // ---------------------------------------------------------------- tick vào lựa chọn của khối nhập
  const choConLai = () => Math.max(0, tran - T.nhapChon.size);
  function tick(m) {
    if (!m.fileId || T.tat) return;
    if (T.nhapChon.has(m.fileId)) { m.tick = true; return; }
    if (T.nhapChon.size >= tran) { thongBao = `Một lượt tối đa ${tran} video — file ${m.file.name} chưa được tick, bỏ bớt video khác rồi tick lại.`; m.tick = false; return; }
    T.nhapChon.add(m.fileId); m.tick = true;
    if (T.capNhatChan) T.capNhatChan();
  }
  function datTick(m, bat) {
    thongBao = "";
    if (bat) tick(m); else { T.nhapChon.delete(m.fileId); m.tick = false; }
    if (T.capNhatChan) T.capNhatChan();
    dat();
  }
  // Lượt đã tạo xong (khối nhập xoá chọn) ⇒ bỏ các dòng đã dùng. Lượt bị từ chối thì ta giữ nguyên (nhapChon vẫn còn id).
  function dongBo() {
    if (!daGui.size) return;
    for (let i = muc.length - 1; i >= 0; i--) { const m = muc[i]; if (m.fileId && daGui.has(m.fileId) && !T.nhapChon.has(m.fileId)) muc.splice(i, 1); }
    if (![...daGui].some((id) => T.nhapChon.has(id))) daGui = new Set();
  }

  // ---------------------------------------------------------------- thêm file
  function them(files) {
    thongBao = "";
    const goc = [...files];
    const cu = new Set(muc.map((m) => `${m.file.name}|${m.file.size}|${m.file.lastModified}`));
    let bo = 0;
    for (const f of goc) {
      const khoa = `${f.name}|${f.size}|${f.lastModified}`;
      if (cu.has(khoa)) { bo++; continue; }
      cu.add(khoa);
      const m = { id: ++tuSo, file: f, size: f.size, ten: f.name, mime: mimeCua(f), tt: "cho", loi: "", thuLai: false, ke: 0, dangGui: 0, url: null, token: null, fileId: null, tick: false, huy: false, xhr: null, canHoi: false };
      const sai = kiemFile(f);
      if (sai) { m.tt = "loi"; m.loi = sai; m.thuLai = false; }
      else if (muc.length >= tran) { m.tt = "loi"; m.loi = `Một lượt tối đa ${tran} video — bỏ bớt file rồi chọn lại.`; }
      muc.push(m);
    }
    if (bo) thongBao = `Bỏ qua ${bo} file đã chọn rồi.`;
    dat(); kich();
  }
  function go(m) {
    m.huy = true;
    if (m.xhr) m.xhr.abort();
    if (m.fileId) { T.nhapChon.delete(m.fileId); if (T.capNhatChan) T.capNhatChan(); }
    const i = muc.indexOf(m); if (i >= 0) muc.splice(i, 1);
    dat(); kich();
  }

  // ---------------------------------------------------------------- vẽ
  function dat() { if (hen) return; hen = setTimeout(() => { hen = null; veDs(); }, 60); }   // gộp các cập nhật tiến độ dồn dập

  function theMuc(m) {
    const li = el("li", "tl-may-the tl-may-" + (m.tt === "dang" || m.tt === "cho" ? "dang" : m.tt === "xong" ? "xong" : "loi"));
    const dau = el("span", "tl-may-dau"), than = el("div", "tl-may-than"), nut = [];
    if (m.tt === "xong") {
      const cb = el("input"); cb.type = "checkbox"; cb.checked = !!m.tick && T.nhapChon.has(m.fileId); cb.disabled = T.tat; cb.setAttribute("aria-label", `Chọn ${m.ten}`);
      cb.addEventListener("change", () => datTick(m, cb.checked));
      dau.append(cb);
    } else dau.textContent = m.tt === "loi" ? "✕" : "↥";
    than.append(el("div", "tl-may-ten", m.ten));
    if (m.tt === "dang" || m.tt === "cho") {
      const gui = Math.min(m.size, m.ke + m.dangGui), pct = m.size ? Math.floor((100 * gui) / m.size) : 0;
      than.append(el("div", "tl-may-phu", `${mb(m.size)} · ${m.tt === "cho" ? "đang chờ tới lượt" : m.fileId ? "đang xác nhận" : "đang tải lên"}`));
      const bar = el("div", "tl-may-bar"); bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-valuemin", "0"); bar.setAttribute("aria-valuemax", "100"); bar.setAttribute("aria-valuenow", String(pct));
      const i = el("i"); i.style.width = pct + "%"; bar.append(i);
      const hang = el("div", "tl-may-tien"); hang.append(bar, el("span", "tl-may-pct", pct + "%"));
      than.append(hang);
      const huy = el("button", "btn", "Huỷ"); huy.type = "button"; huy.addEventListener("click", () => go(m)); nut.push(huy);
    } else if (m.tt === "xong") {
      than.append(el("div", "tl-may-ok", `✓ Đã tải xong · ${mb(m.size)}`));
      const b = el("button", "btn", "Bỏ"); b.type = "button"; b.addEventListener("click", () => go(m)); nut.push(b);
    } else {
      li.setAttribute("role", "alert");
      than.append(el("div", "tl-may-loi-chu", m.loi));
      if (m.thuLai) { const t = el("button", "btn primary", "↻ Thử lại"); t.type = "button"; t.disabled = T.tat; t.addEventListener("click", () => thuLai(m)); nut.push(t); }
      const b = el("button", "btn" + (m.thuLai ? " ghost" : ""), "Bỏ"); b.type = "button"; b.addEventListener("click", () => go(m)); nut.push(b);
    }
    const hopNut = el("div", "tl-may-nut"); hopNut.append(...nut);
    li.append(dau, than, hopNut);
    return li;
  }

  function veDs() {
    if (!vungDs || !vungDs.isConnected || (hop && hop.hidden)) return;
    dongBo();
    vungDs.replaceChildren();
    const dem = (tt) => muc.filter((m) => (tt === "dang" ? m.tt === "dang" || m.tt === "cho" : m.tt === tt)).length;
    if (muc.length) {
      const tom = el("p", "tl-may-tom muted");
      tom.append(`${muc.length} file · `, el("b", "", String(dem("xong"))), " đã tải xong");
      if (dem("dang")) tom.append(` · ${dem("dang")} đang tải`);
      if (dem("loi")) tom.append(" · ", el("b", "tl-may-do", `${dem("loi")} lỗi`));
      vungDs.append(tom);
    }
    const tb = el("p", "tl-may-tb error-text", thongBao); tb.setAttribute("role", "status"); tb.hidden = !thongBao;
    const ul = el("ul", "tl-may-ds"); ul.setAttribute("aria-live", "polite");
    for (const m of muc) ul.append(theMuc(m));
    vungDs.append(tb, ul);
  }

  function veTat() { if (hop && !hop.hidden && co !== true) ve(hop); }

  function ve(h) {
    hop = h; vungDs = null;
    h.replaceChildren();
    if (co !== true) { h.append(el("p", "muted", co === false ? "Tính năng tải video từ máy đang tắt." : "Đang kiểm tra…")); return; }
    const vung = el("div", "tl-may-tha");
    const input = el("input"); input.type = "file"; input.multiple = true; input.accept = "video/*,.mp4,.mov"; input.hidden = true; input.id = "tl-may-input"; input.disabled = T.tat;
    input.addEventListener("change", () => { them(input.files); input.value = ""; });
    const chon = el("button", "btn", "Chọn file từ máy…"); chon.type = "button"; chon.disabled = T.tat; chon.addEventListener("click", () => input.click());
    vung.append(el("div", "tl-may-ic", "⇪"), el("div", "tl-may-tha-tieu", "Kéo thả video vào đây"),
      el("div", "tl-may-tha-phu", "mp4, mov · tối đa 500 MB mỗi file · chọn được nhiều file một lần"), chon, input);
    for (const s of ["dragenter", "dragover"]) vung.addEventListener(s, (e) => { e.preventDefault(); if (!T.tat) vung.classList.add("on"); });
    for (const s of ["dragleave", "drop"]) vung.addEventListener(s, (e) => { e.preventDefault(); vung.classList.remove("on"); });
    vung.addEventListener("drop", (e) => { if (!T.tat && e.dataTransfer && e.dataTransfer.files.length) them(e.dataTransfer.files); });
    h.append(vung, el("p", "tl-may-khoa muted", "🔒 File tải thẳng lên Drive của công ty, chỉ bạn thấy trong danh sách của bạn."));
    vungDs = el("div", "tl-may-vung-ds"); h.append(vungDs);
    veDs();
  }

  window.TL_TAB_NGUON = window.TL_TAB_NGUON || [];
  window.TL_TAB_NGUON.push({
    id: "may",
    giai: "Video có sẵn trên máy tính của bạn. Tải xong sẽ được tick.",
    ve,
    dem() { dongBo(); return muc.filter((m) => m.tt === "xong" && m.tick && T.nhapChon.has(m.fileId)).length; },
  });

  // POST tạo lượt bị từ chối ⇒ giữ nguyên các dòng (id vẫn còn trong lựa chọn).
  document.addEventListener("tl-tao-luot-loi", () => { daGui = new Set(); });

  // Hook thân POST tạo lượt (TL_THAN_POST): id file của tab này rời `drive_file_ids` sang `may_file_ids`. KHÔNG gửi tên/token — máy chủ tự tra theo file_id.
  window.TL_THAN_POST = window.TL_THAN_POST || [];
  window.TL_THAN_POST.push((than) => {
    const cua = new Set(muc.filter((m) => m.tt === "xong" && m.fileId).map((m) => m.fileId));
    const ids = [], may = [];
    for (const id of than.drive_file_ids || []) (cua.has(id) ? may : ids).push(id);
    if (!may.length) return;
    than.drive_file_ids = ids;
    than.may_file_ids = [...(than.may_file_ids || []), ...may];
    daGui = new Set(may);
  });
})();
