"""Cặp ảnh trước/sau + box vùng logo do `xu_ly_video` xuất (đợt 1b), và cột mới của nhật ký thêm idempotent vào DB cũ.
Video TỔNG HỢP (không dùng video bên thứ ba)."""
import json
import sqlite3

import pytest

cv2 = pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless")
import numpy as np  # noqa: E402
from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import nhat_ky, xu_ly_video  # noqa: E402
from tiktok_music_downloader.watermark import find_ffmpeg  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="không tìm thấy ffmpeg")


@pytest.fixture(scope="module")
def clip_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("ts")
    clip = tao_clip(n=40)
    p = d / "goc.mp4"
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (360, 640))
    for i in range(40):
        out.write(cv2.cvtColor(clip.nguon.doc(i), cv2.COLOR_GRAY2BGR))
    out.release()
    return clip, p


def _chay(clip, p, tmp_path, khung):
    conn = nhat_ky.mo(tmp_path / "log.db")
    kq = xu_ly_video.xu_ly(str(p), clip.box_moi(khung=khung), str(tmp_path / "ra.mp4"), conn, tmp_path / "f",
                           nguon_video="drive:x", ffmpeg=FFMPEG)
    v = dict(conn.execute("SELECT * FROM tl_video WHERE id=?", (kq["video_log_id"],)).fetchone())
    return kq, v


def test_render_xuat_cap_anh_cung_khung_va_box_dung_cho(clip_file, tmp_path):
    clip, p = clip_file
    kq, v = _chay(clip, p, tmp_path, (5, 12, 20, 28, 35))
    assert kq["trang_thai"] == "render"
    truoc, sau = cv2.imread(v["duong_dan_truoc"]), cv2.imread(v["duong_dan_sau"])
    assert truoc is not None and sau is not None and truoc.shape == sau.shape == (640, 360, 3)
    assert min(truoc.shape[:2]) <= xu_ly_video.CANH_NGAN_TOI_DA
    b = json.loads(v["box_logo"])
    assert set(b) == {"x", "y", "w", "h"} and all(0 <= b[k] <= 1 for k in b) and b["w"] > 0 and b["h"] > 0
    assert b["x"] + b["w"] <= 1 and b["y"] + b["h"] <= 1
    # Toạ độ phải đúng CHỖ (watermark thật trôi quanh x=60..120, y=420..440 của khung 360x640): đảo rộng/cao ⇒ lệch hẳn.
    assert 55 <= b["x"] * 360 <= 125 and 410 <= b["y"] * 640 <= 450
    # "Sau" khác "trước" trong vùng logo rõ hơn ngoài vùng (khung giữa đoạn đã được thay).
    x0, y0, x1, y1 = (int(b["x"] * 360), int(b["y"] * 640), int((b["x"] + b["w"]) * 360), int((b["y"] + b["h"]) * 640))
    chenh = np.abs(truoc.astype(int) - sau.astype(int)).mean(axis=2)
    trong = chenh[y0:y1, x0:x1].mean()
    mask = np.ones(chenh.shape, bool)
    mask[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8] = False
    assert trong > 3 * chenh[mask].mean() + 1, (trong, chenh[mask].mean())


def test_cho_nguoi_chi_co_anh_truoc_va_box_may_thay(clip_file, tmp_path):
    clip, p = clip_file
    kq, v = _chay(clip, p, tmp_path, (5,))
    assert kq["trang_thai"] == "cho_nguoi"
    assert cv2.imread(v["duong_dan_truoc"]) is not None and v["duong_dan_sau"] is None
    b = json.loads(v["box_logo"])  # box mồi duy nhất ở khung 5: x=65, y=420+1
    assert abs(b["x"] * 360 - 65) < 1 and abs(b["y"] * 640 - 421) < 1


def test_khong_co_box_thi_chi_anh_truoc_khung_giua_va_khong_box(clip_file, tmp_path):
    clip, p = clip_file
    kq = xu_ly_video.tao_cap_truoc_sau(str(p), None, {}, [], 40, tmp_path / "d")
    assert cv2.imread(kq["duong_dan_truoc"]) is not None and kq["duong_dan_sau"] is None and kq["box_logo"] is None


def test_anh_co_canh_ngan_toi_da_720(tmp_path):
    p = tmp_path / "to.mp4"
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (1280, 1920))
    for _ in range(4):
        out.write(np.full((1920, 1280, 3), 90, np.uint8))
    out.release()
    kq = xu_ly_video.tao_cap_truoc_sau(str(p), None, {}, [], 4, tmp_path / "d")
    assert cv2.imread(kq["duong_dan_truoc"]).shape[:2] == (1080, 720)


def test_loi_tao_anh_khong_lam_hong_video(clip_file, tmp_path, monkeypatch):
    clip, p = clip_file

    def hong(*a, **k):
        raise OSError("đĩa đầy")
    monkeypatch.setattr(xu_ly_video, "tao_cap_truoc_sau", hong)
    kq, v = _chay(clip, p, tmp_path, (5, 12, 20, 28, 35))
    assert kq["trang_thai"] == "render" and v["trang_thai"] == "render"
    assert v["duong_dan_truoc"] is None and v["duong_dan_sau"] is None and v["box_logo"] is None


def test_cot_moi_them_idempotent_vao_db_cu_giu_hang(tmp_path):
    db = tmp_path / "cu.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tl_video (id INTEGER PRIMARY KEY, job_id INTEGER, nguon_video TEXT NOT NULL, sha256_goc TEXT, kho TEXT, fps REAL,"
              " so_khung INTEGER, giay_video REAL, phien_ban TEXT NOT NULL, bat_dau REAL NOT NULL, ket_thuc REAL, giay_xu_ly REAL,"
              " rss_dinh_mb REAL, token_agy INTEGER, man_ket_agy INTEGER, cat_giay REAL NOT NULL DEFAULT 0, trang_thai TEXT, loi_text TEXT,"
              " duong_dan_track TEXT, duong_dan_sheet TEXT, drive_file_id_ra TEXT)")
    c.execute("INSERT INTO tl_video (nguon_video, phien_ban, bat_dau, trang_thai) VALUES ('x', 'p', 1.0, 'render')")
    c.commit()
    c.close()
    for _ in range(2):  # lần hai: cột đã có ⇒ không ném lỗi
        conn = nhat_ky.mo(db)
        cot = {r[1] for r in conn.execute("PRAGMA table_info(tl_video)")}
        assert {"duong_dan_truoc", "duong_dan_sau", "box_logo"} <= cot
        assert tuple(conn.execute("SELECT trang_thai, duong_dan_truoc, box_logo FROM tl_video").fetchone()) == ("render", None, None)
        conn.close()


def test_don_dep_go_duong_dan_anh_truoc_sau(clip_file, tmp_path):
    clip, p = clip_file
    kq, v = _chay(clip, p, tmp_path, (5, 12, 20, 28, 35))
    conn = nhat_ky.mo(tmp_path / "log.db")
    nhat_ky.don_dep(conn, tmp_path / "f", bay_gio=v["bat_dau"] + 61 * 86400)
    r = conn.execute("SELECT duong_dan_truoc, duong_dan_sau FROM tl_video WHERE id=?", (v["id"],)).fetchone()
    assert tuple(r) == (None, None) and not (tmp_path / "f" / str(v["id"])).exists()


def test_imwrite_that_bai_thi_khong_ghi_duong_dan_khong_de_nua_cap(clip_file, tmp_path, monkeypatch):
    """`cv2.imwrite` trả False (không ném lỗi): DB không được trỏ tới file không có."""
    clip, p = clip_file
    that = cv2.imwrite
    monkeypatch.setattr(xu_ly_video.cv2, "imwrite", lambda duong, *a, **k: False if duong.endswith("sau.jpg") else that(duong, *a, **k))
    kq, v = _chay(clip, p, tmp_path, (5, 12, 20, 28, 35))
    assert kq["trang_thai"] == "render"
    assert v["duong_dan_truoc"] is None and v["duong_dan_sau"] is None and v["box_logo"] is None
    assert not list((tmp_path / "f").rglob("truoc.jpg")) and not list((tmp_path / "f").rglob("sau.jpg"))
