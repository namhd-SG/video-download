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
  // này). Câu chung ở `STOP_REASON_TEXT` (app.js) nói cho ca job `failed`, còn ở đây người đọc
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

  // Khối nút + chú thích dưới dòng tiến độ. "" cho job không ở bước giải. Chỉ nhúng số (id,
  // số lượt) vào HTML — không có chuỗi do người dùng nhập.
  function khungHanhDong(job) {
    if (!laBuocGiai(job.trang_thai)) return "";
    const id = Number(job.id) || 0;
    if (job.trang_thai === "cho_xac_minh") {
      const con = soLuot(job);
      const het = con === 0;
      return `
        <div class="actions">
          <button type="button" class="btn primary nut-giai-ngay" data-giai-ngay="${id}"${het ? " disabled" : ""}>Tôi giải ngay</button>
          <span class="muted giai-luot">${het
            ? `đã dùng đủ ${TRAN_GIAI_NGAY} lần`
            : (con === null ? "" : `còn ${con} lần · `) + "chỉ chủ job hoặc admin"}</span>
        </div>
        <div class="xn-note">Chưa ai giải thì job tự kết thúc sau 24 giờ. Không giải được? Rút lượt để trả hạn mức.</div>`;
    }
    return `
      <div class="actions">
        <button type="button" class="btn primary" data-mo-giai="${id}">Mở cửa sổ giải</button>
        <span class="muted giai-luot">chỉ chủ job hoặc admin</span>
      </div>`;
  }

  // Dòng cuối thẻ (`escapeHtml` do app.js đưa vào). Rút được ở `cho_xac_minh`/`cho_giai` (máy chủ xoá luôn thư mục profile);
  // `dang_mo`/`dang_giai` thì trình duyệt đang mở nên KHÔNG vẽ nút — bấm vào chỉ ra 409.
  function dongCuoi(job, escapeHtml) {
    if (!laBuocGiai(job.trang_thai)) return "";
    let chu;
    let rut = true;
    if (job.trang_thai === "cho_xac_minh") chu = "Đang chờ người giải";
    else if (job.trang_thai === "cho_giai") {
      chu = job.vi_tri
        ? (job.vi_tri === 1 ? "Tiếp theo: máy chủ mở trang giải" : `Thứ ${job.vi_tri}: chờ máy chủ mở trang giải`)
        : "Chờ máy chủ mở trang giải";
    } else {
      rut = false;
      chu = job.trang_thai === "dang_mo" ? "Máy chủ đang mở trang để giải" : "Đang giải xác minh";
    }
    return `
      <div class="queue-line">
        <span class="queue-pos">${escapeHtml(chu)}</span>
        ${rut ? `<button type="button" class="queue-cancel" data-huy="${Number(job.id) || 0}">Rút lượt</button>` : ""}
      </div>`;
  }

  window.GiaiCaptchaThe = Object.freeze({
    NHAN, TRAN_GIAI_NGAY, laBuocGiai, cauDung, anCauDungCu, khungHanhDong, dongCuoi,
  });
})();
