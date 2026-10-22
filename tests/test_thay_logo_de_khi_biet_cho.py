"""Đè khi đã biết chỗ (`cong.de_khi_biet_cho`): khung bị chặn có toạ độ đáng tin thì đè lại, khung đoán không đáng tin thì giữ chặn."""
from tiktok_music_downloader.thay_logo import cong, duong_ong


def _dt(f, x, y=100, score=0.6):
    return {"frame": f, "state": "detected", "score": score, "x": x, "y": y, "w": 60, "h": 20}


def _chan(f, x, y=100, state="hidden_hinh", score=None):
    return {"frame": f, "state": state, "score": score, "x": x, "y": y, "w": 60, "h": 20}


def _vet_kep(khoang=4, buoc=7, state="hidden_hinh"):
    """Khung dò thật ở 0 và `khoang`, giữa là khung lấp bị chặn; tâm đi `buoc` px/khung."""
    t = [_dt(0, 100)] + [_chan(f, 100 + buoc * f, state=state) for f in range(1, khoang)] + [_dt(khoang, 100 + buoc * khoang)]
    return t


def test_khung_lap_kep_ngan_troi_deu_duoc_de_lai():
    t = _vet_kep()
    assert cong.de_khi_biet_cho(t, "A", 10) == 3
    assert [e["state"] for e in t[1:4]] == ["filled"] * 3
    assert all(e["de_khi_biet"] and e["chan_cu"] == "hidden_hinh" for e in t[1:4])


def test_khoang_kep_dai_hon_nguong_giu_chan_nhung_muc_B_khong_gioi_han():
    t = _vet_kep(khoang=15)
    assert cong.de_khi_biet_cho(t, "A", 10) == 0
    assert cong.de_khi_biet_cho(_vet_kep(khoang=15), "B", None) == 14


def test_buoc_nhay_giua_hai_khung_kep_giu_chan():
    """Tâm đi > 25 px/khung = bước nhảy: chỗ đoán có thể là nền trống (lý do kiểm hình tồn tại)."""
    t = _vet_kep(buoc=30)
    assert cong.de_khi_biet_cho(t, "B", None) == 0
    assert all(e["state"] == "hidden_hinh" for e in t[1:-1])


def test_khung_lap_o_mep_vet_khong_kep_hai_phia_giu_chan():
    t = [_dt(0, 100), _chan(1, 107), _chan(2, 114)]
    assert cong.de_khi_biet_cho(t, "B", None) == 0
    t = [_chan(0, 93), _dt(1, 100)]
    assert cong.de_khi_biet_cho(t, "B", None) == 0


def test_khung_do_that_bi_kiem_hinh_chan_duoc_de_lai_ve_detected():
    t = [_dt(0, 100), _chan(1, 300, score=0.3), _dt(2, 100)]
    assert cong.de_khi_biet_cho(t, "A", 10) == 1
    assert t[1]["state"] == "detected"


def test_khung_khong_toa_do_giu_chan():
    t = [_dt(0, 100), {"frame": 1, "state": "hidden_hinh", "score": None}, _dt(2, 114)]
    assert cong.de_khi_biet_cho(t, "B", None) == 0


def test_cong_noi_dung_chi_go_o_muc_B():
    for st in cong.CAC_CONG_NOI_DUNG:
        assert cong.de_khi_biet_cho(_vet_kep(state=st), "A", 10) == 0
        t = _vet_kep(state=st)
        assert cong.de_khi_biet_cho(t, "B", None) == 3
        assert all(e["chan_cu"] == st for e in t[1:4])


def test_khung_kep_bi_chan_cong_noi_dung_van_tinh_la_moc_do_that():
    """Khung dò thật bị cổng nội dung chặn vẫn biết toạ độ ⇒ được dùng làm mốc kẹp cho khung lấp kế nó."""
    t = [_dt(0, 100), _chan(1, 107), _chan(2, 114, state="hidden_ring", score=0.5)]
    assert cong.de_khi_biet_cho(t, "A", 10) == 1
    assert t[1]["state"] == "filled" and t[2]["state"] == "hidden_ring"


def test_bien_moi_truong_trong_la_tat_va_gia_tri_la_bi_tu_choi():
    assert duong_ong._muc_de_khi_biet("") is None
    assert duong_ong._muc_de_khi_biet("A:5") == ("A", 5)
    assert duong_ong._muc_de_khi_biet("B") == ("B", None)
    try:
        duong_ong._muc_de_khi_biet("X:1")
    except ValueError:
        pass
    else:
        raise AssertionError("giá trị lạ phải bị từ chối")


# --- Mức L (lai): đo 21/10 B đè sai 9/38 chỗ — toàn khung kiểm hình kẹp khoảng dài, neo nhiễu, hinh_hut ---

def test_L_khong_de_khung_hinh_hut_va_khong_lay_no_lam_neo():
    """Kiểm hình hạ khung dò thật vì vết NHẢY rồi bám chỗ khác (`hinh_hut`, vẫn còn score) — chỗ đó không có logo."""
    hut = dict(_chan(1, 300, score=0.3), hinh_hut=0.3)
    t = [_dt(0, 100), hut, _chan(2, 300), dict(_chan(3, 300, score=0.3), hinh_hut=0.3)]
    assert cong.de_khi_biet_cho(t, "L", None) == 0
    assert [e["state"] for e in t[1:]] == ["hidden_hinh"] * 3


def test_L_neo_duoi_san_hinh_khong_duoc_kep():
    """Neo nhiễu (điểm dưới sàn hình của vết) không được kéo khung lấp dậy; neo đạt sàn thì được."""
    tot = [_dt(f, 100 + f, score=0.9) for f in range(0, 30, 3)]
    nhieu = [_dt(30, 130, score=0.1), _chan(31, 131), _dt(32, 132, score=0.1)]
    assert cong.de_khi_biet_cho(tot + nhieu, "L", None) == 0
    t = tot + [_dt(30, 130, score=0.9), _chan(31, 131), _dt(32, 132, score=0.9)]
    assert cong.de_khi_biet_cho(t, "L", None) == 1


def test_L_cong_noi_dung_khong_gioi_han_khoang_kiem_hinh_toi_da_10():
    assert cong.de_khi_biet_cho(_vet_kep(khoang=15, state="hidden_ring"), "L", None) == 14
    assert cong.de_khi_biet_cho(_vet_kep(khoang=15), "L", None) == 0
    assert cong.de_khi_biet_cho(_vet_kep(khoang=10), "L", None) == 9


def test_L_khung_do_that_bi_cong_noi_dung_chan_de_lai_khong_can_kep():
    t = [_chan(0, 100, state="hidden_sub", score=0.7)]
    assert cong.de_khi_biet_cho(t, "L", None) == 1 and t[0]["state"] == "detected"


def test_bien_moi_truong_nhan_muc_L():
    assert duong_ong._muc_de_khi_biet("L") == ("L", None)
    assert duong_ong._muc_de_khi_biet("L:10") == ("L", 10)


def test_C_chi_go_cong_noi_dung_khong_dung_kiem_hinh():
    """Mức C (22/10): chỉ cổng nội dung — khung kiểm hình chặn giữ nguyên dù kẹp ngắn, khung cổng nội dung đè lại."""
    t = _vet_kep(khoang=4)
    assert cong.de_khi_biet_cho(t, "C", None) == 0 and all(e["state"] == "hidden_hinh" for e in t[1:-1])
    assert cong.de_khi_biet_cho(_vet_kep(khoang=15, state="hidden_net"), "C", None) == 14
    assert duong_ong._muc_de_khi_biet("C") == ("C", None)
