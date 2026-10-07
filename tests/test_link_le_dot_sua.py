"""Đợt sửa sau review: cổng 503 nền tảng tắt, câu báo lỗi trung tính, trần đĩa/dung lượng cho TikTok video lẻ,
ô nhập (Ctrl/⌘+Enter), bỏ link đã có TRƯỚC khi gọi nền tảng, nguồn theo từng video, không thử lại lỗi vĩnh viễn,
cảnh báo cấu hình một lần, link YouTube từ Mix/playlist, và mẫu che id chặt hơn.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from yt_dlp.utils import DownloadError, ExtractorError

from link_le_khung import Khung
from yt_dlp_gia import YtdlpGia, loi_tai, thong_tin

from tiktok_music_downloader import downloader
from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.nguon import LinkLe, chuan_hoa_link
from tiktok_music_downloader.utils import VideoRef, che_url
from web import app as app_mod
from web import models, pacer
from web import queue as queue_mod

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
A, B, C = "aAa1aAa1aAa", "bBb2bBb2bBb", "cCc3cCc3cCc"
TT = "https://www.tiktok.com/@nguoi.dung/video/7123456789012345678"
GOC_NODE = ("const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
            "function lay(a,b){const i=src.indexOf(a);const j=src.indexOf(b,i);return src.slice(i,j);}")


def _yt(v):
    return f"https://www.youtube.com/watch?v={v}"


def _node(kich_ban: str, tep: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    ra = subprocess.run([node, "-e", GOC_NODE + kich_ban, str(STATIC / tep)], capture_output=True, text=True, timeout=30)
    assert ra.returncode == 0, ra.stderr
    return json.loads(ra.stdout)


def _dung_app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    return db


def _tao(url, so_luong=5):
    return app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=so_luong), nguoi_tao="a@x.vn")


# ------------------------------------------------------------------ (a) nền tảng TẮT ⇒ 503

def test_nen_tang_dang_tat_thi_post_jobs_503_cau_ro_va_khong_ghi_job(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    pacer.tat_nen_tang(db, "youtube", "not_a_bot")
    with pytest.raises(HTTPException) as e:
        _tao(_yt(A))
    assert e.value.status_code == 503
    assert e.value.detail == "YouTube tạm tắt do bị chặn, admin bật lại"
    assert models.list_jobs(db, None) == []
    # nền tảng khác vẫn nhận; admin bật lại thì YouTube nhận lại
    assert _tao(TT)["nen_tang"] == "tiktok"
    pacer.bat_lai(db, "youtube")
    assert _tao(_yt(A))["trang_thai"] == "pending"


def test_tran_gio_hay_tran_ngay_thi_van_nhan_job(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    for i in range(60):
        pacer.ghi_truoc_khi_goi(db, "youtube", None)
    assert "youtube" in pacer.nen_tang_loai_tru(db)
    assert _tao(_yt(A))["trang_thai"] == "pending"


# ------------------------------------------------------------------ (b) câu báo lỗi trung tính

def test_cau_loi_phia_nguon_khong_noi_tiktok():
    js = (STATIC / "bao-thieu.js").read_text(encoding="utf-8")
    kich_ban = ("global.window={};eval(process.argv[2]);"
                "console.log(JSON.stringify(window.BaoThieu.khungLoi("
                "{loi:2,loi_tiktok:2,tong:5,xong:3,tim_thay:5,trang_thai:'done'})));")
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    r = subprocess.run([node, "-e", kich_ban, "x", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    html = json.loads(r.stdout)
    assert "2 video nguồn không cho tải" in html and "lo-tt" in html
    assert "TikTok" not in html


# ------------------------------------------------------------------ (c) TikTok video lẻ: đĩa từng file + trần dung lượng

class _Dia:
    def __init__(self, ok):
        self.ok, self.reason = ok, "đĩa còn quá ít"


def test_tiktok_le_kiem_dia_tung_file_va_dat_max_filesize(monkeypatch, tmp_path):
    gia = YtdlpGia({TT: {"id": "7123456789012345678"}})
    k = Khung(monkeypatch, tmp_path, gia)
    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda p: _Dia(False))
    job = k.chay(k.tao_job([TT], nen_tang="tiktok"))
    assert (job["trang_thai"], job["ly_do_dung"]) == ("failed", "het_dia")
    assert gia.so_goi("tai") == 0
    # đĩa đủ ⇒ tải, và opts mang trần 500MB
    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda p: _Dia(True))
    job2 = k.chay(k.tao_job([TT], nen_tang="tiktok"))
    assert job2["xong"] == 1
    assert gia.opts_da_tao[-1]["max_filesize"] == 500 * 1024 * 1024


def test_tiktok_le_file_vuot_tran_bi_yt_dlp_bo_qua_la_loi_qua_nang_phia_nguon(monkeypatch, tmp_path):
    gia = YtdlpGia({TT: {"id": "7123456789012345678"}})
    gia.khong_ghi_tep.add(TT)
    k = Khung(monkeypatch, tmp_path, gia)
    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda p: _Dia(True))
    job = k.chay(k.tao_job([TT], nen_tang="tiktok"))
    assert job["xong"] == 0 and job["loi"] == 1 and job["loi_tiktok"] == 1


def test_tiktok_collection_khong_doi_khong_kiem_dia_tung_file_khong_max_filesize(monkeypatch, tmp_path):
    gia = YtdlpGia({"https://www.tiktok.com/@u/video/111": {"id": "111"}})
    k = Khung(monkeypatch, tmp_path, gia)
    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda p: _Dia(False))   # đĩa cạn: collection vẫn chạy như cũ
    goi = {}
    real = queue_mod.download_all

    def do(*a, **kw):
        goi.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(queue_mod, "download_all", do)
    jid = models.create_job(k.db, "https://www.tiktok.com/music/x-1", 5, "a@x.vn")
    job = models.get_job(k.db, jid)
    refs = [VideoRef(video_id="111", url="https://www.tiktok.com/@u/video/111")]
    queue_mod._hoan_tat_tu_refs(k.db, k.downloads, job, refs, {}, None, k.hook_drive)
    assert set(goi) == {"cookies_path", "progress"}, goi
    assert "max_filesize" not in gia.opts_da_tao[0] and models.get_job(k.db, jid)["xong"] == 1


# ------------------------------------------------------------------ (d) ô nhập

def test_o_nhap_co_goi_y_va_phim_tat_gui_form():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Mỗi dòng một link · Ctrl/⌘+Enter để tạo" in html
    ra = _node("eval(lay('function laPhimGuiForm','document.getElementById(\"url\").addEventListener'));"
               "console.log(JSON.stringify([laPhimGuiForm({key:'Enter',ctrlKey:true}),laPhimGuiForm({key:'Enter',metaKey:true}),"
               "laPhimGuiForm({key:'Enter'}),laPhimGuiForm({key:'a',ctrlKey:true}),laPhimGuiForm(null)]));", "app.js")
    assert ra == [True, True, False, False, False]
    assert "requestSubmit()" in (STATIC / "app.js").read_text(encoding="utf-8")


# ------------------------------------------------------------------ 1. không đốt lượt cho link đã có

def test_ba_link_hai_da_co_thi_dung_mot_luot_liet_ke(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(v): thong_tin(v) for v in (A, B, C)})
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([_yt(A), _yt(B)]))
    gia.goi.clear()
    luot_truoc = k.so_luot("youtube")
    job = k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)]))
    assert [u for l, u in gia.goi if l == "liet_ke"] == [_yt(C)]
    assert k.so_luot("youtube") - luot_truoc == 2         # 1 liệt kê + 1 tải; hai link đã có KHÔNG tốn lượt nào
    assert job["bo_qua"] == 2 and job["xong"] == 1


def test_tat_ca_link_da_co_la_already_owned_khong_goi_nen_tang(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(A): thong_tin(A)})
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([_yt(A)]))
    gia.goi.clear()
    job = k.chay(k.tao_job([_yt(A)]))
    assert gia.goi == [] and job["ly_do_dung"] == "already_owned" and job["bo_qua"] == 1


def test_dung_liet_ke_khi_du_so_video_moi(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(v): thong_tin(v) for v in (A, B, C)})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)], so_luong=1))
    assert [u for l, u in gia.goi if l == "liet_ke"] == [_yt(A)] and job["xong"] == 1


def test_so_video_cua_job_link_le_bang_so_link_khong_theo_o_so_luong(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    ra = _tao(f"{_yt(A)}\n{_yt(B)}\n{_yt(C)}", so_luong=1)
    assert models.get_job(db, ra["id"])["tong"] == 3
    assert _tao("https://www.tiktok.com/tag/abc", so_luong=7)["tong"] == 7      # nguồn khác: vẫn theo ô số


# ------------------------------------------------------------------ 2. nguồn theo từng video

def test_nguon_cua_job_nhieu_link_la_url_cua_chinh_video(monkeypatch, tmp_path):
    gia = YtdlpGia({_yt(v): thong_tin(v) for v in (A, B, C)})
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([_yt(A)]))                            # A đã có ⇒ lần sau bị bỏ qua (da_tai=0)
    k.chay(k.tao_job([_yt(A), _yt(B), _yt(C)]))
    with models._connect(k.db) as c:
        nguon = {r["video_id"]: r["nguon"] for r in c.execute(
            "SELECT video_id, nguon FROM video_sightings WHERE job_id = 2")}
    assert nguon == {f"yt-{A}": _yt(A), f"yt-{B}": _yt(B), f"yt-{C}": _yt(C)}


def test_nhan_nguon_giao_dien_theo_nen_tang_cho_link_le_va_giu_nhan_cu_cho_trang():
    kich_ban = ("global.URL=URL;eval(lay('const NEN_TANG_THEO_HOST','function sourceBuckets'));"
                "console.log(JSON.stringify(process.argv.slice(3).map(shortenSourceUrl)));")
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    urls = [_yt(A), "https://youtu.be/dQw4w9WgXcQ", "https://www.instagram.com/reel/Cabc123/",
            TT, "https://www.tiktok.com/tag/ai", "https://www.tiktok.com/@nguoi.dung", "https://www.tiktok.com/music/x-1",
            "https://x.com/u/status/12345"]
    r = subprocess.run([node, "-e", GOC_NODE + kich_ban, str(STATIC / "app.js"), "x", *urls],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    nhan = json.loads(r.stdout)
    assert nhan[0] == f"YouTube · {A}" and nhan[1] == "YouTube · dQw4w9WgXcQ"
    assert nhan[2] == "Instagram · Cabc123" and nhan[3] == "TikTok · 71234567890…"
    assert nhan[4] == "#ai" and nhan[5] == "@nguoi.dung" and nhan[6].startswith("🎵")
    assert nhan[7] == "X · 12345"
    assert len(set(nhan[:2])) == 2                          # chip của hai video khác nhau KHÔNG trùng


# ------------------------------------------------------------------ 4. không thử lại lỗi vĩnh viễn

def _loi_expected():
    return DownloadError("ERROR: boom", (ExtractorError, ExtractorError("boom", expected=True), None))


@pytest.mark.parametrize("loi", [
    _loi_expected,
    lambda: loi_tai("ERROR: [youtube] x: Video unavailable"),
    lambda: loi_tai("ERROR: [youtube] x: Requested format is not available. Use --list-formats"),
    lambda: loi_tai("ERROR: [youtube] x: The uploader has not made this video available in your country (geo restricted)"),
])
def test_loi_vinh_vien_tai_dung_mot_lan_khong_thu_lai(monkeypatch, tmp_path, loi):
    u = _yt(A)
    gia = YtdlpGia({u: thong_tin(A)}, {u: [None, loi(), loi(), loi()]})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([u]))
    assert gia.so_goi("tai") == 1 and job["loi"] == 1
    assert k.so_luot("youtube") == 2                       # 1 liệt kê + 1 tải
    assert k.nen_tang_tat() == {}


def test_loi_tam_thoi_van_thu_lai_ba_lan(monkeypatch, tmp_path):
    u = _yt(A)
    l403 = lambda: loi_tai("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    gia = YtdlpGia({u: thong_tin(A)}, {u: [None, l403(), l403(), l403()]})
    k = Khung(monkeypatch, tmp_path, gia)
    k.chay(k.tao_job([u]))
    assert gia.so_goi("tai") == 3


# ------------------------------------------------------------------ 5. cảnh báo cấu hình một lần

def test_ten_nen_tang_la_trong_cau_hinh_chi_canh_bao_mot_lan_moi_gia_tri(monkeypatch, caplog):
    monkeypatch.setattr(nguon_mod, "_DA_CANH_BAO_CAU_HINH", set())
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,youtub")
    with caplog.at_level("WARNING", logger="ttmd"):
        for _ in range(50):
            nguon_mod.nen_tang_bat()
        assert len(caplog.records) == 1
        monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktoc")
        nguon_mod.nen_tang_bat()
        nguon_mod.nen_tang_bat()
    assert len(caplog.records) == 2


# ------------------------------------------------------------------ 6. link YouTube từ Mix/playlist

@pytest.mark.parametrize("vao, ra", [
    (f"https://www.youtube.com/watch?v={A}&list=RD{A}&index=3&start_radio=1&pp=abc", _yt(A)),
    (f"https://www.youtube.com/watch?list=PLxyz&v={A}", _yt(A)),
    (f"https://youtu.be/{A}?list=PLxyz&t=5", f"https://youtu.be/{A}"),
    (f"https://www.youtube.com/shorts/{A}?list=PLxyz", f"https://www.youtube.com/shorts/{A}"),
    (f"https://m.youtube.com/watch?v={A}&list=PLxyz", _yt(A)),
    ("https://www.instagram.com/reel/Cabc123/?list=1", "https://www.instagram.com/reel/Cabc123/?list=1"),
    ("https://www.youtube.com/playlist?list=PLxyz", "https://www.youtube.com/playlist?list=PLxyz"),   # không có v=
])
def test_chuan_hoa_link_youtube(vao, ra):
    assert chuan_hoa_link(vao) == ra


def test_link_video_mo_tu_mix_duoc_nhan_dung_video_va_khong_tai_playlist(monkeypatch, tmp_path):
    mix = f"https://www.youtube.com/watch?v={A}&list=RD{A}&index=3"
    assert LinkLe().phan_loai(mix) == ("youtube", "yt-")
    assert LinkLe().phan_loai("https://www.youtube.com/playlist?list=PLxyz") is None
    assert LinkLe().phan_loai("https://www.youtube.com/watch?list=PLxyz") is None      # không có video nào
    gia = YtdlpGia({_yt(A): thong_tin(A)})
    k = Khung(monkeypatch, tmp_path, gia)
    job = k.chay(k.tao_job([mix]))
    assert job["xong"] == 1
    assert [u for _, u in gia.goi] == [_yt(A), _yt(A)]      # yt-dlp nhận link ĐÃ chuẩn hoá, không có `list=`
    assert all(o["noplaylist"] for o in gia.opts_da_tao)


# ------------------------------------------------------------------ mẫu che id chặt hơn

@pytest.mark.parametrize("vao, ra", [
    ("[download] Destination: /tmp/x.mp4", "[download] Destination: /tmp/x.mp4"),
    ("[youtube] Extracting URL: https://a", "[youtube] Extracting URL: <url>"),
    ("[info] Traceback: x", "[info] Traceback: x"),
    ("yt-dlp-ejs 0.3 x-forwarded-for: 1.2.3.4", "yt-dlp-ejs 0.3 x-forwarded-for: 1.2.3.4"),
    ("yt-dlp: bắt đầu", "yt-dlp: bắt đầu"),
    ("ERROR: [youtube] aAa1aAa1aAa: Video unavailable", "ERROR: [youtube] <id>: Video unavailable"),
    ("ERROR: [instagram] Cabc_1-xyz: x", "ERROR: [instagram] <id>: x"),
    ("✓ yt-aAa1aAa1aAa.mp4 snap-W7_EDlXW bili-BV1xx411c7mD", "✓ <id>.mp4 <id> <id>"),
])
def test_che_url_che_id_that_khong_che_tu_thuong(vao, ra):
    assert che_url(vao) == ra
