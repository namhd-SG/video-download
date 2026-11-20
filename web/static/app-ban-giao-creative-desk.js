// Bàn giao video sang Creative Desk (tab mới, postMessage, payload URL).
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // "Tạo bộ tự tìm" — bàn giao sang Creative Desk qua THANH ĐỊA CHỈ, không
  // qua API.
  //
  // Vì sao mở tab thay vì gọi backend bên kia: trang này nằm ở origin
  // `video.*`, Creative Desk ở `automation.*`, và cả hai sau Cloudflare
  // Access. Một lời gọi chéo origin từ đây sẽ cần Video Desk cầm token của
  // người dùng hoặc một service token — tức là dựng một bề mặt mạo danh cho
  // một việc vốn chỉ là copy file. Đưa TRÌNH DUYỆT sang đó thì người dùng
  // mang sẵn phiên của chính họ, và bộ được tạo đứng tên đúng người mà bên
  // này không cầm gì cả.
  //
  // Chọn tay (26/09): gửi danh sách qua `postMessage` thay vì query string, để
  // chọn bao nhiêu cũng được và Creative Desk tự chia bộ. Đường của CỤM vẫn đi
  // qua URL (`moLoCum`) — hợp đồng `nhan` không đổi.
  // Tệp nguồn của video này đã chết / sắp bị dọn? Đúng khi server đánh dấu `da_don`
  // (đã vào Thùng rác) hoặc `vao_bo.se_don_luc` ≤ `bayGio` (đã quá hạn 7 ngày — lượt dọn
  // sắp lấy tệp đi). Gửi một item như thế sang Creative Desk là gửi một file sắp không
  // còn để copy; và bên nhận bỏ CẢ LÔ khi một item hỏng. Hàm thuần — test gọi thẳng.
  function nguonDaChet(v, bayGio) {
    if (v.da_don) return true;
    const han = v.vao_bo && v.vao_bo.se_don_luc ? Date.parse(v.vao_bo.se_don_luc) : NaN;
    return !Number.isNaN(han) && han <= bayGio;
  }

  async function moBoTuTim() {
    if (state.dangBanGiao) return;  // bấm đúp khi đang chờ ack ⇒ bỏ qua
    // Thẻ đã chọn ⇒ các TỆP thật để gửi. Video: chính nó. Bài ảnh (thẻ khoá bằng `bai_id`): MỖI tệp của bài là một
    // item — Creative Desk nhận từng file Drive, không có khái niệm "bài" — kèm `chonId` = khoá thẻ để bỏ chọn đúng
    // thẻ sau khi gửi. (Viết tại chỗ: harness `tests/js/` trích riêng hàm này.)
    const daChon = state.videos.filter((v) => state.selected.has(v.video_id)).flatMap((v) => (v.loai === "anh"
      ? (v.files || []).map((f) => ({ ...f, chonId: v.video_id }))
      : [v]));
    // Video chưa lên Drive thì KHÔNG có gì để copy. Bỏ chúng TRƯỚC khi gửi và
    // nói ra số bị bỏ — để số video mỗi bộ bên kia đếm trên đúng thứ sẽ copy.
    const chuaLenDrive = daChon.filter((v) => !v.drive_file_id);
    const coDrive = daChon.filter((v) => v.drive_file_id);
    // Bên nhận bỏ CẢ LÔ, không ack, khi chỉ một item sai luật — người dùng sẽ
    // chờ trọn hạn ack. Lọc trước theo đúng luật đó và nói ra số bị bỏ.
    // Nguồn đã chết/quá hạn dọn: bỏ TRƯỚC, nói ra số bị bỏ (server cũng kiểm lại ở đường lô).
    const bayGio = Date.now();
    const nguonChet = coDrive.filter((v) => nguonDaChet(v, bayGio));
    const conSong = coDrive.filter((v) => !nguonDaChet(v, bayGio));
    const guiDuoc = conSong.filter(itemHopLeBenNhan);
    const khongHopLe = conSong.length - guiDuoc.length;
    const items = guiDuoc.map(itemBanGiao);

    if (!items.length) {
      showToast("Chưa có gì để gửi sang Creative Desk: " + [
        chuaLenDrive.length ? `${chuaLenDrive.length} video chưa lên Drive` : "",
        nguonChet.length ? `${nguonChet.length} video đã quá hạn giữ tệp nguồn` : "",
        khongHopLe ? `${khongHopLe} video thiếu link gốc hợp lệ` : "",
      ].filter(Boolean).join(", ") + ".");
      return;
    }
    if (items.length > MAX_PM_ITEMS) {
      showToast(`Chọn tối đa ${MAX_PM_ITEMS} video cho một lần tạo bộ.`);
      return;
    }

    // Mỗi lần bấm là MỘT tab mới với `?videodesk_pm=1`. Không gửi lại vào tab của
    // lần trước: Creative Desk chuyển người chưa đăng nhập sang `/login` và KHÔNG
    // giữ URL quay lại (`creative-order/layout.tsx` `router.replace("/login")`),
    // nên sau khi đăng nhập tab cũ không còn tham số đó và không bao giờ nghe tin.
    // id sinh TRƯỚC khi mở tab: `crypto.randomUUID` chỉ có ở ngữ cảnh an toàn,
    // ném lỗi sau khi đã mở tab là để lại một tab mồ côi không ai gửi tin tới.
    const id = crypto.randomUUID();
    const tab = moTabCreativeDesk(`${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk_pm=1`);
    if (!tab) {
      showToast("Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại. " +
                "Lựa chọn của bạn vẫn còn.");
      return;
    }
    // Số bị bỏ đi KÈM mọi thông báo kết quả — toast riêng sẽ bị toast sau đè mất.
    const boLai = [
      chuaLenDrive.length ? `${chuaLenDrive.length} video chưa lên Drive` : "",
      nguonChet.length ? `${nguonChet.length} video đã quá hạn giữ tệp nguồn` : "",
      khongHopLe ? `${khongHopLe} video thiếu link gốc hợp lệ` : "",
    ].filter(Boolean).join(", ");
    const ghiChuBoLai = boLai ? ` (${boLai} nên không gửi kèm.)` : "";

    datNutBanGiao(true);
    state.dangBanGiao = true;
    let kq;
    try {
      kq = await guiBanGiaoPm(tab, { type: "videodesk-handoff", v: 2, id, items },
                              PM_HAN_MS, PM_CHU_KY_MS);
    } finally {
      state.dangBanGiao = false;
      datNutBanGiao(false);
    }

    // Bỏ chọn CHỈ khi bên kia xác nhận đã nhận VÀ đã lưu (`ok: true`). Trước đó
    // chưa có gì được bàn giao cả — xoá lựa chọn là bắt người dùng chọn lại vì
    // một việc CHƯA xảy ra.
    if (kq.ket === "ack") {
      // Chỉ bỏ chọn đúng những video ĐÃ gửi: video chưa lên Drive / thiếu link
      // vẫn giữ tick để người dùng thấy chúng chưa đi đâu cả.
      // Thẻ ảnh chỉ bỏ chọn khi MỌI tệp của bài đã đi (còn tệp bị bỏ lại thì giữ tick để người dùng thấy bài chưa trọn).
      const conLai = new Set([...chuaLenDrive, ...nguonChet, ...conSong.filter((v) => !guiDuoc.includes(v))]
        .map((v) => v.chonId || v.video_id));
      boChonCacVideo([...new Set(guiDuoc.map((v) => v.chonId || v.video_id))].filter((id) => !conLai.has(id)));
      showToast(`Đã gửi ${items.length} video sang Creative Desk — chia bộ và bấm tạo ở tab đó.${ghiChuBoLai}`);
      return;
    }
    showToast({
      tu_choi: `Creative Desk không nhận được danh sách${kq.lyDo ? ` (${kq.lyDo})` : ""}. Lựa chọn vẫn còn.`,
      het_han: "Creative Desk chưa xác nhận sau 30 giây. Nếu tab đó bắt đăng nhập: đăng nhập " +
               "xong, đóng tab đó rồi bấm “Tạo bộ tự tìm” lần nữa. Lựa chọn vẫn còn.",
      tab_dong: "Tab Creative Desk đã đóng trước khi nhận — bấm lại để mở tab mới. Lựa chọn vẫn còn.",
    }[kq.ket]);
  }

  function datNutBanGiao(dangGui) {
    const nut = document.querySelector('[data-action="self-bundle"]');
    if (!nut) return;
    nut.disabled = dangGui;
    nut.textContent = dangGui ? "Đang gửi sang Creative Desk…" : "Tạo bộ tự tìm";
  }

  // Gửi `tin` sang `tab` mỗi `chuKyMs` tới khi có ack đúng `id` từ đúng origin
  // Creative Desk, tab đóng, hoặc hết `hanMs`. Trả {ket: "ack"|"tu_choi"|
  // "het_han"|"tab_dong", lyDo?}. targetOrigin CỐ ĐỊNH: trang lạ lọt vào tab
  // (chuyển hướng, gõ tay) không đọc được danh sách.
  function guiBanGiaoPm(tab, tin, hanMs, chuKyMs) {
    return new Promise((xong) => {
      let hetLuc = null, nhip = null;
      const ket = (r) => {
        clearInterval(nhip);
        clearTimeout(hetLuc);
        window.removeEventListener("message", nghe);
        xong(r);
      };
      function nghe(ev) {
        const d = ev.data;
        if (ev.origin !== CREATIVE_DESK_ORIGIN || !d || d.type !== "videodesk-ack" || d.id !== tin.id) return;
        ket(d.ok === true ? { ket: "ack" } : { ket: "tu_choi", lyDo: typeof d.reason === "string" ? d.reason : "" });
      }
      const gui = () => {
        if (tab.closed) { ket({ ket: "tab_dong" }); return; }
        try { tab.postMessage(tin, CREATIVE_DESK_ORIGIN); } catch (e) { /* tab đang chuyển trang — lượt sau gửi lại */ }
      };
      window.addEventListener("message", nghe);
      hetLuc = setTimeout(() => ket({ ket: "het_han" }), hanMs);
      nhip = setInterval(gui, chuKyMs);
      gui();
    });
  }

  // ========================================================================
  // BÀN GIAO sang Creative Desk (hợp đồng `nhan`,
  // plans/260923-1558-tai-theo-cum/hop-dong-nhan.md). Hai đường KHÔNG dùng
  // chung hàm dựng item: nút chọn tay (`moBoTuTim`) tự dựng item bằng
  // `itemBanGiao` + lọc `itemHopLeBenNhan` rồi gửi qua `postMessage`; nút lô
  // của cụm (`moLoCum`) nhận payload DỰNG SẴN ở server
  // (`GET /cum/{id}/lo/{thu}/payload`, `models_chia.xay_payload_lo`, cùng
  // luật lọc) rồi chỉ mã hoá vào URL bằng `maHoaPayload`/`urlBanGiao`.
  // ========================================================================
  function itemBanGiao(v) {
    return { f: v.drive_file_id, n: v.title || v.video_id, u: v.url };
  }

  // Cùng luật với bên nhận (meta-ads `frontend/src/lib/videodesk-handoff.ts`
  // `parseVideodeskHandoffItem`): Drive id `[A-Za-z0-9_-]{10,128}`, link gốc
  // http(s). Tên không cần kiểm — bên nhận tự cắt ở 200 ký tự.
  function itemHopLeBenNhan(v) {
    // Kiểm KIỂU trước: bên nhận đòi đúng chuỗi, không ép kiểu — một id dạng số
    // qua được regex sau `String()` nhưng vẫn bị bên nhận bỏ.
    return typeof v.drive_file_id === "string" && /^[A-Za-z0-9_-]{10,128}$/.test(v.drive_file_id) &&
           typeof v.url === "string" && /^https?:\/\//i.test(v.url);
  }

  // `nhan` CHỈ có khi bàn giao từ cụm; `null` ⇒ không có khoá đó (quy tắc 1-2).
  // Không đường nào trong trang còn gọi hàm này (payload của cụm dựng ở
  // server): chỉ các harness `tests/js/*.js` trích nó ra để dựng payload đối
  // chứng — giữ vì các test đó phụ thuộc vào nó.
  function dungPayload(items, nhan) {
    const p = { v: 1, items };
    if (nhan) p.nhan = nhan;
    return p;
  }

  // base64url: payload đi trong URL nên `+` `/` `=` đều phải biến mất.
  // `TextEncoder` trước `btoa` vì tiêu đề video có tiếng Việt và emoji —
  // `btoa` một mình ném `InvalidCharacterError` ở ký tự ngoài Latin-1.
  function maHoaPayload(p) {
    return btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(p))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function urlBanGiao(p) {
    return `${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk=${maHoaPayload(p)}`;
  }

  // Mở tab TRỐNG ngay (đồng bộ, trong CHÍNH lượt xử lý click) và trả tab, hoặc
  // `null` khi trình duyệt chặn popup.
  //
  // TÁCH mở-tab khỏi điền-địa-chỉ. `window.open` phải chạy trước bất kỳ
  // `await` nào — Chromium chỉ giữ "user activation" khoảng 5s sau cú bấm, và
  // Safari còn khắt khe hơn (chặn NGAY một `window.open` chạy sau `await`, kể
  // cả trong 5s). Mở "về sau mới biết URL" thì phải mở TRỐNG trước, gán địa
  // chỉ sau — `dieuHuongTab` làm phần sau.
  //
  // KHÔNG truyền "noopener" vào `window.open`: với cờ đó trình duyệt LUÔN trả
  // `null` dù tab đã mở (đo trên Chromium 23/09) — mọi phép kiểm "tab có mở
  // không" phía sau sẽ đọc thành "bị chặn". Cắt `opener` bằng tay thay cho cờ.
  function moTabTrong() {
    const tab = window.open("about:blank", "_blank");
    if (tab) {
      try {
        tab.opener = null;
      } catch (e) {
        // Nhánh này chạy ⇒ opener KHÔNG bị cắt: tab Creative Desk vẫn với tới
        // được trang này qua `window.opener`. Tab đã mở và bàn giao vẫn đi,
        // nên vẫn trả `tab` — nhưng nói ra, đừng nuốt im.
        console.warn("Không cắt được window.opener của tab Creative Desk — tab vẫn mở, opener CÒN nguyên:", e);
      }
    }
    return tab;
  }

  // Điền địa chỉ THẬT vào một tab đã mở trống (`moTabTrong`) — phần "sau khi
  // đã biết URL", tách khỏi phần "mở tab" ở trên.
  function dieuHuongTab(tab, url) {
    tab.location = url;
  }

  // Mở tab Creative Desk NGAY VỚI url đã biết (đường chọn tay, `moBoTuTim` —
  // đồng bộ hoàn toàn, không có `await` nào giữa cú bấm và đây). CỐ Ý mở
  // THẲNG bằng url thật thay vì `moTabTrong` + `dieuHuongTab`: đặt
  // `tab.location =` NGAY sau `window.open("about:blank",…)` không đồng bộ
  // với chính commit điều hướng của trình duyệt — `Page.url` phía Playwright
  // (và một số trình duyệt) có thể vẫn đọc ra "about:blank" nếu đọc quá sớm.
  // Đường này không có khoảng chờ nào để tách hai bước ra, nên mở thẳng một
  // lần là vừa an toàn vừa đơn giản hơn.
  function moTabCreativeDesk(url) {
    const tab = window.open(url, "_blank");
    if (tab) {
      try {
        tab.opener = null;
      } catch (e) {
        console.warn("Không cắt được window.opener của tab Creative Desk — tab vẫn mở, opener CÒN nguyên:", e);
      }
    }
    return tab;
  }
