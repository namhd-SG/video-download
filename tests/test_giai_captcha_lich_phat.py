"""Giải captcha trong popup — phần THUẦN: lịch phát với D (đồng hồ GIẢ), đổi đơn vị toạ độ, kiểm đầu
vào, khoá điều khiển theo token, sắp lô theo `seq`, D từ env. Không trình duyệt, không mạng.

Test v9 cũ không có sức phân định (bước 16 ms vs ngưỡng 15 ms ⇒ "phát nhanh 2×" XANH giả; toạ độ nguyên
⇒ đột biến làm tròn XANH giả) nên ở đây so BẰNG NHAU từng khoảng với thời điểm gốc, và toạ độ chọn để
hệ số 1,6 sinh phần lẻ ≥ 0,5.
"""
from __future__ import annotations

import logging
import math

import pytest

from web import giai_captcha as gc
from web.giai_captcha import BoPhatLai, LoiGiai, PhienGiai, SuKien

DEVICE_W, DEVICE_H, KHUNG_W = 1280.0, 900.0, 800.0
KHUNG_H = KHUNG_W * DEVICE_H / DEVICE_W


def _ev(k, x, y, t, buttons=0, dx=0.0, dy=0.0):
    return SuKien(k=k, x=float(x), y=float(y), t=float(t), buttons=buttons, dx=dx, dy=dy)


def chuoi_nguoi():
    """Một gesture kéo: nhấn, kéo với các khoảng nghỉ 16/60/150/400 ms, nhả. t là ms của popup."""
    gaps = [0, 16, 16, 60, 16, 150, 16, 400, 16, 16, 60, 16]
    t, ra = 5000.0, []
    for i, g in enumerate(gaps):
        t += g
        if i == 0:
            ra.append(_ev("down", 10 + i, 20, t, 1))
        elif i == len(gaps) - 1:
            ra.append(_ev("up", 10 + i, 20, t, 0))
        else:
            ra.append(_ev("move", 10 + i * 3.7, 20 + i, t, 1))
    return ra


def mo_phong(d_ms, lo_toi):
    """Chạy `BoPhatLai` theo từng sự kiện thời gian (không lấy mẫu ⇒ không có sai số đo).
    `lo_toi` = [(t_toi_giay, [SuKien])] đã sắp theo t_toi. Trả ([(t_phat_giay, ev)], bo_phat)."""
    bp = BoPhatLai(d_ms)
    i, ra = 0, []
    while i < len(lo_toi) or bp.con_hang():
        toi = lo_toi[i][0] if i < len(lo_toi) else math.inf
        han = bp.diem_ke_tiep()
        han = math.inf if han is None else han
        if toi <= han:
            bp.nhan_lo(lo_toi[i][1], toi)
            i += 1
        else:
            for ev in bp.den_han(han):
                ra.append((han, ev))
    return ra, bp


def chia_lo(events, cua_so_ms=40.0):
    """Gom lô như popup: một lô đóng khi sự kiện kế cách sự kiện ĐẦU của lô quá `cua_so_ms`."""
    lo, hien = [], []
    for e in events:
        if hien and e.t - hien[0].t > cua_so_ms:
            lo.append(hien)
            hien = []
        hien.append(e)
    if hien:
        lo.append(hien)
    return lo


def lich_toi(lo, goc_giay=50.0, rtt=0.0, tre=None):
    """Lô tới lúc `sự kiện đầu của lô + 40 ms + rtt` theo đồng hồ máy chủ. `tre` = {chỉ số lô: giây trễ thêm}."""
    ra = []
    for i, l in enumerate(lo):
        ra.append((goc_giay + l[0].t / 1000.0 + 0.040 + rtt + (tre or {}).get(i, 0.0), l))
    return ra


# ---------------------------------------------------------------------------
# Lịch phát: t_gốc + D, đủ điểm, đúng thứ tự
# ---------------------------------------------------------------------------

def test_lich_phat_dung_t_goc_cong_D_khi_khong_tre():
    ev = chuoi_nguoi()
    d = 120
    lo_toi = lich_toi(chia_lo(ev))
    assert len(lo_toi) >= 5, "chuỗi phải trải qua nhiều lô"
    ra, bp = mo_phong(d, lo_toi)
    anh_xa = lo_toi[0][0] - ev[0].t / 1000.0
    assert len(ra) == len(ev), "đủ điểm, không thêm không bớt"
    assert [e for _, e in ra] == ev, "đúng thứ tự, đúng toạ độ (không nội suy/làm tròn)"
    for (t_phat, e) in ra:
        assert t_phat == pytest.approx(e.t / 1000.0 + anh_xa + d / 1000.0, abs=1e-9)
    assert bp.tre_qua_D == 0


def test_lo_tre_doi_pha_dung_mot_khoang_dai_ra_va_moi_khoang_sau_bang_goc():
    """ĐP-609 câu 1. Đột biến "phát ngay khi trễ" (nén) ⇒ các khoảng sau điểm trễ bị nén ⇒ ĐỎ."""
    ev = chuoi_nguoi()
    d = 120
    lo = chia_lo(ev)
    tre_them = 0.300
    lo_toi = lich_toi(lo, tre={2: tre_them + d / 1000.0})   # lô 2 tới trễ hơn D
    ra, bp = mo_phong(d, lo_toi)
    assert [e for _, e in ra] == ev
    goc = [(b.t - a.t) / 1000.0 for a, b in zip(ev, ev[1:])]
    that = [b[0] - a[0] for a, b in zip(ra, ra[1:])]
    khac = [i for i, (g, h) in enumerate(zip(goc, that)) if abs(g - h) > 1e-9]
    chi_so_dau_lo_2 = sum(len(l) for l in lo[:2])
    assert khac == [chi_so_dau_lo_2 - 1], f"đúng MỘT khoảng (trước sự kiện đầu lô trễ) khác gốc: {khac}"
    i = khac[0]
    assert that[i] - goc[i] == pytest.approx(tre_them, abs=1e-9), "dài ra đúng bằng phần trễ vượt D"
    assert all(abs(goc[j] - that[j]) <= 1e-9 for j in range(i + 1, len(goc))), "mọi khoảng SAU = gốc"
    assert bp.tre_qua_D == 1


def test_khoang_dai_ra_bang_dung_do_tre_vuot_D():
    """Khoảng dài ra = (độ trễ thật của sự kiện) − D, không hơn không kém."""
    d = 120
    a = _ev("down", 1, 1, 1000.0, 1)
    b = _ev("move", 2, 2, 1016.0, 1)
    c = _ev("move", 3, 3, 1032.0, 1)
    # a tới đúng giờ; b+c cùng một lô tới trễ 500 ms sau thời điểm b được tạo ra.
    ra, bp = mo_phong(d, [(10.0, [a]), (10.0 + 0.016 + 0.500, [b, c])])
    that = [t for t, _ in ra]
    assert that[0] == pytest.approx(10.0 + 0.120)
    # b phát ngay lúc nó tới (lịch bị dời đúng bằng độ trễ), c cách b đúng 16 ms như gốc.
    assert that[1] == pytest.approx(10.0 + 0.016 + 0.500)
    assert that[2] - that[1] == pytest.approx(0.016)
    assert bp.tre_qua_D == 1


def test_khong_noi_suy_them_diem_khi_khoang_nghi_dai():
    ev = [_ev("move", 5, 5, 0.0), _ev("move", 6, 6, 400.0)]
    ra, _ = mo_phong(120, [(1.0, ev)])
    assert len(ra) == 2 and [e for _, e in ra] == ev
    assert ra[1][0] - ra[0][0] == pytest.approx(0.400)


def test_dot_moi_sau_khi_hang_doi_rong_anh_xa_lai():
    """Hai đợt cách nhau lâu: đợt sau lấy ánh xạ mới, không mang độ trễ đã dời của đợt trước."""
    ra, bp = mo_phong(120, [(1.0, [_ev("move", 1, 1, 100.0)]),
                           (9.0, [_ev("move", 2, 2, 5000.0)])])
    assert ra[0][0] == pytest.approx(1.0 + 0.120)
    assert ra[1][0] == pytest.approx(9.0 + 0.120)


def test_lich_lech_bat_thuong_bi_tu_choi():
    bp = BoPhatLai(120)
    with pytest.raises(LoiGiai) as e:
        bp.nhan_lo([_ev("move", 1, 1, 0.0), _ev("move", 2, 2, 60_000.0)], 5.0)
    assert e.value.ma == 400


# ---------------------------------------------------------------------------
# Huỷ gesture: tàn dư không lọt sang trang
# ---------------------------------------------------------------------------

def test_huy_gesture_bo_tan_du_den_khi_co_down_moi():
    bp = BoPhatLai(120)
    bp.nhan_lo([_ev("down", 1, 1, 0.0, 1), _ev("move", 2, 2, 16.0, 1)], 1.0)
    bp.huy()
    assert bp.diem_ke_tiep() is None
    bp.nhan_lo([_ev("move", 3, 3, 32.0, 1),     # tàn dư kéo của gesture cũ
                _ev("up", 3, 3, 48.0, 0),       # `up` mồ côi
                _ev("move", 4, 4, 64.0, 0),     # hover: người vẫn di chuột ⇒ phát
                _ev("down", 5, 5, 80.0, 1),
                _ev("up", 5, 5, 96.0, 0)], 2.0)
    kinds = [e.k for e in bp.den_han(100.0)]
    assert kinds == ["move", "down", "up"]
    assert bp.so_bo == 2


def test_up_khong_co_down_di_truoc_bi_bo():
    bp = BoPhatLai(120)
    bp.nhan_lo([_ev("up", 1, 1, 0.0, 0)], 1.0)
    assert bp.den_han(10.0) == [] and bp.so_bo == 1


# ---------------------------------------------------------------------------
# Đổi đơn vị toạ độ + kiểm đầu vào + tham số CDP
# ---------------------------------------------------------------------------

def test_doi_don_vi_khong_lam_tron_va_khong_cong_scroll():
    x, y = gc.doi_don_vi(3, 7, KHUNG_W, DEVICE_W)
    assert (x, y) == (3 * 1.6, 7 * 1.6)  # 4.8 và 11.2: phần lẻ GIỮ NGUYÊN
    assert x != round(x) and y != round(y)


def test_kiem_su_kien_doi_don_vi_va_giu_buttons_nguyen():
    ev = gc.kiem_su_kien({"k": "move", "x": 3, "y": 7, "t": 12.5, "buttons": 0},
                         KHUNG_W, KHUNG_H, DEVICE_W)
    assert (ev.x, ev.y, ev.t, ev.buttons) == (3 * 1.6, 7 * 1.6, 12.5, 0)


@pytest.mark.parametrize("raw", [
    {"k": "move", "x": float("nan"), "y": 1, "t": 1, "buttons": 0},
    {"k": "move", "x": 1, "y": float("inf"), "t": 1, "buttons": 0},
    {"k": "move", "x": 1, "y": 1, "t": float("nan"), "buttons": 0},
    {"k": "move", "x": -0.5, "y": 1, "t": 1, "buttons": 0},                 # ngoài khung
    {"k": "move", "x": 1, "y": KHUNG_H + 1, "t": 1, "buttons": 1},          # ngoài khung
    {"k": "move", "x": 801, "y": 1, "t": 1, "buttons": 1},                  # ngoài khung
    {"k": "wheel", "x": 1, "y": 1, "t": 1, "buttons": 0, "dx": 0, "dy": 40, "delta_mode": 1},
    {"k": "wheel", "x": 1, "y": 1, "t": 1, "buttons": 0, "dx": 0},          # thiếu dy
    {"k": "click", "x": 1, "y": 1, "t": 1, "buttons": 0},
    {"k": "move", "x": 1, "y": 1, "t": 1, "buttons": 99},
    {"k": "move", "x": True, "y": 1, "t": 1, "buttons": 0},
    "không phải dict",
])
def test_kiem_su_kien_tu_choi_va_huy_gesture(raw):
    with pytest.raises(LoiGiai) as e:
        gc.kiem_su_kien(raw, KHUNG_W, KHUNG_H, DEVICE_W)
    assert e.value.ma == 400 and e.value.huy_gesture is True


def test_nut_phai_giua_bi_bo_khong_phat():
    for b in (2, 3, 4):
        assert gc.kiem_su_kien({"k": "down", "x": 1, "y": 1, "t": 1, "buttons": b},
                               KHUNG_W, KHUNG_H, DEVICE_W) is None


def test_tham_so_cdp_hover_buttons_0_va_keo_buttons_1():
    hover = gc.tham_so_cdp(_ev("move", 1.5, 2.5, 0, 0))
    assert hover == {"type": "mouseMoved", "x": 1.5, "y": 2.5, "button": "none", "buttons": 0}
    keo = gc.tham_so_cdp(_ev("move", 1.5, 2.5, 0, 1))
    assert keo["buttons"] == 1 and keo["button"] == "left"
    assert gc.tham_so_cdp(_ev("down", 1, 2, 0, 1)) == {
        "type": "mousePressed", "x": 1, "y": 2, "button": "left", "buttons": 1, "clickCount": 1}
    assert gc.tham_so_cdp(_ev("up", 1, 2, 0, 0))["type"] == "mouseReleased"
    w = gc.tham_so_cdp(_ev("wheel", 5, 6, 0, 0, dx=0.0, dy=400.0))
    assert w["type"] == "mouseWheel" and w["deltaY"] == 400.0 and w["deltaX"] == 0.0


# ---------------------------------------------------------------------------
# PhienGiai: khoá theo token, sắp lô theo seq, thiếu lô, nối lại
# ---------------------------------------------------------------------------

class DongHoGia:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def dh(monkeypatch):
    d = DongHoGia()
    monkeypatch.setattr(gc, "dong_ho", d)
    return d


def _phien():
    p = PhienGiai(1, "chu@x.vn", "dang_giai", d_ms=120)
    assert p.nhan_khoa("token-aaaaaaaa", "chu@x.vn") is True
    return p


def test_lo_toi_lech_thu_tu_duoc_phat_dung_thu_tu_seq(dh):
    """ĐỘT BIẾN: bỏ sắp lại theo `seq` (đưa lô vào lịch theo thứ tự TỚI) ⇒ ĐỎ."""
    p = _phien()
    lo = [[_ev("move", 1, 1, 0.0)], [_ev("move", 2, 2, 16.0)], [_ev("move", 3, 3, 32.0)]]
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 2, lo[2])
    assert p.expected_seq == 0 and p.den_han(dh.t + 5) == []
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 1, lo[1])
    assert p.expected_seq == 0
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 0, lo[0])
    assert p.expected_seq == 3
    thu_tu = [e.x for e in p.den_han(dh.t + 5)]
    assert thu_tu == [1.0, 2.0, 3.0]


def test_lo_bi_tu_choi_toi_truoc_lo_down_van_huy_dung_gesture(dh):
    """Review F1: POST song song ⇒ lô 1 (điểm ngoài khung, 400) tới TRƯỚC lô 0 (`down`). Huỷ phải áp
    ĐÚNG chỗ lô 1 trong dãy `seq`: `down` của lô 0 bị bỏ khỏi hàng đợi, tàn dư (move có nút, `up`) của
    lô 2 bị bỏ — trang không nhận lần kéo thiếu đoạn giữa rồi NỘP.
    ĐỘT BIẾN: `bo_lo` huỷ NGAY thay vì đặt mốc ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    p.bo_lo(tk, chu, 1)                                                        # lô 400 tới đầu tiên
    p.nhan_lo(tk, chu, 2, [_ev("move", 50, 1, 48.0, 1), _ev("up", 50, 1, 64.0, 0)])
    p.nhan_lo(tk, chu, 0, [_ev("down", 20, 1, 0.0, 1), _ev("move", 30, 1, 16.0, 1)])
    assert p.expected_seq == 3
    assert p.den_han(dh.t + 5) == [], "gesture có lô bị từ chối không được phát điểm nào"
    assert p.lay_huy() == "lo_bi_tu_choi"
    # Gesture MỚI sau đó vẫn chạy bình thường.
    p.nhan_lo(tk, chu, 3, [_ev("down", 5, 5, 200.0, 1), _ev("up", 5, 5, 216.0, 0)])
    assert [e.k for e in p.den_han(dh.t + 5)] == ["down", "up"]


def test_lo_bi_tu_choi_chinh_la_lo_down_khong_lot_tan_du_keo(dh):
    """captchahf R16b: lô 0 (chứa `down`) bị từ chối ⇒ move có nút + `up` của lô 1 là tàn dư, không phát.
    Đối chứng: gesture hợp lệ sau đó vẫn phát đủ. ĐỘT BIẾN: bỏ luật chặn move có nút khi chưa có
    `down` ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    p.bo_lo(tk, chu, 0)
    p.nhan_lo(tk, chu, 1, [_ev("move", 30, 1, 16.0, 1), _ev("up", 30, 1, 32.0, 0)])
    assert p.den_han(dh.t + 5) == []
    p.nhan_lo(tk, chu, 2, [_ev("move", 1, 1, 100.0, 0), _ev("down", 2, 2, 116.0, 1),
                           _ev("move", 3, 3, 132.0, 1), _ev("up", 3, 3, 148.0, 0)])
    assert [(e.k, e.buttons) for e in p.den_han(dh.t + 5)] == [("move", 0), ("down", 1), ("move", 1), ("up", 0)]


def test_lo_bi_tu_choi_dung_thu_tu_huy_ngay(dh):
    """Lô 400 tới ĐÚNG thứ tự (sau `down`) ⇒ huỷ ngay khi nó tới, như trước."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    p.nhan_lo(tk, chu, 0, [_ev("down", 20, 1, 0.0, 1)])
    p.bo_lo(tk, chu, 1)
    assert p.lay_huy() == "lo_bi_tu_choi" and p.den_han(dh.t + 5) == []


def test_dem_su_kien_phat_muon_vi_worker_tre(dh):
    """Review F2: worker gọi `den_han` muộn hơn lịch > ngưỡng ⇒ đếm `tre_phat_worker` (chỉ đo, chưa
    đổi cách phát). ĐỘT BIẾN: bỏ phép đếm ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    p.nhan_lo(tk, chu, 0, [_ev("move", 1, 1, 0.0), _ev("move", 2, 2, 16.0)])
    lich_dau = p.diem_ke_tiep()
    assert len(p.den_han(lich_dau)) == 1 and p.tre_phat_worker_tong() == 0     # đúng lịch
    assert len(p.den_han(lich_dau + 0.5)) == 1 and p.tre_phat_worker_tong() == 1  # muộn 0,5 s


def test_lo_trung_seq_phat_dung_mot_lan_ca_khi_da_xa_va_dang_cho(dh):
    """Popup thử lại lô sau timeout ⇒ máy chủ có thể nhận TRÙNG lô (request cũ thật ra đã tới). Mỗi sự
    kiện phải phát đúng MỘT lần. ĐỘT BIẾN: bỏ kiểm `seq < expected_seq` ⇒ ĐỎ; bỏ kiểm `seq in _cho_lo` ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    lo0 = [_ev("down", 1, 1, 0.0, 1), _ev("move", 2, 2, 16.0, 1)]
    assert p.nhan_lo(tk, chu, 0, lo0) == "ok"
    assert p.nhan_lo(tk, chu, 0, lo0) == "trung"                               # trùng lô ĐÃ xả
    lo2 = [_ev("up", 4, 4, 48.0, 0)]
    assert p.nhan_lo(tk, chu, 2, lo2) == "ok"                                  # tới sớm, đang chờ lô 1
    assert p.nhan_lo(tk, chu, 2, lo2) == "trung"                               # trùng lô ĐANG chờ
    assert p.nhan_lo(tk, chu, 1, [_ev("move", 3, 3, 32.0, 1)]) == "ok"
    assert [(e.k, e.x) for e in p.den_han(dh.t + 5)] == [("down", 1.0), ("move", 2.0), ("move", 3.0), ("up", 4.0)]


def test_huy_co_den_seq_bo_lo_toi_muon_va_lo_dang_cho_truoc_moc(dh):
    """ĐP-727 luật B: lô `seq < den_seq` tới SAU lệnh huỷ (vd bị abort vì timeout nhưng thật ra vẫn bay
    tới) ⇒ "trung", KHÔNG phát — `down` trong đó không còn ai huỷ. Lô tới sớm trong vùng đó cũng bỏ;
    lô sau mốc vẫn chạy bình thường. ĐỘT BIẾN: bỏ xử lý `den_seq` ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    assert p.nhan_lo(tk, chu, 0, [_ev("move", 1, 1, 0.0, 0)]) == "ok"
    assert p.nhan_lo(tk, chu, 2, [_ev("move", 9, 9, 40.0, 1)]) == "ok"       # tới sớm, chờ lô 1
    p.huy_gesture_cua_nguoi_giu(tk, chu, den_seq=3)                             # lô 1, 2 thuộc gesture bỏ
    assert p.nhan_lo(tk, chu, 1, [_ev("down", 5, 5, 20.0, 1)]) == "trung"     # lô 1 tới MUỘN
    assert p.nhan_lo(tk, chu, 3, [_ev("move", 6, 6, 300.0, 0), _ev("down", 7, 7, 316.0, 1),
                                  _ev("up", 7, 7, 332.0, 0)]) == "ok"
    assert [(e.k, e.x) for e in p.den_han(dh.t + 5)] == [("move", 6.0), ("down", 7.0), ("up", 7.0)]


def test_huy_den_seq_khong_xoa_lo_sau_moc_da_toi_som(dh):
    """Lô `seq >= den_seq` (cú nhấn MỚI) tới sớm, đang chờ, lúc lệnh huỷ tới: huỷ phải áp TRƯỚC khi xả
    lô đó — xả trước rồi huỷ thì huỷ xoá luôn cú nhấn mới. ĐỘT BIẾN: huỷ SAU khi xả ⇒ ĐỎ."""
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    assert p.nhan_lo(tk, chu, 0, [_ev("down", 1, 1, 0.0, 1)]) == "ok"
    assert p.nhan_lo(tk, chu, 2, [_ev("down", 7, 7, 300.0, 1), _ev("up", 7, 7, 316.0, 0)]) == "ok"
    p.huy_gesture_cua_nguoi_giu(tk, chu, den_seq=2)                             # lô 1 (gesture bỏ) chưa tới
    assert p.expected_seq == 3
    assert [(e.k, e.x) for e in p.den_han(dh.t + 5)] == [("down", 7.0), ("up", 7.0)]


def test_huy_den_seq_ngoai_khoang_400_khong_huy(dh):
    p = _phien()
    tk, chu = "token-aaaaaaaa", "chu@x.vn"
    for xau in (-1, gc.SEQ_NHAY_TOI_DA + 1):
        with pytest.raises(LoiGiai) as e:
            p.huy_gesture_cua_nguoi_giu(tk, chu, den_seq=xau)
        assert e.value.ma == 400
    assert p.lay_huy() is None and p.expected_seq == 0


def test_seq_cu_bi_bo_la_trung_va_nhay_xa_bi_tu_choi(dh):
    p = _phien()
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 0, [_ev("move", 1, 1, 0.0)])
    assert p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 0, [_ev("move", 1, 1, 0.0)]) == "trung"
    with pytest.raises(LoiGiai) as e:
        p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 10_000, [_ev("move", 1, 1, 0.0)])
    assert e.value.ma == 400


def test_token_khong_giu_khoa_bi_409(dh):
    p = _phien()
    with pytest.raises(LoiGiai) as e:
        p.nhan_lo("token-bbbbbbbb", "chu@x.vn", 0, [_ev("move", 1, 1, 0.0)])
    assert e.value.ma == 409
    with pytest.raises(LoiGiai):
        p.nhan_lo("token-aaaaaaaa", "nguoi.khac@x.vn", 0, [_ev("move", 1, 1, 0.0)])


def test_thieu_lo_qua_2_giay_huy_gesture_va_bo_qua_cho_hut(dh):
    p = _phien()
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 0, [_ev("down", 1, 1, 0.0, 1)])
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 2, [_ev("move", 2, 2, 50.0, 1)])  # thiếu lô 1
    dh.t += 1.9
    p.kiem_thieu_lo(dh.t)
    assert p.lay_huy() is None
    dh.t += 0.2
    p.kiem_thieu_lo(dh.t)
    assert p.lay_huy() == "thieu_lo"
    assert p.expected_seq == 3 and p.den_han(dh.t + 10) == []


def test_tab_sau_chi_xem_tab_dau_ngat_thi_tab_sau_lay_duoc():
    p = PhienGiai(1, "chu@x.vn", "dang_giai")
    assert p.nhan_khoa("token-aaaaaaaa", "chu@x.vn") is True
    assert p.nhan_khoa("token-bbbbbbbb", "chu@x.vn") is False      # cùng chủ, tab 2: chỉ xem
    assert p.anh_chup("token-bbbbbbbb", "chu@x.vn")["vai"] == "chi_xem"
    assert p.anh_chup("token-aaaaaaaa", "chu@x.vn")["vai"] == "dieu_khien"
    p.nha_khoa("token-aaaaaaaa", "chu@x.vn")
    assert p.co_nguoi_giu() is False
    assert p.nhan_khoa("token-bbbbbbbb", "chu@x.vn") is True


def test_cung_token_noi_lai_giu_expected_seq_token_moi_reset_va_huy_gesture(dh):
    p = _phien()
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 0, [_ev("down", 1, 1, 0.0, 1)])
    p.nhan_lo("token-aaaaaaaa", "chu@x.vn", 1, [_ev("move", 2, 2, 16.0, 1)])
    assert p.expected_seq == 2
    # EventSource tự nối lại, kết nối cũ chưa bị phát hiện ngắt: đếm 2 kết nối, nhả khi cái cuối ngắt.
    assert p.nhan_khoa("token-aaaaaaaa", "chu@x.vn") is True
    p.nha_khoa("token-aaaaaaaa", "chu@x.vn")
    assert p.co_nguoi_giu() is True
    p.nha_khoa("token-aaaaaaaa", "chu@x.vn")
    assert p.co_nguoi_giu() is False and p.expected_seq == 2
    # Cùng token vào lại sau khi nhả: giữ nguyên seq, KHÔNG huỷ gesture.
    assert p.nhan_khoa("token-aaaaaaaa", "chu@x.vn") is True
    assert p.expected_seq == 2 and p.lay_huy() is None
    p.nha_khoa("token-aaaaaaaa", "chu@x.vn")
    # Popup tải lại ⇒ token MỚI: seq về 0 được nhận, gesture dở của token cũ bị huỷ.
    assert p.nhan_khoa("token-cccccccc", "chu@x.vn") is True
    assert p.expected_seq == 0 and p.lay_huy() == "doi_token"
    assert p.nhan_lo("token-cccccccc", "chu@x.vn", 0, [_ev("move", 9, 9, 0.0)]) == "ok"
    assert p.expected_seq == 1


def test_gioi_han_tan_suat_lo(dh):
    p = _phien()
    for _ in range(gc.LO_TOI_DA_MOI_GIAY):
        p.kiem_tan_suat(dh.t)
    with pytest.raises(LoiGiai) as e:
        p.kiem_tan_suat(dh.t)
    assert e.value.ma == 429
    dh.t += 1.5
    p.kiem_tan_suat(dh.t)  # cửa sổ 1 giây đã trôi


def test_dat_lenh_chi_nguoi_giu_khoa_va_chi_khi_dang_giai():
    p = _phien()
    p.dat_lenh("token-aaaaaaaa", "chu@x.vn", "da_giai")
    assert p.xem_lenh() == "da_giai"
    with pytest.raises(LoiGiai):
        p.dat_lenh("token-bbbbbbbb", "chu@x.vn", "dung")
    q = PhienGiai(2, "chu@x.vn", "cho_giai")
    q.nhan_khoa("token-aaaaaaaa", "chu@x.vn")
    with pytest.raises(LoiGiai):
        q.dat_lenh("token-aaaaaaaa", "chu@x.vn", "dung")


def test_khung_chi_giu_khung_moi_nhat_va_dw_theo_seq():
    p = _phien()
    p.dat_khung("AAA", {"deviceWidth": 1280, "deviceHeight": 900, "pageScaleFactor": 1})
    p.dat_khung("BBB", {"deviceWidth": 1000, "deviceHeight": 700, "pageScaleFactor": 1})
    assert p.lay_khung()["jpeg"] == "BBB" and p.lay_khung()["seq"] == 2
    assert "scrollOffsetY" not in p.lay_khung()
    assert p.kich_thuoc_thiet_bi(1) == (1280.0, 900.0)
    assert p.kich_thuoc_thiet_bi(None) == (1000.0, 700.0)
    assert p.kich_thuoc_thiet_bi(99) == (1000.0, 700.0)


# ---------------------------------------------------------------------------
# D từ env
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _xoa_canh_bao_d(monkeypatch):
    monkeypatch.setattr(gc, "_D_DA_CANH_BAO", set())
    monkeypatch.delenv(gc.ENV_D_MS, raising=False)


def test_d_mac_dinh_120_khi_khong_dat_env():
    assert gc.doc_d_ms() == 120


def test_d_env_hop_le_duoc_dung(monkeypatch, caplog):
    monkeypatch.setenv(gc.ENV_D_MS, "200")
    with caplog.at_level(logging.WARNING, logger="videodl.web"):
        assert gc.doc_d_ms() == 200
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_d_env_la_ve_120_dung_mot_warning(monkeypatch, caplog):
    monkeypatch.setenv(gc.ENV_D_MS, "nhanh")
    with caplog.at_level(logging.WARNING, logger="videodl.web"):
        assert gc.doc_d_ms() == 120
        assert gc.doc_d_ms() == 120
        assert gc.doc_d_ms() == 120
    canh_bao = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(canh_bao) == 1, "đúng MỘT dòng cho mỗi giá trị lạ, không lặp mỗi lượt giải"
    assert gc.ENV_D_MS in canh_bao[0].getMessage()


@pytest.mark.parametrize("tho,ky_vong", [("5", 40), ("39", 40), ("40", 40), ("1000", 1000),
                                          ("1001", 1000), ("99999", 1000), ("-7", 40)])
def test_d_env_ngoai_khoang_bi_kep(monkeypatch, tho, ky_vong):
    monkeypatch.setenv(gc.ENV_D_MS, tho)
    assert gc.doc_d_ms() == ky_vong


def test_phien_moi_lay_d_tu_env(monkeypatch):
    monkeypatch.setenv(gc.ENV_D_MS, "250")
    assert PhienGiai(1, "a@x.vn").bo_phat.d == pytest.approx(0.250)
