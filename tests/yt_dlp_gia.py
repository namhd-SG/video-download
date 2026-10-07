"""yt-dlp giả cho test link lẻ: thay lớp `YoutubeDL` ở RANH GIỚI mạng, mọi thứ phía trên chạy thật.

Một `YtdlpGia` thay cho `nguon.YoutubeDL` VÀ `downloader.YoutubeDL`: ghi lại từng bộ opts được dựng, từng lời gọi
`extract_info` (liệt kê hay tải) và — khi tải — ghi một tệp nhỏ đúng tên `outtmpl` đòi để các bước sau (kiểm luồng,
đẩy Drive) có tệp thật để đi qua. Không có mạng, không có yt-dlp thật.
"""
from __future__ import annotations

from pathlib import Path

from yt_dlp.utils import DownloadError


def thong_tin(vid: str, **them) -> dict:
    """Một `info` video lẻ tối thiểu, đủ cho bước liệt kê (id, tiêu đề, người đăng, thời lượng)."""
    return {"id": vid, "title": f"tieu de {vid}", "uploader": "ai do", "duration": 60, **them}


class YtdlpGia:
    def __init__(self, thong_tin_theo_url: dict | None = None, loi_theo_url: dict | None = None,
                 canh_bao_khi_tai: str | None = None, canh_bao_khi_liet_ke: str | None = None):
        # url -> info dict; url -> exception (hoặc list exception: mỗi lời gọi lấy một cái, hết thì chạy bình thường)
        self.thong_tin = thong_tin_theo_url or {}
        self.loi = loi_theo_url or {}
        # câu phát vào `opts["logger"].warning` trước khi trả về, theo loại lời gọi
        self.canh_bao = {"tai": canh_bao_khi_tai, "liet_ke": canh_bao_khi_liet_ke}
        self.opts_da_tao: list[dict] = []
        self.goi: list[tuple[str, str]] = []   # ("liet_ke" | "tai", url)

    def __call__(self, opts: dict):
        self.opts_da_tao.append(opts)
        return _Ydl(self, opts)

    def so_goi(self, loai: str | None = None) -> int:
        return sum(1 for l, _ in self.goi if loai in (None, l))


class _Ydl:
    def __init__(self, gia: YtdlpGia, opts: dict):
        self._gia, self._opts = gia, opts

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def extract_info(self, url: str, download: bool = True):
        gia = self._gia
        gia.goi.append(("tai" if download else "liet_ke", url))
        loi = gia.loi.get(url)
        if isinstance(loi, list):
            loi = loi.pop(0) if loi else None
        if loi is not None:
            raise loi
        canh_bao = gia.canh_bao["tai" if download else "liet_ke"]
        if canh_bao:
            self._opts["logger"].warning(canh_bao)
        info = gia.thong_tin[url]
        if download:
            dich = Path(self._opts["outtmpl"] % {"id": info["id"], "ext": "mp4"})
            dich.parent.mkdir(parents=True, exist_ok=True)
            dich.write_bytes(b"x")
        return info


def loi_tai(thong_diep: str) -> DownloadError:
    return DownloadError(thong_diep)
