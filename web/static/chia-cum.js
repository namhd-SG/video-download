(() => {
  "use strict";

  // ==========================================================================
  // Màn duyệt nháp "tự chia cụm" (phase 3+4). Tách khỏi app.js (1600+ dòng) —
  // đây là một MÀN RIÊNG, mở từ một nút trên thẻ lượt tải, render trọn vẹn
  // TỪ SERVER (`GET /chia/{job_id}`) sau MỌI thao tác: không giữ trạng thái
  // song song ở client (spec bắt buộc — mỗi hành động = POST rồi vẽ lại).
  // ==========================================================================

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

  // ---- helpers dùng chung, tách khỏi app.js để hai file không phụ vào nhau ----
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  class PhienHetHan extends Error {}

  async function apiGet(path) {
    const res = await fetch(path, { redirect: "manual" });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
    return res.json();
  }

  // Xếp hàng MỌI POST của màn này (dock lệnh sau — `apiQueueDuoi`) — hai
  // `change` liên tiếp (vd sửa usecase rồi Tab sang insight gốc, mỗi ô gửi
  // MỘT `doi_insight` mang CẢ HAI trường) gửi hai POST độc lập; không xếp
  // hàng thì thứ tự PHẢN HỒI tới server không đảm bảo khớp thứ tự GỬI (do
  // mạng, không phải do lỗi), làm giá trị ĐẾN SAU đè giá trị ĐẾN TRƯỚC dù
  // người dùng gõ SAU (lost update). Xếp hàng: lệnh #2 chỉ THỰC SỰ bắt đầu
  // (mở kết nối) sau khi #1 đã có phản hồi (dù thành công hay lỗi) — nên thứ
  // tự phản hồi luôn khớp thứ tự gọi, hết reorder.
  let apiQueueDuoi = Promise.resolve();

  async function apiSend(method, path, body) {
    const luot = apiQueueDuoi.then(
      () => _apiSendMotLuot(method, path, body),
      () => _apiSendMotLuot(method, path, body));
    // Giữ hàng đợi SỐNG kể cả khi lượt này lỗi — một lượt trượt không được
    // chặn đứng mọi lượt sau nó.
    apiQueueDuoi = luot.catch(() => {});
    return luot;
  }

  async function _apiSendMotLuot(method, path, body) {
    const res = await fetch(path, {
      method,
      redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) {
      let ma = null;
      try { ma = (await res.json()).detail; } catch (e) { ma = null; }
      const err = new Error(`${method} ${path} -> ${res.status}`);
      err.ma = ma;
      err.status = res.status;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  let toastTimer = null;
  function showToast(text) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }

  function baoPhienHetHan() {
    const el = document.getElementById("session-expired");
    if (el) el.hidden = false;
  }

  // Bảng câu tiếng Việt cho MỌI mã `tu_choi` server có thể trả
  // (`models_chia._kiem_video_ids_thao_tac`/`_op_hoan_tac`) — không bao giờ để
  // lọt một mã snake_case trần ra toast.
  // Bằng `web/app.py::MAX_VIDEO_LOAI` (test `test_tran_lo_loai_chia_khop_backend`
  // đối chiếu) — lô lớn hơn là 422 và KHÔNG video nào được loại.
  const LOAI_TOI_DA_MOI_LUOT = 50;

  const TU_CHOI_TEXT = {
    khong_hop_le: "Có video không thuộc đúng làn cho thao tác này — không thay đổi gì.",
  };

  function errorDetailText(err) {
    // Lý do RIÊNG từ server (`detail` là một OBJECT, không phải chuỗi hay
    // mảng lỗi validate) — hiện tại chỉ có `video_da_o_cum_that`
    // (`models_chia._kiem_video_ids_thao_tac`, route `/thao-tac`): video đã
    // duyệt/gán tay vào cụm thật thì không di chuyển được nữa qua
    // tách/chuyển/ngoài chủ đề/trả về. Câu chữ RÕ lý do thay vì mã lỗi trần.
    if (err.ma && typeof err.ma === "object" && !Array.isArray(err.ma)) {
      if (err.ma.tu_choi === "video_da_o_cum_that") {
        const n = Array.isArray(err.ma.video_ids) ? err.ma.video_ids.length : 0;
        return `Video đã ở cụm thật, không di chuyển được (${n} video).`;
      }
      if (err.ma.tu_choi === "video_da_loai") {
        const n = Array.isArray(err.ma.video_ids) ? err.ma.video_ids.length : 0;
        return `Video đã bị loại khỏi thư viện, không di chuyển được (${n} video).`;
      }
      if (typeof err.ma.tu_choi === "string") {
        return TU_CHOI_TEXT[err.ma.tu_choi] || "Thao tác không hợp lệ.";
      }
    }
    if (typeof err.ma === "string") {
      // `_kiem_trang_thai_de_xuat` trả CÂU (không phải mã) — tab mở từ trước
      // khi lượt được duyệt vẫn còn nút sửa và chạm vào đây.
      if (/^lượt đang 'da_duyet'/.test(err.ma)) {
        return "Lượt này đã duyệt — không sửa nháp được nữa. Video đã vào cụm; sửa ở “Cụm của tôi”.";
      }
      if (/^lượt đang '/.test(err.ma)) return "Lượt này không còn là bản nháp — tải lại trang để xem trạng thái mới.";
      return TU_CHOI_TEXT[err.ma] || err.ma;
    }
    if (Array.isArray(err.ma)) return err.ma.map((e) => e.msg || JSON.stringify(e)).join("; ");
    return err.message || "Thao tác không thực hiện được";
  }

  async function guard(fn) {
    try {
      await fn();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(errorDetailText(err));
      if (!CC.open) return;
      // Server báo lượt KHÔNG còn là nháp (tab mở từ trước khi duyệt/huỷ) —
      // chỉ vẽ lại thì mọi nút sửa nháp còn nguyên và mỗi cú bấm sau lại 400.
      // Tải lại dữ liệu để trang tự chuyển sang chế độ chỉ đọc.
      if (typeof err.ma === "string" && /^lượt đang '/.test(err.ma)) {
        // Hộp xác nhận sửa nháp đang mở (vd Huỷ lượt) cũng phải đóng — nếu
        // không nút xác nhận của nó còn đó và mỗi cú bấm lại 400.
        CC.modal = null;
        CC.popover = null;
        try {
          await refresh();
        } catch (e) {
          if (e instanceof PhienHetHan) baoPhienHetHan();
        }
        return;
      }
      // Thao tác trượt có thể đã xoá `CC.selected` (dock) TRƯỚC khi gửi POST
      // (vd `dock-ngoai`/`dock-chuyen`) — vẽ lại để số hiện trên dock khớp
      // với `CC.selected` thật, không còn treo số cũ.
      render();
    }
  }

  // ==========================================================================
  // Mở/đóng màn hình
  // ==========================================================================
  function view() { return document.getElementById("chia-view"); }

  async function openChia(jobId) {
    CC.open = true;
    CC.jobId = jobId;
    CC.selected = new Set();
    CC.popover = null;
    CC.modal = null;
    view().hidden = false;
    document.body.classList.add("cc-lock-scroll");
    await refresh();
  }

  function closeChia() {
    CC.open = false;
    view().hidden = true;
    document.body.classList.remove("cc-lock-scroll");
  }

  // Số thứ tự lượt `refresh()` — MỖI GET (job/chia/cum) không tự có thứ tự
  // phản hồi đảm bảo (khác hàng đợi POST ở `apiSend`, cố ý không xếp GET vào
  // đó vì GET không đổi dữ liệu). Không có `seq` thì lượt GET cũ có thể về
  // SAU lượt GET mới hơn và ghi đè `CC.data` bằng bản CŨ — DOM vẽ lại giá trị
  // cũ, và lần `doi_insight` kế tiếp (gửi CẢ hai ô từ DOM) ghi giá trị cũ đó
  // lên server (lost update). `seq` tăng ở ĐẦU mỗi lượt refresh(); lượt nào
  // về mà không còn là lượt MỚI NHẤT vừa bắt đầu thì bỏ, không ghi state.
  let refreshSeq = 0;

  async function refresh() {
    const seq = ++refreshSeq;
    const [job, data, cumRes] = await Promise.all([
      apiGet(`/jobs/${CC.jobId}`),
      apiGet(`/chia/${CC.jobId}`),
      apiGet("/cum"),
    ]);
    if (seq !== refreshSeq) return;  // một refresh() mới hơn đã bắt đầu — bỏ kết quả cũ này
    CC.job = job;
    CC.data = data;
    CC.cums = (cumRes && cumRes.cum) || [];
    if (data && data.truc) CC.axis = data.truc;
    // Tập đang chọn (dock) chỉ giữ id CÒN HIỂN THỊ trong nháp sau khi vẽ lại
    // — video vừa DUYỆT (rời nháp, vào cụm thật) phải rơi khỏi dock, nếu
    // không thao tác kế tiếp (tách/chuyển/ngoài chủ đề) sẽ tưởng nó còn ở
    // nháp và ghi một dòng nhật ký vô nghĩa cho video đã không còn trong lượt
    // (server cũng tự chặn — xem `_hang_video_cum_nhap` — đây chỉ là lớp UI
    // để dock không hiện số chọn sai).
    if (CC.selected.size) {
      const conHienThi = data
        ? new Set([...data.kieu.flatMap((k) => k.video_ids), ...data.huong_dan, ...data.nghi])
        : new Set();
      CC.selected = new Set([...CC.selected].filter((v) => conHienThi.has(v)));
    }
    render();
  }

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
    ctx.textContent = CC.job ? `Lượt tải #${CC.job.id} · ${CC.job.tong} video` : "";

    const tieude = document.getElementById("cc-tieude");
    if (empty) {
      tieude.textContent = "Chưa chia cụm";
    } else {
      const nNhom = new Set(nhomsOf(data)).size;
      const hau = data.trang_thai === "da_duyet" ? "— đã duyệt" : "— bản nháp";
      tieude.textContent =
        `Hệ đã chia thành ${nNhom} nhóm · ${data.kieu.length} kiểu + làn riêng ` +
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
    let r = "<h3>Lượt này</h3>";
    if (chuaCoNhap()) {
      r += `<div class="cc-ri"><span>Chưa vào cụm</span><span class="cc-n">${CC.job ? CC.job.tong : 0}</span></div>`;
    } else {
      const data = CC.data;
      for (const nhom of nhomsOf(data)) {
        const ks = data.kieu.filter((k) => k.nhom === nhom);
        const tong = ks.reduce((s, k) => s + k.video_ids.length, 0);
        r += `<div class="cc-ri"><span>${escapeHtml(nhom)}</span><span class="cc-n">${tong}</span></div>`;
        for (const k of ks) {
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
          <span class="muted">${tong} video · ${ks.length} kiểu</span>
          <span class="cc-sp"></span>
          ${!duyet && ks.length > 1 ? `<button type="button" class="btn" data-cc-action="gop-nhom" ` +
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
    document.getElementById("cc-dachon").textContent = `${n} video đã chọn`;
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
        <h3>Kiểu mới từ ${CC.selected.size} video đã chọn</h3>
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

  // ==========================================================================
  // THAO TÁC — gọi server rồi refresh() từ đầu
  // ==========================================================================
  async function thaoTac(loai, tham) {
    const ket = await apiSend("POST", `/chia/${CC.data.id}/thao-tac`, { loai, ...tham });
    if (ket && ket.tu_choi) {
      showToast(loai === "hoan_tac" ? "Không còn gì để hoàn tác." : "Thao tác không hợp lệ.");
      return null;
    }
    await refresh();
    return ket;
  }

  // Loại video (thao tác THƯ VIỆN `/videos/loai`, không phải sửa nháp — chạy
  // được cả khi lượt đã duyệt). Tuần tự theo lô ≤ LOAI_TOI_DA_MOI_LUOT, cùng
  // khuôn `app.js::loaiDaChon`: cộng đủ ba con số, dừng ở lô đầu trượt và nói
  // rõ còn bao nhiêu chưa gửi. Mỗi id độc lập ở server (trash trượt ⇒ id đó
  // không ghi mốc) nên dừng giữa chừng không để lại trạng thái nửa vời.
  //
  // Loại là KHÔNG lùi được (Drive → Thùng rác), nên các lô đã gửi xong luôn
  // phải được báo số và làn luôn phải vẽ lại — kể cả khi một lô sau hết phiên
  // hay lượt tải lại làn trượt. Hết phiên chỉ được ném tiếp (để `guard` bật
  // băng hết phiên) SAU khi đã báo tóm tắt.
  async function loaiTheoLo(ids) {
    const tong = { da_loai: 0, drive_truot: 0, khong_phai_cua_ban: 0 };
    let daGui = 0;
    let loi = null;
    let hetPhien = null;
    const daLoai = new Set();
    for (let i = 0; i < ids.length; i += LOAI_TOI_DA_MOI_LUOT) {
      const lo = ids.slice(i, i + LOAI_TOI_DA_MOI_LUOT);
      try {
        const res = await apiSend("POST", "/videos/loai", { video_ids: lo });
        tong.da_loai += res.da_loai.length;
        tong.drive_truot += res.drive_truot.length;
        tong.khong_phai_cua_ban += res.khong_phai_cua_ban.length;
        res.da_loai.forEach((v) => { CC.selected.delete(v); daLoai.add(v); });
        daGui += lo.length;
      } catch (err) {
        if (err instanceof PhienHetHan) hetPhien = err;
        else loi = err;
        break;
      }
    }
    let loiTaiLai = false;
    if (daGui > 0) {
      try {
        await refresh();
      } catch (err) {
        if (err instanceof PhienHetHan) hetPhien = hetPhien || err;
        else loiTaiLai = true;
        // Không tải lại được (thường là cùng lúc hết phiên): tự bỏ video đã
        // loại khỏi 2 làn tại chỗ, để làn không còn hiện video đã vào Thùng rác.
        if (CC.data) {
          CC.data.nghi = CC.data.nghi.filter((v) => !daLoai.has(v));
          CC.data.huong_dan = CC.data.huong_dan.filter((v) => !daLoai.has(v));
          render();
        }
      }
    }
    // Chưa gửi được lô nào mà đã hết phiên: không có gì để báo ngoài băng hết phiên.
    if (hetPhien && daGui === 0) throw hetPhien;
    const conLai = ids.length - daGui;
    const phan = [`Đã loại ${tong.da_loai} video`];
    if (tong.drive_truot) phan.push(`${tong.drive_truot} chưa bỏ được khỏi Drive — vẫn còn trong làn, bấm lại`);
    if (tong.khong_phai_cua_ban) phan.push(`${tong.khong_phai_cua_ban} không phải của bạn`);
    if (loi) phan.push(`dừng giữa chừng (${errorDetailText(loi)}) — còn ${conLai} video chưa gửi`);
    if (hetPhien && conLai > 0) phan.push(`phiên đăng nhập hết hạn — còn ${conLai} video chưa gửi`);
    if (loiTaiLai) phan.push("chưa tải lại được làn — tải lại trang để xem");
    showToast(phan.join(" · "));
    if (hetPhien) throw hetPhien;
  }

  async function duyet(body) {
    // MỌI đường duyệt (một kiểu, tất cả, gộp vào cụm có sẵn, xác nhận gộp
    // sau "trùng cụm có sẵn") phải mang usecase/insight gốc HIỆN TẠI trong ô
    // nhập — để server tự ghi một `doi_insight` TRONG CÙNG transaction duyệt
    // trước khi dùng (`_ap_doi_insight_neu_co`) và hết race giữa blur ô nhập
    // với bấm Duyệt (hai POST độc lập, không có thứ tự đảm bảo tới server).
    // Thiếu bước này thì cụm THẬT có thể mang tên theo insight CŨ, và không
    // có đường lùi (duyệt không nằm trong `_HOAN_TAC_DUOC`).
    const usecaseInput = document.querySelector('[data-cc-field="usecase"]');
    const insightInput = document.querySelector('[data-cc-field="insight_goc"]');
    const than = {
      usecase: usecaseInput ? usecaseInput.value : (CC.data && CC.data.usecase) || "",
      insight_goc: insightInput ? insightInput.value : (CC.data && CC.data.insight_goc) || "",
      ...body,
    };
    return apiSend("POST", `/chia/${CC.data.id}/duyet`, than);
  }

  async function duyetKieu(cumNhapId, xacNhanGop) {
    const ket = await duyet({ cum_nhap_id: cumNhapId, xac_nhan_gop: xacNhanGop || [] });
    if (ket.trung_cum_co_san) {
      CC.modal = {
        type: "trung",
        trung: ket.trung_cum_co_san.map((t) => ({ ten: t.ten, so_video: t.so_video, cum_id: t.cum_id })),
        cumNhapId,
      };
      render();
      return;
    }
    showToast(ket.da_co ? "Đã duyệt — đã gộp vào cụm có sẵn." : "Đã duyệt — đã tạo cụm mới.");
    await refresh();
  }

  async function duyetHet() {
    const ket = await duyet({});
    if (ket.trung_cum_co_san && ket.trung_cum_co_san.length) {
      CC.modal = { type: "trung", trung: ket.trung_cum_co_san.map((t) =>
        ({ ten: t.ten, so_video: t.so_video, cum_id: t.cum_id })), all: true };
      render();
      return;
    }
    if (ket.loi_ten && ket.loi_ten.length) {
      showToast(`${ket.loi_ten.length} kiểu tên chưa hợp lệ, vẫn ở lại nháp.`);
    } else {
      showToast(`Đã duyệt ${ket.cum.length} kiểu.`);
    }
    await refresh();
  }

  // ==========================================================================
  // Sự kiện — MỘT listener uỷ quyền trên toàn màn hình (view() vẽ lại liên
  // tục, gắn tay từng nút sẽ mất tay nghe sau mỗi lần render).
  // ==========================================================================
  function wireEvents() {
    const root = view();

    root.addEventListener("click", (ev) => {
      guard(async () => {
        const closeBg = ev.target.closest("[data-cc-modal-bg]");
        if (closeBg && ev.target === closeBg) { CC.modal = null; render(); return; }

        const btn = ev.target.closest("[data-cc-action]");
        if (!btn) {
          // Bấm ra ngoài mọi popover đang mở thì đóng nó — trừ khi bấm NGAY
          // trên chính nút mở popover đó (nút đó tự xử lý toggle bên dưới).
          if (CC.popover && !ev.target.closest(".pop-wrap")) { CC.popover = null; render(); }
          return;
        }
        const action = btn.dataset.ccAction;

        if (action === "back") { closeChia(); return; }

        if (action === "duyet-het") { await duyetHet(); return; }
        if (action === "mo-huy") { CC.modal = { type: "huy" }; render(); return; }
        if (action === "hoan-tac") { await thaoTac("hoan_tac", {}); return; }
        if (action === "modal-close") { CC.modal = null; render(); return; }

        if (action === "loai-lan") {
          const lanIds = btn.dataset.lan === "nghi" ? CC.data.nghi : CC.data.huong_dan;
          const ids = lanIds.filter((v) => CC.selected.has(v));
          if (!ids.length) return;
          CC.modal = { type: "loai", ids };
          render();
          return;
        }
        if (action === "confirm-loai") {
          const ids = CC.modal.ids;
          CC.modal = null;
          CC.dangLoai = true;
          render();
          try {
            await loaiTheoLo(ids);
          } finally {
            CC.dangLoai = false;
            if (CC.open) render();
          }
          return;
        }
        if (action === "confirm-huy") {
          await thaoTac("huy_luot", {});
          CC.modal = null;
          render();
          return;
        }
        if (action === "confirm-trung") {
          const ids = CC.modal.trung.map((t) => t.cum_id);
          const wasAll = !!CC.modal.all;
          const cumNhapId = CC.modal.cumNhapId;
          CC.modal = null;
          if (wasAll) {
            const ket = await duyet({ xac_nhan_gop: ids });
            if (ket.trung_cum_co_san && ket.trung_cum_co_san.length) {
              CC.modal = { type: "trung", all: true, trung: ket.trung_cum_co_san.map((t) =>
                ({ ten: t.ten, so_video: t.so_video, cum_id: t.cum_id })) };
              render();
              return;
            }
            showToast(`Đã duyệt ${ket.cum.length} kiểu.`);
          } else {
            await duyetKieu(cumNhapId, ids);
            return;
          }
          await refresh();
          return;
        }

        if (action === "copy-cmd") {
          const cmd = btn.dataset.cmd || "";
          try { await navigator.clipboard.writeText(cmd); showToast("Đã chép lệnh."); }
          catch (e) { showToast("Không chép được — chọn và copy tay."); }
          return;
        }

        if (action === "xoa-kieu") {
          await thaoTac("xoa_kieu", { cum_nhap_id: Number(btn.dataset.cumNhapId) });
          return;
        }
        if (action === "duyet-kieu") {
          await duyetKieu(Number(btn.dataset.cumNhapId));
          return;
        }
        if (action === "toggle-gop") {
          const id = Number(btn.dataset.cumNhapId);
          CC.popover = (CC.popover && CC.popover.type === "gop" && CC.popover.key === id)
            ? null : { type: "gop", key: id };
          render();
          return;
        }
        if (action === "gop-vao-cum") {
          const cumNhapId = Number(btn.dataset.cumNhapId);
          const cumId = Number(btn.dataset.cumId);
          CC.popover = null;
          const ket = await duyet({ cum_nhap_id: cumNhapId, gop_vao_cum_id: cumId });
          showToast("Đã duyệt — đã gộp vào cụm có sẵn.");
          void ket;
          await refresh();
          return;
        }
        if (action === "gop-nhom") {
          const nhom = btn.dataset.nhom;
          const ks = CC.data.kieu.filter((k) => k.nhom === nhom);
          if (ks.length < 2) return;
          const [den, ...tu] = ks;
          await thaoTac("gop_nhom", {
            den_cum_nhap_id: den.cum_nhap_id, cum_nhap_ids: tu.map((k) => k.cum_nhap_id),
          });
          return;
        }

        if (action === "hd-thanh-kieu") {
          if (!CC.data.huong_dan.length) return;
          await thaoTac("tach", { video_ids: CC.data.huong_dan, nhom: "Hướng dẫn", kieu: "Hướng dẫn" });
          return;
        }
        if (action === "hd-ngoai-chu-de") {
          if (!CC.data.huong_dan.length) return;
          await thaoTac("ngoai_chu_de", { video_ids: CC.data.huong_dan });
          return;
        }
        if (action === "toggle-tra-ve") {
          CC.popover = (CC.popover && CC.popover.type === "traVe") ? null : { type: "traVe" };
          render();
          return;
        }
        if (action === "tra-ve-den") {
          const denId = Number(btn.dataset.cumNhapId);
          const ids = CC.selected.size
            ? [...CC.selected].filter((v) => CC.data.nghi.includes(v) || CC.data.huong_dan.includes(v))
            : CC.data.nghi;
          CC.popover = null;
          if (!ids.length) { render(); return; }
          await thaoTac("tra_ve", { video_ids: ids, den_cum_nhap_id: denId });
          return;
        }
        if (action === "chuyen-den") {
          const denId = Number(btn.dataset.cumNhapId);
          const ids = [...CC.selected];
          CC.popover = null;
          CC.selected = new Set();
          if (!ids.length) { render(); return; }
          await thaoTac("chuyen", { video_ids: ids, den_cum_nhap_id: denId });
          return;
        }

        if (action === "dock-chuyen") {
          if (!CC.selected.size) return;
          CC.popover = (CC.popover && CC.popover.type === "chuyen") ? null : { type: "chuyen" };
          render();
          return;
        }
        if (action === "dock-tach") {
          if (!CC.selected.size) return;
          const nhoms = CC.data ? nhomsOf(CC.data) : [];
          // Lượt còn 0 kiểu (đã `xoa_kieu` hết, hoặc tầng hình xếp mọi video
          // vào nghi/hướng dẫn): mặc định chế độ "+ nhóm mới…" luôn, vì đó
          // là lựa chọn DUY NHẤT trong `<select>` — không có option khác để
          // người dùng CHỌN LẠI mà sinh sự kiện `change` bật `nhomMoi`, nên ô
          // "Tên nhóm mới" sẽ không bao giờ hiện nếu không tự bật ở đây.
          CC.modal = nhoms.length
            ? { type: "tach", nhom: nhoms[0], kieu: "" }
            : { type: "tach", nhom: "", kieu: "", nhomMoi: true };
          render();
          return;
        }
        if (action === "dock-ngoai") {
          if (!CC.selected.size) return;
          // Lọc bỏ video ĐÃ ở nghi trước khi gửi — giống `tra-ve-den`. Server
          // từ chối CẢ yêu cầu nếu danh sách còn lẫn video đã ở nghi (hợp
          // đồng chỉ có MỘT trạng thái "nghi"), nên "chọn cả kiểu lẫn nghi rồi
          // bấm Ngoài chủ đề" — thao tác tự nhiên khi muốn dồn hết vào nghi —
          // phải tự lọc ở đây thay vì rơi vào toast lỗi.
          const ids = [...CC.selected].filter((v) => !CC.data.nghi.includes(v));
          if (!ids.length) {
            showToast("Video đã chọn đều đã ở làn ngoài chủ đề — không có gì để chuyển.");
            return;
          }
          CC.selected = new Set();
          await thaoTac("ngoai_chu_de", { video_ids: ids });
          return;
        }
        if (action === "dock-bo-chon") {
          CC.selected = new Set();
          render();
          return;
        }
        if (action === "confirm-tach") {
          const nhom = CC.modal.nhomMoi ? (CC.modal.nhom || "").trim() : (CC.modal.nhom || "");
          const kieu = (CC.modal.kieu || "").trim();
          if (!nhom || !kieu) { showToast("Cần nhóm và tên kiểu."); return; }
          const ids = [...CC.selected];
          CC.modal = null;
          CC.selected = new Set();
          await thaoTac("tach", { video_ids: ids, nhom, kieu });
          return;
        }
      });
    });

    // Ô "Tên kiểu" của modal tách: cập nhật xem-trước NGAY MỖI PHÍM (không
    // đợi blur như ô usecase/insight — ô đó gọi server nên phải chặn spam,
    // ô này chỉ đổi state phía client). Vá TRỰC TIẾP text của dòng xem-trước
    // thay vì gọi lại `render()` — gọi lại sẽ nạp lại `value` từ state cũ và
    // làm con trỏ nhảy về cuối input giữa lúc đang gõ.
    root.addEventListener("input", (ev) => {
      const kieuInput = ev.target.closest("[data-cc-tach-kieu]");
      if (kieuInput && CC.modal && CC.modal.type === "tach") {
        CC.modal.kieu = kieuInput.value;
        const prev = document.getElementById("cc-tach-preview");
        if (prev) prev.textContent = `Tên cụm khi duyệt: “${tachTenXem()}”. Hoàn tác được.`;
        return;
      }
      const nhomMoiInput = ev.target.closest("[data-cc-tach-nhom-moi]");
      if (nhomMoiInput && CC.modal) CC.modal.nhom = nhomMoiInput.value;
    });

    root.addEventListener("change", (ev) => {
      guard(async () => {
        const field = ev.target.closest("[data-cc-field]");
        if (field) {
          // MỘT `doi_insight` mang CẢ HAI trường hiện tại — không phải một
          // request riêng cho từng ô — để hai ô luôn ghi cùng lúc, đúng luật
          // "một cú bấm/gõ = một dòng nhật ký sửa" (D15).
          const usecaseInput = root.querySelector('[data-cc-field="usecase"]');
          const insightInput = root.querySelector('[data-cc-field="insight_goc"]');
          await thaoTac("doi_insight", {
            usecase: usecaseInput ? usecaseInput.value : (CC.data.usecase || ""),
            insight_goc: insightInput ? insightInput.value : (CC.data.insight_goc || ""),
          });
          return;
        }
        const kieuRename = ev.target.closest("[data-cc-kieu-rename]");
        if (kieuRename) {
          const id = Number(kieuRename.dataset.ccKieuRename);
          const kieu = kieuRename.value.trim();
          if (!kieu) { await refresh(); return; }
          await thaoTac("doi_ten", { cum_nhap_id: id, kieu });
          return;
        }
        const nhomRename = ev.target.closest("[data-cc-nhom-rename]");
        if (nhomRename) {
          const cur = nhomRename.dataset.ccNhomCur;
          const moi = nhomRename.value.trim();
          if (!moi || moi === cur) { await refresh(); return; }
          // MỘT thao tác `doi_ten_nhom` cho CẢ nhóm — atomic ở tầng server,
          // thay vòng lặp `doi_ten` cũ (N request rời cho N kiểu, có thể
          // trượt giữa chừng để lại nhóm đổi tên một nửa).
          await thaoTac("doi_ten_nhom", { nhom_cu: cur, nhom_moi: moi });
          return;
        }
        const huyTruc = ev.target.closest("[data-cc-huy-truc]");
        if (huyTruc) { CC.axis = huyTruc.value; render(); return; }
        const tachNhom = ev.target.closest("[data-cc-tach-nhom]");
        if (tachNhom) {
          CC.modal.nhomMoi = tachNhom.value === "__moi__";
          CC.modal.nhom = CC.modal.nhomMoi ? "" : tachNhom.value;
          render();
          return;
        }
      });
    });

    // Chọn thumbnail cho dock (bất kỳ làn nào).
    root.addEventListener("click", (ev) => {
      const t = ev.target.closest(".cc-t[data-cc-video]");
      if (!t || ev.target.closest("[data-cc-action]")) return;
      const vid = t.dataset.ccVideo;
      if (CC.selected.has(vid)) CC.selected.delete(vid); else CC.selected.add(vid);
      render();
    });
  }

  // ==========================================================================
  // Khởi động — gắn nút mở từ thẻ lượt tải (đầu vào), tạo khung DOM một lần.
  // ==========================================================================
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.getElementById("chia-view")) return;
    wireEvents();
  });

  document.addEventListener("click", (ev) => {
    const openBtn = ev.target.closest("[data-chia]");
    if (!openBtn) return;
    ev.preventDefault();
    guard(() => openChia(Number(openBtn.dataset.chia)));
  });

  window.chiaCum = { open: openChia, close: closeChia };
})();
