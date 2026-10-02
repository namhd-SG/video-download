// Cắt lô phía trang từ `khung_cum` (`GET /cum`) + vế kiểm id lô trong `moLoCum` —
// hàm THẬT trích từ web/static/app.js. Đầu vào: một tệp JSON (argv[3]) `{che_do, ...}`;
// in một dòng JSON cho pytest (tests/test_khung_cum.py).
//   che_do "lo"       : {videos, khungCum|null, videosDaDon, cumIds} ⇒ id từng lô mỗi cụm
//   che_do "loadCums" : {res, cumId} ⇒ gọi `loadCums` thật với `/cum` giả, KHÔNG nạp lại
//                       `/videos`, rồi cắt lô cụm `cumId`
//   che_do "moLo"     : {videos, khungCum, cum, thu, payload, resCum} ⇒ chạy `moLoCum` thật
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const vao = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const grab = (n) => {
  let i = src.indexOf(`function ${n}(`);
  if (i < 0) throw new Error(`không thấy hàm ${n}`);
  if (src.slice(i - 6, i) === "async ") i -= 6;
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};
const HANDOFF_MAX = Number(src.match(/const HANDOFF_MAX = (\d+);/)[1]);
const CREATIVE_DESK_URL = "https://automation.example";
class PhienHetHan extends Error {}
const giaiMa = (url) => JSON.parse(Buffer.from(
  new URL(url).searchParams.get("videodesk"), "base64url").toString("utf8"));
const ids = (l) => l.map((v) => v.video_id + (v.da_don ? "*" : ""));

async function main() {
  const state = { videos: vao.videos || [], videosDaDon: vao.videosDaDon || [],
                  khungCum: vao.khungCum == null ? undefined : vao.khungCum,
                  cums: vao.cum ? [vao.cum] : [], cumLoc: "tat_ca" };
  const nhatKy = [];
  const toast = [];
  const showToast = (m) => toast.push(m);
  const baoPhienHetHan = () => nhatKy.push("het_phien");
  const renderLibrary = () => nhatKy.push("ve");
  const renderCumHead = () => nhatKy.push("ve");
  let diaChiCuoi = null;
  const window = {
    open: () => {
      nhatKy.push("open");
      const tab = { closed: false, close: () => { nhatKy.push("close"); tab.closed = true; } };
      Object.defineProperty(tab, "location", { get: () => diaChiCuoi, set: (u) => { diaChiCuoi = u; } });
      return tab;
    },
  };
  const apiGet = async (path) => {
    nhatKy.push(`GET ${path}`);
    if (path === "/cum") {
      if (vao.loiNapCum) throw new Error("mạng chập");
      return vao.resCum || vao.res;
    }
    if (/^\/cum\/\d+\/lo\/\d+\/payload$/.test(path)) return JSON.parse(JSON.stringify(vao.payload));
    throw new Error(`apiGet không mong đợi: ${path}`);
  };
  const apiSend = async (method, path, body) => {
    nhatKy.push(`${method} ${path}`);
    return { mo_luc: "2026-10-02T10:00:00+00:00", so_item: body?.so_item ?? null,
             so_video: body?.so_video ?? null };
  };
  eval(["chiaLo", "videoCuaCum", "loadCums", "cungLo", "moLoCum", "itemBanGiao", "dungPayload",
        "maHoaPayload", "urlBanGiao", "moTabTrong", "dieuHuongTab", "moTabCreativeDesk"]
    .map((n) => { try { return grab(n); } catch (e) { return ""; } }).join("\n"));

  if (vao.che_do === "lo") {
    const ra = {};
    for (const c of vao.cumIds) ra[c] = chiaLo(videoCuaCum(c), HANDOFF_MAX).map(ids);
    return ra;
  }
  if (vao.che_do === "loadCums") {
    await loadCums();
    const lo = chiaLo(videoCuaCum(vao.cumId), HANDOFF_MAX);
    return { so_lo: lo.length, so_song: lo.flat().filter((v) => !v.da_don).length,
             so_lo_server: state.cums.find((c) => c.id === vao.cumId).so_lo };
  }
  if (vao.che_do === "moLo") {
    const kq = await moLoCum(vao.cum.id, vao.thu);
    return { kq, nhatKy, toast, payload: diaChiCuoi ? giaiMa(diaChiCuoi) : null,
             khung_sau: state.khungCum };
  }
  throw new Error(`che_do lạ: ${vao.che_do}`);
}
main().then((r) => process.stdout.write(JSON.stringify(r)),
            (e) => { process.stderr.write(String(e.stack || e)); process.exit(1); });
