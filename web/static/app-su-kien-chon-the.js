// Sự kiện chọn thẻ, thanh thao tác, thanh bên cụm; bỏ chọn.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // EVENTS — chọn thẻ + thanh thao tác
  // ========================================================================
  function toggleSelection(videoId) {
    if (state.selected.has(videoId)) state.selected.delete(videoId);
    else state.selected.add(videoId);
    const card = document.querySelector(`.card[data-video-id="${CSS.escape(videoId)}"]`);
    if (card) {
      const nowSelected = state.selected.has(videoId);
      card.classList.toggle("selected", nowSelected);
      card.setAttribute("aria-checked", String(nowSelected));
    }
    renderSelectionBar();
    veNutChonTrang();
  }

  document.getElementById("card-grid").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-video-link]")) return; // "Xem gốc" mở tab riêng, không chọn thẻ
    const card = ev.target.closest(".card");
    if (card) toggleSelection(card.dataset.videoId);
  });
  document.getElementById("card-grid").addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const card = ev.target.closest(".card");
    if (card) { ev.preventDefault(); toggleSelection(card.dataset.videoId); }
  });

  document.getElementById("selection-bar").addEventListener("click", (ev) => {
    const action = ev.target.dataset.action;
    if (!action) return;
    if (action === "clear") {
      boChonTatCa();
      return;
    }
    if (action === "loai") loaiDaChon();
    if (action === "self-bundle") moBoTuTim();
    if (action === "cum") {
      const pop = document.getElementById("cum-popover");
      // Mở hộp gán cụm khi có video đã chọn ở trang khác ⇒ hỏi trước, nêu số.
      const ngoai = demNgoaiTrang(state.selected, state.idTrang);
      if (pop.hidden && ngoai > 0 && !window.confirm(
        `Đưa ${state.selected.size} video vào cụm?${dongNgoaiTrang(ngoai)}`)) return;
      pop.hidden = !pop.hidden;
      renderPopoverCum();
    }
  });

  // Uỷ quyền trên vùng cha vì thanh bên, đầu cụm và ô popover đều vẽ lại sau
  // mỗi lần lọc — gắn thẳng lên nút thì nút mới vẽ ra sẽ câm.
  document.getElementById("cum-popover").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-gan-cum]");
    if (b) ganVaoCumCoSan(Number(b.dataset.ganCum));
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.closest(".cum-form")) capNhatXemTruoc(ev.target.closest(".cum-form").parentElement);
  });
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest(".cum-form");
    if (!f) return;
    ev.preventDefault();
    guiFormCum(f);
  });
  document.getElementById("cum-rail").addEventListener("click", (ev) => {
    const hang = ev.target.closest("[data-cum-loc]");
    if (hang) {
      const loc = hang.dataset.cumLoc;
      doiCumLoc(loc === "tat_ca" || loc === "chua" ? loc : Number(loc));
      return;
    }
    if (ev.target.closest("[data-cum-moi]")) {
      const f = document.getElementById("cum-moi-form");
      f.hidden = !f.hidden;
      capNhatXemTruoc(f);
    }
  });
  document.getElementById("cum-head").addEventListener("click", (ev) => {
    const cum = state.cums.find((c) => c.id === state.cumLoc);
    if (!cum) return;
    const lo = ev.target.closest("[data-mo-lo]");
    if (lo) {
      moLoCum(cum.id, Number(lo.dataset.moLo)).then((kq) => {
        if (kq === "chan") showToast("Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại.");
      }).catch((err) => {
        // Không được để lỗi rơi thành unhandled rejection câm — mọi nhánh lỗi
        // mong đợi đã tự báo toast BÊN TRONG `moLoCum`; nhánh này chỉ còn bắt
        // cái GÌ ĐÓ không lường trước.
        if (err instanceof PhienHetHan) baoPhienHetHan();
        else showToast(`Lỗi không lường trước khi mở Creative Desk: ${err.message || err}`);
      });
      return;
    }
    if (ev.target.closest("[data-mo-het]")) {
      moHetLoCum(cum.id).catch((err) => {
        if (err instanceof PhienHetHan) baoPhienHetHan();
        else showToast(`Lỗi không lường trước khi mở Creative Desk: ${err.message || err}`);
      });
      return;
    }
    if (ev.target.closest("[data-doi-kieu]")) { doiKieuCum(cum); return; }
    if (ev.target.closest("[data-xoa-cum]")) xoaCum(cum);
  });

  // Bỏ chọn một nhóm video, giữ nguyên phần còn lại của lựa chọn.
  function boChonCacVideo(ids) {
    ids.forEach((id) => state.selected.delete(id));
    document.querySelectorAll("#card-grid .card").forEach((c) => {
      const chon = state.selected.has(c.dataset.videoId);
      c.classList.toggle("selected", chon);
      c.setAttribute("aria-checked", String(chon));
    });
    renderSelectionBar();
    veNutChonTrang();
  }

  // Bỏ chọn tất cả: xoá state VÀ gỡ dấu trên thẻ. Hai vế phải đi cùng nhau —
  // `loaiDaChon` thoát được vế thứ hai chỉ vì nó `loadVideos()` dựng lại toàn
  // bộ lưới ngay sau đó. Đường nào KHÔNG nạp lại lưới mà chỉ xoá state sẽ để
  // thẻ tô xanh trong khi thanh chọn nói "0 video", và lần bấm kế tiếp đọc
  // một state khác với cái người dùng đang nhìn.
  function boChonTatCa() {
    state.selected.clear();
    document.querySelectorAll(".card.selected").forEach((c) => {
      c.classList.remove("selected");
      c.setAttribute("aria-checked", "false");
    });
    renderSelectionBar();
    veNutChonTrang();
  }
