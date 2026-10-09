// Trang "Thay logo" — phần dùng chung: trạng thái, gọi API, dựng phần tử. Mọi chữ của dữ liệu vào bằng textContent, không innerHTML.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  async function goi(path, opts) {
    const res = await fetch(path, { redirect: "manual", ...opts });
    if (res.type === "opaqueredirect" || res.status === 401) { $("session-expired").hidden = false; throw new Error("het_phien"); }
    return res;
  }
  const goc = (v) => { try { return (v.nguon && JSON.parse(v.nguon).file_id) || `#${v.id}`; } catch (_) { return `#${v.id}`; } };
  const soiKy = (v) => v.trang_thai === "xong" && !!v.can_soi_ky;
  const phut = (giay) => Math.max(0, Math.round(giay / 60));
  const linkDrive = (id, chu) => { const a = el("a", "", chu); a.href = `https://drive.google.com/file/d/${encodeURIComponent(id)}/view`; a.target = "_blank"; a.rel = "noopener"; return a; };
  const sapCo = (chu) => el("p", "tl-sap-co", chu || "Sắp có — chưa có dữ liệu từ máy chủ.");

  // Nhóm trạng thái dùng cho bộ lọc + cột phải. Mỗi video thuộc đúng một nhóm.
  function nhomCua(v) {
    if (v.trang_thai === "xong") return v.danh_gia === "dat" ? "da_dat" : v.danh_gia === "hong" ? "hong" : "cho_duyet";
    if (v.trang_thai === "cho_nguoi") return "khong_chac";
    if (v.trang_thai === "loi") return "loi";
    return "dang_xu_ly";  // cho · cho_agy · dang_chay
  }

  window.TL = {
    $, el, goi, goc, soiKy, phut, linkDrive, sapCo, nhomCua,
    videos: [], locTT: new Set(), tat: false, capNhatLuc: 0, moi: [],
    // Các module đăng ký hàm vẽ vào đây; veLai() vẽ lại tất cả theo dữ liệu hiện có.
    ve: {},
    veLai() { for (const f of Object.values(window.TL.ve)) f(); },
    loi(chu) { $("tl-loi").textContent = chu || ""; },
  };
})();
