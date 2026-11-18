"""Bóc mã video Facebook: hàm thuần, payload tự dựng nhỏ (mô phỏng đường dẫn đo được ở plan §5), không mạng."""
from __future__ import annotations

import json

import pytest

from fb_khung_gia import (
    CHU_LA, CHU_PAGE, container, ma, media_reel, nut, script_reels, script_videos, than_reels, than_videos,
)

from tiktok_music_downloader import fb_xhr_phan_tich as ph


# ------------------------------------------------------------------------------- whitelist XHR

@pytest.mark.parametrize("ten", sorted(ph.TEN_GRAPHQL_DICH))
def test_whitelist_nhan_dung_bon_truy_van(ten):
    assert ph.ten_xhr_dich("https://www.facebook.com/api/graphql/", f"a=1&fb_api_req_friendly_name={ten}&b=2") == ten


def test_whitelist_co_dung_bon_ten_theo_plan():
    assert ph.TEN_GRAPHQL_DICH == {
        "CometProfilePlusVideosRootQuery", "PagesCometChannelTabAllVideosCardImplPaginationQuery",
        "ProfileCometTopAppSectionQuery", "ProfileCometAppCollectionReelsRendererPaginationQuery"}


@pytest.mark.parametrize("ten", ["useInstreamAdsHaloFetcherQuery", "CometChannelTabVideoPreviewRootQuery", "Khac", ""])
def test_whitelist_loai_quang_cao_va_xem_truoc(ten):
    """`useInstreamAdsHaloFetcherQuery` (quảng cáo) và `CometChannelTabVideoPreviewRootQuery` KHÔNG được bắt.
    ĐỘT BIẾN: thêm hai tên đó vào whitelist ⇒ ĐỎ."""
    assert ph.ten_xhr_dich("https://www.facebook.com/api/graphql/", f"fb_api_req_friendly_name={ten}") is None


def test_whitelist_chi_duong_api_graphql_va_ten_tu_header_khi_than_khong_co():
    ten = "CometProfilePlusVideosRootQuery"
    assert ph.ten_xhr_dich("https://www.facebook.com/ajax/x", f"fb_api_req_friendly_name={ten}") is None
    assert ph.ten_xhr_dich("https://www.facebook.com/api/graphql", "", ten) == ten
    assert ph.ten_xhr_dich("https://www.facebook.com/api/graphql", None, "useInstreamAdsHaloFetcherQuery") is None
    assert ph.ten_xhr_dich("https://[::1", "", ten) is None            # URL hỏng không ném


# ------------------------------------------------------------------------------- JSON nhiều dòng / script

def test_doc_nhieu_dong_moi_dong_mot_object_bo_dong_hong():
    assert ph.doc_nhieu_dong('{"a":1}\n\nrac khong phai json\n{"b":2}\n') == [{"a": 1}, {"b": 2}]
    assert ph.doc_nhieu_dong("") == [] and ph.doc_nhieu_dong(None) == []


def test_doc_script_json_bo_the_khong_phai_json():
    assert ph.doc_script_json(['{"a":1}', "window.x=1", "", "[1]"]) == [{"a": 1}, [1]]


# ------------------------------------------------------------------------------- tab /videos

def test_videos_nhan_ca_bon_container_va_nut_truc_tiep_popular():
    goc = [{"data": {
        "all_videos": container([nut(ma(1))]),
        "latest_videos": container([nut(ma(2))]),
        "series_videos": container([nut(ma(3))]),
        "video_list_videos": container([nut(ma(4))]),
        # thẻ "Most popular": nút trực tiếp, KHÔNG có `__typename`
        "channel_tab_popular_video": {"id": ma(5), "owner": {"id": CHU_PAGE}, "playable_duration_in_ms": 90000},
    }}]
    kq = ph.boc_nut(goc, "videos")
    assert [n.ma for n in kq.nut] == [ma(i) for i in (1, 2, 3, 4, 5)]
    assert {n.owner for n in kq.nut} == {CHU_PAGE}
    assert kq.nut[4].giay == 90


def test_videos_khong_di_regex_phang_chi_nhan_nut_o_duong_dan_container():
    """Video của bình luận, mục gợi ý, id trong chuỗi URL… không nằm ở container ⇒ không bao giờ được nhận.
    ĐỘT BIẾN: đổi sang quét mọi `__typename == "Video"` ⇒ ĐỎ."""
    la = nut(ma(77, "7"), CHU_LA)
    goc = [{"data": {
        "all_videos": container([nut(ma(1))]),
        "comment": {"parent_post_story": {"attachments": [{"media": la}]}},        # video của bình luận
        "video": nut(ma(78, "7"), CHU_LA),                                          # nút lẻ ngoài container
        "url": f"https://www.facebook.com/x/videos/{ma(79, '7')}/", "videoId": ma(80, "7"),
    }}]
    assert [n.ma for n in ph.boc_nut(goc, "videos").nut] == [ma(1)]


def test_videos_nut_sai_hinh_bi_bo():
    sai = [{"__typename": "Photo", "id": ma(1), "owner": {"id": CHU_PAGE}},                # không phải Video
           {"__typename": "Video", "id": "abc", "owner": {"id": CHU_PAGE}},                # id không phải số
           {"__typename": "Video", "id": ma(2)},                                           # thiếu owner
           {"__typename": "Video", "id": ma(3), "owner": {"__typename": "User"}},          # owner không có id
           nut(ma(4))]
    kq = ph.boc_nut([{"all_videos": container(sai)}], "videos")
    assert [n.ma for n in kq.nut] == [ma(4)] and kq.so_thieu_owner == 2


def test_videos_nut_popular_co_typename_khac_video_bi_bo():
    assert ph.boc_nut([{"channel_tab_popular_video": {"__typename": "Photo", "id": ma(1), "owner": {"id": CHU_PAGE}}}],
                      "videos").nut == []


def test_nut_trung_ma_chi_giu_mot():
    kq = ph.boc_nut([{"all_videos": container([nut(ma(1)), nut(ma(1))])},
                     {"latest_videos": container([nut(ma(1)), nut(ma(2))])}], "videos")
    assert [n.ma for n in kq.nut] == [ma(1), ma(2)]


def test_videos_boc_tu_script_long_sau_va_xhr_nhieu_dong_bo_video_lac_o_dong_defer():
    goc = ph.doc_script_json([script_videos([nut(ma(1)), nut(ma(2))])]) + ph.doc_nhieu_dong(than_videos([nut(ma(3))]))
    kq = ph.boc_nut(goc, "videos")
    assert [n.ma for n in kq.nut] == [ma(1), ma(2), ma(3)]                  # mảnh `@defer` mang video lạ ⇒ không nhận


# ------------------------------------------------------------------------------- tab /reels

def test_reels_nhan_dung_duong_dan_aggregated_fb_shorts():
    goc = ph.doc_script_json([script_reels([media_reel(ma(1), giay=30)])]) + ph.doc_nhieu_dong(
        than_reels([media_reel(ma(2)), media_reel(ma(3), giay=45)]))
    kq = ph.boc_nut(goc, "reels")
    assert [(n.ma, n.giay) for n in kq.nut] == [(ma(1), 30), (ma(2), None), (ma(3), 45)]   # video lạ ở dòng defer ⇒ không


def test_moi_tab_chi_doc_container_cua_minh():
    goc = [{"all_videos": container([nut(ma(1))]), "node": {"aggregated_fb_shorts": container(
        [media_reel(ma(2))], reels=True)}}]
    assert [n.ma for n in ph.boc_nut(goc, "videos").nut] == [ma(1)]
    assert [n.ma for n in ph.boc_nut(goc, "reels").nut] == [ma(2)]


# ------------------------------------------------------------------------------- phân trang + thời lượng

def test_phan_trang_lay_tu_container_va_none_khi_khong_co():
    assert ph.boc_nut([{"all_videos": container([nut(ma(1))], con_trang=True)}], "videos").con_trang is True
    assert ph.boc_nut([{"all_videos": container([nut(ma(1))], con_trang=False)}], "videos").con_trang is False
    assert ph.boc_nut([{"all_videos": {"edges": [{"node": nut(ma(1))}]}}], "videos").con_trang is None
    # nhiều container: còn trang nếu CÓ container nào còn
    kq = ph.boc_nut([{"all_videos": container([nut(ma(1))], con_trang=False),
                      "latest_videos": container([nut(ma(2))], con_trang=True)}], "videos")
    assert kq.con_trang is True


def test_thoi_luong_giay_hoac_mili_giay_hoac_khong_co():
    assert ph.boc_nut([{"all_videos": container([nut(ma(1), giay=67)])}], "videos").nut[0].giay == 67   # sâu trong cây
    n = nut(ma(2))
    n["length_in_second"] = 50.901
    assert ph.boc_nut([{"all_videos": container([n])}], "videos").nut[0].giay == 50
    assert ph.boc_nut([{"all_videos": container([nut(ma(3))])}], "videos").nut[0].giay is None
    n4 = nut(ma(4))
    n4["playable_duration_in_ms"] = True                                  # bool không phải số đo
    assert ph.boc_nut([{"all_videos": container([n4])}], "videos").nut[0].giay is None


def test_payload_la_khong_lam_vo_bo_boc():
    for goc in ([], [None, 1, "x", [[]], {"all_videos": "x"}, {"all_videos": {"edges": [1, None]}},
                      {"aggregated_fb_shorts": {"edges": [{"profile_reel_node": None}, 3]}}]):
        assert ph.boc_nut(goc, "videos").nut == [] and ph.boc_nut(goc, "reels").nut == []
    assert json.dumps(ph.boc_nut([], "videos").con_trang) == "null"
