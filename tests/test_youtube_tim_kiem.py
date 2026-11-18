"""Nguồn `YoutubeTimKiem`: tìm kiếm / hashtag YouTube sau cờ env `VIDEODL_YT_TIM_KIEM_BAT` (mặc định tắt).

Ranh giới `YoutubeDL` là bản giả (`tests/yt_dlp_gia.py`); nhận dạng, dịch URL, pacer, `process_job`, DB chạy thật.
Không mạng.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from link_le_khung import Khung
from test_youtube_kenh import (KENH_VIDEOS, _dung_app, _tao, _vid, _yt, chay_liet_ke, gia_kenh, muc_video)
from yt_dlp_gia import YtdlpGia, thong_tin

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.nguon import LinkLe, YoutubeKenh, YoutubeTimKiem, chon_nguon
from web import app as app_mod
from web import models
from web import queue as queue_mod

CO = nguon_mod.ENV_YT_TIM_KIEM_BAT
TIM = "https://www.youtube.com/results?search_query=funny+cat"
HASHTAG = "https://www.youtube.com/hashtag/shorts"


@pytest.fixture
def bat(monkeypatch):
    monkeypatch.setenv(CO, "1")


# ---------------------------------------------------------------- cờ env

def test_ten_co_la_videodl_yt_tim_kiem_bat():
    assert CO == "VIDEODL_YT_TIM_KIEM_BAT"


@pytest.mark.parametrize("url", [TIM, HASHTAG])
@pytest.mark.parametrize("gia_tri", [None, "", "0", "false", "no", "off", "bat"])
def test_co_tat_thi_khong_nhan_va_chon_nguon_tra_none(monkeypatch, url, gia_tri):
    monkeypatch.delenv(CO, raising=False)
    if gia_tri is not None:
        monkeypatch.setenv(CO, gia_tri)
    assert not YoutubeTimKiem().nhan(url) and chon_nguon(url) is None


@pytest.mark.parametrize("url", [TIM, HASHTAG])
def test_co_tat_thi_post_job_van_400(tmp_path, monkeypatch, url):
    db = _dung_app(tmp_path, monkeypatch)
    monkeypatch.delenv(CO, raising=False)
    with pytest.raises(HTTPException) as e:
        _tao(url)
    assert e.value.status_code == 400 and models.list_jobs(db, None) == []


@pytest.mark.parametrize("gia_tri", ["1", "true", "YES", " on "])
def test_co_bat_thi_nhan(monkeypatch, gia_tri):
    monkeypatch.setenv(CO, gia_tri)
    assert isinstance(chon_nguon(TIM), YoutubeTimKiem) and isinstance(chon_nguon(HASHTAG), YoutubeTimKiem)


@pytest.mark.parametrize("url", [TIM, HASHTAG])
def test_co_bat_thi_post_job_nhan_di_lane_youtube_va_ep_tran_30(tmp_path, monkeypatch, bat, url):
    _dung_app(tmp_path, monkeypatch)
    ra = _tao(url, so_luong=7)
    assert ra["nen_tang"] == "youtube" and ra["tong"] == 7
    with pytest.raises(HTTPException) as e:
        _tao(url, so_luong=app_mod.MAX_VIDEO_KENH_YOUTUBE + 1)
    assert e.value.status_code == 400


def test_tran_lop_nguon_bang_tran_app():
    assert nguon_mod.TRAN_SO_VIDEO_TIM_KIEM == app_mod.MAX_VIDEO_KENH_YOUTUBE


# ---------------------------------------------------------------- nhận dạng

NHAN = [
    TIM, "https://youtube.com/results?search_query=a", "https://m.youtube.com/results?search_query=a",
    "https://www.youtube.com/results?search_query=a&sp=EgIQAQ%253D%253D",
    "https://www.youtube.com/results/?search_query=a",
    "https://www.youtube.com/hashtag/shorts/", "https://m.youtube.com/hashtag/catsofinstagram",
    "https://www.youtube.com/hashtag/%E3%82%AB%E3%83%A1%E3%83%A9",
]
KHONG_NHAN = [
    "ytsearch5:funny cat", "ytsearch999:x", "https://www.youtube.com/results", "https://www.youtube.com/results?search_query=",
    "https://www.youtube.com/results?search_query=%20%20", "https://www.youtube.com/results?q=a",
    "https://evil.example/results?search_query=a", "https://www.youtube.com/hashtag/", "https://www.youtube.com/hashtag/a/b",
    "https://www.youtube.com/watch?v=aAa1aAa1aAa", "https://www.youtube.com/@kenh/videos",
]


@pytest.mark.parametrize("url", NHAN)
def test_nhan_dang(bat, url):
    assert isinstance(chon_nguon(url), YoutubeTimKiem) and YoutubeTimKiem().nen_tang(url) == "youtube"


@pytest.mark.parametrize("url", KHONG_NHAN)
def test_khong_nhan_chuoi_ytsearch_tran_va_url_khac(bat, url):
    assert not isinstance(chon_nguon(url), YoutubeTimKiem)


def test_kenh_va_link_le_van_do_nguon_cu(bat):
    assert type(chon_nguon("https://www.youtube.com/@kenh/videos")) is YoutubeKenh
    assert isinstance(chon_nguon("https://www.youtube.com/watch?v=aAa1aAa1aAa"), LinkLe)


# ---------------------------------------------------------------- dịch URL ⇒ ytsearchN:kw

@pytest.mark.parametrize("url,n,mong", [
    (TIM, 5, "ytsearch5:funny cat"),
    ("https://m.youtube.com/results?search_query=funny%20cat", 5, "ytsearch5:funny cat"),
    ("https://www.youtube.com/results?search_query=m%C3%A8o+d%E1%BB%85+th%C6%B0%C6%A1ng", 3, "ytsearch3:mèo dễ thương"),
    ("https://www.youtube.com/results?search_query=a%0Ab%09c&sp=x", 2, "ytsearch2:a b c"),
    ("https://www.youtube.com/results?search_query=c%2B%2B+%26+rust", 4, "ytsearch4:c++ & rust"),
    (TIM, 30, "ytsearch30:funny cat"),
    (TIM, 31, "ytsearch30:funny cat"),
    (TIM, 10_000, "ytsearch30:funny cat"),
    (TIM, 0, "ytsearch1:funny cat"),
    (TIM, -4, "ytsearch1:funny cat"),
])
def test_dich_url_tim_kiem(url, n, mong):
    assert YoutubeTimKiem()._link_liet_ke(url, n) == mong


def test_tu_khoa_dai_bi_cat():
    kw = "x" * 500
    assert YoutubeTimKiem()._link_liet_ke(f"https://www.youtube.com/results?search_query={kw}", 5) \
        == "ytsearch5:" + "x" * nguon_mod.TRAN_DO_DAI_TU_KHOA


def test_hashtag_di_nguyen_url():
    assert YoutubeTimKiem()._link_liet_ke(HASHTAG, 5) == HASHTAG


def test_liet_ke_goi_yt_dlp_dung_chuoi_ytsearch_voi_n_da_kep(monkeypatch, tmp_path, bat):
    muc = [muc_video(_vid(i), duration=30) for i in range(40)]
    gia, _ = gia_kenh("ytsearch30:funny cat", muc)
    k = Khung(monkeypatch, tmp_path, gia)
    dung, loi = [], []
    from web import pacer
    cong = pacer.CongNenTang(k.db, k.tao_job([TIM]), "youtube")
    refs = YoutubeTimKiem().liet_ke(
        TIM, max_videos=99, already_have=lambda ids: set(), on_skip=lambda r: None, on_stop=dung.append,
        cong=cong, ghi_loi_video=lambda ma, ct: loi.append(ma), nghi=k._nghi)
    assert len(refs) == 30 and [u for _, u in gia.goi] == ["ytsearch30:funny cat"] and dung == [] and loi == []


# ---------------------------------------------------------------- 0 kết quả ⇒ lý do rõ, không "xong 0/0"

@pytest.mark.parametrize("url,dich", [(HASHTAG, HASHTAG), (TIM, "ytsearch5:funny cat")])
def test_ra_0_video_thi_job_bao_source_empty_khong_im_lang_done(monkeypatch, tmp_path, bat, url, dich):
    gia, _ = gia_kenh(dich, [])
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([url], so_luong=5))
    assert job["ly_do_dung"] == "source_empty" and job["xong"] == 0
    assert job["trang_thai"] == "failed"


def test_ra_0_video_o_liet_ke_tra_source_empty(monkeypatch, tmp_path, bat):
    gia, _ = gia_kenh(HASHTAG, [])
    k = Khung(monkeypatch, tmp_path, gia)
    refs, loi, dung, _ = chay_liet_ke_tim_kiem(k, HASHTAG, 5)
    assert refs == [] and dung == ["source_empty"]


def chay_liet_ke_tim_kiem(k, url, n):
    from web import pacer
    dung, bo, loi = [], [], []
    cong = pacer.CongNenTang(k.db, k.tao_job([url]), "youtube")
    refs = YoutubeTimKiem().liet_ke(url, max_videos=n, already_have=lambda ids: set(), on_skip=bo.append,
                                    on_stop=dung.append, cong=cong,
                                    ghi_loi_video=lambda ma, ct: loi.append(ma), nghi=k._nghi)
    return refs, loi, dung, bo


# ---------------------------------------------------------------- tải qua đường cũ + lọc trùng

def test_search_tai_qua_duong_cu_va_loc_trung_id_yt(monkeypatch, tmp_path, bat):
    v = [_vid(i) for i in range(1, 5)]
    muc = [muc_video(x, duration=30) for x in v] + [muc_video(v[0], duration=30)]
    gia, _ = gia_kenh("ytsearch5:funny cat", muc, info={_yt(x): thong_tin(x) for x in v})
    k = Khung(monkeypatch, tmp_path, gia)
    refs, _, dung, bo = chay_liet_ke_tim_kiem(k, TIM, 5)
    assert [r.video_id for r in refs] == [f"yt-{x}" for x in v] and dung == []
    refs2 = YoutubeTimKiem().liet_ke(
        TIM, max_videos=5, already_have=lambda ids: {i for i in ids if i == f"yt-{v[1]}"}, on_skip=bo.append,
        on_stop=dung.append, cong=None)
    assert f"yt-{v[1]}" not in [r.video_id for r in refs2] and bo and bo[-1].video_id == f"yt-{v[1]}"


def test_la_kenh_youtube_true_cho_tim_kiem(bat):
    assert queue_mod.la_kenh_youtube(TIM) and queue_mod.la_kenh_youtube(HASHTAG)


def test_thong_bao_400_chi_nhac_tim_kiem_hashtag_khi_co_bat(monkeypatch):
    monkeypatch.delenv(CO, raising=False)
    assert YoutubeTimKiem.mo_ta_url not in nguon_mod.mo_ta_cac_nguon()
    monkeypatch.setenv(CO, "1")
    assert YoutubeTimKiem.mo_ta_url in nguon_mod.mo_ta_cac_nguon()


@pytest.mark.parametrize("url", [TIM, HASHTAG])
def test_instagram_khong_cuop_url_tim_kiem_hashtag_youtube_va_nguoc_lai(monkeypatch, url):
    from tiktok_music_downloader.nguon import InstagramHangLoat
    monkeypatch.setenv(CO, "1")
    assert not InstagramHangLoat().nhan(url)
    for ig in ("https://www.instagram.com/explore/tags/cat/", "https://www.instagram.com/nasa/reels/"):
        assert not YoutubeTimKiem().nhan(ig)
