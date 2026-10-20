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
  // Id Drive hợp lệ (cùng một khuôn cho link file, link thư mục và ô nhập của đợt sau); sai khuôn ⇒ không dựng link, chỉ hiện chữ.
  const IDRE = /^[A-Za-z0-9_-]{6,120}$/;
  const linkDrive = (id, chu) => {
    if (!IDRE.test(String(id))) return el("span", "", chu);
    const a = el("a", "", chu); a.href = `https://drive.google.com/file/d/${encodeURIComponent(id)}/view`; a.target = "_blank"; a.rel = "noopener"; return a;
  };
  // Hàng cũ trong DB còn lời lỗi kiểu kỹ sư (tên exception, "khung", "agy", "box", "120s)") ⇒ không cho member đọc; hiện câu thường.
  const MAU_KY_SU = /agy|khung|box|Error\)|\(\w+Error|\d+s\)/i;
  const loiText = (chu) => (!chu ? "Lỗi không rõ" : MAU_KY_SU.test(chu) ? "Máy gặp lỗi khi xử lý video này." : chu);
  // Ca "Máy không chắc": `ly_do_may` là chuỗi lõi ghép (duong_ong.py, "N/M watermark không tự thay được: [cụm k] <lý do>; …").
  // Đổi từng lý do sang lời thường theo CHUỖI CON; lõi đổi chữ ⇒ rơi về câu mặc định, không bao giờ in chữ kỹ thuật.
  // Danh sách chuỗi con được khoá bằng test (đọc thẳng duong_ong.py) — thêm lý do mới ở lõi phải thêm dòng ở đây.
  const LY_DO_MAY = [
    [/không có box mồi nào dùng được/, "Máy không tìm thấy logo cũ đủ rõ để bám theo."],
    [/chỉ dò lại được|cụm chỉ có|vết dựng từ/,"Logo cũ chỉ hiện ở quá ít cảnh, máy chưa đủ chắc."],
    [/nhảy loạn/, "Logo cũ đổi chỗ liên tục trong video, máy chưa bám theo được."],
    [/không tách khỏi nền|không dựng được mẫu|học nhầm nội dung/, "Logo cũ mờ hoặc trong suốt, lẫn vào hình nền nên máy dễ nhận nhầm."],
    [/cổng nội dung chặn/, "Logo cũ nằm đè lên mặt người hoặc chữ, máy dừng để không che nhầm."],
    [/không được vết nào phủ/, "Máy thấy logo cũ nhưng không bám theo được qua các cảnh."],
  ];
  const LY_DO_MAC_DINH = "Máy chưa tự thay được, cần người xem.";
  function lyDoDeHieu(chu) {
    if (!chu) return "";
    const ra = [];
    for (const [re, cau] of LY_DO_MAY) if (re.test(chu) && !ra.includes(cau)) ra.push(cau);
    return ra.length ? ra.slice(0, 2).join(" ") : LY_DO_MAC_DINH;
  }
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
  // HỢP ĐỒNG của module:
  //  - `ve(hop, T)` phải IDEMPOTENT: được gọi LẠI mỗi lần người dùng đổi sang tab đó (và khi tính năng tắt) với `hop` đã được xoá
  //    trống; module vẽ lại từ trạng thái của chính nó, không giả định chỉ được gọi một lần.
  //  - Module TỰ ĐỌC `T.tat` (tính năng tắt ⇒ khoá ô/nút của mình); khối nhập chỉ khoá nút "Thay logo" và tab Thư viện.
  //  - `T.nhapChon` (Set) chỉ nhận ID FILE DRIVE (khớp T.IDRE) — máy chủ từ chối id sai khuôn bằng 400 cho cả lượt.
  //    Thêm/bỏ id xong gọi `T.capNhatChan()` để nút "Thay logo" và bộ đếm "Đã chọn N video" cập nhật.
  //  - Bộ đếm trên nhãn tab = số video ĐÃ CHỌN từ tab đó (module khai `dem()`; tab Link = phần còn lại của giỏ); bằng 0 ⇒ ẩn.
  // Tab chưa có module ⇒ "Sắp có".
  window.TL_TAB_NGUON = window.TL_TAB_NGUON || [];

  // Hook sửa THÂN của POST /api/thay-logo/jobs: module nguồn nhập (tab) đẩy một hàm `(than, T) => void` vào mảng này. Khối nhập dựng
  // `than` = {drive_file_ids, ten_bo}, gọi LẦN LƯỢT từng hàm theo thứ tự đăng ký (hàm sửa trực tiếp `than`, vd thêm `vao_bo` và rút
  // id của mình khỏi `drive_file_ids`), rồi mới gửi. Hàm ném lỗi ⇒ không gửi lượt. Hàm phải tự bỏ qua khi tab mình không có gì được chọn.
  window.TL_THAN_POST = window.TL_THAN_POST || [];
  // Hook phụ: POST tạo lượt bị từ chối ⇒ khối nhập phát `document` event "tl-tao-luot-loi" {detail: {status, coVaoBo}} để tab nguồn tải lại
  // dữ liệu của mình (vd danh sách đã cũ). Module tab có thể khai thêm `dem()` ⇒ số trên nhãn tab = số video đã chọn từ tab đó.

  window.TL = {
    $, el, goi, goc, soiKy, phut, IDRE, linkDrive, loiText, lyDoDeHieu, sapCo, nhomCua, phanSo, tenVideo, ngayGio,
    // Lựa chọn của khối nhập — tạo Ở ĐÂY (file nạp đầu tiên), không ở khối nhập: module nguồn nhập (vd tab "Tải từ máy" khôi phục
    // phiên) có thể chạm vào nó từ một lời gọi API trả về TRƯỚC khi thay-logo-khoi-nhap.js kịp chạy (trình duyệt còn đang tải file đó).
    nhapChon: new Set(),
    videos: [], bo: [], daCham: new Map(), dangTaiLoc: false, locTT: new Set(), tat: false, capNhatLuc: 0, moi: [],
    loc: { job: null, nen: "", ngay: "" }, conNua: false, truocTiep: null, thuVienLoi: false,
    // Các module đăng ký hàm vẽ vào đây; veLai() vẽ lại tất cả theo dữ liệu hiện có.
    ve: {},
    veLai() { for (const f of Object.values(window.TL.ve)) f(); },
    loi(chu) { $("tl-loi").textContent = chu || ""; },
    // Lỗi tải danh sách (khác lỗi của form tạo lượt): xoá được khi lần tải sau thành công mà không đụng câu lỗi của form.
    loiTai(chu) { const e = $("tl-loi-tai"); e.textContent = chu || ""; e.hidden = !chu; },
  };
})();
