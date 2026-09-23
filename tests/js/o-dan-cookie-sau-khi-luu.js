// Chạy NGUYÊN web/static/settings.js trong một DOM giả, bấm "Lưu cookie", rồi
// đọc lại ô dán. In một dòng JSON cho pytest đọc.
//
// Vì sao chạy cả tệp chứ không trích hàm: nhánh cần soi nằm trong một closure
// của IIFE (`noiCookie`), không có tên nào để trích ra — và chạy cả tệp thì đo
// đúng thứ trình duyệt chạy.
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");

function phanTu() {
  const nghe = {};
  return {
    value: "", textContent: "", className: "", hidden: false, disabled: false,
    innerHTML: "", dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    addEventListener(ev, fn) { (nghe[ev] ||= []).push(fn); },
    querySelector: () => phanTu(),
    async bam(ev = "click") { for (const fn of nghe[ev] || []) await fn({ preventDefault() {} }); },
  };
}

async function chay({ status, detail }) {
  const els = {};
  const document = {
    getElementById: (id) => (els[id] ||= phanTu()),
    querySelector: () => phanTu(),
    documentElement: phanTu(),
  };
  const fetch = async (path, opt = {}) => {
    const ok = !(opt.method === "PUT") || status < 400;
    const body = opt.method === "PUT"
      ? (ok ? { co_jar: true, trang_thai: "dung_duoc" } : { detail })
      : path === "/me/quota"
        ? { an_danh: true, luot_tai: { da_dung: 0, tran: 1 }, video: { da_dung: 0, tran: 1 },
            trang_index: { da_dung: 0, tran: 1 } }
        : { co_jar: false, email: "x", la_admin: false };
    return { ok, status: opt.method === "PUT" ? status : 200, type: "basic", json: async () => body };
  };
  const window = {
    MA_COOKIE_TRANG_THAI: { cookie_het_han: "hết hạn" },
    matchMedia: () => ({ matches: false }),
    confirm: () => true,
  };
  const localStorage = { getItem: () => null, setItem() {} };
  vm.runInNewContext(src, { window, document, fetch, localStorage, console, Promise, Error });
  await new Promise((r) => setTimeout(r, 0));

  const o = els["cookie-json"];
  o.value = "[COOKIE-GIA]";
  await els["cookie-luu"].bam();
  return { oDanConLai: o.value, loi: els["cookie-error"].textContent };
}

(async () => {
  const bi_tu_choi = await chay({ status: 400, detail: "cookie_het_han" });
  const loi_mang = await chay({ status: 500, detail: null });
  const thanh_cong = await chay({ status: 200, detail: null });
  process.stdout.write(JSON.stringify({ bi_tu_choi, loi_mang, thanh_cong }));
})();
