// Gọi hàm THẬT `taoJobBody` trích từ web/static/app.js (không chép lại logic).
// In một dòng JSON cho pytest (tests/test_web_app.py).
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (n) => {
  let i = src.indexOf(`function ${n}(`);
  if (i < 0) return "";
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};

eval(grab("taoJobBody"));

console.log(JSON.stringify({
  khong_dien_gi: taoJobBody("https://x", 5, "", ""),
  dien_ca_hai: taoJobBody("https://x", 5, "Dance", "Badaboum"),
  chi_usecase: taoJobBody("https://x", 5, "Dance", ""),
  chi_insight: taoJobBody("https://x", 5, "", "Badaboum"),
}));
