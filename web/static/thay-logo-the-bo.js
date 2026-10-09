// Dải "Bộ của bạn" (đọc /api/thay-logo/bo) + bộ lọc Bộ / Nền tảng / Ngày / Trạng thái. Bộ, nền tảng, ngày lọc ở máy chủ (T.datLoc); trạng thái lọc ở trang.
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TT = [["dang_xu_ly", "Đang xử lý"], ["cho_duyet", "Chờ duyệt"], ["khong_chac", "Máy không chắc"], ["loi", "Lỗi"], ["da_dat", "Đã đạt"], ["hong", "Hỏng"]];
  const NEN = [["", "Tất cả"], ["tiktok", "TikTok"], ["douyin", "Douyin"], ["facebook", "Facebook"]];
  const NGAY = [["", "Tất cả"], ["hom_nay", "Hôm nay"], ["7_ngay", "7 ngày"]];
  const NGUON = { drive: "Thư viện", may: "Tải từ máy", link: "Link Drive", vao_bo: "Đã vào bộ" };
  const IDRE = /^[A-Za-z0-9_-]{6,120}$/;

  // Trạng thái bộ: còn video chưa ra kết quả ⇒ Đang xử lý; hết việc của máy mà còn video chưa chấm ⇒ Chờ bạn duyệt; còn lại Xong.
  function trangThaiBo(b) {
    if (b.tong - b.xong - b.cho_nguoi - b.loi > 0) return ["Đang xử lý", "dang"];
    if (b.cho_duyet > 0) return ["Chờ bạn duyệt", "cho"];
    return ["Xong", "xong"];
  }

  function theBo(b) {
    const [chu, cls] = trangThaiBo(b);
    const the = el("div", "tl-bo-the " + cls + (T.loc.job === b.job_id ? " on" : ""));
    const nut = el("button", "tl-bo-chon"); nut.type = "button"; nut.dataset.job = String(b.job_id);
    nut.setAttribute("aria-pressed", String(T.loc.job === b.job_id));
    const h = el("div", "tl-bo-h"); h.append(el("b", "tl-bo-ten", b.ten_bo), el("span", "tl-bo-tt", chu));
    const nguon = el("div", "tl-bo-nguon", `${NGUON[b.nguon_kieu] || "Nguồn khác"} · ${b.tong} video · ${T.ngayGio(b.tao_luc)}`);
    const bar = el("div", "tl-bo-bar"); const i = el("i"); i.style.width = (b.tong ? Math.round(100 * b.xong / b.tong) : 0) + "%"; bar.append(i);
    const tien = el("div", "tl-bo-tien"); tien.append(el("b", "", `${b.xong}/${b.tong} xong`));
    const phu = [];
    if (b.cho_duyet) phu.push(`${b.cho_duyet} cần bạn xem`);
    if (b.cho_nguoi) phu.push(`${b.cho_nguoi} máy không chắc`);
    if (b.loi) phu.push(`${b.loi} lỗi`);
    if (phu.length) tien.append(" · " + phu.join(" · "));
    nut.append(h, nguon, bar, tien);
    nut.addEventListener("click", () => T.datLoc("job", T.loc.job === b.job_id ? null : b.job_id));
    the.append(nut);
    if (b.thu_muc_ra_id && IDRE.test(b.thu_muc_ra_id)) {
      const a = el("a", "tl-bo-thumuc", "Mở thư mục đầu ra →");
      a.href = `https://drive.google.com/drive/folders/${encodeURIComponent(b.thu_muc_ra_id)}`; a.target = "_blank"; a.rel = "noopener";
      the.append(a);
    }
    return the;
  }

  function veBo() {
    const l = $("tl-bo-list"); l.replaceChildren();
    if (!T.bo.length) { l.append(el("div", "tl-bo-rong", "Chưa có bộ nào. Chọn video ở trên, đặt tên bộ rồi bấm “Thay logo” — bộ sẽ hiện ở đây cùng tiến độ.")); return; }
    for (const b of T.bo) l.append(theBo(b));
  }

  function chipLoc(chu, bat, khiBam, extra) {
    const b = el("button", "tl-chip-loc", chu); b.type = "button"; b.setAttribute("aria-pressed", String(bat));
    if (extra) Object.assign(b.dataset, extra);
    b.addEventListener("click", khiBam);
    return b;
  }

  const docDoTuoi = () => (T.capNhatLuc ? `⟳ ${Math.round((Date.now() - T.capNhatLuc) / 1000)} giây trước` : "⟳ …");

  function veLoc() {
    const hop = $("tl-loc"); hop.replaceChildren();
    const dem = {}; for (const v of T.videos) dem[T.nhomCua(v)] = (dem[T.nhomCua(v)] || 0) + 1;
    const nhom = (ten, ...con) => { const g = el("div", "tl-loc-nhom"); g.append(el("span", "lb", ten), ...con); return g; };
    const sel = el("select", "tl-sel"); sel.id = "tl-loc-bo"; sel.setAttribute("aria-label", "Bộ");
    const o0 = el("option", "", `Tất cả bộ (${T.bo.length})`); o0.value = ""; sel.append(o0);
    for (const b of T.bo) { const o = el("option", "", b.ten_bo); o.value = String(b.job_id); sel.append(o); }
    sel.value = T.loc.job ? String(T.loc.job) : "";
    sel.addEventListener("change", () => T.datLoc("job", sel.value ? Number(sel.value) : null));
    const h1 = el("div", "tl-loc-hang");
    h1.append(nhom("Bộ", sel),
      nhom("Nền tảng", ...NEN.map(([k, ten]) => chipLoc(ten, T.loc.nen === k, () => T.datLoc("nen", k), { nen: k }))),
      nhom("Ngày", ...NGAY.map(([k, ten]) => chipLoc(ten, T.loc.ngay === k, () => T.datLoc("ngay", k), { ngay: k }))));
    const h2 = el("div", "tl-loc-hang");
    const g = nhom("Trạng thái");
    for (const [k, ten] of TT) {
      const b = el("button", "tl-chip-loc"); b.type = "button"; b.dataset.tt = k;
      b.setAttribute("aria-pressed", String(T.locTT.has(k)));
      b.append(ten + " ", el("span", "n", String(dem[k] || 0)));
      b.addEventListener("click", () => { T.locTT.has(k) ? T.locTT.delete(k) : T.locTT.add(k); T.veLai(); });
      g.append(b);
    }
    h2.append(g, el("span", "tl-loc-ghi", "Không bấm trạng thái nào = xem tất cả"),
              Object.assign(el("span", "tl-loc-ghi", docDoTuoi()), { id: "tl-do-tuoi" }));
    hop.append(h1, h2);
    if (T.conNua) {
      const h3 = el("div", "tl-loc-hang"); h3.append(el("span", "tl-loc-ghi", "Còn video cũ hơn chưa hiện."));
      const m = el("button", "btn tl-xem-them", "Xem thêm"); m.type = "button"; m.addEventListener("click", () => T.xemThem());
      h3.append(m); hop.append(h3);
    }
    if (T.thuVienLoi) hop.append(el("p", "tl-loc-canh", "Không đọc được thư viện — tên video tạm ẩn."));
  }

  T.ve.bo = () => { veBo(); veLoc(); };
  T.locDuoc = () => (T.locTT.size ? T.videos.filter((v) => T.locTT.has(T.nhomCua(v))) : T.videos);
  // Chỉ đổi chữ "độ tươi": vẽ lại cả bộ lọc sẽ đóng ô chọn bộ đang mở.
  setInterval(() => { const e = $("tl-do-tuoi"); if (e) e.textContent = docDoTuoi(); }, 5000);
})();
