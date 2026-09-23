// Gọi `catTrang` THẬT trích từ web/static/app.js. In một dòng JSON cho pytest.
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
eval(grab("catTrang") + "\n" + grab("dayTrang"));
const ds = Array.from({ length: 86 }, (_, i) => `v${i}`);
const tom = (r) => ({ trang: r.trang, soTrang: r.soTrang, dau: r.dau, so: r.muc.length,
                      dauTien: r.muc[0] ?? null });
process.stdout.write(JSON.stringify({
  t1: tom(catTrang(ds, 1, 40)), t2: tom(catTrang(ds, 2, 40)), t3: tom(catTrang(ds, 3, 40)),
  qua: tom(catTrang(ds, 9, 40)), am: tom(catTrang(ds, 0, 40)),
  mot: tom(catTrang(ds, 1, 100)), rong: tom(catTrang([], 1, 40)),
  day_giua: dayTrang(100, 200), day_dau: dayTrang(1, 3), day_1: dayTrang(1, 1),
}));
