// Dải "Bộ của bạn" (đọc /api/thay-logo/bo) + bộ lọc Bộ / Nền tảng / Ngày / Trạng thái. Bộ, nền tảng, ngày lọc ở máy chủ (T.datLoc); trạng thái lọc ở trang.
// Bộ nguồn "Đã vào bộ" đã duyệt xong + đang được chọn ⇒ thẻ mở rộng bên dưới dải với nút "Áp N video Đạt vào bộ" / "Hoàn tác" / tiến độ
// (đọc GET /api/thay-logo/bo/{id}/ap; máy chủ tắt cờ ⇒ 404 ⇒ không có nút).
(() => {
  "use strict";
  const T = window.TL, { $, el } = T;
  const TT = [["dang_xu_ly", "Đang xử lý"], ["cho_duyet", "Chờ duyệt"], ["khong_chac", "Máy không chắc"], ["loi", "Lỗi"], ["da_dat", "Đã đạt"], ["hong", "Hỏng"]];
  const NEN = [["", "Tất cả"], ["tiktok", "TikTok"], ["douyin", "Douyin"], ["facebook", "Facebook"]];
  const NGAY = [["", "Tất cả"], ["hom_nay", "Hôm nay"], ["7_ngay", "7 ngày"]];
  const NGUON = { drive: "Thư viện", may: "Tải từ máy", link: "Link Drive", vao_bo: "Đã vào bộ", nhieu: "Nhiều nguồn" };

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
    const ap = apCua[b.job_id];
    if (cls === "xong" && ap && ap.trang_thai === "xong") nut.append(el("span", "tl-bo-tiep ok", `✓ Đã áp vào bộ ${gio(ap.xong_luc)}`));
    else if (cls === "xong" && ap && ap.la_chu && ap.so_du_dieu_kien) nut.append(el("span", "tl-bo-tiep", "Việc còn lại: áp vào bộ →"));
    nut.addEventListener("click", () => T.datLoc("job", T.loc.job === b.job_id ? null : b.job_id));
    the.append(nut);
    if (b.thu_muc_ra_id && T.IDRE.test(b.thu_muc_ra_id)) {
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

  // ------------------------------------------------------------------ thẻ mở rộng: áp vào bộ / hoàn tác (đợt 2A)
  const apCua = {};  // job_id ⇒ phản hồi GET …/ap gần nhất; null = máy chủ tắt tính năng (404)
  const apThu = {};  // job_id ⇒ lúc bắt đầu lần tải gần nhất (chặn vòng tải dồn dập khi máy chủ lỗi tạm)
  let apDangTai = null, apHen = null, apLoi = "";
  const gio = (giay) => { if (!giay) return ""; const d = new Date(giay * 1000), z = (n) => String(n).padStart(2, "0"); return `lúc ${z(d.getHours())}:${z(d.getMinutes())}`; };
  const boMo = () => { const b = T.bo.find((x) => x.job_id === T.loc.job); return b && b.nguon_kieu === "vao_bo" && trangThaiBo(b)[1] === "xong" ? b : null; };

  async function taiAp(jid) {
    if (apDangTai === jid) return;
    apDangTai = jid; apThu[jid] = Date.now();
    try {
      const r = await T.goi(`/api/thay-logo/bo/${jid}/ap`);
      if (r.ok) apCua[jid] = { ...(await r.json()), _luc: Date.now() };
      else if (r.status === 404) apCua[jid] = null;
      else if (!apCua[jid]) delete apCua[jid];  // lỗi tạm ở lần ĐẦU: không dựng khoá rỗng (thẻ sẽ kẹt), thử lại sau
    } catch (_) { if (!apCua[jid]) delete apCua[jid]; } finally { apDangTai = null; }  // mạng chập: giữ dữ liệu cũ nếu có
    clearTimeout(apHen);
    const chua = !(jid in apCua), chay = apCua[jid] && apCua[jid].trang_thai === "chay";
    if ((chua || chay) && T.loc.job === jid) apHen = setTimeout(() => taiAp(jid), 2000);
    veBo(); veMo();
  }

  async function bam(jid, duong) {
    apLoi = "";
    try {
      const r = await T.goi(`/api/thay-logo/bo/${jid}/${duong}`, { method: "POST" });
      if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (_) { /* thân không phải JSON */ } apLoi = typeof d === "string" && d ? d : `Máy chủ từ chối (${r.status}).`; }
      else if (apCua[jid]) apCua[jid].trang_thai = "chay";
    } catch (e) { if (e && e.message !== "het_phien") apLoi = "Không gửi được — kiểm tra mạng rồi thử lại."; }
    veMo(); taiAp(jid);
  }

  const duong = (chu) => el("span", "tl-bx-duong", chu);
  const nho = (...con) => { const p = el("p", "tl-bx-nho"); p.append(...con); return p; };
  const CAU_META = "Hoàn tác KHÔNG lùi camp đã lên Meta.";

  function hanhDong(b, ap) {
    const hop = el("div", "tl-bx-act"), maBo = ap.ma_bo || b.ten_bo, thuMuc = `Thay logo - bản gốc/${maBo}`;
    const nutLink = (chu, f) => { const n = el("button", "tl-bx-link", chu); n.type = "button"; n.addEventListener("click", f); return n; };
    if (!ap.la_chu) {  // quản trị xem bộ người khác: CHỈ ĐỌC
      hop.append(nho(ap.trang_thai === "xong" ? `Chủ lượt đã áp ${ap.so_da_ap} video ${gio(ap.xong_luc)}.`
                                              : "Chỉ người vừa tạo lượt vừa là chủ video mới áp được vào bộ."));
    } else if (ap.trang_thai === "chay") {
      hop.append(el("div", "tl-bx-chay", `Đang chạy… còn ${ap.so_dang_lam} video — có thể rời trang, máy vẫn làm tiếp.`));
    } else if (ap.trang_thai === "xong") {
      const o = el("div", "tl-bx-da-ap"); o.setAttribute("role", "status");
      o.append(`✓ Đã áp ${ap.so_da_ap} video vào bộ ${gio(ap.xong_luc)} · `, nutLink("Hoàn tác", () => bam(b.job_id, "hoan-tac")));
      hop.append(o, nho("Bản gốc đang ở ", duong(thuMuc), ". Creative Desk vẫn dùng bản cũ tới lượt đồng bộ."), nho(CAU_META));
      if (ap.so_du_dieu_kien) hop.append(nho(`Còn ${ap.so_du_dieu_kien} video Đạt chưa áp. Bộ đã áp — hoàn tác trước nếu muốn áp lại cả chúng.`));
    } else if (ap.trang_thai === "do_dang" || ap.trang_thai === "loi") {
      const o = el("div", "tl-bx-do-dang"); o.setAttribute("role", "status");
      o.append(ap.trang_thai === "loi" ? "Có video cần quản trị xem (dưới đây). " : "Lượt trước còn dở. ");
      const tiep = el("button", "btn primary", "Tiếp tục"); tiep.type = "button"; tiep.addEventListener("click", () => bam(b.job_id, "ap"));
      const lui = el("button", "btn", "Hoàn tác"); lui.type = "button"; lui.addEventListener("click", () => bam(b.job_id, "hoan-tac"));
      const hang = el("div", "tl-bx-hang-nut"); hang.append(tiep, lui);
      hop.append(o, hang, nho(CAU_META));
    } else if (ap.so_du_dieu_kien) {
      const n = el("button", "btn primary tl-bx-ap", `Áp ${ap.so_du_dieu_kien} video Đạt vào bộ ${maBo}`); n.type = "button";
      n.addEventListener("click", () => { n.disabled = true; bam(b.job_id, "ap"); });
      const chiBan = el("b", "", "Chỉ video của bạn.");
      hop.append(n, nho(chiBan, " Chỉ áp được video Đạt mà bạn vừa là người tạo lượt vừa là chủ video; video khác vẫn ở thư mục đầu ra."),
                 nho("Bản gốc chuyển sang ", duong(thuMuc), " — hoàn tác được. ", CAU_META));
      if (ap.da_hoan_tac) hop.append(nho("Bộ này đã hoàn tác một lần — áp lại dùng bản mới."));
    } else {
      hop.append(nho("Không còn video Đạt nào của bạn để áp vào bộ này."));
    }
    const loiVideo = (ap.tung_video || []).filter((v) => v.loi);
    if (loiVideo.length) {
      const ul = el("ul", "tl-bx-loi");
      for (const v of loiVideo) ul.append(el("li", "", `${v.ten || "#" + v.job_video_id}: ${v.loi}`));
      hop.append(ul);
    }
    if (apLoi) hop.append(el("p", "error-text tl-bx-loi-bam", apLoi));
    if (b.thu_muc_ra_id && T.IDRE.test(b.thu_muc_ra_id)) {
      const a = el("a", "btn tl-bx-thumuc", "↗ Mở thư mục đầu ra");
      a.href = `https://drive.google.com/drive/folders/${encodeURIComponent(b.thu_muc_ra_id)}`; a.target = "_blank"; a.rel = "noopener";
      const hang = el("div", "tl-bx-hang-nut"); hang.append(a); hop.append(hang);
    }
    return hop;
  }

  function veMo() {
    let hop = $("tl-bo-mo");
    if (!hop) { hop = el("div", "tl-bo-mo"); hop.id = "tl-bo-mo"; $("tl-bo-list").after(hop); }
    hop.replaceChildren();
    const b = boMo();
    if (!b) return;
    if (!(b.job_id in apCua)) { if (Date.now() - (apThu[b.job_id] || 0) > 1500) taiAp(b.job_id); return; }
    const ap = apCua[b.job_id];
    if (ap && Date.now() - ap._luc > 14000) taiAp(b.job_id);  // theo nhịp poll của trang: vẽ bản đang có, tải bản mới ở nền
    if (!ap) return;  // null = máy chủ tắt tính năng áp vào bộ
    const the = el("article", "panel tl-bx"); the.setAttribute("aria-label", `Bộ ${b.ten_bo} đã duyệt xong`);
    const dau = el("div", "tl-bx-head");
    dau.append(el("h3", "", b.ten_bo), el("span", "tl-bx-tt", "Xong · đã duyệt hết"), el("span", "tl-bx-grow"),
               el("span", "tl-bx-nguon", `${NGUON.vao_bo} · ${T.ngayGio(b.tao_luc)}`));
    const tom = el("div", "tl-bx-sum");
    const o = (cls, so, chu) => { const d = el("div", cls); d.append(el("b", "", String(so)), chu); return d; };
    const cuaBan = ap.la_chu && ap.so_du_dieu_kien != null ? ap.so_du_dieu_kien + ap.so_da_ap : null;
    tom.append(o("dat", b.dat, "Đạt" + (cuaBan != null && cuaBan !== b.dat ? ` · ${cuaBan} của bạn` : "")), o("hong", b.hong, "Hỏng"),
               o("", b.cho_nguoi, "Máy không chắc"));
    const anh = el("div", "tl-bx-thumbs"); anh.setAttribute("aria-hidden", "true");
    for (const v of T.videos.filter((x) => x.job_id === b.job_id)) {
      const s = el("span"); s.title = T.tenVideo(v);
      if (v.anh_bia) { const i = el("img"); i.alt = ""; i.src = v.anh_bia; s.append(i); }
      const k = v.danh_gia === "dat" ? ["ok", "✓"] : v.danh_gia === "hong" ? ["bad", "✕"] : ["giu", "="];
      s.append(el("em", k[0], k[1])); anh.append(s);
    }
    the.append(dau, tom, anh, hanhDong(b, ap));
    hop.append(the);
  }

  T.ve.bo = () => { veBo(); veLoc(); veMo(); };
  T.locDuoc = () => (T.locTT.size ? T.videos.filter((v) => T.locTT.has(T.nhomCua(v))) : T.videos);
  // Chỉ đổi chữ "độ tươi": vẽ lại cả bộ lọc sẽ đóng ô chọn bộ đang mở.
  setInterval(() => { const e = $("tl-do-tuoi"); if (e) e.textContent = docDoTuoi(); }, 5000);
})();
