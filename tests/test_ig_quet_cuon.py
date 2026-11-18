"""Vòng cuộn Instagram trên trang giả: đủ N mới, chạy lại 0 trùng, đào qua bài đã có, carousel không tải, trần cuộn,
và MỖI dấu mất phiên dừng job (không trả video, không "xong" rỗng). Không trình duyệt, không mạng."""
from __future__ import annotations

import pytest

from ig_khung_gia import (TrangGia, URL_AUDIO, URL_PROFILE, carousel, dot, ma, nhieu_dot, node, thanh_audio,
                          thanh_gia, xhr)
from tiktok_music_downloader import ig_quet_cuon as q
from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader.utils import (STOP_ALREADY_OWNED, STOP_COMPLETE, STOP_HET_THOI_GIAN, STOP_HET_VONG,
                                           STOP_SOURCE_EMPTY, STOP_STALLED)


def chay(trang, *, n=10, da_co=(), audio=False, **kw):
    ngu, khoang, bo_qua = [], [], []

    def ngau_nhien(a, b):
        khoang.append((a, b))
        return (a + b) / 2

    kq = q.quet(trang, URL_AUDIO if audio else URL_PROFILE, la_audio=audio, max_videos=n,
                already_have=lambda ids: {i for i in ids if i in set(da_co)}, on_skip=bo_qua.append,
                ngu=ngu.append, ngau_nhien=ngau_nhien, **kw)
    kq.ngu, kq.khoang, kq.bo_qua = ngu, khoang, bo_qua
    return kq


def test_profile_n10_du_moi_va_cat_dung_n_ref_mang_id_ig_va_link_reel():
    t = TrangGia(nhieu_dot(5, 4))
    kq = chay(t, n=10)
    assert len(kq.refs) == 10 and kq.ly_do == STOP_COMPLETE and kq.mat_phien is None
    assert kq.refs[0].video_id == "ig-" + ma(0)
    assert kq.refs[0].url == f"https://www.instagram.com/reel/{ma(0)}/"
    assert t.da_mo == [URL_PROFILE] and t.so_cuon == 2          # dừng ngay khi đủ, không cuộn thừa


def test_nghi_cuon_dung_khoang_2_5_den_4_va_cho_ban_dau_6s():
    kq = chay(TrangGia(nhieu_dot(5, 4)), n=10)
    assert kq.ngu[0] == q.CHO_BAN_DAU_GIAY == 6.0
    assert kq.khoang == [(2.5, 4.0)] * 2 and kq.ngu[1:] == [3.25, 3.25]


def test_hashtag_n20_du_moi_khi_nhieu_anh():
    """Hashtag: ~1/8 mã là video; N=20 phải cuộn qua nhiều đợt toàn ảnh/carousel."""
    kich_ban = []
    for d in range(30):
        nodes = [node(ma(d * 2 + k), 2) for k in range(2)] + [node(ma(d * 14 + k, "I"), 1) for k in range(12)]
        kich_ban.append(dot(nodes + [carousel(ma(d, "C"))], con_trang=True))
    kq = chay(TrangGia(kich_ban), n=20)
    assert len(kq.refs) == 20 and kq.so_carousel >= 9 and kq.ly_do == STOP_COMPLETE
    assert all(r.video_id.startswith("ig-V") for r in kq.refs)           # không ảnh, không carousel


def test_link_3_hashtag_ra_dung_6_video_trong_51_ma():
    """Bước 0 link 3 (#emiuquan2): 51 mã/3 đợt = 6 video + 45 carousel (1 có con video) ⇒ đúng 6 video, 0 bị lẫn."""
    car = [carousel(ma(i, "C"), co_video=i == 0) for i in range(45)]
    vid = [node(ma(i)) for i in range(6)]
    dots = [dot(vid[:2] + car[:15]), dot(vid[2:5] + car[15:29]), dot(vid[5:] + car[29:], con_trang=False)]
    kq = chay(TrangGia(dots), n=50)
    assert [r.video_id for r in kq.refs] == ["ig-" + ma(i) for i in range(6)] and kq.so_carousel == 45


def test_chay_lai_0_trung_nho_already_have():
    lan1 = chay(TrangGia(nhieu_dot(4, 5)), n=10)
    da_co = {r.video_id for r in lan1.refs}
    lan2 = chay(TrangGia(nhieu_dot(8, 5)), n=10, da_co=da_co)       # cùng nguồn + thêm bài mới phía sau
    ids2 = {r.video_id for r in lan2.refs}
    assert len(lan2.refs) == 10 and ids2.isdisjoint(da_co)            # 0 trùng với lượt trước
    assert lan2.so_da_co == 10 and len(lan2.bo_qua) == 10             # đã có ⇒ `on_skip` (để lại dấu nguồn)


def test_dao_qua_bai_da_co_toi_khi_du_n_moi():
    t = TrangGia(nhieu_dot(6, 4))
    da_co = {"ig-" + ma(i) for i in range(8)}                         # 8 bài đầu thư viện đã có
    kq = chay(t, n=10, da_co=da_co)
    assert len(kq.refs) == 10 and kq.so_da_co == 8
    assert [r.video_id for r in kq.refs] == ["ig-" + ma(i) for i in range(8, 18)]


def test_carousel_khong_tai_chi_dem_so_ke_ca_carousel_co_video():
    nodes = [node(ma(1)), carousel(ma(2)), carousel(ma(3), co_video=True), node(ma(4), 1), node(ma(5))]
    kq = chay(TrangGia([dot(nodes, con_trang=False)]), n=10)
    assert [r.video_id for r in kq.refs] == ["ig-" + ma(1), "ig-" + ma(5)] and kq.so_carousel == 2


def test_het_trang_khi_chua_du_n_la_stalled_va_van_tra_video():
    kq = chay(TrangGia(nhieu_dot(2, 3)), n=10)                        # 6 video, has_next_page=False ở đợt cuối
    assert len(kq.refs) == 6 and kq.ly_do == STOP_STALLED


def test_het_trang_ma_chi_co_bai_da_co_la_already_owned():
    t = TrangGia([dot([node(ma(1)), node(ma(2))], con_trang=False)])
    kq = chay(t, n=5, da_co={"ig-" + ma(1), "ig-" + ma(2)})
    assert kq.refs == [] and kq.ly_do == STOP_ALREADY_OWNED and kq.mat_phien is None


def test_nguon_co_xhr_nhung_khong_co_video_la_source_empty_khong_phai_mat_phien():
    kq = chay(TrangGia([dot([node(ma(1), 1), carousel(ma(2))], con_trang=False)]), n=5)
    assert kq.refs == [] and kq.ly_do == STOP_SOURCE_EMPTY and kq.so_carousel == 1


def test_tran_cuon_dung_dung_so_lan_va_bao_het_vong():
    """ĐỘT BIẾN: bỏ trần cuộn ⇒ ĐỎ (nguồn vô tận không dừng)."""
    t = TrangGia([dot([node(ma(i))], con_trang=True) for i in range(500)])
    kq = chay(t, n=400, tran_cuon=7)
    assert t.so_cuon == 7 and kq.ly_do == STOP_HET_VONG and len(kq.refs) == 8


def test_tran_thoi_gian_dung_voi_het_thoi_gian():
    gio = iter(range(0, 10_000, 100))
    t = TrangGia([dot([node(ma(i))], con_trang=True) for i in range(50)])
    kq = chay(t, n=40, max_seconds=250, dong_ho=lambda: float(next(gio)))
    assert kq.ly_do == STOP_HET_THOI_GIAN and 1 <= len(kq.refs) < 40


def test_4_lan_cuon_lien_khong_xhr_moi_dung_la_stalled_khong_mat_phien_khi_da_co_video():
    t = TrangGia([dot([node(ma(1))], con_trang=True)])               # chỉ đợt đầu có dữ liệu, sau đó im
    kq = chay(t, n=10)
    assert len(kq.refs) == 1 and kq.mat_phien is None and kq.ly_do == STOP_STALLED
    assert t.so_cuon == q.SO_CUON_LIEN_KHONG_XHR


def test_audio_phan_trang_max_id_tien_to_for_hijack_bi_boc():
    """ĐỘT BIẾN: bỏ bóc `for (;;);` ⇒ audio ra 0 video ⇒ ĐỎ."""
    dots = [[xhr(thanh_audio([node(ma(d * 12 + i)) for i in range(12)], con_trang=d < 6, max_id=f"M{d}"))]
            for d in range(7)]
    kq = chay(TrangGia(dots, url_cuoi=URL_AUDIO), n=30, audio=True)
    assert len(kq.refs) == 30 and kq.ly_do == STOP_COMPLETE
    full = chay(TrangGia(dots, url_cuoi=URL_AUDIO), n=200, audio=True)
    assert len(full.refs) == 84 and full.ly_do == STOP_STALLED          # 7 trang × 12, 0 trùng
    assert len({r.video_id for r in full.refs}) == 84


# --------------------------------------------------- mất phiên: dừng, KHÔNG trả video, từng dấu

def _kiem_mat_phien(kq, ma_dau):
    assert kq.mat_phien == ma_dau and kq.refs == [], "mất phiên phải trả RỖNG kèm mã dấu"


def test_mat_phien_dau_1_url_cuoi_dang_nhap_giua_luot_cuon():
    t = TrangGia(nhieu_dot(5, 4), url_theo_lan={1: "https://www.instagram.com/accounts/login/?next=/x/"})
    _kiem_mat_phien(chay(t, n=50), ph.MP_URL_DANG_NHAP)


def test_mat_phien_dau_1_url_cuoi_challenge_ngay_luc_mo():
    t = TrangGia([], url_cuoi="https://www.instagram.com/challenge/?next=x")
    _kiem_mat_phien(chay(t, n=5), ph.MP_URL_DANG_NHAP)


def test_mat_phien_dau_2_xhr_nho():
    t = TrangGia([[xhr('{"errors":[]}')]])
    _kiem_mat_phien(chay(t, n=5), ph.MP_XHR_NHO)


def test_mat_phien_dau_2_xhr_errors_1675002():
    import json
    loi = xhr(json.dumps({"errors": [{"message": "Unauthorized logged out query.", "code": 1675002}],
                          "pad": "x" * 2000}))
    _kiem_mat_phien(chay(TrangGia([[loi]]), n=5), ph.MP_XHR_LOI)


@pytest.mark.parametrize("audio", [False, True])
def test_mat_phien_dau_3_dom_ke_ca_khi_van_ra_du_lieu(audio):
    dom = ph.DauDom(co_nut_dang_nhap=True)
    t = TrangGia([[xhr(thanh_audio([node(ma(i)) for i in range(12)]))]] if audio else nhieu_dot(3, 12),
                 dom=dom, url_cuoi=URL_AUDIO if audio else URL_PROFILE)
    _kiem_mat_phien(chay(t, n=5, audio=audio), ph.MP_DOM_DANG_NHAP)


def test_mat_phien_dau_4_khong_xhr_dich_sau_tai_va_cuon_trang_thuong():
    t = TrangGia([])
    kq = chay(t, n=5)
    _kiem_mat_phien(kq, ph.MP_KHONG_XHR_DICH)
    assert t.so_cuon == q.SO_CUON_CHO_XHR                             # kết luận sớm, không cuộn hết trần


def test_dau_4_khong_ap_cho_audio_0_xhr_la_source_empty_khong_phai_mat_phien():
    kq = chay(TrangGia([], url_cuoi=URL_AUDIO), n=5, audio=True)
    assert kq.mat_phien is None and kq.ly_do == STOP_SOURCE_EMPTY


def test_mat_phien_dau_5_http_429_tren_xhr_giua_luot_va_tren_dieu_huong():
    t = TrangGia(nhieu_dot(3, 4)[:1] + [[xhr("", status=429)]])
    _kiem_mat_phien(chay(t, n=50), ph.MP_HTTP_429)
    _kiem_mat_phien(chay(TrangGia([], nav=429), n=5), ph.MP_HTTP_429)


def test_mat_phien_giua_chung_vut_bo_video_da_gom_khong_xong_mot_phan():
    """Đã gom 4 video rồi mới thấy dấu ⇒ vẫn RỖNG + mã (job `failed`, không tải nửa vời rồi báo xong)."""
    t = TrangGia(nhieu_dot(5, 4), url_theo_lan={1: "https://www.instagram.com/accounts/login/"})
    kq = chay(t, n=50)
    assert kq.refs == [] and kq.mat_phien == ph.MP_URL_DANG_NHAP
