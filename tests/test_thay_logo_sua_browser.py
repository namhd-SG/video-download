"""Màn Sửa (pha 1b bước 3) trên trình duyệt THẬT: khoanh trên ảnh lớn và ô phóng to ra CÙNG toạ độ khung gốc, lưu từng ô qua
`POST /khoanh`, giữ hình gốc, phím J/L · Shift+J/L · Space · Esc · Enter, và nút Xong ghi rõ có đánh Đạt hay không.

Dùng chung mồi + máy chủ của test màn Lô. Video "A-hai-cho" (60 khung, 64×96): box máy BOX ở khung 5, 8, 30, 31, 59;
đoạn đỏ 6–7, đoạn vàng 30."""
from __future__ import annotations

import json

import pytest
from test_thay_logo_lo_browser import BOX, _ID, may_chu, trinh_duyet  # noqa: F401  (fixture dùng chung)
from trinh_duyet_khong_mang import dem_mang_ngoai, mo_trang

from tiktok_music_downloader.thay_logo import nhat_ky


def _mo_sua(br, goc, ten, khung=None):
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    loi_js: list[str] = []
    yeu_cau: list = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    p.on("request", lambda r: yeu_cau.append(r))
    q = f"&khung={khung}" if khung is not None else ""
    mo_trang(p, f"{goc}/thay-logo-lo.html?lo={_ID['_job']}&sua={_ID[ten]}{q}", dem_mang_ngoai(ctx))
    _cho_khung(p)
    return p, loi_js, yeu_cau


def _cho_khung(p):
    p.wait_for_function("window.TL_SUA && TL_SUA.trangThai() && document.getElementById('sua-zoom-chu').textContent !== ''"
                        " && document.getElementById('sua-anh').complete")  # tải xong HOẶC lỗi — ca lỗi có test riêng


def _khung(p):
    return p.evaluate("TL_SUA.trangThai().khung")


def _keo(p, lop, o):
    """Kéo chuột trên lớp `lop` (#sua-lop-trai | #sua-lop-zoom) để vẽ đúng ô `o` = [x, y, w, h] px khung GỐC."""
    a, b = p.evaluate(f"""(() => {{
        const S = TL_SUA.trangThai(), o = {json.dumps(o)}, r = document.getElementById('{lop}').getBoundingClientRect();
        if ('{lop}' === 'sua-lop-trai') return [[r.left + o[0] / S.W * r.width, r.top + o[1] / S.H * r.height],
                                               [r.left + (o[0] + o[2]) / S.W * r.width, r.top + (o[1] + o[3]) / S.H * r.height]];
        const [cx, cy, cw, ch] = S.zoom, s = Math.min(r.width / cw, r.height / ch), ox = (r.width - cw * s) / 2 - cx * s, oy = (r.height - ch * s) / 2 - cy * s;
        return [[r.left + ox + o[0] * s, r.top + oy + o[1] * s], [r.left + ox + (o[0] + o[2]) * s, r.top + oy + (o[1] + o[3]) * s]];
    }})()""")
    p.mouse.move(*a)
    p.mouse.down()
    p.mouse.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    p.mouse.move(*b)
    p.mouse.up()


def _post_khoanh(yeu_cau):
    return [json.loads(r.post_data) for r in yeu_cau if r.method == "POST" and r.url.endswith("/khoanh")]


def _ca(tmp, vid):
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    try:
        return [dict(r) for r in conn.execute("SELECT khung, x, y, w, h, mau_loi FROM tl_ca_khoanh WHERE job_video_id=? ORDER BY id", (vid,))]
    finally:
        conn.close()


# ---------------------------------------------------------------- mở từ màn Lô
def test_nut_o_man_lo_mo_dung_video_o_doan_dau_tien(may_chu, trinh_duyet):  # noqa: F811
    goc, _ = may_chu
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    mo_trang(p, f"{goc}/thay-logo-lo.html?lo={_ID['_job']}", dem_mang_ngoai(ctx))
    p.get_by_role("button", name="Xem 2 chỗ").click()
    p.wait_for_url(f"**sua={_ID['A-hai-cho']}**")
    _cho_khung(p)
    assert _khung(p) == 6 and "khung=6" in p.url  # đoạn đỏ đầu tiên 6–7
    assert "chỗ đỏ" in p.locator("#sua-tieu-de").inner_text()
    assert p.evaluate("document.getElementById('sua-anh').src").endswith(f"/videos/{_ID['A-hai-cho']}/khung-tai/6?ban=ra")
    assert p.locator("#lo-danh-sach").is_hidden()
    xem2 = p.locator("#sua-xem-2")
    assert xem2.is_disabled() and "bước sau" in xem2.get_attribute("title")  # ĐP chốt: giữ nút, mờ + chú thích


# ---------------------------------------------------------------- khoanh
def test_khoanh_tren_anh_lon_va_o_phong_to_ra_cung_toa_do_khung_goc(may_chu, trinh_duyet):  # noqa: F811
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "A-hai-cho", khung=5)  # khung 5: máy đè BOX ⇒ ô phóng to quanh BOX
    assert p.evaluate("TL_SUA.trangThai().box") == [BOX["x"], BOX["y"], BOX["w"], BOX["h"]]
    assert p.locator("#sua-lop-trai .sua-o-may").count() == 1 and p.locator("#sua-lop-zoom .sua-o-may").count() == 1
    o = [52, 58, 10, 12]  # chữ còn lộ ngay mép phải ô máy
    _keo(p, "sua-lop-trai", o)
    _keo(p, "sua-lop-zoom", o)
    assert p.evaluate("TL_SUA.trangThai().cho.length") == 2
    assert p.locator("#sua-xong").is_disabled()  # còn ô chưa lưu ⇒ chưa cho Xong
    p.get_by_role("button", name="Lưu chỗ khoanh").click()
    p.wait_for_function("TL_SUA.trangThai().cho.length === 0 && TL_SUA.trangThai().daLuu.length === 2")
    gui = _post_khoanh(yeu_cau)
    assert [g["khung"] for g in gui] == [5, 5]
    for g in gui:  # cả hai lớp vẽ quy về CÙNG vùng khung gốc (sai số ≤ 1 px do làm tròn toạ độ chuột)
        v = g["vung"]
        assert abs(v["x"] * 64 - o[0]) <= 1 and abs(v["y"] * 96 - o[1]) <= 1 and abs(v["w"] * 64 - o[2]) <= 1 and abs(v["h"] * 96 - o[3]) <= 1, g
    ca = _ca(tmp, _ID["A-hai-cho"])
    assert len(ca) >= 1 and all(c["mau_loi"] == "lo_mep" for c in ca)  # sát mép box máy ⇒ máy tự gán lộ mép
    assert "lộ mép ô máy đè" in p.locator("#sua-trang").inner_text()
    assert p.locator("#sua-lop-trai .sua-o-luu").count() == 2
    assert loi_js == []


def test_esc_chi_xoa_o_chua_luu_va_giu_hinh_goc(may_chu, trinh_duyet):  # noqa: F811
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "C-chac-1", khung=30)  # khung 30: máy đè (filled)
    _keo(p, "sua-lop-trai", [5, 5, 20, 20])
    assert p.locator("#sua-lop-trai .sua-o-cho").count() == 1
    p.keyboard.press("Escape")
    assert p.locator("#sua-lop-trai .sua-o-cho").count() == 0 and p.evaluate("TL_SUA.trangThai().cho.length") == 0
    p.get_by_role("button", name="Giữ hình gốc đoạn này").click()
    p.wait_for_function("TL_SUA.trangThai().daLuu.length === 1")
    assert _post_khoanh(yeu_cau) == [{"khung": 30, "vung": None, "giu_goc": True}]
    assert _ca(tmp, _ID["C-chac-1"])[-1]["mau_loi"] == "che_nham"
    p.keyboard.press("Escape")  # Esc không xoá chỗ ĐÃ lưu
    assert p.evaluate("TL_SUA.trangThai().daLuu.length") == 1
    assert loi_js == []


# ---------------------------------------------------------------- phím
def test_phim_j_l_shift_va_space(may_chu, trinh_duyet):  # noqa: F811
    goc, _ = may_chu
    p, loi_js, _ = _mo_sua(trinh_duyet, goc, "A-hai-cho", khung=6)
    p.keyboard.press("l")
    p.wait_for_function("TL_SUA.trangThai().khung === 7")
    p.keyboard.press("j")
    p.keyboard.press("j")
    p.wait_for_function("TL_SUA.trangThai().khung === 5")
    p.keyboard.press("Shift+L")  # chỗ kế sau khung 5 = đoạn đỏ 6
    p.wait_for_function("TL_SUA.trangThai().khung === 6")
    p.keyboard.press("Shift+L")  # = đoạn vàng 30 (nhảy theo ĐOẠN, không theo khung)
    p.wait_for_function("TL_SUA.trangThai().khung === 30")
    assert "chỗ vàng" in p.locator("#sua-tieu-de").inner_text()
    p.keyboard.press("Shift+J")
    p.wait_for_function("TL_SUA.trangThai().khung === 6")
    p.keyboard.press("Enter")  # Enter = sang chỗ kế, KHÔNG lưu gì
    p.wait_for_function("TL_SUA.trangThai().khung === 30")
    assert p.evaluate("TL_SUA.trangThai().daLuu.length") == 0
    src = lambda: p.evaluate("document.getElementById('sua-anh').src")  # noqa: E731
    p.keyboard.down(" ")
    assert src().endswith("khung-tai/30?ban=goc") and "BẢN GỐC" in p.locator("#sua-ban").inner_text()
    p.keyboard.up(" ")
    assert src().endswith("khung-tai/30?ban=ra")
    p.keyboard.press("Shift+L")  # hết chỗ ⇒ đứng yên, báo bấm Xong
    assert _khung(p) == 30 and "Hết chỗ cần xem" in p.locator("#sua-trang").inner_text()
    assert loi_js == []


# ---------------------------------------------------------------- nút Xong ghi rõ hành động
def test_xong_danh_dat_khi_chua_khoanh_gi(may_chu, trinh_duyet):  # noqa: F811
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "A-mot-cho")
    # nhật ký ghi 3000 khung, tệp chỉ 60 ⇒ máy chủ không trích được khung đầu (1500) ⇒ trang PHẢI nói ra
    p.wait_for_function("!document.getElementById('lo-loi').hidden")
    assert "Không lấy được ảnh khung" in p.locator("#lo-loi").inner_text()
    x = p.locator("#sua-xong")
    assert x.inner_text() == "Xong — đánh Đạt"
    x.click()
    p.wait_for_url(lambda u: "sua=" not in u)
    assert [json.loads(r.post_data) for r in yeu_cau if r.url.endswith("/danh-gia")] == [{"ket_qua": "dat"}]
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    try:
        log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (_ID["A-mot-cho"],)).fetchone()[0]
        assert [r[0] for r in conn.execute("SELECT ket_qua FROM tl_danh_gia WHERE video_id=?", (log_id,))] == ["dat"]
    finally:
        conn.close()
    assert loi_js == []


def test_xong_ve_lo_khong_danh_dat_khi_da_khoanh(may_chu, trinh_duyet):  # noqa: F811
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "C-chac-2", khung=2)
    x = p.locator("#sua-xong")
    assert x.inner_text() == "Xong — đánh Đạt"
    _keo(p, "sua-lop-trai", [40, 10, 12, 12])
    p.get_by_role("button", name="Lưu chỗ khoanh").click()
    p.wait_for_function("TL_SUA.trangThai().daLuu.length === 1")
    assert x.inner_text() == "Xong — về Lô"  # đã có ô khoanh ⇒ video còn lộ ⇒ KHÔNG được ngầm ghi Đạt
    x.click()
    p.wait_for_url(lambda u: "sua=" not in u)
    assert not [r for r in yeu_cau if r.url.endswith("/danh-gia")]
    # MỞ LẠI video đó (lượt mới, chưa khoanh gì trong lượt này): vẫn KHÔNG được mời đánh Đạt vì còn ca khoanh chờ sửa
    p2, loi2, yc2 = _mo_sua(trinh_duyet, goc, "C-chac-2", khung=2)
    assert p2.locator("#sua-xong").inner_text() == "Xong — về Lô"
    assert "đã có 1 chỗ khoanh từ trước" in p2.locator("#sua-trang").inner_text()
    p2.locator("#sua-xong").click()
    p2.wait_for_url(lambda u: "sua=" not in u)
    assert not [r for r in yc2 if r.url.endswith("/danh-gia")]
    assert loi_js == [] and loi2 == []


def test_video_may_chua_de_gi_xem_ban_goc_o_ba_cho(may_chu, trinh_duyet):  # noqa: F811
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "B-khong-chac")
    assert _khung(p) == 6  # chỗ đầu = 10% của 60 khung
    assert p.evaluate("document.getElementById('sua-anh').src").endswith("khung-tai/6?ban=goc")  # chưa có bản ra
    assert p.evaluate("TL_SUA.trangThai().box") is None and p.locator("#sua-giu-goc").is_disabled()
    p.keyboard.press("Shift+L")
    p.wait_for_function("TL_SUA.trangThai().khung === 30")
    assert p.locator("#sua-xong").inner_text() == "Xong — về Lô"
    _keo(p, "sua-lop-trai", [20, 60, 30, 10])
    p.get_by_role("button", name="Lưu chỗ khoanh").click()
    p.wait_for_function("TL_SUA.trangThai().daLuu.length === 1")
    assert _ca(tmp, _ID["B-khong-chac"])[-1]["mau_loi"] == "may_khong_thay"
    assert loi_js == []


def test_xong_doc_lai_so_ca_truoc_khi_danh_dat(may_chu, trinh_duyet):  # noqa: F811
    """Ca khoanh được lưu ở NƠI KHÁC sau khi trang đã tải (tab thứ hai) ⇒ bấm "Xong — đánh Đạt" phải đọc lại và KHÔNG ghi Đạt."""
    goc, tmp = may_chu
    p, loi_js, yeu_cau = _mo_sua(trinh_duyet, goc, "C-chac-1", khung=0)
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    try:  # C-chac-1 có thể đã có ca từ test trước ⇒ đưa về 0 ca chờ để trang mời "đánh Đạt", rồi mồi 1 ca SAU khi trang tải
        log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (_ID["C-chac-1"],)).fetchone()[0]
        conn.execute("UPDATE tl_ca_khoanh SET trang_thai='huy' WHERE video_log_id=?", (log_id,))
        conn.commit()
    finally:
        conn.close()
    p.reload()
    _cho_khung(p)
    x = p.locator("#sua-xong")
    assert x.inner_text() == "Xong — đánh Đạt"
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    try:
        from tiktok_music_downloader.thay_logo import khoanh
        khoanh.ghi_ca(conn, video_log_id=log_id, job_video_id=_ID["C-chac-1"], member="tab-khac@dev.local", khung=0,
                      vung=(1, 1, 10, 10), mau_loi="lo_mat_dau", chan_cu=None, box_may=None)
    finally:
        conn.close()
    yeu_cau.clear()
    x.click()
    p.wait_for_function("document.getElementById('sua-xong').textContent === 'Xong — về Lô'")
    assert "vừa được lưu ở nơi khác" in p.locator("#sua-trang").inner_text()
    assert not [r for r in yeu_cau if r.url.endswith("/danh-gia")] and "sua=" in p.url  # không ghi Đạt, chưa rời trang
    assert loi_js == []
