"""Dữ liệu và hợp đồng của chế độ tải ảnh: migration, id, ghi/đọc bài ảnh, định tuyến nguồn theo loại.

Mỗi tệp ảnh là một hàng `videos`; bài = các hàng cùng `bai_id`. Test canh: migration chỉ CỘNG và idempotent, bài
được ghi trọn K hàng hoặc không hàng nào, lưới video KHÔNG thấy ảnh, và `chon_nguon` thật sự dùng `loai`.
"""
from __future__ import annotations

import sqlite3

import pytest

from tiktok_music_downloader import nguon, tai_anh_cau_hinh as cfg
from tiktok_music_downloader.utils import VideoRef, che_url, parse_photo_url
from web import models, models_anh, vi_tu_con_song

CHU = "chu@dev.local"
KHAC = "khac@dev.local"


# ---------------------------------------------------------------- migration

def _dung_db_cu(path, so_job=3):
    """jobs.db đời trước chế độ ảnh: có `nen_tang` nhưng chưa có `loai_tai`; `videos` chưa có 4 cột ảnh."""
    with sqlite3.connect(path) as c:
        c.execute(models._SCHEMA)
        c.execute(models._VIDEOS_SCHEMA)
        for i in range(so_job):
            c.execute("INSERT INTO jobs (url, tao_luc) VALUES (?, '2026-01-01T00:00:00')", (f"u{i}",))
        c.execute("INSERT INTO videos (video_id, job_id, url, tao_luc) VALUES ('111', 1, 'u', '2026-01-01T00:00:00')")


def _cot(path, bang):
    with sqlite3.connect(path) as c:
        return [r[1] for r in c.execute(f"PRAGMA table_info({bang})")]


def test_init_db_hai_lan_tren_db_cu_lan_dau_sao_luu_va_them_cot_lan_hai_khong_sao_luu_them(tmp_path):
    path = tmp_path / "jobs.db"
    _dung_db_cu(path)
    assert "loai_tai" not in _cot(path, "jobs")

    models.init_db(path)

    ban_sao = list(tmp_path.glob("jobs.db.truoc-tai-anh-*"))
    assert len(ban_sao) == 1
    # Bản sao là DB cũ NGUYÊN VẸN: chưa có cột mới.
    assert "loai_tai" not in _cot(ban_sao[0], "jobs") and "loai" not in _cot(ban_sao[0], "videos")
    assert "loai_tai" in _cot(path, "jobs")
    assert {"loai", "bai_id", "thu_tu", "bai_thu_muc_id"} <= set(_cot(path, "videos"))
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE loai_tai = 'video'").fetchone()[0] == 3
        assert c.execute("SELECT loai, bai_id, thu_tu FROM videos").fetchall() == [("video", None, None)]
        chi_muc = {r[1] for r in c.execute("PRAGMA index_list(videos)")}
    assert "idx_videos_bai_id" in chi_muc

    models.init_db(path)
    assert list(tmp_path.glob("jobs.db.truoc-tai-anh-*")) == ban_sao, "lần hai không được sao lưu thêm"
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3


def test_db_moi_khong_sinh_ban_sao_tai_anh(tmp_path):
    path = tmp_path / "jobs.db"
    models.init_db(path)
    models.init_db(path)
    assert list(tmp_path.glob("jobs.db.truoc-tai-anh-*")) == []


def test_create_job_tham_so_cuoi_loai_tai_mac_dinh_video(tmp_path):
    path = tmp_path / "jobs.db"
    models.init_db(path)
    mac_dinh = models.create_job(path, "https://www.tiktok.com/tag/x", 5, CHU)
    anh = models.create_job(path, "https://www.tiktok.com/tag/x", 5, CHU, loai_tai=cfg.LOAI_ANH)
    assert models.get_job(path, mac_dinh)["loai_tai"] == "video"
    assert models.get_job(path, anh)["loai_tai"] == "anh"


# ---------------------------------------------------------------- id + hằng

def test_ten_hang_hop_dong_dong_bang():
    assert (cfg.LOAI_VIDEO, cfg.LOAI_ANH, cfg.LOAI_CA_HAI) == ("video", "anh", "ca_hai")
    assert cfg.ENV_TAI_ANH_BAT == "VIDEODL_TAI_ANH_BAT"
    assert cfg.TRAN_ANH_MOI_BAI == 50 and cfg.BYTE_TOI_THIEU >= 1
    assert vi_tu_con_song.LA_VIDEO == "v.loai = 'video'" and vi_tu_con_song.LA_ANH == "v.loai = 'anh'"


def test_co_tai_anh_doc_luc_goi_mac_dinh_tat(monkeypatch):
    monkeypatch.delenv(cfg.ENV_TAI_ANH_BAT, raising=False)
    assert cfg.tai_anh_dang_bat() is False
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "1")
    assert cfg.tai_anh_dang_bat() is True
    monkeypatch.setenv(cfg.ENV_TAI_ANH_BAT, "0")
    assert cfg.tai_anh_dang_bat() is False


def test_id_bai_va_id_tep():
    assert cfg.bai_id_anh("tt", "7123") == "anh-tt-7123"
    assert cfg.bai_id_anh("ig", "Cx_-9Ab") == "anh-ig-Cx_-9Ab"
    assert cfg.bai_id_anh("fbp", "99") == "anh-fbp-99"
    assert cfg.file_id_anh("anh-tt-7123", 1) == "anh-tt-7123-01"
    assert cfg.file_id_anh("anh-tt-7123", 35) == "anh-tt-7123-35"
    for sai in (("yt", "x"), ("tt", ""), ("tt", "a/b"), ("tt", "a" * 80)):
        with pytest.raises(ValueError):
            cfg.bai_id_anh(*sai)
    for sai in (("anh-tt-1", 0), ("anh-tt-1", 100), ("tt-1", 1), ("anh-tt-1", True)):
        with pytest.raises(ValueError):
            cfg.file_id_anh(*sai)


def test_video_ref_them_truong_co_mac_dinh_khong_doi_hop_dong_cu():
    ref = VideoRef(video_id="1", url="u")
    assert (ref.loai, ref.anh_urls, ref.anh_kieu) == ("video", (), ())
    assert ref.filename == "1.mp4"
    anh = VideoRef(video_id="anh-tt-1", url="u", loai="anh", anh_urls=(("a1", "a2"), ("b1",)), anh_kieu=("anh", "video"))
    assert anh.filename == "anh-tt-1.mp4"
    assert len(anh.anh_urls) == len(anh.anh_kieu) == 2


def test_parse_photo_url():
    assert parse_photo_url("https://www.tiktok.com/@nguoi.dung/photo/7123456789012345678") == "7123456789012345678"
    assert parse_photo_url("  https://tiktok.com/@a/photo/9?x=1") == "9"
    assert parse_photo_url("https://www.tiktok.com/@a/video/9") is None
    assert parse_photo_url("https://www.instagram.com/p/abc/") is None


def test_che_id_log_che_id_anh_facebook_va_instagram_giu_id_tiktok():
    ra = che_url("tệp anh-fbp-123456789012 và anh-ig-Cx9AbZ12 lỗi")
    assert "123456789012" not in ra and "Cx9AbZ12" not in ra
    assert "anh-tt-7123456789" in che_url("anh-tt-7123456789 lỗi"), "id TikTok giữ nguyên có chủ đích"


# ---------------------------------------------------------------- ghi / đọc bài ảnh

@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, CHU, loai_tai="anh")
    job_khac = models.create_job(db, "https://www.tiktok.com/tag/y", 5, KHAC, loai_tai="anh")
    return db, job, job_khac


def _hang(job, bai_id, k, **them):
    return [{"video_id": cfg.file_id_anh(bai_id, i), "job_id": job, "url": "https://www.tiktok.com/@a/photo/1",
             "bai_id": bai_id, "thu_tu": i, "bai_thu_muc_id": "thuc-muc", "drive_file_id": f"drv-{bai_id}-{i}",
             "title": "tiêu đề", **them} for i in range(1, k + 1)]


def _dem(db, dieu_kien="1=1"):
    with sqlite3.connect(db) as c:
        return c.execute(f"SELECT COUNT(*) FROM videos WHERE {dieu_kien}").fetchone()[0]


def test_ghi_bai_anh_ghi_du_k_hang_loai_anh(kho):
    db, job, _ = kho
    assert models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 4)) == 4
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM videos ORDER BY thu_tu").fetchall()
    assert [r["video_id"] for r in rows] == [f"anh-tt-100-0{i}" for i in range(1, 5)]
    assert {r["loai"] for r in rows} == {"anh"} and {r["bai_id"] for r in rows} == {"anh-tt-100"}
    assert [r["thu_tu"] for r in rows] == [1, 2, 3, 4]
    assert rows[0]["drive_file_id"] == "drv-anh-tt-100-1" and rows[0]["bai_thu_muc_id"] == "thuc-muc"


def test_ghi_bai_anh_la_mot_giao_dich_loi_giua_chung_khong_de_lai_hang_nao(kho):
    db, job, _ = kho
    with sqlite3.connect(db) as c:    # ép hàng thứ 3 hỏng ở TẦNG DB (sau khi 2 hàng đầu đã vào giao dịch)
        c.execute("CREATE TRIGGER hong BEFORE INSERT ON videos WHEN NEW.thu_tu = 3 "
                  "BEGIN SELECT RAISE(ABORT, 'hong'); END")
    with pytest.raises(sqlite3.DatabaseError):
        models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 4))
    assert _dem(db) == 0


def test_ghi_bai_anh_nhan_ca_ket_noi_va_chay_lai_khong_ghi_de(kho):
    db, job, _ = kho
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 2, title="lần đầu"))
    with models._connect(db) as conn:
        assert models_anh.ghi_bai_anh(conn, _hang(job, "anh-tt-100", 2, title="lần hai")) == 0
    with sqlite3.connect(db) as c:
        assert {r[0] for r in c.execute("SELECT title FROM videos")} == {"lần đầu"}


@pytest.mark.parametrize("sua", [
    lambda h: [],                                             # không tệp nào
    lambda h: h[:1] + [{**h[1], "thu_tu": 1}],                # trùng thu_tu
    lambda h: [h[0], {**h[1], "thu_tu": 3, "video_id": "anh-tt-100-03"}],   # hổng thu_tu (1, 3)
    lambda h: [h[0], {**h[1], "video_id": "anh-tt-100-09"}],  # video_id không khớp bai_id + thu_tu
    lambda h: [h[0], {**h[1], "bai_id": "anh-tt-200"}],       # hai bài trong một lượt ghi
    lambda h: [{**h[0], "cot_la": 1}, h[1]],                  # cột lạ
])
def test_ghi_bai_anh_tu_choi_bai_sai_hinh_truoc_khi_cham_db(kho, sua):
    db, job, _ = kho
    with pytest.raises(ValueError):
        models_anh.ghi_bai_anh(db, sua(_hang(job, "anh-tt-100", 2)))
    assert _dem(db) == 0


def test_bai_anh_khong_lot_vao_luoi_video_va_video_khong_lot_vao_luoi_anh(kho):
    db, job, _ = kho
    models.record_video(db, job, "555", "https://www.tiktok.com/@a/video/555")
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 3))

    assert [v["video_id"] for v in models.list_videos(db, None)] == ["555"]
    assert models.count_videos(db, None) == 1
    assert [v["video_id"] for v in models.list_videos(db, None, loai="anh")] == [f"anh-tt-100-0{i}" for i in (3, 2, 1)]
    assert models.count_videos(db, None, loai="anh") == 3
    assert [b["bai_id"] for b in models_anh.list_bai_anh(db, None)] == ["anh-tt-100"]
    with pytest.raises(ValueError):
        models.list_videos(db, None, loai="ca_hai")


def test_known_video_ids_nhan_ra_bai_anh_qua_bai_id(kho):
    db, job, _ = kho
    models.record_video(db, job, "555", "u")
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 2))
    assert models.known_video_ids(db, ["555", "anh-tt-100", "anh-tt-999", "anh-tt-100-01"]) == {
        "555", "anh-tt-100", "anh-tt-100-01"}
    assert models.known_video_ids(db, []) == set()


def test_list_bai_anh_gom_theo_bai_thu_tu_va_hinh_hang(kho):
    db, job, _ = kho
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 3, tao_luc="2026-01-01T00:00:01"))
    models_anh.ghi_bai_anh(db, _hang(job, "anh-ig-AbC123", 2, tao_luc="2026-01-01T00:00:09"))

    bai = models_anh.list_bai_anh(db, None)

    assert [b["bai_id"] for b in bai] == ["anh-ig-AbC123", "anh-tt-100"], "mới nhất trước"
    b = bai[1]
    assert b["thumb_id"] == "anh-tt-100-01"
    assert b["file_ids"] == ["anh-tt-100-01", "anh-tt-100-02", "anh-tt-100-03"] and b["so_anh"] == 3
    f = b["files"][0]
    # Cùng hình một video của `GET /videos` (`v.*` + `nguoi_tao`) để client dùng lại bộ lọc/bàn giao.
    assert {"video_id", "drive_file_id", "title", "url", "da_loai_luc", "tao_luc", "nguoi_tao"} <= set(f)
    assert f["nguoi_tao"] == CHU and f["drive_file_id"] == "drv-anh-tt-100-1"
    assert models_anh.count_bai_anh(db, None) == 2


def test_list_bai_anh_loc_o_muc_tep_roi_moi_gom(kho):
    """Bỏ một tệp ⇒ bài còn lại tệp kia; bỏ hết ⇒ bài biến mất; `count` luôn khớp `list`."""
    db, job, _ = kho
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 3))
    models.danh_dau_da_loai(db, "anh-tt-100-02", CHU)

    (b,) = models_anh.list_bai_anh(db, None)
    assert b["file_ids"] == ["anh-tt-100-01", "anh-tt-100-03"] and b["so_anh"] == 2
    assert b["thumb_id"] == "anh-tt-100-01"
    for ma in ("anh-tt-100-01", "anh-tt-100-03"):
        models.danh_dau_da_loai(db, ma, CHU)
    assert models_anh.list_bai_anh(db, None) == [] and models_anh.count_bai_anh(db, None) == 0


def test_list_bai_anh_chi_cua_chu_job_va_admin_thay_het(kho):
    db, job, job_khac = kho
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 2))
    models_anh.ghi_bai_anh(db, _hang(job_khac, "anh-tt-200", 2))

    assert [b["bai_id"] for b in models_anh.list_bai_anh(db, CHU)] == ["anh-tt-100"]
    assert models_anh.count_bai_anh(db, CHU) == 1
    assert {b["bai_id"] for b in models_anh.list_bai_anh(db, None)} == {"anh-tt-100", "anh-tt-200"}


def test_list_bai_anh_phan_trang_dem_bai_khong_dem_tep(kho):
    db, job, _ = kho
    for i in range(3):
        models_anh.ghi_bai_anh(db, _hang(job, f"anh-tt-{i}", 4, tao_luc=f"2026-01-01T00:00:0{i}"))
    assert [b["bai_id"] for b in models_anh.list_bai_anh(db, None, limit=2)] == ["anh-tt-2", "anh-tt-1"]
    assert [b["bai_id"] for b in models_anh.list_bai_anh(db, None, limit=2, offset=2)] == ["anh-tt-0"]
    assert models_anh.count_bai_anh(db, None) == 3


def test_chip_vao_bo_loc_o_muc_tep(kho):
    from web import models_vao_bo as vb
    db, job, _ = kho
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-100", 2))
    models_anh.ghi_bai_anh(db, _hang(job, "anh-tt-200", 2))
    with models._connect(db) as conn:     # tệp 01 của bài 100 đã vào bộ (ẩn); bài 200 chưa
        conn.execute("INSERT INTO video_vao_bo (video_id, an_luc) VALUES ('anh-tt-100-01', '2026-01-02T00:00:00')")
    assert vb  # module import được cùng bảng

    chua = models_anh.list_bai_anh(db, None, vao_bo=False)
    assert {b["bai_id"]: b["file_ids"] for b in chua} == {"anh-tt-100": ["anh-tt-100-02"],
                                                          "anh-tt-200": ["anh-tt-200-01", "anh-tt-200-02"]}
    roi = models_anh.list_bai_anh(db, None, vao_bo=True)
    assert [(b["bai_id"], b["file_ids"]) for b in roi] == [("anh-tt-100", ["anh-tt-100-01"])]
    assert models_anh.count_bai_anh(db, None, vao_bo=False) == 2 and models_anh.count_bai_anh(db, None, vao_bo=True) == 1


# ---------------------------------------------------------------- chon_nguon theo loại

TT_MUSIC = "https://www.tiktok.com/music/nhac-123456"
TT_VIDEO = "https://www.tiktok.com/@u/video/7123456789012345678"
TT_PHOTO = "https://www.tiktok.com/@u/photo/7123456789012345678"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT_KENH = "https://www.youtube.com/@kenh/videos"
ADS = "https://www.facebook.com/ads/library/?active_status=all&q=abc"
DRIVE = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
IG_PROFILE = "https://www.instagram.com/nguoi.dung/"
IG_REELS = "https://www.instagram.com/nguoi.dung/reels/"
IG_AUDIO = "https://www.instagram.com/reels/audio/123456789/"
IG_TAG = "https://www.instagram.com/explore/tags/mau/"
IG_BAI = "https://www.instagram.com/p/Cx9AbZ12/"
IG_REEL = "https://www.instagram.com/reel/Cx9AbZ12/"
FB_TRANG = "https://www.facebook.com/trang.nao"
FB_VIDEOS = "https://www.facebook.com/trang.nao/videos"
LOAI = ("video", "anh", "ca_hai")


def _ho_tro(url):
    return {loai for loai in LOAI if nguon.chon_nguon(url, loai) is not None}


def test_chon_nguon_khong_tham_so_y_nhu_truoc_va_tuong_duong_loai_video():
    for url in (TT_MUSIC, TT_VIDEO, YT, YT_KENH, ADS, DRIVE, IG_PROFILE, IG_REELS, IG_AUDIO, IG_BAI, IG_REEL,
                FB_TRANG, FB_VIDEOS, TT_PHOTO, "https://example.com/x"):
        assert nguon.chon_nguon(url) is nguon.chon_nguon(url, "video"), url
    assert nguon.chon_nguon(TT_PHOTO) is None, "link ảnh TikTok không được nhận khi không xin ảnh"
    assert isinstance(nguon.chon_nguon(TT_VIDEO), nguon.LinkLe)


def test_chon_nguon_dung_loai_that_su_nguon_chi_video_tu_choi_anh_va_ca_hai():
    """ĐỘT BIẾN (phải ĐỎ khi áp, XANH khi hoàn nguyên): `chon_nguon` bỏ qua loại, nhận mọi link bất kể loại xin.
    Áp: `python3 -c "import pathlib; p = pathlib.Path('src/tiktok_music_downloader/nguon.py'); p.write_text(p.read_text().replace('return n if loai in loai_ho_tro_cua(n, url) else None', 'return n'))"`
    Hoàn nguyên: cùng lệnh với hai chuỗi đảo chỗ (hoặc `git diff` rồi sửa tay dòng đó)."""
    for url in (YT, YT_KENH, ADS, DRIVE, IG_REELS, IG_AUDIO, IG_REEL, FB_VIDEOS):
        assert _ho_tro(url) == {"video"}, url


def test_chon_nguon_nguon_hai_loai_nhan_dung_loai():
    assert _ho_tro(TT_MUSIC) == set(LOAI)
    assert _ho_tro(TT_VIDEO) == set(LOAI)
    assert _ho_tro(IG_PROFILE) == set(LOAI) and _ho_tro(IG_TAG) == set(LOAI) and _ho_tro(IG_BAI) == set(LOAI)
    # Link ảnh TikTok: chỉ khi xin ảnh/cả hai.
    assert _ho_tro(TT_PHOTO) == {"anh", "ca_hai"}
    # Facebook page: một lượt một tab — KHÔNG có "cả hai".
    assert _ho_tro(FB_TRANG) == {"video", "anh"}


def test_chon_nguon_tra_dung_lop_nguon_theo_loai():
    assert isinstance(nguon.chon_nguon(TT_MUSIC, "anh"), nguon.TikTokCollection)
    assert isinstance(nguon.chon_nguon(TT_PHOTO, "anh"), nguon.LinkLe)
    assert nguon.chon_nguon(TT_PHOTO, "anh").nen_tang(TT_PHOTO) == "tiktok"
    assert nguon.chon_nguon(TT_PHOTO, "video") is None
    assert nguon.chon_nguon(YT, "anh") is None


def test_chon_nguon_loai_la_nem_loi_va_chon_nguon_moi_loai_phan_biet_ly_do():
    with pytest.raises(ValueError):
        nguon.chon_nguon(TT_MUSIC, "gif")
    assert nguon.chon_nguon(YT, "anh") is None and nguon.chon_nguon_moi_loai(YT) is not None
    assert nguon.chon_nguon_moi_loai("https://example.com/x") is None


def test_link_le_phan_loai_anh_chi_khi_xin_anh():
    le = nguon.LinkLe()
    assert le.phan_loai(TT_PHOTO) is None and le.phan_loai(TT_PHOTO, "video") is None
    assert le.phan_loai(TT_PHOTO, "anh") == ("tiktok", "")
    assert le.phan_loai(TT_VIDEO) == ("tiktok", "") == le.phan_loai(TT_VIDEO, "anh")


def _liet_ke_le(url, loai, da_co=(), **them):
    hoi, bo = [], []
    ket = nguon.LinkLe().liet_ke(url, max_videos=5, already_have=lambda ids: hoi.append(list(ids)) or set(da_co) & set(ids),
                                 on_skip=bo.append, on_stop=lambda ly_do: None, loai=loai, **them)
    return ket, hoi, bo


def test_link_le_che_do_anh_loc_bai_da_co_theo_bai_id_truoc_khi_goi_mang():
    # Mọi bài đã có ⇒ KHÔNG chạm điểm liệt kê mạng (nếu chạm sẽ NotImplementedError).
    ket, hoi, bo = _liet_ke_le(f"{TT_PHOTO}\n{IG_BAI}", "anh",
                               da_co={"anh-tt-7123456789012345678", "anh-ig-Cx9AbZ12"}, cookies_path="/khong/can")
    assert ket == []
    assert hoi[0] == ["anh-tt-7123456789012345678", "anh-ig-Cx9AbZ12"]
    assert [r.video_id for r in bo] == ["anh-tt-7123456789012345678", "anh-ig-Cx9AbZ12"]


def test_link_le_che_do_anh_bai_chua_co_thi_chua_cai_trinh_liet_ke_nem_ro_rang_khong_tra_video():
    with pytest.raises(NotImplementedError):
        _liet_ke_le(TT_VIDEO, "anh")
    with pytest.raises(NotImplementedError):
        _liet_ke_le(TT_PHOTO, "ca_hai")


def test_link_le_nhan_cookies_path_va_loai_khong_nuot_vao_tham_so_thua():
    import inspect
    tham_so = inspect.signature(nguon.LinkLe.liet_ke).parameters
    assert "cookies_path" in tham_so and tham_so["loai"].default == "video"


def test_tiktok_collection_nhan_loai_keyword_mac_dinh_video_va_khong_im_lang_tra_video(monkeypatch):
    import inspect
    assert inspect.signature(nguon.TikTokCollection.liet_ke).parameters["loai"].default == "video"
    goi = []
    monkeypatch.setattr(nguon, "scrape_music_page_multi", lambda *a, **kw: goi.append(kw) or [])
    kw = dict(max_videos=1, proxy=None, cookies_path=None, already_have=lambda ids: set(), on_skip=lambda r: None,
              on_stop=lambda ly_do: None, on_pages=lambda n: None, dem_trang=lambda: None, passes=1,
              max_seconds=None, kw_profile={})
    nguon.TikTokCollection().liet_ke(TT_MUSIC, **kw)
    assert "loai" not in goi[0], "loại video: gọi trình quét y hệt trước"
    # Trình quét chưa biết `loai` ⇒ lỗi RÕ, không trả video.
    with pytest.raises(NotImplementedError):
        nguon.TikTokCollection().liet_ke(TT_MUSIC, loai="anh", **kw)
    # Trình quét biết `loai` ⇒ nhận được đúng giá trị.
    monkeypatch.setattr(nguon, "scrape_music_page_multi", lambda *a, loai="video", **kw: goi.append(loai) or [])
    nguon.TikTokCollection().liet_ke(TT_MUSIC, loai="ca_hai", **kw)
    assert goi[-1] == "ca_hai"
