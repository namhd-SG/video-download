"""Khoá / khoá lại có DANH TÍNH vết cho theo_vet — chỉ bật ở lần theo vết cuối; lượt tự học mẫu giữ mã cũ (mẫu + ứng viên không đổi).

theo_vet cũ nhận ứng viên bất kỳ ≥ hi ở bất kỳ đâu và không so cỡ: vết khoá nhầm chữ phụ đề / đồ vật đứng yên có điểm ngang logo.
- Danh tính `dd` = trung vị (w, h, điểm) của vết mã cũ, chỉ lấy khung có cỡ trong ±15% cỡ mẫu (vết bị rác cướp quá nửa không đảo
  được cổng); thiếu khung thì kẹp cỡ về cỡ mẫu. `dd` CỐ ĐỊNH suốt lượt: không trung bình động, không xoá khi mất dấu.
- Cổng `qua_cong`: từ chối ⟺ ≥ 2 trong 3 tín hiệu — đỉnh 1/đỉnh 2 < A_DINH12 · điểm/dd < B_DIEM · |w/dd − 1| > C_CO.
  Chỉ xét lúc KHOÁ (đầu vết, sau lỗ ≥ HO_KHOA_LAI khung kể cả đúng chỗ cũ, nhảy xa, nhánh gần mà lệch dự đoán > nửa cạnh);
  tiếp nối sát dự đoán ngay sau khung trước không qua cổng.
- Khoá vào chỗ mới phải đứng TRE_K khung (hở ≤ HO_CHO) mà khung nào cũng qua cổng mới được ghi (hồi tố); vết cũ quay lại sát dự
  đoán và qua cổng ⇒ huỷ. Đang bám mà ứng viên sát dự đoán trượt cổng thì ứng viên xa qua cổng, điểm ≥ max(hi, THOAT_BAY × gần)
  được vào bộ đệm: vết đã dính đồ vật thì nhánh gần luôn có ứng viên nên nhánh xa (logo thật trở lại) không bao giờ được xét.
- Khoá lại sau lỗ mà ứng viên nằm sát vị trí ngoại suy theo vận tốc (≤ LECH_QUY_DAO cạnh, vết chưa bị quên): vế điểm so với điểm
  của chính vết ngay trước lỗ thay vì danh tính toàn video — logo mờ dần ở cảnh tối vẫn là logo; thứ đứng chỗ logo vừa rời thì
  lệch quỹ đạo hoặc tụt điểm so với vết trước lỗ.
- Hai lượt bất đồng chỗ ⇒ bên qua cổng thắng trước khi so điểm. Khung tiếp nối kế thừa danh tính của lần khoá đã qua cổng; chỉ khung
  vết cũ đi tạm (trượt cổng) trong lúc chờ khoá chỗ mới mới mang cờ trượt — hai bản logo cùng khung lúc chuyển cảnh luôn làm vế đỉnh
  nổ, chấm lại từng khung thì bản đang hiện bị xử thua bản đang tắt.
Ứng viên khớp vị trí box mồi ở khung mồi ±1 được miễn cổng và bộ đệm.
"""
from __future__ import annotations

import math
import statistics as st

from . import theo_vet as tv

# Chọn trong vùng phẳng (1,292; 1,373] của bộ hiệu chỉnh 12 video: cả khoảng đó số khoá SAI bắt được và số khoá ĐÚNG bị chặn
# đều không đổi. Vế này là lá phiếu quyết định khi chỉ một trong hai vế kia nổ (đồ vật đúng cỡ, điểm vừa) ⇒ bộ kiểm độc lập
# phải báo riêng số từ chối do nó (`tu_choi_dinh12`).
A_DINH12 = 1.36
B_DIEM = 0.65
C_CO = 0.05
LECH_KICH_TOI_DA = 0.15   # khung vết cũ lệch cỡ mẫu quá mức này không góp vào danh tính
NUA_CANH = 0.5            # "chỗ khác" = tâm cách > nửa cạnh dài của danh tính
TRE_K = tv.DOAN_TOI_THIEU  # số khung chỗ mới phải đứng được trước khi khoá
HO_CHO = 2                # bộ đệm cho hở tối đa 2 khung liền: mốc đúng ngắn có lỗ 2 khung là neo cho bước bám hai chiều phía sau
HO_KHOA_LAI = 5           # mất ≥ chừng này khung rồi bắt lại (kể cả đúng chỗ cũ) là KHOÁ LẠI, không phải tiếp nối: phải qua cổng
THOAT_BAY = 1.3
LECH_QUY_DAO = 0.15       # khoá lại sát vị trí ngoại suy theo vận tốc (≤ chừng này × cạnh) ⇒ điểm so với chính vết ngay trước lỗ


def _tam(c: tuple) -> tuple[float, float]:
    return c[0] + c[3] / 2, c[1] + c[4] / 2


def danh_tinh(det0: dict[int, dict], kich: tuple[int, int]) -> dict | None:
    """Danh tính vết từ vết mã cũ. None nếu mã cũ không ra khung nào (không có gì để gác)."""
    if not det0:
        return None
    kw, kh = kich
    hop = [e for e in det0.values() if abs(e["w"] / kw - 1) <= LECH_KICH_TOI_DA and abs(e["h"] / kh - 1) <= LECH_KICH_TOI_DA]
    kep = len(hop) < tv.DOAN_TOI_THIEU
    nguon = list(det0.values()) if kep else hop
    return {"w": float(kw) if kep else float(st.median(e["w"] for e in hop)),
            "h": float(kh) if kep else float(st.median(e["h"] for e in hop)),
            "s": max(float(st.median(e["score"] for e in nguon)), 1e-6),
            "kep_kich": kep, "lech_kich": round(1 - len(hop) / len(det0), 3)}


def tin_hieu(c: tuple, cs: list[tuple], dd: dict, s_ref: float | None = None) -> tuple[bool, bool, bool]:
    """(đỉnh 1/đỉnh 2 thấp, điểm thấp, lệch cỡ). Không có ứng viên nào ở chỗ khác ⇒ vế đầu không nổ. Điểm so với `s_ref` nếu có
    (điểm của chính vết ngay trước lỗ, khi khoá lại liền quỹ đạo), không thì với danh tính."""
    c0, cd = _tam(c), max(dd["w"], dd["h"])
    s2 = max((x[2] for x in cs if math.dist(_tam(x), c0) > NUA_CANH * cd), default=None)
    return (s2 is not None and s2 > 0 and c[2] / s2 < A_DINH12, c[2] / (s_ref or dd["s"]) < B_DIEM, abs(c[3] / dd["w"] - 1) > C_CO)


def qua_cong(c: tuple, cs: list[tuple], dd: dict) -> bool:
    return sum(tin_hieu(c, cs, dd)) < 2


def _khop_moi(c: tuple, t: int, hop_moi: dict[int, list[tuple]], cd: float) -> bool:
    c0 = _tam(c)
    return any(math.dist(c0, (x + w / 2, y + h / 2)) <= NUA_CANH * cd
               for k in (t - 1, t, t + 1) for x, y, w, h in hop_moi.get(k, ()))


def mot_luot_cong(uv: list[list[tuple]], thu_tu, hi: float, lo: float, kich: tuple[int, int], dd: dict,
                  hop_moi: dict[int, list[tuple]], dem: dict) -> dict[int, dict]:
    """Như `theo_vet._mot_luot` nhưng mọi lần KHOÁ đi qua cổng danh tính + bộ đệm trễ. Entry mang thêm `dd_ok` cho bước hợp."""
    out: dict[int, dict] = {}
    cd = max(dd["w"], dd["h"])
    s = {"cur": None, "vx": 0.0, "vy": 0.0, "mat": 1, "diem_tb": 0.0, "w": kich[0], "h": kich[1]}
    cho: list[tuple[int, tuple]] = []  # bộ đệm khoá chỗ mới (khung, ứng viên), chưa ghi
    tam: dict[int, dict] = {}          # vết cũ đi tiếp trong lúc chờ: bộ đệm thành thì bỏ, huỷ thì ghi
    cho_nhay, cho_ho, cho_sref = False, 0, None

    def mien(c, t):
        return _khop_moi(c, t, hop_moi, cd)

    def kiem(c, cs, t, s_ref=None):  # cổng lúc khoá; ghi lại từ chối để báo cáo
        if mien(c, t):
            return True
        v = tin_hieu(c, cs, dd, s_ref)
        if sum(v) < 2:
            return True
        dem["tu_choi"].add((t, c[0], c[1]))
        if v[0] and v[1] != v[2]:
            dem["tu_choi_dinh12"].add((t, c[0], c[1]))
        return False

    def nhan(t, c, nhay, dich, ok):
        if s["cur"] is not None and not nhay:
            s["vx"] = 0.7 * s["vx"] + 0.3 * (c[0] - s["cur"][0]) / s["mat"]
            s["vy"] = 0.7 * s["vy"] + 0.3 * (c[1] - s["cur"][1]) / s["mat"]
        else:
            s["vx"] = s["vy"] = 0.0
        s["diem_tb"] = c[2] if s["cur"] is None else (1 - tv.HE_SO_DIEM) * s["diem_tb"] + tv.HE_SO_DIEM * c[2]
        s.update(cur=(c[0], c[1]), mat=1, w=c[3], h=c[4])
        dich[t] = {"frame": t, "x": int(c[0]), "y": int(c[1]), "w": int(c[3]), "h": int(c[4]),
                   "score": round(float(c[2]), 3), "state": "detected", "nhay": bool(nhay), "dd_ok": ok}

    def mat_dau():
        s["mat"] += 1
        if s["mat"] > tv.TRUOT_TOI_DA:  # danh tính dd giữ nguyên; chỉ vị trí/vận tốc bị quên
            s.update(cur=None, vx=0.0, vy=0.0, diem_tb=0.0)

    def bat_dau(t, c, nhay, s_ref=None):
        nonlocal cho_nhay, cho_ho, cho_sref
        cho[:] = [(t, c)]
        tam.clear()
        cho_nhay, cho_ho, cho_sref = nhay, 0, s_ref

    def ghi_cho():
        for i, (t, c) in enumerate(cho):
            s["diem_tb"] = c[2] if i == 0 else (1 - tv.HE_SO_DIEM) * s["diem_tb"] + tv.HE_SO_DIEM * c[2]
            out[t] = {"frame": t, "x": int(c[0]), "y": int(c[1]), "w": int(c[3]), "h": int(c[4]),
                      "score": round(float(c[2]), 3), "state": "detected", "nhay": bool(cho_nhay and i == 0), "dd_ok": True}
        c = cho[-1][1]
        s.update(cur=(c[0], c[1]), vx=0.0, vy=0.0, mat=1, w=c[3], h=c[4])
        cho.clear()
        tam.clear()
        dem["cho_ghi"] += 1

    def huy_cho():
        out.update(tam)
        cho.clear()
        tam.clear()
        dem["cho_huy"] += 1

    for t in thu_tu:
        cs = uv[t]
        lo_t, hi_t = max(lo, tv.TI_LE_DIEM_TOI_THIEU * s["diem_tb"]), max(hi, 0.6 * s["diem_tb"])
        gan: list[tuple[tuple, bool]] = []  # (ứng viên, sát dự đoán ⇒ tiếp nối) theo thứ tự ưu tiên của mã cũ
        lien: set[int] = set()              # ứng viên khoá lại liền quỹ đạo (id)
        s_ref = min(dd["s"], s["diem_tb"]) if s["diem_tb"] > 0 else None
        if s["cur"] is not None:
            px, py = s["cur"][0] + s["vx"] * s["mat"], s["cur"][1] + s["vy"] * s["mat"]
            mw = max(s["w"], s["h"])
            r = min(2.0 * mw, tv.BAN_KINH_CO * mw + 8 + 5 * s["mat"])
            ung = [(c[2] - tv.PHAT_KHOANG_CACH * math.hypot(c[0] - px, c[1] - py) / r, c) for c in cs
                   if c[2] >= lo_t and math.hypot(c[0] - px, c[1] - py) <= r]
            moi_mat = s["mat"] < HO_KHOA_LAI
            gan = [(c, moi_mat and math.hypot(c[0] - px, c[1] - py) <= NUA_CANH * cd) for _, c in sorted(ung, key=lambda z: -z[0])]
            if not moi_mat:
                lien = {id(c) for c in cs if math.hypot(c[0] - px, c[1] - py) <= LECH_QUY_DAO * cd}
        noi = next((c for c, la_noi in gan if la_noi), None)

        if cho:
            if noi is not None and (qua_cong(noi, cs, dd) or mien(noi, t)):
                huy_cho()  # vết cũ quay lại đúng danh tính
                nhan(t, noi, False, out, True)
                continue
            lt, lc = cho[-1]
            mb = max(lc[3], lc[4])
            rb = min(2.0 * mb, tv.BAN_KINH_CO * mb + 8 + 5 * (cho_ho + 1))
            sb = max(lo, tv.TI_LE_DIEM_TOI_THIEU * st.mean(c[2] for _, c in cho))
            bs = [c for c in cs if c[2] >= sb and math.hypot(c[0] - lc[0], c[1] - lc[1]) <= rb and kiem(c, cs, t, cho_sref)]
            if noi is not None:
                nhan(t, noi, False, tam, False)
            else:
                mat_dau()
            if bs:
                b = max(bs, key=lambda c: c[2])
                cho.append((t, b))
                cho_ho = 0
                if len(cho) >= TRE_K or mien(b, t):
                    ghi_cho()
            else:
                cho_ho += 1
                if cho_ho > HO_CHO:
                    huy_cho()
            continue

        chon, la_noi = None, False
        for c, ln in gan:
            if ln or kiem(c, cs, t, s_ref if id(c) in lien else None):
                chon, la_noi = c, ln
                break
        if chon is not None and la_noi:
            ok = qua_cong(chon, cs, dd) or mien(chon, t)
            if not ok:  # vết đang dính thứ trượt danh tính: cho ứng viên xa đủ mạnh và đúng danh tính một lối ra
                xa = [c for c in cs if math.dist(_tam(c), _tam(chon)) > NUA_CANH * cd
                      and c[2] >= max(hi_t, THOAT_BAY * chon[2]) and kiem(c, cs, t)]
                if xa:
                    bat_dau(t, max(xa, key=lambda c: c[2]), True)
                    dem["thoat_bay"] += 1
                    nhan(t, chon, False, tam, False)
                    if len(cho) >= TRE_K or mien(cho[0][1], t):
                        ghi_cho()
                    continue
            nhan(t, chon, False, out, True)  # tiếp nối kế thừa danh tính của lần khoá đã qua cổng
            continue
        nhay = False  # khoá ở nhánh gần (lệch dự đoán) không phải bước nhảy, như mã cũ
        if chon is None:
            for c in sorted((c for c in cs if c[2] >= hi_t), key=lambda c: -c[2]):
                if kiem(c, cs, t):
                    chon, nhay = c, s["cur"] is not None
                    break
        if chon is None:
            mat_dau()
            continue
        if mien(chon, t):
            nhan(t, chon, nhay, out, True)
            continue
        bat_dau(t, chon, nhay, s_ref if id(chon) in lien else None)
        mat_dau()
        if len(cho) >= TRE_K:
            ghi_cho()
    if cho:
        huy_cho()  # hết video mà chỗ mới chưa đứng đủ TRE_K khung
    return out


def hop_hai_luot_cong(xuoi: dict[int, dict], nguoc: dict[int, dict], dd: dict) -> dict[int, dict]:
    """Như `theo_vet.hop_hai_luot`, trừ khi hai lượt bất đồng chỗ (> nửa cạnh) và chỉ một bên qua cổng: bên đó thắng."""
    cd = max(dd["w"], dd["h"])
    out = {}
    for t in sorted(set(xuoi) | set(nguoc)):
        a, b = xuoi.get(t), nguoc.get(t)
        if a is not None and b is not None and a["dd_ok"] != b["dd_ok"] and math.dist(tv._tam(a), tv._tam(b)) > NUA_CANH * cd:
            out[t] = a if a["dd_ok"] else b
        else:
            out[t] = a if b is None or (a is not None and a["score"] >= b["score"]) else b
    return out


def theo_vet_danh_tinh(uv: list[list[tuple]], kich: tuple[int, int], khung_moi: set[int], hop_moi: dict[int, list[tuple]],
                       det0: dict[int, dict], hi: float, lo: float, tt: dict) -> tuple[dict[int, dict], dict]:
    """Chạy lại hai lượt có cổng trên cùng ngưỡng hi/lo của mã cũ. `det0` = kết quả mã cũ (nguồn danh tính)."""
    dd = danh_tinh(det0, kich)
    if dd is None:
        return det0, dict(tt, danh_tinh=None)
    dem = {"tu_choi": set(), "tu_choi_dinh12": set(), "cho_ghi": 0, "cho_huy": 0, "thoat_bay": 0}
    n = len(uv)
    xuoi = mot_luot_cong(uv, range(n), hi, lo, kich, dd, hop_moi, dem)
    nguoc = mot_luot_cong(uv, range(n - 1, -1, -1), hi, lo, kich, dd, hop_moi, dem)
    det = tv.bo_doan_ngan(hop_hai_luot_cong(xuoi, nguoc, dd), khung_moi)
    det = {t: {k: v for k, v in e.items() if k != "dd_ok"} for t, e in det.items()}
    bao = {k: round(v, 3) if isinstance(v, float) else v for k, v in dd.items()}
    bao.update({k: len(v) if isinstance(v, set) else v for k, v in dem.items()}, det0=len(det0))
    return det, dict(tt, xuoi=len(xuoi), nguoc=len(nguoc), hop=len(det), danh_tinh=bao)
