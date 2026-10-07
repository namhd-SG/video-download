// Báo thiếu trên hàng đợi: nguồn cho bao nhiêu, tải xong bao nhiêu TRÊN số dò
// được, lỗi do TikTok hay do hệ thống, và khi nào có nút chạy lại.
//
// Thuần (không đụng DOM, không gọi mạng) để `tests/js/bao-thieu.js` chạy được
// bằng node. Mọi HTML ở đây chỉ nhúng SỐ (đã ép `Number`) và chuỗi cố định —
// không có chuỗi người dùng nào đi qua, nên không cần escape.
//
// Không đổi máy trạng thái job: "Thiếu" / "Nguồn hụt" là nhận xét về KẾT QUẢ ở
// giao diện (USER CHỐT 21/09, xem `app.js::nhanTrangThai`).
(function () {
  "use strict";

  // Trần `so_luong` của POST /jobs — bằng `web/app.py::MAX_SO_LUONG`.
  const MAX_SO_LUONG = 2000;

  // Bốn mã dừng mà CHẠY LẠI có thể ra thêm video. Các mã còn lại cố ý không có
  // nút: `nghi_bi_chan` cần NGHỈ (chạy lại ngay làm đậm dấu vết), `stalled` /
  // `already_owned` / `source_empty` chạy lại cũng ra đúng như vậy, và mã cookie
  // phải chữa cookie trước.
  // `het_dia` (đĩa máy chạy dưới ngưỡng giữa job nền tảng khác) cũng chạy lại được: sau khi đĩa có chỗ,
  // lọc trùng bỏ phần đã lên Drive và tải phần còn lại.
  const MA_CHAY_LAI_DUOC = new Set(["het_vong", "het_thoi_gian", "page_cap", "het_dia"]);

  // Nhãn theo LÝ DO DỪNG cho bốn mã không chạy lại được ngay — nhãn phải nói
  // đúng việc nên làm, nên trùng ý câu ở `app.js::STOP_REASON_TEXT`:
  //   nghi_bi_chan  ⇒ "Nghi bị chặn"  (NGHỈ đã)
  //   stalled       ⇒ "Hết video"     (nguồn không còn gì TikTok cho xem)
  //   already_owned ⇒ "Đã có hết"     (thư viện có hết, đổi nguồn)
  //   source_empty  ⇒ "Nguồn rỗng"
  const NHAN_THEO_LY_DO = Object.freeze({
    nghi_bi_chan: "Nghi bị chặn", stalled: "Hết video",
    already_owned: "Đã có hết", source_empty: "Nguồn rỗng",
  });

  const DANG_CHAY = new Set(["pending", "running"]);

  const so = (x) => Number(x) || 0;

  function soLieu(job) {
    const tong = so(job.tong), tim = so(job.tim_thay), boQua = so(job.bo_qua);
    const loi = so(job.loi);
    const suCoHangLoat = Number(job.nghi_su_co_hang_loat) === 1;
    // `loi_tiktok` NULL = job tạo trước khi có phân loại: KHÔNG biết lỗi nào là
    // của ai, nên không được tính thành lỗi hệ thống (khung đỏ / nhãn Thiếu).
    const chuaPhanLoai = job.loi_tiktok === null || job.loi_tiktok === undefined;
    const loiTiktok = chuaPhanLoai ? 0 : Math.min(so(job.loi_tiktok), loi);
    return {
      tong, tim, boQua, xong: so(job.xong), loi, loiTiktok, suCoHangLoat,
      loiChuaPhanLoai: chuaPhanLoai ? loi : 0,
      loiHt: chuaPhanLoai ? 0 : loi - loiTiktok,
    };
  }

  // Mẫu số của thanh tiến độ: số DÒ ĐƯỢC khi đã biết, còn `tong` (số xin) khi
  // còn đang dò. Chia cho số xin làm một lượt đã tải HẾT nguồn đọc thành 87/140.
  function mauSo(job) {
    const s = soLieu(job);
    return s.tim > 0 ? s.tim : s.tong;
  }

  function phanTram(job) {
    const m = mauSo(job);
    return m > 0 ? Math.min(100, Math.round((so(job.xong) / m) * 100)) : 0;
  }

  function chuTienDo(job) {
    const s = soLieu(job);
    let t = `Tải ${s.xong}/${mauSo(job)}`;
    if (DANG_CHAY.has(job.trang_thai) && s.tim > 0) {
      t += ` · nguồn có ${s.tim + s.boQua} (xin ${s.tong})`;
    }
    return t;
  }

  // Nhãn cho job `done`; `null` = để `nhanTrangThai` dùng nhãn trạng thái gốc.
  //   Thiếu        — có lỗi HỆ THỐNG, hoặc thiếu mà không giải thích được
  //   (theo mã)    — bốn mã dừng ở `NHAN_THEO_LY_DO`: nhãn nói lý do dừng
  //   Nguồn hụt    — CHỈ nhóm chạy lại được (het_vong/het_thoi_gian/page_cap), nguồn
  //                  cho ít hơn số xin, không có lỗi hệ thống
  function nhanThieu(job) {
    if (job.trang_thai !== "done") return null;
    const s = soLieu(job);
    if (s.tong <= 0) return null;
    if (s.loiHt > 0 || s.suCoHangLoat) return { chu: "Thiếu", lop: "thieu" };
    const theoMa = NHAN_THEO_LY_DO[job.ly_do_dung];
    if (theoMa) return { chu: theoMa, lop: "thieu" };
    if (MA_CHAY_LAI_DUOC.has(job.ly_do_dung) && s.tim > 0 && s.tim < s.tong) {
      return { chu: "Nguồn hụt", lop: "thieu" };
    }
    // Thiếu KHÔNG giải thích được: sau khi cộng phần lỗi đã có tên (TikTok không
    // cho tải / chưa phân loại) mà vẫn chưa đủ số video dò được. Thiếu chỉ vì
    // TikTok bỏ qua video thì đã có khung xám nói rồi — không phải "Thiếu".
    const canDat = Math.min(s.tim || s.tong, s.tong);
    if (s.xong + s.loiTiktok + s.loiChuaPhanLoai < canDat) return { chu: "Thiếu", lop: "thieu" };
    return null;
  }

  // Dòng "nguồn lần này có …". Chỉ khi lượt đã dò xong và dừng: đang chạy thì
  // con số đã nằm ở dòng tiến độ, và `bo_qua` còn đang tăng.
  function dongNguon(job) {
    if (DANG_CHAY.has(job.trang_thai)) return "";
    const s = soLieu(job);
    if (s.tim <= 0 && s.boQua <= 0) return "";
    const tong = s.tim + s.boQua;
    const chiTiet = s.boQua > 0 ? ` ${s.tim} mới · ${s.boQua} đã có trong kho.` : "";
    if (s.tim >= s.tong) {
      return `<b>Nguồn lần này có ${tong} video</b> — đủ số bạn xin.${chiTiet}`;
    }
    return `<b>Nguồn lần này có ${tong} video</b> (bạn xin ${s.tong})` +
      (s.boQua > 0 ? `:${chiTiet}` : ".");
  }

  function coSuCoHangLoat(job) {
    return soLieu(job).suCoHangLoat;
  }

  // Cờ sự cố hàng loạt mâu thuẫn với câu "chạy lại có thể ra thêm" — chỉ ba mã
  // khuyên chạy lại mới bị ẩn câu dừng; câu của mã khác (vd. "Hãy NGHỈ…") vẫn
  // đúng và vẫn cần.
  function anCauDung(job) {
    return soLieu(job).suCoHangLoat && MA_CHAY_LAI_DUOC.has(job.ly_do_dung);
  }

  // Có lỗi HỆ THỐNG đã xác định (đỏ)? Lỗi chưa phân loại không tính.
  function coLoiHeThong(job) {
    const s = soLieu(job);
    return s.loiHt > 0 || s.suCoHangLoat;
  }

  function khungLoi(job) {
    const s = soLieu(job);
    let h = "";
    if (s.suCoHangLoat) {
      // Ghi đè khung xám TikTok: nhiều video cùng một lỗi không còn là "từng
      // video hỏng, bỏ qua được".
      h += `<div class="lo-ht">Có thể là sự cố hàng loạt (nhiều video cùng báo ` +
        `'Requested format') — không phải lỗi từng video, báo người phát triển.</div>`;
    } else if (s.loiTiktok > 0) {
      h += `<div class="lo-tt">${s.loiTiktok} video TikTok không cho tải ` +
        `(bài dạng ảnh, bị gỡ hoặc không có bản video) — đã bỏ qua, không phải lỗi hệ thống.</div>`;
    }
    if (s.loiChuaPhanLoai > 0) {
      h += `<div class="lo-tt">${s.loiChuaPhanLoai} lỗi (chưa phân loại — lượt trước bản cập nhật)</div>`;
    }
    if (s.loiHt > 0) {
      h += `<div class="lo-ht">${s.loiHt} video lỗi hệ thống (không tải hoặc không lên được ` +
        `Drive) — báo người phát triển.</div>`;
    }
    return h;
  }

  // Số video kiếm thêm khi chạy lại: phần THIẾU so với số đã xin, không phải
  // số đã xin — chạy lại y nguyên `tong` sẽ đòi thêm video mà lượt này đã có.
  // `null` = không có nút chạy lại.
  function soChayLai(job) {
    const s = soLieu(job);
    // Cờ sự cố hàng loạt ⇒ chạy lại chỉ gặp lại đúng lỗi đó: không mời bấm.
    if (s.suCoHangLoat) return null;
    if (!MA_CHAY_LAI_DUOC.has(job.ly_do_dung) || s.tong <= 0 || s.xong >= s.tong) return null;
    return Math.min(s.tong - s.xong, MAX_SO_LUONG);
  }

  // `mo` = số đang gõ trong ô xác nhận (hoặc `null` khi ô đóng); `dangGui` = đang
  // chờ POST của lượt chạy lại này ⇒ nút xác nhận khoá.
  function khungHanhDong(job, mo, dangGui) {
    const id = so(job.id);
    const n = soChayLai(job);
    let nut = "";
    if (n !== null) {
      nut += mo === null || mo === undefined
        ? `<button type="button" class="btn primary" data-chay-lai="${id}">Chạy lại để kiếm thêm ${n} video…</button>`
        : `<span class="chay-lai-xn">Kiếm thêm <input type="number" class="chay-lai-n" ` +
          `data-chay-lai-n="${id}" min="1" max="${MAX_SO_LUONG}" value="${so(mo)}" ` +
          `aria-label="Số video kiếm thêm"> video ` +
          `<button type="button" class="btn primary" data-chay-lai-ok="${id}"${dangGui ? " disabled" : ""}>Chạy lại</button> ` +
          `<button type="button" class="btn ghost" data-chay-lai-huy="${id}">Thôi</button></span>`;
    }
    nut += `<button type="button" class="btn" data-chep-link="${id}">Chép link</button>`;
    return `<div class="actions">${nut}</div>`;
  }

  // Ép số gõ vào ô xác nhận về 1..MAX_SO_LUONG; không phải số nguyên ⇒ null.
  function chuanHoaSoChayLai(raw) {
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 1 || n > MAX_SO_LUONG) return null;
    return n;
  }

  window.BaoThieu = Object.freeze({
    MAX_SO_LUONG, mauSo, phanTram, coLoiHeThong, coSuCoHangLoat, anCauDung, chuTienDo, nhanThieu, dongNguon, khungLoi,
    soChayLai, khungHanhDong, chuanHoaSoChayLai,
  });
})();
