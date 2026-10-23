"""Nguồn tìm Chrome: URL, đọc DOM, hâm phiên, ngân sách, luôn đóng cửa sổ. Không mở Chrome thật: trang được thay bằng giả."""
from __future__ import annotations

import pytest

from tiktok_music_downloader.tim_trend import nguon_tim
from tiktok_music_downloader.tim_trend.nguon_tim import ChromeTim, HetLuot, tu_dom, url_cua
from tiktok_music_downloader.tim_trend.truy_van import TruyVan

DOM_GD1 = [  # rút từ DOM thật GĐ1 (S7 "7 pose ai trend", 22/10)
    {"url": "https://www.tiktok.com/@saaart3/video/7697969447553813778?is_from_webapp=1", "cover": "https://p16/a.jpeg",
     "caption": "AI collage 7 poses"},
    {"url": "https://www.tiktok.com/@saaart3/video/7697969447553813778", "cover": "https://p16/a.jpeg", "caption": "trùng"},
    {"url": "https://www.tiktok.com/@lovinglylov3ly0/video/7699072089201921301", "cover": "https://p16/b.jpeg",
     "caption": "Tren AI ubah foto menjadi kolase 7 pose"},
    {"url": "https://www.tiktok.com/@x/photo/7699000000000000000", "cover": "https://p16/c.jpeg", "caption": "ảnh, không phải video"},
    {"url": "https://www.tiktok.com/@y/video/7699000000000000001", "cover": "", "caption": "không ảnh bìa"},
]


def test_url_cua():
    assert url_cua(TruyVan("7 pose ai trend", "cau_truc", "en")) == "https://www.tiktok.com/search/video?q=7%20pose%20ai%20trend"
    assert url_cua(TruyVan("#aicatwalk", "mo_rong", "goc", loai="tag")) == "https://www.tiktok.com/tag/aicatwalk"


def test_tu_dom_chi_giu_link_video_chuan():
    ra = tu_dom(DOM_GD1, "7 pose ai trend")
    assert [(u.video_id, u.tac_gia) for u in ra] == [("7697969447553813778", "saaart3"),
                                                     ("7699072089201921301", "lovinglylov3ly0")]
    assert ra[0].url == "https://www.tiktok.com/@saaart3/video/7697969447553813778"


class _ChuotGia:
    def __init__(self):
        self.cuon = 0

    def wheel(self, dx, dy):
        self.cuon += 1


class _TrangGia:
    def __init__(self, ket_qua):
        self.ket_qua = list(ket_qua)
        self.da_goto = []
        self.mouse = _ChuotGia()
        self.dong = False

    def is_closed(self):
        return self.dong

    def goto(self, url, **k):
        self.da_goto.append(url)

    def wait_for_selector(self, *a, **k):
        pass

    def wait_for_timeout(self, *a):
        pass

    def evaluate(self, _js):
        muc = self.ket_qua.pop(0)
        return muc if isinstance(muc, dict) else {"items": muc, "chu": "TikTok Videos"}

    def screenshot(self, path):
        from pathlib import Path
        Path(path).write_bytes(b"png")


def _tim(monkeypatch, ket_qua, tran=6):
    monkeypatch.setattr(nguon_tim.time, "sleep", lambda s: None)
    t = ChromeTim(tran_luot=tran, gian_cach=0, bao=lambda s: None)
    t._page = _TrangGia(ket_qua)
    return t


def test_ham_phien_khi_luot_dau_rong_va_dem_ca_luot_ham(monkeypatch):
    t = _tim(monkeypatch, [[], DOM_GD1])
    ra, ghi_chu = t.tim(TruyVan("kolase 7 pose", "mo_rong", "goc"))
    assert len(ra) == 2 and ghi_chu == "ham phien" and t.da_mo == 2


def test_rong_sau_ham_phien_duoc_ghi_ro(monkeypatch):
    t = _tim(monkeypatch, [[], []])
    ra, ghi_chu = t.tim(TruyVan("x", "cau_truc", "en"))
    assert ra == [] and "feed rong" in ghi_chu


def test_het_luot_tinh_ca_luot_ham(monkeypatch):
    t = _tim(monkeypatch, [[], DOM_GD1, DOM_GD1], tran=2)
    t.tim(TruyVan("a", "cau_truc", "en"))
    with pytest.raises(HetLuot):
        t.tim(TruyVan("b", "cau_truc", "en"))


def test_luon_dong_cua_so_khi_loi(monkeypatch):
    dong = []

    class _Ctx:
        def new_page(self):
            raise RuntimeError("trang hỏng")

        def close(self):
            dong.append("ctx")

    class _Chromium:
        def launch_persistent_context(self, *a, **k):
            return _Ctx()

    class _Pw:
        chromium = _Chromium()

        def stop(self):
            dong.append("pw")

    class _Sync:
        def start(self):
            return _Pw()

    import playwright.sync_api as api
    monkeypatch.setattr(api, "sync_playwright", lambda: _Sync())
    bao = []
    with pytest.raises(RuntimeError):
        with ChromeTim(6, 0, bao=bao.append):
            pass
    assert dong == ["ctx", "pw"] and bao and "cửa sổ Chrome" in bao[0]


def test_captcha_dung_ngay_va_chup_anh(monkeypatch, tmp_path):
    """Pha 4 22/10: trang search hiện "Drag the slider to fit the puzzle" ⇒ phải dừng ở lần mở ĐẦU, không hâm, không đốt tiếp."""
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    t = _tim(monkeypatch, [{"items": [], "chu": "Log in | Drag the slider to fit the puzzle | Audio"}, DOM_GD1])
    t.chan_doan = tmp_path
    with pytest.raises(BiCaptcha):
        t.tim(TruyVan("7 pose ai trend", "cau_truc", "en"))
    assert t.da_mo == 1 and (tmp_path / "captcha-01.png").exists()


def test_la_captcha_tren_html_that_221022():
    """Mảnh HTML thật của trang search bị captcha (Pha 4, 22/10) ⇒ chữ hiển thị nhận ra captcha; trang kết quả thường thì không."""
    from html.parser import HTMLParser
    from pathlib import Path

    from tiktok_music_downloader.tim_trend.nguon_tim import la_captcha

    class _Chu(HTMLParser):
        def __init__(self):
            super().__init__()
            self.chu = []

        def handle_data(self, data):
            self.chu.append(data)

    p = _Chu()
    p.feed((Path(__file__).parent / "fixtures" / "tim_trend" / "captcha-search-221022.html").read_text())
    assert la_captcha(" | ".join(p.chu))
    assert not la_captcha("TikTok | 7 pose ai trend | Top | Users | Videos | AI collage 7 poses | saaart 4 ngày trước")


def _chu_captcha_that():
    """Chữ hiển thị của mảnh HTML captcha thật (Pha 4, 22/10)."""
    from html.parser import HTMLParser
    from pathlib import Path

    class _Chu(HTMLParser):
        def __init__(self):
            super().__init__()
            self.chu = []

        def handle_data(self, data):
            self.chu.append(data)

    p = _Chu()
    p.feed((Path(__file__).parent / "fixtures" / "tim_trend" / "captcha-search-221022.html").read_text())
    return " | ".join(p.chu)


class _DongHo:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _tim_cho(monkeypatch, ket_qua, cho_giai_giay):
    dong_ho = _DongHo()
    monkeypatch.setattr(nguon_tim, "time", dong_ho)
    t = ChromeTim(tran_luot=6, gian_cach=0, bao=lambda s: None, cho_giai_giay=cho_giai_giay)
    t._page = _TrangGia(ket_qua)
    return t


def test_cho_nguoi_giai_captcha_roi_chay_tiep_khong_ton_luot(monkeypatch):
    cap = {"items": [], "chu": _chu_captcha_that()}
    t = _tim_cho(monkeypatch, [cap, cap, cap, {"items": DOM_GD1, "chu": "TikTok | Videos"}], cho_giai_giay=60)
    ra, _ = t.tim(TruyVan("7 pose ai trend", "cau_truc", "en"))
    assert len(ra) == 2 and t.da_mo == 1 and len(t._page.da_goto) == 1   # không mở trang mới khi chờ


def test_giai_xong_luoi_chua_tai_thi_doc_lai_mot_lan(monkeypatch):
    cap = {"items": [], "chu": _chu_captcha_that()}
    t = _tim_cho(monkeypatch, [cap, {"items": [], "chu": "TikTok | Videos"}, {"items": DOM_GD1, "chu": "TikTok"}],
                 cho_giai_giay=60)
    ra, ghi_chu = t.tim(TruyVan("7 pose ai trend", "cau_truc", "en"))
    assert len(ra) == 2 and "ham" not in ghi_chu and t.da_mo == 1


def test_het_gio_cho_thi_dung(monkeypatch):
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    cap = {"items": [], "chu": _chu_captcha_that()}
    t = _tim_cho(monkeypatch, [cap] * 50, cho_giai_giay=10)
    with pytest.raises(BiCaptcha, match="không ai giải trong 10 giây"):
        t.tim(TruyVan("7 pose ai trend", "cau_truc", "en"))


def test_mac_dinh_tat_cho_giai_va_profile_trang(monkeypatch, tmp_path):
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    t = _tim_cho(monkeypatch, [{"items": [], "chu": _chu_captcha_that()}, DOM_GD1], cho_giai_giay=0)
    with pytest.raises(BiCaptcha):
        t.tim(TruyVan("x", "cau_truc", "en"))
    assert ChromeTim(6, 0).profile_ben is None and ChromeTim(6, 0).cho_giai_giay == 0


def test_profile_ben_duoc_dung_lai(monkeypatch, tmp_path):
    da_mo_thu_muc = []

    class _Ctx:
        def new_page(self):
            return object()

        def close(self):
            pass

    class _Chromium:
        def launch_persistent_context(self, thu_muc, **k):
            da_mo_thu_muc.append(thu_muc)
            return _Ctx()

    class _Pw:
        chromium = _Chromium()

        def stop(self):
            pass

    import playwright.sync_api as api
    monkeypatch.setattr(api, "sync_playwright", lambda: type("S", (), {"start": lambda self: _Pw()})())
    ben = tmp_path / "profile-tiktok"
    for _ in range(2):
        with ChromeTim(6, 0, bao=lambda s: None, profile_ben=ben):
            pass
    with ChromeTim(6, 0, bao=lambda s: None):
        pass
    assert da_mo_thu_muc[0] == da_mo_thu_muc[1] == str(ben) and ben.is_dir()
    assert da_mo_thu_muc[2] != str(ben)


def test_anh_giu_cho_data_bi_bo_va_trang_duoc_cuon(monkeypatch):
    """Pha 4 23/10: thẻ chưa cuộn tới có img.src = 'data:…' ⇒ 88/181 ứng viên lỗi InvalidSchema lúc tải."""
    dom = DOM_GD1 + [{"url": "https://www.tiktok.com/@z/video/7699000000000000009",
                      "cover": "data:image/png;base64,iVBOR", "caption": "chưa tải lười"}]
    assert "7699000000000000009" not in [u.video_id for u in tu_dom(dom, "q")]
    t = _tim(monkeypatch, [dom])
    t.tim(TruyVan("q", "cau_truc", "en"))
    assert t._page.mouse.cuon >= 3


def test_captcha_khong_bat_nham_caption_co_chu_captcha():
    from tiktok_music_downloader.tim_trend.nguon_tim import la_captcha
    assert not la_captcha("TikTok | Videos | how I solve every captcha in 2 seconds #captcha #lifehack")
    assert la_captcha("TikTok | Videos", co_hop_captcha=True)
    assert la_captcha("Log in | Drag the slider to fit the puzzle | Audio")


def test_goto_loi_van_dem_luot_va_dung_sach(monkeypatch):
    from tiktok_music_downloader.tim_trend.nguon_tim import LoiMoTrang
    t = _tim(monkeypatch, [DOM_GD1])

    def no(url, **k):
        raise TimeoutError("Timeout 30000ms exceeded")

    t._page.goto = no
    with pytest.raises(LoiMoTrang):
        t.tim(TruyVan("q", "cau_truc", "en"))
    assert t.da_mo == 1


def test_doc_trang_loi_luc_cho_captcha_thi_doc_lai(monkeypatch):
    cap = {"items": [], "chu": "Drag the slider to fit the puzzle"}
    t = _tim_cho(monkeypatch, [cap, RuntimeError("Execution context was destroyed"), {"items": DOM_GD1, "chu": "TikTok"}],
                 cho_giai_giay=60)
    goc = t._page.evaluate

    def eval_co_loi(js):
        muc = t._page.ket_qua[0]
        if isinstance(muc, Exception):
            t._page.ket_qua.pop(0)
            raise muc
        return goc(js)

    t._page.evaluate = eval_co_loi
    ra, _ = t.tim(TruyVan("q", "cau_truc", "en"))
    assert len(ra) == 2 and t.da_mo == 1


def test_profile_tam_bi_xoa_khi_dong(monkeypatch):
    from pathlib import Path
    tao = []

    class _Ctx:
        def new_page(self):
            return object()

        def close(self):
            pass

    class _Chromium:
        def launch_persistent_context(self, thu_muc, **k):
            tao.append(thu_muc)
            (Path(thu_muc) / "Cookies").write_text("tiktok")
            return _Ctx()

    class _Pw:
        chromium = _Chromium()

        def stop(self):
            pass

    import playwright.sync_api as api
    monkeypatch.setattr(api, "sync_playwright", lambda: type("S", (), {"start": lambda self: _Pw()})())
    with ChromeTim(6, 0, bao=lambda s: None):
        assert Path(tao[0]).is_dir()
    assert not Path(tao[0]).exists()


def test_hop_captcha_qua_duong_dom_thi_dung(monkeypatch):
    """Review 23/10 H-b: chữ trang bình thường nhưng DOM có hộp captcha đang hiển thị ⇒ phải dừng qua _mo."""
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    t = _tim(monkeypatch, [{"items": [], "chu": "TikTok | Videos", "hop_captcha": True}, DOM_GD1])
    with pytest.raises(BiCaptcha):
        t.tim(TruyVan("q", "cau_truc", "en"))
    assert t.da_mo == 1


def test_dong_cua_so_luc_cho_captcha_la_loi_trang_khong_phai_captcha(monkeypatch):
    """Review 23/10 M-a: đóng cửa sổ khi đang chờ ⇒ dừng ngay mã 5 (LoiMoTrang), không chờ hết 600 s rồi báo captcha."""
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha, LoiMoTrang
    cap = {"items": [], "chu": "Drag the slider to fit the puzzle"}
    t = _tim_cho(monkeypatch, [cap], cho_giai_giay=600)

    def chet(js):
        if t._page.ket_qua:
            return t._page.ket_qua.pop(0)
        t._page.dong = True
        raise RuntimeError("Target page, context or browser has been closed")

    t._page.evaluate = chet
    with pytest.raises(LoiMoTrang) as e:
        t.tim(TruyVan("q", "cau_truc", "en"))
    assert not isinstance(e.value, BiCaptcha)


def test_doc_lai_sau_khi_giai_bi_loi_khong_sap(monkeypatch):
    """Review 23/10 M-a: lần đọc lại sau khi giải (lưới chưa tải) ném lỗi vì trang tải lại ⇒ không traceback."""
    cap = {"items": [], "chu": "Drag the slider to fit the puzzle"}
    t = _tim_cho(monkeypatch, [cap, {"items": [], "chu": "TikTok"}, RuntimeError("context destroyed"), DOM_GD1],
                 cho_giai_giay=60)
    goc = t._page.evaluate

    def eval_co_loi(js):
        if isinstance(t._page.ket_qua[0], Exception):
            raise t._page.ket_qua.pop(0)
        return goc(js)

    t._page.evaluate = eval_co_loi
    ra, ghi_chu = t.tim(TruyVan("q", "cau_truc", "en"))
    assert len(ra) == 2 and ghi_chu == "ham phien" and t.da_mo == 2   # đọc lại lỗi ⇒ không sập; lưới rỗng ⇒ hâm phiên


def test_luu_dom_trang_thuong_mot_lan(monkeypatch, tmp_path):
    t = _tim(monkeypatch, [DOM_GD1, DOM_GD1])
    t.chan_doan = tmp_path
    t._page.content = lambda: "<html>trang thuong</html>"
    t.tim(TruyVan("a", "cau_truc", "en"))
    t._page.content = lambda: "<html>lan hai</html>"
    t.tim(TruyVan("b", "cau_truc", "en"))
    assert (tmp_path / "dom-trang-thuong.html").read_text() == "<html>trang thuong</html>"
