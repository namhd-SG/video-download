"""Trọn luồng với agy/Chrome/mạng giả, trường lấy từ dữ liệu agy thật GĐ1. Kiểm: chỉ hạng đạt vào links.txt, hop 2 sinh từ
caption kết quả đạt, ctrl trượt ⇒ không xuất link, hết lượt ⇒ dừng có ghi lý do, trang HTML render."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from PIL import Image

from tiktok_music_downloader.tim_trend import agy_boc, anh_bia, khung, luong
from tiktok_music_downloader.tim_trend.nguon_tim import HetLuot, UngVien
from tiktok_music_downloader.tim_trend.trang import render
from tiktok_music_downloader.tim_trend.truong import tu_json

_FIX = Path(__file__).parent / "fixtures" / "tim_trend" / "truong-gd1.json"
F = {m["id"]: m for m in json.loads(_FIX.read_text())["items"]}

# video_id giả ⇒ (mục fixture, caption)
UV = {
    "7000000000000000001": ("s6-7", "lookbook ai kolase multi pose foto potret"),
    "7000000000000000002": ("s7-1", "Tren AI ubah foto menjadi kolase 7 pose Tutorial Pembuatan Gratis"),
    "7000000000000000003": ("s1-7", "ai fashion model"),
    "7000000000000000004": ("s3-4", "dog catwalk"),
    "7000000000000000005": ("s7-0", "kolase multi pose lookbook ai trend"),
    "7000000000000000006": ("s2-3", "baby clone"),
}
HOP1 = ["7000000000000000001", "7000000000000000002", "7000000000000000003", "7000000000000000004"]
HOP2 = ["7000000000000000005", "7000000000000000006"]


def _uv(vid, q):
    return UngVien(f"https://www.tiktok.com/@u{vid[-1]}/video/{vid}", vid, f"https://cdn/{vid}.jpg", UV[vid][1], f"u{vid[-1]}", q)


class _NguonGia:
    def __init__(self, tran=99):
        self.da_mo, self.tran, self.goi = 0, tran, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def tim(self, tv):
        if self.da_mo >= self.tran:
            raise HetLuot("het")
        self.da_mo += 1
        self.goi.append(tv.text)
        ids = HOP1 if len(self.goi) == 1 else HOP2 if "kolase" in tv.text else []
        return [_uv(v, tv.text) for v in ids], ""


@pytest.fixture
def gia(monkeypatch, tmp_path):
    trang_thai = {"ctrl": "ctrl-1"}

    def trich(video, thu_muc, tien_to="dau-vao"):
        thu_muc.mkdir(parents=True, exist_ok=True)
        ra = []
        for i in range(3):
            p = thu_muc / f"{tien_to}-{i}.jpg"
            Image.new("RGB", (36, 64), "white").save(p)
            ra.append(p)
        return ra

    def boc(anh, thu_muc_ra, model=None, ten=""):
        ra = {}
        for a in anh:
            if a.stem.startswith("dau-vao"):
                m = F["ctrl-0"]
            elif a.stem.startswith("ctrl-"):
                m = F[trang_thai["ctrl"]]
            else:
                m = F[UV[a.stem][0]]
            ra[a.stem] = tu_json(dict(m, id=a.stem))
        return ra

    def tai(ds, thu_muc, gian_cach):
        thu_muc.mkdir(parents=True, exist_ok=True)
        tot = {}
        for vid, _ in ds:
            rnd = random.Random(vid)   # ảnh khác nhau ⇒ dHash không gộp nhầm
            img = Image.new("L", (64, 64))
            img.putdata([rnd.randrange(256) for _ in range(64 * 64)])
            tot[vid] = thu_muc / f"{vid}.jpg"
            img.save(tot[vid])
        return tot, {}

    monkeypatch.setattr(khung, "trich_khung", trich)
    monkeypatch.setattr(agy_boc, "boc_truong", boc)
    monkeypatch.setattr(agy_boc, "goi_y_tu_khoa", lambda *a, **k: [])
    monkeypatch.setattr(anh_bia, "tai_anh_bia", tai)
    video = tmp_path / "video test.mp4"
    video.write_bytes(b"x")
    return trang_thai, video


def test_tron_luong_chi_hang_dat_vao_links(gia, tmp_path):
    _, video = gia
    nguon = _NguonGia()
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: nguon, so_truy_van=6, so_hop=2, bao=lambda s: None)
    assert kq.tin_duoc and kq.chu_ky.so_ban_sao == 7
    hang = {u["video_id"]: u["hang"] for u in kq.ung_vien}
    assert hang == {"7000000000000000001": "3", "7000000000000000002": "2A", "7000000000000000003": "1",
                    "7000000000000000004": "0", "7000000000000000005": "3", "7000000000000000006": "2B"}
    assert any("kolase" in q for q in nguon.goi[1:])   # hop 2 sinh từ caption kết quả đạt
    luong.ghi_links(kq, ra)
    assert (ra / "links.txt").read_text().split() == [
        "https://www.tiktok.com/@u1/video/7000000000000000001", "https://www.tiktok.com/@u2/video/7000000000000000002",
        "https://www.tiktok.com/@u5/video/7000000000000000005"]
    html = render(kq, ra, video.name).read_text()
    assert "Đúng dạng" in html and "7000000000000000005" in html and "TRƯỢT" not in html


def test_ctrl_truot_thi_khong_xuat_link(gia, tmp_path):
    trang_thai, video = gia
    trang_thai["ctrl"] = "s3-4"   # agy đọc khung đầu vào thành con chó ⇒ ctrl không ra hạng 3
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert not kq.tin_duoc and all(u["hang"] is None for u in kq.ung_vien)
    assert luong.ghi_links(kq, ra) == [] and not (ra / "links.txt").exists()
    assert "TRƯỢT" in render(kq, ra, video.name).read_text()


def test_het_luot_dung_co_ghi_ly_do(gia, tmp_path):
    _, video = gia
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: _NguonGia(tran=1), so_hop=2, bao=lambda s: None)
    assert kq.dung_vi == "het" and kq.so_lan_mo_trang == 1 and len(kq.ung_vien) == 4


def test_chia_khoi_50(tmp_path):
    kq = luong.KetQua(ung_vien=[{"url": f"https://www.tiktok.com/@a/video/{7 * 10**18 + i}", "hang": "3"} for i in range(120)])
    tep = luong.ghi_links(kq, tmp_path)
    assert [p.name for p in tep] == ["links.txt", "links-01.txt", "links-02.txt", "links-03.txt"]
    assert [len(p.read_text().split()) for p in tep] == [120, 50, 50, 20]


def test_khong_co_ung_vien_nao_thi_khong_ghi_links(gia, tmp_path):
    """Pha 4 22/10: 12/12 lần mở trang feed rỗng ⇒ trước đây ghi links.txt rỗng + thoát 0, trông như "xong, 0 kết quả"."""
    _, video = gia

    class _Rong(_NguonGia):
        def tim(self, tv):
            self.da_mo += 2
            return [], "ham phien; feed rong sau ham phien"

    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _Rong(), so_hop=2, bao=lambda s: None)
    assert kq.rong and kq.tin_duoc
    assert luong.ghi_links(kq, ra) == [] and not (ra / "links.txt").exists()
    assert "KHÔNG CÓ ỨNG VIÊN" in render(kq, ra, video.name).read_text()


def test_captcha_dung_ca_lan_chay(gia, tmp_path):
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    _, video = gia

    class _Captcha(_NguonGia):
        def tim(self, tv):
            self.da_mo += 1
            raise BiCaptcha("TikTok hỏi captcha ở lần mở trang thứ 1")

    nguon = _Captcha()
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: nguon, so_hop=2, bao=lambda s: None)
    assert "captcha" in kq.dung_vi and kq.bi_captcha and nguon.da_mo == 1 and kq.rong
    assert luong.ghi_links(kq, tmp_path / "ra") == []
    assert "CAPTCHA" in render(kq, tmp_path / "ra", video.name).read_text()


class _NguonLan:
    """Hop 1 trả kết quả; từ lượt thứ `loi_tu` ném lỗi `loi`. Đếm cả lượt ném lỗi."""

    def __init__(self, loi, loi_tu=2):
        self.loi, self.loi_tu, self.thu, self.da_mo = loi, loi_tu, 0, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def tim(self, tv):
        self.thu += 1
        self.da_mo += 1
        if self.thu >= self.loi_tu:
            raise self.loi
        return [_uv(v, tv.text) for v in HOP1], ""


def test_captcha_o_hop2_sau_khi_hop1_co_ket_qua_thi_khong_xuat_link(gia, tmp_path):
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    _, video = gia
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _NguonLan(BiCaptcha("captcha")), so_truy_van=1, so_hop=2,
                    bao=lambda s: None)
    assert kq.ung_vien and kq.tin_duoc and kq.bi_captcha
    assert luong.ghi_links(kq, ra) == [] and not list(ra.glob("links*.txt"))


def test_dung_vi_thi_khong_chay_hop_sau(gia, tmp_path):
    from tiktok_music_downloader.tim_trend.nguon_tim import HetLuot
    _, video = gia
    nguon = _NguonLan(HetLuot("het"), loi_tu=2)
    luong.chay(video, tmp_path / "ra", tao_nguon=lambda: nguon, so_truy_van=3, so_hop=3, bao=lambda s: None)
    assert nguon.thu == 2   # 1 lượt được + 1 lượt hết; không thử thêm ở hop sau


def test_loi_mo_trang_giu_ket_qua_hop_truoc_va_khong_xuat_link(gia, tmp_path):
    from tiktok_music_downloader.tim_trend.nguon_tim import LoiMoTrang
    _, video = gia
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _NguonLan(LoiMoTrang("timeout")), so_truy_van=1, so_hop=2,
                    bao=lambda s: None)
    assert kq.loi_trang and len(kq.ung_vien) == 4
    assert luong.ghi_links(kq, ra) == []


def test_chay_lai_xoa_links_va_khung_cu(gia, tmp_path):
    """Review 23/10 H1: lần 1 ra link, lần 2 captcha ⇒ links*.txt cũ không được nằm lại."""
    from tiktok_music_downloader.tim_trend.nguon_tim import BiCaptcha
    _, video = gia
    ra = tmp_path / "ra"
    kq1 = luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    kq1.ung_vien += [dict(kq1.ung_vien[0], url=f"https://www.tiktok.com/@a/video/{7 * 10**18 + i}") for i in range(60)]
    assert len(luong.ghi_links(kq1, ra)) == 3
    (ra / "khung" / "cu-tu-lan-truoc.jpg").write_bytes(b"x")

    class _Cap(_NguonGia):
        def tim(self, tv):
            raise BiCaptcha("captcha")

    kq2 = luong.chay(video, ra, tao_nguon=lambda: _Cap(), so_hop=1, bao=lambda s: None)
    assert not list(ra.glob("links*.txt")) and not (ra / "khung" / "cu-tu-lan-truoc.jpg").exists()
    assert luong.ghi_links(kq2, ra) == []
