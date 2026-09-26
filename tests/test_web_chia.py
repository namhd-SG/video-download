"""Tự chia cụm theo lượt — route (`web/app.py`): `/chia/*` và payload `nhan`
dựng ở server (`GET /cum/{id}/lo/{thu}/payload`).

Gọi thẳng hàm route như `tests/test_web_cum.py` (venv không có httpx), truyền
`nguoi_tao` thay cho dependency đã giải.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from web import app as app_mod
from web import models, models_chia, models_cum
from web.auth import require_user

TOI = "toi@astronex.ai"
HO = "ho@astronex.ai"
_REPO = Path(__file__).resolve().parent.parent
_JS_HARNESS = _REPO / "tests" / "js" / "payload-ban-giao-cu.js"
_OLD_APP_JS_SHA = "97c6f3b"   # commit ngay TRƯỚC khi payload chuyển sang dựng ở server — bản JS cũ tự ghép `nhan`


def _drive(vid: str) -> str:
    return f"1Drive_{vid}_AbCdEfGhIjKl"


@pytest.fixture
def kho(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.moi_admin_tu_env(db, [])
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 6, TOI)
    for i, vid in enumerate(("1", "2", "3", "4", "5", "6")):
        # Link gốc và Drive id có HÌNH DẠNG THẬT: payload lọc theo luật bên
        # nhận (`models_chia._item_hop_le_ben_nhan`), id giả kiểu "d1" bị bỏ.
        models.record_video(db, job_id=job, video_id=vid,
                            url=f"https://www.tiktok.com/@a/video/{vid}",
                            title=f"Video {vid}", drive_file_id=_drive(vid))
    return db, job


def _de_xuat(db, job, chu=TOI, a=("1", "2"), b=("3",)):
    lan_id = models_chia.tao_chia_lan(db, job, chu, "p1")
    models_chia.ghi_de_xuat(db, lan_id, chu, [
        {"nhom": "trang phục", "kieu": [
            {"kieu": "couple", "video_ids": list(a)},
            {"kieu": "cartoon", "video_ids": list(b)},
        ]},
    ])
    return lan_id


def _nhom_id(db, lan_id, kieu, chu=TOI):
    chia = models_chia.lay_chia(db, lan_id, chu)
    return next(k["cum_nhap_id"] for k in chia["kieu"] if k["kieu"] == kieu)


# --- GET /chia/{job_id} ------------------------------------------------------

def test_lay_chia_cua_job_tra_404_neu_chua_co_luot(kho):
    db, job = kho
    with pytest.raises(HTTPException) as e:
        app_mod.lay_chia_cua_job(job, nguoi_tao=TOI)
    assert e.value.status_code == 404


def test_lay_chia_cua_job_khong_thay_luot_cua_nguoi_khac(kho):
    db, job = kho
    _de_xuat(db, job)
    out = app_mod.lay_chia_cua_job(job, nguoi_tao=TOI)
    assert out["kieu"]
    with pytest.raises(HTTPException) as e:
        app_mod.lay_chia_cua_job(job, nguoi_tao=HO)
    assert e.value.status_code == 404


# --- POST /chia/{id}/thao-tac -------------------------------------------------

def test_thao_tac_route_404_cho_luot_khong_phai_cua_minh(kho):
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(
            loai="chap_nhan", cum_nhap_id=_nhom_id(db, lan_id, "couple")), nguoi_tao=HO)
    assert e.value.status_code == 404


def test_thao_tac_route_400_khi_loai_khong_hop_le(kho):
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(loai="xoa-het-du-lieu"),
                              nguoi_tao=TOI)
    assert e.value.status_code == 400


def test_thao_tac_route_409_khi_dich_khong_hop_le(kho):
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(
            loai="doi_ten", cum_nhap_id=999999, kieu="x"), nguoi_tao=TOI)
    assert e.value.status_code == 409


def test_thao_tac_route_chap_nhan_thanh_cong(kho):
    db, job = kho
    lan_id = _de_xuat(db, job)
    couple_id = _nhom_id(db, lan_id, "couple")
    out = app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(
        loai="chap_nhan", cum_nhap_id=couple_id), nguoi_tao=TOI)
    assert out["so_video"] == 2


def test_thao_tac_route_400_khi_hoan_tac_khong_con_gi(kho):
    """Mã lỗi ở tầng ROUTE: `hoan_tac` "không còn gì để lùi" là 400 (trạng
    thái bình thường tự chạm tới), KHÁC 409 của "đích không hợp lệ" (test
    trên) — cùng `{"tu_choi": "khong_hop_le"}` ở tầng model, khác mã ở tầng
    route vì `body.loai` quyết định."""
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(loai="hoan_tac"), nguoi_tao=TOI)
    assert e.value.status_code == 400


@pytest.mark.parametrize("loai,tham_so", [
    ("gop", {}), ("doi_ten", {"cum_nhap_id": 1}), ("chuyen", {"video_ids": ["1"]}),
    ("tra_ve", {"den_cum_nhap_id": 1}), ("ngoai_chu_de", {}), ("xoa_kieu", {}),
    ("chap_nhan", {}),
])
def test_thao_tac_route_400_khong_500_khi_thieu_truong_bat_buoc(kho, loai, tham_so):
    """`{"loai":"gop"}` (không `tu_cum_nhap_id`/`den_cum_nhap_id`) từng ném
    `TypeError` ra tới route ⇒ 500 không bắt được. Giờ phải là 400 rõ ràng,
    không bao giờ 500."""
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(loai=loai, **tham_so),
                              nguoi_tao=TOI)
    assert e.value.status_code == 400, f"{loai}({tham_so}) phải trả 400, không phải 500/khác"


def test_hoan_tac_route_400_khong_500_sau_khi_kieu_da_duyet(kho):
    """`chuyen` một video khỏi "couple" rồi duyệt đúng "couple" rồi hoàn tác
    thao tác `chuyen` đó rơi xuống một `sqlite3.IntegrityError` (khoá
    ngoại) — route phải bắt CẢ `IntegrityError`, không chỉ `ValueError`, để
    trả 400 sạch thay vì lộ ra thành 500."""
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(
        loai="chuyen", video_ids=["1"], den_cum_nhap_id=cartoon_id), nguoi_tao=TOI)
    app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
        cum_nhap_id=couple_id, usecase="Dance", insight_goc="Badaboum"), nguoi_tao=TOI)
    with pytest.raises(HTTPException) as e:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(loai="hoan_tac"), nguoi_tao=TOI)
    assert e.value.status_code == 400, "phải là 400 sạch, KHÔNG được rơi thành 500 (IntegrityError)"


def test_duyet_kieu_va_duyet_het_route_400_giong_nhau_khi_insight_trong(kho):
    """Cả hai đường duyệt phải trả CÙNG mã lỗi (400) cho cùng một đầu vào —
    `duyet_het` trước đây trả 200 kèm `loi_ten` cho ca này, khác hẳn
    `duyet_kieu`."""
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    with pytest.raises(HTTPException) as e1:
        app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
            cum_nhap_id=couple_id, usecase="", insight_goc=""), nguoi_tao=TOI)
    with pytest.raises(HTTPException) as e2:
        app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(usecase="", insight_goc=""),
                          nguoi_tao=TOI)
    assert e1.value.status_code == e2.value.status_code == 400
    assert e1.value.detail == e2.value.detail, "cùng đầu vào phải cho cùng câu chữ ở cả hai đường"


def test_lay_chia_cua_job_admin_xem_duoc_nhung_khong_sua_duyet_thay(kho, monkeypatch):
    """Addendum điều phối 24/09: admin XEM được nháp người khác, KHÔNG
    sửa/duyệt thay — `/thao-tac` và `/duyet` vẫn khoá theo `chu` thật, y hệt
    người thường (404, không lộ chênh lệch hành vi cho admin vs người lạ)."""
    db, job = kho   # job của TOI
    lan_id = _de_xuat(db, job)
    monkeypatch.setattr(app_mod, "_la_admin", lambda email: email == HO)
    out = app_mod.lay_chia_cua_job(job, nguoi_tao=HO)
    assert out["kieu"], "admin xem được nháp của người khác"
    couple_id = _nhom_id(db, lan_id, "couple")
    with pytest.raises(HTTPException) as e1:
        app_mod.thao_tac_chia(lan_id, app_mod.ThaoTacChiaRequest(
            loai="chap_nhan", cum_nhap_id=couple_id), nguoi_tao=HO)
    assert e1.value.status_code == 404, "admin KHÔNG sửa thay người khác"
    with pytest.raises(HTTPException) as e2:
        app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
            usecase="Dance", insight_goc="Badaboum"), nguoi_tao=HO)
    assert e2.value.status_code == 404, "admin KHÔNG duyệt thay người khác"


# --- POST /chia/{id}/duyet ----------------------------------------------------

def test_duyet_route_mot_kieu_va_tat_ca_con_lai(kho):
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    out = app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
        cum_nhap_id=couple_id, usecase="Dance", insight_goc="Badaboum"), nguoi_tao=TOI)
    assert sorted(out["gan"]) == ["1", "2"]

    out2 = app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
        usecase="Dance", insight_goc="Badaboum"), nguoi_tao=TOI)
    assert len(out2["cum"]) == 1 and out2["cum"][0]["gan"] == ["3"]
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "da_duyet"


def test_duyet_route_404_cho_luot_khong_phai_cua_minh(kho):
    db, job = kho
    lan_id = _de_xuat(db, job)
    with pytest.raises(HTTPException) as e:
        app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(usecase="Dance",
                                                            insight_goc="Badaboum"),
                          nguoi_tao=HO)
    assert e.value.status_code == 404


def test_duyet_route_400_khi_nhan_sai_hop_dong(kho):
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1",), b=("2",))
    couple_id = _nhom_id(db, lan_id, "couple")
    with pytest.raises(HTTPException) as e:
        app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
            cum_nhap_id=couple_id, usecase="   ", insight_goc="Badaboum"), nguoi_tao=TOI)
    assert e.value.status_code == 400


def test_duyet_route_tra_trung_cum_co_san_khong_gop(kho):
    db, job = kho
    cu_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    lan_id = _de_xuat(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    out = app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
        cum_nhap_id=couple_id, usecase="Dance", insight_goc="Badaboum"), nguoi_tao=TOI)
    assert out["trung_cum_co_san"][0]["cum_id"] == cu_id
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_cum").fetchone()[0] == 0

    out2 = app_mod.duyet_chia(lan_id, app_mod.DuyetChiaRequest(
        cum_nhap_id=couple_id, usecase="Dance", insight_goc="Badaboum",
        xac_nhan_gop=[cu_id]), nguoi_tao=TOI)
    assert out2["cum_id"] == cu_id and out2["da_co"] is True


# --- GET /cum/{id}/lo/{thu}/payload -------------------------------------------

def test_payload_route_404_cho_cum_nguoi_khac(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1"])
    with pytest.raises(HTTPException) as e:
        app_mod.payload_lo_cum(cum_id, 1, nguoi_tao=HO)
    assert e.value.status_code == 404


def test_payload_route_tu_choi_id_khong_phai_cum_that(kho):
    """Route CHỈ nhận cụm THẬT — một id chỉ tồn tại ở `cum_nhap` (nháp) không
    được xem là cụm hợp lệ; route trả 404 giống hệt cụm không tồn tại."""
    db, job = kho
    lan_id = _de_xuat(db, job)
    cum_nhap_id = _nhom_id(db, lan_id, "couple")
    with sqlite3.connect(db) as conn:
        # id nháp này có thật KHÔNG trùng bất kỳ id nào trong bảng `cum` thật
        # (hai bảng đếm AUTOINCREMENT độc lập) — vẫn kiểm tường minh cho chắc.
        assert conn.execute("SELECT COUNT(*) FROM cum WHERE id = ?",
                            (cum_nhap_id,)).fetchone()[0] == 0
    with pytest.raises(HTTPException) as e:
        app_mod.payload_lo_cum(cum_nhap_id, 1, nguoi_tao=TOI)
    assert e.value.status_code == 404


def test_payload_route_400_khi_lo_ngoai_khoang(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1"])
    with pytest.raises(HTTPException) as e:
        app_mod.payload_lo_cum(cum_id, 2, nguoi_tao=TOI)
    assert e.value.status_code == 400


def test_payload_route_dung_hop_dong_nhan(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3"])
    out = app_mod.payload_lo_cum(cum_id, 1, nguoi_tao=TOI)
    assert out["v"] == 1 and len(out["items"]) == 3
    assert out["nhan"] == {"usecase": "Dance", "insight": "Badaboum couple", "template": "Goc",
                           "cum_id": cum_id, "lo": {"thu": 1, "tong": 1}}
    for item in out["items"]:
        assert set(item) == {"f", "n", "u"}


def test_payload_route_video_khong_len_drive_bi_bo(kho):
    db, job = kho
    models.record_video(db, job_id=job, video_id="99", url="u99")   # không drive_file_id
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "99"])
    out = app_mod.payload_lo_cum(cum_id, 1, nguoi_tao=TOI)
    assert [i["f"] for i in out["items"]] == [_drive("1")]


# --- cửa ngoài ----------------------------------------------------------------

@pytest.mark.parametrize("path,method", [
    ("/chia/{job_id}", "GET"), ("/chia/{chia_lan_id}/thao-tac", "POST"),
    ("/chia/{chia_lan_id}/duyet", "POST"), ("/cum/{cum_id}/lo/{thu}/payload", "GET"),
])
def test_chia_routes_require_a_verified_user(path, method):
    routes = [r for r in app_mod.app.routes
              if getattr(r, "path", None) == path and method in getattr(r, "methods", set())]
    assert routes, f"không tìm thấy route {method} {path}"
    assert any(d.call is require_user for d in routes[0].dependant.dependencies)


# --- byte-equal với bản JS CŨ (client tự ghép) trên CÙNG dữ liệu --------------
#
# Trước đây so với một bản PYTHON cổng lại logic JS, dùng `sort_keys=True` —
# điều đó chứng minh được GIÁ TRỊ khớp, KHÔNG chứng minh được THỨ TỰ KHOÁ
# khớp, và không hề chạy JS thật. Giờ trích NGUYÊN VĂN
# `nhanTuCum`/`dungPayload`/`itemBanGiao`/`chiaLo`/`videoCuaCum` từ chính
# commit TRƯỚC khi payload chuyển sang dựng ở server
# (`git show 97c6f3b:web/static/app.js`), chạy qua `node` trên một fixture
# cụm, rồi so CHUỖI JSON byte-for-byte (không `sort_keys` — thứ tự khoá phải
# khớp tự nhiên, không cần sắp lại mới bằng nhau).

def _node_or_skip() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy bản JS cũ thật — không có thì test này KHÔNG chạy")
    return node


def _payload_kieu_cu_qua_js_that(db, cum_id: int, chu: str, thu: int, handoff_max: int) -> str:
    """Chuỗi JSON payload dựng bằng CHÍNH bản JS cũ (git show, chạy qua node),
    không phải một bản Python đoán lại logic của nó."""
    node = _node_or_skip()
    ket = subprocess.run(
        ["git", "show", f"{_OLD_APP_JS_SHA}:web/static/app.js"],
        cwd=_REPO, capture_output=True, text=True)
    if ket.returncode != 0:
        # Lịch sử git cho commit này không có ở checkout đang chạy (vd một
        # bản clone NÔNG/shallow) — đây là một GIỚI HẠN MÔI TRƯỜNG, không
        # phải một hồi quy của code đang kiểm; test này KHÔNG chứng minh
        # được gì trong ca đó nên phải SKIP, không FAIL (mà cũng không được
        # âm thầm PASS).
        pytest.skip(f"không đọc được {_OLD_APP_JS_SHA}:web/static/app.js qua git "
                    f"(có thể do clone nông, thiếu lịch sử): {ket.stderr.strip()}")
    old_src = ket.stdout
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT v.video_id, v.title, v.url, v.drive_file_id FROM video_cum vc "
            "JOIN videos v ON v.video_id = vc.video_id "
            "WHERE vc.chu = ? AND vc.cum_id = ? ORDER BY v.tao_luc DESC, v.video_id DESC",
            (chu, cum_id)).fetchall()
    # DESC ở trên: `state.videos` thật (từ `GET /videos`) liệt MỚI trước — bản
    # JS cũ tự `.reverse()` bên trong `videoCuaCum` để có "cũ nhất trước".
    cum = models_cum.lay_cum(db, cum_id, chu, chu)
    with tempfile.TemporaryDirectory(prefix="payload-cu-") as tmp:
        old_src_path = Path(tmp) / "app-cu.js"
        old_src_path.write_text(old_src, encoding="utf-8")
        fixture_path = Path(tmp) / "fixture.json"
        fixture_path.write_text(json.dumps({
            # `cum_id` thêm tay: `videoCuaCum` (bản JS cũ) lọc
            # `state.videos` theo `v.cum_id === cumId` — cột đó KHÔNG có
            # trong bảng `videos`/`video_cum` phía SQL (chỉ tồn tại ở
            # `state.videos` phía client, ghép lúc render trang), nên phải
            # tự thêm vào fixture cho khớp hình dạng client thật.
            "videos": [{**dict(r), "cum_id": cum_id} for r in rows], "cum": cum, "thu": thu,
            "handoffMax": handoff_max,
        }), encoding="utf-8")
        r = subprocess.run([node, str(_JS_HARNESS), str(old_src_path), str(fixture_path)],
                           capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _py_json_compact(d: dict) -> str:
    """Cùng định dạng `JSON.stringify` mặc định của node: KHÔNG khoảng trắng
    thừa, unicode giữ nguyên (không escape) — để so byte-for-byte có nghĩa."""
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def test_payload_server_khop_byte_voi_ban_js_cu_tren_cung_cum(kho):
    db, job = kho
    # 34 video: 1 lô 30 + 1 lô dư 4 — buộc phải cắt lô đúng để so byte-equal.
    for i in range(34):
        vid = f"v{i}"
        models.record_video(
            db, job_id=job, video_id=vid, url=f"https://t/{vid}", title=f"Tiêu đề {i}",
            drive_file_id=(_drive(vid) if i % 5 else None),   # rải vài video chưa lên Drive
            tao_luc=(datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(seconds=i)).isoformat())
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, [f"v{i}" for i in range(34)])

    for thu in (1, 2):
        cu = _payload_kieu_cu_qua_js_that(db, cum_id, TOI, thu, models_cum.LO_TOI_DA)
        moi = _py_json_compact(app_mod.payload_lo_cum(cum_id, thu, nguoi_tao=TOI))
        assert moi == cu, f"lô {thu}: payload server phải byte-equal với bản JS cũ"


# --- id số nguyên ngoài miền SQLite ⇒ 422, không 500 --------------------------

def _post_asgi(path: str, body: dict) -> int:
    """Gửi MỘT request POST thẳng vào ứng dụng ASGI (venv không có httpx cho
    TestClient) — đi qua đúng tầng parse body của FastAPI, nơi sinh ra 422.
    Lỗi không bắt được trong route vẫn được `ServerErrorMiddleware` trả 500
    trước khi ném lại; bắt nó ở đây để đọc được mã trạng thái đã gửi."""
    import asyncio

    gui: list[dict] = []

    async def nhan():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    async def gui_di(tin):
        gui.append(tin)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "client": ("test", 1),
             "server": ("test", 80), "headers": [(b"content-type", b"application/json")]}
    app_mod.app.dependency_overrides[require_user] = lambda: TOI
    try:
        asyncio.run(app_mod.app(scope, nhan, gui_di))
    except Exception:  # noqa: BLE001 — lỗi route đã được trả 500 ở trên, xem docstring
        pass
    finally:
        app_mod.app.dependency_overrides.pop(require_user, None)
    return next(t["status"] for t in gui if t["type"] == "http.response.start")


@pytest.mark.parametrize("duong,than", [
    ("thao-tac", {"loai": "chap_nhan", "cum_nhap_id": 2 ** 70}),
    ("thao-tac", {"loai": "gop", "tu_cum_nhap_id": 2 ** 70, "den_cum_nhap_id": 1}),
    ("thao-tac", {"loai": "chuyen", "video_ids": ["1"], "den_cum_nhap_id": 2 ** 70}),
    ("thao-tac", {"loai": "chap_nhan", "cum_nhap_id": 0}),
    ("duyet", {"cum_nhap_id": 2 ** 70}),
    ("duyet", {"xac_nhan_gop": [2 ** 70]}),
])
def test_id_ngoai_mien_sqlite_tra_422_khong_500(kho, duong, than):
    """Id lớn hơn INTEGER 64-bit của SQLite từng tới tận câu SQL ⇒
    `OverflowError` ⇒ 500. Id phải bị chặn ở tầng request (≥1, ≤ 2**63-1)."""
    db, job = kho
    lan_id = _de_xuat(db, job)
    assert _post_asgi(f"/chia/{lan_id}/{duong}", than) == 422


def test_id_hop_le_qua_asgi_van_200(kho):
    """Đối chứng dương cho `_post_asgi`: cùng đường gọi, id thật ⇒ 200."""
    db, job = kho
    lan_id = _de_xuat(db, job)
    assert _post_asgi(f"/chia/{lan_id}/thao-tac",
                      {"loai": "chap_nhan", "cum_nhap_id": _nhom_id(db, lan_id, "couple")}) == 200
