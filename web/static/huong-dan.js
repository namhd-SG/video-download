// Trang Hướng dẫn — điền số và danh sách từ GET /tinh-nang, bảng câu từ hai tệp dùng chung.
//
// Không dùng `app.js` (nó dựng cả trang tải: hàng đợi, thư viện, SSE, vòng poll) — cùng lý do
// `settings.js` không dùng nó. Không chép số nào vào đây: mọi trần đến từ hằng thật ở máy chủ,
// mọi câu đến từ `stop-reason-text.js` / `cookie-status-text.js` mà trang tải cũng đọc.
(() => {
  "use strict";

  const LY_DO = window.STOP_REASON_TEXT || {};
  const MA_COOKIE = window.MA_COOKIE_TRANG_THAI || {};

  // Câu cho từng LOẠI nguồn (`nguon.py::NGUON[i].ten`). Mô tả chính (`mo_ta`) đến từ máy chủ;
  // đây chỉ là ví dụ dạng link để người dùng nhận ra. Loại mới chưa có ví dụ vẫn hiện, chỉ thiếu
  // dòng ví dụ.
  const VI_DU = {
    tiktok: "tiktok.com/music/…, tiktok.com/tag/…, tiktok.com/@tên-kênh, tiktok.com/search?q=…",
    fb_ads: "facebook.com/ads/library/?…",
    drive: "drive.google.com/drive/folders/… (thư mục chia sẻ công khai)",
    youtube_kenh: "youtube.com/@kênh, youtube.com/@kênh/shorts, youtube.com/@kênh/videos, youtube.com/playlist?list=…",
    link_le: "youtube.com/watch?v=…, youtube.com/shorts/…, tiktok.com/@tên/video/…, …",
  };

  class PhienHetHan extends Error {}

  async function apiGet(path) {
    // `redirect: "manual"` — cùng lý do `settings.js`: phiên Access hết hạn trả 302.
    const res = await fetch(path, { redirect: "manual" });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
    return res.json();
  }

  function o(tag, text, cls) {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  function lay(obj, duong) {
    return duong.split(".").reduce((x, k) => (x == null ? undefined : x[k]), obj);
  }

  function veTinhNang(tn) {
    const ten = (nt) => (tn.ten_hien_thi && tn.ten_hien_thi[nt]) || nt;

    const tbody = document.querySelector("#bang-nguon tbody");
    tbody.textContent = "";
    for (const n of tn.nguon) {
      const tr = o("tr");
      tr.append(o("td", n.mo_ta));
      const td = o("td");
      if (VI_DU[n.ten]) td.append(o("code", VI_DU[n.ten]));
      tr.append(td);
      tbody.append(tr);
    }

    const bat = document.getElementById("nen-tang-bat");
    bat.textContent = "";
    for (const nt of tn.nen_tang_bat) bat.append(o("span", ten(nt), "hd-chip"));
    if (!tn.nen_tang_bat.length) bat.textContent = "không có";
    const tat = tn.nen_tang_link_le.filter((nt) => !tn.nen_tang_bat.includes(nt));
    document.getElementById("nen-tang-tat").textContent = tat.length ? tat.map(ten).join(", ") : "không có";
    const tamTat = tn.nen_tang_tam_tat || [];
    document.getElementById("tam-tat").hidden = !tamTat.length;
    document.getElementById("nen-tang-tam-tat").textContent = tamTat.map(ten).join(", ");

    const tran = Object.assign({}, tn.tran, {
      thoi_luong_video_phut: Math.round(tn.tran.thoi_luong_video_giay / 60),
    });
    for (const el of document.querySelectorAll("[data-tran]")) {
      const v = lay(tran, el.dataset.tran);
      el.textContent = v == null ? "?" : String(v);
    }

    // Trần IP chỉ cho nền tảng ĐANG BẬT; nền tảng tắt không gọi được nên số của nó không nói gì.
    const ip = document.getElementById("tran-ip");
    ip.textContent = "";
    const dong = tn.nen_tang_bat
      .filter((nt) => tn.tran.ip_moi_nen_tang[nt])
      .map((nt) => `${ten(nt)}: ${tn.tran.ip_moi_nen_tang[nt].gio} lượt/giờ, ${tn.tran.ip_moi_nen_tang[nt].ngay} lượt/ngày`);
    ip.textContent = dong.length ? dong.join(" · ") : "không có nền tảng nào ngoài TikTok đang bật";
  }

  function veBangCau(tbodySel, bang) {
    const tbody = document.querySelector(tbodySel);
    tbody.textContent = "";
    for (const [ma, cau] of Object.entries(bang)) {
      const tr = o("tr");
      tr.dataset.tim = `${ma} ${cau}`.toLowerCase();
      tr.append(o("td", ma, "hd-ma"), o("td", cau));
      tbody.append(tr);
    }
  }

  function noiTim() {
    const oTim = document.getElementById("tim-ly-do");
    oTim.addEventListener("input", () => {
      const q = oTim.value.trim().toLowerCase();
      for (const tr of document.querySelectorAll("#bang-ly-do tbody tr")) {
        tr.hidden = q !== "" && !tr.dataset.tim.includes(q);
      }
    });
  }

  // ----------------------------------------------------------------- theme
  // Cùng khoá với trang tải và trang Cài đặt để lựa chọn sáng/tối đi theo người dùng qua mọi trang.
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
  veBangCau("#bang-ly-do tbody", LY_DO);
  veBangCau("#bang-cookie tbody", MA_COOKIE);
  noiTim();
  apiGet("/tinh-nang").then(veTinhNang).catch((err) => {
    if (err instanceof PhienHetHan) {
      document.getElementById("session-expired").hidden = false;
      return;
    }
    document.getElementById("tn-loi").hidden = false;
  });
})();
