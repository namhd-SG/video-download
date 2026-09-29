"""`GET /videos` mang `vao_bo` cho video đã vào bộ: mã bộ + ngày sẽ xoá (= an_luc + 7 ngày)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from web import app as app_mod
from web import models, models_vao_bo

TOI = "toi@astronex.ai"
AN = "2026-09-22T03:00:00+00:00"


@pytest.fixture
def kho(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 4, TOI)
    for i in range(1, 5):
        models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                            drive_file_id=f"1Drive_{i}_AbCdEfGhIjKl")
    b = lambda cid, ma: {"ban_copy_id": cid, "folder_id": "F" + cid, "ma_bo": ma,  # noqa: E731
                         "bang_chung": "properties"}
    models_vao_bo.ghi_da_vao_bo(db, "v2", TOI, [b("c1", "N.2809C")], AN)
    models_vao_bo.ghi_da_vao_bo(db, "v3", TOI, [b("c2", "N.2809C"), b("c3", "N.2909B")], AN)
    models_vao_bo.ghi_da_vao_bo(db, "v4", TOI, [b("c4", "N.1")], AN)
    models_vao_bo.ghi_don_drive(db, "v4", "da_don")
    return db


def test_videos_route_gan_vao_bo_cho_video_dang_an(kho, monkeypatch):
    monkeypatch.setenv("VIDEODL_BAT_DON_NGAY7", "1")
    res = app_mod.list_videos(limit=200, offset=0, nguoi_tao=TOI)
    theo = {v["video_id"]: v for v in res["videos"]}
    assert set(theo) == {"v1", "v2", "v3"}, "v4 đã dọn: không hiện ở đâu"
    assert theo["v1"]["vao_bo"] is None
    se_don = (datetime.fromisoformat(AN) + timedelta(days=7)).isoformat()
    assert theo["v2"]["vao_bo"] == {"an_luc": AN, "se_don_luc": se_don, "ma_bo": ["N.2809C"]}
    assert theo["v3"]["vao_bo"]["ma_bo"] == ["N.2809C", "N.2909B"]
    assert res["tong"] == 3, "tong đếm cả video đang ẩn (trang lọc theo chip), không đếm video đã dọn"


# --- trang quản trị: hàng dọn đang lỗi -----------------------------------------------------

def test_endpoint_don_loi_chi_liet_ke_hang_dang_loi(kho):
    models_vao_bo.ghi_truot_don(kho, "v2", "trash_file không ok")
    models_vao_bo.ghi_bao_dong(kho, "v1", TOI, "nguon_o_thung_rac_khong_ban_sao")
    res = app_mod.admin_don_vao_bo_loi(nguoi_tao="admin@astronex.ai")
    theo = {h["video_id"]: h for h in res["hang"]}
    assert res["so_hang"] == 2 and set(theo) == {"v1", "v2"}, "v3 lành, v4 đã dọn xong: không có"
    assert theo["v2"]["so_lan_truot"] == 1 and theo["v2"]["loi_cuoi"] == "trash_file không ok"
    assert theo["v1"]["loi_cuoi"] == "nguon_o_thung_rac_khong_ban_sao"
    assert theo["v1"]["drive_file_id"] == "1Drive_1_AbCdEfGhIjKl"


def test_endpoint_don_loi_chi_danh_cho_quan_tri(kho):
    from fastapi import HTTPException
    route = next(r for r in app_mod.app.routes if getattr(r, "path", "") == "/admin/don-vao-bo-loi")
    assert app_mod.require_admin in [d.call for d in route.dependant.dependencies], \
        "route phải đi qua require_admin (403 ở SERVER, không phải giấu nút)"
    with pytest.raises(HTTPException) as e:
        app_mod.require_admin(nguoi_tao="nguoi-thuong@astronex.ai")
    assert e.value.status_code == 403


def test_khi_don_ngay7_tat_api_khong_gui_se_don_luc_de_the_khong_hua_ngay_xoa(kho, monkeypatch):
    monkeypatch.delenv("VIDEODL_BAT_DON_NGAY7", raising=False)
    theo = {v["video_id"]: v for v in app_mod.list_videos(limit=200, offset=0,
                                                          nguoi_tao=TOI)["videos"]}
    assert theo["v2"]["vao_bo"]["se_don_luc"] is None
    assert theo["v2"]["vao_bo"]["ma_bo"] == ["N.2809C"], "mã bộ vẫn hiện"
    monkeypatch.setenv("VIDEODL_BAT_DON_NGAY7", "1")
    theo = {v["video_id"]: v for v in app_mod.list_videos(limit=200, offset=0,
                                                          nguoi_tao=TOI)["videos"]}
    assert theo["v2"]["vao_bo"]["se_don_luc"] is not None


def test_endpoint_don_loi_bao_so_id_do_loi_lap_chi_dem_khong_nguong(kho):
    models_vao_bo.ghi_tap_thu_lai(kho, {"v1": 3, "v2": 1})
    res = app_mod.admin_don_vao_bo_loi(nguoi_tao="admin@astronex.ai")
    assert res["do_loi_lap"] == {"so_id": 2, "lau_nhat_lan": 3}
    models_vao_bo.ghi_tap_thu_lai(kho, {})
    assert app_mod.admin_don_vao_bo_loi(nguoi_tao="a")["do_loi_lap"] == {"so_id": 0, "lau_nhat_lan": 0}
    import sqlite3
    with sqlite3.connect(kho) as c:
        c.execute("INSERT OR REPLACE INTO vao_bo_kv VALUES ('tap_thu_lai', 'hỏng')")
    assert app_mod.admin_don_vao_bo_loi(nguoi_tao="a")["do_loi_lap"]["so_id"] == 0, \
        "trang quản trị chỉ đọc: R hỏng không làm nó sập"


def test_endpoint_r_json_long_sau_khong_lam_endpoint_sap(kho):
    import sqlite3
    with sqlite3.connect(kho) as c:
        c.execute("INSERT OR REPLACE INTO vao_bo_kv VALUES ('tap_thu_lai', ?)",
                  ("[" * 100000 + "]" * 100000,))
    assert app_mod.admin_don_vao_bo_loi(nguoi_tao="a")["do_loi_lap"] == {"so_id": 0, "lau_nhat_lan": 0}
