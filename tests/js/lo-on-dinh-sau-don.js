// Cắt lô phía trang khi có video đã dọn khỏi Drive: `chiaLo(videoCuaCum(id), 30)`
// THẬT trích từ web/static/app.js. Cụm 65 video v001..v065 (cũ nhất trước theo
// tao_luc) ⇒ lô 30/30/5. In id từng lô TRƯỚC và SAU khi v005 được dọn. Fixture
// giống hệt `tests/test_lo_on_dinh_sau_don.py`.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (n) => {
  const i = src.indexOf(`function ${n}(`);
  if (i < 0) throw new Error(`không thấy hàm ${n}`);
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};
const state = { videos: [], videosDaDon: [] };
eval(["chiaLo", "videoCuaCum"].map(grab).join("\n"));

const CUM = 7;
const id = (i) => `v${String(i).padStart(3, "0")}`;
const luc = (i) => `2026-09-01T00:${String(Math.floor(i / 60)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}+00:00`;
const tatCa = Array.from({ length: 65 }, (_, k) => k + 1);
const the = (i) => ({ video_id: id(i), tao_luc: luc(i), cum_id: CUM });
const lo = () => chiaLo(videoCuaCum(CUM), 30).map((l) => l.map((v) => v.video_id + (v.da_don ? "*" : "")));

// `/videos` trả DESC (mới nhất trước) — `videoCuaCum` tự đảo.
state.videos = tatCa.slice().reverse().map(the);
const truoc = lo();
// v005 được dọn: rời `state.videos`, sang `videosDaDon`.
state.videos = tatCa.filter((i) => i !== 5).reverse().map(the);
state.videosDaDon = [the(5)];
const sau = lo();
// Cụm khác không bị lẫn ghost của cụm này.
state.videosDaDon = [the(5), { video_id: "x", tao_luc: luc(1), cum_id: 99 }];
const lanKhac = lo();
process.stdout.write(JSON.stringify({ truoc, sau, lanKhac }));
