// Vẽ lưới thẻ video, phân trang, thanh chọn và toast.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // RENDER — lưới thẻ + trạng thái rỗng
  // ========================================================================
  // ---- Phân trang thư viện (user 23/09: "phân ra theo trang 10/20/40/100";
  // 26/09 thêm 30: "thêm phần 30 video/page").
  // `loadVideos` đã nạp TRỌN thư viện (lô `LIBRARY_PAGE`, trần `LIBRARY_MAX` mỗi phía chip), bộ lọc chạy ở đây ⇒
  // phân trang cắt trên danh sách ĐÃ LỌC, không cần tham số trang ở API.
  // 17/11/2026 (user, đại tu giao diện hướng B): bộ chọn còn 20 / 50 / 100, mặc định 20.
  const SO_MOI_TRANG = Object.freeze([20, 50, 100]);
  const SO_MOI_TRANG_MAC_DINH = 20;

  // Hàm thuần — test gọi thẳng. `trang` 1-based; kẹp vào [1, soTrang] để một
  // trang cũ (vd trang 3 khi bộ lọc chỉ còn 5 video) không ra lưới rỗng.
  function catTrang(danhSach, trang, soMoiTrang) {
    const soTrang = Math.max(1, Math.ceil(danhSach.length / soMoiTrang));
    const t = Math.min(Math.max(1, trang), soTrang);
    const dau = (t - 1) * soMoiTrang;
    const muc = danhSach.slice(dau, dau + soMoiTrang);
    return { trang: t, soTrang, dau, muc };
  }

  const KHOA_SO_MOI_TRANG = "videodl-per-page";
  function docSoMoiTrang() {
    try {
      const n = Number(localStorage.getItem(KHOA_SO_MOI_TRANG));
      return SO_MOI_TRANG.includes(n) ? n : SO_MOI_TRANG_MAC_DINH;
    } catch (e) { return SO_MOI_TRANG_MAC_DINH; }  // private mode
  }

  // Dải nút trang THU GỌN: 1 … t-2..t+2 … cuối. Trần nạp 5000 ở 10/trang là
  // 500 trang — in đủ 500 nút là thanh điều hướng dài hơn cả lưới.
  function dayTrang(t, soTrang) {
    const giu = new Set([1, soTrang]);
    for (let i = t - 2; i <= t + 2; i++) if (i >= 1 && i <= soTrang) giu.add(i);
    const ds = [...giu].sort((a, b) => a - b);
    const ra = [];
    ds.forEach((n, i) => { if (i && n - ds[i - 1] > 1) ra.push("…"); ra.push(n); });
    return ra;
  }

  function veNutChonTrang() {
    const nut = document.getElementById("chon-trang");
    if (!nut) return;
    const ids = state.idTrang;
    const du = ids.length > 0 && ids.every((id) => state.selected.has(id));
    // Hộp tick thật (role=checkbox): nhãn cố định "Chọn cả trang (N)", trạng thái nằm ở aria-checked.
    nut.innerHTML = `<span class="hop-tick" aria-hidden="true"></span><span>Chọn cả trang (${ids.length})</span>`;
    nut.setAttribute("aria-checked", String(du));
    nut.classList.toggle("on", du);
  }

  function vePhanTrang(ct, tongLoc) {
    const toolbar = document.getElementById("lib-toolbar");
    const pager = document.getElementById("lib-pager");
    toolbar.hidden = pager.hidden = tongLoc === 0;
    if (tongLoc === 0) return;
    const nav = ct.soTrang === 1 ? "" :
      `<button type="button" data-trang="${ct.trang - 1}" aria-label="Trang trước" ${ct.trang === 1 ? "disabled" : ""}>‹</button>` +
      dayTrang(ct.trang, ct.soTrang).map((n) => n === "…" ? `<span class="gian">…</span>` :
        `<button type="button" data-trang="${n}" class="${n === ct.trang ? "on" : ""}"` +
        `${n === ct.trang ? ' aria-current="page"' : ""}>${n}</button>`).join("") +
      `<button type="button" data-trang="${ct.trang + 1}" aria-label="Trang sau" ${ct.trang === ct.soTrang ? "disabled" : ""}>›</button>`;
    document.querySelectorAll("[data-pager]").forEach((el) => { el.innerHTML = nav; });
    document.getElementById("so-moi-trang").innerHTML = SO_MOI_TRANG.map((n) =>
      `<button type="button" data-so="${n}" class="${n === state.soMoiTrang ? "on" : ""}" aria-pressed="${n === state.soMoiTrang}">${n}</button>`).join("");
    document.getElementById("lib-pager-dem").textContent =
      `Hiện ${ct.dau + 1}–${ct.dau + ct.muc.length} / ${tongLoc} video`;
    veNutChonTrang();
  }

  // Đổi trang / đổi số mỗi trang GIỮ lựa chọn (user 26/09: "khi tôi chọn tôi mở
  // qua trang mới không bị mất chọn"; đổi số/trang: "giữ"). Bản 23/09 xoá lựa chọn
  // vì người ta không thấy thẻ đã chọn ở trang kia — cái giá đó giờ trả bằng
  // CON SỐ: thanh chọn nói bao nhiêu video đã chọn KHÔNG hiện ở trang này (ở
  // trang khác, hoặc đang bị bộ lọc ẩn — bộ lọc vốn giữ lựa chọn), và Xoá / Đưa
  // vào cụm nhắc lại con số đó trước khi chạy. "Tạo bộ tự tìm" không hỏi: nó
  // không ghi gì, và Creative Desk hiện đủ danh sách trước khi tạo bộ.
  // "Chọn tất cả" vẫn chỉ là trang đang xem.
  //
  // Hàm thuần — test gọi thẳng.
  function demNgoaiTrang(selected, idTrang) {
    const trang = new Set(idTrang);
    let n = 0;
    for (const id of selected) if (!trang.has(id)) n++;
    return n;
  }

  function nhanNgoaiTrang(soNgoai) {
    return soNgoai > 0 ? `· ${soNgoai} không hiện ở trang này` : "";
  }

  // Dòng chèn vào hộp xác nhận của thao tác hàng loạt; rỗng khi mọi video đã
  // chọn đang nằm trên màn hình.
  function dongNgoaiTrang(soNgoai) {
    return soNgoai > 0
      ? `\n\nTrong đó ${soNgoai} video không hiện ở trang này (ở trang khác hoặc đang bị bộ lọc ẩn).`
      : "";
  }

  function doiTrang(n) {
    if (n === state.trang) return;
    state.trang = n;
    renderLibrary();
    document.getElementById("library-count").scrollIntoView({ block: "start" });
  }

  function doiSoMoiTrang(n) {
    if (n === state.soMoiTrang || !SO_MOI_TRANG.includes(n)) return;
    state.soMoiTrang = n;
    state.trang = 1;
    try { localStorage.setItem(KHOA_SO_MOI_TRANG, String(n)); } catch (e) { /* private mode */ }
    renderLibrary();
  }

  function chonTrangNay() {
    const ids = state.idTrang;
    const du = ids.length > 0 && ids.every((id) => state.selected.has(id));
    ids.forEach((id) => (du ? state.selected.delete(id) : state.selected.add(id)));
    document.querySelectorAll("#card-grid .card").forEach((c) => {
      const chon = state.selected.has(c.dataset.videoId);
      c.classList.toggle("selected", chon);
      c.setAttribute("aria-checked", String(chon));
    });
    renderSelectionBar();
    veNutChonTrang();
  }

  // Đổi BỘ LỌC ⇒ về trang 1 nhưng GIỮ lựa chọn (điều phối chốt 14:50): bộ lọc vốn
  // đã giữ lựa chọn trước khi có phân trang, không đổi hành vi đó ở đây.
  function sauKhiDoiBoLoc() {
    state.trang = 1;
    renderFilterBar();
    renderLibrary();
  }

  function renderLibrary() {
    const grid = document.getElementById("card-grid");
    const emptyState = document.getElementById("empty-state");
    const noMatch = document.getElementById("no-match-state");

    veChipVaoBo();
    // "Thư viện chưa có video nào" chỉ khi CẢ HAI phía chip đều rỗng. Lưới chỉ nạp
    // một phía: phía này rỗng mà phía kia có (chip bật mà chưa video nào vào bộ,
    // hoặc mọi video đều đã vào bộ) là "không khớp bộ lọc", như trước.
    if (state.videos.length === 0 && !state.chiVaoBo && !(state.tongVaoBo > 0)) {
      emptyState.hidden = false;
      noMatch.hidden = true;
      grid.hidden = true;
      grid.innerHTML = "";
      state.idTrang = [];
      renderSelectionBar();
      vePhanTrang(null, 0);
      renderCumRail();
      renderCumHead();
      document.getElementById("library-count").textContent = "";
      renderActiveFilters();
      return;
    }
    emptyState.hidden = true;

    const filtered = state.videos.filter(videoMatchesFilters);
    // Nhãn phải phân biệt được BA con số: số khớp bộ lọc, số đã nạp, và số
    // thật trong thư viện. Gộp hai cái sau là cách con số sai mang hình dạng
    // con số đúng.
    const total = state.videosTotal ?? state.videos.length;
    const loaded = state.videos.length;
    // Mẫu số "x/N" là tập đang hiện theo chip (không gồm video đã vào bộ khi chip tắt):
    // video ẩn theo thiết kế không phải "bị bộ lọc loại".
    const nen = videoTrongNen().length;
    const parts = [];
    parts.push(filtered.length === nen ? `${nen}` : `${filtered.length}/${nen}`);
    parts.push(state.chiVaoBo ? "video đã vào bộ" : "video");
    if (loaded < total) parts.push(`(đang hiện ${loaded} trong ${total})`);
    document.getElementById("library-count").textContent = parts.join(" ");

    noMatch.hidden = filtered.length > 0;
    grid.hidden = filtered.length === 0;
    const ct = catTrang(filtered, state.trang, state.soMoiTrang);
    state.trang = ct.trang;  // kẹp: bỏ video / đổi lọc có thể làm trang cũ vượt quá
    state.idTrang = ct.muc.map((v) => v.video_id);
    renderSelectionBar();  // "· N ở trang khác" đổi theo trang đang xem
    grid.innerHTML = ct.muc.map(renderCard).join("");
    vePhanTrang(ct, filtered.length);
    wireThumbFallback();
    renderActiveFilters();
    renderCumRail();
    renderCumHead();
  }

  // Ngày (không giờ) theo múi giờ của trình duyệt; rỗng nếu không đọc được.
  function fmtNgay(iso) {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? escapeHtml(d.toLocaleDateString("vi-VN")) : "";
  }

  // Huy hiệu mã bộ + ngày sẽ xoá khỏi Video Desk cho video đã vào bộ. Nhiều bộ ⇒ một
  // huy hiệu "N.2809C · N.2909B". Nguồn sự thật về bộ là folder id ở server; đây chỉ hiện.
  function renderBoDaVao(b) {
    if (!b) return "";
    const ma = b.ma_bo && b.ma_bo.length ? b.ma_bo.map(escapeHtml).join(" · ") : "Đã vào bộ";
    const ngay = fmtNgay(b.se_don_luc);
    return `<div class="card-bo"><span class="bo-ma" title="Mã bộ tự tìm">${ma}</span>` +
      (ngay ? `<span class="bo-don">Xoá khỏi Video Desk ${ngay}</span>` : "") + `</div>`;
  }

  function renderCard(video) {
    const isSelected = state.selected.has(video.video_id);
    const duration = fmtDuration(video.duration);
    const plays = fmtCount(video.play_count);
    const metaParts = [];
    metaParts.push(escapeHtml(video.author || "(chưa rõ người đăng)"));
    if (video.region) metaParts.push(escapeHtml(video.region));
    if (plays !== null) metaParts.push(`${plays} lượt xem`);
    return `
      <div class="card${isSelected ? " selected" : ""}" data-video-id="${escapeHtml(video.video_id)}" role="checkbox" aria-checked="${isSelected}" tabindex="0">
        <div class="card-thumb">
          <img src="/thumbs/${encodeURIComponent(video.video_id)}" alt="" loading="lazy" />
          ${duration ? `<span class="card-duration">${duration}</span>` : ""}
        </div>
        <span class="card-check"></span>
        <div class="card-body">
          <div class="card-title">${escapeHtml(video.title || "(chưa có tiêu đề)")}</div>
          <div class="card-meta">${metaParts.map((m, i) => i === 0 ? m : `<span class="sep">·</span>${m}`).join(" ")}</div>
          ${renderBoDaVao(video.vao_bo)}
          ${video.url
            ? `<a class="card-link" href="${escapeHtml(video.url)}" target="_blank" rel="noopener" data-video-link>Xem gốc ↗</a>`
            : `<span class="card-link card-link-trong">chưa rõ link gốc</span>`}
          ${chipCum(video)}
        </div>
      </div>`;
  }

  // <img onerror> gắn bằng JS (không nhúng vào chuỗi HTML) để không phải
  // escape lồng attribute, và vì 404 là NGOẠI LỆ BÌNH THƯỜNG cần một hình
  // dạng riêng, không phải icon-ảnh-vỡ mặc định của trình duyệt.
  function wireThumbFallback() {
    document.querySelectorAll(".card-thumb img").forEach((img) => {
      img.addEventListener("error", () => {
        const wrap = img.closest(".card-thumb");
        wrap.classList.add("no-thumb");
        img.remove();
        const note = document.createElement("span");
        note.textContent = "Chưa cắt được ảnh";
        wrap.appendChild(note);
      }, { once: true });
    });
  }

  // ========================================================================
  // RENDER — thanh chọn + toast
  // ========================================================================
  function renderSelectionBar() {
    const bar = document.getElementById("selection-bar");
    bar.hidden = state.selected.size === 0;
    if (bar.hidden) { const pop = document.getElementById("cum-popover"); if (pop) pop.hidden = true; }
    document.getElementById("selection-count").textContent = `${state.selected.size} đã chọn`;
    const ngoai = document.getElementById("selection-ngoai");
    if (ngoai) ngoai.textContent = nhanNgoaiTrang(demNgoaiTrang(state.selected, state.idTrang));
  }

  let toastTimer = null;
  function showToast(text) {
    const el = document.getElementById("toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    // Câu dài (vd. lý do 409 của máy chủ) cần thời gian đọc: 2,6 s chỉ đủ cho câu ngắn.
    toastTimer = setTimeout(() => { el.hidden = true; }, Math.max(2600, text.length * 60));
  }
