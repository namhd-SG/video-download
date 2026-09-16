"""FastAPI front for the TikTok downloader — the thin web layer Tkinter
cannot provide. Bind 127.0.0.1 only: this box only reaches the outside world
through cloudflared, never a raw 0.0.0.0 listener (phase-02 constraint 4).

Run: `uvicorn web.app:app --host 127.0.0.1 --port 7870` from the repo root
(7870 is free — 7860 is Promax, 11434 ollama, 61208 glances, all measured).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tiktok_music_downloader import downloader
from tiktok_music_downloader.utils import is_tiktok_collection
from web import models
from web.auth import require_user
from web.lifecycle import (daily_cap_rejection, should_reject_new_job,
                           thumb_path_for, thumbs_dir_for)
from web.queue import JobWorker

log = logging.getLogger("videodl.web")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "jobs.db"
DOWNLOADS_DIR = DATA_DIR / "downloads"
COOKIES_DIR = DATA_DIR / "cookies"
# Chỗ jar Netscape tạm được sinh ra, thay vì thư mục tạm hệ thống: để
# quét dọn được mà không đụng tệp của tiến trình khác dùng cùng tiền tố
# (công cụ dòng lệnh chạy trên cùng máy).
COOKIE_TMP_DIR = DATA_DIR / "tmp"
STATIC_DIR = BASE_DIR / "static"
# Derived the same way `web/lifecycle.py` derives it from the DB path, so the
# writer and the reader can never disagree about where thumbnails live.
THUMBS_DIR = thumbs_dir_for(DB_PATH)

# One page of the library grid. The grid renders every row it is given, so the
# ceiling is the render cost, not the query.
VIDEOS_PAGE_SIZE = 200
MAX_VIDEOS_PAGE_SIZE = 1000

# Matches the CLI's own --max ceiling (cli.py: max=2000) — same core, same cap.
MAX_SO_LUONG = 2000
SSE_POLL_SECONDS = 1.0
_END_STATES = ("done", "failed", "interrupted")

worker = JobWorker(DB_PATH, DOWNLOADS_DIR, COOKIES_DIR)


def _make_private_dir(path: Path) -> None:
    """Create `path` readable by this user only, and fix the mode if it is
    already there with looser bits.

    `mkdir(mode=0o700)` alone is not enough for either half: the mode argument
    is masked by umask (022 here → 0755), and it is ignored outright when the
    directory already exists. Measured on the mini 15/09: `web/data/cookies`
    stood at **755** and `jobs.db` at **644** on a box that has a second user
    account — the cookie jar this phase exists to protect was world-readable
    before any cookie had been dropped into it.
    """
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def prepare_data_dir(data_dir: Path, downloads_dir: Path, cookies_dir: Path,
                      db_path: Path) -> None:
    """Make the whole runtime-data tree private before the worker touches it."""
    _make_private_dir(data_dir)
    _make_private_dir(downloads_dir)
    _make_private_dir(cookies_dir)
    _make_private_dir(thumbs_dir_for(db_path))
    # jobs.db carries every job's URL and the email of whoever created it.
    # sqlite creates it on first connect, so tighten it here rather than at
    # creation; a path that does not exist yet is not worth crashing boot over.
    if db_path.exists():
        os.chmod(db_path, 0o600)
    _make_private_dir(COOKIE_TMP_DIR)
    downloader.COOKIE_TMP_DIR = str(COOKIE_TMP_DIR)
    quet_jar_tam(COOKIE_TMP_DIR)


def quet_jar_tam(tmp_dir: Path) -> int:
    """Xoá mọi jar cookie tạm còn sót, trả về số tệp đã xoá.

    Chạy lúc khởi động, TRƯỚC khi worker chạy, nên mọi thứ ở đây đều là rác của
    lượt trước. Cần thiết vì `download_all` chỉ xoá jar trong `finally`, mà
    SIGKILL không chạy `finally` — và launchd `KeepAlive=true` dựng lại ngay
    sau khi bị giết, nên nếu không quét thì mỗi lần bị giết lại để lại một tệp
    chứa cookie dạng văn bản thuần nằm mãi trên đĩa.
    """
    da_xoa = 0
    for f in tmp_dir.glob(f"{downloader.COOKIE_TMP_PREFIX}*"):
        try:
            f.unlink()
            da_xoa += 1
        except OSError:
            log.warning("không xoá được jar tạm còn sót: %s", f.name)
    if da_xoa:
        log.info("đã quét %d jar cookie tạm còn sót từ lượt chạy trước", da_xoa)
    return da_xoa


@asynccontextmanager
async def _lifespan(app: FastAPI):
    prepare_data_dir(DATA_DIR, DOWNLOADS_DIR, COOKIES_DIR, DB_PATH)
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="TikTok Music Downloader", lifespan=_lifespan)

# The page shell and the two files it points at must be re-checked on every
# load. `no-cache` is not "do not store" — it is "revalidate before reuse", so
# the ETag Starlette already sends turns the usual hit into a cheap 304.
#
# Without this, splitting the styles and script out of index.html left a
# regression that only shows on the SECOND change to either file: Cloudflare
# caches .js and .css by default (120-minute edge TTL) when the origin sends
# no Cache-Control, while .html is not cached by default. A fresh index.html
# would then pair with a two-hour-old app.js — and that mismatch is silent,
# since a stale script simply stops finding the ids it expects.
REVALIDATE_PATHS = frozenset({"/", "/index.html", "/app.js", "/app.css"})


@app.middleware("http")
async def add_revalidate_header(request, call_next):
    response = await call_next(request)
    if request.url.path in REVALIDATE_PATHS:
        response.headers["Cache-Control"] = "no-cache"
    return response


class CreateJobRequest(BaseModel):
    """`nguoi_tao` (job creator) is deliberately NOT a client-supplied field:
    it comes from the verified Cloudflare Access JWT (`web/auth.py`), never
    from the body. Accepting this value from the client was an
    unauthenticated path-traversal vector into the cookie jar (see
    `cookies_path_for_user` in web/queue.py)."""

    url: str
    so_luong: int = Field(gt=0, le=MAX_SO_LUONG, description="Số video tối đa muốn tải")


@app.get("/healthz")
def healthz() -> dict:
    """The one unauthenticated route. `launchctl`/KeepAlive and the local
    probe in the handover checklist reach it over loopback with no Access
    JWT, and it discloses nothing but liveness."""
    return {"status": "ok"}


@app.post("/jobs")
def create_job(payload: CreateJobRequest,
               nguoi_tao: str = Depends(require_user)) -> dict:
    # Gate CHẠY TRƯỚC validate URL: `should_reject_new_job` là cổng chặn job
    # mới khi Drive đang backpressure hoặc đĩa sắp đầy — phải chặn trước khi
    # tốn bất cứ việc gì khác cho job này.
    rejection = should_reject_new_job(downloads_dir=DOWNLOADS_DIR)
    if rejection is not None:
        raise HTTPException(status_code=503, detail=rejection)
    # Trần ngày theo cookie. Cũng chạy TRƯỚC khi ghi hàng job, cùng lý do như
    # gate trên: một lượt bị chặn không được để lại hàng 'pending' ma.
    over_cap = daily_cap_rejection(db_path=DB_PATH, cookies_dir=COOKIES_DIR,
                                   nguoi_tao=nguoi_tao, so_luong=payload.so_luong)
    if over_cap is not None:
        raise HTTPException(status_code=429, detail=over_cap)
    if not is_tiktok_collection(payload.url):
        raise HTTPException(
            status_code=400,
            detail="url phải là trang TikTok music/tag/search/profile",
        )
    job_id = models.create_job(DB_PATH, payload.url, payload.so_luong, nguoi_tao)
    job = models.get_job(DB_PATH, job_id)
    assert job is not None  # vừa tạo xong, không thể vắng
    return job


@app.get("/jobs")
def list_jobs(nguoi_tao: str = Depends(require_user)) -> list[dict]:
    return models.list_jobs(DB_PATH)


@app.get("/videos")
def list_videos(limit: int = VIDEOS_PAGE_SIZE, offset: int = 0,
                nguoi_tao: str = Depends(require_user)) -> dict:
    """The library grid's rows. Every member sees the whole team's catalogue
    (user's call 15/09) — one shared library is the point, so that two people
    do not download the same hashtag twice without knowing."""
    if limit < 1 or limit > MAX_VIDEOS_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"limit phải trong khoảng 1..{MAX_VIDEOS_PAGE_SIZE}")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset không được âm")
    videos = models.list_videos(DB_PATH, limit=limit, offset=offset)
    # Một truy vấn `sources_for_videos` cho CẢ TRANG, không phải một truy vấn
    # mỗi video: bộ lọc "Nguồn" của UI cần biết mọi hashtag/music/profile mà
    # mỗi video từng xuất hiện, và trang có tới `limit` video thì N+1 ở đây
    # là N+1 thật, không phải lý thuyết.
    sources = models.sources_for_videos(DB_PATH, [v["video_id"] for v in videos])
    for video in videos:
        video["nguon"] = sources.get(video["video_id"], [])
    return {
        "tong": models.count_videos(DB_PATH),
        "videos": videos,
    }


@app.get("/thumbs/{video_id}")
def get_thumb(video_id: str, nguoi_tao: str = Depends(require_user)) -> FileResponse:
    """One grid thumbnail.

    `video_id` reaches the filesystem, so it is checked by SHAPE before it is
    used: TikTok ids are digits, and a digits-only string cannot contain "/",
    ".." or a NUL. That is a structural guarantee rather than a blocklist —
    the same reasoning as the sha256 filename in `cookies_path_for_user`.
    """
    if not video_id.isdigit():
        raise HTTPException(status_code=404, detail="video_id không hợp lệ")
    path = thumb_path_for(DB_PATH, video_id)
    if not path.is_file():
        # Absent is ordinary, not broken: ffmpeg may have failed on this one,
        # or the video predates thumbnail capture. The grid shows its own
        # placeholder rather than a broken image.
        raise HTTPException(status_code=404, detail="chưa có ảnh cho video này")
    return FileResponse(path, media_type="image/webp")


@app.get("/jobs/{job_id}")
def get_job(job_id: int, nguoi_tao: str = Depends(require_user)) -> dict:
    job = models.get_job(DB_PATH, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job không tồn tại")
    return job


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: int,
                     nguoi_tao: str = Depends(require_user)) -> EventSourceResponse:
    """SSE progress stream. The UI must ALSO poll GET /jobs/{id} as a
    fallback (phase-02 risk note): a tunnel drop can kill this stream while
    the job keeps running server-side, and polling is the way back."""
    if models.get_job(DB_PATH, job_id) is None:
        raise HTTPException(status_code=404, detail="job không tồn tại")

    async def _generator():
        last_payload: str | None = None
        while True:
            job = models.get_job(DB_PATH, job_id)
            if job is None:
                break
            payload = json.dumps(job)
            if payload != last_payload:
                yield {"event": "progress", "data": payload}
                last_payload = payload
            if job["trang_thai"] in _END_STATES:
                break
            await asyncio.sleep(SSE_POLL_SECONDS)

    return EventSourceResponse(_generator())


# Mounted last so it only catches paths none of the routes above matched —
# the single index.html plus its own assets, no build step. Deliberately not
# behind `require_user`: it is a static shell holding no job data, and every
# call it makes back into /jobs* is authenticated on its own. Access still
# gates it for anyone arriving through the tunnel.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
