"""Dọn một video khỏi Drive KHÔNG được làm lô của cụm trượt.

Cụm 65 video ⇒ lô 30/30/5. Video số 5 (ở lô 1) được dọn ở ngày thứ 7. Lô 2 và lô 3
phải giữ NGUYÊN nội dung, lô 1 hụt đúng một item và nói ra "29/30" — cả phía server
(`models_chia._video_trong_lo`/`xay_payload_lo`) lẫn phía trang (`app.js::videoCuaCum`
+ `chiaLo`), vì hai bên cắt lô độc lập và phải cắt cùng một cách.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from web import models, models_chia, models_cum

TOI = "toi@astronex.ai"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HARNESS = Path(__file__).parent / "js"


def _id(i: int) -> str:
    return f"v{i:03d}"


def _luc(i: int) -> str:
    return f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}+00:00"


@pytest.fixture
def cum65(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 65, TOI)
    for i in range(1, 66):
        models.record_video(db, job_id=job, video_id=_id(i), url=f"https://t.co/{i}",
                            title=_id(i), drive_file_id=f"1Drive_{_id(i)}_AbCdEfGhIjKl",
                            tao_luc=_luc(i))
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, [_id(i) for i in range(1, 66)])
    return db, cum_id


def don(db, vid):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES (?, '2026-09-20T00:00:00+00:00', '2026-09-27T00:00:00+00:00', 'test')",
                  (vid,))


def _payloads(db, cum_id):
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    return cum, [models_chia.xay_payload_lo(db, cum, TOI, TOI, thu)
                 for thu in range(1, cum["so_lo"] + 1)]


def _ten(p):
    return [i["n"] for i in p["items"]]


def test_don_video_o_lo_1_giu_nguyen_lo_2_lo_3_va_nhan_x_tren_n(cum65):
    db, cum_id = cum65
    cum0, truoc = _payloads(db, cum_id)
    assert (cum0["so_lo"], [p["so_video"] for p in truoc]) == (3, [30, 30, 5])

    don(db, _id(5))
    cum1, sau = _payloads(db, cum_id)

    assert cum1["so_lo"] == 3, "số lô giữ nguyên"
    assert cum1["so_video"] == 64, "video còn thấy giảm một"
    assert _ten(sau[1]) == _ten(truoc[1]), "lô 2 giữ đúng nội dung"
    assert _ten(sau[2]) == _ten(truoc[2]), "lô 3 giữ đúng nội dung"
    assert sau[1]["so_video"] == 30 and sau[2]["so_video"] == 5
    assert _ten(sau[0]) == [n for n in _ten(truoc[0]) if n != _id(5)]
    assert (len(sau[0]["items"]), sau[0]["so_video"]) == (29, 30), "lô 1 hụt một item: 29/30"
    assert sau[0]["nhan"]["lo"] == {"thu": 1, "tong": 3}


def test_don_ca_lo_1_khong_lam_lo_2_thanh_lo_1(cum65):
    db, cum_id = cum65
    _, truoc = _payloads(db, cum_id)
    for i in range(1, 31):
        don(db, _id(i))
    cum, sau = _payloads(db, cum_id)
    assert cum["so_lo"] == 3
    assert sau[0]["items"] == [] and sau[0]["so_video"] == 30
    assert _ten(sau[1]) == _ten(truoc[1]) and _ten(sau[2]) == _ten(truoc[2])


def test_video_da_don_van_nam_trong_tap_cat_lo(cum65):
    db, cum_id = cum65
    don(db, _id(5))
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    with models._connect(db) as conn:
        lo1 = models_chia._video_trong_lo(conn, cum, TOI, TOI, 1)
    assert [v["video_id"] for v in lo1][:6] == [_id(i) for i in range(1, 7)]
    assert [v["da_don"] for v in lo1][:6] == [0, 0, 0, 0, 1, 0]


def test_da_don_trong_cum_tra_dung_khoa_cat(cum65):
    db, cum_id = cum65
    don(db, _id(5))
    ghost = models_cum.video_da_don_trong_cum(db, TOI, TOI)
    assert ghost == [{"video_id": _id(5), "cum_id": cum_id, "tao_luc": _luc(5)}]
    assert models_cum.video_da_don_trong_cum(db, "ai-do@astronex.ai", "ai-do@astronex.ai") == []


def _chay_node() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này KHÔNG chạy")
    r = subprocess.run([node, str(HARNESS / "lo-on-dinh-sau-don.js"), str(STATIC / "app.js")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_trang_cat_lo_giong_server_khi_co_video_da_don(cum65):
    """`videoCuaCum`+`chiaLo` (JS thật) cắt cùng lô với `_video_trong_lo`."""
    db, cum_id = cum65
    don(db, _id(5))
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    with models._connect(db) as conn:
        server = [[v["video_id"] + ("*" if v["da_don"] else "")
                   for v in models_chia._video_trong_lo(conn, cum, TOI, TOI, thu)]
                  for thu in range(1, cum["so_lo"] + 1)]
    js = _chay_node()
    assert js["sau"] == server
    assert [len(l) for l in js["sau"]] == [30, 30, 5]
    assert js["lanKhac"] == js["sau"], "ghost của cụm khác không lẫn vào cụm này"
    trung = [[x.rstrip("*") for x in l] for l in js["sau"]]
    assert trung == js["truoc"], "lô sau khi dọn = lô trước khi dọn (chỉ khác dấu *)"


def test_route_videos_mang_video_da_don_cua_cum_va_khong_hien_no_o_luoi(cum65, monkeypatch):
    from web import app as app_mod
    db, cum_id = cum65
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    don(db, _id(5))
    res = app_mod.list_videos(limit=200, offset=0, nguoi_tao=TOI)
    assert _id(5) not in {v["video_id"] for v in res["videos"]}, "video đã dọn không hiện ở lưới"
    assert res["tong"] == 64
    assert res["da_don_trong_cum"] == [{"video_id": _id(5), "cum_id": cum_id, "tao_luc": _luc(5)}]


def _ghi_an(db, vid, ngay_truoc):
    from datetime import datetime, timedelta, timezone
    luc = (datetime(2026, 9, 29, tzinfo=timezone.utc) - timedelta(days=ngay_truoc)).isoformat()
    models_vao_bo = __import__("web.models_vao_bo", fromlist=["x"])
    models_vao_bo.ghi_da_vao_bo(db, vid, TOI, [{"ban_copy_id": "c" + vid, "folder_id": "F",
                                                 "ma_bo": "N.1", "bang_chung": "properties"}], luc)


def test_payload_bo_item_qua_han_giu_nguon_chua_kip_don_va_giu_item_con_han(cum65):
    """Đường lô của cụm đọc lại DB: video ẩn ≥ 7 ngày mà lượt dọn chưa kịp lấy tệp đi thì
    KHÔNG gửi; video ẩn < 7 ngày (B3) vẫn gửi. `so_video` giữ nguyên ⇒ nhãn x/N."""
    from datetime import datetime, timezone
    db, cum_id = cum65
    _ghi_an(db, _id(5), 8)          # quá hạn, chưa dọn
    _ghi_an(db, _id(6), 6)          # còn hạn
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1,
                                   bay_gio=datetime(2026, 9, 29, tzinfo=timezone.utc))
    ten = _ten(p)
    assert _id(5) not in ten and _id(6) in ten
    assert (len(p["items"]), p["so_video"]) == (29, 30)
