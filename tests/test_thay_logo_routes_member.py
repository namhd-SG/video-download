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
    thay_logo_routes.dang_ky_route_member(app, lambda: db, require_user, lambda e: e == ADMIN, lambda: worker["w"])
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
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["../etc/passwd"]}).status_code == 400
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": []}).status_code == 422
    r = c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20, "A" * 20, "B" * 20]})
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
    c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20]})
    vid = c.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"][0]["id"]
    assert c.post(f"/api/thay-logo/videos/{vid}/danh-gia", headers=_h("a@x"), json={"ket_qua": "dat"}).status_code == 409


def test_trang_thai_worker_chi_admin_va_tinh_nang_tat_thi_khong_nhan_luot_moi(ctx):
    c, _ = ctx
    c.worker["w"] = None
    assert c.get("/api/thay-logo/admin/worker", headers=_h("a@x")).status_code == 403
    assert c.get("/api/thay-logo/admin/worker", headers=_h(ADMIN)).json() == {"song": False, "luot_cuoi": "tinh_nang_tat"}
    assert c.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": ["A" * 20]}).status_code == 409
