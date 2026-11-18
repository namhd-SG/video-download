// Form tạo lượt tải, banner cookie, và INIT (nạp cuối cùng).
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // Thuần, không đụng DOM — tách riêng để `tests/js/` gọi được thẳng bằng
  // node (xem `tao-job-body.js`). Hai ô tuỳ chọn CHỈ vào body khi có nội
  // dung: client cũ (không có hai ô) và người để trống hai ô phải gửi cùng
  // một body — server đọc "vắng trường" và "trường rỗng" khác nhau cho việc
  // khác (xem `_chuan_hoa_truong_tuy_chon` ở web/app.py).
  function taoJobBody(url, soLuong, usecase, insightGoc) {
    const body = { url, so_luong: soLuong };
    if (usecase) body.usecase = usecase;
    if (insightGoc) body.insight_goc = insightGoc;
    return body;
  }

  // MỘT đường tạo lượt cho cả form lẫn nút "Chạy lại": POST /jobs, đưa job mới
  // lên đầu hàng đợi và theo dõi tiến độ. Trả `{ok:true}` hoặc `{ok:false, loi}`
  // — không ném, để nơi gọi tự chọn nói lỗi ở ô lỗi hay ở toast.
  async function guiTaoJob(body) {
    try {
      const res = await fetch("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return { ok: false, loi: errorDetailText(data) };
      const idx = state.jobs.findIndex((j) => j.id === data.id);
      if (idx >= 0) state.jobs[idx] = data; else state.jobs.unshift(data);
      renderQueue();
      followJob(data.id);
      return { ok: true, job: data };
    } catch (err) {
      return { ok: false, loi: "Lỗi mạng: " + err.message };
    }
  }

  // Ctrl/⌘+Enter trong ô nhập nhiều dòng ⇒ gửi form (Enter trần xuống dòng để dán nhiều link).
  function laPhimGuiForm(ev) {
    return !!(ev && (ev.ctrlKey || ev.metaKey) && ev.key === "Enter");
  }
  document.getElementById("url").addEventListener("keydown", (ev) => {
    if (!laPhimGuiForm(ev)) return;
    ev.preventDefault();
    document.getElementById("job-form").requestSubmit();
  });

  document.getElementById("job-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errorBox = document.getElementById("error");
    const submitBtn = ev.target.querySelector("button[type=submit]");
    errorBox.textContent = "";
    const url = document.getElementById("url").value.trim();
    const soLuong = parseInt(document.getElementById("so-luong").value, 10);
    const usecase = document.getElementById("usecase").value.trim();
    const insightGoc = document.getElementById("insight-goc").value.trim();
    submitBtn.disabled = true;
    try {
      const kq = await guiTaoJob(taoJobBody(url, soLuong, usecase, insightGoc));
      if (!kq.ok) {
        errorBox.textContent = kq.loi;
        return;
      }
      document.getElementById("url").value = "";
      document.getElementById("usecase").value = "";
      document.getElementById("insight-goc").value = "";
    } finally {
      submitBtn.disabled = false;
    }
  });

  // ========================================================================
  // BANNER ẨN DANH
  // ========================================================================
  // Trang này KHÔNG còn quản cookie — việc đó ở /settings.html. Thứ còn lại ở
  // đây là một dòng nhắc, vì chỗ người dùng nhận ra mình đang ẩn danh là lúc
  // sắp tạo lượt tải, không phải lúc đi vào trang Cài đặt.
  async function loadBannerCookie() {
    const banner = document.getElementById("cookie-banner");
    if (!banner) return;
    try {
      veTrangThaiCookie(banner, await apiGet("/me/cookie"));
    } catch (err) {
      // Không đọc được thì ẩn hẳn: thà không nói gì còn hơn nói sai rằng người
      // đã dán cookie là đang ẩn danh.
      banner.hidden = true;
      throw err;
    }
  }

  // BA trạng thái, không phải hai.
  //
  // Bản cũ là một dòng: `banner.hidden = tt.co_jar`. Nó coi "có tệp jar" là
  // "cookie dùng được — không cần nói gì", nhưng `/me/cookie` trả `co_jar:true`
  // cho CẢ jar hết hạn, jar rỗng và jar chưa đăng nhập. Hậu quả đo được: cookie
  // hết hạn thì trang chính trông **y hệt** lúc cookie khoẻ, và tín hiệu duy
  // nhất người dùng có là một sự VẮNG MẶT — thứ không phân biệt được với "trang
  // này vốn không nói gì về cookie". Đúng nguyên văn lời người dùng: *"nhìn vô
  // không biết là có cookie chưa"*.
  //
  // Nên trạng thái khoẻ cũng phải nói ra — nhưng bằng MỘT CHIP, không phải một
  // dải chữ: chỗ này người dùng đi qua mỗi lần tạo lượt tải, và một khối cảnh
  // báo cho tin tốt là tiếng ồn.
  function veTrangThaiCookie(banner, tt) {
    banner.hidden = false;
    const ghiChu = (chu) => `<span class="ti" tabindex="0" role="note" title="${escapeHtml(chu)}" aria-label="${escapeHtml(chu)}">ⓘ</span>`;
    if (!tt.co_jar) {
      banner.className = "hero-ck chip warn";
      banner.innerHTML = '<a href="/settings.html">Đang ẩn danh · dán cookie</a>' +
        ghiChu("Chưa có cookie — lượt tải của bạn chạy ẩn danh và chia chung hạn mức với mọi người chưa dán. Dán ở Cài đặt để có hạn mức riêng.");
      return;
    }
    if (tt.trang_thai !== "dung_duoc") {
      // Câu chữ lấy từ bảng dùng chung với trang Cài đặt — hai trang nói cùng
      // một câu về cùng một tệp, nếu không người dùng phải tự ghép hai cách nói.
      const cach_chua = (window.MA_COOKIE_TRANG_THAI || {})[tt.trang_thai];
      banner.className = "hero-ck chip bad";
      banner.innerHTML = '<a href="/settings.html">Cookie không dùng được · dán lại</a>' +
        ghiChu("Cookie của bạn không dùng được — lượt tải sẽ chạy ẩn danh. " + (cach_chua || ""));
      return;
    }
    banner.className = "hero-ck chip ok";
    banner.textContent = "Cookie đang dùng được";
  }

  // ========================================================================
  // INIT
  // ========================================================================
  renderFilterBar();
  window.GiaiCaptcha.noiVao({
    toast: showToast,
    lamMoiJob: loadJobs,
    layJob: (id) => state.jobs.find((j) => j.id === id) || null,
    baoPhienHetHan,
    cauLyDo: cauMaDung,
  });
  // Thư viện tự báo lỗi của nó (`napLaiThuVien` ⇒ ô `#error` khi lần đầu hỏng).
  Promise.all([loadJobs(), napLaiThuVien(), loadBannerCookie()]).catch((err) => {
    ghiOLoi("Không tải được dữ liệu ban đầu: ", err.message);
  });
  // Polling dự phòng (giữ nguyên lý do từ bản cũ: SSE có thể rớt khi tunnel
  // rớt) — chạy lại dù không còn EventSource nào mở.
  setInterval(() => loadJobs().catch((e) => {
    // Lỗi mạng thoáng qua thì im lặng là đúng — lượt poll sau sẽ tự khỏi.
    // Phiên hết hạn thì không bao giờ tự khỏi, nên nó phải lên màn hình.
    if (e instanceof PhienHetHan) baoPhienHetHan();
  }), 5000);
