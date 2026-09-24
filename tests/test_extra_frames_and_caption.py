"""Lưu thêm lúc tải: khung 50 %/90 % + caption đầy đủ + nhạc.

Vì sao là "lúc tải": mp4 bị xoá ngay sau khi lên Drive (`on_video_verified`),
nên đây là lần DUY NHẤT có tệp để cắt khung, và là lần duy nhất có `info` của
yt-dlp mà không phải gọi mạng thêm. Mọi thứ bỏ lỡ ở đây là mất vĩnh viễn cho
lượt tải đó — nên các test dưới chạy đường THẬT (ffmpeg của repo, DB thật).
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.utils import VideoRef
from tiktok_music_downloader.watermark import find_ffmpeg
from web import lifecycle, models
from web.queue import DESCRIPTION_TOI_DA, _bo_sung_metadata


class _UploaderOk:
    """Drive giả luôn nhận — thứ được đo ở đây là việc xảy ra SAU upload."""

    def is_configured(self) -> bool:
        return True

    def upload_file(self, path, parent_folder_id=None):
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="f1",
                            drive_id="d1", web_view_link="https://drive/x")

    def ensure_folder(self, *a, **k):
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="folder",
                            drive_id="d1", web_view_link="https://drive/folder")


@pytest.fixture
def uploader_ok(monkeypatch):
    lifecycle.set_uploader(_UploaderOk())
    # Thư mục job trên Drive không phải thứ đang đo.
    monkeypatch.setattr(lifecycle, "_ensure_job_folder", lambda *a, **k: None)
    yield
    lifecycle.set_uploader(None)


def _video_that(tmp_path: Path, giay: int) -> Path:
    """mp4 thật bằng ffmpeg của repo. `testsrc` in đồng hồ chạy lên khung, nên
    hai mốc thời gian khác nhau cho ra hai ảnh khác nhau — đó là thứ test 50 %
    vs 90 % dựa vào."""
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("repo's bundled ffmpeg not available here")
    out = tmp_path / "7009.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc=duration={giay}:size=320x568:rate=10",
                    "-pix_fmt", "yuv420p", str(out)], capture_output=True, check=True)
    return out


def _ref(video_id: str = "7009", **kw) -> VideoRef:
    return VideoRef(video_id=video_id, url=f"https://www.tiktok.com/@a/video/{video_id}", **kw)


# ---- khung phụ --------------------------------------------------------------

def test_both_extra_frames_are_cut_before_the_mp4_is_deleted(tmp_path, uploader_ok):
    """ĐỘT BIẾN: bỏ lời gọi `_cut_extra_frames_quietly` trong `on_video_verified` ⇒ ĐỎ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = _video_that(tmp_path, 10)

    lifecycle.on_video_verified(job_id=1, ref=_ref(duration=10), path=video, db_path=db)

    assert not video.exists(), "mp4 vẫn phải bị xoá sau khi lên Drive"
    ff = find_ffmpeg()
    for pt in lifecycle.KHUNG_PHU_PHAN_TRAM:
        khung = lifecycle.khung_phu_path_for(db, "7009", pt)
        assert khung.is_file() and khung.stat().st_size > 0, f"thiếu khung {pt}%"
        probe = subprocess.run([ff, "-i", str(khung)], capture_output=True, text=True, timeout=30)
        assert "Video: webp" in probe.stderr, probe.stderr[:300]
        # Cùng cỡ với poster: rộng THUMB_WIDTH.
        assert f"{lifecycle.THUMB_WIDTH}x" in probe.stderr, probe.stderr[:300]
    # Poster giây 1 vẫn ở chỗ cũ, không bị khung phụ đè.
    assert lifecycle.thumb_path_for(db, "7009").is_file()


def test_the_two_frames_are_taken_at_different_times(tmp_path):
    """ĐỘT BIẾN: cắt cả hai ở cùng một mốc (vd bỏ `* pt / 100`) ⇒ ĐỎ.
    `testsrc` in đồng hồ lên khung, nên mốc khác ⇒ byte khác."""
    db = tmp_path / "jobs.db"
    video = _video_that(tmp_path, 10)

    assert lifecycle._cut_extra_frames_quietly(video, db, "7009", 10) == 2

    sha = {pt: hashlib.sha256(lifecycle.khung_phu_path_for(db, "7009", pt).read_bytes()).hexdigest()
           for pt in lifecycle.KHUNG_PHU_PHAN_TRAM}
    assert len(set(sha.values())) == len(sha), "hai khung trùng byte — cùng một mốc thời gian?"


def test_no_duration_means_zero_frames_and_says_so(tmp_path, caplog):
    db = tmp_path / "jobs.db"
    video = _video_that(tmp_path, 3)

    assert lifecycle._cut_extra_frames_quietly(video, db, "7009", None) == 0
    assert "không có thời lượng" in caplog.text
    assert not (lifecycle.thumbs_dir_for(db) / "khung").exists()


def test_a_seek_past_the_end_leaves_no_empty_file(tmp_path):
    """Thời lượng khai SAI (dài hơn video thật): ffmpeg tạo tệp ra trước rồi
    mới hỏng — tệp 0 byte là lời nói dối "có khung", phải bị dọn."""
    db = tmp_path / "jobs.db"
    video = _video_that(tmp_path, 1)

    n = lifecycle._cut_extra_frames_quietly(video, db, "7009", 100)

    assert n == 0
    for pt in lifecycle.KHUNG_PHU_PHAN_TRAM:
        assert not lifecycle.khung_phu_path_for(db, "7009", pt).exists()


def test_the_mp4_is_deleted_even_when_the_extra_frames_step_explodes(tmp_path, uploader_ok,
                                                                     monkeypatch):
    """ĐỘT BIẾN: bỏ `try/except` bọc ngoài `_cut_extra_frames_quietly` ⇒ ĐỎ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7009.mp4"
    video.write_bytes(b"fake video bytes")
    monkeypatch.setattr(lifecycle, "khung_phu_path_for",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    lifecycle.on_video_verified(job_id=1, ref=_ref(duration=10), path=video, db_path=db)

    assert not video.exists()


# ---- caption + nhạc ---------------------------------------------------------

def test_full_caption_and_music_reach_the_videos_row(tmp_path, uploader_ok):
    """Đường thật: info yt-dlp → `_bo_sung_metadata` → `on_video_verified` → DB.
    ĐỘT BIẾN: bỏ ba khoá trong `_record_video_quietly` ⇒ ĐỎ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7009.mp4"
    video.write_bytes(b"fake video bytes")
    ref = _bo_sung_metadata(
        _ref(title="cắt ở 70 ký tự..."),
        {"description": "  caption đầy đủ #storm #ai  ", "track": "STORM", "artist": "Yung Lean"})

    lifecycle.on_video_verified(job_id=1, ref=ref, path=video, db_path=db)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT title, description, track, artist FROM videos "
                       "WHERE video_id='7009'").fetchone()
    conn.close()
    assert row == ("cắt ở 70 ký tự...", "caption đầy đủ #storm #ai", "STORM", "Yung Lean")


def test_caption_is_capped_and_empty_values_stay_null():
    dai = "x" * (DESCRIPTION_TOI_DA + 50)
    ra = _bo_sung_metadata(_ref(), {"description": dai, "track": "   ", "artist": 42})
    assert len(ra.description) == DESCRIPTION_TOI_DA
    assert ra.track is None and ra.artist is None


def test_an_existing_db_gets_the_new_columns(tmp_path):
    """DB mini tạo từ trước bản này: `init_db` phải thêm cột, không làm mất hàng."""
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, job_id INTEGER NOT NULL, "
                 "url TEXT NOT NULL, title TEXT, author TEXT, region TEXT, duration INTEGER, "
                 "play_count INTEGER, tao_luc TEXT NOT NULL)")
    conn.execute("INSERT INTO videos VALUES ('1', 1, 'u', 't', 'a', 'VN', 5, 9, 'x')")
    conn.commit()
    conn.close()

    models.init_db(db)
    models.init_db(db)  # lần hai: cột đã có ⇒ không được nổ

    conn = sqlite3.connect(db)
    cot = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    n = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()
    assert {"description", "track", "artist"} <= cot
    assert n == 1
