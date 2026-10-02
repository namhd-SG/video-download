"""Chip "Đã vào bộ" lọc Ở SERVER: `/videos?vao_bo=0|1`.

Lọc ở client thì video đã vào bộ (đang ẩn) vẫn chiếm suất `LIBRARY_MAX` của lưới mặc
định. `list_videos` và `count_videos` phải lọc CÙNG phía — lệch một bên thì `tong` không
khớp số hàng các trang và trang hỏi thêm/thiếu trang.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from web import models

TOI = "toi@astronex.ai"
KHAC = "khac@astronex.ai"
SEP = "sep@astronex.ai"
AN = {"t03", "t07", "t11"}            # của TOI, đang ẩn (đã vào bộ)
AN_KHAC = {"k02"}                     # của KHAC, đang ẩn
DON = "t05"                           # của TOI, ẩn + đã dọn khỏi Drive ⇒ rời thư viện


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    from web import app as mod
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(mod, "_la_admin", lambda email: email == SEP)
    j1 = models.create_job(db, "https://www.tiktok.com/tag/a", 12, TOI)
    j2 = models.create_job(db, "https://www.tiktok.com/tag/b", 4, KHAC)
    for i in range(1, 13):
        models.record_video(db, job_id=j1, video_id=f"t{i:02d}", url=f"https://t.co/t{i}",
                            tao_luc=f"2026-09-01T00:00:{i:02d}+00:00")
    for i in range(1, 5):
        models.record_video(db, job_id=j2, video_id=f"k{i:02d}", url=f"https://t.co/k{i}",
                            tao_luc=f"2026-09-01T00:01:{i:02d}+00:00")
    with sqlite3.connect(db) as c:
        for vid in AN | AN_KHAC:
            c.execute("INSERT INTO video_vao_bo (video_id, an_luc) VALUES (?, '2026-09-30T00:00:00+00:00')",
                      (vid,))
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) VALUES "
                  "(?, '2026-09-20T00:00:00+00:00', '2026-09-27T00:00:00+00:00', 'test')", (DON,))
    return mod


def _ids(res):
    return {v["video_id"] for v in res["videos"]}


def _moi_trang(app_mod, nguoi, vao_bo, limit=2):
    """Gom MỌI trang như `loadVideos`, dừng theo `tong` — kiểm `tong` khớp số hàng."""
    ra, offset = [], 0
    while True:
        r = app_mod.list_videos(limit=limit, offset=offset, vao_bo=vao_bo, nguoi_tao=nguoi)
        ra += [v["video_id"] for v in r["videos"]]
        offset += limit
        if offset >= r["tong"]:
            return ra, r


def test_ba_phia_cua_nguoi_thuong(app_mod):
    tat_ca = {f"t{i:02d}" for i in range(1, 13)} - {DON}
    mac_dinh = app_mod.list_videos(limit=100, offset=0, vao_bo=0, nguoi_tao=TOI)
    da_vao = app_mod.list_videos(limit=100, offset=0, vao_bo=1, nguoi_tao=TOI)
    ca_hai = app_mod.list_videos(limit=100, offset=0, nguoi_tao=TOI)
    assert _ids(mac_dinh) == tat_ca - AN, "lưới mặc định không có video đã vào bộ"
    assert _ids(da_vao) == AN, "chip chỉ có video đã vào bộ, không có video đã dọn"
    assert _ids(ca_hai) == tat_ca, "không truyền ⇒ cả hai phía (client cũ)"
    assert (mac_dinh["tong"], da_vao["tong"], ca_hai["tong"]) == (8, 3, 11)
    assert mac_dinh["tong_vao_bo"] == da_vao["tong_vao_bo"] == ca_hai["tong_vao_bo"] == 3
    assert all(v["vao_bo"] for v in da_vao["videos"])
    assert not any(v["vao_bo"] for v in mac_dinh["videos"])


def test_nguoi_thuong_chi_thay_cua_minh_admin_thay_ca_kho(app_mod):
    assert _ids(app_mod.list_videos(limit=100, offset=0, vao_bo=1, nguoi_tao=KHAC)) == AN_KHAC
    sep = app_mod.list_videos(limit=100, offset=0, vao_bo=1, nguoi_tao=SEP)
    assert _ids(sep) == AN | AN_KHAC and sep["tong"] == sep["tong_vao_bo"] == 4


@pytest.mark.parametrize("vao_bo", [0, 1, None])
def test_tong_bang_tong_hang_moi_trang(app_mod, vao_bo):
    ids, cuoi = _moi_trang(app_mod, TOI, vao_bo)
    assert len(ids) == cuoi["tong"] and len(set(ids)) == len(ids)


@pytest.mark.parametrize("sai", [2, -1])
def test_vao_bo_ngoai_0_1_tra_400(app_mod, sai):
    with pytest.raises(HTTPException) as e:
        app_mod.list_videos(limit=10, offset=0, vao_bo=sai, nguoi_tao=TOI)
    assert e.value.status_code == 400


def test_cum_van_dem_chua_vao_cum_tren_ca_hai_phia(app_mod):
    """`/cum` không có chip: "chưa vào cụm" vẫn đếm mọi video còn sống."""
    assert app_mod.liet_ke_cum(nguoi_tao=TOI)["chua_vao_cum"] == 11
