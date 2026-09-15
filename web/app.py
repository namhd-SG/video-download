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
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tiktok_music_downloader.utils import is_tiktok_collection
from web import models
from web.auth import require_user
from web.lifecycle import should_reject_new_job
from web.queue import JobWorker

log = logging.getLogger("videodl.web")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "jobs.db"
DOWNLOADS_DIR = DATA_DIR / "downloads"
COOKIES_DIR = DATA_DIR / "cookies"
STATIC_DIR = BASE_DIR / "static"

# Matches the CLI's own --max ceiling (cli.py: max=2000) — same core, same cap.
MAX_SO_LUONG = 2000
SSE_POLL_SECONDS = 1.0
_END_STATES = ("done", "failed", "interrupted")

worker = JobWorker(DB_PATH, DOWNLOADS_DIR, COOKIES_DIR)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="TikTok Music Downloader", lifespan=_lifespan)


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
