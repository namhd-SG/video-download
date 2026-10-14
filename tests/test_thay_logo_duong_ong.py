"""Lõi thay logo trên clip TỔNG HỢP có ground truth: đường ống chạy đúng, và mỗi lớp an toàn có ĐỘT BIẾN chứng minh nó đang chặn.

Mẫu mỗi test an toàn: (1) có lớp ⇒ không khung nguy hiểm nào được render; (2) gỡ đúng lớp đó bằng monkeypatch ⇒ khung nguy hiểm
LỌT vào danh sách render. Vế (2) là bằng chứng fixture có sức phân định — thiếu nó thì vế (1) xanh cũng không nói lên gì.
"""
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

import cv2  # noqa: E402
from thay_logo_tong_hop import tam_lech, tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import cong, dinh_vi as dinh_vi_mod, duong_ong, mau as mau_mod  # noqa: E402
from tiktok_music_downloader.thay_logo.box_moi import BoxMoi  # noqa: E402


def _vet(clip):
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi())
    assert len(kq.vet) == 1
    return kq.vet[0]


def test_watermark_chu_troi_duoc_dinh_vi_va_render_dung_cho():
    clip = tao_clip()
    v = _vet(clip)
    assert v.trang_thai == "render"
    assert v.khop["qua_cong"] and v.khop["lech"] == 0
    assert len(v.khung_render) >= 50
    assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in v.khung_render) <= 3


def test_hat_giong_hai_box_van_thanh_vet_va_render_dung_cho():
    """Cụm 1–2 box (trước đây vứt theo MIN_BOX=3) là HẠT GIỐNG: dựng mẫu từ box có, dò các khung còn lại."""
    clip = tao_clip()
    for khung in ((5, 15), (30,)):
        kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=khung))
        assert kq.trang_thai == "render" and len(kq.vet) == 1, khung
        v = kq.vet[0]
        assert len(v.khung_render) >= 50
        assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in v.khung_render) <= 3


def test_dot_bien_bo_hat_giong_thi_cum_nho_bi_bo(monkeypatch):
    """Gỡ hạt giống (đòi ≥3 box như MIN_BOX cũ) ⇒ cụm 2 box KHÔNG thành vết, và video báo chờ người kèm lý do (không im lặng)."""
    monkeypatch.setattr(duong_ong, "BOX_TOI_THIEU_HAT_GIONG", 3)
    clip = tao_clip()
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=(5, 15)))
    assert kq.trang_thai == "cho_nguoi" and kq.vet[0].khung_render == [] and "hạt giống" in kq.ly_do


def test_cum_gia_khong_thanh_vet_va_video_cho_nguoi_co_ly_do():
    """Một watermark thật + một box agy gọi nhầm nội dung: vết thật vẫn dựng, cụm giả KHÔNG biến mất mà nằm trong `vet_bi_bo`,
    video KHÔNG `render` im lặng (lỗ của ca 03_9: ≥1 vết render ⇒ cả video render)."""
    clip = tao_clip()
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(cum=1) + [clip.box_gia(cum=2)])
    assert [v.trang_thai for v in kq.vet].count("render") == 1 and len(kq.vet) == 2
    assert kq.trang_thai == "cho_nguoi"
    bo = kq.vet_bi_bo
    assert len(bo) == 1 and bo[0]["nhan"] == "cụm 2" and ("bằng chứng" in bo[0]["ly_do"] or "nhiễu" in bo[0]["ly_do"])
    assert "cụm 2" in kq.ly_do


def test_chi_cum_gia_thi_khong_co_khung_nao_duoc_render():
    clip = tao_clip()
    kq = duong_ong.xu_ly_video(clip.nguon, [clip.box_gia()])
    assert kq.trang_thai == "cho_nguoi" and all(not v.khung_render for v in kq.vet)


def test_khong_co_box_thi_cho_nguoi_co_ly_do():
    kq = duong_ong.xu_ly_video(tao_clip().nguon, [])
    assert kq.vet == [] and kq.trang_thai == "cho_nguoi" and kq.ly_do


def test_gom_vet_theo_cum_va_vi_tri_khong_theo_co():
    from tiktok_music_downloader.thay_logo.box_moi import gom_vet
    # cùng số cụm, cỡ lệch >35% (agy lúc rộng lúc hẹp) ⇒ vẫn MỘT cụm; khác số cụm ở chỗ khác ⇒ cụm riêng
    a = [BoxMoi(i, 10 + 40 * i, 10, 100 - 25 * (i % 2), 30, cum=1) for i in range(4)]
    b = [BoxMoi(i, 50, 300, 220, 70, cum=2) for i in range(3)]
    cum = gom_vet(a + b)
    assert sorted(len(c) for c in cum) == [3, 4]
    assert {z.cum for c in cum for z in c if len(c) == 4} == {1}


def test_gom_vet_cung_cho_chong_nhau_khong_nhan_la_mot_cum():
    from tiktok_music_downloader.thay_logo.box_moi import gom_vet
    cum = gom_vet([BoxMoi(0, 100, 100, 80, 30), BoxMoi(9, 104, 102, 70, 28)])
    assert len(cum) == 1


def test_gom_vet_giong_hinh_gop_du_khac_cho():
    """Không nhãn, không chồng vị trí, nhưng crop GIỐNG nhau (logo trôi) ⇒ một cụm; crop nền khác hẳn ⇒ cụm riêng."""
    from tiktok_music_downloader.thay_logo.box_moi import gom_vet
    clip = tao_clip()
    t = [clip.box_moi(khung=(5, 45))[0], clip.box_moi(khung=(5, 45))[1], clip.box_gia(25)]
    cum = gom_vet(t, clip.nguon)
    assert sorted(len(c) for c in cum) == [1, 2]


def test_khung_filled_duoc_render_con_predicted_thi_khong():
    track = [{"frame": 0, "state": "detected"}, {"frame": 1, "state": "filled"}, {"frame": 2, "state": "predicted"},
             {"frame": 3, "state": "hidden"}, {"frame": 4, "state": "hidden_sub"}]
    assert [e["frame"] for e in cong.khung_duoc_render(track, True)] == [0, 1]
    assert cong.khung_duoc_render(track, False) == []
    assert [e["frame"] for e in cong.khung_con_watermark_khong_thay([dict(e, x=0) for e in track])] == [4]


def test_cong_khop_mot_box_mo_sai_khong_giet_vet_dung():
    track = [{"frame": i, "x": 100, "y": 100, "w": 50, "h": 20, "state": "detected"} for i in range(10)]
    dung = [BoxMoi(i, 100, 100, 50, 20) for i in (1, 3, 5)]
    sai = BoxMoi(7, 300, 400, 50, 20)
    assert cong.cong_khop(track, dung + [sai])["qua_cong"]
    assert not cong.cong_khop(track, [dung[0], sai, BoxMoi(8, 320, 420, 50, 20)])["qua_cong"]


# --- Lớp: bộ lọc ứng viên phụ đề trong C (chữ trắng viền đen) ---

def test_phu_de_vien_den_khong_bao_gio_duoc_render():
    clip = tao_clip(phu_de_vien_den=range(20, 30))
    v = _vet(clip)
    assert v.trang_thai == "render"
    assert not {e["frame"] for e in v.khung_render} & clip.khung_phu_de


def test_dot_bien_bo_ca_ba_lop_phu_de_thi_phu_de_vien_den_lot(monkeypatch):
    """Phụ đề viền đen bị BỐN lớp chồng nhau chặn: bộ lọc ứng viên của C, cổng phụ đề cũ (cùng hàm/pad/ngưỡng với bộ lọc ⇒
    nhánh 'bỏ khung' của nó chỉ kích hoạt khi bộ lọc đã mất), cổng vành ngang (chữ tràn ngang) và cổng nét lạ. Gỡ cả bốn mới lọt."""
    clip = tao_clip(phu_de_vien_den=range(20, 30))
    monkeypatch.setattr(dinh_vi_mod, "NGUONG_PHU_DE_UNG_VIEN", 2.0)
    monkeypatch.setattr(cong, "PHU_DE_TI_LE", 2.0)
    monkeypatch.setattr(cong, "cong_vanh_ngang", lambda track, ti_le: None)
    monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    v = _vet(clip)
    assert {e["frame"] for e in v.khung_render} & clip.khung_phu_de


@pytest.mark.parametrize("go_lop", ["loc_ung_vien", "cong_cu", "vanh", "net_la"])
def test_dot_bien_bo_mot_lop_phu_de_vien_den_van_bi_chan(monkeypatch, go_lop):
    clip = tao_clip(phu_de_vien_den=range(20, 30))
    if go_lop == "loc_ung_vien":
        monkeypatch.setattr(dinh_vi_mod, "NGUONG_PHU_DE_UNG_VIEN", 2.0)
    elif go_lop == "cong_cu":
        monkeypatch.setattr(cong, "PHU_DE_TI_LE", 2.0)
    elif go_lop == "vanh":
        monkeypatch.setattr(cong, "cong_vanh_ngang", lambda track, ti_le: None)
    else:
        monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    v = _vet(clip)
    assert not {e["frame"] for e in v.khung_render} & clip.khung_phu_de


# --- Lớp: cổng vành ngang (phụ đề trắng BÓNG MỜ, không viền đen — lỗ Test 02 _3) ---

def test_phu_de_bong_mo_bi_cong_vanh_ngang_chan():
    clip = tao_clip(phu_de_bong_mo=range(20, 30))
    v = _vet(clip)
    assert v.dem_chan[cong.CHAN_VANH] > 0
    assert not {e["frame"] for e in v.khung_render} & clip.khung_phu_de


def test_dot_bien_bo_cong_vanh_ngang_va_net_la_thi_phu_de_bong_mo_lot(monkeypatch):
    clip = tao_clip(phu_de_bong_mo=range(20, 30))
    monkeypatch.setattr(cong, "cong_vanh_ngang", lambda track, ti_le: None)
    monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    v = _vet(clip)
    assert {e["frame"] for e in v.khung_render} & clip.khung_phu_de


# --- Lớp: cổng tương phản HỌC theo video (icon đặc không được bị giết) ---

def test_icon_dac_tuong_phan_cao_van_duoc_render():
    clip = tao_clip(icon_dac=True)
    v = _vet(clip)
    assert v.trang_thai == "render" and v.dem_chan[cong.CHAN_TUONG_PHAN] == 0


def test_dot_bien_nguong_tuong_phan_co_dinh_65_giet_icon_dac(monkeypatch):
    clip = tao_clip(icon_dac=True)
    monkeypatch.setattr(cong, "nguong_tuong_phan", lambda tcon: 65.0)
    v = _vet(clip)
    assert v.khung_render == []


def test_icon_trang_tren_nen_den_duoc_render_nho_tat_loc_phu_de_khi_mau_giong_phu_de():
    """Nét >215 sát nền <45 trùng định nghĩa 'phụ đề' của bộ lọc ứng viên + cổng phụ đề. Trước đây watermark trắng-trên-đen bị loại
    hết (an toàn nhưng vô ích: Helixa, v30 của Test 03). Nay mẫu CHÍNH NÓ giống phụ đề ⇒ lọc/cổng phụ đề không phân định được ⇒ tắt
    cho vết đó; vẫn phải khớp mẫu mạnh + qua cổng khớp mồi mới được render."""
    clip = tao_clip(icon_dac=True, icon_nen=20.0, icon_tam=240.0)
    v = _vet(clip)
    assert v.trang_thai == "render" and len(v.khung_render) >= 50
    assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in v.khung_render) <= 3


def test_dot_bien_khong_tat_loc_phu_de_cho_mau_giong_phu_de_thi_icon_trang_den_mat(monkeypatch):
    monkeypatch.setattr(duong_ong, "mau_giong_phu_de", lambda mau: False)
    v = _vet(tao_clip(icon_dac=True, icon_nen=20.0, icon_tam=240.0))
    assert v.khung_render == []


# --- Lớp: cổng tương phản chặn nội dung tương phản cao nằm trong box ---

def test_cong_tuong_phan_chan_noi_dung_dam_trong_box(monkeypatch):
    clip = tao_clip()
    mau = mau_mod.dung_mau_sach(clip.nguon, clip.box_moi()[0], clip.box_moi())
    mask, _ = mau_mod.mat_na_va_tuong_phan(mau)
    khung_dam = set(range(30, 36))
    for i in khung_dam:  # cùng hình chữ nhưng ĐẶC, tương phản mạnh (kiểu tên thương hiệu trong UI app, không phải watermark mờ)
        x, y, w, h = clip.hop_that[i]
        mk = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST) > 0
        vung = clip.nguon.doc(i)[y:y + h, x:x + w]
        vung[mk], vung[~mk] = 250, 20
    track = [{"frame": i, "x": x, "y": y, "w": w, "h": h, "state": "detected"}
             for i, (x, y, w, h) in enumerate(clip.hop_that)]
    kq = duong_ong.ap_moi_cong(clip.nguon, [dict(e) for e in track], mau, clip.box_moi())
    assert not {e["frame"] for e in kq.khung_render} & khung_dam
    monkeypatch.setattr(cong, "cong_tuong_phan", lambda g, e, mask, nguong: None)
    monkeypatch.setattr(cong, "cong_phu_de", lambda g, e: None)
    monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    kq = duong_ong.ap_moi_cong(clip.nguon, [dict(e) for e in track], mau, clip.box_moi())
    assert {e["frame"] for e in kq.khung_render} & khung_dam


# --- Lớp: cổng khớp box mồi (mẫu sai tự nhất quán) ---

def _track_lech(clip, dx=120):
    return [{"frame": i, "x": x + dx, "y": y, "w": w, "h": h, "state": "detected"}
            for i, (x, y, w, h) in enumerate(clip.hop_that)]


def test_track_lech_box_moi_bi_cong_khop_chan():
    clip = tao_clip()
    mau = mau_mod.dung_mau_sach(clip.nguon, clip.box_moi()[0], clip.box_moi())
    kq = duong_ong.ap_moi_cong(clip.nguon, _track_lech(clip), mau, clip.box_moi())
    assert kq.khop["lech"] >= 3 and kq.khung_render == [] and kq.trang_thai == "cho_nguoi"


def test_dot_bien_bo_cong_khop_thi_render_len_noi_dung(monkeypatch):
    clip = tao_clip()
    mau = mau_mod.dung_mau_sach(clip.nguon, clip.box_moi()[0], clip.box_moi())
    monkeypatch.setattr(cong, "cong_khop", lambda track, boxes, can=3: {"qua_cong": True})
    kq = duong_ong.ap_moi_cong(clip.nguon, _track_lech(clip), mau, clip.box_moi())
    assert kq.khung_render and min(tam_lech(e, clip.hop_that[e["frame"]]) for e in kq.khung_render) > 100


def test_cong_khop_box_ma_track_vang_khong_tinh_lech():
    track = [{"frame": 0, "state": "hidden"}, {"frame": 1, "x": 0, "y": 0, "w": 10, "h": 10, "state": "detected"}]
    track[1]["frame"] = 5
    kq = cong.cong_khop(track, [BoxMoi(0, 500, 500, 10, 10), BoxMoi(5, 0, 0, 10, 10)], can=1)
    assert kq == {"khop": 1, "lech": 0, "track_vang": 1, "qua_cong": True}


# --- Lớp: từ chối mẫu tự học trôi sang nội dung ---

def test_tu_hoc_tu_choi_mau_moi_lech_mau_cu(monkeypatch):
    clip = tao_clip()
    mau = mau_mod.dung_mau_sach(clip.nguon, clip.box_moi()[0], clip.box_moi())
    track_nen = _track_lech(clip, dx=150)  # khung "chắc" nằm trên nền trơn ⇒ trung vị crop là nền
    moi, nhan = mau_mod.tu_hoc_mau(clip.nguon, track_nen, mau)
    assert not nhan and moi is mau
    monkeypatch.setattr(mau_mod, "NCC_TU_HOC_TOI_THIEU", -1.0)
    moi, nhan = mau_mod.tu_hoc_mau(clip.nguon, track_nen, mau)
    assert nhan and moi is not mau


# --- Lớp: cổng NÉT LẠ (§5c.2) — khối chữ nằm GỌN trong box mà C vẫn "chắc" ---

def test_khoi_chu_trong_box_bi_cong_net_la_chan():
    from thay_logo_tong_hop import dan_khoi_trong_box
    clip = tao_clip()
    dan_khoi_trong_box(clip, range(30, 37))
    v = _vet(clip)
    assert v.trang_thai == "render" and v.dem_chan[cong.CHAN_NET] > 0
    assert not {e["frame"] for e in v.khung_render} & clip.khung_phu_de


def test_dot_bien_bo_cong_net_la_thi_khoi_chu_lot(monkeypatch):
    """Cũng là bằng chứng fixture có sức phân định: không có cổng, C vẫn 'chắc' trên các khung có khối chữ."""
    from thay_logo_tong_hop import dan_khoi_trong_box
    clip = tao_clip()
    dan_khoi_trong_box(clip, range(30, 37))
    monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    v = _vet(clip)
    assert {e["frame"] for e in v.khung_render} & clip.khung_phu_de


@pytest.mark.parametrize("kw", [{}, {"icon_dac": True}])
def test_cong_net_la_khong_chan_watermark_sach(kw):
    v = _vet(tao_clip(**kw))
    assert v.dem_chan[cong.CHAN_NET] == 0 and not v.net_la_pho_bien


def test_net_la_pho_bien_chi_gan_co_khong_tu_nang_trang_thai():
    track = [{"frame": i, "state": "detected"} for i in range(10)] + [{"frame": 10, "state": "hidden_ring"}]
    ti_le = {i: 0.2 for i in range(11)}
    assert cong.cong_net_la(track, ti_le) is True
    assert track[10]["state"] == "hidden_ring"  # cổng chỉ HẠ khung detected, không bao giờ nâng
