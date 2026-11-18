// Màn "tự chia cụm" — phần VẼ: state phía client (`CC`), dữ liệu dẫn xuất và mọi hàm dựng HTML.
// Tách khỏi `chia-cum.js` (thao tác + sự kiện). Chỉ đọc `CC` + `escapeHtml`, không gọi server.
// NẠP TRƯỚC `chia-cum.js` (tệp đó lấy `CC`, `render`, `nhomsOf`, `tachTenXem` từ `window.ChiaCumVe`).
(() => {
  "use strict";

  const { escapeHtml } = window.VDChung;

  const AXES = [
    { v: "trang_phuc_dam_dong", label: "Trang phục đám đông" },
    { v: "trang_phuc_nguoi_chinh", label: "Trang phục người chính" },
    { v: "boi_canh", label: "Bối cảnh" },
  ];
  const AXIS_LABEL = Object.fromEntries(AXES.map((a) => [a.v, a.label]));

  // Trạng thái phía client — CHỈ để nhớ "đang mở job nào" + "đang chọn gì" +
  // "popover/modal nào đang mở". Dữ liệu THẬT luôn tới từ server sau mỗi lần
  // vẽ lại (`CC.data` là bản sao MỚI NHẤT của GET /chia/{job_id}).
  const CC = {
    open: false,
    jobId: null,
    job: null,      // GET /jobs/{id}
    data: null,     // GET /chia/{job_id} — null khi 404 (chưa có lượt chia)
    cums: [],       // GET /cum → .cum — cụm CỦA NGƯỜI XEM
    selected: new Set(),   // video_id đang chọn (dock, bất kể đang ở làn nào)
    popover: null,  // {type:"gop"|"chuyen"|"traVe", key} — key phân biệt nút nào mở popover
    modal: null,    // {type:"tach"|"huy"|"trung", ...}
    axis: "trang_phuc_dam_dong",
  };

  // ==========================================================================
  // Dữ liệu dẫn xuất
  // ==========================================================================
  function chuaCoNhap() {
    return !CC.data || CC.data.trang_thai === "cho_hinh" || CC.data.trang_thai === "huy";
  }

  // Lượt đã duyệt: server từ chối MỌI thao tác sửa nháp (`models_chia.
  // _kiem_trang_thai_de_xuat`, có chủ ý — sửa sau duyệt hồi sinh nháp trong một
  // lượt đã chốt). Trang không vẽ bất kỳ nút/ô sửa nháp nào ở trạng thái này:
  // một nút chắc chắn bị từ chối chỉ để người dùng bấm hoài vào lỗi 400.
  function daDuyet() {
    return !!CC.data && CC.data.trang_thai === "da_duyet";
  }

  function insightTrong() {
    const d = CC.data;
    return !d || !(d.usecase || "").trim() || !(d.insight_goc || "").trim();
  }

  function nhomsOf(data) {
    const seen = [];
    for (const k of data.kieu) if (!seen.includes(k.nhom)) seen.push(k.nhom);
    return seen;
  }

  function baselineChiaTay(data) {
    const soKieu = data.kieu.reduce((s, k) => s + k.video_ids.length, 0);
    return soKieu + data.huong_dan.length + data.nghi.length + data.bi_bo.length;
  }

  // Tên cụm THẬT lúc duyệt = "<insight gốc> <ten_cum hoặc kiểu>" (server:
  // `models_cum.ten_insight_con`, gọi trên `ten_cum or kieu` —
  // `models_chia.py::_giai_quyet_kieu`). `ten_cum` bản thân KHÔNG mang
  // insight gốc (`_chot_ten_moi_kieu` chỉ ghép nhóm khi trùng tên, xem
  // docstring `_giai_va_cham_ten`) — ghép ở đây phải khớp ĐÚNG hai bước đó,
  // không phải hiển thị thẳng `ten_cum`.
  function tenCumDay(k) {
    return `${CC.data.insight_goc} ${k.ten_cum || k.kieu}`.trim().replace(/\s+/g, " ");
  }

  function tenCumHien(k) {
    if (insightTrong()) return `<i class="cc-faint">(insight gốc) ${escapeHtml(k.kieu)}</i>`;
    return escapeHtml(tenCumDay(k));
  }

  function trungCumCoSan(k) {
    if (insightTrong()) return null;
    // Cùng khoá so trùng server dùng (`models_cum._khoa_ten`): CẢ usecase VÀ
    // insight con (chuẩn hoá khoảng trắng + casefold) — thiếu vế usecase thì
    // nhãn này dán "sẽ hỏi gộp" cho một cặp khác usecase, trong khi server sẽ
    // tự tạo cụm MỚI (không hỏi gộp), làm rail "Cụm của tôi" có 2 cụm trùng
    // tên insight nhưng khác usecase.
    const khoa = (s) => (s || "").trim().replace(/\s+/g, " ").toLowerCase();
    const usecaseTa = khoa(CC.data.usecase);
    const insightTa = khoa(tenCumDay(k));
    return CC.cums.find((c) => khoa(c.usecase) === usecaseTa && khoa(c.insight) === insightTa)
      || null;
  }

  // Xem trước tên cụm trong modal "Kiểu mới từ chọn" — CHỈ để hiển thị (ước
  // lượng "<insight gốc> <kiểu mới gõ>"); tên THẬT tính lúc `tach`/`doi_ten`
  // chạy trên server (có thể ghép nhóm khi trùng, D19) nên không luôn khớp
  // tuyệt đối, nhưng khớp trong mọi ca không va chạm — cùng cách mock hiện.
  function tachTenXem() {
    const insightGoc = CC.data && CC.data.insight_goc ? CC.data.insight_goc : "(insight gốc)";
    return `${insightGoc} ${(CC.modal && CC.modal.kieu) || ""}`.trim();
  }

  // ==========================================================================
  // RENDER
  // ==========================================================================
  function render() {
    renderHeader();
    renderRail();
    renderMain();
    renderDock();
    renderModal();
  }

  function renderHeader() {
    const empty = chuaCoNhap();
    const data = CC.data;
    const ctx = document.getElementById("cc-context");
    // Tiêu đề lớn "Chia cụm #nauan" (mock B): nhãn lấy từ link nguồn của lượt (tag/@kênh/tên miền), thiếu thì mã lượt.
    const nhanNguon = (() => {
      try {
        const u = new URL(CC.job.url);
        const doan = u.pathname.split("/").filter(Boolean);
        const cuoi = decodeURIComponent(doan[doan.length - 1] || "");
        if (doan[0] === "tag" && cuoi) return "#" + cuoi;
        if (cuoi.startsWith("@")) return cuoi;
        return cuoi || u.hostname.replace(/^www\./, "");
      } catch (_) { return CC.job ? "#" + CC.job.id : ""; }
    })();
    const h1 = document.getElementById("cc-h1");
    if (h1) h1.textContent = CC.job ? `Chia cụm ${nhanNguon}` : "Chia cụm";
    ctx.textContent = CC.job ? `Lượt tải #${CC.job.id} · ${CC.job.tong} video` : "";

    const tieude = document.getElementById("cc-tieude");
    if (empty) {
      tieude.textContent = "Chưa chia cụm";
    } else {
      // Kiểu rỗng (xem `kieuBlockHtml`) không tính vào số kiểu đã chia. Số
      // nhóm vẫn đếm mọi nhóm đang vẽ thẻ — nhóm chỉ còn kiểu rỗng vẫn hiện
      // (để bấm "Xoá kiểu"), nên tiêu đề phải khớp số thẻ trên màn.
      const kieuCoVideo = data.kieu.filter((k) => k.video_ids.length);
      const nNhom = new Set(nhomsOf(data)).size;
      const hau = data.trang_thai === "da_duyet" ? "— đã duyệt" : "— bản nháp";
      tieude.textContent =
        `Hệ đã chia thành ${nNhom} nhóm · ${kieuCoVideo.length} kiểu + làn riêng ` +
        `(thẻ chữ ${data.huong_dan.length} · nghi ${data.nghi.length}) ${hau}`;
    }

    const trangThai = document.getElementById("cc-trangthai");
    if (!CC.data || CC.data.trang_thai === "cho_hinh") {
      trangThai.innerHTML = `<span class="chip cc-chip-nhap">Chưa phân tích hình — tầng hình chạy từ máy ` +
        `dev, người dùng bấm tay (không 24/7).</span>`;
    } else if (CC.data.trang_thai === "huy") {
      trangThai.innerHTML = `<span class="chip cc-chip-nhap">Lượt đã huỷ — chạy lệnh dưới đây để chia lại.</span>`;
    } else if (CC.data.trang_thai === "da_duyet") {
      trangThai.innerHTML = `<span class="chip cc-chip-ok"><b>Đã duyệt</b></span>`;
    } else {
      trangThai.innerHTML = `<span class="chip cc-chip-nhap"><b>Nháp</b> chưa vào taxonomy · ` +
        `“Tạo bộ” khoá tới khi duyệt</span>`;
    }

    const fields = document.getElementById("cc-fields");
    const tr = insightTrong();
    // Hai ô usecase/insight gốc gửi MỘT `doi_insight` MỖI ô blur (`change`) —
    // refresh() SAU cú của Ô NÀY không được đè lên nội dung Ô KIA nếu người
    // dùng còn đang gõ dở nó (chưa blur, response của ô đầu tới trong lúc ô
    // sau còn focus): thay `fields.innerHTML` bằng dữ liệu SERVER lúc đó sẽ
    // xoá mất bản gõ chưa gửi VÀ cướp mất focus khỏi ô đang gõ. Bỏ qua HẲN
    // việc vẽ lại khối này khi một trong hai ô đang có focus — lượt render
    // kế tiếp (sau khi người dùng blur) sẽ vẽ lại đúng giá trị mới nhất.
    const dangGoODoNao = document.activeElement instanceof HTMLElement
      && fields.contains(document.activeElement)
      && document.activeElement.matches('[data-cc-field]');
    if (dangGoODoNao) {
      // không đụng DOM — giữ nguyên nội dung + focus người dùng đang gõ.
    } else if (empty) {
      fields.innerHTML = "";
    } else {
      const axisLabel = AXIS_LABEL[data.truc] || data.truc || "(chưa đặt)";
      // Đã duyệt ⇒ ô chỉ đọc: đổi ở đây là một `doi_insight` mà server từ chối.
      const khoa = daDuyet() ? ' disabled title="Lượt đã duyệt — tên cụm đã chốt"' : "";
      fields.innerHTML = `
        <label>Usecase<input type="text" class="${tr ? "cc-trong" : ""}" data-cc-field="usecase"
          placeholder="vd Motion" value="${escapeHtml(data.usecase || "")}"${khoa}></label>
        <label>Insight gốc<input type="text" class="${tr ? "cc-trong" : ""}" data-cc-field="insight_goc"
          placeholder="vd Strom Ai" value="${escapeHtml(data.insight_goc || "")}"${khoa}></label>
        <label>Chia theo<select disabled title="Đổi trục = chia lại (Hủy lượt)">
          <option>${escapeHtml(axisLabel)}</option></select></label>`;
    }

    const nut = document.getElementById("cc-nut");
    if (empty) {
      nut.innerHTML = "";
    } else if (data.trang_thai === "da_duyet") {
      nut.innerHTML = `<span class="cc-faint cc-mono">${data.so_thao_tac} thao tác sửa · ` +
        `so với ${baselineChiaTay(data)} nếu chia tay</span>`;
    } else {
      nut.innerHTML = `
        <button type="button" class="btn primary" data-cc-action="duyet-het" ${tr ? "disabled" : ""}>
          Duyệt tất cả còn lại</button>
        ${tr ? `<div class="cc-why">Điền <b>usecase</b> và <b>insight gốc</b> để duyệt — tên cụm = ` +
               `“&lt;insight gốc&gt; &lt;kiểu&gt;”.</div>` : ""}
        <button type="button" class="btn" data-cc-action="mo-huy">Hủy lượt để chia lại…</button>
        <button type="button" class="btn ghost" data-cc-action="hoan-tac" ${data.co_the_hoan_tac ? "" : 'disabled title="Chưa có thao tác sửa nào để hoàn tác"'}>Hoàn tác</button>
        <span class="cc-faint cc-mono">${data.so_thao_tac} thao tác sửa · ` +
        `so với ${baselineChiaTay(data)} nếu chia tay</span>`;
    }
  }

  function renderRail() {
    const rail = document.getElementById("cc-rail");
    let r = "<h3>Nhóm · kiểu</h3>";
    if (chuaCoNhap()) {
      r += `<div class="cc-ri"><span>Chưa vào cụm</span><span class="cc-n">${CC.job ? CC.job.tong : 0}</span></div>`;
    } else {
      const data = CC.data;
      for (const nhom of nhomsOf(data)) {
        const ks = data.kieu.filter((k) => k.nhom === nhom);
        const tong = ks.reduce((s, k) => s + k.video_ids.length, 0);
        r += `<div class="cc-ri"><span>${escapeHtml(nhom)}</span><span class="cc-n">${tong}</span></div>`;
        for (const k of ks) {
          if (!k.video_ids.length) continue;   // kiểu rỗng: không có gì để dẫn tới
          r += `<div class="cc-ri cc-sub"><span>${escapeHtml(k.kieu)}</span>` +
               `<span class="cc-n">${k.video_ids.length}</span></div>`;
        }
      }
      r += `<hr class="rail-sep"><h3>Làn riêng</h3>` +
        `<div class="cc-ri cc-lan"><span>Hướng dẫn / thẻ chữ</span><span class="cc-n">${data.huong_dan.length}</span></div>` +
        `<div class="cc-ri cc-lan"><span>Nghi ngoài chủ đề</span><span class="cc-n">${data.nghi.length}</span></div>`;
    }
    r += `<hr class="rail-sep"><h3>Cụm của tôi (đã có)</h3>`;
    if (CC.cums.length === 0) {
      r += `<div class="cc-faint">Chưa có cụm nào.</div>`;
    } else {
      r += CC.cums.map((c) =>
        `<div class="cc-ri"><span>${escapeHtml(c.insight)}</span><span class="cc-n">${c.so_video}</span></div>`
      ).join("");
    }
    rail.innerHTML = r;
  }

  // `laLanLoai`: làn Hướng dẫn / Nghi — nơi DUY NHẤT người dùng loại video
  // (user chốt 28/09). Làn này chọn được cả khi lượt đã duyệt (loại là thao
  // tác THƯ VIỆN, không phải sửa nháp) và có ô tích rõ; mọi nơi khác, lượt đã
  // duyệt ⇒ không chọn được (không còn thao tác nào trên tập chọn).
  function thumbsHtml(videoIds, laLanLoai = false) {
    if (videoIds.length === 0) return "";
    const chonDuoc = laLanLoai || !daDuyet();
    return `<div class="cc-luoi">` + videoIds.map((vid) => {
      const sel = chonDuoc && CC.selected.has(vid);
      return `<div class="cc-t${sel ? " sel" : ""}${laLanLoai ? " cc-t-loai" : ""}"` +
        (chonDuoc ? ` data-cc-video="${escapeHtml(vid)}"` : "") + `>` +
        `<img src="/thumbs/${escapeHtml(vid)}" loading="lazy" alt="">` +
        (laLanLoai ? `<span class="cc-chk" aria-hidden="true">${sel ? "✓" : ""}</span>` : "") + `</div>`;
    }).join("") + `</div>`;
  }

  /** Nút "Loại N video đã chọn…" của một làn (N = đã chọn ∩ video của làn). */
  function nutLoaiHtml(lan, videoIds) {
    const n = videoIds.filter((v) => CC.selected.has(v)).length;
    // Đang gửi một lượt Loại: khoá nút — bấm lại lúc này sẽ gửi lần hai các id
    // đã loại và server trả chúng là "không phải của bạn" (báo sai).
    if (CC.dangLoai) {
      return `<button type="button" class="btn danger" disabled data-cc-loai-dang-gui="${lan}">Đang loại…</button>`;
    }
    return n
      ? `<button type="button" class="btn danger" data-cc-action="loai-lan" data-lan="${lan}">Loại ${n} video đã chọn…</button>`
      : `<button type="button" class="btn danger" disabled data-cc-loai-trong="${lan}">Chọn video để loại</button>`;
  }

  function kieuBlockHtml(k) {
    const tr = insightTrong();
    const trung = trungCumCoSan(k);
    const trungTag = trung
      ? `<span class="cc-tag cc-tag-nhap" title="D13: server hỏi trước khi gộp">trùng cụm có sẵn — duyệt sẽ hỏi gộp</span>`
      : "";
    const popKey = `gop-${k.cum_nhap_id}`;
    if (daDuyet()) {
      return `
      <div class="cc-kieu" data-cum-nhap-id="${k.cum_nhap_id}">
        <div class="cc-kieu-h">
          <b class="cc-ten">${escapeHtml(k.kieu)}</b>
          <span class="cc-faint">${k.video_ids.length} video · tên cụm: ${tenCumHien(k)}</span>
        </div>
        ${thumbsHtml(k.video_ids)}
      </div>`;
    }
    // Kiểu RỖNG: mọi video của nó đã bị loại hoặc đã vào cụm thật (lọc ở
    // `models_chia.lay_chia`). Duyệt nó không tạo cụm nào (server trả
    // `cum_id=null`) ⇒ không vẽ duyệt/gộp/tạo bộ, chỉ còn đường "Xoá kiểu"
    // (hoàn tác được).
    if (!k.video_ids.length) {
      // MỌI kiểu còn lại đều rỗng: xoá kiểu cuối để lượt kẹt ở `de_xuat` với 0
      // kiểu (server không tự đóng lượt khi xoá). "Duyệt tất cả" lúc kiểu rỗng
      // còn đó thì đóng lượt đúng ⇒ chỉ sang nút đó thay vì "Xoá kiểu".
      const toanRong = CC.data.kieu.every((x) => !x.video_ids.length);
      const bao = toanRong
        ? "Các kiểu còn lại không còn video — bấm Duyệt tất cả để đóng lượt."
        : "Kiểu này không còn video (đã loại hoặc đã vào cụm) — bấm Xoá kiểu.";
      return `
      <div class="cc-kieu" data-cum-nhap-id="${k.cum_nhap_id}" data-cc-kieu-rong>
        <div class="cc-kieu-h">
          <b class="cc-ten">${escapeHtml(k.kieu)}</b>
          <span class="cc-faint">${bao}</span>
          <span class="cc-sp"></span>
          <button type="button" class="btn ghost" data-cc-action="xoa-kieu"
            data-cum-nhap-id="${k.cum_nhap_id}">Xoá kiểu</button>
        </div>
      </div>`;
    }
    return `
      <div class="cc-kieu" data-cum-nhap-id="${k.cum_nhap_id}">
        <div class="cc-kieu-h">
          <input class="cc-ten" data-cc-kieu-rename="${k.cum_nhap_id}" value="${escapeHtml(k.kieu)}">
          <span class="cc-faint">${k.video_ids.length} video · tên cụm: ${tenCumHien(k)}</span>
          ${trungTag}
          <span class="cc-sp"></span>
          <span class="pop-wrap">
            <div class="popover" data-cc-popover="${popKey}" hidden></div>
            <button type="button" class="btn ghost" data-cc-action="toggle-gop"
              data-cum-nhap-id="${k.cum_nhap_id}" ${tr ? 'disabled title="Điền insight gốc trước (D18)"' : ""}>
              Gộp vào cụm có sẵn ▾</button>
          </span>
          <button type="button" class="btn ghost" data-cc-action="xoa-kieu"
            data-cum-nhap-id="${k.cum_nhap_id}">Xoá kiểu</button>
          <button type="button" class="btn" data-cc-action="duyet-kieu"
            data-cum-nhap-id="${k.cum_nhap_id}" ${tr ? 'disabled title="Điền insight gốc trước"' : ""}>
            Duyệt kiểu này</button>
          <button type="button" class="btn" disabled title="Nháp chưa duyệt: server từ chối">
            Tạo bộ tự tìm (${k.video_ids.length})</button>
        </div>
        ${thumbsHtml(k.video_ids)}
      </div>`;
  }

  function kieuPickerPopoverHtml(action, data) {
    if (data.kieu.length === 0) {
      return `<div class="cc-faint" style="padding:6px 8px">Chưa có kiểu nào trong lượt này.</div>`;
    }
    return data.kieu.map((k) =>
      `<div data-cc-action="${action}" data-cum-nhap-id="${k.cum_nhap_id}">` +
      `${escapeHtml(k.nhom)} · <b>${escapeHtml(k.kieu)}</b> ` +
      `<span class="cc-faint">· ${k.video_ids.length} video</span></div>`
    ).join("");
  }

  function renderMain() {
    const main = document.getElementById("cc-main");
    if (chuaCoNhap()) {
      const cmd = CC.data === null
        ? ["bash", "scripts/phan-tich-hinh.sh", "--luot", String(CC.jobId)]
        : ["bash", "scripts/phan-tich-hinh.sh", "--luot", String(CC.jobId), "--truc", CC.axis];
      main.innerHTML = `
        <div class="card cc-empty">
          <h2>Chưa phân tích hình</h2>
          <p class="muted">${CC.job ? CC.job.tong : 0} video đã tải. Hệ chưa chia cụm vì tầng hình chưa chạy. ` +
            `Chạy lệnh này trên máy dev (thử khô trước, thêm <code>--yes</code> để làm thật):</p>
          ${cmdHtml(cmd)}
          <p class="cc-faint">Không có nút chạy ở đây: máy chủ không tự gọi được tầng hình.</p>
        </div>`;
      return;
    }
    const data = CC.data;
    const duyet = daDuyet();
    let m = duyet
      ? `<div class="card cc-note" data-cc-da-duyet>Lượt đã duyệt — video đã vào cụm; sửa ở “Cụm của tôi”.</div>`
      : "";
    for (const nhom of nhomsOf(data)) {
      const ks = data.kieu.filter((k) => k.nhom === nhom);
      const tong = ks.reduce((s, k) => s + k.video_ids.length, 0);
      m += `<div class="card cc-nhom" data-cc-nhom="${escapeHtml(nhom)}">
        <div class="cc-nhom-h">
          ${duyet ? `<b class="cc-ten">${escapeHtml(nhom)}</b>`
            : `<input class="cc-ten" data-cc-nhom-rename data-cc-nhom-cur="${escapeHtml(nhom)}" value="${escapeHtml(nhom)}">
          <span class="chip cc-chip-nhap">đề xuất</span>`}
          <span class="muted">${tong} video · ${ks.filter((k) => k.video_ids.length).length} kiểu</span>
          <span class="cc-sp"></span>
          ${!duyet && ks.filter((k) => k.video_ids.length).length > 1 ? `<button type="button" class="btn" data-cc-action="gop-nhom" ` +
            `data-nhom="${escapeHtml(nhom)}">Gộp cả nhóm thành 1 kiểu</button>` : ""}
        </div>
        ${ks.map(kieuBlockHtml).join("")}
      </div>`;
    }
    m += `<div class="card cc-nhom cc-lan">
      <div class="cc-nhom-h"><b>Hướng dẫn / thẻ chữ</b><span class="muted">${data.huong_dan.length} video</span>
        <span class="cc-sp"></span>
        ${duyet ? "" : `<button type="button" class="btn" data-cc-action="hd-thanh-kieu">Thành kiểu “Hướng dẫn”</button>
        <button type="button" class="btn" data-cc-action="hd-ngoai-chu-de">Đánh dấu ngoài chủ đề</button>`}
        ${nutLoaiHtml("huong_dan", data.huong_dan)}
      </div>
      ${thumbsHtml(data.huong_dan, true)}
    </div>`;
    m += `<div class="card cc-nhom cc-lan">
      <div class="cc-nhom-h"><b>Nghi ngoài chủ đề</b>
        <span class="muted">${data.nghi.length} video · máy không tự xoá, không tự ẩn · không bao giờ vào bộ</span>
        <span class="cc-sp"></span>
        ${duyet ? "" : `<span class="pop-wrap">
          <div class="popover" data-cc-popover="traVe" hidden></div>
          <button type="button" class="btn" data-cc-action="toggle-tra-ve">Không, trả về kiểu…</button>
        </span>`}
        ${nutLoaiHtml("nghi", data.nghi)}
      </div>
      <div class="cc-note">Video ở làn này không vào cụm nào khi duyệt. Vì sao nghi: tầng hình xếp ` +
        `“không có đám đông / không thuộc kiểu nào”, hoặc caption lệch chủ đề. Caption chỉ được TĂNG ` +
        `nghi, không gỡ nghi.</div>
      ${thumbsHtml(data.nghi, true)}
    </div>`;
    main.innerHTML = m;

    // Popover nội dung được vẽ SAU khi khung đã có mặt trong DOM (chọn theo
    // data-cc-popover) — tránh phải escape lồng nhau trong template ở trên.
    for (const k of data.kieu) {
      const el = main.querySelector(`[data-cc-popover="gop-${k.cum_nhap_id}"]`);
      if (el) {
        el.innerHTML = `<div class="cc-faint" style="padding:4px 6px">Duyệt “${escapeHtml(k.kieu)}” bằng cách ` +
          `gộp ${k.video_ids.length} video vào một cụm có sẵn của bạn (khác tên vẫn được):</div>` +
          (CC.cums.length === 0 ? `<div class="cc-faint" style="padding:4px 6px">Chưa có cụm nào.</div>` :
            CC.cums.map((c) => `<div data-cc-action="gop-vao-cum" data-cum-nhap-id="${k.cum_nhap_id}" ` +
              `data-cum-id="${c.id}"><b>${escapeHtml(c.insight)}</b> ` +
              `<span class="cc-faint">· ${c.so_video} video</span></div>`).join("")) +
          `<div class="cc-faint" style="padding:4px 6px">Video đã ở cụm khác của bạn được giữ nguyên chỗ. ` +
          `Không hoàn tác được — như mọi lần duyệt.</div>`;
        el.hidden = !(CC.popover && CC.popover.type === "gop" && CC.popover.key === k.cum_nhap_id);
      }
    }
    const traVeEl = main.querySelector('[data-cc-popover="traVe"]');
    if (traVeEl) {
      traVeEl.innerHTML = kieuPickerPopoverHtml("tra-ve-den", data);
      traVeEl.hidden = !(CC.popover && CC.popover.type === "traVe");
    }
  }

  function renderDock() {
    const dock = document.getElementById("cc-dock");
    const n = CC.selected.size;
    dock.hidden = chuaCoNhap() || daDuyet();
    // ≤480px: dock cao 3 hàng che cột Nhóm·Kiểu ⇒ chỉ hiện khi đã chọn video (CSS `.cc-dock-rong`); màn rộng giữ "luôn hiện, nút xám".
    dock.classList.toggle("cc-dock-rong", CC.selected.size === 0);
    document.getElementById("cc-dachon").textContent = `${n} video đã chọn`;
    // Chưa chọn gì thì 4 nút không làm gì (mọi nhánh `dock-*` thoát ngay khi
    // tập chọn rỗng) — làm xám cho thấy rõ, thay vì nút bấm không ăn.
    // Chỉ 4 nút của dock — không đụng nút chọn kiểu trong popover "Chuyển sang".
    dock.querySelectorAll(":scope > button, :scope > .pop-wrap > button")
      .forEach((b) => { b.disabled = n === 0; });
    const chuyenPop = document.getElementById("cc-chuyen-popover");
    if (chuyenPop) {
      chuyenPop.innerHTML = CC.data ? kieuPickerPopoverHtml("chuyen-den", CC.data) : "";
      chuyenPop.hidden = !(CC.popover && CC.popover.type === "chuyen");
    }
  }

  function cmdHtml(tokens) {
    const raw = tokens.join(" ");
    return `<div class="cc-cmd"><code>${tokens.map((t) => `<span>${escapeHtml(t)}</span>`).join(" ")}</code>` +
      `<button type="button" class="btn ghost" data-cc-action="copy-cmd" data-cmd="${escapeHtml(raw)}">Chép</button></div>`;
  }

  function renderModal() {
    const host = document.getElementById("cc-modal");
    const modal = CC.modal;
    if (!modal) { host.innerHTML = ""; return; }
    if (modal.type === "huy") {
      const cmd = ["bash", "scripts/phan-tich-hinh.sh", "--luot", String(CC.jobId), "--truc", CC.axis];
      host.innerHTML = `<div class="cc-modal-bg"><div class="card cc-modal">
        <h3>Hủy lượt này để chia lại?</h3>
        <p class="muted" style="margin:0">Lượt có <b>${CC.data.so_thao_tac} thao tác sửa</b> — nhật ký vẫn được ` +
          `giữ, nhưng nháp này thôi hiệu lực. Kiểu đã duyệt (nếu có) vẫn là cụm thật, không bị chia lại.</p>
        <label>Chia lại theo<select data-cc-huy-truc>${AXES.map((a) =>
          `<option value="${a.v}" ${a.v === CC.axis ? "selected" : ""}>${escapeHtml(a.label)}</option>`).join("")}
          </select></label>
        <div class="cc-faint" style="margin-top:8px">Sau khi hủy, chạy trên máy dev (thử khô, thêm ` +
          `<code>--yes</code> để làm thật):</div>
        ${cmdHtml(cmd)}
        <div class="cc-row">
          <button type="button" class="btn" data-cc-action="modal-close">Giữ nháp</button>
          <button type="button" class="btn danger" data-cc-action="confirm-huy">Hủy lượt</button>
        </div>
      </div></div>`;
      return;
    }
    if (modal.type === "loai") {
      const n = modal.ids.length;
      host.innerHTML = `<div class="cc-modal-bg"><div class="card cc-modal">
        <h3>Loại ${n} video khỏi thư viện?</h3>
        <div class="cc-mini-luoi">${modal.ids.slice(0, 3).map((vid) =>
          `<div class="cc-t"><img src="/thumbs/${escapeHtml(vid)}" alt=""></div>`).join("")}</div>
        <p style="font-size:.82rem; margin:10px 0 6px">Video sẽ <b>biến khỏi thư viện của bạn</b> và tệp trên Drive ` +
          `được đưa vào <b>Thùng rác</b>. Người khác quét trúng cùng video vẫn tải lại được.</p>
        <p class="muted" style="font-size:.78rem; margin:0">Không có nút khôi phục trong Video Desk.</p>
        <div class="cc-row">
          <button type="button" class="btn primary" data-cc-action="modal-close" autofocus>Huỷ</button>
          <button type="button" class="btn danger" data-cc-action="confirm-loai">Loại ${n} video</button>
        </div>
      </div></div>`;
      return;
    }
    if (modal.type === "tach") {
      const nhoms = CC.data ? nhomsOf(CC.data) : [];
      const first = nhoms[0] || "";
      const mv = [...CC.selected].slice(0, 3);
      const tenXem = tachTenXem();
      host.innerHTML = `<div class="cc-modal-bg"><div class="card cc-modal">
        <div class="cc-modal-h"><h3>Kiểu mới từ ${CC.selected.size} video đã chọn</h3>
          <button type="button" class="cc-modal-x" data-cc-action="modal-close" aria-label="Huỷ">×</button></div>
        <div class="cc-mini-luoi">${mv.map((vid) =>
          `<div class="cc-t"><img src="/thumbs/${escapeHtml(vid)}" alt=""></div>`).join("")}</div>
        <label>Nhóm<select data-cc-tach-nhom>
          ${nhoms.map((n) => `<option value="${escapeHtml(n)}" ${n === (modal.nhom || first) ? "selected" : ""}>` +
            `${escapeHtml(n)}</option>`).join("")}
          <option value="__moi__" ${modal.nhomMoi ? "selected" : ""}>+ nhóm mới…</option>
        </select></label>
        ${modal.nhomMoi ? `<label>Tên nhóm mới<input type="text" data-cc-tach-nhom-moi
          value="${escapeHtml(modal.nhom || "")}"></label>` : ""}
        <label>Tên kiểu<input type="text" data-cc-tach-kieu value="${escapeHtml(modal.kieu || "")}"></label>
        <div class="cc-faint" id="cc-tach-preview" style="margin-top:6px">Tên cụm khi duyệt: “${escapeHtml(tenXem)}”. Hoàn tác được.</div>
        <div class="cc-row">
          <button type="button" class="btn" data-cc-action="modal-close">Huỷ</button>
          <button type="button" class="btn primary" data-cc-action="confirm-tach">Tạo kiểu</button>
        </div>
      </div></div>`;
      return;
    }
    if (modal.type === "trung") {
      host.innerHTML = `<div class="cc-modal-bg"><div class="card cc-modal">
        <h3>Tên trùng cụm có sẵn</h3>
        <p class="muted">Kiểu bạn đang duyệt trùng tên với cụm có sẵn của bạn. Gộp video vào cụm đó?</p>
        <ul>${modal.trung.map((t) => `<li><b>${escapeHtml(t.ten)}</b> · ${t.so_video} video</li>`).join("")}</ul>
        <div class="cc-row">
          <button type="button" class="btn" data-cc-action="modal-close">Huỷ</button>
          <button type="button" class="btn primary" data-cc-action="confirm-trung">Xác nhận gộp</button>
        </div>
      </div></div>`;
      return;
    }
  }

  window.ChiaCumVe = Object.freeze({ CC, render, nhomsOf, tachTenXem });
})();
