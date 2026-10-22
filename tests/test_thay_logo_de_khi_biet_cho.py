"""Đè lại khung bị cổng nội dung chặn khi đã biết chỗ (`cong.de_khi_biet_cho`) + công tắc tắt khẩn THAY_LOGO_DE_KHI_BIET=off."""
from tiktok_music_downloader.thay_logo import cong, duong_ong


def _dt(f, x, y=100, score=0.6):
    return {"frame": f, "state": "detected", "score": score, "x": x, "y": y, "w": 60, "h": 20}


def _chan(f, x, y=100, state="hidden_ring", score=None):
    return {"frame": f, "state": state, "score": score, "x": x, "y": y, "w": 60, "h": 20}


def _vet_kep(khoang=4, buoc=7, state="hidden_ring"):
    """Khung dò thật ở 0 và `khoang`, giữa là khung lấp bị chặn; tâm đi `buoc` px/khung."""
    return [_dt(0, 100)] + [_chan(f, 100 + buoc * f, state=state) for f in range(1, khoang)] + [_dt(khoang, 100 + buoc * khoang)]


def test_khung_lap_kep_bi_cong_noi_dung_chan_duoc_de_lai():
    for st in cong.CAC_CONG_NOI_DUNG:
        t = _vet_kep(state=st)
        assert cong.de_khi_biet_cho(t) == 3
        assert all(e["state"] == "filled" and e["de_khi_biet"] and e["chan_cu"] == st for e in t[1:4])


def test_khoang_kep_dai_van_de_lai():
    """Cổng nội dung đã qua kiểm hình (máy thấy hình logo) ⇒ không giới hạn khoảng kẹp."""
    assert cong.de_khi_biet_cho(_vet_kep(khoang=40)) == 39


def test_khung_kiem_hinh_chan_khong_bao_gio_de_lai():
    """Đè khung kiểm hình chặn từng làm hiện 2 logo (đo 22/10) ⇒ giữ chặn dù kẹp ngắn."""
    t = _vet_kep(state="hidden_hinh")
    assert cong.de_khi_biet_cho(t) == 0 and all(e["state"] == "hidden_hinh" for e in t[1:-1])


def test_buoc_nhay_giua_hai_neo_giu_chan():
    t = _vet_kep(buoc=30)
    assert cong.de_khi_biet_cho(t) == 0 and all(e["state"] == "hidden_ring" for e in t[1:-1])


def test_khung_lap_o_mep_vet_khong_kep_hai_phia_giu_chan():
    assert cong.de_khi_biet_cho([_dt(0, 100), _chan(1, 107), _chan(2, 114)]) == 0
    assert cong.de_khi_biet_cho([_chan(0, 93), _dt(1, 100)]) == 0


def test_khung_do_that_bi_cong_noi_dung_chan_de_lai_khong_can_kep():
    t = [_chan(0, 100, state="hidden_sub", score=0.7)]
    assert cong.de_khi_biet_cho(t) == 1 and t[0]["state"] == "detected"


def test_khung_khong_toa_do_giu_chan():
    assert cong.de_khi_biet_cho([_dt(0, 100), {"frame": 1, "state": "hidden_net", "score": None}, _dt(2, 114)]) == 0


def test_neo_hinh_hut_khong_duoc_kep():
    """Khung kiểm hình hạ vì vết nhảy (`hinh_hut`, vẫn còn score) không phải neo đáng tin."""
    hut = dict(_chan(2, 114, state="hidden_hinh", score=0.3), hinh_hut=0.3)
    assert cong.de_khi_biet_cho([_dt(0, 100), _chan(1, 107), hut]) == 0


def test_neo_duoi_san_hinh_khong_duoc_kep():
    tot = [_dt(f, 100 + f, score=0.9) for f in range(0, 30, 3)]
    assert cong.de_khi_biet_cho(tot + [_dt(30, 130, score=0.1), _chan(31, 131), _dt(32, 132, score=0.1)]) == 0
    assert cong.de_khi_biet_cho(tot + [_dt(30, 130, score=0.9), _chan(31, 131), _dt(32, 132, score=0.9)]) == 1


def test_cong_tac_tat_khan():
    for gia_tri, bat in ((None, True), ("", True), ("off", False), ("OFF", False), (" off ", False), ("on", True)):
        assert duong_ong._bat_de_khi_biet(gia_tri) is bat


def test_hop_dong_bat_khung_phu_de_biet_cho_duoc_de_dung_cho(monkeypatch):
    """Hợp đồng KHI BẬT (mặc định) — user thay bất biến "không bao giờ đè lên phụ đề" cho ca máy BIẾT chỗ logo:
    USER-QUYET 16/10 11:29 "đề lên chữ dc mà đừng sợ"; 21/10 16:32 "đè lên gì cung dc".
    Clip tổng hợp có phụ đề viền đen chạy qua box: bật ⇒ khung phụ đề được đè, ĐÚNG chỗ logo thật (lệch tâm ≤ 3 px);
    tắt ⇒ không khung phụ đề nào được đè (đối chứng cùng clip)."""
    import pytest
    pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless")
    from thay_logo_tong_hop import tam_lech, tao_clip
    from tiktok_music_downloader.thay_logo import qua_chu as qua_chu_mod

    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # tách khỏi che-qua-chữ (có test riêng)

    def de(bat):
        monkeypatch.setattr(duong_ong, "DE_KHI_BIET", bat)
        clip = tao_clip(phu_de_vien_den=range(20, 30))
        kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi())
        assert len(kq.vet) == 1 and kq.vet[0].trang_thai == "render"
        return clip, [e for e in kq.vet[0].khung_render if e["frame"] in clip.khung_phu_de]

    clip, khung = de(True)
    assert khung, "bật: khung phụ đề mà biết chỗ logo phải được đè"
    assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in khung) <= 3
    assert all(e.get("de_khi_biet") for e in khung)
    assert de(False)[1] == []
