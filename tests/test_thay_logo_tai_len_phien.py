"""Nguồn "Tải từ máy" (đợt 4) — lõi `thay_logo/tai_len_phien.py`: tạo phiên resumable (Google GIẢ), chốt phiên, cấp file cho lượt, dọn.

Drive giả: `tests/drive_gia_thay_logo.py`; session HTTP giả: `tests/phien_http_gia_thay_logo.py`. Không mạng, không Drive thật.
Mỗi test gắn với một ĐỘT BIẾN trong plan (ghi ở docstring): bỏ đoạn code tương ứng ⇒ test phải ĐỎ."""
import json
import logging
import re
import types

import pytest
from drive_gia_thay_logo import DriveGiaTL
from phien_http_gia_thay_logo import SO_BI_MAT, URL_BI_MAT, SessionGia

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky, tai_len_phien as tl

RA = "RAFOLDER0000000000001"
ORIGIN = "https://video.nobidigital.asia"
NGAY = 86400


@pytest.fixture
def mt(tmp_path):
    drive = DriveGiaTL()
    drive.them_thu_muc(RA, "Thay logo - đầu ra")
    conn = nhat_ky.mo(tmp_path / "tl.db")
    hang_doi.khoi_tao(conn)
    tl.khoi_tao(conn)
    ss = SessionGia()
    yield types.SimpleNamespace(drive=drive, conn=conn, ss=ss, db=tmp_path / "tl.db", dem=0)
    conn.close()


def _mo(mt, email="a@x", ten="clip.mp4", size=1000, mime="video/mp4", tran=100, bay_gio=None):
    return tl.mo_phien(mt.conn, mt.drive, lambda d: mt.ss, email, ten, size, mime, RA, ORIGIN, tran, bay_gio)


def _hang(mt, token):
    return mt.conn.execute("SELECT * FROM tl_phien_tai WHERE token=?", (token,)).fetchone()


def _len_file(mt, token, *, size=1000, mime="video/mp4", the=None, cha=None):
    """Mô phỏng trình duyệt PUT xong: Drive có file mang thẻ của phiên."""
    r = _hang(mt, token)
    mt.dem += 1
    fid = f"FILE{mt.dem:016d}"
    mt.drive.them_file(fid, r["ten"], cha or r["thu_muc_id"], size=size, mime=mime, md5="MD5X",
                       app_properties={"tl_phien": the if the is not None else token})
    return fid


def _phien_xong(mt, email="a@x", **kw):
    token = _mo(mt, email)["token"]
    fid = _len_file(mt, token, **kw)
    tl.xac_nhan_xong(mt.conn, mt.drive, email, token, fid)
    return token, fid


def _tuoi(mt, token, giay, cot=("tao_luc", "cap_nhat_luc")):
    for c in cot:
        mt.conn.execute(f"UPDATE tl_phien_tai SET {c}=? WHERE token=?", (_hang(mt, token)[c] - giay, token))
    mt.conn.commit()


# ---------------------------------------------------------------- Origin
@pytest.mark.parametrize("tho,ky_vong", [
    ("https://video.nobidigital.asia", "https://video.nobidigital.asia"),
    ("https://Video.Nobidigital.ASIA/", "https://video.nobidigital.asia"),
    ("https://video.nobidigital.asia:443", "https://video.nobidigital.asia"),
    ("http://127.0.0.1:8791/", "http://127.0.0.1:8791"),
    ("https://x.asia/duong-dan", None), ("https://x.asia?a=1", None), ("ftp://x.asia", None), ("null", None), ("", None), (None, None),
    ("https://user@x.asia", None), ("video.nobidigital.asia", None),
])
def test_chuan_hoa_origin(tho, ky_vong):
    assert tl.chuan_hoa_origin(tho) == ky_vong


def test_origin_cau_hinh_thieu_hoac_sai_khuon_thi_503(monkeypatch):
    monkeypatch.delenv(tl.ENV_ORIGIN, raising=False)
    with pytest.raises(tl.LoiPhien) as e:
        tl.origin_cau_hinh()
    assert e.value.ma == 503
    monkeypatch.setenv(tl.ENV_ORIGIN, "https://x.asia/path")
    with pytest.raises(tl.LoiPhien) as e:
        tl.origin_cau_hinh()
    assert e.value.ma == 503
    monkeypatch.setenv(tl.ENV_ORIGIN, "https://X.asia/")
    assert tl.origin_cau_hinh() == "https://x.asia"


def test_kiem_origin_request_chuan_hoa_ca_hai_ve_va_vang_thi_qua():
    tl.kiem_origin_request(ORIGIN, None)  # vắng ⇒ qua
    tl.kiem_origin_request(ORIGIN, "https://VIDEO.nobidigital.asia/")  # cùng origin, khác hoa/`/` ⇒ qua (so thô sẽ 403 nhầm)
    for la in ("https://evil.example", "http://video.nobidigital.asia", "null", ""):
        with pytest.raises(tl.LoiPhien) as e:
            tl.kiem_origin_request(ORIGIN, la)
        assert e.value.ma == 403 and ORIGIN in str(e.value)


# ---------------------------------------------------------------- tạo phiên
def test_mo_phien_goi_google_dung_header_va_metadata(mt):
    kq = _mo(mt, size=2048, mime="video/quicktime", ten="Clip A.mov")
    assert set(kq) == {"token", "url_phien"} and kq["url_phien"] == URL_BI_MAT
    (g,) = mt.ss.goi
    assert g["headers"]["Origin"] == ORIGIN  # đột biến "tạo phiên không gửi Origin" ⇒ ĐỎ
    assert g["headers"]["X-Upload-Content-Length"] == "2048" and g["headers"]["X-Upload-Content-Type"] == "video/quicktime"
    assert g["timeout"] == (10, 30) and "supportsAllDrives=true" in g["url"] and "uploadType=resumable" in g["url"]
    r = _hang(mt, kq["token"])
    assert g["json"] == {"name": "Clip A.mov", "parents": [r["thu_muc_id"]], "appProperties": {"tl_phien": kq["token"]}}
    assert (r["email"], r["size"], r["mime"], r["trang_thai"], r["file_id"]) == ("a@x", 2048, "video/quicktime", "mo", None)
    assert mt.ss.da_dong == 1


def test_thu_muc_vao_theo_email_cung_cha_voi_thu_muc_ra_va_dung_lai(mt):
    t1 = _mo(mt)["token"]
    t2 = _mo(mt)["token"]
    tm = _hang(mt, t1)["thu_muc_id"]
    assert _hang(mt, t2)["thu_muc_id"] == tm
    email_dir = mt.drive.muc[tm]
    cha = mt.drive.muc[email_dir["parents"][0]]
    assert email_dir["name"] == "a@x" and cha["name"] == "Thay logo - đầu vào" and cha["parents"] == mt.drive.muc[RA]["parents"]
    assert _hang(mt, _mo(mt, "b@x")["token"])["thu_muc_id"] != tm  # người khác ⇒ thư mục khác


def test_url_phien_khong_vao_db_khong_vao_log(mt, caplog):
    """Đột biến: lưu URL phiên vào DB ⇒ ĐỎ (quét mọi bảng + byte file DB/WAL)."""
    caplog.set_level(logging.DEBUG)
    _mo(mt)
    dump = "\n".join(mt.conn.iterdump())
    assert SO_BI_MAT not in dump and "upload_id" not in dump
    for f in mt.db.parent.glob("tl.db*"):
        assert SO_BI_MAT.encode() not in f.read_bytes()
    assert SO_BI_MAT not in caplog.text and "upload_id=" not in caplog.text


@pytest.mark.parametrize("cach", ["nem", "ma_500", "location_la", "khong_location"])
def test_google_tuc_thi_503_khong_ghi_phien_va_khong_ro_url(mt, caplog, cach):
    """Đột biến: bỏ bọc exception ⇒ lỗi chứa URL lọt lên (LoiPhien không phải 503 / log có `upload_id=`) ⇒ ĐỎ."""
    caplog.set_level(logging.DEBUG)
    if cach == "nem":
        mt.ss.loi = ConnectionError(f"HTTPSConnectionPool: url: /upload/drive/v3/files?uploadType=resumable&upload_id={SO_BI_MAT}")
    elif cach == "ma_500":
        mt.ss.phan_hoi = types.SimpleNamespace(status_code=500, headers={"Location": URL_BI_MAT})
    elif cach == "location_la":
        mt.ss.phan_hoi = types.SimpleNamespace(status_code=200, headers={"Location": f"https://evil.example/x?upload_id={SO_BI_MAT}"})
    else:
        mt.ss.phan_hoi = types.SimpleNamespace(status_code=200, headers={})
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt)
    assert e.value.ma == 503
    assert SO_BI_MAT not in str(e.value) and e.value.__cause__ is None and e.value.__suppress_context__
    assert mt.conn.execute("SELECT count(*) FROM tl_phien_tai").fetchone()[0] == 0  # không để lại phiên
    assert SO_BI_MAT not in caplog.text and "upload_id=" not in caplog.text
    assert mt.ss.da_dong == 1


def test_drive_loi_khi_tim_thu_muc_thi_503_va_khong_goi_google(mt):
    mt.drive.loi[("tim_con_theo_ten", "*")] = RuntimeError("Drive chết")
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt)
    assert e.value.ma == 503 and mt.ss.goi == []
    assert mt.conn.execute("SELECT count(*) FROM tl_phien_tai").fetchone()[0] == 0


def test_cong_creative_cho_thu_muc_vao(mt):
    """Đột biến: bỏ cổng Creative cho thư mục vào ⇒ thư mục đầu vào được tạo trong cây Creative ⇒ ĐỎ."""
    mt.drive.them_thu_muc("CREATIVE000000000001", "Creative")
    mt.drive.them_thu_muc(RA, "Thay logo - đầu ra", "CREATIVE000000000001")  # thư mục ra NẰM TRONG Creative
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt)
    assert e.value.ma == 503 and "Creative" not in str(e.value)  # member không thấy chi tiết cấu hình
    assert not any(m["name"] in ("Thay logo - đầu vào", "a@x") for m in mt.drive.muc.values())
    assert mt.drive.so_lan("tao_thu_muc") == 0 and mt.ss.goi == []


def test_cong_creative_ne_loi_thi_khong_tao(mt):
    mt.drive.loi[("lay_muc", "*")] = RuntimeError("Drive chậm")  # chưa kiểm được ≠ được phép
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt)
    assert e.value.ma == 503 and mt.drive.so_lan("tao_thu_muc") == 0


@pytest.mark.parametrize("ten,size,mime", [
    ("", 10, "video/mp4"), ("x" * 201, 10, "video/mp4"), ("a\nb", 10, "video/mp4"), (None, 10, "video/mp4"),
    ("a.mp4", 0, "video/mp4"), ("a.mp4", -5, "video/mp4"), ("a.mp4", "10", "video/mp4"), ("a.mp4", True, "video/mp4"),
    ("a.mp4", 500 * 1024 * 1024 + 1, "video/mp4"),
    ("a.mp4", 10, "image/png"), ("a.mp4", 10, "video/"), ("a.mp4", 10, "video/mp4\r\nX: y"), ("a.mp4", 10, None),
])
def test_khai_bao_sai_thi_400(mt, ten, size, mime):
    with pytest.raises(tl.LoiPhien) as e:
        tl.mo_phien(mt.conn, mt.drive, lambda d: mt.ss, "a@x", ten, size, mime, RA, ORIGIN, 100)
    assert e.value.ma == 400 and mt.ss.goi == []


def test_size_dung_tran_500mib_duoc_nhan(mt):
    assert _mo(mt, size=500 * 1024 * 1024)["token"]  # dùng hằng có sẵn TRAN_DUNG_LUONG_BYTE (không hằng mới)


def test_tran_429_chung_voi_video_cho_va_chi_dem_phien_mo_con_han(mt):
    """Đột biến: đếm cả phiên `mo` cũ > 24 h ⇒ ĐỎ (khoá người dùng bằng phiên đã bị dọn/sắp dọn)."""
    cu = _mo(mt, tran=2)["token"]
    _tuoi(mt, cu, 25 * 3600, ("tao_luc",))
    _mo(mt, tran=2)  # còn chỗ: phiên cũ không tính
    _mo(mt, tran=2)  # đủ 2 phiên còn hạn (cũ không tính; nếu tính thì đã 429 ở đây)
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt, tran=2)
    assert e.value.ma == 429
    n_goi = len(mt.ss.goi)
    with pytest.raises(tl.LoiPhien):
        _mo(mt, tran=2)
    assert len(mt.ss.goi) == n_goi  # quá trần ⇒ không gọi Google
    # video đang chờ cũng tính CHUNG
    hang_doi.tao_job(mt.conn, "b@x", [{"kieu": "drive", "file_id": "F" * 20}])
    _mo(mt, "b@x", tran=2)  # 1 video chờ + 0 phiên + 1 = 2
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt, "b@x", tran=2)
    assert e.value.ma == 429
    _mo(mt, "c@x", tran=2)  # người khác không bị ảnh hưởng


def test_tran_429_tinh_ca_phien_xong_trong_24h_con_xong_cu_bo_do_da_dung_thi_khong(mt):
    """Phiên `xong` (đã chốt, chưa thành lượt) trong 24 h giữ chỗ trong trần; `xong` cũ > 24 h, `bo_do`, `da_dung` thì không.
    Đột biến: bỏ `xong` khỏi điều kiện đếm ⇒ ĐỎ (người dùng tải vượt trần rồi mới bị chặn khi tạo lượt)."""
    _phien_xong(mt)
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt, tran=1)  # 1 phiên `xong` còn hạn + 1 mới > 1
    assert e.value.ma == 429
    _mo(mt, tran=2)  # còn đúng 1 chỗ
    # `xong` cũ > 24 h (tính từ `cap_nhat_luc`) không tính
    t_cu, _ = _phien_xong(mt, "b@x")
    _tuoi(mt, t_cu, 25 * 3600)
    _mo(mt, "b@x", tran=1)
    # `bo_do` không tính
    t_bo, _ = _phien_xong(mt, "c@x")
    mt.conn.execute("UPDATE tl_phien_tai SET trang_thai='bo_do' WHERE token=?", (t_bo,))
    mt.conn.commit()
    _mo(mt, "c@x", tran=1)
    # `da_dung` không tính ở đây (nó đã là video chờ trong `hang_doi.dem_dang_cho_cua`, không đếm đôi)
    _, f_dung = _phien_xong(mt, "d@x")
    _tao_luot(mt, "d@x", f_dung)
    mt.conn.execute("UPDATE tl_job_video SET trang_thai='xong'")  # video đã xong ⇒ không còn "chờ"
    mt.conn.commit()
    _mo(mt, "d@x", tran=1)


# ---------------------------------------------------------------- chốt phiên
def test_xong_chap_nhan_file_khop_va_luu_md5(mt):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    assert tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid) == fid
    r = _hang(mt, token)
    assert (r["trang_thai"], r["file_id"], r["md5"]) == ("xong", fid, "MD5X")
    assert tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid) == fid  # FE thử lại cùng file ⇒ vẫn 200
    fid2 = _len_file(mt, token)
    with pytest.raises(tl.LoiPhien) as e:  # đã chốt file khác ⇒ 409
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid2)
    assert e.value.ma == 409


@pytest.mark.parametrize("kw", [
    {"the": "TOKEN-CUA-PHIEN-KHAC-0000000"},  # đột biến "bỏ kiểm tl_phien" ⇒ ĐỎ
    {"the": ""},  # file không mang thẻ (tải ngoài phiên)
    {"size": 999},  # đột biến "bỏ kiểm size" ⇒ ĐỎ
    {"cha": RA},  # sai thư mục cha
    {"mime": "video/webm"},
])
def test_xong_lech_thi_409(mt, kw):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token, **kw)
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid)
    assert e.value.ma == 409 and _hang(mt, token)["trang_thai"] == "mo"


def test_xong_file_trong_thung_rac_thi_409_con_drive_chua_thay_file_thi_503_de_FE_thu_lai(mt):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    mt.drive.muc[fid]["trashed"] = True
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid)
    assert e.value.ma == 409
    with pytest.raises(tl.LoiPhien) as e:  # Drive chưa thấy file (404): lệch tạm thời ⇒ 503 để FE thử lại (4xx ≠ 429 là lỗi cuối ở FE)
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, "KHONGCO000000000001")
    assert e.value.ma == 503 and _hang(mt, token)["trang_thai"] == "mo"


def test_xong_nguoi_khac_403_va_khong_co_phien_404(mt):
    """Đột biến: bỏ kiểm chủ phiên (B chốt phiên A) ⇒ ĐỎ."""
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "b@x", token, fid)
    assert e.value.ma == 403 and _hang(mt, token)["trang_thai"] == "mo"
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", "Z" * 43, fid)
    assert e.value.ma == 404


def test_xong_drive_loi_tam_thi_503_phien_van_mo(mt):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    mt.drive.loi[("lay_muc", fid)] = RuntimeError("timeout")
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid)
    assert e.value.ma == 503 and _hang(mt, token)["trang_thai"] == "mo"


def test_phien_da_bo_do_hoac_dang_don_khong_nhan_chot(mt):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    mt.conn.execute("UPDATE tl_phien_tai SET trang_thai='dang_don' WHERE token=?", (token,))
    with pytest.raises(tl.LoiPhien) as e:
        tl.xac_nhan_xong(mt.conn, mt.drive, "a@x", token, fid)
    assert e.value.ma == 409


# ---------------------------------------------------------------- cấp file cho lượt
def _tao_luot(mt, email, nguon):
    mt.conn.execute("BEGIN IMMEDIATE")
    ng = tl.dung_cho_luot(mt.conn, email, [nguon])
    j = hang_doi.tao_job(mt.conn, email, ng)
    return j, mt.conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0], ng[0]


def test_dung_cho_luot_ghi_nguon_tu_phien_va_xong_thanh_da_dung(mt):
    token, fid = _phien_xong(mt)
    j, vid, ng = _tao_luot(mt, "a@x", fid)
    assert ng == {"kieu": "may", "file_id": fid, "token": token, "ten": "clip.mp4"}
    assert json.loads(mt.conn.execute("SELECT nguon FROM tl_job_video WHERE id=?", (vid,)).fetchone()[0]) == ng
    assert _hang(mt, token)["trang_thai"] == "da_dung"


def test_mot_file_khong_vao_hai_luot(mt):
    """Đột biến: một `file_id` cho 2 lượt ⇒ ĐỎ."""
    token, fid = _phien_xong(mt)
    _tao_luot(mt, "a@x", fid)
    with pytest.raises(tl.LoiPhien) as e:
        _tao_luot(mt, "a@x", fid)
    assert e.value.ma == 409


def test_dung_lai_file_khi_moi_luot_truoc_deu_loi(mt):
    token, fid = _phien_xong(mt)
    j, vid, _ = _tao_luot(mt, "a@x", fid)
    hang_doi.dat(mt.conn, vid, "loi", loi_text="lỗi máy chủ")
    j2, vid2, _ = _tao_luot(mt, "a@x", fid)  # được dùng lại, khỏi tải lại 500 MiB
    assert _hang(mt, token)["trang_thai"] == "da_dung"
    with pytest.raises(tl.LoiPhien) as e:  # nhưng lượt mới chưa lỗi ⇒ chặn
        _tao_luot(mt, "a@x", fid)
    assert e.value.ma == 409


def test_khong_dung_lai_khi_da_don_hoac_dang_don_hoac_bo_do(mt):
    for trang_thai in ("da_don", "dang_don", "bo_do"):
        token, fid = _phien_xong(mt)
        mt.conn.execute("UPDATE tl_phien_tai SET trang_thai=? WHERE token=?", (trang_thai, token))
        mt.conn.commit()
        with pytest.raises(tl.LoiPhien) as e:
            _tao_luot(mt, "a@x", fid)
        assert e.value.ma == 409, trang_thai
        mt.conn.rollback()


def test_file_cua_nguoi_khac_hoac_khong_phai_phien_thi_403(mt):
    token, fid = _phien_xong(mt, "a@x")
    for email, f in (("b@x", fid), ("a@x", "KHONGCO000000000001")):
        with pytest.raises(tl.LoiPhien) as e:
            _tao_luot(mt, email, f)
        assert e.value.ma == 403
        mt.conn.rollback()
    assert _hang(mt, token)["trang_thai"] == "xong"


# ---------------------------------------------------------------- dọn: phiên bỏ dở
def test_don_bo_do_co_hay_khong_co_file_deu_danh_dau_bo_do(mt):
    """Đột biến: chỉ đánh dấu khi có file ⇒ phiên không file kẹt `mo` ⇒ ĐỎ."""
    co_file = _mo(mt)["token"]
    fid = _len_file(mt, co_file)  # file đã lên Drive nhưng `/xong` không bao giờ tới
    khong_file = _mo(mt)["token"]
    con_han = _mo(mt)["token"]
    for t in (co_file, khong_file):
        _tuoi(mt, t, 25 * 3600)
    kq = tl.don_mot_luot(mt.conn, mt.drive)
    assert kq["bo_do"] == 2
    assert (_hang(mt, co_file)["trang_thai"], _hang(mt, khong_file)["trang_thai"], _hang(mt, con_han)["trang_thai"]) == ("bo_do", "bo_do", "mo")
    assert mt.drive.muc[fid]["trashed"] is True


def test_don_bo_do_trash_truot_thi_giu_mo_roi_thu_lai(mt):
    token = _mo(mt)["token"]
    fid = _len_file(mt, token)
    _tuoi(mt, token, 25 * 3600)
    mt.drive.loi[("vao_thung_rac", "*")] = RuntimeError("Drive 500")
    assert tl.don_mot_luot(mt.conn, mt.drive)["bo_do"] == 0
    assert _hang(mt, token)["trang_thai"] == "mo" and mt.drive.muc[fid]["trashed"] is False
    del mt.drive.loi[("vao_thung_rac", "*")]
    assert tl.don_mot_luot(mt.conn, mt.drive)["bo_do"] == 1
    assert _hang(mt, token)["trang_thai"] == "bo_do" and mt.drive.muc[fid]["trashed"] is True


def test_don_phien_xong_qua_24h_chua_thanh_luot(mt):
    cu, fcu = _phien_xong(mt)
    moi, fmoi = _phien_xong(mt)
    _tuoi(mt, cu, 25 * 3600)
    assert tl.don_mot_luot(mt.conn, mt.drive)["xong_qua_han"] == 1
    assert _hang(mt, cu)["trang_thai"] == "bo_do" and mt.drive.muc[fcu]["trashed"] is True
    assert _hang(mt, moi)["trang_thai"] == "xong" and mt.drive.muc[fmoi]["trashed"] is False


def test_quet_theo_the_bat_phien_hoan_tat_sau_bo_do(mt):
    """Đột biến: bỏ quét theo thẻ ⇒ file xuất hiện SAU `bo_do` (URL phiên sống 1 tuần) không bao giờ bị dọn ⇒ ĐỎ."""
    token = _mo(mt)["token"]
    _tuoi(mt, token, 25 * 3600)
    tl.don_mot_luot(mt.conn, mt.drive)
    assert _hang(mt, token)["trang_thai"] == "bo_do"
    fid = _len_file(mt, token)  # upload hoàn tất MUỘN
    mt.drive.tre_chi_muc = True  # tìm theo thẻ có thể trễ ⇒ chỉ liệt kê thư mục mới thấy
    mt.drive._chua_vao_chi_muc.add(fid)
    assert mt.drive.tim_theo_the(_hang(mt, token)["thu_muc_id"], "tl_phien", token) == []
    kq = tl.don_mot_luot(mt.conn, mt.drive)
    assert kq["quet_the"]["rac"] == 1 and mt.drive.muc[fid]["trashed"] is True


def test_quet_theo_the_khong_dong_toi_phien_dang_song_va_token_la(mt, caplog):
    song = _mo(mt)["token"]
    f_song = _len_file(mt, song)
    xong, f_xong = _phien_xong(mt)
    f_la = _len_file(mt, song, the="TOKEN-KHONG-CO-TRONG-SO-0000")
    caplog.set_level(logging.WARNING)
    kq = tl.don_mot_luot(mt.conn, mt.drive)
    assert kq["quet_the"] == {"rac": 0, "the_la": 1}
    assert not any(mt.drive.muc[f]["trashed"] for f in (f_song, f_xong, f_la))  # token lạ ⇒ chỉ log
    assert "không có trong sổ" in caplog.text and "TOKEN-KHONG-CO" not in caplog.text


def test_quet_theo_the_loi_mot_thu_muc_khong_chan_thu_muc_khac(mt):
    a = _mo(mt, "a@x")["token"]
    b = _mo(mt, "b@x")["token"]
    for t in (a, b):
        _tuoi(mt, t, 25 * 3600)
    tl.don_mot_luot(mt.conn, mt.drive)
    f_a, f_b = _len_file(mt, a), _len_file(mt, b)
    mt.drive.loi[("liet_ke_con", _hang(mt, a)["thu_muc_id"])] = RuntimeError("Drive 500")
    tl.don_mot_luot(mt.conn, mt.drive)
    assert mt.drive.muc[f_b]["trashed"] is True and mt.drive.muc[f_a]["trashed"] is False


def test_phuc_hoi_khoa_dang_don_cu(mt):
    mo_, (xong, _), (dung, fdung) = _mo(mt)["token"], _phien_xong(mt), _phien_xong(mt)
    _tao_luot(mt, "a@x", fdung)
    for t in (mo_, xong, dung):
        mt.conn.execute("UPDATE tl_phien_tai SET trang_thai='dang_don', cap_nhat_luc=cap_nhat_luc-? WHERE token=?", (3600, t))
    mt.conn.commit()
    assert tl.don_mot_luot(mt.conn, mt.drive)["phuc_hoi"] == 3
    assert (_hang(mt, mo_)["trang_thai"], _hang(mt, xong)["trang_thai"], _hang(mt, dung)["trang_thai"]) == ("mo", "xong", "da_dung")


# ---------------------------------------------------------------- dọn: file nhập đã dùng
def _da_dung(mt, trang_thai_video="xong", tuoi_ngay=0, danh_gia=None):
    token, fid = _phien_xong(mt)
    j, vid, _ = _tao_luot(mt, "a@x", fid)
    log_id = None
    if danh_gia:
        log_id = nhat_ky.bat_dau_video(mt.conn, nguon_video="x")
        nhat_ky.ghi_danh_gia(mt.conn, log_id, "a@x", danh_gia, "khac" if danh_gia == "hong" else None, "")
    hang_doi.dat(mt.conn, vid, trang_thai_video, **({"video_log_id": log_id} if log_id else {}))
    mt.conn.execute("UPDATE tl_job_video SET cap_nhat_luc = cap_nhat_luc - ? WHERE id=?", (tuoi_ngay * NGAY, vid))
    mt.conn.commit()
    return token, fid, vid


def _nguon(mt, vid):
    return json.loads(mt.conn.execute("SELECT nguon FROM tl_job_video WHERE id=?", (vid,)).fetchone()[0])


@pytest.mark.parametrize("tt", ["cho", "cho_agy", "dang_chay"])
def test_khong_don_file_khi_con_video_chua_o_trang_thai_cuoi(mt, tt):
    """Đột biến: dọn khi còn 1 `tl_job_video` chưa ở trạng thái cuối ⇒ ĐỎ."""
    token, fid, vid = _da_dung(mt, tt, tuoi_ngay=400)
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0
    assert mt.drive.muc[fid]["trashed"] is False and _hang(mt, token)["trang_thai"] == "da_dung"


def test_khong_don_khi_mot_trong_hai_video_chua_cuoi(mt):
    token, fid, vid = _da_dung(mt, "loi", tuoi_ngay=400)
    j2, vid2, _ = _tao_luot(mt, "a@x", fid)  # dùng lại sau lỗi ⇒ video 2 đang `cho`
    mt.conn.commit()
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0 and mt.drive.muc[fid]["trashed"] is False


@pytest.mark.parametrize("tt", ["xong", "cho_nguoi", "loi"])
def test_don_file_da_dung_khi_moi_video_cuoi_va_qua_60_ngay(mt, tt):
    token, fid, vid = _da_dung(mt, tt, tuoi_ngay=61)
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 1
    assert mt.drive.muc[fid]["trashed"] is True and _hang(mt, token)["trang_thai"] == "da_don"
    assert _nguon(mt, vid)["da_don"] is True and _nguon(mt, vid)["token"] == token  # FE ẩn "Bản gốc"


def test_chua_qua_han_giu_thi_khong_don(mt):
    token, fid, vid = _da_dung(mt, "xong", tuoi_ngay=59)
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0 and "da_don" not in _nguon(mt, vid)


def test_danh_gia_hong_giu_180_ngay(mt):
    token, fid, vid = _da_dung(mt, "xong", tuoi_ngay=100, danh_gia="hong")
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0
    mt.conn.execute("UPDATE tl_job_video SET cap_nhat_luc = cap_nhat_luc - ? WHERE id=?", (81 * NGAY, vid))
    mt.conn.commit()
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 1


def test_ghi_da_don_sau_trash_trash_truot_thi_khong_danh_dau(mt):
    """Đột biến: ghi `da_don` TRƯỚC trash ⇒ trash trượt vẫn đánh dấu (FE ẩn "Bản gốc" của file còn nguyên) ⇒ ĐỎ."""
    token, fid, vid = _da_dung(mt, "xong", tuoi_ngay=61)
    mt.drive.loi[("vao_thung_rac", "*")] = RuntimeError("Drive 500")
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0
    assert _hang(mt, token)["trang_thai"] == "da_dung" and "da_don" not in _nguon(mt, vid) and mt.drive.muc[fid]["trashed"] is False
    del mt.drive.loi[("vao_thung_rac", "*")]
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 1  # lượt sau thử lại được
    assert _hang(mt, token)["trang_thai"] == "da_don" and _nguon(mt, vid)["da_don"] is True


def test_khoa_dang_don_chan_dung_lai_file_giua_luc_trash(mt):
    """Trong lúc trash, phiên ở `dang_don` ⇒ POST /jobs không dùng lại được file."""
    token, fid, vid = _da_dung(mt, "loi", tuoi_ngay=61)
    thu = {}

    def trong_luc_trash(drive, ten, arg):
        thu["trang_thai"] = _hang(mt, token)["trang_thai"]
        with pytest.raises(tl.LoiPhien) as e:
            _tao_luot(mt, "a@x", fid)
        thu["ma"] = e.value.ma
        mt.conn.rollback()
    mt.drive.sau_thao_tac.append(trong_luc_trash)
    tl.don_mot_luot(mt.conn, mt.drive)
    assert thu == {"trang_thai": "dang_don", "ma": 409}


def test_don_file_da_dung_kiem_lai_sau_khoa_khi_jobs_dung_lai_file_giua_hai_buoc(mt, monkeypatch):
    """Giữa lúc đọc "đủ điều kiện dọn" và lúc giữ khoá, `/jobs` dùng lại file (video mới `cho`) ⇒ sau khoá phải kiểm lại ⇒ KHÔNG trash,
    phiên về `da_dung`. Đột biến: bỏ bước kiểm lại sau `_giu` ⇒ file bị trash dù đang có video chờ ⇒ ĐỎ."""
    token, fid, vid = _da_dung(mt, "loi", tuoi_ngay=61)
    giu_that = tl._giu

    def giu_sau_khi_jobs_dung_lai(conn, tk, tu, bay_gio):
        _tao_luot(mt, "a@x", fid)  # lượt mới dùng lại file (mọi lượt cũ đều `loi` ⇒ được phép)
        conn.commit()
        return giu_that(conn, tk, tu, bay_gio)
    monkeypatch.setattr(tl, "_giu", giu_sau_khi_jobs_dung_lai)
    assert tl.don_mot_luot(mt.conn, mt.drive)["da_dung"] == 0
    assert mt.drive.muc[fid]["trashed"] is False and _hang(mt, token)["trang_thai"] == "da_dung" and "da_don" not in _nguon(mt, vid)


def test_don_xong_chua_dung_trash_truot_thi_ve_xong_khong_bo_do_roi_thu_lai(mt):
    """Trash trượt ⇒ phiên về `xong` (KHÔNG `bo_do`), lượt sau thử lại. Đột biến: trash trượt mà vẫn ghi `bo_do` ⇒ file kẹt trên Drive
    mà sổ nói đã bỏ ⇒ ĐỎ."""
    token, fid = _phien_xong(mt)
    _tuoi(mt, token, 25 * 3600)
    mt.drive.loi[("vao_thung_rac", "*")] = RuntimeError("Drive 500")
    assert tl.don_mot_luot(mt.conn, mt.drive)["xong_qua_han"] == 0
    assert _hang(mt, token)["trang_thai"] == "xong" and mt.drive.muc[fid]["trashed"] is False
    del mt.drive.loi[("vao_thung_rac", "*")]
    assert tl.don_mot_luot(mt.conn, mt.drive)["xong_qua_han"] == 1
    assert _hang(mt, token)["trang_thai"] == "bo_do" and mt.drive.muc[fid]["trashed"] is True


def test_session_that_dung_session_http_cua_drive_va_thieu_thi_503():
    sentinel = object()
    assert tl.session_that(types.SimpleNamespace(session_http=lambda: sentinel)) is sentinel
    with pytest.raises(tl.LoiPhien) as e:
        tl.session_that(object())
    assert e.value.ma == 503


def test_don_chay_khong_can_co_tai_tu_may(mt, monkeypatch):
    monkeypatch.delenv(tl.ENV_BAT, raising=False)
    token = _mo(mt)["token"]
    _tuoi(mt, token, 25 * 3600)
    assert tl.don_mot_luot(mt.conn, mt.drive)["bo_do"] == 1


def test_dang_ky_route_log_loi_luc_khoi_dong_khi_co_bat_ma_origin_sai(monkeypatch, caplog):
    from fastapi import FastAPI

    from web import thay_logo_tai_len_routes as r
    monkeypatch.setenv(tl.ENV_BAT, "1")
    monkeypatch.setenv(tl.ENV_ORIGIN, "https://x.asia/duong-dan")
    caplog.set_level(logging.ERROR)
    r.dang_ky(FastAPI(), lay_log_db=lambda: None, require_user=lambda: "a", lay_worker=lambda: None, lay_tran_cho=lambda: 1,
              mau_file_id=re.compile("."))
    assert "THAY_LOGO_ORIGIN sai khuôn" in caplog.text
    caplog.clear()
    monkeypatch.delenv(tl.ENV_BAT)  # cờ tắt ⇒ im lặng
    r.dang_ky(FastAPI(), lay_log_db=lambda: None, require_user=lambda: "a", lay_worker=lambda: None, lay_tran_cho=lambda: 1,
              mau_file_id=re.compile("."))
    assert caplog.text == ""


# ---------------------------------------------------------------- phiên của tôi: liệt kê + bỏ
def test_liet_ke_cua_toi_chi_phien_xong_cua_chinh_minh_moi_nhat_truoc_co_tran(mt):
    """ĐỘT BIẾN: bỏ `email=?` ⇒ thấy phiên người khác ⇒ ĐỎ; bỏ `trang_thai='xong'` ⇒ thấy phiên `mo`/`da_dung` ⇒ ĐỎ; bỏ ORDER/LIMIT ⇒ ĐỎ."""
    t1, f1 = _phien_xong(mt, "a@x")
    t2, f2 = _phien_xong(mt, "a@x")
    t3, f3 = _phien_xong(mt, "a@x")
    _phien_xong(mt, "b@x")                       # của người khác
    _mo(mt, "a@x")                               # `mo`: chưa tải xong
    t_dung, _ = _phien_xong(mt, "a@x")
    mt.conn.execute("UPDATE tl_phien_tai SET trang_thai='da_dung' WHERE token=?", (t_dung,))
    mt.conn.commit()
    t_cu, _ = _phien_xong(mt, "a@x")
    mt.conn.execute("UPDATE tl_phien_tai SET cap_nhat_luc=? WHERE token=?", (1_000_000_000 - 2 * NGAY, t_cu))   # quá 24 h: sắp bị dọn ⇒ không dựng lại
    for i, t in enumerate((t1, t2, t3)):
        mt.conn.execute("UPDATE tl_phien_tai SET cap_nhat_luc=? WHERE token=?", (1_000_000_000 + i, t))
    mt.conn.commit()
    ds = tl.liet_ke_cua_toi(mt.conn, "a@x", 10, bay_gio=1_000_000_000 + 100)
    assert [d["token"] for d in ds] == [t3, t2, t1]
    assert set(ds[0]) == {"token", "file_id", "ten", "size", "cap_nhat_luc"} and ds[0]["file_id"] == f3
    assert [d["token"] for d in tl.liet_ke_cua_toi(mt.conn, "a@x", 2, bay_gio=1_000_000_000 + 100)] == [t3, t2]
    assert tl.liet_ke_cua_toi(mt.conn, "nguoi-la@x", 10) == []


def test_bo_phien_mo_va_xong_ve_bo_do_idempotent_va_chi_dong_cua_minh(mt):
    """ĐỘT BIẾN: bỏ `AND trang_thai IN ('mo','xong')` khỏi UPDATE ⇒ `da_dung` bị đổi ⇒ ĐỎ (test 409)."""
    t_mo = _mo(mt, "a@x")["token"]
    t_xong, _ = _phien_xong(mt, "a@x")
    assert tl.bo_phien(mt.conn, "a@x", t_mo) == "bo_do" and tl.bo_phien(mt.conn, "a@x", t_xong) == "bo_do"
    assert tl.bo_phien(mt.conn, "a@x", t_xong) == "bo_do"                      # idempotent
    assert _hang(mt, t_mo)["trang_thai"] == _hang(mt, t_xong)["trang_thai"] == "bo_do"


def test_bo_phien_404_403_409(mt):
    token, _ = _phien_xong(mt, "a@x")
    with pytest.raises(tl.LoiPhien) as e:
        tl.bo_phien(mt.conn, "a@x", "khong-co-token-nay-0000")
    assert e.value.ma == 404
    with pytest.raises(tl.LoiPhien) as e:
        tl.bo_phien(mt.conn, "b@x", token)
    assert e.value.ma == 403 and _hang(mt, token)["trang_thai"] == "xong"
    for tt in ("da_dung", "dang_don", "da_don"):
        mt.conn.execute("UPDATE tl_phien_tai SET trang_thai=? WHERE token=?", (tt, token))
        mt.conn.commit()
        with pytest.raises(tl.LoiPhien) as e:
            tl.bo_phien(mt.conn, "a@x", token)
        assert e.value.ma == 409 and _hang(mt, token)["trang_thai"] == tt


def test_bo_phien_nha_tran_429_ngay(mt):
    """ĐỘT BIẾN: `bo_phien` không đổi trạng thái (hoặc đổi sang trạng thái vẫn tính giữ chỗ) ⇒ vẫn 429 ⇒ ĐỎ."""
    t1, _ = _phien_xong(mt, "a@x")
    t2 = _mo(mt, "a@x", tran=2)["token"]
    with pytest.raises(tl.LoiPhien) as e:
        _mo(mt, "a@x", tran=2)
    assert e.value.ma == 429
    tl.bo_phien(mt.conn, "a@x", t1)
    assert tl.dem_phien_giu_cho(mt.conn, "a@x", __import__("time").time()) == 1
    assert _mo(mt, "a@x", tran=2)["token"]
    tl.bo_phien(mt.conn, "a@x", t2)


def test_bo_phien_xong_co_file_thi_mot_luot_don_dua_file_vao_thung_rac(mt):
    """Không gọi Drive trong request `bo`; thread dọn quét theo thẻ trash file của phiên `bo_do`. ĐỘT BIẾN: bỏ `bo_do` khỏi `_quet_theo_the` ⇒ ĐỎ."""
    token, fid = _phien_xong(mt, "a@x")
    goi_truoc = len(mt.drive.goi)
    tl.bo_phien(mt.conn, "a@x", token)
    assert len(mt.drive.goi) == goi_truoc and mt.drive.muc[fid]["trashed"] is False   # request bo không đụng Drive
    kq = tl.don_mot_luot(mt.conn, mt.drive)
    assert kq["quet_the"]["rac"] == 1 and mt.drive.muc[fid]["trashed"] is True
    assert _hang(mt, token)["trang_thai"] == "bo_do"
