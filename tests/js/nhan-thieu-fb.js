// Chạy hàm THẬT `BaoThieu.nhanThieu` / `soChayLai` của web/static/bao-thieu.js trên job Facebook page bị tường đăng nhập.
// In một dòng JSON cho pytest (tests/test_fb_bang_ma_dung.py).
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const B = window.BaoThieu;
// Ca bắt buộc: xin 30, dò được 16, tải xong 16, dừng vì tường — KHÔNG được ghi "Xong" xanh (nhãn = null).
const job = { trang_thai: "done", tong: 30, tim_thay: 16, xong: 16, ly_do_dung: "fb_chan_dang_nhap" };
console.log(JSON.stringify({
  nhan_tuong: B.nhanThieu(job),
  chay_lai: B.soChayLai(job),
  // đối chứng: cùng số liệu nhưng không có mã ⇒ không có nhãn theo mã
  nhan_khong_ma: B.nhanThieu({ ...job, ly_do_dung: null }),
  // tường nhưng tải được đủ số xin ⇒ vẫn theo mã (mã dừng quyết nhãn)
  nhan_du_so: B.nhanThieu({ ...job, tong: 16 }),
}));
