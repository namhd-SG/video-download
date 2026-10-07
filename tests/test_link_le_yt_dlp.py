"""Link lẻ qua yt-dlp: opts theo nền tảng, cổng thiếu Deno, cảnh báo JS runtime, bước liệt kê (trần 15 phút /
500MB / playlist), nhiều link một job, và log không mang URL/id.

DB file thật; yt-dlp giả ở ranh giới (`tests/yt_dlp_gia.py`); không mạng.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from link_le_khung import DENO, FFMPEG, Khung
from yt_dlp_gia import YtdlpGia, loi_tai, thong_tin

from tiktok_music_downloader import downloader
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.utils import USER_AGENTS, VideoRef
from web import models

A, B, C = "aAa1aAa1aAa", "bBb2bBb2bBb", "cCc3cCc3cCc"


def _yt(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def _gia_ba_video():
    return YtdlpGia({_yt(v): thong_tin(v) for v in (A, B, C)})


# ---------------------------------------------------------------- opts theo nền tảng

def test_opts_tiktok_la_dict_cu_nguyen_ven():
    """Golden: mọi khoá và giá trị của dict TikTok trước khi có nền tảng khác. Thêm/bớt/đổi một khoá ⇒ ĐỎ."""
    opts = downloader._ydl_opts(Path("/o"), None, None)
    logger = opts.pop("logger")
    ua = opts.pop("http_headers")
    assert isinstance(logger, downloader._YtdlpLog)
    assert ua["User-Agent"] in USER_AGENTS and set(ua) == {"User-Agent"}
    assert opts == {
        "format": ("bv*[vcodec^=h264][protocol^=http]+ba/"
                   "best[ext=mp4][vcodec!=none]/best[vcodec!=none]"),
        "outtmpl": "/o/%(id)s.%(ext)s",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 1,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_args": {"tiktok": {"api_hostname": ["api22-normal-c-useast2a.tiktokv.com"]}},
    }
    assert "ffmpeg_location" not in opts and "js_runtimes" not in opts


def test_opts_proxy_va_cookie_cua_tiktok_van_nhu_cu():
    opts = downloader._ydl_opts(Path("/o"), "http://p:1", "/c.txt")
    assert opts["proxy"] == "http://p:1" and opts["cookiefile"] == "/c.txt"


def test_download_all_khong_nen_tang_dung_dung_dict_tiktok(monkeypatch, tmp_path):
    """Lời gọi cũ (không `nen_tang`) tới yt-dlp mang đúng dict TikTok: cùng khoá, outtmpl theo `%(id)s`."""
    gia = YtdlpGia({"https://www.tiktok.com/@u/video/111": {"id": "111"}})
    monkeypatch.setattr(downloader, "YoutubeDL", gia)
    monkeypatch.setattr(downloader.time, "sleep", lambda s: None)
    ref = VideoRef(video_id="111", url="https://www.tiktok.com/@u/video/111")
    ket = downloader.download_all([ref], tmp_path / "o", delay_seconds=0.0)
    assert ket == (1, 0, [])
    opts = gia.opts_da_tao[0]
    assert opts["outtmpl"] == str(tmp_path / "o" / "%(id)s.%(ext)s")
    assert opts["extractor_args"]["tiktok"]["api_hostname"] == ["api22-normal-c-useast2a.tiktokv.com"]
    assert "ffmpeg_location" not in opts and "js_runtimes" not in opts and "noplaylist" not in opts


def test_opts_nen_tang_khac_co_ffmpeg_deno_va_khong_co_dau_vet_tiktok(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "find_deno", lambda: DENO)
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: FFMPEG)
    opts = downloader._ydl_opts_nen_tang_khac(tmp_path, None, None)
    assert opts["ffmpeg_location"] == FFMPEG
    assert opts["js_runtimes"] == {"deno": {"path": DENO}}
    assert "extractor_args" not in opts and "http_headers" not in opts
    assert opts["noplaylist"] is True and opts["merge_output_format"] == "mp4"
    # mọi nhánh format đều đòi luồng có hình, ưu tiên ≤1080p
    nhanh = opts["format"].split("/")
    assert all("vcodec!=none" in n for n in nhanh), nhanh
    assert "height<=1080" in nhanh[0] and "ext=mp4" in nhanh[0]


def test_khong_tim_thay_deno_hay_ffmpeg_thi_bo_khoa_chu_khong_truyen_none(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "find_deno", lambda: None)
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: None)
    opts = downloader._ydl_opts_nen_tang_khac(tmp_path, None, None)
    assert "js_runtimes" not in opts and "ffmpeg_location" not in opts


def test_tai_nen_tang_khac_that_su_mang_ffmpeg_va_deno_va_ten_tep_theo_id_co_tien_to(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["trang_thai"] == "done" and job["xong"] == 1
    opts_tai = [o for o in gia.opts_da_tao if "outtmpl" in o]
    assert len(opts_tai) == 1
    assert opts_tai[0]["ffmpeg_location"] == FFMPEG
    assert opts_tai[0]["js_runtimes"] == {"deno": {"path": DENO}}
    assert opts_tai[0]["outtmpl"].endswith(f"/yt-{A}.%(ext)s")
    assert (k.downloads / str(job["id"]) / f"yt-{A}.mp4").is_file()


def test_buoc_liet_ke_cung_mang_ffmpeg_va_deno(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([_yt(A)]))
    opts_liet_ke = [o for o in gia.opts_da_tao if o.get("skip_download")]
    assert len(opts_liet_ke) == 1
    assert opts_liet_ke[0]["js_runtimes"] == {"deno": {"path": DENO}} and opts_liet_ke[0]["noplaylist"] is True


def test_nen_tang_khac_thieu_ffmpeg_la_loi_cua_video_noi_ro(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia, ffmpeg=None)
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["loi"] == 1 and job["xong"] == 0 and job["trang_thai"] == "failed"
    assert gia.so_goi("tai") == 0          # không gọi tải khi biết sẽ không ghép được


# ---------------------------------------------------------------- cổng thiếu Deno

def test_youtube_thieu_deno_dung_truoc_moi_loi_goi_va_khong_ghi_luot(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia, deno=None)
    job = k.chay(k.tao_job([_yt(A)]))
    assert (job["trang_thai"], job["ly_do_dung"]) == ("failed", "thieu_deno")
    assert gia.goi == [] and gia.opts_da_tao == []     # 0 lượt gọi yt-dlp, kể cả dựng đối tượng
    assert k.so_luot() == 0                            # 0 lượt tính vào trần IP


def test_doi_chung_co_deno_thi_cung_job_chay_binh_thuong(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)               # có Deno
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["ly_do_dung"] in (None, "") and job["xong"] == 1 and gia.so_goi() == 2


def test_thieu_deno_chi_chan_youtube_nen_tang_khac_van_chay(monkeypatch, tmp_path):
    ig = "https://www.instagram.com/reel/Cabc123xyz/"
    gia = YtdlpGia({ig: thong_tin("Cabc123xyz")})
    k = Khung(monkeypatch, tmp_path, gia, deno=None)
    job = k.chay(k.tao_job([ig], nen_tang="instagram"))
    assert job["xong"] == 1 and job["ly_do_dung"] in (None, "")
    assert "js_runtimes" not in gia.opts_da_tao[0]


# ---------------------------------------------------------------- cảnh báo JS runtime

_CANH_BAO_JS = ("[youtube] No supported JavaScript runtime could be found. YouTube extraction without a "
                "JS runtime has been deprecated, and some formats may be missing.")


def test_canh_bao_khong_co_js_runtime_o_buoc_tai_la_loi_video_va_xoa_tep(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(A): thong_tin(A)}, canh_bao_khi_tai=_CANH_BAO_JS)
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["loi"] == 1 and job["xong"] == 0 and job["tim_thay"] == 1
    assert gia.so_goi("tai") >= 1
    assert not (k.downloads / str(job["id"]) / f"yt-{A}.mp4").exists()   # tệp tải dở bị xoá, lượt sau không "đã có"


def test_canh_bao_js_runtime_o_buoc_liet_ke_la_loi_cua_link_do(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(A): thong_tin(A)}, canh_bao_khi_liet_ke=_CANH_BAO_JS)
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["loi"] == 1 and job["xong"] == 0 and job["tim_thay"] == 0
    assert gia.so_goi("tai") == 0


def test_ytdlp_log_bat_canh_bao_js_va_van_xuong_debug(caplog):
    lg = downloader._YtdlpLog()
    with caplog.at_level("DEBUG", logger="ttmd"):
        lg.warning("chuyện khác")
        assert lg.thieu_js is False
        lg.warning("[youtube] No supported JavaScript runtime could be found")
    assert lg.thieu_js is True
    assert all(r.levelno == logging.DEBUG for r in caplog.records)


# ---------------------------------------------------------------- bước liệt kê: trần từng video

@pytest.mark.parametrize("them, ma", [
    ({"duration": 901}, "qua_dai"),
    ({"filesize_approx": 500 * 1024 * 1024 + 1}, "qua_nang"),
    ({"filesize": 600 * 1024 * 1024}, "qua_nang"),
    ({"requested_formats": [{"filesize": 300 * 1024 * 1024}, {"filesize_approx": 300 * 1024 * 1024}]}, "qua_nang"),
    ({"_type": "playlist", "entries": [{}]}, "la_playlist"),
    ({"is_live": True}, "truc_tiep"),
    ({"live_status": "is_upcoming"}, "truc_tiep"),
])
def test_video_vuot_tran_bi_bo_la_loi_tung_video_khong_tai(monkeypatch, tmp_path, caplog, them, ma):
    gia = YtdlpGia({_yt(A): thong_tin(A, **them), _yt(B): thong_tin(B)})
    k = Khung(monkeypatch, tmp_path, gia)
    with caplog.at_level("WARNING", logger="videodl.web"):
        job = k.chay(k.tao_job([_yt(A), _yt(B)]))
    assert job["tim_thay"] == 1 and job["xong"] == 1 and job["loi"] == 1
    assert job["loi_tiktok"] == 1                              # phía nguồn, không phải lỗi hệ thống
    assert gia.so_goi("tai") == 1 and gia.goi[-1] == ("tai", _yt(B))
    assert any(f"[{ma}]" in r.getMessage() for r in caplog.records)
    assert k.nen_tang_tat() == {}


def test_bien_tran_dung_15_phut_va_500mb_van_tai(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(A): thong_tin(A, duration=900, filesize_approx=500 * 1024 * 1024)})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A)]))
    assert job["xong"] == 1 and job["loi"] == 0


def test_moi_link_deu_loi_thi_job_failed_source_empty(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(A): thong_tin(A, duration=9999)})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A)]))
    assert (job["trang_thai"], job["ly_do_dung"], job["loi"]) == ("failed", "source_empty", 1)


def test_loi_mang_o_buoc_liet_ke_la_loi_he_thong_khong_tat_nen_tang(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(B): thong_tin(B)}, {_yt(A): loi_tai("ERROR: Unable to download webpage: timed out")})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A), _yt(B)]))
    assert job["xong"] == 1 and job["loi"] == 1 and job["loi_tiktok"] == 0
    assert k.nen_tang_tat() == {}


# ---------------------------------------------------------------- nhiều link một job

def test_ba_link_cung_nen_tang_la_mot_job_ba_video(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    jid = k.tao_job([_yt(A), _yt(B), _yt(C)])
    job = k.chay(jid)
    assert job["trang_thai"] == "done" and (job["tong"], job["tim_thay"], job["xong"], job["loi"]) == (20, 3, 3, 0)
    assert [u for l, u in gia.goi if l == "liet_ke"] == [_yt(A), _yt(B), _yt(C)]
    assert [u for l, u in gia.goi if l == "tai"] == [_yt(A), _yt(B), _yt(C)]
    # mỗi video một dòng thư viện, id có tiền tố, và nghỉ jitter giữa các lời gọi liệt kê (2 khoảng cho 3 link)
    assert models.known_video_ids(k.db, [f"yt-{A}", f"yt-{B}", f"yt-{C}"]) == {f"yt-{A}", f"yt-{B}", f"yt-{C}"}
    assert k.nghi_giua_luot == 2
    # nghỉ 10–20 s giữa video (2 khoảng cho 3 video)
    nghi_video = [s for s in k.ngu if s > 1]
    assert len(nghi_video) == 2 and all(10.0 <= s <= 20.0 for s in nghi_video), k.ngu


def test_tran_so_luong_cat_bot_so_video_nhan(monkeypatch, tmp_path):
    k = Khung(monkeypatch, tmp_path, _gia_ba_video())
    job = k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)], so_luong=2))
    assert job["xong"] == 2 and job["tim_thay"] == 2


def test_video_da_co_trong_thu_vien_duoc_bo_qua_khi_chay_lai(monkeypatch, tmp_path):
    gia = _gia_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([_yt(A), _yt(B)]))
    gia.goi.clear()
    job2 = k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)]))
    assert job2["bo_qua"] == 2 and job2["xong"] == 1
    assert [u for l, u in gia.goi if l == "tai"] == [_yt(C)]


def test_tiktok_video_le_khong_goi_mang_o_buoc_liet_ke_va_giu_id_so(monkeypatch, tmp_path):
    url = "https://www.tiktok.com/@nguoi.dung/video/7123456789012345678"
    gia = YtdlpGia({url: {"id": "7123456789012345678"}})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([url], nen_tang="tiktok"))
    assert [l for l, _ in gia.goi] == ["tai"]                    # liệt kê không gọi yt-dlp
    opts = gia.opts_da_tao[0]
    assert "extractor_args" in opts and "ffmpeg_location" not in opts and "js_runtimes" not in opts
    assert job["xong"] == 1 and (k.downloads / str(job["id"]) / "7123456789012345678.mp4").is_file()
    assert k.so_luot() == 0                                      # lane TikTok không đi qua pacer IP


# ---------------------------------------------------------------- log không URL, không id

def test_log_job_link_le_khong_mang_url_hay_id(monkeypatch, tmp_path):
    import io
    from web.app import CheUrlFormatter
    ra = io.StringIO()
    h = logging.StreamHandler(ra)
    h.setFormatter(CheUrlFormatter("%(levelname)s %(name)s: %(message)s"))
    tho = io.StringIO()
    h_tho = logging.StreamHandler(tho)                           # đối chứng: log KHÔNG qua formatter che
    h_tho.setFormatter(logging.Formatter("%(message)s"))
    gia = YtdlpGia(
        {_yt(A): thong_tin(A, title=f"gi do {A}"), _yt(B): thong_tin(B), _yt(C): thong_tin(C)},
        {_yt(B): loi_tai(f"ERROR: [youtube] {B}: Video unavailable. https://www.youtube.com/watch?v={B}"),
         # C: liệt kê được (None), rồi LỖI Ở BƯỚC TẢI — hai đường log khác nhau đều phải sạch
         _yt(C): [None, loi_tai(f"ERROR: [youtube] {C}: Video unavailable. https://youtu.be/{C}")]},
    )
    k = Khung(monkeypatch, tmp_path, gia)
    raiz = logging.getLogger()
    cu = raiz.level
    raiz.setLevel(logging.DEBUG)
    raiz.addHandler(h)
    raiz.addHandler(h_tho)
    try:
        k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)]))
    finally:
        raiz.removeHandler(h)
        raiz.removeHandler(h_tho)
        raiz.setLevel(cu)
    sach, tho_txt = ra.getvalue(), tho.getvalue()
    assert f"yt-{A}" in tho_txt, "đối chứng: không qua formatter che thì id có tiền tố PHẢI lộ trong log"
    for nhay in ("youtube.com", "youtu.be", "watch?v=", A, B, C):
        assert nhay not in sach, f"log lộ {nhay!r}:\n{sach}"
    assert "yt-" not in sach.replace("yt-dlp", "")


@pytest.mark.parametrize("thong_diep, con_lai", [
    ("ERROR: [youtube] dQw4w9WgXcQ: Video unavailable", "ERROR: [youtube] <id>: Video unavailable"),
    ("ERROR: [youtube:tab] dQw4w9WgXcQ: x", "ERROR: [youtube:tab] <id>: x"),
    ("✗ yt-dQw4w9WgXcQ: [he_thong] boom", "✗ <id>: [he_thong] boom"),
    ("✓ ig-Cabc_1-xyz.mp4 fbv-123456789 x-1234567890123 pin-123456 dy-7123456789 bili-BV1xx411c7mD snap-W7_EDl",
     "✓ <id>.mp4 <id> <id> <id> <id> <id> <id>"),
])
def test_che_url_che_id_link_le_cua_nen_tang_khac_tiktok(thong_diep, con_lai):
    from tiktok_music_downloader.utils import che_url
    assert che_url(thong_diep) == con_lai


def test_che_url_khong_che_ten_thu_vien_va_giu_id_tiktok_nhu_quyet_dinh_cu():
    from tiktok_music_downloader.utils import che_url
    assert che_url("yt-dlp: [debug] Command-line config") == "yt-dlp: [debug] Command-line config"
    assert che_url("ERROR: [TikTok] 7692740350766517525: No video formats found!") == \
        "ERROR: [TikTok] 7692740350766517525: No video formats found!"
