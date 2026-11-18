"""Nguồn Facebook page hàng loạt ở mức job: nhận dạng URL, `process_job` thật + `download_all` thật (chỉ trình duyệt và yt-dlp
là giả), cổng pacer, tường ⇒ job `failed` nhãn riêng, cờ TẮT, trần 20 ở POST /jobs + /tinh-nang, và log KHÔNG chứa URL /
tên page / mã video / `fbv-`."""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from fb_khung_gia import (
    HOP_THOAI_DONG_DUOC, TUONG, URL_REELS, URL_VIDEOS, PhienGia, TrangGia, ma, media_reel, nhieu_dot, nut, script_reels,
    script_videos, xhr, dot,
)
from link_le_khung import Khung
from yt_dlp_gia import YtdlpGia, thong_tin

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import nguon_facebook_trang as nf
from tiktok_music_downloader.nguon import FacebookTrang, FbAdsLibrary, LinkLe, chon_nguon
from web import app as app_mod
from web import models, pacer
from web import queue as queue_mod

NGUOI = "a@x.vn"


def _watch(m: str) -> str:
    return f"https://www.facebook.com/watch/?v={m}"


def _reel(m: str) -> str:
    return f"https://www.facebook.com/reel/{m}"


def _dung(monkeypatch, tmp_path, trang: TrangGia | None, *, vid=(), url_fn=_watch, loi=None, **info):
    gia = YtdlpGia({url_fn(v): thong_tin(v, **info) for v in vid})
    k = Khung(monkeypatch, tmp_path, gia)
    phien = PhienGia(trang, loi)
    monkeypatch.setattr(nf, "_mo_phien", phien)
    return k, gia, phien


# ------------------------------------------------------------------------------- nhận dạng URL

@pytest.mark.parametrize("url,loai,chuan", [
    ("https://www.facebook.com/ten-page-gia/videos", "videos", "https://www.facebook.com/ten-page-gia/videos"),
    ("https://www.facebook.com/ten-page-gia/videos/", "videos", "https://www.facebook.com/ten-page-gia/videos"),
    ("https://www.facebook.com/ten-page-gia/reels", "reels", "https://www.facebook.com/ten-page-gia/reels"),
    ("https://www.facebook.com/ten-page-gia/reels/", "reels", "https://www.facebook.com/ten-page-gia/reels"),
    ("https://www.facebook.com/ten-page-gia", "videos", "https://www.facebook.com/ten-page-gia/videos"),   # ép /videos
    ("https://www.facebook.com/ten-page-gia/", "videos", "https://www.facebook.com/ten-page-gia/videos"),
    ("https://facebook.com/TenPage.gia", "videos", "https://www.facebook.com/TenPage.gia/videos"),          # không www
    ("https://m.facebook.com/ten-page-gia/reels", "reels", "https://www.facebook.com/ten-page-gia/reels"),
    ("https://web.facebook.com/ten-page-gia/videos", "videos", "https://www.facebook.com/ten-page-gia/videos"),
    ("http://www.facebook.com/100064439573705/videos", "videos", "https://www.facebook.com/100064439573705/videos"),
    ("  https://www.facebook.com/ten-page-gia/reels?ref=x  ", "reels", "https://www.facebook.com/ten-page-gia/reels"),
])
def test_nhan_dang_va_ep_url(url, loai, chuan):
    d = nf.phan_tich_url(url)
    assert d is not None and (d.loai, d.url) == (loai, chuan)
    n = chon_nguon(url)
    assert isinstance(n, FacebookTrang) and n.nen_tang(url) == "facebook" and n.loai_log(url) == f"facebook:{loai}"


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/ads/library/?id=123",                         # thư viện quảng cáo
    "https://www.facebook.com/ten-page-gia/videos/1234567890123/",          # video lẻ của page
    "https://www.facebook.com/ten-page-gia/videos/ten-bai/1234567890123/",
    "https://www.facebook.com/reel/1234567890123", "https://www.facebook.com/reel/1234567890123/",
    "https://www.facebook.com/reels/", "https://www.facebook.com/watch", "https://www.facebook.com/watch/?v=1234567890123",
    "https://www.facebook.com/watch/ten-page-gia/", "https://www.facebook.com/share/v/AbC123/",
    "https://www.facebook.com/share/r/AbC123/", "https://www.facebook.com/groups/ten-nhom/",
    "https://www.facebook.com/groups/ten-nhom/videos", "https://www.facebook.com/events/123/",
    "https://www.facebook.com/profile.php?id=100064439573705", "https://www.facebook.com/profile.php",
    "https://www.facebook.com/video.php?v=123", "https://www.facebook.com/photo/?fbid=1",
    "https://www.facebook.com/ten-page-gia/posts/123", "https://www.facebook.com/ten-page-gia/photos",
    "https://www.facebook.com/ten-page-gia/about", "https://www.facebook.com/ten-page-gia/reels/123",
    "https://www.facebook.com/", "https://www.facebook.com", "https://www.facebook.com/people/Ten/100/",
    "https://www.facebook.com/hashtag/abc", "https://www.facebook.com/stories/123/", "https://www.facebook.com/login/",
    "https://www.facebook.com/ten page/videos", "https://www.facebook.com/ten_page/videos",
    "https://fb.watch/abc123/", "https://example.com/ten-page-gia/videos",
    "https://www.instagram.com/ten.gia/reels/", "https://www.facebook.com.evil.com/ten-page-gia/videos",
    "khong-phai-url", "",
])
def test_khong_nhan_link_le_va_trang_he_thong(url):
    assert nf.phan_tich_url(url) is None
    assert not isinstance(chon_nguon(url), FacebookTrang)


def test_link_le_va_ads_library_van_di_dung_nguon_cu():
    assert isinstance(chon_nguon("https://www.facebook.com/reel/1234567890123"), LinkLe)
    assert isinstance(chon_nguon("https://www.facebook.com/ten-page-gia/videos/1234567890123/"), LinkLe)
    assert isinstance(chon_nguon("https://www.facebook.com/watch/?v=1234567890123"), LinkLe)
    assert isinstance(chon_nguon("https://www.facebook.com/ads/library/?id=123"), FbAdsLibrary)


def test_dung_truoc_linkle_va_nam_trong_nguon_yt_dlp_nen_tang_khac():
    loai = [type(n) for n in nguon_mod.NGUON]
    assert loai.index(FacebookTrang) < loai.index(LinkLe)
    assert FacebookTrang in nguon_mod.NGUON_YT_DLP_NEN_TANG_KHAC


# ------------------------------------------------------------------------------- job đầy đủ

def test_job_videos_n3_tai_3_video_an_danh_khong_cookie_id_fbv(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=ids)
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    assert job["trang_thai"] == "done" and job["xong"] == 3 and job["tim_thay"] == 3
    assert phien.trang.da_mo == [URL_VIDEOS] and phien.proxy_da_dung == [None]
    assert not any(o.get("cookiefile") for o in gia.opts_da_tao)                  # Đường A: không cookie ở đâu cả
    assert sorted(u for l, u in gia.goi if l == "tai") == sorted(_watch(m) for m in ids)
    assert models.known_video_ids(k.db, ["fbv-" + m for m in ids]) == {"fbv-" + m for m in ids}
    assert k.so_luot("facebook") == 1 + 3          # mỗi lượt MỞ trang = 1 lượt pacer, cộng mỗi lần tải


def test_job_reels_tai_bang_url_reel(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2, reels=True)), vid=ids, url_fn=_reel)
    job = k.chay(k.tao_job([URL_REELS], nen_tang="facebook", so_luong=3))
    assert job["trang_thai"] == "done" and job["xong"] == 3 and phien.trang.da_mo == [URL_REELS]
    assert sorted(u for l, u in gia.goi if l == "tai") == sorted(_reel(m) for m in ids)


def test_chay_lai_cung_nguon_0_trung(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(6)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=ids)
    j1 = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    phien.trang = TrangGia(nhieu_dot(3, 2))
    j2 = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    assert j1["xong"] == 3 and j2["xong"] == 3
    tai = [u for l, u in gia.goi if l == "tai"]
    assert len(tai) == len(set(tai)) == 6


def test_job_dat_tran_dung_luong_khi_tai_nhu_kenh_youtube(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(2, 2)), vid=[ma(i) for i in range(2)])
    k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=2))
    opts_tai = [o for o in gia.opts_da_tao if "outtmpl" in o]
    assert opts_tai and all(o["max_filesize"] == queue_mod.TRAN_DUNG_LUONG_BYTE for o in opts_tai)


def test_nut_khong_co_thoi_luong_do_sau_tai_vuot_15_phut_bi_loai_khong_len_drive(monkeypatch, tmp_path):
    """Nút không mang thời lượng ⇒ `la_short` ⇒ trần `TRAN_THOI_LUONG_GIAY` kiểm SAU tải (như Short YouTube)."""
    ids = [ma(0), ma(1)]
    gia = YtdlpGia({_watch(ids[0]): thong_tin(ids[0], duration=40 * 60), _watch(ids[1]): thong_tin(ids[1], duration=30)})
    k = Khung(monkeypatch, tmp_path, gia)
    monkeypatch.setattr(nf, "_mo_phien", PhienGia(TrangGia(nhieu_dot(1, 2))))
    da_len: list[str] = []

    def hook(*, job_id, ref, path, db_path=None):
        da_len.append(ref.video_id)
        return Khung.hook_drive(job_id=job_id, ref=ref, path=path, db_path=db_path)

    jid = k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=5)
    with queue_mod.models._connect(k.db) as c:
        c.execute("UPDATE jobs SET trang_thai='running' WHERE id=?", (jid,))
    queue_mod.process_job(k.db, k.downloads, k.cookies, models.get_job(k.db, jid), lifecycle_hook=hook)
    job = models.get_job(k.db, jid)
    assert da_len == ["fbv-" + ids[1]] and job["xong"] == 1 and job["loi"] == 1


def test_nut_co_thoi_luong_vuot_tran_bi_loai_ngay_luc_liet_ke_khong_ton_luot_tai(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(
        scripts=[script_videos([nut(ma(0), giay=60), nut(ma(1), giay=3600), nut(ma(2), giay=30)], con_trang=False)]),
        vid=[ma(0), ma(2)])
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=5))
    assert job["xong"] == 2 and gia.so_goi("tai") == 2


# ------------------------------------------------------------------------------- tường ⇒ job failed (ĐỘT BIẾN ii, iii)

def test_16_ma_deu_da_co_cong_tuong_job_failed_fb_chan_dang_nhap_khong_xong_rong(monkeypatch, tmp_path):
    """MẶC ĐỊNH BẮT BUỘC: 16 mã đều đã có trong thư viện + hộp thoại đăng nhập không đóng được ⇒ lý do
    `fb_chan_dang_nhap` và job `failed` (không "Xong"). ĐỘT BIẾN (ii) bỏ phát hiện tường ⇒ ĐỎ; (iii) thiếu mã trong
    `_LY_DO_RONG_LA_LOI` ⇒ job "done" ⇒ ĐỎ."""
    ids = [ma(i) for i in range(16)]
    k, gia, phien = _dung(monkeypatch, tmp_path,
                          TrangGia(scripts=[script_videos([nut(m) for m in ids])], dom=TUONG), vid=ids)
    j1 = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=16))            # tải 16 mã, thư viện giờ có đủ
    assert j1["trang_thai"] == "done" and j1["xong"] == 16
    phien.trang = TrangGia(scripts=[script_videos([nut(m) for m in ids])], dom=TUONG)
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=30))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "fb_chan_dang_nhap"
    assert job["xong"] == 0 and job["tim_thay"] == 0 and job["bo_qua"] == 16


def test_tuong_sau_khi_lay_duoc_vai_video_job_done_va_ly_do_van_la_tuong(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(4)]
    k, gia, phien = _dung(monkeypatch, tmp_path,
                          TrangGia(scripts=[script_videos([nut(m) for m in ids])], dom=TUONG), vid=ids)
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=20))
    assert job["trang_thai"] == "done" and job["xong"] == 4 and job["ly_do_dung"] == "fb_chan_dang_nhap"


def test_tuong_0_ma_job_failed(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia([], dom=TUONG))
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=5))
    assert (job["trang_thai"], job["ly_do_dung"]) == ("failed", "fb_chan_dang_nhap") and gia.so_goi("tai") == 0


def test_0_ma_khong_tuong_la_source_empty_failed(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia([]))
    job = k.chay(k.tao_job([URL_REELS], nen_tang="facebook", so_luong=5))
    assert (job["trang_thai"], job["ly_do_dung"]) == ("failed", "source_empty")


def test_hop_thoai_dau_dong_duoc_bam_roi_di_tiep_job_du_n(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(4)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(2, 2), dom_theo_lan={0: HOP_THOAI_DONG_DUOC}), vid=ids)
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=4))
    assert job["trang_thai"] == "done" and job["xong"] == 4 and phien.trang.so_bam_dong == 1


def test_ly_do_rong_la_loi_co_ma_tuong_va_http_429_tat_nen_tang(monkeypatch, tmp_path):
    assert "fb_chan_dang_nhap" in queue_mod._LY_DO_RONG_LA_LOI
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(2, 2), nav=429))
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    assert (job["trang_thai"], job["ly_do_dung"], job["xong"]) == ("failed", "bi_chan", 0)
    assert "facebook" in k.nen_tang_tat()


# ------------------------------------------------------------------------------- cổng pacer (ĐỘT BIẾN v)

def test_cong_pacer_tran_gio_dung_truoc_khi_mo_trinh_duyet(monkeypatch, tmp_path):
    """ĐỘT BIẾN (v): bỏ `cong.truoc_goi()` ở lượt mở trang ⇒ trình duyệt vẫn mở ⇒ ĐỎ."""
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=[ma(i) for i in range(3)])
    tran_gio, _ = pacer.TRAN["facebook"]
    assert tran_gio == 30                                            # KHÔNG đổi trần pacer
    for _ in range(tran_gio):
        assert pacer.ghi_truoc_khi_goi(k.db, "facebook", None, now=k.gio[0]) is None
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "tran_gio" and job["xong"] == 0
    assert phien.so_lan_mo == 0 and gia.so_goi() == 0


def test_loi_trinh_duyet_job_failed_thong_diep_khong_chua_url_va_goi_xu_ly_loi(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    k, gia, phien = _dung(monkeypatch, tmp_path, None,
                          loi=TimeoutError(f"Timeout goto {URL_VIDEOS} HTTP Error 429 Too Many Requests"))
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook"))
    assert job["trang_thai"] == "failed"
    assert "facebook" in k.nen_tang_tat()                            # `cong.xu_ly_loi(exc)` đã thấy tín hiệu chặn
    texto = "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "") for r in caplog.records)
    assert "ten-page-gia" not in texto and "facebook.com" not in texto and "TimeoutError" in texto


# ------------------------------------------------------------------------------- log: 0 URL / tên page / mã / fbv-

CAM_TRONG_LOG = ["ten-page-gia", "facebook.com", "http://", "https://", "fbv-", "watch/?v="]
MODULE_FB = ("fb_quet_cuon", "fb_trinh_duyet", "fb_xhr_phan_tich", "nguon_facebook_trang")


def _log_fb_tho(caplog) -> str:
    return "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "")
                     for r in caplog.records if any(m in r.pathname for m in MODULE_FB))


def _log_qua_formatter(caplog) -> str:
    f = app_mod.CheUrlFormatter("%(levelname)s %(name)s: %(message)s")
    return "\n".join(f.format(r) for r in caplog.records)


def test_log_mot_luot_gia_lap_dem_0_url_ten_page_ma_video_va_fbv(monkeypatch, tmp_path, caplog, capsys):
    """ĐỘT BIẾN (iv): ghi URL / tên page / mã video / `fbv-` vào log ở `liet_ke` ⇒ ĐỎ."""
    caplog.set_level(logging.DEBUG)
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2), dom_theo_lan={0: HOP_THOAI_DONG_DUOC}), vid=ids)
    job = k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=3))
    assert job["xong"] == 3
    tho = _log_fb_tho(caplog)
    assert "facebook:videos" in tho and "3 video mới" in tho and "1 lần đóng hộp thoại" in tho   # nhãn + con số, có log thật
    out = capsys.readouterr()
    for ten, van_ban in (("thô", tho + out.out + out.err), ("qua formatter", _log_qua_formatter(caplog))):
        for tu in CAM_TRONG_LOG + ids:
            assert tu not in van_ban, f"log {ten} lộ {tu!r}"


def test_log_luot_bi_tuong_cung_sach(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(scripts=[script_videos([nut(m) for m in ids])], dom=TUONG), vid=ids)
    k.chay(k.tao_job([URL_VIDEOS], nen_tang="facebook", so_luong=30))
    tho = _log_fb_tho(caplog)
    assert "tường=có" in tho
    for tu in CAM_TRONG_LOG + ids:
        assert tu not in tho and tu not in _log_qua_formatter(caplog)


# ------------------------------------------------------------------------------- cờ TẮT, trần 20, /tinh-nang

def _app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    return db


@pytest.mark.parametrize("url", [URL_VIDEOS, URL_REELS, "https://www.facebook.com/ten-page-gia"])
def test_co_tat_mac_dinh_post_jobs_tu_choi_url_fb_page_va_khong_ghi_job(tmp_path, monkeypatch, url):
    db = _app(tmp_path, monkeypatch)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    assert "facebook" not in nguon_mod.nen_tang_bat()                # mặc định TẮT
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=5), nguoi_tao=NGUOI)
    assert e.value.status_code == 400 and "facebook" in e.value.detail
    assert models.list_jobs(db, None) == []


def test_co_bat_post_jobs_nhan_url_fb_page_nen_tang_facebook(tmp_path, monkeypatch):
    db = _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,facebook")
    out = app_mod.create_job(app_mod.CreateJobRequest(url=URL_VIDEOS, so_luong=7), nguoi_tao=NGUOI)
    job = models.get_job(db, out["id"])
    assert job["nen_tang"] == "facebook" and job["tong"] == 7


def test_tran_20_chan_o_post_jobs_21_la_400_20_la_nhan(tmp_path, monkeypatch):
    db = _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,facebook")
    assert app_mod.MAX_VIDEO_TRANG_FB == 20
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=URL_REELS, so_luong=21), nguoi_tao=NGUOI)
    assert e.value.status_code == 400 and "20" in e.value.detail and models.list_jobs(db, None) == []
    out = app_mod.create_job(app_mod.CreateJobRequest(url=URL_REELS, so_luong=20), nguoi_tao=NGUOI)
    assert models.get_job(db, out["id"])["tong"] == 20


def test_tran_20_chi_ap_cho_fb_page_khong_dung_kenh_youtube(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,facebook")
    out = app_mod.create_job(app_mod.CreateJobRequest(url="https://www.youtube.com/@kenhgia/videos", so_luong=25),
                             nguoi_tao=NGUOI)
    assert out["id"]


def test_tran_20_co_trong_tinh_nang(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    tn = app_mod.tinh_nang(nguoi_tao=NGUOI)
    assert tn["tran"]["video_trang_facebook"] == app_mod.MAX_VIDEO_TRANG_FB == 20
    assert any(n["ten"] == "facebook_trang" for n in tn["nguon"])


def test_nhieu_link_fb_page_trong_mot_job_bi_tu_choi(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,facebook")
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=URL_VIDEOS + "\n" + URL_VIDEOS.replace("gia", "hai"),
                                                    so_luong=5), nguoi_tao=NGUOI)
    assert e.value.status_code == 400
