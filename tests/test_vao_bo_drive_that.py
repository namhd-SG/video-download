"""`DriveThat` — hai truy vấn mới của pha (a) và các truy vấn cũ, qua một dịch vụ GIẢ (stub)
bắt lại từng tham số. Không có mạng, không có credential.
"""
from __future__ import annotations

import types

import pytest
from googleapiclient.errors import HttpError

from web.vao_bo_drive import TOI_DA_ID_MOI_LO, DriveKhongThay, DriveThat


class DichVuGia:
    """`svc.files().list(**kw).execute()` / `.get(**kw).execute()` — ghi lại kw."""

    def __init__(self, tra_ve=None, loi=None):
        self.goi: list[tuple[str, dict]] = []
        self._tra_ve = list(tra_ve or [])
        self._loi = loi

    def files(self):
        return self

    def _lenh(self, ten, kw):
        self.goi.append((ten, kw))
        return types.SimpleNamespace(execute=self._chay)

    def list(self, **kw):
        return self._lenh("list", kw)

    def get(self, **kw):
        return self._lenh("get", kw)

    def _chay(self):
        if self._loi is not None:
            raise self._loi
        return self._tra_ve.pop(0)


class NguoiUploadGia:
    def __init__(self, dich_vu):
        self.dich_vu = dich_vu
        self.so_lan_dung = 0

    def is_configured(self):
        return True

    def _build_service(self):
        self.so_lan_dung += 1
        return self.dich_vu


def tao(dich_vu):
    return DriveThat(NguoiUploadGia(dich_vu)), dich_vu


def id_(i):
    return f"1Src{i:04d}_AbCdEfGhIjKl"


def test_theo_lo_dung_q_chinh_xac_va_tham_so_va_tra_trang_tiep():
    d, dv = tao(DichVuGia([{"files": [{"id": "c1", "properties": {"videodesk_src": id_(1)}}],
                            "nextPageToken": "TOK2"}]))
    tep, tiep = d.liet_ke_ban_sao_theo_lo([id_(1), id_(2)], "TOK1")
    assert tiep == "TOK2" and tep[0]["id"] == "c1"
    ten, kw = dv.goi[0]
    assert ten == "list"
    assert kw == {
        "q": ("(properties has {key='videodesk_src' and value='%s'} or "
              "properties has {key='videodesk_src' and value='%s'}) and trashed = false"
              % (id_(1), id_(2))),
        "corpora": "allDrives", "includeItemsFromAllDrives": True, "supportsAllDrives": True,
        "pageSize": 1000, "pageToken": "TOK1", "fields": "nextPageToken,files(id,properties)"}


def test_theo_lo_trang_cuoi_khong_co_token():
    d, _ = tao(DichVuGia([{"files": []}]))
    assert d.liet_ke_ban_sao_theo_lo([id_(1)], None) == ([], None)


def test_theo_lo_200_id_duoc_201_thi_tu_choi_va_khong_goi_dich_vu():
    d, dv = tao(DichVuGia([{"files": []}]))
    d.liet_ke_ban_sao_theo_lo([id_(i) for i in range(TOI_DA_ID_MOI_LO)], None)
    assert len(dv.goi[0][1]["q"]) < 20000, "q của lô đầy vẫn nằm trong giới hạn đã đo"
    dv.goi.clear()
    for xau in ([], [id_(i) for i in range(TOI_DA_ID_MOI_LO + 1)]):
        with pytest.raises(ValueError):
            d.liet_ke_ban_sao_theo_lo(xau, None)
    assert dv.goi == []


@pytest.mark.parametrize("xau", ["x' or '1'='1", "ngan", "co khoang trang 1234567", "a/b/c/d/e/f/g/h",
                                 "1Src0001_AbCdEfGhIjKl'}"])
def test_theo_lo_id_sai_hinh_dang_bi_tu_choi_truoc_khi_dung_truy_van(xau):
    d, dv = tao(DichVuGia([{"files": []}]))
    with pytest.raises(ValueError):
        d.liet_ke_ban_sao_theo_lo([id_(1), xau], None)
    assert dv.goi == [] and d._up.so_lan_dung == 0, "không dựng dịch vụ, không gọi mạng"


def test_thung_rac_dung_q_fields_phan_trang():
    d, dv = tao(DichVuGia([{"files": [{"id": "t1"}], "nextPageToken": "P2"}]))
    assert d.liet_ke_video_thung_rac("P1") == ([{"id": "t1"}], "P2")
    assert dv.goi[0] == ("list", {
        "q": "trashed = true and mimeType contains 'video/'", "corpora": "allDrives",
        "includeItemsFromAllDrives": True, "supportsAllDrives": True, "pageSize": 1000,
        "pageToken": "P1", "fields": "nextPageToken,files(id)"})


def test_ban_sao_theo_dau_va_shared_drive_giu_truy_van_cu():
    d, dv = tao(DichVuGia([{"files": []}, {"files": [], "nextPageToken": "N"}]))
    d.liet_ke_ban_sao_theo_dau(id_(1), None)
    assert dv.goi[0][1]["q"] == ("properties has {key='videodesk_src' and value='%s'} "
                                 "and trashed = false" % id_(1))
    assert dv.goi[0][1]["corpora"] == "allDrives" and dv.goi[0][1]["pageSize"] == 100
    with pytest.raises(ValueError):
        d.liet_ke_ban_sao_theo_dau("x' or 1=1 --", None)
    assert d.liet_ke_video_shared_drive("DRV", "T") == ([], "N")
    kw = dv.goi[1][1]
    assert (kw["corpora"], kw["driveId"], kw["pageToken"], kw["pageSize"]) == ("drive", "DRV", "T", 1000)
    assert kw["q"] == "trashed = false and mimeType contains 'video/'"


def test_lay_tep_404_la_khong_thay_con_403_nem_nguyen():
    for status, mong in ((404, DriveKhongThay), (403, HttpError), (500, HttpError)):
        d, _ = tao(DichVuGia(loi=HttpError(types.SimpleNamespace(status=status, reason="g"), b"{}")))
        with pytest.raises(mong) as e:
            d.lay_tep(id_(1))
        assert (status == 404) == isinstance(e.value, DriveKhongThay)
