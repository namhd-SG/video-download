"""Facebook page ảnh: bóc nút Photo theo đường dẫn container, quét một lượt (không cuộn), nguồn theo loại, thăm lại URL.
Fixture JSON tự dựng (id/URL giả), không mạng, không trình duyệt.

Đột biến (tự áp rồi hoàn nguyên bằng phép thay ngược; chạy từ gốc worktree):
  1) Enumerator FB bỏ qua `loai` (luôn nhánh video) ⇒ `test_liet_ke_anh_dung_tab_photos_va_ra_ref_anh` ĐỎ:
       sed -i '' 's/                if loai == "anh":/                if False:/' src/tiktok_music_downloader/nguon_facebook_trang.py
     hoàn nguyên: sed -i '' 's/                if False:/                if loai == "anh":/' <cùng tệp>
  2) Bỏ ràng buộc container: trong `boc_nut_anh` thay `_nut_trong_collection(col)` bằng hàm trả MỌI dict trong cây con của
     `o` ⇒ `test_nut_photo_ngoai_container_pageitems_bi_loai` ĐỎ; hoàn nguyên bằng sửa ngược ⇒ XANH.
"""
from __future__ import annotations

import json

import pytest

from fb_khung_gia import TUONG, PhienGia, TrangGia

from tiktok_music_downloader import fb_quet_cuon as qc
from tiktok_music_downloader import fb_xhr_phan_tich as ph
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import nguon_facebook_trang as nf
from tiktok_music_downloader.nguon import FacebookTrang, chon_nguon, chon_nguon_moi_loai, loai_ho_tro_cua
from tiktok_music_downloader.utils import STOP_ALREADY_OWNED, STOP_COMPLETE, STOP_FB_CHAN_DANG_NHAP, STOP_SOURCE_EMPTY, STOP_STALLED, VideoRef

URL_ANH = "https://www.facebook.com/ten-page-gia/photos"


def fid(i: int) -> str:
    return f"{9000000000000 + i}"


def uri(i: int) -> str:
    return f"https://cdn.example.invalid/anh-gia-{i}.jpg"


def nut_anh(i: int, **them) -> dict:
    return {"__typename": "Photo", "id": fid(i), "viewer_image": {"uri": uri(i)}, **them}


def script_anh(so: int, *, bat_dau: int = 0) -> str:
    """Cấu trúc đo được: data.node.all_collections.nodes[].style_renderer.collection.pageItems.edges[].node.node."""
    edges = [{"node": {"node": nut_anh(i)}} for i in range(bat_dau, bat_dau + so)]
    col = {"style_renderer": {"collection": {"pageItems": {"edges": edges}}}}
    return json.dumps({"data": {"node": {"all_collections": {"nodes": [col]}}}})


# ---------------------------------------------------------------------------------------------- bóc nút

def test_boc_nut_anh_ra_du_so_nut_trong_container_va_khong_trung():
    goc = [json.loads(script_anh(8)), json.loads(script_anh(8))]       # cùng 8 nút lặp (đã đo) ⇒ chỉ giữ 8
    nut = ph.boc_nut_anh(goc)
    assert [n.ma for n in nut] == [fid(i) for i in range(8)] and nut[0].uri == uri(0)


def test_nut_photo_ngoai_container_pageitems_bi_loai():
    ngoai = {"comment": {"attachment": nut_anh(50)}, "other": {"pageItems": {"edges": [{"node": {"node": nut_anh(51)}}]}},
             "all_collections": {"nodes": [{"style_renderer": {"collection": {"khac": {"edges": [
                 {"node": {"node": nut_anh(52)}}]}}}}]}}
    goc = [json.loads(script_anh(2)), ngoai]
    assert [n.ma for n in ph.boc_nut_anh(goc)] == [fid(0), fid(1)]


@pytest.mark.parametrize("nut", [
    {"__typename": "Video", "id": fid(1), "viewer_image": {"uri": "https://x.invalid/a.jpg"}},
    {"__typename": "Photo", "id": "abc", "viewer_image": {"uri": "https://x.invalid/a.jpg"}},
    {"__typename": "Photo", "id": fid(1), "viewer_image": {"uri": "http://x.invalid/a.jpg"}},
    {"__typename": "Photo", "id": fid(1)},
])
def test_nut_sai_hinh_bi_bo(nut):
    col = {"style_renderer": {"collection": {"pageItems": {"edges": [{"node": {"node": nut}}]}}}}
    assert ph.boc_nut_anh([{"all_collections": {"nodes": [col]}}]) == []


def test_tab_videos_khong_doi_va_khong_bi_nut_anh_lan():
    from fb_khung_gia import nut, script_videos
    goc = ph.doc_script_json([script_videos([nut("12345678901")])])
    assert [n.ma for n in ph.boc_nut(goc, "videos").nut] == ["12345678901"]
    assert ph.boc_nut_anh(goc) == []


# ---------------------------------------------------------------------------------------------- quét một lượt

def chay(trang, n, co=()):
    skip = []
    kq = qc.quet_anh(trang, URL_ANH, max_videos=n, already_have=lambda ids: {i for i in ids if i in set(co)},
                     on_skip=skip.append, ngu=lambda s: None)
    kq.da_skip = skip
    return kq


def test_quet_anh_du_n_cat_dung_va_ref_dung_hinh():
    t = TrangGia(scripts=[script_anh(8)])
    kq = chay(t, 5)
    assert kq.ly_do == STOP_COMPLETE and len(kq.refs) == 5 and t.so_cuon == 0 and t.da_mo == [URL_ANH]
    r = kq.refs[0]
    assert (r.loai, r.video_id, r.anh_urls, r.anh_kieu) == ("anh", f"anh-fbp-{fid(0)}", ((uri(0),),), ("anh",))
    assert r.url == f"https://www.facebook.com/photo/?fbid={fid(0)}"


def test_quet_anh_xin_nhieu_hon_thay_co_hop_dang_nhap_dung_fb_chan_dang_nhap():
    kq = chay(TrangGia(scripts=[script_anh(8)], dom=TUONG), 20)
    assert kq.ly_do == STOP_FB_CHAN_DANG_NHAP and kq.co_tuong and len(kq.refs) == 8


def test_quet_anh_thieu_khong_hop_thoai_stalled_da_co_va_rong():
    assert chay(TrangGia(scripts=[script_anh(3)]), 9).ly_do == STOP_STALLED
    t = TrangGia(scripts=[script_anh(2)])
    kq = chay(t, 9, co=[f"anh-fbp-{fid(0)}", f"anh-fbp-{fid(1)}"])
    assert kq.ly_do == STOP_ALREADY_OWNED and kq.so_da_co == 2 and len(kq.da_skip) == 2 and kq.refs == []
    assert chay(TrangGia(scripts=[]), 9).ly_do == STOP_SOURCE_EMPTY


def test_quet_anh_da_co_khong_tinh_vao_n():
    kq = chay(TrangGia(scripts=[script_anh(8)]), 3, co=[f"anh-fbp-{fid(0)}"])
    assert [r.video_id for r in kq.refs] == [f"anh-fbp-{fid(i)}" for i in (1, 2, 3)]


def test_quet_anh_429_khi_dieu_huong():
    assert chay(TrangGia(scripts=[script_anh(8)], nav=429), 3).chan_429


# ---------------------------------------------------------------------------------------------- nguồn theo loại

def liet_ke(monkeypatch, url, loai, trang, n=5):
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(trang))
    monkeypatch.setattr(qc.time, "sleep", lambda s: None)
    stop = []
    refs = FacebookTrang().liet_ke(url, max_videos=n, already_have=lambda ids: set(), on_skip=lambda r: None,
                                   on_stop=stop.append, loai=loai)
    return refs, stop


def test_liet_ke_anh_dung_tab_photos_va_ra_ref_anh(monkeypatch):
    for url in ("https://www.facebook.com/ten-page-gia", URL_ANH):
        t = TrangGia(scripts=[script_anh(8)])
        refs, stop = liet_ke(monkeypatch, url, "anh", t)
        assert t.da_mo == [URL_ANH] and len(refs) == 5 and {r.loai for r in refs} == {"anh"} and stop == [STOP_COMPLETE]


def test_liet_ke_video_khong_doi_tren_page_tran(monkeypatch):
    t = TrangGia()
    refs, _ = liet_ke(monkeypatch, "https://www.facebook.com/ten-page-gia", "video", t)
    assert t.da_mo == ["https://www.facebook.com/ten-page-gia/videos"] and refs == []


def test_liet_ke_ca_hai_va_photos_khi_xin_video_bi_tu_choi(monkeypatch):
    with pytest.raises(ValueError):
        liet_ke(monkeypatch, "https://www.facebook.com/ten-page-gia", "ca_hai", TrangGia())
    with pytest.raises(ValueError):
        liet_ke(monkeypatch, URL_ANH, "video", TrangGia())


def test_chon_nguon_tab_photos_chi_nhan_khi_anh_ca_hai_la_400():
    assert isinstance(chon_nguon(URL_ANH, "anh"), FacebookTrang)
    assert chon_nguon(URL_ANH, "video") is None and chon_nguon(URL_ANH, "ca_hai") is None
    assert isinstance(chon_nguon_moi_loai(URL_ANH), FacebookTrang)
    tran = "https://www.facebook.com/ten-page-gia"
    assert isinstance(chon_nguon(tran, "video"), FacebookTrang) and isinstance(chon_nguon(tran, "anh"), FacebookTrang)
    assert chon_nguon(tran, "ca_hai") is None
    assert loai_ho_tro_cua(FacebookTrang(), "https://www.facebook.com/ten-page-gia/videos") == frozenset({"video"})


# ---------------------------------------------------------------------------------------------- thăm lại URL

def ref_cu():
    return VideoRef(video_id=f"anh-fbp-{fid(3)}", url="u", loai="anh", anh_urls=(("het-han",),), anh_kieu=("anh",))


def test_tham_lai_lay_uri_moi_tu_trang_photo(monkeypatch):
    moi = {"data": {"x": {"__typename": "Photo", "id": fid(3), "image": {"uri": "https://cdn.example.invalid/moi.jpg"},
                          "owner": {"id": "1"}}}}
    t = TrangGia(scripts=[json.dumps(moi)])
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(t))
    r = nf.tham_lai(ref_cu(), None)
    assert r.anh_urls == (("https://cdn.example.invalid/moi.jpg",),) and r.video_id == ref_cu().video_id
    assert t.da_mo == [f"https://www.facebook.com/photo/?fbid={fid(3)}"]


def test_tham_lai_khong_thay_hoac_loi_hoac_429_hoac_ref_la_tra_none(monkeypatch):
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(TrangGia(scripts=[script_anh(1)])))     # nút id khác ⇒ không thấy
    assert nf.tham_lai(ref_cu(), None) is None
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(loi=RuntimeError("https://x.invalid/bi-mat")))
    assert nf.tham_lai(ref_cu(), None) is None
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(TrangGia(nav=429)))
    assert nf.tham_lai(ref_cu(), None) is None
    assert nf.tham_lai(VideoRef(video_id="fbv-1", url="u"), None) is None
