"""Mô phỏng độ trễ phát chuột khi gộp `move` quá hạn liên tiếp cùng `buttons` trong `BoPhatLai.den_han`
(đồng hồ giả, không trình duyệt) và kiểm bất biến không gộp `hover`/`wheel`/`down`/`up`, giữ thứ tự.
"""
from __future__ import annotations

import pytest

from web import giai_captcha as gc
from web.giai_captcha import BoPhatLai, SuKien


def _ev(k: str, x: float, y: float, t: float, buttons: int = 0,
        dx: float = 0.0, dy: float = 0.0) -> SuKien:
    return SuKien(k=k, x=float(x), y=float(y), t=float(t), buttons=buttons, dx=dx, dy=dy)


def _tao_cu_keo_120_sk_s_3_giay() -> list[SuKien]:
    """Người kéo 120 sk/s × 3 s: 1 `down`, 360 `move` (`buttons=1`), 1 `up`."""
    buoc_ms = 1000.0 / 120.0
    ra: list[SuKien] = [_ev("down", 100.0, 200.0, 0.0, buttons=1)]
    for i in range(1, 361):
        ra.append(_ev("move", 100.0 + i * 0.75, 200.0 + i * 0.25, i * buoc_ms, buttons=1))
    cuoi = ra[-1]
    ra.append(_ev("up", cuoi.x, cuoi.y, 361 * buoc_ms, buttons=0))
    return ra


def _chia_lo_40ms(events: list[SuKien], goc_giay: float = 10.0) -> list[tuple[float, list[SuKien]]]:
    """Gom lô 40 ms như popup; mỗi lô tới máy chủ ở `sự kiện đầu của lô + 40 ms`."""
    lo: list[list[SuKien]] = []
    hien: list[SuKien] = []
    for e in events:
        if hien and e.t - hien[0].t > 40.0:
            lo.append(hien)
            hien = []
        hien.append(e)
    if hien:
        lo.append(hien)
    return [(goc_giay + l[0].t / 1000.0 + 0.040, l) for l in lo]


def _mo_phong_vong_phat(c_ms: float, lo_toi: list[tuple[float, list[SuKien]]],
                        d_ms: float = gc.D_MAC_DINH_MS) -> tuple[list[SuKien], BoPhatLai]:
    """Vòng phát giả lập giống `_vong_giai`: mỗi sự kiện phát ra tốn `c_ms` đồng hồ giả."""
    bp = BoPhatLai(d_ms)
    t = lo_toi[0][0]
    i = 0
    da_phat: list[SuKien] = []
    while i < len(lo_toi) or bp.con_hang():
        while i < len(lo_toi) and lo_toi[i][0] <= t:
            bp.nhan_lo(lo_toi[i][1], lo_toi[i][0])
            i += 1
        for ev in bp.den_han(t):
            da_phat.append(ev)
            t += c_ms / 1000.0
            while i < len(lo_toi) and lo_toi[i][0] <= t:
                bp.nhan_lo(lo_toi[i][1], lo_toi[i][0])
                i += 1
        if i >= len(lo_toi) and not bp.con_hang():
            break
        ms = gc.TICK_VONG_GIAY * 1000.0
        ke = bp.diem_ke_tiep()
        if ke is not None:
            ms = min(ms, max(1.0, (ke - t) * 1000.0))
        t += ms / 1000.0
    return da_phat, bp


@pytest.mark.parametrize("c_ms", [16.7, 26.0])
def test_mo_phong_keo_120_sk_s_3_giay_p95_tre_duoi_500ms_du_down_up_va_diem_cuoi(c_ms: float):
    """ĐỘT BIẾN: tắt gộp `move` trong `BoPhatLai.den_han` ⇒ hàng đợi tích luỹ tuyến tính, p95 > 500 ms ⇒ ĐỎ."""
    evs = _tao_cu_keo_120_sk_s_3_giay()
    assert len(evs) == 362
    lo_toi = _chia_lo_40ms(evs)
    da_phat, bp = _mo_phong_vong_phat(c_ms, lo_toi)

    tt = gc.tom_tat_tre(bp.thong_ke.mau)
    assert tt is not None
    _p50, p95 = tt
    assert p95 <= 500, f"c_ms={c_ms}: p95={p95} ms vượt trần 500 ms"

    assert [e.k for e in da_phat].count("down") == 1
    assert [e.k for e in da_phat].count("up") == 1
    assert da_phat[0] == evs[0], "sự kiện đầu phải là `down` gốc"
    assert da_phat[-1] == evs[-1], "sự kiện cuối phải là `up` gốc"
    assert da_phat[-2].k == "move" and da_phat[-2] == evs[-2], \
        "move liền trước `up` phải còn và đúng toạ độ cuối của chuỗi kéo"

    assert bp.thong_ke.so_phat == len(evs) == 362
    assert bp.thong_ke.gesture_nop == 1
    assert bp.thong_ke.so_gop == len(evs) - len(da_phat) > 0


def test_hover_wheel_down_up_khong_bi_gop_va_giu_nguyen_thu_tu():
    """Chỉ chuỗi `move` liên tiếp CÙNG `buttons` mới gộp về điểm cuối; hover (`buttons=0`) không gộp
    với kéo (`buttons=1`), `down`/`up`/`wheel` không bao giờ bị bỏ hay gộp, thứ tự giữ nguyên."""
    bp = BoPhatLai(120.0)
    chuoi = [
        _ev("move", 1.5, 2.5, 0.0, buttons=0),          # hover 1
        _ev("move", 3.5, 4.5, 8.0, buttons=0),          # hover 2 (cuối chuỗi hover đầu)
        _ev("down", 3.5, 4.5, 16.0, buttons=1),         # down 1
        _ev("move", 10.25, 20.75, 24.0, buttons=1),     # kéo 1
        _ev("move", 15.25, 25.75, 32.0, buttons=1),     # kéo 2 (trước wheel ⇒ phải còn)
        _ev("wheel", 15.25, 25.75, 40.0, buttons=1, dx=0.0, dy=120.0),
        _ev("wheel", 15.25, 25.75, 48.0, buttons=1, dx=0.0, dy=240.0),
        _ev("move", 30.5, 40.5, 56.0, buttons=1),       # kéo 3
        _ev("move", 45.5, 55.5, 64.0, buttons=1),       # kéo 4 (liền trước up ⇒ phải còn)
        _ev("up", 45.5, 55.5, 72.0, buttons=0),         # up 1
        _ev("move", 60.0, 70.0, 80.0, buttons=0),       # hover sau up, khác buttons với kéo
        _ev("down", 60.0, 70.0, 88.0, buttons=1),       # down 2
        _ev("up", 60.0, 70.0, 96.0, buttons=0),         # up 2
    ]
    bp.nhan_lo(chuoi, t_toi=10.0)
    ra = bp.den_han(100.0)                              # tất cả đã tới hạn trong một lần gọi

    ky_vong = [
        chuoi[1],   # move hover cuối trước down
        chuoi[2],   # down 1
        chuoi[4],   # move kéo cuối trước wheel
        chuoi[5],   # wheel 1 (không gộp với wheel 2)
        chuoi[6],   # wheel 2
        chuoi[8],   # move kéo cuối liền trước up 1
        chuoi[9],   # up 1
        chuoi[10],  # move hover lẻ
        chuoi[11],  # down 2
        chuoi[12],  # up 2
    ]
    assert ra == ky_vong
    assert bp.thong_ke.so_phat == len(chuoi)
    assert bp.thong_ke.so_gop == 3                      # gộp: chuoi[0], chuoi[3], chuoi[7]


def test_move_khac_buttons_lien_tiep_khong_gop_chung():
    """Hai `move` liên tiếp nhưng khác `buttons` (0 rồi 1) không được gộp làm mất điểm chuyển trạng thái."""
    bp = BoPhatLai(120.0)
    bp.nut_giu_nguon = True
    m_hover = _ev("move", 10.0, 20.0, 0.0, buttons=0)
    m_keo_1 = _ev("move", 12.0, 22.0, 8.0, buttons=1)
    m_keo_2 = _ev("move", 14.0, 24.0, 16.0, buttons=1)
    bp.nhan_lo([m_hover, m_keo_1, m_keo_2], t_toi=5.0)
    ra = bp.den_han(50.0)
    assert ra == [m_hover, m_keo_2]
    assert bp.thong_ke.so_gop == 1


def test_move_dung_han_tung_cai_khong_bi_gop():
    """Mỗi `move` được gọi `den_han` đúng lúc nó tới hạn (worker không trễ) ⇒ phát RIÊNG từng điểm, không gộp.
    ĐỘT BIẾN: gộp cả move đúng hạn (vd giữ move lại chờ move sau / gộp qua nhiều lần gọi) ⇒ ĐỎ."""
    bp = BoPhatLai(120.0)
    bp.nut_giu_nguon = True
    chuoi = [_ev("down", 1.0, 1.0, 0.0, buttons=1)] + [
        _ev("move", 1.0 + i * 2.5, 1.0 + i * 0.5, i * 16.0, buttons=1) for i in range(1, 9)]
    bp.nhan_lo(chuoi, t_toi=10.0)
    ra: list[SuKien] = []
    while bp.con_hang():
        ke = bp.diem_ke_tiep()
        lan = bp.den_han(ke)
        assert len(lan) == 1, "đúng hạn ⇒ mỗi lần gọi đúng một sự kiện"
        ra.extend(lan)
    assert ra == chuoi
    assert bp.thong_ke.so_gop == 0
