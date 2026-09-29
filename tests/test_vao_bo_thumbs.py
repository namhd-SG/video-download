"""Dọn ảnh thumb của video đã dọn khỏi Drive — hệ quả của mốc dọn, so TÊN ĐẦY ĐỦ."""
from __future__ import annotations

import sqlite3

import pytest

from web import models, models_chia
from web.vao_bo_thumbs import don_thumbs

TOI = "toi@astronex.ai"


@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 5, TOI)
    thumbs = tmp_path / "thumbs"
    (thumbs / "khung").mkdir(parents=True)
    for vid in ("70", "7009", "5"):
        models.record_video(db, job_id=job, video_id=vid, url=f"u{vid}")
        (thumbs / f"{vid}.webp").write_bytes(b"x")
        for pt in (50, 90):
            (thumbs / "khung" / f"{vid}-{pt}.webp").write_bytes(b"x")
    return db, job, thumbs


def don(db, vid):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES (?, '2026-09-01T00:00:00+00:00', '2026-09-08T00:00:00+00:00', 'da_don')",
                  (vid,))


def ten(thumbs):
    return sorted([p.name for p in thumbs.glob("*.webp")] +
                  [f"khung/{p.name}" for p in (thumbs / "khung").glob("*.webp")])


def test_xoa_dung_anh_cua_video_da_don_khong_lay_nham_id_co_tien_to_trung(kho):
    db, job, thumbs = kho
    don(db, "70")
    kq = don_thumbs(db, thumbs)
    assert kq.tep_da_xoa == 3 and kq.video_da_xu_ly == 1
    assert ten(thumbs) == ["5.webp", "7009.webp", "khung/5-50.webp", "khung/5-90.webp",
                           "khung/7009-50.webp", "khung/7009-90.webp"]


def test_khong_xoa_anh_video_chua_don_va_khong_dong_toi_hang_videos(kho):
    db, job, thumbs = kho
    truoc = ten(thumbs)
    assert don_thumbs(db, thumbs).tep_da_xoa == 0 and ten(thumbs) == truoc
    with sqlite3.connect(db) as c:          # "7009" mới ẨN (7 ngày đầu): còn ảnh để xem lại
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc) VALUES ('7009', "
                  "'2026-09-28T00:00:00+00:00')")
    assert don_thumbs(db, thumbs).tep_da_xoa == 0 and ten(thumbs) == truoc
    don(db, "5")
    don_thumbs(db, thumbs)
    assert models.known_video_ids(db, ["5", "70", "7009"]) == {"5", "70", "7009"}


def test_khong_xoa_anh_video_dang_nam_trong_luot_chia_chua_xong(kho):
    db, job, thumbs = kho
    lan = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "k", "video_ids": ["70"]}]}])
    don(db, "70")
    assert don_thumbs(db, thumbs).tep_da_xoa == 0
    with sqlite3.connect(db) as c:
        c.execute("UPDATE chia_lan SET trang_thai = 'da_duyet'")
    assert don_thumbs(db, thumbs).tep_da_xoa == 3, "lượt đã duyệt xong thì ảnh không còn cần"


def test_tran_moi_luot_va_lan_sau_don_tiep(kho):
    db, job, thumbs = kho
    for v in ("70", "7009", "5"):
        don(db, v)
    assert don_thumbs(db, thumbs, toi_da=1).video_da_xu_ly == 1
    assert don_thumbs(db, thumbs, toi_da=1).video_da_xu_ly == 1
    assert don_thumbs(db, thumbs, toi_da=1).video_da_xu_ly == 1
    assert ten(thumbs) == []


def test_thumb_da_xoa_thi_route_tra_404_khong_500(kho, monkeypatch):
    from fastapi import HTTPException
    from web import app as app_mod
    db, job, thumbs = kho
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    don(db, "70")
    don_thumbs(db, thumbs)
    with pytest.raises(HTTPException) as e:
        app_mod.get_thumb("70", nguoi_tao=TOI)
    assert e.value.status_code == 404
