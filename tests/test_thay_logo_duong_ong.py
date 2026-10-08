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


def test_khong_du_box_moi_thi_cho_nguoi_khong_render():
    clip = tao_clip()
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=(5, 15)))
    assert kq.vet == [] and kq.trang_thai == "cho_nguoi"


def test_hai_thuong_hieu_khac_co_thanh_hai_vet():
    from tiktok_music_downloader.thay_logo.box_moi import gom_vet
    nho = [BoxMoi(i, 10, 10, 100, 30) for i in range(4)]
    to = [BoxMoi(i, 50, 300, 220, 70) for i in range(3)]
    cum = gom_vet(nho + to)
    assert sorted(len(c) for c in cum) == [3, 4]


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


def test_icon_trang_tren_nen_den_hien_bi_loc_nhu_phu_de():
    """GIỚI HẠN ĐÃ BIẾT (ghi lại, không phải hành vi mong muốn): nét >215 sát nền <45 trùng định nghĩa 'phụ đề' của bộ lọc
    ứng viên ⇒ watermark trắng-trên-đen bị loại hết ⇒ chờ người. An toàn (không render sai) nhưng vô ích. Đổi bộ lọc thì
    test này phải đổi theo — có chủ đích."""
    clip = tao_clip(icon_dac=True, icon_nen=20.0, icon_tam=240.0)
    v = _vet(clip)
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


# --- Lớp: cổng cứng — chỉ `detected` mới render ---

def test_khung_predicted_khong_bao_gio_render():
    track = [{"frame": 0, "state": "detected"}, {"frame": 1, "state": "predicted"}, {"frame": 2, "state": "hidden"}]
    assert [e["frame"] for e in cong.khung_duoc_render(track, True)] == [0]
    assert cong.khung_duoc_render(track, False) == []


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
