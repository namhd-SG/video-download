"""Lô của cụm phía trang = lô phía server, kể cả khi thư viện vượt `LIBRARY_MAX`.

Trang cắt lô ở client (`app.js::videoCuaCum` + `chiaLo`), server cắt độc lập
(`models_chia._video_trong_lo`). Trước đây trang cắt trên `state.videos` — tối đa
`LIBRARY_MAX` video MỚI NHẤT — nên thành viên cũ của cụm rơi khỏi lô phía trang.
Nay trang cắt trên `khung_cum` của `GET /cum` (mọi thành viên, đúng thứ tự server),
và `moLoCum` từ chối gửi khi `video_ids` server trả về khác lô trang đã hiện.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from web import models, models_chia, models_cum

TOI = "toi@astronex.ai"
KHAC = "khac@astronex.ai"
SEP = "sep@astronex.ai"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HARNESS = Path(__file__).parent / "js" / "khung-cum.js"
LIBRARY_MAX = int(re.search(r"const LIBRARY_MAX = (\d+);",
                            (STATIC / "app.js").read_text(encoding="utf-8")).group(1))


def _luc(i: int) -> str:
    return f"2026-09-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+00:00"


def _them(db, job, vid, i):
    models.record_video(db, job_id=job, video_id=vid, url=f"https://t.co/{vid}", title=vid,
                        drive_file_id=f"1Drive_{vid}_AbCdEfGhIjKl", tao_luc=_luc(i))


def _an(db, vid, don=False):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES (?, '2026-09-20T00:00:00+00:00', ?, ?)",
                  (vid, "2026-09-27T00:00:00+00:00" if don else None, "test" if don else None))


def _loai(db, vid):
    with sqlite3.connect(db) as c:
        c.execute("UPDATE videos SET da_loai_luc = '2026-09-25T00:00:00+00:00' WHERE video_id = ?",
                  (vid,))


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    from web import app as mod
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(mod, "_la_admin", lambda email: email == SEP)
    return mod


@pytest.fixture
def kho(app_mod):
    """Ca Q3: cụm A của TOI 65 video (v003 ẩn, v010 ẩn+đã dọn, v020 đã loại);
    cụm K của KHAC (k02 ẩn); cụm S của admin SEP gom video của cả hai người."""
    db = app_mod.DB_PATH
    j_toi = models.create_job(db, "https://www.tiktok.com/tag/a", 65, TOI)
    j_khac = models.create_job(db, "https://www.tiktok.com/tag/b", 5, KHAC)
    for i in range(1, 66):
        _them(db, j_toi, f"v{i:03d}", i)
    for i in range(1, 6):
        _them(db, j_khac, f"k{i:02d}", 100 + i)
    a, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, a, TOI, TOI, [f"v{i:03d}" for i in range(1, 66)])
    k, _ = models_cum.tao_cum(db, KHAC, "Dance", "Khac", "solo")
    models_cum.gan_video(db, k, KHAC, KHAC, [f"k{i:02d}" for i in range(1, 6)])
    s, _ = models_cum.tao_cum(db, SEP, "Dance", "Sep", "mix")
    models_cum.gan_video(db, s, SEP, None, [f"v{i:03d}" for i in range(30, 41)] + ["k01", "k02"])
    _an(db, "v003")
    _an(db, "v010", don=True)
    _loai(db, "v020")
    _an(db, "k02")
    return db


def _node(vao: dict, tmp_path: Path, app_js: Path = STATIC / "app.js") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này KHÔNG chạy")
    f = tmp_path / "vao.json"
    f.write_text(json.dumps(vao), encoding="utf-8")
    r = subprocess.run([node, str(HARNESS), str(app_js), str(f)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _videos_trang(app_mod, nguoi):
    """Như `app.js::loadVideos`: nạp theo trang tới `LIBRARY_MAX` video mới nhất."""
    ra, offset = [], 0
    while len(ra) < LIBRARY_MAX:
        trang = app_mod.list_videos(limit=min(1000, LIBRARY_MAX - len(ra)), offset=offset,
                                    nguoi_tao=nguoi)
        ra += trang["videos"]
        offset += len(trang["videos"])
        if not trang["videos"] or offset >= trang["tong"]:
            break
    return ra, trang["da_don_trong_cum"]


def _lo_server(db, nguoi, chi_cua):
    ra = {}
    for c in models_cum.liet_ke_cum(db, nguoi, chi_cua):
        with models._connect(db) as conn:
            ra[str(c["id"])] = [[v["video_id"] + ("*" if v["da_don"] else "")
                                 for v in models_chia._video_trong_lo(conn, c, nguoi, chi_cua, thu)]
                                for thu in range(1, c["so_lo"] + 1)]
    return ra


@pytest.mark.parametrize("nguoi", [TOI, KHAC, SEP])
def test_lo_trang_tu_khung_bang_lo_server_moi_cum_moi_nguoi(app_mod, kho, nguoi, tmp_path):
    chi_cua = None if nguoi == SEP else nguoi
    res = app_mod.liet_ke_cum(nguoi_tao=nguoi)
    videos, da_don = _videos_trang(app_mod, nguoi)
    server = _lo_server(kho, nguoi, chi_cua)
    js = _node({"che_do": "lo", "videos": videos, "videosDaDon": da_don,
                "khungCum": res["khung_cum"], "cumIds": [c["id"] for c in res["cum"]]}, tmp_path)
    assert js == server
    for c in res["cum"]:
        assert len(js[str(c["id"])]) == c["so_lo"], "bất biến: số lô trang = so_lo server"


def test_khung_dung_tap_cat_lo(app_mod, kho):
    khung = app_mod.liet_ke_cum(nguoi_tao=TOI)["khung_cum"]
    vid = [g["video_id"] for g in khung]
    assert "v003" in vid, "ẩn thường vẫn giữ chỗ"
    assert {"video_id": "v010", "cum_id": khung[0]["cum_id"], "tao_luc": _luc(10),
            "da_don": True} in khung, "ẩn + đã dọn: giữ chỗ, đánh dấu da_don"
    assert "v020" not in vid, "đã loại: vắng"
    assert len(vid) == 64
    khung_sep = app_mod.liet_ke_cum(nguoi_tao=SEP)["khung_cum"]
    assert {g["video_id"] for g in khung_sep} == {f"v{i:03d}" for i in range(30, 41)} | {"k01", "k02"}, \
        "admin chỉ thấy khung cụm CỦA MÌNH, không thấy cụm người khác"


def test_thu_vien_vuot_library_max_lo_trang_van_bang_server(app_mod, tmp_path):
    """V_old nằm ngoài `LIBRARY_MAX` video mới nhất. Đường cũ (không khung) cắt ra
    [V_new] — sai; khung cho [V_old, V_new] như server."""
    db = app_mod.DB_PATH
    job = models.create_job(db, "https://www.tiktok.com/tag/c", 2000, TOI)
    n = LIBRARY_MAX + 3
    for i in range(n):
        _them(db, job, f"w{i:05d}", i)
    c, _ = models_cum.tao_cum(db, TOI, "Dance", "Lon", "xa")
    cu, moi = "w00000", f"w{n - 1:05d}"
    models_cum.gan_video(db, c, TOI, TOI, [cu, moi])
    res = app_mod.liet_ke_cum(nguoi_tao=TOI)
    videos, da_don = _videos_trang(app_mod, TOI)
    assert len(videos) == LIBRARY_MAX and cu not in {v["video_id"] for v in videos}
    server = _lo_server(db, TOI, TOI)
    assert server[str(c)] == [[cu, moi]]
    moi_ = _node({"che_do": "lo", "videos": videos, "videosDaDon": da_don,
                  "khungCum": res["khung_cum"], "cumIds": [c]}, tmp_path)
    cu_ = _node({"che_do": "lo", "videos": videos, "videosDaDon": da_don,
                 "khungCum": None, "cumIds": [c]}, tmp_path)
    assert moi_[str(c)] == server[str(c)]
    assert cu_[str(c)] == [[moi]], "đối chứng: đường cũ (state.videos) trượt đúng như lỗi đã biết"


def test_tao_cum_khong_nap_lai_videos_dau_cum_van_dung(app_mod, tmp_path):
    """Hồi quy: thao tác cụm chỉ gọi `loadCums()`. Gán 40 video rồi CHỈ nạp lại
    `/cum` (state.videos rỗng — chưa nạp lại `/videos`) ⇒ vẫn 2 lô, 40 video."""
    db = app_mod.DB_PATH
    job = models.create_job(db, "https://www.tiktok.com/tag/d", 40, TOI)
    for i in range(40):
        _them(db, job, f"x{i:02d}", i)
    c, _ = models_cum.tao_cum(db, TOI, "Dance", "Moi", "tao")
    models_cum.gan_video(db, c, TOI, TOI, [f"x{i:02d}" for i in range(40)])
    js = _node({"che_do": "loadCums", "res": app_mod.liet_ke_cum(nguoi_tao=TOI), "cumId": c},
               tmp_path)
    assert js == {"so_lo": 2, "so_song": 40, "so_lo_server": 2}


@pytest.fixture
def cum31(app_mod):
    db = app_mod.DB_PATH
    job = models.create_job(db, "https://www.tiktok.com/tag/e", 41, TOI)
    for i in range(1, 42):
        _them(db, job, f"y{i:02d}", i)
    c, _ = models_cum.tao_cum(db, TOI, "Dance", "Kiem", "lo")
    models_cum.gan_video(db, c, TOI, TOI, [f"y{i:02d}" for i in range(10, 41)])  # 31 ⇒ 2 lô
    return db, c


def _mo_lo(app_mod, db, c, thu, payload, tmp_path, res_cum=None):
    res = app_mod.liet_ke_cum(nguoi_tao=TOI)
    videos, _ = _videos_trang(app_mod, TOI)
    cum = next(x for x in res["cum"] if x["id"] == c)
    return _node({"che_do": "moLo", "videos": videos, "khungCum": res["khung_cum"], "cum": cum,
                  "thu": thu, "payload": payload, "resCum": res_cum or res}, tmp_path)


def test_payload_tra_video_ids_cua_lo(app_mod, cum31):
    db, c = cum31
    cum = models_cum.lay_cum(db, c, TOI, TOI)
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert p["video_ids"] == [f"y{i:02d}" for i in range(10, 40)]


def test_lo_khop_thi_gui_va_khong_mang_video_ids_sang_creative_desk(app_mod, cum31, tmp_path):
    db, c = cum31
    cum = models_cum.lay_cum(db, c, TOI, TOI)
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    js = _mo_lo(app_mod, db, c, 1, p, tmp_path)
    assert js["kq"] == "mo"
    assert f"POST /cum/{c}/lo/1/da-mo" in js["nhatKy"]
    assert set(js["payload"]) == {"v", "items", "nhan"}, "video_ids/so_video không thuộc hợp đồng v:1"


def test_tab_khac_gan_video_cu_hon_thi_khong_gui_va_nap_lai(app_mod, cum31, tmp_path):
    """Trang nạp khung, rồi tab khác gán y05 (cũ hơn mọi thành viên) ⇒ lô 1 của
    server dịch một ô. Bấm mở lô 1 ⇒ KHÔNG gửi, báo, nạp lại `/cum`."""
    db, c = cum31
    res_truoc = app_mod.liet_ke_cum(nguoi_tao=TOI)
    videos, _ = _videos_trang(app_mod, TOI)
    models_cum.gan_video(db, c, TOI, TOI, ["y05"])
    cum = models_cum.lay_cum(db, c, TOI, TOI)
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    res_sau = app_mod.liet_ke_cum(nguoi_tao=TOI)
    js = _node({"che_do": "moLo", "videos": videos, "khungCum": res_truoc["khung_cum"],
                "cum": next(x for x in res_truoc["cum"] if x["id"] == c), "thu": 1,
                "payload": p, "resCum": res_sau}, tmp_path)
    assert js["kq"] == "loi"
    assert js["payload"] is None, "không điều hướng tab sang Creative Desk"
    assert not any("da-mo" in x for x in js["nhatKy"]), "không ghi mốc đã mở"
    assert "close" in js["nhatKy"] and "GET /cum" in js["nhatKy"]
    assert any("Lô đã đổi" in t for t in js["toast"])
    assert js["khung_sau"] == res_sau["khung_cum"], "khung đã nạp lại"


def test_lo_doi_ma_nap_lai_hong_thi_khong_noi_da_nap_lai(app_mod, cum31, tmp_path):
    db, c = cum31
    res_truoc = app_mod.liet_ke_cum(nguoi_tao=TOI)
    videos, _ = _videos_trang(app_mod, TOI)
    models_cum.gan_video(db, c, TOI, TOI, ["y05"])
    p = models_chia.xay_payload_lo(db, models_cum.lay_cum(db, c, TOI, TOI), TOI, TOI, 1)
    js = _node({"che_do": "moLo", "videos": videos, "khungCum": res_truoc["khung_cum"],
                "cum": next(x for x in res_truoc["cum"] if x["id"] == c), "thu": 1,
                "payload": p, "loiNapCum": True}, tmp_path)
    assert js["kq"] == "loi" and js["payload"] is None
    assert not any("đã nạp lại" in t for t in js["toast"]), js["toast"]
    assert any("không nạp lại được" in t for t in js["toast"])


def test_khung_danh_da_don_thang_ban_da_nap_cu(tmp_path):
    """Khung mới hơn `state.videos`: video vừa bị dọn sau lượt nạp `/videos` vẫn
    nằm trong `state.videos`, nhưng khung đánh `da_don` ⇒ lô coi nó là đã dọn."""
    js = _node({"che_do": "lo", "cumIds": [1],
                "videos": [{"video_id": "a", "cum_id": 1}, {"video_id": "b", "cum_id": 1}],
                "khungCum": [{"video_id": "a", "cum_id": 1, "tao_luc": "1", "da_don": True},
                             {"video_id": "b", "cum_id": 1, "tao_luc": "2", "da_don": False}]},
               tmp_path)
    assert js == {"1": [["a*", "b"]]}


def test_server_cu_khong_tra_video_ids_van_gui(app_mod, cum31, tmp_path):
    db, c = cum31
    cum = models_cum.lay_cum(db, c, TOI, TOI)
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    del p["video_ids"]
    js = _mo_lo(app_mod, db, c, 1, p, tmp_path)
    assert js["kq"] == "mo" and js["payload"] is not None
