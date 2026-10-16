// Khối "Đưa video vào": 4 tab nguồn (mỗi tab một container) bên trái + GIỎ bên phải (nhóm theo nguồn, "Thành phẩm đi đâu?", tên lượt,
// nút chạy). Tab "Bộ tự tìm" đứng đầu và mở sẵn. Chỉ tab Thư viện vẽ ở đây; 3 tab còn lại do module trong TL_TAB_NGUON gắn sau.
// Giỏ trộn (video từ bộ + nguồn khác) gửi MỘT POST; máy chủ tách thành hai lượt nguyên tử (lượt từ bộ trả về bộ gốc, lượt kia theo
// `dich_khac`).
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TABS = [["bo", "Bộ tự tìm"], ["thu-vien", "Thư viện của bạn"], ["may", "Tải từ máy"], ["link", "Dán link Drive"]];
  const SAP_CO = {
    bo: "Chọn lại video đã nằm trong một bộ — sắp có.",
    may: "Tải video từ máy của bạn lên — sắp có.",
    link: "Dán link file hoặc thư mục Drive — sắp có.",
  };
  let tab = "bo", thuVien = null, tim = "";   // thuVien: null = chưa tải, [] = trống
  let dichKhac = "tao_bo";                    // nơi nhận của video nguồn khác — mặc định theo mock đã duyệt (bộ tự tìm mới)
  const chon = new Set();

  function datTab(k) {
    tab = k;
    for (const b of document.querySelectorAll("#tl-tabs [role=tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === k));
    veVung();
  }

  // Tab của module: số video ĐÃ CHỌN từ tab đó (module cung cấp `dem()`); Thư viện: số video thư viện đang chọn.
  const moduleCua = (k) => (window.TL_TAB_NGUON || []).find((m) => m && m.id === k);
  const demModule = (k) => { const m = moduleCua(k); return m && typeof m.dem === "function" ? m.dem() : 0; };
  const demThuVien = () => (thuVien ? thuVien.filter((x) => chon.has(x.drive_file_id)).length : 0);
  // Phân nhóm giỏ theo nguồn. Link Drive không có `dem()` ⇒ phần còn lại sau khi trừ các nguồn đã biết.
  function nhomGio() {
    const bo = demModule("bo"), may = demModule("may"), tv = demThuVien();
    return { bo, may, tv, link: Math.max(0, chon.size - bo - may - tv) };
  }

  function veTabs() {
    const hop = $("tl-tabs"); hop.replaceChildren();
    for (const [k, ten] of TABS) {
      const b = el("button", "tl-tab"); b.type = "button"; b.setAttribute("role", "tab"); b.dataset.tab = k;
      b.setAttribute("aria-selected", String(k === tab));
      b.append(ten + " ");
      const n = k === "thu-vien" ? demThuVien() : demModule(k);
      b.append(el("span", "tl-cnt" + (n ? "" : " zero"), String(n)));
      b.addEventListener("click", () => datTab(k));
      hop.append(b);
    }
  }

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

  // Tên lượt tự điền `dd/mm-n`: n = số lượt hôm nay của member + 1 (đếm từ /bo). Người dùng đã gõ vào ô thì KHÔNG ghi đè.
  let tenSua = false;
  function tenBoMacDinh() {
    const hn = new Date(), z = (n) => String(n).padStart(2, "0"), cung = (g) => { const d = new Date(g * 1000); return d.getFullYear() === hn.getFullYear() && d.getMonth() === hn.getMonth() && d.getDate() === hn.getDate(); };
    const n = T.bo.filter((b) => cung(b.tao_luc)).length + 1;
    return `${z(hn.getDate())}/${z(hn.getMonth() + 1)}-${n}`;
  }

  // Giỏ: mỗi nguồn một nhóm. Video từ bộ liệt theo mã bộ (module "bo" khai `gio()`).
  function veGioDs(g) {
    const hop = $("tl-gio-ds"); hop.replaceChildren();
    const nhom = (ten, so, dong) => {
      const d = el("div", "tl-gio-nhom"); const h = el("h4"); h.append(el("span", "", ten), el("span", "tl-gio-so", `${so} video`)); d.append(h);
      const ul = el("ul"); for (const x of dong) ul.append(el("li", "", x)); d.append(ul); return d;
    };
    if (g.bo) { const m = moduleCua("bo"); hop.append(nhom("Từ bộ tự tìm", g.bo, (m && m.gio ? m.gio() : []).map((x) => `${x.ma} · ${x.so} video`))); }
    const khac = g.tv + g.may + g.link;
    if (khac) hop.append(nhom("Nguồn khác", khac, [g.tv && `Thư viện · ${g.tv} video`, g.may && `Tải từ máy · ${g.may} video`, g.link && `Link Drive · ${g.link} video`].filter(Boolean)));
    if (!g.bo && !khac) hop.append(el("p", "tl-gio-rong", "Giỏ trống — chọn video ở bên trái."));
  }

  // "Thành phẩm đi đâu?": video từ bộ ⇒ cố định trả về bộ gốc sau Đạt; nguồn khác ⇒ chọn bộ tự tìm mới / thư mục Drive.
  function veDich(g) {
    const hop = $("tl-dich"); hop.replaceChildren();
    const khac = g.tv + g.may + g.link;
    if (!g.bo && !khac) { hop.hidden = true; return; }
    hop.hidden = false;
    hop.append(el("h3", "", "Thành phẩm đi đâu?"));
    if (g.bo) {
      const p = el("p", "tl-dich-co-dinh");
      p.append("↩ ", el("b", "", `${g.bo} video từ bộ tự tìm`), " sẽ được trả lại đúng bộ gốc (thay bản cũ) ", el("b", "", "sau khi bạn bấm Đạt"),
               ". Bản cũ được cất riêng, hoàn tác được.");
      hop.append(p);
    }
    if (khac) {
      hop.append(el("p", "tl-dich-hoi", `${khac} video nguồn khác — chọn một:`));
      const lua = (gt, tieuDe, moTa, tat) => {
        const l = el("label", "tl-dich-chon" + (dichKhac === gt && !tat ? " on" : "") + (tat ? " tat" : ""));
        const r = el("input"); r.type = "radio"; r.name = "tl-dich"; r.value = gt; r.checked = dichKhac === gt && !tat; r.disabled = !!tat || T.tat;
        r.addEventListener("change", () => { dichKhac = gt; veChan(); });
        const chu = el("span", "tl-dich-chu"); chu.append(el("b", "", tieuDe)); if (moTa) chu.append(el("span", "tl-dich-mo-ta", moTa));
        if (tat) chu.append(el("span", "tl-dich-sau", tat));
        l.append(r, chu); return l;
      };
      hop.append(lua("tao_bo", "Tạo bộ tự tìm mới", "Duyệt xong, bấm một nút để mở Creative Desk tạo bộ — như nút “Tạo bộ tự tìm” ở trang Tải video."),
                 lua("them_bo", "Thêm vào bộ có sẵn", "", "đợt sau"),
                 lua("drive", "Thư mục Drive riêng", "Máy tạo thư mục cho lượt này và đưa link để mở / tải về."));
    }
    hop.append(el("p", "tl-dich-ghi", "Video chỉ rời máy khi bạn bấm Đạt. Bấm Hỏng thì video không đi đâu cả."));
  }

  function veChan() {
    const n = chon.size, o = $("tl-ten-bo");
    if (!tenSua) o.value = tenBoMacDinh();
    const g = nhomGio();
    veGioDs(g); veDich(g);
    $("tl-dem").textContent = n ? `Đã chọn ${n} video` : "Chưa chọn video nào";
    $("tl-tao").textContent = n ? `Thay logo ${n} video` : "Thay logo";
    $("tl-tao").disabled = T.tat || n === 0;
    veTabs();  // số đã chọn trên nhãn tab của module đổi theo lựa chọn
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

  // Câu lời thường cho lỗi của POST /jobs. Máy chủ đã trả `detail` bằng lời thường (403/409/429…) ⇒ dùng nó; ba ca có câu riêng:
  // 400 khi lượt có video từ bộ (bản trong bộ đã đổi), 422 (dữ liệu/độ lớn lượt), 503 (Drive chưa trả lời). Không bao giờ hiện số lỗi.
  function cauLoi(status, detail, coVaoBo) {
    if (status === 422) return "Lượt quá lớn hoặc dữ liệu không hợp lệ.";
    if (status === 503) return "Chưa hỏi được Drive lúc này — thử lại sau ít phút.";
    if (status === 400 && coVaoBo) return "Một số video trong bộ đã đổi hoặc không còn — tải lại danh sách.";
    if (status === 400) return "Tên lượt cần 1–80 ký tự, và video đã chọn phải hợp lệ. Kiểm lại rồi bấm lại.";
    // Chỉ 409 đọc câu máy chủ: 409 có HAI nghĩa (tính năng tắt / bản đã nằm trong lượt khác). Mã khác giữ câu cố định của trang.
    if (status === 409 && typeof detail === "string" && detail) return detail;
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
    if (!ten || ten.length > 80) { T.loi("Tên lượt cần 1–80 ký tự."); return; }
    dangGui = true; $("tl-tao").disabled = true;
    try {
      const g = nhomGio();
      const than = { drive_file_ids: [...chon], ten_bo: ten };
      if (g.tv + g.may + g.link) than.dich_khac = dichKhac === "drive" ? "drive" : "tao_bo";
      try { for (const hook of window.TL_THAN_POST || []) hook(than, T); }  // tab nguồn sửa thân (vd tab Bộ tự tìm thêm `vao_bo`)
      catch (e) { T.loi("Không gửi được lượt này (lỗi dữ liệu trang) — tải lại trang."); return; }
      const r = await T.goi("/api/thay-logo/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(than) });
      if (!r.ok) {
        let detail = null; try { detail = (await r.json()).detail; } catch (_) { /* thân không phải JSON */ }
        const coVaoBo = !!(than.vao_bo && than.vao_bo.length);
        T.loi(cauLoi(r.status, detail, coVaoBo));
        document.dispatchEvent(new CustomEvent("tl-tao-luot-loi", { detail: { status: r.status, coVaoBo } }));  // tab nguồn tải lại dữ liệu của mình
        return;
      }
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
