"""Render không được phá nội dung NGOÀI vùng thay (nghiệm thu plan p1 §6: "phá nội dung ngoài box = 0 khung").

So bản render với bản mã hoá lại KHÔNG thay gì, cùng tham số, crf 0: mọi khung không thay phải trùng từng điểm ảnh; khung có thay
chỉ được khác trong box + đệm tô lấp/tấm nền (+1px do lấy mẫu màu 2×2 của yuv420p).
"""
import pytest

cv2 = pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

import numpy as np  # noqa: E402
from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import render  # noqa: E402
from tiktok_music_downloader.watermark import find_ffmpeg  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="không tìm thấy ffmpeg")


def _ghi_video(khung, duong_dan):
    out = cv2.VideoWriter(str(duong_dan), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (khung[0].shape[1], khung[0].shape[0]))
    for g in khung:
        out.write(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    out.release()


def _doc(duong_dan):
    cap = cv2.VideoCapture(str(duong_dan))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            return out
        out.append(f)


@pytest.fixture(scope="module")
def ca_render(tmp_path_factory):
    d = tmp_path_factory.mktemp("render")
    clip = tao_clip(n=30)
    goc = d / "goc.mp4"
    _ghi_video([clip.nguon.doc(i) for i in range(30)], goc)
    thay = {i: [{"frame": i, "x": x, "y": y, "w": w, "h": h}] for i, (x, y, w, h) in enumerate(clip.hop_that) if i % 2 == 0}
    dem = render.render_video(str(goc), thay, str(d / "ra.mp4"), FFMPEG, crf=0)
    render.render_video(str(goc), {}, str(d / "doi_chung.mp4"), FFMPEG, crf=0)
    return clip, thay, dem, _doc(d / "ra.mp4"), _doc(d / "doi_chung.mp4"), goc


def test_dem_khung_dung(ca_render):
    clip, thay, dem, ra, dc, _ = ca_render
    assert dem["so_khung"] == 30 == len(ra) == len(dc)
    assert dem["khung_thay"] == len(thay) == 15


def test_khung_khong_thay_trung_tung_diem_anh(ca_render):
    _, thay, _, ra, dc, _ = ca_render
    for i in range(30):
        if i not in thay:
            assert np.array_equal(ra[i], dc[i]), f"khung {i} không thay mà bị đổi"


def test_khung_thay_chi_doi_trong_box_va_dem(ca_render):
    _, thay, _, ra, dc, _ = ca_render
    bien = max(render.PAD_TO, render.PAD_TAM_NEN) + 1
    for i, es in thay.items():
        e = es[0]
        ngoai = np.ones(ra[i].shape[:2], bool)
        ngoai[max(0, e["y"] - bien):e["y"] + e["h"] + bien, max(0, e["x"] - bien):e["x"] + e["w"] + bien] = False
        assert np.array_equal(ra[i][ngoai], dc[i][ngoai]), f"khung {i}: đổi điểm ảnh NGOÀI vùng thay"
        assert not np.array_equal(ra[i][~ngoai], dc[i][~ngoai]), f"khung {i}: vùng thay không đổi gì"


def test_file_goc_khong_bi_dung(ca_render, tmp_path):
    *_, goc = ca_render
    truoc = goc.read_bytes()
    render.render_video(str(goc), {}, str(tmp_path / "x.mp4"), FFMPEG, crf=0)
    assert goc.read_bytes() == truoc


def test_ffmpeg_loi_thi_bao_loi_khong_im_lang(ca_render, tmp_path):
    *_, goc = ca_render
    with pytest.raises(RuntimeError):
        render.render_video(str(goc), {}, str(tmp_path / "khong-co-thu-muc" / "x.mp4"), FFMPEG)
