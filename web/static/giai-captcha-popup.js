// Popup "Giải xác minh TikTok" của Video Desk — người nhìn ảnh trang TikTok đang mở trên máy chủ
// rồi kéo/bấm chuột TRỰC TIẾP trên ảnh; popup chuyển ĐÚNG những sự kiện chuột đó lên máy chủ.
//
// Popup KHÔNG tự giải, không sinh sự kiện chuột nào người không tạo ra, không nội suy, không làm
// tròn toạ độ, không sửa `buttons` (ĐP-529/602/606). Mọi sự kiện đều là `PointerEvent` thật của
// người (kể cả các điểm trong `getCoalescedEvents()`).
//
// Hợp đồng API: docstring `web/giai_captcha.py`. Mock đã duyệt (nguồn sự thật về giao diện):
// plans/261002-1505-video-desk-captcha-headful/mock-popup-giai-captcha.html — KHÔNG có nút ×
// (USER chốt 03/10): popup chỉ đóng bằng "Đã giải xong" / "Dừng job" / hết giờ / lỗi.
(function () {
  "use strict";

  // Cửa sổ giải = `CUA_SO_GIAI_GIAY` ở web/giai_captcha.py; số lần tải lại do gesture dở =
  // `TRAN_TAI_LAI_MOI_LUOT`. Chỉ để vẽ đồng hồ/câu chữ — máy chủ mới là bên đếm thật.
  const CUA_SO_GIAI_GIAY = 300;
  const TRAN_TAI_LAI = 2;
  // Gom lô (khớp `MAC_DINH_GOM_LO_POPUP_MS` / `LO_TOI_DA_SU_KIEN` phía máy chủ).
  const GOM_LO_MS = 40;
  const LO_TOI_DA = 64;
  // POST lô trượt do mạng/429/5xx: thử lại CÙNG `seq` (máy chủ loại trùng theo `seq`).
  const THU_LAI_TOI_DA = 3;
  const THU_LAI_CHO_MS = 150;
  // Sau chừng này không bấm/lăn chuột thì nhắc "Không thấy captcha?" (popup không đọc được DOM
  // trang TikTok nên không tự biết có captcha hay không — chỉ gợi ý theo thời gian).
  // 15 s CHƯA ĐO (ĐP-711): mock không nêu điều kiện; đo ở job thật đầu tiên.
  const GOI_Y_KHONG_THAY_SAU_MS = 15000;

  // Cầu nối do app.js đưa vào (`noiVao`) — file này không phụ thuộc app.js.
  const cau = {
    toast() {}, lamMoiJob: async () => {}, layJob: () => null, baoPhienHetHan() {},
    cauLyDo: () => "",
  };
  let P = null; // popup đang mở (null = không có)

  const IC = {
    tay: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 7v4"/></svg>',
    canh: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5M12 18h.01"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/></svg>',
    khoa: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    dongho: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 2h6"/></svg>',
    dangnhap: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3"/></svg>',
    taiLai: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true" style="vertical-align:-2px;margin-right:6px"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/></svg>',
    khien: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z"/></svg>',
  };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const ngu = (ms) => new Promise((xong) => setTimeout(xong, ms));

  // Token riêng mỗi lần mở popup: khoá điều khiển và số thứ tự lô gắn với nó. 8–64 ký tự
  // [A-Za-z0-9_-]. `randomUUID` chỉ có ở ngữ cảnh an toàn (https / 127.0.0.1) ⇒ có đường dự phòng.
  function taoToken() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    const b = new Uint8Array(16);
    window.crypto.getRandomValues(b);
    return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }

  // Gọi API. Trả {matPhien} khi phiên đăng nhập hết (302 → opaqueredirect, 401, hoặc 200 trả
  // trang HTML đăng nhập thay vì JSON); ngoài ra {ok, status, data}. Mạng đứt thì ném lỗi.
  async function goi(method, path, body) {
    const res = await fetch(path, {
      method,
      redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0 || res.status === 401) return { matPhien: true };
    const laJson = (res.headers.get("content-type") || "").includes("json");
    if (res.ok && !laJson) return { matPhien: true };
    let data = null;
    if (laJson) { try { data = await res.json(); } catch (e) { data = null; } }
    return { ok: res.ok, status: res.status, data };
  }

  function chiTietLoi(r, macDinh) {
    const d = r && r.data && r.data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => e.msg || "").filter(Boolean).join("; ") || macDinh;
    return macDinh;
  }

  function dinhDangGio(giay) {
    const g = Math.max(0, Math.ceil(giay));
    return `${Math.floor(g / 60)}:${String(g % 60).padStart(2, "0")}`;
  }

  function rutGonUrl(url) {
    try {
      const u = new URL(url);
      return u.hostname.replace(/^www\./, "") + u.pathname.replace(/\/$/, "");
    } catch (e) { return String(url); }
  }

  // ------------------------------------------------------------------------
  // Trạng thái hiển thị
  // ------------------------------------------------------------------------
  function dieuKhienDuoc() {
    return !!P && P.ttGiai === "dang_giai" && P.vai === "dieu_khien" && P.coKhung &&
      !P.panel && !P.matKetNoiHan;
  }

  function conLaiGiay() {
    if (!P || !P.conLai) return null;
    return Math.max(0, P.conLai.giay - (performance.now() - P.conLai.luc) / 1000);
  }

  // Một trong: cho-khung · dang-giai · chi-xem · bi-ngat · khong-thay · het-gio · dang-nhap-lai · dong
  function tinhMan() {
    if (P.panel) return P.panel.loai;
    if (!P.coKhung || (P.ttGiai !== "dang_giai")) return "cho-khung";
    if (P.vai !== "dieu_khien") return "chi-xem";
    if (P.biNgat) return "bi-ngat";
    if (P.khongThay) return "khong-thay";
    return "dang-giai";
  }

  const WHY = '<span class="gc-why"><b>Đã giải xong</b>: tool tải lại trang một lần rồi quét tiếp — vẫn bị chặn thì job quay lại “Cần xác minh”.<br><b>Dừng job</b>: job kết thúc, không tải video nào từ trang này.</span>';

  function noteTheoMan(man) {
    switch (man) {
      case "cho-khung":
        return ["trung", IC.info, "Máy chủ đang mở trang của job. Đồng hồ 5 phút chỉ bắt đầu khi ảnh trang hiện lên."];
      case "dang-giai":
        return ["goi-y", IC.tay, "<b>Kéo/bấm trực tiếp trên ảnh. Chỉ dùng chuột.</b> Lăn chuột để cuộn trang. Thao tác của bạn được chuyển nguyên văn tới trang trên máy chủ — ảnh có thể trễ một chút."];
      case "chi-xem":
        return ["trung", IC.info, "Mỗi lúc chỉ một người điều khiển được. Bạn vẫn thấy ảnh trang để theo dõi."];
      case "bi-ngat": {
        if (P.biNgat.loai === "cuc_bo") {
          return ["canh", IC.canh, "<b>Thao tác bị ngắt, kéo lại từ đầu.</b> Cửa sổ vừa mất con trỏ giữa lúc bạn đang nhấn chuột; không có thao tác nhả nào được gửi đi."];
        }
        const con = Math.max(0, TRAN_TAI_LAI - (P.soTaiLai || 0));
        return ["canh", IC.canh, "<b>Thao tác bị ngắt, kéo lại từ đầu.</b> Trang đã tải lại với một captcha mới. " +
          (con > 0
            ? `Lượt giải này còn được tải lại ${con} lần nữa; bị ngắt sau đó thì lượt giải đóng và job quay lại “Cần xác minh”.`
            : "Đã hết lần tải lại: bị ngắt thêm một lần nữa thì lượt giải đóng và job quay lại “Cần xác minh”.")];
      }
      case "khong-thay":
        return ["goi-y", IC.info, "<b>Không thấy captcha?</b> Lăn chuột trong khung, hoặc bấm “Đã giải xong” để tool quét thử."];
      default:
        return null;
    }
  }

  function datHtml(el, html) {
    if (el._h !== html) { el._h = html; el.innerHTML = html; }
  }

  function ve() {
    if (!P || P.daDong) return;
    const q = (id) => P.goc.querySelector("#" + id);
    const man = tinhMan();
    P.man = man;

    // vai trò
    const role = q("gc-role");
    let vai = null;
    if (!P.panel && P.ttGiai === "dang_giai" && P.coKhung) vai = P.vai === "dieu_khien" ? ["ban", "Bạn đang điều khiển"] : ["xem", "Chỉ xem"];
    role.hidden = !vai;
    if (vai) { role.className = "gc-role " + vai[0]; role.textContent = vai[1]; }

    // đồng hồ + thanh thời gian
    veDongHo();

    // ô thông báo (luôn nằm NGOÀI khung ảnh)
    const note = q("gc-note");
    let n = noteTheoMan(man);
    if (P.matKetNoi && !P.panel) {
      n = ["canh", IC.canh, "<b>Mất kết nối tới máy chủ — đang nối lại…</b> Thao tác lúc này có thể chưa tới trang."];
    }
    note.hidden = !n;
    if (n) {
      note.className = "gc-note " + n[0];
      datHtml(note, n[1] + "<span>" + n[2] + "</span>");
    }

    // thân: ảnh sống hoặc khung đã đóng
    if (P.panel) veKhungDong(q("gc-body")); else veKhungSong(q, man);

    // nút
    const hd = q("gc-actions");
    if (P.panel) datHtml(hd, hanhDongKhungDong());
    else {
      const duoc = dieuKhienDuoc() && !P.dangGuiLenh;
      // Người chỉ xem có nút "Đóng" (mock không vẽ): câu trên khung bảo họ "mở lại popup" để nhận
      // quyền, mà không có nút này thì họ không có cách đóng nó. Đóng popup chỉ-xem không nhả gì
      // (họ không giữ khoá).
      datHtml(hd, man === "chi-xem" || man === "cho-khung"
        ? (man === "chi-xem" ? '<span class="gc-why">Hai nút chỉ dùng được cho người đang điều khiển.</span><button type="button" class="btn ghost" data-dong>Đóng</button>' : WHY) +
          '<button type="button" class="btn primary" disabled>Đã giải xong</button><button type="button" class="btn danger-line" disabled>Dừng job</button>'
        : WHY + `<button type="button" class="btn primary" data-lenh="da_giai"${duoc ? "" : " disabled"}>Đã giải xong</button>` +
          `<button type="button" class="btn danger-line" data-lenh="dung"${duoc ? "" : " disabled"}>Dừng job</button>`);
    }
  }

  function veDongHo() {
    if (!P || P.daDong) return;
    const t = P.goc.querySelector("#gc-timer");
    const tr = P.goc.querySelector("#gc-track");
    const fill = P.goc.querySelector("#gc-track-fill");
    const man = P.man;
    let hien = null; // {chu, nho, lop, tiLe, trackLop}
    if (P.panel) {
      if (P.panel.loai === "het-gio") hien = { chu: "0:00", nho: "hết giờ", lop: "het", tiLe: 0, trackLop: "het" };
    } else if (P.ttGiai === "dang_giai" && P.coKhung && P.conLai) {
      const con = conLaiGiay();
      hien = { chu: dinhDangGio(con), nho: "còn", lop: con <= 0 ? "het" : "", tiLe: con / CUA_SO_GIAI_GIAY, trackLop: con <= 0 ? "het" : "" };
    } else if (man === "cho-khung") {
      // Đồng hồ chưa chạy ⇒ thanh xám, không giả vờ đang đếm.
      hien = { chu: dinhDangGio(CUA_SO_GIAI_GIAY), nho: "chưa chạy", lop: "cho", tiLe: 1, trackLop: "cho" };
    }
    t.hidden = !hien; tr.hidden = !hien;
    if (!hien) return;
    t.className = "gc-timer" + (hien.lop ? " " + hien.lop : "");
    const html = `<small>${hien.nho}</small>${hien.chu}`;
    if (t._h !== html) { t._h = html; t.innerHTML = html; }
    tr.className = "gc-time-track" + (hien.trackLop ? " " + hien.trackLop : "");
    fill.style.width = Math.max(0, Math.min(1, hien.tiLe)) * 100 + "%";
  }

  function veKhungSong(q, man) {
    let body = q("gc-body");
    if (!body.querySelector("#gc-khung")) {
      body.innerHTML =
        '<div class="gc-frame" id="gc-khung" draggable="false" ' +
        'aria-label="Ảnh trang TikTok trên máy chủ. Kéo hoặc bấm chuột trực tiếp trên ảnh.">' +
        '<img class="gc-anh" id="gc-anh" alt="" draggable="false" hidden>' +
        '<div class="gc-over" id="gc-over" hidden></div>' +
        '<span class="gc-tag" id="gc-tag" hidden>ảnh trang TikTok trên máy chủ</span></div>';
      P.khung = body.querySelector("#gc-khung");
      P.anh = body.querySelector("#gc-anh");
      gan(P.khung);
      // Ảnh khung mới nhất đã nhận trước khi khung DOM dựng xong (đóng panel rồi mở lại).
      if (P.khungMoi) hienKhung(P.khungMoi);
    }
    P.khung.classList.toggle("dieu-khien", dieuKhienDuoc());
    const anh = P.anh, over = q("gc-over"), tag = q("gc-tag");
    anh.hidden = !P.coKhung;
    tag.hidden = !P.coKhung;
    let html = "", lop = "";
    if (man === "cho-khung" && !P.coKhung) {
      lop = "cho";
      const dangCho = P.ttGiai === "cho_giai";
      html = '<span class="gc-spin" aria-hidden="true"></span>' +
        (dangCho
          ? `<h4>Đang chờ tới lượt mở trang…</h4><p>Máy chủ chỉ mở một trang giải một lúc${P.viTri ? ` (bạn thứ ${esc(P.viTri)} trong hàng)` : ""}. Giữ cửa sổ này mở — trang sẽ tự hiện.</p>`
          : "<h4>Đang mở trang trên máy chủ…</h4><p>Thường mất vài giây đến nửa phút. Nếu không mở được, job quay lại “Cần xác minh” và bạn có thể thử lại.</p>");
    } else if (man === "chi-xem") {
      lop = "xem";
      html = '<div class="hop">' + IC.khoa + "<h4>Người khác đang giải — bạn chỉ xem</h4><p>Có thể là một tab khác của chính bạn. Khi cửa sổ giải bên đó đóng lại, mở lại popup này để nhận quyền điều khiển.</p></div>";
    }
    over.hidden = !lop;
    over.className = "gc-over" + (lop ? " " + lop : "");
    datHtml(over, html);
  }

  const ICON_DONG = { "het-gio": ["het", IC.dongho], khac: ["dn", IC.canh], "dang-nhap-lai": ["dn", IC.dangnhap] };

  function veKhungDong(body) {
    P.khung = null; P.anh = null;
    const p = P.panel;
    const [lop, icon] = ICON_DONG[p.loai] || ICON_DONG.khac;
    let tieuDe, noiDung, nutPhu = "";
    if (p.loai === "het-gio") {
      tieuDe = "Hết thời gian giải — job quay lại “Cần xác minh”";
      noiDung = `Trang trên máy chủ đã đóng. Bạn có thể bấm “Tôi giải ngay” lại${p.con === null ? "" : ` (còn ${p.con} lần)`}. Không giải nữa thì job tự kết thúc sau 24 giờ, hoặc rút lượt để trả hạn mức.`;
    } else if (p.loai === "dang-nhap-lai") {
      tieuDe = "Phiên đăng nhập đã hết — tải lại trang để đăng nhập lại";
      noiDung = "Video Desk không gửi được thao tác của bạn nữa. Trang trên máy chủ vẫn mở tới hết 5 phút rồi job quay lại “Cần xác minh”; sau khi đăng nhập lại, bạn có thể bấm “Tôi giải ngay” nếu còn lượt.";
      nutPhu = `<div class="row"><button type="button" class="btn primary" data-tai-lai-trang>${IC.taiLai}Tải lại trang</button></div>`;
    } else {
      tieuDe = p.tieuDe || "Lượt giải đã đóng";
      noiDung = p.noiDung || "";
    }
    datHtml(body, `<div class="gc-closed"><span class="ic ${lop}">${icon}</span><h4>${esc(tieuDe)}</h4><p>${esc(noiDung)}</p>${nutPhu}</div>`);
  }

  function hanhDongKhungDong() {
    const p = P.panel;
    const dong = '<button type="button" class="btn ghost" data-dong>Đóng</button>';
    if (p.loai === "dang-nhap-lai") return '<span class="gc-why"></span>' + dong;
    const het = p.con === 0;
    return '<span class="gc-why"></span>' + dong +
      `<button type="button" class="btn primary" data-giai-lai${het ? " disabled" : ""}>Tôi giải ngay${p.con === null || het ? "" : ` (còn ${p.con} lần)`}</button>`;
  }

  // ------------------------------------------------------------------------
  // Chuột — chuyển ĐÚNG sự kiện của người
  // ------------------------------------------------------------------------
  function gan(khung) {
    // CSS đã đặt draggable=false / touch-action:none / user-select:none; ở đây chặn nốt menu chuột
    // phải và kéo-thả mặc định của trình duyệt (cả hai sẽ cướp gesture của người).
    khung.addEventListener("contextmenu", (e) => e.preventDefault());
    khung.addEventListener("dragstart", (e) => e.preventDefault());
    khung.addEventListener("pointerdown", khiNhan);
    khung.addEventListener("pointermove", khiDiChuyen);
    khung.addEventListener("pointerup", khiNha);
    khung.addEventListener("pointercancel", () => boCuChi("cuc_bo"));
    khung.addEventListener("lostpointercapture", () => boCuChi("cuc_bo"));
    khung.addEventListener("wheel", khiLan, { passive: false });
  }

  function hinhHoc() {
    const anh = P && P.anh;
    if (!anh || !anh.naturalWidth) return null;
    const r = anh.getBoundingClientRect();
    if (!r.width) return null;
    // MỘT hệ số cho cả x và y (máy chủ cũng dùng một hệ số `deviceWidth / khung_w`).
    return { r, he: anh.naturalWidth / r.width, khungW: anh.naturalWidth };
  }

  // Thêm MỘT sự kiện vào lô đang gom. Toạ độ theo pixel ẢNH khung, KHÔNG làm tròn.
  function them(k, src, h, extra) {
    const ev = Object.assign({
      k, x: (src.clientX - h.r.left) * h.he, y: (src.clientY - h.r.top) * h.he,
      t: src.timeStamp, buttons: src.buttons,
    }, extra || {});
    if (P.buf.length && P.bufKhungW !== h.khungW) xaLo();
    if (!P.buf.length) { P.bufKhungW = h.khungW; P.bufKhungSeq = P.khungHienSeq; }
    P.buf.push(ev);
    if (P.buf.length >= LO_TOI_DA) xaLo();
    else if (!P.hen) P.hen = setTimeout(xaLo, GOM_LO_MS);
  }

  function khiNhan(e) {
    if (!dieuKhienDuoc() || e.pointerType !== "mouse") return;
    e.preventDefault();
    // Chỉ NÚT TRÁI. Nút phải/giữa: không gửi gì, không mở gesture.
    if (e.button !== 0 || (e.buttons & ~1)) { if (P.cuChi) boCuChi("cuc_bo"); return; }
    const h = hinhHoc();
    if (!h) return;
    P.cuChi = { id: e.pointerId };
    P.biNgat = null;
    P.khongThay = false;
    P.moc = performance.now();
    try { P.khung.setPointerCapture(e.pointerId); } catch (err) { /* không bắt được thì vẫn gửi từng sự kiện */ }
    them("down", e, h);
    ve();
  }

  function khiDiChuyen(e) {
    if (!dieuKhienDuoc() || e.pointerType !== "mouse") return;
    if (P.cuChi) {
      if (e.pointerId !== P.cuChi.id) return;
      // Bấm thêm nút phải/giữa, hoặc nút trái đã nhả mà không có `pointerup` ⇒ bỏ gesture, KHÔNG gửi `up`.
      if ((e.buttons & ~1) || !(e.buttons & 1)) { boCuChi("cuc_bo"); return; }
    } else if (e.buttons !== 0) {
      // Đang giữ nút mà không có gesture của popup (gesture đã bỏ, hoặc bấm nút phải/giữa): đây
      // không phải rê chuột ⇒ không gửi gì.
      return;
    }
    const h = hinhHoc();
    if (!h) return;
    const ds = typeof e.getCoalescedEvents === "function" ? e.getCoalescedEvents() : [];
    for (const c of (ds.length ? ds : [e])) them("move", c, h);
  }

  function khiNha(e) {
    if (!P || !P.cuChi || e.pointerId !== P.cuChi.id) return;
    if (e.button !== 0 || (e.buttons & ~1)) { boCuChi("cuc_bo"); return; }
    const h = hinhHoc();
    if (h) them("up", e, h);
    P.cuChi = null;
    try { P.khung.releasePointerCapture(e.pointerId); } catch (err) { /* đã tự nhả */ }
  }

  function khiLan(e) {
    if (!dieuKhienDuoc()) return;
    e.preventDefault();
    const h = hinhHoc();
    if (!h) return;
    // Máy chủ chỉ nhận wheel theo pixel (`delta_mode` 0). Chuột dùng đơn vị dòng/trang (Firefox)
    // thì đổi sang pixel: 1 dòng = 16 px, 1 trang = chiều cao khung (cùng đơn vị ảnh).
    const he = e.deltaMode === 1 ? 16 : (e.deltaMode === 2 ? P.anh.naturalHeight : 1);
    P.moc = performance.now();
    if (P.khongThay) { P.khongThay = false; ve(); }
    them("wheel", e, h, { dx: e.deltaX * he, dy: e.deltaY * he, delta_mode: 0 });
  }

  // Bỏ gesture đang dở: KHÔNG gửi `up` (nhả chuột là bước NỘP lần thử — popup không tự làm bước
  // giải nào thay người). `loai` "cuc_bo" = popup tự bỏ; "may_chu" = máy chủ báo `bi_ngat`/từ chối lô.
  function boCuChi(loai, imLang) {
    if (!P || !P.cuChi) return;
    P.cuChi = null;
    if (!imLang) { P.biNgat = { loai }; ve(); }
    // Popup tự bỏ ⇒ máy chủ chưa biết (nó chỉ tự huỷ khi HỤT `seq`): báo bằng lệnh `huy_gesture`, nếu
    // không nút trên trang máy chủ kẹt ở trạng thái nhấn. Máy chủ bỏ thì đã tự huỷ rồi.
    if (loai === "cuc_bo" && dieuKhienDuoc()) baoHuyGesture();
  }

  // Lệnh `huy_gesture` phải tới SAU mọi lô của gesture: lô và lệnh là hai endpoint, lô `down` tới sau
  // lệnh huỷ thì nút lại bị nhấn mà không còn ai huỷ. Nên xả bộ đệm, chờ mọi lô đang bay được trả lời
  // (kể cả thử lại), rồi mới gửi.
  async function baoHuyGesture() {
    const p = P;
    xaLo();
    await Promise.allSettled([...p.loDangBay]);
    for (let lan = 0; lan <= THU_LAI_TOI_DA; lan++) {
      if (P !== p || !dieuKhienDuoc()) return;
      let r;
      try {
        r = await goi("POST", `/jobs/${p.job.id}/giai/lenh`, { token: p.token, lenh: "huy_gesture" });
      } catch (e) {
        await ngu(THU_LAI_CHO_MS * (lan + 1));
        continue;
      }
      if (P !== p) return;
      if (r.matPhien) { matPhien(); return; }
      if (r.ok || r.status === 409) return; // 409: lượt đã đổi / không còn giữ quyền — SSE sẽ báo
      await ngu(THU_LAI_CHO_MS * (lan + 1));
    }
  }

  function xaLo() {
    if (!P) return;
    clearTimeout(P.hen);
    P.hen = null;
    while (P.buf.length) {
      const su_kien = P.buf.splice(0, LO_TOI_DA);
      const bay = guiLo({
        token: P.token, seq: P.seqLo++, khung_w: P.bufKhungW,
        khung_seq: P.bufKhungSeq === null || P.bufKhungSeq === undefined ? null : P.bufKhungSeq,
        su_kien,
      });
      // Theo dõi lô đang bay để `baoHuyGesture` chờ chúng (guiLo không bao giờ ném).
      const dangBay = P.loDangBay;
      dangBay.add(bay);
      bay.finally(() => dangBay.delete(bay));
    }
  }

  async function guiLo(lo) {
    const p = P;
    for (let lan = 0; lan <= THU_LAI_TOI_DA; lan++) {
      let r;
      try {
        r = await goi("POST", `/jobs/${p.job.id}/giai/chuot`, lo);
      } catch (e) {
        await ngu(THU_LAI_CHO_MS * (lan + 1));
        if (P !== p) return;
        continue;
      }
      if (P !== p) return;
      if (r.matPhien) { matPhien(); return; }
      if (r.ok) { if (p.matKetNoi) { p.matKetNoi = false; ve(); } return; }
      if (r.status === 429 || r.status >= 500) { await ngu(THU_LAI_CHO_MS * (lan + 1)); if (P !== p) return; continue; }
      // 400: lô bị bỏ và máy chủ HUỶ gesture dở ⇒ dừng gửi phần còn lại của gesture này (không có
      // `up` mồ côi). 409: không còn giữ quyền / sai trạng thái — luồng SSE sẽ báo ngay.
      // Câu "kéo lại từ đầu" chờ SSE `bi_ngat` (chỉ khi máy chủ thật sự tải lại trang).
      if (r.status === 400) boCuChi("may_chu", true);
      return;
    }
    if (P === p && !p.matKetNoi) { p.matKetNoi = true; ve(); }
  }

  // ------------------------------------------------------------------------
  // Luồng SSE khung ảnh
  // ------------------------------------------------------------------------
  function hienKhung(k) {
    if (!P || !P.anh) { if (P) P.khungMoi = k; return; }
    const anh = P.anh;
    const seq = k.seq;
    // `khung_seq` gửi kèm lô phải là khung ĐANG HIỂN THỊ: chỉ cập nhật khi ảnh mới đã giải mã xong.
    anh.onload = () => { if (P && P.anh === anh && seq >= (P.khungHienSeq || 0)) P.khungHienSeq = seq; };
    anh.src = "data:image/jpeg;base64," + k.jpeg;
  }

  function noiSse() {
    const p = P;
    const es = new EventSource(`/jobs/${p.job.id}/giai/khung?token=${encodeURIComponent(p.token)}`);
    p.es = es;
    const doc = (ev) => { try { return JSON.parse(ev.data); } catch (e) { return null; } };
    es.addEventListener("trang_thai", (ev) => {
      const d = doc(ev);
      if (!d || P !== p) return;
      if (d.vai === "dieu_khien" && p.vai !== "dieu_khien") p.moc = performance.now();
      p.ttGiai = d.trang_thai;
      p.vai = d.vai;
      p.viTri = d.vi_tri || null;
      p.soTaiLai = d.so_lan_tai_lai || 0;
      if (typeof d.con_lai_giay === "number") p.conLai = { giay: d.con_lai_giay, luc: performance.now() };
      if (d.vai !== "dieu_khien") boCuChi("cuc_bo", true);
      p.matKetNoi = false;
      if (d.trang_thai === "dang_giai" && !p.moc) p.moc = performance.now();
      ve();
    });
    es.addEventListener("khung", (ev) => {
      const d = doc(ev);
      if (!d || P !== p || typeof d.jpeg !== "string") return;
      const dauTien = !p.coKhung;
      p.coKhung = true;
      if (dauTien) { p.moc = performance.now(); ve(); }
      hienKhung(d);
    });
    es.addEventListener("bi_ngat", (ev) => {
      const d = doc(ev);
      if (!d || P !== p) return;
      p.soTaiLai = d.so_lan_tai_lai || p.soTaiLai;
      p.cuChi = null;
      p.biNgat = { loai: "may_chu" };
      p.moc = performance.now(); // captcha mới ⇒ đếm lại gợi ý "không thấy captcha"
      ve();
    });
    es.addEventListener("ket_thuc", (ev) => {
      const d = doc(ev);
      if (P === p) ketThuc(d || {});
    });
    es.onerror = () => {
      if (P !== p || p.daKetThuc) return;
      // CONNECTING: EventSource tự nối lại với CÙNG token (máy chủ giữ nguyên số thứ tự lô).
      // CLOSED: máy chủ từ chối hẳn (409/403/404…) hoặc phiên hết hạn ⇒ hỏi lại job.
      if (es.readyState === EventSource.CLOSED) suCoNoiMat();
      else { p.matKetNoi = true; ve(); }
    };
  }

  async function suCoNoiMat() {
    const p = P;
    if (!p || p.daKetThuc) return;
    let r = null;
    try { r = await goi("GET", `/jobs/${p.job.id}`); } catch (e) { r = null; }
    if (P !== p) return;
    if (r && r.matPhien) { matPhien(); return; }
    if (r && r.ok && r.data) { ketThuc({ trang_thai: r.data.trang_thai, ly_do: r.data.ly_do_dung }); return; }
    ketThuc({ trang_thai: null, ly_do: null, khongNoi: true });
  }

  // Lượt giải đã đóng (máy chủ báo `ket_thuc`). Đọc lại job TRƯỚC khi quyết: `running` sau "Đã giải
  // xong" vẫn có thể quay về `cho_xac_minh` ("captcha_chua_xong") vài giây sau.
  async function ketThuc(d) {
    const p = P;
    if (!p || p.daKetThuc) return;
    p.daKetThuc = true;
    dungKetNoi();
    try { await cau.lamMoiJob(); } catch (e) {
      if (e && e.constructor && e.constructor.name === "PhienHetHan") { if (P === p) matPhien(); return; }
    }
    if (P !== p) return;
    const job = cau.layJob(p.job.id) || p.job;
    const tt = d.trang_thai || job.trang_thai;
    if (tt === "cho_xac_minh" || d.khongNoi) {
      const lyDo = d.ly_do || job.ly_do_dung;
      const con = Number.isFinite(Number(job.giai_con_luot)) ? Math.max(0, Number(job.giai_con_luot)) : null;
      if (d.khongNoi) {
        p.panel = { loai: "khac", con, tieuDe: "Mất kết nối tới máy chủ",
          noiDung: "Không đọc được trạng thái lượt này. Đóng cửa sổ rồi xem lại thẻ lượt tải; trang trên máy chủ (nếu còn mở) tự đóng khi hết 5 phút." };
      } else if (lyDo === "het_gio_giai") {
        p.panel = { loai: "het-gio", con };
      } else {
        p.panel = { loai: "khac", con, tieuDe: "Lượt giải đã đóng — job quay lại “Cần xác minh”",
          noiDung: cau.cauLyDo(lyDo) || (lyDo ? `Mã: ${lyDo}` : "") };
      }
      ve();
      return;
    }
    const chu = {
      running: "Đã giải xong — tool đang quét tiếp.",
      failed: d.ly_do === "feed_rong_khong_captcha" ? "Đã dừng job." : "Job đã dừng — xem lý do trên thẻ lượt tải.",
      cancelled: "Lượt tải đã được rút.",
    }[tt] || "Lượt giải đã đóng.";
    dongPopup();
    cau.toast(chu);
  }

  function matPhien() {
    if (!P || P.daDong) return;
    dungKetNoi();
    P.panel = { loai: "dang-nhap-lai" };
    ve();
  }

  function dungKetNoi() {
    if (!P) return;
    if (P.es) { P.es.close(); P.es = null; }
    clearTimeout(P.hen);
    P.hen = null;
    P.buf = []; // popup đã đóng lượt: không gửi nốt gì (nhất là KHÔNG có `up`)
    P.cuChi = null;
  }

  // ------------------------------------------------------------------------
  // Mở / đóng popup
  // ------------------------------------------------------------------------
  function dung(job) {
    const goc = document.createElement("div");
    goc.className = "gc-bg";
    goc.id = "gc-bg";
    goc.innerHTML = `
      <div class="gc-modal" role="dialog" aria-modal="true" aria-labelledby="gc-tieude" tabindex="-1">
        <div class="gc-head">
          <div>
            <h3 id="gc-tieude">Giải xác minh TikTok</h3>
            <div class="gc-sub">Lượt tải #${Number(job.id)} · ${esc(rutGonUrl(job.url))}</div>
          </div>
          <div class="gc-grow"></div>
          <span class="gc-role" id="gc-role" hidden></span>
          <span class="gc-timer" id="gc-timer" role="timer" aria-live="off" hidden></span>
        </div>
        <div class="gc-time-track" id="gc-track" hidden><i id="gc-track-fill"></i></div>
        <div class="gc-note" id="gc-note" role="status"></div>
        <div class="gc-frame-wrap" id="gc-body"></div>
        <div class="gc-actions" id="gc-actions"></div>
        <div class="gc-foot">${IC.khien}<span>Bạn đang xem trang TikTok đăng nhập bằng cookie của chủ job <b>${esc(job.nguoi_tao || "")}</b>. Chỉ dùng để giải xác minh.</span></div>
      </div>`;
    return goc;
  }

  function mo(job) {
    if (P) {
      if (P.job.id !== job.id) cau.toast(`Đang mở cửa sổ giải của lượt #${P.job.id}.`);
      return;
    }
    const goc = dung(job);
    document.body.appendChild(goc);
    document.body.classList.add("gc-lock-scroll");
    P = {
      job, goc, token: taoToken(), es: null, daDong: false, daKetThuc: false, loDangBay: new Set(),
      ttGiai: ["cho_giai", "dang_mo", "dang_giai"].includes(job.trang_thai) ? job.trang_thai : "cho_giai",
      vai: null, viTri: null, soTaiLai: 0, conLai: null, coKhung: false,
      panel: null, biNgat: null, khongThay: false, matKetNoi: false, matKetNoiHan: false,
      dangGuiLenh: false, moc: performance.now(),
      khung: null, anh: null, khungMoi: null, khungHienSeq: null,
      buf: [], hen: null, bufKhungW: null, bufKhungSeq: null, seqLo: 0, cuChi: null, man: null,
      nhip: setInterval(nhipDongHo, 250),
    };
    window.addEventListener("blur", khiMatTieuCu);
    goc.addEventListener("click", khiBam);
    goc.querySelector(".gc-modal").focus();
    ve();
    noiSse();
  }

  function khiMatTieuCu() { boCuChi("cuc_bo"); }

  function nhipDongHo() {
    if (!P) return;
    veDongHo();
    if (dieuKhienDuoc() && !P.cuChi && !P.khongThay && !P.biNgat &&
        performance.now() - P.moc > GOI_Y_KHONG_THAY_SAU_MS) {
      P.khongThay = true;
      ve();
    }
  }

  function dongPopup() {
    if (!P) return;
    const p = P;
    dungKetNoi();
    p.daDong = true;
    clearInterval(p.nhip);
    window.removeEventListener("blur", khiMatTieuCu);
    p.goc.remove();
    document.body.classList.remove("gc-lock-scroll");
    P = null;
  }

  async function khiBam(ev) {
    const nut = ev.target.closest("button");
    if (!nut || nut.disabled || !P) return;
    const p = P;
    if (nut.dataset.lenh) { await guiLenh(nut.dataset.lenh); return; }
    if (nut.hasAttribute("data-dong")) { dongPopup(); return; }
    if (nut.hasAttribute("data-tai-lai-trang")) { window.location.reload(); return; }
    if (nut.hasAttribute("data-giai-lai")) {
      const job = cau.layJob(p.job.id) || p.job;
      dongPopup();
      await giaiNgay(job, null);
    }
  }

  async function guiLenh(lenh) {
    const p = P;
    if (!dieuKhienDuoc() || p.dangGuiLenh) return;
    // Phát nốt những gì người đã nhấn trước khi ra lệnh (máy chủ cũng phát nốt hàng đợi trước lệnh).
    xaLo();
    p.dangGuiLenh = true;
    ve();
    try {
      const r = await goi("POST", `/jobs/${p.job.id}/giai/lenh`, { token: p.token, lenh });
      if (P !== p) return;
      if (r.matPhien) { matPhien(); return; }
      if (r.ok) return; // nút giữ khoá tới `ket_thuc` (SSE) — bấm đúp không gửi lệnh thứ hai
      cau.toast(chiTietLoi(r, "Không gửi được lệnh — thử lại."));
    } catch (e) {
      if (P === p) cau.toast("Không gửi được lệnh — kiểm tra mạng rồi thử lại.");
    }
    if (P === p) { p.dangGuiLenh = false; ve(); }
  }

  // "Tôi giải ngay": `cho_xac_minh` → `cho_giai`, rồi mở popup.
  async function giaiNgay(job, nut) {
    if (P) { if (P.job.id !== job.id) cau.toast(`Đang mở cửa sổ giải của lượt #${P.job.id}.`); return; }
    if (nut) nut.disabled = true;
    try {
      const r = await goi("POST", `/jobs/${job.id}/giai`);
      if (r.matPhien) { cau.baoPhienHetHan(); return; }
      if (!r.ok) {
        cau.toast(chiTietLoi(r, "Không bắt đầu được lượt giải — thử lại."));
        try { await cau.lamMoiJob(); } catch (e) { /* nhịp poll sau sẽ báo phiên hết hạn */ }
        return;
      }
      mo(Object.assign({}, job, { trang_thai: "cho_giai", giai_con_luot: r.data && r.data.giai_con_luot }));
      cau.lamMoiJob().catch(() => {});
    } catch (e) {
      cau.toast("Không gửi được yêu cầu — kiểm tra mạng rồi thử lại.");
    } finally {
      if (nut) nut.disabled = false;
    }
  }

  window.GiaiCaptcha = Object.freeze({
    noiVao(c) { Object.assign(cau, c); },
    mo,
    giaiNgay,
    dangMo: () => !!P,
  });
})();
