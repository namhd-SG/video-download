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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tiktok_music_downloader import downloader
from tiktok_music_downloader.utils import is_tiktok_collection
from web import models
from web.auth import is_admin, require_user
from web.cookies import (cookie_jar_path, cookies_path_for_user,
                         han_dung_nhat, ly_do_jar_khong_dung_duoc)
from tiktok_music_downloader.gdrive_upload import UploadOutcome
from web.lifecycle import (daily_cap_rejection, should_reject_new_job,
                           trash_drive_file,
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
# Id TikTok đo được là 19 chữ số. Trần này để một id dài bất thường bị chặn ở
# cổng thay vì làm hệ tệp ném ra ngoài.
MAX_VIDEO_ID_LEN = 32
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
                      db_path: Path, cookie_tmp_dir: Path) -> None:
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
    # BẮT BUỘC truyền, KHÔNG có mặc định. Hàm này XOÁ tệp trong thư mục được
    # đưa vào, nên một mặc định trỏ về thư mục production là cái bẫy: người gọi
    # quên tham số thì quét nhầm prod mà không hề biết. Bản vá đầu của tôi cho
    # nó mặc định `COOKIE_TMP_DIR` và ba test cũ gọi thiếu — `pytest` vẫn xoá
    # jar thật, đúng cái lỗi đang đi sửa. Thiếu tham số bây giờ là TypeError.
    _make_private_dir(cookie_tmp_dir)
    downloader.COOKIE_TMP_DIR = str(cookie_tmp_dir)
    quet_jar_tam(cookie_tmp_dir)


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
    prepare_data_dir(DATA_DIR, DOWNLOADS_DIR, COOKIES_DIR, DB_PATH, COOKIE_TMP_DIR)
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
    """Chỉ lượt của chính mình; admin thấy hết.

    User chốt 16/09 khi chuẩn bị mở cho cả team. Hàng job mang URL người khác
    tìm gì, email của họ, và `ly_do_dung` — trong đó có mã trạng thái cookie
    cá nhân (hết hạn / chưa đăng nhập). Lọc ở ĐÂY chứ không ở giao diện: ẩn
    trên màn hình mà API vẫn trả thì chưa sửa gì cả.
    """
    return models.list_jobs(DB_PATH, None if is_admin(nguoi_tao) else nguoi_tao)


# Jar thật trên mini đo 10 196 B. Trần rộng gấp ~25 lần là đủ cho mọi bản
# xuất Cookie-Editor mà vẫn chặn được việc ai đó đẩy một tệp lớn qua đường này.
MAX_COOKIE_BODY = 256 * 1024


class CookieBody(BaseModel):
    json_cookie: str = Field(alias="json", max_length=MAX_COOKIE_BODY,
                             description="Chuỗi JSON xuất từ Cookie-Editor")


def _trang_thai_cookie(nguoi_tao: str) -> dict:
    """What this person's jar looks like, said in codes and timestamps only.

    Not one byte of the jar leaves through here. `ly_do_jar_khong_dung_duoc`
    returns a code from a closed set, and the only other fields are an
    expiry and an mtime. That is a structural guarantee, not a promise to
    remember to redact: there is no code path that can put file contents in
    this dict.
    """
    duong_dan = cookies_path_for_user(COOKIES_DIR, nguoi_tao)
    if duong_dan is None:
        return {"co_jar": False, "trang_thai": None,
                "het_han": None, "cap_nhat_luc": None}
    ma = ly_do_jar_khong_dung_duoc(duong_dan)
    return {
        "co_jar": True,
        "trang_thai": ma or "dung_duoc",
        "het_han": han_dung_nhat(duong_dan),
        "cap_nhat_luc": datetime.fromtimestamp(
            Path(duong_dan).stat().st_mtime, tz=timezone.utc).isoformat(),
    }


@app.get("/me")
def me(nguoi_tao: str = Depends(require_user)) -> dict:
    """Who the browser is, as the server sees it.

    The page has no other way to know: identity arrives in a header that
    Cloudflare Access sets and JavaScript cannot read.
    """
    return {"email": nguoi_tao, "la_admin": is_admin(nguoi_tao)}


@app.get("/me/cookie")
def get_my_cookie(nguoi_tao: str = Depends(require_user)) -> dict:
    return _trang_thai_cookie(nguoi_tao)


@app.put("/me/cookie")
def put_my_cookie(body: CookieBody,
                  nguoi_tao: str = Depends(require_user)) -> dict:
    """Accept a jar only after proving it works, then swap it in atomically.

    Order matters and is the point of this function. The jar is written to a
    temp file first and checked there; a jar that fails the check never
    reaches the place jobs read from, so a bad paste cannot replace a working
    cookie with a broken one. The swap is `os.replace`, which is atomic, so a
    job resolving its jar at that instant sees the old file or the new one
    and never a half-written one.

    The temp file is named with `downloader.COOKIE_TMP_PREFIX` on purpose:
    `quet_jar_tam` sweeps that prefix at startup, so a crash between write and
    replace cannot leave readable cookies lying on a shared machine.

    Safe to use while your own job runs: `download_all` resolves the path and
    converts to a temp Netscape jar when it starts, so it is not reading this
    file mid-flight.
    """
    cookies_dir = COOKIES_DIR
    _make_private_dir(cookies_dir)
    dich = cookie_jar_path(cookies_dir, nguoi_tao)
    tmp_dir = Path(downloader.COOKIE_TMP_DIR)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tam = tmp_dir / f"{downloader.COOKIE_TMP_PREFIX}me-{dich.stem}.json"

    # 0600 from the first byte, not chmod-after-write: between the two there
    # is a window where another account on this shared machine could read it.
    fd = os.open(tam, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body.json_cookie)
        ma = ly_do_jar_khong_dung_duoc(str(tam))
        if ma is not None:
            # Chỉ MÃ ra ngoài. `detail` đi thẳng vào JSON trả về và vào log,
            # nên bất cứ thứ gì lấy từ nội dung tệp đặt vào đây là rò.
            log.info("me/cookie: từ chối, mã=%s", ma)
            raise HTTPException(status_code=400, detail=ma)
        os.replace(tam, dich)
    finally:
        # Trượt ở đâu cũng không để lại cookie đọc được trên đĩa. `os.replace`
        # thành công thì `tam` đã biến mất, nên `missing_ok`.
        tam.unlink(missing_ok=True)
    log.info("me/cookie: đã nhận jar mới")
    return _trang_thai_cookie(nguoi_tao)


@app.delete("/me/cookie", status_code=204, response_model=None)
def delete_my_cookie(nguoi_tao: str = Depends(require_user)) -> None:
    cookie_jar_path(COOKIES_DIR, nguoi_tao).unlink(missing_ok=True)


@app.get("/videos")
def list_videos(limit: int = VIDEOS_PAGE_SIZE, offset: int = 0,
                nguoi_tao: str = Depends(require_user)) -> dict:
    """The library grid's rows — only what this person downloaded.

    User's call 17/09, replacing the shared catalogue of 15/09: "whoever
    presses download owns it", and a member's grid should not be crowded with
    other people's work. The warehouse itself is still ONE shared Drive and
    the duplicate skip is still global, so nothing is downloaded twice; what
    changed is who the grid is addressed to.

    Filtered here rather than in the grid: hiding rows on screen while the
    API still hands them over is not filtering. `nguon` carries the words
    somebody typed into search, so it is filtered too.
    """
    if limit < 1 or limit > MAX_VIDEOS_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"limit phải trong khoảng 1..{MAX_VIDEOS_PAGE_SIZE}")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset không được âm")
    chi_cua = None if is_admin(nguoi_tao) else nguoi_tao
    videos = models.list_videos(DB_PATH, chi_cua, limit=limit, offset=offset)
    # Một truy vấn `sources_for_videos` cho CẢ TRANG, không phải một truy vấn
    # mỗi video: bộ lọc "Nguồn" của UI cần biết mọi hashtag/music/profile mà
    # mỗi video từng xuất hiện, và trang có tới `limit` video thì N+1 ở đây
    # là N+1 thật, không phải lý thuyết.
    sources = models.sources_for_videos(DB_PATH, [v["video_id"] for v in videos],
                                        chi_cua)
    for video in videos:
        video["nguon"] = sources.get(video["video_id"], [])
    return {
        "tong": models.count_videos(DB_PATH, chi_cua),
        "videos": videos,
    }


# Một lượt bỏ tối đa 50 video. Trần tồn tại vì mỗi id là một lượt gọi Drive
# đồng bộ: 500 id trong một request là một phút treo và một cửa sổ dài để chết
# giữa chừng, đúng lúc dữ liệu đang ở trạng thái nửa vời.
MAX_VIDEO_LOAI = 50


class LoaiVideoRequest(BaseModel):
    video_ids: list[str] = Field(min_length=1, max_length=MAX_VIDEO_LOAI)


@app.post("/videos/loai")
def loai_video(body: LoaiVideoRequest,
               nguoi_tao: str = Depends(require_user)) -> dict:
    """Bỏ video khỏi thư viện CỦA NGƯỜI BẤM, và đưa tệp vào Thùng rác Drive.

    Loại là việc riêng (user chốt 17/09): người khác quét trúng cùng video vẫn
    tải lại được, vì `known_video_ids` cố ý không xét cột loại. Thứ biến mất là
    hàng trong thư viện của người bấm, không phải chỗ đứng của video trong kho.

    Trả về ba con số thay vì một chữ "xong": bỏ được bao nhiêu, bao nhiêu id
    không phải của mình, bao nhiêu id trash trượt. Gộp ba thứ đó thành một
    trạng thái là cách một lỗi Drive đi qua mà không ai thấy.
    """
    chi_cua = None if is_admin(nguoi_tao) else nguoi_tao
    cua_toi = models.video_de_loai(DB_PATH, body.video_ids, chi_cua)
    da_loai, drive_truot = [], []

    for hang in cua_toi:
        file_id = hang.get("drive_file_id")
        if file_id:
            ket_qua = trash_drive_file(file_id)
            if not ket_qua.ok and ket_qua.outcome is not UploadOutcome.NOT_CONFIGURED:
                # Trash trượt ⇒ KHÔNG ghi mốc. Video ở lại thư viện, người dùng
                # thấy nó còn đó và bấm lại được — thà ồn còn hơn mất lặng lẽ.
                drive_truot.append(hang["video_id"])
                continue
        # Không có `drive_file_id` (video tiền-chỉ-mục) thì không có gì để bỏ
        # vào thùng rác; vẫn ghi mốc, vì thư viện là thứ người dùng muốn dọn.
        models.danh_dau_da_loai(DB_PATH, hang["video_id"], nguoi_tao)
        da_loai.append(hang["video_id"])

    return {
        "da_loai": da_loai,
        "khong_phai_cua_ban": sorted(set(body.video_ids) - {h["video_id"] for h in cua_toi}),
        "drive_truot": drive_truot,
    }


@app.get("/thumbs/{video_id}")
def get_thumb(video_id: str, nguoi_tao: str = Depends(require_user)) -> FileResponse:
    """One grid thumbnail, from your own library only.

    `video_id` reaches the filesystem, so it is checked by SHAPE before it is
    used: TikTok ids are digits, and a digits-only string cannot contain "/",
    ".." or a NUL. That is a structural guarantee rather than a blocklist —
    the same reasoning as the sha256 filename in `cookies_path_for_user`.
    """
    # Hình dạng chặn traversal; ĐỘ DÀI chặn hệ tệp. `.isdigit()` cho một id
    # 300 chữ số đi qua, rồi `is_file()` ném OSError "File name too long" —
    # lỗi KHÔNG CÓ BIÊN trên một endpoint đã qua xác thực, client nhận 500.
    # Id TikTok là 19 chữ số; 32 đã rất rộng.
    if not video_id.isdigit() or len(video_id) > MAX_VIDEO_ID_LEN:
        raise HTTPException(status_code=404, detail="video_id không hợp lệ")
    path = thumb_path_for(DB_PATH, video_id)
    if not path.is_file():
        # Absent is ordinary, not broken: ffmpeg may have failed on this one,
        # or the video predates thumbnail capture. The grid shows its own
        # placeholder rather than a broken image.
        #
        # Checked BEFORE the ownership query on purpose: no picture means 404
        # for everybody, so there is nothing to hide yet, and this way a
        # missing database still answers 404 instead of raising.
        raise HTTPException(status_code=404, detail="chưa có ảnh cho video này")
    # Cùng câu hỏi `/videos` trả lời, hỏi lại ở đây — cùng câu chữ 404, nên
    # "của người khác" và "không có" không phân biệt được từ ngoài. Bỏ bước
    # này thì cặp 200/404 thành máy trả lời "team đã tải video này chưa" cho
    # bất kỳ ai đăng nhập, và id thật thì CHÍNH tool này phát ra hàng loạt
    # (`hashtag_enumerator.py:165`) — "id khó đoán" không phải lớp bảo vệ.
    if not models.video_nay_cua_toi(DB_PATH, video_id,
                                    None if is_admin(nguoi_tao) else nguoi_tao):
        raise HTTPException(status_code=404, detail="chưa có ảnh cho video này")
    return FileResponse(path, media_type="image/webp")


def _job_cua_toi_hoac_404(job_id: int, nguoi_tao: str) -> dict:
    """The job, if this caller is allowed to see it. Otherwise 404.

    404 and not 403, deliberately: job ids are sequential, so a 403 would
    answer "this id exists and belongs to someone else" for anyone willing
    to count upwards. Both answers must be indistinguishable from outside.

    This mirrors the filter on the list route: a queue that hides other
    people's rows but serves them one id at a time has not hidden anything.
    """
    job = models.get_job(DB_PATH, job_id)
    if job is None or (not is_admin(nguoi_tao) and job["nguoi_tao"] != nguoi_tao):
        raise HTTPException(status_code=404, detail="job không tồn tại")
    return job


@app.get("/jobs/{job_id}")
def get_job(job_id: int, nguoi_tao: str = Depends(require_user)) -> dict:
    return _job_cua_toi_hoac_404(job_id, nguoi_tao)


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: int,
                     nguoi_tao: str = Depends(require_user)) -> EventSourceResponse:
    """SSE progress stream. The UI must ALSO poll GET /jobs/{id} as a
    fallback (phase-02 risk note): a tunnel drop can kill this stream while
    the job keeps running server-side, and polling is the way back.

    Ownership is checked at the gate AND on every tick. The gate alone would
    lean on a guarantee that lives in another file — ids are not reused only
    because `models.py` declares the column AUTOINCREMENT — and nothing here
    would notice if that changed. The loop already re-reads the row for
    progress, so the extra check is one string comparison: no query, no I/O.
    Measured failure it closes: restore `jobs.db` from a backup while a stream
    is open and the same id can belong to someone else, at which point their
    URL, email and cookie status flow down a stream opened by another person.
    """
    _job_cua_toi_hoac_404(job_id, nguoi_tao)

    async def _generator():
        last_payload: str | None = None
        while True:
            job = models.get_job(DB_PATH, job_id)
            if job is None:
                break
            if not is_admin(nguoi_tao) and job["nguoi_tao"] != nguoi_tao:
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
