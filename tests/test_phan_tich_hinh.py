"""Tầng hình trên máy dev — `scripts/phan-tich-hinh.sh` + `scripts/tu-chia-cum/`.

KHÔNG test nào chạm agy thật hay ssh thật: agy là `AgyGia` (tiêm vào `main`,
đếm lượt gọi theo loại, tự viết tệp đích như agy), mini là DB CỤC BỘ
(`--mini-db`, chạy đúng CLI `web.nhap_cum_cli` bằng subprocess). Biến môi
trường `AGY_BIN`/`SSH_BIN` trỏ vào tên không tồn tại cho mọi test, để một
đường lỡ gọi binary thật cũng nổ chứ không chạy.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

import pytest

from web import lifecycle, models, models_chia, models_cum, models_dac_diem

GOC = Path(__file__).resolve().parents[1]
DAY = GOC / "scripts" / "tu-chia-cum"
sys.path.insert(0, str(DAY))

import agy_lenh  # noqa: E402
import mini as mini_mod  # noqa: E402
import phan_tich_hinh as pth  # noqa: E402

TOI = "toi@astronex.ai"
TIKTOK = "https://www.tiktok.com/tag/vest"


@pytest.fixture(autouse=True)
def _khong_binary_that(monkeypatch):
    monkeypatch.setenv("AGY_BIN", "agy-gia-khong-ton-tai")
    monkeypatch.setenv("SSH_BIN", "ssh-gia-khong-ton-tai")


class AgyGia:
    """Đóng vai agy: đọc tệp prompt (đường dẫn lấy từ argv), viết tệp đích.
    `the_chu`: id có thẻ chữ. Video id chẵn không có đám đông. `caption_true`:
    id agy chấm cờ `caption_lech_chu_de = True` (mặc định mọi id ra `False`)."""

    def __init__(self, the_chu=(), caption_true=()):
        self.the_chu = set(the_chu)
        self.caption_true = set(caption_true)
        self.goi: list[str] = []
        self.argv: list[list[str]] = []
        self.cwd: list[Path] = []

    def dem(self) -> Counter:
        return Counter(self.goi)

    def __call__(self, argv, cwd):
        assert argv[0] == "agy-gia-khong-ton-tai"
        self.argv.append(argv)
        self.cwd.append(Path(cwd))
        tep = Path(re.search(r"Đọc tệp (\S+) và", argv[2]).group(1))
        van_ban = tep.read_text(encoding="utf-8")
        ra = Path(re.search(r"^TỆP KẾT QUẢ: (.+)$", van_ban, re.M).group(1))
        dong = [json.loads(d) for d in van_ban.split("\nVIDEO:\n", 1)[1].splitlines() if d.strip()]
        if tep.name.startswith("nhan-"):
            self.goi.append("nhan")
            ra.write_text("\n".join(json.dumps({
                "video_id": d["video_id"], "so_khung": len(d["anh"]),
                "the_chu": d["video_id"] in self.the_chu,
                "trang_phuc_dam_dong": "khong co dam dong" if int(d["video_id"]) % 2 == 0
                else "vest den", "trang_phuc_nguoi_chinh": "so mi trang",
                "boi_canh": "san truong"}) for d in dong))
        elif tep.name.startswith("caption"):
            self.goi.append("caption")
            ra.write_text(json.dumps({d["video_id"]: d["video_id"] in self.caption_true
                                      for d in dong}))
        else:
            self.goi.append("chuan_hoa")
            truc = re.search(r"^TRỤC: (.+)$", van_ban, re.M).group(1)
            gan = {}
            for d in dong:
                gan[d["video_id"]] = {"lan": "nghi"} if d[truc] == "khong co dam dong" \
                    else {"nhom": "Trang phục", "kieu": d[truc].title()}
            kieu = sorted({g["kieu"] for g in gan.values() if "kieu" in g})
            ra.write_text(json.dumps({"nhom": {"Trang phục": kieu}, "gan": gan},
                                     ensure_ascii=False))
        return 0


def _kho(tmp_path, n=5, khong_anh=(), url=TIKTOK, da_loai=()):
    """Job `done` của TOI, video "101".."10n" có poster + khung 50 (trừ
    `khong_anh`), caption khác rỗng trừ video cuối."""
    db = tmp_path / "mini" / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, url, n, TOI)
    for i in range(1, n + 1):
        vid = str(100 + i)
        models.record_video(db, job_id=job, video_id=vid, url=f"https://www.tiktok.com/v/{vid}",
                            description="" if i == n else f"caption video {vid}")
        if vid not in khong_anh:
            for p in (lifecycle.thumb_path_for(db, vid), lifecycle.khung_phu_path_for(db, vid, 50)):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"webp")
    for vid in da_loai:
        models.danh_dau_da_loai(db, vid, TOI)
    models.finish_job(db, job, "done")
    return db, job


def _chay(tmp_path, db, *args, agy=None, ten="s"):
    dong: list[str] = []
    rc = pth.main(["--mini-db", str(db), "--scratch", str(tmp_path / ten), *map(str, args)],
                  chay_agy=agy or AgyGia(), out=dong.append)
    return rc, "\n".join(dong)


def _nhap(db, job) -> dict:
    """Nháp mới nhất của job: `{lan: [id]}` + kiểu."""
    with sqlite3.connect(db) as conn:
        lan = conn.execute("SELECT id FROM chia_lan WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                           (job,)).fetchone()
        if lan is None:
            return {}
        rows = conn.execute("SELECT video_id, lan FROM video_cum_nhap WHERE chia_lan_id = ?",
                            (lan[0],)).fetchall()
    ra: dict[str, list[str]] = {}
    for vid, l in rows:
        ra.setdefault(l, []).append(vid)
    return {k: sorted(v) for k, v in ra.items()}


def _id_da_gui(agy: AgyGia) -> set[str]:
    """Mọi video_id có trong tệp prompt của mọi lượt agy đã gọi — đọc theo
    trường JSON, không so chuỗi con (đường dẫn tạm có thể chứa "103")."""
    ra = set()
    for argv in agy.argv:
        tep = Path(re.search(r"Đọc tệp (\S+) và", argv[2]).group(1))
        ra |= {json.loads(d)["video_id"] for d in
               tep.read_text().split("\nVIDEO:\n", 1)[1].splitlines() if d.strip()}
    return ra


def _dem(db, bang) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {bang}").fetchone()[0]


# --- lệnh agy ------------------------------------------------------------------------

def test_argv_agy_dung_model_co_va_chi_scratch(tmp_path):
    argv, _ = agy_lenh.lenh_nhan(tmp_path, [{"video_id": "1", "anh": [str(tmp_path / "a.webp")]}],
                                 tmp_path / "nhan-1.jsonl")
    assert argv[argv.index("--model") + 1] == "gemini-3.7-flash-low"
    argv2, _ = agy_lenh.lenh_chuan_hoa(tmp_path, "trang_phuc_dam_dong", {}, [],
                                       tmp_path / "chia.json")
    assert argv2[argv2.index("--model") + 1] == "gemini-3.8-flash-high"
    for a in (argv, argv2):
        assert "--effort" not in a
        assert a[a.index("--add-dir") + 1] == str(tmp_path) and a.count("--add-dir") == 1
        assert ["--mode", "accept-edits"] == a[a.index("--mode"):a.index("--mode") + 2]
        assert "--dangerously-skip-permissions" in a
        assert a[a.index("--print-timeout") + 1] == "25m"
        assert "toolchain" in a[2] and "biến môi trường" in a[2]
    for ten in ("prompt-nhan.txt", "prompt-caption.txt", "prompt-chuan-hoa.txt"):
        assert "KHÔNG chạy lệnh nào thay đổi toolchain" in (DAY / ten).read_text()


def test_tep_ket_qua_ngoai_scratch_bi_tu_choi(tmp_path):
    with pytest.raises(ValueError):
        agy_lenh.lenh_caption(tmp_path / "s", "x", {}, tmp_path / "ngoai.json")


def test_caption_di_bang_tep_khong_qua_argv(tmp_path):
    """Caption (kể cả 2 000 ký tự) CHỈ nằm trong tệp prompt; argv không mang
    chuỗi caption nào — argv cắt prompt lớn mà không báo."""
    dai = ("CAPDAI " + "vest đen nhảy #badaboum ") * 100
    caption = {"1": dai[:2000], "2": "CAPHAI mặc vest đi học", "3": "CAPBA 🕺 #fyp",
               "4": "CAPBON lệch chủ đề hẳn: nấu ăn"}
    assert len(caption["1"]) == 2000
    argv, tep = agy_lenh.lenh_caption(tmp_path, TIKTOK, caption, tmp_path / "caption.json")
    for c in caption.values():
        assert not any(c in a or c[:20] in a for a in argv)
    noi_dung = tep.read_text(encoding="utf-8")
    dong = [json.loads(d) for d in noi_dung.split("\nVIDEO:\n", 1)[1].splitlines() if d.strip()]
    assert {d["video_id"]: d["caption"] for d in dong} == caption
    assert tep.parent == tmp_path


def test_nhan_khong_qua_argv_cua_chuan_hoa(tmp_path):
    nhan = {"1": {"trang_phuc_dam_dong": "NHANRIENG vest den ca vat mat chuot"}}
    argv, tep = agy_lenh.lenh_chuan_hoa(tmp_path, "trang_phuc_dam_dong", nhan, ["TENCOSAN"],
                                        tmp_path / "chia.json")
    assert not any("NHANRIENG" in a or "TENCOSAN" in a for a in argv)
    assert "NHANRIENG" in tep.read_text() and "TENCOSAN" in tep.read_text()


def test_nghiem_thu_agy_bang_tep_khong_bang_ma_thoat(tmp_path):
    tep = tmp_path / "chia.json"
    tep.write_text("{}")   # tệp sót của lượt trước — không được đọc như kết quả
    with pytest.raises(agy_lenh.KhongCoTepDich):
        agy_lenh.chay(["agy"], tep, lambda argv, cwd: 0, "json", tmp_path)
    with pytest.raises(agy_lenh.KhongCoTepDich):
        agy_lenh.chay(["agy"], tep, lambda argv, cwd: tep.write_text("{hỏng") and 0, "json",
                      tmp_path)
    with pytest.raises(agy_lenh.KhongCoTepDich):
        agy_lenh.chay(["agy"], tep, lambda argv, cwd: tep.write_bytes(b"\xff\xfe{") and 0,
                      "json", tmp_path)
    assert agy_lenh.chay(["agy"], tep, lambda argv, cwd: tep.write_text('{"a": 1}') and 7,
                         "json", tmp_path) == ({"a": 1}, [])


# --- đường ống trên DB cục bộ ---------------------------------------------------------

def test_chay_that_ghi_nhap_du_video(tmp_path):
    db, job = _kho(tmp_path, n=5, khong_anh=())
    agy = AgyGia(the_chu={"103"})
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == 0, ra
    assert agy.dem() == {"nhan": 1, "caption": 1, "chuan_hoa": 1}
    assert _nhap(db, job) == {"kieu": ["101", "105"], "huong_dan": ["103"],
                              "nghi": ["102", "104"]}
    assert "ĐÃ GHI nháp" in ra
    # Caption chỉ đi qua tệp — ở CHỖ GỌI thật, không chỉ ở hàm dựng lệnh.
    for vid in ("101", "102", "103", "104"):
        assert not any(f"caption video {vid}" in a for argv in agy.argv for a in argv)
    # Ảnh tạm được dọn sau một lượt thành công.
    assert not (tmp_path / "s" / f"job-{job}" / "anh").exists()


def test_caption_lech_chu_de_day_video_ra_khoi_kieu_vao_lan_nghi(tmp_path):
    """`caption_lech_chu_de = True` CHỈ đẩy video RA khỏi một kiểu vào làn
    nghi — không bao giờ ngược lại. "101" (kiểu "Vest Den" theo chuẩn hoá)
    được agy chấm `True` ⇒ phải rơi khỏi kiểu, vào nghi. "102" đã ở nghi
    (không đám đông) TỪ TRƯỚC, cũng chấm `True` ⇒ vẫn ở nghi, không nhân đôi.
    """
    db, job = _kho(tmp_path, n=5, khong_anh=())
    agy = AgyGia(the_chu={"103"}, caption_true={"101", "102"})
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == 0, ra
    assert _nhap(db, job) == {"kieu": ["105"], "huong_dan": ["103"],
                              "nghi": ["101", "102", "104"]}
    # Chỉ "101" bị ĐẨY ra khỏi một kiểu — "102" vốn đã ở nghi, không được đếm
    # lại lần hai.
    assert "caption lệch ⇒ nghi: 1" in ra


def test_caption_khong_ro_hoac_false_khong_doi_gi(tmp_path):
    """Đối chứng dương: không `caption_true` nào ⇒ kết quả y hệt lượt không
    có luật caption (cùng dữ liệu, cùng `AgyGia` trừ cờ)."""
    db, job = _kho(tmp_path, n=5, khong_anh=())
    agy = AgyGia(the_chu={"103"})
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == 0, ra
    assert _nhap(db, job) == {"kieu": ["101", "105"], "huong_dan": ["103"],
                              "nghi": ["102", "104"]}
    assert "caption lệch ⇒ nghi: 0" in ra


def test_agy_chay_voi_cwd_la_scratch(tmp_path):
    db, job = _kho(tmp_path, n=3)
    agy = AgyGia()
    assert _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)[0] == 0
    assert agy.cwd and set(agy.cwd) == {(tmp_path / "s" / f"job-{job}").resolve()}


def test_nguoi_chay_agy_that_truyen_cwd(tmp_path, monkeypatch):
    nhan = {}

    def run(argv, **kw):
        nhan.update(kw)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pth.subprocess, "run", run)
    assert pth._chay_agy_that(["agy"], tmp_path) == 0
    assert nhan["cwd"] == tmp_path


class AgyChiaHong(AgyGia):
    """Vision + caption đúng, chuẩn hoá trả một danh sách thay vì object."""

    def __call__(self, argv, cwd):
        super().__call__(argv, cwd)
        if self.goi[-1] == "chuan_hoa":
            ra = Path(re.search(r"^TỆP KẾT QUẢ: (.+)$", Path(re.search(
                r"Đọc tệp (\S+) và", argv[2]).group(1)).read_text(), re.M).group(1))
            ra.write_bytes(self.hong)
        return 0

    hong = b"[]"


def test_chuan_hoa_truot_lan_hai_khong_tra_tien_lai(tmp_path):
    """Nhãn + cờ caption đã qua phép kiểm được lưu TRƯỚC chuẩn hoá: chuẩn hoá
    trượt ở lượt 1 ⇒ lượt 2 gọi 0 vision + 0 caption."""
    db, job = _kho(tmp_path, n=5)
    dau = AgyChiaHong()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=dau, ten="s1")
    assert rc == pth.MA_KHONG_DAT, ra
    assert dau.dem() == {"nhan": 1, "caption": 1, "chuan_hoa": 1}
    assert _dem(db, "chia_lan") == 0
    sau = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=sau, ten="s2")
    assert rc == 0, ra
    assert sau.dem() == {"chuan_hoa": 1}


def test_chuan_hoa_rac_la_do_hong(tmp_path):
    db, job = _kho(tmp_path, n=3)
    agy = AgyChiaHong()
    agy.hong = b"\xff\xfe r\xe1c"
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == pth.MA_DO_HONG and "ĐO HỎNG" in ra


def test_nhap_da_sua_tay_tu_choi_truoc_khi_keo_anh(tmp_path):
    db, job = _kho(tmp_path, n=3)
    assert _chay(tmp_path, db, "--luot", job, "--yes", ten="s0")[0] == 0
    with sqlite3.connect(db) as conn:
        lan = conn.execute("SELECT id FROM chia_lan").fetchone()[0]
    kieu = models_chia.lay_chia(db, lan, TOI)["kieu"][0]["cum_nhap_id"]
    models_chia.ap_thao_tac(db, lan, TOI, "chap_nhan", cum_nhap_id=kieu)
    for them in ((), ("--yes",)):
        agy = AgyGia()
        rc, ra = _chay(tmp_path, db, "--luot", job, *them, agy=agy, ten="s1")
        assert rc == pth.MA_TU_CHOI, ra
        assert "TỪ CHỐI" in ra and "1 thao tác" in ra
        assert agy.goi == [] and not (tmp_path / "s1").exists()


def test_video_da_o_cum_that_khong_bi_gui_di(tmp_path):
    """Video đã ở một cụm THẬT của chủ job: bộ lọc chung bỏ nó TRƯỚC khi liệt,
    nên ảnh không bao giờ rời máy."""
    db, job = _kho(tmp_path, n=5)
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "Mặc vest")
    models_cum.gan_video(db, cum_id, TOI, None, ["101", "103"])
    rc, ra = _chay(tmp_path, db, "--luot", job)
    assert rc == 0 and "5 → 3 video vào lượt · bỏ 2 (đã loại 0 · đã ở cụm 2)" in ra
    agy = AgyGia()
    assert _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)[0] == 0
    assert _id_da_gui(agy) == {"102", "104", "105"}
    assert not (tmp_path / "s" / f"job-{job}" / "anh" / "thumbs" / "101.webp").exists()
    assert {v for ds in _nhap(db, job).values() for v in ds} == {"102", "104", "105"}


def test_them_khung_sau_thi_nhan_cache_het_hieu_luc(tmp_path):
    db, job = _kho(tmp_path, n=3)
    assert _chay(tmp_path, db, "--luot", job, "--yes", ten="s1")[0] == 0
    p = lifecycle.khung_phu_path_for(db, "101", 90)
    p.write_bytes(b"webp")
    agy = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy, ten="s2")
    assert rc == 0, ra
    assert agy.dem()["nhan"] == 1
    lo = [json.loads(d) for d in (tmp_path / "s2" / f"job-{job}" / "nhan-1.jsonl")
          .read_text().splitlines()]
    assert [(d["video_id"], d["so_khung"]) for d in lo] == [("101", 3)]


def test_doi_model_doi_phien_ban_va_lenh(tmp_path):
    goc = pth.PhienBan.tu_thu_muc(DAY)
    doi = pth.PhienBan.tu_thu_muc(DAY, model_nhan="gemini-3.6-flash-low")
    assert doi.nhan != goc.nhan and doi.nhan.endswith("@gemini-3.6-flash-low")
    assert (doi.caption, doi.chuan_hoa) == (goc.caption, goc.chuan_hoa)
    doi2 = pth.PhienBan.tu_thu_muc(DAY, model_chuan_hoa="gemini-3.1-pro-high")
    assert doi2.nhan == goc.nhan and doi2.caption != goc.caption and doi2.chuan_hoa != goc.chuan_hoa
    db, job = _kho(tmp_path, n=3)
    agy = AgyGia()
    assert _chay(tmp_path, db, "--luot", job, "--yes", "--model-nhan", "gemini-3.6-flash-low",
                 "--model-chuan-hoa", "gemini-3.1-pro-high", agy=agy)[0] == 0
    model = {g: a[a.index("--model") + 1] for g, a in zip(agy.goi, agy.argv)}
    assert model == {"nhan": "gemini-3.6-flash-low", "caption": "gemini-3.1-pro-high",
                     "chuan_hoa": "gemini-3.1-pro-high"}


def test_ghi_rc0_ket_qua_rac_la_do_hong(tmp_path, monkeypatch):
    db, job = _kho(tmp_path, n=3)
    goc = mini_mod.MiniCucBo.cli

    def cli(self, args, stdin=None):
        rc, ra, err = goc(self, args, stdin)
        return (rc, "không phải json", err) if args[0] == "ghi" else (rc, ra, err)

    monkeypatch.setattr(mini_mod.MiniCucBo, "cli", cli)
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes")
    assert rc == pth.MA_DO_HONG and "CÓ THỂ" in ra


def test_cache_caption_lan_hai_doi_truc_khong_cham_lai(tmp_path):
    """Chuẩn hoá lại cùng lượt (đổi trục) ⇒ 0 lượt chấm caption, 0 lượt vision."""
    db, job = _kho(tmp_path, n=5)
    dau = AgyGia()
    assert _chay(tmp_path, db, "--luot", job, "--yes", agy=dau, ten="s1")[0] == 0
    assert dau.dem()["caption"] == 1
    sau = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", "--truc", "trang_phuc_nguoi_chinh",
                   agy=sau, ten="s2")
    assert rc == 0, ra
    assert sau.dem() == {"chuan_hoa": 1}
    with sqlite3.connect(db) as conn:
        pb = {r[0].split(":")[0] for r in conn.execute(
            "SELECT DISTINCT phien_ban_prompt FROM video_dac_diem")}
        assert pb == {"nhan", "caption"}
        assert conn.execute("SELECT COUNT(*) FROM chia_lan").fetchone()[0] == 1


def test_doi_prompt_nhan_khong_lam_mat_cache_caption(tmp_path):
    """Phiên bản prompt NHÃN và CAPTION tách nhau: sửa prompt nhãn ⇒ gán nhãn
    lại, caption vẫn đọc cache."""
    db, job = _kho(tmp_path, n=5)
    assert _chay(tmp_path, db, "--luot", job, "--yes", agy=AgyGia(), ten="s1")[0] == 0
    prompt = tmp_path / "prompt"
    shutil.copytree(DAY, prompt, ignore=shutil.ignore_patterns("__pycache__"))
    (prompt / "prompt-nhan.txt").write_text((DAY / "prompt-nhan.txt").read_text() + "\nThêm luật.")
    sau = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", "--thu-muc-prompt", prompt,
                   agy=sau, ten="s2")
    assert rc == 0, ra
    assert sau.dem() == {"nhan": 1, "chuan_hoa": 1}


def test_hang_caption_khong_bao_gio_la_nhan(tmp_path):
    db, job = _kho(tmp_path, n=3)
    assert _chay(tmp_path, db, "--luot", job, "--yes")[0] == 0
    pb = pth.PhienBan.tu_thu_muc(DAY)
    ids = ["101", "102", "103"]
    with models._connect(db) as conn:
        nhan = models_dac_diem.doc_nhan(conn, ids, pb.nhan)
        cap = models_dac_diem.doc_caption(conn, ids, pb.caption)
    assert set(nhan) == set(cap) == set(ids)
    assert all("caption_lech_chu_de" not in n and "the_chu" in n for n in nhan.values())
    assert all(set(c) == {"caption_lech_chu_de"} for c in cap.values())
    assert cap["103"] == {"caption_lech_chu_de": "khong_ro"}   # caption rỗng, không qua agy


def test_video_khong_anh_luot_van_di_va_bao_id(tmp_path):
    db, job = _kho(tmp_path, n=5, khong_anh=("102", "104"))
    agy = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == 0, ra
    assert re.search(r"không có ảnh nào k=2", ra)
    assert ra.count("102, 104") == 2   # trong kế hoạch VÀ lúc ghi xong
    nhap = _nhap(db, job)
    assert sorted(v for ds in nhap.values() for v in ds) == ["101", "103", "105"]
    nhan_goi = [json.loads(d)["video_id"] for d in
                (tmp_path / "s" / f"job-{job}" / "nhan-1.jsonl").read_text().splitlines()]
    assert sorted(nhan_goi) == ["101", "103", "105"]


def test_video_da_loai_khong_bi_gui_di(tmp_path):
    db, job = _kho(tmp_path, n=5, da_loai=("103",))
    agy = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == 0, ra
    assert "bỏ 1 (đã loại 1 · đã ở cụm 0)" in ra
    assert _id_da_gui(agy) == {"101", "102", "104", "105"}
    assert not (tmp_path / "s" / f"job-{job}" / "anh" / "thumbs" / "103.webp").exists()
    assert "103" not in {v for ds in _nhap(db, job).values() for v in ds}


def test_nguon_khong_phai_tiktok_bi_tu_choi(tmp_path):
    db, job = _kho(tmp_path, n=3, url="https://www.facebook.com/ads/library/?id=1")
    agy = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=agy)
    assert rc == pth.MA_TU_CHOI
    assert "TỪ CHỐI" in ra
    assert agy.goi == [] and _dem(db, "chia_lan") == 0
    assert not (tmp_path / "s" / f"job-{job}").exists()


def test_tiktok_gia_danh_bi_tu_choi():
    for url in ("https://www.tiktok.com.evil.io/x", "http://www.tiktok.com/tag/a",
                "https://tiktok.com/tag/a", None):
        assert not pth.nguon_duoc_phep(url)
    assert pth.nguon_duoc_phep("https://www.tiktok.com/music/abc-123")


def test_khong_yes_la_thu_kho(tmp_path):
    db, job = _kho(tmp_path, n=5, khong_anh=("105",))
    agy = AgyGia()
    rc, ra = _chay(tmp_path, db, "--luot", job, agy=agy)
    assert rc == 0
    assert agy.goi == [] and _dem(db, "chia_lan") == 0 and _dem(db, "video_dac_diem") == 0
    assert not (tmp_path / "s").exists()
    assert "THỬ KHÔ" in ra and "k=1" in ra and "105" in ra
    assert "ước tính 3 lượt gọi agy" in ra


def test_mac_dinh_moi_luot_chua_co_nhap(tmp_path):
    db, job = _kho(tmp_path, n=2)
    job2 = models.create_job(db, TIKTOK, 1, TOI)
    models.record_video(db, job_id=job2, video_id="201", url="u")
    models.finish_job(db, job2, "done")
    rc, ra = _chay(tmp_path, db)
    assert rc == 0 and f"2 lượt tải cần xử: {job}, {job2}" in ra
    assert _chay(tmp_path, db, "--luot", job, "--yes", ten="s1")[0] == 0
    assert f"1 lượt tải cần xử: {job2}" in _chay(tmp_path, db)[1]


def test_ket_qua_sai_khong_ghi_gi_ma_rieng(tmp_path):
    db, job = _kho(tmp_path, n=3)

    class AgyThieuId(AgyGia):
        def __call__(self, argv, cwd):
            super().__call__(argv, cwd)
            if self.goi[-1] == "chuan_hoa":
                ra = Path(re.search(r"^TỆP KẾT QUẢ: (.+)$", Path(re.search(
                    r"Đọc tệp (\S+) và", argv[2]).group(1)).read_text(), re.M).group(1))
                obj = json.loads(ra.read_text())
                obj["gan"].pop(next(iter(obj["gan"])))
                ra.write_text(json.dumps(obj))
            return 0

    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=AgyThieuId())
    assert rc == pth.MA_KHONG_DAT and "thiếu 1/" in ra
    assert _dem(db, "chia_lan") == 0
    assert f"giữ scratch để soi: {tmp_path / 's' / f'job-{job}'}" in ra
    assert (tmp_path / "s" / f"job-{job}" / "anh").is_dir()


def test_agy_khong_sinh_tep_la_do_hong(tmp_path):
    db, job = _kho(tmp_path, n=3)
    rc, ra = _chay(tmp_path, db, "--luot", job, "--yes", agy=lambda argv, cwd: 0)
    assert rc == pth.MA_DO_HONG and "ĐO HỎNG" in ra
    assert _dem(db, "chia_lan") == 0


def test_job_khong_co_la_do_hong(tmp_path):
    db, _ = _kho(tmp_path, n=1)
    assert _chay(tmp_path, db, "--luot", 999)[0] == pth.MA_DO_HONG


# --- vỏ bash -------------------------------------------------------------------------

def test_vo_bash_thu_kho_tren_db_cuc_bo(tmp_path):
    db, job = _kho(tmp_path, n=4, khong_anh=("102",))
    moc = tmp_path / "agy-da-bi-goi"
    gia = tmp_path / "agy-gia.sh"
    gia.write_text(f"#!/bin/sh\ntouch {moc}\n")
    gia.chmod(0o755)
    env = {**os.environ, "PYTHON": sys.executable, "AGY_BIN": str(gia), "SSH_BIN": str(gia)}
    r = subprocess.run(["bash", str(GOC / "scripts" / "phan-tich-hinh.sh"), "--luot", str(job),
                        "--mini-db", str(db)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "THỬ KHÔ" in r.stdout and "k=1" in r.stdout and "102" in r.stdout
    assert not moc.exists() and _dem(db, "chia_lan") == 0


# --- mini qua ssh (người chạy lệnh giả) --------------------------------------------------

def _tar(tep: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for ten, noi in tep.items():
            info = tarfile.TarInfo(ten)
            info.size = len(noi)
            t.addfile(info, io.BytesIO(noi))
    return buf.getvalue()


def test_mini_ssh_dung_lenh_va_giai_tar_chi_muc_da_xin(tmp_path):
    goi = []

    def chay(argv, stdin):
        goi.append(argv)
        if "tar -cf" in argv[-1]:
            return 0, _tar({"thumbs/101.webp": b"a", "thumbs/khung/101-50.webp": b"b"}), b""
        return 0, b"[]", b""

    m = mini_mod.MiniSsh("u@h", "~/Projects/video-download", chay, ssh_bin="ssh")
    assert m.cli(["liet", "10", "--nhan-ver", "nhan:x@y"])[0] == 0
    assert goi[0] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "--", "u@h",
                      "cd ~/Projects/video-download && .venv/bin/python -m "
                      "web.nhap_cum_cli liet 10 --nhan-ver nhan:x@y"]
    m.keo_anh(["thumbs/101.webp", "thumbs/khung/101-50.webp"], tmp_path)
    assert (tmp_path / "thumbs" / "khung" / "101-50.webp").read_bytes() == b"b"
    with pytest.raises(mini_mod.LoiMini):
        m.keo_anh(["thumbs/101.webp"], tmp_path / "x")   # tar trả mục không xin
    with pytest.raises(mini_mod.LoiMini):
        m.keo_anh(["../../etc/passwd"], tmp_path)
    assert len(goi) == 3   # đường dẫn sai bị chặn TRƯỚC khi ra ssh


@pytest.mark.parametrize("host", ["-oProxyCommand=touch /tmp/x", "u@h;ls", "", "a b"])
def test_host_ssh_sai_bi_tu_choi(tmp_path, host):
    with pytest.raises(ValueError):
        mini_mod.MiniSsh(host, "~/Projects/video-download", lambda a, s: (0, b"", b""))
    rc = pth.main(["--ssh", host, "--luot", "1"], chay_agy=AgyGia(), chay_lenh=lambda a, s: 1 / 0,
                  out=lambda _: None)
    assert rc == pth.MA_CU_PHAP


def test_host_ssh_lay_tu_bien_moi_truong_chung(monkeypatch):
    goi = []
    monkeypatch.setenv("VIDEODL_MINI_HOST", "ai@may-khac")

    def chay(argv, stdin):
        goi.append(argv)
        return 1, b"", b"khong"

    assert pth.main(["--luot", "1"], chay_agy=AgyGia(), chay_lenh=chay,
                    out=lambda _: None) == pth.MA_DO_HONG
    assert goi[0][goi[0].index("--") + 1] == "ai@may-khac"


class AgyChuanHoaHong(AgyGia):
    """Như `AgyGia` nhưng tệp chuẩn hoá là một mảng — không đạt kiểm."""

    def __call__(self, argv, cwd):
        rc = super().__call__(argv, cwd)
        if self.goi and self.goi[-1] == "chuan_hoa":
            tep = Path(re.search(r"Đọc tệp (\S+) và", argv[2]).group(1))
            ra = Path(re.search(r"^TỆP KẾT QUẢ: (.+)$", tep.read_text(encoding="utf-8"),
                                re.M).group(1))
            ra.write_text("[]")
        return rc


def test_dung_som_van_ke_lai_job_bi_tu_choi_va_chua_chay(tmp_path):
    """Chạy mọi lượt: job không phải TikTok bị từ chối, job sau không đạt ⇒ mã
    thoát là 4, nhưng dòng tổng kết vẫn kể job bị từ chối."""
    db, job_tu_choi = _kho(tmp_path, n=2, url="https://example.com/khong-phai-tiktok")
    job_hong = models.create_job(db, TIKTOK, 2, TOI)
    for vid in ("201", "202"):
        models.record_video(db, job_id=job_hong, video_id=vid,
                            url=f"https://www.tiktok.com/v/{vid}", description="c")
        p = lifecycle.thumb_path_for(db, vid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"webp")
    models.finish_job(db, job_hong, "done")
    rc, ra = _chay(tmp_path, db, "--yes", agy=AgyChuanHoaHong())
    assert rc == pth.MA_KHONG_DAT, ra
    cuoi = ra.strip().splitlines()[-1]
    assert cuoi.startswith("tổng kết khi dừng") and str(job_tu_choi) in cuoi, ra
