// Cụm của tôi: thanh bên, đầu cụm, chip, mở lô sang Creative Desk, gán video.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // CỤM CỦA TÔI — thanh bên, đầu cụm, chip trên thẻ, "Đưa vào cụm"
  // ========================================================================
  // Hàm thuần: tách danh sách thành lô ≤ `toiDa` (64 ⇒ 30/30/4; 0 ⇒ không lô).
  function chiaLo(ds, toiDa) {
    const ra = [];
    for (let i = 0; i < ds.length; i += toiDa) ra.push(ds.slice(i, i + toiDa));
    return ra;
  }

  // Nhãn "x/N" từ mốc đã mở `m`: `so_item` = số item THẬT đã gửi, `so_video`
  // = số video của lô LÚC ĐÓ (cùng một response payload, xem `moLoCum`). Chỉ
  // hiện "x/N" khi biết cả hai và x < N — video bị lọc vì chưa lên Drive/thiếu
  // link gốc hợp lệ; biết cả hai và x == N ⇒ N trơn CỦA LÚC MỞ (không bịa
  // "n/n"). Chỉ khi CHƯA biết cặp (mốc cũ/client cũ) mới rơi về `nHienTai`
  // (số video hiện tại của lô) — đếm phía trang có thể cũ hoặc lô đã đổi sau
  // khi mở, nên không bao giờ ghép nó với số đã gửi.
  function nhanSoVideo(m, nHienTai) {
    const x = m && m.so_item, n = m && m.so_video;
    if (typeof x !== "number" || typeof n !== "number") return `${nHienTai}`;
    return x < n ? `${x}/${n}` : `${n}`;
  }

  // Khoá so trùng cụm: trim + gộp khoảng trắng + không phân biệt hoa/thường.
  function khoaNhan(s) {
    return String(s || "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  }

  // Cụm có sẵn trùng (usecase, insight gốc, kiểu) theo `khoaNhan`, hoặc null.
  // "Couple" và "couple" là MỘT cụm — tạo hai là tạo hai insight trùng bên kia.
  // Cùng khoá với server (`models_cum._khoa_ten`): usecase + insight CON — thứ
  // Creative Desk nhìn thấy. Đây chỉ là gợi ý sớm cho ô xem trước; server mới
  // là bên quyết (POST /cum trả lại cụm có sẵn khi trùng).
  function timCumTrung(dsCum, usecase, goc, kieu) {
    const k = [khoaNhan(usecase), khoaNhan(xemTruocTen(goc, kieu))].join("\u0000");
    return dsCum.find((c) =>
      [khoaNhan(c.usecase), khoaNhan(c.insight)].join("\u0000") === k) || null;
  }

  // CHỈ để xem trước tên trong ô "cụm mới" — cụm chưa tồn tại nên chưa có
  // `insight` từ server. Cụm đã tạo thì mọi nơi đọc `cum.insight`.
  function xemTruocTen(goc, kieu) {
    return `${goc} ${kieu}`.split(/\s+/).filter(Boolean).join(" ");
  }

  // Video của cụm, CŨ trước: video mới đưa vào nối vào lô cuối thay vì xô lệch
  // Bộ 1/n đã mở. ⚠ Giới hạn đã biết (điều phối chốt 23/09): mốc "đã mở" gắn
  // theo SỐ THỨ TỰ lô; thêm/bớt video làm ranh giới lô dịch đi, và đổi kiểu
  // cũng không xoá mốc cũ — không có cảnh báo "mở dưới tên cũ".
  //
  // Có ngoại lệ ĐÃ CHẶN: video được DỌN khỏi Drive (ngày 7 sau khi vào bộ) KHÔNG
  // làm lô trượt. Chúng không nằm trong `state.videos` (không hiện ở đâu) nhưng
  // vẫn GIỮ CHỖ ở đây, đánh dấu `da_don: true` — cùng tập với server cắt lô
  // (`models_chia._video_trong_lo`, video cũ nhất trước theo (tao_luc, video_id)).
  // Người dùng của hàm này tự bỏ chúng khi đếm video còn sống / gửi đi.
  //
  // Server có `khung_cum` (`GET /cum`) ⇒ cắt từ khung đó: MỌI thành viên của
  // cụm, đúng thứ tự server, kể cả video cũ nằm ngoài `LIBRARY_MAX` video mới
  // nhất đã nạp (không có khung thì các video đó rơi khỏi lô ⇒ lô trượt). Giữ
  // NGUYÊN thứ tự khung, không sắp lại. Đắp đối tượng đầy đủ từ `state.videos`
  // nếu có; không có thì dùng phần tử khung (người dùng chỉ đọc `.da_don` +
  // độ dài). Server cũ không trả khung ⇒ đường cũ bên dưới.
  function videoCuaCum(cumId) {
    if (Array.isArray(state.khungCum)) {
      const daNap = new Map(state.videos.map((v) => [v.video_id, v]));
      return state.khungCum.filter((g) => g.cum_id === cumId).map((g) => {
        const v = daNap.get(g.video_id);
        if (v && !g.da_don) return v;
        return { video_id: g.video_id, tao_luc: g.tao_luc, cum_id: g.cum_id, da_don: !!g.da_don };
      });
    }
    const song = state.videos.filter((v) => v.cum_id === cumId).reverse();
    const da = (state.videosDaDon || []).filter((g) => g.cum_id === cumId)
      .map((g) => ({ video_id: g.video_id, tao_luc: g.tao_luc, cum_id: g.cum_id, da_don: true }));
    if (!da.length) return song;
    return song.concat(da).sort((a, b) =>
      a.tao_luc < b.tao_luc ? -1 : a.tao_luc > b.tao_luc ? 1
        : a.video_id < b.video_id ? -1 : a.video_id > b.video_id ? 1 : 0);
  }

  function mauCum(id) { return `hsl(${(id * 67) % 360} 55% 50%)`; }

  function renderCumRail() {
    const rail = document.getElementById("cum-rail");
    if (!rail) return;
    const dem = new Map();
    let chua = 0;
    const nen = videoTrongNen();
    for (const v of nen) {
      if (v.cum_id == null) chua++; else dem.set(v.cum_id, (dem.get(v.cum_id) || 0) + 1);
    }
    const hang = (loc, nhan, n, lop = "") =>
      `<button type="button" class="cum-row ${lop}${state.cumLoc === loc ? " on" : ""}" data-cum-loc="${loc}">` +
      `${nhan}<span class="n">${n}</span></button>`;
    let h = `<h3>Cụm của tôi</h3>` + hang("tat_ca", "Tất cả", nen.length) +
      hang("chua", "Chưa vào cụm", chua, "chua") + `<hr class="rail-sep">`;
    const nhom = new Map();
    for (const c of state.cums) {
      const k = `${c.usecase}\u0000${c.insight_goc}`;
      if (!nhom.has(k)) nhom.set(k, []);
      nhom.get(k).push(c);
    }
    for (const ds of nhom.values()) {
      const tong = ds.reduce((a, c) => a + (dem.get(c.id) || 0), 0);
      h += `<div class="ins-head"><b>${escapeHtml(ds[0].usecase)} › ${escapeHtml(ds[0].insight_goc)}</b>` +
        `<span class="n">${tong}</span></div>`;
      for (const c of ds) {
        h += hang(c.id, `<span class="cum-dot" style="background:${mauCum(c.id)}"></span>` +
          `<span class="cum-ten">${escapeHtml(c.insight)}</span>`, dem.get(c.id) || 0, "cum-sub");
      }
    }
    // Cách dùng cụm (trước đây là khối chữ "Chưa có cụm nào…") dời vào ⓘ của nút "Cụm mới".
    const huongDanCum = "Chọn vài video cùng một kiểu (vd. cartoon) → bấm Đưa vào cụm ở thanh dưới → chọn insight gốc và gõ kiểu. " +
      "Tên cụm = tên insight con bên Creative Desk. Xoá một cụm không xoá video — chúng về Chưa vào cụm.";
    h += `<button type="button" class="rail-add" data-cum-moi>+ Cụm mới` +
      `<span class="ti" tabindex="0" role="note" title="${escapeHtml(huongDanCum)}" aria-label="${escapeHtml(huongDanCum)}">ⓘ</span></button>` +
      `<div id="cum-moi-form" hidden>${formCum("rail", 0)}</div>`;
    rail.innerHTML = h;
  }

  // Ô tạo cụm dùng chung cho thanh chọn ("Đưa vào cụm") và thanh bên ("Cụm mới").
  // Điền sẵn từ cụm đang xem, vì phân loại thường là nhiều kiểu dưới CÙNG một
  // insight gốc.
  function formCum(noi, soVideo) {
    const goc = state.cums.find((c) => c.id === state.cumLoc) || {};
    const o = (ten, nhan, gt) => `<label class="lb">${nhan}` +
      `<input data-cum-o="${ten}" value="${escapeHtml(gt || "")}" autocomplete="off" /></label>`;
    return `<form class="cum-form" data-noi="${noi}">` +
      `<h4>${soVideo ? `Đưa ${soVideo} video vào cụm mới` : "Cụm mới"}</h4>` +
      o("goc", "Insight gốc", goc.insight_goc) + o("usecase", "Usecase", goc.usecase) +
      o("kieu", "Kiểu", "") +
      `<div class="preview-name">Tên cụm = Insight con: <b data-xem-truoc></b></div>` +
      `<div class="lock-field">Template <b>Goc</b> 🔒 (video tải về)</div>` +
      `<button type="submit" class="btn primary ok">${soVideo ? `Tạo cụm và đưa ${soVideo} video vào` : "Tạo cụm"}</button>` +
      `</form>`;
  }

  function renderCumHead() {
    const head = document.getElementById("cum-head");
    if (!head) return;
    const cum = state.cums.find((c) => c.id === state.cumLoc);
    head.hidden = !cum;
    if (!cum) { head.innerHTML = ""; return; }
    const lo = chiaLo(videoCuaCum(cum.id), HANDOFF_MAX);
    const tong = lo.length;
    // Bất biến: lô cắt ở trang = số lô server đếm (`so_lo`, cùng response
    // `/cum`). Lệch (server cũ không có khung, thư viện > LIBRARY_MAX) ⇒ ghi lại
    // và nhãn "Bộ i/N" dùng N của server — server mới là bên dựng payload.
    const tongNhan = typeof cum.so_lo === "number" ? cum.so_lo : tong;
    if (tongNhan !== tong) console.warn(`cụm ${cum.id}: trang cắt ${tong} lô, server đếm ${cum.so_lo}`);
    // Video đã dọn giữ chỗ trong lô nhưng không tính vào "N video" của cụm.
    const nSong = (l) => l.filter((v) => !v.da_don).length;
    const n = lo.reduce((a, l) => a + nSong(l), 0);
    // Nhãn số video của một lô CHƯA mở: "x/N" khi lô đã hụt vì video được dọn.
    const nhanLoChuaMo = (l) => nSong(l) < l.length ? `${nSong(l)}/${l.length}` : `${l.length}`;
    // Chỉ VẼ mốc của lô còn tồn tại (`thu ≤ số lô`); mốc cũ vẫn nằm trong DB.
    // Giữ NGUYÊN hàng (không chỉ `mo_luc`) — cần cả `so_item` cho nhãn "x/N".
    const moLuc = new Map(cum.lo_mo.filter((m) => m.thu <= tong).map((m) => [m.thu, m]));
    const nut = n === 0 ? `<button type="button" class="btn primary" disabled>Tạo bộ tự tìm từ cụm này (0)</button>`
      : tong === 1 ? `<button type="button" class="btn primary" data-mo-lo="1">Tạo bộ tự tìm từ cụm này (${n})</button>`
      : `<button type="button" class="btn primary" data-mo-het>Tạo ${tong} bộ tự tìm (${lo.map(nhanLoChuaMo).join(" + ")})</button>`;
    const dsLo = tong > 1 ? `<div class="bo-list">${lo.map((l, i) => {
      const m = moLuc.get(i + 1);
      const nhanN = nhanSoVideo(m, nhanLoChuaMo(l));
      return `<div class="bo-row" data-lo="${i + 1}"><b>Bộ ${i + 1}/${tongNhan}</b><span>${nhanN} video</span>` +
        `<span class="muted">${m ? `đã mở Creative Desk lúc ${fmtDateTime(m.mo_luc)}` : "chưa mở"}</span><span class="grow"></span>` +
        `<button type="button" class="btn ghost" data-mo-lo="${i + 1}">${m ? "Mở lại" : "Mở Creative Desk"}</button></div>`;
    }).join("")}</div>` : "";
    const mot = tong === 1 && moLuc.get(1)
      ? `<div class="sent-line">Đã mở Creative Desk cho cụm này lúc ${fmtDateTime(moLuc.get(1).mo_luc)} ` +
        `(${nhanSoVideo(moLuc.get(1), n)} video). ` +
        `Video Desk <b>không biết</b> bộ bên đó đã được tạo hay chưa.</div>` : "";
    head.innerHTML =
      `<div><div class="crumb">${escapeHtml(cum.usecase)} › ${escapeHtml(cum.insight_goc)} ›</div>` +
      `<h3>${escapeHtml(cum.insight)}</h3><div class="tax-line">` +
      `<span class="tax">Usecase <b>${escapeHtml(cum.usecase)}</b></span>` +
      `<span class="tax">Insight <b>${escapeHtml(cum.insight)}</b></span>` +
      `<span class="tax lock">Template <b>Goc</b> 🔒</span></div></div>` +
      `<span class="muted">${n} video</span><span class="grow"></span>` +
      `<button type="button" class="btn ghost" data-doi-kieu>Đổi kiểu</button>` +
      `<button type="button" class="btn ghost danger" data-xoa-cum>Xoá cụm</button>${nut}` +
      `<div class="handoff-note">Mở Creative Desk ở tab mới, điền sẵn <b>Usecase = ${escapeHtml(cum.usecase)}</b> · ` +
      `<b>Insight = ${escapeHtml(cum.insight)}</b> · <b>Template = Goc</b>; bạn vẫn soát và bấm tạo bên đó.` +
      (tong > 1 ? ` Cụm ${n} video vượt ${HANDOFF_MAX}/bộ ⇒ tự tách ${tong} bộ, mỗi bộ mở một tab.`
                : ` Tối đa ${HANDOFF_MAX} video một bộ.`) + `</div>${dsLo}${mot}`;
  }

  function chipCum(video) {
    if (!state.cumsDaNap) return "";
    const cum = video.cum_id == null ? null : state.cums.find((c) => c.id === video.cum_id);
    if (!cum) return `<span class="cum-chip none">chưa vào cụm</span>`;
    return `<span class="cum-chip"><span class="cum-dot" style="background:${mauCum(cum.id)}"></span>` +
      `${escapeHtml(cum.insight)}</span>`;
  }

  function doiCumLoc(loc) {
    if (loc === state.cumLoc) return;
    state.cumLoc = loc;
    sauKhiDoiBoLoc();  // một bộ lọc nữa ⇒ về trang 1, GIỮ lựa chọn
  }

  async function loadCums() {
    apDungCum(await apiGet("/cum"));
  }

  // Ghi một response `GET /cum` vào `state`. Tách khỏi `loadCums` để lượt nạp thư viện
  // lấy `/cum` về TRƯỚC rồi chỉ ghi khi nó còn là lượt mới nhất — `/cum` của một lượt
  // đã bị thay chỗ không được đè dữ liệu cụm của lượt mới hơn.
  function apDungCum(res) {
    state.cums = res.cum;
    // Tập cắt lô (xem `videoCuaCum`). Server cũ không trả ⇒ undefined ⇒ đường cũ.
    state.khungCum = Array.isArray(res.khung_cum) ? res.khung_cum : undefined;
    state.cumsDaNap = true;
    // Cụm đang xem vừa bị xoá (tab khác) ⇒ về "Tất cả" thay vì lưới rỗng câm.
    if (typeof state.cumLoc === "number" && !state.cums.some((c) => c.id === state.cumLoc)) {
      state.cumLoc = "tat_ca";
    }
  }

  // Mở MỘT lô của cụm. Trả "mo" | "chan" | "rong" | "loi".
  //
  // Mở tab TRỐNG trước (`moTabTrong`, đồng bộ trong lượt xử lý click), RỒI
  // mới `await` payload — chặn popup được biết NGAY tại cú bấm, không phải
  // sau một vòng fetch (trước đây `window.open` chạy SAU `await`, nên "chan"
  // chỉ đúng khi fetch đủ chậm để hết "user activation"). Mốc "đã mở" vẫn chỉ
  // ghi SAU khi tab đã mở thật VÀ đã điền đúng địa chỉ — không đổi ý đó, chỉ
  // đổi THỜI ĐIỂM biết được popup có bị chặn hay không.
  //
  // `items`/`nhan` KHÔNG còn tự ghép ở đây — server dựng trọn payload
  // (`GET /cum/{id}/lo/{thu}/payload`), JS chỉ mã hoá + điền vào tab đã mở.
  // `muc.length` (đếm LOCAL, từ `state.videos` đã nạp) chỉ dùng để báo "N
  // video chưa lên Drive", KHÔNG đi vào payload gửi Creative Desk.
  //
  // Fetch trượt (kể cả lỗi KHÔNG PHẢI hết phiên, vd 400 "lô ngoài khoảng" khi
  // một tab khác vừa đổi số video của cụm) ⇒ ĐÓNG tab trống lại (đừng để lại
  // một tab "about:blank" mồ côi) và báo lý do — im lặng nuốt lỗi là đúng lỗ
  // đã sửa ở đây.
  // Hai danh sách id cùng phần tử, cùng thứ tự.
  function cungLo(a, b) {
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }

  // Lô phía trang đã cũ ⇒ nạp lại cụm rồi báo. Chỉ nói "đã nạp lại" SAU khi
  // nạp xong — nạp hỏng thì khung vẫn cũ và bấm lại sẽ bị từ chối tiếp, nên
  // phải nói đúng thế. Trả giá trị cho `moLoCum` (dừng `moHetLoCum`).
  async function napLaiVi(lyDo) {
    try {
      await loadCums();
      showToast(`${lyDo} — đã nạp lại, bấm lại.`);
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      showToast(`${lyDo} nhưng không nạp lại được — tải lại trang (F5).`);
    }
    renderLibrary();
    return "loi";
  }

  async function moLoCum(cumId, thu) {
    const cum = state.cums.find((c) => c.id === cumId);
    if (!cum) return "rong";
    const muc = chiaLo(videoCuaCum(cumId), HANDOFF_MAX)[thu - 1];
    // Lô chỉ còn video đã dọn khỏi Drive ⇒ không có gì để gửi (giống lô rỗng).
    if (!muc || !muc.some((v) => !v.da_don)) return "rong";
    const tab = moTabTrong();
    if (!tab) return "chan";
    let payload;
    try {
      payload = await apiGet(`/cum/${cumId}/lo/${thu}/payload`);
    } catch (err) {
      tab.close();
      // Hết phiên KHÔNG được đọc như "đã mở xong" (trả "mo" như MỌI lỗi
      // khác trước đây): `moHetLoCum` đọc "mo" thành tín hiệu ĐI TIẾP, nên
      // hết phiên ở lô đầu từng kéo theo mở-rồi-đóng một tab trống CHO MỌI
      // lô còn lại, trong khi người dùng đã bị đăng xuất và không lô nào
      // trong số đó có cơ hội thành công. Trả một giá trị RIÊNG để vòng lặp
      // "Mở tất cả" DỪNG ngay ở lô đầu tiên gặp hết phiên.
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      // 400 = lô ngoài khoảng: tab khác vừa làm cụm co bớt lô. Cùng lớp với
      // vế kiểm id lô bên dưới ⇒ nạp lại để trang hết hiện bộ không còn, và chỉ
      // nói "đã nạp lại" sau khi nạp xong.
      if (err && err.status === 400) return napLaiVi("Bộ này không còn (tab khác vừa sửa cụm)");
      showToast(`Không mở được Creative Desk cho bộ này: ${err.message || err}`);
      return "loi";
    }
    // Người dùng có thể đã tự tay đóng tab TRỐNG trong lúc đang chờ payload
    // về — điều hướng (`dieuHuongTab`) một tab đã đóng không ném lỗi nào
    // (trình duyệt lặng lẽ bỏ qua), nên không có gì báo hiệu tự nhiên; và
    // ghi "đã mở Creative Desk" (`POST .../da-mo`) cho một tab người dùng
    // vừa đóng là NÓI DỐI — kiểm `tab.closed` NGAY trước khi điều hướng.
    if (tab.closed) return "dong";
    // `so_video` (số video của lô lúc server dựng payload) là mẫu số của nhãn
    // "x/N", CÙNG thời điểm với `items` — không thuộc hợp đồng v:1 gửi Creative
    // Desk nên tách ra TRƯỚC khi mã hoá URL. Server cũ không trả ⇒ rơi về độ
    // dài lô phía trang cho toast, và không gửi kèm (mốc ghi NULL).
    // `video_ids` (id mọi video của lô server vừa cắt) cũng tách ra như vậy.
    const { so_video: soVideoLo, video_ids: idsLo, ...guiDi } = payload;
    // Lô server ≠ lô trang đã hiện (tab khác vừa gán/gỡ video của cụm giữa lúc
    // nạp và lúc bấm) ⇒ KHÔNG gửi: người dùng đã soát lô này, gửi lô khác là
    // gửi nhầm bộ. Nạp lại để lần bấm sau đúng. Server cũ không trả ⇒ bỏ qua.
    if (Array.isArray(idsLo) && !cungLo(idsLo, muc.map((v) => v.video_id))) {
      tab.close();
      return napLaiVi("Lô đã đổi (tab khác vừa sửa cụm)");
    }
    const soVideo = typeof soVideoLo === "number" ? soVideoLo : muc.length;
    if (!guiDi.items.length) {
      tab.close();
      showToast("Video của bộ này chưa lên Drive hoặc thiếu link gốc hợp lệ — chưa có gì để gửi sang Creative Desk.");
      return "rong";
    }
    if (guiDi.items.length < soVideo) {
      const daDon = muc.filter((v) => v.da_don).length;
      showToast(daDon
        ? `${soVideo - guiDi.items.length} video không gửi kèm (${daDon} đã dọn khỏi Drive sau khi vào bộ, ` +
          `còn lại chưa lên Drive hoặc thiếu link gốc hợp lệ).`
        : `${soVideo - guiDi.items.length} video chưa lên Drive hoặc thiếu link gốc hợp lệ nên không gửi kèm.`);
    }
    dieuHuongTab(tab, urlBanGiao(guiDi));
    try {
      const res = await apiSend("POST", `/cum/${cumId}/lo/${thu}/da-mo`,
        { so_item: guiDi.items.length, so_video: soVideoLo });
      cum.lo_mo = cum.lo_mo.filter((m) => m.thu !== thu)
        .concat([{ thu, mo_luc: res.mo_luc, so_item: res.so_item, so_video: res.so_video }]);
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      showToast("Đã mở Creative Desk nhưng không ghi được mốc “đã mở” — bấm lại nếu cần.");
    }
    renderCumHead();
    return "mo";
  }

  async function moHetLoCum(cumId) {
    const dsLo = chiaLo(videoCuaCum(cumId), HANDOFF_MAX);
    const tong = dsLo.length;
    for (let thu = 1; thu <= tong; thu++) {
      // Lô toàn video đã dọn: bỏ qua, đừng để "rong" chặn các lô sau nó.
      if (!dsLo[thu - 1].some((v) => !v.da_don)) continue;
      const kq = await moLoCum(cumId, thu);
      if (kq === "chan") {
        // Trình duyệt thường chỉ cho MỘT tab mỗi cú bấm. Nói đúng thế, và chỉ
        // chỗ bấm tiếp — lô chưa mở vẫn ghi "chưa mở".
        showToast(thu === 1
          ? "Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại."
          : `Đã mở ${thu - 1}/${tong} bộ. Trình duyệt chặn tab tiếp theo — bấm “Mở Creative Desk” ở từng bộ bên dưới.`);
        return;
      }
      // "rong"/"loi" đã tự báo toast, "het_phien" đã tự bật màn hình hết
      // phiên — TẤT CẢ, bên trong `moLoCum`. "dong" (người dùng tự đóng tab
      // trống) không cần báo gì thêm. Dừng vòng lặp ở đây cho mọi giá trị
      // khác "mo" — đừng mở thêm tab trống cho lô kế tiếp trong lúc phiên
      // hoặc dữ liệu đã có vấn đề.
      if (kq !== "mo") return;
    }
  }

  // Id cụm mang tên `nhap`: cụm có sẵn trùng tên, hoặc cụm vừa tạo. Server tự
  // trả lại cụm có sẵn khi trùng (`da_co`), nên kể cả khi `state.cums` cũ hơn
  // server (tab khác vừa tạo) cũng không sinh cụm thứ hai.
  async function layHoacTaoCum(nhap) {
    const trung = timCumTrung(state.cums, nhap.usecase, nhap.goc, nhap.kieu);
    if (trung) return { cumId: trung.id, daCo: true };
    const moi = await apiSend("POST", "/cum",
      { usecase: nhap.usecase, insight_goc: nhap.goc, kieu: nhap.kieu });
    if (!state.cums.some((c) => c.id === moi.id)) state.cums.push(moi);
    return { cumId: moi.id, daCo: Boolean(moi.da_co) };
  }

  // Gán `ids` vào ĐÚNG cụm `cumId` — không tra lại theo tên. Trả `{da, boQua}`.
  async function ganIdsVaoCum(cumId, ids) {
    let da = 0, boQua = 0;
    for (let i = 0; i < ids.length; i += GAN_CUM_TOI_DA) {
      const lo = ids.slice(i, i + GAN_CUM_TOI_DA);
      const res = await apiSend("POST", `/cum/${cumId}/video`, { video_ids: lo });
      const bo = new Set(res.bo_qua);
      for (const v of state.videos) if (lo.includes(v.video_id) && !bo.has(v.video_id)) v.cum_id = cumId;
      da += res.so_video;
      boQua += res.bo_qua.length;
    }
    return { da, boQua };
  }

  function baoDaGan(cumId, daCo, soId, kq) {
    const ten = (state.cums.find((c) => c.id === cumId) || {}).insight || "";
    const phan = [daCo ? `Dùng lại cụm có sẵn “${ten}”` : `Đã tạo cụm “${ten}”`];
    if (soId) phan.push(`đưa ${kq.da} video vào`);
    if (kq.boQua) phan.push(`${kq.boQua} video không đưa được (không thuộc thư viện của bạn)`);
    showToast(phan.join(" · "));
  }

  // Tạo (hoặc DÙNG LẠI cụm trùng tên) rồi đưa `ids` vào. Trả id cụm.
  async function duaVaoCum(nhap, ids) {
    const { cumId, daCo } = await layHoacTaoCum(nhap);
    const kq = await ganIdsVaoCum(cumId, ids);
    baoDaGan(cumId, daCo, ids.length, kq);
    return cumId;
  }
