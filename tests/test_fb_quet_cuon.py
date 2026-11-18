"""Vòng cuộn Facebook page trên trang GIẢ kịch bản: đủ N mới, lọc `already_have`, tường đăng nhập, hộp thoại đóng được,
lọc chủ page, trần thời lượng, các điều kiện dừng, nhịp nghỉ. Không mạng, không trình duyệt."""
from __future__ import annotations

import pytest

from fb_khung_gia import (
    CHU_LA, HOP_THOAI_DONG_DUOC, TUONG, URL_REELS, URL_VIDEOS, TrangGia, dot, ma, media_reel, nhieu_dot, nut, script_reels,
    script_videos, xhr, than_videos,
)

from tiktok_music_downloader import fb_quet_cuon as qc
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED, STOP_COMPLETE, STOP_FB_CHAN_DANG_NHAP, STOP_HET_THOI_GIAN, STOP_HET_VONG, STOP_SOURCE_EMPTY,
    STOP_STALLED,
)

TRAN = 900


def chay(trang, *, tab="videos", n=10, co=(), tran_cuon=qc.TRAN_LUOT_CUON, max_seconds=None, dong_ho=None, nghi=None,
         tran_tl=TRAN):
    da_skip = []
    kq = qc.quet(trang, URL_REELS if tab == "reels" else URL_VIDEOS, tab=tab, max_videos=n,
                 already_have=lambda ids: {i for i in ids if i in set(co)}, on_skip=da_skip.append,
                 tran_thoi_luong_giay=tran_tl, tran_cuon=tran_cuon, max_seconds=max_seconds,
                 ngu=nghi if nghi is not None else (lambda s: None), ngau_nhien=lambda a, b: a, dong_ho=dong_ho)
    kq.da_skip = da_skip
    return kq


# ------------------------------------------------------------------------------- đủ N, id và URL tải

def test_videos_n10_du_moi_cat_dung_n_ref_id_fbv_va_url_watch():
    t = TrangGia(nhieu_dot(5, 4))
    kq = chay(t, n=10)
    assert len(kq.refs) == 10 and kq.ly_do == STOP_COMPLETE and kq.so_cuon == 2
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in range(10)]
    assert kq.refs[0].url == f"https://www.facebook.com/watch/?v={ma(0)}"
    assert t.da_mo == [URL_VIDEOS]


def test_reels_url_tai_la_reel_ma_va_doc_script_html_mot_lan():
    t = TrangGia(scripts=[script_reels([media_reel(ma(i)) for i in range(3)])], kich_ban=nhieu_dot(3, 3, tu=3, reels=True))
    kq = chay(t, tab="reels", n=7)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in range(7)]
    assert kq.refs[0].url == f"https://www.facebook.com/reel/{ma(0)}"
    assert t.so_doc_script == 1                                      # HTML lúc tải chỉ đọc ở lượt đầu


def test_html_luc_tai_va_xhr_cong_lai_khong_trung_ma():
    t = TrangGia(scripts=[script_videos([nut(ma(0)), nut(ma(1))])], kich_ban=[[], dot([nut(ma(1)), nut(ma(2))])])
    kq = chay(t, n=10)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in range(3)]


def test_nhip_cho_6s_sau_khi_mo_va_nghi_cuon_2_5_den_4s():
    ngu, seen = [], []
    t = TrangGia(nhieu_dot(4, 2))
    qc.quet(t, URL_VIDEOS, tab="videos", max_videos=6, already_have=lambda ids: set(), on_skip=lambda r: None,
            tran_thoi_luong_giay=TRAN, ngu=ngu.append, ngau_nhien=lambda a, b: (seen.append((a, b)), a)[1])
    assert ngu[0] == qc.CHO_BAN_DAU_GIAY == 6.0
    assert set(seen) == {(2.5, 4.0)} and len(seen) == t.so_cuon == 2


# ------------------------------------------------------------------------------- lọc already_have (ĐỘT BIẾN i)

def test_already_have_loc_tung_dot_roi_dao_qua_toi_khi_du_n_moi():
    """ĐỘT BIẾN (i): bỏ lọc `already_have` ⇒ ĐỎ (ref đã có lọt vào kết quả, `on_skip` không được gọi)."""
    co = ["fbv-" + ma(i) for i in range(6)]
    kq = chay(TrangGia(nhieu_dot(5, 4)), n=5, co=co)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in range(6, 11)]
    assert kq.so_da_co == 6 and [r.video_id for r in kq.da_skip] == co and kq.ly_do == STOP_COMPLETE


def test_chay_lai_0_trung_nho_already_have():
    t1 = chay(TrangGia(nhieu_dot(3, 2)), n=4)
    co = [r.video_id for r in t1.refs]
    t2 = chay(TrangGia(nhieu_dot(3, 2)), n=4, co=co)
    assert {r.video_id for r in t2.refs}.isdisjoint(co) and len(t2.refs) == 2 and t2.ly_do == STOP_STALLED


def test_het_trang_ma_chi_co_bai_da_co_la_already_owned():
    co = ["fbv-" + ma(i) for i in range(4)]
    kq = chay(TrangGia(nhieu_dot(2, 2)), n=5, co=co)
    assert kq.refs == [] and kq.so_da_co == 4 and kq.ly_do == STOP_ALREADY_OWNED


# ------------------------------------------------------------------------------- tường đăng nhập (ĐỘT BIẾN ii)

def test_16_ma_deu_da_co_cong_tuong_la_fb_chan_dang_nhap_khong_phai_already_owned():
    """Ca then chốt: 16 mã HTML đều đã có trong thư viện + hộp thoại không đóng được ⇒ `fb_chan_dang_nhap`.
    ĐỘT BIẾN (ii): bỏ phát hiện tường ⇒ rơi về `already_owned` / dừng im ⇒ ĐỎ."""
    ids = [ma(i) for i in range(16)]
    t = TrangGia(scripts=[script_videos([nut(m) for m in ids])], dom=TUONG)
    kq = chay(t, n=30, co=["fbv-" + m for m in ids])
    assert kq.refs == [] and kq.so_da_co == 16
    assert kq.ly_do == STOP_FB_CHAN_DANG_NHAP == "fb_chan_dang_nhap" and kq.co_tuong
    assert t.so_cuon == 0                                            # tường ⇒ dừng ngay, không cuộn thêm


def test_tuong_khi_da_co_vai_ma_moi_tra_ve_so_da_lay_va_nhan_tuong():
    t = TrangGia(scripts=[script_videos([nut(ma(i)) for i in range(16)])], dom_theo_lan={0: TUONG, 1: TUONG})
    kq = chay(t, n=30)
    assert len(kq.refs) == 16 and kq.ly_do == STOP_FB_CHAN_DANG_NHAP


def test_tuong_sau_vai_luot_cuon_khi_hop_thoai_dau_het_nut_dong():
    t = TrangGia(nhieu_dot(5, 3), dom_theo_lan={2: TUONG})
    kq = chay(t, n=30)
    assert len(kq.refs) == 9 and kq.ly_do == STOP_FB_CHAN_DANG_NHAP and t.so_cuon == 2


def test_tuong_nhung_da_du_n_thi_hoan_tat_khong_bao_tuong():
    kq = chay(TrangGia(nhieu_dot(3, 5), dom=TUONG), n=5)
    assert len(kq.refs) == 5 and kq.ly_do == STOP_COMPLETE and not kq.co_tuong


def test_hop_thoai_dau_co_nut_dong_bam_mot_lan_roi_di_tiep():
    t = TrangGia(nhieu_dot(4, 3), dom_theo_lan={0: HOP_THOAI_DONG_DUOC})      # chỉ lượt đầu có hộp thoại, đóng được
    kq = chay(t, n=10)
    assert t.so_bam_dong == 1 and kq.so_bam_dong == 1
    assert len(kq.refs) == 10 and kq.ly_do == STOP_COMPLETE and not kq.co_tuong


def test_hop_thoai_co_nut_dong_hien_lai_hoai_van_la_tuong_sau_tran_lan_bam():
    t = TrangGia(nhieu_dot(40, 1), dom=HOP_THOAI_DONG_DUOC)
    kq = chay(t, n=30)
    assert t.so_bam_dong == qc.TRAN_LAN_BAM_DONG and kq.ly_do == STOP_FB_CHAN_DANG_NHAP


def test_hop_thoai_roi_tuong_dung_hop_thoai_dau_dong_duoc_hop_thoai_hai_khong_nut_dong():
    """Đúng chuỗi đo ở bước 0: hộp thoại 1 có X (bấm), hộp thoại 2 không X (tường)."""
    t = TrangGia(nhieu_dot(10, 4), dom_theo_lan={0: HOP_THOAI_DONG_DUOC, 2: TUONG})
    kq = chay(t, n=30)
    assert t.so_bam_dong == 1 and kq.ly_do == STOP_FB_CHAN_DANG_NHAP and len(kq.refs) == 12


# ------------------------------------------------------------------------------- 0 mã / dừng khác

def test_khong_ma_khong_tuong_la_source_empty_nasa_reels():
    kq = chay(TrangGia([]), tab="reels", n=10)
    assert kq.refs == [] and kq.ly_do == STOP_SOURCE_EMPTY and kq.so_cuon == qc.SO_LUOT_LIEN_KHONG_MOI - 1   # lượt 0..5 = 6 lượt rỗng


def test_het_trang_khi_chua_du_n_la_stalled_va_van_tra_video():
    kq = chay(TrangGia(nhieu_dot(2, 3)), n=20)
    assert len(kq.refs) == 6 and kq.ly_do == STOP_STALLED and kq.so_cuon == 1


def test_6_luot_lien_khong_them_ma_dung_la_stalled():
    t = TrangGia([dot([nut(ma(0)), nut(ma(1))])] + [[xhr("{}")]] * 20)
    t.kich_ban[0] = dot([nut(ma(0)), nut(ma(1))], con_trang=True)
    kq = chay(t, n=10)
    assert len(kq.refs) == 2 and kq.ly_do == STOP_STALLED
    assert kq.so_cuon == qc.SO_LUOT_LIEN_KHONG_MOI == 6               # lượt 0 có mã mới; lượt 1..6 không ⇒ dừng ở lượt 6


def test_tran_cuon_dung_dung_so_lan_va_bao_het_vong():
    kq = chay(TrangGia([dot([nut(ma(i))], con_trang=True) for i in range(100)]), n=50, tran_cuon=5)
    assert kq.ly_do == STOP_HET_VONG and kq.so_cuon == 5 and len(kq.refs) == 6


def test_tran_thoi_gian_dung_voi_het_thoi_gian():
    gio = iter(range(0, 1000, 10))
    kq = chay(TrangGia([dot([nut(ma(i))], con_trang=True) for i in range(100)]), n=50, max_seconds=25,
              dong_ho=lambda: float(next(gio)))
    assert kq.ly_do == STOP_HET_THOI_GIAN and 0 < len(kq.refs) < 50


# ------------------------------------------------------------------------------- lọc chủ page

def test_owner_la_bi_bo_va_dem_so_la_ke_ca_trong_container():
    """Nút nằm trong container nhưng owner KHÁC chủ page (đa số) ⇒ bỏ, đếm `so_la`."""
    t = TrangGia(scripts=[script_videos([nut(ma(0)), nut(ma(1), CHU_LA), nut(ma(2)), nut(ma(3)), nut(ma(4), CHU_LA)])])
    kq = chay(t, n=10)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in (0, 2, 3)] and kq.so_la == 2


def test_video_lac_o_manh_defer_khong_vao_ket_qua_vi_ngoai_container():
    t = TrangGia([[xhr(than_videos([nut(ma(0)), nut(ma(1))], con_trang=False))]])
    kq = chay(t, n=10)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(0), "fbv-" + ma(1)] and kq.so_la == 0


# ------------------------------------------------------------------------------- thời lượng

def test_thoi_luong_co_san_vuot_tran_bo_con_trong_tran_giu_va_thieu_thi_la_short():
    t = TrangGia(scripts=[script_videos([nut(ma(0), giay=60), nut(ma(1), giay=TRAN + 1), nut(ma(2), giay=TRAN), nut(ma(3))])])
    kq = chay(t, n=10)
    assert [r.video_id for r in kq.refs] == ["fbv-" + ma(i) for i in (0, 2, 3)] and kq.so_qua_dai == 1
    assert [(r.duration, r.la_short) for r in kq.refs] == [(60, False), (TRAN, False), (None, True)]


# ------------------------------------------------------------------------------- 429

def test_http_429_khi_mo_trang_khong_tra_video_va_khong_cuon():
    t = TrangGia(nhieu_dot(3, 3), nav=429)
    kq = chay(t, n=5)
    assert kq.chan_429 and kq.refs == [] and t.so_cuon == 0


def test_http_429_tren_xhr_giua_luot_vut_bo_video_da_gom():
    t = TrangGia([dot([nut(ma(0)), nut(ma(1))]), [xhr("", status=429)]])
    kq = chay(t, n=10)
    assert kq.chan_429 and kq.refs == []
