"""Đường ống một video: box mồi → gom vết → mỗi vết: mồi đồng thuận → mẫu → ứng viên + nối vết (xuôi/ngược) → tự học → lấp lỗ + làm
mượt → các cổng nội dung → cổng khớp mồi → bằng chứng → chỉ số nháy.

Quy tắc kết luận video (không im lặng): video chỉ `render` khi MỌI cụm box đều thành vết `render`. Có cụm không thành vết (thiếu bằng
chứng, mẫu hỏng, khớp mồi trượt, mọi khung bị chặn) ⇒ video `cho_nguoi` kèm `ly_do` + danh sách `vet_bi_bo`; worker đẩy người duyệt.
Không render, không gọi agy — box mồi do người gọi đưa vào.

API gọi lại được (vòng kiểm kết quả ở bước sau): `xu_ly_video(nguon, boxes_bo_sung, vet_cu=kq_truoc.vet)` — box bổ sung được gom + xử lý
như mọi box, vết cũ giữ nguyên; `KetQuaVideo.vet` = cũ + mới nên `render.gom_khung_render` ra HỢP mặt nạ cũ và mới.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

import numpy as np

from . import cong
from .ai_vong_hai import gan_moc_ai
from .bam_hai_chieu import bam_lai_doan_mat
from .box_moi import BoxMoi, chon_moi_dong_thuan, gom_vet
from .chu_phu_de import bo_moi_chu, cham_qua_chu, gan_chu, la_logo_qua_chu
from .dinh_vi import dinh_vi, ti_le_phu_de
from .kiem_hinh import CHAN_HINH, kiem_hinh_truoc_dan, san_hinh
from .lam_muot_vet import TOC_DO_NHAY, lap_va_lam_muot
from .lo_trinh import theo_lo_trinh
from .mau import dung_mau_sach, mat_na_va_tuong_phan, tu_hoc_mau
from .nguon_khung import NguonKhung
from .nhay import do_nhay
from .qua_chu import lap_qua_chu
from .theo_vet import theo_vet

# Đè khi đã biết chỗ (thử nghiệm đo 21/10, CHƯA bật trên prod): "" = tắt (hành vi cũ); "A:10" = chỉ khung kiểm hình chặn, khung lấp
# kẹp giữa hai khung dò thật cách ≤ 10 khung; "B" = thêm cổng nội dung, không giới hạn khoảng kẹp; "L" = lai (cổng nội dung không
# giới hạn, kiểm hình ≤ 10, neo sạch, không đè hinh_hut). Xem cong.de_khi_biet_cho.
DE_KHI_BIET = os.environ.get("THAY_LOGO_DE_KHI_BIET", "")


def _muc_de_khi_biet(gia_tri: str) -> tuple[str, int | None] | None:
    if not gia_tri:
        return None
    muc, _, kep = gia_tri.partition(":")
    if muc not in ("A", "B", "L"):
        raise ValueError(f"THAY_LOGO_DE_KHI_BIET lạ: {gia_tri!r}")
    return muc, (int(kep) if kep else None)

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
    san = san_hinh(track)
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    by = {e["frame"]: e for e in track if e.get("state") in cong.DA_CHAC}
    vanh: dict[int, float] = {}
    net: dict[int, float] = {}
    if by:
        cuoi = max(by)
        for i, g in enumerate(nguon.doc_tuan_tu()):
            e = by.get(i)
            if e is not None:
                if e.get("ai"):
                    e["plate_pad"] = cong.PAD_CHAT  # khung AI được đè chữ/vật: tấm nền ép sát logo cũ
                if not bo_phu_de and gan_chu(g, e) and _logo_de_chu(g, e, mau_u8, san):
                    e["de_chu"], e["plate_pad"] = True, cong.PAD_CHAT  # user cho đè chữ: bỏ cổng phụ đề + vành, nét lạ không tính chữ
                if not bo_phu_de and not e.get("de_chu") and not e.get("ai"):
                    cong.cong_phu_de(g, e)
                if e["state"] in cong.DA_CHAC and not e.get("ai"):  # AI đã xác nhận logo ⇒ được đè cả vật/chữ (user chốt 15/10 12:46)
                    cong.cong_tuong_phan(g, e, mask, nguong)
                if e["state"] in cong.DA_CHAC:  # đo cả khung đè chữ/AI cho thống kê ngưỡng; chúng được miễn chặn ở _chan_theo_video
                    vanh[i] = e["vanh"] = round(cong.ti_le_vanh(g, e), 4)
                if e["state"] in cong.DA_CHAC or e["state"] == cong.CHAN_TUONG_PHAN:  # khung bị tương phản chặn cũng cần đo để xét gỡ
                    net[i] = e["net_la"] = round(cong.ti_le_net_la(g, e, mau, bool(e.get("de_chu"))), 4)
            if i >= cuoi:
                break
    cong.cong_vanh_ngang(track, vanh)
    pho_bien = cong.cong_net_la(track, net)
    cong.go_chan_theo_hinh(track, net, san)
    return pho_bien


def _logo_de_chu(g: np.ndarray, e: dict, mau_u8: np.ndarray, san: float | None) -> bool:
    """Khung gần chữ phụ đề là LOGO THẬT đè chữ (được dán đè, user chốt 15/10) ⟺ đã có bằng chứng bám hai chiều (`quy_dao`) HOẶC điểm sau
    xoá chữ qua sàn hình của vết VÀ không tụt so với trước xoá (chữ phụ đề giống logo thì tụt — xem chu_phu_de)."""
    if e.get("quy_dao"):
        return True
    if san is None:
        return False
    t, x = cham_qua_chu(g, mau_u8, e)
    e["diem_xoa_chu"] = round(x, 3)
    return x >= san and la_logo_qua_chu(t, x)


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


def _so_box_tinh(cum: list[BoxMoi]) -> int:
    """Số box lớn nhất cùng đứng yên một chỗ (cách ≥ 10 khung, IoU ≥ 0,5 — cùng tiêu chí `_neo`). Cụm nhiều box nhưng mỗi chỗ chỉ một
    box (logo nhảy bậc) có số này = 1: chưa đủ để tách nền bằng đếm box."""
    return max((1 + sum(1 for o in cum if abs(o.khung - b.khung) >= 10 and _iou_box(b, o) >= 0.5) for b in cum), default=0)


def _iou_box(a: BoxMoi, b: BoxMoi) -> float:
    iw, ih = min(a.x + a.w, b.x + b.w) - max(a.x, b.x), min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return 0.0 if iw <= 0 or ih <= 0 else iw * ih / (a.w * a.h + b.w * b.h - iw * ih)


def _bang_chung(det: dict[int, dict], khung_moi: set[int], so_box: int, tt: dict, so_box_tinh: int | None = None) -> str:
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
    if (so_box if so_box_tinh is None else so_box_tinh) < CUM_LON:  # tách nền: chỉ box đứng yên mới là bằng chứng
        diem = float(np.median([det[t]["score"] for t in ngoai]))
        if diem < tt["nen95"] + BIEN_TACH_NEN:
            return f"điểm khớp trung vị {diem:.2f} không tách khỏi nền nhiễu của video ({tt['nen95']:.2f}): có thể là nội dung"
    return ""


def xu_ly_vet(nguon: NguonKhung, cum: list[BoxMoi], neo_ai: list[BoxMoi] = (), moi_box: list[BoxMoi] | None = None) -> KetQuaVet:
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
    uv = dinh_vi(nguon, mau, neo, 1, not mau_giong_phu_de(mau),
                 [(b.x, b.y, b.w, b.h, b.khung - NEO_KHUNG, b.khung + NEO_KHUNG) for b in neo_ai])
    n = len(uv)
    hop_moi: dict[int, list[tuple]] = {}
    for b in cum:
        hop_moi.setdefault(b.khung, []).append((b.x, b.y, b.w, b.h))
    det, tt = theo_vet([u for u, _ in uv], mau.shape[::-1], khung_moi, hop_moi)  # chỉ lần cuối có cổng danh tính
    det_sach, moi_chu = (det, 0) if mau_giong_phu_de(mau) else bo_moi_chu(nguon, det, mau)  # vết khoá nhầm chữ phụ đề ⇒ thành lỗ
    ai = {}
    if neo_ai:  # lộ trình chỉ chạy ở lượt có AI: không mốc AI thì mồi đứng yên dày đặc (test_2 k371–k403) chiếm đa số cửa sổ khớp
        det_sach, ai = gan_moc_ai(nguon, det_sach, uv, mau, neo_ai)
        det_sach, ai["lo_trinh"] = theo_lo_trinh(nguon, det_sach, mau, list(neo_ai), len(uv))
    det_bam, bam = bam_lai_doan_mat(nguon, det_sach, mau)  # `det` gốc giữ cho _bang_chung: khung bám lại không làm vết "có thật" hơn
    bam["moi_chu"] = moi_chu
    che, doan = lap_va_lam_muot(det_bam, n)
    che = _kep_vao_khung(che, nguon.rong, nguon.cao)
    track = _track_day_du(n, che, uv)
    hinh = kiem_hinh_truoc_dan(nguon, track, mau)
    kq = ap_moi_cong(nguon, track, mau, cum, moi_box)
    kq.ncc_moi, kq.tu_hoc_bi_tu_choi, kq.nhan, kq.doan, kq.thong_tin = round(ncc, 3), tu_choi, nhan, doan, dict(tt, kiem_hinh=hinh, bam_hai_chieu=bam, ai_vong_hai=ai)
    ly_do = _bang_chung(det, khung_moi, len(cum), tt, _so_box_tinh(cum))
    if ly_do:
        kq.trang_thai, kq.khung_render, kq.ly_do = "cho_nguoi", [], ly_do
    kq.nhay = do_nhay(doan, {e["frame"] for e in kq.khung_render})
    return kq


def mau_giong_phu_de(mau: np.ndarray) -> bool:
    """Mẫu watermark chính nó đã là chữ trắng viền đen: bộ lọc/cổng phụ đề không phân định được ⇒ phải tắt, kẻo giết cả vết."""
    m = np.clip(mau, 0, 255).astype(np.uint8)
    return ti_le_phu_de(m, 0, 0, m.shape[1], m.shape[0], 0) > cong.PHU_DE_TI_LE


def ap_moi_cong(nguon: NguonKhung, track: list[dict], mau: np.ndarray, cum: list[BoxMoi], moi_box: list[BoxMoi] | None = None) -> KetQuaVet:
    """Mọi cổng trên track cuối của một vết, theo đúng thứ tự; trả kết quả vết (sửa `track` tại chỗ)."""
    _, tcon = mat_na_va_tuong_phan(mau)
    net_pho_bien = _ap_cong_khung(nguon, track, mau, mau_giong_phu_de(mau))
    qua_chu = lap_qua_chu(nguon, track, cum, moi_box)
    cong.go_chan_le(track)
    muc = _muc_de_khi_biet(DE_KHI_BIET)
    if not muc:
        cong.chuan_pad_vet(track)
    khop = cong.cong_khop(track, cum)
    de_khi_biet = 0
    if muc and khop["qua_cong"]:  # sau cổng khớp: không đổi vết nào được render, chỉ thêm khung được đè trong vết đã render
        de_khi_biet = cong.de_khi_biet_cho(track, *muc)
    if muc:  # pad cố định theo vết phải tính cả khung vừa đè lại (cong_khop không đọc/ghi plate_pad)
        cong.chuan_pad_vet(track)
    render = cong.khung_duoc_render(track, khop["qua_cong"])
    dem = {s: sum(1 for e in track if e.get("state") == s)
           for s in (cong.CHAN_PHU_DE, cong.CHAN_TUONG_PHAN, cong.CHAN_VANH, cong.CHAN_NET, CHAN_HINH)}
    dem["go_chan_le"] = sum(1 for e in track if "chan_cu" in e and not e.get("go_hinh") and not e.get("qua_chu")
                            and not e.get("de_khi_biet"))
    dem["go_theo_hinh"] = sum(1 for e in track if e.get("go_hinh"))
    dem["de_chu"] = sum(1 for e in track if e.get("de_chu") and e.get("state") in cong.DA_CHAC and not e.get("qua_chu"))
    dem["qua_chu"] = qua_chu
    dem["de_khi_biet"] = de_khi_biet
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


# Dán logo SAI CHỖ (lên người, phụ đề) tệ hơn SÓT: video sai đi thẳng tới khách, `cho_nguoi` chỉ tốn công người xem lại (ĐP 14/10).
# Hạt giống 1–2 box vẫn được DÒ (vết + lý do hiện cho người duyệt) nhưng không tự render: mẫu từ 1–2 crop có thể là nền, vết bám nền
# tĩnh qua mọi cổng — tái hiện ở v24 L2 khi agy gán box BR một số cụm riêng.
LY_DO_HAT_GIONG_NHO = ("vết dựng từ {n} box agy (dưới " + str(CUM_LON) + "): mẫu ít crop có thể là nền/nội dung — cần người kiểm, "
                       "máy không tự thay")
LY_DO_VONG_HAI = ("box agy không được vết nào phủ; vết dò lại từ box này có thể bám vào nền/nội dung (mẫu học từ ít box) — "
                  "cần người kiểm, máy không tự thay")


def _xu_ly_cac_cum(nguon: NguonKhung, cum: list[list[BoxMoi]], vet: list[KetQuaVet], tu_render: bool = True,
                   neo_ai: list[BoxMoi] = (), moi_box: list[BoxMoi] | None = None) -> list[BoxMoi]:
    """Xử lý từng cụm, thêm vào `vet`. Trả các box của cụm render mà vết KHÔNG phủ (số cụm agy gán nhầm, hoặc box giả lẫn vào).

    `tu_render=False` (vòng hai): vết MỚI dò từ box sót không được tự render. Mẫu học từ 1–2 box mà phần lớn crop là nền thì vết bám
    nền tĩnh, qua mọi cổng (khớp mồi đúng chỗ, dò được hàng trăm khung) và dán logo lên nội dung cả video — đo được ở v24 L2 (chân
    người) và v05 L2 (phụ đề). Cụm vòng hai trùng vết vòng một thì vẫn gộp như thường."""
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
        if tu_render and len(cl) < CUM_LON and not any(b.nguon == "tay" for b in cl):
            # hạt giống nhỏ không bao giờ tự render ở vòng một (xem dưới): khỏi dò cả video để rồi bỏ — đỡ vết/ảnh rác
            vet.append(KetQuaVet("cho_nguoi", len(cl), nhan=_ten_cum(cl), ly_do=LY_DO_HAT_GIONG_NHO.format(n=len(cl))))
            continue
        so_cum = {b.cum for b in cl}
        ai = [b for b in neo_ai if b.cum in so_cum]
        v = xu_ly_vet(nguon, cl, ai, moi_box) if ai else xu_ly_vet(nguon, cl, moi_box=moi_box)
        if v.trang_thai == "render" and not tu_render:
            v.trang_thai, v.khung_render, v.ly_do = "cho_nguoi", [], LY_DO_VONG_HAI
        elif v.trang_thai == "render" and len(cl) < CUM_LON:
            v.trang_thai, v.khung_render, v.ly_do = "cho_nguoi", [], LY_DO_HAT_GIONG_NHO.format(n=len(cl))
        vet.append(v)
        if v.trang_thai == "render":
            chua += [b for b in cl if not _box_duoc_phu(v, b)]
    return chua


def xu_ly_video(nguon: NguonKhung, boxes: list[BoxMoi], vet_cu: list[KetQuaVet] | None = None,
                neo_ai: list[BoxMoi] = ()) -> KetQuaVideo:
    """Mỗi cụm box (số cụm agy + hình + vị trí) là một watermark riêng, kể cả cụm 1–2 box (hạt giống). `vet_cu` = vết của lượt trước khi
    gọi lại với box bổ sung (xem docstring module). Cụm không thành vết KHÔNG biến mất: nằm trong `vet` với trạng thái ≠ render.

    Vòng hai: box thuộc cụm đã thành vết nhưng vết không phủ (số cụm agy nhập nhầm hai watermark, hoặc box giả) KHÔNG được lặng lẽ
    rơi mất — gom lại BỎ số cụm (chỉ hình + vị trí) và xử lý như cụm mới; cụm mới đó KHÔNG tự render (xem `_xu_ly_cac_cum`) mà nằm
    trong `vet_bi_bo` ⇒ video `cho_nguoi`. Mọi box sót vì thế đều có dấu vết, không rơi mất sau vòng hai."""
    cum = gom_vet(boxes, nguon)
    vet = list(vet_cu or [])
    box_cu = sum(v.box_cum for v in vet)
    chua = _xu_ly_cac_cum(nguon, cum, vet, neo_ai=neo_ai, moi_box=boxes)  # neo_ai: box AI vòng hai — CHỈ làm mốc dò cục bộ, không vào mẫu/khớp mồi
    if chua:
        _xu_ly_cac_cum(nguon, gom_vet([replace(b, cum=None) for b in chua], nguon), vet, tu_render=False, moi_box=boxes)
    return KetQuaVideo(vet, len(boxes) + box_cu, len(cum) + len(vet_cu or []))
