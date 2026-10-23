"""Trích khung bằng ffmpeg thật trên video tổng hợp (testsrc) — không mạng."""
from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image

from tiktok_music_downloader.tim_trend.khung import RONG, thoi_luong, trich_khung

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="cần ffmpeg/ffprobe trên PATH")


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=540x960:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", str(p)], check=True)
    return p


def test_ba_khung_dung_co(video, tmp_path):
    assert 2.5 < thoi_luong(video) < 3.5
    khung = trich_khung(video, tmp_path / "k")
    assert [k.name for k in khung] == ["dau-vao-0.jpg", "dau-vao-1.jpg", "dau-vao-2.jpg"]
    assert all(Image.open(k).size[0] == RONG for k in khung)


def test_file_khong_phai_video(tmp_path):
    hong = tmp_path / "hong.mp4"
    hong.write_bytes(b"khong phai video")
    with pytest.raises(subprocess.CalledProcessError):
        trich_khung(hong, tmp_path / "k")
