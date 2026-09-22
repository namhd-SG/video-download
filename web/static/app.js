(() => {
  "use strict";

  // ========================================================================
  // CONSTANTS
  // ========================================================================
  const UNKNOWN = "__unknown__"; // khoá bucket dùng chung cho mọi trường thiếu dữ liệu

  // Creative Desk — cùng đội, URL công khai, người dùng đã đăng nhập sẵn ở đó.
  const CREATIVE_DESK_URL = "https://automation.nobidigital.asia";
  // Trần số video một bộ. Lý do là ĐỘ DÀI URL, không phải giới hạn nghiệp vụ:
  // payload đi trong query string, và trình duyệt/proxy bắt đầu cắt quanh 8KB.
  // 30 item giữ URL dưới ~6KB kể cả khi tiêu đề dài và có dấu.
  const HANDOFF_MAX = 30;

  const STATUS_LABEL = {
    pending: "Đang chờ", running: "Đang chạy", done: "Xong",
    failed: "Lỗi", interrupted: "Bị ngắt", cancelled: "Đã rút",
  };

  // Ba lý do dừng sớm KHÁC NHAU (hashtag_enumerator.py) trông giống hệt nhau
  // từ ngoài nhìn vào nếu không dịch riêng — xem `guard-marker` và spec: đừng
  // gộp thành "không lấy được video".
  const STOP_REASON_TEXT = {
    stalled: "Dừng sớm: nhiều trang liên tiếp không thấy video mới — có thể " +
             "nguồn này đã hết video TikTok đang cho xem, không phải lỗi.",
    page_cap: "Dừng sớm: đã quét hết số trang cho phép mà chưa đủ số lượng " +
               "yêu cầu — nguồn có thể còn video, thử chạy lại lượt tải này.",
    index_failed: "Dừng sớm: nguồn liệt kê bên ngoài (không phải TikTok) bị " +
                  "lỗi giữa chừng — thử lại sau.",
    // Ba mã dưới đây sinh ra 21/09 cùng lúc với việc nhánh music/search/profile
    // biết đào sâu. Mỗi câu phải khuyên MỘT việc khác nhau — đó là cả lý do
    // chúng là ba mã chứ không phải một:
    //   · hết giờ / hết vòng ⇒ chạy lại CÓ THỂ ra thêm
    //   · nghi bị chặn       ⇒ NGHỈ đã, chạy lại ngay chỉ làm đậm dấu vết
    //   · đã có hết          ⇒ ĐỔI NGUỒN (mã `already_owned`, đã có ở trên)
    // Gộp chúng thành "không lấy đủ video" là quay về đúng sự im lặng mà bản
    // vá này sinh ra để chấm dứt.
    het_thoi_gian: "Dừng: hết thời gian cho một lượt tải (10 phút) trước khi " +
                   "đủ số bạn xin. Những video đã tìm được vẫn được giữ — " +
                   "chạy lại lượt này có thể ra thêm.",
    het_vong: "Dừng: đã quét lại hết số vòng cho phép mà chưa đủ số bạn xin. " +
              "Nguồn có thể còn video — chạy lại lượt này có thể ra thêm.",
    nghi_bi_chan: "Dừng: nguồn đang trả video rồi đột ngột ngừng — nhiều khả " +
                  "năng TikTok đang tạm chặn. Hãy NGHỈ một lúc rồi chạy lại; " +
                  "chạy lại ngay thường bị chặn tiếp.",
    // Bốn mã cookie: người dùng TỰ CHỮA ĐƯỢC cả bốn, nên câu chữ phải nói
    // cách chữa, không được rơi vào nhánh "báo cho người phát triển" ở dưới.
    // Nguồn còn sống, chỉ là thư viện đã có hết những gì nó đưa ra. Câu này
    // KHÔNG được bảo "thử chạy lại" — chạy lại cũng ra đúng như vậy, chỉ tốn
    // thêm lượt gọi TikTok.
    already_owned: "Xong: thư viện đã có hết video mà nguồn này đang đưa ra. " +
                   "Chạy lại cũng không ra thêm — thử hashtag hoặc nguồn khác.",
    source_empty: "Xong: nguồn này hiện không có video nào.",
    cookie_khong_doc_duoc: "Dừng: tệp cookie của bạn không đọc được. Hãy xuất " +
                           "lại từ Cookie-Editor và chọn đúng định dạng JSON " +
                           "(không phải Header String hay Netscape), rồi dán lại.",
    cookie_rong: "Dừng: tệp cookie của bạn không có cookie nào. Hãy xuất lại " +
                 "khi đang mở tiktok.com và đã đăng nhập.",
    cookie_chua_dang_nhap: "Dừng: cookie của bạn không có phiên đăng nhập — " +
                           "có vẻ được xuất lúc chưa đăng nhập TikTok. Đăng " +
                           "nhập tiktok.com rồi xuất lại cookie.",
    cookie_het_han: "Dừng: cookie đăng nhập của bạn đã hết hạn. Vào lại " +
                    "tiktok.com, xuất cookie mới rồi dán lại.",
  };

  // Các hộp lọc theo mock. `getBuckets(video)` luôn trả một MẢNG bucket
  // {key,label} — mảng vì "Nguồn" có thể có nhiều giá trị trên một video
  // (một clip lên từ hai hashtag), còn các trường khác trả mảng 1 phần tử.
  //
  // Bỏ nhóm "Khung" (tỉ lệ khung) 18/09: nó được ship ở dạng `disabled` kèm
  // dòng chữ "Chưa có dữ liệu tỉ lệ khung (chưa đọc từ ffmpeg)" nằm ngay
  // giữa dải lọc. Đó là một NÚT CHẾT cộng một câu giải thích rải ra giao
  // diện — đúng hai thứ luật dự án cấm. Và nó tự mâu thuẫn với chính khối
  // chú thích ngay dưới đây: nhóm "Người tải" đã bị bỏ vì "một bộ lọc không
  // lọc được gì là một ô gây nhiễu", trong khi "Khung" lọc được ÍT HƠN THẾ.
  // Dựng lại khi ffmpeg thật sự ghi tỉ lệ khung vào DB, và lúc đó nó là một
  // nhóm bình thường có `getBuckets` — đừng bật lại ở dạng disabled.
  const FILTER_GROUPS = [
    { id: "nguon", label: "Nguồn", getBuckets: sourceBuckets },
    { id: "dai", label: "Dài", getBuckets: (v) => [durationBucket(v.duration)] },
    { id: "thi_truong", label: "Thị trường", getBuckets: (v) => [regionBucket(v.region)] },
    { id: "ngay_tai", label: "Ngày tải", getBuckets: (v) => [dateBucket(v.tao_luc)] },
    // Bỏ nhóm "Người tải" 17/09: thư viện chỉ còn video của chính người đang
    // xem (user chốt "ai nhấn tải thì của người đó"), nên nhóm này chỉ còn
    // đúng một giá trị — một bộ lọc không lọc được gì là một ô gây nhiễu.
    // Quản trị vẫn thấy cả kho qua API; nếu sau này cần lọc cho vai đó thì
    // dựng lại nhóm này CÓ ĐIỀU KIỆN, đừng bật lại vô điều kiện.
  ];

  // ========================================================================
  // STATE — nguồn sự thật duy nhất phía client; mọi render đọc từ đây.
  // ========================================================================
  const state = {
    jobs: [],
    videos: [],
    selected: new Set(),      // video_id đang được chọn trong thư viện
    filters: {},              // groupId -> Map<bucketKey, bucketLabel>
    openStreams: new Map(),   // job_id -> EventSource đang theo dõi
  };
  for (const g of FILTER_GROUPS) state.filters[g.id] = new Map();

  // ========================================================================
  // HELPERS — escape, format, bucket
  // ========================================================================
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Server ghi UTC kèm offset (`models.py::_now` → `…+00:00`), nên để `Date` tự
  // đọc offset đó và đổi sang múi giờ của trình duyệt. Đừng cộng tay 7 tiếng:
  // như vậy là cắm cứng một múi giờ vào mã. Cắt chuỗi (bản cũ) không đổi múi giờ
  // chút nào, nên thẻ job hiện giờ UTC trong khi trang Cài đặt hiện giờ địa phương.
  function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return escapeHtml(String(iso));
    return escapeHtml(d.toLocaleString("vi-VN"));
  }

  function fmtDuration(sec) {
    if (sec === null || sec === undefined) return null;
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function fmtCount(n) {
    if (n === null || n === undefined) return null;
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "tr";
    if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  // Rút gọn URL nguồn để hiện trong hộp lọc/pill mà không mất khả năng nhận
  // ra nguồn nào là nguồn nào (URL đầy đủ vẫn nằm trong `title=`).
  function shortenSourceUrl(u) {
    try {
      const url = new URL(u);
      const path = url.pathname.replace(/\/+$/, "");
      if (path.startsWith("/tag/")) return "#" + path.slice(5);
      if (path.startsWith("/music/")) return "🎵 " + decodeURIComponent(path.slice(7));
      if (path.startsWith("/@")) return path.slice(1);
      if (path.startsWith("/search")) return "Tìm kiếm: " + (url.searchParams.get("q") || "");
      return path || u;
    } catch {
      return u;
    }
  }

  function sourceBuckets(video) {
    if (!video.nguon || video.nguon.length === 0) return [{ key: UNKNOWN, label: "Không rõ" }];
    return video.nguon.map((u) => ({ key: u, label: shortenSourceUrl(u) }));
  }

  function durationBucket(sec) {
    if (sec === null || sec === undefined) return { key: UNKNOWN, label: "Không rõ" };
    if (sec < 15) return { key: "u15", label: "Dưới 15 giây" };
    if (sec < 60) return { key: "15-60", label: "15 giây – 1 phút" };
    if (sec < 180) return { key: "60-180", label: "1 – 3 phút" };
    return { key: "gt180", label: "Trên 3 phút" };
  }

  function regionBucket(region) {
    return region ? { key: region, label: region } : { key: UNKNOWN, label: "Không rõ" };
  }

  function dateBucket(iso) {
    const d = iso ? new Date(iso) : null;
    if (!d || Number.isNaN(d.getTime())) return { key: UNKNOWN, label: "Không rõ" };
    const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diffDays = Math.floor((startOfDay(new Date()) - startOfDay(d)) / 86_400_000);
    if (diffDays <= 0) return { key: "today", label: "Hôm nay" };
    if (diffDays === 1) return { key: "yesterday", label: "Hôm qua" };
    if (diffDays <= 7) return { key: "7d", label: "7 ngày qua" };
    if (diffDays <= 30) return { key: "30d", label: "30 ngày qua" };
    return { key: "older", label: "Cũ hơn" };
  }

  // Đếm số video rơi vào mỗi bucket của MỘT nhóm lọc, trên toàn bộ thư viện
  // (không trừ theo các nhóm lọc khác đang bật — đơn giản hoá có chủ đích,
  // KISS: đủ để trả lời "còn bao nhiêu video ở nhánh này", không hứa đúng
  // "còn bao nhiêu sau khi áp mọi lọc khác" như facet search đầy đủ).
  function buildBuckets(group) {
    const map = new Map();
    for (const v of state.videos) {
      const seenThisVideo = new Set();
      for (const b of group.getBuckets(v)) {
        if (seenThisVideo.has(b.key)) continue;
        seenThisVideo.add(b.key);
        if (!map.has(b.key)) map.set(b.key, { key: b.key, label: b.label, count: 0 });
        map.get(b.key).count += 1;
      }
    }
    return Array.from(map.values()).sort((a, b) => {
      if (a.key === UNKNOWN) return 1;
      if (b.key === UNKNOWN) return -1;
      return b.count - a.count || a.label.localeCompare(b.label);
    });
  }

  function videoMatchesFilters(video) {
    return FILTER_GROUPS.every((g) => {
      const selected = state.filters[g.id];
      if (selected.size === 0) return true;
      return g.getBuckets(video).some((b) => selected.has(b.key));
    });
  }

  // ========================================================================
  // API
  // ========================================================================
  // Ném khi phiên Cloudflare Access đã hết hạn. Tách thành lớp riêng vì nó
  // cần một phản ứng khác hẳn mọi lỗi mạng: tải lại trang thì đăng nhập lại
  // được, còn thử lại ngầm thì không bao giờ khỏi.
  class PhienHetHan extends Error {}

  async function apiGet(path) {
    // `redirect: "manual"` là phần quan trọng. Khi phiên Access hết hạn,
    // Cloudflare trả 302 sang trang đăng nhập; `fetch` mặc định đi theo, gặp
    // CORS và ném `TypeError` — mà vòng poll 5 giây lại nuốt mọi lỗi, nên
    // hàng đợi đứng hình vĩnh viễn, không một lời nào trên màn hình.
    const res = await fetch(path, { redirect: "manual" });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
    return res.json();
  }

  async function apiSend(method, path, body) {
    // Cùng bẫy `redirect: "manual"` như `apiGet` — một phiên Access hết hạn
    // giữa lúc đang dán cookie mà im lặng thì người dùng dán lại mãi.
    const res = await fetch(path, {
      method,
      redirect: "manual",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) {
      // `detail` của backend là một MÃ đóng, không phải câu chữ, và không
      // mang byte nào của tệp cookie — nên đưa thẳng vào bảng dịch được.
      let ma = null;
      try { ma = (await res.json()).detail; } catch (e) { ma = null; }
      const err = new Error(`${method} ${path} -> ${res.status}`);
      err.ma = ma;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  function baoPhienHetHan() {
    const el = document.getElementById("session-expired");
    if (el) el.hidden = false;
  }

  function errorDetailText(data) {
    // FastAPI trả `detail` là STRING cho lỗi tay (400/503) nhưng là MẢNG khi
    // pydantic tự chặn (422) — in thẳng mảng đó ra sẽ hiện "[object Object]".
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
    }
    return "Không tạo được lượt tải";
  }

  // ========================================================================
  // RENDER — hàng đợi
  // ========================================================================
  function renderQueue() {
    const list = document.getElementById("queue-list");
    const emptyHint = document.getElementById("queue-empty");
    document.getElementById("queue-count").textContent =
      state.jobs.length ? `${state.jobs.length} lượt` : "";
    emptyHint.hidden = state.jobs.length > 0;
    list.innerHTML = state.jobs.map(renderQueueItem).join("");
  }

  // "Xong" cho một job hụt mục tiêu đọc thành thành công.
  //
  // USER CHỐT 21/09: job chạy hết mà không đủ số đã xin phải mang nhãn RIÊNG.
  // Đây cố ý là một phép suy ra Ở GIAO DIỆN, không phải một trạng thái mới
  // trong DB: `trang_thai` là máy trạng thái của worker (`VALID_END_STATES`),
  // còn "thiếu" là một nhận xét về KẾT QUẢ. Nhét nó vào `trang_thai` là đổi
  // máy trạng thái, kéo theo migration và mọi nhánh đang so `== "done"` — đắt
  // hơn nhiều, và lui lại khó hơn nhiều, so với thứ user thật sự xin.
  //
  // Chỉ áp cho `done`: `failed`/`cancelled`/`interrupted` đã có câu chuyện
  // riêng và không được cái nhãn này che mất.
  function nhanTrangThai(job) {
    if (job.trang_thai === "done" && job.tong > 0 && job.xong < job.tong) {
      return { chu: "Thiếu", lop: "thieu" };
    }
    return { chu: STATUS_LABEL[job.trang_thai] || job.trang_thai, lop: job.trang_thai };
  }

  function renderQueueItem(job) {
    const pct = job.tong > 0 ? Math.min(100, Math.round((job.xong / job.tong) * 100)) : 0;
    const hasErrors = job.loi > 0;
    const stopText = job.ly_do_dung
      ? (STOP_REASON_TEXT[job.ly_do_dung] ||
         `Dừng sớm (mã chưa dịch: ${escapeHtml(job.ly_do_dung)}) — báo cho người phát triển.`)
      : "";
    // Vì sao con số này phải hiện: lọc trùng chạy trên TOÀN kho, nên người tìm
    // sau nhận ít video hơn người tìm trước — và những video bị bỏ KHÔNG hiện ở
    // đâu trong thư viện của họ. Không nói ra thì một lượt chạy đúng bị đọc
    // thành "nguồn đã cạn", và họ đổi nguồn mà không cần.
    // (`CHECKLIST-VAN-HANH.md`: "phải báo thẳng trên lượt tải".)
    //
    // Khác `already_owned` ở chỗ mã đó chỉ bắn khi bỏ qua HẾT. Ca hay gặp là bỏ
    // qua MỘT PHẦN, và đó chính là ca không có gì giải thích cho tới bản vá này.
    const boQua = Number(job.bo_qua) || 0;
    const skipText = boQua > 0
      ? `Bỏ qua ${boQua} video đã có trong kho.`
      : "";
    const driveLink = job.drive_folder_link
      ? `<a href="${escapeHtml(job.drive_folder_link)}" target="_blank" rel="noopener">Mở thư mục Drive</a>`
      : "";
    return `
      <li class="queue-item" id="job-${job.id}" data-status="${escapeHtml(job.trang_thai)}">
        <div class="queue-item-top">
          <span class="queue-url" title="${escapeHtml(job.url)}">${escapeHtml(job.url)}</span>
          <span class="status-badge status-${escapeHtml(nhanTrangThai(job).lop)}">${escapeHtml(nhanTrangThai(job).chu)}</span>
        </div>
        <div class="progress-row">
          <div class="progress-track"><div class="progress-fill${hasErrors ? " has-errors" : ""}" style="width:${pct}%"></div></div>
          <span>${job.xong}/${job.tong}${hasErrors ? ` · ${job.loi} lỗi` : ""}</span>
        </div>
        ${skipText ? `<div class="skip-note">${skipText}</div>` : ""}
        ${stopText ? `<div class="stop-reason">${stopText}</div>` : ""}
        ${queueLine(job)}
        <div class="job-meta">${escapeHtml(job.nguoi_tao)} · ${fmtDateTime(job.tao_luc)}${driveLink ? " · " + driveLink : ""}</div>
      </li>`;
  }

  // Dòng "thứ N trong hàng" + nút rút. CHỈ cho job đang chờ: job đang tải
  // không rút được (worker đã nhặt), và một nút bấm vào là báo lỗi thì thà
  // đừng vẽ ra.
  //
  // KHÔNG hứa thời gian. Số đo duy nhất đang có là 6,6 giây/video từ đúng
  // một lượt; "còn khoảng N phút" dựng trên n=1 là một lời hứa bịa, và
  // người dùng sẽ đo nó bằng đồng hồ thật.
  function queueLine(job) {
    if (job.trang_thai !== "pending") return "";
    const thu = job.vi_tri
      ? (job.vi_tri === 1 ? "Tiếp theo trong hàng"
                          : `Thứ ${job.vi_tri} trong hàng`)
      : "Đang chờ tới lượt";
    return `
      <div class="queue-line">
        <span class="queue-pos">${escapeHtml(thu)}</span>
        <button type="button" class="queue-cancel" data-huy="${job.id}">Rút lượt</button>
      </div>`;
  }

  // ========================================================================
  // RENDER — bộ lọc + pill "đang lọc"
  // ========================================================================
  function renderFilterBar() {
    const bar = document.getElementById("filter-bar");
    bar.innerHTML = FILTER_GROUPS.map(renderFilterBox).join("");
    // Popover đóng khi bấm ra ngoài hoặc Esc — gắn MỘT LẦN, không nhân bản
    // mỗi lần renderFilterBar chạy lại.
  }

  function renderFilterBox(group) {
    const selected = state.filters[group.id];
    return `
      <div class="filter-box" data-group="${group.id}">
        <button type="button" class="filter-trigger" data-toggle="${group.id}" aria-expanded="false">
          ${escapeHtml(group.label)}
          ${selected.size ? `<span class="count">${selected.size}</span>` : ""}
          <span class="caret">▾</span>
        </button>
        <div class="filter-panel" data-panel="${group.id}" hidden></div>
      </div>`;
  }

  function renderFilterPanelBody(group) {
    const panel = document.querySelector(`.filter-panel[data-panel="${group.id}"]`);
    if (!panel) return;
    const buckets = buildBuckets(group);
    if (buckets.length === 0) {
      panel.innerHTML = `<div class="no-options">Chưa có video để lọc</div>`;
      return;
    }
    const selected = state.filters[group.id];
    panel.innerHTML = buckets.map((b) => `
      <label title="${escapeHtml(b.key === UNKNOWN ? "" : b.key)}">
        <input type="checkbox" data-group="${group.id}" value="${escapeHtml(b.key)}" ${selected.has(b.key) ? "checked" : ""} />
        ${escapeHtml(b.label)}
        <span class="opt-count">${b.count}</span>
      </label>`).join("");
  }

  function renderActiveFilters() {
    const wrap = document.getElementById("active-filters");
    const pills = [];
    for (const group of FILTER_GROUPS) {
      for (const [key, label] of state.filters[group.id]) {
        pills.push({ groupId: group.id, groupLabel: group.label, key, label });
      }
    }
    wrap.hidden = pills.length === 0;
    if (pills.length === 0) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = pills.map((p) => `
      <span class="pill">${escapeHtml(p.groupLabel)}: ${escapeHtml(p.label)}
        <button type="button" data-remove-group="${p.groupId}" data-remove-key="${escapeHtml(p.key)}" aria-label="Gỡ lọc">✕</button>
      </span>`).join("") +
      `<span class="pill clear-all" id="clear-all-pill">Xoá hết ✕</span>`;
  }

  // ========================================================================
  // RENDER — lưới thẻ + trạng thái rỗng
  // ========================================================================
  function renderLibrary() {
    const grid = document.getElementById("card-grid");
    const emptyState = document.getElementById("empty-state");
    const noMatch = document.getElementById("no-match-state");

    if (state.videos.length === 0) {
      emptyState.hidden = false;
      noMatch.hidden = true;
      grid.hidden = true;
      grid.innerHTML = "";
      document.getElementById("library-count").textContent = "";
      renderActiveFilters();
      return;
    }
    emptyState.hidden = true;

    const filtered = state.videos.filter(videoMatchesFilters);
    // Nhãn phải phân biệt được BA con số: số khớp bộ lọc, số đã nạp, và số
    // thật trong thư viện. Gộp hai cái sau là cách con số sai mang hình dạng
    // con số đúng.
    const total = state.videosTotal ?? state.videos.length;
    const loaded = state.videos.length;
    const parts = [];
    parts.push(filtered.length === loaded ? `${loaded}` : `${filtered.length}/${loaded}`);
    parts.push("video");
    if (loaded < total) parts.push(`(đang hiện ${loaded} trong ${total})`);
    document.getElementById("library-count").textContent = parts.join(" ");

    noMatch.hidden = filtered.length > 0;
    grid.hidden = filtered.length === 0;
    grid.innerHTML = filtered.map(renderCard).join("");
    wireThumbFallback();
    renderActiveFilters();
  }

  function renderCard(video) {
    const isSelected = state.selected.has(video.video_id);
    const duration = fmtDuration(video.duration);
    const plays = fmtCount(video.play_count);
    const metaParts = [];
    metaParts.push(escapeHtml(video.author || "(chưa rõ người đăng)"));
    if (video.region) metaParts.push(escapeHtml(video.region));
    if (plays !== null) metaParts.push(`${plays} lượt xem`);
    return `
      <div class="card${isSelected ? " selected" : ""}" data-video-id="${escapeHtml(video.video_id)}" role="checkbox" aria-checked="${isSelected}" tabindex="0">
        <div class="card-thumb">
          <img src="/thumbs/${encodeURIComponent(video.video_id)}" alt="" loading="lazy" />
          ${duration ? `<span class="card-duration">${duration}</span>` : ""}
        </div>
        <span class="card-check"></span>
        <div class="card-body">
          <div class="card-title">${escapeHtml(video.title || "(chưa có tiêu đề)")}</div>
          <div class="card-meta">${metaParts.map((m, i) => i === 0 ? m : `<span class="sep">·</span>${m}`).join(" ")}</div>
          ${video.url
            ? `<a class="card-link" href="${escapeHtml(video.url)}" target="_blank" rel="noopener" data-video-link>Xem gốc ↗</a>`
            : `<span class="card-link card-link-trong">chưa rõ link gốc</span>`}
        </div>
      </div>`;
  }

  // <img onerror> gắn bằng JS (không nhúng vào chuỗi HTML) để không phải
  // escape lồng attribute, và vì 404 là NGOẠI LỆ BÌNH THƯỜNG cần một hình
  // dạng riêng, không phải icon-ảnh-vỡ mặc định của trình duyệt.
  function wireThumbFallback() {
    document.querySelectorAll(".card-thumb img").forEach((img) => {
      img.addEventListener("error", () => {
        const wrap = img.closest(".card-thumb");
        wrap.classList.add("no-thumb");
        img.remove();
        const note = document.createElement("span");
        note.textContent = "Chưa cắt được ảnh";
        wrap.appendChild(note);
      }, { once: true });
    });
  }

  // ========================================================================
  // RENDER — thanh chọn + toast
  // ========================================================================
  function renderSelectionBar() {
    const bar = document.getElementById("selection-bar");
    bar.hidden = state.selected.size === 0;
    document.getElementById("selection-count").textContent = `${state.selected.size} đã chọn`;
  }

  let toastTimer = null;
  function showToast(text) {
    const el = document.getElementById("toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  // ========================================================================
  // EVENTS — bộ lọc (mở/đóng popover, tick checkbox, gỡ pill)
  // ========================================================================
  function closeAllFilterPanels(exceptGroupId) {
    document.querySelectorAll(".filter-panel").forEach((p) => {
      if (p.dataset.panel !== exceptGroupId) p.hidden = true;
    });
    document.querySelectorAll(".filter-trigger[data-toggle]").forEach((t) => {
      if (t.dataset.toggle !== exceptGroupId) t.setAttribute("aria-expanded", "false");
    });
  }

  // Rút lượt. Uỷ quyền trên `queue-list` vì hàng đợi vẽ lại mỗi nhịp poll —
  // gắn trực tiếp lên từng nút thì nút mới sau mỗi lần vẽ sẽ không có tay
  // nghe nào, và hỏng ÂM THẦM: nút vẫn ở đó, bấm không ra gì.
  document.getElementById("queue-list").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-huy]");
    if (!btn) return;
    const jobId = Number(btn.dataset.huy);
    btn.disabled = true;
    try {
      await apiSend("DELETE", `/jobs/${jobId}`);
      showToast("Đã rút lượt khỏi hàng đợi.");
    } catch (err) {
      if (err instanceof PhienHetHan) throw err;
      // 409 là ca THẬT, không phải lỗi người dùng: worker vừa nhặt job
      // đúng lúc họ bấm. Nói đúng chuyện đó, đừng nói "không tìm thấy".
      showToast(String(err.message).includes("409")
        ? "Lượt này vừa bắt đầu tải nên không rút được nữa."
        : "Không rút được lượt này.");
    } finally {
      // Vẽ lại từ máy chủ trong MỌI ca, kể cả ca trượt: trạng thái thật
      // nằm ở DB, và sau một lần 409 thì hàng này đã sang "Đang chạy".
      await loadJobs();
    }
  });

  document.getElementById("filter-bar").addEventListener("click", (ev) => {
    const trigger = ev.target.closest("[data-toggle]");
    if (trigger) {
      const groupId = trigger.dataset.toggle;
      const panel = document.querySelector(`.filter-panel[data-panel="${groupId}"]`);
      const willOpen = panel.hidden;
      closeAllFilterPanels(willOpen ? groupId : null);
      panel.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) renderFilterPanelBody(FILTER_GROUPS.find((g) => g.id === groupId));
      return;
    }
  });

  document.getElementById("filter-bar").addEventListener("change", (ev) => {
    const box = ev.target;
    if (box.tagName !== "INPUT" || box.type !== "checkbox") return;
    const groupId = box.dataset.group;
    const group = FILTER_GROUPS.find((g) => g.id === groupId);
    const selected = state.filters[groupId];
    if (box.checked) {
      const bucket = buildBuckets(group).find((b) => b.key === box.value);
      selected.set(box.value, bucket ? bucket.label : box.value);
    } else {
      selected.delete(box.value);
    }
    renderFilterBar(); // cập nhật badge số lượng trên nút
    renderLibrary();
  });

  document.getElementById("active-filters").addEventListener("click", (ev) => {
    if (ev.target.id === "clear-all-pill") {
      for (const g of FILTER_GROUPS) state.filters[g.id].clear();
      renderFilterBar();
      renderLibrary();
      return;
    }
    const btn = ev.target.closest("[data-remove-group]");
    if (btn) {
      state.filters[btn.dataset.removeGroup].delete(btn.dataset.removeKey);
      renderFilterBar();
      renderLibrary();
    }
  });

  document.getElementById("clear-filters-btn").addEventListener("click", () => {
    for (const g of FILTER_GROUPS) state.filters[g.id].clear();
    renderFilterBar();
    renderLibrary();
  });

  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".filter-box")) closeAllFilterPanels(null);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeAllFilterPanels(null);
  });

  // ========================================================================
  // EVENTS — chọn thẻ + thanh thao tác
  // ========================================================================
  function toggleSelection(videoId) {
    if (state.selected.has(videoId)) state.selected.delete(videoId);
    else state.selected.add(videoId);
    const card = document.querySelector(`.card[data-video-id="${CSS.escape(videoId)}"]`);
    if (card) {
      const nowSelected = state.selected.has(videoId);
      card.classList.toggle("selected", nowSelected);
      card.setAttribute("aria-checked", String(nowSelected));
    }
    renderSelectionBar();
  }

  document.getElementById("card-grid").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-video-link]")) return; // "Xem gốc" mở tab riêng, không chọn thẻ
    const card = ev.target.closest(".card");
    if (card) toggleSelection(card.dataset.videoId);
  });
  document.getElementById("card-grid").addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const card = ev.target.closest(".card");
    if (card) { ev.preventDefault(); toggleSelection(card.dataset.videoId); }
  });

  document.getElementById("selection-bar").addEventListener("click", (ev) => {
    const action = ev.target.dataset.action;
    if (!action) return;
    if (action === "clear") {
      boChonTatCa();
      return;
    }
    if (action === "loai") loaiDaChon();
    if (action === "self-bundle") moBoTuTim();
  });

  // Bỏ chọn tất cả: xoá state VÀ gỡ dấu trên thẻ. Hai vế phải đi cùng nhau —
  // `loaiDaChon` thoát được vế thứ hai chỉ vì nó `loadVideos()` dựng lại toàn
  // bộ lưới ngay sau đó. Đường nào KHÔNG nạp lại lưới mà chỉ xoá state sẽ để
  // thẻ tô xanh trong khi thanh chọn nói "0 video", và lần bấm kế tiếp đọc
  // một state khác với cái người dùng đang nhìn.
  function boChonTatCa() {
    state.selected.clear();
    document.querySelectorAll(".card.selected").forEach((c) => {
      c.classList.remove("selected");
      c.setAttribute("aria-checked", "false");
    });
    renderSelectionBar();
  }

  // "Tạo bộ tự tìm" — bàn giao sang Creative Desk qua THANH ĐỊA CHỈ, không
  // qua API.
  //
  // Vì sao mở tab thay vì gọi backend bên kia: trang này nằm ở origin
  // `video.*`, Creative Desk ở `automation.*`, và cả hai sau Cloudflare
  // Access. Một lời gọi chéo origin từ đây sẽ cần Video Desk cầm token của
  // người dùng hoặc một service token — tức là dựng một bề mặt mạo danh cho
  // một việc vốn chỉ là copy file. Đưa TRÌNH DUYỆT sang đó thì người dùng
  // mang sẵn phiên của chính họ, và bộ được tạo đứng tên đúng người mà bên
  // này không cầm gì cả.
  function moBoTuTim() {
    const daChon = state.videos.filter((v) => state.selected.has(v.video_id));
    // Video chưa lên Drive thì KHÔNG có gì để copy. Bỏ qua chúng và nói ra số
    // bị bỏ — im lặng gửi thiếu là cách người dùng mất video mà không biết.
    const chuaLenDrive = daChon.filter((v) => !v.drive_file_id);
    const items = daChon
      .filter((v) => v.drive_file_id)
      .map((v) => ({ f: v.drive_file_id, n: v.title || v.video_id, u: v.url }));

    if (!items.length) {
      showToast("Video đã chọn chưa lên Drive — chưa có gì để gửi sang Creative Desk.");
      return;
    }
    if (items.length > HANDOFF_MAX) {
      showToast(`Chọn tối đa ${HANDOFF_MAX} video cho một bộ.`);
      return;
    }
    if (chuaLenDrive.length) {
      showToast(`${chuaLenDrive.length} video chưa lên Drive nên không gửi kèm.`);
    }

    // base64url: payload đi trong URL nên `+` `/` `=` đều phải biến mất.
    // `TextEncoder` trước `btoa` vì tiêu đề video có tiếng Việt và emoji —
    // `btoa` một mình ném `InvalidCharacterError` ở ký tự ngoài Latin-1.
    const json = JSON.stringify({ v: 1, items });
    const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const tab = window.open(
      `${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk=${b64}`,
      "_blank", "noopener");

    // Bỏ chọn sau khi đã bàn giao, KHÔNG phải trước. Bàn giao xong mà lựa chọn
    // còn nguyên thì lần bấm kế tiếp mở thêm một tab với ĐÚNG danh sách cũ —
    // người dùng đọc thành "bộ cũ không gỡ được".
    //
    // Chỉ bỏ khi tab thật sự mở. `window.open` trả `null` khi trình duyệt chặn
    // popup, và lúc đó chưa có gì được bàn giao cả: xoá lựa chọn ở đó là bắt
    // người dùng chọn lại từ đầu vì một việc CHƯA xảy ra. Đây cũng là khuôn của
    // `loaiDaChon` bên dưới — nó chỉ `clear()` sau khi lời gọi API thành công.
    if (!tab) {
      showToast("Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại. " +
                "Lựa chọn của bạn vẫn còn.");
      return;
    }
    boChonTatCa();
  }

  async function loaiDaChon() {
    const ids = [...state.selected];
    if (!ids.length) return;
    // Hỏi trước: xoá là việc khó lùi ở phía người dùng (tệp vào Thùng rác
    // Drive). Nói rõ nó KHÔNG đụng người khác — đó là thứ người bấm cần biết
    // để bấm mà không phải đoán.
    const ok = window.confirm(
      `Bỏ ${ids.length} video khỏi thư viện của bạn?\n\n` +
      `Tệp vào Thùng rác Drive (lấy lại được trong 30 ngày). ` +
      `Người khác không bị ảnh hưởng, và lượt quét sau của bạn sẽ không tải lại chúng.`);
    if (!ok) return;

    try {
      const res = await apiSend("POST", "/videos/loai", { video_ids: ids });
      state.selected.clear();
      await loadVideos();
      renderSelectionBar();
      // Báo đủ ba con số, không gộp thành một chữ "xong": Drive trượt mà im
      // lặng thì người dùng tưởng đã dọn trong khi tệp còn nguyên.
      const phan = [`đã bỏ ${res.da_loai.length}`];
      if (res.drive_truot.length) phan.push(`${res.drive_truot.length} chưa bỏ được khỏi Drive — thử lại`);
      if (res.khong_phai_cua_ban.length) phan.push(`${res.khong_phai_cua_ban.length} không phải của bạn`);
      showToast(phan.join(" · "));
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast("Không bỏ được: " + err.message);
    }
  }

  document.getElementById("library-refresh").addEventListener("click", () => {
    loadVideos().catch((err) => showToast("Không tải lại được thư viện: " + err.message));
  });

  // ========================================================================
  // EVENTS — theme
  // ========================================================================
  const THEME_KEY = "videodl-theme";
  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }
  applyTheme(localStorage.getItem(THEME_KEY));
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });

  // ========================================================================
  // DATA LOADING — jobs (+ SSE tiến độ) và videos
  // ========================================================================
  async function loadJobs() {
    state.jobs = await apiGet("/jobs");
    renderQueue();
    state.jobs.forEach((job) => {
      if ((job.trang_thai === "pending" || job.trang_thai === "running") && !state.openStreams.has(job.id)) {
        followJob(job.id);
      }
    });
  }

  function followJob(jobId) {
    const es = new EventSource(`/jobs/${jobId}/events`);
    state.openStreams.set(jobId, es);
    es.addEventListener("progress", (ev) => {
      const job = JSON.parse(ev.data);
      const idx = state.jobs.findIndex((j) => j.id === job.id);
      // `vi_tri` chỉ có ở `GET /jobs` (máy chủ đếm cả hàng đợi của người
      // khác); payload SSE là một hàng job trần. Gán đè nguyên hàng thì vị
      // trí BIẾN MẤT ngay nhịp tiến độ đầu tiên và dòng chữ tụt về "Đang
      // chờ tới lượt" — đo được bằng ảnh chụp 18/09, test API không thấy vì
      // nó không đi qua đường này. Giữ lại giữa hai nhịp poll `loadJobs`.
      if (idx >= 0) {
        const vi_tri_cu = state.jobs[idx].vi_tri;
        state.jobs[idx] = job;
        if (job.vi_tri === undefined && job.trang_thai === "pending"
            && vi_tri_cu !== undefined) {
          state.jobs[idx].vi_tri = vi_tri_cu;
        }
      } else {
        state.jobs.unshift(job);
      }
      renderQueue();
      if (job.trang_thai !== "pending" && job.trang_thai !== "running") {
        es.close();
        state.openStreams.delete(jobId);
        // Job vừa xong (hoặc lỗi/bị ngắt) — nạp lại thư viện để creative mới
        // (nếu có) xuất hiện mà không cần user tự bấm "Làm mới".
        loadVideos().catch((e) => { if (e instanceof PhienHetHan) baoPhienHetHan(); });
      }
    });
    es.onerror = () => {
      // Tunnel/SSE có thể rớt trong khi job vẫn chạy ở server — đóng stream
      // này, dựa vào polling `loadJobs` bên dưới để giữ hàng đợi đúng.
      es.close();
      state.openStreams.delete(jobId);
    };
  }

  // Trần cứng cho số video giữ trong trình duyệt. Có trần là vì lưới dựng DOM
  // cho từng thẻ; không có trần thì thư viện lớn dần sẽ làm treo tab của người
  // dùng, và đó là kiểu hỏng khó truy hơn hẳn một dòng chữ "đang hiện 2000/5000".
  const LIBRARY_PAGE = 500;
  const LIBRARY_MAX = 2000;

  async function loadVideos() {
    // Bản đầu gọi `/videos` không tham số, tức nhận đúng 200 video mặc định
    // của server, KHÔNG đọc `tong`, và in nhãn theo số đã nạp. Hậu quả: video
    // thứ 201 trở đi không tồn tại với người dùng, mọi bộ lọc chạy trên tập
    // con, và nhãn "200 video" trông y hệt một con số đúng. Thư viện dùng
    // chung cả team mà cắt im lặng như vậy là hỏng đúng thứ nó sinh ra để làm.
    const first = await apiGet(`/videos?limit=${LIBRARY_PAGE}&offset=0`);
    const videos = first.videos.slice();
    const tong = first.tong;

    while (videos.length < tong && videos.length < LIBRARY_MAX) {
      const next = await apiGet(`/videos?limit=${LIBRARY_PAGE}&offset=${videos.length}`);
      if (next.videos.length === 0) break;   // server hết hàng sớm hơn `tong`
      videos.push(...next.videos);
    }

    state.videos = videos;
    state.videosTotal = tong;
    renderLibrary();
  }

  document.getElementById("job-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errorBox = document.getElementById("error");
    const submitBtn = ev.target.querySelector("button[type=submit]");
    errorBox.textContent = "";
    const url = document.getElementById("url").value.trim();
    const soLuong = parseInt(document.getElementById("so-luong").value, 10);
    submitBtn.disabled = true;
    try {
      const res = await fetch("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, so_luong: soLuong }),
      });
      const data = await res.json();
      if (!res.ok) {
        errorBox.textContent = errorDetailText(data);
        return;
      }
      const idx = state.jobs.findIndex((j) => j.id === data.id);
      if (idx >= 0) state.jobs[idx] = data; else state.jobs.unshift(data);
      renderQueue();
      followJob(data.id);
      document.getElementById("url").value = "";
    } catch (err) {
      errorBox.textContent = "Lỗi mạng: " + err.message;
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
    if (!tt.co_jar) {
      banner.className = "banner-an-danh";
      banner.innerHTML = 'Chưa có cookie — lượt tải của bạn chạy <strong>ẩn danh</strong> ' +
        'và chia chung hạn mức với mọi người chưa dán. ' +
        '<a href="/settings.html">Dán cookie của bạn →</a>';
      return;
    }
    if (tt.trang_thai !== "dung_duoc") {
      // Câu chữ lấy từ bảng dùng chung với trang Cài đặt — hai trang nói cùng
      // một câu về cùng một tệp, nếu không người dùng phải tự ghép hai cách nói.
      const cach_chua = (window.MA_COOKIE_TRANG_THAI || {})[tt.trang_thai];
      banner.className = "banner-an-danh";
      banner.innerHTML = "Cookie của bạn <strong>không dùng được</strong> — lượt tải sẽ chạy " +
        "ẩn danh. " + (cach_chua ? escapeHtml(cach_chua) + " " : "") +
        '<a href="/settings.html">Dán lại cookie →</a>';
      return;
    }
    banner.className = "chip chip-ok";
    banner.textContent = "Cookie đang dùng được";
  }

  // ========================================================================
  // INIT
  // ========================================================================
  renderFilterBar();
  Promise.all([loadJobs(), loadVideos(), loadBannerCookie()]).catch((err) => {
    document.getElementById("error").textContent = "Không tải được dữ liệu ban đầu: " + err.message;
  });
  // Polling dự phòng (giữ nguyên lý do từ bản cũ: SSE có thể rớt khi tunnel
  // rớt) — chạy lại dù không còn EventSource nào mở.
  setInterval(() => loadJobs().catch((e) => {
    // Lỗi mạng thoáng qua thì im lặng là đúng — lượt poll sau sẽ tự khỏi.
    // Phiên hết hạn thì không bao giờ tự khỏi, nên nó phải lên màn hình.
    if (e instanceof PhienHetHan) baoPhienHetHan();
  }), 5000);
})();
