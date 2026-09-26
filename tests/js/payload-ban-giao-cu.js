// Golden payload dựng bằng CHÍNH bản JS CŨ (trước khi payload chuyển sang
// dựng ở server, `git show 97c6f3b`) — không phải một bản Python cổng lại
// logic JS. Trích `nhanTuCum`/
// `dungPayload`/`itemBanGiao`/`chiaLo`/`videoCuaCum` NGUYÊN VĂN từ nội dung
// app.js cũ (argv[2]), chạy trên một fixture cụm (argv[3], JSON), in ra
// CHUỖI JSON kết quả (không format lại) để pytest so byte-equal với payload
// server hiện tại.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const fixture = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

const grab = (n) => {
  const i = src.indexOf(`function ${n}(`);
  if (i < 0) throw new Error(`không tìm thấy function ${n}(...) trong app.js cũ`);
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
  throw new Error(`không đóng được thân hàm ${n}`);
};

// `videoCuaCum` (bản cũ) đọc `state.videos` — mồi state với fixture, giữ
// NGUYÊN THỨ TỰ đã cho (test Python xếp DESC theo tao_luc, giống thứ `/videos`
// trả về thật, để `.reverse()` của hàm cũ cho ra đúng "cũ nhất trước").
const state = { videos: fixture.videos };

eval(["chiaLo", "videoCuaCum", "itemBanGiao", "dungPayload", "nhanTuCum"].map(grab).join("\n"));

const lo = chiaLo(videoCuaCum(fixture.cum.id), fixture.handoffMax);
const muc = lo[fixture.thu - 1] || [];
const items = muc.filter((v) => v.drive_file_id).map(itemBanGiao);
const nhan = nhanTuCum(fixture.cum, fixture.thu, lo.length || 1);
process.stdout.write(JSON.stringify(dungPayload(items, nhan)));
