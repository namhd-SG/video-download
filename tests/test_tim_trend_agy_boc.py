"""Đọc kết quả agy: từ file đích, từ log khi agy in ra stdout (sự cố GĐ1), bỏ mục bịa id. agy được thay bằng giả."""
from __future__ import annotations

import json
from pathlib import Path

from tiktok_music_downloader.tim_trend import agy_boc

_FIX = Path(__file__).parent / "fixtures" / "tim_trend" / "truong-gd1.json"
ITEMS = json.loads(_FIX.read_text())["items"]


def _anh(tmp_path, ids):
    d = tmp_path / "anh"
    d.mkdir(exist_ok=True)
    for i in ids:
        (d / f"{i}.jpg").write_bytes(b"x")
    return [d / f"{i}.jpg" for i in ids]


def test_doc_tu_file_dich(tmp_path, monkeypatch):
    anh = _anh(tmp_path, ["ctrl-0", "s6-7", "s3-4"])

    def gia(prompt, add_dir, model, giay=0):
        dich = Path(prompt.split("Ghi JSON vao ")[1].split(" :")[0])
        dich.write_text(json.dumps({"items": [m for m in ITEMS if m["id"] in ("ctrl-0", "s6-7", "s3-4")]}))
        return "ok"

    monkeypatch.setattr(agy_boc, "goi_agy", gia)
    ra = agy_boc.boc_truong(anh, tmp_path)
    assert set(ra) == {"ctrl-0", "s6-7", "s3-4"} and ra["s6-7"].so_ban_sao == 7


def test_cuu_json_trong_log_khi_agy_khong_ghi_file(tmp_path, monkeypatch):
    anh = _anh(tmp_path, ["s7-1"])
    log = "agy noi gi do\n```json\n" + json.dumps({"items": [m for m in ITEMS if m["id"] == "s7-1"]}) + "\n```\n"
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: log)
    ra = agy_boc.boc_truong(anh, tmp_path)
    assert ra["s7-1"].la_tutorial is True


def test_bo_muc_bia_id_va_thieu_muc(tmp_path, monkeypatch):
    anh = _anh(tmp_path, ["s6-7", "s3-4"])
    bia = dict(ITEMS[0], id="khong-co-trong-lo")
    du = [m for m in ITEMS if m["id"] == "s6-7"] + [bia]
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: "```json\n" + json.dumps({"items": du}) + "\n```")
    ra = agy_boc.boc_truong(anh, tmp_path)
    assert set(ra) == {"s6-7"}   # s3-4 agy bỏ sót ⇒ vắng, không đoán; id bịa ⇒ bỏ


def test_khong_co_json_nao(tmp_path, monkeypatch):
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: "Eligibility check failed: UNAVAILABLE (503)")
    assert agy_boc.boc_truong(_anh(tmp_path, ["s6-7"]), tmp_path) == {}


def test_chia_lo(tmp_path, monkeypatch):
    goi = []
    monkeypatch.setattr(agy_boc, "LO_TOI_DA", 2)
    monkeypatch.setattr(agy_boc, "goi_agy", lambda p, *a, **k: goi.append(p) or "")
    agy_boc.boc_truong(_anh(tmp_path, ["a", "b", "c", "d", "e"]), tmp_path)
    assert len(goi) == 3


def test_goi_y_tu_khoa(tmp_path, monkeypatch):
    out = {"nhan_dang": "ai collage 7 pose", "chu_de": {"en": ["ai pose collage"], "es": ["collage ia"], "vi": ["x"]},
           "san_pham": {"pt": ["conjunto preto"]}}
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: "```json\n" + json.dumps(out) + "\n```")
    tv = agy_boc.goi_y_tu_khoa(_anh(tmp_path, ["dau-vao-0"]), tmp_path)
    assert [(t.text, t.nhom, t.lang) for t in tv] == [("ai pose collage", "chu_de", "en"), ("collage ia", "chu_de", "es"),
                                                     ("conjunto preto", "san_pham", "pt")]


def test_khong_doc_lai_file_cu_khi_agy_truot(tmp_path, monkeypatch):
    """Lượt trước để lại file đích; lượt này agy trượt (không ghi, không in JSON) ⇒ phải ra rỗng, không đọc file cũ."""
    anh = _anh(tmp_path, ["s6-7"])
    (tmp_path / "agy-truong-0.json").write_text(json.dumps({"items": [m for m in ITEMS if m["id"] == "s6-7"]}))
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: "Eligibility check failed")
    assert agy_boc.boc_truong(anh, tmp_path) == {}


def test_goi_y_tu_khoa_khong_doc_file_cu(tmp_path, monkeypatch):
    (tmp_path / "agy-tu-khoa.json").write_text(json.dumps({"chu_de": {"en": ["key cu tu lan truoc"]}}))
    monkeypatch.setattr(agy_boc, "goi_agy", lambda *a, **k: "Eligibility check failed")
    assert agy_boc.goi_y_tu_khoa(_anh(tmp_path, ["dau-vao-0"]), tmp_path) == []
