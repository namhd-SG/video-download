// Gọi các hàm THẬT trích từ web/static/app.js cho phần giữ lựa chọn xuyên trang.
// In một dòng JSON cho pytest.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (n) => {
  const i = src.indexOf(`function ${n}(`);
  if (i < 0) return "";
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};
eval(grab("demNgoaiTrang") + "\n" + grab("nhanNgoaiTrang") + "\n" + grab("dongNgoaiTrang"));
const m = src.match(/const SO_MOI_TRANG = Object\.freeze\((\[[^\]]*\])\)/);
const trang1 = ["a", "b", "c"];
process.stdout.write(JSON.stringify({
  so_moi_trang: m ? JSON.parse(m[1]) : null,
  ngoai_0: demNgoaiTrang(new Set(["a", "b"]), trang1),
  ngoai_2: demNgoaiTrang(new Set(["a", "x", "y"]), trang1),
  ngoai_rong: demNgoaiTrang(new Set(), trang1),
  nhan_0: nhanNgoaiTrang(0),
  nhan_2: nhanNgoaiTrang(2),
  dong_0: dongNgoaiTrang(0),
  dong_2: dongNgoaiTrang(2),
}));
