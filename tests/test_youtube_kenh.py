"""Nguồn `YoutubeKenh`: kênh / tab Videos-Shorts / playlist YouTube, liệt kê N video MỚI bằng MỘT lời gọi
`extract_info(process=False)` rồi tự duyệt `entries`.

Mục phẳng dựng bằng chính `InfoExtractor.url_result` / `playlist_result` của yt-dlp, cùng tham số mà trình trích tab
của yt-dlp truyền (nhánh `lockupViewModel` của tab Videos, `shortsLockupViewModel` của tab Shorts, playlist lồng) —
không tự dựng dict. Ranh giới `YoutubeDL` là bản giả (`tests/yt_dlp_gia.py`) nhưng `entries` là generator LƯỜI thật,
đếm số mục đã bị kéo và kiểm phiên yt-dlp còn mở lúc kéo; mọi thứ phía trên (nhận dạng, pacer, `process_job`,
`download_all`, DB) chạy thật. Không mạng.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.youtube import YoutubeIE, YoutubeTabIE

from link_le_khung import Khung
from yt_dlp_gia import YtdlpGia, loi_tai, thong_tin

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.nguon import LinkLe, YoutubeKenh, chon_nguon
from web import app as app_mod
from web import models, pacer
from web import queue as queue_mod

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
GOC_NODE = ("const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
            "function lay(a,b){const i=src.indexOf(a);const j=src.indexOf(b,i);return src.slice(i,j);}")
KENH = "https://www.youtube.com/@kenh.rieng.tu"
KENH_VIDEOS = KENH + "/videos"
KENH_SHORTS = KENH + "/shorts"
PLAYLIST = "https://www.youtube.com/playlist?list=PLaaaaaaaaaaaaaaaaaaaa"
PHUT = 60
BOT = "ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies-from-browser"


def _vid(i: int) -> str:
    return f"{i:011d}"


def _yt(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def _sh(vid: str) -> str:
    return f"https://www.youtube.com/shorts/{vid}"


# ---------------------------------------------------------------- mục phẳng theo đúng khuôn trình trích tab

def muc_video(vid: str, duration=None, **them) -> dict:
    """Mục tab Videos (`_extract_lockup_view_model`, nhánh video): `duration` đọc từ chữ huy hiệu thumbnail, có thể None."""
    return InfoExtractor.url_result(
        _yt(vid), YoutubeIE, vid, title=f"tieu de {vid}", thumbnails=[], duration=duration, view_count=10,
        timestamp=None, live_status=them.pop("live_status", None), availability=them.pop("availability", "public"),
        channel_url="https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx", uploader_url=KENH,
        creators=None, channel="Kenh", channel_id="UCxxxxxxxxxxxxxxxxxxxxxx", uploader="Kenh", uploader_id="@kenh",
        **them)


def muc_short(vid: str) -> dict:
    """Mục tab Shorts (`_rich_entries`, nhánh `shortsLockupViewModel`): KHÔNG có khoá `duration`."""
    return InfoExtractor.url_result(
        _sh(vid), ie=YoutubeIE, video_id=vid, title=f"short {vid}", view_count=7, thumbnails=[])


def muc_playlist(pid: str) -> dict:
    """Playlist lồng trong tab (nhánh `LOCKUP_CONTENT_TYPE_PLAYLIST`): KHÔNG phải video."""
    return InfoExtractor.url_result(
        f"https://www.youtube.com/playlist?list={pid}", YoutubeTabIE, pid, title="mot playlist", thumbnails=[])


class DanhSach:
    """Nguồn `entries` lười: một generator MỚI mỗi lần `extract_info`, đếm số mục đã bị kéo (`keo`), và ghi lại nếu
    có mục bị đọc sau khi phiên `with YoutubeDL(...)` đã đóng (`doc_ngoai_phien`)."""

    def __init__(self, gia: YtdlpGia, muc: list, loi_o: int | None = None, loi: Exception | None = None):
        self.gia, self.muc, self.loi_o, self.loi = gia, muc, loi_o, loi
        self.keo = 0
        self.doc_ngoai_phien = False

    def __call__(self) -> dict:
        def sinh():
            for i, m in enumerate(self.muc):
                if self.gia.so_phien_mo <= 0:
                    self.doc_ngoai_phien = True
                if self.loi_o == i:
                    raise self.loi
                self.keo += 1
                yield m
        return InfoExtractor.playlist_result(sinh(), "UCxxxxxxxxxxxxxxxxxxxxxx", "kenh")


def gia_kenh(url: str, muc: list, *, info: dict | None = None, loi: dict | None = None, **kw):
    """`(gia, danh_sach)`: `url` mở ra playlist `muc`; `info` là thông tin theo URL mục cho lượt tải/đường lui."""
    gia = YtdlpGia(info or {}, loi, **kw)
    ds = DanhSach(gia, muc)
    gia.ie_tho[url] = ds
    return gia, ds


def chay_liet_ke(k: Khung, url: str, n: int, da_co=()):
    """Gọi `YoutubeKenh.liet_ke` trực tiếp với cổng pacer thật. Trả `(refs, mã_lỗi, lý_do_dừng, bỏ_qua)`."""
    dung, bo, loi = [], [], []
    cong = pacer.CongNenTang(k.db, k.tao_job([url]), "youtube")
    refs = YoutubeKenh().liet_ke(
        url, max_videos=n, already_have=lambda ids: {i for i in ids if i in da_co},
        on_skip=bo.append, on_stop=dung.append, cong=cong,
        ghi_loi_video=lambda ma, ct: loi.append(ma), nghi=k._nghi)
    return refs, loi, dung, bo


# ================================================================== 1. nhận dạng

KENH_NHAN = [
    KENH, KENH_VIDEOS, KENH_SHORTS, KENH_SHORTS + "/", KENH_VIDEOS + "?view=0&sort=dd",
    "https://youtube.com/@kenh.rieng.tu/shorts", "https://m.youtube.com/@kenh.rieng.tu",
    "https://www.youtube.com/@%E3%82%AB%E3%83%A1%E3%83%A9/videos",
    "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
    "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx/videos",
    "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx/shorts",
    PLAYLIST, "https://www.youtube.com/playlist?list=PLaaaaaaaaaaaaaaaaaaaa&si=xyz",
]
KENH_KHONG_NHAN = [
    KENH + "/live", KENH + "/streams", KENH + "/community", KENH + "/playlists", KENH + "/search?query=abc",
    "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx/streams",
    "https://www.youtube.com/playlist",                              # không có list=
    "https://www.youtube.com/playlist?list=",
    "https://www.youtube.com/results?search_query=abc",              # tìm kiếm
    "https://www.youtube.com/watch?v=aAa1aAa1aAa",                   # video lẻ
    "https://www.youtube.com/shorts/aAa1aAa1aAa",
    "https://youtu.be/aAa1aAa1aAa",
    "https://example.com/@kenh/videos",
    "https://www.tiktok.com/@nguoi.dung",                            # profile TikTok: không phải của nguồn này
    "khong-phai-url",
    "@kenh.rieng.tu",
]


@pytest.fixture
def khong_mang(monkeypatch):
    def _cam(*a, **kw):
        raise AssertionError("nhận dạng không được chạm mạng")
    monkeypatch.setattr(socket.socket, "connect", _cam)
    monkeypatch.setattr(socket, "getaddrinfo", _cam)


@pytest.mark.parametrize("url", KENH_NHAN)
def test_kenh_tab_va_playlist_duoc_nhan_boi_nguon_kenh_khong_phai_link_le(khong_mang, url):
    n = chon_nguon(url)
    assert isinstance(n, YoutubeKenh) and not isinstance(n, LinkLe)
    assert LinkLe().phan_loai(url) is None                          # LinkLe không bao giờ nhận kênh
    assert n.nen_tang(url) == "youtube" and n.loai_log(url) == "youtube:kenh"
    assert url not in n.loai_log(url) and "rieng.tu" not in n.loai_log(url)


@pytest.mark.parametrize("url", KENH_KHONG_NHAN)
def test_tab_live_community_tim_kiem_video_le_khong_phai_kenh(khong_mang, url):
    assert not YoutubeKenh().nhan(url)
    assert not isinstance(chon_nguon(url), YoutubeKenh)


def test_nhan_dang_khong_goi_yt_dlp(monkeypatch):
    gia = YtdlpGia()
    monkeypatch.setattr(nguon_mod, "YoutubeDL", gia)
    for url in KENH_NHAN + KENH_KHONG_NHAN:
        YoutubeKenh().nhan(url)
        chon_nguon(url)
    assert gia.opts_da_tao == [] and gia.goi == []


# ================================================================== 2. lượt pacer của liệt kê

def test_liet_ke_45_muc_ghi_dung_3_luot_va_keo_het_45_muc(monkeypatch, tmp_path):
    muc = [muc_video(_vid(i), duration=30) for i in range(45)]
    gia, ds = gia_kenh(KENH_VIDEOS, muc)
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 100)
    assert len(refs) == 45 and loi == [] and dung == [] and ds.keo == 45
    assert k.so_luot("youtube") == 3          # lời gọi đầu (mục 0-19), trước mục 20, trước mục 40
    assert gia.so_goi("liet_ke_tho") == 1     # MỘT lời gọi extract_info, không cắt lát
    assert k.nghi_giua_luot == 2              # nghỉ jitter giữa hai lượt liên tiếp
    assert not ds.doc_ngoai_phien, "generator lười phải được duyệt trong phiên yt-dlp còn mở"


@pytest.mark.parametrize("n, luot", [(5, 1), (20, 1), (21, 2), (40, 2), (41, 3)])
def test_dung_keo_ngay_khi_du_n_moi_va_ghi_luot_truoc_khi_keo_20_muc_tiep(monkeypatch, tmp_path, n, luot):
    gia, ds = gia_kenh(KENH_VIDEOS, [muc_video(_vid(i), duration=30) for i in range(100)])
    k = Khung(monkeypatch, tmp_path, gia)
    refs, _, dung, _ = chay_liet_ke(k, KENH_VIDEOS, n)
    assert len(refs) == n and dung == []
    assert ds.keo == n, "không được kéo dư mục nào sau khi đủ N video mới"
    assert k.so_luot("youtube") == luot


def test_gap_tran_gio_giua_chung_thi_dung_keo_va_tra_ly_do(monkeypatch, tmp_path):
    gia, ds = gia_kenh(KENH_VIDEOS, [muc_video(_vid(i), duration=30) for i in range(100)])
    k = Khung(monkeypatch, tmp_path, gia)
    monkeypatch.setitem(pacer.TRAN, "youtube", (2, 300))             # chỉ 2 lượt/giờ
    refs, _, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 100)
    assert len(refs) == 40 and ds.keo == 40 and dung == ["tran_gio"]
    assert k.so_luot("youtube") == 2 and gia.so_goi("liet_ke_tho") == 1


# ================================================================== 3. phân giải URL (tối đa 3 lời gọi)

def _url_buoc(den: str, loai: str = "url") -> dict:
    return InfoExtractor.url_result(den, YoutubeTabIE, None, url_transparent=(loai == "url_transparent"))


@pytest.mark.parametrize("so_buoc_url", [1, 2])
def test_mot_hai_buoc_url_van_ra_playlist_moi_buoc_mot_luot(monkeypatch, tmp_path, so_buoc_url):
    muc = [muc_video(_vid(i), duration=30) for i in range(3)]
    gia = YtdlpGia()
    # Bước nối giữa các trang TAB (playlist ⇒ playlist khác). Kênh trần không còn là ca này: nó bị ép sang `/videos`
    # TRƯỚC lời gọi (xem test ép `/videos` bên dưới).
    p2, p3 = PLAYLIST.replace("PLa", "PLb"), PLAYLIST.replace("PLa", "PLc")
    chuoi = [PLAYLIST, p2, p3][:so_buoc_url + 1]
    for truoc, sau in zip(chuoi, chuoi[1:]):
        gia.ie_tho[truoc] = _url_buoc(sau, "url_transparent" if truoc == PLAYLIST else "url")
    ds = DanhSach(gia, muc)
    gia.ie_tho[chuoi[-1]] = ds
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, PLAYLIST, 10)
    assert len(refs) == 3 and loi == []
    assert [u for _, u in gia.goi] == chuoi
    assert k.so_luot("youtube") == so_buoc_url + 1                    # mỗi lời gọi một lượt, ghi TRƯỚC


def test_ba_lan_deu_tra_url_thi_dung_o_3_loi_goi_khong_co_loi_goi_thu_4(monkeypatch, tmp_path):
    muc = [muc_video(_vid(i), duration=30) for i in range(3)]
    u = [KENH_VIDEOS, KENH + "/a", KENH + "/b", KENH + "/c"]
    gia = YtdlpGia()
    for truoc, sau in zip(u, u[1:]):
        gia.ie_tho[truoc] = _url_buoc(sau)
    gia.ie_tho[u[3]] = DanhSach(gia, muc)         # nếu lời gọi thứ 4 xảy ra, nó sẽ THÀNH CÔNG và test này đỏ
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 10)
    assert [x for _, x in gia.goi] == u[:3], "đúng 3 lời gọi, lời gọi thứ 4 không bao giờ xảy ra"
    assert k.so_luot("youtube") == 3
    assert refs == [] and loi == ["khong_doc_duoc"] and dung == ["source_empty"]


@pytest.mark.parametrize("ket_qua", [
    {"_type": "video", "id": "aAa1aAa1aAa"},                  # không phải playlist
    {"_type": "playlist", "entries": None},                   # playlist không có entries
    {"_type": "url", "url": "javascript:alert(1)"},           # URL đích hỏng
    None,
])
def test_ket_qua_cuoi_khong_phai_playlist_co_entries_thi_tu_choi(monkeypatch, tmp_path, ket_qua):
    gia = YtdlpGia(ie_tho_theo_url={KENH_VIDEOS: ket_qua})
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 10)
    assert refs == [] and loi == ["khong_doc_duoc"] and dung == ["source_empty"]


def test_canh_bao_thieu_js_runtime_la_loi_cua_link_khong_ra_video(monkeypatch, tmp_path):
    gia, _ = gia_kenh(KENH_VIDEOS, [muc_video(_vid(0), duration=30)],
                      canh_bao_khi_liet_ke="No supported JavaScript runtime could be found")
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 10)
    assert refs == [] and loi == ["thieu_js"] and dung == ["source_empty"]


# ================================================================== 4. lọc trùng trước mọi lượt tải

def _gia_kenh_ba_video():
    vs = [_vid(i) for i in (1, 2, 3)]
    muc = [muc_video(vs[0], duration=None), muc_video(vs[1], duration=30), muc_video(vs[2], duration=None)]
    info = {_yt(v): thong_tin(v) for v in vs}
    return vs, *gia_kenh(KENH_VIDEOS, muc, info=info)


def test_chay_lai_cung_kenh_khong_co_video_moi_va_khong_ton_luot_tai_hay_duong_lui(monkeypatch, tmp_path):
    vs, gia, ds = _gia_kenh_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    job1 = k.chay(k.tao_job([KENH_VIDEOS], so_luong=10))
    assert job1["xong"] == 3 and job1["trang_thai"] == "done"
    gia.goi.clear()
    luot_truoc = k.so_luot("youtube")
    job2 = k.chay(k.tao_job([KENH_VIDEOS], so_luong=10))
    assert job2["ly_do_dung"] == "already_owned" and job2["bo_qua"] == 3 and job2["xong"] == 0
    assert [l for l, _ in gia.goi] == ["liet_ke_tho"], "id đã có không được tốn lời gọi tải hay đường lui duration"
    assert k.so_luot("youtube") - luot_truoc == 1


def test_dao_sau_qua_cac_muc_da_co_toi_khi_du_n_moi(monkeypatch, tmp_path):
    vs = [_vid(i) for i in range(6)]
    gia, ds = gia_kenh(KENH_VIDEOS, [muc_video(v, duration=30) for v in vs],
                       info={_yt(v): thong_tin(v) for v in vs})
    k = Khung(monkeypatch, tmp_path, gia)
    da_co = {f"yt-{vs[0]}", f"yt-{vs[1]}", f"yt-{vs[3]}"}
    refs, loi, dung, bo = chay_liet_ke(k, KENH_VIDEOS, 2, da_co=da_co)
    assert [r.video_id for r in refs] == [f"yt-{vs[2]}", f"yt-{vs[4]}"]
    assert [r.video_id for r in bo] == [f"yt-{vs[0]}", f"yt-{vs[1]}", f"yt-{vs[3]}"]
    assert ds.keo == 5 and dung == [] and loi == []


def test_muc_da_co_khong_thieu_duration_van_khong_goi_duong_lui(monkeypatch, tmp_path):
    vs, gia, ds = _gia_kenh_ba_video()
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, bo = chay_liet_ke(k, KENH_VIDEOS, 10, da_co={f"yt-{vs[0]}", f"yt-{vs[2]}"})
    assert [r.video_id for r in refs] == [f"yt-{vs[1]}"] and len(bo) == 2
    assert gia.so_goi("liet_ke") == 0, "mục đã có (thiếu duration) không được tốn lời gọi đường lui"


def test_muc_khong_phai_video_va_dang_phat_truc_tiep_bi_bo_khong_tinh_la_moi(monkeypatch, tmp_path):
    vs = [_vid(i) for i in range(2)]
    muc = [muc_playlist("PLbbbbbbbbbbbbbbbbbbbb"), muc_video(_vid(9), live_status="is_live", duration=None),
           muc_video(_vid(8), live_status="is_upcoming", duration=None), muc_video(vs[0], duration=30),
           muc_video(vs[0], duration=30), muc_video(vs[1], duration=30)]
    gia, ds = gia_kenh(KENH_VIDEOS, muc)
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, bo = chay_liet_ke(k, KENH_VIDEOS, 2)
    assert [r.video_id for r in refs] == [f"yt-{vs[0]}", f"yt-{vs[1]}"] and loi == [] and bo == []
    assert gia.so_goi("liet_ke") == 0


# ================================================================== 5. trần 15 phút ở tab Videos / playlist

def test_tab_videos_qua_15_phut_la_qua_dai_khong_tai_va_thieu_duration_thi_do_rieng_tung_muc(monkeypatch, tmp_path):
    v = [_vid(i) for i in range(1, 6)]
    muc = [muc_video(v[0], duration=20 * PHUT),            # đủ thông tin: quá dài
           muc_video(v[1], duration=None),                 # đường lui: 1 phút ⇒ tải
           muc_video(v[2], duration=None),                 # đường lui: 25 phút ⇒ qua_dai
           muc_video(v[3], duration=None),                 # đường lui: 600MB ⇒ qua_nang
           muc_video(v[4], duration=30)]                   # tải thẳng
    info = {_yt(v[0]): thong_tin(v[0], duration=20 * PHUT), _yt(v[1]): thong_tin(v[1], duration=PHUT),
            _yt(v[2]): thong_tin(v[2], duration=25 * PHUT),
            _yt(v[3]): thong_tin(v[3], filesize_approx=600 * 1024 * 1024), _yt(v[4]): thong_tin(v[4])}
    gia, ds = gia_kenh(KENH_VIDEOS, muc, info=info)
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([KENH_VIDEOS], so_luong=10))
    assert [u for l, u in gia.goi if l == "liet_ke"] == [_yt(v[1]), _yt(v[2]), _yt(v[3])], \
        "đúng MỘT đường lui cho mỗi mục thiếu duration, không hơn"
    assert sorted(u for l, u in gia.goi if l == "tai") == sorted([_yt(v[1]), _yt(v[4])])
    assert job["xong"] == 2 and job["loi"] == 3 and job["loi_tiktok"] == 3
    assert k.so_luot("youtube") == 1 + 3 + 2                          # liệt kê + đường lui + tải


def test_duong_lui_ghi_dung_ma_loi_tung_video(monkeypatch, tmp_path):
    v = [_vid(i) for i in range(1, 4)]
    muc = [muc_video(v[0], duration=16 * PHUT), muc_video(v[1], duration=None), muc_video(v[2], duration=None)]
    info = {_yt(v[1]): thong_tin(v[1], duration=40 * PHUT), _yt(v[2]): thong_tin(v[2], filesize_approx=2 * 1024 ** 3)}
    gia, _ = gia_kenh(KENH_VIDEOS, muc, info=info)
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 10)
    assert refs == [] and loi == ["qua_dai", "qua_dai", "qua_nang"] and dung == ["source_empty"]


def test_tab_videos_khong_danh_dau_short_va_playlist_thieu_duration_van_co_duong_lui(monkeypatch, tmp_path):
    v = _vid(1)
    gia, _ = gia_kenh(PLAYLIST, [muc_video(v, duration=None)], info={_yt(v): thong_tin(v, duration=90)})
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, _, _ = chay_liet_ke(k, PLAYLIST, 5)
    assert [(r.video_id, r.duration, r.la_short) for r in refs] == [(f"yt-{v}", 90, False)]
    assert gia.so_goi("liet_ke") == 1


# ================================================================== 6. Short: trần kiểm SAU tải, TRƯỚC Drive

def _chay_voi_hook(k: Khung, jid: int):
    da_len: list[str] = []

    def hook(*, job_id, ref, path, db_path=None):
        da_len.append(ref.video_id)
        return k.hook_drive(job_id=job_id, ref=ref, path=path, db_path=db_path)

    k.process_job = lambda job: queue_mod.process_job(k.db, k.downloads, k.cookies, job, lifecycle_hook=hook)
    return k.chay(jid), da_len


def test_tab_shorts_danh_dau_short_khong_goi_duong_lui_va_khong_tinh_duration(monkeypatch, tmp_path):
    v = [_vid(i) for i in range(3)]
    gia, _ = gia_kenh(KENH_SHORTS, [muc_short(x) for x in v])
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, _, _ = chay_liet_ke(k, KENH_SHORTS, 10)
    assert [(r.video_id, r.url, r.duration, r.la_short) for r in refs] == [
        (f"yt-{x}", _sh(x), None, True) for x in v]
    assert gia.so_goi("liet_ke") == 0 and k.so_luot("youtube") == 1 and loi == []


@pytest.mark.parametrize("duration_info, do_duoc, len_len", [
    (20 * PHUT, "khong-duoc-goi", False),    # info nói quá dài ⇒ xoá, không lên Drive
    (45, "khong-duoc-goi", True),            # info nói 45 giây ⇒ lên Drive, không cần đo
    (None, None, False),                     # info thiếu, đo không ra ⇒ COI LÀ VƯỢT TRẦN
    (None, 20 * PHUT, False),                # info thiếu, đo ra 20 phút ⇒ vượt
    (None, 30, True),                        # info thiếu, đo ra 30 giây ⇒ lên Drive
    (15 * PHUT + 1, "khong-duoc-goi", False),
    (15 * PHUT, "khong-duoc-goi", True),     # đúng trần thì được
])
def test_short_kiem_tran_sau_tai_truoc_khi_len_drive(monkeypatch, tmp_path, caplog, duration_info, do_duoc, len_len):
    v = _vid(1)
    gia, _ = gia_kenh(KENH_SHORTS, [muc_short(v)], info={_sh(v): thong_tin(v, duration=duration_info)})
    k = Khung(monkeypatch, tmp_path, gia)

    def do(path):
        assert do_duoc != "khong-duoc-goi", "info đã có thời lượng thì không đo lại trên tệp"
        return do_duoc
    monkeypatch.setattr(queue_mod, "_do_thoi_luong_quietly", do)
    jid = k.tao_job([KENH_SHORTS], so_luong=5)
    with caplog.at_level("WARNING", logger="videodl.web"):
        job, da_len = _chay_voi_hook(k, jid)
    tep = k.downloads / str(jid) / f"yt-{v}.mp4"
    if len_len:
        assert da_len == [f"yt-{v}"] and job["xong"] == 1 and job["loi"] == 0
    else:
        assert da_len == [], "Short vượt trần không được lên Drive"
        assert not tep.exists(), "Short vượt trần phải bị xoá khỏi đĩa"
        assert job["xong"] == 0 and job["loi"] == 1 and job["loi_tiktok"] == 1 and job["trang_thai"] == "failed"
        assert any("qua_dai" in r.getMessage() for r in caplog.records), "phải có lỗi RÕ, không bỏ qua lặng lẽ"


def test_job_hon_hop_short_dai_bi_xoa_short_ngan_len_drive(monkeypatch, tmp_path):
    v = [_vid(1), _vid(2), _vid(3)]
    info = {_sh(v[0]): thong_tin(v[0], duration=40 * PHUT), _sh(v[1]): thong_tin(v[1], duration=20),
            _sh(v[2]): thong_tin(v[2], duration=59)}
    gia, _ = gia_kenh(KENH_SHORTS, [muc_short(x) for x in v], info=info)
    k = Khung(monkeypatch, tmp_path, gia)
    jid = k.tao_job([KENH_SHORTS], so_luong=5)
    job, da_len = _chay_voi_hook(k, jid)
    assert da_len == [f"yt-{v[1]}", f"yt-{v[2]}"] and job["xong"] == 2 and job["loi"] == 1
    assert job["trang_thai"] == "done"
    assert not (k.downloads / str(jid) / f"yt-{v[0]}.mp4").exists()


# ================================================================== trần dung lượng lúc tải

def test_kenh_dat_tran_dung_luong_khi_tai_va_nhan_qua_nang_tu_dong_log_yt_dlp(monkeypatch, tmp_path):
    v = [_vid(1), _vid(2)]
    info = {_yt(x): thong_tin(x) for x in v}
    gia, _ = gia_kenh(KENH_VIDEOS, [muc_video(x, duration=30) for x in v], info=info)
    gia.vuot_tran = {_yt(v[0])}
    k = Khung(monkeypatch, tmp_path, gia)
    jid = k.tao_job([KENH_VIDEOS], so_luong=5)
    job, da_len = _chay_voi_hook(k, jid)
    opts_tai = [o for o in gia.opts_da_tao if "outtmpl" in o]
    assert opts_tai and all(o["max_filesize"] == queue_mod.TRAN_DUNG_LUONG_BYTE for o in opts_tai)
    assert da_len == [f"yt-{v[1]}"] and job["xong"] == 1 and job["loi"] == 1 and job["loi_tiktok"] == 1


# ================================================================== 7. tín hiệu chặn

def test_tin_hieu_chan_khi_mo_kenh_tat_nen_tang_va_dung_job_nhu_link_le(monkeypatch, tmp_path):
    gia, _ = gia_kenh(KENH_VIDEOS, [muc_video(_vid(1), duration=30)], loi={KENH_VIDEOS: loi_tai(BOT)})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([KENH_VIDEOS], so_luong=5))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "bi_chan" and job["xong"] == 0
    assert "youtube" in k.nen_tang_tat()
    assert gia.so_goi() == 1 and k.so_luot("youtube") == 1


def test_tin_hieu_chan_giua_luc_keo_trang_tiep_giu_20_muc_da_co_va_tat_nen_tang(monkeypatch, tmp_path):
    muc = [muc_video(_vid(i), duration=30) for i in range(60)]
    gia = YtdlpGia()
    ds = DanhSach(gia, muc, loi_o=20, loi=loi_tai(BOT))
    gia.ie_tho[KENH_VIDEOS] = ds
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 50)
    assert len(refs) == 20 and loi == [] and dung == ["bi_chan"]
    assert "youtube" in k.nen_tang_tat() and k.so_luot("youtube") == 2


def test_loi_thuong_khi_keo_trang_tiep_khong_tat_nen_tang(monkeypatch, tmp_path):
    muc = [muc_video(_vid(i), duration=30) for i in range(60)]
    gia = YtdlpGia()
    gia.ie_tho[KENH_VIDEOS] = DanhSach(gia, muc, loi_o=20, loi=loi_tai("ERROR: Unable to download API page: timed out"))
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 50)
    assert len(refs) == 20 and loi == ["loi_khac"] and dung == []
    assert k.nen_tang_tat() == {}


def test_nen_tang_dang_tat_thi_job_kenh_dung_ngay_khong_goi_yt_dlp(monkeypatch, tmp_path):
    gia, _ = gia_kenh(KENH_VIDEOS, [muc_video(_vid(1), duration=30)])
    k = Khung(monkeypatch, tmp_path, gia)
    pacer.tat_nen_tang(k.db, "youtube", "not_a_bot")
    job = k.chay(k.tao_job([KENH_VIDEOS], so_luong=5))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "bi_chan" and gia.so_goi() == 0


# ================================================================== 8. cổng nền tảng, ô số lượng, một URL mỗi job

def _dung_app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    return db


def _tao(url, so_luong=5):
    return app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=so_luong), nguoi_tao="a@x.vn")


@pytest.mark.parametrize("url", [KENH, KENH_SHORTS, PLAYLIST])
def test_job_kenh_lay_so_video_tu_o_so_luong_va_di_lane_youtube(tmp_path, monkeypatch, url):
    _dung_app(tmp_path, monkeypatch)
    ra = _tao(url, so_luong=7)
    assert ra["nen_tang"] == "youtube" and ra["tong"] == 7 and ra["url"] == url


def test_nen_tang_youtube_chua_bat_thi_job_kenh_bi_tu_choi_nhu_link_le(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "tiktok")
    for url in (KENH_SHORTS, PLAYLIST, "https://www.youtube.com/watch?v=aAa1aAa1aAa"):
        with pytest.raises(HTTPException) as e:
            _tao(url)
        assert e.value.status_code == 400 and "youtube chưa bật" in e.value.detail
    assert models.list_jobs(db, None) == []
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube")
    assert _tao(KENH_SHORTS)["trang_thai"] == "pending"


def test_nen_tang_youtube_dang_tat_sau_khi_bi_chan_thi_job_kenh_503(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    pacer.tat_nen_tang(db, "youtube", "not_a_bot")
    with pytest.raises(HTTPException) as e:
        _tao(KENH_SHORTS)
    assert e.value.status_code == 503 and models.list_jobs(db, None) == []


def test_nhieu_dong_chi_nhan_link_le_kenh_chi_mot_url_moi_job(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    le = "https://www.youtube.com/watch?v=aAa1aAa1aAa"
    for o in (f"{KENH_SHORTS}\n{le}", f"{le}\n{KENH_SHORTS}", f"{KENH}\n{KENH_SHORTS}"):
        with pytest.raises(HTTPException) as e:
            _tao(o)
        assert e.value.status_code == 400 and "nhiều link chỉ nhận link video lẻ" in e.value.detail
    assert models.list_jobs(db, None) == []


def test_thong_bao_url_khong_nhan_nhac_toi_kenh_playlist():
    assert "kênh / tab Shorts / playlist YouTube" in nguon_mod.mo_ta_cac_nguon()


# ================================================================== log không mang URL, handle hay id

def test_log_job_kenh_khong_mang_url_handle_hay_id(monkeypatch, tmp_path):
    from web.app import CheUrlFormatter
    ra, tho = io.StringIO(), io.StringIO()
    h = logging.StreamHandler(ra)
    h.setFormatter(CheUrlFormatter("%(levelname)s %(name)s: %(message)s"))
    h_tho = logging.StreamHandler(tho)
    h_tho.setFormatter(logging.Formatter("%(message)s"))
    v = [_vid(1), _vid(2), _vid(3)]
    muc = [muc_video(v[0], duration=None), muc_video(v[1], duration=40 * PHUT), muc_video(v[2], duration=30)]
    gia, _ = gia_kenh(KENH_VIDEOS, muc, info={_yt(v[2]): thong_tin(v[2])},
                      loi={_yt(v[0]): loi_tai(f"ERROR: [youtube] {v[0]}: Video unavailable. {_yt(v[0])} {KENH}")})
    k = Khung(monkeypatch, tmp_path, gia)
    raiz = logging.getLogger()
    cu = raiz.level
    raiz.setLevel(logging.DEBUG)
    raiz.addHandler(h)
    raiz.addHandler(h_tho)
    try:
        job = k.chay(k.tao_job([KENH_VIDEOS], so_luong=5))
    finally:
        raiz.removeHandler(h)
        raiz.removeHandler(h_tho)
        raiz.setLevel(cu)
    assert job["xong"] == 1 and job["loi"] == 2
    sach, tho_txt = ra.getvalue(), tho.getvalue()
    assert f"yt-{v[2]}" in tho_txt, "đối chứng: không qua formatter che thì id có tiền tố PHẢI lộ trong log"
    for nhay in ("youtube.com", "kenh.rieng.tu", "watch?v=", *v):
        assert nhay not in sach, f"log lộ {nhay!r}:\n{sach}"
    assert "yt-" not in sach.replace("yt-dlp", "")


# ================================================================== giao diện: nhãn nguồn của kênh

def test_nhan_nguon_giao_dien_cho_kenh_va_playlist_khong_gop_vao_hop_youtube_chung():
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    kich_ban = ("global.URL=URL;eval(lay('const NEN_TANG_THEO_HOST','function sourceBuckets'));"
                "console.log(JSON.stringify(process.argv.slice(3).map(shortenSourceUrl)));")
    urls = [KENH_SHORTS, KENH_VIDEOS, "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx", PLAYLIST,
            "https://www.youtube.com/watch?v=aAa1aAa1aAa"]
    r = subprocess.run([node, "-e", GOC_NODE + kich_ban, str(STATIC / "app.js"), "x", *urls],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["@kenh.rieng.tu/shorts", "@kenh.rieng.tu/videos",
                                    "channel/UCxxxxxxxxxxxxxxxxxxxxxx", "Playlist YouTube",
                                    "YouTube · aAa1aAa1aAa"]


# ================================================================== kênh trần, url tới video, mục hội viên, trần N, log tab

def test_kenh_tran_bi_ep_sang_tab_videos_truoc_loi_goi_dau(monkeypatch, tmp_path):
    """Kênh không tab: yt-dlp coi là "mọi video tải lên" — tự thêm tab `/streams`, `/shorts`, TẢI NGAY chúng trong
    cùng lời gọi (ngoài bộ đếm lượt) và trả playlist LỒNG nhiều tab (`_tab.py` nhánh `extra_tabs`: `playlist_result`
    của các `playlist_result` từng tab). Bản giả trả đúng khuôn lồng đó cho URL trần: nếu nguồn không ép `/videos`
    trước khi gọi thì danh sách rỗng (mục lồng không phải video) và test này đỏ."""
    vids = [_vid(i) for i in range(3)]
    gia = YtdlpGia()

    def tab(muc):
        return InfoExtractor.playlist_result(iter(muc), "UCxxxxxxxxxxxxxxxxxxxxxx", "tab")

    gia.ie_tho[KENH] = InfoExtractor.playlist_result(
        [tab([muc_video(v, duration=30) for v in vids]), tab([muc_short(_vid(9))])], "UCxxxxxxxxxxxxxxxxxxxxxx", "kenh")
    gia.ie_tho[KENH_VIDEOS] = DanhSach(gia, [muc_video(v, duration=30) for v in vids])
    gia.ie_tho[KENH_VIDEOS + "?si=x"] = DanhSach(gia, [muc_video(v, duration=30) for v in vids])
    k = Khung(monkeypatch, tmp_path, gia)
    for vao, ra in ((KENH, KENH_VIDEOS), (KENH + "/", KENH_VIDEOS), (KENH + "?si=x", KENH_VIDEOS + "?si=x")):
        gia.goi.clear()
        refs, loi, dung, _ = chay_liet_ke(k, vao, 10)
        assert [u for _, u in gia.goi] == [ra], "kênh trần phải được gọi bằng URL tab /videos (giữ query)"
        assert [r.video_id for r in refs] == [f"yt-{v}" for v in vids] and loi == [] and dung == []
        assert not any(r.la_short for r in refs)


def test_url_dich_la_video_thi_khong_theo_va_khong_ton_luot(monkeypatch, tmp_path):
    """Tab `/live` (hoặc yt-dlp "không nhận ra playlist") trả `url` tới một VIDEO: theo tiếp là một lượt trích xuất
    video đầy đủ cho kết quả chắc bị bỏ ⇒ dừng ở lời gọi đầu."""
    gia = YtdlpGia()
    gia.ie_tho[KENH_VIDEOS] = InfoExtractor.url_result(_yt(_vid(1)), YoutubeIE, _vid(1))
    gia.ie_tho[_yt(_vid(1))] = DanhSach(gia, [muc_video(_vid(2), duration=30)])    # nếu bị theo thì sẽ ra video
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke(k, KENH_VIDEOS, 10)
    assert [u for _, u in gia.goi] == [KENH_VIDEOS] and k.so_luot("youtube") == 1
    assert refs == [] and loi == ["khong_doc_duoc"] and dung == ["source_empty"]


@pytest.mark.parametrize("availability", ["subscriber_only", "premium_only", "needs_auth"])
def test_muc_chi_hoi_vien_bi_bo_khi_liet_ke_khong_ton_luot_tai(monkeypatch, tmp_path, availability):
    vs = [_vid(1), _vid(2)]
    muc = [muc_video(vs[0], duration=30, availability=availability), muc_video(vs[1], duration=30)]
    gia, _ = gia_kenh(KENH_VIDEOS, muc, info={_yt(v): thong_tin(v) for v in vs})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([KENH_VIDEOS], so_luong=5))
    assert job["xong"] == 1 and job["loi"] == 0
    assert [u for loai, u in gia.goi if loai == "tai"] == [_yt(vs[1])], "mục chỉ hội viên không được tốn lượt tải"


def test_job_kenh_toi_da_30_video_moi_luot(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    for url in (KENH, KENH_SHORTS, PLAYLIST):
        with pytest.raises(HTTPException) as e:
            _tao(url, so_luong=31)
        assert e.value.status_code == 400 and "tối đa 30 video" in e.value.detail
    assert models.list_jobs(db, None) == []
    assert _tao(KENH_SHORTS, so_luong=30)["tong"] == 30
    # Link lẻ không bị trần này (số video = số link).
    assert _tao("https://www.youtube.com/watch?v=aAa1aAa1aAa", so_luong=500)["tong"] == 1


@pytest.mark.parametrize("vao, khong_duoc_co", [
    ("ERROR: [youtube:tab] @kenh.rieng.tu: This channel does not have a shorts tab", "kenh.rieng.tu"),
    ("ERROR: [youtube:tab] UCxxxxxxxxxxxxxxxxxxxxxx page 1: HTTP Error 429: Too Many Requests", "UCxxxxxxxx"),
    ("ERROR: [youtube:tab] PLaaaaaaaaaaaaaaaaaaaa page 3: Incomplete data received", "PLaaaaaaaa"),
])
def test_che_url_che_handle_va_id_trong_loi_trang_tab(vao, khong_duoc_co):
    """Dạng lỗi thật của trình trích tab yt-dlp: "id" là handle (`@...`) và lỗi trang tiếp mang đuôi ` page N`."""
    from tiktok_music_downloader.utils import che_url
    ra = che_url(vao)
    assert khong_duoc_co not in ra and "[youtube:tab]" in ra
    assert ra.split(": ", 2)[-1] == vao.split(": ", 2)[-1], "lý do lỗi phải giữ nguyên"


def test_log_job_kenh_loi_mo_tab_khong_lo_handle(monkeypatch, tmp_path):
    from web.app import CheUrlFormatter
    ra = io.StringIO()
    h = logging.StreamHandler(ra)
    h.setFormatter(CheUrlFormatter("%(levelname)s %(name)s: %(message)s"))
    gia = YtdlpGia(loi_theo_url={KENH_SHORTS: loi_tai(
        "ERROR: [youtube:tab] @kenh.rieng.tu: This channel does not have a shorts tab")})
    k = Khung(monkeypatch, tmp_path, gia)
    raiz = logging.getLogger()
    cu = raiz.level
    raiz.setLevel(logging.DEBUG)
    raiz.addHandler(h)
    try:
        job = k.chay(k.tao_job([KENH_SHORTS], so_luong=5))
    finally:
        raiz.removeHandler(h)
        raiz.setLevel(cu)
    assert job["trang_thai"] == "failed" and job["loi"] == 1
    assert "kenh.rieng.tu" not in ra.getvalue() and "does not have a shorts tab" in ra.getvalue()


def _node(kich_ban: str, tep: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    r = subprocess.run([node, "-e", GOC_NODE + kich_ban, str(STATIC / tep)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_cau_dung_tran_gio_noi_da_tai_bao_nhieu_va_chay_lai_tai_tiep():
    """Chạm trần giờ GIỮA job ⇒ job dừng (không chờ). Câu trên thẻ phải nói đã tải bao nhiêu, chạm giới hạn giờ, chạy
    lại sau sẽ tải tiếp phần còn lại — không phải lỗi chung chung. Mã khác giữ nguyên câu."""
    ra = _node(
        "const ham=lay('function cauDungTranIp','const STOP_REASON_TEXT');"
        "const bang=lay('const STOP_REASON_TEXT','};')+'};';"
        "eval(ham+bang.replace('const STOP_REASON_TEXT','globalThis.STOP_REASON_TEXT'));"
        "const j=(ma,xong,tong)=>({ly_do_dung:ma,xong:xong,tong:tong});"
        "console.log(JSON.stringify(["
        " cauDungTranIp(j('tran_gio',12,30),STOP_REASON_TEXT.tran_gio),"
        " cauDungTranIp(j('tran_ngay',0,30),STOP_REASON_TEXT.tran_ngay),"
        " cauDungTranIp(j('het_dia',3,30),STOP_REASON_TEXT.het_dia),"
        " cauDungTranIp(j('ma_la',3,30),undefined)]));",
        "app.js")
    gio, ngay, dia, la = ra
    assert gio.startswith("Đã tải 12/30 video.") and "mỗi giờ" in gio and "tải phần còn lại" in gio
    assert ngay.startswith("Đã tải 0/30 video.") and "NGÀY" in ngay
    assert not dia.startswith("Đã tải") and la is None
