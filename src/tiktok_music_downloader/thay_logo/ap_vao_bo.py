"""Áp bản đã thay logo VÀO BỘ (thay bản trong bộ) + Hoàn tác — chỉ cho nguồn "Đã vào bộ" (`nguon.kieu == "vao_bo"`).

Thuật ngữ: "bản gốc" G = BẢN TRONG BỘ `ban_copy_id` (bản Creative Desk copy, mang `properties.videodesk_src`), KHÁC file thư viện.
"Bản mới" M = bản copy PHÍA MÁY CHỦ của file đầu ra (`drive_file_id_ra`), gắn `appProperties` `tl_ap_bo=<id>.<lan>` + `tl_ap_goc=<G>`.

BẤT BIẾN: KHÔNG lúc nào bộ có đồng thời G hợp lệ + M. Áp = dời G sang `Thay logo - bản gốc/<mã bộ> (#folder6)/` (gốc Shared Drive,
ngoài cây `Creative`) RỒI MỚI copy M vào bộ. Hoàn tác = đổi tên M `HOAN-TAC-…` + dời M ra `…/da-hoan-tac/` RỒI MỚI trả G về bộ.
Không hàm nào xoá vĩnh viễn; G không bao giờ bị bỏ thùng rác (là bằng chứng "đã vào bộ" — video thư viện vẫn ẩn).

PHỤC HỒI theo PHÉP ĐO Drive, không theo `buoc`: DB chỉ giữ CHIỀU ý định `ap | lui | hoan_tac` (ghi TRƯỚC lời gọi Drive đầu của chiều
đó) + `lan`. Mỗi lần chạy một hàng đo G (`bo` | `ban_goc` | `mat`) và M (bản mang thẻ của lần này còn sống trong bộ) rồi đi theo bảng
trong plan; mỗi bước GHI probe trước (`parents`, tên) nên chạy lại bao nhiêu lần cũng ra cùng một kết quả. `buoc` chỉ để hiển thị,
ghi SAU lời gọi Drive thành công. Khoá theo bộ: `tl_ap_bo_khoa(folder_id PK)` lấy trong `BEGIN IMMEDIATE` (uvicorn MỘT tiến trình).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable

from tiktok_music_downloader.thay_logo.drive_tl import MIME_THU_MUC, DriveTL, DriveTLKhongQuyen, DriveTLKhongThay, ly_do_creative
from tiktok_music_downloader.thay_logo.thu_muc_bo import CongCreativeCam

log = logging.getLogger(__name__)

ENV_BAT = "TL_AP_VAO_BO"  # mặc định TẮT ⇒ route 404, nút ẩn, khởi động không đụng Drive
THE_AP, THE_GOC = "tl_ap_bo", "tl_ap_goc"
KHOA_DAU_NGUON = "videodesk_src"  # cùng khoá với `web/vao_bo_drive.py:KHOA_DAU_NGUON` (dấu Creative Desk gắn vào bản trong bộ)
TEN_THU_MUC_BAN_GOC = "Thay logo - bản gốc"
TEN_DA_HOAN_TAC = "da-hoan-tac"
TIEN_TO_HOAN_TAC = "HOAN-TAC-"
TRAN_LIET_KE_BO = 5000  # đếm tên trùng trong bộ: bộ có nhiều file hơn ⇒ không kết luận được ⇒ bỏ video (không đoán)
TRAN_VONG_MOT_HANG = 6  # mỗi vòng đổi chiều/trạng thái; vượt trần = có gì đó lặp ⇒ dừng hàng, để người xem

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_ap_bo (
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, job_video_id INTEGER NOT NULL, folder_id TEXT NOT NULL,
  ban_copy_id TEXT NOT NULL, ban_moi_id TEXT,
  chieu TEXT NOT NULL CHECK (chieu IN ('ap', 'lui', 'hoan_tac')),
  buoc TEXT NOT NULL, lan INTEGER NOT NULL DEFAULT 1, loi TEXT, luc REAL NOT NULL,
  UNIQUE (folder_id, ban_copy_id));
CREATE INDEX IF NOT EXISTS ix_tl_ap_bo_job ON tl_ap_bo(job_id);
CREATE TABLE IF NOT EXISTS tl_ap_bo_khoa (folder_id TEXT PRIMARY KEY, job_id INTEGER NOT NULL, luc REAL NOT NULL);
"""

LY_DO_SAI_CHU = "không phải video của bạn"
LY_DO_SO_CHU = "sổ Đã vào bộ chưa xác nhận bạn là chủ video"
LY_DO_DO_LUOT_KHAC = "đang dở ở lượt"
LY_DO_DA_AP = "Bộ này đã áp — hoàn tác trước nếu muốn áp lại."
THONG_DIEP_THIEU_QUYEN = "Tài khoản máy thiếu quyền Content manager trên bộ — báo quản trị."


class LoiAp(Exception):
    """Từ chối ở tầng DB — mang mã HTTP cho route."""

    def __init__(self, ma: int, thong_diep: str):
        super().__init__(thong_diep)
        self.ma = ma


def dang_bat() -> bool:
    return os.environ.get(ENV_BAT) == "1"


def khoi_tao(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def the_lan(rid: int, lan: int) -> str:
    """Thẻ bản mới THEO LẦN áp: dùng lại hàng sau hoàn tác thì lần sau mang thẻ khác ⇒ bản mới của lần trước không bao giờ bị nhận nhầm."""
    return f"{rid}.{lan}"


def ten_thu_muc_bo_goc(ma_bo: str | None, folder_id: str) -> str:
    sach = "".join(c for c in (ma_bo or "") if c.isprintable()).replace("/", "-").strip()
    return f"{sach or folder_id} (#{folder_id[:6]})"


def da_xong(chieu: str, buoc: str) -> bool:
    """Hàng đã tới trạng thái cuối của chiều hiện tại (không còn gì để chạy)."""
    if buoc == "can_nguoi":
        return True
    return {"ap": buoc in ("xong", "bo_qua"), "lui": buoc == "loi", "hoan_tac": buoc == "da_hoan_tac"}[chieu]


def _dung_lai_duoc(chieu: str, buoc: str) -> bool:
    """Trạng thái cuối mà G đang nằm yên trong bộ, không có M ⇒ áp lại được (dùng lại hàng, tăng `lan`)."""
    return (chieu, buoc) in (("hoan_tac", "da_hoan_tac"), ("lui", "loi"), ("ap", "bo_qua"))


def _dat(conn, rid: int, **cot) -> None:
    cot["luc"] = time.time()
    conn.execute(f"UPDATE tl_ap_bo SET {','.join(f'{k}=?' for k in cot)} WHERE id=?", [*cot.values(), rid])
    conn.commit()


# ============================================================================ tầng DB (route gọi, KHÔNG gọi Drive)
def cac_video(conn, job_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT v.id, v.nguon, v.trang_thai, v.drive_file_id_ra, (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id "
        "ORDER BY luc DESC LIMIT 1) AS dg FROM tl_job_video v WHERE v.job_id = ? ORDER BY v.id", (job_id,)).fetchall()
    out = []
    for r in rows:
        try:
            n = json.loads(r["nguon"])
        except ValueError:
            n = {}
        out.append({"id": r["id"], "nguon": n if isinstance(n, dict) else {}, "trang_thai": r["trang_thai"],
                    "file_ra": r["drive_file_id_ra"], "dg": r["dg"]})
    return out


def chu_job(conn, job_id: int) -> str:
    r = conn.execute("SELECT nguoi_tao FROM tl_job WHERE id=?", (job_id,)).fetchone()
    if r is None:
        raise LoiAp(404, "không có lượt này")
    return r["nguoi_tao"]


_TRUONG_CAN = ("file_id", "folder_id", "md5", "size", "ten", "video_id")


def phan_loai(conn, job_id: int, email: str, chu_cua: Callable[[list[str]], dict]) -> dict:
    """Kiểm TẦNG DB cho lượt `job_id` của `email` (đã là chủ lượt). `chu_cua(video_ids)` trả {video_id: (nguoi_tao jobs.db,
    video_vao_bo.chu)}. Trả {lam: [(video, hang|None, cach)], bo_qua, da_ap, hoan_tac_do, sai_chu}. `cach` ∈ moi | dung_lai | tiep."""
    vids = cac_video(conn, job_id)
    vb = [v for v in vids if v["nguon"].get("kieu") == "vao_bo"]
    chu = chu_cua(sorted({v["nguon"].get("video_id") for v in vb if v["nguon"].get("video_id")})) if vb else {}
    hang = {(r["folder_id"], r["ban_copy_id"]): r for r in conn.execute(
        "SELECT * FROM tl_ap_bo WHERE ban_copy_id IN (%s)" % ",".join("?" * len(vb)), [v["nguon"].get("file_id") for v in vb]
    ).fetchall()} if vb else {}
    kq = {"lam": [], "bo_qua": [], "da_ap": 0, "hoan_tac_do": 0, "sai_chu": 0}

    def bo(v, ly_do):
        kq["bo_qua"].append({"job_video_id": v["id"], "ly_do": ly_do})

    for v in vids:
        n = v["nguon"]
        if n.get("kieu") != "vao_bo":
            bo(v, "không phải video Đã vào bộ")
            continue
        if v["trang_thai"] != "xong" or v["dg"] != "dat" or not v["file_ra"]:
            bo(v, "chưa Đạt")
            continue
        if not all(n.get(k) for k in _TRUONG_CAN):
            bo(v, "thiếu ảnh chụp nguồn lúc tạo lượt")
            continue
        # Chủ video: ảnh chụp lúc tạo lượt VÀ jobs.db hiện tại VÀ sổ `video_vao_bo.chu` (NULL ⇒ từ chối — khác lúc TẠO lượt). Admin
        # cũng KHÔNG áp thay (USER chốt "video của ai người đó tự ghi").
        nguoi_tao, chu_so = chu.get(n["video_id"], (None, None))
        if n.get("chu_video") != email or nguoi_tao != email:
            kq["sai_chu"] += 1
            bo(v, LY_DO_SAI_CHU)
            continue
        if chu_so != email:
            kq["sai_chu"] += 1
            bo(v, LY_DO_SO_CHU)
            continue
        h = hang.get((n["folder_id"], n["file_id"]))
        if h is None:
            kq["lam"].append((v, None, "moi"))
        elif h["buoc"] == "can_nguoi":
            bo(v, "cần người xem (Drive lệch) — báo quản trị")
        elif h["chieu"] == "ap" and h["buoc"] == "xong":
            kq["da_ap"] += 1
        elif h["chieu"] == "hoan_tac" and not da_xong(h["chieu"], h["buoc"]):
            kq["hoan_tac_do"] += 1
        elif _dung_lai_duoc(h["chieu"], h["buoc"]):
            kq["lam"].append((v, h, "dung_lai"))
        elif h["job_id"] != job_id:  # hàng dở của lượt KHÁC: lượt này chạy `WHERE job_id=?` sẽ không bao giờ chạm nó
            bo(v, f"{LY_DO_DO_LUOT_KHAC} #{h['job_id']} — mở lượt đó bấm Tiếp tục")
        else:  # ap/lui dở (Drive lỗi giữa chừng, tiến trình chết) ⇒ "Tiếp tục" = chạy tiếp theo phép đo
            kq["lam"].append((v, h, "tiep"))
    return kq


def _lay_khoa(conn, folders: set[str], job_id: int) -> None:
    """Trong `BEGIN IMMEDIATE` của người gọi. Bộ nào đang khoá ⇒ 409 (không lấy phần nào)."""
    for f in sorted(folders):
        r = conn.execute("SELECT job_id FROM tl_ap_bo_khoa WHERE folder_id=?", (f,)).fetchone()
        if r is not None:
            raise LoiAp(409, "Bộ này đang có một lượt áp/hoàn tác khác chạy — đợi xong rồi thử lại.")
    now = time.time()
    conn.executemany("INSERT INTO tl_ap_bo_khoa (folder_id, job_id, luc) VALUES (?,?,?)", [(f, job_id, now) for f in sorted(folders)])


def dat_lich_ap(conn, job_id: int, email: str, chu_cua: Callable[[list[str]], dict]) -> dict:
    """Route `POST …/ap`: kiểm tầng DB, lấy khoá bộ, GHI CHIỀU `ap` (mốc ý định) cho từng video — tất cả trong MỘT `BEGIN IMMEDIATE`.
    Người gọi khởi thread chạy Drive sau đó (thread nhả khoá trong `finally`). Ném `LoiAp`."""
    khoi_tao(conn)
    if chu_job(conn, job_id) != email:
        raise LoiAp(403, "chỉ người tạo lượt được áp vào bộ")
    conn.execute("BEGIN IMMEDIATE")
    try:
        kq = phan_loai(conn, job_id, email, chu_cua)
        if kq["hoan_tac_do"]:
            raise LoiAp(409, "Hoàn tác của bộ này đang dở — bấm Hoàn tác để chạy tiếp.")
        if kq["da_ap"]:  # bộ đã có video áp xong (chưa hoàn tác): KHÔNG áp thêm phần còn lại; chỉ cho "Tiếp tục" hàng đang dở
            for v, _, cach in kq["lam"]:
                if cach != "tiep":
                    kq["bo_qua"].append({"job_video_id": v["id"], "ly_do": LY_DO_DA_AP})
            kq["lam"] = [x for x in kq["lam"] if x[2] == "tiep"]
        if not kq["lam"]:
            if kq["da_ap"]:
                raise LoiAp(409, LY_DO_DA_AP)
            khac = next((b["ly_do"] for b in kq["bo_qua"] if b["ly_do"].startswith(LY_DO_DO_LUOT_KHAC)), None)
            if khac:
                raise LoiAp(409, f"Video {khac}.")
            if kq["sai_chu"]:
                raise LoiAp(403, "Chỉ áp được video của chính bạn.")
            raise LoiAp(409, "Không có video Đạt nào để áp.")
        _lay_khoa(conn, {v["nguon"]["folder_id"] for v, _, _ in kq["lam"]}, job_id)
        now = time.time()
        for v, h, cach in kq["lam"]:
            n = v["nguon"]
            if cach == "moi":
                conn.execute("INSERT INTO tl_ap_bo (job_id, job_video_id, folder_id, ban_copy_id, chieu, buoc, lan, luc) "
                             "VALUES (?,?,?,?, 'ap', 'moi', 1, ?)", (job_id, v["id"], n["folder_id"], n["file_id"], now))
            elif cach == "dung_lai":  # áp lại sau hoàn tác: MỌI trạng thái phục hồi reset trong CÙNG câu, `lan` tăng ⇒ thẻ mới
                # Cũng dùng lại hàng `lui/loi` và `ap/bo_qua`. Cái giá: lỗi CỐ ĐỊNH (vd bản copy luôn mang dấu nguồn) ⇒ mỗi lần bấm
                # sinh 1 bản copy rồi bỏ thùng rác. CHƯA đặt trần số lần thử — cố ý (ĐP chốt giữ nguyên, chờ số liệu thật).
                conn.execute("UPDATE tl_ap_bo SET chieu='ap', job_id=?, job_video_id=?, ban_moi_id=NULL, buoc='moi', loi=NULL, "
                             "lan = lan + 1, luc=? WHERE id=?", (job_id, v["id"], now, h["id"]))
            else:
                conn.execute("UPDATE tl_ap_bo SET loi=NULL, luc=? WHERE id=?", (now, h["id"]))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"ap_id": job_id, "so_video": len(kq["lam"]), "bo_qua": kq["bo_qua"]}


def dat_lich_hoan_tac(conn, job_id: int, email: str) -> dict:
    """Route `POST …/hoan-tac`: hàng đã áp (hoặc đang dở bất kỳ chiều nào) ⇒ chiều `hoan_tac` + khoá bộ, trong MỘT `BEGIN IMMEDIATE`."""
    khoi_tao(conn)
    if chu_job(conn, job_id) != email:
        raise LoiAp(403, "chỉ người tạo lượt được hoàn tác")
    conn.execute("BEGIN IMMEDIATE")
    try:
        lam = [r for r in conn.execute("SELECT * FROM tl_ap_bo WHERE job_id=?", (job_id,)).fetchall()
               if (r["chieu"] == "ap" and r["buoc"] == "xong") or not da_xong(r["chieu"], r["buoc"])]
        if not lam:
            raise LoiAp(409, "Bộ này chưa áp video nào.")
        _lay_khoa(conn, {r["folder_id"] for r in lam}, job_id)
        now = time.time()
        conn.executemany("UPDATE tl_ap_bo SET chieu='hoan_tac', loi=NULL, luc=? WHERE id=?", [(now, r["id"]) for r in lam])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"ap_id": job_id, "so_video": len(lam)}


def nha_khoa(conn, job_id: int) -> None:
    conn.execute("DELETE FROM tl_ap_bo_khoa WHERE job_id=?", (job_id,))
    conn.commit()


def ban_da_ap(conn) -> set[str]:
    """`ban_copy_id` đang ở trạng thái đã áp / đang áp (tab "Đã vào bộ" đánh dấu "đã áp")."""
    khoi_tao(conn)
    return {r[0] for r in conn.execute("SELECT ban_copy_id FROM tl_ap_bo WHERE chieu IN ('ap', 'lui') AND buoc NOT IN ('bo_qua', 'loi')")}


def trang_thai(conn, job_id: int) -> dict:
    """Tiến độ của bộ cho `GET …/ap` (chỉ đọc DB)."""
    khoi_tao(conn)
    rows = conn.execute("SELECT a.*, v.nguon FROM tl_ap_bo a JOIN tl_job_video v ON v.id = a.job_video_id WHERE a.job_id=? ORDER BY a.id",
                        (job_id,)).fetchall()
    chay = conn.execute("SELECT 1 FROM tl_ap_bo_khoa WHERE job_id=? LIMIT 1", (job_id,)).fetchone() is not None
    tung = []
    for r in rows:
        try:
            ten = json.loads(r["nguon"]).get("ten")
        except (ValueError, AttributeError):
            ten = None
        d = {"job_video_id": r["job_video_id"], "ten": ten, "buoc": r["buoc"], "chieu": r["chieu"]}
        if r["loi"]:
            d["loi"] = r["loi"]
        tung.append(d)
    xong = [r for r in rows if r["chieu"] == "ap" and r["buoc"] == "xong"]
    if chay:
        tt = "chay"
    elif any(r["buoc"] == "can_nguoi" for r in rows):
        tt = "loi"
    elif any(not da_xong(r["chieu"], r["buoc"]) for r in rows):
        tt = "do_dang"
    elif xong:
        tt = "xong"
    elif any(r["buoc"] in ("bo_qua", "loi") and r["chieu"] != "hoan_tac" for r in rows):
        tt = "loi"
    else:
        tt = "chua_ap"
    return {"trang_thai": tt, "tung_video": tung, "so_da_ap": len(xong), "xong_luc": max((r["luc"] for r in xong), default=None),
            "da_hoan_tac": any(r["chieu"] == "hoan_tac" and r["buoc"] == "da_hoan_tac" for r in rows),
            "so_dang_lam": sum(1 for r in rows if not da_xong(r["chieu"], r["buoc"]))}


# ============================================================================ tầng Drive (thread `tl-ap`)
class _ThuMuc:
    """Tìm/tạo `Thay logo - bản gốc/<mã bộ> (#folder6)/[da-hoan-tac/]` — một lượt chạy giữ bộ nhớ đệm. `cha_goc(folder_id)` trả id nơi đặt
    thư mục gốc (mặc định: gốc Shared Drive chứa bộ). Mọi thư mục bản gốc qua cổng `ly_do_creative` TRƯỚC khi dùng (N1)."""

    def __init__(self, drive: DriveTL, cha_goc: Callable[[str], str] | None = None):
        self.drive, self._cha_goc, self._dem = drive, cha_goc, {}

    def _goc(self, folder_id: str) -> str:
        if self._cha_goc is not None:
            return self._cha_goc(folder_id)
        m = self.drive.lay_muc(folder_id)
        if not m.get("driveId"):
            raise RuntimeError("bộ không nằm trên Shared Drive")
        return m["driveId"]

    def _tim_tao(self, ten: str, cha: str, tao: bool) -> list[str]:
        co = [m["id"] for m in self.drive.tim_con_theo_ten(cha, ten)]
        if co or not tao:
            return co
        return [self.drive.tao_thu_muc(ten, cha)]

    def cac_ban_goc(self, folder_id: str, ma_bo: str) -> set[str]:
        """MỌI thư mục bản gốc của bộ đang có (chỉ tìm, không tạo) — để đo G nằm ở đâu, kể cả khi có thư mục trùng tên."""
        khoa = ("tim", folder_id)
        if khoa not in self._dem:
            out = set()
            for g in self._tim_tao(TEN_THU_MUC_BAN_GOC, self._goc(folder_id), False):
                out.update(self._tim_tao(ten_thu_muc_bo_goc(ma_bo, folder_id), g, False))
            self._dem[khoa] = out
        return self._dem[khoa]

    def ban_goc(self, folder_id: str, ma_bo: str) -> str:
        khoa = ("dung", folder_id)
        if khoa not in self._dem:
            g = self._tim_tao(TEN_THU_MUC_BAN_GOC, self._goc(folder_id), True)[0]
            sub = self._tim_tao(ten_thu_muc_bo_goc(ma_bo, folder_id), g, True)[0]
            ly_do = ly_do_creative(self.drive, sub)
            if ly_do:
                raise CongCreativeCam(ly_do)
            self._dem[khoa] = sub
            self._dem.pop(("tim", folder_id), None)
        return self._dem[khoa]

    def da_hoan_tac(self, folder_id: str, ma_bo: str) -> str:
        khoa = ("hoan", folder_id)
        if khoa not in self._dem:
            self._dem[khoa] = self._tim_tao(TEN_DA_HOAN_TAC, self.ban_goc(folder_id, ma_bo), True)[0]
        return self._dem[khoa]


def _do_g(drive: DriveTL, g: str, folder: str, cac_ban_goc: set[str]) -> tuple[str, dict | None]:
    """Vị trí G: `bo` | `ban_goc` | `mat` (404, thùng rác, hoặc cha ngoài {bộ, bản gốc} — không tự đoán)."""
    try:
        m = drive.lay_muc(g)
    except DriveTLKhongThay:
        return "mat", None
    cha = set(m.get("parents") or [])
    if m.get("trashed"):
        return "mat", m
    if folder in cha:
        return "bo", m
    if cha & cac_ban_goc:
        return "ban_goc", m
    return "mat", m


def _liet_ke_bo(drive: DriveTL, folder: str) -> list[dict]:
    """Con trực tiếp CHƯA vào thùng rác của bộ (liệt theo thư mục — không qua chỉ mục tìm kiếm `appProperties has`, vốn có thể trễ sau
    một lần copy). Bộ quá lớn để đọc hết ⇒ ném (không kết luận được "không có bản mới")."""
    con = drive.liet_ke_con(folder, TRAN_LIET_KE_BO)
    if len(con) >= TRAN_LIET_KE_BO:
        raise RuntimeError(f"bộ có từ {TRAN_LIET_KE_BO} mục trở lên — không đọc hết được")
    return [c for c in con if not c.get("trashed")]


def _cac_m_trong_bo(drive: DriveTL, folder: str, g: str) -> list[dict]:
    """MỌI bản mới của G đang nằm trong bộ: file mang `appProperties.tl_ap_goc == G`, BẤT KỂ thẻ lần nào (bản của lần áp trước bị kéo về
    bộ cũng tính — bất biến nói "bộ không có G + bản mới của G", không nói "bản mới của lần này")."""
    return [c for c in _liet_ke_bo(drive, folder)
            if c.get("mimeType") != MIME_THU_MUC and (c.get("appProperties") or {}).get(THE_GOC) == g]


def _cung_ten_trong_bo(drive: DriveTL, folder: str, ten: str) -> list[str] | None:
    """Id các file CHƯA vào thùng rác mang đúng tên `ten` trong bộ. Bộ quá lớn để đếm hết ⇒ None (không kết luận được)."""
    con = drive.liet_ke_con(folder, TRAN_LIET_KE_BO)
    if len(con) >= TRAN_LIET_KE_BO:
        return None
    return [c["id"] for c in con if not c.get("trashed") and c.get("name") == ten]


def _kiem_truoc_ap(drive: DriveTL, gm: dict, n: dict) -> str | None:
    """Tầng Drive (N2, N6): G trùng ảnh chụp lúc tạo lượt và bộ không có file KHÁC cùng tên. None = qua; chuỗi = lý do bỏ video."""
    if (gm.get("trashed") or gm.get("md5Checksum") != n["md5"] or str(gm.get("size")) != str(n["size"])
            or list(gm.get("parents") or []) != [n["folder_id"]]):
        return "Bản trong bộ đã đổi từ lúc tạo lượt (md5/dung lượng/thư mục) — không thay."
    cung = _cung_ten_trong_bo(drive, n["folder_id"], n["ten"])
    if cung is None:
        return "Bộ quá nhiều file, không kiểm được tên trùng — không thay."
    if [i for i in cung if i != n["file_id"]]:
        return "Bộ đã có file khác cùng tên — không thay."
    return None


def _ap(conn, drive: DriveTL, tm: _ThuMuc, h, n: dict, file_ra: str) -> None:
    """Bước 2→5, chạy lại được từ bất kỳ đâu: mỗi bước GHI probe trước."""
    folder, g, the = n["folder_id"], n["file_id"], the_lan(h["id"], h["lan"])
    bg = tm.ban_goc(folder, n.get("ma_bo") or "")                       # 2. thư mục bản gốc (cổng Creative)
    gm = drive.lay_muc(g)                                                # 3. probe parents ⇒ dời G ra khỏi bộ TRƯỚC
    if folder in (gm.get("parents") or []):
        drive.doi_cha(g, bg, folder)
    if h["buoc"] == "moi":
        _dat(conn, h["id"], buoc="da_doi_goc")
    # 4. Đo bản mới bằng LIỆT KÊ bộ (không bằng truy vấn thẻ — chỉ mục có thể trễ ⇒ copy bản thứ hai). Bản của lần này ⇒ dùng lại (copy
    # đã có hiệu lực mà chết trước khi ghi DB). Có bản của G mang thẻ KHÁC (lần trước, bị kéo về) ⇒ KHÔNG copy thêm, chuyển `lui`: bản đó
    # có thể là copy của một đầu ra khác, nhận nó làm "xong" là áp nhầm video.
    ms = _cac_m_trong_bo(drive, folder, g)
    cua_lan = [m for m in ms if (m.get("appProperties") or {}).get(THE_AP) == the]
    if len(cua_lan) != len(ms) or len(cua_lan) > 1:
        _dat(conn, h["id"], chieu="lui", loi="Trong bộ có bản mới lạ hoặc trùng của video này — đã gỡ, bản trong bộ trả về.")
        return
    moi = cua_lan[0]["id"] if cua_lan else drive.sao_chep(file_ra, folder, n["ten"], {THE_AP: the, THE_GOC: g})
    _dat(conn, h["id"], buoc="da_sao", ban_moi_id=moi)
    mm = drive.lay_muc(moi)                                              # kiểm sau copy: không mang dấu nguồn, tên duy nhất
    ly_do = None
    if (mm.get("properties") or {}).get(KHOA_DAU_NGUON):
        ly_do = "Bản copy mang dấu nguồn Creative Desk — đã gỡ, bản trong bộ trả về."
    else:
        cung = _cung_ten_trong_bo(drive, folder, n["ten"])
        if cung != [moi]:
            ly_do = "Tên trong bộ không còn duy nhất sau khi copy — đã gỡ, bản trong bộ trả về."
    if ly_do:
        _dat(conn, h["id"], chieu="lui", loi=ly_do)  # chiều ghi TRƯỚC lời gọi Drive đầu của chiều lui
        return
    _dat(conn, h["id"], buoc="xong", loi=None)                          # 5.


def _cac_m(drive: DriveTL, h, folder: str, g: str) -> list[str]:
    """Bản mới cần gỡ của hàng: mọi bản của G trong bộ (đo bằng liệt kê) + `ban_moi_id` đã ghi (người gọi probe lại từng cái)."""
    ids = [m["id"] for m in _cac_m_trong_bo(drive, folder, g)]
    if h["ban_moi_id"] and h["ban_moi_id"] not in ids:
        ids.append(h["ban_moi_id"])
    return ids


def _tra_g_ve(drive: DriveTL, g: str, folder: str, cac_ban_goc: set[str]) -> None:
    gm = drive.lay_muc(g)  # probe: G đã ở bộ ⇒ không dời
    cha = list(gm.get("parents") or [])
    if folder in cha:
        return
    tu = next((p for p in cha if p in cac_ban_goc), None)
    if tu is None:
        raise RuntimeError("bản trong bộ không nằm ở thư mục bản gốc")
    drive.doi_cha(g, folder, tu)


def _lui(conn, drive: DriveTL, tm: _ThuMuc, h, n: dict) -> None:
    """Gỡ M (thùng rác — M là bản copy của đầu ra, đầu ra vẫn còn) rồi trả G về bộ ⇒ video `loi`."""
    folder = n["folder_id"]
    for m in _cac_m(drive, h, folder, n["file_id"]):
        try:
            mm = drive.lay_muc(m)
        except DriveTLKhongThay:
            continue
        if not mm.get("trashed") and folder in (mm.get("parents") or []):
            drive.vao_thung_rac(m)
    _tra_g_ve(drive, n["file_id"], folder, tm.cac_ban_goc(folder, n.get("ma_bo") or ""))
    _dat(conn, h["id"], buoc="loi")


def _hoan_tac(conn, drive: DriveTL, tm: _ThuMuc, h, n: dict) -> None:
    """Đổi tên M `HOAN-TAC-…` + dời M ra `da-hoan-tac/` (mỗi việc probe trước) RỒI trả G về bộ."""
    folder, ma_bo = n["folder_id"], n.get("ma_bo") or ""
    ms = _cac_m(drive, h, folder, n["file_id"])
    if ms:
        dh = tm.da_hoan_tac(folder, ma_bo)
        for m in ms:
            try:
                mm = drive.lay_muc(m)
            except DriveTLKhongThay:
                continue
            if mm.get("trashed"):
                continue
            if not (mm.get("name") or "").startswith(TIEN_TO_HOAN_TAC):
                drive.doi_ten(m, TIEN_TO_HOAN_TAC + (mm.get("name") or ""))
            if folder in (mm.get("parents") or []):
                drive.doi_cha(m, dh, folder)
        _dat(conn, h["id"], buoc="da_doi_moi")
    _tra_g_ve(drive, n["file_id"], folder, tm.cac_ban_goc(folder, ma_bo))
    _dat(conn, h["id"], buoc="da_hoan_tac", loi=None)


def _chay_hang(conn, drive: DriveTL, tm: _ThuMuc, rid: int) -> None:
    """Đo G, M rồi đi theo bảng phục hồi tới trạng thái cuối. Lỗi Drive tạm ⇒ giữ `buoc`, ghi `loi` (bấm Tiếp tục). `CongCreativeCam` /
    `DriveTLKhongQuyen` ném lên: dừng cả lượt."""
    for _ in range(TRAN_VONG_MOT_HANG):
        h = conn.execute("SELECT a.*, v.nguon, v.drive_file_id_ra FROM tl_ap_bo a JOIN tl_job_video v ON v.id = a.job_video_id "
                         "WHERE a.id=?", (rid,)).fetchone()
        if h is None or da_xong(h["chieu"], h["buoc"]):
            return
        n = json.loads(h["nguon"])
        folder, g = n["folder_id"], n["file_id"]
        try:
            vi_tri, gm = _do_g(drive, g, folder, tm.cac_ban_goc(folder, n.get("ma_bo") or ""))
            if vi_tri == "mat":
                log.error("thay logo áp: bản trong bộ %s (hàng %s) mất/lệch chỗ — dừng, cần người xem", g, rid)
                _dat(conn, rid, buoc="can_nguoi", loi="Bản trong bộ đã mất hoặc nằm sai chỗ — cần quản trị xem (script khôi phục).")
                return
            co_m = bool(_cac_m_trong_bo(drive, folder, g))
            if h["chieu"] == "ap":
                if vi_tri == "bo" and co_m:  # code đúng không sinh ra ca này
                    log.error("thay logo áp: VI PHẠM BẤT BIẾN — bộ %s có cả bản trong bộ %s và bản mới (hàng %s)", folder, g, rid)
                    _dat(conn, rid, chieu="lui", loi="Bộ có cả bản cũ và bản mới — đã gỡ bản mới.")
                    continue
                if vi_tri == "bo":
                    ly_do = _kiem_truoc_ap(drive, gm, n)
                    if ly_do:
                        _dat(conn, rid, buoc="bo_qua", loi=ly_do)
                        return
                _ap(conn, drive, tm, h, n, h["drive_file_id_ra"])
            elif h["chieu"] == "lui":
                _lui(conn, drive, tm, h, n)
            else:
                _hoan_tac(conn, drive, tm, h, n)
        except (CongCreativeCam, DriveTLKhongQuyen):
            raise
        except Exception as e:  # noqa: BLE001 — Drive lỗi tạm / tiến trình bị cắt: giữ chiều + buoc, đo lại ở lần sau
            log.warning("thay logo áp: hàng %s lỗi (%s): %s", rid, type(e).__name__, e)
            _dat(conn, rid, loi=f"Drive lỗi tạm ({type(e).__name__}) — bấm Tiếp tục.")
            return
    _dat(conn, rid, buoc="can_nguoi", loi="Lặp quá số vòng — cần quản trị xem.")


def _chay_cac_hang(conn, drive: DriveTL, rids: list[int], cha_goc=None) -> None:
    tm = _ThuMuc(drive, cha_goc)
    for i, rid in enumerate(rids):
        try:
            _chay_hang(conn, drive, tm, rid)
        except (CongCreativeCam, DriveTLKhongQuyen) as e:
            msg = (f"Thư mục bản gốc nằm trong cây Creative — dừng ({e})" if isinstance(e, CongCreativeCam) else THONG_DIEP_THIEU_QUYEN)
            log.warning("thay logo áp: dừng cả lượt — %s", msg)
            for r in rids[i:]:
                _dat(conn, r, loi=msg)
            return


def chay_luot(conn, drive: DriveTL, job_id: int, cha_goc=None) -> None:
    """Chạy mọi hàng chưa xong của lượt `job_id` (route đã ghi chiều + lấy khoá)."""
    rids = [r[0] for r in conn.execute("SELECT id, chieu, buoc FROM tl_ap_bo WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
            if not da_xong(r[1], r[2])]
    _chay_cac_hang(conn, drive, rids, cha_goc)


def chay_nen(mo_conn: Callable[[], object], drive: DriveTL, job_id: int, cha_goc=None) -> threading.Thread:
    """Thread `tl-ap` cho một lượt. Khoá bộ NHẢ trong `finally`: exception bất kỳ không được giữ khoá tới lần khởi động lại."""
    def _chay():
        try:
            conn = mo_conn()
            try:
                chay_luot(conn, drive, job_id, cha_goc)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 — lỗi ngoài dự kiến: ghi log, khoá vẫn nhả bên dưới
            log.exception("thay logo áp: lượt %s lỗi ngoài dự kiến", job_id)
        finally:
            try:
                c = mo_conn()
                try:
                    nha_khoa(c, job_id)
                finally:
                    c.close()
            except Exception:  # noqa: BLE001
                log.exception("thay logo áp: KHÔNG nhả được khoá lượt %s", job_id)

    t = threading.Thread(target=_chay, name="tl-ap", daemon=True)
    t.start()
    return t


KHOA_QUET = 0  # `job_id` của khoá do quét khởi động lấy: id lượt thật luôn ≥ 1 ⇒ `nha_khoa(job_id)` của một lượt không xoá nhầm được


def quet_do_dang(conn, drive: DriveTL, moc: float | None = None, cha_goc=None) -> dict:
    """Lúc khởi động (thread `tl-ap`): chạy tiếp MỌI hàng chưa xong (cả chiều áp lẫn hoàn tác) theo phép đo Drive, rồi xoá khoá CŨ
    (lấy trước `moc`). Khoá lấy SAU `moc` là của lượt đang sống ⇒ bộ đó để yên (lượt đó tự chạy hết). Một bộ lỗi không chặn bộ khác;
    khoá cũ luôn được xoá (`finally`)."""
    khoi_tao(conn)
    moc = time.time() if moc is None else moc
    theo_bo: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, folder_id, chieu, buoc FROM tl_ap_bo ORDER BY id").fetchall():
        if not da_xong(r["chieu"], r["buoc"]):
            theo_bo.setdefault(r["folder_id"], []).append(r["id"])
    xoa = 0
    da_chay = 0
    try:
        # Bộ không còn hàng dở: khoá cũ không canh gì nữa ⇒ xoá NGAY (đừng để chúng chờ tới cuối một lượt quét dài).
        cu = [r[0] for r in conn.execute("SELECT folder_id FROM tl_ap_bo_khoa WHERE luc < ?", (moc,)) if r[0] not in theo_bo]
        for f in cu:
            xoa += conn.execute("DELETE FROM tl_ap_bo_khoa WHERE folder_id=? AND luc < ?", (f, moc)).rowcount
        conn.commit()
        for folder, rids in theo_bo.items():
            try:
                conn.execute("BEGIN IMMEDIATE")
                k = conn.execute("SELECT luc FROM tl_ap_bo_khoa WHERE folder_id=?", (folder,)).fetchone()
                if k is not None and k["luc"] >= moc:
                    conn.rollback()
                    continue
                luc = time.time()
                conn.execute("INSERT OR REPLACE INTO tl_ap_bo_khoa (folder_id, job_id, luc) VALUES (?,?,?)", (folder, KHOA_QUET, luc))
                conn.commit()
                try:
                    _chay_cac_hang(conn, drive, rids, cha_goc)
                    da_chay += len(rids)
                finally:
                    conn.execute("DELETE FROM tl_ap_bo_khoa WHERE folder_id=? AND job_id=? AND luc=?", (folder, KHOA_QUET, luc))
                    conn.commit()
            except Exception:  # noqa: BLE001 — một bộ hỏng (DB/Drive lạ) không được chặn các bộ khác
                if conn.in_transaction:
                    conn.rollback()
                log.exception("thay logo áp: quét bộ %s lỗi", folder)
    finally:
        xoa += conn.execute("DELETE FROM tl_ap_bo_khoa WHERE luc < ?", (moc,)).rowcount
        conn.commit()
    return {"hang_chay_tiep": da_chay, "khoa_cu_xoa": xoa}
