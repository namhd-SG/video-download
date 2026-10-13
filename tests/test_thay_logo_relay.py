"""Hộp thư relay §3e: token riêng (thiếu ⇒ 503 đóng), chỉ job_id + UUID rời mini, chỉ toạ độ đúng schema quay về."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import json  # noqa: E402
import time  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from tiktok_music_downloader.thay_logo.hop_thu import HopThu, LoiHopThu  # noqa: E402
from web import thay_logo_routes  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
TOKEN = "t-relay-test-" + "x" * 32
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def hop(tmp_path):
    return HopThu(tmp_path / "hop_thu")


class _Client:
    """Bọc MayChu cho giống giao diện tối thiểu test cần: get/post trả đối tượng có status_code/content/json()."""

    def __init__(self, mc):
        self.mc = mc

    def _r(self, cach, duong, headers=None, json=None):
        ma, than = self.mc.goi(cach, duong, headers=headers, json_body=json)
        return _Resp(ma, than)

    def get(self, duong, headers=None):
        return self._r("get", duong, headers)

    def post(self, duong, headers=None, json=None):
        return self._r("post", duong, headers, json)


class _Resp:
    def __init__(self, ma, than):
        self.status_code, self.content = ma, than

    def json(self):
        return json.loads(self.content)


@pytest.fixture
def client(hop, monkeypatch):
    monkeypatch.setenv(thay_logo_routes.ENV_TOKEN, TOKEN)
    app = FastAPI()
    thay_logo_routes.dang_ky_route(app, lambda: hop)
    mc = MayChu(app)
    yield _Client(mc)
    mc.dung()


def _ket_qua(anh_viec, **them):
    it = {"anh": anh_viec, "man_ket": False, "watermarks": [{"box_2d": [10, 20, 30, 40]}]}
    it.update(them)
    return {"items": [it]}


R = thay_logo_routes.TIEN_TO


@pytest.mark.parametrize("cach,duong", [("get", "/viec"), ("get", "/anh/" + "a" * 32), ("post", "/ket-qua/1")])
def test_thieu_token_moi_route_tra_503(client, monkeypatch, cach, duong):
    monkeypatch.delenv(thay_logo_routes.ENV_TOKEN)
    r = getattr(client, cach)(R + duong, headers=H, **({"json": {"items": []}} if cach == "post" else {}))
    assert r.status_code == 503


def test_token_ngan_hon_32_ky_tu_coi_nhu_chua_cau_hinh(client, monkeypatch):
    monkeypatch.setenv(thay_logo_routes.ENV_TOKEN, "ngan-qua")
    assert client.get(R + "/viec", headers={"Authorization": "Bearer ngan-qua"}).status_code == 503


@pytest.mark.parametrize("hdr", [{}, {"Authorization": "Bearer sai"}, {"Authorization": "Bearer "}])
def test_sai_hoac_khong_co_token_tra_401(client, hdr):
    assert client.get(R + "/viec", headers=hdr).status_code == 401


def test_luong_day_du_chi_job_id_va_uuid_roi_mini(client, hop):
    ids = hop.tao_viec(7, [JPEG, JPEG])
    r = client.get(R + "/viec", headers=H)
    assert r.json() == {"viec": [{"job_id": 7, "anh": ids, "luot": 1}]}
    r = client.get(R + f"/anh/{ids[0]}", headers=H)
    assert r.status_code == 200 and r.content == JPEG
    assert client.post(R + "/ket-qua/7", headers=H, json=_ket_qua(ids[0])).status_code == 204
    assert hop.doc_ket_qua(7)["items"][0]["watermarks"] == [{"box_2d": [10, 20, 30, 40]}]
    assert client.get(R + "/viec", headers=H).json() == {"viec": []}
    assert client.post(R + "/ket-qua/7", headers=H, json=_ket_qua(ids[1])).status_code == 409


@pytest.mark.parametrize("sai", [
    {"label": "Learna"},                                            # trường chữ từ agy KHÔNG được quay về mini
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "label": "learna"}]},          # §3e: KHÔNG chữ nào từ máy dev, kể cả label
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": "0"}]},                  # cum dạng chuỗi
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": True}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": -1}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": 64}]},                   # chạm trần TRAN_CUM
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": 1.0}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "cum": 0, "label": "x"}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 40], "ten": "x"}]},                  # khoá lạ ngoài cum
    {"watermarks": [{"box_2d": [10, 20, 30]}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 1001]}]},
    {"watermarks": [{"box_2d": [10, 20, 30, "40"]}]},
    {"watermarks": [{"box_2d": [10, 20, 30, 40.5]}]},
    {"watermarks": [{"box_2d": [True, 20, 30, 40]}]},
    {"man_ket": "khong"},
    {"anh": "f" * 32},                                              # ảnh không thuộc việc
])
def test_ket_qua_sai_schema_bi_tu_choi_va_khong_ghi(client, hop, sai):
    ids = hop.tao_viec(3, [JPEG])
    r = client.post(R + "/ket-qua/3", headers=H, json=_ket_qua(ids[0], **sai))
    assert r.status_code == 400
    assert hop.doc_ket_qua(3) is None


def test_viec_khong_ton_tai_404_va_ten_anh_sai_khuon_400(client):
    assert client.post(R + "/ket-qua/99", headers=H, json={"items": []}).status_code == 404
    assert client.get(R + "/anh/..%2Fviec", headers=H).status_code in (400, 404)
    assert client.get(R + "/anh/ABC", headers=H).status_code == 400
    assert client.get(R + "/anh/" + "a" * 32, headers=H).status_code == 404


def test_tao_viec_chi_nhan_jpeg_trong_tran(hop):
    with pytest.raises(LoiHopThu):
        hop.tao_viec(1, [b"\x89PNG...."])
    with pytest.raises(LoiHopThu):
        hop.tao_viec(1, [])
    with pytest.raises(LoiHopThu):
        hop.tao_viec(0, [JPEG])
    hop.tao_viec(1, [JPEG])
    with pytest.raises(LoiHopThu):
        hop.tao_viec(1, [JPEG])


# ---------------------------------------------------------------- nhãn, nhiều lượt, báo lỗi agy (relay thay logo R1)

def test_cum_so_nguyen_hop_le_duoc_giu_va_payload_cu_khong_cum_van_204(client, hop):
    ids = hop.tao_viec(4, [JPEG])
    assert client.post(R + "/ket-qua/4", headers=H, json=_ket_qua(ids[0])).status_code == 204  # payload cũ, không cum
    ids = hop.tao_viec(5, [JPEG])
    kq = _ket_qua(ids[0], watermarks=[{"box_2d": [1, 2, 3, 4], "cum": 0}, {"box_2d": [5, 6, 7, 8]}, {"box_2d": [5, 6, 7, 9], "cum": 63}])
    assert client.post(R + "/ket-qua/5", headers=H, json=kq).status_code == 204
    assert hop.doc_ket_qua(5)["items"][0]["watermarks"] == [{"box_2d": [1, 2, 3, 4], "cum": 0}, {"box_2d": [5, 6, 7, 8]},
                                                            {"box_2d": [5, 6, 7, 9], "cum": 63}]


def test_nhieu_luot_moi_luot_khoa_rieng_chi_mot_lan_nop(client, hop):
    ids1 = hop.tao_viec(8, [JPEG])
    with pytest.raises(LoiHopThu) as e:
        hop.tao_viec(8, [JPEG], luot=2)  # lượt 1 chưa có kết quả ⇒ chưa được mở lượt 2
    assert e.value.ma == 409
    assert client.post(R + "/ket-qua/8", headers=H, json=_ket_qua(ids1[0])).status_code == 204
    ids2 = hop.tao_viec(8, [JPEG, JPEG], luot=2)
    assert client.get(R + "/viec", headers=H).json() == {"viec": [{"job_id": 8, "anh": ids2, "luot": 2}]}
    assert client.get(R + f"/anh/{ids2[1]}", headers=H).content == JPEG  # ảnh của lượt 2 tải được qua route cũ
    assert client.post(R + "/ket-qua/8?luot=2", headers=H, json=_ket_qua(ids1[0])).status_code == 400  # ảnh lượt 1 ≠ ảnh lượt 2
    assert client.post(R + "/ket-qua/8?luot=2", headers=H, json=_ket_qua(ids2[0])).status_code == 204
    assert client.post(R + "/ket-qua/8?luot=2", headers=H, json=_ket_qua(ids2[1])).status_code == 409
    assert hop.doc_ket_qua(8, 1)["items"][0]["anh"] == ids1[0] and hop.doc_ket_qua(8, 2)["items"][0]["anh"] == ids2[0]
    assert client.post(R + "/ket-qua/8?luot=9", headers=H, json={"items": []}).status_code == 400  # ngoài trần số lượt
    with pytest.raises(LoiHopThu):
        hop.tao_viec(8, [JPEG], luot=2)  # lượt 2 đã tồn tại
    hop.xoa_viec(8)
    assert hop.viec_cho() == [] and hop.doc_ket_qua(8, 2) is None  # xoá việc ⇒ xoá mọi lượt


def test_bao_loi_agy_dem_theo_luot_va_chi_nhan_enum(client, hop):
    ids = hop.tao_viec(6, [JPEG])
    for i in (1, 2):
        assert client.post(R + "/loi/6", headers=H, json={"ma": "het_gio"}).status_code == 204
        assert hop.so_loi(6) == i
    d = hop.doc_loi(6)
    assert (d["so"], d["ma_cuoi"]) == (2, "het_gio") and d["dau_luc"] <= time.time()
    assert hop.viec_cho()[0]["job_id"] == 6  # lỗi KHÔNG làm việc biến mất: relay còn thử lại
    for sai in ({"ma": "chu tu do tu agy"}, {"ma": "het_gio", "them": 1}, {"ma": "het_gio", "luot": 9}, {"luot": 1}):
        assert client.post(R + "/loi/6", headers=H, json=sai).status_code in (400, 422)
    assert hop.so_loi(6) == 2 and hop.so_loi(6, 2) == 0
    assert client.post(R + "/loi/99", headers=H, json={"ma": "het_gio"}).status_code == 404
    assert client.post(R + "/loi/6", json={"ma": "het_gio"}).status_code == 401
    assert client.post(R + "/ket-qua/6", headers=H, json=_ket_qua(ids[0])).status_code == 204
    assert client.post(R + "/loi/6", headers=H, json={"ma": "het_gio"}).status_code == 409  # lỗi đến muộn sau khi đã có kết quả
    assert hop.so_loi(6) == 2
