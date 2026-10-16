"""Lọc mốc AI thô trước lộ trình (`loc_moc_ai.chon_moc_ai`): 4 ca đo thật trên Test3 (số lấy từ lượt đo xung đột AI 15/10 —
tâm box AI, điểm xoá chữ tại AI, khoảng cách + điểm xoá chữ của det cùng khung). Box có ứng viên lõi luôn giữ."""
from tiktok_music_downloader.thay_logo.box_moi import BoxMoi
from tiktok_music_downloader.thay_logo.loc_moc_ai import chon_moc_ai

W, H = 148, 24


def _b(k: int, cx: float, cy: float) -> BoxMoi:
    return BoxMoi(k, int(cx - W / 2), int(cy - H / 2), W, H, "agy", 0)


def test_ai_lap_cung_box_sai_tren_dong_chu_bi_bac_ca_cum():
    """v13 k9646–k9701: AI vẽ cùng một box lên dòng chữ 17 lần. 9 box có det mạnh khác chỗ ⇒ L5; 8 box còn lại (det yếu / không det,
    có box có-ứng-viên gần) ⇒ lan cụm tĩnh từ L5."""
    co = {9643: _b(9643, 383, 763), 9649: _b(9649, 387, 758)}
    ks = [9646, 9652, 9655, 9658, 9661, 9664, 9667, 9670, 9673, 9676, 9679, 9682, 9685, 9688, 9695, 9698, 9701]
    tho = [_b(k, 370, 776) for k in ks]
    diem = {k: 0.10 for k in ks}
    xd = {9655: (121.2, 0.093), 9658: (121.2, 0.093), 9661: (121.2, 0.093), 9664: (121.2, 0.093), 9667: (121.2, 0.090),
          9673: (48.9, 0.383), 9676: (51.0, 0.428), 9679: (53.9, 0.454), 9682: (58.1, 0.566), 9685: (59.5, 0.630),
          9688: (62.4, 0.589), 9695: (70.1, 0.755), 9698: (71.5, 0.814), 9701: (74.5, 0.817)}
    giu, bo_l5, ly = chon_moc_ai(co, tho, diem, xd, san=0.713)
    assert {b.khung for b in giu} == set(co)
    assert bo_l5 == {9673, 9676, 9679, 9682, 9685, 9688, 9695, 9698, 9701}
    assert all(ly[k].startswith("d1") for k in (9646, 9652, 9655, 9658, 9661, 9664, 9667, 9670))


def test_ai_lap_tam_vung_cat_troi_len_ao_trong_bi_bac_ke_ca_khung_khong_co_det():
    """v01 k4340–k4355: logo dưới chữ, AI vẽ box lên áo trống. 4340–4346 có det đúng ⇒ L5; 4349/4355 không det, không box có-ứng-viên
    khớp quỹ đạo trong ±10, điểm tại AI < 0,15 ⇒ bác (4355 là chỗ dán sai mới khi chỉ có L5)."""
    co = {4334: _b(4334, 532, 898), 4337: _b(4337, 522, 900)}
    tho = [_b(4340, 514, 850), _b(4343, 504, 828), _b(4346, 494, 806), _b(4349, 484, 784), _b(4355, 566, 708)]
    diem = {4340: 0.106, 4343: 0.109, 4346: 0.149, 4349: 0.098, 4355: 0.119}
    xd = {4340: (49.0, 0.469), 4343: (71.0, 0.469), 4346: (92.5, 0.455)}
    giu, bo_l5, ly = chon_moc_ai(co, tho, diem, xd, san=0.683)
    assert {b.khung for b in giu} == set(co)
    assert bo_l5 == {4340, 4343, 4346}
    assert ly[4349].startswith("d2") and ly[4355].startswith("d2")


def test_logo_that_dung_yen_sau_chu_khong_ung_vien_van_giu():
    """v01 k2609–k2624: logo thật đứng yên sau dòng chữ, không ứng viên lõi, không det, không box có-ứng-viên gần. Điểm tại AI
    0,17–0,20 ≥ 0,15 và các box khớp nhau ⇒ GIỮ (đứng yên không phải dấu hiệu sai)."""
    ks = [2609, 2612, 2615, 2618, 2621, 2624]
    tho = [_b(k, 200 if k < 2621 else 199, 900) for k in ks]
    diem = dict(zip(ks, (0.182, 0.166, 0.184, 0.191, 0.203, 0.199)))
    giu, bo_l5, ly = chon_moc_ai({}, tho, diem, {}, san=0.683)
    assert [b.khung for b in giu] == ks and not bo_l5 and not ly


def test_ai_nhay_sai_bi_l5_bac_nhung_chi_dung_khung_do():
    """v05 k1004/k1007: box AI nhảy 190 px khỏi chuỗi trong khi det đúng (điểm 0,51–0,56) ⇒ L5 bác đúng hai khung đó; box có ứng viên
    hai bên giữ. (Lộ trình chỉ bỏ det tại đúng khung L5 bác — bỏ cả lân cận làm mất det đúng k1001.)"""
    co = {998: _b(998, 363, 898), 1001: _b(1001, 366, 898), 1009: _b(1009, 510, 830)}
    tho = [_b(1004, 556, 812), _b(1007, 556, 820)]
    giu, bo_l5, _ = chon_moc_ai(co, tho, {1004: 0.044, 1007: 0.184}, {1004: (205.8, 0.555), 1007: (200.3, 0.511)}, san=0.548)
    assert bo_l5 == {1004, 1007}
    assert {b.khung for b in giu} == {998, 1001, 1009}


def test_box_nam_tren_duong_noi_hai_box_co_ung_vien_khong_bi_l5():
    """Box thô nằm đúng đường nối hai box có-ứng-viên (logo sau hộp phụ đề) mà det nhảy sang mép hộp ⇒ không L5 dù det mạnh hơn."""
    co = {903: _b(903, 294, 808), 917: _b(917, 298, 833)}
    tho = [_b(910, 295, 822)]
    giu, bo_l5, _ = chon_moc_ai(co, tho, {910: 0.129}, {910: (123.0, 0.40)}, san=0.548)
    assert not bo_l5 and 910 in {b.khung for b in giu}
