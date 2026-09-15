(() => {
  "use strict";

  // ========================================================================
  // CONSTANTS
  // ========================================================================
  const UNKNOWN = "__unknown__"; // khoá bucket dùng chung cho mọi trường thiếu dữ liệu

  const STATUS_LABEL = {
    pending: "Đang chờ", running: "Đang chạy", done: "Xong",
    failed: "Lỗi", interrupted: "Bị ngắt",
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
  };

  // Sáu hộp lọc theo mock. `getBuckets(video)` luôn trả một MẢNG bucket
  // {key,label} — mảng vì "Nguồn" có thể có nhiều giá trị trên một video
  // (một clip lên từ hai hashtag), còn các trường khác trả mảng 1 phần tử.
  // `disabled` = có ô trong dải lọc nhưng không lọc được, vì KHÔNG có dữ
  // liệu tỉ lệ khung ở đâu cả (chưa ai đọc nó từ ffmpeg) — thà disable còn
  // hơn bịa lựa chọn không dựa trên dữ liệu thật.
  const FILTER_GROUPS = [
    { id: "nguon", label: "Nguồn", getBuckets: sourceBuckets },
    { id: "khung", label: "Khung", disabled: true,
      note: "Chưa có dữ liệu tỉ lệ khung (chưa đọc từ ffmpeg)" },
    { id: "dai", label: "Dài", getBuckets: (v) => [durationBucket(v.duration)] },
    { id: "thi_truong", label: "Thị trường", getBuckets: (v) => [regionBucket(v.region)] },
    { id: "ngay_tai", label: "Ngày tải", getBuckets: (v) => [dateBucket(v.tao_luc)] },
    { id: "nguoi_tai", label: "Người tải", getBuckets: (v) => [creatorBucket(v)] },
  ];

  // ========================================================================
  // STATE — nguồn sự thật duy nhất phía client; mọi render đọc từ đây.
  // ========================================================================
  const state = {
    jobs: [],
    videos: [],
    jobCreatorMap: new Map(), // job_id -> nguoi_tao, dựng từ GET /jobs
    selected: new Set(),      // video_id đang được chọn trong thư viện
    filters: {},              // groupId -> Map<bucketKey, bucketLabel>
    openStreams: new Map(),   // job_id -> EventSource đang theo dõi
  };
  for (const g of FILTER_GROUPS) if (!g.disabled) state.filters[g.id] = new Map();

  // ========================================================================
  // HELPERS — escape, format, bucket
  // ========================================================================
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function fmtDateTime(iso) {
    return escapeHtml((iso || "").replace("T", " ").slice(0, 19)) || "—";
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

  function creatorBucket(video) {
    const who = state.jobCreatorMap.get(video.job_id);
    return who ? { key: who, label: who } : { key: UNKNOWN, label: "Không rõ" };
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
      if (g.disabled) return true;
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

  function renderQueueItem(job) {
    const pct = job.tong > 0 ? Math.min(100, Math.round((job.xong / job.tong) * 100)) : 0;
    const hasErrors = job.loi > 0;
    const stopText = job.ly_do_dung
      ? (STOP_REASON_TEXT[job.ly_do_dung] ||
         `Dừng sớm (mã chưa dịch: ${escapeHtml(job.ly_do_dung)}) — báo cho người phát triển.`)
      : "";
    const driveLink = job.drive_folder_link
      ? `<a href="${escapeHtml(job.drive_folder_link)}" target="_blank" rel="noopener">Mở thư mục Drive</a>`
      : "";
    return `
      <li class="queue-item" id="job-${job.id}" data-status="${escapeHtml(job.trang_thai)}">
        <div class="queue-item-top">
          <span class="queue-url" title="${escapeHtml(job.url)}">${escapeHtml(job.url)}</span>
          <span class="status-badge status-${escapeHtml(job.trang_thai)}">${escapeHtml(STATUS_LABEL[job.trang_thai] || job.trang_thai)}</span>
        </div>
        <div class="progress-row">
          <div class="progress-track"><div class="progress-fill${hasErrors ? " has-errors" : ""}" style="width:${pct}%"></div></div>
          <span>${job.xong}/${job.tong}${hasErrors ? ` · ${job.loi} lỗi` : ""}</span>
        </div>
        ${stopText ? `<div class="stop-reason">${stopText}</div>` : ""}
        <div class="job-meta">${escapeHtml(job.nguoi_tao)} · ${fmtDateTime(job.tao_luc)}${driveLink ? " · " + driveLink : ""}</div>
      </li>`;
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
    if (group.disabled) {
      return `
        <div class="filter-box disabled">
          <button type="button" class="filter-trigger" disabled title="${escapeHtml(group.note)}">
            ${escapeHtml(group.label)} <span class="filter-note">${escapeHtml(group.note)}</span>
          </button>
        </div>`;
    }
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
      if (group.disabled) continue;
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
          <a class="card-link" href="${escapeHtml(video.url)}" target="_blank" rel="noopener" data-video-link>Xem gốc ↗</a>
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
      for (const g of FILTER_GROUPS) if (!g.disabled) state.filters[g.id].clear();
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
    for (const g of FILTER_GROUPS) if (!g.disabled) state.filters[g.id].clear();
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
      state.selected.clear();
      document.querySelectorAll(".card.selected").forEach((c) => {
        c.classList.remove("selected");
        c.setAttribute("aria-checked", "false");
      });
      renderSelectionBar();
      return;
    }
    // Giỏ và phân tích nội dung CHƯA có backend — báo thật, đừng gọi endpoint
    // không tồn tại và đừng giả vờ đã làm.
    if (action === "cart") showToast("Chưa làm — tính năng \"gồm vào giỏ\" chưa có ở backend.");
    if (action === "analyze") showToast("Chưa làm — tính năng \"phân tích nội dung\" chưa có ở backend.");
  });

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
    state.jobCreatorMap = new Map(state.jobs.map((j) => [j.id, j.nguoi_tao]));
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
      if (idx >= 0) state.jobs[idx] = job; else state.jobs.unshift(job);
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
  // INIT
  // ========================================================================
  renderFilterBar();
  Promise.all([loadJobs(), loadVideos()]).catch((err) => {
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
