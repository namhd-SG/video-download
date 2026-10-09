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
  function duongVideos(truoc) {
    const q = new URLSearchParams();
    if (T.loc.job) q.set("job_id", String(T.loc.job));
    if (T.loc.nen) q.set("nen_tang", T.loc.nen);
    if (T.loc.ngay === "hom_nay") q.set("tu", ngayCuc(new Date()));
    if (T.loc.ngay === "7_ngay") q.set("tu", ngayCuc(new Date(Date.now() - 6 * 86400000)));
    if (truoc) q.set("truoc_id", String(truoc));
    const chuoi = q.toString();
    return "/api/thay-logo/videos" + (chuoi ? "?" + chuoi : "");
  }
  let soTrang = 1, dangTai = false, choTaiLai = false;
  async function taiBo() {
    const r = await T.goi("/api/thay-logo/bo");
    if (r.ok) {
      T.bo = (await r.json()).bo || [];
      if (T.loc.job && !T.bo.some((b) => b.job_id === T.loc.job)) T.loc.job = null;
    }
  }
  async function taiVideos(themTrang) {
    if (themTrang) soTrang += 1;
    let ds = [], truoc = null, d = null;
    for (let i = 0; i < soTrang; i++) {  // poll tải lại đủ số trang người dùng đã mở, không cắt về trang đầu
      const r = await T.goi(duongVideos(truoc));
      if (!r.ok) { if (r.status === 503) T.loi("Không đọc được thư viện để lọc theo nền tảng — thử lại sau."); return false; }
      d = await r.json(); ds = ds.concat(d.videos || []); truoc = d.truoc_tiep;
      if (!d.con_nua) { soTrang = i + 1; break; }
    }
    T.videos = ds; T.conNua = !!d.con_nua; T.truocTiep = d.truoc_tiep; T.thuVienLoi = !!d.thu_vien_loi;
    return true;
  }
  async function taiLai(themTrang) {
    if (dangTai) { choTaiLai = true; return; }  // đổi bộ lọc giữa lúc đang tải ⇒ tải lại ngay sau đó, không để dữ liệu cũ nằm lại
    dangTai = true;
    try {
      await Promise.all([taiBo(), taiVideos(themTrang === true)]);
      T.capNhatLuc = Date.now();
      T.veLai();
    } catch (_) { /* hết phiên đã báo ở trên */ } finally { dangTai = false; if (choTaiLai) { choTaiLai = false; taiLai(); } }
  }
  window.TL_taiLai = taiLai;
  T.datLoc = (khoa, gia) => { T.loc[khoa] = gia; soTrang = 1; T.veLai(); taiLai(); };
  T.xemThem = () => taiLai(true);

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
  setInterval(taiLai, POLL_MS);
})();
