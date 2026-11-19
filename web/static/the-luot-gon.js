// Thẻ lượt tải GỌN trên hàng đợi + popup chi tiết (mock R-07 v2, user duyệt 18/11/2026).
//
// Thẻ chỉ còn: chip trạng thái · x/y · thanh · link ngắn · MỘT dòng note 2–4 chữ · MỘT hàng nút nhỏ ·
// chân "user · giờ". Mọi câu dài (câu dừng, dòng nguồn, khung lỗi, vị trí hàng, ghi chú xác minh)
// nằm trong popup mở khi bấm thẻ.
//
// Thuần (không đụng DOM, không gọi mạng) như `bao-thieu.js`: nhận `job` + `ctx` do app.js đưa vào
// và trả chuỗi HTML. Chuỗi người dùng đều đi qua `ctx.esc`; `ctx.stopText` là HTML dựng sẵn từ bảng
// cố định (`stop-reason-text.js`) nên nhúng nguyên. Sự kiện (bấm thẻ, nút, Esc) do app.js gắn — mọi
// nút giữ nguyên thuộc tính data-* cũ (`data-chep-link`, `data-chay-lai*`, `data-huy`,
// `data-giai-ngay`, `data-mo-giai`, `data-chia`) để các tay nghe uỷ quyền cũ vẫn chạy.
(function () {
  "use strict";

  const BT = window.BaoThieu;
  const GT = window.GiaiCaptchaThe;

  // Nhãn ngắn theo MÃ DỪNG (`ly_do_dung`). Thỏa thuận với điều phối 18/11: chỉ suy từ mã sẵn có.
  const NHAN_MA = Object.freeze({
    cookie_het_han: "Cookie hết hạn", cookie_chua_dang_nhap: "Cookie chưa đăng nhập",
    cookie_khong_phai_tiktok: "Cookie sai trang", cookie_rong: "Cookie rỗng", cookie_khong_doc_duoc: "Cookie hỏng",
    feed_rong_khong_captcha: "TikTok trả rỗng",
    captcha_chua_xong: "Giải chưa xong", khong_ai_xem: "Giải chưa xong", het_gio_giai: "Giải chưa xong",
    mo_trang_truot: "Giải chưa xong", roi_mien: "Giải chưa xong", khong_co_khung: "Giải chưa xong",
    gesture_bo_do_qua_nhieu: "Giải chưa xong", khoi_dong_lai: "Giải chưa xong",
    loi_trinh_duyet: "Lỗi máy chủ", loi_he_thong: "Lỗi máy chủ",
    xac_minh_qua_han: "Quá hạn 24 giờ", tinh_nang_giai_tat: "Tắt tính năng giải",
    het_thoi_gian: "Hết giờ", het_vong: "Hết vòng quét", page_cap: "Chạm trần trang", het_dia: "Đĩa sắp đầy",
    tran_gio: "Chạm trần giờ", tran_ngay: "Chạm trần ngày",
    ig_mat_phien: "Cookie IG hết hạn / bị IG chặn", ig_chua_co_cookie: "Chưa có cookie IG",
    fb_chan_dang_nhap: "Facebook đòi đăng nhập",
    nghi_bi_chan: "Nghi bị chặn", bi_chan: "Nền tảng chặn", thieu_deno: "Máy thiếu Deno",
    hashtag_khong_tra_duoc: "Hashtag không đọc được", index_failed: "Nguồn ngoài lỗi",
    source_empty: "Nguồn rỗng", already_owned: "Đã có hết", stalled: "Hết video",
  });
  const MA_FEED = new Set(["feed_rong", "khong_do_duoc_feed"]);
  const MA_COOKIE = /^cookie_/;
  const HONG = new Set(["failed", "interrupted"]);

  const so = (x) => Number(x) || 0;

  // Mã → nhãn; `feed_rong`/`khong_do_duoc_feed` đổi nghĩa theo trạng thái (đang chờ người giải vs đã hỏng).
  function nhanMa(job) {
    const ma = job.ly_do_dung;
    if (MA_FEED.has(ma)) return job.trang_thai === "cho_xac_minh" ? "TikTok đòi xác minh" : "TikTok trả rỗng";
    return NHAN_MA[ma] || null;
  }

  function viTri(job, dau) {
    return job.vi_tri ? (job.vi_tri === 1 ? dau[0] : dau[1].replace("{n}", job.vi_tri)) : dau[2];
  }

  // Dòng note ngắn duy nhất của thẻ: { chu, lop } — `lop` chọn màu chấm (n-ok/n-loi/n-hut/n-tai/n-xn/n-cho).
  function nganGon(job) {
    const tt = job.trang_thai;
    const s = so(job.tong), xong = so(job.xong);
    if (tt === "cho_xac_minh") return { chu: "TikTok đòi xác minh", lop: "n-xn" };
    if (tt === "cho_giai") return { chu: viTri(job, ["Tiếp theo: mở trang giải", "Thứ {n} chờ mở trang", "Chờ mở trang giải"]), lop: "n-xn" };
    if (tt === "dang_mo") return { chu: "Đang mở trang giải", lop: "n-xn" };
    if (tt === "dang_giai") return { chu: "Đang giải xác minh", lop: "n-xn" };
    if (tt === "pending") return { chu: viTri(job, ["Tiếp theo trong hàng", "Thứ {n} trong hàng", "Đang chờ tới lượt"]), lop: "n-cho" };
    if (tt === "running") return { chu: `Đang tải · ${BT.phanTram(job)}%`, lop: "n-tai" };
    if (tt === "cancelled") return { chu: "Bạn đã rút lượt", lop: "n-cho" };
    const ma = nhanMa(job);
    const n = BT.soChayLai(job);
    if (tt === "done") {
      if (s > 0 && xong >= s) return { chu: "Đủ số bạn xin", lop: "n-ok" };
      if (ma) return { chu: n !== null ? `${ma} · thiếu ${n}` : ma, lop: "n-hut" };
      if (BT.coSuCoHangLoat(job)) return { chu: "Nghi sự cố hàng loạt", lop: "n-loi" };
      if (BT.coLoiHeThong(job)) return { chu: "Có video lỗi hệ thống", lop: "n-loi" };
      if (BT.nhanThieu(job)) return { chu: s > xong ? `Thiếu ${s - xong}` : "Thiếu video", lop: "n-hut" };
      return { chu: "Đã tải xong", lop: "n-ok" };
    }
    if (HONG.has(tt)) {
      const goc = ma || (tt === "interrupted" ? "Bị ngắt giữa chừng" : "Lỗi khác");
      return { chu: n !== null ? `${goc} · thiếu ${n}` : goc, lop: "n-loi" };
    }
    return { chu: tt, lop: "n-cho" };
  }

  // ---- nút -----------------------------------------------------------------
  // Mỗi hành động = { k, html }; `html` là một nút/liên kết (cỡ nhỏ khi `sm`).
  function hanhDong(job, ctx, sm) {
    const id = so(job.id), tt = job.trang_thai, ma = job.ly_do_dung || "";
    const z = sm ? " sm" : "";
    const ds = [];
    // Nút giải (Xác minh / Mở cửa sổ giải) lấy từ MỘT nguồn `GT.khungHanhDong` — đứng chung hàng nút của thẻ.
    const giai = GT.khungHanhDong(job, sm).nut;
    if (giai) ds.push({ k: tt === "cho_xac_minh" ? "xm" : "mo", html: giai });
    const n = BT.soChayLai(job);
    if (n !== null) {
      const mo = ctx.mo;
      ds.push({
        k: "them", xacNhan: mo !== null && mo !== undefined,
        html: mo === null || mo === undefined
          ? `<button type="button" class="btn${z} primary" data-chay-lai="${id}">Tải thêm ${n} cho đủ</button>`
          : `<span class="chay-lai-xn">Thêm <input type="number" class="chay-lai-n" data-chay-lai-n="${id}" min="1" ` +
            `max="${BT.MAX_SO_LUONG}" value="${so(mo)}" aria-label="Số video kiếm thêm"> ` +
            `<button type="button" class="btn${z} primary" data-chay-lai-ok="${id}"${ctx.dangGuiChayLai ? " disabled" : ""}>Chạy lại</button> ` +
            `<button type="button" class="btn${z}" data-chay-lai-huy="${id}">Thôi</button></span>`,
      });
    }
    if (MA_COOKIE.test(ma) && (HONG.has(tt) || tt === "done")) {
      ds.push({ k: "cookie", html: `<a class="btn${z}" href="settings.html">Sửa cookie →</a>` });
    }
    // "Tải lại" = cùng link, cùng số xin: chỉ khi KHÔNG có "Tải thêm" (nút đó đã là cách chạy lại hợp lý).
    if (HONG.has(tt) && n === null) {
      ds.push({ k: "tailai", html: `<button type="button" class="btn${z} primary" data-tai-lai="${id}"${ctx.dangGuiTaiLai ? " disabled" : ""}>Tải lại</button>` });
    }
    if (tt === "pending" || tt === "cho_xac_minh" || tt === "cho_giai") {
      ds.push({ k: "rut", html: `<button type="button" class="btn${z}" data-huy="${id}">Rút lượt</button>` });
    }
    return ds;
  }

  const nutChep = (id, sm) => `<button type="button" class="btn${sm ? " sm" : ""}" data-chep-link="${id}">Chép link</button>`;
  const nutChia = (id, sm) => `<button type="button" class="btn${sm ? " sm" : ""}" data-chia="${id}">Chia cụm</button>`;

  // ---- thẻ ------------------------------------------------------------------
  function gioNgan(iso) {
    const d = new Date(iso);
    if (!iso || Number.isNaN(d.getTime())) return "—";
    const p = (x) => String(x).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())} ${p(d.getDate())}/${p(d.getMonth() + 1)}`;
  }

  function theGon(job, ctx) {
    const id = so(job.id), esc = ctx.esc;
    const note = nganGon(job);
    const acts = hanhDong(job, ctx, true);
    const xacNhan = acts.some((a) => a.xacNhan);
    const nut = acts.map((a) => a.html);
    // Chỗ trên một hàng chỉ đủ ~2 nút: "Chép link" chỉ đứng cùng khi còn chỗ; "Chia cụm" cho lượt xong không có việc khác.
    if (!xacNhan && acts.length < 2 && job.trang_thai !== "cho_xac_minh") nut.push(nutChep(id, true));
    if (!xacNhan && acts.length === 0 && job.trang_thai === "done") nut.push(nutChia(id, true));
    const hienUrl = BT.nhanUrl(job.url).replace(/^https?:\/\/(www\.)?/, "");
    const tenNguoi = String(job.nguoi_tao || "").split("@")[0];
    const chip = ctx.chip;
    const hasErrors = BT.coLoiHeThong(job);
    return `
      <li class="queue-item${job.trang_thai === "cho_xac_minh" ? " can-xn" : ""}" id="job-${id}" data-status="${esc(job.trang_thai)}" ` +
      `tabindex="0" role="button" aria-haspopup="dialog" aria-label="${esc(`Lượt #${id}: ${chip.chu}, ${note.chu}. Mở chi tiết`)}">
        <div class="queue-item-top">
          <span class="status-badge status-${esc(chip.lop)}">${esc(chip.chu)}</span>
          <span class="grow"></span>
          <span class="chi-tiet">Chi tiết</span>
        </div>
        <div class="qi-big">${so(job.xong)}<small>/${BT.mauSo(job)}</small></div>
        <div class="progress-row">
          <div class="progress-track"><div class="progress-fill${hasErrors ? " has-errors" : ""}" style="width:${BT.phanTram(job)}%"></div></div>
          <span>${so(job.xong)}/${BT.mauSo(job)}</span>
        </div>
        <span class="queue-url" title="${esc(job.url)}">${esc(hienUrl)}</span>
        <span class="hn-note ${note.lop}"><span class="dot" aria-hidden="true"></span>${esc(note.chu)}</span>
        <div class="hn-nut">${nut.join("")}</div>
        <span class="job-meta">${esc(tenNguoi)} · ${gioNgan(job.tao_luc)}</span>
      </li>`;
  }

  // ---- popup ----------------------------------------------------------------
  // Các bước "Cách xử lý" theo nhóm mã. Nhóm không có bước riêng (câu dừng đã đủ) → [].
  function buoc(job) {
    const tt = job.trang_thai, ma = job.ly_do_dung || "";
    if (tt === "cho_xac_minh") {
      return ["Bấm “Xác minh”: cửa sổ giải mở ngay trong Video Desk, kéo/bấm trực tiếp trên ảnh.",
        "Giải xong bấm “Đã giải xong”: tool quét tiếp và tải video.",
        { xn: "Chưa ai giải thì job tự kết thúc sau 24 giờ. Không giải được? Rút lượt để trả hạn mức." }];
    }
    if (tt === "cho_giai" || tt === "dang_mo" || tt === "dang_giai") {
      return ["Bấm “Mở cửa sổ giải” để vào cửa sổ giải xác minh của lượt này."];
    }
    if (BT.soChayLai(job) !== null) {
      return ["Bấm “Tải thêm N cho đủ”: tool tạo lượt mới chỉ kiếm phần còn thiếu, video đã có được bỏ qua.",
        "Muốn số khác thì sửa số trong ô xác nhận trước khi chạy."];
    }
    if (!HONG.has(tt) && tt !== "done") return [];
    if (MA_COOKIE.test(ma)) {
      return ["Mở tiktok.com, đăng nhập, xuất cookie bằng Cookie-Editor (JSON).",
        "Bấm “Sửa cookie →” để vào Cài đặt và dán cookie mới.",
        "Quay lại, bấm “Tải lại” để chạy lại cùng link."];
    }
    if (MA_FEED.has(ma) || ma === "feed_rong_khong_captcha") {
      return ["Đợi một lúc: TikTok đang chặn trình duyệt tự động. Dán lại cookie không chữa được lỗi này.",
        "Bấm “Tải lại”: tạo lượt mới cùng link, cùng số video.",
        "Vẫn rỗng thì tạo lượt bằng link hashtag (tiktok.com/tag/…) cùng chủ đề: đường hashtag không đi qua trình duyệt."];
    }
    return [];
  }

  // Dòng vị trí/chờ dài cho phần tóm tắt của popup (thẻ chỉ có bản ngắn).
  function dongViTri(job) {
    const tt = job.trang_thai;
    if (tt === "pending") return viTri(job, ["Tiếp theo trong hàng", "Thứ {n} trong hàng", "Đang chờ tới lượt"]);
    if (tt === "cho_xac_minh") return "Đang chờ người giải";
    if (tt === "cho_giai") return viTri(job, ["Tiếp theo: máy chủ mở trang giải", "Thứ {n}: chờ máy chủ mở trang giải", "Chờ máy chủ mở trang giải"]);
    if (tt === "dang_mo") return "Máy chủ đang mở trang để giải";
    if (tt === "dang_giai") return "Đang giải xác minh";
    return "";
  }

  function popup(job, ctx) {
    const id = so(job.id), esc = ctx.esc;
    const note = nganGon(job);
    const hasErrors = BT.coLoiHeThong(job);
    const nguon = BT.dongNguon(job);
    const boQua = so(job.bo_qua);
    const skip = boQua > 0 && !nguon ? `Bỏ qua ${boQua} video đã có trong kho.` : "";
    const loi = BT.khungLoi(job);
    const coVanDe = ctx.stopText || loi || skip;
    const doDo = HONG.has(job.trang_thai) || hasErrors;
    const acts = hanhDong(job, ctx, false);
    const steps = buoc(job);
    const vitri = dongViTri(job);
    const ghi = GT.khungHanhDong(job, false).ghi;
    const xuLy = steps.length || acts.length
      ? `<div class="khoi xu-ly"><h4>Cách xử lý</h4>
          ${steps.length ? `<ol>${steps.map((b) => typeof b === "string" ? `<li>${esc(b)}</li>` : `<li class="xn-note">${esc(b.xn)}</li>`).join("")}</ol>` : ""}
          ${acts.length ? `<div class="hn-nut">${acts.map((a) => a.html).join("")}${ghi}</div>` : ""}
        </div>` : "";
    return `
      <div class="hn-pop-h"><span class="status-badge status-${esc(ctx.chip.lop)}">${esc(ctx.chip.chu)}</span>
        <h3 id="hn-tieu" class="grow">${esc(note.chu)}</h3><span class="ma">#${id}</span>
        <button type="button" class="btn icon ghost" data-hn-dong aria-label="Đóng">✕</button></div>
      <div class="hn-pop-b">
        <div>
          <div class="qi-big">${so(job.xong)}<small>/${BT.mauSo(job)}</small></div>
          <div class="progress-row"><div class="progress-track"><div class="progress-fill${hasErrors ? " has-errors" : ""}" style="width:${BT.phanTram(job)}%"></div></div></div>
          <p class="nho">${esc(BT.chuTienDo(job))}</p>
          ${nguon ? `<p class="nho nguon">${nguon}</p>` : ""}
          ${vitri ? `<p class="nho queue-pos">${esc(vitri)}</p>` : ""}
        </div>
        <div class="link-row"><code>${esc(job.url)}</code>${nutChep(id, false)}</div>
        ${coVanDe ? `<div class="khoi van-de${doDo ? "" : " vang"}"><h4>Vấn đề</h4>
          ${loi}
          ${skip ? `<div class="skip-note">${esc(skip)}</div>` : ""}
          ${ctx.stopText ? `<div class="stop-reason">${ctx.stopText}</div>` : ""}</div>` : ""}
        ${xuLy}
        <dl class="meta"><dt>Người tạo</dt><dd>${esc(job.nguoi_tao)}</dd><dt>Tạo lúc</dt><dd>${ctx.taoLuc}</dd><dt>Mã lượt</dt><dd class="ma">#${id}</dd></dl>
        <div class="hn-pop-f"><span class="nho">Khác:</span>${nutChia(id, false)}${job.drive_folder_link
          ? `<a class="btn" href="${esc(job.drive_folder_link)}" target="_blank" rel="noopener">Mở thư mục Drive ↗</a>` : ""}</div>
      </div>`;
  }

  window.TheLuotGon = Object.freeze({ nganGon, hanhDong, theGon, popup, buoc, nhanMa, gioNgan });
})();
