// Gọi `moBoTuTim` THẬT trích từ web/static/app.js (đường postMessage, 26/09).
// `window` và tab Creative Desk là giả; hẹn giờ là thật nhưng rút ngắn.
// In một dòng JSON cho pytest đọc.
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

// cachTra: "ack" | "tu_choi" | "im" | "sai_origin" | "sai_id" | null (popup bị chặn)
async function chay({ cachTra, ackSauLuot = 2, soVideo = 3, chuaDrive = 0, bamDup = false, lanHaiAck = false }) {
  const CREATIVE_DESK_URL = "https://automation.example";
  const CREATIVE_DESK_ORIGIN = "https://automation.example";
  const MAX_PM_ITEMS = 500;
  const PM_CHU_KY_MS = 5;
  const PM_HAN_MS = 120;
  const ids = Array.from({ length: soVideo }, (_, i) => `v${i}`);
  const state = {
    selected: new Set(ids),
    videos: ids.map((id, i) => ({ video_id: id, drive_file_id: i < chuaDrive ? null : "d" + id,
                                  title: "t" + id, url: "u" + id })),
    idTrang: [], dangBanGiao: false, banGiaoDo: null,
  };
  const daGoi = { renderSelectionBar: 0, open: 0, toast: [], gui: [], url: null };
  const the = state.videos.map(() => ({
    classList: { _co: true, remove() { this._co = false; } },
    setAttribute() {},
  }));
  const showToast = (m) => daGoi.toast.push(m);
  const renderSelectionBar = () => { daGoi.renderSelectionBar++; };
  const nut = { disabled: false, textContent: "Tạo bộ tự tìm" };
  const document = { querySelectorAll: () => the, getElementById: () => null, querySelector: () => nut };
  const nguoiNghe = new Set();
  const window = {
    open: (url) => {
      daGoi.open++; daGoi.url = url;
      if (cachTra === null) return null;
      return {
        closed: false,
        postMessage(tin, dich) {
          daGoi.gui.push({ dich, tin });
          if (cachTra === "im" || daGoi.gui.length < ackSauLuot || daGoi.daAck) return;
          daGoi.daAck = true;
          const origin = cachTra === "sai_origin" ? "https://ke-gian.example" : CREATIVE_DESK_ORIGIN;
          const data = { type: "videodesk-ack", id: cachTra === "sai_id" ? "khac" : tin.id,
                         ok: cachTra !== "tu_choi", reason: cachTra === "tu_choi" ? "day" : undefined };
          setTimeout(() => nguoiNghe.forEach((f) => f({ origin, data })), 0);
        },
      };
    },
    addEventListener: (t, f) => { if (t === "message") nguoiNghe.add(f); },
    removeEventListener: (t, f) => { if (t === "message") nguoiNghe.delete(f); },
  };
  // `grab` cắt từ chữ "function" nên mất tiền tố `async` của moBoTuTim — gắn lại.
  eval(["veNutChonTrang", "boChonTatCa", "datNutBanGiao", "guiBanGiaoPm",
        "itemBanGiao", "moTabCreativeDesk"].map(grab).join("\n") + "\n" +
       grab("moBoTuTim").replace(/^function/, "async function") + "\nvar __f = moBoTuTim;");
  const p1 = __f();
  const nutKhiCho = { disabled: nut.disabled, text: nut.textContent };
  if (bamDup) await __f();          // lần 2 trong lúc lần 1 đang chờ ack
  await p1;
  // Gửi lại: lần 1 hết hạn (tab vẫn mở), đổi sang chế độ ack rồi bấm lần 2 ⇒
  // phải gửi vào ĐÚNG tab cũ với ĐÚNG id, không mở tab mới.
  if (lanHaiAck) {
    const idLan1 = daGoi.gui[0].tin.id;
    cachTra = "ack"; daGoi.daAck = false;
    const truoc = daGoi.gui.length;
    await __f();
    daGoi.lanHai = { cungId: daGoi.gui.slice(truoc).every((g) => g.tin.id === idLan1),
                     soGuiThem: daGoi.gui.length - truoc };
  }
  const tin = daGoi.gui[0] ? daGoi.gui[0].tin : null;
  return {
    moTab: daGoi.open,
    url: daGoi.url,
    conChon: state.selected.size,
    theConTo: the.filter((t) => t.classList._co).length,
    veLaiThanh: daGoi.renderSelectionBar,
    soLanGui: daGoi.gui.length,
    dich: daGoi.gui[0] ? daGoi.gui[0].dich : null,
    tin: tin && { type: tin.type, v: tin.v, coId: typeof tin.id === "string" && tin.id.length >= 8,
                  soItem: tin.items.length, coNhan: "nhan" in tin },
    nutKhiCho, nutSau: { disabled: nut.disabled, text: nut.textContent },
    conDo: state.banGiaoDo !== null,
    toast: daGoi.toast.join(" | "),
    lanHai: daGoi.lanHai || null,
  };
}

(async () => {
  const kq = {
    ack: await chay({ cachTra: "ack" }),
    tu_choi: await chay({ cachTra: "tu_choi" }),
    im: await chay({ cachTra: "im" }),
    sai_origin: await chay({ cachTra: "sai_origin" }),
    sai_id: await chay({ cachTra: "sai_id" }),
    popup_bi_chan: await chay({ cachTra: null }),
    nhieu: await chay({ cachTra: "ack", soVideo: 90, chuaDrive: 4 }),
    qua_tran: await chay({ cachTra: "ack", soVideo: 501 }),
    bam_dup: await chay({ cachTra: "ack", ackSauLuot: 3, bamDup: true }),
    gui_lai: await chay({ cachTra: "im", lanHaiAck: true }),
  };
  process.stdout.write(JSON.stringify(kq));
})();
