"""Nguồn Instagram hàng loạt ở mức job: nhận dạng URL, `process_job` thật + `download_all` thật (chỉ trình duyệt và yt-dlp
là giả), cổng pacer, tiền kiểm jar, từng dấu mất phiên ⇒ job `failed` nhãn riêng, cờ TẮT, và log KHÔNG chứa
cookie / URL / handle / mã bài."""
from __future__ import annotations

import hashlib
import json
import logging
import time

import pytest
from fastapi import HTTPException

from ig_khung_gia import PhienGia, TrangGia, dot, ma, nhieu_dot, node, thanh_audio, xhr
from link_le_khung import Khung
from yt_dlp_gia import YtdlpGia, thong_tin

from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import nguon_instagram as ni
from tiktok_music_downloader.nguon import InstagramHangLoat, LinkLe, chon_nguon
from web import app as app_mod
from web import models, pacer

NGUOI = "a@x.vn"
PROFILE = "https://www.instagram.com/ten.gia/reels/"
GIA_TRI_COOKIE = "GIA-TRI-BI-MAT-0123456789"
TEN_COOKIE_LA = "csrftoken"


def _jar(het_han: float | None = None, session=True, dang_nhap=True, mien=".instagram.com") -> str:
    """Bản xuất kiểu Cookie-Editor (list dict, `expirationDate`, `sameSite` kiểu `no_restriction`)."""
    cs = [{"name": TEN_COOKIE_LA, "value": GIA_TRI_COOKIE + "-c", "domain": mien, "path": "/", "secure": True,
           "httpOnly": False, "sameSite": "no_restriction", "expirationDate": time.time() + 86400 * 300}]
    if dang_nhap:
        c = {"name": "sessionid", "value": GIA_TRI_COOKIE + "-s", "domain": mien, "path": "/", "secure": True,
             "httpOnly": True, "sameSite": "lax", "hostOnly": False, "session": session, "storeId": "0"}
        if het_han is not None:
            c["expirationDate"] = het_han
        cs.append(c)
    return json.dumps(cs)


def _ghi_jar(k, noi_dung: str, nguoi=NGUOI, nen_tang="instagram") -> str:
    k.cookies.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(nguoi.encode()).hexdigest()
    p = k.cookies / (f"{digest}.json" if nen_tang == "tiktok" else f"{digest}.{nen_tang}.json")
    p.write_text(noi_dung, encoding="utf-8")
    return str(p)


def _dung(monkeypatch, tmp_path, trang: TrangGia | None, *, vid=(), jar=True, loi=None):
    gia = YtdlpGia({f"https://www.instagram.com/reel/{v}/": thong_tin(v) for v in vid})
    k = Khung(monkeypatch, tmp_path, gia)
    phien = PhienGia(trang, loi)
    monkeypatch.setattr(ni, "_mo_phien", phien)
    if jar:
        _ghi_jar(k, _jar())
    return k, gia, phien


# ------------------------------------------------------------------------------- nhận dạng URL

@pytest.mark.parametrize("url,loai,chuan", [
    ("https://www.instagram.com/ten.gia/reels/", "profile", "https://www.instagram.com/ten.gia/reels/"),
    ("https://www.instagram.com/ten.gia/", "profile", "https://www.instagram.com/ten.gia/reels/"),     # ép /reels/
    ("https://instagram.com/ten.gia", "profile", "https://www.instagram.com/ten.gia/reels/"),
    ("https://www.instagram.com/explore/search/keyword/?q=tandoor", "keyword",
     "https://www.instagram.com/explore/search/keyword/?q=tandoor"),
    ("https://www.instagram.com/explore/search/keyword/?q=%23emiuquan2", "hashtag",
     "https://www.instagram.com/explore/search/keyword/?q=%23emiuquan2"),
    ("https://www.instagram.com/explore/tags/emiuquan2/", "hashtag",
     "https://www.instagram.com/explore/search/keyword/?q=%23emiuquan2"),                              # ép sang keyword
    ("https://www.instagram.com/reels/audio/1485893805770596/", "audio",
     "https://www.instagram.com/reels/audio/1485893805770596/"),
])
def test_nhan_dang_va_ep_url(url, loai, chuan):
    d = ni.phan_tich_url(url)
    assert d is not None and (d.loai, d.url) == (loai, chuan)
    n = chon_nguon(url)
    assert isinstance(n, InstagramHangLoat) and n.nen_tang(url) == "instagram" and n.loai_log(url) == f"instagram:{loai}"


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/reel/Cabc123xyz/", "https://www.instagram.com/p/Cabc123xyz/",
    "https://www.instagram.com/stories/ten.gia/123/", "https://www.instagram.com/explore/",
    "https://www.instagram.com/accounts/login/", "https://www.instagram.com/reels/",
    "https://www.instagram.com/explore/search/keyword/?q=", "https://www.instagram.com/explore/search/keyword/",
    "https://example.com/ten.gia/", "https://www.instagram.com/ten gia/", "khong-phai-url",
])
def test_khong_nhan_link_le_va_trang_he_thong(url):
    assert ni.phan_tich_url(url) is None
    assert not isinstance(chon_nguon(url), InstagramHangLoat)


def test_link_le_instagram_van_la_link_le_va_dung_truoc_linkle():
    assert isinstance(chon_nguon("https://www.instagram.com/reel/Cabc123xyz/"), LinkLe)
    assert [type(n) for n in nguon_mod.NGUON].index(InstagramHangLoat) < [type(n) for n in nguon_mod.NGUON].index(LinkLe)
    assert InstagramHangLoat in nguon_mod.NGUON_YT_DLP_NEN_TANG_KHAC


# ------------------------------------------------------------------------------- job đầy đủ

def test_job_profile_n3_tai_3_video_bang_jar_ig_va_cookiefile_yt_dlp(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=ids)
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    assert job["trang_thai"] == "done" and job["xong"] == 3 and job["tim_thay"] == 3
    assert phien.jar_da_dung == [str(k.cookies / f"{hashlib.sha256(NGUOI.encode()).hexdigest()}.instagram.json")]
    assert phien.trang.da_mo == [PROFILE]
    assert all(o.get("cookiefile") for o in gia.opts_da_tao if o.get("skip_download") is not True)
    # mỗi lượt MỞ URL IG = 1 lượt pacer, cộng mỗi lần yt-dlp tải = 1 lượt
    assert k.so_luot("instagram") == 1 + 3


def test_chay_lai_cung_nguon_0_trung(monkeypatch, tmp_path):
    ids = [ma(i) for i in range(6)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=ids)
    j1 = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    phien.trang = TrangGia(nhieu_dot(3, 2))
    j2 = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    assert j1["xong"] == 3 and j2["xong"] == 3
    tai = [u for l, u in gia.goi if l == "tai"]
    assert len(tai) == len(set(tai)) == 6                                  # 6 bài khác nhau, không bài nào tải hai lần


def test_job_audio_dung_nguon_audio_va_so_ref_theo_o_so_luong(monkeypatch, tmp_path):
    dots = [[xhr(thanh_audio([node(ma(d * 12 + i)) for i in range(12)], con_trang=True))] for d in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(dots), vid=[ma(i) for i in range(5)])
    url = "https://www.instagram.com/reels/audio/1485893805770596/"
    job = k.chay(k.tao_job([url], nen_tang="instagram", so_luong=5))
    assert job["trang_thai"] == "done" and job["xong"] == 5 and phien.trang.da_mo == [url]


# ------------------------------------------------------------------------------- cổng pacer + tiền kiểm jar

def test_cong_pacer_tran_gio_dung_truoc_khi_mo_trinh_duyet(monkeypatch, tmp_path):
    """ĐỘT BIẾN: bỏ `cong.truoc_goi()` ở lượt mở URL ⇒ ĐỎ."""
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), vid=[ma(i) for i in range(3)])
    tran_gio, _ = pacer.TRAN["instagram"]
    assert tran_gio == 30
    for _ in range(tran_gio):
        assert pacer.ghi_truoc_khi_goi(k.db, "instagram", None, now=k.gio[0]) is None
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "tran_gio" and job["xong"] == 0
    assert phien.so_lan_mo == 0 and gia.so_goi() == 0


def test_khong_co_jar_ig_dung_ngay_khong_chay_an_danh(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), jar=False)
    _ghi_jar(k, _jar(mien=".tiktok.com"), nen_tang="tiktok")                   # có jar TikTok cũng KHÔNG được dùng
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "ig_chua_co_cookie"
    assert phien.so_lan_mo == 0 and k.so_luot() == 0


def test_jar_ig_het_han_la_ig_mat_phien_va_jar_hong_la_chua_co_cookie(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), jar=False)
    _ghi_jar(k, _jar(het_han=time.time() - 3600, session=False))
    j = k.chay(k.tao_job([PROFILE], nen_tang="instagram"))
    assert (j["trang_thai"], j["ly_do_dung"]) == ("failed", "ig_mat_phien")
    _ghi_jar(k, _jar(dang_nhap=False))
    j = k.chay(k.tao_job([PROFILE], nen_tang="instagram"))
    assert (j["trang_thai"], j["ly_do_dung"]) == ("failed", "ig_chua_co_cookie")
    _ghi_jar(k, _jar(mien=".tiktok.com"))
    j = k.chay(k.tao_job([PROFILE], nen_tang="instagram"))
    assert (j["trang_thai"], j["ly_do_dung"]) == ("failed", "ig_chua_co_cookie")
    assert phien.so_lan_mo == 0


def test_cookie_chi_cua_nguoi_tao_job_nguoi_khac_khong_dung_chung(monkeypatch, tmp_path):
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2)), jar=False)
    _ghi_jar(k, _jar(), nguoi="nguoi.khac@x.vn")
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram"))
    assert job["ly_do_dung"] == "ig_chua_co_cookie" and phien.so_lan_mo == 0


# ------------------------------------------------------------------------------- mất phiên ⇒ failed, KHÔNG "xong" rỗng

MAT_PHIEN = {
    "dau1_url": TrangGia([], url_cuoi="https://www.instagram.com/accounts/login/?next=/x/"),
    "dau2_nho": TrangGia([[xhr('{"data":1}')]]),
    "dau2_errors": TrangGia([[xhr(json.dumps({"errors": [{"code": 1675002}], "p": "x" * 2000}))]]),
    "dau3_dom": TrangGia(nhieu_dot(3, 3), dom=ph.DauDom(co_o_ten_dang_nhap=True)),
    "dau4_khong_xhr": TrangGia([]),
    "dau5_429": TrangGia([[xhr("", status=429)]]),
}


@pytest.mark.parametrize("ten", sorted(MAT_PHIEN))
def test_moi_dau_mat_phien_job_failed_nhan_ig_khong_xong_rong(monkeypatch, tmp_path, ten):
    k, gia, phien = _dung(monkeypatch, tmp_path, MAT_PHIEN[ten])
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=5))
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "ig_mat_phien"
    assert job["xong"] == 0 and job["tim_thay"] == 0 and gia.so_goi("tai") == 0
    assert pacer.nen_tang_dang_tat(k.db) == {}                            # mất phiên IG không tắt nền tảng của người khác


def test_mat_phien_audio_chi_bat_bang_dom(monkeypatch, tmp_path):
    dots = [[xhr(thanh_audio([node(ma(i)) for i in range(12)]))]]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(dots, dom=ph.DauDom(co_nut_dang_nhap=True)))
    job = k.chay(k.tao_job(["https://www.instagram.com/reels/audio/1485893805770596/"], nen_tang="instagram"))
    assert (job["trang_thai"], job["ly_do_dung"], job["xong"]) == ("failed", "ig_mat_phien", 0)


def test_loi_trinh_duyet_job_failed_va_thong_diep_khong_chua_url(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    k, gia, phien = _dung(monkeypatch, tmp_path, None, loi=TimeoutError(f"Timeout goto {PROFILE} cookie={GIA_TRI_COOKIE}"))
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram"))
    assert job["trang_thai"] == "failed"
    texto = "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "") for r in caplog.records)
    assert "ten.gia" not in texto and GIA_TRI_COOKIE not in texto and "instagram.com" not in texto
    assert "TimeoutError" in texto                                  # còn tên lớp lỗi để chẩn đoán


# ------------------------------------------------------------------------------- log: 0 cookie / URL / handle / mã bài

CAM_TRONG_LOG = [GIA_TRI_COOKIE, "sessionid", TEN_COOKIE_LA, "instagram.com", "ten.gia", "http://", "https://"]
MODULE_IG = ("ig_quet_cuon", "ig_trinh_duyet", "ig_xhr_phan_tich", "nguon_instagram")


def _log_ig_tho(caplog) -> str:
    """Thông điệp THÔ (chưa qua formatter che URL) của chính các module IG: ở đây URL/handle/cookie/mã bài phải = 0."""
    return "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "")
                     for r in caplog.records if any(m in r.pathname for m in MODULE_IG))


def _log_qua_formatter(caplog) -> str:
    """Toàn bộ dòng log của lượt chạy, qua `CheUrlFormatter` như production (nó che `ig-<mã>`, URL, handle)."""
    f = app_mod.CheUrlFormatter("%(levelname)s %(name)s: %(message)s")
    return "\n".join(f.format(r) for r in caplog.records)


def test_log_mot_luot_gia_lap_dem_0_cookie_url_handle_shortcode(monkeypatch, tmp_path, caplog, capsys):
    """Log thật của một lượt giả lập: 0 cookie, 0 URL, 0 handle, 0 mã bài. ĐỘT BIẾN: ghi cookie/URL vào log ở
    `liet_ke` ⇒ ĐỎ."""
    caplog.set_level(logging.DEBUG)
    ids = [ma(i) for i in range(3)]
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(3, 2, anh_moi_dot=1)), vid=ids)
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=3))
    assert job["xong"] == 3
    tho = _log_ig_tho(caplog)
    assert "instagram:profile" in tho and "3 video mới" in tho and "0 carousel bỏ qua" in tho   # nhãn + con số, có log thật
    out = capsys.readouterr()
    for ten, van_ban in (("thô", tho + out.out + out.err), ("qua formatter", _log_qua_formatter(caplog))):
        for tu in CAM_TRONG_LOG + ids:
            assert tu not in van_ban, f"log {ten} lộ {tu!r}"
    assert "ig-V0" not in _log_qua_formatter(caplog) and "ig-V0" not in tho


# ------------------------------------------------------------------------------- cờ TẮT ⇒ POST /jobs từ chối

def _app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    return db


@pytest.mark.parametrize("url", [PROFILE, "https://www.instagram.com/explore/tags/emiuquan2/",
                                 "https://www.instagram.com/reels/audio/1485893805770596/",
                                 "https://www.instagram.com/explore/search/keyword/?q=tandoor"])
def test_co_tat_mac_dinh_post_jobs_tu_choi_url_ig_hang_loat_va_khong_ghi_job(tmp_path, monkeypatch, url):
    db = _app(tmp_path, monkeypatch)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=5), nguoi_tao=NGUOI)
    assert e.value.status_code == 400 and "instagram" in e.value.detail
    assert models.list_jobs(db, None) == []


def test_co_bat_post_jobs_nhan_url_ig_hang_loat_nen_tang_instagram(tmp_path, monkeypatch):
    db = _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,instagram")
    out = app_mod.create_job(app_mod.CreateJobRequest(url=PROFILE, so_luong=7), nguoi_tao=NGUOI)
    job = models.get_job(db, out["id"])
    assert job["nen_tang"] == "instagram" and job["tong"] == 7


def test_nhieu_link_ig_hang_loat_trong_mot_job_bi_tu_choi(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,instagram")
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=PROFILE + "\n" + PROFILE.replace("ten.gia", "ten.hai"),
                                                    so_luong=5), nguoi_tao=NGUOI)
    assert e.value.status_code == 400


def test_nhip_job_ig_cho_6s_cuon_2_5_den_4s_va_nghi_giua_video_trong_khoang_pacer(monkeypatch, tmp_path):
    """Nhịp thật của một job: sau mở trang chờ 6 s; giữa các lần cuộn 2,5–4 s; giữa hai lần yt-dlp tải dùng
    `pacer.NGHI_GIUA_LUOT` (10–20 s — DÀI HƠN mức 2–4 s đã đo ở bước 0, chủ ý thận trọng; xem báo cáo)."""
    k, gia, phien = _dung(monkeypatch, tmp_path, TrangGia(nhieu_dot(5, 2)), vid=[ma(i) for i in range(6)])
    seen = []
    monkeypatch.setattr(ni.ig_quet_cuon.random, "uniform", lambda a, b: (seen.append((a, b)), a)[1])
    job = k.chay(k.tao_job([PROFILE], nen_tang="instagram", so_luong=6))
    assert job["xong"] == 6
    assert seen and set(seen) == {(2.5, 4.0)}                                   # mọi lần cuộn xin đúng khoảng 2,5–4 s
    assert k.ngu[0] == 6.0                                                      # chờ ban đầu sau khi mở trang
    giua_video = [x for x in k.ngu if x >= 10]
    assert len(giua_video) == 5 and all(pacer.NGHI_GIUA_LUOT[0] <= x <= pacer.NGHI_GIUA_LUOT[1] for x in giua_video)
