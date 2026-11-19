"""Phanh vòng trang rỗng `hasMorePrevious` (agy R1b vd-r09-vong-530, ĐK-V530-1..3).

`YoutubeDL` giả phát dòng `[tiktok:user] <id>: Downloading page N` qua `logger.debug` TRƯỚC mỗi trang (như
`_request_webpage` thật) rồi yield mục của trang đó; đếm số trang đã "tải" (dòng debug trả về bình thường)."""
from __future__ import annotations

import inspect
import logging
import re

import pytest
from yt_dlp.extractor.tiktok import TikTokUserIE

from tiktok_music_downloader import nguon_profile_yt_dlp as prof_yt
from tiktok_music_downloader import phan_loai_loi_profile_yt_dlp as pl

URL = "https://www.tiktok.com/@lynherne"
K = pl.SO_TRANG_RONG_LIEN_TIEP_TOI_DA
TRAN = pl.TRAN_TRANG_MOI_LUOT
MAU_LOG = re.compile(r"ket_thuc=(\w+) loi=(\w+)$")


def _id(n: int) -> str:
    return f"740000000000000{n:04d}"


def _muc(n: int) -> dict:
    return {"id": _id(n), "url": f"{URL}/video/{_id(n)}"}


class GiaTrang:
    """`YoutubeDL` giả: `trang[i]` = danh sách mục của trang i+1; đếm `so_trang_da_tai`."""

    def __init__(self, trang: list[list[dict]]):
        self.trang = trang
        self.so_trang_da_tai = 0
        self.so_phien = 0

    def __call__(self, opts: dict):
        self.so_phien += 1
        logger = opts["logger"]
        goc = self

        class _Phien:
            def __enter__(self_):
                return self_

            def __exit__(self_, *_a):
                return False

            def extract_info(self_, url, download=True, process=True):
                # Dòng to_screen KHÁC của TikTokUserIE không được đếm là trang.
                logger.debug("[tiktok:user] lynherne: Downloading user embed page")
                logger.debug("[tiktok:user] Downloading page 1 (sai khuôn, thiếu id)")

                def _gen():
                    for so, muc_trang in enumerate(goc.trang, start=1):
                        logger.debug(f"[tiktok:user] lynherne: Downloading page {so}")
                        goc.so_trang_da_tai += 1
                        yield from muc_trang
                return {"_type": "playlist", "entries": _gen()}

        return _Phien()


@pytest.fixture(autouse=True)
def _moi_truong(monkeypatch):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP, "1")
    monkeypatch.delenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, raising=False)


def _chay(monkeypatch, caplog, gia: GiaTrang, max_videos: int = 5, already_have=None):
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)
    caplog.set_level(logging.INFO, logger="ttmd")
    ra = prof_yt.liet_ke_profile_yt_dlp(URL, max_videos=max_videos, already_have=already_have)
    dong = [r.getMessage() for r in caplog.records if r.getMessage().startswith("profile yt-dlp:")]
    assert len(dong) == 1
    return ra, MAU_LOG.search(dong[0]).groups()


# --- ĐK-V530-2 (i): canh nguồn yt-dlp đang cài -------------------------------------------------------------

def test_canh_nguon_yt_dlp_con_phat_dong_downloading_page():
    # Nâng yt-dlp mà `_entries` đổi chữ ⇒ phanh mất âm thầm ⇒ test này phải đỏ trước khi lên prod.
    nguon = inspect.getsource(TikTokUserIE._entries)
    assert "f'Downloading page {page}'" in nguon or 'f"Downloading page {page}"' in nguon
    assert TikTokUserIE.IE_NAME == "tiktok:user"
    # Khuôn thật: `InfoExtractor.to_screen` thêm `[IE_NAME] ` + `report_download_webpage` thêm `<video_id>: `.
    assert pl.MAU_LOG_TRANG.match(f"[{TikTokUserIE.IE_NAME}] lynherne: Downloading page 1")
    assert pl.MAU_LOG_TRANG.match(f"[{TikTokUserIE.IE_NAME}] MS4wLjABAAAA_x-y: Downloading page 532")
    assert not pl.MAU_LOG_TRANG.match("[tiktok:user] lynherne: Downloading user embed page")
    assert not pl.MAU_LOG_TRANG.match("[tiktok] 7400: Downloading page 1")


# --- ĐK-V530-1/2 (ii): 533 trang rỗng, biên off-by-one ----------------------------------------------------

def test_533_trang_rong_dung_sau_K_trang_tra_none(monkeypatch, caplog):
    gia = GiaTrang([[] for _ in range(533)])
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia)
    assert ra is None
    assert gia.so_trang_da_tai == K
    assert (ket_thuc, loi) == ("loi_trang_dau", "rong_item_list")
    assert gia.so_phien == 1  # rong_item_list không kích thử lại


def test_K_trang_rong_roi_het_danh_sach_khong_bi_phanh(monkeypatch, caplog):
    # Đúng K trang rỗng rồi generator tự hết ⇒ không phát dòng trang K+1 ⇒ không phanh.
    gia = GiaTrang([[] for _ in range(K)])
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia)
    assert ra is None
    assert gia.so_trang_da_tai == K
    assert (ket_thuc, loi) == ("het_danh_sach", "rong_item_list")


def test_K_tru_1_trang_rong_roi_trang_K_co_muc_khong_bi_cat(monkeypatch, caplog):
    trang = [[] for _ in range(K - 1)] + [[_muc(1)]] + [[] for _ in range(K - 1)]
    gia = GiaTrang(trang)
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia)
    assert [r.video_id for r in ra] == [_id(1)]
    assert gia.so_trang_da_tai == len(trang)
    assert (ket_thuc, loi) == ("het_danh_sach", "khong")


def test_co_muc_trang_1_roi_533_trang_rong_dung_giu_muc_nhan_giua_chung(monkeypatch, caplog):
    gia = GiaTrang([[_muc(1), _muc(2)]] + [[] for _ in range(532)])
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia, max_videos=30)
    assert [r.video_id for r in ra] == [_id(1), _id(2)]
    assert gia.so_trang_da_tai == 1 + K
    assert (ket_thuc, loi) == ("loi_giua_chung", "rong_item_list")


def test_muc_da_co_van_tinh_la_trang_khong_rong(monkeypatch, caplog):
    # Mục hợp lệ nhưng đã có trong thư viện vẫn chứng tỏ API đang trả dữ liệu thật.
    trang = [[_muc(n)] for n in range(1, 2 * K + 1)]
    gia = GiaTrang(trang)
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia, already_have=lambda ids: set(ids))
    assert ra == []
    assert gia.so_trang_da_tai == len(trang)
    assert (ket_thuc, loi) == ("het_danh_sach", "khong")


# --- ĐK-V530-3: trần cứng trang/lượt ---------------------------------------------------------------------

def test_tran_trang_khi_van_co_muc_la_tran_keo_khong(monkeypatch, caplog):
    # Mỗi trang 1 mục đã có ⇒ không bao giờ rỗng, chưa chạm tran_keo (300) ⇒ trần trang cắt ở đầu trang TRAN+1.
    gia = GiaTrang([[_muc(n)] for n in range(1, 100)])
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia, already_have=lambda ids: set(ids))
    assert ra == []
    assert gia.so_trang_da_tai == TRAN
    assert (ket_thuc, loi) == ("tran_keo", "khong")


def test_tran_trang_khi_0_hop_le_la_rong_item_list(monkeypatch, caplog):
    # Hạ K tạm để trần trang (đặt nhỏ) nổ trước phanh rỗng ⇒ 0 hợp lệ ⇒ loi_trang_dau rong_item_list.
    monkeypatch.setattr(pl, "SO_TRANG_RONG_LIEN_TIEP_TOI_DA", 1000)
    monkeypatch.setattr(pl, "TRAN_TRANG_MOI_LUOT", 5)
    gia = GiaTrang([[] for _ in range(50)])
    ra, (ket_thuc, loi) = _chay(monkeypatch, caplog, gia)
    assert ra is None
    assert gia.so_trang_da_tai == 5
    assert (ket_thuc, loi) == ("loi_trang_dau", "rong_item_list")

