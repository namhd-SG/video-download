// Khối "Đưa video vào": 4 tab (mỗi tab một container), Thu gọn, Tên bộ tự điền, nút chạy. Chỉ tab Thư viện có sẵn; 3 tab còn lại do module trong TL_TAB_NGUON gắn sau, chưa có thì báo "Sắp có".
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TABS = [["thu-vien", "Thư viện của bạn"], ["bo", "Đã vào bộ"], ["may", "Tải từ máy"], ["link", "Dán link Drive"]];
  const SAP_CO = {
    bo: "Chọn lại video đã nằm trong một bộ — sắp có.",
    may: "Tải video từ máy của bạn lên — sắp có.",
    link: "Dán link file hoặc thư mục Drive — sắp có.",
  };
  let tab = "thu-vien", thuVien = null, tim = "";   // thuVien: null = chưa tải, [] = trống
  const chon = new Set();

  function datTab(k) {
    tab = k;
    for (const b of document.querySelectorAll("#tl-tabs [role=tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === k));
    veVung();
  }

  function veTabs() {
    const hop = $("tl-tabs"); hop.replaceChildren();
    for (const [k, ten] of TABS) {
      const b = el("button", "tl-tab"); b.type = "button"; b.setAttribute("role", "tab"); b.dataset.tab = k;
      b.setAttribute("aria-selected", String(k === tab));
      b.append(ten + " ");
      const n = k === "thu-vien" && thuVien ? thuVien.length : 0;
      b.append(el("span", "tl-cnt" + (n ? "" : " zero"), String(n)));
      b.addEventListener("click", () => datTab(k));
      hop.append(b);
    }
  }

  // Mỗi tab có container riêng (#tl-tab-<k>). Tab có module đăng ký trong window.TL_TAB_NGUON thì module vẽ; chưa có ⇒ "Sắp có".
  const moduleCua = (k) => (window.TL_TAB_NGUON || []).find((m) => m && m.id === k);

  function veVung() {
    const m = tab === "thu-vien" ? null : moduleCua(tab);
    $("tl-tab-giai").textContent = tab === "thu-vien" ? "Video bạn đã tải qua Video Desk (đã lên Drive). Tick những video muốn thay." : (m && m.giai) || SAP_CO[tab];
    $("tl-tim-hop").hidden = tab !== "thu-vien";
    for (const [k] of TABS) $("tl-tab-" + k).hidden = k !== tab;
    if (tab !== "thu-vien") {
      const hop = $("tl-tab-" + tab); hop.replaceChildren();
      if (m && typeof m.ve === "function") m.ve(hop, T); else hop.append(T.sapCo("Sắp có — chưa có dữ liệu từ máy chủ."));
      return;
    }
    const v = $("tl-tab-thu-vien"); v.replaceChildren();
    if (thuVien === null) { v.append(el("p", "muted", "Đang tải thư viện…")); return; }
    const ds = thuVien.filter((x) => !tim || String(x.title || x.video_id || x.drive_file_id).toLowerCase().includes(tim));
    if (!ds.length) { v.append(el("p", "muted", thuVien.length ? "Không có video khớp." : "Thư viện chưa có video nào đã lên Drive.")); return; }
    const luoi = el("div", "tl-luoi");
    for (const x of ds) {
      const the = el("label", "tl-the-v" + (chon.has(x.drive_file_id) ? " on" : ""));
      const cb = el("input"); cb.type = "checkbox"; cb.value = x.drive_file_id; cb.checked = chon.has(x.drive_file_id); cb.disabled = T.tat;
      cb.addEventListener("change", () => { cb.checked ? chon.add(x.drive_file_id) : chon.delete(x.drive_file_id); the.classList.toggle("on", cb.checked); veChan(); });
      const bia = el("span", "tl-bia", "▶");
      if (x.video_id) {
        const img = el("img"); img.alt = ""; img.src = `/thumbs/${encodeURIComponent(x.video_id)}`;
        img.addEventListener("load", () => bia.replaceChildren(img), { once: true });  // chỉ thay chữ ▶ khi ảnh bìa tải được
      }
      the.append(cb, bia, el("span", "tl-ten-v", x.title || x.video_id || "Video"));
      luoi.append(the);
    }
    v.append(luoi);
  }

  // Tên bộ tự điền `dd/mm-n`: n = số bộ hôm nay của member + 1 (đếm từ /bo). Người dùng đã gõ vào ô thì KHÔNG ghi đè.
  let tenSua = false;
  function tenBoMacDinh() {
    const hn = new Date(), z = (n) => String(n).padStart(2, "0"), cung = (g) => { const d = new Date(g * 1000); return d.getFullYear() === hn.getFullYear() && d.getMonth() === hn.getMonth() && d.getDate() === hn.getDate(); };
    const n = T.bo.filter((b) => cung(b.tao_luc)).length + 1;
    return `${z(hn.getDate())}/${z(hn.getMonth() + 1)}-${n}`;
  }

  function veChan() {
    const n = chon.size, o = $("tl-ten-bo");
    if (!tenSua) o.value = tenBoMacDinh();
    const ten = o.value.trim();
    $("tl-dem").textContent = n ? `Đã chọn ${n} video` : "Chưa chọn video nào";
    $("tl-tao").textContent = n ? `Thay logo ${n} video${ten ? " · bộ " + ten : ""}` : "Thay logo";
    $("tl-tao").disabled = T.tat || n === 0;
  }

  async function taiThuVien() {
    try {
      const r = await T.goi("/videos?limit=100");
      thuVien = r.ok ? ((await r.json()).videos || []).filter((x) => x.drive_file_id) : [];
    } catch (_) { thuVien = []; }
    veTabs(); veVung(); veChan();
  }

  function datThuGon(gon) {
    $("tl-form").hidden = gon; $("tl-nhap-gon").hidden = !gon;
    $("tl-thu-gon").setAttribute("aria-expanded", String(!gon));
  }

  // Câu lời thường cho từng mã lỗi của POST /jobs (400 sai khuôn · 403 video không thuộc bạn · 409 cổng cấm · 429 quá nhiều chờ).
  function cauLoi(status, detail) {
    if (status === 400) return "Tên bộ cần 1–80 ký tự, và video đã chọn phải hợp lệ. Kiểm lại rồi bấm lại.";
    if (status === 403) return "Chỉ chọn được video trong thư viện của bạn hoặc link bạn đã kiểm trong 24 giờ qua — nếu dán link lâu rồi, bấm Kiểm link lại.";
    if (status === 409) return "Tính năng thay logo đang tạm tắt — chưa nhận lượt mới. Thử lại sau hoặc báo quản trị.";
    if (status === 429) return "Bạn đang có quá nhiều video chờ (tối đa 100). Đợi máy làm bớt rồi bấm lại.";
    return "Chưa gửi được lượt này. Thử lại sau ít phút.";
  }

  let dangGui = false;
  async function tao(ev) {
    ev.preventDefault(); T.loi("");
    if (dangGui) return;
    if (!chon.size) { T.loi("Chưa có video nào."); return; }
    const ten = $("tl-ten-bo").value.trim();
    if (!ten || ten.length > 80) { T.loi("Tên bộ cần 1–80 ký tự."); return; }
    dangGui = true; $("tl-tao").disabled = true;
    try {
      const than = { drive_file_ids: [...chon], ten_bo: ten };
      for (const hook of window.TL_THAN_POST || []) hook(than, T);  // tab nguồn sửa thân (vd tab Đã vào bộ thêm `vao_bo`)
      const r = await T.goi("/api/thay-logo/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(than) });
      if (!r.ok) { T.loi(cauLoi(r.status)); return; }
      chon.clear(); tenSua = false;
      veVung();
      await window.TL_taiLai();
    } catch (e) { if (!e || e.message !== "het_phien") T.loi("Chưa gửi được — kiểm tra mạng rồi bấm lại."); }  // hết phiên đã có thông báo riêng
    finally { dangGui = false; veChan(); }
  }

  T.ve.nhap = () => { veChan(); if (T.tat) veVung(); };
  $("tl-thu-gon").addEventListener("click", () => datThuGon(true));
  $("tl-nhap-gon").addEventListener("click", () => datThuGon(false));
  $("tl-ten-bo").addEventListener("input", () => { tenSua = true; veChan(); });
  $("tl-tim").addEventListener("input", (e) => { tim = e.target.value.trim().toLowerCase(); veVung(); });
  $("tl-form").addEventListener("submit", tao);
  T.nhapChon = chon; T.capNhatChan = veChan;
  veTabs(); veVung(); veChan(); taiThuVien();
})();
