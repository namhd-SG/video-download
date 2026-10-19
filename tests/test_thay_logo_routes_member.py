"""Route member trang Thay logo: chỉ người tạo hoặc admin thấy/đánh giá; đánh giá chỉ khi đã thay xong; trạng thái worker chỉ admin."""
import json
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from fastapi import FastAPI, Request  # noqa: E402
from test_thay_logo_relay import _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky  # noqa: E402
from web import thay_logo_routes  # noqa: E402

ADMIN = "sep@x"


@pytest.fixture
def ctx(tmp_path):
    db = tmp_path / "tl.db"

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    worker = {"w": object()}
    thu_vien = {"a@x": {"A" * 20, "B" * 20, "F" * 20}}
    thay_logo_routes.dang_ky_route_member(app, lambda: db, require_user, lambda e: e == ADMIN, lambda: worker["w"],
                                          lambda email, ids: thu_vien.get(email, set()) & set(ids))
    mc = MayChu(app)
    c = _Client(mc)
    c.worker = worker
    yield c, db
    mc.dung()


def _h(u):
    return {"x-user": u}


def _xong(db, nguoi="a@x"):
    conn = nhat_ky.mo(db)
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, nguoi, [{"kieu": "drive", "file_id": "F" * 20}])
    vid = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
    log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
    hang_doi.dat(conn, vid, "xong", video_log_id=log_id)
    conn.close()
    return vid, log_id


def test_tao_job_kiem_ma_drive_va_luu_nguoi_tao(ctx):
    c, db = ctx
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["../etc/passwd"], "ten_bo": "Bộ thử"}).status_code == 400
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": [], "ten_bo": "Bộ thử"}).status_code == 422
    r = c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20, "A" * 20, "B" * 20], "ten_bo": "Bộ thử"})
    assert r.status_code == 201
    v = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]
    assert len(v) == 2 and all(x["nguoi_tao"] == "a@x" and x["trang_thai"] == "cho" for x in v)  # trùng mã ⇒ một video


def test_nguoi_khac_khong_thay_khong_danh_gia_duoc_admin_thi_duoc(ctx):
    c, db = ctx
    vid, _ = _xong(db)
    assert c.get("/api/thay-logo/videos", headers=_h("b@x")).json()["videos"] == []
    assert len(c.get("/api/thay-logo/videos", headers=_h(ADMIN)).json()["videos"]) == 1
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h("b@x"), json={"ket_qua": "dat"}).status_code == 403
    assert c.get(f"/api/thay-logo/videos/{vid}/sheet.jpg", headers=_h("b@x")).status_code == 403
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h(ADMIN), json={"ket_qua": "dat"}).status_code == 204


def test_danh_gia_ghi_vao_nhat_ky_va_hong_bat_buoc_loai_loi(ctx):
    c, db = ctx
    vid, log_id = _xong(db)
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h("a@x"), json={"ket_qua": "hong"}).status_code == 400
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h("a@x"),
                  json={"ket_qua": "hong", "loai_loi": "che_phu_de", "ghi_chu": "giây 3"}).status_code == 204
    conn = nhat_ky.mo(db)
    r = conn.execute("SELECT video_id, member, ket_qua, loai_loi FROM tl_danh_gia").fetchone()
    assert tuple(r) == (log_id, "a@x", "hong", "che_phu_de")
    v = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"][0]
    assert v["danh_gia"] == "hong"


def test_chua_xong_thi_khong_danh_gia(ctx):
    c, db = ctx
    c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20], "ten_bo": "Bộ thử"})
    vid = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"][0]["id"]
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h("a@x"), json={"ket_qua": "dat"}).status_code == 409


def test_trang_thai_worker_chi_admin_va_tinh_nang_tat_thi_khong_nhan_luot_moi(ctx):
    c, _ = ctx
    c.worker["w"] = None
    assert c.get("/api/thay-logo/admin/worker", headers=_h("a@x")).status_code == 403
    assert c.get("/api/thay-logo/admin/worker", headers=_h(ADMIN)).json() == {"song": False, "luot_cuoi": "tinh_nang_tat"}
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20], "ten_bo": "Bộ thử"}).status_code == 409


def test_member_chi_chon_duoc_video_trong_thu_vien_cua_minh(ctx):
    c, _ = ctx
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20, "Z" * 20], "ten_bo": "Bộ thử"}).status_code == 403
    assert c.post("/api/thay-logo/jobs", headers=_h("b@x"), json={"drive_file_ids": ["A" * 20], "ten_bo": "Bộ thử"}).status_code == 403
    assert c.post("/api/thay-logo/jobs", headers=_h(ADMIN), json={"drive_file_ids": ["Z" * 20], "ten_bo": "Bộ thử"}).status_code == 201


def test_tran_video_cho_moi_nguoi(ctx, monkeypatch):
    c, _ = ctx
    monkeypatch.setattr(thay_logo_routes, "TRAN_CHO_MOI_NGUOI", 2)
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20, "B" * 20], "ten_bo": "Bộ thử"}).status_code == 201
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["F" * 20], "ten_bo": "Bộ thử"}).status_code == 429


def test_mo_danh_sach_khi_chua_co_db_khong_tao_db(ctx):
    c, db = ctx
    assert not db.exists()
    assert c.get("/api/thay-logo/videos", headers=_h("a@x")).json() == {"videos": [], "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False}
    assert not db.exists()


def test_drive_ids_cua_dung_dinh_nghia_so_huu_cua_thu_vien(tmp_path):
    import sqlite3
    db = tmp_path / "jobs.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, nguoi_tao TEXT)")
        c.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, job_id INTEGER, drive_file_id TEXT)")
        c.executemany("INSERT INTO jobs VALUES (?,?)", [(1, "a@x"), (2, "b@x")])
        c.executemany("INSERT INTO videos (job_id, drive_file_id) VALUES (?,?)", [(1, "A" * 20), (2, "B" * 20)])
    assert thay_logo_routes.drive_ids_cua(db, "a@x", ["A" * 20, "B" * 20]) == {"A" * 20}
    assert thay_logo_routes.drive_ids_cua(tmp_path / "khong-co.db", "a@x", ["A" * 20]) == set()


# ---------------------------------------------------------------- tên bộ · /bo · lọc /videos · ghép thư viện

def _jobs_db(db, hang=()):
    """`jobs.db` giả nằm cạnh `tl.db` (route mặc định tìm ở đó). `hang`: (drive_file_id, video_id, title, nen_tang, nguoi_tao)."""
    import sqlite3
    with sqlite3.connect(db.parent / "jobs.db") as c:
        c.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, nguoi_tao TEXT, nen_tang TEXT)")
        # `url` NOT NULL như bảng thật (`web/models.py`): route đọc link gốc cho hand-off "Tạo bộ tự tìm".
        c.execute("CREATE TABLE IF NOT EXISTS videos (video_id TEXT PRIMARY KEY, job_id INTEGER, title TEXT, drive_file_id TEXT, "
                  "url TEXT NOT NULL DEFAULT '')")
        for i, (fid, vid, title, nt, nguoi) in enumerate(hang, 1):
            c.execute("INSERT INTO jobs VALUES (?,?,?)", (i, nguoi, nt))
            c.execute("INSERT INTO videos VALUES (?,?,?,?,?)", (vid, i, title, fid, f"https://x/{vid}"))


def _bo(db, nguoi, ten, fids, tao_luc=None):
    conn = nhat_ky.mo(db)
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, nguoi, [{"kieu": "drive", "file_id": f} for f in fids], "", ten)
    if tao_luc is not None:
        conn.execute("UPDATE tl_job SET tao_luc=? WHERE id=?", (tao_luc, j))
        conn.commit()
    vids = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (j,))]
    conn.close()
    return j, vids


def _dat(db, vid, tt, danh_gia=None):
    conn = nhat_ky.mo(db)
    log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
    hang_doi.dat(conn, vid, tt, video_log_id=log_id)
    if danh_gia:
        nhat_ky.ghi_danh_gia(conn, log_id, "a@x", danh_gia, "che_phu_de" if danh_gia == "hong" else None)
    conn.close()


def test_ten_bo_bat_buoc_cat_khoang_trang_1_den_80_ky_tu(ctx):
    c, db = ctx
    body = {"drive_file_ids": ["A" * 20]}
    for sai in ({}, {"ten_bo": ""}, {"ten_bo": "   "}, {"ten_bo": None}, {"ten_bo": "x" * 81}, {"ten_bo": "a\nb"}):
        assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={**body, **sai}).status_code == 400, sai
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={**body, "ten_bo": "  09/10-1  "}).status_code == 201
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={**body, "ten_bo": "x" * 80}).status_code == 201
    got = [r[0] for r in nhat_ky.mo(db).execute("SELECT ten_bo FROM tl_job ORDER BY id")]
    assert got == ["09/10-1", "x" * 80]  # 400 không để lại job


def test_ten_bo_sai_van_giu_cac_kiem_cu(ctx):
    c, _ = ctx
    # tên bộ hợp lệ KHÔNG đẩy qua cổng thư viện của member
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["Z" * 20], "ten_bo": "ok"}).status_code == 403


def test_bo_dem_theo_trang_thai_va_danh_gia(ctx):
    c, db = ctx
    j, v = _bo(db, "a@x", "Bộ 1", [chr(65 + i) * 20 for i in range(6)])
    _dat(db, v[0], "xong", "dat")
    _dat(db, v[1], "xong", "hong")
    _dat(db, v[2], "xong")
    _dat(db, v[3], "cho_nguoi")
    _dat(db, v[4], "loi")  # v[5] còn "cho"
    conn = nhat_ky.mo(db)
    conn.execute("UPDATE tl_job SET thu_muc_ra_id='FOLDER1' WHERE id=?", (j,))
    conn.commit()
    conn.close()
    r = c.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"]
    assert len(r) == 1
    b = r[0]
    assert (b["job_id"], b["ten_bo"], b["nguon_kieu"], b["thu_muc_ra_id"]) == (j, "Bộ 1", "drive", "FOLDER1")
    assert (b["tong"], b["xong"], b["cho_duyet"], b["cho_nguoi"], b["loi"], b["dat"], b["hong"]) == (6, 3, 1, 1, 1, 1, 1)
    assert isinstance(b["tao_luc"], float)


def test_bo_job_cu_khong_ten_hien_luot_id(ctx):
    c, db = ctx
    conn = nhat_ky.mo(db)
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, "a@x", [{"kieu": "drive", "file_id": "A" * 20}])  # không tên bộ = job trước khi có tính năng
    conn.close()
    assert c.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"][0]["ten_bo"] == f"Lượt #{j}"
    assert c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"][0]["ten_bo"] == f"Lượt #{j}"


def test_bo_member_chi_thay_bo_cua_minh_admin_thay_het(ctx):
    c, db = ctx
    _bo(db, "a@x", "của a", ["A" * 20])
    _bo(db, "b@x", "của b", ["B" * 20])
    assert [b["ten_bo"] for b in c.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"]] == ["của a"]
    assert [b["ten_bo"] for b in c.get("/api/thay-logo/bo", headers=_h("b@x")).json()["bo"]] == ["của b"]
    assert c.get("/api/thay-logo/bo", headers=_h("c@x")).json()["bo"] == []
    assert {b["ten_bo"] for b in c.get("/api/thay-logo/bo", headers=_h(ADMIN)).json()["bo"]} == {"của a", "của b"}


def test_bo_chua_co_db_khong_tao_db(ctx):
    c, db = ctx
    assert c.get("/api/thay-logo/bo", headers=_h("a@x")).json() == {"bo": []}
    assert not db.exists()


def test_videos_ghep_thu_vien_va_loc(ctx):
    c, db = ctx
    _jobs_db(db, [("A" * 20, "111", "Video A", "tiktok", "a@x"), ("B" * 20, "fb-9", "Video B", "facebook", "a@x")])
    j1, (v1,) = _bo(db, "a@x", "Bộ 1", ["A" * 20], tao_luc=1_700_000_000)
    j2, (v2, v3) = _bo(db, "a@x", "Bộ 2", ["B" * 20, "F" * 20], tao_luc=1_800_000_000)
    _dat(db, v2, "xong")
    ds = lambda q, u="a@x": c.get(f"/api/thay-logo/videos{q}", headers=_h(u)).json()["videos"]  # noqa: E731
    d = {x["id"]: x for x in ds("")}
    assert len(d) == 3
    assert (d[v1]["ten_bo"], d[v1]["ten_video"], d[v1]["anh_bia"], d[v1]["nen_tang"]) == ("Bộ 1", "Video A", "/thumbs/111", "tiktok")
    assert (d[v2]["ten_video"], d[v2]["anh_bia"], d[v2]["nen_tang"]) == ("Video B", "/thumbs/fb-9", "facebook")
    assert (d[v3]["ten_video"], d[v3]["anh_bia"], d[v3]["nen_tang"]) == (None, None, None)  # không có trong thư viện ⇒ null, vẫn hiện
    assert {x["id"] for x in ds(f"?job_id={j1}")} == {v1}
    assert {x["id"] for x in ds("?trang_thai=xong")} == {v2}
    assert {x["id"] for x in ds("?nen_tang=facebook")} == {v2}
    assert {x["id"] for x in ds("?nen_tang=tiktok")} == {v1}
    assert {x["id"] for x in ds("?tu=1750000000")} == {v2, v3}
    assert {x["id"] for x in ds("?den=1750000000")} == {v1}
    assert {x["id"] for x in ds(f"?job_id={j2}&trang_thai=cho")} == {v3}
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ngay1 = datetime.fromtimestamp(1_700_000_000, ZoneInfo("Asia/Saigon")).strftime("%Y-%m-%d")  # ngày theo giờ VN; `den` tính HẾT ngày
    assert {x["id"] for x in ds(f"?tu={ngay1}&den={ngay1}")} == {v1}
    assert c.get("/api/thay-logo/videos?tu=hom-qua", headers=_h("a@x")).status_code == 400


def test_video_co_trong_thu_vien_ma_title_null_van_co_ten_hien_thi(ctx):
    """Có hàng thư viện mà title NULL/rỗng ⇒ tên dự phòng (để trang không nói dối "không còn trong thư viện"); không có hàng ⇒ vẫn null."""
    c, db = ctx
    _jobs_db(db, [("A" * 20, "111", None, "tiktok", "a@x"), ("B" * 20, "112", "", "tiktok", "a@x")])
    _, (v1, v2, v3) = _bo(db, "a@x", "Bộ", ["A" * 20, "B" * 20, "F" * 20])
    d = {x["id"]: x for x in c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]}
    assert d[v1]["ten_video"] == "Video không tên" and d[v2]["ten_video"] == "Video không tên"
    assert d[v3]["ten_video"] is None


def test_videos_loc_khong_pha_cong_quyen_member(ctx):
    c, db = ctx
    _jobs_db(db, [("A" * 20, "111", "Video A", "tiktok", "a@x")])
    j, (v,) = _bo(db, "a@x", "Bộ của a", ["A" * 20])
    _dat(db, v, "xong")
    q = f"?job_id={j}&trang_thai=xong&nen_tang=tiktok&tu=0"
    assert len(c.get(f"/api/thay-logo/videos{q}", headers=_h("a@x")).json()["videos"]) == 1
    assert c.get(f"/api/thay-logo/videos{q}", headers=_h("b@x")).json()["videos"] == []  # b dò đúng job_id của a: không thấy gì
    assert c.get("/api/thay-logo/videos", headers=_h("b@x")).json()["videos"] == []
    assert len(c.get(f"/api/thay-logo/videos{q}", headers=_h(ADMIN)).json()["videos"]) == 1


def test_videos_khong_co_jobs_db_van_tra_dong_khong_ten(ctx):
    c, db = ctx
    _bo(db, "a@x", "Bộ", ["A" * 20])
    v = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]
    assert len(v) == 1 and v[0]["ten_video"] is None and v[0]["nen_tang"] is None


def test_bo_dem_dat_hong_theo_danh_gia_moi_nhat(ctx):
    c, db = ctx
    j, (v1, v2) = _bo(db, "a@x", "B", ["A" * 20, "B" * 20])
    _dat(db, v1, "xong", "hong")
    conn = nhat_ky.mo(db)  # cùng video: hỏng trước, đạt SAU ⇒ tính là đạt
    log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (v1,)).fetchone()[0]
    conn.execute("UPDATE tl_danh_gia SET luc = luc - 100")
    nhat_ky.ghi_danh_gia(conn, log_id, "a@x", "dat")
    conn.close()
    _dat(db, v2, "xong", "hong")
    b = c.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"][0]
    assert (b["dat"], b["hong"], b["cho_duyet"], b["xong"]) == (1, 1, 0, 2)
    # cùng câu trả lời với dòng video (`danh_gia` lấy đánh giá mới nhất)
    dg = {x["id"]: x["danh_gia"] for x in c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]}
    assert dg == {v1: "dat", v2: "hong"}


def _nhieu(db, n, nen_tang_cua=lambda i: "tiktok"):
    """n video trong MỘT bộ; thư viện có đủ. Trả job_id."""
    fids = [f"V{i:05d}" + "x" * 10 for i in range(n)]
    _jobs_db(db, [(f, f"vid{i}", f"T{i}", nen_tang_cua(i), "a@x") for i, f in enumerate(fids)])
    return _bo(db, "a@x", "Bộ lớn", fids)[0]


def test_videos_gioi_han_300_trong_sql_va_bao_con_nua(ctx):
    c, db = ctx
    _nhieu(db, 305)
    r = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()
    tat_ca = [r_[0] for r_ in nhat_ky.mo(db).execute("SELECT id FROM tl_job_video ORDER BY id DESC")]
    assert [v["id"] for v in r["videos"]] == tat_ca[:300] and r["con_nua"] is True  # ĐÚNG 300 id mới nhất, theo thứ tự
    r2 = c.get(f"/api/thay-logo/videos?truoc_id={r['truoc_tiep']}", headers=_h("a@x")).json()
    assert [v["id"] for v in r2["videos"]] == tat_ca[300:] and r2["con_nua"] is False and r2["truoc_tiep"] is None
    _nhieu_nho = c.get("/api/thay-logo/videos?job_id=999", headers=_h("a@x")).json()
    assert _nhieu_nho == {"videos": [], "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False}


def test_videos_loc_nen_tang_doc_nhieu_lo_den_khi_du_300(ctx):
    c, db = ctx
    _nhieu(db, 650, lambda i: "tiktok" if i % 2 == 0 else "facebook")  # 325 khớp mỗi nền tảng, rải đều khắp các lô
    r = c.get("/api/thay-logo/videos?nen_tang=facebook", headers=_h("a@x")).json()
    fb = [r_[0] for r_ in nhat_ky.mo(db).execute("SELECT id FROM tl_job_video ORDER BY id DESC") if r_[0] % 2 == 0]
    # video thứ i (0-based) có id i+1; i lẻ ⇒ facebook ⇒ id chẵn
    assert [v["id"] for v in r["videos"]] == fb[:300] and r["con_nua"] is True  # ĐÚNG 300 facebook mới nhất, không sót/lặp
    r_2 = c.get(f"/api/thay-logo/videos?nen_tang=facebook&truoc_id={r['truoc_tiep']}", headers=_h("a@x")).json()
    assert [v["id"] for v in r_2["videos"]] == fb[300:] and r_2["con_nua"] is False
    r2 = c.get("/api/thay-logo/videos?nen_tang=facebook&job_id=1&tu=0", headers=_h("a@x")).json()
    assert len(r2["videos"]) == 300
    r3 = c.get("/api/thay-logo/videos?nen_tang=zalo", headers=_h("a@x")).json()
    assert r3 == {"videos": [], "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False}


def test_videos_loc_nen_tang_it_hon_300_khong_con_nua(ctx):
    c, db = ctx
    _nhieu(db, 40, lambda i: "tiktok" if i < 7 else "facebook")
    r = c.get("/api/thay-logo/videos?nen_tang=tiktok", headers=_h("a@x")).json()
    assert len(r["videos"]) == 7 and r["con_nua"] is False


def test_thu_vien_khong_doc_duoc_loc_nen_tang_thi_503_khong_loc_thi_van_tra(ctx, caplog):
    c, db = ctx
    _bo(db, "a@x", "Bộ", ["A" * 20])
    (db.parent / "jobs.db").write_bytes(b"day khong phai sqlite")  # đọc lỗi `file is not a database`
    import logging
    with caplog.at_level(logging.WARNING):
        r = c.get("/api/thay-logo/videos", headers=_h("a@x"))
    assert r.status_code == 200 and r.json()["videos"][0]["nen_tang"] is None and "không đọc được thư viện" in caplog.text
    assert c.get("/api/thay-logo/videos?nen_tang=tiktok", headers=_h("a@x")).status_code == 503


def test_tu_den_bien_deu_400_khong_500(ctx):
    c, db = ctx
    _bo(db, "a@x", "B", ["A" * 20])
    for q in ("tu=9999-12-31&den=9999-12-31", "den=9999-12-31", "tu=0001-01-01", "den=0001-01-01", "tu=nan", "den=inf", "tu=1e999",
              "tu=-inf", "tu=2026-13-45", "tu=abc"):
        r = c.get(f"/api/thay-logo/videos?{q}", headers=_h("a@x"))
        assert r.status_code in (200, 400), q  # không bao giờ 500
    for q in ("tu=nan", "den=inf", "tu=1e999", "tu=-inf", "tu=2026-13-45", "tu=abc", "den=9999-12-31"):
        assert c.get(f"/api/thay-logo/videos?{q}", headers=_h("a@x")).status_code == 400, q


def test_trang_thai_ngoai_tap_hop_le_la_400(ctx):
    c, db = ctx
    _bo(db, "a@x", "B", ["A" * 20])
    assert c.get("/api/thay-logo/videos?trang_thai=bay_ba", headers=_h("a@x")).status_code == 400
    assert c.get("/api/thay-logo/videos?trang_thai=cho", headers=_h("a@x")).status_code == 200


def test_con_nua_khong_duong_gia_khi_cham_tran_quet(ctx, monkeypatch):
    c, db = ctx
    _nhieu(db, 40, lambda i: "tiktok")
    monkeypatch.setattr(thay_logo_routes, "TRAN_TRANG_VIDEO", 10)
    monkeypatch.setattr(thay_logo_routes, "TRAN_QUET_VIDEO", 22)  # 11 + 11 dòng/lô ⇒ chạm trần khi còn 18 dòng
    r = c.get("/api/thay-logo/videos?nen_tang=facebook", headers=_h("a@x")).json()
    assert r["videos"] == [] and r["con_nua"] is True and r["truoc_tiep"] is not None  # còn dòng chưa đọc ⇒ thật sự còn
    monkeypatch.setattr(thay_logo_routes, "TRAN_QUET_VIDEO", 11)
    r = c.get("/api/thay-logo/videos?nen_tang=facebook&truoc_id=3", headers=_h("a@x")).json()
    assert r["con_nua"] is False  # còn 2 dòng (id 1, 2) nhưng lô <= trần ⇒ đã hết, không dương giả


def test_thu_vien_loi_bao_trong_phan_hoi(ctx):
    c, db = ctx
    _bo(db, "a@x", "Bộ", ["A" * 20])
    assert c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["thu_vien_loi"] is True  # chưa có jobs.db
    _jobs_db(db, [("A" * 20, "1", "T", "tiktok", "a@x")])
    assert c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["thu_vien_loi"] is False


def test_job_id_ngoai_mien_la_422_khong_500(ctx):
    c, db = ctx
    _bo(db, "a@x", "B", ["A" * 20])
    for q in ("job_id=0", "job_id=-1", f"job_id={2**63}", "job_id=99999999999999999999", "truoc_id=0"):
        assert c.get(f"/api/thay-logo/videos?{q}", headers=_h("a@x")).status_code in (400, 422), q


def test_post_jobs_cong_cam_vinh_vien_409_loi_tam_van_nhan(ctx):
    c, db = ctx

    class W:
        ly_do_khong_nhan = None
    c.worker["w"] = W()
    body = {"drive_file_ids": ["A" * 20], "ten_bo": "B"}
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json=body).status_code == 201  # chưa kiểm xong / lỗi tạm ⇒ nhận
    W.ly_do_khong_nhan = "thư mục đầu ra nằm trong cây 'Creative' (bí mật)"
    r = c.post("/api/thay-logo/jobs", headers=_h("a@x"), json=body)
    assert r.status_code == 409 and "báo quản trị" in r.json()["detail"] and "Creative" not in r.json()["detail"]  # member không thấy chi tiết


# ---------------------------------------------------------------- đợt 2A: POST/GET /bo/{job_id}/ap, POST /bo/{job_id}/hoan-tac
F_AP = "FOLDERBO1" + "f" * 12
BAN_AP = {1: "BANCOPY0001" + "a" * 10, 2: "BANCOPY0002" + "b" * 10, 3: "BANCOPY0003" + "c" * 10}


@pytest.fixture
def ap(tmp_path, monkeypatch):
    """Lượt `vao_bo` thật: `jobs.db` (models), `POST /jobs` qua route (producer thật), video xong + Đạt; worker có `bat_dau_ap` chạy
    thread `tl-ap` THẬT trên DB file và Drive giả. Cờ `TL_AP_VAO_BO=1` (chỉ trong tiến trình test)."""
    import types

    from drive_gia_thay_logo import DriveGiaTL

    from tiktok_music_downloader.thay_logo import ap_vao_bo
    from web import models, models_vao_bo

    monkeypatch.setenv(ap_vao_bo.ENV_BAT, "1")
    jobs = tmp_path / "jobs.db"
    models.init_db(jobs)
    ja = models.create_job(jobs, "https://x/a", 2, "a@x", nen_tang="tiktok")
    jb = models.create_job(jobs, "https://x/b", 1, "b@x", nen_tang="tiktok")
    for i, j in ((1, ja), (2, ja), (3, jb)):
        models.record_video(jobs, j, f"V{i}", f"https://x/v{i}", title=f"T{i}", drive_file_id=f"SRC{i}" + "x" * 12)
        models_vao_bo.ghi_da_vao_bo(jobs, f"V{i}", "a@x" if i < 3 else "b@x",
                                    [dict(ban_copy_id=BAN_AP[i], folder_id=F_AP, ma_bo="N.1AAAA", bang_chung="properties")])
    drive = DriveGiaTL()
    drive.them_thu_muc(F_AP, "N.1AAAA")
    drive.them_thu_muc("DAURA00000" + "o" * 10, "Thay logo - đầu ra")
    for i in (1, 2, 3):
        drive.them_file(BAN_AP[i], f"v{i}.mp4", F_AP, md5=f"MD5-{i}", size=str(100 * i))
        drive.them_file(f"RA{i:04d}" + "r" * 14, f"ra{i}.mp4", "DAURA00000" + "o" * 10, md5=f"MD5-RA{i}", size=str(90 * i))
    log_db = tmp_path / "tl.db"

    def mo():
        conn = nhat_ky.mo(log_db)
        hang_doi.khoi_tao(conn)
        return conn

    luong: list = []
    worker = types.SimpleNamespace(drive_tl=drive, ly_do_khong_nhan=None,
                                   bat_dau_ap=lambda job_id: luong.append(ap_vao_bo.chay_nen(mo, drive, job_id)))

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    box = {"w": worker}
    thay_logo_routes.dang_ky_route_member(app, lambda: log_db, require_user, lambda e: e == ADMIN, lambda: box["w"],
                                          lambda email, ids: set(), lay_jobs_db=lambda: jobs)
    mc = MayChu(app)
    c = _Client(mc)
    c.drive, c.mo, c.box, c.jobs, c.luong = drive, mo, box, jobs, luong

    def tao(nguoi, cac, dat=True):
        r = c.post("/api/thay-logo/jobs", headers=_h(nguoi), json={"vao_bo": [{"video_id": f"V{i}", "ban_copy_id": BAN_AP[i]} for i in cac],
                                                                   "ten_bo": "N.1AAAA"})
        assert r.status_code == 201, r.content
        jid = r.json()["job_id"]
        conn = mo()
        for (vid, n) in conn.execute("SELECT id, nguon FROM tl_job_video WHERE job_id=? ORDER BY id", (jid,)).fetchall():
            i = int(json.loads(n)["video_id"][1:])
            log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
            if dat:
                nhat_ky.ghi_danh_gia(conn, log_id, nguoi, "dat")
            hang_doi.dat(conn, vid, "xong", video_log_id=log_id, drive_file_id_ra=f"RA{i:04d}" + "r" * 14)
        conn.close()
        return jid
    c.tao = tao
    yield c
    for t in luong:
        t.join(10)
    mc.dung()



def _cho(c):
    for t in list(c.luong):
        t.join(10)


def _so_ghi(drive):
    return sum(drive.so_lan(t) for t in ("doi_cha", "doi_ten", "sao_chep", "vao_thung_rac", "tao_thu_muc"))


def test_ap_co_tat_thi_404_ca_ba_route(ap, monkeypatch):
    from tiktok_music_downloader.thay_logo import ap_vao_bo
    j = ap.tao("a@x", [1])
    monkeypatch.delenv(ap_vao_bo.ENV_BAT)
    for cach, duong in (("post", f"/bo/{j}/ap"), ("post", f"/bo/{j}/hoan-tac"), ("get", f"/bo/{j}/ap")):
        assert getattr(ap, cach)(f"/api/thay-logo{duong}", headers=_h("a@x")).status_code == 404
    assert ap.drive.goi == [("lay_muc", BAN_AP[1])]  # chỉ lời gọi chụp nguồn lúc tạo lượt


def test_ap_202_roi_xong_bam_lai_409_hoan_tac_roi_ap_lai(ap):
    j = ap.tao("a@x", [1, 2])
    assert ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()["so_du_dieu_kien"] == 2
    r = ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x"))
    assert r.status_code == 202 and r.json() == {"ap_id": j, "so_video": 2, "bo_qua": []}
    _cho(ap)
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()
    assert (g["trang_thai"], g["so_da_ap"], g["la_chu"], g["ma_bo"], g["so_du_dieu_kien"]) == ("xong", 2, True, "N.1AAAA", 0)
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 409
    assert ap.post(f"/api/thay-logo/bo/{j}/hoan-tac", headers=_h("a@x")).status_code == 202
    _cho(ap)
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()
    assert (g["trang_thai"], g["da_hoan_tac"]) == ("chua_ap", True)
    assert ap.post(f"/api/thay-logo/bo/{j}/hoan-tac", headers=_h("a@x")).status_code == 409  # chưa áp
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 202  # áp lại sau hoàn tác
    _cho(ap)
    assert ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()["trang_thai"] == "xong"
    vb = {v["ban_copy_id"]: v["da_ap"] for b in ap.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bo"] for v in b["videos"]}
    assert vb == {BAN_AP[1]: True, BAN_AP[2]: True}


def test_ap_quyen_member_khac_403_admin_chi_doc(ap):
    j = ap.tao("a@x", [1])
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("b@x")).status_code == 403
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h(ADMIN)).status_code == 403
    assert ap.post(f"/api/thay-logo/bo/{j}/hoan-tac", headers=_h(ADMIN)).status_code == 403
    assert ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("b@x")).status_code == 403
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h(ADMIN))
    assert g.status_code == 200 and g.json()["la_chu"] is False and g.json()["so_du_dieu_kien"] is None
    assert ap.post("/api/thay-logo/bo/99999/ap", headers=_h("a@x")).status_code == 404
    assert ap.post("/api/thay-logo/bo/0/ap", headers=_h("a@x")).status_code == 422
    assert _so_ghi(ap.drive) == 0


def test_admin_tao_luot_cho_video_nguoi_khac_cung_khong_ap_thay_duoc(ap):
    """ĐỘT BIẾN: bỏ kiểm `chu_video == email` ⇒ admin áp được bản trong bộ của b ⇒ ĐỎ."""
    j = ap.tao(ADMIN, [3])
    r = ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h(ADMIN))
    assert r.status_code == 403 and _so_ghi(ap.drive) == 0


def test_so_vao_bo_chu_null_thi_403_cho_video_do(ap):
    """Lúc TẠO lượt NULL được qua; lúc ÁP thì không. ĐỘT BIẾN: bỏ kiểm `video_vao_bo.chu` ⇒ ĐỎ."""
    import sqlite3
    j = ap.tao("a@x", [1, 2])
    with sqlite3.connect(ap.jobs) as k:
        k.execute("UPDATE video_vao_bo SET chu = NULL WHERE video_id = 'V1'")
    r = ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x"))
    assert r.status_code == 202 and r.json()["so_video"] == 1 and r.json()["bo_qua"][0]["ly_do"].startswith("sổ Đã vào bộ")
    _cho(ap)
    assert ("doi_cha", BAN_AP[1]) not in ap.drive.goi and ("doi_cha", BAN_AP[2]) in ap.drive.goi
    with sqlite3.connect(ap.jobs) as k:
        k.execute("UPDATE video_vao_bo SET chu = NULL WHERE video_id = 'V2'")
    ap.post(f"/api/thay-logo/bo/{j}/hoan-tac", headers=_h("a@x"))
    _cho(ap)
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 403  # cả hai video NULL ⇒ không còn gì của "bạn"


def test_chua_dat_hoac_nguon_khac_khong_ap(ap):
    j = ap.tao("a@x", [1], dat=False)
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 409
    assert _so_ghi(ap.drive) == 0


def test_khong_co_drive_thi_503(ap):
    import types
    j = ap.tao("a@x", [1])
    ap.box["w"] = types.SimpleNamespace(ly_do_khong_nhan=None)
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 503


def test_hai_post_that_cung_bo_chi_mot_202(ap):
    """Hai lượt KHÁC NHAU cùng bộ (folder), hai request HTTP thật trên hai luồng, DB đã tạo trước. Thread của lượt thắng bị giữ ở lời gọi
    Drive đầu ⇒ khoá còn đó. ĐỘT BIẾN: bỏ khoá bộ ⇒ hai 202 ⇒ ĐỎ."""
    import threading
    j1, j2 = ap.tao("a@x", [1]), ap.tao("a@x", [2])
    di = threading.Event()
    goc = ap.drive.lay_muc

    def cham(fid):
        di.wait(10)
        return goc(fid)
    ap.drive.lay_muc = cham
    kq = []
    ts = [threading.Thread(target=lambda j=j: kq.append(ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code)) for j in (j1, j2)]
    [t.start() for t in ts]
    [t.join(15) for t in ts]
    assert sorted(kq) == [202, 409]
    assert ap.get(f"/api/thay-logo/bo/{j1}/ap", headers=_h("a@x")).json()["trang_thai"] in ("chay", "chua_ap")
    di.set()
    _cho(ap)
    # áp ‖ hoàn tác cùng bộ cũng 409: lượt thắng xong ⇒ hoàn tác nó trong lúc lượt kia đang chạy
    thang = j1 if ap.get(f"/api/thay-logo/bo/{j1}/ap", headers=_h("a@x")).json()["so_da_ap"] else j2
    thua = j2 if thang == j1 else j1
    di.clear()
    assert ap.post(f"/api/thay-logo/bo/{thua}/ap", headers=_h("a@x")).status_code == 202
    assert ap.post(f"/api/thay-logo/bo/{thang}/hoan-tac", headers=_h("a@x")).status_code == 409
    di.set()
    _cho(ap)


def test_quyen_kiem_truoc_drive_nguoi_la_403_khong_phai_503(ap):
    """ĐỘT BIẾN: kiểm worker/Drive trước quyền ⇒ người lạ nhận 503 (lộ cấu hình máy chủ) ⇒ ĐỎ."""
    import types
    j = ap.tao("a@x", [1])
    ap.box["w"] = types.SimpleNamespace(ly_do_khong_nhan=None)
    for duong in ("ap", "hoan-tac"):
        assert ap.post(f"/api/thay-logo/bo/{j}/{duong}", headers=_h("b@x")).status_code == 403
        assert ap.post(f"/api/thay-logo/bo/{j}/{duong}", headers=_h(ADMIN)).status_code == 403
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 503


def test_tab_da_vao_bo_co_tat_khong_tao_bang_ap(ap, monkeypatch):
    """ĐỘT BIẾN: gọi `ban_da_ap` cả khi cờ tắt ⇒ bảng `tl_ap_bo` bị tạo ⇒ ĐỎ."""
    from tiktok_music_downloader.thay_logo import ap_vao_bo
    ap.tao("a@x", [1])
    monkeypatch.delenv(ap_vao_bo.ENV_BAT)
    vb = ap.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()
    assert [v["da_ap"] for b in vb["bo"] for v in b["videos"]] == [False, False]
    conn = ap.mo()
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'tl_ap_bo%'").fetchone()[0] == 0
    conn.close()


def _danh_gia_moi(ap, j, i, ket_qua):
    """Ghi một đánh giá MỚI HƠN cho video thứ i (1-based theo thứ tự id) của lượt j."""
    import time
    conn = ap.mo()
    vid, log_id = conn.execute("SELECT id, video_log_id FROM tl_job_video WHERE job_id=? ORDER BY id", (j,)).fetchall()[i - 1]
    conn.execute("INSERT INTO tl_danh_gia (video_id, member, ket_qua, loai_loi, luc) VALUES (?,?,?,?,?)",
                 (log_id, "a@x", ket_qua, "khac" if ket_qua == "hong" else None, time.time() + 1))
    conn.commit()
    conn.close()


def test_bo_mot_xong_mot_lui_ap_lai_duoc_video_lui(ap):
    """1 video `xong` + 1 video `lui/loi` ⇒ GET báo `xong`, còn 1 video áp lại được, 0 video mới bị chặn; POST ⇒ 202, video lùi vào bộ.
    ĐỘT BIẾN: `dat_lich_ap` chỉ cho `tiep` qua ⇒ POST 409 ⇒ ĐỎ."""
    ra1 = "RA0001" + "r" * 14
    ap.drive.copy_mang_properties = True
    ap.drive.muc[ra1]["properties"] = {"videodesk_src": "SRCX" + "x" * 12}  # bản copy của video 1 mang dấu nguồn ⇒ lùi
    j = ap.tao("a@x", [1, 2])
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 202
    _cho(ap)
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()
    assert (g["trang_thai"], g["so_da_ap"], g["so_du_dieu_kien"], g["so_moi_bi_chan"]) == ("xong", 1, 1, 0)
    assert [(v["chieu"], v["buoc"]) for v in g["tung_video"]] == [("lui", "loi"), ("ap", "xong")]
    del ap.drive.muc[ra1]["properties"]  # lỗi đã hết
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).status_code == 202
    _cho(ap)
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()
    assert (g["trang_thai"], g["so_da_ap"], g["so_du_dieu_kien"], g["so_moi_bi_chan"]) == ("xong", 2, 0, 0)
    assert F_AP not in ap.drive.muc[BAN_AP[1]]["parents"]


def test_bo_da_ap_video_dat_moi_bi_chan_dem_rieng(ap):
    """Video 2 được chấm Đạt SAU khi bộ đã áp ⇒ `so_moi_bi_chan == 1`, `so_du_dieu_kien == 0`; POST ⇒ 409 "đã áp".
    ĐỘT BIẾN: bỏ `so_moi_bi_chan` (đếm video mới vào `so_du_dieu_kien`) ⇒ ĐỎ."""
    j = ap.tao("a@x", [1, 2])
    _danh_gia_moi(ap, j, 2, "hong")
    assert ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()["so_video"] == 1
    _cho(ap)
    _danh_gia_moi(ap, j, 2, "dat")
    g = ap.get(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x")).json()
    assert (g["trang_thai"], g["so_du_dieu_kien"], g["so_moi_bi_chan"]) == ("xong", 0, 1)
    r = ap.post(f"/api/thay-logo/bo/{j}/ap", headers=_h("a@x"))
    assert r.status_code == 409 and "hoàn tác trước" in r.json()["detail"]


# ---------------------------------------------------------------- đợt 4: Tải từ máy (cờ TL_TAI_TU_MAY) — Google/Drive GIẢ, không mạng
RA_TAI = "RAFOLDER0000000000001"
ORIGIN_ENV = "https://Video.Nobidigital.asia/"  # cố ý hoa + `/` cuối: so Origin thô sẽ 403 nhầm
ORIGIN_CHUAN = "https://video.nobidigital.asia"


@pytest.fixture
def tai(tmp_path, monkeypatch, capfd):
    """`capfd` đứng TRƯỚC: uvicorn gắn handler log vào stderr lúc dựng máy chủ ⇒ phải dựng SAU khi capfd đã bắt fd 2."""
    import types

    from drive_gia_thay_logo import DriveGiaTL
    from phien_http_gia_thay_logo import SessionGia

    from tiktok_music_downloader.thay_logo import tai_len_phien

    monkeypatch.setenv(tai_len_phien.ENV_BAT, "1")
    monkeypatch.setenv(tai_len_phien.ENV_ORIGIN, ORIGIN_ENV)
    monkeypatch.setenv(tai_len_phien.ENV_THU_MUC_RA, RA_TAI)
    drive = DriveGiaTL()
    drive.them_thu_muc(RA_TAI, "Thay logo - đầu ra")
    ss = SessionGia()
    db = tmp_path / "tl.db"
    _jobs_db(db)

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    box = {"w": types.SimpleNamespace(drive_tl=drive, ly_do_khong_nhan=None)}
    thay_logo_routes.dang_ky_route_member(app, lambda: db, require_user, lambda e: e == ADMIN, lambda: box["w"],
                                          lambda email, ids: set(), lay_jobs_db=lambda: db.parent / "jobs.db",
                                          lay_session_tai=lambda d: ss)
    mc = MayChu(app)
    c = _Client(mc)
    c.drive, c.ss, c.db, c.box, c.capfd = drive, ss, db, box, capfd
    yield c
    mc.dung()


PHIEN = "/api/thay-logo/tai-len/phien"


def _khai(**kw):
    return {"ten": "clip.mp4", "size": 1000, "mime": "video/mp4", **kw}


def _len(tai, token, **kw):
    """Mô phỏng trình duyệt PUT xong ở Google: file có trên Drive, mang thẻ phiên."""
    conn = nhat_ky.mo(tai.db)
    r = conn.execute("SELECT * FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
    conn.close()
    fid = f"UP{len(tai.drive.muc):018d}"
    tai.drive.them_file(fid, r["ten"], r["thu_muc_id"], size=kw.get("size", r["size"]), mime=r["mime"], md5="MD5X",
                        app_properties={"tl_phien": kw.get("the", token)})
    return fid


def _phien_xong(tai, nguoi="a@x"):
    r = tai.post(PHIEN, headers=_h(nguoi), json=_khai())
    assert r.status_code == 201, r.content
    token = r.json()["token"]
    fid = _len(tai, token)
    assert tai.post(f"/api/thay-logo/tai-len/{token}/xong", headers=_h(nguoi), json={"file_id": fid}).status_code == 200
    return token, fid


def test_tai_len_co_tat_thi_ca_ba_route_va_may_file_ids_deu_404(tai, monkeypatch):
    """Đột biến: bỏ cổng cờ ở một route ⇒ ĐỎ. Cờ tắt ⇒ không đụng Drive, không gọi Google, không tạo DB."""
    from tiktok_music_downloader.thay_logo import tai_len_phien
    monkeypatch.delenv(tai_len_phien.ENV_BAT)
    assert tai.get("/api/thay-logo/tai-len/bat", headers=_h("a@x")).status_code == 404
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 404
    assert tai.post("/api/thay-logo/tai-len/" + "T" * 43 + "/xong", headers=_h("a@x"), json={"file_id": "F" * 20}).status_code == 404
    assert tai.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"may_file_ids": ["F" * 20], "ten_bo": "Bộ"}).status_code == 404
    assert tai.ss.goi == [] and tai.drive.goi == [] and not tai.db.exists()


def test_tai_len_bat_200_khi_bat_cho_moi_nguoi_dung(tai):
    r = tai.get("/api/thay-logo/tai-len/bat", headers=_h("a@x"))
    assert r.status_code == 200 and r.json() == {}


def test_tao_phien_201_origin_gui_google_la_env_chuan_hoa(tai):
    r = tai.post(PHIEN, headers={**_h("a@x"), "Origin": "https://VIDEO.nobidigital.asia"}, json=_khai())
    assert r.status_code == 201, r.content  # env có `/` cuối + hoa, request khác hoa ⇒ KHÔNG 403 nhầm (đột biến "so thô" ⇒ ĐỎ)
    assert set(r.json()) == {"token", "url_phien"} and r.json()["url_phien"].startswith("https://www.googleapis.com/")
    assert tai.ss.goi[0]["headers"]["Origin"] == ORIGIN_CHUAN  # header gửi Google LUÔN = env chuẩn hoá


def test_tao_phien_origin_la_403_va_khong_goi_google(tai):
    """Đột biến: lấy Origin từ header request thay vì env ⇒ ĐỎ (201 + header lạ gửi Google)."""
    r = tai.post(PHIEN, headers={**_h("a@x"), "Origin": "https://evil.example"}, json=_khai())
    assert r.status_code == 403 and ORIGIN_CHUAN in r.json()["detail"]
    assert tai.ss.goi == [] and tai.drive.goi == []


def test_tao_phien_khong_co_origin_van_qua_va_van_gui_origin_cho_google(tai):
    """Đột biến: tạo phiên không gửi Origin ⇒ ĐỎ (Google nhận file nhưng trình duyệt không đọc được 200 cuối — hỏng âm thầm)."""
    r = tai.post(PHIEN, headers=_h("a@x"), json=_khai())  # urllib không tự gắn Origin
    assert r.status_code == 201 and tai.ss.goi[0]["headers"]["Origin"] == ORIGIN_CHUAN


@pytest.mark.parametrize("env", [None, "", "https://x.asia/duong-dan", "ftp://x.asia", "x.asia"])
def test_tao_phien_env_origin_thieu_hoac_sai_thi_503(tai, monkeypatch, env):
    from tiktok_music_downloader.thay_logo import tai_len_phien
    if env is None:
        monkeypatch.delenv(tai_len_phien.ENV_ORIGIN)
    else:
        monkeypatch.setenv(tai_len_phien.ENV_ORIGIN, env)
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 503
    assert tai.ss.goi == []


@pytest.mark.parametrize("sai", [{"size": 0}, {"size": -1}, {"size": "10"}, {"size": 500 * 1024 * 1024 + 1}, {"mime": "image/png"},
                                 {"mime": None}, {"ten": ""}, {"ten": "x" * 201}])
def test_tao_phien_khai_sai_thi_400(tai, sai):
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai(**sai)).status_code == 400
    assert tai.ss.goi == []


def test_tao_phien_drive_hoac_google_loi_thi_503_khong_ghi_phien(tai):
    tai.ss.loi = ConnectionError("lỗi mạng")
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 503
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT count(*) FROM tl_phien_tai").fetchone()[0] == 0
    tai.ss.loi = None
    tai.box["w"].drive_tl = None
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 503
    tai.box["w"] = None
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 409


def test_tao_phien_tran_429_chung_tran_cho(tai, monkeypatch):
    monkeypatch.setattr(thay_logo_routes, "TRAN_CHO_MOI_NGUOI", 2)
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 201
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 201
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 429
    assert tai.post(PHIEN, headers=_h("b@x"), json=_khai()).status_code == 201


def test_url_phien_khong_lot_stderr_log_hay_db_ke_ca_khi_loi_khong_boc(tai, caplog):
    """Rò URL phiên kiểm ở CẢ `caplog` VÀ stderr tiến trình (`capfd`): traceback uvicorn đi stderr, `caplog` có thể xanh giả.
    Đột biến: bỏ bọc exception ở `mo_phien` ⇒ 500 + traceback chứa `upload_id=` ⇒ ĐỎ."""
    from phien_http_gia_thay_logo import SO_BI_MAT
    caplog.set_level(logging.DEBUG)
    tai.ss.loi = ConnectionError(f"HTTPSConnectionPool: url: /upload/drive/v3/files?uploadType=resumable&upload_id={SO_BI_MAT}")
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 503
    tai.ss.loi = None
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 201  # đường thành công cũng không log URL
    toan_bo = tai.capfd.readouterr()
    for kenh in (caplog.text, toan_bo.out, toan_bo.err):
        assert "upload_id=" not in kenh and SO_BI_MAT not in kenh
    for f in tai.db.parent.glob("tl.db*"):
        assert SO_BI_MAT.encode() not in f.read_bytes()


def test_xong_chu_phien_200_va_lech_409_va_khong_co_404(tai):
    r = tai.post(PHIEN, headers=_h("a@x"), json=_khai())
    token = r.json()["token"]
    duong = f"/api/thay-logo/tai-len/{token}/xong"
    assert tai.post(duong, headers=_h("a@x"), json={"file_id": _len(tai, token, size=999)}).status_code == 409  # đột biến "bỏ kiểm size" ⇒ ĐỎ
    assert tai.post(duong, headers=_h("a@x"), json={"file_id": _len(tai, token, the="TOKEN-KHAC-00000000000")}).status_code == 409  # "bỏ kiểm tl_phien" ⇒ ĐỎ
    assert tai.post(duong, headers=_h("a@x"), json={"file_id": "../x"}).status_code == 400
    assert tai.post(duong, headers=_h("a@x"), json={}).status_code == 400
    fid = _len(tai, token)
    assert tai.post(duong, headers=_h("a@x"), json={"file_id": fid}).json() == {"file_id": fid}
    assert tai.post(duong, headers=_h("a@x"), json={"file_id": fid}).status_code == 200  # thử lại cùng file
    assert tai.post("/api/thay-logo/tai-len/" + "Z" * 43 + "/xong", headers=_h("a@x"), json={"file_id": fid}).status_code == 404
    assert tai.post("/api/thay-logo/tai-len/ngan/xong", headers=_h("a@x"), json={"file_id": fid}).status_code == 404


def test_xong_nguoi_khac_va_admin_deu_403(tai):
    """Đột biến: bỏ kiểm chủ phiên ⇒ ĐỎ; admin chốt phiên người khác ⇒ ĐỎ."""
    token = tai.post(PHIEN, headers=_h("a@x"), json=_khai()).json()["token"]
    fid = _len(tai, token)
    duong = f"/api/thay-logo/tai-len/{token}/xong"
    assert tai.post(duong, headers=_h("b@x"), json={"file_id": fid}).status_code == 403
    assert tai.post(duong, headers=_h(ADMIN), json={"file_id": fid}).status_code == 403
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()[0] == "mo"


def _tao_job_may(tai, nguoi, fids, **kw):
    return tai.post("/api/thay-logo/jobs", headers=_h(nguoi), json={"may_file_ids": fids, "ten_bo": "Bộ máy", **kw})


def test_jobs_may_file_ids_server_tu_tra_ten_token_va_ghi_nguon_may(tai):
    token, fid = _phien_xong(tai)
    r = _tao_job_may(tai, "a@x", [fid, fid], may_ten="ten-gia-tu-fe", ten="ten-gia")  # trường lạ của FE bị bỏ; trùng id ⇒ một video
    assert r.status_code == 201, r.content
    conn = nhat_ky.mo(tai.db)
    rows = [json.loads(x[0]) for x in conn.execute("SELECT nguon FROM tl_job_video")]
    assert rows == [{"kieu": "may", "file_id": fid, "token": token, "ten": "clip.mp4"}]
    assert conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()[0] == "da_dung"
    v = tai.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]
    assert len(v) == 1 and v[0]["ten_video"] == "clip.mp4" and v[0]["da_don"] is False  # tên ưu tiên `nguon.ten`, không "Video không tên"
    assert tai.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"][0]["nguon_kieu"] == "may"


def test_videos_tra_co_da_don_khi_nguon_da_don(tai):
    token, fid = _phien_xong(tai)
    _tao_job_may(tai, "a@x", [fid])
    conn = nhat_ky.mo(tai.db)
    conn.execute("UPDATE tl_job_video SET nguon=json_set(nguon, '$.da_don', json('true'))")
    conn.commit()
    assert tai.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"][0]["da_don"] is True


def test_jobs_mot_file_khong_vao_hai_luot_409(tai):
    """Đột biến: 1 `file_id` cho 2 lượt ⇒ ĐỎ."""
    token, fid = _phien_xong(tai)
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 201
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 409
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT count(*) FROM tl_job_video").fetchone()[0] == 1 and conn.execute("SELECT count(*) FROM tl_job").fetchone()[0] == 1


def test_jobs_dung_lai_file_khi_moi_lan_truoc_loi(tai):
    token, fid = _phien_xong(tai)
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 201
    conn = nhat_ky.mo(tai.db)
    conn.execute("UPDATE tl_job_video SET trang_thai='loi'")
    conn.commit()
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 201
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 409


def test_jobs_may_file_cua_nguoi_khac_admin_hoac_chua_chot_deu_403(tai):
    token_a, fid_a = _phien_xong(tai, "a@x")
    token_mo = tai.post(PHIEN, headers=_h("a@x"), json=_khai()).json()["token"]
    fid_mo = _len(tai, token_mo)  # đã lên Drive nhưng CHƯA `/xong`
    assert _tao_job_may(tai, "b@x", [fid_a]).status_code == 403
    assert _tao_job_may(tai, ADMIN, [fid_a]).status_code == 403  # admin cũng không dùng phiên người khác
    assert _tao_job_may(tai, "a@x", [fid_mo]).status_code == 403
    assert _tao_job_may(tai, "a@x", ["N" * 20]).status_code == 403
    assert _tao_job_may(tai, "a@x", ["../x"]).status_code == 400
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT count(*) FROM tl_job").fetchone()[0] == 0
    assert conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token_a,)).fetchone()[0] == "xong"  # 403 không đổi trạng thái


def test_jobs_tron_may_va_link_roi_mot_loi_thi_khong_doi_trang_thai_phien(tai):
    """Một mục sai ⇒ cả lượt bị từ chối VÀ phiên `xong` không bị đổi thành `da_dung` (cùng giao dịch)."""
    token, fid = _phien_xong(tai)
    r = tai.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["Z" * 20], "may_file_ids": [fid], "ten_bo": "B"})
    assert r.status_code == 403
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()[0] == "xong"


def test_jobs_may_tinh_vao_tran_cho(tai, monkeypatch):
    t1, f1 = _phien_xong(tai)
    t2, f2 = _phien_xong(tai)
    monkeypatch.setattr(thay_logo_routes, "TRAN_CHO_MOI_NGUOI", 1)
    assert _tao_job_may(tai, "a@x", [f1, f2]).status_code == 429  # 2 video mới > trần 1
    conn = nhat_ky.mo(tai.db)
    assert conn.execute("SELECT count(*) FROM tl_phien_tai WHERE trang_thai='xong'").fetchone()[0] == 2  # 429 không đổi phiên
    assert _tao_job_may(tai, "a@x", [f1]).status_code == 201
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 429  # video chờ + phiên mở chung một trần


def test_tao_phien_drive_treo_luc_tim_thu_muc_vao_thi_503_nhanh(tai):
    """Tìm/tạo thư mục đầu vào chạy TRONG request: phải xin timeout ngắn (`ngan=True`). Drive giả: lời gọi KHÔNG xin ngắn thì treo 15 s
    (như `_svc()` không timeout gặp Drive treo); xin ngắn thì ném `TimeoutError` (như httplib2 hết `TIMEOUT_LAY_MUC_GIAY`).
    ĐỘT BIẾN: bỏ `ngan=True` ở `thu_muc_vao_cua` ⇒ request treo 15 s rồi 201 ⇒ ĐỎ."""
    import threading
    import time

    goc = tai.drive.tim_con_theo_ten

    def tim(cha_id, ten, *, ngan=False):
        if not ngan:
            threading.Event().wait(15)
            return goc(cha_id, ten)
        raise TimeoutError("timed out")

    tai.drive.tim_con_theo_ten = tim
    t0 = time.monotonic()
    r = tai.post(PHIEN, headers=_h("a@x"), json=_khai())
    assert r.status_code == 503, r.content
    assert time.monotonic() - t0 < 10
    assert tai.ss.goi == []  # không tạo phiên Google khi chưa có thư mục


# ---------------------------------------------------------------- phiên của tôi: liệt kê + bỏ
CUA_TOI = "/api/thay-logo/tai-len/cua-toi"


def _bo_phien(tai, nguoi, token):
    return tai.post(f"/api/thay-logo/tai-len/{token}/bo", headers=_h(nguoi))


def _tt(tai, token):
    return nhat_ky.mo(tai.db).execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()[0]


def test_cua_toi_va_bo_co_tat_thi_404(tai, monkeypatch):
    """ĐỘT BIẾN: bỏ `_cong()` ở một trong hai route ⇒ ĐỎ."""
    from tiktok_music_downloader.thay_logo import tai_len_phien
    monkeypatch.delenv(tai_len_phien.ENV_BAT)
    assert tai.get(CUA_TOI, headers=_h("a@x")).status_code == 404
    assert _bo_phien(tai, "a@x", "T" * 43).status_code == 404
    assert tai.drive.goi == [] and not tai.db.exists()


def test_cua_toi_chi_phien_xong_cua_chinh_minh_khong_lo_url_hay_thu_muc(tai):
    """ĐỘT BIẾN: liệt kê phiên người khác / phiên không phải `xong` ⇒ ĐỎ; thêm `url_phien`/`upload_id`/`thu_muc_id` vào response ⇒ ĐỎ."""
    from phien_http_gia_thay_logo import SO_BI_MAT, URL_BI_MAT
    t1, f1 = _phien_xong(tai, "a@x")
    _phien_xong(tai, "b@x")
    _phien_xong(tai, ADMIN)
    t_mo = tai.post(PHIEN, headers=_h("a@x"), json=_khai()).json()["token"]   # `mo`
    r = tai.get(CUA_TOI, headers=_h("a@x"))
    assert r.status_code == 200
    ds = r.json()["phien"]
    assert [(d["token"], d["file_id"]) for d in ds] == [(t1, f1)] and t_mo not in r.content.decode()
    assert set(ds[0]) == {"token", "file_id", "ten", "size", "cap_nhat_luc"} and ds[0]["ten"] == "clip.mp4" and ds[0]["size"] == 1000
    for cam in ("url_phien", "upload_id", "thu_muc_id", "googleapis", SO_BI_MAT, URL_BI_MAT):
        assert cam not in r.content.decode()
    assert len(tai.get(CUA_TOI, headers=_h(ADMIN)).json()["phien"]) == 1   # admin cũng chỉ thấy của mình
    assert tai.get(CUA_TOI, headers=_h("c@x")).json() == {"phien": []}


def test_bo_phien_xong_va_mo_200_idempotent(tai):
    t_xong, _ = _phien_xong(tai)
    t_mo = tai.post(PHIEN, headers=_h("a@x"), json=_khai()).json()["token"]
    for t in (t_xong, t_mo):
        assert _bo_phien(tai, "a@x", t).json() == {"trang_thai": "bo_do"} and _tt(tai, t) == "bo_do"
        assert _bo_phien(tai, "a@x", t).status_code == 200
    assert tai.get(CUA_TOI, headers=_h("a@x")).json() == {"phien": []}   # bỏ rồi ⇒ không dựng lại sau tải lại trang


def test_bo_phien_nguoi_khac_va_admin_403_khong_doi_trang_thai_404_khong_co(tai):
    """ĐỘT BIẾN: bỏ kiểm email (B/admin bỏ phiên của A) ⇒ ĐỎ."""
    token, _ = _phien_xong(tai, "a@x")
    assert _bo_phien(tai, "b@x", token).status_code == 403
    assert _bo_phien(tai, ADMIN, token).status_code == 403
    assert _tt(tai, token) == "xong"
    assert _bo_phien(tai, "a@x", "Z" * 43).status_code == 404
    assert _bo_phien(tai, "a@x", "ngan").status_code == 404


def test_bo_phien_da_dung_dang_don_da_don_409(tai):
    """ĐỘT BIẾN: cho bỏ phiên `da_dung` (UPDATE không ràng trạng thái) ⇒ ĐỎ: file đang nằm trong một lượt sẽ bị dọn dưới chân lượt."""
    token, fid = _phien_xong(tai)
    assert _tao_job_may(tai, "a@x", [fid]).status_code == 201
    assert _tt(tai, token) == "da_dung" and _bo_phien(tai, "a@x", token).status_code == 409 and _tt(tai, token) == "da_dung"
    conn = nhat_ky.mo(tai.db)
    for tt in ("dang_don", "da_don"):
        conn.execute("UPDATE tl_phien_tai SET trang_thai=? WHERE token=?", (tt, token))
        conn.commit()
        assert _bo_phien(tai, "a@x", token).status_code == 409 and _tt(tai, token) == tt


def test_bo_phien_nha_tran_429(tai, monkeypatch):
    """ĐỘT BIẾN: `bo` không đổi trạng thái ⇒ vẫn 429 ⇒ ĐỎ."""
    monkeypatch.setattr(thay_logo_routes, "TRAN_CHO_MOI_NGUOI", 2)
    t1, _ = _phien_xong(tai)
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 201
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 429
    assert _bo_phien(tai, "a@x", t1).status_code == 200
    assert tai.post(PHIEN, headers=_h("a@x"), json=_khai()).status_code == 201


def test_bo_phien_xong_roi_thread_don_trash_file(tai):
    """Cả đường: bỏ phiên `xong` có file qua route ⇒ request không đụng Drive ⇒ một lượt `don_mot_luot` ⇒ file vào thùng rác."""
    from tiktok_music_downloader.thay_logo import tai_len_phien
    token, fid = _phien_xong(tai)
    goi = len(tai.drive.goi)
    assert _bo_phien(tai, "a@x", token).status_code == 200 and len(tai.drive.goi) == goi and tai.drive.muc[fid]["trashed"] is False
    conn = nhat_ky.mo(tai.db)
    assert tai_len_phien.don_mot_luot(conn, tai.drive)["bo_do_co_file"] == 1
    assert tai.drive.muc[fid]["trashed"] is True and _tt(tai, token) == "da_don"
    conn.close()


def test_bo_phien_da_bo_do_cua_nguoi_khac_van_403_khong_phai_200_idempotent(tai):
    """ĐỘT BIẾN: đưa lối tắt idempotent `bo_do ⇒ 200` lên TRƯỚC kiểm chủ phiên ⇒ B (và admin) thấy 200 trên token đã bỏ của A ⇒ ĐỎ."""
    token, _ = _phien_xong(tai, "a@x")
    assert _bo_phien(tai, "a@x", token).status_code == 200 and _tt(tai, token) == "bo_do"
    assert _bo_phien(tai, "b@x", token).status_code == 403
    assert _bo_phien(tai, ADMIN, token).status_code == 403
    assert _tt(tai, token) == "bo_do"
    assert _bo_phien(tai, "a@x", token).status_code == 200   # chủ phiên vẫn idempotent


@pytest.mark.parametrize("tz_may", ["America/Los_Angeles", "Asia/Saigon", "UTC"])
def test_loc_theo_ngay_tinh_theo_gio_VN_bat_ke_gio_may_chu(monkeypatch, tz_may):
    """Máy chủ ca-n chạy giờ LA (VN −14h): ngày `YYYY-MM-DD` người dùng gõ là ngày VN, không được trôi theo múi máy."""
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setenv("TZ", tz_may)
    time.tzset()
    try:
        dau = datetime(2026, 10, 20, tzinfo=ZoneInfo("Asia/Saigon")).timestamp()
        assert thay_logo_routes._moc_thoi_gian("2026-10-20", "tu") == dau
        assert thay_logo_routes._moc_thoi_gian("2026-10-20", "den", cuoi_ngay=True) == dau + 86400
    finally:
        monkeypatch.undo()
        time.tzset()
