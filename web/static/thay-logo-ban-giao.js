// "Tạo bộ tự tìm" từ video ĐẠT của một lượt thay logo: mở tab Creative Desk và bàn giao bằng postMessage — CÙNG giao thức với nút
// "Tạo bộ tự tìm" ở trang Tải video (`web/static/app.js` `moBoTuTim`/`guiBanGiaoPm`, `type: "videodesk-handoff", v: 2`). Không tách hàm
// ra khỏi app.js để dùng chung: các harness `tests/js/*.js` trích hàm THẲNG từ app.js theo tên, dời đi là vỡ chúng.
// Khác trang Tải video ở 2 chỗ: `f` = file ĐÃ thay logo (`drive_file_id_ra`), không phải file gốc; `u` = link gốc nếu video thuộc thư
// viện, không thì link Drive của file ra (bên nhận chỉ đòi URL http(s) — `videodesk-handoff.ts` + `LinkSourceItemIn`, đo 16/10).
(() => {
  "use strict";
  const T = window.TL;
  const CREATIVE_DESK_URL = "https://automation.nobidigital.asia";
  const CREATIVE_DESK_ORIGIN = new URL(CREATIVE_DESK_URL).origin;
  const MAX_PM_ITEMS = 500, PM_CHU_KY_MS = 500, PM_HAN_MS = 30000;
  const ID_DRIVE = /^[A-Za-z0-9_-]{10,128}$/;

  // Item theo luật bên nhận (`parseVideodeskHandoffItem`): sai một item thì bên nhận bỏ CẢ LÔ, không ack ⇒ lọc trước ở đây.
  function item(v) {
    const f = v.drive_file_id_ra;
    if (typeof f !== "string" || !ID_DRIVE.test(f)) return null;
    const u = typeof v.url === "string" && /^https?:\/\//i.test(v.url) ? v.url : `https://drive.google.com/file/d/${encodeURIComponent(f)}/view`;
    return { f, n: T.tenVideo(v), u };
  }

  // Đọc ĐỦ video của lượt (không dựa vào danh sách đang hiện — có thể đang lọc/phân trang). Trả [] khi lỗi.
  async function videoDatCua(jobId) {
    let ds = [], truoc = null;
    for (let i = 0; i < 20; i++) {
      const q = new URLSearchParams({ job_id: String(jobId) }); if (truoc) q.set("truoc_id", String(truoc));
      const r = await T.goi("/api/thay-logo/videos?" + q);
      if (!r.ok) throw new Error("http");
      const d = await r.json(); ds = ds.concat(d.videos || []); truoc = d.truoc_tiep;
      if (!d.con_nua) break;
    }
    return ds.filter((v) => v.trang_thai === "xong" && v.danh_gia === "dat");
  }

  function guiBanGiaoPm(tab, tin) {
    return new Promise((xong) => {
      let hetLuc = null, nhip = null;
      const ket = (r) => { clearInterval(nhip); clearTimeout(hetLuc); window.removeEventListener("message", nghe); xong(r); };
      function nghe(ev) {
        const d = ev.data;
        if (ev.origin !== CREATIVE_DESK_ORIGIN || !d || d.type !== "videodesk-ack" || d.id !== tin.id) return;
        ket(d.ok === true ? { ket: "ack" } : { ket: "tu_choi", lyDo: typeof d.reason === "string" ? d.reason : "" });
      }
      const gui = () => {
        if (tab.closed) { ket({ ket: "tab_dong" }); return; }
        try { tab.postMessage(tin, CREATIVE_DESK_ORIGIN); } catch (e) { /* tab đang chuyển trang — lượt sau gửi lại */ }
      };
      window.addEventListener("message", nghe);
      hetLuc = setTimeout(() => ket({ ket: "het_han" }), PM_HAN_MS);
      nhip = setInterval(gui, PM_CHU_KY_MS);
      gui();
    });
  }

  // Trả câu kết quả cho người dùng (luôn là lời thường). Tab mở NGAY trong cú bấm (trình duyệt chặn popup mở sau `await`).
  T.taoBoTuTim = async function taoBoTuTim(jobId) {
    const id = crypto.randomUUID();
    const tab = window.open(`${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk_pm=1`, "_blank");
    if (!tab) return "Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại.";
    try { tab.opener = null; } catch (e) { console.warn("Không cắt được window.opener của tab Creative Desk — tab vẫn mở, opener CÒN nguyên:", e); }
    let ds;
    try { ds = await videoDatCua(jobId); } catch (e) { tab.close(); return "Chưa đọc được danh sách video — thử lại sau ít phút."; }
    const items = ds.map(item).filter(Boolean).slice(0, MAX_PM_ITEMS);
    if (!items.length) { tab.close(); return "Lượt này chưa có video Đạt nào có file thành phẩm."; }
    const kq = await guiBanGiaoPm(tab, { type: "videodesk-handoff", v: 2, id, items });
    return {
      ack: `Đã gửi ${items.length} video sang Creative Desk — chọn usecase/insight/template và bấm tạo bộ ở tab đó.`,
      tu_choi: `Creative Desk không nhận được danh sách${kq.lyDo ? ` (${kq.lyDo})` : ""}.`,
      het_han: "Creative Desk chưa xác nhận sau 30 giây. Nếu tab đó bắt đăng nhập: đăng nhập xong, đóng tab rồi bấm lại.",
      tab_dong: "Tab Creative Desk đã đóng trước khi nhận — bấm lại để mở tab mới.",
    }[kq.ket];
  };
})();
