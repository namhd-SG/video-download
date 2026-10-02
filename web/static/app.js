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
  // Chọn tay đi đường KHÁC: `postMessage` sang tab Creative Desk, không qua URL
  // ⇒ không vướng trần 8KB, Creative Desk tự chia thành nhiều bộ. Trần dưới đây
  // chỉ là phanh an toàn, khớp `MAX_PM_ITEMS` phía nhận
  // (meta-ads `frontend/src/lib/videodesk-postmessage.ts`).
  const CREATIVE_DESK_ORIGIN = new URL(CREATIVE_DESK_URL).origin;
  const MAX_PM_ITEMS = 500;
  // Gửi lặp tới khi có ack: tab mới cần vài giây để tải và gắn bộ nghe, tin gửi
  // trước đó rơi mất. Creative Desk KHÔNG đứng sau Cloudflare Access; cổng của nó
  // là trang `/login` của app, và sau khi đăng nhập tab không quay lại trang này
  // — chờ lâu hơn không cứu được ca đó, chỉ khoá nút lâu hơn. 30 s đủ cho tải trang.
  const PM_CHU_KY_MS = 500;
  const PM_HAN_MS = 30000;

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
    // Mã này phát cả khi lỗi ngay trang đầu (lượt 0 video ⇒ "Lỗi") lẫn giữa
    // chừng (đã có vài video ⇒ "Xong"/"Thiếu"), nên câu phải đúng cả hai ca.
    index_failed: "Không đọc tiếp được hashtag: nguồn liệt kê bên ngoài (không " +
                  "phải TikTok) bị lỗi — thử lại sau.",
    hashtag_khong_tra_duoc: "Không đọc được hashtag: không tra được mã của " +
                            "hashtag này trên TikTok (hashtag sai, không tồn " +
                            "tại, hoặc TikTok không trả mã) — kiểm lại hashtag " +
                            "rồi thử lại.",
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
    // Lượt rỗng với mã này giờ ghi "Lỗi" (không còn "Xong"), nên câu không được
    // mở bằng "Xong:". Nhánh hashtag cũng phát mã này khi nguồn hết trang mà
    // chưa đủ số xin (`hashtag_enumerator.py`), nên câu phải đúng cả hai ca.
    source_empty: "Nguồn không đưa thêm video nào cho link này. Nếu chưa tải " +
                  "được video nào: link có thể sai hoặc đã hết hạn, hoặc nguồn " +
                  "chưa có video — kiểm lại link.",
    // KHÔNG phải "đã tải rồi": feed TikTok trả RỖNG (0 byte) ở mọi lần hỏi,
    // nên việc thư viện có hay không chưa từng được hỏi tới. Đo 01–02/10: trang
    // hiện captcha với trình duyệt tự động; không cookie / cookie khác rỗng y
    // hệt ⇒ KHÔNG được khuyên dán lại cookie (bản cũ khuyên vậy là chỉ sai hướng).
    // "Thường do" chứ không khẳng định: mã này dùng chung cho search/nhạc/trang
    // cá nhân, còn captcha mới thấy tận mắt ở trang cá nhân. Chỉ khuyên HASHTAG:
    // đường hashtag gọi API bằng urllib (`hashtag_enumerator`), không qua trình
    // duyệt; khuyên "nhạc/tìm kiếm" là khuyên đổi sang đúng loại trang vừa rỗng.
    feed_rong: "Dừng: TikTok trả kết quả RỖNG cho link này (không phải vì bạn " +
               "đã tải rồi). Thường do TikTok đang đòi xác minh (captcha) với " +
               "trình duyệt tự động — dán lại cookie không chữa được. Đợi một " +
               "lúc rồi thử lại, hoặc lấy video qua link hashtag.",
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
    dangBanGiao: false,       // đang chờ Creative Desk ack — khoá nút "Tạo bộ tự tìm"
    trang: 1,                 // trang thư viện đang xem, 1-based
    soMoiTrang: 40,           // nạp lại từ localStorage lúc khởi động — xem docSoMoiTrang
    idTrang: [],              // video_id của TRANG đang hiện — "Chọn tất cả" chỉ lấy ở đây
    filters: {},              // groupId -> Map<bucketKey, bucketLabel>
    cums: [],                 // GET /cum — cụm CỦA NGƯỜI XEM, kèm `insight` do server ghép
    videosDaDon: [],          // GET /videos → da_don_trong_cum: video đã dọn khỏi Drive, GIỮ CHỖ trong lô
    khungCum: undefined,      // GET /cum → khung_cum: tập cắt lô của mọi cụm (undefined = server cũ)
    cumLoc: "tat_ca",         // "tat_ca" | "chua" | <cum id> — bộ lọc thanh bên "Cụm của tôi"
    chiVaoBo: false,          // chip "Đã vào bộ": true ⇒ lưới CHỈ hiện video đã vào bộ; false ⇒ ẩn chúng
    tongVaoBo: undefined,     // GET /videos → tong_vao_bo: số trên chip (undefined = server cũ, tự đếm)
    luotNapVideo: 0,          // lượt `loadVideos` mới nhất — lượt cũ về trễ thì bỏ
    boHuyNap: null,           // AbortController của lượt nạp mới nhất (`batDauLuotNap`)
    phiaDaVe: undefined,      // phía chip mà lưới ĐANG thật sự vẽ (0/1; undefined = chưa vẽ lần nào)
    openStreams: new Map(),   // job_id -> EventSource đang theo dõi
    dangGuiChayLai: new Set(), // job_id đang chờ POST /jobs của nút "Chạy lại" — chặn bấm đôi qua các lần vẽ lại
    chayLai: new Map(),       // job_id -> số đang gõ trong ô "chạy lại kiếm thêm" (ô đang mở)
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
    for (const v of videoTrongNen()) {
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
    chip.textContent = `Đã vào bộ (${n})`;
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
  // Ném khi phiên Cloudflare Access đã hết hạn. Tách thành lớp riêng vì nó
  // cần một phản ứng khác hẳn mọi lỗi mạng: tải lại trang thì đăng nhập lại
  // được, còn thử lại ngầm thì không bao giờ khỏi.
  class PhienHetHan extends Error {}

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
      err.status = res.status;
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
    // Đang gõ số trong ô "chạy lại" thì KHÔNG vẽ lại: mỗi nhịp poll thay cả
    // `innerHTML` và ô mất focus giữa chừng. Dữ liệu vẫn nạp vào `state.jobs`;
    // hàng đợi vẽ lại ở nhịp poll đầu tiên sau khi rời ô. (Không vẽ lại ngay
    // lúc `focusout`: bấm nút "Chạy lại" làm ô mất focus TRƯỚC khi click tới,
    // vẽ lại lúc đó thay mất nút và làm mất cú bấm.)
    const dangGo = document.activeElement;
    if (dangGo && dangGo.classList && dangGo.classList.contains("chay-lai-n") && list.contains(dangGo)) return;
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
  //
  // Hai nhãn (`bao-thieu.js::nhanThieu`): "Nguồn hụt" khi nguồn cho ít hơn số
  // xin và không có lỗi hệ thống; "Thiếu" khi có lỗi hệ thống hoặc thiếu mà
  // nguồn không giải thích được.
  function nhanTrangThai(job) {
    const thieu = window.BaoThieu.nhanThieu(job);
    if (thieu) return thieu;
    return { chu: STATUS_LABEL[job.trang_thai] || job.trang_thai, lop: job.trang_thai };
  }

  function renderQueueItem(job) {
    // Mẫu số là số DÒ ĐƯỢC, không phải số xin: xong 87/88 là đã tải hết nguồn,
    // không phải mới tải 62% (`bao-thieu.js::mauSo`).
    const BT = window.BaoThieu;
    const pct = BT.phanTram(job);
    // Đỏ CHỈ cho lỗi hệ thống; lỗi phía TikTok có khung xám riêng.
    const hasErrors = BT.coLoiHeThong(job);
    // Có cờ sự cố hàng loạt thì câu "chạy lại có thể ra thêm" (chỉ ba mã chạy lại
    // được) mâu thuẫn với khung đỏ nên bị ẩn; câu của mã khác giữ nguyên.
    const stopText = job.ly_do_dung && !window.BaoThieu.anCauDung(job)
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
    // Đã có dòng nguồn (`dongNguon`) thì con số này nằm ở đó; chỉ còn cần khi
    // lượt đang chạy và dòng nguồn chưa hiện.
    const nguonText = BT.dongNguon(job);
    const skipText = boQua > 0 && !nguonText
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
          <span>${BT.chuTienDo(job)}</span>
        </div>
        ${nguonText ? `<div class="nguon">${nguonText}</div>` : ""}
        ${skipText ? `<div class="skip-note">${skipText}</div>` : ""}
        ${BT.khungLoi(job)}
        ${stopText ? `<div class="stop-reason">${stopText}</div>` : ""}
        ${BT.khungHanhDong(job, state.chayLai.has(job.id) ? state.chayLai.get(job.id) : null,
          state.dangGuiChayLai.has(job.id))}
        ${queueLine(job)}
        <div class="job-meta">${escapeHtml(job.nguoi_tao)} · ${fmtDateTime(job.tao_luc)}${driveLink ? " · " + driveLink : ""}
          · <button type="button" class="chia-link" data-chia="${job.id}">Chia cụm</button></div>
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
  // ---- Phân trang thư viện (user 23/09: "phân ra theo trang 10/20/40/100";
  // 26/09 thêm 30: "thêm phần 30 video/page").
  // `loadVideos` đã nạp TRỌN thư viện (lô `LIBRARY_PAGE`, trần `LIBRARY_MAX` mỗi phía chip), bộ lọc chạy ở đây ⇒
  // phân trang cắt trên danh sách ĐÃ LỌC, không cần tham số trang ở API.
  const SO_MOI_TRANG = Object.freeze([10, 20, 30, 40, 100]);
  const SO_MOI_TRANG_MAC_DINH = 40;

  // Hàm thuần — test gọi thẳng. `trang` 1-based; kẹp vào [1, soTrang] để một
  // trang cũ (vd trang 3 khi bộ lọc chỉ còn 5 video) không ra lưới rỗng.
  function catTrang(danhSach, trang, soMoiTrang) {
    const soTrang = Math.max(1, Math.ceil(danhSach.length / soMoiTrang));
    const t = Math.min(Math.max(1, trang), soTrang);
    const dau = (t - 1) * soMoiTrang;
    const muc = danhSach.slice(dau, dau + soMoiTrang);
    return { trang: t, soTrang, dau, muc };
  }

  const KHOA_SO_MOI_TRANG = "videodl-per-page";
  function docSoMoiTrang() {
    try {
      const n = Number(localStorage.getItem(KHOA_SO_MOI_TRANG));
      return SO_MOI_TRANG.includes(n) ? n : SO_MOI_TRANG_MAC_DINH;
    } catch (e) { return SO_MOI_TRANG_MAC_DINH; }  // private mode
  }

  // Dải nút trang THU GỌN: 1 … t-2..t+2 … cuối. Trần nạp 5000 ở 10/trang là
  // 500 trang — in đủ 500 nút là thanh điều hướng dài hơn cả lưới.
  function dayTrang(t, soTrang) {
    const giu = new Set([1, soTrang]);
    for (let i = t - 2; i <= t + 2; i++) if (i >= 1 && i <= soTrang) giu.add(i);
    const ds = [...giu].sort((a, b) => a - b);
    const ra = [];
    ds.forEach((n, i) => { if (i && n - ds[i - 1] > 1) ra.push("…"); ra.push(n); });
    return ra;
  }

  function veNutChonTrang() {
    const nut = document.getElementById("chon-trang");
    if (!nut) return;
    const ids = state.idTrang;
    const du = ids.length > 0 && ids.every((id) => state.selected.has(id));
    nut.textContent = du ? "☑ Bỏ chọn trang này" : `☐ Chọn tất cả trang này (${ids.length})`;
    nut.classList.toggle("on", du);
  }

  function vePhanTrang(ct, tongLoc) {
    const toolbar = document.getElementById("lib-toolbar");
    const pager = document.getElementById("lib-pager");
    toolbar.hidden = pager.hidden = tongLoc === 0;
    if (tongLoc === 0) return;
    const nav = ct.soTrang === 1 ? "" :
      `<button type="button" data-trang="${ct.trang - 1}" ${ct.trang === 1 ? "disabled" : ""}>‹ Trước</button>` +
      dayTrang(ct.trang, ct.soTrang).map((n) => n === "…" ? `<span class="gian">…</span>` :
        `<button type="button" data-trang="${n}" class="${n === ct.trang ? "on" : ""}"` +
        `${n === ct.trang ? ' aria-current="page"' : ""}>${n}</button>`).join("") +
      `<button type="button" data-trang="${ct.trang + 1}" ${ct.trang === ct.soTrang ? "disabled" : ""}>Sau ›</button>`;
    document.querySelectorAll("[data-pager]").forEach((el) => { el.innerHTML = nav; });
    document.getElementById("so-moi-trang").innerHTML = SO_MOI_TRANG.map((n) =>
      `<button type="button" data-so="${n}" class="${n === state.soMoiTrang ? "on" : ""}">${n}</button>`).join("");
    document.getElementById("lib-pager-dem").textContent =
      `Hiện ${ct.dau + 1}–${ct.dau + ct.muc.length} / ${tongLoc} video`;
    veNutChonTrang();
  }

  // Đổi trang / đổi số mỗi trang GIỮ lựa chọn (user 26/09: "khi tôi chọn tôi mở
  // qua trang mới không bị mất chọn"; đổi số/trang: "giữ"). Bản 23/09 xoá lựa chọn
  // vì người ta không thấy thẻ đã chọn ở trang kia — cái giá đó giờ trả bằng
  // CON SỐ: thanh chọn nói bao nhiêu video đã chọn KHÔNG hiện ở trang này (ở
  // trang khác, hoặc đang bị bộ lọc ẩn — bộ lọc vốn giữ lựa chọn), và Xoá / Đưa
  // vào cụm nhắc lại con số đó trước khi chạy. "Tạo bộ tự tìm" không hỏi: nó
  // không ghi gì, và Creative Desk hiện đủ danh sách trước khi tạo bộ.
  // "Chọn tất cả" vẫn chỉ là trang đang xem.
  //
  // Hàm thuần — test gọi thẳng.
  function demNgoaiTrang(selected, idTrang) {
    const trang = new Set(idTrang);
    let n = 0;
    for (const id of selected) if (!trang.has(id)) n++;
    return n;
  }

  function nhanNgoaiTrang(soNgoai) {
    return soNgoai > 0 ? `· ${soNgoai} không hiện ở trang này` : "";
  }

  // Dòng chèn vào hộp xác nhận của thao tác hàng loạt; rỗng khi mọi video đã
  // chọn đang nằm trên màn hình.
  function dongNgoaiTrang(soNgoai) {
    return soNgoai > 0
      ? `\n\nTrong đó ${soNgoai} video không hiện ở trang này (ở trang khác hoặc đang bị bộ lọc ẩn).`
      : "";
  }

  function doiTrang(n) {
    if (n === state.trang) return;
    state.trang = n;
    renderLibrary();
    document.getElementById("library-count").scrollIntoView({ block: "start" });
  }

  function doiSoMoiTrang(n) {
    if (n === state.soMoiTrang || !SO_MOI_TRANG.includes(n)) return;
    state.soMoiTrang = n;
    state.trang = 1;
    try { localStorage.setItem(KHOA_SO_MOI_TRANG, String(n)); } catch (e) { /* private mode */ }
    renderLibrary();
  }

  function chonTrangNay() {
    const ids = state.idTrang;
    const du = ids.length > 0 && ids.every((id) => state.selected.has(id));
    ids.forEach((id) => (du ? state.selected.delete(id) : state.selected.add(id)));
    document.querySelectorAll("#card-grid .card").forEach((c) => {
      const chon = state.selected.has(c.dataset.videoId);
      c.classList.toggle("selected", chon);
      c.setAttribute("aria-checked", String(chon));
    });
    renderSelectionBar();
    veNutChonTrang();
  }

  // Đổi BỘ LỌC ⇒ về trang 1 nhưng GIỮ lựa chọn (điều phối chốt 14:50): bộ lọc vốn
  // đã giữ lựa chọn trước khi có phân trang, không đổi hành vi đó ở đây.
  function sauKhiDoiBoLoc() {
    state.trang = 1;
    renderFilterBar();
    renderLibrary();
  }

  function renderLibrary() {
    const grid = document.getElementById("card-grid");
    const emptyState = document.getElementById("empty-state");
    const noMatch = document.getElementById("no-match-state");

    veChipVaoBo();
    // "Thư viện chưa có video nào" chỉ khi CẢ HAI phía chip đều rỗng. Lưới chỉ nạp
    // một phía: phía này rỗng mà phía kia có (chip bật mà chưa video nào vào bộ,
    // hoặc mọi video đều đã vào bộ) là "không khớp bộ lọc", như trước.
    if (state.videos.length === 0 && !state.chiVaoBo && !(state.tongVaoBo > 0)) {
      emptyState.hidden = false;
      noMatch.hidden = true;
      grid.hidden = true;
      grid.innerHTML = "";
      state.idTrang = [];
      renderSelectionBar();
      vePhanTrang(null, 0);
      renderCumRail();
      renderCumHead();
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
    // Mẫu số "x/N" là tập đang hiện theo chip (không gồm video đã vào bộ khi chip tắt):
    // video ẩn theo thiết kế không phải "bị bộ lọc loại".
    const nen = videoTrongNen().length;
    const parts = [];
    parts.push(filtered.length === nen ? `${nen}` : `${filtered.length}/${nen}`);
    parts.push(state.chiVaoBo ? "video đã vào bộ" : "video");
    if (loaded < total) parts.push(`(đang hiện ${loaded} trong ${total})`);
    document.getElementById("library-count").textContent = parts.join(" ");

    noMatch.hidden = filtered.length > 0;
    grid.hidden = filtered.length === 0;
    const ct = catTrang(filtered, state.trang, state.soMoiTrang);
    state.trang = ct.trang;  // kẹp: bỏ video / đổi lọc có thể làm trang cũ vượt quá
    state.idTrang = ct.muc.map((v) => v.video_id);
    renderSelectionBar();  // "· N ở trang khác" đổi theo trang đang xem
    grid.innerHTML = ct.muc.map(renderCard).join("");
    vePhanTrang(ct, filtered.length);
    wireThumbFallback();
    renderActiveFilters();
    renderCumRail();
    renderCumHead();
  }

  // Ngày (không giờ) theo múi giờ của trình duyệt; rỗng nếu không đọc được.
  function fmtNgay(iso) {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? escapeHtml(d.toLocaleDateString("vi-VN")) : "";
  }

  // Huy hiệu mã bộ + ngày sẽ xoá khỏi Video Desk cho video đã vào bộ. Nhiều bộ ⇒ một
  // huy hiệu "N.2809C · N.2909B". Nguồn sự thật về bộ là folder id ở server; đây chỉ hiện.
  function renderBoDaVao(b) {
    if (!b) return "";
    const ma = b.ma_bo && b.ma_bo.length ? b.ma_bo.map(escapeHtml).join(" · ") : "Đã vào bộ";
    const ngay = fmtNgay(b.se_don_luc);
    return `<div class="card-bo"><span class="bo-ma" title="Mã bộ tự tìm">${ma}</span>` +
      (ngay ? `<span class="bo-don">Xoá khỏi Video Desk ${ngay}</span>` : "") + `</div>`;
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
          ${renderBoDaVao(video.vao_bo)}
          ${video.url
            ? `<a class="card-link" href="${escapeHtml(video.url)}" target="_blank" rel="noopener" data-video-link>Xem gốc ↗</a>`
            : `<span class="card-link card-link-trong">chưa rõ link gốc</span>`}
          ${chipCum(video)}
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
    if (bar.hidden) { const pop = document.getElementById("cum-popover"); if (pop) pop.hidden = true; }
    document.getElementById("selection-count").textContent = `${state.selected.size} đã chọn`;
    const ngoai = document.getElementById("selection-ngoai");
    if (ngoai) ngoai.textContent = nhanNgoaiTrang(demNgoaiTrang(state.selected, state.idTrang));
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

  // Chạy lại để kiếm thêm + chép link. Cùng lý do uỷ quyền như "Rút lượt".
  const queueList = document.getElementById("queue-list");
  queueList.addEventListener("input", (ev) => {
    const o = ev.target.closest("[data-chay-lai-n]");
    if (o) state.chayLai.set(Number(o.dataset.chayLaiN), o.value);
  });
  queueList.addEventListener("click", async (ev) => {
    const nut = ev.target.closest("[data-chay-lai],[data-chay-lai-ok],[data-chay-lai-huy],[data-chep-link]");
    if (!nut) return;
    const id = Number(nut.dataset.chayLai ?? nut.dataset.chayLaiOk ?? nut.dataset.chayLaiHuy ?? nut.dataset.chepLink);
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return;
    if (nut.dataset.chepLink !== undefined) {
      try {
        await navigator.clipboard.writeText(job.url);
        showToast("Đã chép link.");
      } catch (e) {
        showToast("Không chép được — chọn và copy tay.");
      }
    } else if (nut.dataset.chayLai !== undefined) {
      state.chayLai.set(id, window.BaoThieu.soChayLai(job));
      renderQueue();
      const o = queueList.querySelector(`[data-chay-lai-n="${id}"]`);
      if (o) o.focus();
    } else if (nut.dataset.chayLaiHuy !== undefined) {
      state.chayLai.delete(id);
      renderQueue();
    } else {
      const n = window.BaoThieu.chuanHoaSoChayLai(state.chayLai.get(id));
      if (n === null) {
        showToast(`Số video phải từ 1 đến ${window.BaoThieu.MAX_SO_LUONG}.`);
        return;
      }
      // `disabled` đặt tay lên nút sẽ MẤT ở lần vẽ lại kế tiếp (poll/SSE thay
      // `innerHTML`), nên cờ sống ở `state` và cả lần vẽ lẫn lần bấm đều đọc nó.
      if (state.dangGuiChayLai.has(id)) return;
      state.dangGuiChayLai.add(id);
      renderQueue();
      try {
        // Đúng đường tạo lượt của form: một POST /jobs, không route riêng.
        // Mang theo usecase / insight gốc của lượt gốc: chạy lại là CÙNG một
        // việc, và bỏ hai ô này thì màn nháp duyệt kiểu hỏi lại từ đầu.
        const kq = await guiTaoJob(taoJobBody(job.url, n, job.usecase, job.insight_goc));
        if (kq.ok) {
          state.chayLai.delete(id);
          showToast(`Đã tạo lượt mới kiếm thêm ${n} video.`);
        } else {
          showToast(kq.loi);
        }
      } finally {
        state.dangGuiChayLai.delete(id);
        renderQueue();
      }
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
    sauKhiDoiBoLoc(); // cập nhật badge số lượng trên nút + về trang 1
  });

  // Đổi phía chip = nạp lại thư viện phía đó (server lọc). Lựa chọn ở phía kia
  // rơi và được nói ra (`loadVideos`) — giữ id ngoài tập đã nạp là mở đường Xoá mù.
  //
  // Chip đổi trạng thái NGAY; lưới giữ nội dung cũ, đánh dấu đang nạp
  // (`aria-busy`, `data-nap-phia` rỗng) và chỉ vẽ lại khi phía mới về — vẽ ngay
  // thì lưới nháy "không khớp bộ lọc" trên tập của phía kia.
  function doiPhiaVaoBo(chiVaoBo) {
    if (state.chiVaoBo === chiVaoBo) return Promise.resolve();
    state.chiVaoBo = chiVaoBo;
    state.trang = 1;
    veChipVaoBo();
    const grid = document.getElementById("card-grid");
    grid.setAttribute("aria-busy", "true");
    grid.dataset.napPhia = "";
    // Nạp hỏng thì `loadVideos` tự đưa chip/lưới về phía đã vẽ; ở đây chỉ báo.
    return napLaiThuVien({ lyDoRoi: "vì đang xem phía khác của chip “Đã vào bộ”" });
  }

  document.getElementById("chip-vao-bo").addEventListener("click", () => {
    doiPhiaVaoBo(!state.chiVaoBo);
  });

  document.getElementById("active-filters").addEventListener("click", (ev) => {
    if (ev.target.id === "clear-all-pill") {
      for (const g of FILTER_GROUPS) state.filters[g.id].clear();
      sauKhiDoiBoLoc();
      return;
    }
    const btn = ev.target.closest("[data-remove-group]");
    if (btn) {
      state.filters[btn.dataset.removeGroup].delete(btn.dataset.removeKey);
      sauKhiDoiBoLoc();
    }
  });

  document.getElementById("clear-filters-btn").addEventListener("click", () => {
    for (const g of FILTER_GROUPS) state.filters[g.id].clear();
    state.cumLoc = "tat_ca";
    if (state.chiVaoBo) {
      renderFilterBar();   // huy hiệu số trên nút nhóm — lưới vẽ lại khi phía 0 về
      doiPhiaVaoBo(false);
    } else sauKhiDoiBoLoc();
  });

  function dongPopoverCum() {
    const pop = document.getElementById("cum-popover");
    if (pop) pop.hidden = true;
  }
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".filter-box")) closeAllFilterPanels(null);
    if (!ev.target.closest(".pop-wrap")) dongPopoverCum();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { closeAllFilterPanels(null); dongPopoverCum(); }
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
    veNutChonTrang();
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
    if (action === "cum") {
      const pop = document.getElementById("cum-popover");
      // Mở hộp gán cụm khi có video đã chọn ở trang khác ⇒ hỏi trước, nêu số.
      const ngoai = demNgoaiTrang(state.selected, state.idTrang);
      if (pop.hidden && ngoai > 0 && !window.confirm(
        `Đưa ${state.selected.size} video vào cụm?${dongNgoaiTrang(ngoai)}`)) return;
      pop.hidden = !pop.hidden;
      renderPopoverCum();
    }
  });

  // Uỷ quyền trên vùng cha vì thanh bên, đầu cụm và ô popover đều vẽ lại sau
  // mỗi lần lọc — gắn thẳng lên nút thì nút mới vẽ ra sẽ câm.
  document.getElementById("cum-popover").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-gan-cum]");
    if (b) ganVaoCumCoSan(Number(b.dataset.ganCum));
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.closest(".cum-form")) capNhatXemTruoc(ev.target.closest(".cum-form").parentElement);
  });
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest(".cum-form");
    if (!f) return;
    ev.preventDefault();
    guiFormCum(f);
  });
  document.getElementById("cum-rail").addEventListener("click", (ev) => {
    const hang = ev.target.closest("[data-cum-loc]");
    if (hang) {
      const loc = hang.dataset.cumLoc;
      doiCumLoc(loc === "tat_ca" || loc === "chua" ? loc : Number(loc));
      return;
    }
    if (ev.target.closest("[data-cum-moi]")) {
      const f = document.getElementById("cum-moi-form");
      f.hidden = !f.hidden;
      capNhatXemTruoc(f);
    }
  });
  document.getElementById("cum-head").addEventListener("click", (ev) => {
    const cum = state.cums.find((c) => c.id === state.cumLoc);
    if (!cum) return;
    const lo = ev.target.closest("[data-mo-lo]");
    if (lo) {
      moLoCum(cum.id, Number(lo.dataset.moLo)).then((kq) => {
        if (kq === "chan") showToast("Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại.");
      }).catch((err) => {
        // Không được để lỗi rơi thành unhandled rejection câm — mọi nhánh lỗi
        // mong đợi đã tự báo toast BÊN TRONG `moLoCum`; nhánh này chỉ còn bắt
        // cái GÌ ĐÓ không lường trước.
        if (err instanceof PhienHetHan) baoPhienHetHan();
        else showToast(`Lỗi không lường trước khi mở Creative Desk: ${err.message || err}`);
      });
      return;
    }
    if (ev.target.closest("[data-mo-het]")) {
      moHetLoCum(cum.id).catch((err) => {
        if (err instanceof PhienHetHan) baoPhienHetHan();
        else showToast(`Lỗi không lường trước khi mở Creative Desk: ${err.message || err}`);
      });
      return;
    }
    if (ev.target.closest("[data-doi-kieu]")) { doiKieuCum(cum); return; }
    if (ev.target.closest("[data-xoa-cum]")) xoaCum(cum);
  });

  // Bỏ chọn một nhóm video, giữ nguyên phần còn lại của lựa chọn.
  function boChonCacVideo(ids) {
    ids.forEach((id) => state.selected.delete(id));
    document.querySelectorAll("#card-grid .card").forEach((c) => {
      const chon = state.selected.has(c.dataset.videoId);
      c.classList.toggle("selected", chon);
      c.setAttribute("aria-checked", String(chon));
    });
    renderSelectionBar();
    veNutChonTrang();
  }

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
    veNutChonTrang();
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
  //
  // Chọn tay (26/09): gửi danh sách qua `postMessage` thay vì query string, để
  // chọn bao nhiêu cũng được và Creative Desk tự chia bộ. Đường của CỤM vẫn đi
  // qua URL (`moLoCum`) — hợp đồng `nhan` không đổi.
  // Tệp nguồn của video này đã chết / sắp bị dọn? Đúng khi server đánh dấu `da_don`
  // (đã vào Thùng rác) hoặc `vao_bo.se_don_luc` ≤ `bayGio` (đã quá hạn 7 ngày — lượt dọn
  // sắp lấy tệp đi). Gửi một item như thế sang Creative Desk là gửi một file sắp không
  // còn để copy; và bên nhận bỏ CẢ LÔ khi một item hỏng. Hàm thuần — test gọi thẳng.
  function nguonDaChet(v, bayGio) {
    if (v.da_don) return true;
    const han = v.vao_bo && v.vao_bo.se_don_luc ? Date.parse(v.vao_bo.se_don_luc) : NaN;
    return !Number.isNaN(han) && han <= bayGio;
  }

  async function moBoTuTim() {
    if (state.dangBanGiao) return;  // bấm đúp khi đang chờ ack ⇒ bỏ qua
    const daChon = state.videos.filter((v) => state.selected.has(v.video_id));
    // Video chưa lên Drive thì KHÔNG có gì để copy. Bỏ chúng TRƯỚC khi gửi và
    // nói ra số bị bỏ — để số video mỗi bộ bên kia đếm trên đúng thứ sẽ copy.
    const chuaLenDrive = daChon.filter((v) => !v.drive_file_id);
    const coDrive = daChon.filter((v) => v.drive_file_id);
    // Bên nhận bỏ CẢ LÔ, không ack, khi chỉ một item sai luật — người dùng sẽ
    // chờ trọn hạn ack. Lọc trước theo đúng luật đó và nói ra số bị bỏ.
    // Nguồn đã chết/quá hạn dọn: bỏ TRƯỚC, nói ra số bị bỏ (server cũng kiểm lại ở đường lô).
    const bayGio = Date.now();
    const nguonChet = coDrive.filter((v) => nguonDaChet(v, bayGio));
    const conSong = coDrive.filter((v) => !nguonDaChet(v, bayGio));
    const guiDuoc = conSong.filter(itemHopLeBenNhan);
    const khongHopLe = conSong.length - guiDuoc.length;
    const items = guiDuoc.map(itemBanGiao);

    if (!items.length) {
      showToast("Chưa có gì để gửi sang Creative Desk: " + [
        chuaLenDrive.length ? `${chuaLenDrive.length} video chưa lên Drive` : "",
        nguonChet.length ? `${nguonChet.length} video đã quá hạn giữ tệp nguồn` : "",
        khongHopLe ? `${khongHopLe} video thiếu link gốc hợp lệ` : "",
      ].filter(Boolean).join(", ") + ".");
      return;
    }
    if (items.length > MAX_PM_ITEMS) {
      showToast(`Chọn tối đa ${MAX_PM_ITEMS} video cho một lần tạo bộ.`);
      return;
    }

    // Mỗi lần bấm là MỘT tab mới với `?videodesk_pm=1`. Không gửi lại vào tab của
    // lần trước: Creative Desk chuyển người chưa đăng nhập sang `/login` và KHÔNG
    // giữ URL quay lại (`creative-order/layout.tsx` `router.replace("/login")`),
    // nên sau khi đăng nhập tab cũ không còn tham số đó và không bao giờ nghe tin.
    // id sinh TRƯỚC khi mở tab: `crypto.randomUUID` chỉ có ở ngữ cảnh an toàn,
    // ném lỗi sau khi đã mở tab là để lại một tab mồ côi không ai gửi tin tới.
    const id = crypto.randomUUID();
    const tab = moTabCreativeDesk(`${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk_pm=1`);
    if (!tab) {
      showToast("Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại. " +
                "Lựa chọn của bạn vẫn còn.");
      return;
    }
    // Số bị bỏ đi KÈM mọi thông báo kết quả — toast riêng sẽ bị toast sau đè mất.
    const boLai = [
      chuaLenDrive.length ? `${chuaLenDrive.length} video chưa lên Drive` : "",
      nguonChet.length ? `${nguonChet.length} video đã quá hạn giữ tệp nguồn` : "",
      khongHopLe ? `${khongHopLe} video thiếu link gốc hợp lệ` : "",
    ].filter(Boolean).join(", ");
    const ghiChuBoLai = boLai ? ` (${boLai} nên không gửi kèm.)` : "";

    datNutBanGiao(true);
    state.dangBanGiao = true;
    let kq;
    try {
      kq = await guiBanGiaoPm(tab, { type: "videodesk-handoff", v: 2, id, items },
                              PM_HAN_MS, PM_CHU_KY_MS);
    } finally {
      state.dangBanGiao = false;
      datNutBanGiao(false);
    }

    // Bỏ chọn CHỈ khi bên kia xác nhận đã nhận VÀ đã lưu (`ok: true`). Trước đó
    // chưa có gì được bàn giao cả — xoá lựa chọn là bắt người dùng chọn lại vì
    // một việc CHƯA xảy ra.
    if (kq.ket === "ack") {
      // Chỉ bỏ chọn đúng những video ĐÃ gửi: video chưa lên Drive / thiếu link
      // vẫn giữ tick để người dùng thấy chúng chưa đi đâu cả.
      boChonCacVideo(guiDuoc.map((v) => v.video_id));
      showToast(`Đã gửi ${items.length} video sang Creative Desk — chia bộ và bấm tạo ở tab đó.${ghiChuBoLai}`);
      return;
    }
    showToast({
      tu_choi: `Creative Desk không nhận được danh sách${kq.lyDo ? ` (${kq.lyDo})` : ""}. Lựa chọn vẫn còn.`,
      het_han: "Creative Desk chưa xác nhận sau 30 giây. Nếu tab đó bắt đăng nhập: đăng nhập " +
               "xong, đóng tab đó rồi bấm “Tạo bộ tự tìm” lần nữa. Lựa chọn vẫn còn.",
      tab_dong: "Tab Creative Desk đã đóng trước khi nhận — bấm lại để mở tab mới. Lựa chọn vẫn còn.",
    }[kq.ket]);
  }

  function datNutBanGiao(dangGui) {
    const nut = document.querySelector('[data-action="self-bundle"]');
    if (!nut) return;
    nut.disabled = dangGui;
    nut.textContent = dangGui ? "Đang gửi sang Creative Desk…" : "Tạo bộ tự tìm";
  }

  // Gửi `tin` sang `tab` mỗi `chuKyMs` tới khi có ack đúng `id` từ đúng origin
  // Creative Desk, tab đóng, hoặc hết `hanMs`. Trả {ket: "ack"|"tu_choi"|
  // "het_han"|"tab_dong", lyDo?}. targetOrigin CỐ ĐỊNH: trang lạ lọt vào tab
  // (chuyển hướng, gõ tay) không đọc được danh sách.
  function guiBanGiaoPm(tab, tin, hanMs, chuKyMs) {
    return new Promise((xong) => {
      let hetLuc = null, nhip = null;
      const ket = (r) => {
        clearInterval(nhip);
        clearTimeout(hetLuc);
        window.removeEventListener("message", nghe);
        xong(r);
      };
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
      hetLuc = setTimeout(() => ket({ ket: "het_han" }), hanMs);
      nhip = setInterval(gui, chuKyMs);
      gui();
    });
  }

  // ========================================================================
  // BÀN GIAO sang Creative Desk (hợp đồng `nhan`,
  // plans/260923-1558-tai-theo-cum/hop-dong-nhan.md). Hai đường KHÔNG dùng
  // chung hàm dựng item: nút chọn tay (`moBoTuTim`) tự dựng item bằng
  // `itemBanGiao` + lọc `itemHopLeBenNhan` rồi gửi qua `postMessage`; nút lô
  // của cụm (`moLoCum`) nhận payload DỰNG SẴN ở server
  // (`GET /cum/{id}/lo/{thu}/payload`, `models_chia.xay_payload_lo`, cùng
  // luật lọc) rồi chỉ mã hoá vào URL bằng `maHoaPayload`/`urlBanGiao`.
  // ========================================================================
  function itemBanGiao(v) {
    return { f: v.drive_file_id, n: v.title || v.video_id, u: v.url };
  }

  // Cùng luật với bên nhận (meta-ads `frontend/src/lib/videodesk-handoff.ts`
  // `parseVideodeskHandoffItem`): Drive id `[A-Za-z0-9_-]{10,128}`, link gốc
  // http(s). Tên không cần kiểm — bên nhận tự cắt ở 200 ký tự.
  function itemHopLeBenNhan(v) {
    // Kiểm KIỂU trước: bên nhận đòi đúng chuỗi, không ép kiểu — một id dạng số
    // qua được regex sau `String()` nhưng vẫn bị bên nhận bỏ.
    return typeof v.drive_file_id === "string" && /^[A-Za-z0-9_-]{10,128}$/.test(v.drive_file_id) &&
           typeof v.url === "string" && /^https?:\/\//i.test(v.url);
  }

  // `nhan` CHỈ có khi bàn giao từ cụm; `null` ⇒ không có khoá đó (quy tắc 1-2).
  // Không đường nào trong trang còn gọi hàm này (payload của cụm dựng ở
  // server): chỉ các harness `tests/js/*.js` trích nó ra để dựng payload đối
  // chứng — giữ vì các test đó phụ thuộc vào nó.
  function dungPayload(items, nhan) {
    const p = { v: 1, items };
    if (nhan) p.nhan = nhan;
    return p;
  }

  // base64url: payload đi trong URL nên `+` `/` `=` đều phải biến mất.
  // `TextEncoder` trước `btoa` vì tiêu đề video có tiếng Việt và emoji —
  // `btoa` một mình ném `InvalidCharacterError` ở ký tự ngoài Latin-1.
  function maHoaPayload(p) {
    return btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(p))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function urlBanGiao(p) {
    return `${CREATIVE_DESK_URL}/creative-order/self-bundles?videodesk=${maHoaPayload(p)}`;
  }

  // Mở tab TRỐNG ngay (đồng bộ, trong CHÍNH lượt xử lý click) và trả tab, hoặc
  // `null` khi trình duyệt chặn popup.
  //
  // TÁCH mở-tab khỏi điền-địa-chỉ. `window.open` phải chạy trước bất kỳ
  // `await` nào — Chromium chỉ giữ "user activation" khoảng 5s sau cú bấm, và
  // Safari còn khắt khe hơn (chặn NGAY một `window.open` chạy sau `await`, kể
  // cả trong 5s). Mở "về sau mới biết URL" thì phải mở TRỐNG trước, gán địa
  // chỉ sau — `dieuHuongTab` làm phần sau.
  //
  // KHÔNG truyền "noopener" vào `window.open`: với cờ đó trình duyệt LUÔN trả
  // `null` dù tab đã mở (đo trên Chromium 23/09) — mọi phép kiểm "tab có mở
  // không" phía sau sẽ đọc thành "bị chặn". Cắt `opener` bằng tay thay cho cờ.
  function moTabTrong() {
    const tab = window.open("about:blank", "_blank");
    if (tab) {
      try {
        tab.opener = null;
      } catch (e) {
        // Nhánh này chạy ⇒ opener KHÔNG bị cắt: tab Creative Desk vẫn với tới
        // được trang này qua `window.opener`. Tab đã mở và bàn giao vẫn đi,
        // nên vẫn trả `tab` — nhưng nói ra, đừng nuốt im.
        console.warn("Không cắt được window.opener của tab Creative Desk — tab vẫn mở, opener CÒN nguyên:", e);
      }
    }
    return tab;
  }

  // Điền địa chỉ THẬT vào một tab đã mở trống (`moTabTrong`) — phần "sau khi
  // đã biết URL", tách khỏi phần "mở tab" ở trên.
  function dieuHuongTab(tab, url) {
    tab.location = url;
  }

  // Mở tab Creative Desk NGAY VỚI url đã biết (đường chọn tay, `moBoTuTim` —
  // đồng bộ hoàn toàn, không có `await` nào giữa cú bấm và đây). CỐ Ý mở
  // THẲNG bằng url thật thay vì `moTabTrong` + `dieuHuongTab`: đặt
  // `tab.location =` NGAY sau `window.open("about:blank",…)` không đồng bộ
  // với chính commit điều hướng của trình duyệt — `Page.url` phía Playwright
  // (và một số trình duyệt) có thể vẫn đọc ra "about:blank" nếu đọc quá sớm.
  // Đường này không có khoảng chờ nào để tách hai bước ra, nên mở thẳng một
  // lần là vừa an toàn vừa đơn giản hơn.
  function moTabCreativeDesk(url) {
    const tab = window.open(url, "_blank");
    if (tab) {
      try {
        tab.opener = null;
      } catch (e) {
        console.warn("Không cắt được window.opener của tab Creative Desk — tab vẫn mở, opener CÒN nguyên:", e);
      }
    }
    return tab;
  }

  // ========================================================================
  // CỤM CỦA TÔI — thanh bên, đầu cụm, chip trên thẻ, "Đưa vào cụm"
  // ========================================================================
  // Hàm thuần: tách danh sách thành lô ≤ `toiDa` (64 ⇒ 30/30/4; 0 ⇒ không lô).
  function chiaLo(ds, toiDa) {
    const ra = [];
    for (let i = 0; i < ds.length; i += toiDa) ra.push(ds.slice(i, i + toiDa));
    return ra;
  }

  // Nhãn "x/N" từ mốc đã mở `m`: `so_item` = số item THẬT đã gửi, `so_video`
  // = số video của lô LÚC ĐÓ (cùng một response payload, xem `moLoCum`). Chỉ
  // hiện "x/N" khi biết cả hai và x < N — video bị lọc vì chưa lên Drive/thiếu
  // link gốc hợp lệ; biết cả hai và x == N ⇒ N trơn CỦA LÚC MỞ (không bịa
  // "n/n"). Chỉ khi CHƯA biết cặp (mốc cũ/client cũ) mới rơi về `nHienTai`
  // (số video hiện tại của lô) — đếm phía trang có thể cũ hoặc lô đã đổi sau
  // khi mở, nên không bao giờ ghép nó với số đã gửi.
  function nhanSoVideo(m, nHienTai) {
    const x = m && m.so_item, n = m && m.so_video;
    if (typeof x !== "number" || typeof n !== "number") return `${nHienTai}`;
    return x < n ? `${x}/${n}` : `${n}`;
  }

  // Khoá so trùng cụm: trim + gộp khoảng trắng + không phân biệt hoa/thường.
  function khoaNhan(s) {
    return String(s || "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  }

  // Cụm có sẵn trùng (usecase, insight gốc, kiểu) theo `khoaNhan`, hoặc null.
  // "Couple" và "couple" là MỘT cụm — tạo hai là tạo hai insight trùng bên kia.
  // Cùng khoá với server (`models_cum._khoa_ten`): usecase + insight CON — thứ
  // Creative Desk nhìn thấy. Đây chỉ là gợi ý sớm cho ô xem trước; server mới
  // là bên quyết (POST /cum trả lại cụm có sẵn khi trùng).
  function timCumTrung(dsCum, usecase, goc, kieu) {
    const k = [khoaNhan(usecase), khoaNhan(xemTruocTen(goc, kieu))].join("\u0000");
    return dsCum.find((c) =>
      [khoaNhan(c.usecase), khoaNhan(c.insight)].join("\u0000") === k) || null;
  }

  // CHỈ để xem trước tên trong ô "cụm mới" — cụm chưa tồn tại nên chưa có
  // `insight` từ server. Cụm đã tạo thì mọi nơi đọc `cum.insight`.
  function xemTruocTen(goc, kieu) {
    return `${goc} ${kieu}`.split(/\s+/).filter(Boolean).join(" ");
  }

  // Video của cụm, CŨ trước: video mới đưa vào nối vào lô cuối thay vì xô lệch
  // Bộ 1/n đã mở. ⚠ Giới hạn đã biết (điều phối chốt 23/09): mốc "đã mở" gắn
  // theo SỐ THỨ TỰ lô; thêm/bớt video làm ranh giới lô dịch đi, và đổi kiểu
  // cũng không xoá mốc cũ — không có cảnh báo "mở dưới tên cũ".
  //
  // Có ngoại lệ ĐÃ CHẶN: video được DỌN khỏi Drive (ngày 7 sau khi vào bộ) KHÔNG
  // làm lô trượt. Chúng không nằm trong `state.videos` (không hiện ở đâu) nhưng
  // vẫn GIỮ CHỖ ở đây, đánh dấu `da_don: true` — cùng tập với server cắt lô
  // (`models_chia._video_trong_lo`, video cũ nhất trước theo (tao_luc, video_id)).
  // Người dùng của hàm này tự bỏ chúng khi đếm video còn sống / gửi đi.
  //
  // Server có `khung_cum` (`GET /cum`) ⇒ cắt từ khung đó: MỌI thành viên của
  // cụm, đúng thứ tự server, kể cả video cũ nằm ngoài `LIBRARY_MAX` video mới
  // nhất đã nạp (không có khung thì các video đó rơi khỏi lô ⇒ lô trượt). Giữ
  // NGUYÊN thứ tự khung, không sắp lại. Đắp đối tượng đầy đủ từ `state.videos`
  // nếu có; không có thì dùng phần tử khung (người dùng chỉ đọc `.da_don` +
  // độ dài). Server cũ không trả khung ⇒ đường cũ bên dưới.
  function videoCuaCum(cumId) {
    if (Array.isArray(state.khungCum)) {
      const daNap = new Map(state.videos.map((v) => [v.video_id, v]));
      return state.khungCum.filter((g) => g.cum_id === cumId).map((g) => {
        const v = daNap.get(g.video_id);
        if (v && !g.da_don) return v;
        return { video_id: g.video_id, tao_luc: g.tao_luc, cum_id: g.cum_id, da_don: !!g.da_don };
      });
    }
    const song = state.videos.filter((v) => v.cum_id === cumId).reverse();
    const da = (state.videosDaDon || []).filter((g) => g.cum_id === cumId)
      .map((g) => ({ video_id: g.video_id, tao_luc: g.tao_luc, cum_id: g.cum_id, da_don: true }));
    if (!da.length) return song;
    return song.concat(da).sort((a, b) =>
      a.tao_luc < b.tao_luc ? -1 : a.tao_luc > b.tao_luc ? 1
        : a.video_id < b.video_id ? -1 : a.video_id > b.video_id ? 1 : 0);
  }

  function mauCum(id) { return `hsl(${(id * 67) % 360} 55% 50%)`; }

  function renderCumRail() {
    const rail = document.getElementById("cum-rail");
    if (!rail) return;
    const dem = new Map();
    let chua = 0;
    const nen = videoTrongNen();
    for (const v of nen) {
      if (v.cum_id == null) chua++; else dem.set(v.cum_id, (dem.get(v.cum_id) || 0) + 1);
    }
    const hang = (loc, nhan, n, lop = "") =>
      `<button type="button" class="cum-row ${lop}${state.cumLoc === loc ? " on" : ""}" data-cum-loc="${loc}">` +
      `${nhan}<span class="n">${n}</span></button>`;
    let h = `<h3>Cụm của tôi</h3>` + hang("tat_ca", "Tất cả", nen.length) +
      hang("chua", "Chưa vào cụm", chua, "chua") + `<hr class="rail-sep">`;
    if (!state.cums.length) {
      h += `<div class="rail-empty">Chưa có cụm nào. Chọn vài video cùng một kiểu (vd. cartoon) → bấm ` +
        `<b>Đưa vào cụm</b> ở thanh dưới → chọn <b>insight gốc</b> và gõ <b>kiểu</b>. ` +
        `Tên cụm = tên insight con bên Creative Desk.</div>`;
    }
    const nhom = new Map();
    for (const c of state.cums) {
      const k = `${c.usecase}\u0000${c.insight_goc}`;
      if (!nhom.has(k)) nhom.set(k, []);
      nhom.get(k).push(c);
    }
    for (const ds of nhom.values()) {
      const tong = ds.reduce((a, c) => a + (dem.get(c.id) || 0), 0);
      h += `<div class="ins-head"><b>${escapeHtml(ds[0].usecase)} › ${escapeHtml(ds[0].insight_goc)}</b>` +
        `<span class="n">${tong}</span></div>`;
      for (const c of ds) {
        h += hang(c.id, `<span class="cum-dot" style="background:${mauCum(c.id)}"></span>` +
          `<span class="cum-ten">${escapeHtml(c.insight)}</span>`, dem.get(c.id) || 0, "cum-sub");
      }
    }
    h += `<button type="button" class="rail-add" data-cum-moi>＋ Cụm mới</button>` +
      `<div id="cum-moi-form" hidden>${formCum("rail", 0)}</div>`;
    rail.innerHTML = h;
  }

  // Ô tạo cụm dùng chung cho thanh chọn ("Đưa vào cụm") và thanh bên ("Cụm mới").
  // Điền sẵn từ cụm đang xem, vì phân loại thường là nhiều kiểu dưới CÙNG một
  // insight gốc.
  function formCum(noi, soVideo) {
    const goc = state.cums.find((c) => c.id === state.cumLoc) || {};
    const o = (ten, nhan, gt) => `<label class="lb">${nhan}` +
      `<input data-cum-o="${ten}" value="${escapeHtml(gt || "")}" autocomplete="off" /></label>`;
    return `<form class="cum-form" data-noi="${noi}">` +
      `<h4>${soVideo ? `Đưa ${soVideo} video vào cụm mới` : "Cụm mới"}</h4>` +
      o("goc", "Insight gốc", goc.insight_goc) + o("usecase", "Usecase", goc.usecase) +
      o("kieu", "Kiểu", "") +
      `<div class="preview-name">Tên cụm = Insight con: <b data-xem-truoc></b></div>` +
      `<div class="lock-field">Template <b>Goc</b> 🔒 (video tải về)</div>` +
      `<button type="submit" class="btn primary ok">${soVideo ? `Tạo cụm và đưa ${soVideo} video vào` : "Tạo cụm"}</button>` +
      `</form>`;
  }

  function renderCumHead() {
    const head = document.getElementById("cum-head");
    if (!head) return;
    const cum = state.cums.find((c) => c.id === state.cumLoc);
    head.hidden = !cum;
    if (!cum) { head.innerHTML = ""; return; }
    const lo = chiaLo(videoCuaCum(cum.id), HANDOFF_MAX);
    const tong = lo.length;
    // Bất biến: lô cắt ở trang = số lô server đếm (`so_lo`, cùng response
    // `/cum`). Lệch (server cũ không có khung, thư viện > LIBRARY_MAX) ⇒ ghi lại
    // và nhãn "Bộ i/N" dùng N của server — server mới là bên dựng payload.
    const tongNhan = typeof cum.so_lo === "number" ? cum.so_lo : tong;
    if (tongNhan !== tong) console.warn(`cụm ${cum.id}: trang cắt ${tong} lô, server đếm ${cum.so_lo}`);
    // Video đã dọn giữ chỗ trong lô nhưng không tính vào "N video" của cụm.
    const nSong = (l) => l.filter((v) => !v.da_don).length;
    const n = lo.reduce((a, l) => a + nSong(l), 0);
    // Nhãn số video của một lô CHƯA mở: "x/N" khi lô đã hụt vì video được dọn.
    const nhanLoChuaMo = (l) => nSong(l) < l.length ? `${nSong(l)}/${l.length}` : `${l.length}`;
    // Chỉ VẼ mốc của lô còn tồn tại (`thu ≤ số lô`); mốc cũ vẫn nằm trong DB.
    // Giữ NGUYÊN hàng (không chỉ `mo_luc`) — cần cả `so_item` cho nhãn "x/N".
    const moLuc = new Map(cum.lo_mo.filter((m) => m.thu <= tong).map((m) => [m.thu, m]));
    const nut = n === 0 ? `<button type="button" class="btn primary" disabled>Tạo bộ tự tìm từ cụm này (0)</button>`
      : tong === 1 ? `<button type="button" class="btn primary" data-mo-lo="1">Tạo bộ tự tìm từ cụm này (${n})</button>`
      : `<button type="button" class="btn primary" data-mo-het>Tạo ${tong} bộ tự tìm (${lo.map(nhanLoChuaMo).join(" + ")})</button>`;
    const dsLo = tong > 1 ? `<div class="bo-list">${lo.map((l, i) => {
      const m = moLuc.get(i + 1);
      const nhanN = nhanSoVideo(m, nhanLoChuaMo(l));
      return `<div class="bo-row" data-lo="${i + 1}"><b>Bộ ${i + 1}/${tongNhan}</b><span>${nhanN} video</span>` +
        `<span class="muted">${m ? `đã mở Creative Desk lúc ${fmtDateTime(m.mo_luc)}` : "chưa mở"}</span><span class="grow"></span>` +
        `<button type="button" class="btn ghost" data-mo-lo="${i + 1}">${m ? "Mở lại" : "Mở Creative Desk"}</button></div>`;
    }).join("")}</div>` : "";
    const mot = tong === 1 && moLuc.get(1)
      ? `<div class="sent-line">Đã mở Creative Desk cho cụm này lúc ${fmtDateTime(moLuc.get(1).mo_luc)} ` +
        `(${nhanSoVideo(moLuc.get(1), n)} video). ` +
        `Video Desk <b>không biết</b> bộ bên đó đã được tạo hay chưa.</div>` : "";
    head.innerHTML =
      `<div><div class="crumb">${escapeHtml(cum.usecase)} › ${escapeHtml(cum.insight_goc)} ›</div>` +
      `<h3>${escapeHtml(cum.insight)}</h3><div class="tax-line">` +
      `<span class="tax">Usecase <b>${escapeHtml(cum.usecase)}</b></span>` +
      `<span class="tax">Insight <b>${escapeHtml(cum.insight)}</b></span>` +
      `<span class="tax lock">Template <b>Goc</b> 🔒</span></div></div>` +
      `<span class="muted">${n} video</span><span class="grow"></span>` +
      `<button type="button" class="btn ghost" data-doi-kieu>Đổi kiểu</button>` +
      `<button type="button" class="btn ghost danger" data-xoa-cum>Xoá cụm</button>${nut}` +
      `<div class="handoff-note">Mở Creative Desk ở tab mới, điền sẵn <b>Usecase = ${escapeHtml(cum.usecase)}</b> · ` +
      `<b>Insight = ${escapeHtml(cum.insight)}</b> · <b>Template = Goc</b>; bạn vẫn soát và bấm tạo bên đó.` +
      (tong > 1 ? ` Cụm ${n} video vượt ${HANDOFF_MAX}/bộ ⇒ tự tách ${tong} bộ, mỗi bộ mở một tab.`
                : ` Tối đa ${HANDOFF_MAX} video một bộ.`) + `</div>${dsLo}${mot}`;
  }

  function chipCum(video) {
    if (!state.cumsDaNap) return "";
    const cum = video.cum_id == null ? null : state.cums.find((c) => c.id === video.cum_id);
    if (!cum) return `<span class="cum-chip none">chưa vào cụm</span>`;
    return `<span class="cum-chip"><span class="cum-dot" style="background:${mauCum(cum.id)}"></span>` +
      `${escapeHtml(cum.insight)}</span>`;
  }

  function doiCumLoc(loc) {
    if (loc === state.cumLoc) return;
    state.cumLoc = loc;
    sauKhiDoiBoLoc();  // một bộ lọc nữa ⇒ về trang 1, GIỮ lựa chọn
  }

  async function loadCums() {
    apDungCum(await apiGet("/cum"));
  }

  // Ghi một response `GET /cum` vào `state`. Tách khỏi `loadCums` để lượt nạp thư viện
  // lấy `/cum` về TRƯỚC rồi chỉ ghi khi nó còn là lượt mới nhất — `/cum` của một lượt
  // đã bị thay chỗ không được đè dữ liệu cụm của lượt mới hơn.
  function apDungCum(res) {
    state.cums = res.cum;
    // Tập cắt lô (xem `videoCuaCum`). Server cũ không trả ⇒ undefined ⇒ đường cũ.
    state.khungCum = Array.isArray(res.khung_cum) ? res.khung_cum : undefined;
    state.cumsDaNap = true;
    // Cụm đang xem vừa bị xoá (tab khác) ⇒ về "Tất cả" thay vì lưới rỗng câm.
    if (typeof state.cumLoc === "number" && !state.cums.some((c) => c.id === state.cumLoc)) {
      state.cumLoc = "tat_ca";
    }
  }

  // Mở MỘT lô của cụm. Trả "mo" | "chan" | "rong" | "loi".
  //
  // Mở tab TRỐNG trước (`moTabTrong`, đồng bộ trong lượt xử lý click), RỒI
  // mới `await` payload — chặn popup được biết NGAY tại cú bấm, không phải
  // sau một vòng fetch (trước đây `window.open` chạy SAU `await`, nên "chan"
  // chỉ đúng khi fetch đủ chậm để hết "user activation"). Mốc "đã mở" vẫn chỉ
  // ghi SAU khi tab đã mở thật VÀ đã điền đúng địa chỉ — không đổi ý đó, chỉ
  // đổi THỜI ĐIỂM biết được popup có bị chặn hay không.
  //
  // `items`/`nhan` KHÔNG còn tự ghép ở đây — server dựng trọn payload
  // (`GET /cum/{id}/lo/{thu}/payload`), JS chỉ mã hoá + điền vào tab đã mở.
  // `muc.length` (đếm LOCAL, từ `state.videos` đã nạp) chỉ dùng để báo "N
  // video chưa lên Drive", KHÔNG đi vào payload gửi Creative Desk.
  //
  // Fetch trượt (kể cả lỗi KHÔNG PHẢI hết phiên, vd 400 "lô ngoài khoảng" khi
  // một tab khác vừa đổi số video của cụm) ⇒ ĐÓNG tab trống lại (đừng để lại
  // một tab "about:blank" mồ côi) và báo lý do — im lặng nuốt lỗi là đúng lỗ
  // đã sửa ở đây.
  // Hai danh sách id cùng phần tử, cùng thứ tự.
  function cungLo(a, b) {
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }

  // Lô phía trang đã cũ ⇒ nạp lại cụm rồi báo. Chỉ nói "đã nạp lại" SAU khi
  // nạp xong — nạp hỏng thì khung vẫn cũ và bấm lại sẽ bị từ chối tiếp, nên
  // phải nói đúng thế. Trả giá trị cho `moLoCum` (dừng `moHetLoCum`).
  async function napLaiVi(lyDo) {
    try {
      await loadCums();
      showToast(`${lyDo} — đã nạp lại, bấm lại.`);
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      showToast(`${lyDo} nhưng không nạp lại được — tải lại trang (F5).`);
    }
    renderLibrary();
    return "loi";
  }

  async function moLoCum(cumId, thu) {
    const cum = state.cums.find((c) => c.id === cumId);
    if (!cum) return "rong";
    const muc = chiaLo(videoCuaCum(cumId), HANDOFF_MAX)[thu - 1];
    // Lô chỉ còn video đã dọn khỏi Drive ⇒ không có gì để gửi (giống lô rỗng).
    if (!muc || !muc.some((v) => !v.da_don)) return "rong";
    const tab = moTabTrong();
    if (!tab) return "chan";
    let payload;
    try {
      payload = await apiGet(`/cum/${cumId}/lo/${thu}/payload`);
    } catch (err) {
      tab.close();
      // Hết phiên KHÔNG được đọc như "đã mở xong" (trả "mo" như MỌI lỗi
      // khác trước đây): `moHetLoCum` đọc "mo" thành tín hiệu ĐI TIẾP, nên
      // hết phiên ở lô đầu từng kéo theo mở-rồi-đóng một tab trống CHO MỌI
      // lô còn lại, trong khi người dùng đã bị đăng xuất và không lô nào
      // trong số đó có cơ hội thành công. Trả một giá trị RIÊNG để vòng lặp
      // "Mở tất cả" DỪNG ngay ở lô đầu tiên gặp hết phiên.
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      // 400 = lô ngoài khoảng: tab khác vừa làm cụm co bớt lô. Cùng lớp với
      // vế kiểm id lô bên dưới ⇒ nạp lại để trang hết hiện bộ không còn, và chỉ
      // nói "đã nạp lại" sau khi nạp xong.
      if (err && err.status === 400) return napLaiVi("Bộ này không còn (tab khác vừa sửa cụm)");
      showToast(`Không mở được Creative Desk cho bộ này: ${err.message || err}`);
      return "loi";
    }
    // Người dùng có thể đã tự tay đóng tab TRỐNG trong lúc đang chờ payload
    // về — điều hướng (`dieuHuongTab`) một tab đã đóng không ném lỗi nào
    // (trình duyệt lặng lẽ bỏ qua), nên không có gì báo hiệu tự nhiên; và
    // ghi "đã mở Creative Desk" (`POST .../da-mo`) cho một tab người dùng
    // vừa đóng là NÓI DỐI — kiểm `tab.closed` NGAY trước khi điều hướng.
    if (tab.closed) return "dong";
    // `so_video` (số video của lô lúc server dựng payload) là mẫu số của nhãn
    // "x/N", CÙNG thời điểm với `items` — không thuộc hợp đồng v:1 gửi Creative
    // Desk nên tách ra TRƯỚC khi mã hoá URL. Server cũ không trả ⇒ rơi về độ
    // dài lô phía trang cho toast, và không gửi kèm (mốc ghi NULL).
    // `video_ids` (id mọi video của lô server vừa cắt) cũng tách ra như vậy.
    const { so_video: soVideoLo, video_ids: idsLo, ...guiDi } = payload;
    // Lô server ≠ lô trang đã hiện (tab khác vừa gán/gỡ video của cụm giữa lúc
    // nạp và lúc bấm) ⇒ KHÔNG gửi: người dùng đã soát lô này, gửi lô khác là
    // gửi nhầm bộ. Nạp lại để lần bấm sau đúng. Server cũ không trả ⇒ bỏ qua.
    if (Array.isArray(idsLo) && !cungLo(idsLo, muc.map((v) => v.video_id))) {
      tab.close();
      return napLaiVi("Lô đã đổi (tab khác vừa sửa cụm)");
    }
    const soVideo = typeof soVideoLo === "number" ? soVideoLo : muc.length;
    if (!guiDi.items.length) {
      tab.close();
      showToast("Video của bộ này chưa lên Drive hoặc thiếu link gốc hợp lệ — chưa có gì để gửi sang Creative Desk.");
      return "rong";
    }
    if (guiDi.items.length < soVideo) {
      const daDon = muc.filter((v) => v.da_don).length;
      showToast(daDon
        ? `${soVideo - guiDi.items.length} video không gửi kèm (${daDon} đã dọn khỏi Drive sau khi vào bộ, ` +
          `còn lại chưa lên Drive hoặc thiếu link gốc hợp lệ).`
        : `${soVideo - guiDi.items.length} video chưa lên Drive hoặc thiếu link gốc hợp lệ nên không gửi kèm.`);
    }
    dieuHuongTab(tab, urlBanGiao(guiDi));
    try {
      const res = await apiSend("POST", `/cum/${cumId}/lo/${thu}/da-mo`,
        { so_item: guiDi.items.length, so_video: soVideoLo });
      cum.lo_mo = cum.lo_mo.filter((m) => m.thu !== thu)
        .concat([{ thu, mo_luc: res.mo_luc, so_item: res.so_item, so_video: res.so_video }]);
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      showToast("Đã mở Creative Desk nhưng không ghi được mốc “đã mở” — bấm lại nếu cần.");
    }
    renderCumHead();
    return "mo";
  }

  async function moHetLoCum(cumId) {
    const dsLo = chiaLo(videoCuaCum(cumId), HANDOFF_MAX);
    const tong = dsLo.length;
    for (let thu = 1; thu <= tong; thu++) {
      // Lô toàn video đã dọn: bỏ qua, đừng để "rong" chặn các lô sau nó.
      if (!dsLo[thu - 1].some((v) => !v.da_don)) continue;
      const kq = await moLoCum(cumId, thu);
      if (kq === "chan") {
        // Trình duyệt thường chỉ cho MỘT tab mỗi cú bấm. Nói đúng thế, và chỉ
        // chỗ bấm tiếp — lô chưa mở vẫn ghi "chưa mở".
        showToast(thu === 1
          ? "Trình duyệt đã chặn tab mới — cho phép popup rồi bấm lại."
          : `Đã mở ${thu - 1}/${tong} bộ. Trình duyệt chặn tab tiếp theo — bấm “Mở Creative Desk” ở từng bộ bên dưới.`);
        return;
      }
      // "rong"/"loi" đã tự báo toast, "het_phien" đã tự bật màn hình hết
      // phiên — TẤT CẢ, bên trong `moLoCum`. "dong" (người dùng tự đóng tab
      // trống) không cần báo gì thêm. Dừng vòng lặp ở đây cho mọi giá trị
      // khác "mo" — đừng mở thêm tab trống cho lô kế tiếp trong lúc phiên
      // hoặc dữ liệu đã có vấn đề.
      if (kq !== "mo") return;
    }
  }

  // Id cụm mang tên `nhap`: cụm có sẵn trùng tên, hoặc cụm vừa tạo. Server tự
  // trả lại cụm có sẵn khi trùng (`da_co`), nên kể cả khi `state.cums` cũ hơn
  // server (tab khác vừa tạo) cũng không sinh cụm thứ hai.
  async function layHoacTaoCum(nhap) {
    const trung = timCumTrung(state.cums, nhap.usecase, nhap.goc, nhap.kieu);
    if (trung) return { cumId: trung.id, daCo: true };
    const moi = await apiSend("POST", "/cum",
      { usecase: nhap.usecase, insight_goc: nhap.goc, kieu: nhap.kieu });
    if (!state.cums.some((c) => c.id === moi.id)) state.cums.push(moi);
    return { cumId: moi.id, daCo: Boolean(moi.da_co) };
  }

  // Gán `ids` vào ĐÚNG cụm `cumId` — không tra lại theo tên. Trả `{da, boQua}`.
  async function ganIdsVaoCum(cumId, ids) {
    let da = 0, boQua = 0;
    for (let i = 0; i < ids.length; i += GAN_CUM_TOI_DA) {
      const lo = ids.slice(i, i + GAN_CUM_TOI_DA);
      const res = await apiSend("POST", `/cum/${cumId}/video`, { video_ids: lo });
      const bo = new Set(res.bo_qua);
      for (const v of state.videos) if (lo.includes(v.video_id) && !bo.has(v.video_id)) v.cum_id = cumId;
      da += res.so_video;
      boQua += res.bo_qua.length;
    }
    return { da, boQua };
  }

  function baoDaGan(cumId, daCo, soId, kq) {
    const ten = (state.cums.find((c) => c.id === cumId) || {}).insight || "";
    const phan = [daCo ? `Dùng lại cụm có sẵn “${ten}”` : `Đã tạo cụm “${ten}”`];
    if (soId) phan.push(`đưa ${kq.da} video vào`);
    if (kq.boQua) phan.push(`${kq.boQua} video không đưa được (không thuộc thư viện của bạn)`);
    showToast(phan.join(" · "));
  }

  // Tạo (hoặc DÙNG LẠI cụm trùng tên) rồi đưa `ids` vào. Trả id cụm.
  async function duaVaoCum(nhap, ids) {
    const { cumId, daCo } = await layHoacTaoCum(nhap);
    const kq = await ganIdsVaoCum(cumId, ids);
    baoDaGan(cumId, daCo, ids.length, kq);
    return cumId;
  }

  // Một lượt gửi cụm tại một thời điểm, cho CẢ form lẫn các dòng "cụm có sẵn".
  // Bấm đôi mà không có cờ này thì hai lượt cùng đọc `state.cums` cũ và cùng
  // POST — đúng ca để lại hai cụm trùng tên (review PR #13).
  let dangGuiCum = false;

  // Bằng `web/app.py::MAX_VIDEO_CUM`.
  const GAN_CUM_TOI_DA = 1000;

  function renderPopoverCum() {
    const pop = document.getElementById("cum-popover");
    if (!pop || pop.hidden) return;
    const co = state.cums.length
      ? `<h4>Đưa vào cụm có sẵn</h4>` + state.cums.map((c) =>
          `<button type="button" class="cum-row" data-gan-cum="${c.id}"><span class="cum-dot" style="background:${mauCum(c.id)}"></span>` +
          `<span class="cum-ten">${escapeHtml(c.insight)}</span><span class="n">${escapeHtml(c.usecase)}</span></button>`).join("") +
        `<hr class="rail-sep">`
      : "";
    pop.innerHTML = co + formCum("thanh", state.selected.size);
    capNhatXemTruoc(pop);
  }

  function capNhatXemTruoc(goc) {
    const f = goc.querySelector(".cum-form");
    if (!f) return;
    const gt = (t) => f.querySelector(`[data-cum-o="${t}"]`).value;
    // Trùng một cụm có sẵn ⇒ nói TRƯỚC khi bấm rằng sẽ dùng lại cụm đó, và
    // hiện tên của CỤM ĐÓ (từ server), không phải chữ vừa gõ.
    const trung = timCumTrung(state.cums, gt("usecase"), gt("goc"), gt("kieu"));
    f.querySelector("[data-xem-truoc]").textContent =
      trung ? `${trung.insight} (đã có — dùng lại cụm này)` : (xemTruocTen(gt("goc"), gt("kieu")) || "—");
    const n = f.dataset.noi === "thanh" ? state.selected.size : 0;
    f.querySelector("button[type=submit]").textContent = trung
      ? (n ? `Đưa ${n} video vào cụm có sẵn` : "Cụm này đã có")
      : (n ? `Tạo cụm và đưa ${n} video vào` : "Tạo cụm");
  }

  async function guiFormCum(form) {
    const gt = (t) => form.querySelector(`[data-cum-o="${t}"]`).value;
    const nhap = { goc: gt("goc"), usecase: gt("usecase"), kieu: gt("kieu") };
    if (!khoaNhan(nhap.goc) || !khoaNhan(nhap.usecase) || !khoaNhan(nhap.kieu)) {
      showToast("Điền đủ insight gốc, usecase và kiểu.");
      return;
    }
    const ids = form.dataset.noi === "thanh" ? [...state.selected] : [];
    if (dangGuiCum) return;
    dangGuiCum = true;
    const nut = form.querySelector("button[type=submit]");
    nut.disabled = true;
    try {
      const cumId = await duaVaoCum(nhap, ids);
      if (ids.length) boChonTatCa();
      await loadCums();
      document.getElementById("cum-popover").hidden = true;
      state.cumLoc = cumId;
      sauKhiDoiBoLoc();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đưa được vào cụm: ${typeof err.ma === "string" ? err.ma : lyDoLoiLoai(err)}`);
      await loadCums().catch(() => {});
      renderLibrary();
    } finally {
      dangGuiCum = false;
      nut.disabled = false;
    }
  }

  // Dòng "cụm có sẵn" mang id ⇒ gán THẲNG vào id đó. Tra lại theo tên (bản
  // trước) thì khi có hai cụm cùng tên, bấm cụm B mà video vào cụm A.
  async function ganVaoCumCoSan(cumId) {
    if (dangGuiCum || !state.cums.some((c) => c.id === cumId)) return;
    dangGuiCum = true;
    try {
      const ids = [...state.selected];
      baoDaGan(cumId, true, ids.length, await ganIdsVaoCum(cumId, ids));
      boChonTatCa();
      await loadCums();
      document.getElementById("cum-popover").hidden = true;
      renderLibrary();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đưa được vào cụm: ${lyDoLoiLoai(err)}`);
    } finally {
      dangGuiCum = false;
    }
  }

  async function doiKieuCum(cum) {
    const kieu = window.prompt(`Kiểu mới cho “${cum.insight}” (insight gốc “${cum.insight_goc}” giữ nguyên):`, cum.kieu);
    if (kieu === null || !khoaNhan(kieu)) return;
    try {
      await apiSend("PATCH", `/cum/${cum.id}`, { kieu });
      await loadCums();
      renderLibrary();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không đổi được kiểu: ${typeof err.ma === "string" ? err.ma : lyDoLoiLoai(err)}`);
    }
  }

  async function xoaCum(cum) {
    if (!window.confirm(`Xoá cụm “${cum.insight}”?\n\nVideo trong cụm về “Chưa vào cụm” — không video nào bị xoá.`)) return;
    try {
      await apiSend("DELETE", `/cum/${cum.id}`);
      for (const v of state.videos) if (v.cum_id === cum.id) v.cum_id = null;
      await loadCums();
      sauKhiDoiBoLoc();
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
      showToast(`Không xoá được cụm: ${lyDoLoiLoai(err)}`);
    }
  }

  // Bằng `web/app.py::MAX_VIDEO_LOAI`. Test `test_tran_lo_loai_khop_backend`
  // đối chiếu hai số — đổi một bên mà quên bên kia là 422 quay lại.
  const LOAI_TOI_DA_MOI_LUOT = 50;

  // Câu cho NGƯỜI DÙNG khi một lô bỏ video trượt. Bản trước in thẳng
  // "POST /videos/loai -> 422" — đúng với dev, vô nghĩa với người bấm. Mã vẫn đi
  // kèm trong ngoặc để ai báo lỗi còn chép được.
  function lyDoLoiLoai(err) {
    const st = err && err.status;
    if (st === 422) return `máy chủ từ chối yêu cầu (mã 422) — báo người phát triển`;
    if (st >= 500) return `máy chủ đang lỗi (mã ${st}) — thử lại sau ít phút`;
    if (st) return `không bỏ được (mã ${st})`;
    return `mất kết nối tới máy chủ — kiểm mạng rồi bấm lại`;
  }

  async function loaiDaChon() {
    const ids = [...state.selected];
    if (!ids.length) return;
    // Hỏi trước: xoá là việc khó lùi ở phía người dùng (tệp vào Thùng rác
    // Drive). Nói rõ nó KHÔNG đụng người khác — đó là thứ người bấm cần biết
    // để bấm mà không phải đoán.
    const ok = window.confirm(
      `Bỏ ${ids.length} video khỏi thư viện của bạn?` +
      `${dongNgoaiTrang(demNgoaiTrang(state.selected, state.idTrang))}\n\n` +
      `Tệp vào Thùng rác Drive (lấy lại được trong 30 ngày). ` +
      `Người khác không bị ảnh hưởng, và lượt quét sau của bạn sẽ không tải lại chúng.`);
    if (!ok) return;

    // Gửi theo LÔ ≤ `LOAI_TOI_DA_MOI_LUOT`, tuần tự. Backend chặn cứng 50 id một
    // request (`web/app.py::MAX_VIDEO_LOAI` — mỗi id là một lượt gọi Drive đồng
    // bộ), còn thư viện một người đã có 86 video: gửi nguyên lựa chọn thì >50 là
    // 422 và KHÔNG video nào được bỏ (đo 23/09 10:45). Tuần tự chứ không song
    // song: song song là đúng cái request dài mà trần kia sinh ra để chặn.
    const tong = { da_loai: 0, drive_truot: 0, khong_phai_cua_ban: 0 };
    let loi = null;
    let loDaGui = 0;
    const soLo = Math.ceil(ids.length / LOAI_TOI_DA_MOI_LUOT);
    for (let i = 0; i < ids.length; i += LOAI_TOI_DA_MOI_LUOT) {
      const lo = ids.slice(i, i + LOAI_TOI_DA_MOI_LUOT);
      try {
        const res = await apiSend("POST", "/videos/loai", { video_ids: lo });
        tong.da_loai += res.da_loai.length;
        tong.drive_truot += res.drive_truot.length;
        tong.khong_phai_cua_ban += res.khong_phai_cua_ban.length;
        // Gỡ khỏi lựa chọn ĐÚNG lô vừa xong — như bản một-lượt trước đây
        // `clear()` sau khi API trả về. Lô chưa gửi vẫn nằm đó để bấm lại.
        lo.forEach((id) => state.selected.delete(id));
        loDaGui++;
      } catch (err) {
        if (err instanceof PhienHetHan) { baoPhienHetHan(); return; }
        loi = err;
        break;
      }
    }

    // Nạp lại hỏng KHÔNG được nuốt câu tóm tắt: tệp đã vào Thùng rác, người dùng phải
    // biết số đã bỏ — câu "không tải lại được" gộp vào cùng toast (không đè nó).
    const nap = loDaGui > 0 ? await napLaiThuVien({ imLoi: true }) : "ok";
    renderSelectionBar();
    // Báo đủ ba con số, không gộp thành một chữ "xong": Drive trượt mà im
    // lặng thì người dùng tưởng đã dọn trong khi tệp còn nguyên.
    const phan = [`đã bỏ ${tong.da_loai}`];
    if (tong.drive_truot) phan.push(`${tong.drive_truot} chưa bỏ được khỏi Drive — thử lại`);
    if (tong.khong_phai_cua_ban) phan.push(`${tong.khong_phai_cua_ban} không phải của bạn`);
    if (loi) {
      phan.push(`dừng ở lô ${loDaGui + 1}/${soLo}: ${lyDoLoiLoai(loi)}`,
                `còn ${state.selected.size} video đang chọn — bấm lại để tiếp`);
    }
    if (nap === "loi") phan.push("không tải lại được thư viện — bấm Làm mới");
    if (nap === "het_phien") phan.push("phiên đã hết hạn — tải lại trang để thấy thư viện mới");
    showToast(phan.join(" · "));
  }

  state.soMoiTrang = docSoMoiTrang();
  document.getElementById("chon-trang").addEventListener("click", chonTrangNay);
  document.getElementById("so-moi-trang").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-so]");
    if (b) doiSoMoiTrang(Number(b.dataset.so));
  });
  document.querySelectorAll("[data-pager]").forEach((nav) => nav.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-trang]");
    if (b && !b.disabled) doiTrang(Number(b.dataset.trang));
  }));

  document.getElementById("library-refresh").addEventListener("click", () => {
    napLaiThuVien();
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
        // Lỗi thường cũng phải NÓI: nạp hỏng có thể vừa đưa chip về phía đang vẽ
        // (xem `loadVideos`) — chip tự lật mà im lặng thì người dùng không biết vì sao.
        napLaiThuVien();
      }
    });
    es.onerror = () => {
      // Tunnel/SSE có thể rớt trong khi job vẫn chạy ở server — đóng stream
      // này, dựa vào polling `loadJobs` bên dưới để giữ hàng đợi đúng.
      es.close();
      state.openStreams.delete(jobId);
    };
  }

  // Trần cứng cho số video giữ trong trình duyệt MỖI phía chip. Lưới đã phân trang
  // nên DOM không còn là chi phí; chi phí thật là JSON tải về (~1,2–1,7 KB/video,
  // đo 02/10) cộng các vòng lọc/đếm chạy trên cả tập. Không có trần thì thư viện
  // lớn dần sẽ làm treo tab, kiểu hỏng khó truy hơn hẳn một dòng chữ "đang hiện
  // 5000/6000". 5000 là phanh tạm cho tới khi lưới phân trang ở server.
  // `LIBRARY_PAGE` = `MAX_VIDEOS_PAGE_SIZE` của server (web/app.py) — ít lượt hơn.
  const LIBRARY_PAGE = 1000;
  const LIBRARY_MAX = 5000;
  // Từ mức này (80 % trần) băng cảnh báo hiện SỚM — để người dùng và người vận hành
  // thấy trước khi lưới bắt đầu cắt, không cần ai đi đo tay.
  const LIBRARY_CANH_BAO_SOM = Math.ceil(LIBRARY_MAX * 0.8);
  // ⚠ Phân trang ở `renderLibrary` KHÔNG kéo dữ liệu: nó cắt trên `state.videos`
  // đã nạp trọn ở đây. Thư viện vượt `LIBRARY_MAX` thì phân trang cũng chỉ thấy
  // `LIBRARY_MAX` video đầu — muốn hơn phải chuyển sang phân trang phía server.

  // Badge worker (CHỈ quản trị): worker chết / lỗi lặp / chờ đĩa thì job pending không
  // chạy mà trang vẫn trông bình thường — nói ra. Hàm thuần theo `tt` (null ⇒ ẩn).
  function chuBadgeWorker(tt) {
    if (!tt) return "";
    if (!tt.song) return "Worker đã dừng — job chờ sẽ không chạy";
    if (tt.job_ket && tt.job_ket.length) return `Worker: ${tt.job_ket.length} job kẹt "đang chạy", chưa ghi được trạng thái`;
    if (tt.loi_lien_tiep > 0) return `Worker lỗi lặp ${tt.loi_lien_tiep} lần (${tt.loi_cuoi || "?"})`;
    if (tt.cho_dia) return `Worker chờ đĩa: ${tt.cho_dia}`;
    return "";
  }

  function veBadgeWorker(tt) {
    const el = document.getElementById("badge-worker");
    if (!el) return;
    const chu = chuBadgeWorker(tt);
    el.textContent = chu;
    el.hidden = !chu;
  }

  // Badge "Dọn lỗi (N)": CHỈ quản trị (server kiểm `require_admin`; người thường không
  // gọi endpoint). Lỗi mạng/không phải admin ⇒ ẩn badge, không làm hỏng thư viện.
  async function loadBadgeDonLoi() {
    const el = document.getElementById("badge-don-loi");
    const elLap = document.getElementById("badge-do-loi-lap");
    if (!el) return;
    el.hidden = true;
    if (elLap) elLap.hidden = true;
    veBadgeWorker(null);
    try {
      const me = await apiGet("/me");
      if (!me.la_admin) return;
      veBadgeWorker(await apiGet("/admin/worker").catch((e) => {
        if (e instanceof PhienHetHan) throw e;
        return null;
      }));
      const res = await apiGet("/admin/don-vao-bo-loi");
      // Chỉ ĐẾM (không ngưỡng): N id đang trong tập thử-lại, lâu nhất K lần trượt liên tiếp.
      if (elLap && res.do_loi_lap && res.do_loi_lap.so_id) {
        elLap.textContent = `${res.do_loi_lap.so_id} id đo lỗi lặp, lâu nhất ${res.do_loi_lap.lau_nhat_lan} lần`;
        elLap.hidden = false;
      }
      if (!res.so_hang) return;
      el.textContent = `Dọn lỗi (${res.so_hang})`;
      el.title = res.hang.slice(0, 10).map((h) =>
        `${h.video_id}: ${h.loi_cuoi || "?"} (${h.so_lan_truot} lần)`).join("\n");
      el.hidden = false;
    } catch (err) {
      if (err instanceof PhienHetHan) throw err;
    }
  }

  // Thư viện của người xem lớn hơn trần nạp ⇒ lưới CHỈ có `LIBRARY_MAX` video mới nhất. Hàm
  // thuần: trả câu cảnh báo, hoặc "" khi chưa vượt (đúng bằng trần chưa bị cắt: `>` không phải `>=`).
  // `chiVaoBo`: `tong` là số của phía "Đã vào bộ" (trần nạp tính riêng mỗi phía).
  // Mức cảnh báo: "cat" (vượt trần, lưới đang thiếu video) | "som" (từ `som` trở lên mà
  // CHƯA vượt) | "". MỘT chỗ quyết mức — chữ (`canhBaoGioiHan`) và màu/`role`
  // (`veCanhBaoGioiHan`) cùng đọc nó, để không thể lệch nhau ở ca biên.
  function mucGioiHan(tong, tran, som) {
    if (tong > tran) return "cat";
    return typeof som === "number" && tong >= som ? "som" : "";
  }

  // `som` (tuỳ chọn): từ mức này trở lên mà CHƯA vượt trần ⇒ cảnh báo sớm.
  function canhBaoGioiHan(tong, tran, chiVaoBo, som) {
    const muc = mucGioiHan(tong, tran, som);
    if (muc === "cat") {
      return chiVaoBo ? `Có ${tong} video đã vào bộ, chỉ nạp ${tran} video mới nhất`
        : `Thư viện có ${tong} video, lưới chỉ nạp ${tran} video mới nhất`;
    }
    if (muc === "som") {
      return chiVaoBo ? `Có ${tong} video đã vào bộ — sắp chạm trần nạp ${tran}`
        : `Thư viện có ${tong} video — sắp chạm trần nạp ${tran}`;
    }
    return "";
  }

  function veCanhBaoGioiHan(tong) {
    const el = document.getElementById("canh-bao-gioi-han");
    if (!el) return;
    const chu = canhBaoGioiHan(tong, LIBRARY_MAX, state.chiVaoBo, LIBRARY_CANH_BAO_SOM);
    // Hai mức phải NHÌN khác nhau: vàng = "sắp chạm trần", đỏ = "đã cắt, lưới đang
    // thiếu video". Và NGHE khác nhau: chỉ "đã cắt" mới ngắt ngang (`alert`); "sắp"
    // không gấp nên lịch sự (`status`). `role` đặt TRƯỚC khi ghi chữ, để thông báo
    // mang đúng mức; chỉ đặt khi đổi.
    const muc = mucGioiHan(tong, LIBRARY_MAX, LIBRARY_CANH_BAO_SOM);
    const role = muc === "cat" ? "alert" : "status";
    if (el.getAttribute("role") !== role) el.setAttribute("role", role);
    el.dataset.muc = muc;
    el.classList.toggle("som", muc === "som");
    // Băng được vẽ lại MỖI lượt nạp (Làm mới, job xong, đổi chip…). Ghi lại cùng chữ
    // thay nút chữ ⇒ trình đọc màn hình đọc lại ⇒ chỉ ghi khi chữ đổi.
    if (el.textContent !== chu) el.textContent = chu;
    el.hidden = chu === "";
  }

  // `lyDoRoi`: vì sao lựa chọn có thể rơi lượt này (đổi phía chip ⇒ nói đúng thế).
  async function loadVideos({ lyDoRoi } = {}) {
    // Bản đầu gọi `/videos` không tham số, tức nhận đúng 200 video mặc định
    // của server, KHÔNG đọc `tong`, và in nhãn theo số đã nạp. Hậu quả: video
    // thứ 201 trở đi không tồn tại với người dùng, mọi bộ lọc chạy trên tập
    // con, và nhãn "200 video" trông y hệt một con số đúng. Thư viện dùng
    // chung cả team mà cắt im lặng như vậy là hỏng đúng thứ nó sinh ra để làm.
    //
    // Chỉ nạp phía chip đang xem (`vao_bo=0|1`): video đã vào bộ không chiếm suất
    // `LIBRARY_MAX` của lưới mặc định, và phía "Đã vào bộ" có trần riêng. Bấm chip
    // liên tiếp ⇒ nhiều lượt chồng nhau: chỉ lượt MỚI NHẤT được đụng `state`/DOM.
    // Mọi thứ nạp về giữ ở biến cục bộ tới SAU lần chờ cuối (`/cum`), rồi mới
    // kiểm lượt và ghi — ghi sớm thì lượt cũ để lại `state` lệch DOM khi lượt
    // mới hỏng.
    const { luot, signal } = batDauLuotNap();
    const phia = state.chiVaoBo ? 1 : 0;
    const url = (offset) => `/videos?limit=${LIBRARY_PAGE}&offset=${offset}&vao_bo=${phia}`;
    let first, videos, tong, resCum = null;
    try {
      first = await apiGet(url(0), { signal });
      videos = first.videos.slice();
      tong = first.tong;
      while (luot === state.luotNapVideo && videos.length < tong && videos.length < LIBRARY_MAX) {
        const next = await apiGet(url(videos.length), { signal });
        if (next.videos.length === 0) break;   // server hết hàng sớm hơn `tong`
        videos.push(...next.videos);
      }
      if (luot !== state.luotNapVideo) return false;
      // Cụm nạp cùng nhịp với video: chip và số đếm đọc cả hai. Lấy về ở đây, GHI
      // ở bước commit (`apDungCum`) — lượt bị thay không được đè cụm. Cụm lỗi thì
      // thư viện VẪN hiện (không chip), và nói ra — đừng để thanh bên trống câm.
      try {
        resCum = await apiGet("/cum", { signal });
      } catch (err) {
        if (err instanceof PhienHetHan) throw err;
        // Lượt đã bị thay (kể cả bị abort ở đây) ⇒ lỗi /cum của nó không phải sự
        // thật về thư viện ⇒ im.
        if (luot !== state.luotNapVideo) return false;
        showToast("Không tải được danh sách cụm — thư viện vẫn dùng được, bấm Làm mới để thử lại.");
      }
    } catch (err) {
      // Lượt mới nhất hỏng ⇒ `state.videos`, lưới và lựa chọn vẫn là phía ĐÃ VẼ.
      // Đưa chip về đúng phía đó (không phải "phía trước lần bấm này" — bấm hai
      // lần nhanh thì hai thứ đó khác nhau) và vẽ lại cho chip, bộ lọc, trang
      // khớp nhau. Để chip phía mới trên lưới phía cũ thì "Bỏ" thao tác trên
      // video người dùng không tưởng là mình đang xem.
      // Chưa vẽ lần nào (lần nạp đầu hỏng) ⇒ không có gì để quay về; vẽ lúc này
      // sẽ hiện "Thư viện chưa có video nào" — nói sai, thư viện chưa NẠP được.
      if (luot === state.luotNapVideo) {
        const g = document.getElementById("card-grid");
        g.setAttribute("aria-busy", "false");
        if (state.phiaDaVe !== undefined) {
          state.chiVaoBo = state.phiaDaVe === 1;
          renderLibrary();
          g.dataset.napPhia = String(state.phiaDaVe);
        } else {
          // Chưa vẽ lần nào: không vẽ, nhưng chip vẫn về mặc định (tắt) cho khớp
          // lưới rỗng, và hết "đang nạp".
          state.chiVaoBo = false;
          veChipVaoBo();
        }
        g.dataset.luotXong = String(luot);
      }
      // Lượt đã bị thay chỗ: lỗi của nó không còn là sự thật về thư viện (lượt
      // mới hơn có thể đã nạp xong) ⇒ đừng ném cho bên gọi toast "không tải lại
      // được", đè mất câu báo của lượt mới (vd "Đã bỏ N video…"). Hết phiên thì
      // vẫn ném — đó là sự thật về phiên, không về lượt.
      if (luot !== state.luotNapVideo && !(err instanceof PhienHetHan)) return false;
      throw err;
    }
    // Lượt mới hơn bắt đầu trong lúc chờ `/cum` ⇒ để lượt đó ghi và vẽ.
    if (luot !== state.luotNapVideo) return false;

    // `/cum` dị dạng (không có mảng `cum`) ⇒ chỉ là lỗi CỤM: thư viện vẫn vẽ, như khi
    // `/cum` trả lỗi — không để `apDungCum` ném giữa bước ghi và bỏ dở `state`.
    if (resCum && !Array.isArray(resCum.cum)) {
      showToast("Không tải được danh sách cụm — thư viện vẫn dùng được, bấm Làm mới để thử lại.");
      resCum = null;
    }
    if (resCum) apDungCum(resCum);
    ghiOLoi(LOI_THU_VIEN, "");   // đã nạp được ⇒ câu "không tải được thư viện" cũ thành sai
    state.videos = videos;
    state.phiaDaVe = phia;   // cùng lúc với `state.videos`: phục hồi vẽ lại từ đúng tập này
    state.tongVaoBo = typeof first.tong_vao_bo === "number" ? first.tong_vao_bo : undefined;
    state.videosTotal = tong;
    veCanhBaoGioiHan(tong);
    state.videosDaDon = first.da_don_trong_cum || [];
    // Lựa chọn giờ sống qua nhiều trang (26/09) ⇒ id của video đã biến mất (xoá
    // ở tab khác, rơi khỏi tập đã nạp) phải rơi khỏi lựa chọn, nếu không nó bị
    // đếm vào "không hiện ở trang này" và vào số của hộp xác nhận Xoá.
    // Mọi thao tác chỉ thấy tập ĐÃ NẠP (bộ lọc `renderLibrary`, `moBoTuTim` đều
    // lọc trên `state.videos`) — giữ id ngoài tập là để Xoá xoá mù đúng video đó.
    // Bỏ thì phải NÓI ra: lựa chọn không được mất im lặng.
    const conLai = new Set(videos.map((v) => v.video_id));
    const roi = [...state.selected].filter((id) => !conLai.has(id));
    roi.forEach((id) => state.selected.delete(id));
    if (roi.length) {
      showToast(`Đã bỏ ${roi.length} video khỏi lựa chọn ${lyDoRoi || "vì không còn trong thư viện đang hiện"}.`);
    }
    renderLibrary();
    // Tín hiệu "lưới đã vẽ xong phía này" — cho người đọc màn hình và cho test.
    const grid = document.getElementById("card-grid");
    grid.setAttribute("aria-busy", "false");
    grid.dataset.napPhia = String(phia);
    // Mốc "lượt `luot` đã kết thúc" (thành công hay hỏng) — tín hiệu chắc chắn cho test.
    grid.dataset.luotXong = String(luot);
    loadBadgeDonLoi().catch(() => { /* phiên hết hạn đã được các lời gọi khác báo */ });
    return true;
  }

  // Ô `#error` dùng chung (form job, dữ liệu ban đầu, thư viện). Nguồn đi qua đây giữ MỘT
  // câu mở đầu bằng `dau`: ghi câu mới thay câu cũ của CÙNG nguồn, không đè câu nguồn khác
  // cũng đi qua đây; `cau` rỗng ⇒ gỡ câu của nguồn đó (vd thư viện đã nạp lại được thì câu
  // lỗi cũ thành sai). ⚠ Form job (submit) CHƯA đi qua đây — nó vẫn xoá/ghi thẳng ô này, nên
  // có thể làm mất câu lỗi thư viện (nợ ghi ở plan 261002-1305 "Nợ đã biết").
  function ghiOLoi(dau, cau) {
    const el = document.getElementById("error");
    if (!el) return;
    const con = el.textContent.split(" · ").filter((x) => x && !x.startsWith(dau));
    if (cau) con.push(dau + cau);
    el.textContent = con.join(" · ");
  }
  const LOI_THU_VIEN = "Không tải được thư viện: ";

  // Bắt đầu một lượt nạp thư viện. ĐỒNG BỘ, không `await` nào xen giữa: tăng số lượt,
  // huỷ request của lượt cũ, tạo bộ huỷ mới. `abort()` chỉ xếp hàng lỗi cho lượt cũ
  // — `catch` của nó chạy SAU khối này, lúc số lượt đã tăng ⇒ nó thấy mình đã bị thay
  // và im. Bất biến: mọi `catch` của lượt nạp kiểm số lượt TRƯỚC khi phục hồi/báo.
  function batDauLuotNap() {
    const luot = ++state.luotNapVideo;
    if (state.boHuyNap) state.boHuyNap.abort();
    state.boHuyNap = new AbortController();
    return { luot, signal: state.boHuyNap.signal };
  }

  // MỘT chỗ duy nhất bắt lỗi nạp lại thư viện cho mọi nơi gọi (đổi chip, Làm mới, job
  // xong, sau Bỏ, lần đầu). Trả "ok" | "bi_thay" | "loi" | "het_phien".
  // `imLoi`: bên gọi tự nói lỗi (vd `loaiDaChon` gộp vào toast tóm tắt của nó).
  async function napLaiThuVien({ lyDoRoi, imLoi = false } = {}) {
    try {
      return (await loadVideos({ lyDoRoi })) ? "ok" : "bi_thay";
    } catch (err) {
      if (err instanceof PhienHetHan) { baoPhienHetHan(); return "het_phien"; }
      // Chưa vẽ lần nào (lần nạp đầu hỏng): toast 2,6 s rồi trang trống là im lặng
      // ⇒ ghi vào ô lỗi thường trực.
      if (state.phiaDaVe === undefined) {
        ghiOLoi(LOI_THU_VIEN, err.message);
      } else if (!imLoi) {
        showToast("Không tải lại được thư viện: " + err.message);
      }
      return "loi";
    }
  }

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
})();
