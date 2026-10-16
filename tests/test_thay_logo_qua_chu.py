"""Che qua chữ (`qua_chu.lap_qua_chu`) trên clip TỔNG HỢP có ground truth: đoạn bị cổng chặn ngắn giữa hai khung đang dán được che (đè
chữ, user 16/10), đúng vị trí logo; đoạn dài / khung box mồi giữ nguyên; dò hai đầu chỉ ở lượt có AI và theo kịp logo nhảy chỗ.
Mỗi tính năng có đột biến chứng minh fixture phân định được."""
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless")

from thay_logo_tong_hop import tam_lech, tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import cong, duong_ong, mau as mau_mod, qua_chu  # noqa: E402

PHU_DE = range(20, 30)


def _vet(clip):
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi())
    assert len(kq.vet) == 1
    return kq.vet[0]


def test_phu_de_ngan_giua_hai_khung_che_duoc_che_qua_chu_dung_cho_logo():
    clip = tao_clip(phu_de_vien_den=PHU_DE)
    v = _vet(clip)
    by = {e["frame"]: e for e in v.khung_render}
    box = {b.khung + d for b in clip.box_moi() for d in (-1, 0, 1)}
    che = [k for k in PHU_DE if k not in box]
    assert che and all(k in by and by[k].get("qua_chu") and by[k].get("de_chu") for k in che)
    assert all(tam_lech(by[k], clip.hop_that[k]) <= 12 for k in che)
    assert not any(by.get(k, {}).get("qua_chu") for k in PHU_DE if k in box)  # khung box mồi ±1 không bị dời
    assert v.dem_chan["qua_chu"]["noi"] >= len(che)


def test_dot_bien_tat_che_qua_chu_thi_phu_de_lo_lai(monkeypatch):
    monkeypatch.setattr(qua_chu, "GAP_MAX", -1)
    clip = tao_clip(phu_de_vien_den=PHU_DE)
    v = _vet(clip)
    assert not {e["frame"] for e in v.khung_render} & set(PHU_DE)


def test_doan_chan_dai_hon_gap_max_van_bi_chan(monkeypatch):
    monkeypatch.setattr(qua_chu, "GAP_MAX", 5)  # phụ đề 10 khung > trần ⇒ coi như nội dung dài, cổng giữ chặn
    clip = tao_clip(phu_de_vien_den=PHU_DE)
    v = _vet(clip)
    assert not {e["frame"] for e in v.khung_render} & set(PHU_DE)


A, B = (60, 420), (60, 560)  # logo nhảy 140 px giữa khung 14 và 15 (kiểu Test 03_1 k4353–4357)


def _track_nhay():
    clip = tao_clip(n=30, duong_di=lambda i: A if i < 15 else B)
    boxes = clip.box_moi(khung=(2, 5, 25))
    mau = mau_mod.dung_mau_sach(clip.nguon, boxes[0], boxes)
    track = []
    for i, (x, y, w, h) in enumerate(clip.hop_that):
        if 10 <= i < 20:  # vết dò mất ở đoạn chữ: cổng phụ đề chặn, không có vị trí tin được
            track.append({"frame": i, "x": None, "y": None, "w": w, "h": h, "state": cong.CHAN_PHU_DE, "score": None})
        else:
            track.append({"frame": i, "x": x, "y": y, "w": w, "h": h, "state": "detected", "score": 0.9})
    return clip, mau, track


def test_do_hai_dau_chi_chay_o_luot_co_ai_va_theo_kip_logo_nhay():
    clip, mau, track = _track_nhay()
    dem = qua_chu.lap_qua_chu(clip.nguon, [dict(e) for e in track], mau, [], co_ai=False)
    assert dem == {"noi": 0, "dp": 0}  # hai đầu xa nhau ⇒ không nội suy; không có AI ⇒ không dò
    dem = qua_chu.lap_qua_chu(clip.nguon, track, mau, [], co_ai=True)
    lap = [e for e in track if e.get("qua_chu") == "dp"]
    assert dem["dp"] == len(lap) >= 7  # bước ≤ BUOC_DP: quanh cú nhảy tức thời 140 px đường phải đi qua chỗ không có logo ⇒ điểm thấp, không dán
    assert all(tam_lech(e, clip.hop_that[e["frame"]]) <= 12 for e in lap)


def test_doan_lap_mot_phan_thi_khung_con_lai_giu_chan_khong_cho_go_chan_le_go_an_theo(monkeypatch):
    monkeypatch.setattr(qua_chu, "SAN_DAN", 2.0)  # không khung nào đạt sàn dò ⇒ chỉ khi có khung được lấp mới gắn giữ chặn
    clip, mau, track = _track_nhay()
    qua_chu.lap_qua_chu(clip.nguon, track, mau, [], co_ai=True)
    assert not any(e.get("giu_chan") for e in track)
    monkeypatch.setattr(qua_chu, "SAN_DAN", 0.165)
    clip, mau, track = _track_nhay()
    qua_chu.lap_qua_chu(clip.nguon, track, mau, [], co_ai=True)
    con = [e for e in track[10:20] if not e.get("qua_chu")]
    assert all(e.get("giu_chan") for e in con)


def test_do_hai_dau_khong_dan_vao_khung_vang_logo():
    """Logo ở A (k10–12), TẮT k13–16 (không có logo — dán vào là dán sai), hiện lại ở B (k17–19): chỉ dán chỗ có logo."""
    vang = set(range(13, 17))
    clip = tao_clip(n=30, duong_di=lambda i: A if i < 15 else B, vang_khung=vang)
    boxes = clip.box_moi(khung=(2, 5, 25))
    mau = mau_mod.dung_mau_sach(clip.nguon, boxes[0], boxes)
    track = []
    for i, (x, y, w, h) in enumerate(clip.hop_that):
        an = 10 <= i < 20
        track.append({"frame": i, "x": None if an else x, "y": None if an else y, "w": w, "h": h,
                      "state": cong.CHAN_PHU_DE if an else "detected", "score": None if an else 0.9})
    qua_chu.lap_qua_chu(clip.nguon, track, mau, [], co_ai=True)
    lap = {e["frame"]: e for e in track if e.get("qua_chu") == "dp"}
    assert not set(lap) & vang
    assert {10, 11, 12, 17, 18, 19} <= set(lap)
    assert all(tam_lech(e, clip.hop_that[k]) <= 12 for k, e in lap.items())


def test_khong_co_duong_tron_doan_thi_do_tu_moi_dau_vao(monkeypatch):
    """Hai đầu cách ~570 px qua 4 khung trống (mỗi bước > BUOC_DP) ⇒ không có đường trọn đoạn; logo ở A k10–11, ở B k12–13 ⇒ dò từ đầu
    trái lấp k10–11, từ đầu phải lấp k12–13. (Test 03_4 k273–293: không có đường ⇒ trước đây không lấp được cả khung sát đầu.)"""
    monkeypatch.setattr(qua_chu, "SAN_DAN", 0.10)  # nền tổng hợp ở B cho điểm khớp ~0,16: tách riêng logic dò từ hai đầu khỏi sàn dán
    xa, xb = (10, 40), (250, 560)
    clip = tao_clip(n=30, duong_di=lambda i: xa if i < 12 else xb)
    boxes = clip.box_moi(khung=(2, 5, 25))
    mau = mau_mod.dung_mau_sach(clip.nguon, boxes[0], boxes)
    track = []
    for i, (x, y, w, h) in enumerate(clip.hop_that):
        an = 10 <= i < 14
        track.append({"frame": i, "x": None if an else x, "y": None if an else y, "w": w, "h": h,
                      "state": cong.CHAN_PHU_DE if an else "detected", "score": None if an else 0.9})
    qua_chu.lap_qua_chu(clip.nguon, track, mau, [], co_ai=True)
    lap = {e["frame"]: e for e in track if e.get("qua_chu") == "dp"}
    assert set(lap) == {10, 11, 12, 13}
    assert all(tam_lech(e, clip.hop_that[k]) <= 20 for k, e in lap.items())  # B sát mép phải (x 250+98 / 360): vùng tìm bị cắt mép


def test_khung_box_moi_bo_qua_khong_giu_chan_de_go_chan_le_go_tai_cho():
    """Đoạn chặn k10–13 (nội suy được), box mồi ở k12 ⇒ k11–13 không bị dời; chúng KHÔNG được gắn giữ chặn ⇒ go_chan_le gỡ tại vị trí
    vết dò (Test 03_40 k294–296: mốc user k295 lộ khi gắn nhầm)."""
    clip = tao_clip(n=30)
    track = []
    for i, (x, y, w, h) in enumerate(clip.hop_that):
        chan = 10 <= i < 14
        track.append({"frame": i, "x": x, "y": y, "w": w, "h": h, "state": cong.CHAN_NET if chan else "detected", "score": 0.5})
    mau = mau_mod.dung_mau_sach(clip.nguon, clip.box_moi(khung=(5,))[0], clip.box_moi(khung=(5, 12, 20)))
    qua_chu.lap_qua_chu(clip.nguon, track, mau, clip.box_moi(khung=(12,)), co_ai=False)
    assert track[10].get("qua_chu") == "noi" and not any(track[k].get("qua_chu") for k in (11, 12, 13))
    assert not any(track[k].get("giu_chan") for k in (11, 12, 13))
    cong.go_chan_le(track)
    assert all(track[k]["state"] in cong.DA_CHAC and tam_lech(track[k], clip.hop_that[k]) == 0 for k in (11, 12, 13))
