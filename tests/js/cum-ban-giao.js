// Gọi các hàm cụm THẬT trích từ web/static/app.js (không đọc chuỗi, không
// chép lại logic). In một dòng JSON cho pytest (tests/test_cum_browser_and_js.py).
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (n) => {
  let i = src.indexOf(`function ${n}(`);
  if (i < 0) return "";
  if (src.slice(i - 6, i) === "async ") i -= 6;   // giữ `async` — thiếu nó thì `await` là lỗi cú pháp
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};
const hang = (n) => {
  const m = src.match(new RegExp(`const ${n} = (\\d+);`));
  return m ? Number(m[1]) : null;
};
const giaiMa = (url) => JSON.parse(Buffer.from(
  new URL(url).searchParams.get("videodesk"), "base64url").toString("utf8"));

const CREATIVE_DESK_URL = "https://automation.example";
const HANDOFF_MAX = hang("HANDOFF_MAX");
const GAN_CUM_TOI_DA = hang("GAN_CUM_TOI_DA");
class PhienHetHan extends Error {}

// `insight` CỐ Ý khác `insight_goc + " " + kieu`: nếu payload lấy tên từ chuỗi
// JS tự ghép thay vì từ dữ liệu cụm, test sẽ thấy "Badaboum couple" thay vì
// "INSIGHT-TU-SERVER".
const CUM = { id: 12, usecase: "Dance", insight_goc: "Badaboum", kieu: "couple",
              insight: "INSIGHT-TU-SERVER", lo_mo: [] };

function chay({ soVideo, thu, popupBiChan, cum = CUM }) {
  const nhatKy = [];
  const toast = [];
  const state = {
    cums: [JSON.parse(JSON.stringify(cum))],
    videos: Array.from({ length: soVideo }, (_, i) => ({
      video_id: `v${i}`, drive_file_id: `d${i}`, title: `t${i}`, url: `u${i}`, cum_id: cum.id,
    })),
  };
  const showToast = (m) => toast.push(m);
  const baoPhienHetHan = () => {};
  const renderCumHead = () => nhatKy.push("ve");
  const window = { open: (url) => { nhatKy.push("open"); nhatKy.url = url;
                                    return popupBiChan ? null : { opener: 1 }; } };
  const apiSend = async (method, path) => { nhatKy.push(`${method} ${path}`);
                                            return { mo_luc: "2026-09-23T10:42:00+00:00" }; };
  eval(["moLoCum", "chiaLo", "videoCuaCum", "itemBanGiao", "dungPayload", "nhanTuCum",
        "maHoaPayload", "urlBanGiao", "moTabCreativeDesk"].map(grab).join("\n"));
  return moLoCum(cum.id, thu).then((kq) => ({
    kq, nhatKy: [...nhatKy], toast,
    payload: nhatKy.url ? giaiMa(nhatKy.url) : null,
    lo_mo: state.cums[0].lo_mo,
  }));
}

async function chayDuaVao(nhap, cums) {
  const goi = [];
  const toast = [];
  const state = { cums: JSON.parse(JSON.stringify(cums)),
                  videos: [{ video_id: "v1", cum_id: null }, { video_id: "v2", cum_id: null }] };
  const showToast = (m) => toast.push(m);
  const apiSend = async (method, path, body) => {
    goi.push(`${method} ${path}`);
    if (path === "/cum") return { id: 99, usecase: body.usecase, insight_goc: body.insight_goc,
                                  kieu: body.kieu, insight: "moi", lo_mo: [] };
    return { so_video: body.video_ids.length, bo_qua: [] };
  };
  eval(["duaVaoCum", "timCumTrung", "khoaNhan"].map(grab).join("\n"));
  const cumId = await duaVaoCum(nhap, ["v1", "v2"]);
  return { cumId, goi, cum_id_video: state.videos.map((v) => v.cum_id) };
}

(async () => {
  eval(["chiaLo", "khoaNhan", "timCumTrung", "xemTruocTen"].map(grab).join("\n"));
  const dai = (n) => chiaLo(Array.from({ length: n }, (_, i) => i), HANDOFF_MAX).map((l) => l.length);
  const out = {
    HANDOFF_MAX, GAN_CUM_TOI_DA,
    lo_64: dai(64), lo_30: dai(30), lo_31: dai(31), lo_0: dai(0),
    trung_hoa_thuong: timCumTrung([CUM], "  dance ", "BADABOUM", " Couple  ")?.id ?? null,
    trung_khac_kieu: timCumTrung([CUM], "Dance", "Badaboum", "cartoon")?.id ?? null,
    xem_truoc: xemTruocTen("  Badaboum ", "  couple  "),
    // Cụm 64 video: lô 2/3 và lô 3/3.
    lo2: await chay({ soVideo: 64, thu: 2, popupBiChan: false }),
    lo3: await chay({ soVideo: 64, thu: 3, popupBiChan: false }),
    mot_lo: await chay({ soVideo: 12, thu: 1, popupBiChan: false }),
    bi_chan: await chay({ soVideo: 12, thu: 1, popupBiChan: true }),
    dua_trung: await chayDuaVao({ usecase: " dance", goc: "badaboum ", kieu: "COUPLE" }, [CUM]),
    dua_moi: await chayDuaVao({ usecase: "Dance", goc: "Badaboum", kieu: "nhóm" }, [CUM]),
  };
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
