"""Phép kiểm máy cho đầu ra tầng hình — `scripts/tu-chia-cum/kiem-ket-qua.py`.

Fixture DƯƠNG là đầu ra agy THẬT của job 10 (59 poster, đo 24/09): nhãn
vision (`nhan-job10-poster.jsonl`, bản chưa có `so_khung`/`boi_canh`) và lượt
chuẩn hoá 2 tầng mù (`chia-2-tang-job10.json`). Chỉ chứa id video TikTok công
khai và nhãn trang phục. Fixture ÂM dựng từ chính hai tệp đó, sửa đúng MỘT chỗ.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

GOC = Path(__file__).resolve().parents[1]
FIX = GOC / "tests" / "fixtures" / "tu-chia-cum"


def _nap():
    spec = importlib.util.spec_from_file_location(
        "kiem_ket_qua", GOC / "scripts" / "tu-chia-cum" / "kiem-ket-qua.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kiem = _nap()

# Bản nhãn đo 24/09 chưa có `so_khung`/`boi_canh` (schema hiện tại có).
TRUONG_BAN_DAU = ("video_id", "the_chu", "trang_phuc_dam_dong", "trang_phuc_nguoi_chinh")


@pytest.fixture
def nhan():
    return [json.loads(d) for d in (FIX / "nhan-job10-poster.jsonl").read_text().splitlines()
            if d.strip()]


@pytest.fixture
def chia():
    return json.loads((FIX / "chia-2-tang-job10.json").read_text())


@pytest.fixture
def ids(nhan):
    return {h["video_id"] for h in nhan}


# --- dương: đầu ra thật -------------------------------------------------------

def test_nhan_that_job10_dat(nhan, ids):
    assert len(ids) == 59
    assert kiem.kiem_nhan(nhan, ids, truong=TRUONG_BAN_DAU) == []


def test_chia_2_tang_that_job10_dat(chia, ids):
    assert set(chia["gan"]) == ids
    assert kiem.kiem_chia(chia, ids, []) == []


def test_nhan_ban_dau_thieu_truong_moi_bi_bat_theo_schema_hien_tai(nhan, ids):
    """Schema hiện tại đòi `so_khung` + `boi_canh` — bản cũ phải trượt đúng ở đó."""
    loi = kiem.kiem_nhan(nhan, ids)
    assert len(loi) == 59 and all("so_khung" in d and "boi_canh" in d for d in loi)


# --- âm: đủ id / mỗi id một lần / id lạ ----------------------------------------

def test_nhan_thieu_mot_id_bi_bat(nhan, ids):
    loi = kiem.kiem_nhan(nhan[1:], ids, truong=TRUONG_BAN_DAU)
    assert any("thiếu 1/59" in d and nhan[0]["video_id"] in d for d in loi)


def test_chia_thieu_mot_id_bi_bat(chia, ids):
    bot = copy.deepcopy(chia)
    vid = next(iter(bot["gan"]))
    del bot["gan"][vid]
    loi = kiem.kiem_chia(bot, ids, [])
    assert any("thiếu 1/59" in d and vid in d for d in loi)


def test_nhan_trung_id_bi_bat(nhan, ids):
    loi = kiem.kiem_nhan(nhan + [nhan[3]], ids, truong=TRUONG_BAN_DAU)
    assert any("hơn một lần" in d and nhan[3]["video_id"] in d for d in loi)


def test_chia_trung_khoa_id_trong_json_bi_bat(tmp_path, chia, ids):
    """`json.loads` trần giữ bản sau của khoá trùng — id lặp phải bị bắt,
    không được biến mất."""
    vid, gan = next(iter(chia["gan"].items()))
    van_ban = json.dumps(chia, ensure_ascii=False)
    lap = json.dumps({vid: gan}, ensure_ascii=False)[1:-1]
    van_ban = van_ban.replace('"gan": {', '"gan": {' + lap + ", ", 1)
    tep = tmp_path / "chia.json"
    tep.write_text(van_ban)
    obj, trung = kiem._doc_json(tep)
    assert trung == [vid]
    assert any("hơn một lần" in d and vid in d for d in kiem.kiem_chia(obj, ids, trung))


def test_id_la_bi_bat(chia, ids):
    them = copy.deepcopy(chia)
    them["gan"]["123"] = {"nhom": "Hoá trang", "kieu": "Mặt nạ"}
    assert any("ngoài tập mong đợi" in d and "123" in d for d in kiem.kiem_chia(them, ids, []))


# --- âm: kiểu thuộc hai nhóm / nhãn ngoài danh sách ----------------------------

def test_kieu_thuoc_hai_nhom_bi_bat(chia, ids):
    sai = copy.deepcopy(chia)
    sai["nhom"]["Trang phục vest"].append("mặt  NẠ")   # khác hoa/thường + khoảng trắng
    loi = kiem.kiem_chia(sai, ids, [])
    assert any("thuộc 2 nhóm" in d for d in loi)


def test_gan_vao_kieu_chua_khai_bi_bat(chia, ids):
    sai = copy.deepcopy(chia)
    vid = next(iter(sai["gan"]))
    sai["gan"][vid] = {"nhom": "Hoá trang", "kieu": "Vest công sở"}   # kiểu có, sai nhóm
    assert any("ngoài danh sách" in d and vid in d for d in kiem.kiem_chia(sai, ids, []))


def test_lan_ngoai_danh_sach_bi_bat(chia, ids):
    sai = copy.deepcopy(chia)
    vid = next(iter(sai["gan"]))
    sai["gan"][vid] = {"lan": "rac"}
    assert any("làn ngoài danh sách" in d for d in kiem.kiem_chia(sai, ids, []))
    sai["gan"][vid] = {"lan": "nghi"}
    assert kiem.kiem_chia(sai, ids, []) == []


def test_the_chu_ngoai_true_false_bi_bat(nhan, ids):
    sai = copy.deepcopy(nhan)
    sai[0]["the_chu"] = "co"
    assert any("the_chu ngoài danh sách" in d
               for d in kiem.kiem_nhan(sai, ids, truong=TRUONG_BAN_DAU))


def test_so_khung_phai_khop_so_anh_da_cap():
    hang = [{"video_id": "1", "so_khung": 1, "the_chu": False, "trang_phuc_dam_dong": "a",
             "trang_phuc_nguoi_chinh": "b", "boi_canh": "c"}]
    assert kiem.kiem_nhan(hang, {"1"}, {"1": 1}) == []
    assert any("đã cấp 3 ảnh" in d for d in kiem.kiem_nhan(hang, {"1"}, {"1": 3}))


def test_caption_co_ngoai_danh_sach_va_thieu_id_bi_bat():
    assert kiem.kiem_caption({"1": True, "2": "khong_ro", "3": False}, {"1", "2", "3"}, []) == []
    loi = kiem.kiem_caption({"1": "co", "2": 1}, {"1", "2", "3"}, [])
    assert any("thiếu 1/3" in d for d in loi)
    assert sum("cờ ngoài danh sách" in d for d in loi) == 2


# --- CLI ------------------------------------------------------------------------

def test_cli_ma_thoat_dat_khong_dat_do_hong(tmp_path, chia, ids):
    tep_ids = tmp_path / "ids.txt"
    tep_ids.write_text("\n".join(sorted(ids)))
    assert kiem.main(["chia", str(FIX / "chia-2-tang-job10.json"), "--ids", str(tep_ids)]) == 0
    bot = copy.deepcopy(chia)
    del bot["gan"][next(iter(bot["gan"]))]
    (tmp_path / "bot.json").write_text(json.dumps(bot, ensure_ascii=False))
    assert kiem.main(["chia", str(tmp_path / "bot.json"), "--ids", str(tep_ids)]) == 4
    assert kiem.main(["chia", str(tmp_path / "khong-co.json"), "--ids", str(tep_ids)]) == 3
