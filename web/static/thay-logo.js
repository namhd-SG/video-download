// Trang "Thay logo" (M2 khung theo bộ). Khởi động: theme, kiểm tính năng bật/tắt, poll danh sách. Poll 15 giây, không SSE.
(() => {
  "use strict";
  const T = window.TL, { $ } = T;
  const POLL_MS = 15000;

  const THEME_KEY = "videodl-theme";
  const apTheme = (t) => (t === "light" || t === "dark") ? document.documentElement.setAttribute("data-theme", t)
                                                        : document.documentElement.removeAttribute("data-theme");
  try { apTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* trình duyệt chặn lưu trữ: theo hệ điều hành */ }
  $("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* bỏ qua */ }
    apTheme(next);
  });

  function veTomTat() {
    const dem = {}; for (const v of T.videos) dem[T.nhomCua(v)] = (dem[T.nhomCua(v)] || 0) + 1;
    const soi = T.videos.filter((v) => T.nhomCua(v) === "cho_duyet" && T.soiKy(v)).length;
    const p = $("tl-tom-tat"); p.replaceChildren();
    const b = document.createElement("b"); b.textContent = `${dem.cho_duyet || 0} video chờ duyệt`;
    p.append("Việc của bạn: ", b, ` · ${soi} cần bạn xem kỹ · ${dem.dang_xu_ly || 0} video máy đang làm, bạn không cần chờ.`);
  }
  T.ve.tomTat = veTomTat;

  const z2 = (n) => String(n).padStart(2, "0");
  const ngayCuc = (d) => `${d.getFullYear()}-${z2(d.getMonth() + 1)}-${z2(d.getDate())}`;
  // Bộ lọc nối API thật: bộ (job_id), nền tảng, ngày (tu) lọc ở máy chủ; trạng thái lọc ở trang (nhiều chip cùng lúc).
  // Nhận BẢN CHỤP bộ lọc (không đọc T.loc) để một vòng tải nhiều trang không trộn hai bộ lọc khi người dùng đổi giữa chừng.
  function duongVideos(loc, truoc) {
    const q = new URLSearchParams();
    if (loc.job) q.set("job_id", String(loc.job));
    if (loc.nen) q.set("nen_tang", loc.nen);
    if (loc.ngay === "hom_nay") q.set("tu", ngayCuc(new Date()));
    if (loc.ngay === "7_ngay") q.set("tu", ngayCuc(new Date(Date.now() - 6 * 86400000)));
    if (truoc) q.set("truoc_id", String(truoc));
    const chuoi = q.toString();
    return "/api/thay-logo/videos" + (chuoi ? "?" + chuoi : "");
  }
  const LOI_TAI = "Chưa tải được danh sách mới nhất — máy sẽ tự thử lại sau ít giây.";
  const LOI_LOC = "Không đọc được thư viện để lọc theo nền tảng — thử lại sau.";
  let soTrang = 1, dangTai = false, choTaiLai = false;
  let the = 0;  // số THẾ HỆ bộ lọc: đổi lọc ⇒ +1; phản hồi của vòng tải bắt đầu ở thế hệ cũ bị bỏ, không vẽ video của lọc cũ
  let timPoll = null;
  async function taiBo() {
    const r = await T.goi("/api/thay-logo/bo");
    return r.ok ? ((await r.json()).bo || []) : null;
  }
  // Trả {ds, conNua, truocTiep, thuVienLoi, soTrangThat} hoặc {loi}. Số trang là BIẾN CỤC BỘ: `xemThem` bấm giữa vòng tải không bị ghi đè.
  async function taiVideos(loc, trang) {
    let ds = [], truoc = null, d = null, daTai = 0;
    for (let i = 0; i < trang; i++) {  // poll tải lại đủ số trang người dùng đã mở, không cắt về trang đầu
      const r = await T.goi(duongVideos(loc, truoc));
      if (!r.ok) return { loi: r.status === 503 && loc.nen ? LOI_LOC : LOI_TAI };
      d = await r.json(); ds = ds.concat(d.videos || []); truoc = d.truoc_tiep; daTai = i + 1;
      if (!d.con_nua) break;
    }
    return { ds, conNua: !!d.con_nua, truocTiep: d.truoc_tiep, thuVienLoi: !!d.thu_vien_loi, soTrangThat: daTai };
  }
  async function taiLai() {
    if (dangTai) { choTaiLai = true; return; }  // đổi bộ lọc giữa lúc đang tải ⇒ tải lại ngay sau đó, không để dữ liệu cũ nằm lại
    dangTai = true;
    const the0 = the, loc = { ...T.loc }, trang = soTrang;
    try {
      const [bo, vd] = await Promise.all([taiBo(), taiVideos(loc, trang)]);
      if (the0 !== the) return;  // lọc đã đổi trong lúc chờ: bỏ phản hồi này (vòng tải kế tiếp do `finally` kích)
      let loi = bo ? "" : LOI_TAI;
      if (bo) {
        T.bo = bo;
        if (T.loc.job && !bo.some((b) => b.job_id === T.loc.job)) {  // bộ đang lọc không còn ⇒ bỏ lọc và tải lại, dữ liệu vừa tải thuộc lọc cũ
          T.loc.job = null; the += 1; soTrang = 1; choTaiLai = true; return;
        }
      }
      if (vd.loi) loi = vd.loi;
      else {
        for (const v of vd.ds) if (!v.danh_gia && T.daCham.has(v.id)) v.danh_gia = T.daCham.get(v.id);  // phản hồi tải sớm hơn lúc chấm không được đưa video về hàng chờ
        T.videos = vd.ds; T.conNua = vd.conNua; T.truocTiep = vd.truocTiep; T.thuVienLoi = vd.thuVienLoi;
        if (vd.soTrangThat < trang) soTrang = Math.max(1, Math.min(soTrang, vd.soTrangThat));  // máy chủ hết dữ liệu sớm hơn số trang đã mở
      }
      T.dangTaiLoc = false;
      T.loiTai(loi);
      if (!loi) T.capNhatLuc = Date.now();  // "⟳ x giây trước" chỉ nhích khi CẢ /bo và /videos đều ok
      T.veLai();
    } catch (e) {
      if (e && e.message === "het_phien") { clearInterval(timPoll); return; }  // hết phiên đã báo trên trang; poll tiếp chỉ tạo thêm 401
      if (the0 === the) { T.dangTaiLoc = false; T.loiTai(LOI_TAI); T.veLai(); }  // lỗi mạng
    } finally { dangTai = false; if (choTaiLai) { choTaiLai = false; taiLai(); } }
  }
  window.TL_taiLai = taiLai;
  T.datLoc = (khoa, gia) => {
    T.loc[khoa] = gia; soTrang = 1; the += 1;
    T.videos = []; T.conNua = false; T.dangTaiLoc = true;  // đừng để video của lọc cũ nằm dưới chip lọc mới
    T.veLai(); taiLai();
  };
  T.xemThem = () => { soTrang += 1; taiLai(); };

  async function kiemBat() {
    try {
      const r = await T.goi("/tinh-nang");
      if (r.ok && !(await r.json()).thay_logo_bat) {  // máy chủ không nhận lượt mới (409) ⇒ đừng để nút trông bấm được
        T.tat = true; $("tat").hidden = false;
        document.querySelectorAll("#tl-nhap input, #tl-nhap button.btn").forEach((e) => { if (e.id !== "tl-thu-gon") e.disabled = true; });
        T.veLai();
      }
    } catch (_) { /* bỏ qua */ }
  }

  T.veLai();
  kiemBat();
  taiLai();
  timPoll = setInterval(taiLai, POLL_MS);
})();
