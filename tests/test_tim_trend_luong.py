"""Trọn luồng với agy/Chrome/mạng giả, trường lấy từ dữ liệu agy thật GĐ1. Kiểm: chỉ hạng đạt vào links.txt, hop 2 sinh từ
caption kết quả đạt, ctrl trượt ⇒ không xuất link, hết lượt ⇒ dừng có ghi lý do, trang HTML render."""
from __future__ import annotations

import json
import os
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
def ffmpeg_gia(tmp_path, monkeypatch):
    """ffmpeg/ffprobe GIẢ trên PATH: `trich_khung` chạy mã thật (gồm file đánh dấu) mà không cần video thật.
    Fixture trước tự ghi file đánh dấu nên xoá dòng đó trong khung.py test vẫn xanh (review 23/10 M11)."""
    bin_gia = tmp_path / "bin-gia"
    bin_gia.mkdir()
    (bin_gia / "ffprobe").write_text('#!/bin/sh\necho \'{"format": {"duration": "3.0"}}\'\n')
    (bin_gia / "ffmpeg").write_text('#!/bin/sh\nfor a in "$@"; do dich="$a"; done\nprintf x > "$dich"\n')
    for f in bin_gia.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_gia}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture
def gia(monkeypatch, tmp_path, ffmpeg_gia):
    # ctrl_theo_luot: danh sách mục fixture cho ctrl, mỗi lượt agy CHẤM LÔ lấy 1 phần tử (hết thì dùng "ctrl").
    trang_thai = {"ctrl": "ctrl-1", "ctrl_thay": [], "ctrl_theo_luot": [], "goi": []}

    def boc(anh, thu_muc_ra, model=None, ten=""):
        ra = {}
        if ten.startswith("agy-truong-lo-"):
            trang_thai["goi"].append((ten, len(anh)))
            ctrl_lan = trang_thai["ctrl_theo_luot"].pop(0) if trang_thai["ctrl_theo_luot"] else trang_thai["ctrl"]
        for a in anh:
            if a.stem.startswith("dau-vao"):
                m = F["ctrl-0"]
            elif a.stem in UV:
                m = F[UV[a.stem][0]]
            else:   # ctrl: tên số ngẫu nhiên, không có trong UV
                trang_thai["ctrl_thay"].append(a.stem)
                m = F[ctrl_lan]
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
    assert (ra / "links-ket-qua.txt").read_text().split() == [
        "https://www.tiktok.com/@u1/video/7000000000000000001", "https://www.tiktok.com/@u5/video/7000000000000000005"]
    assert (ra / "links-huong-dan.txt").read_text().split() == ["https://www.tiktok.com/@u2/video/7000000000000000002"]
    assert [(l["lo"], l["lan"]) for l in kq.lo_ctrl] == [(0, 1), (1, 1)] and (kq.so_lo, kq.so_lo_bo) == (2, 0)
    html = render(kq, ra, video.name).read_text()
    assert "Đúng dạng · kết quả" in html and "Đúng dạng · hướng dẫn" in html and "7000000000000000005" in html
    assert "TRƯỢT" not in html


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
    assert [p.name for p in tep] == ["links.txt", "links-01.txt", "links-02.txt", "links-03.txt", "links-ket-qua.txt",
                                     "links-ket-qua-01.txt", "links-ket-qua-02.txt", "links-ket-qua-03.txt"]
    assert [len(p.read_text().split()) for p in tep] == [120, 50, 50, 20] * 2
    assert not (tmp_path / "links-huong-dan.txt").exists()   # nhóm rỗng thì không ghi


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
    assert len(luong.ghi_links(kq1, ra)) == 7   # links + 2 khối, links-ket-qua + 2 khối, links-huong-dan
    (ra / "khung" / "cu-tu-lan-truoc.jpg").write_bytes(b"x")

    class _Cap(_NguonGia):
        def tim(self, tv):
            raise BiCaptcha("captcha")

    kq2 = luong.chay(video, ra, tao_nguon=lambda: _Cap(), so_hop=1, bao=lambda s: None)
    assert not list(ra.glob("links*.txt")) and not (ra / "khung" / "cu-tu-lan-truoc.jpg").exists()
    assert luong.ghi_links(kq2, ra) == []


def test_khung_doi_chung_chon_khung_khop_chu_ky_khi_video_nhieu_canh():
    """Ca 3 23/10: khung giữa là cảnh hướng dẫn điện thoại, 2 khung kia là cảnh concert ⇒ ctrl phải là khung concert."""
    from tiktok_music_downloader.tim_trend import cham
    concert = {"so_ban_sao": 1, "chu_the": "nguoi thuong", "loai_nen": "san_dien", "hanh_dong": "khac"}
    dien_thoai = {"so_ban_sao": 1, "chu_the": "nguoi thuong", "loai_nen": "trong_nha", "hanh_dong": "khac",
                  "la_tutorial": True}
    khung = [Path(f"dau-vao-{i}.jpg") for i in range(3)]
    truong = {"dau-vao-0": tu_json(dict(concert, id="dau-vao-0")), "dau-vao-1": tu_json(dict(dien_thoai, id="dau-vao-1")),
              "dau-vao-2": tu_json(dict(concert, id="dau-vao-2"))}
    ck = cham.chu_ky(list(truong.values()))
    assert [k.name for k in luong.chon_khung_doi_chung(khung, truong, ck, cham.NGUONG_MAC_DINH)] == [
        "dau-vao-0.jpg", "dau-vao-2.jpg"]


def test_khong_khung_nao_khop_thi_dung():
    from tiktok_music_downloader.tim_trend.cham import ChuKy
    ck = ChuKy(7, ">=3", "nguoi", "tron", "tao_dang", False)
    khung = [Path("dau-vao-0.jpg")]
    truong = {"dau-vao-0": tu_json(dict(F["s3-4"], id="dau-vao-0"))}
    with pytest.raises(luong.ChuKyKhongOnDinh):
        luong.chon_khung_doi_chung(khung, truong, ck, frozenset({"3", "2A"}))


def test_ctrl_chon_tu_luot_rieng_nhung_cham_mu_trong_lo(gia, tmp_path):
    """Không vòng tròn: khung ctrl được CHỌN theo lượt bóc riêng của khung đầu vào (khớp chữ ký), nhưng agy chấm lại MÙ
    trong lô; lô trả hạng 0 cho ctrl ⇒ tin_duoc=False (ĐP 23/10: điểm chọn và điểm kiểm phải là hai lượt khác nhau)."""
    trang_thai, video = gia
    trang_thai["ctrl"] = "s3-4"   # trong lô, agy đọc ctrl thành con chó ⇒ hạng 0
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert kq.chu_ky.so_ban_sao == 7                         # khung đầu vào khớp chữ ký ⇒ chọn được ctrl
    assert [l["hang_ctrl"] for l in kq.lo_ctrl] == [["0"] * 3] * 2   # lượt chấm trong lô là lượt riêng (+ 1 lần chấm lại)
    assert kq.tin_duoc is False


def test_truy_van_tay_thay_han_key_tu_sinh(gia, tmp_path, monkeypatch):
    from tiktok_music_downloader.tim_trend import agy_boc as ab
    goi_y = []
    monkeypatch.setattr(ab, "goi_y_tu_khoa", lambda *a, **k: goi_y.append(1) or [])
    _, video = gia
    nguon = _NguonGia()
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: nguon, so_hop=1, bao=lambda s: None,
                    truy_van_tay=["kiss camera trend capcut", "efecto kiss cam coldplay"])
    assert nguon.goi == ["kiss camera trend capcut", "efecto kiss cam coldplay"]
    assert not goi_y and all(t["nhom"] == "tay" for t in kq.truy_van)


def test_don_chi_xoa_dung_tep_cua_cong_cu(tmp_path):
    """Review 23/10 H-a: không xoá links-cua-toi.txt, không sập khi có thư mục tên links-01.txt, không xoá khung/ của người dùng."""
    ra = tmp_path / "ra"
    (ra / "khung").mkdir(parents=True)
    (ra / "khung" / "anh-cua-toi.jpg").write_bytes(b"x")          # không có file đánh dấu ⇒ không phải của công cụ
    (ra / "links-01.txt").mkdir()                                 # thư mục trùng mẫu tên
    for ten in ("links.txt", "links-02.txt", "links-cua-toi.txt", "links-100.txt"):
        (ra / ten).write_text("x")
    luong.don_dau_ra_cu(ra)
    con = sorted(p.name for p in ra.iterdir())
    assert con == ["khung", "links-01.txt", "links-100.txt", "links-cua-toi.txt"]
    assert (ra / "khung" / "anh-cua-toi.jpg").exists()
    (ra / "khung" / khung.DANH_DAU).write_text("x")
    luong.don_dau_ra_cu(ra)
    assert not (ra / "khung").exists()


def test_khung_co_san_cua_nguoi_dung_khong_bi_danh_dau_va_khong_bi_xoa(gia, tmp_path):
    """Review 23/10 vòng 3 HIGH: `--ra` trỏ vào thư mục đã có `khung/` của người dùng ⇒ chạy 2 lần (trich_khung thật)
    vẫn còn ảnh của họ, và công cụ không đánh dấu thư mục đó là của mình."""
    _, video = gia
    ra = tmp_path / "ra"
    (ra / "khung").mkdir(parents=True)
    (ra / "khung" / "anh-cua-toi.jpg").write_bytes(b"x")
    for _ in range(2):
        luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert (ra / "khung" / "anh-cua-toi.jpg").exists()
    assert not (ra / "khung" / khung.DANH_DAU).exists()


def test_khung_moi_duoc_danh_dau(gia, tmp_path):
    """Chiều thuận của test trên: thư mục do công cụ tạo thì có đánh dấu (để lần sau dọn được)."""
    _, video = gia
    ra = tmp_path / "ra"
    luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert (ra / "khung" / khung.DANH_DAU).is_file()


def test_video_chi_co_canh_huong_dan_bao_rieng():
    """Review 23/10 M3: video 1 cảnh hướng dẫn ⇒ mọi khung ra 2A ⇒ báo là video hướng dẫn, không khuyên cắt cảnh."""
    from tiktok_music_downloader.tim_trend import cham
    huong_dan = {"so_ban_sao": 1, "chu_the": "nguoi thuong", "loai_nen": "trong_nha", "hanh_dong": "khac",
                 "la_tutorial": True}
    ds = [Path(f"dau-vao-{i}.jpg") for i in range(3)]
    truong = {k.stem: tu_json(dict(huong_dan, id=k.stem)) for k in ds}
    with pytest.raises(luong.VideoHuongDan):
        luong.chon_khung_doi_chung(ds, truong, cham.chu_ky(list(truong.values())), cham.NGUONG_MAC_DINH)


def test_ctrl_ten_so_va_lan_vao_lo(gia, tmp_path):
    """Review 23/10 LOW: ctrl mang tên `ctrl-N` thì agy biết ảnh nào là đối chứng ⇒ đặt tên cùng mẫu số với ảnh bìa."""
    trang_thai, video = gia
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    ten = [t for l in kq.lo_ctrl for t in l["ten_ctrl"]]
    assert sorted(ten) == sorted(trang_thai["ctrl_thay"]) and kq.tin_duoc and len(ten) == 3   # 3 khung khớp ⇒ 3 ctrl
    assert not [p for p in (tmp_path / "ra" / "bia").glob("*.jpg") if p.stem not in UV]   # ctrl tạm đã dọn
    assert all(t.isdigit() and len(t) == 19 and t not in UV for t in ten)


def test_truy_van_tay_bo_trung_va_bao_khi_cat(gia, tmp_path):
    _, video = gia
    nguon, bao = _NguonGia(), []
    luong.chay(video, tmp_path / "ra", tao_nguon=lambda: nguon, so_truy_van=2, so_hop=1, bao=bao.append,
               truy_van_tay=["a", "b", "a", "c"])
    assert nguon.goi == ["a", "b"]
    assert any("2/3" in b and "'c'" in b for b in bao)


def test_don_ket_qua_va_trang_cu_chi_khi_cua_cong_cu(tmp_path):
    """Review 23/10 M4: ket-qua.json/index.html của lần trước bị dọn; file trùng tên của người dùng thì giữ."""
    ra = tmp_path / "ra"
    ra.mkdir()
    luong.ghi_links(luong.KetQua(), ra)
    (ra / "ket-qua.json").write_text(json.dumps({"chu_ky": None, "lo_ctrl": [], "ung_vien": []}))
    render(luong.KetQua(), ra, "v.mp4")
    luong.don_dau_ra_cu(ra)
    assert not (ra / "ket-qua.json").exists() and not (ra / "index.html").exists()
    (ra / "ket-qua.json").write_text('{"cua": "toi"}')
    (ra / "index.html").write_text("<title>trang cua toi</title>")
    luong.don_dau_ra_cu(ra)
    assert (ra / "ket-qua.json").exists() and (ra / "index.html").exists()


def test_nguong_cli_ap_vao_cong_ctrl(gia, tmp_path):
    """agy R1b ĐK1a: ctrl ra 2A (s7-1) ⇒ lô đạt với ngưỡng mặc định {3,2A}, nhưng trượt khi người chạy chỉ giữ {3}."""
    trang_thai, video = gia
    trang_thai["ctrl"] = "s7-1"
    assert luong.chay(video, tmp_path / "a", tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None).tin_duoc
    kq = luong.chay(video, tmp_path / "b", tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None,
                    nguong=frozenset({"3"}))
    assert not kq.tin_duoc and kq.so_lo_bo == 1


def test_lo_truot_lan_1_cham_lai_dat_thi_dung_hang_lan_2(gia, tmp_path):
    """Ca B (agy đọc lệch nền cả lô) ở lần 1, lần 2 đọc đúng ⇒ lô đạt, hạng ứng viên lấy từ lần 2; tên file lần 2 riêng."""
    trang_thai, video = gia
    trang_thai["ctrl_theo_luot"] = ["s3-4", "ctrl-1"]
    kq = luong.chay(video, tmp_path / "ra", tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert [(l["lo"], l["lan"], l["tin"]) for l in kq.lo_ctrl] == [(0, 1, False), (0, 2, True)]
    assert [g[0] for g in trang_thai["goi"]] == ["agy-truong-lo-0", "agy-truong-lo-0-lan2"]
    assert kq.tin_duoc and (kq.so_lo, kq.so_lo_bo) == (1, 0)
    assert {u["video_id"]: u["hang"] for u in kq.ung_vien}["7000000000000000001"] == "3"


def test_bo_mot_trong_hai_lo_van_xuat_link_cua_lo_dat(gia, tmp_path, monkeypatch):
    """Quyết của ĐP 23/10 + agy ĐK4: 2 lô, lô 0 đạt, lô 1 trượt cả 2 lần ⇒ link chỉ từ lô 0, cả lượt vẫn tin (1/2 ≤ 50%).
    Cỡ lô trừ chỗ cho 3 ctrl (ĐK3a): LO_TOI_DA=5 ⇒ 2 ảnh bìa + 3 ctrl mỗi lượt."""
    trang_thai, video = gia
    monkeypatch.setattr(agy_boc, "LO_TOI_DA", 5)
    trang_thai["ctrl_theo_luot"] = ["ctrl-1", "s3-4", "s3-4"]
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert [g[1] for g in trang_thai["goi"]] == [5, 5, 5]
    assert [g[0] for g in trang_thai["goi"]] == ["agy-truong-lo-0", "agy-truong-lo-1", "agy-truong-lo-1-lan2"]
    assert (kq.so_lo, kq.so_lo_bo) == (2, 1) and kq.tin_duoc
    hang = {u["video_id"]: u["hang"] for u in kq.ung_vien}
    assert hang["7000000000000000001"] == "3" and hang["7000000000000000002"] == "2A"    # lô 0 chấm thật
    assert hang["7000000000000000003"] is None and hang["7000000000000000004"] is None   # lô 1 bị bỏ
    luong.ghi_links(kq, ra)
    assert (ra / "links.txt").read_text().split() == [
        "https://www.tiktok.com/@u1/video/7000000000000000001", "https://www.tiktok.com/@u2/video/7000000000000000002"]
    assert "Bỏ 1/2 lô" in render(kq, ra, video.name).read_text()


def test_lo_dat_nhung_khong_link_nao_khi_co_lo_bo_thi_khong_tin(gia, tmp_path, monkeypatch):
    """agy ĐK4: lô 1 đạt nhưng 0 link giữ, lô 0 bị bỏ ⇒ "0 kết quả" là giả ⇒ không tin (mã 7), không ghi links.txt."""
    trang_thai, video = gia
    monkeypatch.setattr(agy_boc, "LO_TOI_DA", 5)
    trang_thai["ctrl_theo_luot"] = ["s3-4", "s3-4", "ctrl-1"]
    ra = tmp_path / "ra"
    kq = luong.chay(video, ra, tao_nguon=lambda: _NguonGia(), so_hop=1, bao=lambda s: None)
    assert not kq.tin_duoc and luong.ghi_links(kq, ra) == [] and not (ra / "links.txt").exists()


def test_don_ca_tep_link_theo_nhom(tmp_path):
    """agy R1b ĐK5: lần trước ghi links-ket-qua*/links-huong-dan* ⇒ lần sau phải dọn, file của người dùng vẫn giữ."""
    ra = tmp_path / "ra"
    ra.mkdir()
    for ten in ("links-ket-qua.txt", "links-ket-qua-01.txt", "links-huong-dan.txt", "links-cua-toi.txt"):
        (ra / ten).write_text("x")
    luong.don_dau_ra_cu(ra)
    assert sorted(p.name for p in ra.iterdir()) == ["links-cua-toi.txt"]
