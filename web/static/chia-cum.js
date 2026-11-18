(() => {
  "use strict";

  // ==========================================================================
  // Màn duyệt nháp "tự chia cụm" (phase 3+4). Tách khỏi app.js (1600+ dòng) —
  // đây là một MÀN RIÊNG, mở từ một nút trên thẻ lượt tải, render trọn vẹn
  // TỪ SERVER (`GET /chia/{job_id}`) sau MỌI thao tác: không giữ trạng thái
  // song song ở client (spec bắt buộc — mỗi hành động = POST rồi vẽ lại).
  // ==========================================================================

  // State `CC` + các hàm vẽ ở `chia-cum-ve.js` (nạp TRƯỚC tệp này).
  const { CC, render, nhomsOf, tachTenXem } = window.ChiaCumVe;

  // Helper dùng chung (`chung-tien-ich.js`, nạp TRƯỚC tệp này). `guiMotLuot` = một POST trần, không xếp hàng.
  const { escapeHtml, PhienHetHan, baoPhienHetHan, apiSend: guiMotLuot } = window.VDChung;

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
      () => guiMotLuot(method, path, body),
      () => guiMotLuot(method, path, body));
    // Giữ hàng đợi SỐNG kể cả khi lượt này lỗi — một lượt trượt không được
    // chặn đứng mọi lượt sau nó.
    apiQueueDuoi = luot.catch(() => {});
    return luot;
  }

  let toastTimer = null;
  // Hai toast chạm nhau mà MỘT trong hai là lỗi thì NỐI lại, không đè — theo
  // CẢ HAI chiều: vd lệnh dock bị từ chối (video vừa loại) và "Đã loại N
  // video" về gần như cùng lúc, thứ tự không đảm bảo (GET làm mới của Loại
  // không đi qua hàng đợi POST). Đè thì mất hoặc lý do từ chối, hoặc câu xác
  // nhận của một thao tác KHÔNG lùi được. Giữ tối đa 2 phần (một lỗi, một câu
  // thường) để chuỗi không dài mãi. `toastDaGhi`: `app.js` cũng ghi
  // vào `#toast` — chữ không phải của màn này thì coi như toast mới.
  let toastPhan = [];
  let toastDaGhi = "";
  function showToast(text, laLoi = false) {
    const el = document.getElementById("toast");
    if (!el) return;
    const conHien = !el.hidden && el.textContent === toastDaGhi;
    const coLoi = toastPhan.some((p) => p.loi);
    if (conHien && (laLoi || coLoi)) {
      // Tối đa MỘT lỗi + MỘT câu thường, mỗi loại giữ bản MỚI NHẤT: phần mới
      // thay phần cũ CÙNG loại — không bao giờ nuốt câu thường vừa tới (vd
      // "Đã loại N video") chỉ vì đã có hai lỗi.
      const cu = toastPhan.findIndex((p) => p.loi === laLoi);
      if (cu >= 0) toastPhan.splice(cu, 1);
      toastPhan.push({ text, loi: laLoi });
    } else {
      toastPhan = [{ text, loi: laLoi }];
    }
    text = toastDaGhi = toastPhan.map((p) => p.text).join(" · ");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
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
    // mảng lỗi validate) — `video_da_o_cum_that` và `video_da_loai`
    // (`models_chia._kiem_video_ids_thao_tac`, route `/thao-tac`): video đã
    // duyệt/gán tay vào cụm thật, hoặc đã bị loại khỏi thư viện, thì không di
    // chuyển được nữa qua tách/chuyển/ngoài chủ đề/trả về. Câu chữ RÕ lý do
    // thay vì mã lỗi trần.
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
      showToast(errorDetailText(err), true);
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
  // THAO TÁC — gọi server rồi refresh() từ đầu
  // ==========================================================================
  async function thaoTac(loai, tham) {
    const ket = await apiSend("POST", `/chia/${CC.data.id}/thao-tac`, { loai, ...tham });
    if (ket && ket.tu_choi) {
      showToast(loai === "hoan_tac" ? "Không còn gì để hoàn tác." : "Thao tác không hợp lệ.", true);
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
    // Loại không trọn (trượt Drive, không phải của bạn, dừng giữa chừng) là LỖI.
    showToast(phan.join(" · "), phan.length > 1);
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
    // `gan` rỗng: kiểu không còn video (tab cũ còn nút duyệt) — server không
    // gán video nào, đừng báo "đã tạo cụm mới". Xét `gan`, KHÔNG xét `cum_id`:
    // duyệt kiểu rỗng trả `cum_id=null` nhưng gộp vào cụm có sẵn trả `cum_id`
    // của cụm đích dù `gan=[]`.
    showToast(!kieuCoGan(ket) ? "Kiểu không còn video — không tạo cụm."
      : ket.da_co ? "Đã duyệt — đã gộp vào cụm có sẵn." : "Đã duyệt — đã tạo cụm mới.");
    await refresh();
  }

  function kieuCoGan(ket) { return !!(ket && ket.gan && ket.gan.length); }

  // Toast của "Duyệt tất cả": chỉ đếm kiểu THẬT SỰ gán video (kiểu rỗng về
  // trong `cum` với `gan=[]`); lượt đóng mà không duyệt kiểu nào ⇒ nói rõ.
  function tomTatDuyetHet(ket) {
    const n = ket.cum.filter(kieuCoGan).length;
    if (!n && ket.da_dong) return "Đã đóng lượt — không còn kiểu nào để duyệt.";
    return `Đã duyệt ${n} kiểu.`;
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
      showToast(`${ket.loi_ten.length} kiểu tên chưa hợp lệ, vẫn ở lại nháp.`, true);
    } else {
      showToast(tomTatDuyetHet(ket));
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
            showToast(tomTatDuyetHet(ket));
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
          catch (e) { showToast("Không chép được — chọn và copy tay.", true); }
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
          showToast(kieuCoGan(ket) ? "Đã duyệt — đã gộp vào cụm có sẵn."
            : "Kiểu không còn video — không gộp gì.");
          await refresh();
          return;
        }
        if (action === "gop-nhom") {
          const nhom = btn.dataset.nhom;
          // Chỉ gộp kiểu CÒN video — kiểu rỗng không được làm ĐÍCH (kiểu thật
          // sẽ mang tên nó) và cũng không cần kéo theo (nó chờ "Xoá kiểu").
          const ks = CC.data.kieu.filter((k) => k.nhom === nhom && k.video_ids.length);
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
            showToast("Video đã chọn đều đã ở làn ngoài chủ đề — không có gì để chuyển.", true);
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
          if (!nhom || !kieu) { showToast("Cần nhóm và tên kiểu.", true); return; }
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
