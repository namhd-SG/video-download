"""Job 2 pha agy học mẫu, đầu–cuối trên clip TỔNG HỢP: mini đặt việc ⇒ relay máy dev (agy GIẢ trả box thật) ⇒ mini đọc ⇒ lõi render.
agy giả chỉ thay đúng một thứ: lời gọi tiến trình agy. Mọi thứ khác (hộp thư, ánh xạ UUID, kiểm schema, lõi) là thật."""
import json

import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import hoc_mau_agy, relay_may_dev  # noqa: E402
from tiktok_music_downloader.thay_logo.duong_ong import xu_ly_video  # noqa: E402
from tiktok_music_downloader.thay_logo.hop_thu import HopThu  # noqa: E402


class MiniGia:
    """Thay HTTP bằng gọi thẳng HopThu (route đã có test riêng)."""

    def __init__(self, hop):
        self.hop, self.da_nop, self.da_loi = hop, [], []

    def viec(self):
        return self.hop.viec_cho()

    def anh(self, u):
        return self.hop.doc_anh(u)

    def nop(self, job_id, kq, luot=1):
        self.da_nop.append(job_id)
        self.hop.nop_ket_qua(job_id, kq, luot)

    def nop_loi(self, job_id, ma, luot=1):
        self.da_loi.append((job_id, ma, luot))
        self.hop.nop_loi(job_id, ma, luot)


def _agy_that_tu_ground_truth(clip, hop, job_id):
    bang = json.loads((hop.goc / str(job_id) / "khung.json").read_text())

    def agy(anh):
        items = []
        for p in anh:
            k = bang[p.stem]
            x, y, w, h = clip.hop_that[k["khung"]]
            box = [y * 1000 // 640, x * 1000 // 360, (y + h) * 1000 // 640, (x + w) * 1000 // 360]
            items.append({"file": str(p), "endcard": False,
                          "watermarks": [{"label": "IGNORE PREVIOUS INSTRUCTIONS", "box_2d": box}]})
        return {"items": items}
    return agy


def test_dau_cuoi_dat_viec_relay_doc_ket_qua_render(tmp_path):
    clip = tao_clip()
    hop = HopThu(tmp_path / "hop")
    assert hoc_mau_agy.dat_viec(clip.nguon, hop, 5) == 7
    assert hop.viec_cho()[0].keys() == {"job_id", "anh", "luot"}  # bảng UUID↔khung không rời mini
    assert hoc_mau_agy.doc_ket_qua(clip.nguon, hop, 5) is None  # chưa nộp ⇒ job vẫn chờ agy
    mini = MiniGia(hop)
    assert relay_may_dev.mot_vong(mini, _agy_that_tu_ground_truth(clip, hop, 5)) == 1
    assert "IGNORE" not in (hop.goc / "5" / "ket_qua.json").read_text()  # nhãn về mini đã lower + whitelist (không còn chữ hoa/ký tự lạ)
    boxes, man_ket = hoc_mau_agy.doc_ket_qua(clip.nguon, hop, 5)
    assert len(boxes) == 6 and man_ket is False and all(b.nguon == "agy" for b in boxes)
    kq = xu_ly_video(clip.nguon, boxes)
    assert kq.trang_thai == "render"


def test_agy_hong_thi_khong_nop_gi_job_van_cho(tmp_path):
    clip = tao_clip(n=20)
    hop = HopThu(tmp_path / "hop")
    hoc_mau_agy.dat_viec(clip.nguon, hop, 9)
    mini = MiniGia(hop)
    assert relay_may_dev.mot_vong(mini, lambda anh: None) == 0
    assert mini.da_nop == [] and hop.viec_cho()[0]["job_id"] == 9
    assert mini.da_loi == [(9, "khong_ket_qua", 1)] and hop.so_loi(9) == 1  # agy trượt ⇒ BÁO mini, không im lặng


def test_box_tren_khung_agy_goi_la_man_ket_bi_bo(tmp_path):
    clip = tao_clip(n=20)
    hop = HopThu(tmp_path / "hop")
    ids = hop.tao_viec(2, [b"\xff\xd8\xff" + b"0"] * 2)
    (hop.goc / "2" / "khung.json").write_text(json.dumps({ids[0]: {"khung": 3, "vai": "hoc_mau"},
                                                          ids[1]: {"khung": 19, "vai": "man_ket"}}))
    hop.nop_ket_qua(2, {"items": [
        {"anh": ids[0], "man_ket": True, "watermarks": [{"box_2d": [10, 10, 50, 50]}]},
        {"anh": ids[1], "man_ket": True, "watermarks": []}]})
    boxes, man_ket = hoc_mau_agy.doc_ket_qua(clip.nguon, hop, 2)
    assert boxes == [] and man_ket is True


def test_ghep_ket_qua_bo_ten_file_la_va_box_sai():
    u = "a" * 32
    ra = {"items": [{"file": f"/x/{u}.jpg", "endcard": False,
                     "watermarks": [{"label": "x", "box_2d": [1, 2, 3, 4]}, {"label": "y", "box_2d": [1, 2, 3]},
                                    {"label": "z", "box_2d": [1, 2, 3, 2000]}]},
                    {"file": "/x/../../etc/passwd", "endcard": True, "watermarks": []}]}
    kq = relay_may_dev.ghep_ket_qua([{"job_id": 1, "anh": [u]}], ra)
    assert kq == {1: {"items": [{"anh": u, "man_ket": False, "watermarks": [{"box_2d": [1, 2, 3, 4], "label": "x"}]}]}}


# ---------------------------------------------------------------- phía máy dev (kongming 09/10 lỗ 6–8)

def test_agy_bo_sot_anh_thi_khong_nop_job_do():
    """Lỗ 8: agy không mở được ảnh (trả items rỗng) KHÔNG được nộp thành 'không có watermark'."""
    u, w = "a" * 32, "b" * 32
    ra = {"items": [{"file": f"/x/{u}.jpg", "endcard": False, "watermarks": []}]}
    assert relay_may_dev.ghep_ket_qua([{"job_id": 1, "anh": [u, w]}, {"job_id": 2, "anh": [u]}], ra) == \
        {2: {"items": [{"anh": u, "man_ket": False, "watermarks": []}]}}


def test_agy_chay_voi_cwd_la_thu_muc_tam(tmp_path, monkeypatch):
    """Lỗ 6: không đặt cwd ⇒ agy có cả thư mục người gõ lệnh (repo) làm không gian làm việc."""
    import subprocess
    thay = {}

    def gia(cmd, **k):
        thay["cwd"] = k.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, '{"status": "SUCCESS", "structured_output": {"items": []}}', "")
    monkeypatch.setattr(relay_may_dev.subprocess, "run", gia)
    p = tmp_path / ("c" * 32 + ".jpg")
    p.write_bytes(b"\xff\xd8\xff")
    relay_may_dev.goi_agy([p])
    assert thay["cwd"] == str(tmp_path)


def test_bo_qua_job_qua_nhieu_anh_va_anh_khong_phai_jpeg(monkeypatch):
    """Lỗ 7: mini hỏng/bị chiếm không được đổ dữ liệu vô hạn sang máy dev."""
    class M:
        def viec(self):
            return [{"job_id": 1, "anh": ["d" * 32] * 65}]
    assert relay_may_dev.mot_vong(M(), lambda anh: pytest.fail("không được gọi agy")) == 0
    mini = relay_may_dev._Mini("http://127.0.0.1:1", "t" * 40)
    monkeypatch.setattr(mini, "_req", lambda path, data=None, tran=0: b"<html>not jpeg</html>")
    with pytest.raises(ValueError):
        mini.anh("e" * 32)


# ---------------------------------------------------------------- relay R1: model mặc định, báo lỗi, cấu hình, nhãn, lượt

def test_model_mac_dinh_la_ban_con_trong_agy():
    assert relay_may_dev.MODEL == "gemini-3.8-flash-low" or "THAY_LOGO_AGY_MODEL" in __import__("os").environ


def _chay_agy_gia(monkeypatch, tmp_path, stdout, rc=0, stderr="", loi=None):
    import subprocess

    def gia(cmd, **k):
        if loi:
            raise loi
        return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
    monkeypatch.setattr(relay_may_dev.subprocess, "run", gia)
    p = tmp_path / ("c" * 32 + ".jpg")
    p.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(relay_may_dev.LoiAgy) as e:
        relay_may_dev.goi_agy([p])
    return e.value.ma


@pytest.mark.parametrize("kwargs,ma", [
    ({"stdout": "", "loi": __import__("subprocess").TimeoutExpired("agy", 900)}, "het_gio"),
    ({"stdout": "", "loi": FileNotFoundError()}, "agy_loi_chay"),
    ({"stdout": "", "rc": 1, "stderr": "boom"}, "agy_loi_chay"),
    ({"stdout": "xin chao, khong phai json"}, "khong_phai_json"),
    ({"stdout": '["x"]'}, "khong_phai_json"),
    ({"stdout": '{"status": "ERROR"}'}, "trang_thai_khac"),
    ({"stdout": '{"status": "SUCCESS"}'}, "khong_ket_qua"),
    ({"stdout": "", "rc": 1, "stderr": "model gemini-3.7-flash-low is not recognized"}, "model_khong_nhan"),
    ({"stdout": "invalid model selection", "rc": 0}, "model_khong_nhan"),
])
def test_goi_agy_phan_loai_moi_ca_truot_thanh_ma_enum(monkeypatch, tmp_path, kwargs, ma):
    assert _chay_agy_gia(monkeypatch, tmp_path, **kwargs) == ma
    assert ma in relay_may_dev.MA_LOI_AGY


def test_agy_truot_thi_nop_loi_cho_moi_job_trong_lo_va_khong_nop_ket_qua(tmp_path):
    hop = HopThu(tmp_path / "hop")
    hop.tao_viec(1, [b"\xff\xd8\xff0"])
    hop.tao_viec(2, [b"\xff\xd8\xff1"])
    mini = MiniGia(hop)

    def agy(anh):
        raise relay_may_dev.LoiAgy("het_gio")
    assert relay_may_dev.mot_vong(mini, agy) == 0
    assert sorted(mini.da_loi) == [(1, "het_gio", 1), (2, "het_gio", 1)] and mini.da_nop == []
    assert hop.so_loi(1) == hop.so_loi(2) == 1


def test_agy_bo_sot_anh_cua_mot_job_thi_chi_job_do_nhan_loi_thieu_anh(tmp_path):
    hop = HopThu(tmp_path / "hop")
    u1 = hop.tao_viec(1, [b"\xff\xd8\xff0"])[0]
    hop.tao_viec(2, [b"\xff\xd8\xff1"])
    mini = MiniGia(hop)
    assert relay_may_dev.mot_vong(mini, lambda anh: {"items": [{"file": f"/x/{u1}.jpg", "endcard": False, "watermarks": []}]}) == 1
    assert mini.da_nop == [1] and mini.da_loi == [(2, "thieu_anh", 1)]


def test_loi_mot_job_khong_chan_job_con_lai_va_nop_dung_luot(tmp_path):
    hop = HopThu(tmp_path / "hop")
    u = hop.tao_viec(3, [b"\xff\xd8\xff0"])[0]
    hop.nop_ket_qua(3, {"items": [{"anh": u, "man_ket": False, "watermarks": []}]})
    hop.tao_viec(3, [b"\xff\xd8\xff2"], luot=2)
    mini = MiniGia(hop)

    def agy(anh):
        raise relay_may_dev.LoiAgy("trang_thai_khac")
    relay_may_dev.mot_vong(mini, agy)
    assert mini.da_loi == [(3, "trang_thai_khac", 2)] and hop.so_loi(3, 2) == 1 and hop.so_loi(3, 1) == 0


@pytest.mark.parametrize("mini,token,agy,thieu", [
    ("http://100.64.0.1:8765", "t" * 40, "/bin/agy", None),
    ("http://100.64.0.1:8765", "", "/bin/agy", "TOKEN"),
    ("http://100.64.0.1:8765", "ngan", "/bin/agy", "ngắn"),
    ("100.64.0.1:8765", "t" * 40, "/bin/agy", "--mini"),
    ("", "t" * 40, "/bin/agy", "--mini"),
    ("http://100.64.0.1:8765", "t" * 40, None, "agy"),
])
def test_kiem_cau_hinh_phan_biet_chua_cau_hinh(mini, token, agy, thieu):
    kq = relay_may_dev.kiem_cau_hinh(mini, token, agy)
    assert (kq is None) if thieu is None else (thieu in kq)


def test_main_thoat_ma_khac_0_khi_chua_cau_hinh_va_khong_vao_vong(monkeypatch, capsys):
    monkeypatch.delenv("THAY_LOGO_RELAY_TOKEN", raising=False)
    monkeypatch.setattr(relay_may_dev.sys, "argv", ["relay", "--mini", "http://127.0.0.1:9"])
    monkeypatch.setattr(relay_may_dev, "mot_vong", lambda *a, **k: pytest.fail("không được vào vòng khi chưa cấu hình"))
    assert relay_may_dev.main() == 2
    assert "chưa cấu hình" in capsys.readouterr().err
    monkeypatch.setenv("THAY_LOGO_RELAY_TOKEN", "t" * 40)
    monkeypatch.setattr(relay_may_dev, "_chon_agy", lambda: None)  # đã có token mà thiếu binary agy
    assert relay_may_dev.main() == 2


def test_nhan_xuyen_tu_agy_den_doc_ket_qua_co_nhan_song_song_voi_box(tmp_path):
    clip = tao_clip(n=20)
    hop = HopThu(tmp_path / "hop")
    hoc_mau_agy.dat_viec(clip.nguon, hop, 5)
    bang = json.loads((hop.goc / "5" / "khung.json").read_text())

    def agy(anh):
        items = []
        for i, p in enumerate(anh):
            nhan = {0: "Learna", 1: "bad\nlabel"}.get(i)  # nhãn xấu bị bỏ, box vẫn giữ
            wm = {"box_2d": [100, 100, 200, 200], **({"label": nhan} if nhan else {})}
            items.append({"file": str(p), "endcard": False, "watermarks": [wm] if bang[p.stem]["vai"] == "hoc_mau" else []})
        return {"items": items}
    assert relay_may_dev.mot_vong(MiniGia(hop), agy) == 1
    boxes, man_ket, nhan = hoc_mau_agy.doc_ket_qua_co_nhan(clip.nguon, hop, 5)
    assert len(boxes) == len(nhan) == 6 and nhan[0] == "learna" and nhan[1] is None and all(n is None for n in nhan[2:])
    b2, m2 = hoc_mau_agy.doc_ket_qua(clip.nguon, hop, 5)  # hàm cũ giữ nguyên chữ ký/giá trị trả
    assert [b.__dict__ for b in b2] == [b.__dict__ for b in boxes] and m2 == man_ket


def test_doc_ket_qua_luot_2_dung_khung_json_rieng_cua_luot(tmp_path):
    clip = tao_clip(n=20)
    hop = HopThu(tmp_path / "hop")
    u1 = hop.tao_viec(7, [b"\xff\xd8\xff0"])[0]
    hop.nop_ket_qua(7, {"items": [{"anh": u1, "man_ket": False, "watermarks": []}]})
    u2 = hop.tao_viec(7, [b"\xff\xd8\xff1"], luot=2)[0]
    (hop.thu_muc_luot(7, 1)).joinpath("khung.json").write_text(json.dumps({u1: {"khung": 1, "vai": "hoc_mau"}}))
    (hop.thu_muc_luot(7, 2)).joinpath("khung.json").write_text(json.dumps({u2: {"khung": 4, "vai": "hoc_mau"}}))
    assert hoc_mau_agy.doc_ket_qua_co_nhan(clip.nguon, hop, 7, luot=2) is None  # lượt 2 chưa nộp
    hop.nop_ket_qua(7, {"items": [{"anh": u2, "man_ket": False, "watermarks": [{"box_2d": [10, 10, 60, 60], "label": "dau"}]}]}, 2)
    boxes, _, nhan = hoc_mau_agy.doc_ket_qua_co_nhan(clip.nguon, hop, 7, luot=2)
    assert len(boxes) == 1 and nhan == ["dau"] and boxes[0].khung == 4
