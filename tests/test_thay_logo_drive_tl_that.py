"""`DriveTLThat` với service GIẢ ném `HttpError` THẬT của googleapiclient: phân biệt 403 "không được quyền" với 403 hết hạn mức,
404, 429/5xx; phân trang `liet_ke_con`; danh sách trường. Không gọi mạng."""
import json

import pytest

pytest.importorskip("googleapiclient")
import httplib2  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

from tiktok_music_downloader.thay_logo import drive_tl  # noqa: E402
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongQuyen, DriveTLKhongThay, DriveTLThat  # noqa: E402


def _loi(status, reason=None, **them):
    thân = {"error": {"code": status, "message": "x", "errors": [{"reason": reason}] if reason else [], **them}}
    return HttpError(httplib2.Response({"status": status}), json.dumps(thân).encode())


class _Goi:
    def __init__(self, ket_qua, ghi):
        self.ket_qua, self.ghi = ket_qua, ghi

    def execute(self):
        r = self.ket_qua.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Files:
    def __init__(self, ket_qua):
        self.ket_qua, self.goi = list(ket_qua), []

    def get(self, **kw):
        self.goi.append(("get", kw))
        return _Goi(self.ket_qua, self.goi)

    def list(self, **kw):
        self.goi.append(("list", kw))
        return _Goi(self.ket_qua, self.goi)


class _Svc:
    def __init__(self, ket_qua):
        self.f = _Files(ket_qua)

    def files(self):
        return self.f


def _drive(ket_qua):
    d = DriveTLThat(uploader=object())
    svc = _Svc(ket_qua)
    d._svc_ngan = lambda: svc
    return d, svc.f


@pytest.mark.parametrize("loi,mong", [
    (_loi(403, "insufficientFilePermissions"), DriveTLKhongQuyen),
    (_loi(403, "forbidden"), DriveTLKhongQuyen),
    (_loi(404, "notFound"), DriveTLKhongThay),
    (_loi(404), DriveTLKhongThay),
    (_loi(403, "userRateLimitExceeded"), HttpError),
    (_loi(403, "rateLimitExceeded"), HttpError),
    (_loi(403, "dailyLimitExceeded"), HttpError),
    (_loi(403), HttpError),                      # 403 không đọc được lý do ⇒ "chưa đo được", KHÔNG đoán là chưa chia sẻ
    (_loi(429, "rateLimitExceeded"), HttpError),
    (_loi(500, "backendError"), HttpError),
    (_loi(503), HttpError),
])
def test_phan_loai_loi_http_lay_muc_day_du_va_liet_ke(loi, mong):
    """ĐỘT BIẾN: xoá vế phân biệt hạn mức (mọi 403 ⇒ KhongQuyen) ⇒ các ca rateLimit/403 trơn ĐỎ."""
    d, _ = _drive([loi])
    with pytest.raises(mong) as e:
        d.lay_muc_day_du("F" * 20)
    assert type(e.value) is mong or isinstance(e.value, mong)
    if mong is HttpError:
        assert not isinstance(e.value, (DriveTLKhongQuyen, DriveTLKhongThay))
    d, _ = _drive([loi])
    with pytest.raises(mong):
        d.liet_ke_con("F" * 20, 10)


def test_thân_loi_khong_phai_json_khong_ne_ra_khong_quyen():
    e = HttpError(httplib2.Response({"status": 403}), b"<html>insufficientFilePermissions</html>")
    d, _ = _drive([e])
    with pytest.raises(HttpError):
        d.lay_muc_day_du("F" * 20)  # chuỗi con nằm trong thân KHÔNG đủ — phải là `reason` trong JSON


def test_phan_trang_dung_o_toi_da_va_khong_goi_corpora():
    """ĐỘT BIẾN: bỏ `while len(out) < toi_da` ⇒ gọi thêm trang / trả quá `toi_da` ⇒ ĐỎ. Thêm `corpora` lại ⇒ ĐỎ."""
    f = lambda *ids: {"files": [{"id": i} for i in ids]}  # noqa: E731
    d, files = _drive([{**f("a", "b"), "nextPageToken": "T2"}, {**f("c", "d"), "nextPageToken": "T3"}, f("e")])
    assert [x["id"] for x in d.liet_ke_con("P" * 10, 3)] == ["a", "b", "c"]
    loi = [kw for t, kw in files.goi if t == "list"]
    assert len(loi) == 2 and loi[0].get("pageToken") is None and loi[1]["pageToken"] == "T2"
    assert loi[0]["pageSize"] == 3 and loi[1]["pageSize"] == 1
    assert all("corpora" not in kw and kw["supportsAllDrives"] and kw["includeItemsFromAllDrives"] for kw in loi)
    d, _ = _drive([{**f("a"), "nextPageToken": "T2"}, f("b")])
    assert [x["id"] for x in d.liet_ke_con("P" * 10, 100)] == ["a", "b"]  # hết trang thì dừng


def test_incomplete_search_la_loi_khong_phai_thu_muc_it_video():
    """ĐỘT BIẾN: bỏ kiểm `incompleteSearch` ⇒ ĐỎ."""
    d, _ = _drive([{"files": [{"id": "a"}], "incompleteSearch": True}])
    with pytest.raises(RuntimeError, match="incompleteSearch"):
        d.liet_ke_con("P" * 10, 10)


def test_id_la_khong_di_vao_cau_truy_van():
    d, files = _drive([])
    with pytest.raises(ValueError):
        d.liet_ke_con("x' or '1'='1", 10)
    assert files.goi == []


def test_truong_video_khai_tuong_minh_khong_lap_size():
    parts = drive_tl.TRUONG_VIDEO.split(",")
    assert len(parts) == len(set(parts)) and "size" in parts
    d, files = _drive([{"id": "x"}])
    d.lay_muc_day_du("F" * 20)
    assert files.goi[0][1]["fields"] == drive_tl.TRUONG_VIDEO
