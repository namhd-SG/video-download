// Ghim hai tính chất KHÔNG máy nào tự bắt được ngoài node:
// (1) `window.open` trong `moLoCum` phải chạy ĐỒNG BỘ, TRƯỚC await đầu tiên
//     (fetch payload) — Safari chặn NGAY một `window.open` chạy sau một
//     `await`, kể cả trong 5 giây "user activation" (khác Chromium, nới hơn
//     nhưng cũng có hạn).
// (2) Người GỌI `moLoCum`/`moHetLoCum` (handler click ở `#cum-head`) PHẢI có
//     `.catch` — thiếu nó, một lỗi không lường trước rơi thành unhandled
//     rejection câm, không ai thấy, không toast nào hiện ra.
// In một dòng JSON cho pytest (tests/test_cum_browser_and_js.py).
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

const grab = (n) => {
  let i = src.indexOf(`function ${n}(`);
  if (i < 0) return "";
  if (src.slice(i - 6, i) === "async ") i -= 6;
  let d = 0;
  for (let k = src.indexOf("{", i); k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
};

const hang = (n) => {
  const m = src.match(new RegExp(`const ${n} = (\\d+);`));
  return m ? Number(m[1]) : null;
};
const HANDOFF_MAX = hang("HANDOFF_MAX");

// Trích NGUYÊN VĂN thân của một khối `{...}` bắt đầu ngay sau `marker` —
// dùng cho khối không phải hàm có tên (arrow function truyền thẳng vào
// `addEventListener`), nơi `grab` (dựa vào `function NAME(`) không với tới.
const grabBlock = (marker) => {
  const i = src.indexOf(marker);
  if (i < 0) throw new Error("không tìm thấy trong nguồn: " + marker);
  const start = i + marker.length - 1;   // vị trí dấu `{` mở đầu, marker đã kết bằng nó
  let d = 0;
  for (let k = start; k < src.length; k++) {
    if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(start, k + 1);
  }
};

// (1) Fetch payload TREO VĨNH VIỄN (không bao giờ resolve/reject) — mô
// phỏng mạng chậm vô hạn. Gọi `moLoCum` mà KHÔNG await: JS chạy một hàm
// `async` đồng bộ tới `await` ĐẦU TIÊN rồi mới trả quyền điều khiển, nên nếu
// `window.open` chạy trước await đó, `nhatKy` đã có "open" NGAY tại đây —
// không cần chờ thêm nhịp nào của vòng lặp sự kiện.
function chayFetchTreo() {
  const nhatKy = [];
  const cum = { id: 12, usecase: "Dance", insight_goc: "Badaboum", kieu: "couple",
                insight: "Badaboum couple", lo_mo: [] };
  const state = { cums: [cum], videos: Array.from({ length: 5 }, (_, i) => ({
    video_id: `v${i}`, drive_file_id: `d${i}`, title: `t${i}`, url: `u${i}`, cum_id: cum.id })) };
  const showToast = () => {};
  const baoPhienHetHan = () => {};
  const renderCumHead = () => {};
  const window = {
    open: () => { nhatKy.push("open");
                  return { closed: false, close: () => {}, location: null }; },
  };
  const apiGet = () => new Promise(() => {});   // KHÔNG BAO GIỜ resolve/reject
  const apiSend = async () => ({});
  eval(["moLoCum", "chiaLo", "videoCuaCum", "itemBanGiao", "dungPayload",
        "maHoaPayload", "urlBanGiao", "moTabTrong", "dieuHuongTab"].map(grab).join("\n"));
  moLoCum(cum.id, 1);   // CỐ Ý không await — kiểm phần ĐỒNG BỘ chạy trước khi trả quyền điều khiển
  return { daMoNgayLapTuc: nhatKy.includes("open") };
}

// (2) `.catch` bắt buộc ở người gọi — trích NGUYÊN VĂN thân handler click
// `#cum-head`, ép `moLoCum` ném lỗi không lường trước, và đo xem có
// `unhandledRejection` nào lọt ra ngoài không (không có ⇒ `.catch` đã bắt).
async function chayCatchBatBuoc() {
  let batDuocUnhandled = false;
  const onRej = () => { batDuocUnhandled = true; };
  process.on("unhandledRejection", onRej);

  const cum = { id: 12 };
  const state = { cumLoc: 12, cums: [cum] };
  const showToast = () => {};
  const baoPhienHetHan = () => {};
  class PhienHetHan extends Error {}
  const moLoCum = async () => { throw new Error("lỗi không lường trước"); };
  const moHetLoCum = async () => { throw new Error("lỗi không lường trước"); };
  const doiKieuCum = () => {};
  const xoaCum = () => {};

  const than = grabBlock('document.getElementById("cum-head").addEventListener("click", (ev) => {');
  // Ghép bằng CỘNG CHUỖI, không phải template literal: thân khối chứa những
  // dấu backtick riêng của nó (các câu `showToast(\`...\`)`), lồng chúng vào
  // MỘT template literal khác sẽ vỡ cú pháp.
  const handler = eval("(ev) => " + than);
  handler({ target: { closest: (sel) => (sel === "[data-mo-lo]"
              ? { dataset: { moLo: "1" } } : null) } });

  // Nhường vòng lặp sự kiện vài nhịp macrotask để `unhandledRejection` (nếu
  // có) kịp nổ — Node chỉ phát sự kiện này SAU khi hàng đợi microtask hiện
  // tại đã rỗng, tức cần ít nhất một `setImmediate`, không phải một `await`
  // Promise đơn thuần.
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  process.off("unhandledRejection", onRej);
  return { batDuocUnhandled };
}

(async () => {
  const out = {
    fetchTreo: chayFetchTreo(),
    catchBatBuoc: await chayCatchBatBuoc(),
  };
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
