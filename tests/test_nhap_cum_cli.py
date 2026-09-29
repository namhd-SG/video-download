"""CLI trên mini cho tầng hình — `web/nhap_cum_cli.py`, cùng `models_chia`
(`video_vao_luot_chia`, `nhap_de_xuat`) và cache `models_dac_diem`.

Gọi thẳng `main(argv)` trên một DB tạm, đọc JSON ở stdout như máy dev đọc qua ssh.
"""
from __future__ import annotations

import io
import json
import sqlite3

import pytest

from web import lifecycle, models, models_chia, models_cum, models_dac_diem, nhap_cum_cli

TOI = "toi@astronex.ai"
HO = "ho@astronex.ai"
PB = "nhan:abc@m;caption:def@m;chuan-hoa:ghi@m"


@pytest.fixture
def kho(tmp_path):
    """Job `done` của TOI (nguồn TikTok) với video 1..4. Ảnh: 1 đủ poster + 2
    khung, 2 chỉ poster, 3 chỉ khung 50, 4 không có ảnh nào."""
    db = tmp_path / "data" / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/vest", 4, TOI)
    for vid in ("1", "2", "3", "4"):
        models.record_video(db, job_id=job, video_id=vid, url=f"u{vid}", description=f"cap {vid}")
    models.finish_job(db, job, "done")
    for p in (lifecycle.thumb_path_for(db, "1"), lifecycle.khung_phu_path_for(db, "1", 50),
              lifecycle.khung_phu_path_for(db, "1", 90), lifecycle.thumb_path_for(db, "2"),
              lifecycle.khung_phu_path_for(db, "3", 50)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"webp")
    return db, job


def _chay(capsys, db, *args, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    rc = nhap_cum_cli.main(["--db", str(db), *map(str, args)])
    ra = capsys.readouterr()
    return rc, (json.loads(ra.out) if ra.out.strip() else None), ra.err


def _tep(tmp_path, obj) -> str:
    tep = tmp_path / "ghi.json"
    tep.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(tep)


def _de_xuat(**them):
    return {"phien_ban_prompt": PB, "truc": "trang_phuc_dam_dong",
            "nhoms": [{"nhom": "Vest", "kieu": [{"kieu": "Vest công sở", "video_ids": ["1", "2"]}]}],
            "huong_dan": ["3"], "nghi": [],
            "dac_diem": [{"video_id": "1", "phien_ban_prompt": "nhan:abc@m",
                          "nhan": {"the_chu": False}},
                         {"video_id": "1", "phien_ban_prompt": "caption:def@m",
                          "nhan": {"caption_lech_chu_de": "khong_ro"}}], **them}


def _dem(db, bang, where="1=1", args=()) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {bang} WHERE {where}", args).fetchone()[0]


# --- lọc video vào lượt chia ---------------------------------------------------

def test_video_da_loai_khong_vao_luot_chia(kho):
    db, job = kho
    models.danh_dau_da_loai(db, "2", TOI)
    with models._connect(db) as conn:
        ids = [r["video_id"] for r in models_chia.video_vao_luot_chia(conn, job)]
    assert ids == ["1", "3", "4"]


def test_liet_anh_co_that_va_bo_video_da_loai(kho, capsys):
    db, job = kho
    models.danh_dau_da_loai(db, "4", TOI)
    rc, ra, _ = _chay(capsys, db, "liet", job)
    assert rc == 0
    assert (ra["so_video_cua_job"], ra["so_bi_loc"]) == (4, 1)
    assert {v["video_id"]: v["anh"] for v in ra["video"]} == {
        "1": ["thumbs/1.webp", "thumbs/khung/1-50.webp", "thumbs/khung/1-90.webp"],
        "2": ["thumbs/2.webp"], "3": ["thumbs/khung/3-50.webp"]}
    assert ra["url"].startswith("https://www.tiktok.com/")
    assert all(v["nhan"] is None and v["caption"] is None for v in ra["video"])


def test_liet_tra_cache_dung_phien_ban(kho, capsys, tmp_path):
    db, job = kho
    assert _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[0] == 0
    rc, ra, _ = _chay(capsys, db, "liet", job, "--nhan-ver", "nhan:abc@m",
                      "--caption-ver", "caption:def@m")
    v1 = next(v for v in ra["video"] if v["video_id"] == "1")
    assert v1["nhan"] == {"the_chu": False}
    assert v1["caption"] == {"caption_lech_chu_de": "khong_ro"}
    rc, ra, _ = _chay(capsys, db, "liet", job, "--nhan-ver", "nhan:KHAC@m")
    assert next(v for v in ra["video"] if v["video_id"] == "1")["nhan"] is None


def test_liet_job_khong_co(kho, capsys):
    db, _ = kho
    assert _chay(capsys, db, "liet", 999)[0] == nhap_cum_cli.MA_KHONG_CO_JOB


# --- cache nhãn / caption: hai loại hàng không lẫn nhau --------------------------

def test_doc_nhan_khong_bao_gio_doc_hang_caption(kho):
    db, _ = kho
    with models._connect(db) as conn:
        models_dac_diem.ghi(conn, [
            {"video_id": "1", "phien_ban_prompt": "nhan:v1", "nhan": {"the_chu": True}},
            {"video_id": "1", "phien_ban_prompt": "caption:v1",
             "nhan": {"caption_lech_chu_de": True}},
            {"video_id": "2", "phien_ban_prompt": "caption:v1",
             "nhan": {"caption_lech_chu_de": False}}])
    with models._connect(db) as conn:
        assert models_dac_diem.doc_nhan(conn, ["1", "2"], "nhan:v1") == {"1": {"the_chu": True}}
        assert set(models_dac_diem.doc_caption(conn, ["1", "2"], "caption:v1")) == {"1", "2"}
        with pytest.raises(ValueError):
            models_dac_diem.doc_nhan(conn, ["1"], "caption:v1")
        with pytest.raises(ValueError):
            models_dac_diem.doc_caption(conn, ["1"], "nhan:v1")
        with pytest.raises(ValueError):
            models_dac_diem.ghi(conn, [{"video_id": "1", "phien_ban_prompt": "v1", "nhan": {}}])


# --- ten-co-san ------------------------------------------------------------------

def _cum(db, chu, insight, kieu):
    with models._connect(db) as conn:
        conn.execute("INSERT INTO cum (chu, usecase, insight_goc, kieu, tao_luc) "
                     "VALUES (?, 'Dance', ?, ?, 'x')", (chu, insight, kieu))


def test_ten_co_san_loc_theo_insight_cua_nguoi_tao(kho, capsys):
    db, job = kho
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET usecase = 'Dance', insight_goc = 'Badaboum' WHERE id = ?",
                     (job,))
    _cum(db, TOI, "badaboum ", "Vest công sở")
    _cum(db, TOI, "Khác", "Mặt nạ")
    _cum(db, HO, "Badaboum", "Của người khác")
    rc, ra, err = _chay(capsys, db, "ten-co-san", job)
    assert rc == 0
    assert ra == {"job_id": job, "usecase": "Dance", "insight_goc": "Badaboum",
                  "loc_theo_insight": True, "kieu": ["Vest công sở"]}
    assert "không lọc" not in err


def test_ten_co_san_job_chua_co_insight_lay_moi_kieu(kho, capsys):
    db, job = kho
    _cum(db, TOI, "A", "Vest")
    _cum(db, TOI, "B", "Mặt nạ")
    _cum(db, HO, "A", "Của người khác")
    rc, ra, err = _chay(capsys, db, "ten-co-san", job)
    assert (rc, ra["loc_theo_insight"], ra["kieu"]) == (0, False, ["Vest", "Mặt nạ"])
    assert "không lọc theo insight" in err


def test_ten_co_san_chua_co_cum_nao(kho, capsys):
    db, job = kho
    rc, ra, _ = _chay(capsys, db, "ten-co-san", job)
    assert (rc, ra["kieu"]) == (0, [])


# --- cho-chia ----------------------------------------------------------------------

def test_cho_chia_chi_job_done_chua_co_nhap(kho, capsys, tmp_path):
    db, job = kho
    job_loi = models.create_job(db, "https://www.tiktok.com/tag/b", 1, TOI)
    models.finish_job(db, job_loi, "failed")
    assert [j["job_id"] for j in _chay(capsys, db, "cho-chia")[1]] == [job]
    assert _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[0] == 0
    assert _chay(capsys, db, "cho-chia")[1] == []


# --- ghi ------------------------------------------------------------------------------

def test_ghi_tao_luot_ghi_nhap_va_cache_trong_mot_lan(kho, capsys, tmp_path):
    db, job = kho
    rc, ra, _ = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))
    assert rc == 0
    assert (ra["tao_moi"], ra["so_video"], ra["da_o_cum"], ra["bo_vi_loc"]) == (True, 3, [], [])
    chia = models_chia.lay_chia(db, ra["chia_lan_id"], TOI)
    assert chia["trang_thai"] == "de_xuat" and chia["phien_ban_prompt"] == PB
    assert chia["chu"] == TOI
    assert [(k["nhom"], k["kieu"], k["video_ids"]) for k in chia["kieu"]] == [
        ("Vest", "Vest công sở", ["1", "2"])]
    assert chia["huong_dan"] == ["3"]
    assert _dem(db, "video_dac_diem") == 2


def test_ghi_doc_tu_stdin(kho, capsys, monkeypatch):
    db, job = kho
    rc, ra, _ = _chay(capsys, db, "ghi", job, "-", stdin=json.dumps(_de_xuat()),
                      monkeypatch=monkeypatch)
    assert rc == 0 and ra["so_video"] == 3


def test_ghi_lan_hai_dung_lai_luot_chua_sua(kho, capsys, tmp_path):
    db, job = kho
    dau = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]
    sau = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat(truc="boi_canh")))[1]
    assert sau["chia_lan_id"] == dau["chia_lan_id"] and sau["tao_moi"] is False
    assert _dem(db, "chia_lan") == 1
    assert models_chia.lay_chia(db, sau["chia_lan_id"], TOI)["truc"] == "boi_canh"


def test_ghi_tu_choi_de_nhap_da_co_sua_tay(kho, capsys, tmp_path):
    db, job = kho
    lan = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]["chia_lan_id"]
    kieu = models_chia.lay_chia(db, lan, TOI)["kieu"][0]["cum_nhap_id"]
    # Chỉ sửa CÁCH CHIA (hoặc duyệt) mới chặn ghi đè; `chap_nhan`/`doi_insight`
    # đơn lẻ thì không (xem `models_chia.LOAI_CHAN_GHI_DE_NHAP`).
    models_chia.ap_thao_tac(db, lan, TOI, "doi_ten", cum_nhap_id=kieu, kieu="x")
    truoc = models_chia.lay_chia(db, lan, TOI)
    rc, _, err = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat(nhoms=[])))
    assert rc == nhap_cum_cli.MA_NHAP_BI_CHAN and "thao tác" in err
    assert models_chia.lay_chia(db, lan, TOI) == truoc


def test_ghi_sau_luot_da_huy_mo_luot_moi(kho, capsys, tmp_path):
    db, job = kho
    lan = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]["chia_lan_id"]
    with models._connect(db) as conn:
        conn.execute("UPDATE chia_lan SET trang_thai = 'huy' WHERE id = ?", (lan,))
    ra = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]
    assert ra["tao_moi"] is True and ra["chia_lan_id"] != lan


def test_ghi_bo_video_bi_loc_va_bao_lai(kho, capsys, tmp_path):
    db, job = kho
    models.danh_dau_da_loai(db, "2", TOI)
    rc, ra, _ = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))
    assert rc == 0 and ra["bo_vi_loc"] == ["2"] and ra["so_video"] == 2
    chia = models_chia.lay_chia(db, ra["chia_lan_id"], TOI)
    assert chia["kieu"][0]["video_ids"] == ["1"]


def test_ghi_bo_video_da_o_cum_that(kho, capsys, tmp_path):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "Có sẵn")
    models_cum.gan_video(db, cum_id, TOI, None, ["1"])
    ra = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]
    # Bị bộ lọc chung loại trước (không bao giờ vào lượt) — `da_o_cum` của
    # `ghi_de_xuat` là lớp chặn thứ hai cho nháp song song.
    assert ra["bo_vi_loc"] == ["1"] and ra["da_o_cum"] == [] and ra["so_video"] == 2


@pytest.mark.parametrize("sua, chu_loi", [
    ({"huong_dan": ["1"]}, "hơn một lần"),
    ({"nghi": ["999"]}, "không thuộc job"),
    ({"nhoms": [{"nhom": " ", "kieu": []}]}, "nhom"),
    ({"dac_diem": [{"video_id": "1", "phien_ban_prompt": "v1", "nhan": {}}]}, "tiền tố"),
    ({"nhoms": "x"}, "nhoms"),
])
def test_ghi_tep_sai_khong_ghi_gi(kho, capsys, tmp_path, sua, chu_loi):
    db, job = kho
    rc, ra, err = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat(**sua)))
    assert rc == nhap_cum_cli.MA_TEP_SAI and ra is None and chu_loi in err
    assert (_dem(db, "chia_lan"), _dem(db, "video_dac_diem")) == (0, 0)


def test_ghi_tep_thieu_khoa_json_hong_khoa_trung(kho, capsys, tmp_path):
    db, job = kho
    obj = _de_xuat()
    del obj["nghi"]
    assert _chay(capsys, db, "ghi", job, _tep(tmp_path, obj))[0] == nhap_cum_cli.MA_TEP_SAI
    (tmp_path / "hong.json").write_text("{")
    assert _chay(capsys, db, "ghi", job, tmp_path / "hong.json")[0] == nhap_cum_cli.MA_TEP_SAI
    (tmp_path / "trung.json").write_text(
        json.dumps(_de_xuat())[:-1] + ', "nghi": []}')
    rc, _, err = _chay(capsys, db, "ghi", job, tmp_path / "trung.json")
    assert rc == nhap_cum_cli.MA_TEP_SAI and "khoá trùng" in err


def test_ghi_job_khong_co_va_db_khong_co(kho, capsys, tmp_path):
    db, _ = kho
    assert _chay(capsys, db, "ghi", 999, _tep(tmp_path, _de_xuat()))[0] == \
        nhap_cum_cli.MA_KHONG_CO_JOB
    assert _chay(capsys, tmp_path / "khong.db", "cho-chia")[0] == nhap_cum_cli.MA_LOI_DB
    assert not (tmp_path / "khong.db").exists()


def test_ghi_trot_giua_chung_khong_de_lai_gi(kho, capsys, tmp_path, monkeypatch):
    """Lượt chia + cache nhãn + nháp là MỘT transaction: bước ghi nháp nổ ⇒ cả
    lượt chia lẫn hàng cache đều không còn."""
    db, job = kho

    def no(*a, **k):
        raise sqlite3.OperationalError("giả lập đĩa đầy")

    monkeypatch.setattr(models_chia, "_ghi_de_xuat_tren", no)
    rc, _, err = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))
    assert rc == nhap_cum_cli.MA_LOI_DB and "đĩa đầy" in err
    assert (_dem(db, "chia_lan"), _dem(db, "video_dac_diem")) == (0, 0)


# --- ghi-dac-diem: cache lưu độc lập với nháp ----------------------------------------

def test_ghi_dac_diem_chi_ghi_cache(kho, capsys, tmp_path):
    db, job = kho
    tep = _tep(tmp_path, {"dac_diem": _de_xuat()["dac_diem"]})
    rc, ra, _ = _chay(capsys, db, "ghi-dac-diem", job, tep)
    assert (rc, ra) == (0, {"so_hang": 2})
    assert (_dem(db, "video_dac_diem"), _dem(db, "chia_lan")) == (2, 0)


@pytest.mark.parametrize("obj", [
    {"dac_diem": [{"video_id": "999", "phien_ban_prompt": "nhan:a", "nhan": {}}]},
    {"dac_diem": [{"video_id": "1", "phien_ban_prompt": "a", "nhan": {}}]},
    {"dac_diem": [], "nhoms": []},
    [],
])
def test_ghi_dac_diem_tep_sai_khong_ghi_gi(kho, capsys, tmp_path, obj):
    db, job = kho
    assert _chay(capsys, db, "ghi-dac-diem", job, _tep(tmp_path, obj))[0] == \
        nhap_cum_cli.MA_TEP_SAI
    assert _dem(db, "video_dac_diem") == 0


# --- liet báo lượt mới nhất + lý do lọc ------------------------------------------------

def test_liet_bao_luot_moi_nhat_va_so_thao_tac(kho, capsys, tmp_path):
    db, job = kho
    assert _chay(capsys, db, "liet", job)[1]["luot_moi_nhat"] is None
    lan = _chay(capsys, db, "ghi", job, _tep(tmp_path, _de_xuat()))[1]["chia_lan_id"]
    assert _chay(capsys, db, "liet", job)[1]["luot_moi_nhat"] == {
        "id": lan, "trang_thai": "de_xuat", "so_thao_tac": 0}
    kieu = models_chia.lay_chia(db, lan, TOI)["kieu"][0]["cum_nhap_id"]
    models_chia.ap_thao_tac(db, lan, TOI, "chap_nhan", cum_nhap_id=kieu)
    assert _chay(capsys, db, "liet", job)[1]["luot_moi_nhat"]["so_thao_tac"] == 1


def test_liet_bo_video_da_o_cum_that_cua_chu_job(kho, capsys):
    """Chỉ cụm của CHỦ JOB loại video; cụm của người khác không."""
    db, job = kho
    cum_toi, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "Mặc vest")
    models_cum.gan_video(db, cum_toi, TOI, None, ["1", "2"])
    cum_ho, _ = models_cum.tao_cum(db, HO, "Dance", "Badaboum", "Mặc vest")
    models_cum.gan_video(db, cum_ho, HO, None, ["3"])
    models.danh_dau_da_loai(db, "2", TOI)
    ra = _chay(capsys, db, "liet", job)[1]
    assert [v["video_id"] for v in ra["video"]] == ["3", "4"]
    assert ra["so_bi_loc"] == 2
    assert ra["bi_loc_theo_ly_do"] == {"da_loai": 1, "da_vao_bo": 0, "da_don_drive": 0,
                                     "da_o_cum": 2}


# --- kiểu rỗng sau khi lọc không vào nháp -----------------------------------------------

def _ten_cum(db, lan_id) -> dict:
    return {(k["nhom"], k["kieu"]): k["ten_cum"]
            for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}


def test_kieu_rong_sau_loc_khong_tao_hang_va_khong_ep_ten(kho, capsys, tmp_path):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "Có sẵn")
    models_cum.gan_video(db, cum_id, TOI, None, ["1", "2"])
    obj = _de_xuat(nhoms=[
        {"nhom": "A", "kieu": [{"kieu": "Vest", "video_ids": ["1", "2"]}]},
        {"nhom": "B", "kieu": [{"kieu": "Vest", "video_ids": ["3"]}]}], huong_dan=["4"])
    ra = _chay(capsys, db, "ghi", job, _tep(tmp_path, obj))[1]
    assert _ten_cum(db, ra["chia_lan_id"]) == {("B", "Vest"): "Vest"}
    assert _dem(db, "cum_nhap") == 1


def test_ghi_de_xuat_kieu_rong_vi_da_o_cum_khong_tao_hang(kho):
    """Lớp chặn thứ hai (`ghi_de_xuat::loc`, nháp song song): kiểu còn 0 video
    cũng không vào nháp."""
    db, job = kho
    lan = models_chia.tao_chia_lan(db, job, TOI, "p")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "Có sẵn")
    models_cum.gan_video(db, cum_id, TOI, None, ["1"])
    ket = models_chia.ghi_de_xuat(db, lan, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "Vest", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "Vest", "video_ids": ["2"]}]}])
    assert ket["da_o_cum"] == ["1"]
    assert _ten_cum(db, lan) == {("B", "Vest"): "Vest"}
