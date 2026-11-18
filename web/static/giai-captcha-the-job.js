// Thẻ job ở bốn bước "giải xác minh trong popup" (`cho_xac_minh`, `cho_giai`, `dang_mo`,
// `dang_giai`). Thuần (không đụng DOM, không gọi mạng) — cùng khuôn `bao-thieu.js`.
//
// Hợp đồng và máy trạng thái: docstring `web/giai_captcha.py`. Cờ `VIDEODL_PROFILE_CAPTCHA`
// TẮT thì không job nào ở các bước này (boot sweep đưa chúng về `interrupted`), nên thẻ job
// của mọi job còn lại KHÔNG đổi một ký tự: không nhãn mới, không nút mới.
//
// Plan: plans/261002-1505-video-desk-captcha-headful/plan.md §3, §6.
(function () {
  "use strict";

  const NHAN = Object.freeze({
    cho_xac_minh: "Cần xác minh",
    cho_giai: "Chờ mở trang giải",
    dang_mo: "Đang mở trang giải",
    dang_giai: "Đang giải",
  });

  // Trần "Tôi giải ngay" mỗi job = `TRAN_GIAI_NGAY` ở web/giai_captcha.py (chỉ để viết câu chữ;
  // số còn lại thật do máy chủ trả ở `giai_con_luot`).
  const TRAN_GIAI_NGAY = 3;

  const laBuocGiai = (tt) => Object.prototype.hasOwnProperty.call(NHAN, tt);

  // Câu cho thẻ `cho_xac_minh` khi mã lý do là "TikTok đòi xác minh" (cả hai mã vào trạng thái
  // này). Câu chung ở `STOP_REASON_TEXT` (stop-reason-text.js) nói cho ca job `failed`, còn ở đây người đọc
  // đang nhìn nút "Tôi giải ngay" nên câu phải trỏ tới nút đó.
  const CAU_DOI_XAC_MINH =
    "TikTok đòi xác minh trước khi cho xem danh sách video của trang này. " +
    "Tool đã dừng quét và chờ người giải — không tự giải.";
  const MA_DOI_XAC_MINH = new Set(["feed_rong", "khong_do_duoc_feed"]);

  // Câu dừng riêng cho thẻ ở bước giải; "" = không có (để app.js dùng bảng chung).
  // `ly_do_dung` KHÔNG bị xoá khi job đi tiếp sang `cho_giai`/`dang_*` (giữ lý do lần trước), và
  // job bị rút (`cancelled`) cũng giữ nó ⇒ hiện nó ở các thẻ đó là nói một chuyện đã cũ.
  function cauDung(job) {
    if (job.trang_thai === "cho_xac_minh" && MA_DOI_XAC_MINH.has(job.ly_do_dung)) return CAU_DOI_XAC_MINH;
    return "";
  }

  function anCauDungCu(job) {
    return job.trang_thai === "cho_giai" || job.trang_thai === "dang_mo" ||
      job.trang_thai === "dang_giai" || job.trang_thai === "cancelled";
  }

  const soLuot = (job) => {
    const n = Number(job.giai_con_luot);
    return Number.isFinite(n) ? Math.max(0, n) : null;
  };

  // NGUỒN DUY NHẤT của nút giải trên thẻ gọn VÀ popup chi tiết (`the-luot-gon.js` gọi, không tự vẽ):
  // `{ nut, ghi }` — `nut` = MỘT nút ("Xác minh" mang `data-giai-ngay` ở `cho_xac_minh`, "Mở cửa sổ giải"
  // mang `data-mo-giai` ở 3 bước sau) để đứng chung hàng nút của thẻ; `ghi` = chú thích số lượt cho popup.
  // `sm` = nút cỡ nhỏ (thẻ). Job không ở bước giải ⇒ `{ nut: "", ghi: "" }`. Chỉ nhúng số (id, số lượt).
  function khungHanhDong(job, sm) {
    if (!laBuocGiai(job.trang_thai)) return { nut: "", ghi: "" };
    const id = Number(job.id) || 0;
    const z = sm ? " sm" : "";
    if (job.trang_thai === "cho_xac_minh") {
      const con = soLuot(job);
      const het = con === 0;
      return {
        nut: `<button type="button" class="btn${z} primary nut-giai-ngay" data-giai-ngay="${id}"${het ? " disabled" : ""}>Xác minh</button>`,
        ghi: `<span class="muted giai-luot">${het
          ? `đã dùng đủ ${TRAN_GIAI_NGAY} lần`
          : (con === null ? "" : `còn ${con} lần · `) + "chỉ chủ job hoặc admin"}</span>`,
      };
    }
    return {
      nut: `<button type="button" class="btn${z} primary" data-mo-giai="${id}">Mở cửa sổ giải</button>`,
      ghi: `<span class="muted giai-luot">chỉ chủ job hoặc admin</span>`,
    };
  }

  window.GiaiCaptchaThe = Object.freeze({
    NHAN, TRAN_GIAI_NGAY, laBuocGiai, cauDung, anCauDungCu, khungHanhDong,
  });
})();
