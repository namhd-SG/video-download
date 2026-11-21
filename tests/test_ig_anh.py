"""Tải ẢNH Instagram (profile ảnh + carousel + reel, link lẻ `/p/`): payload TỰ DỰNG, không mạng, không trình duyệt.

Đột biến (tự áp, xác nhận ĐỎ, hoàn nguyên XANH; chạy `PYTHONPATH=src:. python -m pytest -q -p no:cacheprovider
tests/test_ig_anh.py` sau khi áp):
  * M7  `nguon_instagram.py::liet_ke`: bỏ `loai=loai` khỏi lời gọi `ig_quet_cuon.quet(...)` (enumerator IG bỏ qua loai)
        ⇒ `test_liet_ke_ca_hai_*` / `test_liet_ke_anh_*` ĐỎ (ra reel thay vì bài ảnh).
  * M11 `tai_anh.py::tai_mot_bai`/`_tai_mot_tep`: bỏ lời gọi `kiem_video(...)` của con-video
        ⇒ `test_con_video_carousel_ig_phai_qua_cong_kiem_video` ĐỎ (và `tests/test_tai_anh_loi.py` của lớp tải).
"""
from __future__ import annotations

import json

import pytest

from ig_khung_gia import PhienGia, TrangGia, dot, ma, node, xhr
from tiktok_music_downloader import ig_quet_cuon as q
from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader import nguon_instagram as ni
from tiktok_music_downloader import tai_anh
from tiktok_music_downloader.utils import STOP_COMPLETE

URL_LUOI = "https://www.instagram.com/ten.gia/"
URL_REELS = "https://www.instagram.com/ten.gia/reels/"


def cand(w: int, h: int, tag: str) -> dict:
    return {"width": w, "height": h, "url": f"https://cdn.gia/{tag}_{w}x{h}.jpg"}


def anh(code: str, tag: str | None = None) -> dict:
    t = tag or code
    return node(code, 1, image_versions2={"candidates": [cand(320, 400, t), cand(1080, 1350, t), cand(640, 800, t)]},
                user={"username": "nguoi_gia"}, caption={"text": "mô tả giả"})


def con_anh(tag: str) -> dict:
    return {"media_type": 1, "image_versions2": {"candidates": [cand(150, 150, tag), cand(1080, 1080, tag)]}}


def con_video(tag: str) -> dict:
    return {"media_type": 2, "video_versions": [{"url": f"https://cdn.gia/{tag}_a.mp4"},
                                                {"url": f"https://cdn.gia/{tag}_b.mp4"}]}


def cuon(code: str, cons: list[dict]) -> dict:
    return node(code, 8, carousel_media=cons)


def luoi() -> list[dict]:
    """Lưới profile: ảnh, carousel 3 ảnh, reel, carousel (ảnh+video+ảnh), ảnh."""
    return [anh(ma(1, "A")), cuon(ma(2, "C"), [con_anh("c1"), con_anh("c2"), con_anh("c3")]), node(ma(3, "R"), 2),
            cuon(ma(4, "D"), [con_anh("d1"), con_video("d2"), con_anh("d3")]), anh(ma(5, "A"))]


def chay(loai: str, nodes=None, **kw):
    t = TrangGia([dot(nodes or luoi(), con_trang=False)], url_cuoi=URL_LUOI)
    bo_qua = []
    kq = q.quet(t, URL_LUOI, la_audio=False, max_videos=kw.pop("n", 20), already_have=lambda ids: set(),
                on_skip=bo_qua.append, ngu=lambda s: None, ngau_nhien=lambda a, b: a, loai=loai, **kw)
    return kq


# ---------------------------------------------------------------------------- phân tích node

def test_anh_don_lay_candidate_lon_nhat_va_url_du_phong_giam_dan():
    ref = ph.ref_anh_tu_node(anh(ma(1, "A"), "t"))
    assert ref.loai == "anh" and ref.video_id == f"anh-ig-{ma(1, 'A')}"
    assert ref.url == f"https://www.instagram.com/p/{ma(1, 'A')}/"
    assert ref.anh_kieu == ("anh",)
    assert ref.anh_urls == (("https://cdn.gia/t_1080x1350.jpg", "https://cdn.gia/t_640x800.jpg",
                             "https://cdn.gia/t_320x400.jpg"),)
    assert ref.author == "nguoi_gia" and ref.title == "mô tả giả"


def test_carousel_tach_con_anh_video_theo_thu_tu_mot_bai_mot_ref():
    ref = ph.ref_anh_tu_node(luoi()[3])
    assert ref.anh_kieu == ("anh", "video", "anh")
    assert ref.anh_urls[0][0].endswith("d1_1080x1080.jpg")
    assert ref.anh_urls[1] == ("https://cdn.gia/d2_a.mp4", "https://cdn.gia/d2_b.mp4")      # video_versions[0] đầu
    assert len(ref.anh_urls) == len(ref.anh_kieu) == 3


@pytest.mark.parametrize("hong", [
    cuon(ma(9, "H"), []),
    cuon(ma(9, "H"), [con_anh("x"), {"media_type": 2}]),               # con video không có video_versions
    cuon(ma(9, "H"), [con_anh("x"), {"media_type": 1}]),               # con ảnh không có candidates
    cuon(ma(9, "H"), [con_anh("x"), {"media_type": 5}]),               # loại con lạ
    node(ma(9, "H"), 1),                                               # ảnh đơn không URL
    node("a b", 1, image_versions2={"candidates": [cand(10, 10, "z")]}),   # mã sai hình
])
def test_bai_thieu_url_hoac_sai_hinh_bi_bo_ca_bai(hong):
    assert ph.ref_anh_tu_node(hong) is None
    ra, so_hong = ph.loc_anh([hong]) if hong["code"] != "a b" else ([], 0)
    assert ra == [] and so_hong == (1 if hong["code"] != "a b" else 0)


def test_loc_video_giu_nguyen_chi_media_type_2_va_dem_carousel():
    video, so_cuon = ph.loc_video(ph.duyet_node_media(json.loads(json.dumps(luoi()))))
    assert [n["code"] for n in video] == [ma(3, "R")] and so_cuon == 2


def test_loc_anh_giu_1_va_8_bo_video_va_trung():
    nodes = luoi() + [anh(ma(1, "A"))]
    ra, hong = ph.loc_anh(nodes)
    assert [n["code"] for n in ra] == [ma(1, "A"), ma(2, "C"), ma(4, "D"), ma(5, "A")] and hong == 0


def test_loc_ca_hai_giu_thu_tu_luoi():
    ra, _ = ph.loc_ca_hai(luoi())
    assert [(k, n["code"]) for k, n in ra] == [("anh", ma(1, "A")), ("anh", ma(2, "C")), ("video", ma(3, "R")),
                                               ("anh", ma(4, "D")), ("anh", ma(5, "A"))]


def test_xhr_luoi_bai_chi_bat_khi_gom_anh():
    for ten in ("PolarisProfilePostsQuery", "PolarisProfilePostsTabContentQuery_connection"):
        post = f"fb_api_req_friendly_name={ten}"
        assert ph.la_xhr_dich("https://www.instagram.com/graphql/query", post) is None
        assert ph.la_xhr_dich("https://www.instagram.com/graphql/query", post, gom_anh=True) == "profile"
    ten_cu = "fb_api_req_friendly_name=ProfileReelsTab"
    assert ph.la_xhr_dich("https://www.instagram.com/graphql/query", ten_cu) == "profile"


# ---------------------------------------------------------------------------- vòng quét theo loai

def test_quet_ca_hai_so_item_bang_so_bai_va_video_y_het():
    kq = chay("ca_hai", n=5)
    assert len(kq.refs) == 5 and kq.ly_do == STOP_COMPLETE            # carousel = 1 item
    assert [r.loai for r in kq.refs] == ["anh", "anh", "video", "anh", "anh"]
    assert kq.refs[2].video_id == "ig-" + ma(3, "R") and kq.refs[2].url.endswith(f"/reel/{ma(3, 'R')}/")
    kv = chay("video")
    assert [r.video_id for r in kv.refs] == ["ig-" + ma(3, "R")] and kv.so_carousel == 2 and kv.so_anh_hong == 0


def test_quet_mac_dinh_la_video():
    t = TrangGia([dot(luoi(), con_trang=False)], url_cuoi=URL_LUOI)
    kq = q.quet(t, URL_LUOI, la_audio=False, max_videos=9, already_have=lambda i: set(), on_skip=lambda r: None,
                ngu=lambda s: None, ngau_nhien=lambda a, b: a)
    assert [r.video_id for r in kq.refs] == ["ig-" + ma(3, "R")]


def test_quet_anh_chi_anh_va_dedupe_theo_bai_id_va_cat_n():
    kq = chay("anh", n=3)
    assert [r.video_id for r in kq.refs] == [f"anh-ig-{ma(1, 'A')}", f"anh-ig-{ma(2, 'C')}", f"anh-ig-{ma(4, 'D')}"]
    t = TrangGia([dot(luoi(), con_trang=False)], url_cuoi=URL_LUOI)
    co = {f"anh-ig-{ma(2, 'C')}"}
    hoi = []
    bo = []
    kq = q.quet(t, URL_LUOI, la_audio=False, max_videos=9, loai="anh",
                already_have=lambda ids: hoi.extend(ids) or {i for i in ids if i in co}, on_skip=bo.append,
                ngu=lambda s: None, ngau_nhien=lambda a, b: a)
    assert len(kq.refs) == 3 and kq.so_da_co == 1 and bo[0].video_id in co and "ig-" + ma(3, "R") not in hoi


def test_quet_dem_bai_anh_hong_khong_nam_trong_ket_qua():
    kq = chay("anh", nodes=[anh(ma(1, "A")), node(ma(2, "A"), 1), cuon(ma(3, "C"), [])])
    assert len(kq.refs) == 1 and kq.so_anh_hong == 2


# ---------------------------------------------------------------------------- nguồn

def test_phan_tich_url_luoi_chi_khi_khong_phai_video():
    assert ni.phan_tich_url(URL_LUOI).url == URL_REELS                                # video ≡ hôm nay
    assert ni.phan_tich_url(URL_LUOI, "anh").url == URL_LUOI
    assert ni.phan_tich_url("https://instagram.com/ten.gia", "ca_hai").url == URL_LUOI
    assert ni.phan_tich_url(URL_REELS, "anh").url == URL_REELS                        # reels gõ rõ: giữ reels
    aud = "https://www.instagram.com/reels/audio/1485893805770596/"
    assert ni.phan_tich_url(aud, "anh").loai == "audio"


def test_loai_ho_tro_khai_dung():
    n = ni.InstagramHangLoat()
    ba = frozenset({"video", "anh", "ca_hai"})
    kw = "https://www.instagram.com/explore/search/keyword/?q=tandoor"
    ht = "https://www.instagram.com/explore/search/keyword/?q=%23tandoor"
    assert n.loai_ho_tro(URL_LUOI) == n.loai_ho_tro(kw) == n.loai_ho_tro(ht) == ba
    assert n.loai_ho_tro(URL_REELS) == frozenset({"video"})
    assert n.loai_ho_tro("https://www.instagram.com/reels/audio/1485893805770596/") == frozenset({"video"})


def _liet_ke(url, loai, monkeypatch, tmp_path, trang):
    monkeypatch.setattr(q.time, "sleep", lambda s: None)          # không chờ thật 6 giây mỗi lượt
    jar = tmp_path / "jar.json"
    jar.write_text("[]")
    video, anh_ = PhienGia(trang), PhienGia(trang)
    monkeypatch.setattr(ni, "_mo_phien", video)
    monkeypatch.setattr(ni, "_mo_phien_anh", anh_)
    ra = ni.InstagramHangLoat().liet_ke(url, max_videos=20, cookies_path=str(jar), already_have=lambda ids: set(),
                                        on_skip=lambda r: None, on_stop=lambda m: None, loai=loai)
    return ra, video, anh_


def test_liet_ke_ca_hai_mo_phien_anh_va_ra_dung_so_bai(monkeypatch, tmp_path):
    ra, video, anh_ = _liet_ke(URL_LUOI, "ca_hai", monkeypatch, tmp_path, TrangGia([dot(luoi(), con_trang=False)]))
    assert len(ra) == 5 and anh_.so_lan_mo == 1 and video.so_lan_mo == 0
    assert anh_.trang.da_mo == [URL_LUOI]                              # lưới bài, không ép /reels/


def test_liet_ke_anh_hashtag(monkeypatch, tmp_path):
    ht = "https://www.instagram.com/explore/search/keyword/?q=%23tandoor"
    ra, _, _ = _liet_ke(ht, "anh", monkeypatch, tmp_path, TrangGia([dot(luoi(), con_trang=False)], url_cuoi=ht))
    assert [r.loai for r in ra] == ["anh"] * 4


def test_liet_ke_video_y_het_dung_phien_cu(monkeypatch, tmp_path):
    ra, video, anh_ = _liet_ke(URL_LUOI, "video", monkeypatch, tmp_path, TrangGia([dot(luoi(), con_trang=False)]))
    assert [r.video_id for r in ra] == ["ig-" + ma(3, "R")] and video.so_lan_mo == 1 and anh_.so_lan_mo == 0
    assert video.trang.da_mo == [URL_REELS]


@pytest.mark.parametrize("url", [URL_REELS, "https://www.instagram.com/reels/audio/1485893805770596/"])
def test_liet_ke_reels_va_audio_khong_nhan_anh(url, monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        _liet_ke(url, "anh", monkeypatch, tmp_path, TrangGia([]))


# ---------------------------------------------------------------------------- link lẻ /p/

def _trang_bai(scripts: list[str], url_cuoi="https://www.instagram.com/p/ABCDE12345/", nav=200):
    class Trang:
        da_mo: list = []

        def mo(self, url):
            self.da_mo = [url]
            return nav

        def url_cuoi(self):
            return url_cuoi

        def doc_script_json(self):
            return scripts
    return Trang()


def _gia_bai(monkeypatch, trang):
    phien = PhienGia(trang)
    monkeypatch.setattr(ni, "_mo_phien_bai", phien)
    return phien


def _jar(tmp_path):
    p = tmp_path / "jar.json"
    p.write_text("[]")
    return str(p)


def test_link_le_boc_dung_node_theo_ma_khong_lay_bai_goi_y(monkeypatch, tmp_path):
    ma_dich = "ABCDE12345"
    goi_y = anh("ZZZZZ99999")
    dich = cuon(ma_dich, [con_anh("k1"), con_video("k2")])
    scripts = ["không phải json", json.dumps({"feed": [goi_y]}), json.dumps({"x": {"items": [dich]}})]
    t = _trang_bai(scripts)
    _gia_bai(monkeypatch, t)
    ref = ni.doc_bai_link_le(f"https://www.instagram.com/p/{ma_dich}/?img_index=2", cookies_path=_jar(tmp_path))
    assert ref.video_id == f"anh-ig-{ma_dich}" and ref.anh_kieu == ("anh", "video") and ref.loai == "anh"
    assert t.da_mo == [f"https://www.instagram.com/p/{ma_dich}/"]


def test_link_le_thu_node_cung_ma_ke_tiep_khi_ban_dau_thieu_url(monkeypatch, tmp_path):
    thieu = node("ABCDE12345", 1)
    day = anh("ABCDE12345")
    _gia_bai(monkeypatch, _trang_bai([json.dumps([thieu]), json.dumps([day])]))
    assert ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=_jar(tmp_path)) is not None


def test_link_le_khong_co_node_hoac_la_video_tra_none(monkeypatch, tmp_path):
    _gia_bai(monkeypatch, _trang_bai([json.dumps([anh("ZZZZZ99999"), node("ABCDE12345", 2)])]))
    assert ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=_jar(tmp_path)) is None


def test_link_le_can_cookie_va_url_dung_dang(monkeypatch, tmp_path):
    phien = _gia_bai(monkeypatch, _trang_bai([]))
    with pytest.raises(ValueError):
        ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=None)
    with pytest.raises(ValueError):
        ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=str(tmp_path / "khong-co.json"))
    with pytest.raises(ValueError):
        ni.doc_bai_link_le("https://www.instagram.com/reel/ABCDE12345/", cookies_path=_jar(tmp_path))
    assert phien.so_lan_mo == 0                                         # chưa mở trình duyệt


@pytest.mark.parametrize("url_cuoi,nav", [("https://www.instagram.com/accounts/login/?next=/p/x/", 200),
                                          ("https://www.instagram.com/p/ABCDE12345/", 429)])
def test_link_le_mat_phien_ne_loi_khong_lo_url(url_cuoi, nav, monkeypatch, tmp_path):
    _gia_bai(monkeypatch, _trang_bai([], url_cuoi=url_cuoi, nav=nav))
    with pytest.raises(RuntimeError) as e:
        ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=_jar(tmp_path))
    assert "ABCDE12345" not in str(e.value) and "instagram.com" not in str(e.value)


def test_link_le_loi_trinh_duyet_chi_giu_ten_lop(monkeypatch, tmp_path):
    monkeypatch.setattr(ni, "_mo_phien_bai", PhienGia(None, loi=OSError("goto https://www.instagram.com/p/ABCDE12345/")))
    with pytest.raises(RuntimeError) as e:
        ni.doc_bai_link_le("https://www.instagram.com/p/ABCDE12345/", cookies_path=_jar(tmp_path))
    assert "OSError" in str(e.value) and "instagram.com" not in str(e.value)


def test_tham_lai_tra_ref_moi_cung_id_va_thieu_cookie_ne_loi(monkeypatch, tmp_path):
    cu = ph.ref_anh_tu_node(anh("ABCDE12345", "cu"))
    _gia_bai(monkeypatch, _trang_bai([json.dumps([anh("ABCDE12345", "moi")])]))
    moi = ni.tham_lai(cu, None, cookies_path=_jar(tmp_path))
    assert moi.video_id == cu.video_id and moi.anh_urls != cu.anh_urls and "moi" in moi.anh_urls[0][0]
    with pytest.raises(ValueError):
        ni.tham_lai(cu, None)


# ---------------------------------------------------------------------------- con-video đi cổng kiểm luồng hình

def test_con_video_carousel_ig_phai_qua_cong_kiem_video(tmp_path):
    """ĐỘT BIẾN M11: bỏ lời gọi `kiem_video` của con-video trong `tai_anh.py` ⇒ ca `kiem_video=False` thành công
    thay vì hụt và `goi` rỗng ⇒ ĐỎ."""
    from test_tai_anh_loi import PhanHoi, anh_bytes
    ref = ph.ref_anh_tu_node(luoi()[3])                     # ảnh, VIDEO, ảnh
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 3000
    kich_ban = {u[0]: PhanHoi(body=video, ctype="video/mp4") if k == "video" else PhanHoi(body=anh_bytes())
                for u, k in zip(ref.anh_urls, ref.anh_kieu)}
    goi = []
    ok = tai_anh.tai_mot_bai(ref, tmp_path / "a", lay=lambda url, **kw: kich_ban[url],
                             kiem_video=lambda p: goi.append(p.name) or True)
    assert ok.ok and len(goi) == 1 and [p.suffix for p in ok.tep] == [".jpg", ".mp4", ".jpg"]
    sai = tai_anh.tai_mot_bai(ref, tmp_path / "b", lay=lambda url, **kw: kich_ban[url], kiem_video=lambda p: False)
    assert not sai.ok and not (tmp_path / "b" / ref.video_id).exists()
