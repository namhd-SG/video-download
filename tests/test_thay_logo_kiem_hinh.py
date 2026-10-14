"""Kiểm hình trước khi dán + gỡ chặn theo hình, trên clip TỔNG HỢP có ground truth. Mỗi tính năng có đột biến chứng minh fixture
phân định được (tắt tính năng ⇒ lỗi cũ quay lại)."""
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless")

from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import cong, duong_ong  # noqa: E402

A, B = (30, 60), (230, 520)
VANG = set(range(35, 45))  # logo TẮT 10 khung giữa hai lần hiện ở hai chỗ khác nhau


def _clip_nhay_co_vang():
    return tao_clip(n=70, duong_di=lambda i: A if i < 35 else B, vang_khung=VANG)


def _vet(clip, khung=(5, 27, 50)):
    kq = duong_ong.xu_ly_video(clip.nguon, clip.box_moi(khung=khung))
    assert len(kq.vet) == 1, [v.ly_do for v in kq.vet]
    return kq.vet[0]


def test_lo_qua_buoc_nhay_logo_tat_khong_dan_vao_cho_trong():
    """test_2: lấp lỗ giữ chỗ cũ nửa đầu lỗ, chỗ mới nửa sau, không nhìn ảnh ⇒ dán logo lên nền trống khi logo tắt. Kiểm hình bác."""
    v = _vet(_clip_nhay_co_vang())
    ren = {e["frame"] for e in v.khung_render}
    assert not ren & VANG
    assert set(range(5, 33)) <= ren and set(range(47, 68)) <= ren  # hai chỗ thật vẫn được che


def test_dot_bien_tat_kiem_hinh_thi_dan_vao_cho_trong(monkeypatch):
    monkeypatch.setattr(duong_ong, "kiem_hinh_truoc_dan", lambda nguon, track, mau: {})
    v = _vet(_clip_nhay_co_vang())
    assert {e["frame"] for e in v.khung_render} & VANG


def _e(f, st, score=0.9):
    return {"frame": f, "state": st, "score": score, "x": 10, "y": 10, "w": 40, "h": 20}


def test_go_theo_hinh_chi_go_tuong_phan_va_vanh_khi_hinh_khop_va_khong_net_la():
    """Vùng tối Test3: khung bị cổng tương phản chặn mà hình khớp + không nét lạ ⇒ che lại, tấm nền hẹp. Cổng phụ đề / nét lạ không
    gỡ; hình dưới sàn hoặc có nét lạ ⇒ giữ chặn. (Tích hợp trên video thật: v01/v04/v05 — xem nghiệm thu.)"""
    tr = [_e(0, "detected"), _e(1, cong.CHAN_TUONG_PHAN), _e(2, cong.CHAN_VANH), _e(3, cong.CHAN_PHU_DE), _e(4, cong.CHAN_NET),
          _e(5, cong.CHAN_TUONG_PHAN, 0.3), _e(6, cong.CHAN_VANH), _e(7, "detected")]
    net = {1: 0.0, 2: 0.01, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.2}
    assert cong.go_chan_theo_hinh(tr, net, san=0.6) == 2
    assert [e["state"] for e in tr] == ["detected", "detected", "detected", cong.CHAN_PHU_DE, cong.CHAN_NET,
                                        cong.CHAN_TUONG_PHAN, cong.CHAN_VANH, "detected"]
    assert tr[1]["plate_pad"] == cong.PAD_CHAT and tr[1]["chan_cu"] == cong.CHAN_TUONG_PHAN and tr[1]["go_hinh"]


def test_go_mot_phan_doan_chan_thi_go_chan_le_khong_go_an_theo_manh_con_lai():
    """Đoạn chặn 6 khung bị gỡ 4 ⇒ còn mẩu 2 khung (đã xét, trượt): go_chan_le (gỡ đoạn ≤3) không được gỡ chúng."""
    tr = [_e(0, "detected")] + [_e(i, cong.CHAN_VANH) for i in range(1, 7)] + [_e(7, "detected")]
    net = {i: (0.5 if i in (3, 4) else 0.0) for i in range(1, 7)}
    assert cong.go_chan_theo_hinh(tr, net, san=0.6) == 4
    cong.go_chan_le(tr)
    assert tr[3]["state"] == cong.CHAN_VANH and tr[4]["state"] == cong.CHAN_VANH


def test_doan_chan_khong_go_duoc_khung_nao_van_theo_go_chan_le_cu():
    tr = [_e(0, "detected"), _e(1, cong.CHAN_VANH, 0.1), _e(2, cong.CHAN_VANH, 0.1), _e(3, "detected")]
    assert cong.go_chan_theo_hinh(tr, {1: 0.0, 2: 0.0}, san=0.6) == 0
    assert cong.go_chan_le(tr) == 2
