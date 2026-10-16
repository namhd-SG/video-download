// Tab "Bộ tự tìm" của khối "Đưa video vào": video của bạn đã nằm trong một bộ tự tìm. Tìm bộ theo MÃ BỘ + NGÀY VÀO BỘ (lọc ở máy chủ,
// `GET /api/thay-logo/da-vao-bo?q=&tu=&den=`), mỗi bộ MỘT dòng với nút "Nạp cả bộ"; "bỏ bớt / xem video" mở danh sách tick từng video.
// Máy dùng BẢN TRONG BỘ; thay xong và bạn bấm Đạt thì bản mới được trả lại đúng bộ đó.
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
  const NGAY = [["", "Tất cả"], ["hom_nay", "Hôm nay"], ["7_ngay", "7 ngày"]];
  const chon = new Map();               // ban_copy_id → { video_id, ma_bo }: phần của T.nhapChon đến từ tab này
  let data = null, biCat = false, loi = false, dangTai = false, hopVe = null, maTuDien = null;
  let tim = "", ngay = "7_ngay", ngayChon = "", the = 0, henTim = null;
  const moRong = new Set();             // folder_id đang mở "bỏ bớt / xem video"

  const z2 = (n) => String(n).padStart(2, "0");
  const ngayCuc = (d) => `${d.getFullYear()}-${z2(d.getMonth() + 1)}-${z2(d.getDate())}`;
  const ngayNgan = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : `${z2(d.getDate())}/${z2(d.getMonth() + 1)}`; };
  const dongBoChon = () => { for (const id of [...chon.keys()]) if (!T.nhapChon.has(id)) chon.delete(id); };  // khối nhập đã xoá (tạo lượt xong)

  // Tên lượt tự điền mã bộ khi MỌI video đang chọn cùng một bộ; chỉ ghi đè ô khi nó trống / là tên mặc định / là mã do chính tab này điền.
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
    const theV = el("label", "tl-the-v" + (bat ? " on" : "") + (v.da_trong_luot ? " mo" : ""));
    const cb = el("input"); cb.type = "checkbox"; cb.value = v.ban_copy_id; cb.checked = bat; cb.disabled = T.tat || v.da_trong_luot;
    cb.addEventListener("change", () => { datChon(v, ma, cb.checked); xong(); });
    const bia = el("span", "tl-bia", "▶");
    if (v.anh_bia) { const img = el("img"); img.alt = ""; img.src = v.anh_bia; img.addEventListener("load", () => bia.replaceChildren(img), { once: true }); }
    const ten = el("span", "tl-ten-v", v.ten_video || "Video");
    const phu = [TEN_NEN[v.nen_tang] || v.nen_tang, v.da_ap ? "đã trả bản thay logo vào bộ" : v.da_trong_luot ? "đã thay logo trước đó" : ""].filter(Boolean).join(" · ");
    theV.append(cb, bia, ten);
    if (phu) theV.append(el("span", "tl-vb-phu", phu));
    return theV;
  }

  // Mã bộ với phần khớp ô tìm được tô (dựng bằng textContent — mã bộ là dữ liệu, không innerHTML).
  function maToSang(ma) {
    const b = el("b", "tl-vb-ma");
    const i = tim ? ma.toLowerCase().indexOf(tim.toLowerCase()) : -1;
    if (i < 0) { b.textContent = ma; return b; }
    b.append(ma.slice(0, i), el("mark", "", ma.slice(i, i + tim.length)), ma.slice(i + tim.length));
    return b;
  }

  function dongBo(bo) {
    const ds = bo.videos, chonDuoc = ds.filter((v) => !v.da_trong_luot), daChon = chonDuoc.filter((v) => chon.has(v.ban_copy_id)).length;
    const trangThai = !chonDuoc.length || daChon === 0 ? "false" : daChon === chonDuoc.length ? "true" : "mixed";
    const daThay = ds.length - chonDuoc.length;
    const dong = el("div", "tl-vb-nhom" + (trangThai === "true" ? " on" : ""));
    const giua = el("div", "tl-vb-giua");
    const nens = [...new Set(ds.map((v) => TEN_NEN[v.nen_tang] || v.nen_tang).filter(Boolean))].join(", ");
    giua.append(maToSang(bo.ma_bo),
      el("span", "tl-vb-meta", [`vào bộ ${ngayNgan(bo.vao_bo_luc)}`, `${ds.length} video`, nens, daThay ? `${daThay} video đã thay logo trước đó` : ""].filter(Boolean).join(" · ")));
    const dai = el("div", "tl-vb-dai"); dai.setAttribute("aria-hidden", "true");
    for (const v of ds.slice(0, 12)) {
      const o = el("i");
      if (v.anh_bia) { const img = el("img"); img.alt = ""; img.src = v.anh_bia; img.addEventListener("error", () => img.remove(), { once: true }); o.append(img); }
      dai.append(o);
    }
    giua.append(dai);
    // Nút chính: bật/tắt cả bộ. Giữ vai checkbox ba trạng thái (aria-checked) để trình đọc màn hình nói đúng.
    const b = el("button", "tl-vb-chon-ca btn" + (trangThai === "true" ? "" : " primary")); b.type = "button"; b.setAttribute("role", "checkbox");
    b.setAttribute("aria-checked", trangThai); b.disabled = T.tat || !chonDuoc.length;
    b.append(el("span", "tl-vb-hop"), !chonDuoc.length ? "Đã thay hết" : trangThai === "true" ? "Bỏ khỏi giỏ"
      : daThay || trangThai === "mixed" ? `+ Nạp ${chonDuoc.length - daChon} video còn lại` : `+ Nạp cả bộ (${chonDuoc.length})`);
    b.addEventListener("click", () => { const bat = trangThai !== "true"; for (const v of chonDuoc) datChon(v, bo.ma_bo, bat); xong(); });
    const mo = el("button", "tl-vb-mo", moRong.has(bo.folder_id) ? "thu gọn ▴" : "bỏ bớt / xem video ▾"); mo.type = "button";
    mo.setAttribute("aria-expanded", String(moRong.has(bo.folder_id)));
    mo.addEventListener("click", () => { moRong.has(bo.folder_id) ? moRong.delete(bo.folder_id) : moRong.add(bo.folder_id); ve(hopVe); });
    const phai = el("div", "tl-vb-phai");
    phai.append(b, el("span", "tl-vb-dem", daChon ? `đã nạp ${daChon}/${chonDuoc.length}` : ""), mo);
    dong.append(el("span", "tl-vb-dau", trangThai === "true" ? "✓" : ""), giua, phai);
    const khoi = el("div", "tl-vb-khoi"); khoi.append(dong);
    if (moRong.has(bo.folder_id)) {
      const luoi = el("div", "tl-luoi tl-vb-luoi");
      for (const v of ds) luoi.append(theVideo(v, bo.ma_bo));
      khoi.append(luoi);
    }
    return khoi;
  }

  function veTimKiem(hop) {
    const hang = el("div", "tl-vb-tim");
    const o = el("input"); o.type = "search"; o.id = "tl-vb-tim"; o.placeholder = "Gõ mã bộ, vd N.1510 hoặc 1510…"; o.value = tim;
    o.setAttribute("aria-label", "Tìm bộ theo mã"); o.autocomplete = "off"; o.maxLength = 80;  // máy chủ nhận q tối đa 80 ký tự (422 nếu dài hơn)
    o.addEventListener("input", () => { tim = o.value.trim(); clearTimeout(henTim); henTim = setTimeout(() => taiDuLieu(true), 300); });
    hang.append(o);
    for (const [k, ten] of NGAY) {
      const c = el("button", "tl-chip-loc", ten); c.type = "button"; c.dataset.ngay = k; c.setAttribute("aria-pressed", String(!ngayChon && ngay === k));
      c.addEventListener("click", () => { ngay = k; ngayChon = ""; taiDuLieu(true); });
      hang.append(c);
    }
    const lich = el("input", "tl-vb-lich"); lich.type = "date"; lich.value = ngayChon; lich.setAttribute("aria-label", "Chọn ngày vào bộ");
    lich.addEventListener("change", () => { ngayChon = lich.value; taiDuLieu(true); });
    hang.append(lich);
    hop.append(hang);
    return o;
  }

  function moTaKetQua() {
    const ngayChu = ngayChon ? `vào bộ ngày ${ngayNgan(ngayChon + "T12:00:00")}` : ngay === "hom_nay" ? "vào bộ hôm nay"
      : ngay === "7_ngay" ? "vào bộ trong 7 ngày qua" : "mọi ngày";
    return `${data.length} bộ${tim ? ` khớp “${tim}”` : ""} · ${ngayChu} · mới nhất trên cùng`;
  }

  function ve(hop) {
    hopVe = hop; dongBoChon();
    const dangGo = document.activeElement && document.activeElement.id === "tl-vb-tim";
    hop.replaceChildren();
    const o = veTimKiem(hop);
    if (dangGo) { o.focus(); o.setSelectionRange(o.value.length, o.value.length); }  // vẽ lại khi kết quả về không cướp con trỏ đang gõ
    hop.append(el("p", "tl-vb-ghi", "Máy dùng bản trong bộ. Bạn bấm Đạt xong, bản thay logo được trả lại đúng bộ đó."));
    if (data === null) { hop.append(el("p", "muted", loi ? "Chưa tìm được — kiểm tra mạng hoặc thử lại sau ít phút." : "Đang tìm…")); taiDuLieu(); return; }
    hop.append(el("p", "tl-vb-ket-qua", moTaKetQua()));
    if (biCat) hop.append(el("p", "tl-vb-ghi", "Danh sách dài nên chỉ hiện các bộ mới nhất — gõ mã bộ để tìm bộ cũ hơn."));
    if (!data.length) {
      hop.append(el("p", "muted", tim || ngay || ngayChon ? "Không có bộ nào khớp — thử mã khác hoặc chọn “Tất cả” ngày." : "Bạn chưa có video nào trong bộ tự tìm."));
    } else {
      const ds = el("div", "tl-vb-ds");
      for (const bo of data) ds.append(dongBo(bo));
      hop.append(ds);
    }
    taiDuLieu();  // mỗi lần MỞ tab tải lại một lần (cờ "đã thay logo trước đó" phải mới sau khi vừa tạo lượt); `daHoi` chặn vòng lặp
  }

  function duong() {
    const q = new URLSearchParams();
    if (tim) q.set("q", tim);
    if (ngayChon) { q.set("tu", ngayChon); q.set("den", ngayChon); }
    else if (ngay === "hom_nay") q.set("tu", ngayCuc(new Date()));
    else if (ngay === "7_ngay") q.set("tu", ngayCuc(new Date(Date.now() - 6 * 86400000)));
    const s = q.toString();
    return "/api/thay-logo/da-vao-bo" + (s ? "?" + s : "");
  }

  // Mỗi lần mở tab tải lại một lần (nền): cờ "đã trong lượt" luôn mới. Đổi ô tìm/ngày (`ep`) ⇒ tải lại ngay; phản hồi của lần tìm CŨ
  // bị bỏ (số thế hệ `the`) để gõ nhanh "15" rồi "1510" không bị kết quả "15" về muộn đè lên.
  let daHoi = false;
  async function taiDuLieu(ep) {
    if (!ep && (dangTai || daHoi)) return;
    const theNay = ++the;
    dangTai = daHoi = true;
    try {
      const r = await T.goi(duong());
      if (!r.ok) throw new Error("http");
      const j = await r.json();
      if (theNay !== the) return;
      data = j.bo || []; biCat = !!j.bi_cat; loi = false;
    } catch (e) {
      // Lần tìm này trượt (mạng / máy chủ): KHÔNG để kết quả của lần tìm TRƯỚC nằm dưới chữ tìm mới — bỏ dữ liệu cũ, báo lỗi.
      if (theNay === the) { data = null; loi = true; }
    }
    finally {
      if (theNay === the) {
        dangTai = false;
        if (hopVe && !hopVe.hidden) { dongBoChon(); daHoi = true; ve(hopVe); }
      }
    }
  }

  window.TL_TAB_NGUON = window.TL_TAB_NGUON || [];
  window.TL_TAB_NGUON.push({
    id: "bo",
    giai: "Tìm bộ theo mã hoặc ngày rồi bấm “Nạp cả bộ”. Thay xong, bạn bấm Đạt thì video được trả lại đúng bộ đó.",
    ve(hop) { daHoi = false; ve(hop); },
    dem() { dongBoChon(); return chon.size; },  // số trên nhãn tab = số video đã chọn từ tab này
    // Giỏ: mỗi mã bộ một dòng (số video đã nạp).
    gio() { dongBoChon(); const n = new Map(); for (const c of chon.values()) n.set(c.ma_bo, (n.get(c.ma_bo) || 0) + 1); return [...n].map(([ma, so]) => ({ ma, so })); },
  });

  // POST tạo lượt bị từ chối vì video đã đổi/đã nằm trong lượt khác ⇒ bỏ dữ liệu cũ, tải lại khi tab mở.
  document.addEventListener("tl-tao-luot-loi", (e) => {
    if (!e.detail || !e.detail.coVaoBo || ![400, 409].includes(e.detail.status)) return;
    for (const id of chon.keys()) T.nhapChon.delete(id);  // lựa chọn cũ không còn đáng tin: chọn lại từ danh sách mới
    chon.clear(); T.capNhatChan();
    data = null; daHoi = false;
    if (hopVe && !hopVe.hidden) ve(hopVe);
  });

  // Hook thân POST tạo lượt (TL_THAN_POST): id bản-trong-bộ rời `drive_file_ids` sang `vao_bo`.
  window.TL_THAN_POST = window.TL_THAN_POST || [];
  window.TL_THAN_POST.push((than) => {
    dongBoChon();
    const vb = [], ids = [];
    for (const id of than.drive_file_ids || []) { const c = chon.get(id); if (c) vb.push({ video_id: c.video_id, ban_copy_id: id }); else ids.push(id); }
    if (vb.length) { than.drive_file_ids = ids; than.vao_bo = [...(than.vao_bo || []), ...vb]; }  // nối thêm, không ghi đè phần module khác đã thêm
  });
})();
