// Màn Lô (pha 1b bước 2): video của MỘT lượt xếp theo việc cần người, dải màu theo `/dai`, ảnh soi nhanh theo `/soi`.
// Chạy song song trang cũ thay-logo.html (không đụng trang đó). Chữ dữ liệu vào bằng textContent qua T.el, không innerHTML.
// Màn Sửa là bước sau ⇒ nút sang Sửa hiện đúng như mock nhưng MỜ, kèm chú thích (ĐP chốt 23/10, phương án c).
(() => {
  "use strict";
  const T = window.TL, { $, el, goi } = T;

  // Theme: cùng khoá + cùng hành vi với trang cũ (thay-logo.js:7-14) — trang cũ phải giữ nguyên nên chép, không dời.
  const THEME_KEY = "videodl-theme";
  const apTheme = (t) => (t === "light" || t === "dark") ? document.documentElement.setAttribute("data-theme", t)
                                                        : document.documentElement.removeAttribute("data-theme");
  try { apTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* không có storage: theo hệ thống */ }
  $("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const moi = cur === "dark" ? "light" : "dark";
    apTheme(moi);
    try { localStorage.setItem(THEME_KEY, moi); } catch (_) { /* bỏ qua */ }
  });

  const SONG_SONG = 4;               // số request /dai, /soi cùng lúc — máy chủ chỉ có 2 khe ffmpeg, đừng dồn
  const DOAN_TOI_THIEU_PX = 3;       // đoạn 1 khung vẫn phải thấy trên dải (mock: chỗ vàng 1 khung)
  const CHU_SUA = "Màn Sửa có ở bước sau — hiện chỉ xem được dải và ảnh soi.";
  const api = (vid, duoi) => `/api/thay-logo/videos/${encodeURIComponent(vid)}/${duoi}`;

  async function json(path, opts) {
    const r = await goi(path, opts);
    if (!r.ok) throw new Error(`${path} ⇒ ${r.status}`);
    return r.status === 204 ? null : r.json();
  }

  // Chạy `viec` cho từng phần tử, tối đa `n` cái cùng lúc; lỗi của một phần tử không làm hỏng phần còn lại.
  async function chayGioiHan(ds, n, viec) {
    const kq = new Array(ds.length);
    let i = 0;
    const tho = async () => { while (i < ds.length) { const k = i++; try { kq[k] = await viec(ds[k]); } catch (e) { kq[k] = { loi: e }; } } };
    await Promise.all(Array.from({ length: Math.min(n, ds.length) }, tho));
    return kq;
  }

  // Xếp nhóm TẤT ĐỊNH theo trạng thái máy (thiết kế phase-1b-2-man-lo.md):
  //  A xong + có đoạn đỏ/vàng · C xong không đoạn nào · B cho_nguoi + agy thấy box (so_box>0: thấy logo mà chưa bám/chưa chắc)
  //  D cho_nguoi + agy 0 box (máy tin không có logo cũ — agy bỏ sót ảnh thì relay không nộp, relay_may_dev.py:155-157).
  // B/D tách theo so_box, KHÔNG theo số vết: so_box>0 mà 0 vết vẫn là "máy thấy logo" ⇒ phải khoanh.
  function nhom(v, dai) {
    if (v.trang_thai === "xong") {
      if (!dai || dai.loi) return "khac";
      return dai.doan.length ? "A" : "C";
    }
    if (v.trang_thai === "cho_nguoi") {
      if (v.so_box > 0) return v.bo_qua_luc ? "khac" : "B";  // B đã bỏ qua (giữ bản gốc) = người đã xử lý xong
      return "D";  // D giữ trong nhóm kể cả đã xác nhận: dòng đó có nút Hoàn tác
    }
    return "khac";
  }

  function demDoan(dai) {
    const d = { do: 0, vang: 0 };
    for (const x of (dai && !dai.loi ? dai.doan : [])) d[x.loai] += 1;
    return d;
  }

  const giayCua = (dai, khung) => khung / ((dai && dai.fps) || 30);
  const mmss = (giay) => { const s = Math.max(0, Math.round(giay)); return `${Math.floor(s / 60)}′${String(s % 60).padStart(2, "0")}″`; };

  // Dải màu: nền xanh (xong) hoặc xám (cho_nguoi, KHÔNG tô đoạn — /dai còn trả đoạn từ vết dở, handoff mục 5).
  function veDai(v, dai) {
    const d = el("div", "lo-dai " + (v.trang_thai === "xong" ? "lo-dai-xanh" : "lo-dai-xam"));
    d.setAttribute("role", "img");
    if (v.trang_thai !== "xong" || !dai || dai.loi || !dai.so_khung) {
      d.setAttribute("aria-label", v.trang_thai === "xong" ? "chưa đọc được dải" : "máy chưa thay gì");
      return d;
    }
    const n = dai.so_khung;
    for (const x of dai.doan) {
      const s = el("span", `lo-doan lo-doan-${x.loai}`);
      s.style.left = `${(x.tu / n) * 100}%`;
      s.style.width = `max(${DOAN_TOI_THIEU_PX}px, ${((x.den - x.tu + 1) / n) * 100}%)`;
      s.dataset.tu = x.tu; s.dataset.den = x.den;
      s.title = `khung ${x.tu}–${x.den} · ${mmss(giayCua(dai, x.tu))}–${mmss(giayCua(dai, x.den))} · ` +
        (x.loai === "do" ? "đỏ = máy biết còn lộ" : "vàng = máy cảnh báo");
      d.append(s);
    }
    d.setAttribute("aria-label", `${dai.doan.length} đoạn cần xem`);
    return d;
  }

  function nutSua(chu) {
    const b = el("button", "lo-nut lo-nut-chinh", chu);
    b.type = "button"; b.disabled = true; b.title = CHU_SUA;
    return b;
  }

  function bia(v) {
    const b = el("div", "lo-bia");
    if (v.anh_bia) { const i = el("img"); i.src = v.anh_bia; i.alt = ""; i.loading = "lazy"; b.append(i); }
    return b;
  }

  function dongVideo(v, dai, moTa, nut) {
    const r = el("article", "lo-dong");
    r.dataset.vid = v.id;
    const giua = el("div", "lo-giua");
    const tieuDe = el("p", "lo-ten");
    tieuDe.append(el("strong", "", T.tenVideo(v)));
    if (dai && !dai.loi && dai.so_khung) tieuDe.append(el("span", "lo-phu", ` ${mmss(dai.so_khung / (dai.fps || 30))}`));
    if (moTa) tieuDe.append(el("span", "lo-phu", ` · ${moTa}`));
    giua.append(tieuDe, veDai(v, dai));
    r.append(bia(v), giua, nut);
    return r;
  }

  // Lưới ảnh soi của một nhóm: chỉ gọi /soi khi người BẤM mở (ĐK4: không tải 3×N ảnh lúc vào trang).
  async function moLuoi(hop, ds, nutCuaVideo) {
    hop.replaceChildren(el("p", "lo-phu", `Đang lấy ảnh soi của ${ds.length} video…`));
    const kq = await chayGioiHan(ds, SONG_SONG, (x) => json(api(x.v.id, "soi")));
    hop.replaceChildren();
    ds.forEach((x, k) => {
      const o = el("div", "lo-soi-video");
      o.dataset.vid = x.v.id;
      o.append(el("p", "lo-ten", T.tenVideo(x.v)));
      const s = kq[k];
      const hang = el("div", "lo-soi-hang");
      if (!s || s.loi || !s.co) {
        hang.append(el("p", "lo-phu", "Chưa có ảnh soi cho video này (video đã dọn khỏi máy hoặc máy chưa dựng được)."));
      } else {
        for (const a of s.anh) {
          const i = el("img", "lo-soi-anh");
          i.src = api(x.v.id, `soi/${a.i}`); i.loading = "lazy";
          i.alt = `khung ${a.khung}`; i.title = `khung ${a.khung} · ${mmss(giayCua(x.dai, a.khung))}`;
          hang.append(i);
        }
      }
      o.append(hang);
      if (nutCuaVideo) o.append(nutCuaVideo(x.v));
      hop.append(o);
    });
  }

  function nhomGop(lop, tieuDe, moTa, chuNut, ds, nutCuaVideo) {
    const w = el("section", `lo-nhom ${lop}`);
    const r = el("article", "lo-dong lo-dong-gop");
    const giua = el("div", "lo-giua");
    const p = el("p", "lo-ten"); p.append(el("strong", "", tieuDe));
    giua.append(p, el("div", `lo-dai ${lop === "lo-nhom-C" ? "lo-dai-xanh" : "lo-dai-xam"}`), el("p", "lo-phu", moTa));
    const nut = el("button", "lo-nut", chuNut); nut.type = "button";
    const o = el("div", "lo-luoi"); o.hidden = true;
    nut.addEventListener("click", async () => {
      o.hidden = !o.hidden;
      if (!o.hidden && !o.dataset.da) { o.dataset.da = "1"; await moLuoi(o, ds, nutCuaVideo); }
    });
    const so = el("div", "lo-bia lo-bia-so", `${ds.length}\nvideo`);
    r.append(so, giua, nut);
    w.append(r, o);
    return w;
  }

  // Nhóm D: người xác nhận từng video — "Đúng là không có logo" = bỏ qua (giữ bản gốc, hoàn tác được); "Có logo" ⇒ màn Sửa (bước sau).
  function nutXacNhan(v) {
    const o = el("div", "lo-xac-nhan");
    const ve = () => {
      o.replaceChildren();
      if (v.bo_qua_luc) {
        o.append(el("span", "lo-phu", "Đã xác nhận không có logo — giữ bản gốc."));
        const h = el("button", "lo-nut", "Hoàn tác"); h.type = "button";
        h.addEventListener("click", () => doi(h, "bo-qua/hoan-tac", null));
        o.append(h);
      } else {
        const k = el("button", "lo-nut", "Đúng là không có logo"); k.type = "button";
        k.addEventListener("click", () => doi(k, "bo-qua", Date.now() / 1000));
        o.append(k, nutSua("Có logo"));
      }
    };
    async function doi(nut, duoi, luc) {
      nut.disabled = true;
      try { await json(api(v.id, duoi), { method: "POST" }); v.bo_qua_luc = luc; ve(); veTomTat(); }
      catch (e) { nut.disabled = false; baoLoi("Không lưu được xác nhận, thử lại."); }
    }
    ve();
    return o;
  }

  let LUOT = { videos: [], dai: new Map() };

  function baoLoi(chu) { const e = $("lo-loi"); e.textContent = chu || ""; e.hidden = !chu; }

  function veTomTat() {
    const { videos, dai } = LUOT, dem = { A: 0, B: 0, C: 0, D: 0, khac: 0 };
    let cho = 0;
    for (const v of videos) {
      const g = nhom(v, dai.get(v.id)); dem[g] += 1;
      if (g === "A") { const d = demDoan(dai.get(v.id)); cho += d.do + d.vang; }
    }
    const conLam = videos.filter((v) => ["cho", "cho_agy", "dang_chay"].includes(v.trang_thai)).length;
    const loi = videos.filter((v) => v.trang_thai === "loi").length;
    const dChua = videos.filter((v) => nhom(v, dai.get(v.id)) === "D" && !v.bo_qua_luc).length;
    const p = $("lo-tom-tat");
    p.replaceChildren(`${videos.length} video · máy xong ${videos.length - conLam - loi}/${videos.length} · `);
    p.append(el("strong", "", `cần bạn: ${dem.A + dem.B} video, ${cho} chỗ`),
      ` · ${dem.C} video máy chắc · ${dChua} video máy cho là không có logo cũ chưa xác nhận`);
    if (conLam || loi) p.append(` · máy còn làm ${conLam} · lỗi ${loi}`);
  }

  function veDanhSach() {
    const { videos, dai } = LUOT, hop = $("lo-danh-sach"), theo = { A: [], B: [], C: [], D: [] };
    for (const v of videos) { const g = nhom(v, dai.get(v.id)); if (theo[g]) theo[g].push({ v, dai: dai.get(v.id) }); }
    hop.replaceChildren();
    // A: nhiều chỗ trước; cùng số chỗ thì video mới trước (id lớn) — thứ tự ổn định giữa các lần tải.
    theo.A.sort((a, b) => { const x = demDoan(a.dai), y = demDoan(b.dai); return (y.do + y.vang) - (x.do + x.vang) || b.v.id - a.v.id; });
    for (const { v, dai: d } of theo.A) {
      const c = demDoan(d), n = c.do + c.vang;
      const moTa = [c.vang && `${c.vang} chỗ vàng`, c.do && `${c.do} chỗ đỏ`].filter(Boolean).join(" · ");
      hop.append(dongVideo(v, d, moTa, nutSua(`Xem ${n} chỗ`)));
    }
    for (const { v, dai: d } of theo.B) hop.append(dongVideo(v, d, T.lyDoDeHieu(v.ly_do_may), nutSua("Khoanh logo")));
    if (theo.C.length) hop.append(nhomGop("lo-nhom-C", `${theo.C.length} video máy chắc`,
      "Mỗi video có 3 ảnh phóng to vùng logo (đầu · giữa · cuối) — lướt cả nhóm bằng mắt trong 1 màn.",
      `Soi nhanh ${theo.C.length} video`, theo.C, null));
    if (theo.D.length) hop.append(nhomGop("lo-nhom-D", `${theo.D.length} video máy cho là không có logo cũ`,
      "Máy có thể bỏ sót logo mờ (đã gặp: chữ \"CO\" mờ trôi). Mỗi video 3 ảnh để bạn xác nhận.",
      `Xác nhận ${theo.D.length} video`, theo.D, nutXacNhan));
    if (!videos.length) hop.append(el("p", "lo-phu", "Lô này chưa có video."));
    veTomTat();
  }

  async function taiLuot(jobId) {
    baoLoi("");
    $("lo-danh-sach").replaceChildren(el("p", "lo-phu", "Đang tải…"));
    try {
      const d = await json(`/api/thay-logo/videos?job_id=${encodeURIComponent(jobId)}`);
      const videos = d.videos;
      const can = videos.filter((v) => v.trang_thai === "xong" || v.trang_thai === "cho_nguoi");
      const kq = await chayGioiHan(can, SONG_SONG, (v) => json(api(v.id, "dai")));
      LUOT = { videos, dai: new Map(can.map((v, k) => [v.id, kq[k]])) };
      veDanhSach();
    } catch (e) {
      if (e.message !== "het_phien") baoLoi("Không tải được lô này.");
    }
  }

  async function batDau() {
    let bo;
    try { bo = (await json("/api/thay-logo/bo")).bo; } catch (e) { if (e.message !== "het_phien") baoLoi("Không tải được danh sách lô."); return; }
    const chon = $("lo-chon-lo");
    for (const b of bo) { const o = el("option", "", `${b.ten_bo} · ${b.tong} video`); o.value = b.job_id; chon.append(o); }
    if (!bo.length) { $("lo-danh-sach").replaceChildren(el("p", "lo-phu", "Bạn chưa có lô nào.")); return; }
    const muon = new URLSearchParams(location.search).get("lo");
    chon.value = bo.some((b) => String(b.job_id) === muon) ? muon : String(bo[0].job_id);
    chon.addEventListener("change", () => {
      const u = new URL(location.href); u.searchParams.set("lo", chon.value); history.replaceState(null, "", u);
      taiLuot(chon.value);
    });
    await taiLuot(chon.value);
  }

  window.TL_LO = { nhom, demDoan };  // cho test đọc phân nhóm trực tiếp
  batDau();
})();
