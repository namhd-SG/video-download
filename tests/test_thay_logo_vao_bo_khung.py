"""Đợt 1b — route ảnh trước/sau (`/videos/{vid}/khung/{truoc,sau}.jpg`, `co_truoc_sau`, `box_logo`) và tab "Đã vào bộ"
(`GET /da-vao-bo`, `POST /jobs` với `vao_bo`): quyền theo CHỦ VIDEO (`jobs.nguoi_tao`), ảnh chụp nguồn (md5/size/folder/mã bộ) chụp lúc
tạo lượt, lỗi Drive không tạo lượt. Drive là bản giả; không test nào gọi mạng."""
import json
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from drive_gia_thay_logo import DriveGiaTL  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from test_thay_logo_relay import _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky  # noqa: E402
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongThay  # noqa: E402
from web import models, models_vao_bo, thay_logo_routes  # noqa: E402

ADMIN = "sep@x"
BAN1, BAN2, BAN3 = "BANCOPY0001" + "a" * 10, "BANCOPY0002" + "b" * 10, "BANCOPY0003" + "c" * 10
F1, F2 = "FOLDERBO1" + "f" * 12, "FOLDERBO2" + "g" * 12
JPEG = b"\xff\xd8\xff\xe0" + b"jpegdata" * 20


@pytest.fixture
def ctx(tmp_path):
    jobs = tmp_path / "jobs.db"
    models.init_db(jobs)
    ja = models.create_job(jobs, "https://x/a", 2, "a@x", nen_tang="tiktok")
    jb = models.create_job(jobs, "https://x/b", 1, "b@x", nen_tang="douyin")
    models.record_video(jobs, ja, "V1", "https://x/v1", title="Máy hút bụi", drive_file_id="SRC1" + "x" * 12)
    models.record_video(jobs, ja, "V2", "https://x/v2", title="Chảo chống dính", drive_file_id="SRC2" + "x" * 12)
    models.record_video(jobs, jb, "V3", "https://x/v3", title="Son kem lì", drive_file_id="SRC3" + "x" * 12)
    models_vao_bo.ghi_da_vao_bo(jobs, "V1", None, [dict(ban_copy_id=BAN1, folder_id=F1, ma_bo="N.1AAAA", bang_chung="properties")])
    models_vao_bo.ghi_da_vao_bo(jobs, "V2", None, [dict(ban_copy_id=BAN2, folder_id=F1, ma_bo="N.1AAAA", bang_chung="properties")])
    models_vao_bo.ghi_da_vao_bo(jobs, "V3", "b@x", [dict(ban_copy_id=BAN3, folder_id=F2, ma_bo="N.2BBBB", bang_chung="properties")])
    drive = DriveGiaTL()
    drive.them_thu_muc(F1, "N.1AAAA")
    drive.them_thu_muc(F2, "N.2BBBB")
    drive.them_file(BAN1, "v1.mp4", F1, md5="MD5-1", size="111")
    drive.them_file(BAN2, "v2.mp4", F1, md5="MD5-2", size="222")
    drive.them_file(BAN3, "v3.mp4", F2, md5="MD5-3", size="333")
    log_db = tmp_path / "tl.db"
    worker = types.SimpleNamespace(drive_tl=drive, ly_do_khong_nhan=None)

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    box = {"w": worker}
    thay_logo_routes.dang_ky_route_member(app, lambda: log_db, require_user, lambda e: e == ADMIN, lambda: box["w"],
                                          lambda email, ids: set(), lay_jobs_db=lambda: jobs)
    mc = MayChu(app)
    c = _Client(mc)
    c.drive, c.log_db, c.jobs, c.box = drive, log_db, jobs, box
    yield c
    mc.dung()


def _h(u):
    return {"x-user": u}


def _vb(video_id, ban):
    return {"video_id": video_id, "ban_copy_id": ban}


def _tao(c, nguoi, muc, **kw):
    return c.post("/api/thay-logo/jobs", headers=_h(nguoi), json={"vao_bo": muc, "ten_bo": "N.1AAAA", **kw})


def _so_dong(c):
    if not c.log_db.exists():
        return 0
    conn = nhat_ky.mo(c.log_db)
    hang_doi.khoi_tao(conn)
    try:
        return conn.execute("SELECT count(*) FROM tl_job_video").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- GET /da-vao-bo
def test_da_vao_bo_moi_nguoi_chi_thay_video_cua_minh_admin_thay_het(ctx):
    a = ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bo"]
    assert [(b["ma_bo"], b["folder_id"], sorted(v["video_id"] for v in b["videos"])) for b in a] == [("N.1AAAA", F1, ["V1", "V2"])]
    b = ctx.get("/api/thay-logo/da-vao-bo", headers=_h("b@x")).json()["bo"]
    assert [(x["ma_bo"], [v["video_id"] for v in x["videos"]]) for x in b] == [("N.2BBBB", ["V3"])]
    assert ctx.get("/api/thay-logo/da-vao-bo", headers=_h("c@x")).json() == {"bo": []}
    assert sorted(x["ma_bo"] for x in ctx.get("/api/thay-logo/da-vao-bo", headers=_h(ADMIN)).json()["bo"]) == ["N.1AAAA", "N.2BBBB"]
    v = next(v for v in a[0]["videos"] if v["video_id"] == "V1")
    assert (v["ban_copy_id"], v["ten_video"], v["nen_tang"], v["anh_bia"], v["da_trong_luot"]) == (BAN1, "Máy hút bụi", "tiktok", "/thumbs/V1", False)
    assert a[0]["vao_bo_luc"]


def test_da_trong_luot_bat_sau_khi_tao_luot_va_tha_lai_khi_loi(ctx):
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 201
    v = {x["video_id"]: x["da_trong_luot"] for x in ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bo"][0]["videos"]}
    assert v == {"V1": True, "V2": False}
    conn = nhat_ky.mo(ctx.log_db)
    hang_doi.dat(conn, conn.execute("SELECT id FROM tl_job_video").fetchone()[0], "loi", loi_text="x")
    conn.close()
    v = {x["video_id"]: x["da_trong_luot"] for x in ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bo"][0]["videos"]}
    assert v == {"V1": False, "V2": False}  # lượt lỗi không giữ video lại: chọn lại được


# ---------------------------------------------------------------- POST /jobs với vao_bo
def test_tao_luot_vao_bo_chup_day_du_nguon(ctx):
    r = _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V2", BAN2)])
    assert r.status_code == 201
    conn = nhat_ky.mo(ctx.log_db)
    nguon = [json.loads(x[0]) for x in conn.execute("SELECT nguon FROM tl_job_video ORDER BY id")]
    conn.close()
    assert nguon == [
        {"kieu": "vao_bo", "video_id": "V1", "file_id": BAN1, "folder_id": F1, "ma_bo": "N.1AAAA", "md5": "MD5-1", "size": "111", "ten": "v1.mp4"},
        {"kieu": "vao_bo", "video_id": "V2", "file_id": BAN2, "folder_id": F1, "ma_bo": "N.1AAAA", "md5": "MD5-2", "size": "222", "ten": "v2.mp4"}]


def test_vao_bo_cua_nguoi_khac_bi_403_va_khong_goi_drive_khong_tao_luot(ctx):
    assert _tao(ctx, "a@x", [_vb("V3", BAN3)]).status_code == 403
    assert _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V3", BAN3)]).status_code == 403  # một mục lạ ⇒ hỏng cả lượt
    assert _tao(ctx, "c@x", [_vb("V1", BAN1)]).status_code == 403
    assert ctx.drive.so_lan("lay_muc") == 0 and _so_dong(ctx) == 0
    assert _tao(ctx, ADMIN, [_vb("V3", BAN3)]).status_code == 201  # admin chọn được bản của mọi người


def test_vao_bo_khong_khop_video_hoac_khong_co_ban_nay_bi_403(ctx):
    assert _tao(ctx, "a@x", [_vb("V2", BAN1)]).status_code == 403  # bản của V1 khai là của V2
    assert _tao(ctx, "a@x", [_vb("V1", "KHONGCO" + "z" * 12)]).status_code == 403
    assert _so_dong(ctx) == 0


@pytest.mark.parametrize("sua", ["thung_rac", "doi_thu_muc", "mat_md5", "mat_size", "khong_thay", "loi_mang"])
def test_nguon_drive_khong_hop_le_thi_khong_tao_luot(ctx, sua):
    m = ctx.drive.muc[BAN1]
    if sua == "thung_rac":
        m["trashed"] = True
    elif sua == "doi_thu_muc":
        m["parents"] = [F2]
    elif sua == "mat_md5":
        del m["md5Checksum"]
    elif sua == "mat_size":
        del m["size"]
    elif sua == "khong_thay":
        del ctx.drive.muc[BAN1]
    else:
        ctx.drive.loi[("lay_muc", BAN1)] = TimeoutError("treo")
    r = _tao(ctx, "a@x", [_vb("V1", BAN1)])
    assert r.status_code == (503 if sua == "loi_mang" else 400), r.content
    assert _so_dong(ctx) == 0
    assert DriveTLKhongThay  # (khong_thay đi qua nhánh 404 của Drive)


def test_khong_co_adapter_drive_thi_503(ctx):
    ctx.box["w"] = types.SimpleNamespace(ly_do_khong_nhan=None)
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 503 and _so_dong(ctx) == 0


def test_chon_rong_hoac_qua_tran_va_tron_hai_nguon(ctx):
    assert ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"ten_bo": "x"}).status_code == 422
    assert ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"ten_bo": "x", "vao_bo": [], "drive_file_ids": []}).status_code == 422
    assert _tao(ctx, "a@x", [_vb("V1", "../etc")]).status_code == 400
    # trộn thư viện + vào bộ trong một lượt: thư viện vẫn kiểm theo thu_vien_cua (ở fixture là rỗng ⇒ 403 với member)
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)], drive_file_ids=["SRC1" + "x" * 12]).status_code == 403
    assert _tao(ctx, ADMIN, [_vb("V1", BAN1)], drive_file_ids=["SRC1" + "x" * 12]).status_code == 201
    assert _so_dong(ctx) == 2


def test_quota_cho_tinh_ca_vao_bo(ctx, monkeypatch):
    monkeypatch.setattr(thay_logo_routes, "TRAN_CHO_MOI_NGUOI", 1)
    assert _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V2", BAN2)]).status_code == 429
    assert ctx.drive.so_lan("lay_muc") == 0


def test_videos_ghep_ten_nen_tang_cho_nguon_vao_bo(ctx):
    _tao(ctx, "a@x", [_vb("V1", BAN1)])
    v = ctx.get("/api/thay-logo/videos", headers=_h("a@x")).json()
    d = v["videos"][0]
    assert (d["ten_video"], d["nen_tang"], d["anh_bia"], v["thu_vien_loi"]) == ("Máy hút bụi", "tiktok", "/thumbs/V1", False)
    assert ctx.get("/api/thay-logo/videos?nen_tang=douyin", headers=_h("a@x")).json()["videos"] == []
    assert len(ctx.get("/api/thay-logo/videos?nen_tang=tiktok", headers=_h("a@x")).json()["videos"]) == 1


# ---------------------------------------------------------------- ảnh trước/sau
def _video_da_xong(c, tmp_path, *, truoc=True, sau=True, box='{"x":0.1,"y":0.2,"w":0.3,"h":0.05}', nguoi="a@x"):
    conn = nhat_ky.mo(c.log_db)
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, nguoi, [{"kieu": "drive", "file_id": "F" * 20}])
    vid = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
    log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
    duong = {}
    for ten, co in (("truoc", truoc), ("sau", sau)):
        if co:
            p = tmp_path / f"{ten}-{vid}.jpg"
            p.write_bytes(JPEG)
            duong["duong_dan_" + ten] = str(p)
    nhat_ky.cap_nhat_video(conn, log_id, box_logo=box, **duong)
    hang_doi.dat(conn, vid, "xong", video_log_id=log_id)
    conn.close()
    return vid


def test_khung_chu_xem_duoc_nguoi_khac_bi_chan_admin_xem_duoc(ctx, tmp_path):
    vid = _video_da_xong(ctx, tmp_path)
    for ten in ("truoc", "sau"):
        r = ctx.get(f"/api/thay-logo/videos/{vid}/khung/{ten}.jpg", headers=_h("a@x"))
        assert r.status_code == 200 and r.content == JPEG
        assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/{ten}.jpg", headers=_h("b@x")).status_code == 403
        assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/{ten}.jpg", headers=_h(ADMIN)).status_code == 200


def test_khung_chua_co_hoac_ten_la_hoac_khong_ton_tai_thi_404(ctx, tmp_path):
    vid = _video_da_xong(ctx, tmp_path, sau=False)  # video cho_nguoi: chỉ có ảnh trước
    assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/truoc.jpg", headers=_h("a@x")).status_code == 200
    assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/sau.jpg", headers=_h("a@x")).status_code == 404
    assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/..%2Fx.jpg", headers=_h("a@x")).status_code == 404
    assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/giua.jpg", headers=_h("a@x")).status_code == 404
    assert ctx.get("/api/thay-logo/videos/99999/khung/truoc.jpg", headers=_h("a@x")).status_code == 404
    vid2 = _video_da_xong(ctx, tmp_path, truoc=False, sau=False)
    assert ctx.get(f"/api/thay-logo/videos/{vid2}/khung/truoc.jpg", headers=_h("a@x")).status_code == 404


def test_file_anh_bi_don_thi_404_khong_500(ctx, tmp_path):
    vid = _video_da_xong(ctx, tmp_path)
    (tmp_path / f"truoc-{vid}.jpg").unlink()
    assert ctx.get(f"/api/thay-logo/videos/{vid}/khung/truoc.jpg", headers=_h("a@x")).status_code == 404


def test_videos_bao_co_truoc_sau_va_box_logo(ctx, tmp_path):
    v_du = _video_da_xong(ctx, tmp_path)
    v_nua = _video_da_xong(ctx, tmp_path, sau=False, box=None)
    v_hong = _video_da_xong(ctx, tmp_path, box='{"x":2,"y":0,"w":0.1,"h":0.1}')  # ngoài miền 0–1 ⇒ bỏ box, không tin
    ds = {d["id"]: d for d in ctx.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]}
    assert (ds[v_du]["co_truoc_sau"], ds[v_du]["box_logo"]) == (True, {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05})
    assert (ds[v_nua]["co_truoc_sau"], ds[v_nua]["box_logo"]) == (False, None)
    assert (ds[v_hong]["co_truoc_sau"], ds[v_hong]["box_logo"]) == (True, None)
    assert not any(k in ds[v_du] for k in ("co_truoc", "co_sau", "box_logo_json"))


def test_tran_tong_muc_moi_luot_dung_hang_chung(ctx, monkeypatch):
    monkeypatch.setattr(thay_logo_routes, "TRAN_VIDEO_MOT_JOB", 2)
    r = _tao(ctx, ADMIN, [_vb("V1", BAN1), _vb("V2", BAN2)], drive_file_ids=["SRC1" + "x" * 12])
    assert r.status_code == 422 and "2" in r.content.decode()
    assert _tao(ctx, ADMIN, [_vb("V1", BAN1), _vb("V2", BAN2)]).status_code == 201
