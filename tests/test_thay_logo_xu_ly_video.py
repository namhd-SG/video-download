"""Xử lý trọn một video: nhật ký đủ trường, ảnh soi + track lưu, `cho_nguoi` không ghi file ra, lỗi được ghi rồi ném lại."""
import pytest

cv2 = pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import nhat_ky, xu_ly_video  # noqa: E402
from tiktok_music_downloader.watermark import find_ffmpeg  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="không tìm thấy ffmpeg")


@pytest.fixture(scope="module")
def clip_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("xl")
    clip = tao_clip(n=40)
    p = d / "goc.mp4"
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (360, 640))
    for i in range(40):
        out.write(cv2.cvtColor(clip.nguon.doc(i), cv2.COLOR_GRAY2BGR))
    out.release()
    return clip, p


def test_render_ghi_file_ra_va_nhat_ky_day_du(clip_file, tmp_path):
    clip, p = clip_file
    conn = nhat_ky.mo(tmp_path / "log.db")
    kq = xu_ly_video.xu_ly(str(p), clip.box_moi(khung=(5, 12, 20, 28, 35)), str(tmp_path / "ra.mp4"), conn, tmp_path / "f",
                           nguon_video="drive:x", ffmpeg=FFMPEG, job_id=3, token_agy=19000, man_ket_agy=False)
    assert kq["trang_thai"] == "render" and kq["dau_ra"] and (tmp_path / "ra.mp4").exists()
    v = dict(conn.execute("SELECT * FROM tl_video WHERE id=?", (kq["video_log_id"],)).fetchone())
    assert (v["trang_thai"], v["job_id"], v["token_agy"], v["man_ket_agy"], v["kho"], v["so_khung"]) == \
        ("render", 3, 19000, 0, "360x640", 40)
    assert v["giay_xu_ly"] is not None and v["rss_dinh_mb"] > 0 and len(v["sha256_goc"]) == 64
    assert cv2.imread(v["duong_dan_sheet"]) is not None
    assert conn.execute("SELECT count(*) FROM tl_box_moi WHERE video_id=?", (kq["video_log_id"],)).fetchone()[0] == 5
    assert conn.execute("SELECT so_render FROM tl_vet WHERE video_id=?", (kq["video_log_id"],)).fetchone()[0] > 0


def test_cho_nguoi_khong_ghi_file_ra(clip_file, tmp_path):
    clip, p = clip_file
    conn = nhat_ky.mo(tmp_path / "log.db")
    kq = xu_ly_video.xu_ly(str(p), clip.box_moi(khung=(5,)), str(tmp_path / "ra.mp4"), conn, tmp_path / "f",
                           nguon_video="drive:y", ffmpeg=FFMPEG)
    assert kq == {"video_log_id": kq["video_log_id"], "trang_thai": "cho_nguoi", "dau_ra": None}
    assert not (tmp_path / "ra.mp4").exists()


def test_loi_duoc_ghi_vao_nhat_ky_roi_nem_lai(clip_file, tmp_path, monkeypatch):
    clip, p = clip_file
    conn = nhat_ky.mo(tmp_path / "log.db")

    def hong(*a, **k):
        raise RuntimeError("ffmpeg rc=1: disk full")
    monkeypatch.setattr(xu_ly_video.render, "render_video", hong)
    with pytest.raises(RuntimeError):
        xu_ly_video.xu_ly(str(p), clip.box_moi(khung=(5, 12, 20, 28, 35)), str(tmp_path / "ra.mp4"), conn, tmp_path / "f",
                          nguon_video="drive:z", ffmpeg=FFMPEG)
    r = conn.execute("SELECT trang_thai, loi_text FROM tl_video").fetchone()
    assert r["trang_thai"] == "loi" and "disk full" in r["loi_text"]
