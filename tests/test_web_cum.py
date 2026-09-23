"""Cụm của tôi — schema, model và route (web/models_cum.py, web/app.py).

Gọi thẳng hàm route như tests/test_web_app.py (venv không có httpx), truyền
`nguoi_tao` thay cho dependency đã giải. Việc route thật sự đòi
`require_user` được canh riêng ở cuối tệp.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from web import app as app_mod
from web import models, models_cum
from web.auth import require_user

TOI = "toi@astronex.ai"
HO = "ho@astronex.ai"


@pytest.fixture
def kho(tmp_path, monkeypatch):
    """Kho hai chủ: video 1..5 của TOI, video 9 của HO. Không ai là admin."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.moi_admin_tu_env(db, [])
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job_toi = models.create_job(db, "https://www.tiktok.com/tag/a", 5, TOI)
    job_ho = models.create_job(db, "https://www.tiktok.com/tag/b", 5, HO)
    for vid in ("1", "2", "3", "4", "5"):
        models.record_video(db, job_id=job_toi, video_id=vid, url=f"u{vid}")
    models.record_video(db, job_id=job_ho, video_id="9", url="u9")
    return db


def _tao(nguoi=TOI, usecase="Dance", insight_goc="Badaboum", kieu="couple") -> dict:
    return app_mod.tao_cum(app_mod.TaoCumRequest(
        usecase=usecase, insight_goc=insight_goc, kieu=kieu), nguoi_tao=nguoi)


def _gan(cum_id, ids, nguoi=TOI, bo=False) -> dict:
    return app_mod.gan_video_cum(cum_id, app_mod.GanVideoCumRequest(
        video_ids=ids, bo=bo), nguoi_tao=nguoi)


def _so_video(cum_id, nguoi=TOI) -> int:
    return {c["id"]: c["so_video"]
            for c in app_mod.liet_ke_cum(nguoi_tao=nguoi)["cum"]}[cum_id]


# --- tên insight con ------------------------------------------------------

@pytest.mark.parametrize("goc,kieu,ten", [
    ("Badaboum", "couple", "Badaboum couple"),
    ("  Badaboum  ", "  couple ", "Badaboum couple"),
    ("Birthday   Virgo", "chibi\t3D", "Birthday Virgo chibi 3D"),
    ("Nhảy đôi", "hoạt hình", "Nhảy đôi hoạt hình"),
])
def test_insight_con_is_goc_space_kieu_trimmed_and_collapsed(goc, kieu, ten):
    assert models_cum.ten_insight_con(goc, kieu) == ten


def test_the_created_cluster_carries_the_same_name_the_payload_will(kho):
    c = _tao(insight_goc=" Badaboum ", kieu="  couple  ")
    assert c["insight"] == "Badaboum couple"
    assert (c["insight_goc"], c["kieu"], c["usecase"]) == ("Badaboum", "couple", "Dance")


@pytest.mark.parametrize("usecase,goc,kieu", [
    ("   ", "Badaboum", "couple"),
    ("x" * 81, "Badaboum", "couple"),
    ("Dance", "   ", "couple"),
    ("Dance", "Badaboum", "   "),
    ("Dance", "a" * 60, "b" * 60),   # 60 + 1 + 60 = 121 > 120
])
def test_labels_outside_the_contract_are_refused(kho, usecase, goc, kieu):
    with pytest.raises(HTTPException) as e:
        _tao(usecase=usecase, insight_goc=goc, kieu=kieu)
    assert e.value.status_code == 400


def test_so_lo_splits_by_thirty():
    assert [models_cum.so_lo(n) for n in (0, 1, 30, 31, 60, 64)] == [0, 1, 1, 2, 2, 3]


# --- một video một cụm ----------------------------------------------------

def test_assigning_to_b_moves_the_video_out_of_a(kho):
    a, b = _tao(kieu="couple")["id"], _tao(kieu="Cartoon")["id"]
    _gan(a, ["1", "2"])
    out = _gan(b, ["1"])

    assert out["so_video"] == 1
    assert _so_video(a) == 1 and _so_video(b) == 1
    with sqlite3.connect(kho) as conn:
        hang = conn.execute(
            "SELECT cum_id FROM video_cum WHERE video_id = '1' AND chu = ?", (TOI,)).fetchall()
    assert hang == [(b,)], "video 1 phải nằm ĐÚNG một cụm, và là cụm B"
    ids = {v["video_id"]: v["cum_id"] for v in app_mod.list_videos(nguoi_tao=TOI)["videos"]}
    assert ids["1"] == b and ids["2"] == a and ids["3"] is None


def test_unassign_returns_the_video_to_no_cluster(kho):
    a = _tao()["id"]
    _gan(a, ["1", "2"])
    out = _gan(a, ["1", "3"], bo=True)
    assert out["so_video"] == 1 and out["bo_qua"] == ["3"]
    assert _so_video(a) == 1
    assert app_mod.liet_ke_cum(nguoi_tao=TOI)["chua_vao_cum"] == 4


def test_chua_vao_cum_counts_the_rest_of_my_library(kho):
    a = _tao()["id"]
    assert app_mod.liet_ke_cum(nguoi_tao=TOI)["chua_vao_cum"] == 5
    _gan(a, ["1", "2"])
    assert app_mod.liet_ke_cum(nguoi_tao=TOI)["chua_vao_cum"] == 3


# --- quyền sở hữu ---------------------------------------------------------

def test_someone_else_does_not_see_my_clusters(kho):
    _tao()
    assert app_mod.liet_ke_cum(nguoi_tao=HO)["cum"] == []
    assert len(app_mod.liet_ke_cum(nguoi_tao=TOI)["cum"]) == 1   # control


def test_someone_else_cannot_assign_into_my_cluster(kho):
    a = _tao()["id"]
    with pytest.raises(HTTPException) as e:
        _gan(a, ["9"], nguoi=HO)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        _gan(a, ["1"], nguoi=HO, bo=False)
    assert e.value.status_code == 404
    # Đếm thẳng bảng, không qua `_so_video`: video 9 không thuộc thư viện của
    # TOI nên cách đếm theo thư viện sẽ không bao giờ thấy nó dù đã bị ghi vào.
    with sqlite3.connect(kho) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_cum").fetchone()[0] == 0


def test_someone_else_cannot_unassign_from_my_cluster(kho):
    a = _tao()["id"]
    _gan(a, ["1"])
    with pytest.raises(HTTPException) as e:
        _gan(a, ["1"], nguoi=HO, bo=True)
    assert e.value.status_code == 404
    assert _so_video(a) == 1


def test_i_cannot_put_someone_elses_video_into_my_cluster(kho):
    a = _tao()["id"]
    out = _gan(a, ["1", "9", "khong-co"])
    assert out["so_video"] == 1
    assert out["bo_qua"] == ["9", "khong-co"]
    with sqlite3.connect(kho) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_cum WHERE video_id = '9'").fetchone()[0] == 0


def test_a_removed_video_cannot_be_assigned(kho):
    a = _tao()["id"]
    models.danh_dau_da_loai(kho, "2", TOI)
    out = _gan(a, ["2"])
    assert out["so_video"] == 0 and out["bo_qua"] == ["2"]


def test_someone_else_cannot_rename_or_delete_my_cluster(kho):
    a = _tao()["id"]
    with pytest.raises(HTTPException) as e:
        app_mod.doi_kieu_cum(a, app_mod.DoiKieuRequest(kieu="hack"), nguoi_tao=HO)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        app_mod.xoa_cum(a, nguoi_tao=HO)
    assert e.value.status_code == 404
    c = app_mod.liet_ke_cum(nguoi_tao=TOI)["cum"]
    assert [(x["id"], x["kieu"]) for x in c] == [(a, "couple")]


def test_someone_else_cannot_mark_my_batch_opened(kho):
    a = _tao()["id"]
    _gan(a, ["1"])
    with pytest.raises(HTTPException) as e:
        app_mod.ghi_lo_da_mo(a, 1, nguoi_tao=HO)
    assert e.value.status_code == 404
    assert app_mod.liet_ke_cum(nguoi_tao=TOI)["cum"][0]["lo_mo"] == []


def test_videos_shows_my_cluster_not_theirs(kho, monkeypatch):
    """Admin thấy cả kho, nhưng `cum_id` trên từng video là cụm của CHÍNH người xem."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    models.moi_admin_tu_env(kho, ["sep@astronex.ai"])
    a = _tao()["id"]
    _gan(a, ["1"])
    sep = {v["video_id"]: v["cum_id"] for v in app_mod.list_videos(nguoi_tao="sep@astronex.ai")["videos"]}
    assert sep["1"] is None and "9" in sep
    assert app_mod.liet_ke_cum(nguoi_tao="sep@astronex.ai")["cum"] == []


# --- đổi kiểu / xoá -------------------------------------------------------

def test_changing_kieu_changes_the_insight_name(kho):
    a = _tao()["id"]
    c = app_mod.doi_kieu_cum(a, app_mod.DoiKieuRequest(kieu="  nhóm  nhảy "), nguoi_tao=TOI)
    assert c["kieu"] == "nhóm nhảy" and c["insight"] == "Badaboum nhóm nhảy"


def test_deleting_a_cluster_returns_its_videos_to_no_cluster(kho):
    a = _tao()["id"]
    _gan(a, ["1", "2"])
    app_mod.ghi_lo_da_mo(a, 1, nguoi_tao=TOI)
    assert app_mod.xoa_cum(a, nguoi_tao=TOI) == {"da_xoa": a}

    assert app_mod.liet_ke_cum(nguoi_tao=TOI) == {"cum": [], "chua_vao_cum": 5}
    assert all(v["cum_id"] is None for v in app_mod.list_videos(nguoi_tao=TOI)["videos"])
    with sqlite3.connect(kho) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_cum").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM cum_lo_mo").fetchone()[0] == 0
    # Video không bị loại khỏi thư viện — xoá cụm không phải xoá video.
    assert app_mod.list_videos(nguoi_tao=TOI)["tong"] == 5


def test_a_deleted_cluster_id_is_never_reused(kho):
    a = _tao()["id"]
    app_mod.xoa_cum(a, nguoi_tao=TOI)
    assert _tao()["id"] != a


# --- mốc lô đã mở ---------------------------------------------------------

def test_marking_a_batch_opened_is_recorded_per_batch(kho):
    a = _tao()["id"]
    _gan(a, ["1", "2"])
    out = app_mod.ghi_lo_da_mo(a, 1, nguoi_tao=TOI)
    assert out["thu"] == 1 and out["mo_luc"]
    lo = app_mod.liet_ke_cum(nguoi_tao=TOI)["cum"][0]["lo_mo"]
    assert lo == [{"thu": 1, "mo_luc": out["mo_luc"]}]

    lai = app_mod.ghi_lo_da_mo(a, 1, nguoi_tao=TOI)   # "Mở lại" làm mới mốc
    lo = app_mod.liet_ke_cum(nguoi_tao=TOI)["cum"][0]["lo_mo"]
    assert lo == [{"thu": 1, "mo_luc": lai["mo_luc"]}]
    assert lai["mo_luc"] >= out["mo_luc"]


def test_a_batch_outside_the_cluster_is_refused(kho):
    a = _tao()["id"]
    with pytest.raises(HTTPException) as e:   # cụm rỗng ⇒ 0 lô
        app_mod.ghi_lo_da_mo(a, 1, nguoi_tao=TOI)
    assert e.value.status_code == 400
    _gan(a, ["1"])
    for thu in (0, 2):
        with pytest.raises(HTTPException) as e:
            app_mod.ghi_lo_da_mo(a, thu, nguoi_tao=TOI)
        assert e.value.status_code == 400


# --- init_db --------------------------------------------------------------

def test_init_db_twice_keeps_clusters(kho):
    a = _tao()["id"]
    _gan(a, ["1"])
    models.init_db(kho)
    models.init_db(kho)
    assert _so_video(a) == 1


def test_init_db_upgrades_a_database_from_before_clusters(tmp_path):
    """DB có sẵn từ trước khi có cụm: chỉ có `jobs` và `videos` bản cũ."""
    db = tmp_path / "cu.db"
    with sqlite3.connect(db) as conn:
        conn.execute(models._SCHEMA)
        conn.execute(models._VIDEOS_SCHEMA)
        conn.execute("INSERT INTO jobs (url, tao_luc, nguoi_tao) VALUES ('u', 't', ?)", (TOI,))
    models.init_db(db)
    models.init_db(db)
    with sqlite3.connect(db) as conn:
        bang = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cum", "video_cum", "cum_lo_mo"} <= bang


# --- cửa ngoài -------------------------------------------------------------

@pytest.mark.parametrize("path,method", [
    ("/cum", "GET"), ("/cum", "POST"), ("/cum/{cum_id}", "PATCH"),
    ("/cum/{cum_id}", "DELETE"), ("/cum/{cum_id}/video", "POST"),
    ("/cum/{cum_id}/lo/{thu}/da-mo", "POST"),
])
def test_cluster_routes_require_a_verified_user(path, method):
    routes = [r for r in app_mod.app.routes
              if getattr(r, "path", None) == path and method in getattr(r, "methods", set())]
    assert routes, f"không tìm thấy route {method} {path}"
    assert any(d.call is require_user for d in routes[0].dependant.dependencies)
