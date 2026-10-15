"""Tracker mới (top-K ứng viên, xuôi + ngược, lấp lỗ, làm mượt) trên clip TỔNG HỢP có ground truth: vết tĩnh, trôi nhanh, nhảy góc,
mất vài khung. Tiêu chí chính là MẶT NẠ: mọi khung trong khoảng sống phải có ô che phủ tâm watermark thật, và chỉ số nháy ≤ 2%.
Mỗi lớp có đột biến chứng minh fixture phân định được (chỉ render khung detected ⇒ nháy; bỏ lấp lỗ ⇒ nháy)."""
import numpy as np
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from thay_logo_tong_hop import tam_lech, tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import cong, duong_ong, lam_muot_vet, mat_na_vet, nhay, theo_vet  # noqa: E402

TRONG_BOX = 3  # tâm watermark thật nằm trong ô che nới tối đa vài px


def _chay(clip, khung=(5, 15, 25)):  # ≥ CUM_LON box: cụm nhỏ hơn không tự render (test riêng ở test_thay_logo_duong_ong)
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=khung))
    assert len(kq.vet) == 1, [v.ly_do for v in kq.vet]
    return kq, kq.vet[0]


def _tam_thua_mat_na(kq, clip, khung):
    mn = mat_na_vet.mat_na_theo_khung(kq.vet)
    out = []
    for i in khung:
        x, y, w, h = clip.hop_that[i]
        if not mat_na_vet.diem_trong_mat_na(mn, i, x + w / 2, y + h / 2):
            out.append(i)
    return out


def test_vet_tinh_che_moi_khung_va_vi_tri_on_dinh():
    clip = tao_clip(n=70, duong_di=lambda i: (140, 300))
    kq, v = _chay(clip)
    assert kq.trang_thai == "render" and _tam_thua_mat_na(kq, clip, range(70)) == []
    xs = [e["x"] for e in v.khung_render]
    assert max(xs) - min(xs) <= 1  # vết tĩnh không rung: mượt hoá xoá nhiễu ±1px của ứng viên
    assert v.nhay["pct_nhay"] <= 2


def test_vet_troi_nhanh_hon_8px_moi_khung_khong_bi_ep_vao_tran_van_toc():
    """Viterbi cũ trần 8 px/khung bỏ logo này; tracker mới theo kịp 12 px/khung (P90 đo ở ca 03_9)."""
    clip = tao_clip(n=45, duong_di=lambda i: (120, 30 + 12 * i))
    kq, v = _chay(clip, khung=(3, 16, 30))
    assert _tam_thua_mat_na(kq, clip, range(45)) == []
    assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in v.khung_render) <= 4


def test_nhay_goc_ca_hai_vi_tri_deu_duoc_che():
    """Logo đứng ở góc A rồi NHẢY sang góc B: bước nhảy lớn được nhận (ứng viên mạnh) và mặt nạ không kéo ô qua màn hình."""
    clip = tao_clip(n=70, duong_di=lambda i: (30, 60) if i < 35 else (230, 520))
    kq, v = _chay(clip, khung=(5, 27, 50))
    assert _tam_thua_mat_na(kq, clip, [i for i in range(70) if abs(i - 35) > 2]) == []
    mn = mat_na_vet.mat_na_theo_khung(kq.vet)
    for i in (10, 20, 60):  # ô không bao giờ nằm lơ lửng giữa hai góc
        x0, y0, x1, y1 = mn[i][0]
        gx, gy, gw, gh = clip.hop_that[i]
        assert abs((x0 + x1) / 2 - (gx + gw / 2)) < 12 and abs((y0 + y1) / 2 - (gy + gh / 2)) < 12


def test_mat_vai_khung_duoc_lap_va_chi_so_nhay_dat():
    che = set(range(30, 35))
    clip = tao_clip(n=70, che_khung=che)
    kq, v = _chay(clip)
    assert {e["frame"] for e in v.khung_render} >= che  # khung bị phủ vẫn được che nhờ lấp lỗ
    assert {e["state"] for e in v.track if e["frame"] in che} == {"filled"}
    assert v.nhay["pct_nhay"] <= 2 and v.nhay["so_lan_doi"] == 0


def test_dot_bien_chi_render_khung_detected_thi_chi_so_nhay_do(monkeypatch):
    """Gỡ phần lấp lỗ khỏi danh sách render (kiểu cũ: chỉ `detected`) ⇒ 5 khung lộ trong ~70 ⇒ nháy vượt đích 2%."""
    monkeypatch.setattr(cong, "DA_CHAC", ("detected",))
    clip = tao_clip(n=70, che_khung=set(range(30, 35)))
    _, v = _chay(clip)
    assert v.nhay["pct_nhay"] > 2 and v.nhay["so_lan_doi"] >= 2


def test_do_nhay_dem_khung_lo_va_so_lan_doi():
    r = nhay.do_nhay([(0, 9)], {0, 1, 2, 3, 7, 8, 9})
    assert (r["khung_song"], r["khung_lo"], r["so_lan_doi"], r["pct_nhay"]) == (10, 3, 2, 30.0)
    assert nhay.do_nhay([], set())["pct_nhay"] == 0.0


def test_nguong_tuong_doi_theo_video_khong_phai_0_75():
    nen = [[(0, 0, 0.9, 10, 10), (5, 5, 0.12, 10, 10), (9, 9, 0.10, 10, 10)] for _ in range(50)]
    hi, lo, q = theo_vet.nguong_tuong_doi(nen)
    assert hi < 0.75 and lo < hi  # nền nhiễu thấp ⇒ ngưỡng thấp: không đòi 0,75 như skill
    nhieu = [[(0, 0, 0.9, 10, 10), (5, 5, 0.5, 10, 10), (9, 9, 0.45, 10, 10)] for _ in range(50)]
    assert theo_vet.nguong_tuong_doi(nhieu)[0] > hi  # nền nhiễu cao ⇒ ngưỡng nâng theo


def test_lam_muot_khong_keo_vet_dung_yen_va_giu_buoc_nhay():
    det = {t: {"frame": t, "x": 100 + (t % 2), "y": 200, "w": 60, "h": 20, "score": 0.8, "state": "detected"} for t in range(0, 40)}
    out, doan = lam_muot_vet.lap_va_lam_muot(det, 100)
    assert doan == [(0, 42)] and max(e["x"] for e in out.values()) - min(e["x"] for e in out.values()) <= 1
    nhay_det = {t: {"frame": t, "x": 20 if t < 10 else 300, "y": 50, "w": 60, "h": 20, "score": 0.8, "state": "detected"}
                for t in (*range(0, 10), *range(14, 30))}
    out, _ = lam_muot_vet.lap_va_lam_muot(nhay_det, 100)
    assert {out[t]["state"] for t in range(10, 14)} == {"filled"}
    assert abs(out[11]["x"] - 20) < 3 and abs(out[13]["x"] - 300) < 3  # nửa đầu lỗ giữ chỗ cũ, nửa sau chỗ mới: không nội suy xuyên màn
    assert abs(out[15]["x"] - 300) < 3


def test_lo_qua_dai_tach_thanh_hai_doan_song():
    det = {t: {"frame": t, "x": 50, "y": 50, "w": 40, "h": 20, "score": 0.8, "state": "detected"}
           for t in (*range(0, 10), *range(100, 110))}
    out, doan = lam_muot_vet.lap_va_lam_muot(det, 200)
    assert len(doan) == 2 and 50 not in out


def test_mat_na_chi_lay_vet_render_va_nhan_pad():
    class V:  # vết tối thiểu
        trang_thai = "render"
        khung_render = [{"frame": 3, "x": 10, "y": 20, "w": 30, "h": 10, "plate_pad": 2}]
    class X(V):
        trang_thai = "cho_nguoi"
    mn = mat_na_vet.mat_na_theo_khung([V(), X()])
    assert mn == {3: [(7, 17, 43, 33)]}  # nới max(PAD_TO=3, pad=2)
    assert mat_na_vet.diem_trong_mat_na(mn, 3, 44, 20, dung_sai=2) and not mat_na_vet.diem_trong_mat_na(mn, 4, 20, 20)


def test_go_chan_le_chi_go_doan_ngan_giu_doan_dai():
    """Báo động giả lẻ loi (≤3 khung) không được tạo nháy; phụ đề/nội dung thật kéo dài vẫn bị chặn."""
    track = [{"frame": i, "state": "detected", "score": 0.9, "x": 1, "y": 1, "w": 5, "h": 5} for i in range(30)]
    track[4]["state"] = cong.CHAN_NET                       # lẻ 1 khung
    for i in (10, 11, 12):
        track[i]["state"] = cong.CHAN_VANH                  # 3 khung liền (ngưỡng)
    for i in range(20, 28):
        track[i]["state"] = cong.CHAN_PHU_DE                # 8 khung = phụ đề thật
    track[15] = {"frame": 15, "state": cong.CHAN_NET, "score": None, "x": 1, "y": 1, "w": 5, "h": 5}  # khung lấp bị chặn lẻ
    assert cong.go_chan_le(track) == 5
    assert [e["state"] for e in track[:5]] == ["detected"] * 5 and track[15]["state"] == "filled"
    assert all(e["state"] == cong.CHAN_PHU_DE for e in track[20:28])
    assert cong.khung_con_watermark_khong_thay(track) == track[20:28]


def test_dot_bien_go_chan_le_tat_thi_khung_bi_chan_lo_ra(monkeypatch):
    """Cổng chặn oan một khung giữa vết: có gỡ chặn lẻ ⇒ khung vẫn được che; không có ⇒ nháy."""
    clip = tao_clip(n=70)
    monkeypatch.setattr(cong, "cong_net_la", lambda track, ti_le: False)
    monkeypatch.setattr(cong, "go_chan_theo_hinh", lambda track, net, san: 0)  # cô lập gỡ chặn lẻ: gỡ theo hình có test riêng
    orig = cong.cong_vanh_ngang

    def chan_oan(track, ti_le):
        orig(track, ti_le)
        for e in track:
            if e["frame"] in (30, 31) and e["state"] in cong.DA_CHAC:
                e["state"] = cong.CHAN_VANH
    monkeypatch.setattr(cong, "cong_vanh_ngang", chan_oan)
    _, v = _chay(clip)
    assert {30, 31} <= {e["frame"] for e in v.khung_render} and v.nhay["pct_nhay"] == 0
    monkeypatch.setattr(cong, "go_chan_le", lambda track, toi_da=None: 0)
    _, v = _chay(clip)
    assert not {30, 31} & {e["frame"] for e in v.khung_render} and v.nhay["so_lan_doi"] == 2
