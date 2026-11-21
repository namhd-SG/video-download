"""Bài ảnh TikTok: tikwm (hashtag) phân loại theo `loai`, thăm bài `tiktok_anh`, feed/anchor ở trình duyệt.

Không mạng, fixture tự dựng ẩn danh (handle `u1`, id số giả, URL `example.invalid`).

ĐỘT BIẾN (chứng minh test không xanh giả): bỏ qua `loai` trong trình liệt kê hashtag ⇒ các test `loai=...` ĐỎ.
  áp:      sed -i '' 's/kw_loai = {} if loai is None else {"loai": loai}/kw_loai = {}/' src/tiktok_music_downloader/hashtag_enumerator.py
  hoàn:    sed -i '' 's/        kw_loai = {}$/        kw_loai = {} if loai is None else {"loai": loai}/' src/tiktok_music_downloader/hashtag_enumerator.py
  chạy:    PYTHONPATH=src:. python -m pytest -q -p no:cacheprovider tests/test_tiktok_anh.py
"""
from __future__ import annotations

import json

import pytest

from tiktok_music_downloader import hashtag_enumerator as he
from tiktok_music_downloader import nguon_profile_yt_dlp as npy
from tiktok_music_downloader import scraper, tiktok_anh as ta
from tiktok_music_downloader.utils import VideoRef

ID_ANH = "7300000000000000001"
ID_VID = "7300000000000000002"


@pytest.fixture(autouse=True)
def _khong_ngu(monkeypatch):
    monkeypatch.setattr(he.time, "sleep", lambda _s: None)


# ---------- tikwm / hashtag ----------

def _muc(vid, images=None):
    m = {"video_id": vid, "author": {"unique_id": "u1"}, "title": "t", "duration": 0 if images else 9}
    if images is not None:
        m["images"] = images
    return m


def _noi_tikwm(monkeypatch, muc):
    body = json.dumps({"data": {"videos": muc, "cursor": 5, "hasMore": False}}).encode()

    def fake(url, ua, timeout=25.0, proxy=None):
        return b'href="/challenge/detail/2709669"' if "/tag/" in url else body

    monkeypatch.setattr(he, "_fetch", fake)


ANH2 = ["https://example.invalid/a1.jpeg", "https://example.invalid/a2.jpeg"]


def test_mac_dinh_khong_truyen_loai_giu_het_nhu_cu(monkeypatch):
    _noi_tikwm(monkeypatch, [_muc(ID_VID), _muc(ID_ANH, ANH2)])
    refs = he.enumerate_hashtag("t")
    # Cũ: bài ảnh vẫn ra như một ref video thường (không phân loại), cùng tập id/url.
    assert [r.video_id for r in refs] == [ID_VID, ID_ANH]
    assert all(r.loai == "video" and not r.anh_urls for r in refs)
    assert refs[1].url == f"https://www.tiktok.com/@u1/video/{ID_ANH}"


def test_loai_anh_chi_ra_bai_anh_voi_url_tung_tep(monkeypatch):
    _noi_tikwm(monkeypatch, [_muc(ID_VID), _muc(ID_ANH, ANH2)])
    refs = he.enumerate_hashtag("t", loai="anh")
    assert len(refs) == 1
    r = refs[0]
    assert (r.loai, r.video_id) == ("anh", f"anh-tt-{ID_ANH}")
    assert r.anh_urls == tuple((u,) for u in ANH2) and r.anh_kieu == ("anh", "anh")
    assert r.url == f"https://www.tiktok.com/@u1/video/{ID_ANH}"


def test_loai_video_tuong_minh_bo_bai_anh(monkeypatch):
    _noi_tikwm(monkeypatch, [_muc(ID_VID), _muc(ID_ANH, ANH2)])
    refs = he.enumerate_hashtag("t", loai="video")
    assert [r.video_id for r in refs] == [ID_VID] and refs[0].loai == "video"


def test_loai_ca_hai_giu_ca_hai_va_dem_theo_bai(monkeypatch):
    _noi_tikwm(monkeypatch, [_muc(ID_ANH, ANH2 * 5), _muc(ID_VID)])
    refs = he.enumerate_hashtag("t", loai="ca_hai", max_videos=2)
    assert [r.loai for r in refs] == ["anh", "video"]      # bài 10 ảnh vẫn là MỘT bài trong N
    assert len(refs[0].anh_urls) == 10


def test_bai_anh_co_url_hong_hoac_qua_tran_bi_bo_khi_loc_loai(monkeypatch):
    _noi_tikwm(monkeypatch, [_muc(ID_ANH, [ANH2[0], 5]),
                             _muc("7300000000000000003", [f"https://example.invalid/{i}" for i in range(51)])])
    assert he.enumerate_hashtag("t", loai="anh") == []


# ---------- tiktok_anh ----------

def _html(chi_tiet) -> str:
    goc = {"__DEFAULT_SCOPE__": {"webapp.video-detail": chi_tiet}}
    return f'<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(goc)}</script>'


def _item_anh(n=2):
    return {"id": ID_ANH, "desc": "mo ta", "author": {"uniqueId": "u1"},
            "imagePost": {"images": [{"imageURL": {"urlList": [f"https://example.invalid/{i}a",
                                                                f"https://example.invalid/{i}b"]}}
                                     for i in range(n)]}}


def _noi_html(monkeypatch, html, ghi=None):
    def fake(url, proxy):
        if ghi is not None:
            ghi.append((url, proxy))
        return html
    monkeypatch.setattr(ta, "_tai_html", fake)


def test_tham_bai_doc_url_anh_ke_ca_khi_nguon_la_photo(monkeypatch):
    ghi: list = []
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": _item_anh(3)}}), ghi)
    ref = ta.tham_bai(f"https://www.tiktok.com/@u1/photo/{ID_ANH}", proxy="http://p.invalid:1")
    assert ghi == [(f"https://www.tiktok.com/@_/video/{ID_ANH}", "http://p.invalid:1")]   # luôn thăm /video/
    assert (ref.loai, ref.video_id) == ("anh", f"anh-tt-{ID_ANH}")
    assert len(ref.anh_urls) == 3 and ref.anh_urls[0] == ("https://example.invalid/0a", "https://example.invalid/0b")
    assert ref.anh_kieu == ("anh",) * 3


def test_tham_bai_video_thuong_tra_ref_video(monkeypatch):
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": {
        "id": ID_VID, "author": {"uniqueId": "u1"}}}}))
    ref = ta.tham_bai(ID_VID)
    assert (ref.loai, ref.video_id, ref.anh_urls) == ("video", ID_VID, ())


def test_tham_bai_status_khac_khong_la_loi_phia_nguon(monkeypatch):
    _noi_html(monkeypatch, _html({"statusCode": 10204}))
    with pytest.raises(ta.LoiNguonTikTok) as e:
        ta.tham_bai(ID_ANH)
    assert e.value.ma == 10204 and e.value.loai == "tiktok"


def test_tham_bai_trang_khong_co_du_lieu_va_qua_tran_anh(monkeypatch):
    _noi_html(monkeypatch, "<html></html>")
    with pytest.raises(ta.LoiNguonTikTok):
        ta.tham_bai(ID_ANH)
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": _item_anh(51)}}))
    with pytest.raises(ta.LoiNguonTikTok, match="quá nhiều"):
        ta.tham_bai(ID_ANH)


def test_tham_bai_dau_vao_sai_la_valueerror():
    with pytest.raises(ValueError):
        ta.tham_bai("khong-phai-bai")


def test_tham_lai_tra_ref_moi_none_khi_bai_mat_hoac_thanh_video(monkeypatch):
    cu = VideoRef(video_id=f"anh-tt-{ID_ANH}", url="x", loai="anh")
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": _item_anh()}}))
    assert ta.tham_lai(cu, None).video_id == cu.video_id
    _noi_html(monkeypatch, _html({"statusCode": 10204}))
    assert ta.tham_lai(cu, None) is None
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": {"id": ID_ANH}}}))
    assert ta.tham_lai(cu, None) is None
    with pytest.raises(ValueError):
        ta.tham_lai(VideoRef(video_id="khac", url="x"), None)


def test_http_404_la_loi_phia_nguon(monkeypatch):
    class R:
        status_code, text = 404, ""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    with pytest.raises(ta.LoiNguonTikTok) as e:
        ta._tai_html("https://www.tiktok.com/@_/video/1", None)
    assert e.value.ma == 404


@pytest.mark.parametrize("loai,url_id,ky_vong", [
    ("anh", ID_ANH, 1), ("video", ID_ANH, 0), ("ca_hai", ID_ANH, 1),
])
def test_liet_ke_link_le_theo_loai(monkeypatch, loai, url_id, ky_vong):
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": _item_anh()}}))
    assert len(ta.liet_ke_link_le(f"https://www.tiktok.com/@u1/photo/{url_id}", loai=loai)) == ky_vong


def test_liet_ke_link_le_video_voi_loai_anh_la_rong(monkeypatch):
    _noi_html(monkeypatch, _html({"statusCode": 0, "itemInfo": {"itemStruct": {"id": ID_VID}}}))
    assert ta.liet_ke_link_le(f"https://www.tiktok.com/@u1/video/{ID_VID}", loai="anh") == []


def test_ref_anh_tu_feed_tim_bai_o_moi_chieu_sau():
    feed = {"itemList": [_item_anh(2), {"id": ID_VID}], "data": [{"item": {**_item_anh(1), "id": "7300000000000000009"}}]}
    ra = ta.ref_anh_tu_feed(feed)
    assert set(ra) == {f"anh-tt-{ID_ANH}", "anh-tt-7300000000000000009"}
    assert ra[f"anh-tt-{ID_ANH}"].url == f"https://www.tiktok.com/@u1/photo/{ID_ANH}"


# ---------- scraper (trang giả) ----------

class _TrangGia:
    def __init__(self, photo=(), video=()):
        self.ds = {scraper._PHOTO_LINK_SELECTOR: list(photo), scraper._VIDEO_LINK_SELECTOR: list(video)}

    def eval_on_selector_all(self, sel, _js):
        return self.ds[sel]


def test_collect_links_mac_dinh_van_chi_doc_anchor_video():
    p = _TrangGia(photo=[f"https://www.tiktok.com/@u1/photo/{ID_ANH}"],
                  video=[f"https://www.tiktok.com/@u1/video/{ID_VID}"])
    assert {r.video_id for r in scraper._collect_links(p)} == {ID_VID}


def test_collect_links_anh_lay_ban_feed_co_url_va_anchor_chua_co_url_de_trong():
    feed = ta.ref_anh_tu_feed(_item_anh(2))
    p = _TrangGia(photo=[f"https://www.tiktok.com/@u1/photo/{ID_ANH}", "https://www.tiktok.com/@u1/photo/7300000000000000007"],
                  video=[f"https://www.tiktok.com/@u1/video/{ID_VID}"])
    anh = {r.video_id: r for r in scraper._collect_links(p, "anh", feed)}
    assert set(anh) == {f"anh-tt-{ID_ANH}", "anh-tt-7300000000000000007"}      # không có video, không trùng bài
    assert len(anh[f"anh-tt-{ID_ANH}"].anh_urls) == 2
    assert anh["anh-tt-7300000000000000007"].anh_urls == ()
    ca_hai = scraper._collect_links(p, "ca_hai", feed)
    assert {r.loai for r in ca_hai} == {"anh", "video"} and len(ca_hai) == 3


def test_quet_va_multi_nhan_tham_so_loai():
    import inspect
    for ham in (scraper.quet_tren_trang, scraper.scrape_music_page_multi, scraper.scrape_music_page,
                he.enumerate_hashtag, npy.liet_ke_profile_yt_dlp):
        assert "loai" in inspect.signature(ham).parameters


def test_profile_yt_dlp_loai_anh_roi_ve_trinh_duyet_khong_cham_mang(monkeypatch):
    monkeypatch.setattr(npy, "_mot_luot", lambda *a, **k: pytest.fail("không được gọi yt-dlp"))
    monkeypatch.setattr(npy, "profile_yt_dlp_dang_bat", lambda: True)
    for loai in ("anh", "ca_hai"):
        assert npy.liet_ke_profile_yt_dlp("https://www.tiktok.com/@u1", max_videos=5, loai=loai) is None


@pytest.mark.parametrize("ma", [403, 429])
def test_tham_lai_http_chan_nem_loi_chan_khong_bao_bai_khong_con(monkeypatch, ma):
    """Review PR #125 M2: 403/429 khi thăm lại là TikTok chặn/giới hạn, không phải bài đã gỡ (trả None)."""
    class R:
        status_code, text = ma, ""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    with pytest.raises(ta.LoiChanTikTok, match="TikTok chặn/giới hạn"):
        ta.tham_lai(VideoRef(video_id=f"anh-tt-{ID_ANH}", url="x", loai="anh"), None)


def test_tham_lai_trang_chan_khong_co_du_lieu_bai_la_loi_chan(monkeypatch):
    _noi_html(monkeypatch, "<html><body>Please wait...</body></html>")
    with pytest.raises(ta.LoiChanTikTok):
        ta.tham_lai(VideoRef(video_id=f"anh-tt-{ID_ANH}", url="x", loai="anh"), None)


@pytest.mark.parametrize("ma", [404, 410])
def test_tham_lai_404_410_van_la_bai_khong_con(monkeypatch, ma):
    class R:
        status_code, text = ma, ""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert ta.tham_lai(VideoRef(video_id=f"anh-tt-{ID_ANH}", url="x", loai="anh"), None) is None
