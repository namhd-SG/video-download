"""Che qua chữ (`qua_chu.lap_qua_chu`) trên clip TỔNG HỢP có ground truth: đoạn bị cổng chặn ngắn giữa hai khung đang dán được che (đè
chữ, user 16/10), đúng vị trí logo; đoạn dài / logo nhảy chỗ / khung box mồi giữ nguyên.
Mỗi tính năng có đột biến chứng minh fixture phân định được."""
import dataclasses

import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless")

from thay_logo_tong_hop import tam_lech, tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import cong, duong_ong, qua_chu  # noqa: E402
from tiktok_music_downloader.thay_logo.kiem_hinh import CHAN_HINH  # noqa: E402

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
    tai_box = [k for k in PHU_DE if k in box]
    assert tai_box and all(k in by and by[k]["plate_pad"] == cong.PAD_CHAT for k in tai_box)  # khung box mồi ±1 gỡ tại chỗ, tấm nền hẹp
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


def _track(clip, chan, state=cong.CHAN_PHU_DE, co_vi_tri=False):
    """Track từ ground truth; khung trong `chan` bị cổng `state` chặn (có/không vị trí vết dò)."""
    out = []
    for i, (x, y, w, h) in enumerate(clip.hop_that):
        an = i in chan
        out.append({"frame": i, "x": None if an and not co_vi_tri else x, "y": None if an and not co_vi_tri else y, "w": w, "h": h,
                    "state": state if an else "detected", "score": (0.5 if co_vi_tri else None) if an else 0.9})
    return out


def test_logo_nhay_cho_thi_khong_lap_gi():
    """Logo nhảy 140 px giữa k14 và k15 (kiểu Test 03_1 k4353–4357), k10–19 bị chặn không có vị trí: đường không AI không biết logo đi
    đâu ⇒ không dán khung nào (dò ảnh ở đây từng dán lên má em bé / tháp)."""
    clip = tao_clip(n=30, duong_di=lambda i: (60, 420) if i < 15 else (60, 560))
    track = _track(clip, set(range(10, 20)))
    assert qua_chu.lap_qua_chu(clip.nguon, track, []) == {"noi": 0}
    assert not any(e.get("qua_chu") for e in track)


def test_khung_box_moi_trung_vet_go_tai_cho_tam_nen_hep():
    """Đoạn chặn k10–13, box mồi ở k12, vết dò ở k11–13 trùng box ⇒ gỡ TẠI CHỖ (không dời, tấm nền hẹp như khung che qua chữ): không
    nháy giữa vùng đã che (go_chan_le không gỡ được khi bị giữ chặn / kiểm hình bác / đoạn box > 3 khung), không phình tấm nền."""
    clip = tao_clip(n=30)
    track = _track(clip, set(range(10, 14)), state=CHAN_HINH, co_vi_tri=True)
    qua_chu.lap_qua_chu(clip.nguon, track, clip.box_moi(khung=(12,)))
    assert all(track[k].get("qua_chu") == "noi" and track[k]["plate_pad"] == cong.PAD_CHAT for k in range(10, 14))
    assert all(tam_lech(track[k], clip.hop_that[k]) == 0 for k in (11, 12, 13))
    assert all(track[k]["state"] == "detected" for k in (11, 12, 13))  # có điểm vết dò ⇒ detected


def test_khung_box_moi_khong_trung_vet_de_nguyen():
    """Vết dò ở k11–13 lệch xa box mồi k12 ⇒ không gỡ, không dời (dời làm box mồi "không được phủ" ⇒ cả video chờ người — 03_38)."""
    clip = tao_clip(n=30)
    track = _track(clip, set(range(10, 14)), state=cong.CHAN_NET, co_vi_tri=True)
    for k in (11, 12, 13):
        track[k]["x"] += 80
    qua_chu.lap_qua_chu(clip.nguon, track, clip.box_moi(khung=(12,)))
    assert not any(track[k].get("qua_chu") for k in (11, 12, 13))
    assert all(track[k]["state"] == cong.CHAN_NET for k in (11, 12, 13))


def test_box_moi_cum_khac_cung_duoc_go_tai_cho():
    """Box mồi thuộc cụm KHÁC (agy tách một logo thành hai cụm) mà vết trùng ⇒ cũng gỡ tại chỗ, không dời — để vết vẫn phủ box đó và
    cụm kia được gộp (`_vet_da_giai_thich`)."""
    clip = tao_clip(n=30)
    track = _track(clip, set(range(10, 14)), state=cong.CHAN_NET, co_vi_tri=True)
    for k in (11, 12, 13):
        track[k]["y"] += 15  # vết lệch đường nối > GAN_DET nhưng vẫn trùng box ⇒ chỉ gỡ tại chỗ mới giữ vị trí này
    khac = [dataclasses.replace(b, cum=7) for b in clip.box_moi(khung=(12,))]
    qua_chu.lap_qua_chu(clip.nguon, track, [], moi_box=khac)
    assert all(track[k].get("qua_chu") == "noi" and track[k]["y"] == clip.hop_that[k][1] + 15 for k in (11, 12, 13))


def test_box_moi_sai_khung_bi_kiem_hinh_bac_lech_duong_thi_de_nguyen():
    """Kiểu Test 03_5 k895–897: box mồi nằm cao hơn logo thật, vết lõi kẻ trùng box nhưng kiểm hình đã bác (`hidden_hinh`) và lệch đường
    nối hai đầu > GAN_DET ⇒ KHÔNG gỡ tại chỗ (box mồi có thể sai), không dời."""
    clip = tao_clip(n=30)
    track = _track(clip, set(range(10, 14)), state=CHAN_HINH, co_vi_tri=True)
    for k in (11, 12, 13):
        track[k]["y"] -= 30
    sai = [dataclasses.replace(b, y=b.y - 30) for b in clip.box_moi(khung=(12,))]
    qua_chu.lap_qua_chu(clip.nguon, track, sai)
    assert not any(track[k].get("qua_chu") for k in (11, 12, 13))
    assert all(track[k]["state"] == CHAN_HINH for k in (11, 12, 13))


def test_box_moi_lech_duong_noi_van_lap_cac_khung_con_lai():
    """Box mồi trong đoạn chặn nằm lệch đường nối a → b (Test 03_38 k297 lệch ~53 px): các khung không phải box mồi vẫn được dán theo
    đường. Chặn cả đoạn trong ca này để lộ hẳn logo ở 03_38 k287–299 (đo 16/10: lộ 0,4% → 1,8%)."""
    clip = tao_clip(n=40)
    chan = set(range(10, 30))
    track = _track(clip, chan)
    b = clip.box_moi(khung=(20,))[0]
    lech = dataclasses.replace(b, x=b.x + 60)  # box mồi lệch hẳn khỏi đường nối
    qua_chu.lap_qua_chu(clip.nguon, track, [lech])
    lap = [k for k in sorted(chan) if k not in (19, 20, 21)]
    assert all(track[k].get("qua_chu") == "noi" and tam_lech(track[k], clip.hop_that[k]) <= 12 for k in lap)
    assert not any(track[k].get("qua_chu") for k in (19, 20, 21))


def test_vet_do_that_gan_duong_duoc_giu_vi_tri_khung_kiem_hinh_bac_thi_khong():
    """Logo lượn nhẹ (≤10 px khỏi đường thẳng) trong đoạn chặn k10–19: khung có vết dò thật nằm ≤ GAN_DET quanh đường ⇒ dán ĐÚNG vị trí
    vết dò; khung kiểm hình đã bác (`hidden_hinh`, vị trí lõi tự kẻ) ⇒ không tin vị trí đó, dán theo đường."""
    def di(i):
        return (60, 420 + (10 if 12 <= i <= 17 else 0))
    clip = tao_clip(n=30, duong_di=di)
    track = _track(clip, set(range(10, 20)), state=cong.CHAN_PHU_DE, co_vi_tri=True)
    qua_chu.lap_qua_chu(clip.nguon, track, [])
    assert all(track[k].get("qua_chu") == "noi" and tam_lech(track[k], clip.hop_that[k]) == 0 for k in range(10, 20))
    track = _track(clip, set(range(10, 20)), state=CHAN_HINH, co_vi_tri=True)
    qua_chu.lap_qua_chu(clip.nguon, track, [])
    assert all(track[k].get("qua_chu") == "noi" for k in range(10, 20))
    assert max(tam_lech(track[k], clip.hop_that[k]) for k in range(12, 18)) >= 8  # theo đường thẳng, không theo vị trí bị bác


def test_khung_che_qua_chu_khong_keo_ca_vet_sang_tam_nen_hep():
    """Khung che qua chữ luôn mang tấm nền hẹp; nếu đếm chúng vào ngưỡng ≥20% thì cả vết bị ép tấm nền hẹp dù phụ đề sát chỉ 0–1 khung
    (Test 03_10: 99/474 = 20,9% khung che qua chữ)."""
    track = [{"frame": i, "state": "detected", "plate_pad": cong.PAD_TAM_NEN} for i in range(100)]
    for e in track[:25]:
        e.update(state="filled", qua_chu="noi", plate_pad=cong.PAD_CHAT)
    cong.chuan_pad_vet(track)
    assert all(e["plate_pad"] == cong.PAD_TAM_NEN for e in track[25:])
    for e in track[25:50]:  # phụ đề sát thật ≥20% các khung không phải che qua chữ ⇒ cả vết hẹp
        e["plate_pad"] = cong.PAD_CHAT
    cong.chuan_pad_vet(track)
    assert all(e["plate_pad"] == cong.PAD_CHAT for e in track)


def test_khung_box_moi_khong_trung_vet_khoa_khoi_go_chan_le():
    """Mẩu ≤ 3 khung box mồi ±1 để nguyên phải được khoá: không thì `go_chan_le` gỡ nó tại vị trí lệch box ⇒ `cong_khop` đếm lệch.
    Xảy ra cả với 1 box (k11–13) lẫn khi 2 box chẻ đoạn chặn (k14–15 lệch box k14, k11–13 trùng box k12)."""
    clip = tao_clip(n=30)
    track = _track(clip, set(range(10, 14)), state=cong.CHAN_NET, co_vi_tri=True)
    for k in (11, 12, 13):
        track[k]["x"] += 80
    cum = clip.box_moi(khung=(12,))
    qua_chu.lap_qua_chu(clip.nguon, track, cum)
    cong.go_chan_le(track)
    assert track[10].get("qua_chu") == "noi"
    assert all(track[k]["state"] == cong.CHAN_NET and track[k].get("giu_chan") for k in (11, 12, 13))
    assert cong.cong_khop(track, cum)["lech"] == 0

    track = _track(clip, set(range(11, 16)), state=cong.CHAN_NET, co_vi_tri=True)
    for k in (14, 15):
        track[k]["x"] += 80
    cum = clip.box_moi(khung=(12, 14))
    qua_chu.lap_qua_chu(clip.nguon, track, cum)
    cong.go_chan_le(track)
    assert all(track[k]["state"] == "detected" and track[k].get("qua_chu") == "noi" for k in (11, 12, 13))
    assert all(track[k]["state"] == cong.CHAN_NET and track[k].get("giu_chan") for k in (14, 15))
    khop = cong.cong_khop(track, cum)
    assert khop["lech"] == 0 and khop["qua_cong"]



def test_xu_ly_video_truyen_moi_box_giua_hai_cum_cung_logo(monkeypatch):
    """Một logo bị tách hai cụm: che qua chữ của MỖI cụm phải nhận box mồi của MỌI cụm (`moi_box`), không thì khung box cụm kia nằm
    trong đoạn chặn bị kéo về đường thẳng ⇒ box đó "không được phủ" ⇒ cụm không gộp được (03_38). Clip tổng hợp không dựng được vết
    dò lệch đường dưới phụ đề (bộ lọc vết giữ vị trí cũ), nên khoá dây nối bằng cách ghi lại `moi_box` mà `lap_qua_chu` nhận."""
    nhan = []

    def ghi(nguon, track, cum, moi_box=None):
        nhan.append(moi_box)
        return qua_chu.lap_qua_chu(nguon, track, cum, moi_box)

    monkeypatch.setattr(duong_ong, "lap_qua_chu", ghi)
    clip = tao_clip(phu_de_vien_den=PHU_DE)
    boxes = clip.box_moi(khung=(5, 15, 35), cum=0) + clip.box_moi(khung=(25,), cum=1)
    kq = duong_ong.xu_ly_video(clip.nguon, boxes)
    assert kq.trang_thai == "render" and len(kq.vet) == 1
    assert nhan and all(m is not None and {b.khung for b in m} == {5, 15, 25, 35} for m in nhan)


def test_dai_phu_de_50_khung_van_noi_duoc():
    """Dải phụ đề 50 khung liền (Test 03_5 k854–903) không còn mốc dò nào ở giữa ⇒ vẫn nối qua, đúng chỗ logo."""
    clip = tao_clip(n=80)
    track = _track(clip, set(range(10, 60)))
    assert qua_chu.lap_qua_chu(clip.nguon, track, []) == {"noi": 50}
    assert all(tam_lech(track[k], clip.hop_that[k]) <= 12 for k in range(10, 60))


def test_dot_bien_gap_max_cu_thi_dai_50_khung_lo(monkeypatch):
    monkeypatch.setattr(qua_chu, "GAP_MAX", 45)
    clip = tao_clip(n=80)
    track = _track(clip, set(range(10, 60)))
    assert qua_chu.lap_qua_chu(clip.nguon, track, []) == {"noi": 0}
