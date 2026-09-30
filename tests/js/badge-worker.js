// Gọi `chuBadgeWorker` THẬT trích từ web/static/app.js. In một dòng JSON cho pytest.
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
eval(grab("chuBadgeWorker"));
const tt = (o) => Object.assign({ song: true, loi_lien_tiep: 0, loi_cuoi: null, cho_dia: null }, o);
process.stdout.write(JSON.stringify({
  null: chuBadgeWorker(null),
  ok: chuBadgeWorker(tt({})),
  chet: chuBadgeWorker(tt({ song: false })),
  loi: chuBadgeWorker(tt({ loi_lien_tiep: 3, loi_cuoi: "OperationalError" })),
  dia: chuBadgeWorker(tt({ cho_dia: "đĩa còn 1 MB" })),
  ket: chuBadgeWorker(tt({ job_ket: [7, 9] })),
}));
