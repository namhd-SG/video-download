// Thẻ "Cookie Instagram" ở trang Cài đặt (R-08). Cố ý tách khỏi `settings.js`: thẻ TikTok gắn chặt với id `ck-*`,
// còn thẻ này chỉ có ba việc — đọc trạng thái, dán (PUT), xoá (DELETE) — qua `/me/cookie/instagram`.
// Không bao giờ hiện nội dung cookie: chỉ mã trạng thái + hạn + vân tay do máy chủ trả.
(() => {
  "use strict";
  const MA = window.MA_COOKIE_TRANG_THAI || {};
  const URL_IG = "/me/cookie/instagram";
  const $ = (id) => document.getElementById(id);
  const ngay = (iso) => new Date(iso).toLocaleDateString("vi-VN");
  const gio = (iso) => new Date(iso).toLocaleString("vi-VN");

  async function goi(method, body) {
    const res = await fetch(URL_IG, {
      method, redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0) {
      const el = $("session-expired");
      if (el) el.hidden = false;
      throw new Error("phien_het_han");
    }
    if (!res.ok) {
      let ma = null;
      try { ma = (await res.json()).detail; } catch (e) { ma = null; }
      const err = new Error(`${method} ${URL_IG} -> ${res.status}`);
      err.ma = ma;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  // [lớp màu, biểu tượng, tiêu đề, một câu]. `ig_mat_phien` = jar còn hạn nhưng job IG gần nhất đã bị IG đá ra ⇒ ĐỎ.
  function khoi(tt) {
    if (!tt.co_jar) {
      return ["tt-trong", "–", "Chưa có cookie Instagram",
              "Job Instagram hàng loạt (profile, từ khoá, hashtag, audio) cần cookie của tài khoản phụ."];
    }
    if (tt.trang_thai === "dung_duoc") {
      return ["tt-ok", "✓", "Đang dùng được", "Job Instagram của bạn chạy bằng cookie này."];
    }
    if (tt.trang_thai === "ig_mat_phien") {
      return ["tt-loi", "!", "Cookie IG hết hạn / bị IG chặn",
              "Job Instagram gần nhất bị dừng vì mất phiên. Đăng nhập lại tài khoản phụ, xuất và dán cookie mới."];
    }
    if (tt.trang_thai === "cookie_het_han") {
      return ["tt-loi", "!", tt.het_han ? `Cookie đã hết hạn ngày ${ngay(tt.het_han)}` : "Cookie đã hết hạn",
              "Job Instagram sẽ dừng cho tới khi bạn dán cookie mới."];
    }
    return ["tt-loi", "!", "Cookie đang lưu không dùng được", MA[tt.trang_thai] || tt.trang_thai];
  }

  function ve(tt) {
    const [lop, icon, tieuDe, cau] = khoi(tt);
    $("ig-tt").className = "tt " + lop;
    $("ig-tt-icon").textContent = icon;
    $("ig-tt-tieu-de").textContent = tieuDe;
    $("ig-tt-cau").textContent = cau;
    $("ig-han").textContent = tt.het_han ? ngay(tt.het_han) : (tt.co_jar ? "Phiên không ghi hạn" : "—");
    $("ig-luc").textContent = tt.cap_nhat_luc ? gio(tt.cap_nhat_luc) : "—";
    $("ig-van-tay").textContent = tt.van_tay || "—";
    $("ig-cookie-xoa").hidden = !tt.co_jar;
  }

  function bao(tieuDe, chiTiet) {
    const el = $("ig-cookie-error");
    el.textContent = "";
    if (!tieuDe) { el.hidden = true; return; }
    const b = document.createElement("b");
    b.textContent = tieuDe;
    el.append(b, document.createTextNode(chiTiet || ""));
    el.hidden = false;
  }

  async function tai() {
    try {
      ve(await goi("GET"));
    } catch (err) {
      $("ig-tt").className = "tt tt-loi";
      $("ig-tt-tieu-de").textContent = "Không đọc được trạng thái cookie Instagram";
      $("ig-tt-cau").textContent = "Tải lại trang; vẫn lỗi thì báo người phát triển.";
    }
  }

  $("ig-cookie-luu").addEventListener("click", async () => {
    const o = $("ig-cookie-json");
    if (!o.value.trim()) { bao("Chưa dán gì.", " Dán chuỗi JSON xuất từ Cookie-Editor."); return; }
    try {
      ve(await goi("PUT", { json: o.value }));
      o.value = "";
      bao(null);
    } catch (err) {
      // Bị từ chối ⇒ cookie cũ vẫn giữ nguyên; chỉ MÃ lỗi được hiện.
      bao("Cookie bị từ chối.", " " + (MA[err.ma] || err.ma || "Lỗi không rõ.") + " Cookie cũ (nếu có) vẫn đang dùng.");
    }
  });

  $("ig-cookie-xoa").addEventListener("click", async () => {
    if (!window.confirm("Xoá cookie Instagram? Job Instagram sẽ dừng cho tới khi bạn dán lại.")) return;
    try { await goi("DELETE"); await tai(); } catch (err) { bao("Không xoá được.", ""); }
  });

  tai();
})();
