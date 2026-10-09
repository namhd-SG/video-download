"""Nguồn "Dán link Drive": parse link, phân loại file/thư mục bằng Drive GIẢ, route `kiem-link`, và cổng quyền của `POST /jobs`
(id ngoài thư viện chỉ nhận khi CHÍNH member đã kiểm trong 24 h). Không test nào gọi Drive thật."""
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from drive_gia_thay_logo import DriveGiaTL  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from test_thay_logo_relay import _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo import link_da_kiem, nguon_drive, nhat_ky  # noqa: E402
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongQuyen  # noqa: E402
from web import thay_logo_routes  # noqa: E402

MB = 1024 * 1024
ID = lambda c: (c * 20)[:20]  # noqa: E731 — id Drive giả đúng khuôn (20 ký tự)


# ------------------------------------------------------------------ parse
@pytest.mark.parametrize("dong,mong", [
    (f"https://drive.google.com/file/d/{ID('A')}/view?usp=sharing", ID("A")),
    (f"https://drive.google.com/file/d/{ID('A')}/view", ID("A")),
    (f"https://drive.google.com/drive/folders/{ID('B')}", ID("B")),
    (f"https://drive.google.com/drive/folders/{ID('B')}?usp=sharing", ID("B")),
    (f"https://drive.google.com/drive/u/0/folders/{ID('B')}", ID("B")),
    (f"https://drive.google.com/drive/u/2/my-drive/folders/{ID('B')}", ID("B")),
    (f"https://drive.google.com/open?id={ID('C')}", ID("C")),
    (f"https://drive.google.com/open?id={ID('C')}&usp=drive_fs", ID("C")),
    (f"https://drive.google.com/uc?id={ID('C')}&export=download", ID("C")),
    (f"https://drive.google.com/u/0/file/d/{ID('A')}/view", ID("A")),
    (f"  https://drive.google.com/file/d/{ID('A')}/view  ", ID("A")),
    (f"https://docs.google.com/document/d/{ID('D')}/edit", ID("D")),
    # rác
    ("", None), ("hello", None), (ID("A"), None),
    (f"https://evil.example.com/file/d/{ID('A')}/view", None),
    (f"https://drive.google.com.evil.example/file/d/{ID('A')}/view", None),
    (f"ftp://drive.google.com/file/d/{ID('A')}/view", None),
    ("https://drive.google.com/file/d/ab/view", None),
    ("https://drive.google.com/open?id=../../etc", None),
    ("https://drive.google.com/", None),
])
def test_tach_id_moi_dang_link_va_rac(dong, mong):
    assert nguon_drive.tach_id(dong) == mong


def test_tach_dong_bo_dong_trong_va_tach_theo_dong():
    assert nguon_drive.tach_dong(["a\n\n  b  \r\nc", "", "  "]) == ["a", "b", "c"]


# ------------------------------------------------------------------ phân loại
def _kho():
    d = DriveGiaTL()
    d.them_thu_muc("TM1" + "x" * 17, "Review T10", drive="D1")
    tm = "TM1" + "x" * 17
    d.them_file(ID("1"), "b.mp4", tm, size=10 * MB)
    d.them_file(ID("2"), "a.MOV", tm, size=20 * MB, mime="video/quicktime")
    d.them_file(ID("3"), "to.mp4", tm, size=600 * MB)                      # quá 500 MB
    d.them_file(ID("4"), "bang-gia.pdf", tm, size=1 * MB, mime="application/pdf")
    d.them_file(ID("5"), "da-xoa.mp4", tm, size=5 * MB, trashed=True)
    d.them_file(ID("6"), "khong-size.mp4", tm, size=None)
    d.them_file(ID("7"), "khac.mkv", tm, size=5 * MB, mime="video/x-matroska")
    d.them_thu_muc("SUB" + "y" * 17, "Thư mục con", cha=tm)
    d.them_file(ID("8"), "trong-con.mp4", "SUB" + "y" * 17, size=5 * MB)   # video nằm trong thư mục CON
    d.them_file(ID("9"), "dat-ten-mp4-sai-mime", tm, size=5 * MB, mime="application/octet-stream")
    return d, tm


def test_thu_muc_chi_lay_video_truc_tiep_va_dem_thu_muc_con():
    d, tm = _kho()
    kq = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/drive/folders/{tm}"])["ket_qua"][0]
    assert kq["trang_thai"] == "nhan" and kq["kieu"] == "thu_muc" and kq["ten"] == "Review T10"
    assert [v["ten"] for v in kq["videos"]] == ["a.MOV", "b.mp4"]
    assert ID("8") not in [v["id"] for v in kq["videos"]]          # video trong thư mục con KHÔNG lấy
    assert kq["bo_qua_thu_muc_con"] == 1
    assert kq["bo_qua_khac"] == 5  # quá nặng, pdf, không size, mkv, đuôi không phải video (trashed không đếm)
    assert [v["size"] for v in kq["videos"]] == [20 * MB, 10 * MB]
    assert d.so_lan("liet_ke_con") == 1  # không đệ quy vào thư mục con


def test_loc_size_mime_trashed_o_file_le():
    d, _ = _kho()
    ly = lambda i: nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/file/d/{ID(i)}/view"])["ket_qua"][0]  # noqa: E731
    assert ly("1")["trang_thai"] == "nhan" and ly("1")["size"] == 10 * MB
    assert ly("3")["trang_thai"] == "khong_hop_le" and "500 MB" in ly("3")["ly_do"]
    assert ly("4")["trang_thai"] == "khong_hop_le" and "không phải video" in ly("4")["ly_do"]
    assert ly("5")["trang_thai"] == "khong_hop_le" and "thùng rác" in ly("5")["ly_do"]
    assert ly("6")["trang_thai"] == "khong_hop_le"
    assert ly("7")["trang_thai"] == "khong_hop_le"


def test_dung_500mb_la_nhan_501mb_la_tu_choi():
    d = DriveGiaTL()
    d.them_file(ID("a"), "vua.mp4", size=500 * MB)
    d.them_file(ID("b"), "qua.mp4", size=500 * MB + 1)
    r = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/file/d/{ID('a')}/view", f"https://drive.google.com/file/d/{ID('b')}/view"])
    assert [k["trang_thai"] for k in r["ket_qua"]] == ["nhan", "khong_hop_le"]


def test_thu_muc_trong_hoac_qua_300_video_bi_tu_choi_co_ly_do():
    d = DriveGiaTL()
    d.them_thu_muc("RONG" + "z" * 16, "Rỗng")
    d.them_thu_muc("DAY" + "z" * 17, "Đầy")
    for i in range(nguon_drive.TRAN_VIDEO_THU_MUC + 1):
        d.them_file(f"V{i:04d}" + "q" * 15, f"v{i}.mp4", "DAY" + "z" * 17, size=MB)
    r = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/drive/folders/{'RONG' + 'z' * 16}", f"https://drive.google.com/drive/folders/{'DAY' + 'z' * 17}"])
    assert [k["trang_thai"] for k in r["ket_qua"]] == ["khong_hop_le", "khong_hop_le"]
    assert "tối đa 300" in r["ket_qua"][1]["ly_do"]
    d.muc.pop(f"V{0:04d}" + "q" * 15)  # đúng 300 ⇒ nhận
    r = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/drive/folders/{'DAY' + 'z' * 17}"])
    assert r["ket_qua"][0]["trang_thai"] == "nhan" and len(r["ket_qua"][0]["videos"]) == 300


def test_403_404_la_khong_mo_duoc_kem_email_may_con_loi_khac_la_loi_tam():
    d, tm = _kho()
    d.khong_quyen.add(ID("Q"))
    d.loi[("lay_muc_day_du", ID("T"))] = TimeoutError("mạng")
    r = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/file/d/{ID('Q')}/view", f"https://drive.google.com/file/d/{ID('N')}/view",
                                      f"https://drive.google.com/file/d/{ID('T')}/view"])
    assert [k["trang_thai"] for k in r["ket_qua"]] == ["khong_mo_duoc", "khong_mo_duoc", "loi_tam"]
    assert r["email_may"] == d.email
    # lỗi tạm KHÔNG được đọc thành "chưa chia sẻ" (member sẽ đi chia sẻ vô ích)
    assert "chia sẻ" not in r["ket_qua"][2]["ly_do"]
    r2 = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/file/d/{ID('1')}/view"])
    assert r2["email_may"] is None and d.so_lan("email_dich_vu") == 0


def test_thu_muc_khong_quyen_o_buoc_liet_ke_cung_la_khong_mo_duoc():
    d, tm = _kho()
    d.loi[("liet_ke_con", tm)] = DriveTLKhongQuyen(tm)
    assert nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/drive/folders/{tm}"])["ket_qua"][0]["trang_thai"] == "khong_mo_duoc"


def test_trung_id_bo_va_dong_sai_van_co_ket_qua():
    d, _ = _kho()
    r = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/file/d/{ID('1')}/view", f"https://drive.google.com/open?id={ID('1')}", "rác", "rác 2"])
    assert r["trung_bo"] == 1 and [k["trang_thai"] for k in r["ket_qua"]] == ["nhan", "khong_hop_le", "khong_hop_le"]
    assert d.so_lan("lay_muc_day_du") == 1


def test_ids_duoc_nhan_chi_lay_id_file_khong_lay_id_thu_muc():
    d, tm = _kho()
    kq = nguon_drive.kiem_cac_link(d, [f"https://drive.google.com/drive/folders/{tm}", f"https://drive.google.com/file/d/{ID('1')}/view"])["ket_qua"]
    ids = nguon_drive.ids_duoc_nhan(kq)
    assert tm not in ids and set(ids) == {ID("1"), ID("2")}


# ------------------------------------------------------------------ route + cổng quyền POST /jobs
@pytest.fixture
def ctx(tmp_path):
    db = tmp_path / "tl.db"

    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    app = FastAPI()
    drive, _ = _kho()
    thu_vien = {"a@x": {"A" * 20}}
    thay_logo_routes.dang_ky_route_member(app, lambda: db, require_user, lambda e: e == "sep@x", lambda: object(),
                                          lambda email, ids: thu_vien.get(email, set()) & set(ids), lay_drive=lambda: drive)
    mc = MayChu(app)
    c = _Client(mc)
    c.drive, c.db = drive, db
    yield c
    mc.dung()


def _h(u):
    return {"x-user": u}


def _link(i):
    return f"https://drive.google.com/file/d/{ID(i)}/view"


def _tao(c, user, ids):
    return c.post("/api/thay-logo/jobs", headers=_h(user), json={"drive_file_ids": ids, "ten_bo": "Bộ thử"})


def test_kiem_link_tra_ket_qua_moi_dong_va_email_may(ctx):
    r = ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [f"{_link('1')}\n{_link('Q')}\n{_link('4')}"]})
    assert r.status_code == 200
    j = r.json()
    assert [k["trang_thai"] for k in j["ket_qua"]] == ["nhan", "khong_mo_duoc", "khong_hop_le"]
    assert j["email_may"] == ctx.drive.email and j["da_ghi_nhan"] == 1
    assert j["ket_qua"][0]["ten"] == "b.mp4"


def test_kiem_link_tran_20_link_va_rong_la_400(ctx):
    ok = ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")] * 20})
    assert ok.status_code == 200
    assert ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link(str(i % 9)) for i in range(21)]}).status_code == 400
    assert ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": ["\n  \n"]}).status_code == 400
    assert ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": ["x" * 41_000]}).status_code == 400


def test_kiem_link_tinh_nang_tat_409_va_drive_chua_cau_hinh_409(tmp_path):
    def require_user(request: Request) -> str:
        return request.headers["x-user"]
    for worker, cau_hinh in ((None, True), (object(), False)):
        app, drive = FastAPI(), DriveGiaTL()
        drive.cau_hinh = cau_hinh
        thay_logo_routes.dang_ky_route_member(app, lambda: tmp_path / "t.db", require_user, lambda e: False, lambda w=worker: w,
                                              lambda e, i: set(), lay_drive=lambda d=drive: d)
        mc = MayChu(app)
        try:
            assert _Client(mc).post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]}).status_code == 409
        finally:
            mc.dung()


def test_jobs_id_chua_kiem_la_403(ctx):
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 403
    assert _tao(ctx, "a@x", ["A" * 20, ID("1")]).status_code == 403  # lẫn thư viện + id chưa kiểm: một id sai là từ chối cả lượt


def test_jobs_id_da_kiem_la_201_ca_file_le_lan_video_trong_thu_muc(ctx):
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1"), "https://drive.google.com/drive/folders/" + "TM1" + "x" * 17]})
    assert _tao(ctx, "a@x", [ID("1"), ID("2"), "A" * 20]).status_code == 201
    # id thư mục KHÔNG phải id file được phép; video nằm trong thư mục CON chưa từng được kiểm
    assert _tao(ctx, "a@x", ["TM1" + "x" * 17]).status_code == 403
    assert _tao(ctx, "a@x", [ID("8")]).status_code == 403


def test_jobs_id_do_member_khac_kiem_la_403(ctx):
    """ĐỘT BIẾN: bỏ điều kiện `email = ?` trong `link_da_kiem.con_han` ⇒ ĐỎ."""
    ctx.post("/api/thay-logo/kiem-link", headers=_h("b@x"), json={"links": [_link("1")]})
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 403
    assert _tao(ctx, "b@x", [ID("1")]).status_code == 201


def test_jobs_id_kiem_qua_24h_la_403_kiem_lai_thi_het_han_tinh_lai(ctx):
    """ĐỘT BIẾN: bỏ điều kiện `luc >= ?` ⇒ ĐỎ."""
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]})
    conn = nhat_ky.mo(ctx.db)
    conn.execute("UPDATE tl_link_kiem SET luc = ?", (time.time() - link_da_kiem.CUA_SO_GIAY - 60,))
    conn.commit()
    conn.close()
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 403
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]})
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 201


def test_jobs_id_ngay_sat_moc_23h_van_nhan(ctx):
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]})
    conn = nhat_ky.mo(ctx.db)
    conn.execute("UPDATE tl_link_kiem SET luc = ?", (time.time() - 23 * 3600,))
    conn.commit()
    conn.close()
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 201


def test_admin_van_dan_id_bat_ky_khong_can_kiem(ctx):
    assert _tao(ctx, "sep@x", [ID("1")]).status_code == 201


def test_link_khong_dung_duoc_khong_duoc_ghi_vao_so(ctx):
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("4"), _link("3"), _link("Q")]})
    assert _tao(ctx, "a@x", [ID("4")]).status_code == 403 and _tao(ctx, "a@x", [ID("3")]).status_code == 403


def test_con_han_va_ghi_da_kiem_o_tang_thap(tmp_path):
    conn = nhat_ky.mo(tmp_path / "t.db")
    link_da_kiem.khoi_tao(conn)
    link_da_kiem.ghi_da_kiem(conn, "a@x", ["F1", "F2", "F1"], luc=1000.0)
    assert link_da_kiem.con_han(conn, "a@x", ["F1", "F2", "F3"], bay_gio=1000.0 + 10) == {"F1", "F2"}
    assert link_da_kiem.con_han(conn, "b@x", ["F1"], bay_gio=1010.0) == set()
    assert link_da_kiem.con_han(conn, "a@x", ["F1"], bay_gio=1000.0 + link_da_kiem.CUA_SO_GIAY + 1) == set()
    link_da_kiem.ghi_da_kiem(conn, "a@x", ["F9"], luc=1000.0 + 8 * 24 * 3600)  # ghi mới dọn dòng cũ hơn 7 ngày
    assert conn.execute("SELECT count(*) FROM tl_link_kiem").fetchone()[0] == 1


def test_tran_mot_luot_la_100_bang_tran_cho_va_429_khi_cong_don_vuot(ctx):
    """USER CHỐT: không trần theo bộ. ĐỘT BIẾN: `TRAN_VIDEO_MOT_JOB = 50` ⇒ ĐỎ. Dùng admin (không cần kiểm id)."""
    assert thay_logo_routes.TRAN_VIDEO_MOT_JOB == thay_logo_routes.TRAN_CHO_MOI_NGUOI == 100
    ids = lambda n, t: [f"{t}{i:04d}" + "k" * 10 for i in range(n)]  # noqa: E731
    assert _tao(ctx, "sep@x", ids(101, "a")).status_code == 422
    assert _tao(ctx, "sep@x", ids(100, "b")).status_code == 201          # chưa có chờ ⇒ nhận đủ 100
    assert _tao(ctx, "sep@x", ids(1, "c")).status_code == 429           # đã đủ 100 chờ


def test_60_cho_cong_50_moi_la_429(ctx):
    assert _tao(ctx, "sep@x", [f"p{i:04d}" + "k" * 10 for i in range(60)]).status_code == 201
    assert _tao(ctx, "sep@x", [f"q{i:04d}" + "k" * 10 for i in range(50)]).status_code == 429
    assert _tao(ctx, "sep@x", [f"r{i:04d}" + "k" * 10 for i in range(40)]).status_code == 201
