"""Đường ống một video: box mồi → gom vết → mỗi vết: mồi đồng thuận → mẫu → ứng viên + nối vết (xuôi/ngược) → tự học → lấp lỗ + làm
mượt → các cổng nội dung → cổng khớp mồi → bằng chứng → chỉ số nháy.

Quy tắc kết luận video (không im lặng): video chỉ `render` khi MỌI cụm box đều thành vết `render`. Có cụm không thành vết (thiếu bằng
chứng, mẫu hỏng, khớp mồi trượt, mọi khung bị chặn) ⇒ video `cho_nguoi` kèm `ly_do` + danh sách `vet_bi_bo`; worker đẩy người duyệt.
Không render, không gọi agy — box mồi do người gọi đưa vào.

API gọi lại được (vòng kiểm kết quả ở bước sau): `xu_ly_video(nguon, boxes_bo_sung, vet_cu=kq_truoc.vet)` — box bổ sung được gom + xử lý
như mọi box, vết cũ giữ nguyên; `KetQuaVideo.vet` = cũ + mới nên `render.gom_khung_render` ra HỢP mặt nạ cũ và mới.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from . import cong
from .box_moi import BoxMoi, chon_moi_dong_thuan, gom_vet
from .dinh_vi import dinh_vi, ti_le_phu_de
from .lam_muot_vet import TOC_DO_NHAY, lap_va_lam_muot
from .mau import dung_mau_sach, mat_na_va_tuong_phan, tu_hoc_mau
from .nguon_khung import NguonKhung
from .nhay import do_nhay
from .theo_vet import theo_vet

SO_VONG_TU_HOC = 1
BUOC_TU_HOC = 4  # lượt tự học mẫu dò mỗi 4 khung (rẻ 4×); lượt cuối dò đủ mọi khung
# Bằng chứng để một cụm thành vết: số khung dò được NGOÀI các khung mồi (±2). Cụm ≥3 box đã có bằng chứng từ chính các box.
BANG_CHUNG_CUM_NHO, BANG_CHUNG_CUM_LON, CUM_LON = 5, 2, 3
BOX_TOI_THIEU_HAT_GIONG = 1  # cụm có ít box hơn mức này thì không dò (1 = mọi cụm, kể cả 1 box, là hạt giống được dò)
NEO_KHUNG = 3  # dò quanh box mồi của logo có thể trôi: ±3 khung
TI_LE_NHAY_LOAN = 0.05  # quá 5% cặp khung dò liền nhau là bước NHẢY (> TOC_DO_NHAY px/khung) ⇒ vết nhảy loạn giữa các chỗ giống nhau, không phải một watermark
BIEN_TACH_NEN = 0.05  # cụm 1–2 box: điểm trung vị các khung dò được phải vượt phân vị 95 của nền nhiễu video ít nhất chừng này


@dataclass
class KetQuaVet:
    trang_thai: str  # "render" | "cho_nguoi" | "loi_mau"
    box_cum: int
    ncc_moi: float = 0.0
    track: list[dict] = field(default_factory=list)
    khung_render: list[dict] = field(default_factory=list)
    khop: dict = field(default_factory=dict)
    tu_hoc_bi_tu_choi: int = 0  # số vòng tự học mà mẫu mới lệch mẫu cũ ⇒ giữ mẫu cũ (cờ cho người duyệt)
    tuong_phan_mau: float = 0.0
    dem_chan: dict = field(default_factory=dict)
    net_la_pho_bien: bool = False  # nội dung lạ trong box ở phần lớn video ⇒ cổng nét lạ mù ⇒ cờ cho member soi kỹ
    ly_do: str = ""  # vì sao KHÔNG render (rỗng khi render)
    nhay: dict = field(default_factory=dict)  # xem nhay.do_nhay
    doan: list = field(default_factory=list)  # [(đầu, cuối)] khoảng sống
    khung_chan: list[dict] = field(default_factory=list)  # khung còn watermark nhưng bị cổng chặn
    nhan: str = ""
    thong_tin: dict = field(default_factory=dict)  # ngưỡng tương đối + số khung mỗi lượt, cho nhật ký tune

    @property
    def pct_chac(self) -> float:
        return round(100 * len(self.khung_render) / max(1, len(self.track)), 1)


@dataclass
class KetQuaVideo:
    vet: list[KetQuaVet]
    so_box: int
    so_cum: int

    @property
    def vet_bi_bo(self) -> list[dict]:
        return [{"box_cum": v.box_cum, "nhan": v.nhan, "trang_thai": v.trang_thai, "ly_do": v.ly_do}
                for v in self.vet if v.trang_thai != "render"]

    @property
    def trang_thai(self) -> str:
        """`render` ⟺ có vết VÀ mọi vết đều render. Còn một vết bị bỏ ⇒ chờ người (không để sót im lặng)."""
        return "render" if self.vet and all(v.trang_thai == "render" for v in self.vet) else "cho_nguoi"

    @property
    def ly_do(self) -> str:
        if self.trang_thai == "render":
            return ""
        if not self.vet:
            return "không có box mồi nào dùng được"
        bo = self.vet_bi_bo
        return f"{len(bo)}/{len(self.vet)} watermark không tự thay được: " + "; ".join(
            f"[{b['nhan'] or 'không số cụm'}, {b['box_cum']} box] {b['ly_do']}" for b in bo)[:900]


def _ten_cum(cum: list[BoxMoi]) -> str:
    """Tên hiển thị trong lý do/nhật ký: số cụm agy (nếu có), không thì rỗng."""
    c = next((b.cum for b in cum if b.cum is not None), None)
    return "" if c is None else f"cụm {c}"


def _ap_cong_khung(nguon: NguonKhung, track: list[dict], mau: np.ndarray, bo_phu_de: bool = False) -> bool:
    """Mọi cổng theo khung + theo video trên khung được che của `track` (sửa tại chỗ). Một lượt đọc tuần tự: phụ đề + tương phản từng
    khung, đo vành ngang + nét lạ (ghi vào khung để tune offline), rồi áp ngưỡng theo video. Trả True nếu nét lạ phổ biến (cờ)."""
    mask, tcon = mat_na_va_tuong_phan(mau)
    nguong = cong.nguong_tuong_phan(tcon)
    by = {e["frame"]: e for e in track if e.get("state") in cong.DA_CHAC}
    vanh: dict[int, float] = {}
    net: dict[int, float] = {}
    if by:
        cuoi = max(by)
        for i, g in enumerate(nguon.doc_tuan_tu()):
            e = by.get(i)
            if e is not None:
                if not bo_phu_de:
                    cong.cong_phu_de(g, e)
                if e["state"] in cong.DA_CHAC:
                    cong.cong_tuong_phan(g, e, mask, nguong)
                if e["state"] in cong.DA_CHAC:
                    vanh[i] = e["vanh"] = round(cong.ti_le_vanh(g, e), 4)
                    net[i] = e["net_la"] = round(cong.ti_le_net_la(g, e, mau), 4)
            if i >= cuoi:
                break
    cong.cong_vanh_ngang(track, vanh)
    return cong.cong_net_la(track, net)


def _kep_vao_khung(che: dict[int, dict], rong: int, cao: int) -> dict[int, dict]:
    """Ô làm mượt có thể tràn khỏi khung hình (logo trôi ra mép): cắt vào khung; phần còn trong khung < 4 px ⇒ bỏ khung đó."""
    out = {}
    for t, e in che.items():
        x0, y0, x1, y1 = max(0, e["x"]), max(0, e["y"]), min(rong, e["x"] + e["w"]), min(cao, e["y"] + e["h"])
        if x1 - x0 >= 4 and y1 - y0 >= 4:
            e.update(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
            out[t] = e
    return out


def _track_day_du(n: int, che: dict[int, dict], uv) -> list[dict]:
    """Mỗi khung một entry: khung trong khoảng sống lấy entry của vết; khung ngoài là `hidden` (kèm điểm ứng viên tốt nhất để tune)."""
    out = []
    for i in range(n):
        e = che.get(i)
        if e is None:
            e = {"frame": i, "state": "hidden"}
        e["diem_tot"] = round(float(uv[i][0][0][2]), 3) if uv[i][0] else -1.0
        e["loc_pd"] = uv[i][1]
        out.append(e)
    return out


def _neo(cum: list[BoxMoi]) -> list[tuple[int, int, int, int, int, int]]:
    """Vị trí dò cục bộ quanh box mồi. Box có box khác (cách ≥ 10 khung) CHỒNG vị trí ⇒ watermark đứng yên ⇒ dò suốt video; không thì
    logo có thể đã trôi đi ⇒ chỉ dò ±NEO_KHUNG khung quanh khung của box (dò tĩnh cả video sẽ bắt rác tại chỗ cũ khi logo đã đi)."""
    out = []
    for b in cum:
        tinh = any(abs(o.khung - b.khung) >= 10 and _iou_box(b, o) >= 0.5 for o in cum)
        out.append((b.x, b.y, b.w, b.h, 0 if tinh else b.khung - NEO_KHUNG, 10 ** 9 if tinh else b.khung + NEO_KHUNG))
    return out


def _iou_box(a: BoxMoi, b: BoxMoi) -> float:
    iw, ih = min(a.x + a.w, b.x + b.w) - max(a.x, b.x), min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return 0.0 if iw <= 0 or ih <= 0 else iw * ih / (a.w * a.h + b.w * b.h - iw * ih)


def _bang_chung(det: dict[int, dict], khung_moi: set[int], so_box: int, tt: dict) -> str:
    """Rỗng nếu đủ bằng chứng, không thì lý do (tiếng Việt, cho người duyệt)."""
    ngoai = [t for t in det if all(abs(t - f) > 2 for f in khung_moi)]
    can = BANG_CHUNG_CUM_LON if so_box >= CUM_LON else BANG_CHUNG_CUM_NHO
    if len(ngoai) < can:
        return f"chỉ dò lại được {len(ngoai)} khung ngoài khung mồi (cần ≥{can}): chưa đủ bằng chứng đây là watermark"
    ds = sorted(det)
    nhay = sum(1 for a, b in zip(ds, ds[1:]) if np.hypot(det[b]["x"] - det[a]["x"], det[b]["y"] - det[a]["y"]) > TOC_DO_NHAY * (b - a))
    loan = nhay / len(ds)
    if loan > TI_LE_NHAY_LOAN:
        return f"vết nhảy loạn ({nhay} bước nhảy xa trong {len(ds)} khung dò được) giữa các chỗ giống mẫu: không phải một watermark"
    if so_box < CUM_LON:
        diem = float(np.median([det[t]["score"] for t in ngoai]))
        if diem < tt["nen95"] + BIEN_TACH_NEN:
            return f"điểm khớp trung vị {diem:.2f} không tách khỏi nền nhiễu của video ({tt['nen95']:.2f}): có thể là nội dung"
    return ""


def xu_ly_vet(nguon: NguonKhung, cum: list[BoxMoi]) -> KetQuaVet:
    nhan = _ten_cum(cum)
    moi, ncc = chon_moi_dong_thuan(nguon, cum)
    mau = dung_mau_sach(nguon, moi, cum)
    if mau is None:
        return KetQuaVet("loi_mau", len(cum), ncc, ly_do="không dựng được mẫu từ box mồi (box ngoài khung hình / khung không đọc được)",
                         nhan=nhan)
    neo = _neo(cum)
    khung_moi = {b.khung for b in cum}
    tu_choi = 0
    bo_pd = mau_giong_phu_de(mau)
    for _ in range(SO_VONG_TU_HOC):
        uv = dinh_vi(nguon, mau, neo, BUOC_TU_HOC, not bo_pd)
        det, _ = theo_vet([u for u, _ in uv], mau.shape[::-1], {f // BUOC_TU_HOC for f in khung_moi})
        if det:  # học từ nửa khung dò CHẮC hơn (điểm ≥ trung vị) kẻo ứng viên lẻ làm mẫu trôi sang nội dung
            med = float(np.median([e["score"] for e in det.values()]))
            mau, nhan_ok = tu_hoc_mau(nguon, [dict(e, frame=t * BUOC_TU_HOC) for t, e in det.items() if e["score"] >= med], mau)
            tu_choi += 0 if nhan_ok else 1
    uv = dinh_vi(nguon, mau, neo, 1, not mau_giong_phu_de(mau))
    n = len(uv)
    det, tt = theo_vet([u for u, _ in uv], mau.shape[::-1], khung_moi)
    che, doan = lap_va_lam_muot(det, n)
    che = _kep_vao_khung(che, nguon.rong, nguon.cao)
    track = _track_day_du(n, che, uv)
    kq = ap_moi_cong(nguon, track, mau, cum)
    kq.ncc_moi, kq.tu_hoc_bi_tu_choi, kq.nhan, kq.doan, kq.thong_tin = round(ncc, 3), tu_choi, nhan, doan, tt
    ly_do = _bang_chung(det, khung_moi, len(cum), tt)
    if ly_do:
        kq.trang_thai, kq.khung_render, kq.ly_do = "cho_nguoi", [], ly_do
    kq.nhay = do_nhay(doan, {e["frame"] for e in kq.khung_render})
    return kq


def mau_giong_phu_de(mau: np.ndarray) -> bool:
    """Mẫu watermark chính nó đã là chữ trắng viền đen: bộ lọc/cổng phụ đề không phân định được ⇒ phải tắt, kẻo giết cả vết."""
    m = np.clip(mau, 0, 255).astype(np.uint8)
    return ti_le_phu_de(m, 0, 0, m.shape[1], m.shape[0], 0) > cong.PHU_DE_TI_LE


def ap_moi_cong(nguon: NguonKhung, track: list[dict], mau: np.ndarray, cum: list[BoxMoi]) -> KetQuaVet:
    """Mọi cổng trên track cuối của một vết, theo đúng thứ tự; trả kết quả vết (sửa `track` tại chỗ)."""
    _, tcon = mat_na_va_tuong_phan(mau)
    net_pho_bien = _ap_cong_khung(nguon, track, mau, mau_giong_phu_de(mau))
    cong.go_chan_le(track)
    cong.chuan_pad_vet(track)
    khop = cong.cong_khop(track, cum)
    render = cong.khung_duoc_render(track, khop["qua_cong"])
    dem = {s: sum(1 for e in track if e.get("state") == s) for s in (cong.CHAN_PHU_DE, cong.CHAN_TUONG_PHAN, cong.CHAN_VANH, cong.CHAN_NET)}
    dem["go_chan_le"] = sum(1 for e in track if "chan_cu" in e)
    ly_do = ""
    if not render:
        ly_do = ("vết không khớp box mồi (mẫu có thể học nhầm nội dung)" if not khop["qua_cong"]
                 else "mọi khung đều bị cổng nội dung chặn (phụ đề/nét lạ chồng lên watermark)")
    return KetQuaVet("render" if render else "cho_nguoi", len(cum), track=track, khung_render=render, khop=khop,
                     tuong_phan_mau=round(tcon, 1), dem_chan=dem, net_la_pho_bien=net_pho_bien, ly_do=ly_do,
                     khung_chan=cong.khung_con_watermark_khong_thay(track))


def _box_duoc_phu(v: KetQuaVet, b: BoxMoi) -> bool:
    """Vết có ô trùng box mồi (tâm lệch ≤ 0,5 cạnh dài box) ở khung box ±1? Tính cả khung bị cổng nội dung chặn: watermark vẫn ĐÃ được
    nhận ra ở đó (chỉ không thay vì phụ đề đè lên) — không phải box mồi sai."""
    by = {e["frame"]: e for e in v.track if "x" in e}
    return any(f in by and abs(by[f]["x"] + by[f]["w"] / 2 - (b.x + b.w / 2)) <= 0.5 * max(b.w, b.h)
               and abs(by[f]["y"] + by[f]["h"] / 2 - (b.y + b.h / 2)) <= 0.5 * max(b.w, b.h) for f in (b.khung - 1, b.khung, b.khung + 1))


def _vet_da_giai_thich(vet: list[KetQuaVet], cum: list[BoxMoi]) -> KetQuaVet | None:
    """Vết đã render mà phủ ĐỦ mọi box của cụm ⇒ cụm chỉ là bản nhắc lại cùng một watermark (agy gán số cụm/cỡ khác nhau ở các
    khung khác nhau): không dò lại, không đếm là vết riêng."""
    for v in vet:
        if v.trang_thai == "render" and v.track and all(_box_duoc_phu(v, b) for b in cum):
            return v
    return None


def _xu_ly_cac_cum(nguon: NguonKhung, cum: list[list[BoxMoi]], vet: list[KetQuaVet]) -> list[BoxMoi]:
    """Xử lý từng cụm, thêm vào `vet`. Trả các box của cụm render mà vết KHÔNG phủ (số cụm agy gán nhầm, hoặc box giả lẫn vào)."""
    chua: list[BoxMoi] = []
    for cl in cum:
        trung = _vet_da_giai_thich(vet, cl)
        if len(cl) < BOX_TOI_THIEU_HAT_GIONG:
            vet.append(KetQuaVet("cho_nguoi", len(cl), nhan=_ten_cum(cl),
                                 ly_do=f"cụm chỉ có {len(cl)} box, dưới ngưỡng {BOX_TOI_THIEU_HAT_GIONG} để làm hạt giống"))
            continue
        if trung is not None:
            trung.box_cum += len(cl)
            trung.thong_tin["cum_gop"] = trung.thong_tin.get("cum_gop", 0) + 1
            continue
        v = xu_ly_vet(nguon, cl)
        vet.append(v)
        if v.trang_thai == "render":
            chua += [b for b in cl if not _box_duoc_phu(v, b)]
    return chua


def xu_ly_video(nguon: NguonKhung, boxes: list[BoxMoi], vet_cu: list[KetQuaVet] | None = None) -> KetQuaVideo:
    """Mỗi cụm box (số cụm agy + hình + vị trí) là một watermark riêng, kể cả cụm 1–2 box (hạt giống). `vet_cu` = vết của lượt trước khi
    gọi lại với box bổ sung (xem docstring module). Cụm không thành vết KHÔNG biến mất: nằm trong `vet` với trạng thái ≠ render.

    Vòng hai: box thuộc cụm đã thành vết nhưng vết không phủ (số cụm agy nhập nhầm hai watermark, hoặc box giả) KHÔNG được lặng lẽ
    rơi mất — gom lại BỎ số cụm (chỉ hình + vị trí) và xử lý như cụm mới; không thành vết thì nằm trong `vet_bi_bo`."""
    cum = gom_vet(boxes, nguon)
    vet = list(vet_cu or [])
    box_cu = sum(v.box_cum for v in vet)
    chua = _xu_ly_cac_cum(nguon, cum, vet)
    if chua:
        _xu_ly_cac_cum(nguon, gom_vet([replace(b, cum=None) for b in chua], nguon), vet)
    return KetQuaVideo(vet, len(boxes) + box_cu, len(cum) + len(vet_cu or []))
