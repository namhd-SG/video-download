// Dải "Bộ của bạn" + bộ lọc. Máy chủ CHƯA lưu tên bộ/tag nên dải bộ báo "sắp có"; chỉ lọc theo trạng thái là thật.
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TT = [["dang_xu_ly", "Đang xử lý"], ["cho_duyet", "Chờ duyệt"], ["khong_chac", "Máy không chắc"], ["loi", "Lỗi"], ["da_dat", "Đã đạt"], ["hong", "Hỏng"]];

  function veBo() {
    const l = $("tl-bo-list"); l.replaceChildren();
    l.append(el("div", "tl-bo-rong", "Chưa có bộ nào. Đặt tên bộ và xem tiến độ từng bộ: sắp có — cần máy chủ lưu tên bộ cho mỗi lượt."));
  }

  function veLoc() {
    const hop = $("tl-loc"); hop.replaceChildren();
    const dem = {}; for (const v of T.videos) dem[T.nhomCua(v)] = (dem[T.nhomCua(v)] || 0) + 1;
    const nhom = (ten, ...con) => { const g = el("div", "tl-loc-nhom"); g.append(el("span", "lb", ten), ...con); return g; };
    const cho = (chu) => { const b = el("button", "tl-chip-loc", chu); b.type = "button"; b.disabled = true; b.title = "Sắp có"; return b; };
    const sel = el("select", "tl-sel"); sel.disabled = true; sel.title = "Sắp có"; sel.setAttribute("aria-label", "Bộ");
    sel.append(el("option", "", "Tất cả bộ (sắp có)"));
    const h1 = el("div", "tl-loc-hang");
    h1.append(nhom("Bộ", sel), nhom("Nền tảng", cho("Tất cả"), cho("TikTok"), cho("Douyin"), cho("Facebook")), nhom("Ngày", cho("7 ngày")));
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
              el("span", "tl-loc-ghi", T.capNhatLuc ? `⟳ ${Math.round((Date.now() - T.capNhatLuc) / 1000)} giây trước` : "⟳ …"));
    hop.append(h1, h2);
  }

  T.ve.bo = () => { veBo(); veLoc(); };
  T.locDuoc = () => (T.locTT.size ? T.videos.filter((v) => T.locTT.has(T.nhomCua(v))) : T.videos);
  setInterval(veLoc, 5000);  // chỉ cập nhật chip "độ tươi"
})();
