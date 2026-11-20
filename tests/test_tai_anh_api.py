"""API của chế độ tải ảnh: cổng cờ, chọn nguồn theo loại, `/tinh-nang`, `GET /anh`, cụm, thumb.

Gọi thẳng hàm route (như `tests/test_web_app.py`): không cần client HTTP.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from tiktok_music_downloader import nguon, tai_anh_cau_hinh as cfg
from web import app as app_mod
from web import lifecycle, models, models_anh

TOI = "toi@dev.local"
HO = "ho@dev.local"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TT_MUSIC = "https://www.tiktok.com/music/nhac-123456"
TT_PHOTO = "https://www.tiktok.com/@u/photo/7123456789012345678"
IG_PROFILE = "https://www.instagram.com/nguoi.dung/"
IG_REELS = "https://www.instagram.com/nguoi.dung/reels/"
FB_TRANG = "https://www.facebook.com/trang.nao"


@pytest.fixture
def may(tmp_path, monkeypatch):
    """DB tạm, cổng backpressure/trần ngày mở, nền tảng bật đủ 4, cờ ảnh TẮT (mặc định thật)."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "ck")
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setenv(nguon.ENV_NEN_TANG_BAT, "youtube,tiktok,instagram,facebook")
    monkeypatch.delenv(cfg.ENV_TAI_ANH_BAT, raising=False)
    return db


def _tao(url, loai_tai=None, so_luong=5, nguoi=TOI):
    kw = {} if loai_tai is None else {"loai_tai": loai_tai}
    return app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=so_luong, **kw), nguoi_tao=nguoi)


def _so_job(db):
    return len(models.list_jobs(db, None))


# ---------------------------------------------------------------- POST /jobs

def test_thieu_loai_tai_la_job_video_y_nhu_hom_nay(may):
    job = _tao(TT_MUSIC)
    assert job["loai_tai"] == "video"
    assert models.get_job(may, job["id"])["loai_tai"] == "video"


def test_co_tat_thi_loai_anh_va_ca_hai_bi_400_va_khong_co_hang_job(may):
    for loai in ("anh", "ca_hai"):
        with pytest.raises(HTTPException) as e:
            _tao(TT_MUSIC, loai)
        assert e.value.status_code == 400 and "tắt" in e.value.detail
    assert _so_job(may) == 0
    assert _tao(TT_MUSIC, "video")["loai_tai"] == "video", "chế độ video không bị cờ chặn"


def test_loai_tai_la_bi_tu_choi_o_cua_vao():
    with pytest.raises(ValidationError):
        app_mod.CreateJobRequest(url=TT_MUSIC, so_luong=5, loai_tai="gif")


def test_co_bat_thi_job_anh_va_ca_hai_duoc_tao_va_luu_loai_tai(may, monkeypatch):
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    assert _tao(TT_MUSIC, "anh")["loai_tai"] == "anh"
    assert _tao(TT_MUSIC, "ca_hai")["loai_tai"] == "ca_hai"
    assert {j["loai_tai"] for j in app_mod.list_jobs(nguoi_tao=TOI)} == {"anh", "ca_hai"}, "API danh sách job trả loai_tai"


@pytest.mark.parametrize("url, loai", [
    (YT, "anh"), (YT, "ca_hai"),                       # YouTube chỉ video
    (IG_REELS, "anh"),                                 # IG /reels/ chỉ video
    (FB_TRANG, "ca_hai"),                              # FB page: một lượt một tab
    ("https://www.facebook.com/ads/library/?active_status=all&q=a", "anh"),
])
def test_nguon_khong_ho_tro_loai_bi_400_noi_ro_va_khong_co_hang_job(may, monkeypatch, url, loai):
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    with pytest.raises(HTTPException) as e:
        _tao(url, loai)
    assert e.value.status_code == 400
    assert "không hỗ trợ" in e.value.detail or "chọn Video hoặc Ảnh" in e.value.detail, e.value.detail
    assert _so_job(may) == 0


def test_facebook_page_ca_hai_noi_dung_cau_chon_video_hoac_anh(may, monkeypatch):
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    with pytest.raises(HTTPException) as e:
        _tao(FB_TRANG, "ca_hai")
    assert e.value.detail.startswith("Facebook page: chọn Video hoặc Ảnh")


def test_nguon_ho_tro_loai_van_tao_duoc(may, monkeypatch):
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    assert _tao(IG_PROFILE, "ca_hai")["loai_tai"] == "ca_hai"
    assert _tao(IG_PROFILE, "anh")["nen_tang"] == "instagram"
    assert _tao(FB_TRANG, "anh")["nen_tang"] == "facebook"
    assert _tao(IG_REELS, "video")["loai_tai"] == "video"


def test_link_anh_tiktok_chi_nhan_khi_xin_anh_che_do_video_giu_cau_400_chung(may, monkeypatch):
    with pytest.raises(HTTPException) as e:
        _tao(TT_PHOTO)
    assert e.value.status_code == 400 and e.value.detail.startswith("url không được nhận")
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    job = _tao(TT_PHOTO, "anh")
    assert job["nen_tang"] == "tiktok" and job["loai_tai"] == "anh"


def test_nhieu_link_xet_loai_tung_link(may, monkeypatch):
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    with pytest.raises(HTTPException) as e:        # một link reel IG không có ảnh ⇒ cả lượt bị từ chối
        _tao(f"{TT_PHOTO}\nhttps://www.instagram.com/reel/Cx9AbZ12/", "anh")
    assert e.value.status_code == 400 and "không hỗ trợ" in e.value.detail
    assert _so_job(may) == 0
    # Hai link ảnh TikTok: hợp lệ (cùng nền tảng, đều là link lẻ).
    job = _tao(f"{TT_PHOTO}\nhttps://www.tiktok.com/@u/photo/7123456789012345679", "anh")
    assert job["tong"] == 2


# ---------------------------------------------------------------- /tinh-nang

def test_tinh_nang_co_tai_anh_bat_va_nen_tang_anh_giao_voi_nen_tang_bat(may, monkeypatch):
    tn = app_mod.tinh_nang(nguoi_tao=TOI)
    assert tn["tai_anh_bat"] is False and tn["nen_tang_anh"] == []
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    tn = app_mod.tinh_nang(nguoi_tao=TOI)
    assert tn["tai_anh_bat"] is True and tn["nen_tang_anh"] == ["facebook", "instagram", "tiktok"]
    monkeypatch.setenv(nguon.ENV_NEN_TANG_BAT, "youtube,instagram")
    assert app_mod.tinh_nang(nguoi_tao=TOI)["nen_tang_anh"] == ["instagram"]


# ---------------------------------------------------------------- GET /anh, /videos, cụm, thumb

def _them_bai(db, nguoi, bai_id, k, nguon_url="https://www.tiktok.com/music/nhac-1"):
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, nguoi, loai_tai="anh")
    models_anh.ghi_bai_anh(db, [
        {"video_id": cfg.file_id_anh(bai_id, i), "job_id": job, "url": "https://www.tiktok.com/@a/photo/1",
         "bai_id": bai_id, "thu_tu": i, "drive_file_id": f"drv{bai_id}{i}"} for i in range(1, k + 1)])
    models.record_sighting(db, bai_id, job, nguon_url, True)
    return job


def test_get_anh_gom_theo_bai_dung_quyen_va_videos_khong_thay_anh(may, monkeypatch):
    _them_bai(may, TOI, "anh-tt-100", 3)
    _them_bai(may, HO, "anh-tt-200", 2, nguon_url="https://www.tiktok.com/tag/BI-MAT-CUA-HO")
    models.record_video(may, models.create_job(may, "https://www.tiktok.com/tag/x", 1, TOI), "777", "u")

    out = app_mod.list_anh(nguoi_tao=TOI)

    assert out["tong"] == 1 and [b["bai_id"] for b in out["bai"]] == ["anh-tt-100"]
    b = out["bai"][0]
    assert b["thumb_id"] == "anh-tt-100-01" and b["so_anh"] == 3 and len(b["file_ids"]) == 3
    assert b["nguon"] == ["https://www.tiktok.com/music/nhac-1"]
    f = b["files"][0]
    assert f["cum_id"] is None and f["vao_bo"] is None and f["nguon"] == b["nguon"]
    assert [v["video_id"] for v in app_mod.list_videos(nguoi_tao=TOI)["videos"]] == ["777"]
    assert app_mod.list_videos(nguoi_tao=TOI)["tong"] == 1
    # Quyền: chữ của người khác không rò qua `nguon`; admin thấy hết.
    assert "BI-MAT-CUA-HO" not in str(out)
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@dev.local")
    models.moi_admin_tu_env(may, ["sep@dev.local"])      # đúng việc `_lifespan` làm lúc khởi động
    assert {b["bai_id"] for b in app_mod.list_anh(nguoi_tao="sep@dev.local")["bai"]} == {"anh-tt-100", "anh-tt-200"}


def test_get_anh_dung_luat_tham_so_nhu_videos(may):
    for kw in ({"limit": 0}, {"limit": 10**6}, {"offset": -1}, {"vao_bo": 2}):
        with pytest.raises(HTTPException) as e:
            app_mod.list_anh(nguoi_tao=TOI, **{"limit": 10, "offset": 0, "vao_bo": None, **kw})
        assert e.value.status_code == 400


def test_post_cum_video_tu_choi_id_anh(may):
    with pytest.raises(HTTPException) as e:
        app_mod.gan_video_cum(1, app_mod.GanVideoCumRequest(video_ids=["123", "anh-tt-100-01"], bo=False), nguoi_tao=TOI)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        app_mod.gan_video_cum(1, app_mod.GanVideoCumRequest(video_ids=["anh-tt-100-01"], bo=True), nguoi_tao=TOI)
    assert e.value.status_code == 422
    # Id video thường vẫn đi tiếp tới tầng cụm (cụm không tồn tại ⇒ 404 như trước).
    with pytest.raises(HTTPException) as e:
        app_mod.gan_video_cum(999, app_mod.GanVideoCumRequest(video_ids=["123"], bo=False), nguoi_tao=TOI)
    assert e.value.status_code == 404


def test_thumb_nhan_id_anh_va_van_kiem_chu(may):
    _them_bai(may, TOI, "anh-tt-100", 2)
    tep = lifecycle.thumb_path_for(may, "anh-tt-100-01")
    tep.parent.mkdir(parents=True, exist_ok=True)
    tep.write_bytes(b"RIFF....WEBP")

    assert app_mod.get_thumb("anh-tt-100-01", nguoi_tao=TOI).path == tep
    with pytest.raises(HTTPException) as e:                 # người khác: 404 như "không có"
        app_mod.get_thumb("anh-tt-100-01", nguoi_tao=HO)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:                 # hình id sai (traversal)
        app_mod.get_thumb("anh-../x", nguoi_tao=TOI)
    assert e.value.status_code == 404


def test_loai_video_nhan_id_anh_de_bo_tay(may):
    _them_bai(may, TOI, "anh-tt-100", 2)
    out = app_mod.loai_video(app_mod.LoaiVideoRequest(video_ids=["anh-tt-100-01"]), nguoi_tao=TOI)
    assert "anh-tt-100-01" in str(out)
    with sqlite3.connect(may) as c:
        assert c.execute("SELECT da_loai_luc IS NOT NULL FROM videos WHERE video_id='anh-tt-100-01'").fetchone()[0] == 1
