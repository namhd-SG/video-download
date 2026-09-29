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


def test_videos_route_gan_vao_bo_cho_video_dang_an(kho):
    res = app_mod.list_videos(limit=200, offset=0, nguoi_tao=TOI)
    theo = {v["video_id"]: v for v in res["videos"]}
    assert set(theo) == {"v1", "v2", "v3"}, "v4 đã dọn: không hiện ở đâu"
    assert theo["v1"]["vao_bo"] is None
    se_don = (datetime.fromisoformat(AN) + timedelta(days=7)).isoformat()
    assert theo["v2"]["vao_bo"] == {"an_luc": AN, "se_don_luc": se_don, "ma_bo": ["N.2809C"]}
    assert theo["v3"]["vao_bo"]["ma_bo"] == ["N.2809C", "N.2909B"]
    assert res["tong"] == 3, "tong đếm cả video đang ẩn (trang lọc theo chip), không đếm video đã dọn"
