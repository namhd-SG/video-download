"""Pacer trần IP của lane nền tảng khác: trần giờ/ngày (đồng hồ tiêm), lượt ghi TRƯỚC khi gọi, tín hiệu chặn ⇒ tắt
nền tảng, admin bật lại, và `loai_tru_fn` nối vào lane thật.

DB file thật, `JobWorker` thật, `process_job` thật; chỉ yt-dlp/Drive/đồng hồ là giả (xem `link_le_khung.py`).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from link_le_khung import Khung
from yt_dlp_gia import YtdlpGia, loi_tai, thong_tin

from tiktok_music_downloader import nguon as nguon_mod
from web import app as app_mod
from web import models, pacer
from web.queue import JobWorker

POLL = 0.05
IG = "https://www.instagram.com/reel/Cabc123xyz/"


def _yt(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def _vid(i):
    return f"{i:011d}"


class _Dia:
    ok = True
    reason = ""


def _cho(dieu_kien, giay=8.0):
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        time.sleep(0.01)
    return dieu_kien()


def _trang_thai(db, jid):
    return models.get_job(db, jid)["trang_thai"]


def _worker_khac(k):
    return JobWorker(k.db, k.downloads, k.cookies, poll_interval=POLL, process_job_fn=k.process_job_fn(),
                     disk_guard_fn=lambda _p: _Dia(), lane="khac",
                     loai_tru_fn=lambda: pacer.nen_tang_loai_tru(k.db))


def _gia(*vids, ig=False):
    t = {_yt(v): thong_tin(v) for v in vids}
    if ig:
        t[IG] = thong_tin("Cabc123xyz")
    return YtdlpGia(t)


# ------------------------------------------------------------------ hằng số và sổ lượt

def test_hang_so_tran_o_mot_cho():
    assert pacer.TRAN["youtube"] == (60, 300)
    for nt in ("instagram", "facebook", "x", "pinterest", "douyin", "bilibili", "snapchat"):
        assert pacer.TRAN[nt] == (30, 100), nt
    assert "tiktok" not in pacer.TRAN                       # lane TikTok y nguyên
    assert pacer.NGHI_GIUA_LUOT == (10.0, 20.0)


def test_tran_gio_60_cho_phep_va_luot_61_bi_tu_choi_khong_ghi(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    t0 = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    for i in range(60):
        assert pacer.ghi_truoc_khi_goi(db, "youtube", 1, now=t0 + timedelta(seconds=i)) is None
    t = t0 + timedelta(minutes=5)
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1, now=t) == "tran_gio"
    with models._connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM luot_tai").fetchone()[0] == 60        # từ chối không ghi
    # cửa sổ TRƯỢT 60 phút: lượt cũ nhất rời cửa sổ thì đúng một chỗ trống
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1, now=t0 + timedelta(minutes=59)) == "tran_gio"
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1, now=t0 + timedelta(minutes=60, seconds=1)) is None
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1, now=t0 + timedelta(minutes=60, seconds=1)) == "tran_gio"
    # nền tảng khác không chung sổ
    assert pacer.ghi_truoc_khi_goi(db, "instagram", 2, now=t) is None


def test_tran_ngay_theo_gio_vn_va_ngay_moi_chay_lai_duoc(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setitem(pacer.TRAN, "instagram", (1000, 7))
    t0 = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)       # 22:00 giờ VN ngày 7
    for i in range(7):
        assert pacer.ghi_truoc_khi_goi(db, "instagram", 1, now=t0 + timedelta(minutes=i)) is None
    assert pacer.ghi_truoc_khi_goi(db, "instagram", 1, now=t0 + timedelta(hours=1)) == "tran_ngay"
    # 16:59 UTC = 23:59 VN: vẫn ngày 7 ⇒ vẫn hết trần. 17:01 UTC = 00:01 VN ngày 8 ⇒ ngày mới.
    assert pacer.ghi_truoc_khi_goi(db, "instagram", 1, now=datetime(2026, 10, 7, 16, 59, tzinfo=timezone.utc)) == "tran_ngay"
    assert pacer.ghi_truoc_khi_goi(db, "instagram", 1, now=datetime(2026, 10, 7, 17, 1, tzinfo=timezone.utc)) is None


def test_nen_tang_tat_tu_choi_ngay_ke_ca_khi_con_tran(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    assert pacer.tat_nen_tang(db, "youtube", "not_a_bot") is True
    assert pacer.tat_nen_tang(db, "youtube", "http_429") is False        # giữ mốc và lý do ĐẦU
    assert pacer.nen_tang_dang_tat(db)["youtube"]["ly_do"] == "not_a_bot"
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1) == "bi_chan"
    assert pacer.bat_lai(db, "youtube") is True and pacer.bat_lai(db, "youtube") is False
    assert pacer.ghi_truoc_khi_goi(db, "youtube", 1) is None


def test_bang_luot_tai_va_nen_tang_tat_song_sau_khi_khoi_dong_lai(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    pacer.ghi_truoc_khi_goi(db, "youtube", 7)
    pacer.tat_nen_tang(db, "instagram", "http_429")
    models.init_db(db)                                      # khởi động lại: idempotent, không xoá gì
    with models._connect(db) as c:
        assert [tuple(r) for r in c.execute("SELECT nen_tang, job_id FROM luot_tai")] == [("youtube", 7)]
    assert "instagram" in pacer.nen_tang_dang_tat(db)


# ------------------------------------------------------------------ loai_tru = TẮT ∪ hết trần giờ ∪ hết trần ngày

def test_loai_tru_la_hop_cua_tat_tran_gio_tran_ngay_va_nen_tang_chua_bat(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,instagram,facebook,x,tiktok")
    monkeypatch.setitem(pacer.TRAN, "instagram", (2, 1000))
    monkeypatch.setitem(pacer.TRAN, "facebook", (1000, 2))
    t0 = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    assert pacer.nen_tang_loai_tru(db, now=t0) == ("bilibili", "douyin", "pinterest", "snapchat")   # chỉ vì chưa bật
    pacer.tat_nen_tang(db, "youtube", "not_a_bot")
    for _ in range(2):
        pacer.ghi_truoc_khi_goi(db, "instagram", 1, now=t0)
    for i in range(2):
        pacer.ghi_truoc_khi_goi(db, "facebook", 1, now=t0 - timedelta(hours=5, minutes=-i))   # ngoài cửa sổ giờ, trong ngày
    ra = pacer.nen_tang_loai_tru(db, now=t0)
    assert {"youtube", "instagram", "facebook"} <= set(ra) and "x" not in ra
    # sau 61 phút instagram hết chặn giờ, facebook (trần ngày) thì chưa; sang ngày VN mới thì facebook cũng hết
    ra2 = pacer.nen_tang_loai_tru(db, now=t0 + timedelta(minutes=61))
    assert "instagram" not in ra2 and "facebook" in ra2 and "youtube" in ra2
    ra3 = pacer.nen_tang_loai_tru(db, now=datetime(2026, 10, 7, 17, 5, tzinfo=timezone.utc))
    assert "facebook" not in ra3 and "youtube" in ra3          # tắt vì bị chặn thì KHÔNG tự hết theo giờ


def test_loai_tru_fn_cua_lane_khac_noi_vao_db_that_cua_app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    assert "youtube" not in app_mod.worker_khac._loai_tru_fn()
    pacer.tat_nen_tang(db, "youtube", "http_429")
    assert "youtube" in app_mod.worker_khac._loai_tru_fn()
    assert "youtube" not in app_mod.worker._loai_tru_fn()       # lane TikTok không lọc theo bộ này


def test_lifespan_dung_worker_khac_voi_loai_tru_fn_that(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    da_dung: list[dict] = []

    class WorkerGia:
        def __init__(self, *a, lane="tiktok", loai_tru_fn=None, **k):
            self.lane, self.loai_tru_fn = lane, loai_tru_fn
            da_dung.append({"lane": lane, "loai_tru_fn": loai_tru_fn})

        def start(self): ...
        def stop(self): ...

    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "cookies")
    monkeypatch.setattr(app_mod, "COOKIE_TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(app_mod, "JobWorker", WorkerGia)
    monkeypatch.setattr(app_mod, "worker", WorkerGia(lane="tiktok"))
    monkeypatch.setattr(app_mod, "worker_khac", app_mod.worker_khac)
    monkeypatch.setattr(app_mod, "quet_khoi_dong", lambda p: 0)
    monkeypatch.setenv(app_mod.ENV_TAT_LAP_VAO_BO, "1")

    async def chay():
        async with app_mod._lifespan(app_mod.app):
            pass

    asyncio.run(chay())
    khac = [d for d in da_dung if d["lane"] == "khac"]
    assert len(khac) == 1 and khac[0]["loai_tru_fn"] is not None
    pacer.tat_nen_tang(db, "youtube", "http_429")
    assert "youtube" in khac[0]["loai_tru_fn"]()


# ------------------------------------------------------------------ lượt ghi TRƯỚC khi gọi (crash giữa chừng vẫn đếm)

def test_luot_liet_ke_ghi_truoc_khi_goi_nen_tang_chet_giua_loi_goi_van_dem(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(_vid(1)): thong_tin(_vid(1))}, {_yt(_vid(1)): SystemExit(1)})
    k = Khung(monkeypatch, tmp_path, gia)
    jid = k.tao_job([_yt(_vid(1))])
    with pytest.raises(SystemExit):
        k.chay(jid)
    assert gia.so_goi("liet_ke") == 1
    assert k.so_luot("youtube") == 1, "tiến trình chết GIỮA lời gọi mà sổ chưa có lượt nào ⇒ đếm thiếu"


def test_luot_tai_ghi_truoc_khi_goi_nen_tang_chet_giua_loi_goi_van_dem(monkeypatch, tmp_path):
    u = _yt(_vid(1))
    gia = YtdlpGia({u: thong_tin(_vid(1))}, {u: [None, SystemExit(1)]})     # liệt kê xong, CHẾT lúc tải
    k = Khung(monkeypatch, tmp_path, gia)
    jid = k.tao_job([u])
    with pytest.raises(SystemExit):
        k.chay(jid)
    assert gia.so_goi("tai") == 1
    assert k.so_luot("youtube") == 2, "liệt kê 1 + tải 1; chết giữa lúc tải vẫn phải có lượt tải"


def test_moi_lan_thu_lai_cua_loi_thuong_la_mot_luot(monkeypatch, tmp_path):
    u = _yt(_vid(1))
    loi_403 = lambda: loi_tai("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    gia = YtdlpGia({u: thong_tin(_vid(1))}, {u: [None, loi_403(), loi_403(), loi_403()]})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([u]))
    assert gia.so_goi("tai") == 3 and job["loi"] == 1
    assert k.so_luot("youtube") == 4                        # 1 liệt kê + 3 lần tải (kể cả lần lỗi)
    assert k.nen_tang_tat() == {}


# ------------------------------------------------------------------ T4: trần giờ ⇒ job DỪNG, lane nhận ngay job nền tảng khác

def _gieo_luot(db, nen_tang, so, luc):
    for i in range(so):
        assert pacer.ghi_truoc_khi_goi(db, nen_tang, None, now=luc + timedelta(seconds=i)) is None


def test_t4_tran_gio_job_dung_lane_nhan_ngay_job_nen_tang_khac_khong_nhan_cung_nen_tang(monkeypatch, tmp_path):
    a, c = _vid(1), _vid(2)
    gia = _gia(a, c, ig=True)
    k = Khung(monkeypatch, tmp_path, gia)
    _gieo_luot(k.db, "youtube", 59, k.gio[0] - timedelta(minutes=10))
    ja = k.tao_job([_yt(a)])
    jb = k.tao_job([IG], nen_tang="instagram")
    jc = k.tao_job([_yt(c)])
    w = _worker_khac(k)
    w.start()
    try:
        assert _cho(lambda: _trang_thai(k.db, ja) == "failed")
        t_a = time.monotonic()
        job_a = models.get_job(k.db, ja)
        assert job_a["ly_do_dung"] == "tran_gio" and job_a["xong"] == 0
        assert k.so_luot("youtube") == 60                    # 59 gieo + lượt liệt kê thứ 60; lượt tải 61 bị từ chối
        assert _cho(lambda: _trang_thai(k.db, jb) == "done")
        assert time.monotonic() - t_a <= 2 * POLL + 0.5, "lane không nhận NGAY job nền tảng khác"
        assert models.get_job(k.db, jb)["xong"] == 1
        # job YouTube sau đó KHÔNG được nhận khi cửa sổ giờ còn đầy (chờ quá vài nhịp poll)
        time.sleep(6 * POLL)
        assert _trang_thai(k.db, jc) == "pending" and gia.so_goi("liet_ke") == 2
        # cửa sổ trống (đồng hồ tiêm +61 phút) ⇒ nhận và chạy
        k.gio[0] += timedelta(minutes=61)
        assert _cho(lambda: _trang_thai(k.db, jc) == "done")
    finally:
        w.stop()


def test_t4_khong_ngu_cho_cua_so_job_dung_ngay_ca_luc_cua_so_khong_trong(monkeypatch, tmp_path):
    a = _vid(1)
    k = Khung(monkeypatch, tmp_path, _gia(a))
    _gieo_luot(k.db, "youtube", 59, k.gio[0] - timedelta(minutes=1))
    job = k.chay(k.tao_job([_yt(a)]))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "tran_gio"
    assert not [s for s in k.ngu if s >= 60], f"job ngủ chờ cửa sổ giờ: {k.ngu}"


# ------------------------------------------------------------------ T5: trần ngày

def test_t5_tran_ngay_chay_den_het_trong_ngay_roi_ngay_moi_chay_lai(monkeypatch, tmp_path):
    monkeypatch.setitem(pacer.TRAN, "youtube", (1000, 11))   # mỗi video = 1 lượt liệt kê + 1 lượt tải ⇒ 5 video + 1 lượt dư
    vids = [_vid(i) for i in range(1, 9)]
    gia = _gia(*vids)
    k = Khung(monkeypatch, tmp_path, gia)
    jobs = [k.tao_job([_yt(v)]) for v in vids]
    w = _worker_khac(k)
    w.start()
    try:
        assert _cho(lambda: _trang_thai(k.db, jobs[5]) == "failed")
        da_tai = [models.get_job(k.db, j)["xong"] for j in jobs]
        assert da_tai[:5] == [1] * 5 and da_tai[5] == 0
        assert models.get_job(k.db, jobs[5])["ly_do_dung"] == "tran_ngay"
        time.sleep(6 * POLL)                                 # lane KHÔNG nhận thêm job nào của nền tảng hết trần
        assert [_trang_thai(k.db, j) for j in jobs[6:]] == ["pending", "pending"]
        assert gia.so_goi("tai") == 5
        # ngày mới theo giờ VN (00:30 ngày 8) ⇒ hai job còn lại chạy
        k.gio[0] = datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)
        assert _cho(lambda: [_trang_thai(k.db, j) for j in jobs[6:]] == ["done", "done"])
    finally:
        w.stop()


def test_t5_het_tran_ngay_tu_truoc_thi_job_khong_bi_nhan(monkeypatch, tmp_path):
    monkeypatch.setitem(pacer.TRAN, "youtube", (1000, 10))
    vids = [_vid(i) for i in range(1, 8)]
    k = Khung(monkeypatch, tmp_path, _gia(*vids))
    jobs = [k.tao_job([_yt(v)]) for v in vids]
    w = _worker_khac(k)
    w.start()
    try:
        assert _cho(lambda: _trang_thai(k.db, jobs[4]) == "done")
        time.sleep(6 * POLL)
        assert [_trang_thai(k.db, j) for j in jobs[5:]] == ["pending", "pending"]   # đúng 10 lượt ⇒ không nhận job 6
        assert "youtube" in pacer.nen_tang_loai_tru(k.db)
    finally:
        w.stop()


# ------------------------------------------------------------------ tín hiệu chặn

CHUOI_CHAN = [
    ("not_a_bot", "ERROR: [youtube] aaaaaaaaaaa: Sign in to confirm you’re not a bot. Use --cookies-from-browser "
                  "or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ"),
    ("captcha_challenge", "ERROR: [youtube] aaaaaaaaaaa: Video unavailable. YouTube is requiring a captcha "
                          "challenge before playback"),
    ("rate_limited", "ERROR: [youtube] aaaaaaaaaaa: This content isn't available, try again later. The current "
                     "session has been rate-limited by YouTube for up to an hour. It is recommended to use `-t sleep`"),
    ("http_429", "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests "
                 "(caused by <HTTPError 429: Too Many Requests>)"),
]
CHUOI_RIENG_VIDEO = [
    "ERROR: [youtube] aaaaaaaaaaa: Sign in to confirm your age. This video may be inappropriate for some users. "
    "Use --cookies-from-browser or --cookies for the authentication.",
    "ERROR: [youtube] aaaaaaaaaaa: Private video. Sign in if you've been granted access to this video",
]


@pytest.mark.parametrize("giai_doan", ["liet_ke", "tai"])
@pytest.mark.parametrize("ma, thong_diep", CHUOI_CHAN)
def test_tin_hieu_chan_tat_nen_tang_job_bi_chan_va_admin_bat_lai_thi_nhan_lai(
        monkeypatch, tmp_path, giai_doan, ma, thong_diep):
    a, b = _vid(1), _vid(2)
    loi = loi_tai(thong_diep)
    gia = YtdlpGia({_yt(a): thong_tin(a), _yt(b): thong_tin(b)},
                   {_yt(a): loi if giai_doan == "liet_ke" else [None, loi]})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(a), _yt(b)]))
    assert (job["trang_thai"], job["ly_do_dung"]) == ("failed", "bi_chan")
    assert k.nen_tang_tat()["youtube"]["ly_do"] == ma
    # không gọi thêm gì sau tín hiệu chặn, và không thử lại lời gọi đã bị chặn
    assert gia.so_goi("tai") == (0 if giai_doan == "liet_ke" else 1)
    assert gia.so_goi("liet_ke") == (1 if giai_doan == "liet_ke" else 2)
    assert "youtube" in pacer.nen_tang_loai_tru(k.db)
    # lane không nhận job YouTube mới; admin bật lại ⇒ nhận lại
    jid2 = k.tao_job([_yt(b)])
    assert models.claim_next_pending_job(k.db, lane="khac", loai_tru=pacer.nen_tang_loai_tru(k.db)) is None
    assert pacer.bat_lai(k.db, "youtube") is True
    nhan = models.claim_next_pending_job(k.db, lane="khac", loai_tru=pacer.nen_tang_loai_tru(k.db))
    assert nhan is not None and nhan["id"] == jid2


@pytest.mark.parametrize("giai_doan", ["liet_ke", "tai"])
@pytest.mark.parametrize("thong_diep", CHUOI_RIENG_VIDEO)
def test_video_rieng_tu_hay_gioi_han_tuoi_chi_la_loi_video_khong_tat_nen_tang(
        monkeypatch, tmp_path, giai_doan, thong_diep):
    a, b = _vid(1), _vid(2)
    loi = loi_tai(thong_diep)
    gia = YtdlpGia({_yt(a): thong_tin(a), _yt(b): thong_tin(b)},
                   {_yt(a): loi if giai_doan == "liet_ke" else [None, loi]})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(a), _yt(b)]))
    assert k.nen_tang_tat() == {}
    assert job["trang_thai"] == "done" and job["xong"] == 1 and job["loi"] == 1 and job["loi_tiktok"] == 1
    assert job["ly_do_dung"] in (None, "")
    assert "youtube" not in pacer.nen_tang_loai_tru(k.db)
    if giai_doan == "tai":
        assert gia.so_goi("tai") == 2, "video riêng tư tải lại vô ích: đúng 1 lần cho A + 1 cho B"


def test_429_cua_nen_tang_khac_youtube_cung_tat_dung_nen_tang_do(monkeypatch, tmp_path):
    gia = YtdlpGia({IG: thong_tin("Cabc123xyz")}, {IG: loi_tai("ERROR: HTTP Error 429: Too Many Requests")})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([IG], nen_tang="instagram"))
    assert job["ly_do_dung"] == "bi_chan" and list(k.nen_tang_tat()) == ["instagram"]
    assert "youtube" not in pacer.nen_tang_loai_tru(k.db)


def test_so_429_tran_trong_url_hay_id_khong_phai_tin_hieu_chan(monkeypatch, tmp_path):
    a = _vid(1)
    gia = YtdlpGia({_yt(a): thong_tin(a)}, {_yt(a): loi_tai("ERROR: [youtube] 429429429: Video unavailable")})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(a)]))
    assert k.nen_tang_tat() == {} and job["loi"] == 1


# ------------------------------------------------------------------ admin

def test_admin_bat_lai_va_badge_hien_nen_tang_dang_tat(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    assert app_mod.admin_worker(nguoi_tao="sep@x.vn")["nen_tang_tat"] == {}
    pacer.tat_nen_tang(db, "youtube", "not_a_bot")
    hien = app_mod.admin_worker(nguoi_tao="sep@x.vn")["nen_tang_tat"]
    assert list(hien) == ["youtube"] and hien["youtube"]["ly_do"] == "not_a_bot" and hien["youtube"]["luc"]
    assert app_mod.admin_bat_nen_tang("youtube", nguoi_tao="sep@x.vn") == {"nen_tang": "youtube", "da_bat_lai": True}
    assert app_mod.admin_worker(nguoi_tao="sep@x.vn")["nen_tang_tat"] == {}
    assert app_mod.admin_bat_nen_tang("youtube", nguoi_tao="sep@x.vn")["da_bat_lai"] is False   # idempotent


@pytest.mark.parametrize("ten", ["tiktok", "drive", "fb_ads", "khong-co", "../etc"])
def test_admin_bat_lai_ten_la_hay_nen_tang_khong_dieu_toc_la_404(tmp_path, monkeypatch, ten):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    with pytest.raises(HTTPException) as e:
        app_mod.admin_bat_nen_tang(ten, nguoi_tao="sep@x.vn")
    assert e.value.status_code == 404


def test_route_bat_lai_doi_quyen_admin():
    from fastapi.routing import APIRoute
    r = next(r for r in app_mod.app.routes
             if isinstance(r, APIRoute) and r.path == "/admin/nen-tang/{nen_tang}/bat")
    assert r.methods == {"POST"} and any(d.call is app_mod.require_admin for d in r.dependant.dependencies)
