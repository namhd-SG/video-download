"""Ảnh KHÔNG lọt vào tính năng CHỈ-VIDEO (cụm, chia kiểu, thay logo).

Hai lớp:
  1. Cấu trúc: quét mã nguồn bốn module, mỗi câu SQL đọc bảng `videos` phải mang bí danh `v` VÀ
     điều kiện `LA_VIDEO` (hoặc nằm trong `DUOC_PHEP` kèm lý do). Câu thiếu bí danh ⇒ ĐỎ.
  2. Hành vi: job `ca_hai` (1 video + 2 ảnh) — ảnh không được đếm/liệt/gán/dựng payload/hiện ở
     thay logo, kể cả khi id ảnh bị nhét thẳng vào bảng nháp/cụm.

Đột biến (áp tạm ⇒ ĐỎ, hoàn nguyên ⇒ XANH):
  * Xoá `AND {LA_VIDEO}` (hoặc `{LA_VIDEO} AND `) khỏi MỘT câu bất kỳ trong `web/models_cum.py`,
    `web/models_chia.py`, `web/nhap_cum_cli.py`, `web/thay_logo_routes.py` — thử riêng từng module.
  * Đổi `FROM videos v` thành `FROM videos` ở một câu (bỏ bí danh `v`).
  * Bỏ `{LA_VIDEO}` khỏi truy vấn trong `thay_logo_routes._ban_vao_bo_cua` (hoặc `chu_video_vao_bo`),
    `models_cum.khung_cum` (qua `_VIDEO_TRONG_LO_CAT`), `models_chia._kiem_video_ids_thao_tac`,
    `_giai_quyet_kieu`, `_giai_quyet_kieu_vao_cum` ⇒ các test hành vi cuối file (`test_ban_vao_bo_cua_*`,
    `test_chu_video_vao_bo_*`, `test_khung_cum_*`, `test_thao_tac_theo_id_*`, `test_duyet_*_khong_nhan_anh_*`) đỏ,
    không chỉ test cấu trúc.
  * Trong `web/vao_bo_drive.py` bỏ vế `or mimeType contains 'image/'` ở truy vấn liệt kê Shared Drive
    hoặc Thùng rác (ca này đỏ ở `test_vao_bo_drive_that.py` và `test_anh_vao_bo_va_don.py`).
"""
from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from fastapi import FastAPI, Request  # noqa: E402  (chú thích kiểu phải phân giải được ở mức module)

from tiktok_music_downloader.tai_anh_cau_hinh import bai_id_anh, file_id_anh
from web import models, models_anh, models_chia, models_cum, nhap_cum_cli, thay_logo_routes

GOC = Path(__file__).resolve().parent.parent
TOI = "toi@astronex.ai"
LUC = "2026-09-29T01:00:00+00:00"

# Module -> số câu `videos` tối thiểu phải quét thấy (chặn bộ quét "xanh vì không thấy gì").
MODULE_QUET = {
    "web/models_cum.py": 3,
    "web/models_chia.py": 8,
    "web/nhap_cum_cli.py": 3,
    "web/thay_logo_routes.py": 6,
}
# (module, đoạn nhận diện câu) -> lý do không cần `LA_VIDEO`. Thêm ca mới phải ghi lý do.
DUOC_PHEP: dict[tuple[str, str], str] = {
    ("web/thay_logo_routes.py", "FROM videos v WHERE v.loai = 'anh'"):
        "chính câu dò ảnh của cổng 422: cố ý chỉ chọn ảnh, `LA_VIDEO` sẽ làm nó luôn rỗng",
}

_TU_VIDEOS = re.compile(r"\b(?:FROM|JOIN)\s+videos\b(?P<sau>\s+\w+)?", re.IGNORECASE)
_TU_KHOA_SQL = {"WHERE", "LEFT", "JOIN", "ON", "INNER", "ORDER", "GROUP", "LIMIT", "AND", "SET"}


def _cac_cau_videos(duong_dan: str) -> list[str]:
    """Văn bản của từng chuỗi (kể cả f-string, `{biểu thức}` giữ nguyên chữ) có `FROM|JOIN videos`.
    Bỏ docstring/chuỗi trần (nhắc tên bảng trong lời giải thích không phải câu SQL)."""
    cay = ast.parse((GOC / duong_dan).read_text(encoding="utf-8"))
    cha: dict[int, ast.AST] = {}
    for nut in ast.walk(cay):
        for con in ast.iter_child_nodes(nut):
            cha[id(con)] = nut
    ra: list[str] = []
    for nut in ast.walk(cay):
        if not isinstance(nut, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(cha.get(id(nut)), (ast.JoinedStr, ast.FormattedValue)) or isinstance(cha.get(id(nut)), ast.Expr):
            continue
        if isinstance(nut, ast.Constant):
            if not isinstance(nut.value, str):
                continue
            chu = nut.value
        else:
            chu = "".join(p.value if isinstance(p, ast.Constant) else "{" + ast.unparse(p.value) + "}"
                          for p in nut.values)
        if _TU_VIDEOS.search(chu):
            ra.append(chu)
    return ra


@pytest.mark.parametrize("duong_dan", MODULE_QUET)
def test_moi_cau_videos_co_bi_danh_v_va_la_video(duong_dan):
    cau = _cac_cau_videos(duong_dan)
    assert len(cau) >= MODULE_QUET[duong_dan], f"{duong_dan}: chỉ quét thấy {len(cau)} câu — bộ quét hỏng?"
    loi = []
    for c in cau:
        if any(m == duong_dan and doan in c for (m, doan) in DUOC_PHEP):
            continue
        for kh in _TU_VIDEOS.finditer(c):
            bi_danh = (kh.group("sau") or "").strip()
            if bi_danh != "v":
                loi.append(f"thiếu bí danh `v` ({bi_danh or 'không có'}): {c[:90]!r}")
        if "LA_VIDEO" not in c and "v.loai = 'video'" not in c:
            loi.append(f"thiếu LA_VIDEO: {c[:90]!r}")
    assert not loi, f"{duong_dan}:\n" + "\n".join(loi)


# --- hành vi ----------------------------------------------------------------------

def _fid(ten: str) -> str:
    return f"1{ten}_AbCdEfGhIjKlMn"


def _ghi_bai(db, job, ma, k, *, tien_to):
    bai = bai_id_anh("tt", ma)
    models_anh.ghi_bai_anh(db, [
        {"video_id": file_id_anh(bai, i), "job_id": job, "url": f"https://www.tiktok.com/@a/photo/{ma}",
         "bai_id": bai, "thu_tu": i, "drive_file_id": _fid(f"{tien_to}{i}"), "description": f"anh {ma}"}
        for i in range(1, k + 1)])
    return [file_id_anh(bai, i) for i in range(1, k + 1)]


@pytest.fixture
def kho(tmp_path):
    """Job `ca_hai` (done): video v1, v2 + bài ảnh A (A-01 còn, A-02 đã loại) ; job `chi_anh` (done): bài B."""
    db = tmp_path / "data" / "jobs.db"
    models.init_db(db)
    ca_hai = models.create_job(db, "https://www.tiktok.com/@a", 4, TOI)
    for v in ("v1", "v2"):
        models.record_video(db, job_id=ca_hai, video_id=v, url=f"u{v}", drive_file_id=_fid(v), description=v)
    a1, a2 = _ghi_bai(db, ca_hai, "111", 2, tien_to="A")
    models.danh_dau_da_loai(db, a2, TOI)
    models.finish_job(db, ca_hai, "done")
    chi_anh = models.create_job(db, "https://www.tiktok.com/@b", 2, TOI)
    b1, = _ghi_bai(db, chi_anh, "222", 1, tien_to="B")
    models.finish_job(db, chi_anh, "done")
    return {"db": db, "ca_hai": ca_hai, "chi_anh": chi_anh, "a1": a1, "a2": a2, "b1": b1}


def _sql(db, cau, *tham):
    with sqlite3.connect(db) as c:
        c.execute(cau, tham)


def test_dem_bi_loc_chi_dem_video(kho):
    db, job = kho["db"], kho["ca_hai"]
    models.danh_dau_da_loai(db, "v2", TOI)
    _sql(db, "INSERT INTO video_vao_bo (video_id, an_luc) VALUES (?, ?)", kho["a1"], LUC)   # ảnh ẩn: không tính
    with models._connect(db) as conn:
        dem = models_chia.dem_bi_loc_theo_ly_do(conn, job)
        vao = [r["video_id"] for r in models_chia.video_vao_luot_chia(conn, job)]
    assert dem == {"da_loai": 1, "da_vao_bo": 0, "da_don_drive": 0, "da_o_cum": 0}
    assert vao == ["v1"], "ảnh (kể cả còn sống) không vào lượt chia"


def test_cho_chia_bo_job_chi_anh(kho, capsys):
    assert nhap_cum_cli.main(["--db", str(kho["db"]), "cho-chia"]) == 0
    import json
    ra = json.loads(capsys.readouterr().out)
    assert [r["job_id"] for r in ra] == [kho["ca_hai"]], "job chỉ-ảnh không chờ chia; job ca_hai vẫn chờ"


def _ghi_tep(tmp_path, obj):
    import json
    tep = tmp_path / "ghi.json"
    tep.write_text(json.dumps(obj), encoding="utf-8")
    return str(tep)


def test_nhap_cum_cli_ghi_dac_diem_khong_nhan_id_anh_la_cua_job(kho, capsys, tmp_path):
    tep = _ghi_tep(tmp_path, {"dac_diem": [
        {"video_id": kho["a1"], "phien_ban_prompt": "nhan:abc@m", "nhan": {"the_chu": False}}]})
    rc = nhap_cum_cli.main(["--db", str(kho["db"]), "ghi-dac-diem", str(kho["ca_hai"]), tep])
    ra = capsys.readouterr()
    assert rc == nhap_cum_cli.MA_TEP_SAI, ra.out + ra.err
    assert "không thuộc job" in ra.err and kho["a1"] in ra.err


def test_nhap_cum_cli_ghi_de_xuat_khong_nhan_id_anh_la_cua_job(kho, capsys, tmp_path):
    tep = _ghi_tep(tmp_path, {
        "phien_ban_prompt": "p", "truc": "t", "huong_dan": [], "nghi": [], "dac_diem": [],
        "nhoms": [{"nhom": "n", "kieu": [{"kieu": "k", "video_ids": ["v1", kho["a1"]]}]}]})
    rc = nhap_cum_cli.main(["--db", str(kho["db"]), "ghi", str(kho["ca_hai"]), tep])
    ra = capsys.readouterr()
    assert rc != 0, ra.out + ra.err
    assert kho["a1"] in ra.err, ra.err


def test_nhap_cum_cli_liet_dem_tong_chi_video(kho, capsys):
    import json
    assert nhap_cum_cli.main(["--db", str(kho["db"]), "liet", str(kho["ca_hai"])]) == 0
    ra = json.loads(capsys.readouterr().out)
    assert {v["video_id"] for v in ra["video"]} == {"v1", "v2"}
    assert ra["so_video_cua_job"] == 2 and ra["so_bi_loc"] == 0
    assert kho["a1"] not in json.dumps(ra), "ảnh không được liệt cho tầng chia"


def test_lay_chia_roi_anh_vao_da_loai(kho):
    db, job = kho["db"], kho["ca_hai"]
    lan = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan, TOI, [{"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["v1"]}]}])
    with sqlite3.connect(db) as c:      # nhét thẳng một ảnh còn sống vào nháp, như dữ liệu cũ/lệch
        cn = c.execute("SELECT id FROM cum_nhap WHERE chia_lan_id = ?", (lan,)).fetchone()[0]
        c.execute("INSERT INTO video_cum_nhap (chia_lan_id, video_id, cum_nhap_id, lan) VALUES (?, ?, ?, 'kieu')",
                  (lan, kho["a1"], cn))
    r = models_chia.lay_chia(db, lan, TOI)
    assert r["kieu"][0]["video_ids"] == ["v1"], "ảnh không hiện ở làn nào của nháp"
    assert kho["a1"] not in r["bi_bo"] + r["huong_dan"] + r["nghi"]


def test_gan_video_vao_cum_bo_anh(kho):
    db = kho["db"]
    cum, _ = models_cum.tao_cum(db, TOI, "Dance", "Kiem", "lo")
    gan = models_cum.gan_video(db, cum, TOI, TOI, ["v1", kho["a1"], kho["b1"]])
    assert gan == ["v1"]
    assert models_cum.lay_cum(db, cum, TOI, TOI)["so_video"] == 1


def test_payload_lo_khong_co_anh_du_bi_nhet_vao_cum(kho):
    db = kho["db"]
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Kiem", "lo")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["v1"])
    _sql(db, "INSERT INTO video_cum (video_id, chu, cum_id) VALUES (?, ?, ?)", kho["a1"], TOI, cum_id)
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    assert cum["so_video"] == 1, "đếm cụm không tính ảnh nhét thẳng"
    p = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert p["video_ids"] == ["v1"]
    assert all(it["f"] != _fid("A1") for it in p["items"])


def test_thay_logo_thu_vien_khong_thay_anh(kho):
    db = kho["db"]
    fa = _fid("A1")
    assert thay_logo_routes.drive_ids_cua(db, TOI, [_fid("v1"), fa]) == {_fid("v1")}
    assert set(thay_logo_routes.thong_tin_thu_vien(db, [_fid("v1"), fa])) == {_fid("v1")}
    assert set(thay_logo_routes.thong_tin_theo_video(db, ["v1", kho["a1"]])) == {"v1"}


def test_thay_logo_tab_vao_bo_khong_thay_anh(kho):
    db = kho["db"]
    for v, ban in (("v1", "ban-v1"), (kho["a1"], "ban-a1")):
        _sql(db, "INSERT INTO video_vao_bo (video_id, an_luc, chu) VALUES (?, ?, ?)", v, LUC, TOI)
        _sql(db, "INSERT INTO video_vao_bo_ban (video_id, ban_copy_id, folder_id, ma_bo, bang_chung, thay_luc) "
                 "VALUES (?, ?, 'BO1', 'N.1', 'properties', ?)", v, ban, LUC)
    hang = thay_logo_routes._doc_da_vao_bo(db, TOI)
    assert [h["video_id"] for h in hang] == ["v1"]


# --- cổng 422 của POST /api/thay-logo/jobs ----------------------------------------

def require_user(request: Request) -> str:
    return request.headers["x-user"]


@pytest.fixture
def api(tmp_path, kho):
    from test_thay_logo_relay import _Client
    from thay_logo_may_chu import MayChu

    admin = "sep@x"
    app = FastAPI()

    thay_logo_routes.dang_ky_route_member(
        app, lambda: kho["db"].parent / "tl.db", require_user, lambda e: e == admin, lambda: object(), lambda email, ids: set(ids))
    mc = MayChu(app)
    yield _Client(mc), admin
    mc.dung()


def _h(u):
    return {"x-user": u}


def test_tao_job_thay_logo_id_anh_la_422_cho_ca_admin_lan_member(api, kho):
    c, admin = api
    for nguoi in (TOI, admin):
        r = c.post("/api/thay-logo/jobs", headers=_h(nguoi),
                   json={"drive_file_ids": [_fid("A1")], "ten_bo": "Bộ thử"})
        assert r.status_code == 422, (nguoi, r.status_code)
        r = c.post("/api/thay-logo/jobs", headers=_h(nguoi),
                   json={"vao_bo": [{"video_id": kho["a1"], "ban_copy_id": "BanA1_AbCdEfGhIj"}], "ten_bo": "Bộ thử"})
        assert r.status_code == 422, (nguoi, r.status_code)
        r = c.post("/api/thay-logo/jobs", headers=_h(nguoi),
                   json={"drive_file_ids": [_fid("v1"), _fid("B1")], "ten_bo": "Bộ thử"})
        assert r.status_code == 422, "một ảnh lẫn trong lô video cũng chặn cả lô"
    r = c.post("/api/thay-logo/jobs", headers=_h(TOI), json={"drive_file_ids": [_fid("v1")], "ten_bo": "Bộ thử"})
    assert r.status_code == 201, (r.status_code, r.content)


# --- hành vi: các câu truy vấn mà bộ quét cấu trúc một mình không giữ được ----------------------------

def _gan_ban_trong_bo(db, kho):
    """Video v1 và ảnh a1 cùng có bản sao trong bộ (ảnh vào sổ qua dữ liệu lệch/cũ)."""
    for v, ban in (("v1", "ban-v1"), (kho["a1"], "ban-a1")):
        _sql(db, "INSERT INTO video_vao_bo (video_id, an_luc, chu) VALUES (?, ?, ?)", v, LUC, TOI)
        _sql(db, "INSERT INTO video_vao_bo_ban (video_id, ban_copy_id, folder_id, ma_bo, bang_chung, thay_luc) "
                 "VALUES (?, ?, 'BO1', 'N.1', 'properties', ?)", v, ban, LUC)


@pytest.mark.parametrize("nguoi_tao", [TOI, None], ids=["thanh_vien", "admin"])
def test_ban_vao_bo_cua_khong_nhan_ban_cua_anh(kho, nguoi_tao):
    from fastapi import HTTPException
    db = kho["db"]
    _gan_ban_trong_bo(db, kho)
    muc_v = thay_logo_routes.MucVaoBo(video_id="v1", ban_copy_id="ban-v1")
    muc_a = thay_logo_routes.MucVaoBo(video_id=kho["a1"], ban_copy_id="ban-a1")
    assert set(thay_logo_routes._ban_vao_bo_cua(db, nguoi_tao, [muc_v])) == {"ban-v1"}
    with pytest.raises(HTTPException) as e:
        thay_logo_routes._ban_vao_bo_cua(db, nguoi_tao, [muc_a])
    assert e.value.status_code == 403, "bản sao của ảnh không được ra như bản sao của video"
    with pytest.raises(HTTPException) as e:
        thay_logo_routes._ban_vao_bo_cua(db, nguoi_tao, [muc_v, muc_a])
    assert e.value.status_code == 403, "một ảnh lẫn trong lô video chặn cả lô"


def test_chu_video_vao_bo_khong_tra_chu_cua_anh(kho):
    db = kho["db"]
    _gan_ban_trong_bo(db, kho)
    assert set(thay_logo_routes.chu_video_vao_bo(db, ["v1", kho["a1"]])) == {"v1"}


def test_khung_cum_khong_tra_anh_nhet_thang_vao_cum(kho):
    db = kho["db"]
    cum, _ = models_cum.tao_cum(db, TOI, "Dance", "Kiem", "lo")
    models_cum.gan_video(db, cum, TOI, TOI, ["v1"])
    _sql(db, "INSERT INTO video_cum (video_id, chu, cum_id) VALUES (?, ?, ?)", kho["a1"], TOI, cum)
    assert [r["video_id"] for r in models_cum.khung_cum(db, TOI, TOI)] == ["v1"]


def _nhap_anh_vao_kieu(kho):
    """Lượt chia có kiểu chứa v1 và (dữ liệu lệch) ảnh a1 còn sống: trả (chia_lan_id, cum_nhap_id)."""
    db = kho["db"]
    lan = models_chia.tao_chia_lan(db, kho["ca_hai"], TOI, "p1")
    models_chia.ghi_de_xuat(db, lan, TOI, [{"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["v1"]}]}])
    with sqlite3.connect(db) as c:
        cn = c.execute("SELECT id FROM cum_nhap WHERE chia_lan_id = ?", (lan,)).fetchone()[0]
        c.execute("INSERT INTO video_cum_nhap (chia_lan_id, video_id, cum_nhap_id, lan) VALUES (?, ?, ?, 'kieu')",
                  (lan, kho["a1"], cn))
    return lan, cn


def test_thao_tac_theo_id_tu_choi_anh_nhu_video_da_loai(kho):
    lan, _ = _nhap_anh_vao_kieu(kho)
    with models._connect(kho["db"]) as conn:
        kq = models_chia._kiem_video_ids_thao_tac(conn, lan, TOI, [kho["a1"]])
    assert kq == {"tu_choi": "video_da_loai", "video_ids": [kho["a1"]]}


def _cac_video_trong_cum_that(db):
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT video_id FROM video_cum")}


def test_duyet_kieu_tao_cum_moi_khong_nhan_anh_nhet_vao_kieu(kho):
    lan, cn = _nhap_anh_vao_kieu(kho)
    models_chia.duyet_kieu(kho["db"], lan, cn, TOI, TOI, usecase="Dance", insight_goc="Kiem")
    assert _cac_video_trong_cum_that(kho["db"]) == {"v1"}


def test_duyet_kieu_gop_vao_cum_co_san_khong_nhan_anh_nhet_vao_kieu(kho):
    lan, cn = _nhap_anh_vao_kieu(kho)
    cum, _ = models_cum.tao_cum(kho["db"], TOI, "Dance", "Kiem", "lo")
    models_chia.duyet_kieu(kho["db"], lan, cn, TOI, TOI, usecase="Dance", insight_goc="Kiem", gop_vao_cum_id=cum)
    assert _cac_video_trong_cum_that(kho["db"]) == {"v1"}
