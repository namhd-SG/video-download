// Tab "Dán link Drive": dán link FILE hoặc THƯ MỤC (mỗi dòng một link) → "Kiểm link" (POST /api/thay-logo/kiem-link) → tick video muốn thay.
// Đăng ký vào window.TL_TAB_NGUON theo hợp đồng trong thay-logo-chung.js: ve() idempotent (mọi trạng thái nằm trong closure này),
// tự đọc T.tat, chỉ đưa ID FILE Drive vào T.nhapChon. Mọi chữ từ máy chủ/Drive (tên file, link) vào bằng textContent — không innerHTML.
(() => {
  "use strict";
  const T = window.TL;
  if (!T) return;
  const { el } = T;
  const TRAN_LINK = 20, SO_DONG_GON = 4;
  const MAU_TEN_MAC_DINH = /^\d{2}\/\d{2}-\d+$/;  // dạng `dd/mm-n` mà khối nhập tự điền

  let hop = null;                 // container của lần ve() gần nhất (vẽ lại khi trạng thái đổi)
  let van = "";                   // nội dung ô dán (giữ khi đổi tab)
  let kq = null;                  // phản hồi gần nhất của kiem-link: {ket_qua, email_may, trung_bo}
  let dangKiem = false, thongBao = "", daCopy = false;
  let tran = 100;                 // số video tối đa một lượt (đọc từ /tinh-nang)
  const moRong = new Set();       // id thư mục đang mở hết danh sách
  const cuaTab = new Set();       // id file do tab này đưa vào T.nhapChon (để gỡ đúng phần của mình)
  const daGap = new Set();        // id đã được tự tick một lần — kiểm lại KHÔNG tick lại video người dùng đã bỏ

  T.goi("/tinh-nang").then((r) => (r.ok ? r.json() : null)).then((j) => { if (j && j.thay_logo_video_mot_luot > 0) tran = j.thay_logo_video_mot_luot; }).catch(() => {});

  // Chỗ còn lại của member = trần một lượt trừ video của họ đang chờ máy (tong − xong − cần-người − lỗi, cộng qua các bộ ở T.bo).
  // Máy chủ vẫn là người chốt (429); đây chỉ để không cho tick quá số chắc chắn bị từ chối.
  const choConLai = () => {
    const dangCho = (T.bo || []).reduce((a, b) => a + Math.max(0, (b.tong || 0) - (b.xong || 0) - (b.cho_nguoi || 0) - (b.loi || 0)), 0);
    return Math.max(0, tran - dangCho);
  };
  const tickDuoc = (id) => {
    if (T.nhapChon.has(id)) return true;
    if (T.nhapChon.size >= choConLai()) { thongBao = `Bạn còn được xếp ${choConLai()} video — bỏ bớt video khác rồi chọn tiếp.`; return false; }
    T.nhapChon.add(id); cuaTab.add(id); return true;
  };
  const bo = (id) => { T.nhapChon.delete(id); };
  function datTick(id, bat) { if (bat) tickDuoc(id); else bo(id); }
  const sau = () => { T.capNhatChan(); ve(hop, T); };

  const mb = (n) => (n == null ? "" : n >= 1048576 ? `${Math.round(n / 1048576)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  const dongCua = () => van.split(/\r?\n/).map((d) => d.trim()).filter(Boolean);

  async function kiem() {
    if (dangKiem || T.tat) return;
    const dong = dongCua();
    thongBao = "";
    if (!dong.length) { thongBao = "Dán ít nhất một link Google Drive."; return ve(hop, T); }
    if (dong.length > TRAN_LINK) { thongBao = `Mỗi lần kiểm tối đa ${TRAN_LINK} link — bỏ bớt ${dong.length - TRAN_LINK} link.`; return ve(hop, T); }
    dangKiem = true; ve(hop, T);
    try {
      const r = await T.goi("/api/thay-logo/kiem-link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ links: dong }) });
      if (!r.ok) {
        thongBao = r.status === 400 ? "Link chưa đúng: dán tối đa 20 link, mỗi dòng một link."
          : r.status === 409 ? "Tính năng đang tạm tắt hoặc máy chủ chưa nối Google Drive — báo quản trị."
          : `Chưa kiểm được (lỗi ${r.status}). Thử lại sau ít phút.`;
      } else {
        nhanKetQua(await r.json());
      }
    } catch (e) {
      if (!e || e.message !== "het_phien") thongBao = "Chưa kiểm được — kiểm tra mạng rồi bấm Kiểm link lại.";
    } finally { dangKiem = false; sau(); }
  }

  function nhanKetQua(j) {
    kq = j;
    const idHienCo = new Set();
    let thuMucDau = null;
    for (const k of j.ket_qua || []) {
      if (k.trang_thai !== "nhan") continue;
      const ids = k.kieu === "file" ? [k.id] : (k.videos || []).map((v) => v.id);
      ids.forEach((i) => idHienCo.add(i));
      let moi = 0;
      for (const i of ids) if (!daGap.has(i)) { daGap.add(i); if (tickDuoc(i)) moi++; }  // mặc định tick hết (tới trần một lượt)
      if (k.kieu === "thu_muc" && moi && !thuMucDau) thuMucDau = k.ten;
    }
    for (const i of [...cuaTab]) if (!idHienCo.has(i)) { bo(i); cuaTab.delete(i); }  // link đã bị bỏ/sửa khỏi kết quả ⇒ gỡ video của nó
    if (thuMucDau) dienTenBo(thuMucDau);
  }

  // Tên bộ tự điền tên thư mục — CHỈ khi ô đang để trống hoặc dạng mặc định `dd/mm-n` (không ghi đè chữ người dùng đã gõ).
  function dienTenBo(ten) {
    const o = document.getElementById("tl-ten-bo");
    if (!o || T.tat) return;
    const hien = o.value.trim();
    if (hien !== "" && !MAU_TEN_MAC_DINH.test(hien)) return;
    o.value = String(ten).slice(0, 80);
    o.dispatchEvent(new Event("input", { bubbles: true }));  // khối nhập đọc sự kiện này để ngừng tự điền đè lên
  }

  async function chepEmail(chu, nut) {
    try { await navigator.clipboard.writeText(chu); daCopy = true; nut.textContent = "✓ Đã copy"; }
    catch (_) { nut.textContent = "Chọn địa chỉ rồi copy"; }
  }

  function veThuMuc(k) {
    const li = el("li", "tl-lk-the tl-lk-thu-muc");
    const ids = (k.videos || []).map((v) => v.id), n = ids.length, so = ids.filter((i) => T.nhapChon.has(i)).length;
    const head = el("div", "tl-lk-tm-head");
    const ca = el("input"); ca.type = "checkbox"; ca.checked = so === n; ca.indeterminate = so > 0 && so < n; ca.disabled = T.tat;
    ca.setAttribute("aria-label", `Chọn cả thư mục ${k.ten}`);
    ca.addEventListener("change", () => { thongBao = ""; ids.forEach((i) => datTick(i, ca.checked)); sau(); });
    const than = el("div", "tl-lk-than");
    than.append(el("div", "tl-lk-ten", "▤ " + k.ten), el("div", "tl-lk-phu", `${n} video nằm trực tiếp trong thư mục (bỏ qua thư mục con)`));
    const them = [];
    if (k.bo_qua_thu_muc_con) them.push(`bỏ qua ${k.bo_qua_thu_muc_con} thư mục con`);
    if (k.bo_qua_khac) them.push(`${k.bo_qua_khac} file khác bị bỏ (không phải mp4/mov hoặc quá 500 MB)`);
    if (them.length) than.append(el("div", "tl-lk-phu", them.join(" · ")));
    than.append(el("div", "tl-lk-url", k.link));
    head.append(ca, than, el("span", "tl-lk-dem", `${so}/${n} đã chọn`));
    const ds = el("ul", "tl-lk-ds-vid"), mo = moRong.has(k.id), hien = mo ? k.videos : k.videos.slice(0, SO_DONG_GON);
    for (const v of hien) {
      const row = el("li"), cb = el("input"); cb.type = "checkbox"; cb.checked = T.nhapChon.has(v.id); cb.disabled = T.tat;
      cb.setAttribute("aria-label", `Chọn ${v.ten}`);
      cb.addEventListener("change", () => { thongBao = ""; datTick(v.id, cb.checked); sau(); });
      row.append(cb, el("span", "tl-lk-t", v.ten), el("span", "tl-lk-mb", mb(v.size)));
      ds.append(row);
    }
    li.append(head, ds);
    if (n > SO_DONG_GON) {
      const nut = el("button", "tl-lk-them", mo ? "Thu gọn ▴" : `Hiện cả ${n} video ▾`); nut.type = "button"; nut.setAttribute("aria-expanded", String(mo));
      nut.addEventListener("click", () => { mo ? moRong.delete(k.id) : moRong.add(k.id); ve(hop, T); });
      li.append(nut);
    }
    return li;
  }

  function veFile(k) {
    const li = el("li", "tl-lk-the tl-lk-file");
    const cb = el("input"); cb.type = "checkbox"; cb.checked = T.nhapChon.has(k.id); cb.disabled = T.tat; cb.setAttribute("aria-label", `Chọn ${k.ten}`);
    cb.addEventListener("change", () => { thongBao = ""; datTick(k.id, cb.checked); sau(); });
    const than = el("div", "tl-lk-than");
    than.append(el("div", "tl-lk-ten", k.ten), el("div", "tl-lk-ok", `✓ Nhận · ${mb(k.size)}`), el("div", "tl-lk-url", k.link));
    li.append(cb, than);
    return li;
  }

  function boDong(k) {
    const con = dongCua().filter((d) => d.slice(0, 300) !== k.link);
    van = con.join("\n");
    kq = { ...kq, ket_qua: kq.ket_qua.filter((x) => x !== k) };
    sau();
  }

  function veLoi(k) {
    const li = el("li", "tl-lk-the tl-lk-loi"); li.setAttribute("role", "alert");
    const than = el("div", "tl-lk-than"), la = /\/folders\//.test(k.link) ? "thư mục" : "file";
    let nut;
    if (k.trang_thai === "khong_mo_duoc") {
      than.append(el("div", "tl-lk-ten tl-lk-do", `Máy chưa mở được ${la} này`), el("div", "tl-lk-url", k.link));
      const email = kq && kq.email_may;
      than.append(el("div", "tl-lk-chi", email ? `Hãy chia sẻ ${la} cho địa chỉ dưới đây (quyền Xem) rồi bấm Kiểm lại.` : `Hãy chia sẻ ${la} cho tài khoản máy (quyền Xem) rồi bấm Kiểm lại — hỏi quản trị địa chỉ cần chia sẻ.`));
      if (email) {
        const h = el("div", "tl-lk-email"), code = el("code", "", email), cp = el("button", "btn", daCopy ? "✓ Đã copy" : "⧉ Copy"); cp.type = "button";
        cp.addEventListener("click", () => chepEmail(email, cp));
        h.append(code, cp); than.append(h);
      }
      nut = el("button", "btn primary", "↻ Kiểm lại"); nut.addEventListener("click", kiem);
    } else if (k.trang_thai === "loi_tam") {
      than.append(el("div", "tl-lk-ten tl-lk-do", "Chưa kiểm được link này"), el("div", "tl-lk-url", k.link), el("div", "tl-lk-chi", k.ly_do || "Drive đang bận. Bấm Kiểm lại sau ít phút."));
      nut = el("button", "btn primary", "↻ Kiểm lại"); nut.addEventListener("click", kiem);
    } else {
      than.append(el("div", "tl-lk-ten tl-lk-do", "Không dùng được link này"), el("div", "tl-lk-url", k.link), el("div", "tl-lk-chi", k.ly_do || "Link không dùng được."));
      nut = el("button", "btn ghost", "Bỏ"); nut.addEventListener("click", () => boDong(k));
    }
    nut.type = "button"; nut.disabled = T.tat || dangKiem;
    li.append(el("span", "tl-lk-dau", "✕"), than, nut);
    return li;
  }

  function ve(h, tt) {
    hop = h;
    h.replaceChildren();
    const nhan = el("label", "tl-lk-nhan muted", "Link Google Drive (file hoặc thư mục)"); nhan.htmlFor = "tl-o-link";
    const o = el("textarea", "tl-o-link"); o.id = "tl-o-link"; o.rows = 4; o.value = van; o.disabled = tt.tat; o.spellcheck = false;
    o.placeholder = "Dán link, mỗi dòng một link.\nvd: https://drive.google.com/drive/folders/…";
    o.addEventListener("input", () => { van = o.value; });
    const hang = el("div", "tl-lk-hang");
    const ds = (kq && kq.ket_qua) || [], nhanN = ds.filter((k) => k.trang_thai === "nhan").length;
    const tom = el("span", "muted");
    if (ds.length) {
      tom.append(`${ds.length} link · `, el("b", "tl-lk-ok", `${nhanN} nhận`), " · ", el("b", "tl-lk-do", `${ds.length - nhanN} chưa dùng được`));
      if (kq.trung_bo) tom.append(` · bỏ ${kq.trung_bo} link trùng`);
    } else tom.textContent = "Chưa kiểm link nào.";
    const nut = el("button", "btn", dangKiem ? "Đang kiểm…" : "Kiểm link"); nut.type = "button"; nut.disabled = tt.tat || dangKiem;
    nut.addEventListener("click", kiem);
    hang.append(tom, nut);
    h.append(nhan, o, hang);
    const tb = el("p", "tl-lk-tb error-text", thongBao); tb.setAttribute("role", "status"); tb.hidden = !thongBao;
    h.append(tb);
    const ul = el("ul", "tl-lk-ds"); ul.setAttribute("aria-live", "polite");
    for (const k of ds) ul.append(k.trang_thai === "nhan" ? (k.kieu === "thu_muc" ? veThuMuc(k) : veFile(k)) : veLoi(k));
    h.append(ul);
  }

  (window.TL_TAB_NGUON = window.TL_TAB_NGUON || []).push({ id: "link", giai: "Dán link file hoặc thư mục Google Drive, mỗi dòng một link.", ve });
})();
