"""Khung dựng chung cho test link lẻ: DB file thật, `process_job` thật, chỉ ranh giới yt-dlp/ffmpeg/Drive là giả.

Giả ĐÚNG những thứ sau (mọi thứ còn lại chạy thật: nhận dạng, liệt kê, cổng IP, `download_all`, ghi DB):
  · `YoutubeDL` (cả `nguon` lẫn `downloader`) ⇒ `YtdlpGia`;
  · `find_ffmpeg`/`find_deno` (đường tệp trên máy chạy test không phải thứ test muốn đo);
  · `verify_video_stream` (không có ffmpeg thật probe tệp 1 byte) và hook đẩy Drive;
  · giấc nghỉ jitter (ghi lại số lần/giá trị, không ngủ);
  · đồng hồ của pacer (tiêm `pacer.bay_gio`).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import partial

from tiktok_music_downloader import downloader
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from web import models, pacer
from web import queue as queue_mod

UPLOAD_OK = UploadResult(outcome=UploadOutcome.SUCCESS, file_id="f1", drive_id="d1")
TAT_CA_NEN_TANG = "youtube,tiktok,instagram,facebook,x,pinterest,douyin,bilibili,snapchat"
DENO = "/opt/gia/deno"
FFMPEG = "/opt/gia/ffmpeg"


class Khung:
    def __init__(self, monkeypatch, tmp_path, gia, deno=DENO, ffmpeg=FFMPEG):
        self.gia = gia
        self.db = tmp_path / "jobs.db"
        models.init_db(self.db)
        self.downloads, self.cookies = tmp_path / "dl", tmp_path / "ck"
        self.nghi_giua_luot = 0          # số lần pacer nghỉ jitter giữa hai lời gọi liệt kê
        self.ngu: list[float] = []       # mọi `time.sleep` (JitterThrottle giữa video, backoff)
        self.gio = [datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)]   # 22:00 giờ VN
        monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, TAT_CA_NEN_TANG)
        monkeypatch.setattr(nguon_mod, "YoutubeDL", gia)
        monkeypatch.setattr(downloader, "YoutubeDL", gia)
        monkeypatch.setattr(downloader, "find_deno", lambda: deno)
        monkeypatch.setattr(downloader, "find_ffmpeg", lambda: ffmpeg)
        monkeypatch.setattr(queue_mod, "find_deno", lambda: deno)
        monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **k: True)
        monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
        monkeypatch.setattr(pacer, "bay_gio", lambda: self.gio[0])
        monkeypatch.setattr(pacer, "nghi_giua_luot", self._nghi)
        monkeypatch.setattr(time, "sleep", self.ngu.append)

    def _nghi(self):
        self.nghi_giua_luot += 1

    def tao_job(self, links, nen_tang="youtube", so_luong=20):
        return models.create_job(self.db, "\n".join(links), so_luong, "a@x.vn", nen_tang=nen_tang)

    def chay(self, job_id):
        """Nhận job như worker (pending → running) rồi chạy `process_job` thật. Trả hàng job sau khi chạy."""
        with models._connect(self.db) as c:
            c.execute("UPDATE jobs SET trang_thai='running' WHERE id=?", (job_id,))
        self.process_job(models.get_job(self.db, job_id))
        return models.get_job(self.db, job_id)

    @staticmethod
    def hook_drive(*, job_id, ref, path, db_path=None):
        """Hook đẩy Drive giả: báo thành công và ghi hàng thư viện như `on_video_verified` thật làm."""
        models.record_video(db_path, job_id, ref.video_id, ref.url, title=ref.title, author=ref.author,
                            duration=ref.duration)
        return UPLOAD_OK

    def process_job(self, job):
        return queue_mod.process_job(self.db, self.downloads, self.cookies, job, lifecycle_hook=self.hook_drive)

    def process_job_fn(self):
        """Hàm cho `JobWorker(process_job_fn=…)`: `process_job` thật với hook Drive giả."""
        return partial(queue_mod.process_job, lifecycle_hook=self.hook_drive)

    def so_luot(self, nen_tang=None):
        with models._connect(self.db) as c:
            if nen_tang is None:
                return c.execute("SELECT COUNT(*) FROM luot_tai").fetchone()[0]
            return c.execute("SELECT COUNT(*) FROM luot_tai WHERE nen_tang=?", (nen_tang,)).fetchone()[0]

    def nen_tang_tat(self):
        return pacer.nen_tang_dang_tat(self.db)
