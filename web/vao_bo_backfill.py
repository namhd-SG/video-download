"""Backfill MỘT LẦN "đã vào bộ" cho video vào bộ TRƯỚC khi Creative Desk gắn dấu nguồn.

Bằng chứng = bằng chứng của bộ kiểm định kỳ TRỪ vế `properties`: có file khác trên
cùng Shared Drive trùng `md5Checksum` + `size`, chưa vào thùng rác, folder cha khác
folder nguồn, id khác id nguồn (`vao_bo_drive.ban_hop_le(..., can_dau_nguon=False)`).
Thêm hai lưới an toàn đã đo ở kiểm chéo 29/09 (0 ca lúc đó, nhưng là hai cách một
video bị ẩn oan):
  * bản "sao" chính là tệp nguồn của một video Video Desk khác (hai video trùng nội
    dung sẽ tự chứng minh cho nhau);
  * bản "sao" nằm trong folder đang chứa tệp nguồn Video Desk.

MẶC ĐỊNH DRY-RUN: chỉ đọc, in bảng số đo. Ghi CHỈ khi `that=True`, với
`bang_chung='md5_backfill'` (khác `'properties'` để phân biệt về sau). Đồng hồ 7 ngày
tính từ lúc ghi. Chạy lần hai ghi 0 hàng: video đã ẩn không còn là ứng viên.

Đọc Drive xong TOÀN BỘ (kể cả tên folder) rồi mới ghi: lỗi Drive giữa chừng ⇒ ném,
chưa ghi gì.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from web import models_vao_bo
from web.models import _connect
from web.vao_bo_drive import (DriveVaoBo, ban_hop_le, chon_folder, doc_het_trang,
                              ma_bo_tu_ten, KHOA_DAU_NGUON)
from web.vi_tu_con_song import CON_SONG_CHUNG


class ThieuBang(RuntimeError):
    """DB không mở được ở chế độ chỉ-đọc, hoặc chưa có bảng cần (`videos`,
    `video_vao_bo`) — dry-run KHÔNG tự dựng lược đồ, nên nói thẳng thay vì đoán."""


@contextmanager
def _ket_noi_doc_chi(db_path: Path):
    """Mở DB `mode=ro`: không tạo tệp, không ghi WAL, không `init_db`. Ném `ThieuBang`
    (thông điệp sạch) nếu tệp/bảng không có."""
    if not db_path.is_file():
        raise ThieuBang(f"không thấy tệp DB: {db_path}")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise ThieuBang(f"không mở được DB chỉ-đọc: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        co = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('videos', 'video_vao_bo')")}
        thieu = {"videos", "video_vao_bo"} - co
        if thieu:
            raise ThieuBang(f"DB chưa có bảng {sorted(thieu)} — chạy ứng dụng (init_db) trước")
        yield conn
    except sqlite3.OperationalError as exc:
        raise ThieuBang(f"đọc DB trượt: {exc}") from exc
    finally:
        conn.close()


@dataclass
class BaoCaoBackfill:
    so_song_co_drive: int = 0          # mọi video còn sống có drive_file_id
    da_an_tu_truoc: int = 0            # trong đó đã ẩn (không xét lại)
    nguon_ok: int = 0
    nguon_loi: int = 0
    nguon_phu_loi: int = 0             # nguồn KHÔNG phải ứng viên mà không lấy được folder cha
    so_folder_nguon: int = 0           # folder cha của MỌI nguồn Video Desk đã biết
    so_shared_drive: int = 0
    so_file_video: int = 0
    so_co_dau: int = 0
    se_danh_dau: list = field(default_factory=list)     # [{video_id, chu, nguon, ban:[...]}]
    bo_vi_duong_gia: int = 0
    tien_to_folder: dict = field(default_factory=dict)
    so_folder_cha: int = 0
    ten_folder: dict = field(default_factory=dict)
    mau: list = field(default_factory=list)
    da_ghi: int = 0
    that: bool = False


def _video_song(db_path: Path, chi_doc: bool) -> tuple[list[dict], set[str]]:
    """(mọi video còn sống có drive_file_id, mọi drive_file_id kể cả đã ẩn/loại/dọn).
    `chi_doc`: mở DB `mode=ro` (dry-run) thay vì kết nối thường."""
    cm = _ket_noi_doc_chi(db_path) if chi_doc else _connect(db_path)
    with cm as conn:
        rows = conn.execute(
            "SELECT v.video_id, v.drive_file_id, j.nguoi_tao AS chu, "
            "EXISTS (SELECT 1 FROM video_vao_bo b WHERE b.video_id = v.video_id "
            "        AND b.an_luc IS NOT NULL) AS da_an "
            "FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.drive_file_id IS NOT NULL AND {CON_SONG_CHUNG} "
            "ORDER BY v.tao_luc DESC, v.video_id DESC").fetchall()
        moi_nguon = {r[0] for r in conn.execute(
            "SELECT drive_file_id FROM videos WHERE drive_file_id IS NOT NULL")}
    return [dict(r) for r in rows], moi_nguon


def chay_backfill(db_path: Path, drive: DriveVaoBo, *, that: bool = False,
                  luc: str | None = None) -> BaoCaoBackfill:
    bc = BaoCaoBackfill(that=that)
    song, moi_nguon_id = _video_song(db_path, chi_doc=not that)
    bc.so_song_co_drive = len(song)
    ung_vien = [v for v in song if not v["da_an"]]
    bc.da_an_tu_truoc = len(song) - len(ung_vien)

    nguon: dict[str, dict] = {}
    for v in ung_vien:
        try:
            nguon[v["video_id"]] = drive.lay_tep(v["drive_file_id"])
        except Exception:  # noqa: BLE001 — chỉ đếm, như bản dry-run
            bc.nguon_loi += 1
    bc.nguon_ok = len(nguon)

    drive_ids = sorted({n["driveId"] for n in nguon.values() if n.get("driveId")})
    bc.so_shared_drive = len(drive_ids)
    tat_ca: list[dict] = []
    for did in drive_ids:
        tat_ca += doc_het_trang(lambda t, did=did: drive.liet_ke_video_shared_drive(did, t))
    bc.so_file_video = len(tat_ca)
    bc.so_co_dau = sum(1 for f in tat_ca if (f.get("properties") or {}).get(KHOA_DAU_NGUON))

    theo_khoa: dict[tuple, list[dict]] = defaultdict(list)
    for f in tat_ca:
        if f.get("md5Checksum") and f.get("size"):
            theo_khoa[(f["md5Checksum"], f["size"])].append(f)
    # Folder cha của MỌI nguồn Video Desk — không chỉ của ứng viên đang xét. Một bản "sao"
    # nằm trong folder đang chứa nguồn của video đã ẩn / đã loại / lấy-trượt vẫn là dương
    # giả. Nguồn không phải ứng viên: lấy siêu dữ liệu để biết folder (Thùng rác vẫn trả
    # `parents`); không lấy được thì chỉ còn lưới theo id (`moi_nguon_id`) che cho nó.
    cha_cua_nguon = {p for n in nguon.values() for p in (n.get("parents") or [])}
    da_thu = {v["drive_file_id"] for v in ung_vien}
    for fid in sorted(moi_nguon_id - da_thu):
        try:
            cha_cua_nguon.update(drive.lay_tep(fid).get("parents") or [])
        except Exception:  # noqa: BLE001
            bc.nguon_phu_loi += 1
    bc.so_folder_nguon = len(cha_cua_nguon)

    cha_ban_sao: set[str] = set()
    for v in ung_vien:
        src = nguon.get(v["video_id"])
        if src is None or src.get("trashed"):
            continue
        ban = []
        for f in theo_khoa.get((src.get("md5Checksum"), src.get("size")), []):
            if not ban_hop_le(src["id"], src, f, can_dau_nguon=False):
                continue
            if f["id"] in moi_nguon_id or set(f.get("parents") or []) & cha_cua_nguon:
                bc.bo_vi_duong_gia += 1
                continue
            ban.append(f)
        if not ban:
            continue
        bc.se_danh_dau.append({"video_id": v["video_id"], "chu": v["chu"], "nguon": src,
                               "ban": ban})
        for f in ban:
            cha_ban_sao.update(f.get("parents") or [])
        if len(bc.mau) < 10:
            bc.mau.append((v["video_id"], src["id"][:8], len(ban),
                           [p[:8] for p in ban[0].get("parents") or []],
                           bool((ban[0].get("properties") or {}).get(KHOA_DAU_NGUON))))
    bc.so_folder_cha = len(cha_ban_sao)

    # Tên MỌI folder cha (cần để ghi `ma_bo`). Dry-run chịu "?" như bản script; ghi
    # thật thì trượt là ném — không ghi một `ma_bo` sai/thiếu vĩnh viễn.
    for pid in sorted(cha_ban_sao):
        try:
            bc.ten_folder[pid] = drive.ten_thu_muc(pid)
        except Exception:
            if that:
                raise
            bc.ten_folder[pid] = "?"
    tien_to: dict[str, int] = defaultdict(int)
    for pid in sorted(cha_ban_sao)[:40]:
        tien_to[bc.ten_folder[pid].split(".")[0][:3]] += 1
    bc.tien_to_folder = dict(tien_to)

    if that:
        for m in bc.se_danh_dau:
            dong = []
            for f in m["ban"]:
                folder = chon_folder(f, m["nguon"])
                if folder is not None:
                    dong.append({"ban_copy_id": f["id"], "folder_id": folder,
                                 "ma_bo": ma_bo_tu_ten(bc.ten_folder[folder]),
                                 "bang_chung": "md5_backfill"})
            if dong and models_vao_bo.ghi_da_vao_bo(db_path, m["video_id"], m["chu"], dong, luc):
                bc.da_ghi += 1
    return bc


def in_bang(bc: BaoCaoBackfill) -> list[str]:
    """Bảng số đo — CÙNG chữ với `dry-run-backfill-md5.py` để so hai bản với nhau."""
    dong = [
        f"video còn sống có drive_file_id: {bc.so_song_co_drive}",
        f"đã ẩn từ trước (không xét lại): {bc.da_an_tu_truoc}",
        f"files.get nguồn OK: {bc.nguon_ok} · lỗi: {bc.nguon_loi}",
        f"folder cha của MỌI nguồn Video Desk: {bc.so_folder_nguon} "
        f"(nguồn ngoài ứng viên không lấy được: {bc.nguon_phu_loi})",
        f"số Shared Drive chứa nguồn: {bc.so_shared_drive}",
        f"file video (chưa trash) trên Shared Drive: {bc.so_file_video}",
        f"file mang dấu properties.videodesk_src: {bc.so_co_dau}",
        f"SẼ ĐÁNH DẤU (dry-run): {len(bc.se_danh_dau)} / {bc.nguon_ok} video nguồn",
        f"bỏ vì bản sao là nguồn Video Desk khác / nằm trong folder nguồn: {bc.bo_vi_duong_gia}",
        f"số folder cha khác nhau của bản sao: {bc.so_folder_cha}",
        f"tiền tố tên folder cha (≤40 folder đầu): {bc.tien_to_folder}",
        "10 mẫu (video_id, nguồn[:8], số bản sao, cha bản sao[:8], bản sao có dấu?):",
    ]
    dong += [f"   {m}" for m in bc.mau]
    dong.append(f"ĐÃ GHI {bc.da_ghi} hàng video_vao_bo (bang_chung=md5_backfill)" if bc.that
                else "DRY-RUN: KHÔNG ghi gì — thêm --that để ghi")
    return dong
