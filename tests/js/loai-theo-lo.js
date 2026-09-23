// Gọi `loaiDaChon` THẬT trích từ web/static/app.js, với `apiSend` giả áp ĐÚNG
// trần của backend (`MAX_VIDEO_LOAI`, truyền vào argv[3]): quá trần ⇒ ném lỗi
// 422 như FastAPI thật. In một dòng JSON cho pytest đọc.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const TRAN_BACKEND = Number(process.argv[3]);

const grab = (n) => {
  const i = src.indexOf(`function ${n}(`);
  if (i < 0) return "";
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};
// Hằng lô: trích dòng khai báo nếu có. Bản chưa vá không có ⇒ harness vẫn chạy
// (đối chứng), hàm cũ không đọc tới nó.
const hang = (src.match(/const LOAI_TOI_DA_MOI_LUOT = \d+;/) || [""])[0];

async function chay({ soId, loLoi = null }) {
  class PhienHetHan extends Error {}
  const state = { selected: new Set(Array.from({ length: soId }, (_, i) => `v${i}`)) };
  const goi = [];
  const toast = [];
  let lanNap = 0;
  const apiSend = async (method, path, body) => {
    goi.push(body.video_ids.length);
    const nem = (st) => { const e = new Error(`${method} ${path} -> ${st}`); e.status = st; throw e; };
    if (body.video_ids.length > TRAN_BACKEND) nem(422);
    if (loLoi !== null && goi.length === loLoi) nem(500);
    return { da_loai: body.video_ids, drive_truot: [], khong_phai_cua_ban: [] };
  };
  const loadVideos = async () => { lanNap++; };
  const renderSelectionBar = () => {};
  const showToast = (m) => toast.push(m);
  const baoPhienHetHan = () => {};
  const window = { confirm: () => true };
  eval(hang + "\n" + grab("lyDoLoiLoai") + "\n" + grab("loaiDaChon").replace(/^function/, "async function") + "\nvar __f = loaiDaChon;");
  await __f();
  return { goi, conChon: state.selected.size, toast: toast.join(" | "), lanNap };
}

(async () => {
  const out = {
    ba_lo: await chay({ soId: 120 }),
    mot_lo: await chay({ soId: 30 }),
    dung_ngay_50: await chay({ soId: 50 }),
    loi_lo_2: await chay({ soId: 120, loLoi: 2 }),
  };
  process.stdout.write(JSON.stringify(out));
})();
