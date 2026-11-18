// Sự kiện hàng đợi (rút/chạy lại/popup) và bộ lọc/chip/popover cụm.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // EVENTS — bộ lọc (mở/đóng popover, tick checkbox, gỡ pill)
  // ========================================================================
  function closeAllFilterPanels(exceptGroupId) {
    document.querySelectorAll(".filter-panel").forEach((p) => {
      if (p.dataset.panel !== exceptGroupId) p.hidden = true;
    });
    document.querySelectorAll(".filter-trigger[data-toggle]").forEach((t) => {
      if (t.dataset.toggle !== exceptGroupId) t.setAttribute("aria-expanded", "false");
    });
  }

  // Rút lượt. Uỷ quyền trên `queue-list` vì hàng đợi vẽ lại mỗi nhịp poll —
  // gắn trực tiếp lên từng nút thì nút mới sau mỗi lần vẽ sẽ không có tay
  // nghe nào, và hỏng ÂM THẦM: nút vẫn ở đó, bấm không ra gì.
  // Hàng đợi hướng B: "Chép link" đã có sẵn trên thẻ (bao-thieu.js `data-chep-link`); đây chỉ thêm "Xem tất cả N" + nút ‹ ›.
  const xemHetNut = document.getElementById("queue-xem-het");
  if (xemHetNut) xemHetNut.addEventListener("click", () => {
    const l = document.getElementById("queue-list");
    l.classList.toggle("xem-het");
    xemHetNut.textContent = l.classList.contains("xem-het") ? "Thu gọn" : `Xem tất cả ${state.jobs.length} →`;
  });
  // Popup chi tiết (mock R-07 v2): bấm thân thẻ / "Chi tiết", hoặc Enter/Space khi thẻ đang focus. Bấm NÚT/LIÊN KẾT/Ô NHẬP
  // trên thẻ chỉ chạy việc của nút — KHÔNG mở popup (bỏ cái guard này thì mọi nút đều bật popup).
  const hnScrim = document.getElementById("hn-scrim");
  const hnPop = document.getElementById("hn-pop");
  const queueList = document.getElementById("queue-list");
  // Hàng đợi vẽ lại mỗi nhịp poll và popup có cùng bộ nút ⇒ uỷ quyền gắn cho CẢ HAI chỗ.
  const tren = (loai, fn) => { queueList.addEventListener(loai, fn); hnPop.addEventListener(loai, fn); };
  queueList.addEventListener("click", (ev) => {
    if (ev.target.closest("button, a, input, label")) return;
    const the = ev.target.closest(".queue-item");
    if (the) moPopup(Number(the.id.replace("job-", "")));
  });
  queueList.addEventListener("keydown", (ev) => {
    if (ev.target.classList && ev.target.classList.contains("queue-item") && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      moPopup(Number(ev.target.id.replace("job-", "")));
    }
  });
  hnScrim.addEventListener("click", (ev) => {
    if (ev.target === hnScrim || ev.target.closest("[data-hn-dong]")) dongPopup(true);
    // Chia cụm mở màn riêng ở lớp trên: đóng popup sau khi tay nghe `data-chia` (chia-cum.js) đã đọc nút.
    else if (ev.target.closest("[data-chia]")) setTimeout(() => dongPopup(false), 0);
  });
  document.addEventListener("keydown", (ev) => {
    if (state.popupId === null) return;
    if (ev.key === "Escape") { ev.preventDefault(); dongPopup(true); return; }
    if (ev.key !== "Tab") return;
    // Giữ Tab trong popup (aria-modal).
    const f = [...hnPop.querySelectorAll("button:not(:disabled), a[href], input")];
    if (!f.length) return;
    const dau = f[0], cuoi = f[f.length - 1];
    if (!hnPop.contains(document.activeElement)) { ev.preventDefault(); dau.focus(); }
    else if (ev.shiftKey && document.activeElement === dau) { ev.preventDefault(); cuoi.focus(); }
    else if (!ev.shiftKey && document.activeElement === cuoi) { ev.preventDefault(); dau.focus(); }
  });
  document.querySelectorAll("[data-cuon]").forEach((b) => b.addEventListener("click", () => {
    const l = document.getElementById("queue-list");
    l.scrollBy({ left: Number(b.dataset.cuon) * 272, behavior: "smooth" });
  }));
  tren("click", async (ev) => {
    const btn = ev.target.closest("[data-huy]");
    if (!btn) return;
    const jobId = Number(btn.dataset.huy);
    btn.disabled = true;
    try {
      await apiSend("DELETE", `/jobs/${jobId}`);
      showToast("Đã rút lượt khỏi hàng đợi.");
    } catch (err) {
      if (err instanceof PhienHetHan) throw err;
      // 409 là ca THẬT, không phải lỗi người dùng: worker vừa nhặt job
      // đúng lúc họ bấm. Nói đúng chuyện đó, đừng nói "không tìm thấy".
      // Job đang giải xác minh (`dang_mo`/`dang_giai`): câu của máy chủ nói đúng chuyện đó —
      // đừng bảo "đã bắt đầu tải" khi chưa tải gì.
      showToast(!String(err.message).includes("409") ? "Không rút được lượt này."
        : (typeof err.ma === "string" && err.ma.includes("giải xác minh"))
          ? err.ma
          : "Lượt này vừa bắt đầu tải nên không rút được nữa.");
    } finally {
      // Vẽ lại từ máy chủ trong MỌI ca, kể cả ca trượt: trạng thái thật
      // nằm ở DB, và sau một lần 409 thì hàng này đã sang "Đang chạy".
      await loadJobs();
    }
  });

  // Chạy lại để kiếm thêm + chép link. Cùng lý do uỷ quyền như "Rút lượt".
  // "Xác minh" (= "Tôi giải ngay") / "Mở cửa sổ giải" (giải xác minh trong popup — `giai-captcha-popup.js`).
  // Uỷ quyền như "Rút lượt": thẻ job vẽ lại mỗi nhịp poll/SSE.
  tren("click", (ev) => {
    const nut = ev.target.closest("[data-giai-ngay],[data-mo-giai]");
    if (!nut) return;
    const id = Number(nut.dataset.giaiNgay ?? nut.dataset.moGiai);
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return;
    if (hnPop.contains(nut)) dongPopup(false);   // cửa sổ giải mở ở lớp trên: không để hai hộp thoại chồng nhau
    if (nut.dataset.giaiNgay !== undefined) window.GiaiCaptcha.giaiNgay(job, nut);
    else window.GiaiCaptcha.mo(job);
  });
  tren("input", (ev) => {
    const o = ev.target.closest("[data-chay-lai-n]");
    if (o) state.chayLai.set(Number(o.dataset.chayLaiN), o.value);
  });
  tren("click", async (ev) => {
    const nut = ev.target.closest("[data-chay-lai],[data-chay-lai-ok],[data-chay-lai-huy],[data-chep-link],[data-tai-lai]");
    if (!nut) return;
    const id = Number(nut.dataset.chayLai ?? nut.dataset.chayLaiOk ?? nut.dataset.chayLaiHuy ?? nut.dataset.chepLink ?? nut.dataset.taiLai);
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return;
    if (nut.dataset.chepLink !== undefined) {
      try {
        await navigator.clipboard.writeText(job.url);
        showToast("Đã chép link.");
      } catch (e) {
        showToast("Không chép được — chọn và copy tay.");
      }
    } else if (nut.dataset.taiLai !== undefined) {
      // "Tải lại": cùng link, cùng số xin (`tong`), cùng usecase/insight — một POST /jobs như form và "Tải thêm".
      if (state.dangGuiTaiLai.has(id)) return;
      state.dangGuiTaiLai.add(id);
      renderQueue();
      try {
        const kq = await guiTaoJob(taoJobBody(job.url, job.tong, job.usecase, job.insight_goc));
        if (kq.ok) {
          showToast(`Đã tạo lượt mới tải lại ${job.tong} video.`);
          if (state.popupId === id) dongPopup(false);
        } else {
          showToast(kq.loi);
        }
      } finally {
        state.dangGuiTaiLai.delete(id);
        renderQueue();
      }
    } else if (nut.dataset.chayLai !== undefined) {
      state.chayLai.set(id, window.BaoThieu.soChayLai(job));
      renderQueue();
      const o = (state.popupId === id ? hnPop : queueList).querySelector(`[data-chay-lai-n="${id}"]`);
      if (o) o.focus();
    } else if (nut.dataset.chayLaiHuy !== undefined) {
      state.chayLai.delete(id);
      renderQueue();
    } else {
      const n = window.BaoThieu.chuanHoaSoChayLai(state.chayLai.get(id));
      if (n === null) {
        showToast(`Số video phải từ 1 đến ${window.BaoThieu.MAX_SO_LUONG}.`);
        return;
      }
      // `disabled` đặt tay lên nút sẽ MẤT ở lần vẽ lại kế tiếp (poll/SSE thay
      // `innerHTML`), nên cờ sống ở `state` và cả lần vẽ lẫn lần bấm đều đọc nó.
      if (state.dangGuiChayLai.has(id)) return;
      state.dangGuiChayLai.add(id);
      renderQueue();
      try {
        // Đúng đường tạo lượt của form: một POST /jobs, không route riêng.
        // Mang theo usecase / insight gốc của lượt gốc: chạy lại là CÙNG một
        // việc, và bỏ hai ô này thì màn nháp duyệt kiểu hỏi lại từ đầu.
        const kq = await guiTaoJob(taoJobBody(job.url, n, job.usecase, job.insight_goc));
        if (kq.ok) {
          state.chayLai.delete(id);
          showToast(`Đã tạo lượt mới kiếm thêm ${n} video.`);
        } else {
          showToast(kq.loi);
        }
      } finally {
        state.dangGuiChayLai.delete(id);
        renderQueue();
      }
    }
  });

  document.getElementById("filter-bar").addEventListener("click", (ev) => {
    const trigger = ev.target.closest("[data-toggle]");
    if (trigger) {
      const groupId = trigger.dataset.toggle;
      const panel = document.querySelector(`.filter-panel[data-panel="${groupId}"]`);
      const willOpen = panel.hidden;
      closeAllFilterPanels(willOpen ? groupId : null);
      panel.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) renderFilterPanelBody(FILTER_GROUPS.find((g) => g.id === groupId));
      return;
    }
  });

  document.getElementById("filter-bar").addEventListener("change", (ev) => {
    const box = ev.target;
    if (box.tagName !== "INPUT" || box.type !== "checkbox") return;
    const groupId = box.dataset.group;
    const group = FILTER_GROUPS.find((g) => g.id === groupId);
    const selected = state.filters[groupId];
    if (box.checked) {
      const bucket = buildBuckets(group).find((b) => b.key === box.value);
      selected.set(box.value, bucket ? bucket.label : box.value);
    } else {
      selected.delete(box.value);
    }
    sauKhiDoiBoLoc(); // cập nhật badge số lượng trên nút + về trang 1
  });

  // Đổi phía chip = nạp lại thư viện phía đó (server lọc). Lựa chọn ở phía kia
  // rơi và được nói ra (`loadVideos`) — giữ id ngoài tập đã nạp là mở đường Xoá mù.
  //
  // Chip đổi trạng thái NGAY; lưới giữ nội dung cũ, đánh dấu đang nạp
  // (`aria-busy`, `data-nap-phia` rỗng) và chỉ vẽ lại khi phía mới về — vẽ ngay
  // thì lưới nháy "không khớp bộ lọc" trên tập của phía kia.
  function doiPhiaVaoBo(chiVaoBo) {
    if (state.chiVaoBo === chiVaoBo) return Promise.resolve();
    state.chiVaoBo = chiVaoBo;
    state.trang = 1;
    veChipVaoBo();
    const grid = document.getElementById("card-grid");
    grid.setAttribute("aria-busy", "true");
    grid.dataset.napPhia = "";
    // Nạp hỏng thì `loadVideos` tự đưa chip/lưới về phía đã vẽ; ở đây chỉ báo.
    return napLaiThuVien({ lyDoRoi: "vì đang xem phía khác của chip “Đã vào bộ”" });
  }

  document.getElementById("chip-vao-bo").addEventListener("click", () => {
    doiPhiaVaoBo(!state.chiVaoBo);
  });

  document.getElementById("active-filters").addEventListener("click", (ev) => {
    if (ev.target.id === "clear-all-pill") {
      for (const g of FILTER_GROUPS) state.filters[g.id].clear();
      sauKhiDoiBoLoc();
      return;
    }
    const btn = ev.target.closest("[data-remove-group]");
    if (btn) {
      state.filters[btn.dataset.removeGroup].delete(btn.dataset.removeKey);
      sauKhiDoiBoLoc();
    }
  });

  document.getElementById("clear-filters-btn").addEventListener("click", () => {
    for (const g of FILTER_GROUPS) state.filters[g.id].clear();
    state.cumLoc = "tat_ca";
    if (state.chiVaoBo) {
      renderFilterBar();   // huy hiệu số trên nút nhóm — lưới vẽ lại khi phía 0 về
      doiPhiaVaoBo(false);
    } else sauKhiDoiBoLoc();
  });

  function dongPopoverCum() {
    const pop = document.getElementById("cum-popover");
    if (pop) pop.hidden = true;
  }
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".filter-box")) closeAllFilterPanels(null);
    if (!ev.target.closest(".pop-wrap")) dongPopoverCum();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { closeAllFilterPanels(null); dongPopoverCum(); }
  });
