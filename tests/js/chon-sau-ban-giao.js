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
  // `getElementById` → null: `veNutChonTrang` (phân trang, 23/09) tự thoát khi
  // không có nút; harness này không đo nút đó.
  const document = { querySelectorAll: () => the, getElementById: () => null };
  const window = {
    open: (url) => { daGoi.open++; daGoi.url = url; return popupBiChan ? null : { focus() {} }; },
  };
  state.idTrang = [];  // `veNutChonTrang` đọc trường này
  eval(["veNutChonTrang", "boChonTatCa", "moBoTuTim", "itemBanGiao", "dungPayload",
        "maHoaPayload", "urlBanGiao", "moTabCreativeDesk"].map(grab).join("\n"));
  moBoTuTim();
  return {
    conChon: state.selected.size,
    moTab: daGoi.open,
    theConTo: the.filter((t) => t.classList._co).length,
    veLaiThanh: daGoi.renderSelectionBar,
    // Payload giải mã từ URL THẬT đã đưa cho `window.open` — bàn giao chọn tay
    // KHÔNG được mang `nhan` (hợp đồng, quy tắc 2).
    payload: daGoi.url ? JSON.parse(Buffer.from(
      new URL(daGoi.url).searchParams.get("videodesk"), "base64url").toString("utf8")) : null,
  };
}

console.log(JSON.stringify({
  binh_thuong: chay({ popupBiChan: false }),
  popup_bi_chan: chay({ popupBiChan: true }),
}));
