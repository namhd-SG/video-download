"""Nguồn "Dán link Drive": parse link, phân loại file/thư mục bằng Drive GIẢ, route `kiem-link`, và cổng quyền của `POST /jobs`
(id ngoài thư viện chỉ nhận khi CHÍNH member đã kiểm trong 24 h). Không test nào gọi Drive thật."""
import json
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
    (f"https://docs.google.com/document/d/{ID('D')}/edit", None),  # Google Docs không nhận
    (f"https://drive.google.com/document/d/{ID('D')}/edit", None),
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
    assert ly("4")["trang_thai"] == "khong_hop_le" and "không phải video" in ly("4")["ly_do"].lower()
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
    link_da_kiem.ghi_da_kiem(conn, "a@x", [("F1", "một.mp4", 5), ("F2", "", None), ("F1", "một.mp4", 5)], luc=1000.0)
    assert link_da_kiem.con_han(conn, "a@x", ["F1", "F2", "F3"], bay_gio=1000.0 + 10) == {"F1", "F2"}
    assert link_da_kiem.con_han(conn, "b@x", ["F1"], bay_gio=1010.0) == set()
    assert link_da_kiem.con_han(conn, "a@x", ["F1"], bay_gio=1000.0 + link_da_kiem.CUA_SO_GIAY + 1) == set()
    assert link_da_kiem.ten_da_kiem(conn, "a@x", ["F1", "F2", "F3"]) == {"F1": "một.mp4", "F2": None}  # tên rỗng ⇒ None
    assert link_da_kiem.ten_da_kiem(conn, "b@x", ["F1"]) == {}
    link_da_kiem.ghi_da_kiem(conn, "a@x", [("F9", "chín.mp4", 1)], luc=1000.0 + 30 * 24 * 3600)
    assert link_da_kiem.ten_da_kiem(conn, "a@x", ["F1"]) == {"F1": "một.mp4"}  # sổ giữ lâu dài: tên còn sau khi cửa sổ 24 h hết


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


# ------------------------------------------------------------------ hạn chung, file lạ không lộ tên, đuôi + mime
def test_han_chung_ca_luot_link_cham_thanh_loi_tam_link_nhanh_van_tra(monkeypatch):
    """ĐỘT BIẾN: bỏ `timeout=` ở `wait(...)` ⇒ lượt kiểm chờ hết link chậm ⇒ ĐỎ (quá giờ)."""
    d, _ = _kho()
    d.cham[ID("S")] = 3.0
    d.them_file(ID("S"), "cham.mp4", size=MB)
    monkeypatch.setattr(nguon_drive, "TRAN_GIAY_CA_LUOT", 0.3)
    t0 = time.monotonic()
    r = nguon_drive.kiem_cac_link(d, [_link("1"), _link("S")])
    assert time.monotonic() - t0 < 2.0
    assert [k["trang_thai"] for k in r["ket_qua"]] == ["nhan", "loi_tam"] and "quá lâu" in r["ket_qua"][1]["ly_do"]


def test_file_khong_dung_duoc_khong_tra_ten_va_docs_khong_goi_drive():
    """ĐỘT BIẾN: thêm `ten=` lại vào kết quả `khong_hop_le` của file ⇒ ĐỎ."""
    d, _ = _kho()
    r = nguon_drive.kiem_cac_link(d, [_link("4"), _link("3"), f"https://docs.google.com/document/d/{ID('D')}/edit"])
    for k in r["ket_qua"]:
        assert k["trang_thai"] == "khong_hop_le" and "ten" not in k
    assert "bang-gia" not in str(r) and "to.mp4" not in str(r)
    assert d.so_lan("lay_muc_day_du") == 2  # link docs bị chặn trước khi hỏi Drive


@pytest.mark.parametrize("ten,mime,mong", [
    ("x.mp4", "video/mp4", True), ("x.bin", "video/quicktime", True), ("x.mp4", "application/octet-stream", True),
    ("x.MOV", "video/x-m4v", True), ("x.mp4", "application/pdf", False), ("x.mp4", "image/png", False),
    ("x.mkv", "video/x-matroska", False), ("x.pdf", "application/octet-stream", False),
])
def test_la_video_duoi_phai_di_kem_mime_video_hoac_octet_stream(ten, mime, mong):
    """ĐỘT BIẾN: `_la_video` chỉ xét đuôi ⇒ các ca `.mp4` + pdf/png ĐỎ."""
    assert (nguon_drive.danh_gia_file({"name": ten, "mimeType": mime, "size": "100"}) is None) is mong


def test_kiem_link_409_khi_cong_cau_hinh_cam(tmp_path):
    def require_user(request: Request) -> str:
        return request.headers["x-user"]

    class _W:
        ly_do_khong_nhan = "thư mục đầu ra nằm trong Creative"
    app, drive = FastAPI(), DriveGiaTL()
    thay_logo_routes.dang_ky_route_member(app, lambda: tmp_path / "t.db", require_user, lambda e: False, lambda: _W(),
                                          lambda e, i: set(), lay_drive=lambda: drive)
    mc = MayChu(app)
    try:
        assert _Client(mc).post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]}).status_code == 409
        assert drive.goi == []
    finally:
        mc.dung()


def test_dong_so_tro_ve_moi_dong_cung_id_ke_ca_dong_trung():
    d, _ = _kho()
    r = nguon_drive.kiem_cac_link(d, [_link("1"), "rác", f"https://drive.google.com/open?id={ID('1')}"])
    assert [k["dong_so"] for k in r["ket_qua"]] == [[0, 2], [1]]


# ------------------------------------------------------------------ tên video nhập từ link hiện ở /videos
def test_videos_hien_ten_tu_so_link_dung_nguoi_tao_va_fallback(ctx):
    """ĐỘT BIẾN: tra sổ theo email KHÁC người tạo lượt (vd email người xem) ⇒ ĐỎ ở phần admin xem."""
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1"), _link("2")]})
    assert _tao(ctx, "a@x", [ID("1"), ID("2")]).status_code == 201
    conn = nhat_ky.mo(ctx.db)
    conn.execute("UPDATE tl_link_kiem SET ten = NULL WHERE file_id = ?", (ID("2"),))
    conn.commit()
    conn.close()
    ten = lambda u: {json.loads(v["nguon"])["file_id"]: v["ten_video"] for v in ctx.get("/api/thay-logo/videos", headers=_h(u)).json()["videos"]}  # noqa: E731
    assert ten("a@x") == {ID("1"): "b.mp4", ID("2"): "Video từ link Drive"}
    assert ten("sep@x") == {ID("1"): "b.mp4", ID("2"): "Video từ link Drive"}  # admin xem lượt của a: tên theo NGƯỜI TẠO
    assert ten("b@x") == {}


def test_videos_link_toi_file_thu_vien_nguoi_khac_khong_lo_title_nen_tang_video_id(ctx):
    """A dán link tới file nằm trong thư viện của B (tool đã tải cho B ⇒ SA đọc được). /videos của A chỉ được hiện tên từ sổ của A,
    không được hiện title / nền tảng / video_id của B. ĐỘT BIẾN: bỏ phép so `chu` ở `_thu_vien_cua_chu` ⇒ ĐỎ.
    Đối chứng dương: lượt của CHÍNH B trên cùng file vẫn ghép đủ thư viện (sửa không làm mất tên của chủ)."""
    import sqlite3
    with sqlite3.connect(ctx.db.parent / "jobs.db") as c:
        c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, nguoi_tao TEXT, nen_tang TEXT)")
        c.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, job_id INTEGER, title TEXT, drive_file_id TEXT)")
        c.execute("INSERT INTO jobs VALUES (1, 'b@x', 'tiktok')")
        c.execute("INSERT INTO videos VALUES ('7777777', 1, 'Bí mật của B', ?)", (ID("1"),))
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1")]})
    assert _tao(ctx, "a@x", [ID("1")]).status_code == 201
    conn = nhat_ky.mo(ctx.db)
    from tiktok_music_downloader.thay_logo import hang_doi
    hang_doi.tao_job(conn, "b@x", [{"kieu": "drive", "file_id": ID("1")}], "", "Bộ của B")
    conn.close()

    r_a = ctx.get("/api/thay-logo/videos", headers=_h("a@x"))
    (v,) = r_a.json()["videos"]
    assert (v["ten_video"], v["anh_bia"], v["nen_tang"]) == ("b.mp4", None, None)
    than = r_a.content.decode()
    assert "Bí mật của B" not in than and "7777777" not in than and "tiktok" not in than

    (vb,) = ctx.get("/api/thay-logo/videos", headers=_h("b@x")).json()["videos"]
    assert (vb["ten_video"], vb["anh_bia"], vb["nen_tang"]) == ("Bí mật của B", "/thumbs/7777777", "tiktok")
    theo_nguoi = {x["nguoi_tao"]: x["ten_video"] for x in ctx.get("/api/thay-logo/videos", headers=_h("sep@x")).json()["videos"]}
    assert theo_nguoi == {"a@x": "b.mp4", "b@x": "Bí mật của B"}  # admin: tên theo NGƯỜI TẠO từng lượt


# ------------------------------------------------------------------ nhãn nguồn của bộ: thư viện / link / trộn
def _nguon_bo(c, user="a@x"):
    return {b["job_id"]: b["nguon_kieu"] for b in c.get("/api/thay-logo/bo", headers=_h(user)).json()["bo"]}


def _kieu_luu(c, job_id):
    conn = nhat_ky.mo(c.db)
    try:
        return {json.loads(r[0])["file_id"]: json.loads(r[0])["kieu"]
                for r in conn.execute("SELECT nguon FROM tl_job_video WHERE job_id = ?", (job_id,))}
    finally:
        conn.close()


def test_nhan_nguon_bo_chi_link_chi_thu_vien_va_tron(ctx):
    """Ca thật 09/10: lượt dán link Drive hiện "Thư viện" vì /jobs ghi `kieu: "drive"` cho MỌI id.
    ĐỘT BIẾN: ghi "drive" cho mọi id ⇒ ĐỎ (ca link + trộn). ĐỘT BIẾN: /bo lấy kiểu video ĐẦU ⇒ ĐỎ (ca trộn)."""
    ctx.post("/api/thay-logo/kiem-link", headers=_h("a@x"), json={"links": [_link("1"), _link("2")]})
    j_link = _tao(ctx, "a@x", [ID("1"), ID("2")]).json()["job_id"]
    j_tv = _tao(ctx, "a@x", ["A" * 20]).json()["job_id"]
    j_tron = _tao(ctx, "a@x", ["A" * 20, ID("1")]).json()["job_id"]
    assert _kieu_luu(ctx, j_link) == {ID("1"): "link", ID("2"): "link"}
    assert _kieu_luu(ctx, j_tv) == {"A" * 20: "drive"}
    assert _kieu_luu(ctx, j_tron) == {"A" * 20: "drive", ID("1"): "link"}
    assert _nguon_bo(ctx) == {j_link: "link", j_tv: "drive", j_tron: "nhieu"}
    assert _nguon_bo(ctx, "sep@x") == {j_link: "link", j_tv: "drive", j_tron: "nhieu"}  # admin thấy cùng nhãn


def test_admin_dan_id_ngoai_thu_vien_cua_minh_la_link(ctx):
    """Admin được bỏ qua cổng nhưng nhãn vẫn theo sự thật: id không thuộc thư viện của người tạo lượt ⇒ "link"."""
    j = _tao(ctx, "sep@x", [ID("7")]).json()["job_id"]
    assert _kieu_luu(ctx, j) == {ID("7"): "link"}


def test_the_bo_co_nhan_cho_moi_kieu_nguon():
    """Mọi `nguon_kieu` /bo có thể trả phải có chữ trên thẻ — thiếu ⇒ thẻ hiện "Nguồn khác"."""
    from web import app as app_mod
    js = (app_mod.STATIC_DIR / "thay-logo-the-bo.js").read_text(encoding="utf-8")
    for k, chu in (("drive", "Thư viện"), ("link", "Link Drive"), ("nhieu", "Nhiều nguồn")):
        assert f'{k}: "{chu}"' in js, k


# ------------------------------------------------------------------ TOCTOU của trần chờ
def test_hai_post_cung_luc_khong_cung_vuot_tran_cho(ctx, monkeypatch):
    """ĐỘT BIẾN: bỏ `BEGIN IMMEDIATE` ở tao_job ⇒ cả hai cùng đếm 0 và cùng 201 ⇒ ĐỎ."""
    import threading
    from tiktok_music_downloader.thay_logo import hang_doi

    c0 = nhat_ky.mo(ctx.db)  # DB có sẵn (đã WAL) như trên máy thật; lần mở ĐẦU của hai kết nối đồng thời là cuộc đua khác, có từ trước
    hang_doi.khoi_tao(c0)
    c0.close()
    goc = hang_doi.dem_dang_cho_cua

    def cham(conn, nguoi):
        n = goc(conn, nguoi)
        time.sleep(0.4)  # nới cửa sổ giữa "đếm" và "ghi" để cuộc đua xảy ra chắc chắn nếu không có khoá
        return n
    monkeypatch.setattr(hang_doi, "dem_dang_cho_cua", cham)
    kq = []
    mo = lambda t: [f"{t}{i:04d}" + "k" * 10 for i in range(60)]  # noqa: E731
    ts = [threading.Thread(target=lambda t=t: kq.append(_tao(ctx, "sep@x", mo(t)).status_code)) for t in "ab"]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(kq) == [201, 429]
