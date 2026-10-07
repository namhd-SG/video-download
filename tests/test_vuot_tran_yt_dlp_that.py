"""Nhãn `qua_nang` của TikTok video lẻ dựa vào dòng log yt-dlp in khi bỏ một lượt tải vì vượt `max_filesize`.

Test này chạy bộ tải HTTP THẬT của yt-dlp với một máy chủ localhost (không mạng ngoài) để khoá hai giả định mà
`downloader._YtdlpLog` dựa vào: (1) yt-dlp so trần với TỪNG lượt tải, kể cả định dạng ghép; (2) dòng báo bỏ vì
trần đi tới `logger.debug`. Nâng bản yt-dlp mà một trong hai đổi thì test này đỏ trước.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from tiktok_music_downloader import downloader

TRAN = 1000   # byte


class _MayChu(BaseHTTPRequestHandler):
    """`/<n>.bin` trả n byte, luôn kèm Content-Length (như CDN thật)."""

    def do_GET(self):
        n = int(self.path.strip("/").split(".")[0])
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(n))
        self.end_headers()
        self.wfile.write(b"x" * n)

    def log_message(self, *_a):
        pass


@pytest.fixture(scope="module")
def goc_url():
    may = ThreadingHTTPServer(("127.0.0.1", 0), _MayChu)
    luong = threading.Thread(target=may.serve_forever, daemon=True)
    luong.start()
    yield f"http://127.0.0.1:{may.server_address[1]}"
    may.shutdown()
    may.server_close()


def _tai(goc_url, tmp_path, dinh_dang: list[tuple[str, str, str, int]], chon: str):
    """Tải thật qua yt-dlp; trả (cờ vuot_tran, tên các tệp đã ghi, lỗi yt-dlp nếu có).

    `allow_unplayable_formats`: định dạng ghép thì tải TỪNG luồng và KHÔNG ghép, bất kể máy có ffmpeg hay không (thiếu
    ffmpeg thì yt-dlp mặc định dừng TRƯỚC khi tải luồng nào) ⇒ kết quả tất định trên mọi máy. Kết cục giống ca thật
    "tải đủ luồng mà thiếu `<id>.mp4`" (ghép trượt) — đúng ca cần phân định."""
    formats = [{"format_id": fid, "url": f"{goc_url}/{n}.bin", "ext": ext, "protocol": "http",
                "vcodec": "h264" if kieu == "hinh" else "none", "acodec": "aac" if kieu == "tieng" else "none"}
               for fid, kieu, ext, n in dinh_dang]
    info = {"id": "v1", "title": "t", "extractor": "gia", "extractor_key": "Gia",
            "webpage_url": f"{goc_url}/trang", "formats": formats}
    logger = downloader._YtdlpLog()
    opts = {"logger": logger, "max_filesize": TRAN, "format": chon, "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
            "retries": 0, "noprogress": True, "allow_unplayable_formats": True}
    loi = None
    with YoutubeDL(opts) as ydl:
        try:
            ydl.process_ie_result(info, download=True)
        except DownloadError as exc:
            loi = exc
    return logger.vuot_tran, sorted(p.name for p in tmp_path.iterdir()), loi


def test_mot_luong_vuot_tran_thi_yt_dlp_bo_va_co_bat_duoc(goc_url, tmp_path):
    vuot, tep, _loi = _tai(goc_url, tmp_path, [("v", "hinh", "mp4", 5 * TRAN)], "v")
    assert vuot is True and not any(t.startswith("v1.") and not t.endswith(".part") for t in tep)


def test_doi_chung_mot_luong_duoi_tran_thi_tai_va_khong_bat_co(goc_url, tmp_path):
    vuot, tep, loi = _tai(goc_url, tmp_path, [("v", "hinh", "mp4", TRAN // 2)], "v")
    assert vuot is False and "v1.mp4" in tep and loi is None


def test_dinh_dang_ghep_tong_vuot_tran_nhung_tung_luong_duoi_tran_thi_khong_bat_co(goc_url, tmp_path):
    """Hình 800 + tiếng 800 > trần 1000, nhưng yt-dlp so từng lượt tải ⇒ tải cả hai, KHÔNG có dòng vượt trần. Ghép
    có trượt (byte rác) hay không thì thiếu `v1.mp4` ở đây cũng KHÔNG được dán `qua_nang`."""
    vuot, tep, _loi = _tai(goc_url, tmp_path, [("v", "hinh", "mp4", 800), ("a", "tieng", "m4a", 800)], "v+a")
    assert vuot is False
    assert tep == ["v1.fa.m4a", "v1.fv.mp4"]          # cả hai luồng đã xuống đĩa, KHÔNG có `v1.mp4`


def test_dinh_dang_ghep_mot_luong_vuot_tran_thi_bat_co(goc_url, tmp_path):
    vuot, tep, loi = _tai(goc_url, tmp_path, [("v", "hinh", "mp4", 5 * TRAN), ("a", "tieng", "m4a", 100)], "v+a")
    assert vuot is True and loi is None and tep == ["v1.fa.m4a"]   # yt-dlp bỏ IM LẶNG: không ném, chỉ có dòng log


def test_cau_vuot_tran_con_trong_nguon_yt_dlp_da_cai():
    """Hợp đồng NGẦM với yt-dlp: `_YtdlpLog` bắt câu này bằng chuỗi. Nâng bản yt-dlp mà câu đổi thì nhãn `qua_nang`
    hỏng ÂM THẦM (cờ luôn False) ⇒ test này đỏ với thông báo chỉ thẳng vào chỗ phải sửa (các test tải thật bên trên
    cũng đỏ, nhưng không nói vì sao)."""
    from pathlib import Path

    import yt_dlp.downloader.http as http_ytdlp
    nguon = Path(http_ytdlp.__file__).read_text(encoding="utf-8").lower()
    assert downloader._MAU_VUOT_TRAN in nguon, (
        "yt-dlp đã đổi câu báo bỏ lượt tải vì max_filesize — sửa `downloader._MAU_VUOT_TRAN`")


def test_co_vuot_tran_dat_lai_moi_lan_thu_cua_tenacity(monkeypatch):
    """Lần thử 1: yt-dlp bỏ một luồng vì trần rồi lỗi mạng ⇒ thử lại. Lần thử 2 tải xong không có dòng vượt trần ⇒
    cờ phải là False (không sót từ lần thử 1)."""
    import tenacity

    luot = []

    class _Ydl:
        def __init__(self, opts):
            self._opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def extract_info(self, url, download=True):
            luot.append(url)
            if len(luot) == 1:
                self._opts["logger"].debug(f"\r[download] File is larger than max-filesize (2 bytes > {TRAN} bytes). Aborting.")
                raise ConnectionError("đứt mạng giữa chừng")
            return {"id": "v1"}

    monkeypatch.setattr(downloader, "YoutubeDL", _Ydl)
    monkeypatch.setattr(downloader._download_one.retry, "wait", tenacity.wait_none())
    logger = downloader._YtdlpLog()
    downloader._download_one("http://e.invalid/v", {"logger": logger})
    assert len(luot) == 2 and logger.vuot_tran is False


def test_lan_thu_cuoi_bi_bo_vi_tran_thi_co_van_true(monkeypatch):
    """Chiều ngược: đặt lại cờ đầu mỗi lần thử KHÔNG được làm mất cờ đúng. Lần 1 lỗi mạng ⇒ thử lại; lần 2 yt-dlp bỏ
    vì trần (in dòng, KHÔNG ném) ⇒ hàm trả bình thường và cờ phải còn True."""
    import tenacity

    luot = []

    class _Ydl:
        def __init__(self, opts):
            self._opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def extract_info(self, url, download=True):
            luot.append(url)
            if len(luot) == 1:
                raise ConnectionError("đứt mạng giữa chừng")
            self._opts["logger"].debug(f"\r[download] File is larger than max-filesize (2 bytes > {TRAN} bytes). Aborting.")
            return {"id": "v1"}

    monkeypatch.setattr(downloader, "YoutubeDL", _Ydl)
    monkeypatch.setattr(downloader._download_one.retry, "wait", tenacity.wait_none())
    logger = downloader._YtdlpLog()
    downloader._download_one("http://e.invalid/v", {"logger": logger})
    assert len(luot) == 2 and logger.vuot_tran is True
