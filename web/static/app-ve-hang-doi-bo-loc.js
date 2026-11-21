// Vẽ hàng đợi (thẻ gọn + popup chi tiết lượt) và thanh bộ lọc/pill.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // RENDER — hàng đợi
  // ========================================================================
  // "N lượt · X cần bạn · Y đang chạy" (mock B) — tính từ `state.jobs` đã nạp, không gọi thêm API.
  // "Cần bạn" = đang chờ người giải xác minh; "đang chạy" = worker đang tải. Con số 0 thì bỏ cả cụm cho đỡ ồn.
  function tomTatHangDoi(jobs) {
    if (!jobs.length) return "";
    const canBan = jobs.filter((j) => j.trang_thai === "cho_xac_minh").length;
    const dangChay = jobs.filter((j) => j.trang_thai === "running").length;
    return [`${jobs.length} lượt`,
      canBan ? `<b class="can-ban">${canBan} cần bạn</b>` : "",
      dangChay ? `${dangChay} đang chạy` : ""].filter(Boolean).join(" · ");
  }

  function renderQueue() {
    const list = document.getElementById("queue-list");
    const emptyHint = document.getElementById("queue-empty");
    document.getElementById("queue-count").innerHTML = tomTatHangDoi(state.jobs);
    const xemHet = document.getElementById("queue-xem-het");
    if (xemHet) {
      xemHet.hidden = state.jobs.length < 2;
      xemHet.textContent = list.classList.contains("xem-het") ? "Thu gọn" : `Xem tất cả ${state.jobs.length} →`;
    }
    emptyHint.hidden = state.jobs.length > 0;
    // Đang gõ số trong ô "chạy lại" thì KHÔNG vẽ lại: mỗi nhịp poll thay cả
    // `innerHTML` và ô mất focus giữa chừng. Dữ liệu vẫn nạp vào `state.jobs`;
    // hàng đợi vẽ lại ở nhịp poll đầu tiên sau khi rời ô. (Không vẽ lại ngay
    // lúc `focusout`: bấm nút "Chạy lại" làm ô mất focus TRƯỚC khi click tới,
    // vẽ lại lúc đó thay mất nút và làm mất cú bấm.)
    const dangGo = document.activeElement;
    if (dangGo && dangGo.classList && dangGo.classList.contains("chay-lai-n") && list.contains(dangGo)) return;
    list.innerHTML = state.jobs.map(renderQueueItem).join("");
    capNhatPopup();
  }

  // "Xong" cho một job hụt mục tiêu đọc thành thành công.
  //
  // USER CHỐT 21/09: job chạy hết mà không đủ số đã xin phải mang nhãn RIÊNG.
  // Đây cố ý là một phép suy ra Ở GIAO DIỆN, không phải một trạng thái mới
  // trong DB: `trang_thai` là máy trạng thái của worker (`VALID_END_STATES`),
  // còn "thiếu" là một nhận xét về KẾT QUẢ. Nhét nó vào `trang_thai` là đổi
  // máy trạng thái, kéo theo migration và mọi nhánh đang so `== "done"` — đắt
  // hơn nhiều, và lui lại khó hơn nhiều, so với thứ user thật sự xin.
  //
  // Chỉ áp cho `done`: `failed`/`cancelled`/`interrupted` đã có câu chuyện
  // riêng và không được cái nhãn này che mất.
  //
  // Hai nhãn (`bao-thieu.js::nhanThieu`): "Nguồn hụt" khi nguồn cho ít hơn số
  // xin và không có lỗi hệ thống; "Thiếu" khi có lỗi hệ thống hoặc thiếu mà
  // nguồn không giải thích được.
  function nhanTrangThai(job) {
    const thieu = window.BaoThieu.nhanThieu(job);
    if (thieu) return thieu;
    return { chu: STATUS_LABEL[job.trang_thai] || job.trang_thai, lop: job.trang_thai };
  }

  // Ngữ cảnh vẽ thẻ gọn/popup (`the-luot-gon.js`): câu dừng + trạng thái ô "tải thêm" của lượt này.
  // Câu dài KHÔNG lên thẻ — chỉ popup dùng `stopText`.
  function ctxThe(job) {
    // Bốn bước giải xác minh: câu dừng riêng / ẩn câu cũ (`giai-captcha-the-job.js`).
    const GT = window.GiaiCaptchaThe;
    const stopText = GT.anCauDungCu(job) ? ""
      : GT.cauDung(job) || (job.ly_do_dung && !window.BaoThieu.anCauDung(job)
        ? (cauDungTranIp(job, BANG_CAU_DUNG[job.ly_do_dung]) || escapeHtml(cauMaDung(job.ly_do_dung)))
        : "");
    return {
      esc: escapeHtml, chip: nhanTrangThai(job), stopText, taoLuc: fmtDateTime(job.tao_luc),
      mo: state.chayLai.has(job.id) ? state.chayLai.get(job.id) : null,
      dangGuiChayLai: state.dangGuiChayLai.has(job.id), dangGuiTaiLai: state.dangGuiTaiLai.has(job.id),
      hienNhanVideo: state.taiAnhBat === true,   // cờ tải ảnh bật ⇒ lượt video cũng có nhãn "Video" để so với "Ảnh"
    };
  }

  const renderQueueItem = (job) => window.TheLuotGon.theGon(job, ctxThe(job));

  // Popup chi tiết của một lượt (`the-luot-gon.js::popup`). Chỉ vẽ lại khi HTML đổi để nhịp poll không
  // làm mất vị trí cuộn/focus; đang gõ trong ô "tải thêm" của popup thì để yên.
  function capNhatPopup() {
    const scrim = document.getElementById("hn-scrim");
    if (state.popupId === null) return;
    const job = state.jobs.find((j) => j.id === state.popupId);
    if (!job) { dongPopup(false); return; }
    const dangGo = document.activeElement;
    if (dangGo && dangGo.classList && dangGo.classList.contains("chay-lai-n") && scrim.contains(dangGo)) return;
    const html = window.TheLuotGon.popup(job, ctxThe(job));
    if (html === state.popupHtml) return;
    const pop = document.getElementById("hn-pop");
    const giuFocus = pop.contains(dangGo);
    pop.innerHTML = html;
    state.popupHtml = html;
    if (giuFocus && !pop.contains(document.activeElement)) pop.querySelector("[data-hn-dong]").focus();
  }

  function moPopup(id) {
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return;
    state.popupId = id;
    state.popupHtml = "";
    document.getElementById("hn-scrim").hidden = false;
    capNhatPopup();
    document.querySelector("#hn-pop [data-hn-dong]").focus();
  }

  // `traFocus`: trả focus về thẻ (đóng bằng ✕/Esc/nền); false khi đóng để mở việc khác (cửa sổ giải, chia cụm).
  function dongPopup(traFocus) {
    if (state.popupId === null) return;
    const id = state.popupId;
    state.popupId = null;
    state.popupHtml = "";
    document.getElementById("hn-scrim").hidden = true;
    document.getElementById("hn-pop").innerHTML = "";
    if (traFocus !== false) {
      const the = document.getElementById(`job-${id}`);
      if (the) the.focus();
    }
  }

  // ========================================================================
  // RENDER — bộ lọc + pill "đang lọc"
  // ========================================================================
  function renderFilterBar() {
    const bar = document.getElementById("filter-bar");
    bar.innerHTML = FILTER_GROUPS
      .filter((g) => !(g.chiVideo && state.loaiThuVien === "anh"))
      .map(renderFilterBox).join("");
    // Popover đóng khi bấm ra ngoài hoặc Esc — gắn MỘT LẦN, không nhân bản
    // mỗi lần renderFilterBar chạy lại.
  }

  function renderFilterBox(group) {
    const selected = state.filters[group.id];
    return `
      <div class="filter-box" data-group="${group.id}">
        <button type="button" class="filter-trigger" data-toggle="${group.id}" aria-expanded="false">
          ${escapeHtml(group.label)}
          ${selected.size ? `<span class="count">${selected.size}</span>` : ""}
          <span class="caret">▾</span>
        </button>
        <div class="filter-panel" data-panel="${group.id}" hidden></div>
      </div>`;
  }

  function renderFilterPanelBody(group) {
    const panel = document.querySelector(`.filter-panel[data-panel="${group.id}"]`);
    if (!panel) return;
    const buckets = buildBuckets(group);
    if (buckets.length === 0) {
      panel.innerHTML = `<div class="no-options">Chưa có video để lọc</div>`;
      return;
    }
    const selected = state.filters[group.id];
    panel.innerHTML = buckets.map((b) => `
      <label title="${escapeHtml(b.key === UNKNOWN ? "" : (b.title || b.key))}">
        <input type="checkbox" data-group="${group.id}" value="${escapeHtml(b.key)}" ${selected.has(b.key) ? "checked" : ""} />
        ${escapeHtml(b.label)}
        <span class="opt-count">${b.count}</span>
      </label>`).join("");
  }

  function renderActiveFilters() {
    const wrap = document.getElementById("active-filters");
    const pills = [];
    for (const group of FILTER_GROUPS) {
      for (const [key, label] of state.filters[group.id]) {
        pills.push({ groupId: group.id, groupLabel: group.label, key, label });
      }
    }
    wrap.hidden = pills.length === 0;
    if (pills.length === 0) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = pills.map((p) => `
      <span class="pill">${escapeHtml(p.groupLabel)}: ${escapeHtml(p.label)}
        <button type="button" data-remove-group="${p.groupId}" data-remove-key="${escapeHtml(p.key)}" aria-label="Gỡ lọc">✕</button>
      </span>`).join("") +
      `<span class="pill clear-all" id="clear-all-pill">Xoá hết ✕</span>`;
  }
