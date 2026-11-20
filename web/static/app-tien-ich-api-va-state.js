// Định dạng, bucket bộ lọc, lọc video, `apiGet`/`errorDetailText`; rồi nhóm bộ lọc + `state` (nguồn sự thật phía client).
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

  // ========================================================================
  // HELPERS — escape, format, bucket
  // ========================================================================
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
  // Nhãn nền tảng cho nguồn là LINK VIDEO LẺ (mỗi video có nguồn riêng là URL của chính nó): "YouTube · <id ngắn>".
  // Chỉ tên nền tảng thì mọi chip trùng nhau; URL đầy đủ vẫn nằm trong `title=`. `null` = không phải link lẻ.
  const NEN_TANG_THEO_HOST = [
    [/(^|\.)(youtube\.com|youtu\.be)$/, "YouTube"], [/(^|\.)instagram\.com$/, "Instagram"],
    [/(^|\.)(facebook\.com|fb\.watch)$/, "Facebook"], [/(^|\.)(x\.com|twitter\.com)$/, "X"],
    [/(^|\.)pinterest\.[a-z.]+$/, "Pinterest"], [/(^|\.)douyin\.com$/, "Douyin"],
    [/(^|\.)bilibili\.com$/, "Bilibili"], [/(^|\.)snapchat\.com$/, "Snapchat"],
    [/(^|\.)tiktok\.com$/, "TikTok"],
  ];
  function thongTinLinkLe(url) {
    const host = url.hostname.toLowerCase();
    const ten = (NEN_TANG_THEO_HOST.find(([re]) => re.test(host)) || [])[1];
    if (!ten) return null;
    const path = url.pathname.replace(/\/+$/, "");
    const id = url.searchParams.get("v") || (path.match(/\/(?:video|shorts|reel|reels|p|status|pin|spotlight)\/([^/]+)/) || [])[1]
      || (host.endsWith("youtu.be") ? path.slice(1) : "") || url.searchParams.get("fbid") || "";
    // TikTok: trang tag/music/profile giữ nhãn cũ; chỉ `/video/<id>` là link lẻ.
    if (ten === "TikTok" && !/\/video\/\d+/.test(path)) return null;
    if (ten === "Facebook" && /\/ads\/library/.test(path)) return null;
    // Kênh / tab / playlist YouTube là NGUỒN của cả loạt video (một job), không phải link video lẻ: giữ nhãn theo
    // đường dẫn (`@kênh/shorts`) để bộ lọc nguồn không gộp mọi kênh vào một hộp "YouTube".
    if (ten === "YouTube" && /^\/(@|channel\/|playlist$)/.test(path)) return null;
    return { ten, id };
  }

  function nhanLinkLe(url) {
    const t = thongTinLinkLe(url);
    if (!t) return null;
    if (!t.id) return t.ten;
    return `${t.ten} · ${t.id.length > 12 ? t.id.slice(0, 11) + "…" : t.id}`;
  }

  // Bộ lọc nguồn cho link lẻ: khoá theo NỀN TẢNG, không theo URL đầy đủ — mỗi video link lẻ có nguồn riêng, khoá theo
  // URL sinh ra hàng trăm hộp một-video. `null` = không phải link lẻ (giữ bucket theo URL như cũ).
  function bucketNenTangLinkLe(u) {
    try {
      const t = thongTinLinkLe(new URL(u));
      if (!t) return null;
      return { key: `nen-tang:${t.ten}`, label: t.ten === "TikTok" ? "TikTok · video lẻ" : t.ten };
    } catch {
      return null;
    }
  }

  function shortenSourceUrl(u) {
    try {
      const url = new URL(u);
      const path = url.pathname.replace(/\/+$/, "");
      const le = nhanLinkLe(url);
      if (le) return le;
      if (path.startsWith("/tag/")) return "#" + path.slice(5);
      if (path.startsWith("/music/")) return "🎵 " + decodeURIComponent(path.slice(7));
      if (path.startsWith("/@")) return path.slice(1);
      if (path === "/playlist") return "Playlist YouTube";
      if (path.startsWith("/channel/")) return path.slice(1);
      if (path.startsWith("/search")) return "Tìm kiếm: " + (url.searchParams.get("q") || "");
      return path || u;
    } catch {
      return u;
    }
  }

  function sourceBuckets(video) {
    if (!video.nguon || video.nguon.length === 0) return [{ key: UNKNOWN, label: "Không rõ" }];
    return video.nguon.map((u) => {
      const le = bucketNenTangLinkLe(u);
      return le ? { ...le, title: u } : { key: u, label: shortenSourceUrl(u) };
    });
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
    for (const v of videoTrongNen()) {
      const seenThisVideo = new Set();
      for (const b of group.getBuckets(v)) {
        if (seenThisVideo.has(b.key)) continue;
        seenThisVideo.add(b.key);
        if (!map.has(b.key)) map.set(b.key, { key: b.key, label: b.label, title: b.title, count: 0 });
        map.get(b.key).count += 1;
      }
    }
    return Array.from(map.values()).sort((a, b) => {
      if (a.key === UNKNOWN) return 1;
      if (b.key === UNKNOWN) return -1;
      return b.count - a.count || a.label.localeCompare(b.label);
    });
  }

  // Thanh bên "Cụm của tôi" là MỘT BỘ LỌC NỮA, chạy ở client trên thư viện đã
  // nạp trọn (như bốn hộp lọc) — không có tham số lọc cụm ở server.
  function videoKhopCum(video, cumLoc) {
    if (cumLoc === "tat_ca") return true;
    if (cumLoc === "chua") return video.cum_id == null;
    return video.cum_id === cumLoc;
  }

  // Video đã vào bộ tự tìm (server gắn `vao_bo`): ẨN khỏi lưới mặc định, chỉ hiện
  // khi bật chip "Đã vào bộ". Server lọc theo phía chip (`/videos?vao_bo=0|1`, xem
  // `loadVideos`); lọc lại ở client vẫn giữ — thừa với server mới, cần với server cũ
  // (trả cả hai phía). ⚠ CHỈ lưới/đếm/hộp lọc đi qua đây; cắt lô của cụm (`videoCuaCum`) KHÔNG,
  // vì video đã vào bộ vẫn nằm trong lô của cụm.
  function videoDaVaoBo(video) { return Boolean(video.vao_bo); }

  // Tập video ĐANG HIỆN theo chip: mẫu số cho nhãn "x/N video", số đếm ở thanh bên
  // và số đếm trong các hộp lọc — để chúng khớp lưới người dùng đang nhìn.
  function videoTrongNen() {
    return state.videos.filter((v) => videoDaVaoBo(v) === state.chiVaoBo);
  }

  function veChipVaoBo() {
    const chip = document.getElementById("chip-vao-bo");
    if (!chip) return;
    // Lưới chỉ nạp MỘT phía chip ⇒ số phải lấy từ server; server cũ (trả cả hai
    // phía) thì tự đếm như trước.
    const n = typeof state.tongVaoBo === "number" ? state.tongVaoBo
      : state.videos.filter(videoDaVaoBo).length;
    // Chỉ ghi vào nhãn: chip còn có ⓘ (`.ti`) — ghi textContent của cả chip sẽ đè mất nó.
    const nhan = chip.querySelector(".chip-vao-bo-nhan") || chip;
    nhan.textContent = `Đã vào bộ (${n})`;
    chip.classList.toggle("on", state.chiVaoBo);
    chip.setAttribute("aria-pressed", String(state.chiVaoBo));
  }

  function videoMatchesFilters(video) {
    if (videoDaVaoBo(video) !== state.chiVaoBo) return false;
    if (!videoKhopCum(video, state.cumLoc)) return false;
    return FILTER_GROUPS.every((g) => {
      const selected = state.filters[g.id];
      if (selected.size === 0) return true;
      return g.getBuckets(video).some((b) => selected.has(b.key));
    });
  }

  // ========================================================================
  // API
  // ========================================================================
  // `signal` (tuỳ chọn): huỷ request — chỉ lượt nạp thư viện dùng (`batDauLuotNap`).
  async function apiGet(path, { signal } = {}) {
    // `redirect: "manual"` là phần quan trọng. Khi phiên Access hết hạn,
    // Cloudflare trả 302 sang trang đăng nhập; `fetch` mặc định đi theo, gặp
    // CORS và ném `TypeError` — mà vòng poll 5 giây lại nuốt mọi lỗi, nên
    // hàng đợi đứng hình vĩnh viễn, không một lời nào trên màn hình.
    const res = await fetch(path, { redirect: "manual", signal });
    if (res.type === "opaqueredirect" || res.status === 0) throw new PhienHetHan();
    if (!res.ok) {
      const err = new Error(`GET ${path} -> ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
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
    // `chiVideo`: ảnh không có thời lượng/thị trường ⇒ nhóm ẩn khi thư viện ở chế độ Ảnh (đổi loại đã xoá bộ lọc).
    { id: "dai", label: "Dài", chiVideo: true, getBuckets: (v) => [durationBucket(v.duration)] },
    { id: "thi_truong", label: "Thị trường", chiVideo: true, getBuckets: (v) => [regionBucket(v.region)] },
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
    popupId: null,            // id lượt đang mở popup chi tiết (null = đóng)
    popupHtml: "",            // HTML popup đang hiện — so để nhịp poll không vẽ lại khi không đổi
    videos: [],
    selected: new Set(),      // video_id đang được chọn trong thư viện
    dangBanGiao: false,       // đang chờ Creative Desk ack — khoá nút "Tạo bộ tự tìm"
    trang: 1,                 // trang thư viện đang xem, 1-based
    soMoiTrang: 40,           // nạp lại từ localStorage lúc khởi động — xem docSoMoiTrang
    idTrang: [],              // video_id của TRANG đang hiện — "Chọn tất cả" chỉ lấy ở đây
    filters: {},              // groupId -> Map<bucketKey, bucketLabel>
    cums: [],                 // GET /cum — cụm CỦA NGƯỜI XEM, kèm `insight` do server ghép
    videosDaDon: [],          // GET /videos → da_don_trong_cum: video đã dọn khỏi Drive, GIỮ CHỖ trong lô
    khungCum: undefined,      // GET /cum → khung_cum: tập cắt lô của mọi cụm (undefined = server cũ)
    cumLoc: "tat_ca",         // "tat_ca" | "chua" | <cum id> — bộ lọc thanh bên "Cụm của tôi"
    taiAnhBat: false,         // GET /tinh-nang → tai_anh_bat: có công tắc loại tải / "Loại" thư viện không
    loaiThuVien: "video",     // "video" | "anh": thư viện đang NẠP /videos hay /anh (không nhớ giữa các lần mở trang)
    loaiDaVe: undefined,      // loại mà lưới ĐANG thật sự vẽ (như `phiaDaVe`)
    chiVaoBo: false,          // chip "Đã vào bộ": true ⇒ lưới CHỈ hiện video đã vào bộ; false ⇒ ẩn chúng
    tongVaoBo: undefined,     // GET /videos → tong_vao_bo: số trên chip (undefined = server cũ, tự đếm)
    luotNapVideo: 0,          // lượt `loadVideos` mới nhất — lượt cũ về trễ thì bỏ
    boHuyNap: null,           // AbortController của lượt nạp mới nhất (`batDauLuotNap`)
    phiaDaVe: undefined,      // phía chip mà lưới ĐANG thật sự vẽ (0/1; undefined = chưa vẽ lần nào)
    openStreams: new Map(),   // job_id -> EventSource đang theo dõi
    dangGuiChayLai: new Set(), // job_id đang chờ POST /jobs của nút "Chạy lại" — chặn bấm đôi qua các lần vẽ lại
    dangGuiTaiLai: new Set(), // job_id đang chờ POST /jobs của nút "Tải lại" — chặn bấm đôi
    chayLai: new Map(),       // job_id -> số đang gõ trong ô "chạy lại kiếm thêm" (ô đang mở)
  };
  for (const g of FILTER_GROUPS) state.filters[g.id] = new Map();
