"""Lõi thay logo trên clip TỔNG HỢP có ground truth: đường ống chạy đúng, và mỗi lớp an toàn có ĐỘT BIẾN chứng minh nó đang chặn.

Mẫu mỗi test an toàn: (1) có lớp ⇒ không khung nguy hiểm nào được render; (2) gỡ đúng lớp đó bằng monkeypatch ⇒ khung nguy hiểm
LỌT vào danh sách render. Vế (2) là bằng chứng fixture có sức phân định — thiếu nó thì vế (1) xanh cũng không nói lên gì.
"""
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

import cv2  # noqa: E402
from thay_logo_tong_hop import tam_lech, tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import qua_chu as qua_chu_mod  # noqa: E402
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


def test_hat_giong_hai_box_van_thanh_vet_dung_cho_nhung_cho_nguoi_duyet():
    """Cụm 1–2 box (trước đây vứt theo MIN_BOX=3) là HẠT GIỐNG: dựng mẫu từ box có, dò các khung còn lại — vết hiện cho người duyệt.
    Nhưng KHÔNG tự render: mẫu 1–2 crop có thể là nền (dán sai chỗ tệ hơn sót, ĐP 14/10)."""
    clip = tao_clip()
    for khung in ((5, 15), (30,)):
        # box vẽ tay vẫn được dò đầy đủ (hạt giống agy nhỏ thì bỏ dò, xem test_hat_giong_agy_nho_khong_dung_tim_kiem_day_du)
        kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=khung, nguon="tay"))
        assert kq.trang_thai == "cho_nguoi" and len(kq.vet) == 1, khung
        v = kq.vet[0]
        assert v.khung_render == [] and f"{len(khung)} box" in v.ly_do
        dinh = [e for e in v.track if "x" in e]
        assert len(dinh) >= 50
        assert max(tam_lech(e, clip.hop_that[e["frame"]]) for e in dinh) <= 3


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
    # cụm giả 1 box agy nay bị chặn ngay ở hạt giống nhỏ (không dò) thay vì rơi ở cổng bằng chứng
    assert len(bo) == 1 and bo[0]["nhan"] == "cụm 2" and "1 box" in bo[0]["ly_do"]
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


# Job 2 (20/10, "Test 03_12"): logo trong suốt trôi; cụm 0 gom 3 box agy ở 3 chỗ, vết bám má/mắt. Toạ độ thật từ tl_box_moi + track.json.
_CUM_JOB2 = [BoxMoi(115, 192, 97, 61, 53), BoxMoi(192, 97, 110, 54, 56), BoxMoi(422, 182, 79, 43, 30)]


def _track_job2(k115: dict) -> list[dict]:
    return [dict({"frame": 115, "x": 215, "y": 225, "w": 60, "h": 52, "score": 0.324}, **k115),  # má, cách box mồi ~130 px
            {"frame": 192, "state": "hidden"},  # vết không phủ khung này
            {"frame": 422, "state": "detected", "x": 166, "y": 79, "w": 68, "h": 59, "score": 0.776}]  # trùng box (logo đè mắt)


def test_cong_khop_khung_box_bi_chan_ma_vet_lech_thi_dem_lech():
    """Vết bám mặt qua cổng chỉ nhờ 1 box khớp khi box kia rơi vào khung bị cổng nội dung chặn ⇒ phải trượt cổng — kể cả khi ô đó
    mang `giu_chan` (đoạn chặn bị gỡ một phần, hoặc nối qua chữ mà hai đầu cùng nằm trên mặt)."""
    for k115 in ({"state": cong.CHAN_NET}, {"state": cong.CHAN_NET, "giu_chan": True}):
        kq = cong.cong_khop(_track_job2(k115), _CUM_JOB2)
        assert (kq["khop"], kq["lech"], kq["track_vang"]) == (1, 1, 1)
        assert not kq["qua_cong"]
    assert not cong.cong_khop(_track_job2({"state": "detected"}), _CUM_JOB2)["qua_cong"]  # đối chứng: đúng như prod 20/10


def _track_chan(k: int, **o) -> list[dict]:
    track = [{"frame": i, "x": 100, "y": 100, "w": 50, "h": 20, "state": "detected", "score": 0.8} for i in range(10)]
    for i in (k - 1, k, k + 1):
        track[i] = dict(track[i], state=cong.CHAN_NET, x=300)  # bị chặn và lệch box
    track[k] = dict(track[k], **o)
    return track


@pytest.mark.parametrize("o", [
    {"x": 100},  # một ô trong ±1 trùng box: vết có mặt đúng chỗ, chỉ bị chặn
    {"state": "filled"},  # ô DA_CHAC xét trước như cũ ⇒ không vào nhánh chặn
], ids=["mot-o-trung", "da-chac-truoc"])
def test_cong_khop_o_bi_chan_khong_lam_hong_vet_dung(o):
    boxes = [BoxMoi(1, 100, 100, 50, 20), BoxMoi(5, 100, 100, 50, 20)]
    track = _track_chan(5, **o)
    if o.get("state") == "filled":
        track[5]["x"] = 100
    kq = cong.cong_khop(track, boxes)
    assert kq["lech"] == 0 and kq["qua_cong"]


@pytest.mark.parametrize("o", [
    {"score": None},  # ô lấp mù: toạ độ giữ góc cũ, bộ dò không bắt gì ở đó
    {"state": "hidden_hinh"},  # kiểm hình đã bác: không có logo ở đó
    {"giu_chan": True, "qua_chu_khop": True},  # nối qua chữ, đường nối đi qua box ⇒ ô lệch là dò sai dưới chữ
], ids=["lap-mu", "kiem-hinh-bac", "qua-chu-khop"])
def test_cong_khop_o_bi_chan_khong_phai_bang_chung_thi_la_vang(o):
    boxes = [BoxMoi(1, 100, 100, 50, 20), BoxMoi(5, 100, 100, 50, 20)]
    track = _track_chan(5, **o)
    for i in (4, 6):
        track[i] = dict(track[i], **o)
    kq = cong.cong_khop(track, boxes)
    assert (kq["khop"], kq["lech"], kq["track_vang"]) == (1, 0, 1) and kq["qua_cong"]


# --- Lớp: bộ lọc ứng viên phụ đề trong C (chữ trắng viền đen) ---

def test_phu_de_vien_den_khong_bao_gio_duoc_render(monkeypatch):
    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # kiểm RIÊNG lớp cổng: tắt che qua chữ (có test riêng ở test_thay_logo_qua_chu.py)
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
    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # kiểm RIÊNG lớp cổng: tắt che qua chữ (có test riêng ở test_thay_logo_qua_chu.py)
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

def test_phu_de_bong_mo_bi_cong_vanh_ngang_chan(monkeypatch):
    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # kiểm RIÊNG lớp cổng: tắt che qua chữ (có test riêng ở test_thay_logo_qua_chu.py)
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
    monkeypatch.setattr(cong, "go_chan_theo_hinh", lambda track, net, san: 0)  # cô lập ngưỡng học: gỡ theo hình có test riêng
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
    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # kiểm RIÊNG lớp cổng: tắt che qua chữ (có test riêng ở test_thay_logo_qua_chu.py)
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

def test_khoi_chu_trong_box_bi_cong_net_la_chan(monkeypatch):
    monkeypatch.setattr(qua_chu_mod, "GAP_MAX", -1)  # kiểm RIÊNG lớp cổng: tắt che qua chữ (có test riêng ở test_thay_logo_qua_chu.py)
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


def test_vet_vong_hai_tu_box_sot_khong_tu_render_va_khong_box_nao_roi_mat(monkeypatch):
    """Box mà vết vòng một không phủ ⇒ vòng hai dò lại. Vết vòng hai học mẫu từ 1–2 box, dễ bám nền tĩnh (đo v24 L2: logo dán lên
    chân người cả video, video vẫn `render`) ⇒ phải ra `cho_nguoi` kèm lý do, và box đó phải có dấu vết trong `vet_bi_bo`."""
    a = [BoxMoi(k, 10, 10, 40, 20, cum=0) for k in (0, 5, 10)]
    sot = BoxMoi(15, 300, 200, 40, 20, cum=0)  # cùng số cụm nhưng ở chỗ khác: vết của cụm 0 không phủ
    goi = []

    def gom_gia(boxes, nguon):
        return [list(boxes)]

    def vet_gia(nguon, cl, moi_box=None):
        goi.append(list(cl))
        dau = cl[0]
        return duong_ong.KetQuaVet("render", len(cl), track=[{"frame": f, "x": dau.x, "y": dau.y, "w": dau.w, "h": dau.h} for f in range(20)],
                                   khung_render=[{"frame": f} for f in range(20)])
    monkeypatch.setattr(duong_ong, "gom_vet", gom_gia)
    monkeypatch.setattr(duong_ong, "xu_ly_vet", vet_gia)
    kq = duong_ong.xu_ly_video(object(), a + [sot])
    assert [len(c) for c in goi] == [4, 1]  # vòng hai chạy đúng trên box sót
    assert kq.trang_thai == "cho_nguoi" and duong_ong.LY_DO_VONG_HAI in kq.ly_do
    vong_hai = kq.vet[1]
    assert vong_hai.trang_thai == "cho_nguoi" and vong_hai.khung_render == []  # không một khung nào được dán logo
    assert len(kq.vet) == 2 and vong_hai.box_cum == 1  # box sót có dấu vết riêng, không rơi mất


def test_cum_hat_giong_duoi_cum_lon_o_vong_mot_duoc_do_nhung_khong_tu_render(monkeypatch):
    """Cụm 1 box mang số cụm riêng (agy gán nhãn không ổn định) ⇒ mẫu từ 1 crop có thể là nền; tái hiện v24 L2: logo dán lên chân
    người cả video. Phải ra `cho_nguoi` kèm lý do; cụm đủ `CUM_LON` box vẫn render."""
    lon = [BoxMoi(k, 10, 10, 40, 20, cum=0) for k in (0, 5, 10)]
    nho = [BoxMoi(32, 300, 200, 40, 20, cum=1)]

    def vet_gia(nguon, cl, moi_box=None):
        dau = cl[0]
        return duong_ong.KetQuaVet("render", len(cl), track=[{"frame": f, "x": dau.x, "y": dau.y, "w": dau.w, "h": dau.h} for f in range(40)],
                                   khung_render=[{"frame": f} for f in range(40)])
    monkeypatch.setattr(duong_ong, "gom_vet", lambda boxes, nguon: [lon, nho])
    monkeypatch.setattr(duong_ong, "xu_ly_vet", vet_gia)
    kq = duong_ong.xu_ly_video(object(), lon + nho)
    assert [v.trang_thai for v in kq.vet] == ["render", "cho_nguoi"]
    assert kq.vet[1].khung_render == [] and "1 box" in kq.vet[1].ly_do
    assert kq.trang_thai == "cho_nguoi"


def _nguon_logo_o(x: int, y: int, w: int = 40, h: int = 16, rong: int = 240, cao: int = 160, n: int = 3):
    """Khung xám có cùng một mảng hoa văn (logo) ở (x, y) — đủ để dựng mẫu từ crop."""
    import numpy as np

    from tiktok_music_downloader.thay_logo.nguon_khung import NguonKhungMang

    rng = np.random.default_rng(7)
    logo = rng.integers(0, 255, (h, w), dtype=np.uint8)
    khung = []
    for _ in range(n):
        g = rng.integers(90, 110, (cao, rong), dtype=np.uint8)
        g[y:y + h, x:x + w] = logo
        khung.append(g)
    return NguonKhungMang(khung)


def test_box_moi_sat_mep_phai_duoi_van_dung_duoc_mau():
    """Test 03_22: box agy sát mép phải — nới 10% vượt khung 1 px ⇒ lát cắt hụt ⇒ 'không dựng được mẫu'. Kẹp biên ⇒ dựng được."""
    nguon = _nguon_logo_o(200, 144)  # logo chạm mép phải (240) và mép dưới (160)
    moi = BoxMoi(0, 200, 144, 40, 16)
    assert mau_mod.no_box_moi(moi) != mau_mod.no_box_moi(moi, 240, 160)  # nới thô vượt khung
    assert mau_mod.dung_mau_sach(nguon, moi, [BoxMoi(k, 200, 144, 40, 16) for k in range(3)]) is not None


def test_box_moi_giua_khung_kep_bien_khong_doi_gi():
    nguon = _nguon_logo_o(100, 60)
    moi = BoxMoi(0, 100, 60, 40, 16)
    assert mau_mod.no_box_moi(moi) == mau_mod.no_box_moi(moi, 240, 160)
    assert mau_mod.dung_mau_sach(nguon, moi, [BoxMoi(k, 100, 60, 40, 16) for k in range(3)]) is not None


# --- Dọn lỗi GĐ1: đếm box tĩnh, bỏ dò hạt giống nhỏ ---

def test_so_box_tinh_chi_dem_box_dung_yen_cung_cho():
    tinh = [BoxMoi(k, 10, 10, 40, 20, cum=0) for k in (0, 10, 20)]  # cùng chỗ, cách ≥ 10 khung ⇒ 3
    nhay_bac = [BoxMoi(k, 10 + 100 * i, 10, 40, 20, cum=0) for i, k in enumerate((0, 10, 20, 30))]  # mỗi chỗ một box ⇒ 1
    gan_khung = [BoxMoi(k, 10, 10, 40, 20, cum=0) for k in (0, 3, 6)]  # cách < 10 khung không tính ⇒ 1
    assert duong_ong._so_box_tinh(tinh) == 3
    assert duong_ong._so_box_tinh(nhay_bac) == 1 and duong_ong._so_box_tinh(gan_khung) == 1
    assert duong_ong._so_box_tinh([]) == 0


def test_bang_chung_tach_nen_dung_so_box_tinh_chu_khong_phai_so_box():
    """Cụm 6 box nhảy bậc (tĩnh = 1) mà điểm khớp không tách khỏi nền ⇒ vẫn phải bị chặn; trước đây `len(cum)=6 ≥ CUM_LON` bỏ qua phép tách."""
    det = {t: {"x": 10, "y": 10, "score": 0.1} for t in range(10, 30)}
    tt = {"nen95": 0.5}
    assert "nền nhiễu" in duong_ong._bang_chung(det, {0}, 6, tt, so_box_tinh=1)
    assert duong_ong._bang_chung(det, {0}, 6, tt, so_box_tinh=3) == ""  # đủ box đứng yên ⇒ không cần tách nền
    assert duong_ong._bang_chung(det, {0}, 6, tt) == ""  # không truyền ⇒ dùng số box như cũ


def test_xu_ly_vet_truyen_so_box_tinh_vao_bang_chung(monkeypatch):
    clip = tao_clip()
    thay = []
    that = duong_ong._bang_chung
    monkeypatch.setattr(duong_ong, "_bang_chung", lambda *a, **k: (thay.append(a), that(*a, **k))[1])
    cum = clip.box_moi()
    duong_ong.xu_ly_vet(clip.nguon, cum)
    assert len(thay) == 1 and thay[0][4] == duong_ong._so_box_tinh(cum)


def test_hat_giong_agy_nho_khong_dung_tim_kiem_day_du(monkeypatch):
    """Cụm < CUM_LON box từ agy không bao giờ tự render ⇒ vòng một không chạy `xu_ly_vet` (khỏi vết/ảnh rác); cụm có box vẽ tay thì vẫn dò."""
    goi = []
    monkeypatch.setattr(duong_ong, "xu_ly_vet", lambda nguon, cl, *a, **k: goi.append(list(cl)) or duong_ong.KetQuaVet("cho_nguoi", len(cl)))
    monkeypatch.setattr(duong_ong, "gom_vet", lambda boxes, nguon: [list(boxes)])
    agy = [BoxMoi(0, 10, 10, 40, 20, cum=4), BoxMoi(5, 10, 10, 40, 20, cum=4)]
    kq = duong_ong.xu_ly_video(object(), agy)
    assert goi == [] and kq.trang_thai == "cho_nguoi" and len(kq.vet) == 1
    v = kq.vet[0]
    assert v.box_cum == 2 and v.nhan == "cụm 4" and v.track == [] and v.khung_render == []
    assert v.ly_do == duong_ong.LY_DO_HAT_GIONG_NHO.format(n=2)
    tay = [BoxMoi(0, 10, 10, 40, 20, nguon="tay"), BoxMoi(5, 10, 10, 40, 20, nguon="agy")]
    duong_ong.xu_ly_video(object(), tay)
    assert len(goi) == 1

