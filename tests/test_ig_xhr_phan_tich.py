"""Hàm thuần phân tích XHR Instagram: bóc `for (;;);`, duyệt node, lọc video, phân trang, từng dấu mất phiên."""
from __future__ import annotations

import json

import pytest

from ig_khung_gia import PAD, carousel, ma, node, thanh_audio, thanh_gia, xhr
from tiktok_music_downloader import ig_xhr_phan_tich as ph

OK = "https://www.instagram.com/ten.gia/reels/"
TOT = [xhr(thanh_gia([node(ma(1))]))]


def test_bo_tien_to_for_hijack_roi_parse_json():
    """ĐỘT BIẾN: bỏ bóc `for (;;);` ⇒ ĐỎ."""
    tho = thanh_audio([node(ma(1))])
    assert tho.startswith("for (;;);")
    assert ph.bo_tien_to(tho).startswith("{")
    assert ph.bo_tien_to("  for (;;);{\"a\":1}") == '{"a":1}'
    j = ph.doc_json(tho)
    assert isinstance(j, dict) and len(j["items"]) == 1
    assert ph.doc_json("khong phai json") is None and ph.doc_json("") is None


def test_duyet_node_khong_di_vao_ben_trong_node_media_va_giu_thu_tu():
    goc = json.loads(thanh_gia([node(ma(1)), carousel(ma(2), co_video=True), node(ma(3), 1)]))
    nodes = ph.duyet_node_media(goc)
    assert [n["code"] for n in nodes] == [ma(1), ma(2), ma(3)]
    # con của carousel có thể mang `code` riêng: không được đếm lần hai
    car = node(ma(9), 8, carousel_media=[node(ma(10), 2)])
    assert [n["code"] for n in ph.duyet_node_media({"x": [car]})] == [ma(9)]


def test_loc_video_chi_giu_media_type_2_va_dem_carousel():
    """ĐỘT BIẾN: bỏ lọc video (giữ cả ảnh/carousel) ⇒ ĐỎ."""
    nodes = [node(ma(1)), node(ma(2), 1), carousel(ma(3)), carousel(ma(4), co_video=True), node(ma(1)), node(ma(5))]
    video, so_car = ph.loc_video(nodes)
    assert [n["code"] for n in video] == [ma(1), ma(5)]          # ảnh bỏ, carousel (kể cả có con video) bỏ, trùng bỏ
    assert so_car == 2


def test_loc_video_bo_ma_la_khong_vao_url():
    video, _ = ph.loc_video([node("a/../b"), node("ab"), node(ma(7))])
    assert [n["code"] for n in video] == [ma(7)]


def test_doc_phan_trang_graphql_va_audio():
    assert ph.doc_phan_trang(json.loads(thanh_gia([], con_trang=True, con_tro="C1"))) == ph.Phan(True, "C1")
    assert ph.doc_phan_trang(json.loads(thanh_gia([], con_trang=False, con_tro=None))) == ph.Phan(False, None)
    assert ph.doc_phan_trang(ph.doc_json(thanh_audio([], con_trang=True, max_id="M9"))) == ph.Phan(True, "M9")
    assert ph.doc_phan_trang(ph.doc_json(thanh_audio([], con_trang=False, max_id=None))).con_trang is False
    assert ph.doc_phan_trang({"khong": "co"}) is None


@pytest.mark.parametrize("url,post,loai", [
    ("https://www.instagram.com/graphql/query", "fb_api_req_friendly_name=PolarisProfileReelsTabContentQuery_connection&v=1", "profile"),
    ("https://www.instagram.com/api/graphql", "fb_api_req_friendly_name=KeywordSearchExplorePageQuery", "keyword"),
    ("https://www.instagram.com/api/v1/clips/music/", "max_id=abc", "audio"),
    ("https://www.instagram.com/graphql/query", "fb_api_req_friendly_name=PolarisFeedQuery", None),
    ("https://www.instagram.com/graphql/query", "", None),
    ("https://www.instagram.com/api/v1/feed/timeline/", "x=1", None),
])
def test_nhan_dang_xhr_dich(url, post, loai):
    assert ph.la_xhr_dich(url, post) == loai


# ------------------------------------------------------------ từng dấu mất phiên (mỗi dấu một test + đột biến)

def _mp(url=OK, x=TOT, dom=None, audio=False, cho=True):
    return ph.phan_loai_mat_phien(url, x, dom or ph.DauDom(), la_audio=audio, da_cho_du_xhr=cho)


def test_phien_binh_thuong_khong_co_dau():
    assert _mp() is None
    assert _mp(x=[], cho=False) is None            # chưa đợi đủ ⇒ chưa kết luận
    assert _mp(url="https://www.instagram.com/ten.gia/reels/", audio=True, x=[]) is None


@pytest.mark.parametrize("url", ["https://www.instagram.com/accounts/login/?next=/ten.gia/reels/",
                                 "https://www.instagram.com/challenge/action/xyz/",
                                 "https://www.instagram.com/accounts/suspended/checkpoint/"])
def test_dau_1_url_cuoi_dang_nhap_challenge_checkpoint(url):
    """ĐỘT BIẾN dấu 1: bỏ kiểm URL ⇒ ĐỎ."""
    assert _mp(url=url) == ph.MP_URL_DANG_NHAP
    assert _mp(url=url, audio=True) == ph.MP_URL_DANG_NHAP        # audio cũng bắt được dấu 1


def test_dau_2_xhr_dich_nho_hon_1kb():
    """ĐỘT BIẾN dấu 2 (kích thước): bỏ kiểm < 1024 B ⇒ ĐỎ."""
    nho = [xhr('{"data":{"a":1}}')]
    assert nho[0].size < ph.NGUONG_XHR_NHO_BYTE
    assert _mp(x=nho) == ph.MP_XHR_NHO
    assert _mp(x=nho + TOT) is None          # chỉ khi MỌI XHR đều nhỏ


def test_dau_2_xhr_json_co_errors_ma_1675002():
    """ĐỘT BIẾN dấu 2 (errors): bỏ kiểm `errors` ⇒ ĐỎ."""
    loi = xhr(json.dumps({"errors": [{"message": "Unauthorized logged out query.", "code": 1675002}], "pad": PAD}))
    assert loi.size >= ph.NGUONG_XHR_NHO_BYTE        # lớn: chỉ `errors` mới bắt được
    assert _mp(x=TOT + [loi]) == ph.MP_XHR_LOI
    assert _mp(x=[xhr(json.dumps({"require_login": True, "pad": PAD}))]) == ph.MP_XHR_LOI


@pytest.mark.parametrize("dom", [ph.DauDom(co_o_ten_dang_nhap=True), ph.DauDom(co_nut_dang_nhap=True),
                                 ph.DauDom(tieu_de_loi=True), ph.DauDom(chu_loi=True)])
def test_dau_3_dom_bat_ca_tren_trang_audio(dom):
    """ĐỘT BIẾN dấu 3: bỏ kiểm DOM ⇒ ĐỎ. Trang audio KHÔNG cookie vẫn ra dữ liệu ⇒ chỉ dấu 1/3 bắt được."""
    audio_van_ra_du_lieu = [xhr(thanh_audio([node(ma(i)) for i in range(12)]))]
    assert _mp(x=audio_van_ra_du_lieu, dom=dom, audio=True) == ph.MP_DOM_DANG_NHAP
    assert _mp(x=TOT, dom=dom) == ph.MP_DOM_DANG_NHAP


def test_audio_khong_bi_bat_nham_boi_dau_2_va_4():
    """Audio: lượt cuối nhỏ / 0 XHR không phải mất phiên (đo: audio không cookie vẫn ra dữ liệu)."""
    nho = [xhr('for (;;);{"items":[],"paging_info":{"more_available":false}}')]
    assert _mp(x=nho, audio=True) is None
    assert _mp(x=[], audio=True) is None


def test_dau_4_trang_khong_phai_audio_0_xhr_sau_tai_va_cuon():
    """ĐỘT BIẾN dấu 4: bỏ kiểm 0 XHR ⇒ ĐỎ."""
    assert _mp(x=[], cho=True) == ph.MP_KHONG_XHR_DICH


def test_dau_5_http_429_tren_xhr_dich():
    """ĐỘT BIẾN dấu 5: bỏ kiểm 429 ⇒ ĐỎ."""
    assert _mp(x=TOT + [xhr("", status=429)]) == ph.MP_HTTP_429
    assert _mp(x=[xhr("", status=429)], audio=True) == ph.MP_HTTP_429


def test_tom_tat_node_lay_tac_gia_va_mo_ta_cat_ngan_va_chiu_thieu():
    t = ph.tom_tat_node({"code": ma(1), "media_type": 2, "user": {"username": "u1"},
                         "caption": {"text": "c" * 500}})
    assert t == {"author": "u1", "title": "c" * 200}
    assert ph.tom_tat_node(node(ma(1))) == {"author": None, "title": None}
