"""Cookie Instagram: jar `<sha256>.instagram.json` tách khỏi jar TikTok (so BYTE), nạp jar không có cookie instagram.com
⇒ 400 và jar cũ giữ nguyên, kiểm hạn / chưa đăng nhập, `_write_netscape_cookies` đọc được bản xuất Cookie-Editor,
đường dẫn không thoát thư mục, thẻ đỏ khi job IG gần nhất dừng vì mất phiên, và trang Cài đặt có thẻ."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from tiktok_music_downloader import downloader as dl
from web import app as app_mod
from web import cookies, models

NGUOI = "a@x.vn"
BI_MAT_TT = "TIKTOK-BI-MAT-111"
BI_MAT_IG = "IG-BI-MAT-222"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def _jar_tiktok() -> str:
    return json.dumps([{"name": "sessionid", "value": BI_MAT_TT, "domain": ".tiktok.com", "path": "/",
                        "expires": 4102444800}])


def _jar_ig(gia_tri=BI_MAT_IG, domain=".instagram.com", han=None, ten="sessionid", session=False) -> str:
    c = {"name": ten, "value": gia_tri, "domain": domain, "path": "/", "secure": True, "httpOnly": True,
         "sameSite": "no_restriction", "hostOnly": False, "session": session, "storeId": "0"}
    if han is not None:
        c["expirationDate"] = han
    return json.dumps([c, {"name": "csrftoken", "value": "c", "domain": domain, "path": "/", "sameSite": "lax"}])


def _san(tmp_path, monkeypatch):
    cookies_dir, tmp_dir = tmp_path / "cookies", tmp_path / "tmp"
    cookies_dir.mkdir()
    tmp_dir.mkdir()
    monkeypatch.setattr(app_mod, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(dl, "COOKIE_TMP_DIR", str(tmp_dir))
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")
    models.init_db(tmp_path / "jobs.db")
    return cookies_dir, tmp_dir


def _put_ig(txt, nguoi=NGUOI):
    return app_mod.put_my_cookie_instagram(app_mod.CookieBody(json=txt), nguoi_tao=nguoi)


def _put_tt(txt, nguoi=NGUOI):
    return app_mod.put_my_cookie(app_mod.CookieBody(json=txt), nguoi_tao=nguoi)


def test_ten_tep_jar_theo_nen_tang_tiktok_giu_nguyen_duong_cu(tmp_path):
    d = hashlib.sha256(NGUOI.encode()).hexdigest()
    assert cookies.cookie_jar_path(tmp_path, NGUOI) == (tmp_path / f"{d}.json").resolve()
    assert cookies.cookie_jar_path(tmp_path, NGUOI, "tiktok") == (tmp_path / f"{d}.json").resolve()
    assert cookies.cookie_jar_path(tmp_path, NGUOI, "instagram") == (tmp_path / f"{d}.instagram.json").resolve()
    assert cookies.cookies_path_for_user(tmp_path, NGUOI, "instagram") is None
    (tmp_path / f"{d}.instagram.json").write_text("[]")
    assert cookies.cookies_path_for_user(tmp_path, NGUOI, "instagram") == str((tmp_path / f"{d}.instagram.json").resolve())
    assert cookies.cookies_path_for_user(tmp_path, NGUOI) is None            # jar IG không phải jar TikTok


@pytest.mark.parametrize("nt", ["../../etc/passwd", "facebook", "", "tiktok/../x"])
def test_nen_tang_la_khong_the_thoat_thu_muc_jar(tmp_path, nt):
    with pytest.raises(ValueError):
        cookies.cookie_jar_path(tmp_path, NGUOI, nt)
    with pytest.raises(ValueError):
        cookies.cookies_path_for_user(tmp_path, NGUOI, nt)


def test_nap_va_xoa_cookie_ig_khong_doi_byte_cookie_tiktok(tmp_path, monkeypatch):
    """ĐỘT BIẾN: nạp IG ghi đè / đụng jar TikTok ⇒ ĐỎ (so BYTE và mtime_ns)."""
    cookies_dir, _ = _san(tmp_path, monkeypatch)
    _put_tt(_jar_tiktok())
    tt = cookies.cookie_jar_path(cookies_dir, NGUOI)
    truoc, mtime = tt.read_bytes(), tt.stat().st_mtime_ns
    out = _put_ig(_jar_ig())
    assert out["co_jar"] is True and out["trang_thai"] == "dung_duoc"
    ig = cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram")
    assert ig.name == f"{hashlib.sha256(NGUOI.encode()).hexdigest()}.instagram.json" and ig.is_file()
    assert tt.read_bytes() == truoc and tt.stat().st_mtime_ns == mtime
    _put_ig(_jar_ig("IG-MOI-333"))                                           # thay jar IG
    assert tt.read_bytes() == truoc
    app_mod.delete_my_cookie_instagram(nguoi_tao=NGUOI)                      # xoá jar IG
    assert not ig.exists() and tt.read_bytes() == truoc and tt.stat().st_mtime_ns == mtime
    app_mod.delete_my_cookie(nguoi_tao=NGUOI)                                # xoá TikTok không đụng IG
    _put_ig(_jar_ig())
    app_mod.delete_my_cookie(nguoi_tao=NGUOI)
    assert ig.is_file() and not tt.exists()


@pytest.mark.parametrize("jar_xau,ma_mong_doi", [
    (_jar_tiktok(), "cookie_khong_phai_instagram"),                           # jar TikTok dán nhầm vào ô IG
    (_jar_ig(domain=".notinstagram.com"), "cookie_khong_phai_instagram"),
    (_jar_ig(domain="instagram.com.evil.io"), "cookie_khong_phai_instagram"),
    (_jar_ig(ten="ig_did"), "cookie_chua_dang_nhap"),
    (_jar_ig(han=time.time() - 3600), "cookie_het_han"),
    ("[]", "cookie_rong"),
    ("không phải json", "cookie_khong_doc_duoc"),
])
def test_nap_jar_xau_400_va_jar_ig_cu_giu_nguyen_byte(tmp_path, monkeypatch, jar_xau, ma_mong_doi):
    cookies_dir, tmp_dir = _san(tmp_path, monkeypatch)
    _put_ig(_jar_ig())
    ig = cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram")
    truoc = ig.read_bytes()
    with pytest.raises(HTTPException) as e:
        _put_ig(jar_xau)
    assert e.value.status_code == 400 and e.value.detail == ma_mong_doi       # chỉ MÃ, không một byte của tệp
    assert BI_MAT_IG not in str(e.value.detail) and BI_MAT_TT not in str(e.value.detail)
    assert ig.read_bytes() == truoc
    assert list(tmp_dir.iterdir()) == []                                      # không để cookie đọc được ở thư mục tạm


def test_jar_khong_co_cookie_instagram_com_400_khi_chua_co_jar_cu_thi_khong_tao_tep(tmp_path, monkeypatch):
    cookies_dir, _ = _san(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as e:
        _put_ig(_jar_tiktok())
    assert e.value.status_code == 400
    assert not cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram").exists()


def test_jar_tiktok_van_chi_nhan_cookie_tiktok_jar_ig_dan_vao_o_tiktok_bi_tu_choi(tmp_path, monkeypatch):
    _san(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as e:
        _put_tt(_jar_ig())
    assert e.value.status_code == 400 and e.value.detail == "cookie_khong_phai_tiktok"


def test_trang_thai_get_ig_chi_ma_con_so_khong_ro_byte(tmp_path, monkeypatch):
    _san(tmp_path, monkeypatch)
    assert app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI) == {
        "co_jar": False, "trang_thai": None, "het_han": None, "cap_nhat_luc": None, "van_tay": None}
    han = time.time() + 86400 * 10
    out = _put_ig(_jar_ig(han=han))
    assert out["co_jar"] and out["trang_thai"] == "dung_duoc" and out["het_han"].startswith("20")
    assert BI_MAT_IG not in json.dumps(out) and len(out["van_tay"]) == 8
    assert app_mod.get_my_cookie(nguoi_tao=NGUOI)["co_jar"] is False          # ô TikTok không thấy jar IG


def test_nguoi_dung_khac_khong_thay_jar_ig_cua_nhau(tmp_path, monkeypatch):
    _san(tmp_path, monkeypatch)
    _put_ig(_jar_ig(), nguoi="a@x.vn")
    assert app_mod.get_my_cookie_instagram(nguoi_tao="b@x.vn")["co_jar"] is False


# ---------------------------------------------------------------- thẻ đỏ khi job IG gần nhất dừng vì mất phiên

def test_the_do_khi_job_ig_gan_nhat_ig_mat_phien_va_het_do_khi_dan_lai_jar(tmp_path, monkeypatch):
    cookies_dir, _ = _san(tmp_path, monkeypatch)
    _put_ig(_jar_ig())
    ig = cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram")
    os.utime(ig, (time.time() - 3600, time.time() - 3600))                   # jar dán từ 1 giờ trước
    assert app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI)["trang_thai"] == "dung_duoc"
    db = tmp_path / "jobs.db"
    jid = models.create_job(db, "https://www.instagram.com/x/reels/", 5, NGUOI, nen_tang="instagram")
    models.set_job_stop_reason(db, jid, "ig_mat_phien")
    models.finish_job(db, jid, "failed")
    assert app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI)["trang_thai"] == "ig_mat_phien"
    assert app_mod.get_my_cookie_instagram(nguoi_tao="b@x.vn")["trang_thai"] is None      # người khác không đỏ theo
    _put_ig(_jar_ig("IG-MOI"))                                               # dán lại SAU job ⇒ hết đỏ
    assert app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI)["trang_thai"] == "dung_duoc"


def test_the_khong_do_khi_job_ig_gan_nhat_dung_vi_ly_do_khac(tmp_path, monkeypatch):
    cookies_dir, _ = _san(tmp_path, monkeypatch)
    _put_ig(_jar_ig())
    ig = cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram")
    os.utime(ig, (time.time() - 3600, time.time() - 3600))
    db = tmp_path / "jobs.db"
    j1 = models.create_job(db, "https://www.instagram.com/x/reels/", 5, NGUOI, nen_tang="instagram")
    models.set_job_stop_reason(db, j1, "ig_mat_phien")
    j2 = models.create_job(db, "https://www.instagram.com/x/reels/", 5, NGUOI, nen_tang="instagram")
    models.set_job_stop_reason(db, j2, "tran_gio")
    assert app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI)["trang_thai"] == "dung_duoc"


def test_jar_ig_het_han_the_do_bang_ma_cookie_het_han(tmp_path, monkeypatch):
    cookies_dir, _ = _san(tmp_path, monkeypatch)
    ig = cookies.cookie_jar_path(cookies_dir, NGUOI, "instagram")
    ig.write_text(_jar_ig(han=time.time() - 10))
    out = app_mod.get_my_cookie_instagram(nguoi_tao=NGUOI)
    assert out["trang_thai"] == "cookie_het_han" and out["het_han"] is not None


# ---------------------------------------------------------------- yt-dlp đọc được bản xuất Cookie-Editor

def test_write_netscape_cookies_doc_duoc_json_cookie_editor_cua_ig(tmp_path, monkeypatch):
    _san(tmp_path, monkeypatch)
    jar = tmp_path / "ig.json"
    jar.write_text(_jar_ig(han=time.time() + 86400 * 30.7))
    tep = dl._write_netscape_cookies(jar)
    try:
        dong = [l for l in tep.read_text().splitlines() if l and not l.startswith("#")]
        cot = {l.split("\t")[5]: l.split("\t") for l in dong}
        assert set(cot) == {"sessionid", "csrftoken"} and all(len(c) == 7 for c in cot.values())
        assert cot["sessionid"][:4] == [".instagram.com", "TRUE", "/", "TRUE"]   # subdomain + secure
        assert cot["sessionid"][4].isdigit() and cot["sessionid"][6] == BI_MAT_IG   # `expirationDate` thập phân ⇒ int
    finally:
        tep.unlink(missing_ok=True)


# ---------------------------------------------------------------- trang Cài đặt

def test_trang_cai_dat_co_the_cookie_instagram_tai_khoan_phu_va_js_hop_le():
    html = (STATIC / "settings.html").read_text(encoding="utf-8")
    assert 'data-nen-tang="instagram"' in html and "Cookie Instagram — dùng tài khoản PHỤ" in html
    assert '/settings-instagram.js' in html
    js = (STATIC / "settings-instagram.js").read_text(encoding="utf-8")
    assert "/me/cookie/instagram" in js and "ig_mat_phien" in js and "Cookie IG hết hạn / bị IG chặn" in js
    for id_ in ("ig-tt", "ig-cookie-json", "ig-cookie-luu", "ig-cookie-xoa", "ig-cookie-error", "ig-van-tay"):
        assert f'id="{id_}"' in html, id_
    import shutil
    import subprocess
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(STATIC / "settings-instagram.js")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_moi_ma_ig_moi_co_cau_tren_giao_dien():
    stop = (STATIC / "stop-reason-text.js").read_text(encoding="utf-8")
    ck = (STATIC / "cookie-status-text.js").read_text(encoding="utf-8")
    for ma in ("ig_mat_phien", "ig_chua_co_cookie", "cookie_khong_phai_instagram"):
        assert f"{ma}:" in stop, ma
    assert "cookie_khong_phai_instagram:" in ck
