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
