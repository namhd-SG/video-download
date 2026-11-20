// Gắn nút phân trang + theme; nạp jobs (+SSE), badge quản trị, thư viện video.
//
// Các tệp `app-*.js` + `app.js` là MỘT chương trình tách theo khoảng dòng (trước đây một IIFE 2526 dòng).
// Chúng là script thường, nạp TUẦN TỰ trong index.html (thứ tự = thứ tự gắn sự kiện cũ), chia sẻ phạm vi
// toàn cục: `const`/`function` khai ở tệp trước dùng được ở tệp sau. Code chạy NGAY lúc nạp (khởi tạo hằng,
// gọi hàm ở cấp tệp) chỉ được trỏ tới thứ đã khai ở tệp TRƯỚC hoặc cùng tệp — `function` chỉ hoist trong
// CÙNG tệp. Handler/render chạy sau khi mọi tệp đã nạp nên trỏ đi đâu cũng được.
"use strict";

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
      if (TRANG_THAI_SONG.has(job.trang_thai) && !state.openStreams.has(job.id)) {
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
      if (!TRANG_THAI_SONG.has(job.trang_thai)) {
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

  // `/admin/worker` trả các trường phẳng của lane TikTok VÀ `lanes.khac` (Facebook Ads / Drive).
  // Thiếu `lanes` (server cũ) ⇒ chỉ chữ của lane TikTok, y như trước. Mỗi lane tự phán, lane khác
  // chết không bị lane TikTok che.
  function chuBadgeCacLane(res) {
    if (!res) return "";
    const chuTiktok = chuBadgeWorker(res);
    const chuKhac = res.lanes && res.lanes.khac ? chuBadgeWorker(res.lanes.khac) : "";
    return [chuTiktok, chuKhac && `Lane nền tảng khác: ${chuKhac}`].filter(Boolean).join(" · ");
  }

  function veBadgeWorker(tt) {
    const el = document.getElementById("badge-worker");
    if (!el) return;
    const chu = chuBadgeCacLane(tt);
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
    // Loại CHỐT ở đầu lượt: đổi công tắc "Loại" giữa chừng sẽ bắt đầu lượt mới và huỷ lượt này.
    const loai = state.loaiThuVien;
    const laAnh = loai === "anh";
    // Ảnh: `/anh` trả BÀI (mỗi bài nhiều tệp); `hang` đổi mỗi bài thành một "thẻ" cùng hình một video để lưới, bộ lọc,
    // phân trang và lựa chọn dùng lại nguyên (video_id của thẻ = bai_id; tệp thật nằm ở `files`/`file_ids`).
    const duong = laAnh ? "/anh" : "/videos";
    const hang = (res) => (laAnh ? res.bai.map(theTuBaiAnh) : res.videos);
    const url = (offset) => `${duong}?limit=${LIBRARY_PAGE}&offset=${offset}&vao_bo=${phia}`;
    let first, videos, tong, resCum = null;
    try {
      first = await apiGet(url(0), { signal });
      videos = hang(first);
      tong = first.tong;
      while (luot === state.luotNapVideo && videos.length < tong && videos.length < LIBRARY_MAX) {
        const next = hang(await apiGet(url(videos.length), { signal }));
        if (next.length === 0) break;   // server hết hàng sớm hơn `tong`
        videos.push(...next);
      }
      if (luot !== state.luotNapVideo) return false;
      // Cụm nạp cùng nhịp với video: chip và số đếm đọc cả hai. Lấy về ở đây, GHI
      // ở bước commit (`apDungCum`) — lượt bị thay không được đè cụm. Cụm lỗi thì
      // thư viện VẪN hiện (không chip), và nói ra — đừng để thanh bên trống câm.
      // Ảnh không vào cụm ⇒ không nạp `/cum` ở chế độ ảnh.
      try {
        if (!laAnh) resCum = await apiGet("/cum", { signal });
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
          state.loaiThuVien = state.loaiDaVe || "video";   // công tắc "Loại" cũng về loại đang thật sự vẽ
          renderLibrary();
          g.dataset.napPhia = String(state.phiaDaVe);
        } else {
          // Chưa vẽ lần nào: không vẽ, nhưng chip vẫn về mặc định (tắt) cho khớp
          // lưới rỗng, và hết "đang nạp".
          state.chiVaoBo = false;
          state.loaiThuVien = "video";
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
    state.loaiDaVe = loai;
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
    grid.dataset.napLoai = loai;
    // Mốc "lượt `luot` đã kết thúc" (thành công hay hỏng) — tín hiệu chắc chắn cho test.
    grid.dataset.luotXong = String(luot);
    loadBadgeDonLoi().catch(() => { /* phiên hết hạn đã được các lời gọi khác báo */ });
    return true;
  }

  // Một BÀI ảnh (`GET /anh`) ⇒ một "thẻ" cùng hình video: lấy hàng của tệp 01 làm gốc (tiêu đề, người đăng, link gốc,
  // `drive_file_id`…), đè danh tính bằng `bai_id` (khoá chọn/lọc của lưới) và mang `files`/`file_ids` để thao tác
  // (gửi Creative Desk, Bỏ) mở rộng thành TỪNG TỆP. `thumb_id` = video_id của tệp 01 (thumb đặt tên theo tệp).
  function theTuBaiAnh(b) {
    const dau = b.files[0] || {};
    const daVaoBo = b.files.find((f) => f.vao_bo);
    return {
      ...dau, video_id: b.bai_id, loai: "anh", bai_id: b.bai_id, thumb_id: b.thumb_id,
      file_ids: b.file_ids, so_anh: b.so_anh, files: b.files, nguon: b.nguon, tao_luc: b.tao_luc,
      cum_id: null, vao_bo: daVaoBo ? daVaoBo.vao_bo : null, duration: null, play_count: null,
    };
  }

  // Công tắc "Loại" Video | Ảnh của thư viện — KHÔNG phải nhóm trong `FILTER_GROUPS`: nhóm lọc chỉ cắt trên tập đã
  // nạp, mà ảnh nằm ở API khác nên chọn loại phải NẠP LẠI. Vẽ bằng JS, chỉ khi tính năng bật (cờ tắt ⇒ DOM y hệt cũ).
  function veCongTacLoaiThuVien() {
    const hang = document.querySelector(".filter-row");
    if (!hang || state.taiAnhBat !== true) return;
    if (!document.getElementById("chip-loai")) {
      const nhom = document.createElement("span");
      nhom.id = "chip-loai";
      nhom.className = "chip-loai";
      nhom.setAttribute("role", "group");
      nhom.setAttribute("aria-label", "Loại trong thư viện");
      nhom.innerHTML = '<span class="chip-loai-nhan">Loại</span>' +
        '<button type="button" data-loai-thu-vien="video">Video</button>' +
        '<button type="button" data-loai-thu-vien="anh">Ảnh</button>';
      nhom.addEventListener("click", (ev) => {
        const b = ev.target.closest("[data-loai-thu-vien]");
        if (b) doiLoaiThuVien(b.dataset.loaiThuVien);
      });
      hang.insertBefore(nhom, hang.firstChild);
    }
    veTrangThaiLoaiThuVien();
  }

  // Tô nút đang chọn + đánh dấu lưới theo loại (CSS ẩn cụm/"Đưa vào cụm" ở chế độ ảnh). Gọi từ `renderLibrary`.
  function veTrangThaiLoaiThuVien() {
    document.querySelectorAll("#chip-loai [data-loai-thu-vien]").forEach((b) => {
      const on = b.dataset.loaiThuVien === state.loaiThuVien;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const lay = document.querySelector(".lib-layout");
    if (lay) lay.dataset.loai = state.loaiThuVien;
    document.body.dataset.loaiThuVien = state.loaiThuVien;
  }

  // Đổi loại ⇒ nạp lại từ API tương ứng. Khoá chọn của hai loại khác nhau (video_id ↔ bai_id) nên lựa chọn bị xoá,
  // và cụm/trang/bộ lọc về mặc định (ảnh không có cụm). Nạp hỏng ⇒ `loadVideos` đưa công tắc về loại đang vẽ.
  async function doiLoaiThuVien(loai) {
    if (loai === state.loaiThuVien || (loai !== "video" && loai !== "anh")) return;
    state.loaiThuVien = loai;
    state.selected.clear();
    state.cumLoc = "tat_ca";
    state.trang = 1;
    for (const g of FILTER_GROUPS) state.filters[g.id].clear();
    renderFilterBar();
    veTrangThaiLoaiThuVien();
    renderSelectionBar();
    await napLaiThuVien();
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
