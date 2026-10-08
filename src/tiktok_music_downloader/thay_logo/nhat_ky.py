"""Nhật ký quyết định từng video + đánh giá của member — dữ liệu để tune các vòng sau (USER 08/10 23:50, ĐP-1493/1494).

SQLite RIÊNG (không chung `jobs.db` ⇒ không đụng migration của Video Desk), mặc định `web/data/thay_logo_log.db` trên mini
(`deploy-to-mini.sh` loại `web/data` khỏi rsync ⇒ bền qua deploy). File nặng (track từng khung, ảnh soi) nằm cạnh DB, có trần
dung lượng; HÀNG DB không bao giờ xoá (nhỏ, là chuỗi thời gian để so phiên bản thuật toán).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

TRAN_FILE_BYTE = 1_000_000_000
NGAY_GIU_FILE, NGAY_GIU_FILE_HONG = 60, 180
LOAI_LOI = ("sot_watermark", "sai_cho", "che_phu_de", "pha_noi_dung", "khac")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_video (
  id INTEGER PRIMARY KEY, job_id INTEGER, nguon_video TEXT NOT NULL, sha256_goc TEXT, kho TEXT, fps REAL, so_khung INTEGER,
  giay_video REAL, phien_ban TEXT NOT NULL, bat_dau REAL NOT NULL, ket_thuc REAL, giay_xu_ly REAL, rss_dinh_mb REAL,
  token_agy INTEGER, man_ket_agy INTEGER, cat_giay REAL NOT NULL DEFAULT 0, trang_thai TEXT, loi_text TEXT,
  duong_dan_track TEXT, duong_dan_sheet TEXT, drive_file_id_ra TEXT);
CREATE TABLE IF NOT EXISTS tl_box_moi (
  video_id INTEGER NOT NULL REFERENCES tl_video(id), khung INTEGER, x INTEGER, y INTEGER, w INTEGER, h INTEGER,
  nguon TEXT NOT NULL CHECK (nguon IN ('agy', 'tay')), nhan_agy TEXT, cum INTEGER);
CREATE TABLE IF NOT EXISTS tl_vet (
  video_id INTEGER NOT NULL REFERENCES tl_video(id), vet INTEGER, trang_thai TEXT, box_cum INTEGER, ncc_moi REAL,
  tuong_phan_mau REAL, tu_hoc_tu_choi INTEGER, khop INTEGER, lech INTEGER, track_vang INTEGER, so_khung INTEGER,
  so_chac INTEGER, so_render INTEGER, so_predicted INTEGER, so_hidden INTEGER, chan_phu_de INTEGER, chan_tuong_phan INTEGER,
  chan_vanh INTEGER, chan_net_la INTEGER, net_la_pho_bien INTEGER, pct_render REAL, diem_c_p50 REAL, diem_c_p90 REAL, khung_loc_phu_de INTEGER);
CREATE TABLE IF NOT EXISTS tl_danh_gia (
  video_id INTEGER NOT NULL REFERENCES tl_video(id), member TEXT NOT NULL, ket_qua TEXT NOT NULL CHECK (ket_qua IN ('dat', 'hong')),
  loai_loi TEXT, ghi_chu TEXT, luc REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_tl_video_bat_dau ON tl_video(bat_dau);
CREATE INDEX IF NOT EXISTS ix_tl_danh_gia_video ON tl_danh_gia(video_id);
"""


def mo(duong_dan: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(duong_dan), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def phien_ban_thuat_toan() -> str:
    """Băm nội dung mọi file .py của lõi ⇒ đổi một hằng số là đổi phiên bản, không cần git trên máy chạy."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:12]


def sha256_file(duong_dan: str | Path) -> str:
    h = hashlib.sha256()
    with open(duong_dan, "rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


def bat_dau_video(conn, *, nguon_video: str, job_id: int | None = None, **truong) -> int:
    cot = {"nguon_video": nguon_video, "job_id": job_id, "phien_ban": phien_ban_thuat_toan(), "bat_dau": time.time(), **truong}
    cur = conn.execute(f"INSERT INTO tl_video ({','.join(cot)}) VALUES ({','.join('?' * len(cot))})", list(cot.values()))
    conn.commit()
    return cur.lastrowid


def cap_nhat_video(conn, video_id: int, **truong) -> None:
    if truong:
        conn.execute(f"UPDATE tl_video SET {','.join(f'{k}=?' for k in truong)} WHERE id=?", [*truong.values(), video_id])
        conn.commit()


def ghi_box_moi(conn, video_id: int, boxes, cum_cua: dict | None = None) -> None:
    conn.executemany("INSERT INTO tl_box_moi (video_id, khung, x, y, w, h, nguon, nhan_agy, cum) VALUES (?,?,?,?,?,?,?,?,?)",
                     [(video_id, b.khung, b.x, b.y, b.w, b.h, b.nguon, getattr(b, "nhan", None), (cum_cua or {}).get(b))
                      for b in boxes])
    conn.commit()


def _phan_vi(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def ghi_vet(conn, video_id: int, vet_so: int, v) -> None:
    """`v` là `duong_ong.KetQuaVet`. Mọi số đếm tính lại từ track để nhật ký không phụ thuộc trường tóm tắt."""
    tr = v.track
    dem = lambda s: sum(1 for e in tr if e.get("state") == s)  # noqa: E731
    diem = [e["diem_tot"] for e in tr if "diem_tot" in e and e["diem_tot"] > -1]
    hang = {
        "video_id": video_id, "vet": vet_so, "trang_thai": v.trang_thai, "box_cum": v.box_cum, "ncc_moi": v.ncc_moi,
        "tuong_phan_mau": v.tuong_phan_mau, "tu_hoc_tu_choi": v.tu_hoc_bi_tu_choi, "khop": v.khop.get("khop"),
        "lech": v.khop.get("lech"), "track_vang": v.khop.get("track_vang"), "so_khung": len(tr),
        "so_chac": dem("detected"), "so_render": len(v.khung_render), "so_predicted": dem("predicted"),
        "so_hidden": dem("hidden"), "chan_phu_de": dem("hidden_sub"), "chan_tuong_phan": dem("hidden_contrast"),
        "chan_vanh": dem("hidden_ring"), "chan_net_la": dem("hidden_net"),
        "net_la_pho_bien": int(getattr(v, "net_la_pho_bien", False)), "pct_render": v.pct_chac,
        "diem_c_p50": _phan_vi(diem, 0.5), "diem_c_p90": _phan_vi(diem, 0.9),
        "khung_loc_phu_de": sum(1 for e in tr if e.get("loc_pd")),
    }
    conn.execute(f"INSERT INTO tl_vet ({','.join(hang)}) VALUES ({','.join('?' * len(hang))})", list(hang.values()))
    conn.commit()


def ghi_danh_gia(conn, video_id: int, member: str, ket_qua: str, loai_loi: str | None = None, ghi_chu: str = "") -> None:
    """Nhiều lượt đánh giá/video được phép (giữ lịch sử). `hong` bắt buộc có loại lỗi — không có thì không tune được."""
    if ket_qua not in ("dat", "hong"):
        raise ValueError("ket_qua phải là 'dat' hoặc 'hong'")
    if ket_qua == "hong" and loai_loi not in LOAI_LOI:
        raise ValueError(f"đánh giá 'hong' cần loai_loi trong {LOAI_LOI}")
    conn.execute("INSERT INTO tl_danh_gia (video_id, member, ket_qua, loai_loi, ghi_chu, luc) VALUES (?,?,?,?,?,?)",
                 (video_id, member, ket_qua, loai_loi if ket_qua == "hong" else None, ghi_chu[:2000], time.time()))
    conn.commit()


def luu_track(thu_muc_goc: Path, video_id: int, cac_track: list[list[dict]]) -> str:
    d = Path(thu_muc_goc) / str(video_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "track.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(cac_track, f, separators=(",", ":"))
    return str(p)


def don_dep(conn, thu_muc_goc: Path, bay_gio: float | None = None, tran_byte: int = TRAN_FILE_BYTE) -> dict:
    """Xoá THƯ MỤC FILE theo tuổi rồi theo trần (cũ nhất trước); hàng DB giữ, chỉ xoá đường dẫn.
    Video có đánh giá MỚI NHẤT là `hong` giữ tới NGAY_GIU_FILE_HONG ngày — dữ liệu tune quý nhất — và chỉ bị xoá vì trần
    khi đã hết mọi video khác để xoá."""
    bay_gio = bay_gio or time.time()
    hang = conn.execute("""
        SELECT v.id, v.bat_dau,
               (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.id ORDER BY luc DESC LIMIT 1) AS danh_gia_cuoi
        FROM tl_video v WHERE v.duong_dan_track IS NOT NULL OR v.duong_dan_sheet IS NOT NULL ORDER BY v.bat_dau""").fetchall()

    def co(vid):
        d = Path(thu_muc_goc) / str(vid)
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.exists() else 0

    xoa, tong = [], {r["id"]: co(r["id"]) for r in hang}
    for r in hang:
        ngay = NGAY_GIU_FILE_HONG if r["danh_gia_cuoi"] == "hong" else NGAY_GIU_FILE
        if bay_gio - r["bat_dau"] > ngay * 86400:
            xoa.append(r["id"])
    con_lai = sum(b for k, b in tong.items() if k not in xoa)
    for uu_tien_hong in (False, True):
        for r in hang:
            if con_lai <= tran_byte:
                break
            if r["id"] in xoa or (r["danh_gia_cuoi"] == "hong") != uu_tien_hong:
                continue
            xoa.append(r["id"])
            con_lai -= tong[r["id"]]
    for vid in xoa:
        shutil.rmtree(Path(thu_muc_goc) / str(vid), ignore_errors=True)
        conn.execute("UPDATE tl_video SET duong_dan_track=NULL, duong_dan_sheet=NULL WHERE id=?", (vid,))
    conn.commit()
    return {"xoa": len(xoa), "byte_con_lai": con_lai}
