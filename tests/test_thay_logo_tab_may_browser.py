"""Tab "Tải từ máy" (đợt 4) trên trình duyệt THẬT (Chromium, chặn mạng ngoài). Máy chủ thay logo được GIẢ bằng `page.route` (cờ, phiên, xong, jobs)
và "Google" cũng giả bằng `page.route` trên một host không phân giải được (`upload.google.test`) — không gọi Google thật, không đụng DB dùng chung.

Google giả là máy trạng thái resumable thật: nhận khúc đúng byte kế thì 308 + `Range` (hoặc 200 + id ở khúc cuối), `bytes */size` trả tiến độ
hoặc 200 khi đã xong. Mỗi test bẻ MỘT hành vi của nó (Range ngắn, 308 trần, mất phản hồi cuối, đứt giữa khúc).

Ảnh nghiệm thu ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt.
"""
from __future__ import annotations

import json
import re

import pytest
from test_thay_logo_trang_browser import _anh, _dong_mo, _tra_json, may_chu, trinh_duyet  # noqa: F401 — fixture dùng lại
from trinh_duyet_khong_mang import dem_mang_ngoai, mo_trang

from web import app as app_mod

MB = 1024 * 1024
GOOGLE = "https://upload.google.test"
BI_MAT = "SECRETSESSIONUPLOADID"
FILE_ID = "1GoogleFileIdAbCdEfGh"
TOKEN = "tokenphien" + "x" * 30


def _url_phien(n: int) -> str:
    return f"{GOOGLE}/upload/drive/v3/files?uploadType=resumable&upload_id={BI_MAT}{n}"


class GoogleGia:
    """Phía Google của upload resumable. `hook(g, s, info)` chạy TRƯỚC logic mặc định: trả "abort" / (status, headers, body) / None."""

    def __init__(self, hook=None, giu=None):
        self.phien: dict[str, dict] = {}   # upload_id → {"da": byte đã nhận liên tục, "size": tổng}
        self.puts: list[dict] = []         # mọi PUT (cả câu hỏi `*/size`), theo thứ tự đến
        self.hook, self.giu, self.da_giu = hook, giu or {}, []

    @property
    def du_lieu(self) -> list[str]:
        return [p["cr"] for p in self.puts if not p["hoi"]]

    @property
    def hoi(self) -> list[str]:
        return [p["cr"] for p in self.puts if p["hoi"]]

    def __call__(self, route):
        req = route.request
        cors = {"access-control-allow-origin": req.headers.get("origin", "*"), "access-control-allow-credentials": "true",
                "access-control-expose-headers": "Range", "access-control-allow-headers": "content-range,content-type",
                "access-control-allow-methods": "PUT, OPTIONS"}
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        up = re.search(r"upload_id=(\w+)", req.url).group(1)
        cr = req.headers.get("content-range", "")
        hoi = cr.startswith("bytes */")
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)", cr)
        s = self.phien.setdefault(up, {"da": 0, "size": int((re.search(r"/(\d+)$", cr) or [0, 0])[1])})
        info = {"cr": cr, "hoi": hoi, "up": up, "dau": int(m.group(1)) if m else None, "cuoi": int(m.group(2)) if m else None,
                "size": s["size"], "headers": req.all_headers(), "n": len(req.post_data_buffer or b"")}
        self.puts.append(info)
        ke = sum(1 for p in self.puts if p["up"] == up and not p["hoi"])  # đây là khúc dữ liệu thứ mấy của phiên này
        if not hoi and self.giu.get(up) == ke:
            self.da_giu.append(route)  # giữ im: khúc "đang bay"
            return None
        if self.hook:
            act = self.hook(self, s, info)
            if act == "abort":
                return route.abort()
            if act:
                return route.fulfill(status=act[0], headers={**cors, **act[1]}, body=act[2])
        if hoi:
            if s["da"] >= s["size"]:
                return route.fulfill(status=200, headers=cors, body=json.dumps({"id": FILE_ID}))
            return route.fulfill(status=308, headers={**cors, **({"Range": f"bytes=0-{s['da'] - 1}"} if s["da"] else {})}, body="")
        if info["dau"] != s["da"]:
            return route.fulfill(status=400, headers=cors, body="lech byte")
        s["da"] = info["cuoi"] + 1
        if s["da"] >= s["size"]:
            return route.fulfill(status=200, headers=cors, body=json.dumps({"id": FILE_ID}))
        return route.fulfill(status=308, headers={**cors, "Range": f"bytes=0-{s['da'] - 1}"}, body="")


def _trang(br, goc, monkeypatch, *, google=None, bat=True, phien_loi=(), videos=None, rong=1280, xong_loi=(), cua_toi=None, cua_toi_loi=False, giu_cua_toi=False, bo_loi=False):
    monkeypatch.setattr(app_mod, "worker_thay_logo", object())
    ctx = br.new_context(viewport={"width": rong, "height": 900})
    ctx.add_cookies([{"name": "phien_may_chu", "value": "COOKIE-BI-MAT", "domain": "upload.google.test", "path": "/", "secure": True, "sameSite": "None"}])  # có cookie cho host Google: gửi kèm là LỘ ngay
    p = ctx.new_page()
    p.phien, p.xong, p.jobs, p.loi_js, p.google = [], [], [], [], google or GoogleGia()
    p.cua_toi, p.cua_toi_goi, p.cua_toi_giu, p.bo = list(cua_toi or []), [], [], []   # `cua_toi` = sổ phiên `xong` phía máy chủ giả
    p.on("pageerror", lambda e: p.loi_js.append(str(e)))

    def phien(r):
        p.phien.append(json.loads(r.request.post_data))
        n = len(p.phien)
        if n in phien_loi:
            return _tra_json(r, {"detail": "Drive đang bận — thử lại sau ít phút."}, status=503)
        _tra_json(r, {"token": f"{TOKEN}{n}", "url_phien": _url_phien(n)}, status=201)

    def xong(r):
        p.xong.append({"url": r.request.url, "body": json.loads(r.request.post_data)})
        if len(p.xong) in xong_loi:
            return _tra_json(r, {"detail": "Drive chưa thấy file này — thử lại sau vài giây."}, status=503)
        ten, size = p.phien[-1]["ten"], p.phien[-1]["size"]
        p.cua_toi.append({"token": re.search(r"/tai-len/([^/]+)/xong", r.request.url).group(1), "file_id": FILE_ID, "ten": ten, "size": size, "cap_nhat_luc": 1.0})
        _tra_json(r, {"file_id": FILE_ID})

    def cua(r):
        p.cua_toi_goi.append(1)
        if cua_toi_loi:
            return _tra_json(r, {"detail": "lỗi"}, status=500)
        if giu_cua_toi:
            p.cua_toi_giu.append(r)   # giữ im: test tự trả lời sau (mô phỏng GET về muộn)
            return None
        _tra_json(r, {"phien": list(p.cua_toi)})

    def bo(r):
        p.bo.append(re.search(r"/tai-len/([^/]+)/bo", r.request.url).group(1))
        if bo_loi:
            return _tra_json(r, {"detail": "Drive bận"}, status=503)
        p.cua_toi[:] = [x for x in p.cua_toi if x["token"] != p.bo[-1]]
        _tra_json(r, {"trang_thai": "bo_do"})

    def jobs(r):
        if r.request.method != "POST":
            return r.fallback()
        p.jobs.append(json.loads(r.request.post_data))
        _tra_json(r, {"job_id": 99}, status=201)

    p.route("**/api/thay-logo/tai-len/bat", lambda r: _tra_json(r, {}) if bat else r.fulfill(status=404, body="{}", content_type="application/json"))
    p.route("**/api/thay-logo/tai-len/phien", phien)
    p.route("**/api/thay-logo/tai-len/*/xong", xong)
    p.route("**/api/thay-logo/tai-len/cua-toi", cua)
    p.route("**/api/thay-logo/tai-len/*/bo", bo)
    p.route("**/api/thay-logo/jobs", jobs)
    if videos is not None:
        p.route("**/api/thay-logo/videos*", lambda r: _tra_json(r, {"videos": videos, "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False}))
    p.route(f"{GOOGLE}/**", p.google)
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelectorAll('#tl-tabs [role=tab]').length === 4")
    if bat:
        p.wait_for_function("document.body.classList.contains('tl-co-may')")
        p.locator("#tl-tabs [role=tab]").nth(2).click()
        p.wait_for_selector("#tl-may-input", state="attached")
    return p


def _file(p, ten, size, mime="video/mp4"):
    p.set_input_files("#tl-may-input", files=[{"name": ten, "mimeType": mime, "buffer": b"\x00" * size}])


def _cho_xong(p, n=1):
    p.wait_for_function(f"document.querySelectorAll('#tl-tab-may .tl-may-xong').length === {n}", timeout=20000)


def test_co_tat_tab_an_han_va_khong_goi_gi(may_chu, trinh_duyet, monkeypatch):
    """`GET /tai-len/bat` → 404 ⇒ nhãn tab "Tải từ máy" ẩn (không bấm được), body không có class bật. ĐỐI CHỨNG: cờ bật ⇒ tab hiện (các test dưới)."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, bat=False)
    p.wait_for_timeout(300)
    assert p.locator("#tl-tabs [role=tab]").nth(2).is_hidden() and not p.evaluate("document.body.classList.contains('tl-co-may')")
    assert p.phien == [] and p.google.puts == [] and not p.loi_js


def test_co_bat_tab_hien_ra(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch)
    assert p.locator("#tl-tabs [role=tab]").nth(2).is_visible() and "Kéo thả video vào đây" in p.locator("#tl-tab-may").inner_text()


def test_tai_nhieu_khuc_khong_gui_cookie_authorization_roi_tao_luot_chi_may_file_ids(may_chu, trinh_duyet, monkeypatch):
    """File 9 MiB = 2 khúc (8 MiB + 1 MiB). PUT tới Google KHÔNG mang Authorization/Cookie (context có cookie cho host Google ⇒ gửi kèm là lộ).
    Xong ⇒ file được tick; tạo lượt gửi `may_file_ids` và KHÔNG có ten/token. URL phiên không lọt chữ hiện, không vào storage.
    ĐỘT BIẾN: `xhr.withCredentials = true` ⇒ Cookie đi kèm ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch)
    _file(p, "clip-may.mp4", 9 * MB)
    _cho_xong(p)
    assert p.google.du_lieu == [f"bytes 0-{8 * MB - 1}/{9 * MB}", f"bytes {8 * MB}-{9 * MB - 1}/{9 * MB}"]
    for put in p.google.puts:
        assert "authorization" not in put["headers"] and "cookie" not in put["headers"], put["headers"]
    assert p.phien == [{"ten": "clip-may.mp4", "size": 9 * MB, "mime": "video/mp4"}]
    assert len(p.xong) == 1 and p.xong[0]["body"] == {"file_id": FILE_ID} and p.xong[0]["url"].endswith(f"/{TOKEN}1/xong")
    assert "Đã chọn 1 video" in p.locator("#tl-dem").inner_text() and p.locator("#tl-tab-may .tl-may-xong input").is_checked()
    # URL phiên chỉ ở bộ nhớ biến JS
    assert BI_MAT not in p.content() and BI_MAT not in p.evaluate("JSON.stringify([{...localStorage}, {...sessionStorage}, document.cookie])")
    _anh(p, "dot4-0-tai-xong-1280.png")
    p.locator("#tl-tao").click()
    for _ in range(40):
        if p.jobs:
            break
        p.wait_for_timeout(50)
    gui = p.jobs[0]
    assert gui["may_file_ids"] == [FILE_ID] and gui["drive_file_ids"] == []
    assert "ten" not in gui and "token" not in gui and set(gui) == {"drive_file_ids", "ten_bo", "may_file_ids"}
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-the').length === 0")  # lượt tạo xong ⇒ dòng đã dùng được bỏ
    assert not p.loi_js


def test_doc_range_cua_308_khong_tu_cong_offset(may_chu, trinh_duyet, monkeypatch):
    """Khúc 1 gửi 8 MiB nhưng Google chỉ nhận 4 MiB (Range NGẮN hơn khúc đã gửi) ⇒ PUT kế phải bắt đầu đúng 4 MiB.
    ĐỘT BIẾN: `m.ke = dau + (cuoi - dau + 1)` thay vì `byteKe(r)` ⇒ khúc 2 bắt đầu 8 MiB, Google 400 ⇒ ĐỎ."""
    def hook(g, s, info):
        if info["dau"] == 0 and not getattr(g, "_da", False):
            g._da = True
            s["da"] = 4 * MB
            return (308, {"Range": f"bytes=0-{4 * MB - 1}"}, "")
    p = _trang(trinh_duyet, may_chu, monkeypatch, google=GoogleGia(hook))
    _file(p, "range-ngan.mp4", 16 * MB)
    _cho_xong(p)
    assert p.google.du_lieu == [f"bytes 0-{8 * MB - 1}/{16 * MB}", f"bytes {4 * MB}-{12 * MB - 1}/{16 * MB}", f"bytes {12 * MB}-{16 * MB - 1}/{16 * MB}"]


def test_308_tran_khong_range_gui_lai_tu_byte_0(may_chu, trinh_duyet, monkeypatch):
    """308 KHÔNG `Range` ⇒ Google chưa nhận byte nào ⇒ byte kế = 0 (không sập, không đứng). ĐỘT BIẾN: thiếu Range ⇒ ném lỗi ⇒ dòng đỏ, không xong ⇒ ĐỎ."""
    def hook(g, s, info):
        if not getattr(g, "_da", False):
            g._da = True
            s["da"] = 0
            return (308, {}, "")
    p = _trang(trinh_duyet, may_chu, monkeypatch, google=GoogleGia(hook))
    _file(p, "tran.mp4", 9 * MB)
    _cho_xong(p)
    ds = p.google.du_lieu
    assert ds[0] == ds[1] == f"bytes 0-{8 * MB - 1}/{9 * MB}" and len(ds) == 3, ds


def test_hoi_size_tra_200_la_da_xong_goi_xong_khong_put_lai(may_chu, trinh_duyet, monkeypatch):
    """Khúc cuối Google nhận đủ nhưng phản hồi MẤT (đứt mạng) ⇒ FE hỏi `bytes */size` ⇒ 200 + id ⇒ gọi /xong với id đó, KHÔNG PUT lại dữ liệu.
    ĐỘT BIẾN: coi 200 của `*/size` là "byte 0" ⇒ PUT lại từ 0 ⇒ ĐỎ."""
    def hook(g, s, info):
        if info["dau"] == 8 * MB:
            s["da"] = info["size"]
            return "abort"
    p = _trang(trinh_duyet, may_chu, monkeypatch, google=GoogleGia(hook))
    _file(p, "mat-phan-hoi.mp4", 9 * MB)
    _cho_xong(p)
    assert len(p.google.du_lieu) == 2 and len(p.google.hoi) == 1, (p.google.du_lieu, p.google.hoi)
    assert p.xong[0]["body"] == {"file_id": FILE_ID}


def test_dut_mang_giua_khuc_hoi_size_roi_noi_tiep(may_chu, trinh_duyet, monkeypatch):
    """Khúc 2 bị đứt mạng 1 lần (route abort, Google chưa nhận) ⇒ hỏi `*/size` (308 Range 0-8MiB-1) ⇒ gửi lại khúc 2 và xong."""
    def hook(g, s, info):
        if info["dau"] == 8 * MB and not getattr(g, "_da", False):
            g._da = True
            return "abort"
    p = _trang(trinh_duyet, may_chu, monkeypatch, google=GoogleGia(hook))
    _file(p, "dut-mang.mp4", 9 * MB)
    _cho_xong(p)
    khuc2 = f"bytes {8 * MB}-{9 * MB - 1}/{9 * MB}"
    assert p.google.du_lieu == [f"bytes 0-{8 * MB - 1}/{9 * MB}", khuc2, khuc2] and p.google.hoi == [f"bytes */{9 * MB}"]


def test_file_khong_hop_le_chan_o_trang_khong_goi_phien(may_chu, trinh_duyet, monkeypatch):
    """Không phải video ⇒ dòng lỗi, KHÔNG gọi /phien. Hàm kiểm: đúng 500 MiB qua, 500 MiB + 1 byte bị chặn, file rỗng bị chặn."""
    p = _trang(trinh_duyet, may_chu, monkeypatch)
    _file(p, "anh-bia.png", 2048, mime="image/png")
    p.wait_for_selector("#tl-tab-may .tl-may-loi")
    chu = p.locator("#tl-tab-may").inner_text()
    assert "Không phải video" in chu and p.phien == [] and p.google.puts == []
    kq = p.evaluate("""() => { const k = window.TL.tabMay.kiemFile, M = 1048576, v = 'video/mp4';
        return [k({name:'a.mp4', size: 500*M, type: v}), k({name:'a.mp4', size: 500*M + 1, type: v}), k({name:'a.mp4', size: 0, type: v}), k({name:'a.pdf', size: 5, type: 'application/pdf'})]; }""")
    assert kq[0] == "" and "quá 500 MB" in kq[1] and kq[2] != "" and "Không phải video" in kq[3], kq
    assert "Chỉ nhận file video" in kq[3] and "mp4 hoặc mov" not in kq[3], kq  # chữ khớp hành vi (nhận mọi video/*)


def test_loi_may_chu_thu_lai_chay_tiep_va_huy(may_chu, trinh_duyet, monkeypatch):
    """/phien 503 ⇒ dòng đỏ có "Thử lại" + câu `detail` của máy chủ; bấm Thử lại ⇒ tải được. Huỷ một file đang tải thì dòng biến mất."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, phien_loi={1})
    _file(p, "bi-loi-phien.mp4", 2 * MB)
    p.wait_for_selector("#tl-tab-may .tl-may-loi")
    assert "Drive đang bận" in p.locator("#tl-tab-may").inner_text() and "503" not in p.locator("#tl-tab-may").inner_text()
    p.get_by_role("button", name="↻ Thử lại").click()
    _cho_xong(p)
    assert len(p.phien) == 2 and not p.loi_js
    # Huỷ: giữ khúc đầu của file thứ hai (đang bay) rồi bấm Huỷ
    p.google.giu["SECRETSESSIONUPLOADID3"] = 1
    _file(p, "se-huy.mp4", 2 * MB)
    p.wait_for_selector("#tl-tab-may .tl-may-dang")
    p.get_by_role("button", name="Huỷ").click()
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-dang').length === 0")
    assert p.locator("#tl-tab-may .tl-may-the").count() == 1


def test_hop_duyet_dong_da_don_khong_co_link_ban_goc(may_chu, trinh_duyet, monkeypatch):
    """Dòng `da_don:true` (file nhập đã dọn) không gắn link "Bản gốc"; dòng khác vẫn có. ĐỘT BIẾN: bỏ `&& !v.da_don` ở hop-duyet ⇒ ĐỎ."""
    def ng(fid):
        return json.dumps({"kieu": "may", "file_id": fid, "token": "t", "ten": "x.mp4"})
    vs = [_dong_mo(1, nguon=ng("DONFILE" + "a" * 12), da_don=True), _dong_mo(2, nguon=ng("CONFILE" + "b" * 12), da_don=False)]
    p = _trang(trinh_duyet, may_chu, monkeypatch, videos=vs)
    p.wait_for_function("document.querySelectorAll('#tl-duyet .tl-phim-o').length === 2")
    co = {}
    for i in range(2):
        p.locator("#tl-duyet .tl-phim-o").nth(i).click()
        co[i] = p.locator("#tl-duyet .tl-link-phu").get_by_text("Bản gốc").count()
    assert sorted(co.values()) == [0, 1], co


@pytest.mark.parametrize("rong", [1280, 390])
def test_khong_cuon_ngang(may_chu, trinh_duyet, monkeypatch, rong):
    p = _trang(trinh_duyet, may_chu, monkeypatch, rong=rong)
    _file(p, "mot-file-co-ten-rat-dai-" + "x" * 80 + ".mp4", 2 * MB)
    _cho_xong(p)
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_anh_nghiem_thu_rong_dang_tai_va_loi(may_chu, trinh_duyet, monkeypatch):
    """Ba ảnh 1280 ghi vào `$VIDEODL_ANH_THAY_LOGO`: tab rỗng · 2 file đang tải (tiến độ khác nhau) + 1 xong · có dòng lỗi."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, phien_loi={4})
    p.evaluate("document.getElementById('tl-vung').style.height = 'auto'")
    _anh(p, "dot4-1-tab-rong-1280.png")
    p.google.giu = {f"{BI_MAT}1": 3, f"{BI_MAT}2": 2}   # file 1 giữ ở khúc 3 (đã 16/24 MiB), file 2 giữ ở khúc 2 (8/20 MiB)
    _file(p, "review-noi-com-dien-1-8L.mp4", 24 * MB)
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-the').length === 1")
    p.wait_for_function("document.querySelector('#tl-tab-may .tl-may-pct') && document.querySelector('#tl-tab-may .tl-may-pct').textContent === '66%'", timeout=15000)
    _file(p, "unbox-tai-nghe-chup-tai.mov", 20 * MB, mime="video/quicktime")
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-pct').length === 2 && [...document.querySelectorAll('#tl-tab-may .tl-may-pct')].some((e) => e.textContent === '40%')", timeout=15000)
    _file(p, "son-duong-moi-co-mau.mp4", 3 * MB)
    _cho_xong(p)
    _anh(p, "dot4-2-dang-tai-2-file-1280.png")
    _file(p, "test-may-loc-khong-khi.mp4", 3 * MB)        # phien lần thứ 4 ⇒ 503
    _file(p, "anh-bia-san-pham.png", 4096, mime="image/png")
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-loi').length === 2")
    _anh(p, "dot4-3-co-file-loi-1280.png")
    assert not p.loi_js


def test_xong_503_mot_lan_roi_200_dong_thanh_xong(may_chu, trinh_duyet, monkeypatch):
    """`/xong` 503 ("Drive chưa thấy file") một lần ⇒ FE thử lại ⇒ 200 ⇒ dòng thành xong, không lỗi. Đột biến: FE coi 503 là lỗi cuối ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, xong_loi={1})
    _file(p, "xong-503.mp4", 2 * MB)
    _cho_xong(p)
    assert len(p.xong) == 2 and not p.loi_js and p.locator("#tl-tab-may .tl-may-loi").count() == 0


@pytest.mark.parametrize("cach", ["abort", "503"])
def test_khuc_hong_mai_ma_hoi_size_van_308_cung_range_thi_bao_loi_huu_han(may_chu, trinh_duyet, monkeypatch, cach):
    """Khúc dữ liệu luôn hỏng (abort mạng / 503) trong khi `*/size` trả 308 cùng `Range` (không tiến) ⇒ thẻ ra lỗi có Thử lại trong thời gian
    hữu hạn, không lặp vô hạn. Đột biến: bỏ đếm "không tiến" ở nhánh lỗi mạng / 5xx ⇒ thẻ đứng mãi ⇒ hết giờ ⇒ ĐỎ."""
    def hook(g, s, info):
        if info["hoi"]:
            return (308, {"Range": f"bytes=0-{4 * MB - 1}"}, "")   # Google nhận 4 MiB và đứng yên
        return "abort" if cach == "abort" else (503, {}, "")
    p = _trang(trinh_duyet, may_chu, monkeypatch, google=GoogleGia(hook))
    p.evaluate("window.setTimeout = ((st) => (f, ms, ...a) => st(f, Math.min(ms || 0, 20), ...a))(window.setTimeout)")  # rút thời gian lùi (500ms…8s) cho test
    _file(p, "hong-mai.mp4", 9 * MB)
    p.wait_for_selector("#tl-tab-may .tl-may-loi", timeout=20000)
    assert "Google không nhận thêm dữ liệu" in p.locator("#tl-tab-may").inner_text()
    assert p.get_by_role("button", name="↻ Thử lại").count() == 1 and not p.loi_js


# ---------------------------------------------------------------- phiên của tôi: khôi phục sau tải lại trang, Bỏ/Huỷ nhả chỗ
F2 = "1GoogleFileIdZzYyXxWw"
KHOI_PHUC = [{"token": "tokenkhoiphuc" + "a" * 30, "file_id": FILE_ID, "ten": "clip-khoi-phuc-1.mp4", "size": 5 * MB, "cap_nhat_luc": 2.0},
             {"token": "tokenkhoiphuc" + "b" * 30, "file_id": F2, "ten": "clip-khoi-phuc-2.mov", "size": 12 * MB, "cap_nhat_luc": 1.0}]


def _mo_tab_may(p):
    p.wait_for_function("document.body.classList.contains('tl-co-may')")
    p.locator("#tl-tabs [role=tab]").nth(2).click()
    p.wait_for_selector("#tl-may-input", state="attached")


def test_tai_lai_trang_khoi_phuc_dong_xong_tick_san_roi_tao_luot_dung_may_file_ids(may_chu, trinh_duyet, monkeypatch):
    """GET /cua-toi trả 2 phiên ⇒ tab dựng lại 2 dòng "Đã tải xong", tick sẵn; tạo lượt gửi đúng 2 `may_file_ids` (KHÔNG ten/token).
    ĐỘT BIẾN: FE không gọi cua-toi / không dựng dòng ⇒ ĐỎ; dựng dòng mà không tick vào `nhapChon` ⇒ may_file_ids rỗng ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, cua_toi=KHOI_PHUC)
    _cho_xong(p, 2)
    assert p.cua_toi_goi == [1] and p.phien == [] and p.google.puts == []
    chu = p.locator("#tl-tab-may").inner_text()
    assert "clip-khoi-phuc-1.mp4" in chu and "clip-khoi-phuc-2.mov" in chu and "Đã tải xong" in chu
    assert p.locator("#tl-tab-may .tl-may-xong input:checked").count() == 2 and "Đã chọn 2 video" in p.locator("#tl-dem").inner_text()
    assert p.locator("#tl-tab-may .tl-may-xong").get_by_role("button", name="Bỏ").count() == 2
    p.evaluate("document.getElementById('tl-vung').style.height = 'auto'")
    _anh(p, "dot4-4-khoi-phuc-sau-tai-lai-1280.png")
    p.locator("#tl-tao").click()
    for _ in range(40):
        if p.jobs:
            break
        p.wait_for_timeout(50)
    gui = p.jobs[0]
    assert sorted(gui["may_file_ids"]) == sorted([FILE_ID, F2]) and gui["drive_file_ids"] == []
    assert set(gui) == {"drive_file_ids", "ten_bo", "may_file_ids"} and not p.loi_js


def test_tai_xong_roi_tai_lai_trang_van_con_dong_xong(may_chu, trinh_duyet, monkeypatch):
    """Cả vòng: tải file (máy chủ giả ghi phiên `xong`) ⇒ `reload` (mất hết bộ nhớ JS) ⇒ dòng xong dựng lại từ máy chủ, tick sẵn."""
    p = _trang(trinh_duyet, may_chu, monkeypatch)
    _file(p, "truoc-khi-tai-lai.mp4", 2 * MB)
    _cho_xong(p)
    p.reload()
    p.wait_for_function("document.querySelectorAll('#tl-tabs [role=tab]').length === 4")
    _mo_tab_may(p)
    _cho_xong(p)
    assert "truoc-khi-tai-lai.mp4" in p.locator("#tl-tab-may").inner_text() and len(p.cua_toi_goi) == 2
    assert p.locator("#tl-tab-may .tl-may-xong input:checked").count() == 1 and not p.loi_js


def test_khoi_phuc_khong_trung_dong_vua_tai_xong_trong_trang(may_chu, trinh_duyet, monkeypatch):
    """GET /cua-toi về MUỘN (sau khi file vừa tải xong trong trang này) và chứa chính phiên đó ⇒ vẫn đúng 1 dòng. ĐỘT BIẾN: bỏ kiểm trùng token/file_id ⇒ 2 dòng ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, giu_cua_toi=True)
    _file(p, "vua-tai-xong.mp4", 2 * MB)
    _cho_xong(p)
    (giu,) = p.cua_toi_giu
    _tra_json(giu, {"phien": list(p.cua_toi) + [KHOI_PHUC[1]]})   # phiên vừa tải + một phiên cũ khác
    _cho_xong(p, 2)
    ten = p.locator("#tl-tab-may .tl-may-ten").all_inner_texts()
    assert sorted(ten) == ["clip-khoi-phuc-2.mov", "vua-tai-xong.mp4"], ten


def test_bo_tren_dong_khoi_phuc_goi_bo_va_go_dong(may_chu, trinh_duyet, monkeypatch):
    """ĐỘT BIẾN: nút Bỏ chỉ gỡ dòng, không POST /bo ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, cua_toi=KHOI_PHUC)
    _cho_xong(p, 2)
    p.locator("#tl-tab-may .tl-may-xong").first.get_by_role("button", name="Bỏ").click()
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-xong').length === 1")
    p.wait_for_timeout(200)
    assert p.bo == [KHOI_PHUC[0]["token"]] and "Đã chọn 1 video" in p.locator("#tl-dem").inner_text() and not p.loi_js


def test_huy_dong_dang_tai_da_co_token_abort_xhr_roi_goi_bo(may_chu, trinh_duyet, monkeypatch):
    """Khúc đầu bị giữ (đang bay) ⇒ bấm Huỷ ⇒ XHR bị abort (Google không nhận thêm khúc nào) VÀ POST /bo token của phiên. ĐỘT BIẾN: Huỷ không gọi /bo ⇒ ĐỎ; Huỷ không abort XHR ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch)
    p.google.giu[f"{BI_MAT}1"] = 1
    huy_mang = []
    p.on("requestfailed", lambda r: huy_mang.append(r.url) if r.url.startswith(GOOGLE) else None)
    _file(p, "se-huy-co-bo.mp4", 2 * MB)
    p.wait_for_selector("#tl-tab-may .tl-may-dang")
    for _ in range(40):
        if p.google.puts:
            break
        p.wait_for_timeout(50)
    p.get_by_role("button", name="Huỷ").click()
    p.wait_for_function("document.querySelectorAll('#tl-tab-may .tl-may-the').length === 0")
    for _ in range(40):
        if p.bo:
            break
        p.wait_for_timeout(50)
    assert p.bo == [f"{TOKEN}1"] and len(p.google.du_lieu) == 1 and p.xong == [] and not p.loi_js
    assert len(huy_mang) == 1 and BI_MAT in huy_mang[0], huy_mang   # XHR đang bay bị abort thật (không chỉ dòng biến mất)


def test_bo_truot_mang_thu_lai_mot_lan_roi_bao_chu_ngan_va_van_go_dong(may_chu, trinh_duyet, monkeypatch):
    """/bo luôn 503 ⇒ thử đúng 2 lần, dòng vẫn gỡ, hiện chữ ngắn (không im lặng sai)."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, cua_toi=KHOI_PHUC[:1], bo_loi=True)
    _cho_xong(p)
    p.locator("#tl-tab-may .tl-may-xong").get_by_role("button", name="Bỏ").click()
    p.wait_for_selector("#tl-tab-may .tl-may-tb:not([hidden])", timeout=8000)
    assert len(p.bo) == 2 and "Chưa báo được máy chủ bỏ file clip-khoi-phuc-1.mp4" in p.locator("#tl-tab-may .tl-may-tb").inner_text()
    assert p.locator("#tl-tab-may .tl-may-the").count() == 0


def test_cua_toi_loi_thi_bo_qua_yen_lang_khong_chan_tab_khong_lap(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, cua_toi_loi=True)
    p.wait_for_timeout(500)
    assert p.cua_toi_goi == [1] and p.locator("#tl-tab-may .tl-may-the").count() == 0 and not p.loi_js
    _file(p, "van-tai-duoc.mp4", 2 * MB)   # tab vẫn dùng bình thường
    _cho_xong(p)
    assert p.cua_toi_goi == [1]
