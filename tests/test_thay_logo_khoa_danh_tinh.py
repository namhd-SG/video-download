"""Khoá / khoá lại có danh tính vết: cổng 2-trong-3, bộ đệm trễ, thoát bẫy nhánh gần, danh tính chống nhiễm, hợp hai lượt.

Ứng viên tổng hợp (x, y, điểm, w, h); danh tính logo 74×72 điểm 0,66. Mỗi lớp có đột biến chứng minh test phân định được."""
from tiktok_music_downloader.thay_logo import khoa_danh_tinh as kd
from tiktok_music_downloader.thay_logo import theo_vet as tv

DD = {"w": 74.0, "h": 72.0, "s": 0.66}
KICH = (74, 72)
L = (600, 500, 0.8, 74, 72)      # logo thật
B = (100, 1000, 0.8, 74, 72)     # cùng hình ở chỗ khác (logo đổi chỗ thật / bản sao): qua cổng
B_XAU = (100, 1000, 0.40, 66, 64)  # điểm thấp + lệch cỡ: trượt cổng
W = (100, 1000, 0.52, 68, 66)    # đồ vật: lệch cỡ, điểm vừa


def _dem():
    return {"tu_choi": set(), "tu_choi_dinh12": set(), "cho_ghi": 0, "cho_huy": 0, "thoat_bay": 0}


def _chay(uv, hop_moi=None, dd=None):
    return kd.mot_luot_cong(uv, range(len(uv)), 0.45, 0.3, KICH, dict(dd or DD), hop_moi or {}, _dem())


def _xs(out, tu):
    return {out[t]["x"] for t in out if t >= tu}


def test_cong_hai_trong_ba_tung_tin_hieu_va_mien_khung_moi():
    assert kd.qua_cong(L, [L], DD)                                   # một mình, đúng cỡ, điểm cao
    assert kd.qua_cong(L, [L, (100, 1000, 0.7, 74, 72)], DD)         # chỉ vế đỉnh1/đỉnh2 nổ
    assert kd.qua_cong((600, 500, 0.8, 66, 64), [(600, 500, 0.8, 66, 64)], DD)  # chỉ lệch cỡ
    assert not kd.qua_cong((600, 500, 0.40, 74, 72), [(600, 500, 0.40, 74, 72), (100, 1000, 0.35, 74, 72)], DD)  # đỉnh + điểm
    assert not kd.qua_cong(B_XAU, [B_XAU], DD)                       # điểm + cỡ, không có ứng viên chỗ khác
    assert not kd.qua_cong((600, 500, 0.8, 66, 64), [(600, 500, 0.8, 66, 64), (100, 1000, 0.7, 74, 72)], DD)  # đỉnh + cỡ
    assert kd.tin_hieu(L, [L], DD)[0] is False                       # không ứng viên chỗ khác ⇒ vế đỉnh không nổ
    moi = {10: [(598, 498, 78, 76)]}
    assert kd._khop_moi((600, 500, 0.4, 66, 64), 11, moi, 74) and not kd._khop_moi((600, 500, 0.4, 66, 64), 12, moi, 74)
    assert not kd._khop_moi(B, 10, moi, 74)                          # đúng khung mồi nhưng sai chỗ: không miễn


def test_cong_chan_khoa_vao_do_vat_sai_danh_tinh():
    noi = (300, 200, 0.5, 40, 40)
    out = _chay([[L]] * 20 + [[(100, 1000, 0.55, 68, 66), noi]] * 12)
    assert set(out) == set(range(20))


def test_dot_bien_bo_cong_thi_khoa_vao_do_vat(monkeypatch):
    monkeypatch.setattr(kd, "tin_hieu", lambda c, cs, dd, s_ref=None: (False, False, False))
    out = _chay([[L]] * 20 + [[(100, 1000, 0.55, 68, 66), (300, 200, 0.5, 40, 40)]] * 12)
    assert _xs(out, 20) == {100}


def test_tre_vang_ba_khung_giu_vet_cu():
    out = _chay([[L]] * 20 + [[B]] * 3 + [[L]] * 10)
    assert not set(range(20, 23)) & set(out) and _xs(out, 23) == {600}


def test_dot_bien_bo_tre_thi_nhay_ngay(monkeypatch):
    monkeypatch.setattr(kd, "TRE_K", 1)
    out = _chay([[L]] * 20 + [[B]] * 3 + [[L]] * 10)
    assert {out[t]["x"] for t in range(20, 23)} == {100}


def test_tre_khung_giua_bo_dem_truot_cong_thi_huy():
    """Khung thứ 3 của chỗ mới trượt cổng rồi chỗ mới biến mất ⇒ không đủ 4 khung qua cổng ⇒ không khoá."""
    out = _chay([[L]] * 20 + [[B], [B], [B_XAU], [B], [], []] + [[]] * 4)
    assert set(out) == set(range(20))


def test_tre_doi_cho_that_ghi_hoi_to():
    out = _chay([[L]] * 20 + [[B]] * 20)
    assert set(out) == set(range(40)) and _xs(out, 20) == {100}
    assert out[20]["nhay"] and not out[21]["nhay"]


def test_thoat_bay_khi_vet_dinh_do_vat_va_logo_tro_lai():
    out = _chay([[W]] * 10 + [[W, L]] * 20)
    assert _xs(out, 10) == {600}
    assert all(out[t]["x"] == 100 for t in range(10))


def test_dot_bien_bo_thoat_bay_thi_bam_do_vat(monkeypatch):
    monkeypatch.setattr(kd, "THOAT_BAY", 1e9)
    out = _chay([[W]] * 10 + [[W, L]] * 20)
    assert _xs(out, 10) == {100}


def test_dot_bien_danh_tinh_troi_theo_vet_thi_mat_thoat_bay(monkeypatch):
    """Danh tính trung bình động (trôi theo thứ đang bám) ⇒ đồ vật thành 'đúng cỡ' ⇒ không còn lối ra."""
    goc = kd.tin_hieu

    def troi(c, cs, dd, s_ref=None):
        dd["w"] = 0.7 * dd["w"] + 0.3 * c[3]
        return goc(c, cs, dd, s_ref)
    monkeypatch.setattr(kd, "tin_hieu", troi)
    out = _chay([[W]] * 10 + [[W, L]] * 20)
    assert _xs(out, 10) == {100}


def test_khoa_lai_sau_lo_dung_cho_cu_van_qua_cong():
    """Mất ≥ HO_KHOA_LAI khung rồi có thứ ở đúng chỗ cũ: là khoá lại, phải đúng danh tính (thứ đứng yên chỗ logo vừa rời)."""
    ho = kd.HO_KHOA_LAI
    gia = (600, 500, 0.40, 74, 72)                     # đúng chỗ, đúng cỡ, điểm 0,6× + có đối thủ ngang điểm ⇒ trượt cổng
    out = _chay([[L]] * 10 + [[]] * ho + [[gia, (100, 1000, 0.38, 74, 72)]] * 10)
    assert set(out) == set(range(10))
    out = _chay([[L]] * 10 + [[]] * ho + [[L]] * 10)  # đối chứng: logo thật trở lại ⇒ giữ cả 10 khung (ghi hồi tố)
    assert set(out) == set(range(10)) | set(range(10 + ho, 20 + ho))


def test_dot_bien_khoa_lai_dung_cho_cu_khong_qua_cong(monkeypatch):
    monkeypatch.setattr(kd, "HO_KHOA_LAI", 10 ** 6)
    ho = 5
    out = _chay([[L]] * 10 + [[]] * ho + [[(600, 500, 0.40, 74, 72), (100, 1000, 0.38, 74, 72)]] * 10)
    assert set(range(10 + ho, 20 + ho)) <= set(out)


def test_bo_dem_cho_ho_hai_khung():
    """Mốc đúng ngắn có lỗ 2 khung vẫn khoá được: nó là neo cho bước bám hai chiều phía sau."""
    out = _chay([[L]] * 20 + [[B], [B], [], [], [B], [B]] + [[]] * 4)
    assert {20, 21, 24, 25} <= set(out) and _xs(out, 20) == {100}


def test_dot_bien_bo_dem_ho_mot_khung_thi_mat_moc(monkeypatch):
    monkeypatch.setattr(kd, "HO_CHO", 1)
    out = _chay([[L]] * 20 + [[B], [B], [], [], [B], [B]] + [[]] * 4)
    assert set(out) == set(range(20))


def _mo_dan(lech=0.0):
    """Logo rõ rồi mờ dần (tiếp nối, không cổng), mất 8 khung, trở lại đúng quỹ đạo (hoặc lệch `lech` cạnh) vẫn mờ, có đối thủ ngang điểm."""
    mo = (600, 500, 0.40, 74, 72)
    ve = (600 + lech * 74, 500, 0.38, 74, 72)
    return [[L]] * 5 + [[mo]] * 10 + [[]] * 8 + [[ve, (100, 1000, 0.33, 74, 72)]] * 6


def test_khoa_lai_lien_quy_dao_logo_mo_so_diem_voi_vet_truoc_lo():
    """So với danh tính toàn video, điểm 0,38 + đối thủ ngang điểm là trượt cổng; so với chính vết mờ ngay trước lỗ thì qua."""
    out = _chay(_mo_dan())
    assert set(range(23, 29)) <= set(out) and _xs(out, 23) == {600}
    out = _chay(_mo_dan(lech=0.3))  # đối chứng: lệch quỹ đạo 0,3 cạnh ⇒ vẫn so với danh tính ⇒ chặn
    assert not set(range(23, 29)) & set(out)


def test_dot_bien_bo_lien_quy_dao_thi_logo_mo_bi_chan(monkeypatch):
    monkeypatch.setattr(kd, "LECH_QUY_DAO", -1.0)
    assert not set(range(23, 29)) & set(_chay(_mo_dan()))


def test_tiep_noi_ke_thua_danh_tinh_khi_hai_ban_logo_cung_khung():
    """Lúc chuyển cảnh hai bản logo ngang điểm ⇒ vế đỉnh nổ, cỡ nhích 1 chút ⇒ chấm lại thì trượt; khung tiếp nối vẫn mang cờ qua cổng."""
    nhich = (600, 500, 0.8, 79, 72)
    out = _chay([[L]] * 5 + [[nhich, (100, 1000, 0.75, 74, 72)]] * 5)
    assert not kd.qua_cong(nhich, [nhich, (100, 1000, 0.75, 74, 72)], DD)
    assert all(out[t]["dd_ok"] for t in range(5, 10))


def test_mat_dau_qua_lau_quen_vi_tri_nhung_giu_danh_tinh():
    """> TRUOT_TOI_DA khung mất ⇒ quên vị trí/vận tốc (khoá lại là khoá mới, không phải 'nhảy' từ chỗ cũ đã trôi xa)."""
    out = _chay([[L]] * 10 + [[]] * (tv.TRUOT_TOI_DA + 2) + [[B]] * 6)
    t0 = 10 + tv.TRUOT_TOI_DA + 2
    assert set(out) == set(range(10)) | set(range(t0, t0 + 6)) and not out[t0]["nhay"]


def _det0(cac_co):
    return {t: {"frame": t, "x": 0, "y": 0, "w": w, "h": h, "score": s} for t, (w, h, s) in enumerate(cac_co)}


def test_danh_tinh_chong_nhiem_khi_vet_cu_sai_co_qua_nua():
    d = kd.danh_tinh(_det0([(50, 48, 0.9)] * 6 + [(74, 72, 0.6)] * 4), KICH)
    assert (d["w"], d["h"], d["s"], d["kep_kich"], d["lech_kich"]) == (74.0, 72.0, 0.6, False, 0.6)
    d = kd.danh_tinh(_det0([(50, 48, 0.9)] * 6 + [(74, 72, 0.6)] * 3), KICH)
    assert (d["w"], d["h"], d["kep_kich"]) == (74.0, 72.0, True)  # thiếu khung đúng cỡ ⇒ kẹp về cỡ mẫu
    assert kd.danh_tinh({}, KICH) is None


def test_dot_bien_danh_tinh_lay_ca_khung_sai_co(monkeypatch):
    monkeypatch.setattr(kd, "LECH_KICH_TOI_DA", 10.0)
    assert kd.danh_tinh(_det0([(50, 48, 0.9)] * 6 + [(74, 72, 0.6)] * 4), KICH)["w"] == 50


def _e(x, y, diem, ok):
    return {"frame": 0, "x": x, "y": y, "w": 74, "h": 72, "score": diem, "state": "detected", "nhay": False, "dd_ok": ok}


def test_hop_hai_luot_ben_qua_cong_thang_khi_bat_dong_cho():
    assert kd.hop_hai_luot_cong({0: _e(100, 1000, 0.9, False)}, {0: _e(600, 500, 0.6, True)}, DD)[0]["x"] == 600
    assert kd.hop_hai_luot_cong({0: _e(600, 500, 0.9, False)}, {0: _e(605, 500, 0.6, True)}, DD)[0]["x"] == 600  # cùng chỗ: điểm
    assert kd.hop_hai_luot_cong({0: _e(100, 1000, 0.9, True)}, {0: _e(600, 500, 0.6, True)}, DD)[0]["x"] == 100  # cùng qua: điểm


def test_theo_vet_chi_bat_cong_khi_co_box_moi():
    uv = [[L]] * 20 + [[B]] * 3 + [[L]] * 10
    det_cu, tt_cu = tv.theo_vet(uv, KICH, {0})
    assert "danh_tinh" not in tt_cu and {det_cu[t]["x"] for t in range(20, 23)} == {100}  # mã cũ: nhảy ngay
    det, tt = tv.theo_vet(uv, KICH, {0}, {0: [(600, 500, 74, 72)]})
    assert not set(range(20, 23)) & set(det) and "dd_ok" not in det[0]
    assert tt["danh_tinh"]["det0"] == len(det_cu) and tt["danh_tinh"]["cho_huy"] >= 1


def test_mien_khung_moi_khoa_ngay_khong_qua_cong_va_bo_dem():
    """Ứng viên khớp box mồi (khung mồi ±1) khoá ngay dù trượt cổng và chưa đủ 4 khung: mồi là sự thật đã duyệt."""
    x = (100, 1000, 0.5, 66, 64)
    dd = {"w": 74.0, "h": 72.0, "s": 0.8}  # x: điểm 0,625× + lệch cỡ ⇒ trượt cổng
    uv = [[x]] * 2 + [[]] * 5
    assert set(_chay(uv, hop_moi={1: [(100, 1000, 66, 64)]}, dd=dd)) == {0, 1}
    assert _chay(uv, dd=dd) == {}                                    # đối chứng: không mồi ⇒ bị chặn
