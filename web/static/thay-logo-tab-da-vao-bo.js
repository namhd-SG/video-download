// Tab "Đã vào bộ" của khối "Đưa video vào": video của bạn đã nằm trong một bộ chạy quảng cáo, nhóm theo mã bộ. Máy dùng BẢN TRONG BỘ.
// Đăng ký vào window.TL_TAB_NGUON theo hợp đồng ở thay-logo-chung.js: `ve(hop, T)` idempotent, tự đọc T.tat.
//
// Chọn video = thêm `ban_copy_id` (id file Drive hợp lệ) vào T.nhapChon để bộ đếm / nút "Thay logo" chạy như các tab khác. Khối nhập
// đưa các id đó vào `drive_file_ids`; hook TL_THAN_POST của module này chuyển id nào là bản trong bộ sang
// `vao_bo: [{video_id, ban_copy_id}]` (máy chủ cần video_id để kiểm chủ video và chụp md5/size nguồn).
(() => {
  "use strict";
  const T = window.TL, { el } = T;
  const TEN_NEN = { tiktok: "TikTok", douyin: "Douyin", facebook: "Facebook" };
  const MA_TEN_MAC_DINH = /^\d{2}\/\d{2}-\d+$/;
  const chon = new Map();               // ban_copy_id → { video_id, ma_bo }: phần của T.nhapChon đến từ tab này
  let data = null, loi = false, dangTai = false, nen = "", hopVe = null, maTuDien = null;

  const ngay = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`; };
  const dongBoChon = () => { for (const id of [...chon.keys()]) if (!T.nhapChon.has(id)) chon.delete(id); };  // khối nhập đã xoá (tạo lượt xong)

  // Tên bộ tự điền mã bộ khi MỌI video đang chọn cùng một bộ; chỉ ghi đè ô khi nó trống / là tên mặc định / là mã do chính tab này điền.
  function tuDienTenBo() {
    const o = document.getElementById("tl-ten-bo"), mas = new Set([...chon.values()].map((c) => c.ma_bo));
    if (!o || mas.size !== 1 || chon.size !== T.nhapChon.size) return;
    const ma = [...mas][0], hien = o.value.trim();
    if (hien === "" || hien === maTuDien || MA_TEN_MAC_DINH.test(hien)) {
      if (hien !== ma) { o.value = ma; o.dispatchEvent(new Event("input")); }  // "input" ⇒ khối nhập coi là tên đã sửa, không ghi đè lại
      maTuDien = ma;
    }
  }

  function datChon(v, ma, bat) {
    if (bat) { chon.set(v.ban_copy_id, { video_id: v.video_id, ma_bo: ma }); T.nhapChon.add(v.ban_copy_id); }
    else { chon.delete(v.ban_copy_id); T.nhapChon.delete(v.ban_copy_id); }
  }
  function xong() { T.capNhatChan(); tuDienTenBo(); if (hopVe) ve(hopVe); }

  function theVideo(v, ma) {
    const bat = chon.has(v.ban_copy_id);
    const the = el("label", "tl-the-v" + (bat ? " on" : "") + (v.da_trong_luot ? " mo" : ""));
    const cb = el("input"); cb.type = "checkbox"; cb.value = v.ban_copy_id; cb.checked = bat; cb.disabled = T.tat || v.da_trong_luot;
    cb.addEventListener("change", () => { datChon(v, ma, cb.checked); xong(); });
    const bia = el("span", "tl-bia", "▶");
    if (v.anh_bia) { const img = el("img"); img.alt = ""; img.src = v.anh_bia; img.addEventListener("load", () => bia.replaceChildren(img), { once: true }); }
    const ten = el("span", "tl-ten-v", v.ten_video || "Video");
    const phu = [TEN_NEN[v.nen_tang] || v.nen_tang, v.da_trong_luot ? "đã trong lượt thay logo" : ""].filter(Boolean).join(" · ");
    the.append(cb, bia, ten);
    if (phu) the.append(el("span", "tl-vb-phu", phu));
    return the;
  }

  function dauNhom(bo, ds) {
    const chonDuoc = ds.filter((v) => !v.da_trong_luot), daChon = chonDuoc.filter((v) => chon.has(v.ban_copy_id)).length;
    const trangThai = !chonDuoc.length || daChon === 0 ? "false" : daChon === chonDuoc.length ? "true" : "mixed";
    const d = el("div", "tl-vb-nhom");
    const b = el("button", "tl-vb-chon-ca"); b.type = "button"; b.setAttribute("role", "checkbox"); b.setAttribute("aria-checked", trangThai);
    b.disabled = T.tat || !chonDuoc.length;
    b.append(el("span", "tl-vb-hop"), "Chọn cả bộ ");
    const ma = el("b", "", bo.ma_bo); b.append(ma, ` (${ds.length} video)`);
    b.addEventListener("click", () => { const bat = trangThai !== "true"; for (const v of chonDuoc) datChon(v, bo.ma_bo, bat); xong(); });
    d.append(b, el("span", "muted", `vào bộ ${ngay(bo.vao_bo_luc)}`));
    return d;
  }

  function ve(hop) {
    hopVe = hop; dongBoChon();
    hop.replaceChildren();
    hop.append(el("p", "tl-vb-ghi", "Máy dùng bản trong bộ."));
    if (data === null) { hop.append(el("p", "muted", loi ? "Chưa tải được danh sách — chuyển sang tab khác rồi quay lại để thử lại." : "Đang tải…")); taiDuLieu(); return; }
    const nens = [...new Set(data.flatMap((b) => b.videos.map((v) => v.nen_tang)).filter(Boolean))];
    if (nens.length > 1 || nen) {
      const hang = el("div", "tl-loc-nhom");
      for (const [k, t] of [["", "Tất cả"], ...nens.map((n) => [n, TEN_NEN[n] || n])]) {
        const c = el("button", "tl-chip-loc", t); c.type = "button"; c.setAttribute("aria-pressed", String(k === nen));
        c.addEventListener("click", () => { nen = k; ve(hop); });
        hang.append(c);
      }
      hop.append(hang);
    }
    const luoi = el("div", "tl-luoi"); let co = 0;
    for (const bo of data) {
      const ds = bo.videos.filter((v) => !nen || v.nen_tang === nen);
      if (!ds.length) continue;
      co += ds.length; luoi.append(dauNhom(bo, ds));
      for (const v of ds) luoi.append(theVideo(v, bo.ma_bo));
    }
    hop.append(co ? luoi : el("p", "muted", data.length ? "Không có video khớp." : "Bạn chưa có video nào đã vào bộ."));
    taiDuLieu();
  }

  // Mỗi lần mở tab tải lại một lần (nền): danh sách + cờ "đã trong lượt" luôn mới; không có lượt tải chồng nhau.
  let daHoi = false;
  async function taiDuLieu() {
    if (dangTai || daHoi) return;
    dangTai = daHoi = true;
    try {
      const r = await T.goi("/api/thay-logo/da-vao-bo");
      if (!r.ok) throw new Error("http");
      data = (await r.json()).bo || []; loi = false;
    } catch (e) { if (data === null) loi = true; }
    finally {
      dangTai = false;
      if (hopVe && !hopVe.hidden) { dongBoChon(); const h = hopVe; daHoi = true; ve(h); }
    }
  }

  window.TL_TAB_NGUON = window.TL_TAB_NGUON || [];
  window.TL_TAB_NGUON.push({
    id: "bo",
    giai: "Video của bạn đã nằm trong một bộ. Chọn cả bộ hoặc tick từng video.",
    ve(hop) { daHoi = false; ve(hop); },
  });

  // Hook thân POST tạo lượt (TL_THAN_POST): id bản-trong-bộ rời `drive_file_ids` sang `vao_bo`.
  window.TL_THAN_POST = window.TL_THAN_POST || [];
  window.TL_THAN_POST.push((than) => {
    dongBoChon();
    const vb = [], ids = [];
    for (const id of than.drive_file_ids || []) { const c = chon.get(id); if (c) vb.push({ video_id: c.video_id, ban_copy_id: id }); else ids.push(id); }
    if (vb.length) { than.drive_file_ids = ids; than.vao_bo = vb; }
  });
})();
