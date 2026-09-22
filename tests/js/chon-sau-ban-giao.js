// Gọi `moBoTuTim` THẬT trích từ web/static/app.js, không đọc chuỗi.
// In một dòng JSON cho pytest đọc.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (n) => {
  const i = src.indexOf(`function ${n}(`);
  // Khoan dung: harness phải chạy được trên CẢ bản chưa vá (nơi
  // `boChonTatCa` chưa tồn tại), nếu không thì không có đối chứng.
  if (i < 0) return "";
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};

function chay({ popupBiChan }) {
  const CREATIVE_DESK_URL = "https://automation.example";
  const HANDOFF_MAX = 30;
  const state = {
    selected: new Set(["v1", "v2", "v3"]),
    videos: ["v1", "v2", "v3"].map((id) => ({
      video_id: id, drive_file_id: "d" + id, title: "t" + id, url: "u" + id,
    })),
  };
  const daGoi = { renderSelectionBar: 0, open: 0, toast: [] };
  const the = state.videos.map(() => ({
    classList: { _co: true, remove() { this._co = false; } },
    setAttribute(k, v) { this._aria = v; },
  }));
  const showToast = (m) => daGoi.toast.push(m);
  const renderSelectionBar = () => { daGoi.renderSelectionBar++; };
  const document = { querySelectorAll: () => the };
  const window = {
    open: () => { daGoi.open++; return popupBiChan ? null : { focus() {} }; },
  };
  eval(grab("boChonTatCa") + "\n" + grab("moBoTuTim"));
  moBoTuTim();
  return {
    conChon: state.selected.size,
    moTab: daGoi.open,
    theConTo: the.filter((t) => t.classList._co).length,
    veLaiThanh: daGoi.renderSelectionBar,
  };
}

console.log(JSON.stringify({
  binh_thuong: chay({ popupBiChan: false }),
  popup_bi_chan: chay({ popupBiChan: true }),
}));
