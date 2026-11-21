// Cụm của tôi: popover/form đưa vào cụm, đổi kiểu, xoá cụm; loại video đã chọn.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // Một lượt gửi cụm tại một thời điểm, cho CẢ form lẫn các dòng "cụm có sẵn".
  // Bấm đôi mà không có cờ này thì hai lượt cùng đọc `state.cums` cũ và cùng
  // POST — đúng ca để lại hai cụm trùng tên (review PR #13).
  let dangGuiCum = false;

  // Bằng `web/app.py::MAX_VIDEO_CUM`.
  const GAN_CUM_TOI_DA = 1000;

  function renderPopoverCum() {
    const pop = document.getElementById("cum-popover");
    if (!pop || pop.hidden) return;
    const co = state.cums.length
      ? `<h4>Đưa vào cụm có sẵn</h4>` + state.cums.map((c) =>
          `<button type="button" class="cum-row" data-gan-cum="${c.id}"><span class="cum-dot" style="background:${mauCum(c.id)}"></span>` +
          `<span class="cum-ten">${escapeHtml(c.insight)}</span><span class="n">${escapeHtml(c.usecase)}</span></button>`).join("") +
        `<hr class="rail-sep">`
      : "";
    pop.innerHTML = co + formCum("thanh", state.selected.size);
    capNhatXemTruoc(pop);
  }

  function capNhatXemTruoc(goc) {
    const f = goc.querySelector(".cum-form");
    if (!f) return;
    const gt = (t) => f.querySelector(`[data-cum-o="${t}"]`).value;
    // Trùng một cụm có sẵn ⇒ nói TRƯỚC khi bấm rằng sẽ dùng lại cụm đó, và
    // hiện tên của CỤM ĐÓ (từ server), không phải chữ vừa gõ.
    const trung = timCumTrung(state.cums, gt("usecase"), gt("goc"), gt("kieu"));
    f.querySelector("[data-xem-truoc]").textContent =
      trung ? `${trung.insight} (đã có — dùng lại cụm này)` : (xemTruocTen(gt("goc"), gt("kieu")) || "—");
    const n = f.dataset.noi === "thanh" ? state.selected.size : 0;
    f.querySelector("button[type=submit]").textContent = trung
      ? (n ? `Đưa ${n} video vào cụm có sẵn` : "Cụm này đã có")
      : (n ? `Tạo cụm và đưa ${n} video vào` : "Tạo cụm");
  }

  async function guiFormCum(form) {
    const gt = (t) => form.querySelector(`[data-cum-o="${t}"]`).value;
    const nhap = { goc: gt("goc"), usecase: gt("usecase"), kieu: gt("kieu") };
    if (!khoaNhan(nhap.goc) || !khoaNhan(nhap.usecase) || !khoaNhan(nhap.kieu)) {
      showToast("Điền đủ insight gốc, usecase và kiểu.");
      return;
    }
    const ids = form.dataset.noi === "thanh" ? [...state.selected] : [];
    if (dangGuiCum) return;
    dangGuiCum = true;
    const nut = form.querySelector("button[type=submit]");
    nut.disabled = true;
    try {
      const cumId = await duaVaoCum(nhap, ids);
      if (ids.length) boChonTatCa();
      await loadCums();
      document.getElementById("cum-popover").hidden = true;
      state.cumLoc = cumId;
      sauKhiDoiBoLoc();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đưa được vào cụm: ${typeof err.ma === "string" ? err.ma : lyDoLoiLoai(err)}`);
      await loadCums().catch(() => {});
      renderLibrary();
    } finally {
      dangGuiCum = false;
      nut.disabled = false;
    }
  }

  // Dòng "cụm có sẵn" mang id ⇒ gán THẲNG vào id đó. Tra lại theo tên (bản
  // trước) thì khi có hai cụm cùng tên, bấm cụm B mà video vào cụm A.
  async function ganVaoCumCoSan(cumId) {
    if (dangGuiCum || !state.cums.some((c) => c.id === cumId)) return;
    dangGuiCum = true;
    try {
      const ids = [...state.selected];
      baoDaGan(cumId, true, ids.length, await ganIdsVaoCum(cumId, ids));
      boChonTatCa();
      await loadCums();
      document.getElementById("cum-popover").hidden = true;
      renderLibrary();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đưa được vào cụm: ${lyDoLoiLoai(err)}`);
    } finally {
      dangGuiCum = false;
    }
  }

  async function doiKieuCum(cum) {
    const kieu = window.prompt(`Kiểu mới cho “${cum.insight}” (insight gốc “${cum.insight_goc}” giữ nguyên):`, cum.kieu);
    if (kieu === null || !khoaNhan(kieu)) return;
    try {
      await apiSend("PATCH", `/cum/${cum.id}`, { kieu });
      await loadCums();
      renderLibrary();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đổi được kiểu: ${typeof err.ma === "string" ? err.ma : lyDoLoiLoai(err)}`);
    }
  }

  async function xoaCum(cum) {
    if (!window.confirm(`Xoá cụm “${cum.insight}”?\n\nVideo trong cụm về “Chưa vào cụm” — không video nào bị xoá.`)) return;
    try {
      await apiSend("DELETE", `/cum/${cum.id}`);
      for (const v of state.videos) if (v.cum_id === cum.id) v.cum_id = null;
      await loadCums();
      sauKhiDoiBoLoc();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không xoá được cụm: ${lyDoLoiLoai(err)}`);
    }
  }

  // Bằng `web/app.py::MAX_VIDEO_LOAI`. Test `test_tran_lo_loai_khop_backend`
  // đối chiếu hai số — đổi một bên mà quên bên kia là 422 quay lại.
  const LOAI_TOI_DA_MOI_LUOT = 50;

  // Câu cho NGƯỜI DÙNG khi một lô bỏ video trượt. Bản trước in thẳng
  // "POST /videos/loai -> 422" — đúng với dev, vô nghĩa với người bấm. Mã vẫn đi
  // kèm trong ngoặc để ai báo lỗi còn chép được.
  function lyDoLoiLoai(err) {
    const st = err && err.status;
    if (st === 422) return `máy chủ từ chối yêu cầu (mã 422) — báo người phát triển`;
    if (st >= 500) return `máy chủ đang lỗi (mã ${st}) — thử lại sau ít phút`;
    if (st) return `không bỏ được (mã ${st})`;
    return `mất kết nối tới máy chủ — kiểm mạng rồi bấm lại`;
  }

  async function loaiDaChon() {
    const khoaThe = [...state.selected];
    if (!khoaThe.length) return;
    const laAnh = state.loaiThuVien === "anh";
    // Khoá thẻ ⇒ id tệp gửi `POST /videos/loai`. Video: chính nó. Bài ảnh: `file_ids` của bài (server bỏ theo TỪNG tệp =
    // một hàng `videos`). Viết tại chỗ: harness `tests/js/` trích riêng hàm này.
    const idTepCuaThe = (k) => {
      const v = (state.videos || []).find((x) => x.video_id === k);
      return v && v.loai === "anh" ? (v.file_ids || []) : [k];
    };
    const ids = khoaThe.flatMap(idTepCuaThe);   // chia lô ≤ LOAI_TOI_DA_MOI_LUOT tính trên TỆP
    // Hỏi trước: xoá là việc khó lùi ở phía người dùng (tệp vào Thùng rác
    // Drive). Nói rõ nó KHÔNG đụng người khác — đó là thứ người bấm cần biết
    // để bấm mà không phải đoán.
    const ok = window.confirm(
      (laAnh ? `Bỏ ${khoaThe.length} bài ảnh (${ids.length} ảnh) khỏi thư viện của bạn?` : `Bỏ ${ids.length} video khỏi thư viện của bạn?`) +
      `${dongNgoaiTrang(demNgoaiTrang(state.selected, state.idTrang))}\n\n` +
      `Tệp vào Thùng rác Drive (lấy lại được trong 30 ngày). ` +
      `Người khác không bị ảnh hưởng, và lượt quét sau của bạn sẽ không tải lại chúng.`);
    if (!ok) return;

    // Gửi theo LÔ ≤ `LOAI_TOI_DA_MOI_LUOT`, tuần tự. Backend chặn cứng 50 id một
    // request (`web/app.py::MAX_VIDEO_LOAI` — mỗi id là một lượt gọi Drive đồng
    // bộ), còn thư viện một người đã có 86 video: gửi nguyên lựa chọn thì >50 là
    // 422 và KHÔNG video nào được bỏ (đo 23/09 10:45). Tuần tự chứ không song
    // song: song song là đúng cái request dài mà trần kia sinh ra để chặn.
    const tong = { da_loai: 0, drive_truot: 0, khong_phai_cua_ban: 0 };
    let loi = null;
    let loDaGui = 0;
    const daGui = new Set();
    const soLo = Math.ceil(ids.length / LOAI_TOI_DA_MOI_LUOT);
    for (let i = 0; i < ids.length; i += LOAI_TOI_DA_MOI_LUOT) {
      const lo = ids.slice(i, i + LOAI_TOI_DA_MOI_LUOT);
      try {
        const res = await apiSend("POST", "/videos/loai", { video_ids: lo });
        tong.da_loai += res.da_loai.length;
        tong.drive_truot += res.drive_truot.length;
        tong.khong_phai_cua_ban += res.khong_phai_cua_ban.length;
        // Gỡ khỏi lựa chọn ĐÚNG lô vừa xong — như bản một-lượt trước đây
        // `clear()` sau khi API trả về. Lô chưa gửi vẫn nằm đó để bấm lại.
        // Thẻ ảnh chỉ rời lựa chọn khi MỌI tệp của bài đã đi (một bài có thể cắt ngang hai lô).
        lo.forEach((id) => daGui.add(id));
        khoaThe.forEach((k) => { if (idTepCuaThe(k).every((f) => daGui.has(f))) state.selected.delete(k); });
        loDaGui++;
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        loi = err;
        break;
      }
    }

    // Nạp lại hỏng KHÔNG được nuốt câu tóm tắt: tệp đã vào Thùng rác, người dùng phải
    // biết số đã bỏ — câu "không tải lại được" gộp vào cùng toast (không đè nó).
    const nap = loDaGui > 0 ? await napLaiThuVien({ imLoi: true }) : "ok";
    renderSelectionBar();
    // Báo đủ ba con số, không gộp thành một chữ "xong": Drive trượt mà im
    // lặng thì người dùng tưởng đã dọn trong khi tệp còn nguyên.
    const phan = [`đã bỏ ${tong.da_loai}`];
    if (tong.drive_truot) phan.push(`${tong.drive_truot} chưa bỏ được khỏi Drive — thử lại`);
    if (tong.khong_phai_cua_ban) phan.push(`${tong.khong_phai_cua_ban} không phải của bạn`);
    if (loi) {
      phan.push(`dừng ở lô ${loDaGui + 1}/${soLo}: ${lyDoLoiLoai(loi)}`,
                `còn ${state.selected.size} video đang chọn — bấm lại để tiếp`);
    }
    if (nap === "loi") phan.push("không tải lại được thư viện — bấm Làm mới");
    if (nap === "het_phien") phan.push("phiên đã hết hạn — tải lại trang để thấy thư viện mới");
    showToast(phan.join(" · "));
  }
