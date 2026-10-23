"""Mã thoát của lệnh CLI theo kết quả chạy (0 / 3 / 4 / 5 / 6 / 7) — `chay` được thay bằng giả, không Chrome/agy."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tiktok_music_downloader.tim_trend import __main__ as cli
from tiktok_music_downloader.tim_trend.luong import ChuKyKhongOnDinh, KetQua, VideoHuongDan

UV = {"url": "https://www.tiktok.com/@a/video/7000000000000000001", "video_id": "7000000000000000001", "hang": "3",
      "tac_gia": "a", "caption": "", "truong": None, "co": [], "cover_url": "", "truy_van": "q"}


@pytest.mark.parametrize("kq, ma", [
    (KetQua(ung_vien=[UV]), 0),
    (KetQua(ung_vien=[UV], tin_duoc=False), 7),
    (KetQua(), 3),
    (KetQua(ung_vien=[UV], bi_captcha=True, dung_vi="captcha"), 4),
    (KetQua(ung_vien=[UV], loi_trang=True, dung_vi="timeout"), 5),
])
def test_ma_thoat(tmp_path, monkeypatch, kq, ma):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cli, "chay", lambda *a, **k: kq)
    ra = tmp_path / "ra"
    ra.mkdir()
    kq_cli = CliRunner().invoke(cli.app, [str(video), "--ra", str(ra)])
    assert kq_cli.exit_code == ma, kq_cli.output
    assert (ra / "ket-qua.json").exists() and (ra / "index.html").exists()
    assert (ra / "links.txt").exists() == (ma == 0)


def test_help_ghi_ranh_gioi_du_lieu():
    out = CliRunner().invoke(cli.app, ["--help"]).output
    assert "RANH GIỚI DỮ LIỆU" in out and "creative nội bộ" in out


def test_truy_van_tay_qua_cli(tmp_path, monkeypatch):
    nhan = {}
    monkeypatch.setattr(cli, "chay", lambda *a, **k: nhan.update(k) or KetQua(ung_vien=[UV]))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    CliRunner().invoke(cli.app, [str(video), "--ra", str(tmp_path / "ra"), "--truy-van", " a | b ||c "])
    assert nhan["truy_van_tay"] == ["a", "b", "c"]


@pytest.mark.parametrize("loi, chu, khong_co", [
    (ChuKyKhongOnDinh("nhieu canh"), "cắt video", "HƯỚNG DẪN"),
    (VideoHuongDan("toan huong dan"), "HƯỚNG DẪN", "cắt video"),
])
def test_ma_thoat_6_va_khong_de_ket_qua_cu(tmp_path, monkeypatch, loi, chu, khong_co):
    """Review 23/10 M12 + M4: mã 6 thoát trước khi ghi gì ⇒ ket-qua.json/index.html/links của lần trước phải bị dọn."""
    from tiktok_music_downloader.tim_trend import luong

    def chay_gia(video, ra, **k):
        luong.don_dau_ra_cu(ra)
        raise loi

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    ra = tmp_path / "ra"
    ra.mkdir()
    monkeypatch.setattr(cli, "chay", lambda *a, **k: KetQua(ung_vien=[UV]))
    assert CliRunner().invoke(cli.app, [str(video), "--ra", str(ra)]).exit_code == 0
    assert (ra / "links.txt").exists()
    monkeypatch.setattr(cli, "chay", chay_gia)
    kq_cli = CliRunner().invoke(cli.app, [str(video), "--ra", str(ra)])
    assert kq_cli.exit_code == 6
    assert chu in kq_cli.output and khong_co not in kq_cli.output
    assert not any((ra / t).exists() for t in ("links.txt", "ket-qua.json", "index.html"))
