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
// Cụm có `insight` ĐÚNG như server ghép — dùng cho các ca so trùng tên.
const CUM_TEN = { id: 12, usecase: "Dance", insight_goc: "Badaboum", kieu: "couple",
                  insight: "Badaboum couple", lo_mo: [] };
const CUM = { id: 12, usecase: "Dance", insight_goc: "Badaboum", kieu: "couple",
              insight: "INSIGHT-TU-SERVER", lo_mo: [] };

function chay({ soVideo, thu, popupBiChan, cum = CUM, loiPayload = null,
                hetPhien = false, dongTabTruocDieuHuong = false }) {
  const nhatKy = [];
  const toast = [];
  let baoPhien = false;
  const state = {
    cums: [JSON.parse(JSON.stringify(cum))],
    videos: Array.from({ length: soVideo }, (_, i) => ({
      video_id: `v${i}`, drive_file_id: `d${i}`, title: `t${i}`, url: `u${i}`, cum_id: cum.id,
    })),
  };
  const showToast = (m) => toast.push(m);
  const baoPhienHetHan = () => { baoPhien = true; };
  const renderCumHead = () => nhatKy.push("ve");
  // `window.open` giờ mở "about:blank" TRƯỚC bất kỳ `await` nào, rồi địa
  // chỉ THẬT được điền sau bằng `tab.location = …` (`dieuHuongTab`) — tab giả
  // ở đây phải có một thuộc tính `location` GHI ĐƯỢC để bắt đúng giá trị CUỐI
  // CÙNG được điền, không phải đọc lại tham số của `window.open` (luôn là
  // "about:blank" bây giờ). `closed` GHI ĐƯỢC để mô phỏng người dùng tự tay
  // đóng tab trống trong lúc đang chờ payload về.
  let diaChiCuoi = null;
  const window = {
    open: () => {
      nhatKy.push("open");
      if (popupBiChan) return null;
      const tab = { closed: false, close: () => { nhatKy.push("close"); tab.closed = true; } };
      Object.defineProperty(tab, "location", {
        get: () => diaChiCuoi, set: (u) => { diaChiCuoi = u; },
      });
      return tab;
    },
  };
  const apiSend = async (method, path) => { nhatKy.push(`${method} ${path}`);
                                            return { mo_luc: "2026-09-23T10:42:00+00:00" }; };
  class PhienHetHan extends Error {}
  // Giả lập `GET /cum/{id}/lo/{thu}/payload` — cắt lô ĐÚNG thứ tự
  // `videoCuaCum`+`chiaLo` (video cũ nhất trước) rồi lọc `drive_file_id`,
  // cùng khuôn `web/models_chia.py::xay_payload_lo`. KHÔNG ghi vào `nhatKy`:
  // trước khi payload chuyển sang dựng ở server, không có lời gọi mạng nào ở
  // bước này, và các test dưới đây so `nhatKy` với danh sách CHỈ gồm
  // "open"/"POST .../da-mo"/"close".
  const apiGet = async (path) => {
    if (hetPhien) throw new PhienHetHan();
    if (loiPayload) throw loiPayload;
    // Người dùng đóng tab NGAY TRƯỚC KHI payload về (fetch thành công, nhưng
    // đã trễ) — mô phỏng bằng cách gắn cờ trên chính tab đang mở, đúng lúc
    // apiGet sắp resolve, TRƯỚC khi `moLoCum` kịp kiểm `tab.closed`.
    if (dongTabTruocDieuHuong) tabHienTai.closed = true;
    const m = path.match(/^\/cum\/(\d+)\/lo\/(\d+)\/payload$/);
    if (!m) throw new Error(`apiGet không mong đợi trong harness: ${path}`);
    const cacLo = chiaLo(
      state.videos.filter((v) => v.cum_id === Number(m[1])).slice().reverse(), HANDOFF_MAX);
    const muc = cacLo[Number(m[2]) - 1] || [];
    return {
      v: 1,
      items: muc.filter((v) => v.drive_file_id).map(itemBanGiao),
      nhan: { usecase: cum.usecase, insight: cum.insight, template: "Goc", cum_id: cum.id,
             lo: { thu: Number(m[2]), tong: cacLo.length } },
    };
  };
  eval(["moLoCum", "chiaLo", "videoCuaCum", "itemBanGiao", "dungPayload",
        "maHoaPayload", "urlBanGiao", "moTabTrong", "dieuHuongTab",
        "moTabCreativeDesk"].map(grab).join("\n"));
  // `moTabTrong` (grab ở trên) gọi `window.open` — bọc lại để giữ tham chiếu
  // tab MỚI NHẤT cho `apiGet` ở trên đọc (chỉ cần cho `dongTabTruocDieuHuong`).
  let tabHienTai = null;
  const moTabTrongGoc = moTabTrong;
  moTabTrong = () => { tabHienTai = moTabTrongGoc(); return tabHienTai; };
  return moLoCum(cum.id, thu).then((kq) => ({
    kq, nhatKy: [...nhatKy], toast, baoPhien,
    payload: diaChiCuoi ? giaiMa(diaChiCuoi) : null,
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
  eval(["duaVaoCum", "layHoacTaoCum", "ganIdsVaoCum", "baoDaGan", "timCumTrung", "khoaNhan",
        "xemTruocTen"].map(grab).join("\n"));
  const cumId = await duaVaoCum(nhap, ["v1", "v2"]);
  return { cumId, goi, cum_id_video: state.videos.map((v) => v.cum_id) };
}

// Hai cụm CÙNG tên (dữ liệu cũ / tab khác): bấm dòng cụm 13 ⇒ phải gán vào 13,
// không phải cụm trùng tên đầu tiên (12).
async function chayGanCoSan(cumId) {
  const goi = [];
  const state = {
    cums: [{ ...CUM_TEN, id: 12 }, { ...CUM_TEN, id: 13 }],
    selected: new Set(["v1"]), videos: [{ video_id: "v1", cum_id: null }],
  };
  const showToast = () => {};
  const apiSend = async (method, path, body) => { goi.push(`${method} ${path}`);
                                                  return { so_video: body.video_ids.length, bo_qua: [] }; };
  const boChonTatCa = () => state.selected.clear();
  const loadCums = async () => {};
  const renderLibrary = () => {};
  const document = { getElementById: () => ({ hidden: false }) };
  let dangGuiCum = false;
  eval(["ganVaoCumCoSan", "ganIdsVaoCum", "baoDaGan", "timCumTrung", "khoaNhan",
        "xemTruocTen", "lyDoLoiLoai"].map(grab).join("\n"));
  await ganVaoCumCoSan(cumId);
  return { goi, cum_id_video: state.videos[0].cum_id };
}

// `tab.opener = null` ném lỗi ⇒ vẫn trả tab (tab ĐÃ mở), và phải cảnh báo.
function chayOpenerNem() {
  const canhBao = [];
  const console = { warn: (...a) => canhBao.push(a.map(String).join(" ")) };
  const tab = {};
  Object.defineProperty(tab, "opener", { set() { throw new Error("SecurityError"); } });
  const window = { open: () => tab };
  eval(grab("moTabCreativeDesk"));
  return { traTab: moTabCreativeDesk("https://x") === tab, canhBao };
}

// `moHetLoCum` phải DỪNG ở lô ĐẦU gặp hết phiên, không mở-đóng lặp cho MỌI lô
// còn lại (review lượt 2: `moLoCum` từng trả "mo" cho ca hết phiên, khiến
// `moHetLoCum` đọc thành "đi tiếp"). Cụm 64 video ⇒ 3 lô (30/30/4); mọi
// `apiGet` đều ném hết phiên NGAY — nếu vòng lặp không dừng, "open" sẽ xuất
// hiện 3 lần thay vì 1.
async function chayMoHetLoCumHetPhienGiuaChung() {
  const nhatKy = [];
  const cum = { ...CUM, id: 20 };
  const state = {
    cums: [JSON.parse(JSON.stringify(cum))],
    videos: Array.from({ length: 64 }, (_, i) => ({
      video_id: `v${i}`, drive_file_id: `d${i}`, title: `t${i}`, url: `u${i}`, cum_id: cum.id,
    })),
  };
  const showToast = (m) => nhatKy.push(`toast:${m}`);
  const baoPhienHetHan = () => nhatKy.push("het_phien_bao");
  const renderCumHead = () => {};
  class PhienHetHan extends Error {}
  const window = {
    open: () => {
      nhatKy.push("open");
      const tab = { closed: false, close: () => { nhatKy.push("close"); tab.closed = true; } };
      Object.defineProperty(tab, "location", { get: () => null, set: () => {} });
      return tab;
    },
  };
  const apiGet = async () => { throw new PhienHetHan(); };
  const apiSend = async () => ({ mo_luc: "2026-09-23T10:42:00+00:00" });
  eval(["moLoCum", "moHetLoCum", "chiaLo", "videoCuaCum", "itemBanGiao", "dungPayload",
        "maHoaPayload", "urlBanGiao", "moTabTrong", "dieuHuongTab"].map(grab).join("\n"));
  await moHetLoCum(cum.id);
  return { soLanOpen: nhatKy.filter((x) => x === "open").length,
          soLanBaoHetPhien: nhatKy.filter((x) => x === "het_phien_bao").length, nhatKy };
}

(async () => {
  eval(["chiaLo", "khoaNhan", "timCumTrung", "xemTruocTen"].map(grab).join("\n"));
  const dai = (n) => chiaLo(Array.from({ length: n }, (_, i) => i), HANDOFF_MAX).map((l) => l.length);
  const out = {
    HANDOFF_MAX, GAN_CUM_TOI_DA,
    lo_64: dai(64), lo_30: dai(30), lo_31: dai(31), lo_0: dai(0),
    trung_hoa_thuong: timCumTrung([CUM_TEN], "  dance ", "BADABOUM", " Couple  ")?.id ?? null,
    trung_khac_kieu: timCumTrung([CUM_TEN], "Dance", "Badaboum", "cartoon")?.id ?? null,
    xem_truoc: xemTruocTen("  Badaboum ", "  couple  "),
    // Cụm 64 video: lô 2/3 và lô 3/3.
    lo2: await chay({ soVideo: 64, thu: 2, popupBiChan: false }),
    lo3: await chay({ soVideo: 64, thu: 3, popupBiChan: false }),
    mot_lo: await chay({ soVideo: 12, thu: 1, popupBiChan: false }),
    bi_chan: await chay({ soVideo: 12, thu: 1, popupBiChan: true }),
    // Fetch payload trượt vì lý do KHÔNG PHẢI hết phiên (vd 400 "lô ngoài
    // khoảng" — một tab khác vừa đổi số video của cụm) ⇒ đóng tab trống đã
    // mở, báo lý do, KHÔNG âm thầm nuốt lỗi.
    loi_payload: await chay({ soVideo: 12, thu: 1, popupBiChan: false,
                              loiPayload: new Error("lô phải trong khoảng 1..1") }),
    // Hết phiên ngay lúc fetch payload — tab trống phải bị ĐÓNG, "đã mở"
    // KHÔNG được ghi, và giá trị trả về phải KHÁC "mo".
    het_phien: await chay({ soVideo: 12, thu: 1, popupBiChan: false, hetPhien: true }),
    // Người dùng tự đóng tab trống trong lúc đang chờ payload — không được
    // điều hướng một tab đã đóng, không được ghi "đã mở".
    tab_dong_truoc_dieu_huong: await chay({ soVideo: 12, thu: 1, popupBiChan: false,
                                            dongTabTruocDieuHuong: true }),
    mo_het_het_phien: await chayMoHetLoCumHetPhienGiuaChung(),
    dua_trung: await chayDuaVao({ usecase: " dance", goc: "badaboum ", kieu: "COUPLE" }, [CUM_TEN]),
    dua_moi: await chayDuaVao({ usecase: "Dance", goc: "Badaboum", kieu: "nhóm" }, [CUM_TEN]),
    gan_co_san_13: await chayGanCoSan(13),
    opener_nem: chayOpenerNem(),
  };
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
