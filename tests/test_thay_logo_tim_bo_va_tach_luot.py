"""Tab "Bộ tự tìm" có ô tìm (`GET /da-vao-bo?q=&tu=&den=`) và giỏ trộn tách HAI lượt nguyên tử (`POST /jobs` với `dich_khac`).

- Tìm lọc ở mức BỘ: bộ khớp ⇒ trả ĐỦ video của bộ (không xé lẻ theo ngày của từng bản sao); ngày so theo chuỗi ISO UTC, ranh giới ngày VN.
- Giỏ trộn (bản trong bộ + nguồn khác) ⇒ hai `tl_job` trong một giao dịch: lượt "Đã vào bộ" không mang `dich_khac`, lượt kia mang.
Drive là bản giả; không test nào gọi mạng."""
import sqlite3
import types
from urllib.parse import urlencode

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from drive_gia_thay_logo import DriveGiaTL  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from test_thay_logo_relay import _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky  # noqa: E402
from web import models, models_vao_bo, thay_logo_routes  # noqa: E402

BAN1, BAN2, BAN3 = "BANCOPY0001" + "a" * 10, "BANCOPY0002" + "b" * 10, "BANCOPY0003" + "c" * 10
F1, F2 = "FOLDERBO1" + "f" * 12, "FOLDERBO2" + "g" * 12
SRC1, SRC4 = "SRC1" + "x" * 12, "SRC4" + "x" * 12


@pytest.fixture
def ctx(tmp_path):
    jobs = tmp_path / "jobs.db"
    models.init_db(jobs)
    ja = models.create_job(jobs, "https://x/a", 3, "a@x", nen_tang="tiktok")
    models.record_video(jobs, ja, "V1", "https://x/v1", title="Máy hút bụi", drive_file_id=SRC1)
    models.record_video(jobs, ja, "V2", "https://x/v2", title="Chảo", drive_file_id="SRC2" + "x" * 12)
    models.record_video(jobs, ja, "V3", "https://x/v3", title="Son", drive_file_id="SRC3" + "x" * 12)
    models.record_video(jobs, ja, "V4", "https://www.tiktok.com/@a/video/4", title="Nồi", drive_file_id=SRC4)
    models_vao_bo.ghi_da_vao_bo(jobs, "V1", None, [dict(ban_copy_id=BAN1, folder_id=F1, ma_bo="N.1510C", bang_chung="properties")])
    models_vao_bo.ghi_da_vao_bo(jobs, "V2", None, [dict(ban_copy_id=BAN2, folder_id=F1, ma_bo="N.1510C", bang_chung="properties")])
    models_vao_bo.ghi_da_vao_bo(jobs, "V3", None, [dict(ban_copy_id=BAN3, folder_id=F2, ma_bo="N_1210B", bang_chung="properties")])
    with sqlite3.connect(jobs) as c:  # bộ F1: bản đầu 15/10 (VN), bản sau 16/10 — tìm theo ngày phải trả ĐỦ cả bộ
        c.execute("UPDATE video_vao_bo_ban SET thay_luc='2026-10-15T03:00:00.000000+00:00' WHERE ban_copy_id=?", (BAN1,))
        c.execute("UPDATE video_vao_bo_ban SET thay_luc='2026-10-16T03:00:00.000000+00:00' WHERE ban_copy_id=?", (BAN2,))
        c.execute("UPDATE video_vao_bo_ban SET thay_luc='2026-10-12T03:00:00.000000+00:00' WHERE ban_copy_id=?", (BAN3,))
    drive = DriveGiaTL()
    drive.them_thu_muc(F1, "N.1510C")
    drive.them_thu_muc(F2, "N_1210B")
    drive.them_file(BAN1, "v1.mp4", F1, md5="MD5-1", size="111")
    drive.them_file(BAN2, "v2.mp4", F1, md5="MD5-2", size="222")
    drive.them_file(BAN3, "v3.mp4", F2, md5="MD5-3", size="333")
    log_db = tmp_path / "tl.db"
    worker = types.SimpleNamespace(drive_tl=drive, ly_do_khong_nhan=None)

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    thay_logo_routes.dang_ky_route_member(app, lambda: log_db, require_user, lambda e: False, lambda: worker,
                                          lambda email, ids: {i for i in ids if email == "a@x" and i.startswith("SRC")},
                                          lay_jobs_db=lambda: jobs)
    mc = MayChu(app)
    c = _Client(mc)
    c.log_db = log_db
    yield c
    mc.dung()


def _h(u):
    return {"x-user": u}


def _bo(c, **q):
    r = c.get("/api/thay-logo/da-vao-bo?" + urlencode(q), headers=_h("a@x"))
    assert r.status_code == 200, r.text
    return {b["ma_bo"]: sorted(v["ban_copy_id"] for v in b["videos"]) for b in r.json()["bo"]}


def test_tim_theo_ma_bo_khong_phan_biet_hoa_thuong(ctx):
    assert _bo(ctx, q="1510") == {"N.1510C": [BAN1, BAN2]}
    assert _bo(ctx, q="n.1510c") == {"N.1510C": [BAN1, BAN2]}
    assert _bo(ctx) == {"N.1510C": [BAN1, BAN2], "N_1210B": [BAN3]}


def test_ky_tu_dac_biet_trong_q_khong_thanh_ky_tu_dai_dien(ctx):
    # `_` trong LIKE khớp MỌI ký tự: không thoát thì "N_1" khớp cả "N.1510C".
    assert _bo(ctx, q="N_1") == {"N_1210B": [BAN3]}
    assert _bo(ctx, q="%") == {}


def test_loc_ngay_theo_bo_tra_du_video_cua_bo(ctx):
    # Bộ N.1510C vào bộ ngày 15/10 (bản sớm nhất). Lọc 15/10 ⇒ ĐỦ 2 video, kể cả bản thêm ngày 16/10.
    assert _bo(ctx, tu="2026-10-15", den="2026-10-15") == {"N.1510C": [BAN1, BAN2]}
    # Lọc 16/10: ngày vào bộ của N.1510C là 15/10 ⇒ không khớp (không xé lẻ 1 video ra thành "bộ" riêng).
    assert _bo(ctx, tu="2026-10-16", den="2026-10-16") == {}
    assert _bo(ctx, tu="2026-10-10") == {"N.1510C": [BAN1, BAN2], "N_1210B": [BAN3]}
    assert _bo(ctx, q="1210", tu="2026-10-13") == {}


def test_ngay_sai_khuon_tra_400(ctx):
    assert ctx.get("/api/thay-logo/da-vao-bo?tu=15%2F10", headers=_h("a@x")).status_code == 400


def test_nguoi_khac_khong_thay_bo_cua_minh_khi_tim(ctx):
    r = ctx.get("/api/thay-logo/da-vao-bo?q=1510", headers=_h("b@x"))
    assert r.status_code == 200 and r.json()["bo"] == []


def _jobs(c):
    conn = nhat_ky.mo(c.log_db)
    hang_doi.khoi_tao(conn)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT j.id, j.ten_bo, j.dich_khac, count(v.id) AS n FROM tl_job j JOIN tl_job_video v ON v.job_id=j.id GROUP BY j.id ORDER BY j.id")]
    finally:
        conn.close()


def test_gio_tron_tach_hai_luot_nguyen_tu(ctx):
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={
        "vao_bo": [{"video_id": "V1", "ban_copy_id": BAN1}, {"video_id": "V2", "ban_copy_id": BAN2}],
        "drive_file_ids": [SRC4], "ten_bo": "16/10-1", "dich_khac": "tao_bo"})
    assert r.status_code == 201, r.text
    assert len(r.json()["job_ids"]) == 2
    j = _jobs(ctx)
    assert [(x["ten_bo"], x["dich_khac"], x["n"]) for x in j] == [("N.1510C", None, 2), ("16/10-1", "tao_bo", 1)]


def test_mot_nguon_khac_mac_dinh_drive(ctx):
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": [SRC4], "ten_bo": "16/10-2"})
    assert r.status_code == 201, r.text
    assert [(x["dich_khac"], x["n"]) for x in _jobs(ctx)] == [("drive", 1)]


def test_chi_vao_bo_khong_mang_dich_khac(ctx):
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={
        "vao_bo": [{"video_id": "V3", "ban_copy_id": BAN3}], "ten_bo": "N_1210B", "dich_khac": "tao_bo"})
    assert r.status_code == 201, r.text
    assert [(x["dich_khac"], x["n"]) for x in _jobs(ctx)] == [(None, 1)]


def test_dich_khac_la_tra_400_va_khong_tao_luot(ctx):
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": [SRC4], "ten_bo": "x", "dich_khac": "ftp"})
    assert r.status_code == 400
    assert not ctx.log_db.exists() or _jobs(ctx) == []


def test_luot_2_hong_thi_luot_1_cung_khong_con(ctx, monkeypatch):
    # Nguyên tử: lượt thứ hai trượt giữa giao dịch ⇒ lượt "Đã vào bộ" cũng rollback, bấm lại không vướng 409 "đã trong lượt khác".
    goc = hang_doi.tao_job

    def tao_job_hong_lan_2(conn, *a, **kw):
        if kw.get("dich_khac"):
            raise RuntimeError("giả lập hỏng giữa chừng")
        return goc(conn, *a, **kw)
    monkeypatch.setattr(hang_doi, "tao_job", tao_job_hong_lan_2)
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={
        "vao_bo": [{"video_id": "V1", "ban_copy_id": BAN1}], "drive_file_ids": [SRC4], "ten_bo": "x", "dich_khac": "drive"})
    assert r.status_code == 500
    monkeypatch.setattr(hang_doi, "tao_job", goc)
    assert _jobs(ctx) == []
    r = ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={
        "vao_bo": [{"video_id": "V1", "ban_copy_id": BAN1}], "drive_file_ids": [SRC4], "ten_bo": "x", "dich_khac": "drive"})
    assert r.status_code == 201, r.text


def test_bo_tra_dich_khac_va_videos_tra_url(ctx):
    ctx.post("/api/thay-logo/jobs", headers=_h("a@x"), json={"drive_file_ids": [SRC4], "ten_bo": "16/10-3", "dich_khac": "tao_bo"})
    bo = ctx.get("/api/thay-logo/bo", headers=_h("a@x")).json()["bo"]
    assert [b["dich_khac"] for b in bo] == ["tao_bo"]
    vd = ctx.get("/api/thay-logo/videos", headers=_h("a@x")).json()["videos"]
    assert [v["url"] for v in vd] == ["https://www.tiktok.com/@a/video/4"]
