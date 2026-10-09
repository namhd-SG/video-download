"""Route member trang Thay logo: chỉ người tạo hoặc admin thấy/đánh giá; đánh giá chỉ khi đã thay xong; trạng thái worker chỉ admin."""
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
        c.execute("CREATE TABLE IF NOT EXISTS videos (video_id TEXT PRIMARY KEY, job_id INTEGER, title TEXT, drive_file_id TEXT)")
        for i, (fid, vid, title, nt, nguoi) in enumerate(hang, 1):
            c.execute("INSERT INTO jobs VALUES (?,?,?)", (i, nguoi, nt))
            c.execute("INSERT INTO videos VALUES (?,?,?,?)", (vid, i, title, fid))


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
    ngay1 = datetime.fromtimestamp(1_700_000_000).strftime("%Y-%m-%d")  # ngày theo giờ máy chủ; `den` tính HẾT ngày đó
    assert {x["id"] for x in ds(f"?tu={ngay1}&den={ngay1}")} == {v1}
    assert c.get("/api/thay-logo/videos?tu=hom-qua", headers=_h("a@x")).status_code == 400


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
