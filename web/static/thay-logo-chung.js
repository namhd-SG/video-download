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
  // pct_render (0-100) → phân số dễ hiểu ("khoảng 2/3 video"). Chọn k/n (n ≤ 5) gần nhất; ≥ 95 ⇒ gần như cả video.
  function phanSo(pct) {
    if (pct >= 95) return "gần như cả video";
    if (pct <= 5) return "rất ít video";
    let tot = [1, 2];
    for (let n = 2; n <= 5; n++) for (let k = 1; k < n; k++) if (Math.abs(k / n - pct / 100) < Math.abs(tot[0] / tot[1] - pct / 100) - 1e-9) tot = [k, n];
    return `khoảng ${tot[0]}/${tot[1]} video`;
  }
  const tenVideo = (v) => v.ten_video || (window.TL.thuVienLoi ? "Tên video tạm ẩn" : "Video không còn trong thư viện");
  const ngayGio = (giay) => { const d = new Date(giay * 1000), z = (n) => String(n).padStart(2, "0"); return `${z(d.getDate())}/${z(d.getMonth() + 1)} ${z(d.getHours())}:${z(d.getMinutes())}`; };
  const sapCo = (chu) => el("p", "tl-sap-co", chu || "Sắp có — chưa có dữ liệu từ máy chủ.");

  // Nhóm trạng thái dùng cho bộ lọc + cột phải. Mỗi video thuộc đúng một nhóm.
  function nhomCua(v) {
    if (v.trang_thai === "xong") return v.danh_gia === "dat" ? "da_dat" : v.danh_gia === "hong" ? "hong" : "cho_duyet";
    if (v.trang_thai === "cho_nguoi") return "khong_chac";
    if (v.trang_thai === "loi") return "loi";
    return "dang_xu_ly";  // cho · cho_agy · dang_chay
  }

  // Chỗ gắn cho đợt sau: mỗi nguồn nhập mới là MỘT file .js đẩy một module vào mảng này rồi thêm 1 dòng <script> trong thay-logo.html.
  //   window.TL_TAB_NGUON.push({ id: "bo" | "may" | "link", giai: "dòng mô tả", ve(hop, T) { /* vẽ vào hop */ } });
  // Module thêm Drive file id vào `T.nhapChon` (Set) rồi gọi `T.capNhatChan()` để nút "Thay logo" cập nhật. Tab chưa có module ⇒ "Sắp có".
  window.TL_TAB_NGUON = window.TL_TAB_NGUON || [];

  window.TL = {
    $, el, goi, goc, soiKy, phut, linkDrive, sapCo, nhomCua, phanSo, tenVideo, ngayGio,
    videos: [], bo: [], locTT: new Set(), tat: false, capNhatLuc: 0, moi: [],
    loc: { job: null, nen: "", ngay: "" }, conNua: false, truocTiep: null, thuVienLoi: false,
    // Các module đăng ký hàm vẽ vào đây; veLai() vẽ lại tất cả theo dữ liệu hiện có.
    ve: {},
    veLai() { for (const f of Object.values(window.TL.ve)) f(); },
    loi(chu) { $("tl-loi").textContent = chu || ""; },
  };
})();
