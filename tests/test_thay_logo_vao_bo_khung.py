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
    assert ctx.get("/api/thay-logo/da-vao-bo", headers=_h("c@x")).json() == {"bo": [], "bi_cat": False}
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
        {"kieu": "vao_bo", "video_id": "V1", "file_id": BAN1, "folder_id": F1, "ma_bo": "N.1AAAA", "md5": "MD5-1", "size": "111", "ten": "v1.mp4",
         "chu_video": "a@x", "file_id_nguon": "SRC1" + "x" * 12},
        {"kieu": "vao_bo", "video_id": "V2", "file_id": BAN2, "folder_id": F1, "ma_bo": "N.1AAAA", "md5": "MD5-2", "size": "222", "ten": "v2.mp4",
         "chu_video": "a@x", "file_id_nguon": "SRC2" + "x" * 12}]


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
    v_khong = _video_da_xong(ctx, tmp_path, truoc=False, sau=False, box=None)  # không có ảnh trước: `and` đoản mạch từng bỏ sót pop co_sau
    assert set(ds_khong := next(d for d in ctx.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"] if d["id"] == v_khong)) \
        .isdisjoint({"co_sau", "box_logo_json"}) and ds_khong["co_truoc"] is False and ds_khong["co_truoc_sau"] is False
    assert not any(k in ds[v_du] for k in ("co_sau", "box_logo_json"))
    assert not any(k in ds[v_nua] for k in ("co_sau", "box_logo_json"))  # short-circuit của `and` từng làm rò khoá thô khi không có ảnh trước
    assert (ds[v_du]["co_truoc"], ds[v_nua]["co_truoc"]) == (True, True)


def test_tran_tong_muc_moi_luot_dung_hang_chung(ctx, monkeypatch):
    monkeypatch.setattr(thay_logo_routes, "TRAN_VIDEO_MOT_JOB", 2)
    r = _tao(ctx, ADMIN, [_vb("V1", BAN1), _vb("V2", BAN2)], drive_file_ids=["SRC1" + "x" * 12])
    assert r.status_code == 422 and "2" in r.content.decode()
    assert _tao(ctx, ADMIN, [_vb("V1", BAN1), _vb("V2", BAN2)]).status_code == 201


# ---------------------------------------------------------------- sửa theo review: chủ sổ, song song, trùng lượt, cắt danh sách
def _dat_chu_so(c, video_id, chu):
    import sqlite3
    with sqlite3.connect(c.jobs) as k:
        k.execute("UPDATE video_vao_bo SET chu = ? WHERE video_id = ?", (chu, video_id))


def test_chu_so_khac_nguoi_tao_thi_403_ke_ca_admin_null_thi_qua(ctx):
    _dat_chu_so(ctx, "V1", "nguoi-la@x")  # sổ ghi chủ khác người đã tải video
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 403
    assert _tao(ctx, ADMIN, [_vb("V1", BAN1)]).status_code == 403
    assert _so_dong(ctx) == 0
    _dat_chu_so(ctx, "V1", "a@x")  # khớp ⇒ qua
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 201
    assert _tao(ctx, "a@x", [_vb("V2", BAN2)]).status_code == 201  # chu NULL ⇒ qua


def test_admin_tao_luot_cho_video_nguoi_khac_snapshot_ghi_chu_video(ctx):
    assert _tao(ctx, ADMIN, [_vb("V3", BAN3)]).status_code == 201
    conn = nhat_ky.mo(ctx.log_db)
    n = json.loads(conn.execute("SELECT nguon FROM tl_job_video").fetchone()[0])
    conn.close()
    assert (n["chu_video"], n["file_id_nguon"]) == ("b@x", "SRC3" + "x" * 12)


class _DriveCham(DriveGiaTL):
    def __init__(self, giay):
        super().__init__()
        self.giay = giay

    def lay_muc(self, file_id):
        import time
        time.sleep(self.giay)
        return super().lay_muc(file_id)


def _doi_drive_cham(ctx, giay):
    cham = _DriveCham(giay)
    cham.muc = ctx.drive.muc
    ctx.box["w"] = types.SimpleNamespace(drive_tl=cham, ly_do_khong_nhan=None)
    return cham


def test_chup_song_song_nhanh_hon_tuan_tu(ctx):
    import time
    _doi_drive_cham(ctx, 0.5)
    t0 = time.time()
    r = _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V2", BAN2)])
    assert r.status_code == 201 and time.time() - t0 < 0.95  # tuần tự sẽ ≥ 1,0 s


def test_chup_het_han_chung_thi_503_va_khong_tao_luot(ctx, monkeypatch):
    monkeypatch.setattr(thay_logo_routes, "HAN_CHUP_GIAY", 0.3)
    _doi_drive_cham(ctx, 1.5)
    assert _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V2", BAN2)]).status_code == 503
    assert _so_dong(ctx) == 0


def test_cung_ban_vao_hai_luot_thi_cai_thu_hai_409_lot_loi_thi_chon_lai_duoc(ctx):
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 201
    assert _tao(ctx, "a@x", [_vb("V1", BAN1), _vb("V2", BAN2)]).status_code == 409  # một mục trùng ⇒ hỏng cả lượt
    assert _tao(ctx, ADMIN, [_vb("V1", BAN1)]).status_code == 409  # người khác cũng không được giữ cùng bản
    assert _so_dong(ctx) == 1
    conn = nhat_ky.mo(ctx.log_db)
    hang_doi.dat(conn, conn.execute("SELECT id FROM tl_job_video").fetchone()[0], "loi", loi_text="x")
    conn.close()
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 201


def test_da_vao_bo_bi_cat_khi_vuot_tran(ctx, monkeypatch):
    assert ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bi_cat"] is False
    monkeypatch.setattr(thay_logo_routes, "TRAN_DONG_DA_VAO_BO", 1)
    j = ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()
    assert j["bi_cat"] is True and sum(len(b["videos"]) for b in j["bo"]) == 1
    monkeypatch.setattr(thay_logo_routes, "TRAN_DONG_DA_VAO_BO", 2)  # đúng bằng số dòng ⇒ KHÔNG cắt
    assert ctx.get("/api/thay-logo/da-vao-bo", headers=_h("a@x")).json()["bi_cat"] is False


def test_luot_khac_giu_ban_trong_luc_cho_drive_thi_kiem_lai_va_409(ctx):
    """Drive chậm: giữa lúc chụp, một lượt khác đã giữ cùng bản. Chỉ kiểm ở đầu thì lượt thứ hai lọt qua ⇒ phải kiểm LẠI ngay trước khi tạo."""
    class _Chen(DriveGiaTL):
        def lay_muc(self, file_id):
            conn = nhat_ky.mo(ctx.log_db)
            hang_doi.khoi_tao(conn)
            hang_doi.tao_job(conn, "b@x", [{"kieu": "vao_bo", "file_id": BAN1}])
            conn.close()
            return super().lay_muc(file_id)
    chen = _Chen()
    chen.muc = ctx.drive.muc
    ctx.box["w"] = types.SimpleNamespace(drive_tl=chen, ly_do_khong_nhan=None)
    assert _tao(ctx, "a@x", [_vb("V1", BAN1)]).status_code == 409
    assert _so_dong(ctx) == 1  # chỉ dòng do "lượt khác" chèn


def test_hai_post_that_cung_ban_cung_luc_chi_mot_luot_duoc_tao(ctx):
    """Hai request HTTP thật trên hai luồng, cùng một bản trong bộ. Rào chắn trong `lay_muc` giữ cả hai ở bước chụp Drive cho tới
    khi CẢ HAI đã qua kiểm tra sơ bộ (chưa ai ghi) ⇒ chỉ lần kiểm LẠI trong khoá ghi phân định được: đúng một 201, một 409, một dòng.
    ĐỘT BIẾN: bỏ `_chan_ban_da_trong_luot` trong khoá ⇒ hai 201, hai dòng ⇒ ĐỎ."""
    import threading
    rao = threading.Barrier(2, timeout=10)

    class _ChoNhau(DriveGiaTL):
        def lay_muc(self, file_id):
            rao.wait()  # cả hai request đều đang ở bước chụp ⇒ cả hai đã qua kiểm tra sơ bộ khi chưa có dòng nào
            return super().lay_muc(file_id)
    cho = _ChoNhau()
    cho.muc = ctx.drive.muc
    ctx.box["w"] = types.SimpleNamespace(drive_tl=cho, ly_do_khong_nhan=None)
    kq = []
    ts = [threading.Thread(target=lambda u=u: kq.append(_tao(ctx, u, [_vb("V1", BAN1)]).status_code)) for u in ("a@x", ADMIN)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(kq) == [201, 409]
    assert _so_dong(ctx) == 1
