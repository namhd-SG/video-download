"""Tab "Dán link Drive" trên trình duyệt THẬT (Chromium, chặn mạng ngoài). API `kiem-link` và `jobs` được GIẢ bằng `page.route`
(không Drive thật, không đụng DB dùng chung): kiểm cách tab vẽ, tick từng video, tên bộ tự điền, id gửi đi đúng, XSS, màu ô dán.

Ảnh nghiệm thu ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt.
"""
from __future__ import annotations

import json
import re

import pytest
from test_thay_logo_trang_browser import FILE_THU_VIEN, _anh, _bo_mo, _tra_json, may_chu, trinh_duyet  # noqa: F401 — fixture dùng lại
from trinh_duyet_khong_mang import dem_mang_ngoai, mo_trang

from web import app as app_mod

EMAIL_MAY = "may@du-an.iam.gserviceaccount.com"
URL_TM = "https://drive.google.com/drive/folders/1Fk3AbCdEfGhIjKl"
URL_F = "https://drive.google.com/file/d/1aQ7AbCdEfGhIjKlmn/view"
URL_CHUA = "https://drive.google.com/drive/folders/1Wn8AbCdEfGhIjKl"
URL_PDF = "https://drive.google.com/file/d/1Bd5AbCdEfGhIjKlmn/view"
MB = 1024 * 1024


def _videos(n, tien_to="v"):
    return [{"id": f"{tien_to}{i:03d}" + "x" * 12, "ten": f"{tien_to}-{i}.mp4", "size": (10 + i) * MB} for i in range(n)]


def _tm(ten="Review T10 – Mẹ & Bé", n=6, **them):
    return {"link": URL_TM, "trang_thai": "nhan", "kieu": "thu_muc", "id": "1Fk3AbCdEfGhIjKl", "ten": ten, "videos": _videos(n),
            "bo_qua_thu_muc_con": 2, "bo_qua_khac": 0, **them}


def _file():
    return {"link": URL_F, "trang_thai": "nhan", "kieu": "file", "id": "1aQ7AbCdEfGhIjKlmn", "ten": "Review máy ép chậm.mp4", "size": 64 * MB}


CHUA = {"link": URL_CHUA, "trang_thai": "khong_mo_duoc", "id": "1Wn8AbCdEfGhIjKl", "ly_do": "Máy chưa mở được mục này.", "dong_so": [0]}
PDF = {"link": URL_PDF, "trang_thai": "khong_hop_le", "id": "1Bd5AbCdEfGhIjKlmn", "kieu": "file", "dong_so": [1],
       "ly_do": "Không phải video mp4/mov, hoặc nặng quá 500 MB."}


def _trang(br, goc, monkeypatch, ket_qua, *, theme="light", rong=1280, email=EMAIL_MAY, me=None, bo=None):
    """Trang mở, tính năng bật, `kiem-link` trả `ket_qua`, `POST /jobs` được ghi lại vào `p.jobs` và trả 201."""
    monkeypatch.setattr(app_mod, "worker_thay_logo", object())
    ctx = br.new_context(viewport={"width": rong, "height": 900}, color_scheme=theme)
    p = ctx.new_page()
    p.jobs, p.kiem = [], []
    loi_js = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    p.loi_js = loi_js

    def kiem_link(r):
        p.kiem.append(json.loads(r.request.post_data))
        _tra_json(r, {"ket_qua": ket_qua() if callable(ket_qua) else ket_qua, "trung_bo": 0, "email_may": email, "da_ghi_nhan": 0})

    def jobs(r):
        if r.request.method != "POST":
            return r.fallback()
        p.jobs.append(json.loads(r.request.post_data))
        _tra_json(r, {"job_id": 99}, status=201)

    if me is not None:
        p.route("**/me", lambda r: _tra_json(r, me))
    if bo is not None:
        p.route("**/api/thay-logo/bo", lambda r: _tra_json(r, {"bo": bo}))
    p.route("**/api/thay-logo/kiem-link", kiem_link)
    p.route("**/api/thay-logo/jobs", jobs)
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelectorAll('#tl-tabs [role=tab]').length === 4")
    p.locator("#tl-tabs [role=tab]").nth(3).click()
    p.wait_for_selector("#tl-o-link")
    return p


def _dan_va_kiem(p, noi_dung=None):
    p.locator("#tl-o-link").fill(noi_dung or f"{URL_TM}\n{URL_F}")
    p.get_by_role("button", name="Kiểm link").click()
    p.wait_for_selector("#tl-tab-link .tl-lk-the")


def test_dan_thu_muc_danh_sach_bo_tick_mot_video_post_dung_id_va_ten_bo(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm(), _file()])
    _dan_va_kiem(p)
    vung = p.locator("#tl-tab-link")
    assert "6 video nằm trực tiếp trong thư mục (bỏ qua thư mục con)" in vung.inner_text()
    assert "bỏ qua 2 thư mục con" in vung.inner_text() and "6/6 đã chọn" in vung.inner_text()
    assert vung.locator(".tl-lk-ds-vid li").count() == 4  # gọn: 4 dòng đầu
    vung.get_by_role("button", name="Hiện cả 6 video").click()
    assert vung.locator(".tl-lk-ds-vid li").count() == 6
    vung.get_by_label("Chọn v-2.mp4").uncheck()
    assert "5/6 đã chọn" in vung.inner_text()
    assert vung.locator(".tl-lk-tm-head input").evaluate("e => e.indeterminate") is True
    assert "Đã chọn 6 video" in p.locator("#tl-dem").inner_text()  # 5 trong thư mục + 1 file lẻ
    assert p.locator("#tl-ten-bo").input_value() == "Review T10 – Mẹ & Bé"  # tên bộ tự điền tên thư mục
    p.locator("#tl-tao").click()
    for _ in range(40):
        if p.jobs:
            break
        p.wait_for_timeout(50)
    gui = p.jobs[0]
    ids_tm = [v["id"] for v in _tm()["videos"] if v["ten"] != "v-2.mp4"]
    assert sorted(gui["drive_file_ids"]) == sorted(ids_tm + ["1aQ7AbCdEfGhIjKlmn"])
    assert gui["ten_bo"] == "Review T10 – Mẹ & Bé" and not p.loi_js
    # chỉ id FILE Drive đi lên — không có id thư mục
    assert "1Fk3AbCdEfGhIjKl" not in gui["drive_file_ids"]


def test_ten_bo_khong_ghi_de_chu_nguoi_dung_da_go_va_chon_ca_thu_muc_bat_tat(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm()])
    p.locator("#tl-ten-bo").fill("Tên tôi tự đặt")
    _dan_va_kiem(p, URL_TM)
    assert p.locator("#tl-ten-bo").input_value() == "Tên tôi tự đặt"
    ca = p.locator("#tl-tab-link .tl-lk-tm-head input")
    ca.uncheck()
    assert "0/6 đã chọn" in p.locator("#tl-tab-link").inner_text() and "Chưa chọn video nào" in p.locator("#tl-dem").inner_text()
    p.locator("#tl-tab-link .tl-lk-tm-head input").check()
    assert "6/6 đã chọn" in p.locator("#tl-tab-link").inner_text()


def test_ve_idempotent_doi_tab_roi_quay_lai_giu_ket_qua_va_tick(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm()])
    _dan_va_kiem(p, URL_TM)
    p.locator("#tl-tab-link .tl-lk-ds-vid input").first.uncheck()
    p.locator("#tl-tabs [role=tab]").nth(0).click()
    p.locator("#tl-tabs [role=tab]").nth(3).click()
    assert "5/6 đã chọn" in p.locator("#tl-tab-link").inner_text() and p.locator("#tl-o-link").input_value() == URL_TM
    assert p.locator("#tl-tab-link .tl-lk-the").count() == 1  # không vẽ trùng


def test_kiem_lai_giu_video_nguoi_dung_da_bo(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm()])
    _dan_va_kiem(p, URL_TM)
    p.locator("#tl-tab-link .tl-lk-ds-vid input").first.uncheck()
    p.get_by_role("button", name="Kiểm link").click()
    p.wait_for_function("document.querySelector('#tl-tab-link .tl-lk-dem').textContent === '5/6 đã chọn'")
    assert len(p.kiem) == 2


def test_loi_chua_chia_se_hien_email_may_nut_copy_kiem_lai_gui_lai(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [CHUA, PDF])
    _dan_va_kiem(p, f"{URL_CHUA}\n{URL_PDF}")
    vung = p.locator("#tl-tab-link")
    txt = vung.inner_text()
    assert "Máy chưa mở được thư mục này" in txt and EMAIL_MAY in txt and "quyền Xem" in txt
    assert vung.get_by_role("button", name=re.compile("Copy")).count() == 1
    assert "không phải video" in txt.lower() and "0 nhận" in txt and "2 chưa dùng được" in txt
    vung.get_by_role("button", name="↻ Kiểm lại").click()
    p.wait_for_function("document.querySelectorAll('#tl-tab-link .tl-lk-loi').length === 2")
    assert len(p.kiem) == 2 and p.kiem[1]["links"] == [URL_CHUA, URL_PDF]
    vung.get_by_role("button", name="Bỏ").click()  # bỏ dòng PDF khỏi ô dán và khỏi danh sách
    assert p.locator("#tl-o-link").input_value() == URL_CHUA and vung.locator(".tl-lk-loi").count() == 1


def test_qua_20_link_chan_o_trang_khong_goi_may_chu(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_file()])
    p.locator("#tl-o-link").fill("\n".join(f"https://drive.google.com/file/d/{i:020d}/view" for i in range(21)))
    p.get_by_role("button", name="Kiểm link").click()
    assert "tối đa 20 link" in p.locator(".tl-lk-tb").inner_text() and p.kiem == []


def test_tick_toi_da_bang_so_cho_con_lai_cua_member(may_chu, trinh_duyet, monkeypatch):
    """Seed: bộ A 1 video chờ máy, bộ B 2 video chờ ⇒ còn 97 chỗ (trần 100). Thư mục 120 video chỉ tick 97 và báo câu thường."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm(n=120)])
    p.wait_for_function("document.querySelectorAll('#tl-bo-list .tl-bo-the').length === 2")
    _dan_va_kiem(p, URL_TM)
    p.wait_for_function("document.querySelector('#tl-tab-link .tl-lk-dem').textContent === '97/120 đã chọn'")
    assert "Bạn còn được xếp 97 video" in p.locator(".tl-lk-tb").inner_text()


def test_tinh_nang_tat_khoa_o_dan_va_nut(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm()])
    monkeypatch.setattr(app_mod, "worker_thay_logo", None)
    p.reload()
    p.wait_for_function("document.querySelectorAll('#tl-tabs [role=tab]').length === 4")
    p.wait_for_function("!document.getElementById('tat').hidden")
    p.locator("#tl-tabs [role=tab]").nth(3).click()
    assert p.locator("#tl-o-link").is_disabled() and p.get_by_role("button", name="Kiểm link").is_disabled()


def test_ten_la_html_hien_nguyen_van_khong_chay(may_chu, trinh_duyet, monkeypatch):
    xau = "<img src=x onerror=alert(1)>"
    tm = _tm(ten=xau, link=xau)
    tm["videos"][0]["ten"] = xau
    f = {**_file(), "ten": xau, "link": xau}
    p = _trang(trinh_duyet, may_chu, monkeypatch, [tm, f, {**CHUA, "link": xau}])
    hop = []
    p.on("dialog", lambda d: (hop.append(d.message), d.dismiss()))
    _dan_va_kiem(p, URL_TM)
    p.wait_for_timeout(300)
    vung = p.locator("#tl-tab-link")
    assert xau in vung.inner_text() and vung.locator("img").count() == 0 and p.locator("img[src='x']").count() == 0 and hop == []


def test_van_ban_member_thay_khong_co_chu_ky_su(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm(), _file(), CHUA, PDF, {"link": "x", "trang_thai": "loi_tam", "ly_do": "Drive đang bận. Bấm Kiểm lại sau ít phút."}])
    _dan_va_kiem(p)
    p.get_by_role("button", name="Hiện cả 6 video").click()
    chu = p.locator("#tl-tab-link").inner_text() + " " + p.locator("#tl-tab-giai").inner_text()
    assert not re.search(r"\bagy\b|khung|\bbox\b", chu, re.I), chu


def test_o_nhap_ban_toi_dung_mau_o_nhap_cua_app(may_chu, trinh_duyet, monkeypatch):
    """ĐP-1519: ô nhập bản tối từng hiện nền xám mặc định của trình duyệt. Ô dán link = nền ô nhập của app (--bg, như ô Tên bộ).
    ĐỘT BIẾN: bỏ `background: var(--bg)` ở luật `.tl-o-link` ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_file()], theme="dark")
    nen = p.evaluate("""() => { const bg = (e) => getComputedStyle(e).backgroundColor;
        return { app: bg(document.body), ten_bo: bg(document.getElementById('tl-ten-bo')), link: bg(document.getElementById('tl-o-link')) }; }""")
    assert nen["link"] == nen["ten_bo"] == nen["app"], nen


@pytest.mark.parametrize("rong", [1280, 390])
def test_khong_cuon_ngang_va_anh_nghiem_thu(may_chu, trinh_duyet, monkeypatch, rong):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm(), _file(), CHUA, PDF], rong=rong)
    _dan_va_kiem(p, f"{URL_TM}\n{URL_F}\n{URL_CHUA}\n{URL_PDF}")
    p.wait_for_function("document.querySelectorAll('#tl-tab-link .tl-lk-the').length === 4")
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    p.evaluate("document.getElementById('tl-vung').style.height = 'auto'")  # chỉ để ảnh thấy hết các thẻ (vùng thật cuộn trong khung)
    _anh(p, f"3-link-{rong}.png")


def test_nut_bo_go_dung_dong_theo_dong_so_ke_ca_hai_link_trung_300_ky_tu_dau(may_chu, trinh_duyet, monkeypatch):
    """Hai link dài giống nhau 300 ký tự đầu, khác ở đuôi: Bỏ link thứ hai chỉ gỡ dòng thứ hai. ĐỘT BIẾN: so khớp theo chuỗi cắt 300 ⇒ gỡ cả hai ⇒ ĐỎ."""
    dai = URL_PDF + "?x=" + "a" * 320
    l1, l2 = dai + "&k=1", dai + "&k=2"
    mau = {"trang_thai": "khong_hop_le", "kieu": "file", "ly_do": "Không phải video mp4/mov, hoặc nặng quá 500 MB."}
    p = _trang(trinh_duyet, may_chu, monkeypatch, [{**mau, "link": l1[:300], "dong_so": [0]}, {**mau, "link": l2[:300], "dong_so": [1]}])
    _dan_va_kiem(p, f"{l1}\n{l2}")
    p.locator("#tl-tab-link .tl-lk-loi").nth(1).get_by_role("button", name="Bỏ").click()
    assert p.locator("#tl-o-link").input_value() == l1 and p.locator("#tl-tab-link .tl-lk-loi").count() == 1


def test_loi_may_chu_khong_lo_ma_loi_ra_chu_nguoi_dung(may_chu, trinh_duyet, monkeypatch):
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_file()])
    p.route("**/api/thay-logo/kiem-link", lambda r: r.fulfill(status=500, body="boom"))
    p.locator("#tl-o-link").fill(URL_F)
    p.get_by_role("button", name="Kiểm link").click()
    p.wait_for_selector(".tl-lk-tb:not([hidden])")
    chu = p.locator(".tl-lk-tb").inner_text()
    assert "Chưa kiểm được lúc này" in chu and "500" not in chu and "lỗi" not in chu.lower()


@pytest.mark.parametrize("la_admin,mong", [(True, 100), (False, 50)])
def test_admin_chi_dem_bo_cua_chinh_minh_khi_tinh_cho_con_lai(may_chu, trinh_duyet, monkeypatch, la_admin, mong):
    """/bo của admin chứa bộ của người khác (50 video chờ). Admin: trần 100 (bộ kia không tính). Member (cùng dữ liệu): còn 50.
    ĐỘT BIẾN: bỏ bộ lọc `nguoi_tao` ở `choConLai` ⇒ ca admin ra 50 ⇒ ĐỎ."""
    bo = [{**_bo_mo(1, "Của người khác", tong=50), "nguoi_tao": "khac@x"}, {**_bo_mo(2, "Của tôi", tong=3, xong=3), "nguoi_tao": "sep@x"}]
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_tm(n=120)], me={"email": "sep@x", "la_admin": la_admin}, bo=bo)
    p.wait_for_function("document.querySelectorAll('#tl-bo-list .tl-bo-the').length === 2")
    _dan_va_kiem(p, URL_TM)
    p.wait_for_function(f"document.querySelector('#tl-tab-link .tl-lk-dem').textContent === '{mong}/120 đã chọn'")


def test_bo_link_khong_go_tick_cua_video_dang_co_trong_thu_vien(may_chu, trinh_duyet, monkeypatch):
    """Video X do tab Link tick, X cũng nằm trong lưới Thư viện ⇒ khi link bị gỡ khỏi kết quả, X vẫn còn tick (không biết tab nào cũng chọn).
    ĐỘT BIẾN: bỏ `coTrongThuVien` ở nhánh gỡ ⇒ ĐỎ. Video không ở thư viện thì vẫn được gỡ."""
    x = FILE_THU_VIEN[0]
    ket = {"v": [{**_file(), "id": x}, {**_file(), "id": "KHONGTHUVIEN12345", "link": URL_PDF}]}
    p = _trang(trinh_duyet, may_chu, monkeypatch, lambda: ket["v"])
    p.wait_for_function("document.querySelectorAll('#tl-tab-thu-vien input[type=checkbox]').length >= 8")
    _dan_va_kiem(p, f"{URL_F}\n{URL_PDF}")
    assert "Đã chọn 2 video" in p.locator("#tl-dem").inner_text()
    ket["v"] = []
    p.get_by_role("button", name="Kiểm link").click()
    p.wait_for_function("document.querySelectorAll('#tl-tab-link .tl-lk-the').length === 0")
    assert "Đã chọn 1 video" in p.locator("#tl-dem").inner_text()


def test_403_khi_tao_luot_nhac_bam_kiem_link_lai(may_chu, trinh_duyet, monkeypatch):
    """ĐỘT BIẾN: trả câu 403 cũ ("…trong thư viện của bạn.") ⇒ ĐỎ."""
    p = _trang(trinh_duyet, may_chu, monkeypatch, [_file()])
    p.route("**/api/thay-logo/jobs", lambda r: r.fulfill(status=403, content_type="application/json", body='{"detail":"x"}') if r.request.method == "POST" else r.fallback())
    _dan_va_kiem(p, URL_F)
    p.locator("#tl-tao").click()
    p.wait_for_function("document.getElementById('tl-loi').textContent.length > 0")
    chu = p.locator("#tl-loi").inner_text()
    assert "24 giờ" in chu and "Kiểm link lại" in chu and "lỗi 4" not in chu
