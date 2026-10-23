"""Mã thoát của lệnh CLI theo kết quả chạy (0 / 2 / 3 / 4 / 5) — `chay` được thay bằng giả, không Chrome/agy."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tiktok_music_downloader.tim_trend import __main__ as cli
from tiktok_music_downloader.tim_trend.luong import KetQua

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
