"""Lược đồ `video_vao_bo` / `video_vao_bo_ban` — thêm thuần tuý, không đụng bảng cũ."""
from __future__ import annotations

import sqlite3

import pytest

from web import models


def _cot(db, bang):
    with sqlite3.connect(db) as c:
        return [r[1] for r in c.execute(f"PRAGMA table_info({bang})")]


def test_hai_bang_moi_co_du_cot(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    assert _cot(db, "video_vao_bo") == [
        "video_id", "chu", "an_luc", "drive_don_luc", "ly_do_don", "so_lan_truot", "loi_cuoi"]
    assert _cot(db, "video_vao_bo_ban") == [
        "video_id", "ban_copy_id", "folder_id", "ma_bo", "bang_chung", "thay_luc"]


def test_init_db_hai_lan_khong_loi_va_khong_mat_du_lieu(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    with models._connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc) VALUES ('1', 'x')")
    models.init_db(db)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT video_id, an_luc FROM video_vao_bo").fetchall() == [("1", "x")]


def test_db_cu_khong_co_hai_bang_duoc_them_va_du_lieu_cu_con_nguyen(tmp_path):
    """Một jobs.db từ trước bản này: có `videos`, chưa có hai bảng mới."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, 1, "111", "https://t/1", drive_file_id="F" * 12)
    with sqlite3.connect(db) as c:
        c.execute("DROP TABLE video_vao_bo")
        c.execute("DROP TABLE video_vao_bo_ban")
    models.init_db(db)
    assert _cot(db, "video_vao_bo") and _cot(db, "video_vao_bo_ban")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT video_id, drive_file_id FROM videos").fetchall() == [("111", "F" * 12)]
        assert c.execute("SELECT COUNT(*) FROM video_vao_bo").fetchone()[0] == 0


def test_ban_copy_id_la_duy_nhat_va_bang_chung_chi_nhan_hai_gia_tri(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    ins = ("INSERT INTO video_vao_bo_ban (video_id, ban_copy_id, folder_id, ma_bo, bang_chung, "
           "thay_luc) VALUES (?, ?, 'F', 'N.2809C', ?, 't')")
    with models._connect(db) as c:
        c.execute(ins, ("1", "copy1", "properties"))
        c.execute(ins, ("2", "copy2", "md5_backfill"))
    with pytest.raises(sqlite3.IntegrityError):
        with models._connect(db) as c:
            c.execute(ins, ("3", "copy1", "properties"))   # cùng bản sao cho video khác
    with pytest.raises(sqlite3.IntegrityError):
        with models._connect(db) as c:
            c.execute(ins, ("4", "copy4", "doan_mo"))
