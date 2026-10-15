"""Điểm vào prod (`chay_mot_video`, worker spawn) KHÔNG với tới AI vòng hai / lộ trình — kể cả khi box mồi mang `nguon="agy"` + `cum`.

AI vòng hai (`gan_moc_ai`) và lộ trình (`theo_lo_trinh`) chỉ chạy khi `duong_ong.xu_ly_video(..., neo_ai=[...])` nhận mốc khác rỗng;
điểm vào prod không có tham số nào để truyền chúng. Test thứ hai chứng minh bản vá giả có răng: gọi thẳng với `neo_ai` thì nổ.
"""
import json

import pytest

cv2 = pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import chay_mot_video, duong_ong  # noqa: E402
from tiktok_music_downloader.thay_logo.box_moi import BoxMoi  # noqa: E402
from tiktok_music_downloader.watermark import find_ffmpeg  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="không tìm thấy ffmpeg")


class _ChamAI(Exception):
    pass


def _cam(*_a, **_k):
    raise _ChamAI("đường AI vòng hai bị gọi")


@pytest.fixture
def cam_ai(monkeypatch):
    monkeypatch.setattr(duong_ong, "gan_moc_ai", _cam)
    monkeypatch.setattr(duong_ong, "theo_lo_trinh", _cam)


@pytest.fixture(scope="module")
def clip_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("khong_ai")
    clip = tao_clip(n=40)
    p = d / "goc.mp4"
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (360, 640))
    for i in range(40):
        out.write(cv2.cvtColor(clip.nguon.doc(i), cv2.COLOR_GRAY2BGR))
    out.release()
    return clip, p


def test_diem_vao_prod_render_ma_khong_goi_ai(cam_ai, clip_file, tmp_path, capsys):
    clip, p = clip_file
    boxes = tmp_path / "boxes.json"
    boxes.write_text(json.dumps([b.__dict__ for b in clip.box_moi(khung=(5, 12, 20, 28, 35), nguon="agy", cum=1)]))
    rc = chay_mot_video.main(["--video", str(p), "--boxes", str(boxes), "--out", str(tmp_path / "ra.mp4"),
                              "--db", str(tmp_path / "log.db"), "--files", str(tmp_path / "f"), "--nguon-video", "drive:x",
                              "--ffmpeg", FFMPEG, "--job-id", "7", "--man-ket", "0"])
    kq = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and kq["trang_thai"] == "render", kq


def test_ban_va_gia_co_rang_khi_truyen_neo_ai(cam_ai, clip_file):
    clip, _ = clip_file
    boxes = clip.box_moi(khung=(5, 12, 20, 28, 35), cum=1)
    with pytest.raises(_ChamAI):
        duong_ong.xu_ly_video(clip.nguon, boxes, neo_ai=[BoxMoi(20, *clip.hop_that[20], nguon="agy", cum=1)])
