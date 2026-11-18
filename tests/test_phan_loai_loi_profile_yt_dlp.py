"""R-09 #2 (agy R1b ĐK-R09-1..4): nhãn log tĩnh `loi=`, 3 tầng bóc lỗi yt-dlp, bất biến 0 mục hợp lệ ⇒ None,
thử lại 1 lần khi timeout ở trang đầu sau cờ `VIDEODL_PROFILE_YT_DLP_THU_LAI` (mặc định TẮT)."""
from __future__ import annotations

import io
import logging
import re
import sys

import pytest
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.utils import DownloadError, ExtractorError

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import nguon_profile_yt_dlp as prof_yt
from tiktok_music_downloader import phan_loai_loi_profile_yt_dlp as pl
from tiktok_music_downloader.nguon import TikTokCollection
from tiktok_music_downloader.utils import STOP_ALREADY_OWNED, VideoRef

URL = "https://www.tiktok.com/@lynherne"
MAU_LOG = re.compile(
    r"^profile yt-dlp: thu=(\d) keo=(\d+) hop_le=(\d+) moi=(\d+) da_co=(\d+) ket_thuc=(\w+) loi=(\w+)$")


def _id(n: int) -> str:
    return f"740000000000000{n:04d}"


def _muc(n: int) -> dict:
    return {"id": _id(n), "url": f"{URL}/video/{_id(n)}"}


def _http(status: int) -> HTTPError:
    return HTTPError(Response(io.BytesIO(b""), f"{URL}?x=1", {}, status=status))


def _boc_nhu_extract_info(loi_trong: BaseException) -> DownloadError:
    """Như `YoutubeDL.extract_info`: bọc ExtractorError vào `DownloadError(msg, exc_info)` (tầng i)."""
    try:
        raise loi_trong
    except BaseException:  # noqa: BLE001
        return DownloadError(f"ERROR: {loi_trong}", sys.exc_info())


def _ee(msg: str, cause: BaseException | None = None) -> ExtractorError:
    return ExtractorError(msg, cause=cause, expected=True)


class Gia:
    """`YoutubeDL` giả theo PHIÊN: mỗi `kich_ban[i]` điều khiển phiên thứ i (lượt `thu=i+1`).
    Kịch bản: dict(canh_bao=[...], loi_extract=exc, muc=[...], loi_o=idx, loi_next=exc)."""

    def __init__(self, *kich_ban: dict):
        self.kich_ban = list(kich_ban)
        self.opts: list[dict] = []

    def __call__(self, opts: dict):
        self.opts.append(opts)
        kb = self.kich_ban[len(self.opts) - 1]
        logger = opts["logger"]

        class _Phien:
            def __enter__(self_):
                return self_

            def __exit__(self_, *_a):
                return False

            def extract_info(self_, url, download=True, process=True):
                for cb in kb.get("canh_bao", []):
                    logger.warning(cb)
                if kb.get("loi_extract") is not None:
                    raise kb["loi_extract"]

                def _gen():
                    for i, m in enumerate(kb.get("muc", [])):
                        if kb.get("loi_o") == i:
                            raise kb["loi_next"]
                        yield m
                    if kb.get("loi_o") == len(kb.get("muc", [])):
                        raise kb["loi_next"]
                return {"_type": "playlist", "entries": _gen()}

        return _Phien()


@pytest.fixture(autouse=True)
def _moi_truong(monkeypatch):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP, "1")
    monkeypatch.delenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, raising=False)
    monkeypatch.setattr(prof_yt, "GIAY_NGHI_THU_LAI", 0)


def _chay(monkeypatch, caplog, gia: Gia, **kw):
    monkeypatch.setattr(prof_yt, "YoutubeDL", gia)
    caplog.set_level(logging.INFO, logger="ttmd")
    ra = prof_yt.liet_ke_profile_yt_dlp(URL, max_videos=kw.pop("max_videos", 5), **kw)
    dong = [r.getMessage() for r in caplog.records if r.getMessage().startswith("profile yt-dlp:")]
    return ra, dong


def _tach(dong: str) -> dict:
    m = MAU_LOG.match(dong)
    assert m, f"dòng log sai khuôn tĩnh: {dong!r}"
    thu, keo, hop_le, moi, da_co, ket_thuc, loi = m.groups()
    assert loi in pl.TAP_NHAN_LOI
    return dict(thu=int(thu), keo=int(keo), hop_le=int(hop_le), ket_thuc=ket_thuc, loi=loi)


# --- ĐK-R09-1: bất biến 0 mục hợp lệ ⇒ None (không bao giờ []) -------------------------------------------

def test_het_danh_sach_0_muc_tra_none_nhan_rong_item_list(monkeypatch, caplog):
    ra, dong = _chay(monkeypatch, caplog, Gia({"muc": []}))
    assert ra is None
    assert len(dong) == 1
    assert _tach(dong[0]) == dict(thu=1, keo=0, hop_le=0, ket_thuc="het_danh_sach", loi="rong_item_list")


def test_toan_id_rac_tra_none_khong_phai_mang_rong(monkeypatch, caplog):
    ra, dong = _chay(monkeypatch, caplog, Gia({"muc": [{"id": "abc"}, {"id": "x"}]}))
    assert ra is None
    assert _tach(dong[0])["loi"] == "rong_item_list"


def test_0_muc_hop_le_khong_dong_job_da_co_het_ma_roi_trinh_duyet(monkeypatch):
    monkeypatch.setattr(prof_yt, "YoutubeDL", Gia({"muc": []}))
    ref_browser = [VideoRef(video_id=_id(9), url=f"{URL}/video/{_id(9)}")]
    monkeypatch.setattr(nguon_mod, "scrape_music_page_multi", lambda url, **kw: ref_browser)
    dung: list[str] = []
    ra = TikTokCollection().liet_ke(
        URL, max_videos=5, proxy=None, cookies_path=None, passes=1, max_seconds=60.0,
        kw_profile={"profile_dir": None}, already_have=lambda ids: set(), on_skip=lambda r: None,
        on_stop=dung.append, on_pages=lambda n: None, dem_trang=lambda: None)
    assert ra == ref_browser
    assert STOP_ALREADY_OWNED not in dung


def test_moi_muc_da_co_van_tra_mang_rong(monkeypatch, caplog):
    # `[]` chỉ hợp lệ khi có mục hợp lệ nhưng đều đã có trong thư viện.
    ra, dong = _chay(monkeypatch, caplog, Gia({"muc": [_muc(1), _muc(2)]}),
                     already_have=lambda ids: set(ids))
    assert ra == []
    assert _tach(dong[0])["loi"] == "khong"


# --- ĐK-R09-2 (i): DownloadError.exc_info → ExtractorError.cause → HTTPError.status ----------------------

@pytest.mark.parametrize("status,nhan", [(403, "http_403"), (429, "http_429"), (500, "http_khac")])
def test_tang_i_boc_download_error_lay_ma_http(monkeypatch, caplog, status, nhan):
    loi = _boc_nhu_extract_info(_ee("Unable to download webpage", cause=_http(status)))
    ra, dong = _chay(monkeypatch, caplog, Gia({"loi_extract": loi}))
    assert ra is None
    assert _tach(dong[0]) == dict(thu=1, keo=0, hop_le=0, ket_thuc="loi_extract", loi=nhan)


def test_tang_i_timeout_qua_transport_error(monkeypatch, caplog):
    loi = _boc_nhu_extract_info(_ee("Unable to download webpage", cause=TransportError("read timed out")))
    _ra, dong = _chay(monkeypatch, caplog, Gia({"loi_extract": loi}))
    assert _tach(dong[0])["loi"] == "timeout"


@pytest.mark.parametrize("msg,nhan", [
    ("This user's account is private", "tk_rieng_tu"),
    ("This account does not have any videos posted", "tk_khong_video"),
    ("TikTok API keeps sending the same page", "lap_trang"),
    ("điều gì đó lạ", "khac"),
])
def test_tang_i_nhan_theo_thong_diep(monkeypatch, caplog, msg, nhan):
    _ra, dong = _chay(monkeypatch, caplog, Gia({"loi_extract": _boc_nhu_extract_info(_ee(msg))}))
    assert _tach(dong[0])["loi"] == nhan


# --- ĐK-R09-2 (ii): lỗi next(it) trang đầu ≠ loi_giua_chung ---------------------------------------------

def test_tang_ii_loi_next_khi_chua_co_muc_la_loi_trang_dau(monkeypatch, caplog):
    loi = _ee("Unable to download JSON", cause=_http(429))
    ra, dong = _chay(monkeypatch, caplog, Gia({"muc": [], "loi_o": 0, "loi_next": loi}))
    assert ra is None
    assert _tach(dong[0]) == dict(thu=1, keo=0, hop_le=0, ket_thuc="loi_trang_dau", loi="http_429")


def test_tang_ii_loi_next_sau_khi_co_muc_la_loi_giua_chung_giu_muc(monkeypatch, caplog):
    loi = _ee("Unable to download JSON", cause=_http(403))
    ra, dong = _chay(monkeypatch, caplog,
                     Gia({"muc": [_muc(1), _muc(2), _muc(3)], "loi_o": 3, "loi_next": loi}))
    assert [r.video_id for r in ra] == [_id(1), _id(2), _id(3)]
    assert _tach(dong[0]) == dict(thu=1, keo=3, hop_le=3, ket_thuc="loi_giua_chung", loi="http_403")


# --- ĐK-R09-2 (iii): warning fatal=False + "Unable to extract secondary user ID" (cause=None) -------------

@pytest.mark.parametrize("canh_bao,nhan", [
    (["[tiktok:user] 77: Unable to download webpage: HTTP Error 403: Forbidden"], "http_403"),
    (["[tiktok:user] 77: Unable to download webpage: HTTP Error 429: Too Many Requests"], "http_429"),
    (["[tiktok:user] 77: Unable to download webpage: Failed to perform; curl: (28) Connection timed out"],
     "timeout"),
    ([], "khong_secuid"),
    # 429 thắng timeout thắng 403 khi lẫn nhiều cảnh báo.
    (["HTTP Error 403: Forbidden", "Read timed out", "HTTP Error 429"], "http_429"),
    (["HTTP Error 403: Forbidden", "Read timed out"], "timeout"),
])
def test_tang_iii_mat_secuid_phan_loai_theo_canh_bao(monkeypatch, caplog, canh_bao, nhan):
    loi = _boc_nhu_extract_info(_ee("Unable to extract secondary user ID"))
    _ra, dong = _chay(monkeypatch, caplog, Gia({"canh_bao": canh_bao, "loi_extract": loi}))
    assert _tach(dong[0])["loi"] == nhan


def test_tang_iii_canh_bao_trung_gian_bo_qua_khi_co_muc(monkeypatch, caplog):
    ra, dong = _chay(monkeypatch, caplog,
                     Gia({"canh_bao": ["HTTP Error 403: Forbidden"], "muc": [_muc(1)]}))
    assert len(ra) == 1
    assert _tach(dong[0])["loi"] == "khong"


def test_tang_iii_co_khong_ro_giua_cac_luot(monkeypatch, caplog):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, "1")
    secuid = lambda: _boc_nhu_extract_info(_ee("Unable to extract secondary user ID"))  # noqa: E731
    _ra, dong = _chay(monkeypatch, caplog, Gia(
        {"canh_bao": ["Read timed out"], "loi_extract": secuid()},
        {"loi_extract": secuid()}))
    assert [_tach(d)["loi"] for d in dong] == ["timeout", "khong_secuid"]


# --- ĐK-R09-3: log tĩnh, 0 URL/handle ------------------------------------------------------------------

def test_log_khong_chua_url_hay_handle(monkeypatch, caplog):
    loi = _boc_nhu_extract_info(_ee(f"Unable to download webpage {URL}", cause=_http(403)))
    _ra, dong = _chay(monkeypatch, caplog, Gia({"canh_bao": [f"HTTP Error 403 {URL}"], "loi_extract": loi}))
    assert len(dong) == 1
    assert "lynherne" not in dong[0] and "http" not in dong[0].split("loi=")[0]
    _tach(dong[0])


# --- ĐK-R09-4: thử lại 1 lần, cờ mặc định TẮT, socket_timeout ------------------------------------------

def _timeout_extract():
    return _boc_nhu_extract_info(_ee("Unable to download webpage", cause=TransportError("timed out")))


def test_co_tat_mac_dinh_khong_thu_lai(monkeypatch, caplog):
    gia = Gia({"loi_extract": _timeout_extract()}, {"muc": [_muc(1)]})
    ra, dong = _chay(monkeypatch, caplog, gia)
    assert ra is None
    assert len(gia.opts) == 1 and len(dong) == 1


def test_co_bat_timeout_trang_dau_thu_lai_dung_1_lan(monkeypatch, caplog):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, "1")
    gia = Gia({"muc": [], "loi_o": 0, "loi_next": _ee("x", cause=TransportError("timed out"))},
              {"muc": [_muc(1), _muc(2)]})
    ra, dong = _chay(monkeypatch, caplog, gia)
    assert [r.video_id for r in ra] == [_id(1), _id(2)]
    assert len(gia.opts) == 2
    assert [(_tach(d)["thu"], _tach(d)["loi"]) for d in dong] == [(1, "timeout"), (2, "khong")]


def test_co_bat_lan_2_van_timeout_khong_thu_lan_3(monkeypatch, caplog):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, "1")
    gia = Gia({"loi_extract": _timeout_extract()}, {"loi_extract": _timeout_extract()},
              {"muc": [_muc(1)]})
    ra, dong = _chay(monkeypatch, caplog, gia)
    assert ra is None
    assert len(gia.opts) == 2 and len(dong) == 2


def test_co_bat_khong_thu_lai_khi_da_keo_hoac_loi_khac(monkeypatch, caplog):
    monkeypatch.setenv(prof_yt.ENV_PROFILE_YT_DLP_THU_LAI, "1")
    # Đã kéo mục (id rác) rồi mới timeout ⇒ keo>0 ⇒ không thử lại (tránh đếm đúp dem_trang).
    gia = Gia({"muc": [{"id": "rac"}], "loi_o": 1, "loi_next": _ee("x", cause=TransportError("timed out"))},
              {"muc": [_muc(1)]})
    ra, _d = _chay(monkeypatch, caplog, gia)
    assert ra is None and len(gia.opts) == 1
    # 403 ⇒ không thử lại.
    gia2 = Gia({"loi_extract": _boc_nhu_extract_info(_ee("x", cause=_http(403)))}, {"muc": [_muc(1)]})
    ra2, _d2 = _chay(monkeypatch, caplog, gia2)
    assert ra2 is None and len(gia2.opts) == 1


def test_opts_co_socket_timeout(monkeypatch, caplog):
    gia = Gia({"muc": [_muc(1)]})
    _chay(monkeypatch, caplog, gia)
    assert gia.opts[0]["socket_timeout"] == prof_yt.SOCKET_TIMEOUT
    assert isinstance(gia.opts[0]["logger"], pl.LogBatCo)
