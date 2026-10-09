// Khối "Đưa video vào": 4 tab, Thu gọn, Tên bộ, nút chạy. Chỉ tab Thư viện có API thật; 3 tab còn lại báo "sắp có".
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TABS = [["thu-vien", "Thư viện của bạn"], ["bo", "Đã vào bộ"], ["may", "Tải từ máy"], ["link", "Dán link Drive"]];
  const SAP_CO = {
    bo: "Chọn lại video đã nằm trong một bộ — cần máy chủ lưu tên bộ/tag cho từng lượt.",
    may: "Tải video từ máy lên — cần máy chủ nhận file.",
    link: "Dán link file hoặc thư mục Drive — cần máy chủ kiểm link thư mục.",
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

  function veVung() {
    const v = $("tl-vung"); v.replaceChildren();
    $("tl-tab-giai").textContent = tab === "thu-vien" ? "Video bạn đã tải qua Video Desk (đã lên Drive). Tick những video muốn thay." : SAP_CO[tab];
    $("tl-tim-hop").hidden = tab !== "thu-vien";
    if (tab !== "thu-vien") { v.append(T.sapCo("Sắp có — chưa có dữ liệu từ máy chủ.")); return; }
    if (thuVien === null) { v.append(el("p", "muted", "Đang tải thư viện…")); return; }
    const ds = thuVien.filter((x) => !tim || String(x.video_id || x.drive_file_id).toLowerCase().includes(tim));
    if (!ds.length) { v.append(el("p", "muted", thuVien.length ? "Không có video khớp." : "Thư viện chưa có video nào đã lên Drive.")); return; }
    const luoi = el("div", "tl-luoi");
    for (const x of ds) {
      const the = el("label", "tl-the-v" + (chon.has(x.drive_file_id) ? " on" : ""));
      const cb = el("input"); cb.type = "checkbox"; cb.value = x.drive_file_id; cb.checked = chon.has(x.drive_file_id); cb.disabled = T.tat;
      cb.addEventListener("change", () => { cb.checked ? chon.add(x.drive_file_id) : chon.delete(x.drive_file_id); the.classList.toggle("on", cb.checked); veChan(); });
      the.append(cb, el("span", "tl-bia", "▶"), el("span", "tl-ten-v", x.video_id || x.drive_file_id));
      luoi.append(the);
    }
    v.append(luoi);
  }

  function veChan() {
    const n = chon.size;
    $("tl-dem").textContent = n ? `Đã chọn ${n} video` : "Chưa chọn video nào";
    $("tl-tao").textContent = n ? `Thay logo ${n} video` : "Thay logo";
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

  async function tao(ev) {
    ev.preventDefault(); T.loi("");
    if (!chon.size) { T.loi("Chưa có video nào."); return; }
    const r = await T.goi("/api/thay-logo/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ drive_file_ids: [...chon] }) });
    if (!r.ok) { const b = await r.json().catch(() => ({})); T.loi((b.detail && String(b.detail)) || `Lỗi ${r.status}`); return; }
    chon.clear(); veVung(); veChan();
    window.TL_taiLai();
  }

  T.ve.nhap = () => { veChan(); if (T.tat) veVung(); };
  $("tl-thu-gon").addEventListener("click", () => datThuGon(true));
  $("tl-nhap-gon").addEventListener("click", () => datThuGon(false));
  $("tl-tim").addEventListener("input", (e) => { tim = e.target.value.trim().toLowerCase(); veVung(); });
  $("tl-form").addEventListener("submit", tao);
  T.nhapChon = chon;
  veTabs(); veVung(); veChan(); taiThuVien();
})();
