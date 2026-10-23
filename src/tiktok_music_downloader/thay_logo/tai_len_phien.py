"""Nguồn "Tải từ máy": phiên tải resumable THẲNG lên Google Drive (trình duyệt PUT từng khúc, file không đi qua máy chủ).

Luồng (plan đợt 4): server tạo phiên resumable bằng service account (header `Origin` = giá trị cấu hình `THAY_LOGO_ORIGIN`, để Google cho
trình duyệt đọc phản hồi cuối), trả URL phiên cho trình duyệt MỘT lần; tải xong trình duyệt gọi `/xong` ⇒ server đối chiếu file trên Drive
(thẻ `appProperties.tl_phien`, size, thư mục cha, mime) rồi mới coi file là của phiên. Mô-đun này gồm bảng `tl_phien_tai`, tạo/chốt phiên,
cấp file cho lượt thay logo, và các hàm dọn (chạy ở thread `tl-don-phien` của worker).

URL PHIÊN LÀ QUYỀN GHI vào thư mục đầu vào cho tới khi Google huỷ nó (~1 tuần): nó KHÔNG vào DB, KHÔNG vào log, KHÔNG vào thông điệp lỗi.
Mọi exception trên đường gọi Google chỉ được log bằng `mo_ta_loi` (tên kiểu + mã HTTP) — không bao giờ `str(e)`, `exc_info`, hay URL.

Máy trạng thái phiên (CHECK ở schema):
  mo → xong → da_dung → da_don          (da_dung → xong KHÔNG có; dùng lại file sau lỗi giữ nguyên da_dung)
  mo → bo_do · xong → bo_do             (quá 24 h chưa thành lượt, hoặc người dùng bỏ)
  bo_do (đã có file_id) → dang_don → da_don   (trash THẲNG theo file_id; không phụ thuộc quét theo thẻ bị chặn bởi trần liệt kê)
  dang_don: khoá của tác vụ dọn trong lúc trash (từ mo | xong | da_dung | bo_do); trash trượt ⇒ trả về trạng thái cũ
  (cột `dang_don_tu` ghi trạng thái trước khoá để khoá chết giữa chừng trả đúng chỗ).
Dọn LUÔN: khoá `dang_don` (UPDATE có điều kiện) ⇒ trash ⇒ ghi trạng thái cuối. Ghi mốc SAU việc nó khẳng định.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky, thu_muc_bo
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongThay, ly_do_creative
from tiktok_music_downloader.thay_logo.thu_muc_bo import CongCreativeCam

log = logging.getLogger(__name__)

ENV_BAT = "TL_TAI_TU_MAY"  # mặc định TẮT ⇒ route 404, tab ẩn (mẫu `ap_vao_bo.ENV_BAT`)
ENV_ORIGIN = "THAY_LOGO_ORIGIN"
ENV_THU_MUC_RA = "THAY_LOGO_DRIVE_THU_MUC_RA"  # cùng biến với `web/thay_logo_worker.py:ENV_THU_MUC_RA`
THE_PHIEN = "tl_phien"
URL_TAO_PHIEN = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true"
TIMEOUT_TAO_PHIEN = (10, 30)  # (nối, đọc) giây — Drive có lần treo > 60 s (smoke 2A)
HAN_BO_DO_GIAY = 24 * 3600
HAN_DANG_DON_GIAY = 600  # khoá `dang_don` cũ hơn mức này = tiến trình dọn đã chết giữa chừng
TRAN_LIET_KE_THE = 5000  # số con tối đa đọc mỗi thư mục vào khi quét theo thẻ
TRANG_THAI_CUOI_VIDEO = ("xong", "cho_nguoi", "loi")
TRANG_THAI = ("mo", "xong", "da_dung", "da_don", "bo_do", "dang_don")
MAU_MIME = re.compile(r"^video/[A-Za-z0-9.+_-]{1,60}$")
TEN_TOI_DA = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_phien_tai (
  token TEXT PRIMARY KEY, email TEXT NOT NULL, ten TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL, md5 TEXT,
  thu_muc_id TEXT NOT NULL, tao_luc REAL NOT NULL, cap_nhat_luc REAL NOT NULL, file_id TEXT,
  trang_thai TEXT NOT NULL DEFAULT 'mo'
    CHECK (trang_thai IN ('mo', 'xong', 'da_dung', 'da_don', 'bo_do', 'dang_don')), dang_don_tu TEXT);
CREATE INDEX IF NOT EXISTS ix_tl_phien_tai_email ON tl_phien_tai(email, trang_thai);
CREATE INDEX IF NOT EXISTS ix_tl_phien_tai_file ON tl_phien_tai(file_id);
"""


class LoiPhien(Exception):
    """Từ chối/lỗi mang mã HTTP cho route. Thông điệp an toàn để trả member (không có URL, không có chi tiết cấu hình)."""

    def __init__(self, ma: int, thong_diep: str):
        super().__init__(thong_diep)
        self.ma = ma


def dang_bat() -> bool:
    return os.environ.get(ENV_BAT) == "1"


def khoi_tao(conn) -> None:
    conn.executescript(SCHEMA)
    if "dang_don_tu" not in {r[1] for r in conn.execute("PRAGMA table_info(tl_phien_tai)").fetchall()}:  # DB tạo trước khi có cột
        try:
            conn.execute("ALTER TABLE tl_phien_tai ADD COLUMN dang_don_tu TEXT")
        except sqlite3.OperationalError as e:  # thread dọn và một request cùng thấy thiếu cột rồi cùng ALTER (khởi động đầu sau deploy)
            if "duplicate column" not in str(e).lower():
                raise
    conn.commit()


def mo_ta_loi(e: BaseException) -> str:
    """Mô tả AN TOÀN để log: tên kiểu + mã HTTP nếu có. KHÔNG dùng `str(e)` (lỗi của `requests`/Google nhúng URL, có thể có `upload_id`)."""
    ma = (getattr(getattr(e, "resp", None), "status", None) or getattr(getattr(e, "response", None), "status_code", None)
          or getattr(e, "ma_http", None))
    return f"{type(e).__name__}" + (f" http={ma}" if ma else "")


# ============================================================================ Origin (CORS của phiên Google)
def chuan_hoa_origin(gia_tri: str | None) -> str | None:
    """`scheme://host[:port]` viết thường, bỏ `/` cuối và cổng mặc định; không phải origin hợp lệ (path/query/userinfo, scheme ∉ http|https)
    ⇒ None. Dạng này CÙNG khuôn với header `Origin` trình duyệt gửi, nên so sánh/gửi Google đều dùng nó (không dùng chuỗi cấu hình thô)."""
    if not isinstance(gia_tri, str) or not gia_tri.strip():
        return None
    try:
        u = urlsplit(gia_tri.strip())
        port = u.port
    except ValueError:
        return None
    scheme = u.scheme.lower()
    if scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
        return None
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname.lower()
    return f"{scheme}://{host}" + (f":{port}" if port and port != (443 if scheme == "https" else 80) else "")


def origin_cau_hinh() -> str:
    """Origin công khai của trang (từ env) đã chuẩn hoá. Thiếu hoặc sai khuôn ⇒ 503 (không đoán)."""
    tho = os.environ.get(ENV_ORIGIN, "")
    if not tho.strip():
        log.error("thay logo tải từ máy: thiếu %s — không tạo được phiên", ENV_ORIGIN)
        raise LoiPhien(503, "Máy chủ chưa cấu hình tải từ máy — báo quản trị.")
    chuan = chuan_hoa_origin(tho)
    if chuan is None:
        log.error("thay logo tải từ máy: %s sai khuôn (phải là scheme://host[:port], không path/query, http|https) — không tạo được phiên", ENV_ORIGIN)
        raise LoiPhien(503, "Máy chủ chưa cấu hình tải từ máy — báo quản trị.")
    return chuan


def kiem_origin_request(origin_cau_hinh_chuan: str, origin_request: str | None) -> None:
    """`Origin` của request VẮNG ⇒ qua (proxy bỏ header không bị chặn). Có mà khác cấu hình (sau chuẩn hoá cả hai) ⇒ 403: phiên Google
    tạo với Origin = cấu hình nên trình duyệt ở origin khác sẽ tải hết rồi KHÔNG đọc được phản hồi cuối — lỗi ồn sớm tốt hơn hỏng im lặng."""
    if origin_request is None:
        return
    if chuan_hoa_origin(origin_request) != origin_cau_hinh_chuan:
        raise LoiPhien(403, f"Hãy mở trang này qua {origin_cau_hinh_chuan} (địa chỉ hiện tại không dùng được để tải từ máy).")


# ============================================================================ kiểm đầu vào
def kiem_khai_bao(ten, size, mime) -> tuple[str, int, str]:
    """Server là cổng thật (FE cũng chặn). Trả (tên sạch, size, mime) hoặc `LoiPhien(400)`."""
    from tiktok_music_downloader.nguon import TRAN_DUNG_LUONG_BYTE  # nạp muộn: `nguon` kéo yt-dlp; trần dùng CHUNG với worker tải

    t = ten.strip() if isinstance(ten, str) else ""
    if not t or len(t) > TEN_TOI_DA or not t.isprintable():
        raise LoiPhien(400, f"Tên file bắt buộc, 1–{TEN_TOI_DA} ký tự.")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise LoiPhien(400, "Kích thước file không hợp lệ.")
    if size > TRAN_DUNG_LUONG_BYTE:
        raise LoiPhien(400, f"File quá lớn (tối đa {TRAN_DUNG_LUONG_BYTE // (1024 * 1024)} MiB).")
    if not isinstance(mime, str) or not MAU_MIME.match(mime):
        raise LoiPhien(400, "Chỉ nhận file video.")
    return t, size, mime


# ============================================================================ tạo phiên
def dem_phien_giu_cho(conn, email: str, bay_gio: float) -> int:
    """Phiên còn giữ chỗ trong trần chờ chung của một người: `mo` còn trong hạn 24 h (tính từ `tao_luc`) VÀ `xong` chưa thành lượt còn
    trong hạn 24 h (tính từ `cap_nhat_luc`, tức lúc chốt). `xong` phải tính: file đã tải xong là một video sắp chờ, không đếm thì người dùng
    tải vượt trần rồi mới bị chặn ở bước tạo lượt. Phiên cũ hơn 24 h sẽ bị dọn ⇒ không giữ trần; `da_dung`/`bo_do`/`da_don` không tính
    (`da_dung` đã nằm trong `hang_doi.dem_dang_cho_cua` qua video của lượt)."""
    han = bay_gio - HAN_BO_DO_GIAY
    return conn.execute("SELECT count(*) FROM tl_phien_tai WHERE email=? AND ((trang_thai='mo' AND tao_luc > ?) OR (trang_thai='xong' AND cap_nhat_luc > ?))",
                        (email, han, han)).fetchone()[0]


def session_that(drive):
    """`AuthorizedSession` từ credentials service account CỦA CHÍNH adapter Drive đang dùng (`DriveTLThat.session_http`, không đọc credentials lần hai)."""
    ham = getattr(drive, "session_http", None)
    if ham is None:
        raise LoiPhien(503, "Máy chủ chưa nối được Google Drive — báo quản trị.")
    return ham()


def _xin_url_phien(session, origin: str, ten: str, size: int, mime: str, thu_muc_id: str, token: str) -> str:
    """Gọi Google tạo phiên resumable, trả URL phiên (`Location`). Người gọi BỌC mọi exception; hàm này không log gì."""
    r = session.post(
        URL_TAO_PHIEN, timeout=TIMEOUT_TAO_PHIEN, json={"name": ten, "parents": [thu_muc_id], "appProperties": {THE_PHIEN: token}},
        headers={"Origin": origin, "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": mime,
                 "Content-Type": "application/json; charset=UTF-8"})
    if r.status_code != 200:
        raise _LoiGoogle(r.status_code)
    url = (r.headers or {}).get("Location") or ""
    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != "https" or not (host == "googleapis.com" or host.endswith(".googleapis.com")):
        raise _LoiGoogle(r.status_code)  # không trả cho trình duyệt một URL không phải của Google
    return url


class _LoiGoogle(Exception):
    """Google trả mã khác 200 hoặc Location lạ. Chỉ mang MÃ (không mang thân phản hồi)."""

    def __init__(self, ma: int):
        super().__init__(f"http {ma}")
        self.ma_http = ma


def mo_phien(conn, drive, lay_session, email: str, ten, size, mime, thu_muc_ra_id: str, origin: str, tran_cho: int,
             bay_gio: float | None = None) -> dict:
    """Tạo phiên: `{token, url_phien}`. Trần chờ `tran_cho` CHUNG của video đang chờ (`hang_doi.dem_dang_cho_cua`) và phiên `mo` còn hạn.
    Thứ tự: kiểm khai báo → (sơ bộ) trần → thư mục vào (qua cổng Creative) → GIỮ CHỖ trong khoá ghi (đếm + INSERT) → gọi Google →
    Google trượt ⇒ xoá dòng giữ chỗ (503, không để lại phiên). URL phiên chỉ nằm trong biến cục bộ rồi đi ra response."""
    ten, size, mime = kiem_khai_bao(ten, size, mime)
    bay_gio = bay_gio or time.time()
    thong_diep_429 = f"Bạn đang có quá nhiều video chờ (tối đa {tran_cho})."
    if hang_doi.dem_dang_cho_cua(conn, email) + dem_phien_giu_cho(conn, email, bay_gio) + 1 > tran_cho:
        raise LoiPhien(429, thong_diep_429)  # sơ bộ, TRƯỚC mọi lời gọi Drive
    try:
        thu_muc_id = thu_muc_bo.thu_muc_vao_cua(drive, thu_muc_ra_id, email, lambda: ly_do_creative(drive, thu_muc_ra_id))
    except CongCreativeCam as e:
        log.warning("thay logo tải từ máy: %s — không tạo thư mục đầu vào", e)
        raise LoiPhien(503, "Tính năng tải từ máy tạm tắt do cấu hình máy chủ — báo quản trị.") from None
    except Exception as e:  # noqa: BLE001 — Drive lỗi/timeout: chưa tạo được thư mục ⇒ không tạo phiên
        log.warning("thay logo tải từ máy: không tìm/tạo được thư mục đầu vào (%s)", mo_ta_loi(e))
        raise LoiPhien(503, "Chưa nối được Google Drive lúc này — thử lại sau ít phút.") from None
    token = secrets.token_urlsafe(32)  # khớp `drive_tl._THE_AN_TOAN`
    conn.execute("BEGIN IMMEDIATE")
    try:
        if hang_doi.dem_dang_cho_cua(conn, email) + dem_phien_giu_cho(conn, email, bay_gio) + 1 > tran_cho:
            conn.rollback()
            raise LoiPhien(429, thong_diep_429)
        conn.execute("INSERT INTO tl_phien_tai (token, email, ten, size, mime, thu_muc_id, tao_luc, cap_nhat_luc) VALUES (?,?,?,?,?,?,?,?)",
                     (token, email, ten, size, mime, thu_muc_id, bay_gio, bay_gio))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    try:
        session = lay_session(drive)
        try:
            url = _xin_url_phien(session, origin, ten, size, mime, thu_muc_id, token)
        finally:
            dong = getattr(session, "close", None)
            if callable(dong):
                dong()
    except Exception as e:  # noqa: BLE001 — BỌC mọi lỗi: chỉ tên kiểu + mã HTTP (thông điệp lỗi của requests có thể chứa URL phiên)
        log.warning("thay logo tải từ máy: Google không tạo được phiên (%s)", mo_ta_loi(e))
        conn.execute("DELETE FROM tl_phien_tai WHERE token=? AND trang_thai='mo'", (token,))
        conn.commit()
        raise LoiPhien(503, "Google Drive chưa tạo được phiên tải — thử lại sau ít phút.") from None
    return {"token": token, "url_phien": url}


# ============================================================================ chốt phiên
def _doi_chieu(r, m: dict) -> str | None:
    """Lý do file Drive `m` không khớp phiên `r`, hoặc None. File trên Drive là nguồn sự thật: thẻ + size + cha + mime + chưa vào thùng rác."""
    if (m.get("appProperties") or {}).get(THE_PHIEN) != r["token"]:
        return "thẻ phiên"
    if str(m.get("size")) != str(r["size"]):
        return "kích thước"
    if (m.get("parents") or []) != [r["thu_muc_id"]]:
        return "thư mục"
    if m.get("trashed"):
        return "thùng rác"
    if m.get("mimeType") != r["mime"]:
        return "loại file"
    return None


def xac_nhan_xong(conn, drive, email: str, token: str, file_id: str) -> str:
    """Chốt phiên `mo` → `xong` sau khi đối chiếu file trên Drive. Chốt lại cùng file (FE thử lại) ⇒ 200 như cũ. Admin cũng chỉ chốt phiên của mình."""
    r = conn.execute("SELECT * FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
    if r is None:
        raise LoiPhien(404, "Không có phiên tải này.")
    if r["email"] != email:
        raise LoiPhien(403, "Phiên tải này không phải của bạn.")
    if r["trang_thai"] == "xong" and r["file_id"] == file_id:
        return file_id
    if r["trang_thai"] != "mo":
        raise LoiPhien(409, "Phiên tải này không còn nhận chốt — tải lại file.")
    try:
        m = drive.lay_muc(file_id)
    except DriveTLKhongThay:
        raise LoiPhien(503, "Drive chưa thấy file này — thử lại sau vài giây.") from None  # 503 (không phải 409): FE coi 4xx là lỗi cuối, 503 thì thử lại
    except Exception as e:  # noqa: BLE001 — chưa đo được ≠ lệch
        log.warning("thay logo tải từ máy: không đọc được file để chốt phiên (%s)", mo_ta_loi(e))
        raise LoiPhien(503, "Chưa hỏi được Drive lúc này — thử lại sau ít phút.") from None
    ly_do = _doi_chieu(r, m)
    if ly_do:
        log.warning("thay logo tải từ máy: file không khớp phiên (%s)", ly_do)
        raise LoiPhien(409, f"File trên Drive không khớp phiên tải ({ly_do}) — tải lại file.")
    cur = conn.execute("UPDATE tl_phien_tai SET file_id=?, md5=?, trang_thai='xong', cap_nhat_luc=? WHERE token=? AND trang_thai='mo'",
                       (file_id, m.get("md5Checksum"), time.time(), token))
    conn.commit()
    if cur.rowcount == 1:
        return file_id
    r2 = conn.execute("SELECT trang_thai, file_id FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
    if r2 is not None and r2["trang_thai"] == "xong" and r2["file_id"] == file_id:  # hai lần chốt cùng lúc: một bên ghi, bên kia thấy kết quả
        return file_id
    raise LoiPhien(409, "Phiên tải này không còn nhận chốt — tải lại file.")


# ============================================================================ phiên của tôi (khôi phục sau tải lại trang + nhả chỗ)
def liet_ke_cua_toi(conn, email: str, gioi_han: int, bay_gio: float | None = None) -> list[dict]:
    """Phiên `xong` (chưa thành lượt, còn trong hạn 24 h như `dem_phien_giu_cho`) của CHÍNH `email`, mới nhất trước. Admin cũng chỉ thấy của mình.
    Chỉ trả cái FE cần dựng lại dòng: KHÔNG có `thu_muc_id`, KHÔNG có URL phiên (không lưu ở đâu cả)."""
    han = (bay_gio or time.time()) - HAN_BO_DO_GIAY
    rows = conn.execute("SELECT token, file_id, ten, size, cap_nhat_luc FROM tl_phien_tai "
                        "WHERE email=? AND trang_thai='xong' AND cap_nhat_luc > ? ORDER BY cap_nhat_luc DESC, token LIMIT ?",
                        (email, han, max(0, int(gioi_han)))).fetchall()
    return [{"token": r["token"], "file_id": r["file_id"], "ten": r["ten"], "size": r["size"], "cap_nhat_luc": r["cap_nhat_luc"]} for r in rows]


def bo_phien(conn, email: str, token: str, bay_gio: float | None = None) -> str:
    """Người dùng bỏ phiên CỦA MÌNH (`mo` | `xong` → `bo_do`) bằng MỘT UPDATE có điều kiện; KHÔNG gọi Drive trong request. Thread `tl-don-phien`
    trash file của phiên `bo_do` theo `file_id` (`_don_bo_do_co_file`, rồi `da_don`) và file xuất hiện muộn theo thẻ (`_quet_theo_the`).
    Trả `bo_do` (đã `bo_do` ⇒ vẫn trả); thread đã dọn xong (`da_don`) ⇒ 409, FE coi là trả lời dứt khoát.
    Thứ tự quyền như `xac_nhan_xong`: 404 (không có) → 403 (của người khác, admin cũng vậy) → 409 (`da_dung`/`dang_don`/`da_don`)."""
    bay_gio = bay_gio or time.time()
    r = conn.execute("SELECT email, trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
    if r is None:
        raise LoiPhien(404, "Không có phiên tải này.")
    if r["email"] != email:
        raise LoiPhien(403, "Phiên tải này không phải của bạn.")
    if r["trang_thai"] == "bo_do":
        return "bo_do"
    cur = conn.execute("UPDATE tl_phien_tai SET trang_thai='bo_do', cap_nhat_luc=? WHERE token=? AND email=? AND trang_thai IN ('mo', 'xong')",
                       (bay_gio, token, email))
    conn.commit()
    if cur.rowcount == 1:
        return "bo_do"
    r2 = conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
    if r2 is not None and r2["trang_thai"] == "bo_do":  # hai lần bỏ cùng lúc
        return "bo_do"
    raise LoiPhien(409, "Phiên tải này không còn bỏ được (file đã nằm trong một lượt hoặc đang được dọn).")


# ============================================================================ cấp file cho lượt (gọi TRONG BEGIN IMMEDIATE của POST /jobs)
def _chi_con_video_loi(conn, file_id: str) -> bool:
    """Mọi video đã dùng `file_id` đều đang `loi` (cùng ngữ nghĩa `_nguon_dang_trong_luot`: `trang_thai != 'loi'` mới giữ nguồn)."""
    n, loi = conn.execute("SELECT count(*), coalesce(sum(trang_thai = 'loi'), 0) FROM tl_job_video "
                          "WHERE json_extract(nguon, '$.kieu') = 'may' AND json_extract(nguon, '$.file_id') = ?", (file_id,)).fetchone()
    return n == loi


def dung_cho_luot(conn, email: str, file_ids: list[str], bay_gio: float | None = None) -> list[dict]:
    """Mỗi `file_id` phải là file của phiên CỦA CHÍNH `email` (admin cũng không dùng phiên người khác ⇒ 403), ở trạng thái `xong`
    (⇒ `da_dung`) hoặc `da_dung` mà mọi lượt dùng nó đều `loi` (dùng lại sau lỗi máy chủ, khỏi tải lại). Trả danh sách `nguon` cho
    `hang_doi.tao_job`. Gọi trong `BEGIN IMMEDIATE`; người gọi commit (cùng `tao_job`) hoặc rollback."""
    bay_gio = bay_gio or time.time()
    out = []
    for fid in file_ids:
        r = conn.execute("SELECT token, email, ten, trang_thai FROM tl_phien_tai WHERE file_id=?", (fid,)).fetchone()
        if r is None or r["email"] != email:
            raise LoiPhien(403, "Chỉ dùng được file bạn đã tải lên từ máy.")
        if r["trang_thai"] == "xong":
            cur = conn.execute("UPDATE tl_phien_tai SET trang_thai='da_dung', cap_nhat_luc=? WHERE token=? AND trang_thai='xong'",
                               (bay_gio, r["token"]))
            if cur.rowcount != 1:
                raise LoiPhien(409, "File tải lên này không còn dùng được — tải lại.")
        elif r["trang_thai"] == "da_dung":
            if not _chi_con_video_loi(conn, fid):
                raise LoiPhien(409, "File này đã nằm trong một lượt thay logo khác.")
        else:
            raise LoiPhien(409, "File tải lên này không còn dùng được — tải lại.")
        out.append({"kieu": "may", "file_id": fid, "token": r["token"], "ten": r["ten"]})
    return out


# ============================================================================ dọn (thread `tl-don-phien`, KHÔNG phụ thuộc cờ)
def _rac(drive, file_id: str) -> None:
    try:
        drive.vao_thung_rac(file_id)
    except DriveTLKhongThay:  # đã mất = đã dọn
        pass


def _giu(conn, token: str, tu: str, bay_gio: float) -> bool:
    cur = conn.execute("UPDATE tl_phien_tai SET trang_thai='dang_don', dang_don_tu=?, cap_nhat_luc=? WHERE token=? AND trang_thai=?",
                       (tu, bay_gio, token, tu))
    conn.commit()
    return cur.rowcount == 1


def _tra(conn, token: str, ve: str, cap_nhat_luc: float) -> None:
    conn.execute("UPDATE tl_phien_tai SET trang_thai=?, dang_don_tu=NULL, cap_nhat_luc=? WHERE token=? AND trang_thai='dang_don'", (ve, cap_nhat_luc, token))
    conn.commit()


def _phuc_hoi_khoa_cu(conn, bay_gio: float) -> int:
    """Khoá `dang_don` quá cũ (tiến trình chết giữa trash) ⇒ trả về trạng thái trước: khoá từ `bo_do` ⇒ `bo_do` (không được sống lại thành `xong`); không file ⇒ `mo`; file đã vào lượt ⇒ `da_dung`; còn lại `xong`."""
    n = 0
    for r in conn.execute("SELECT token, file_id, tao_luc, dang_don_tu FROM tl_phien_tai WHERE trang_thai='dang_don' AND cap_nhat_luc < ?",
                          (bay_gio - HAN_DANG_DON_GIAY,)).fetchall():
        if r["dang_don_tu"] == "bo_do":
            _tra(conn, r["token"], "bo_do", bay_gio)
            n += 1
            continue
        if not r["file_id"]:
            ve = "mo"
        elif conn.execute("SELECT 1 FROM tl_job_video WHERE json_extract(nguon, '$.kieu') = 'may' AND json_extract(nguon, '$.file_id') = ? LIMIT 1",
                          (r["file_id"],)).fetchone():
            ve = "da_dung"
        else:
            ve = "xong"
        _tra(conn, r["token"], ve, r["tao_luc"])
        n += 1
    return n


def _don_bo_do(conn, drive, bay_gio: float) -> int:
    """Phiên `mo` quá 24 h: trash file mang thẻ (nếu có) RỒI đánh dấu `bo_do` — CÓ HAY KHÔNG CÓ file đều đánh dấu (upload chưa xong thì
    Drive không sinh file). Trash trượt ⇒ về `mo`, lượt sau thử lại."""
    n = 0
    for r in conn.execute("SELECT token, thu_muc_id, tao_luc FROM tl_phien_tai WHERE trang_thai='mo' AND tao_luc < ?",
                          (bay_gio - HAN_BO_DO_GIAY,)).fetchall():
        if not _giu(conn, r["token"], "mo", bay_gio):
            continue
        try:
            for f in drive.tim_theo_the(r["thu_muc_id"], THE_PHIEN, r["token"]):
                _rac(drive, f["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("thay logo tải từ máy: dọn phiên bỏ dở lỗi (%s) — giữ nguyên, thử lại lượt sau", mo_ta_loi(e))
            _tra(conn, r["token"], "mo", r["tao_luc"])
            continue
        _tra(conn, r["token"], "bo_do", bay_gio)
        n += 1
    return n


def _don_xong_chua_dung(conn, drive, bay_gio: float) -> int:
    """Phiên `xong` quá 24 h chưa thành lượt: trash file như bỏ dở."""
    n = 0
    for r in conn.execute("SELECT token, file_id, cap_nhat_luc FROM tl_phien_tai WHERE trang_thai='xong' AND cap_nhat_luc < ?",
                          (bay_gio - HAN_BO_DO_GIAY,)).fetchall():
        if not _giu(conn, r["token"], "xong", bay_gio):
            continue  # vừa thành lượt (`da_dung`) giữa lúc đọc và khoá
        try:
            _rac(drive, r["file_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("thay logo tải từ máy: dọn file đã chốt chưa dùng lỗi (%s)", mo_ta_loi(e))
            _tra(conn, r["token"], "xong", r["cap_nhat_luc"])
            continue
        _tra(conn, r["token"], "bo_do", bay_gio)
        n += 1
    return n


def _don_bo_do_co_file(conn, drive, bay_gio: float) -> int:
    """Phiên `bo_do` đã biết `file_id`: trash THẲNG theo `file_id` rồi mới ghi `da_don` (không dựa vào quét theo thẻ: nó chỉ đọc tối đa
    `TRAN_LIET_KE_THE` con mỗi thư mục, không sắp thứ tự ⇒ file có thể nằm ngoài lần đọc mãi mãi). Khoá `dang_don` trước; trash trượt ⇒ về
    `bo_do`, lượt sau thử lại; file đã mất (404) ⇒ `_rac` coi như đã dọn."""
    n = 0
    for r in conn.execute("SELECT token, file_id, cap_nhat_luc FROM tl_phien_tai WHERE trang_thai='bo_do' AND file_id IS NOT NULL").fetchall():
        if not _giu(conn, r["token"], "bo_do", bay_gio):
            continue
        try:
            _rac(drive, r["file_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("thay logo tải từ máy: dọn file của phiên đã bỏ lỗi (%s) — giữ nguyên, thử lại lượt sau", mo_ta_loi(e))
            _tra(conn, r["token"], "bo_do", r["cap_nhat_luc"])
            continue
        _tra(conn, r["token"], "da_don", bay_gio)
        n += 1
    return n


def _het_han_giu(conn, file_id: str, bay_gio: float) -> bool:
    """Mọi video dùng file đã ở trạng thái cuối VÀ quá hạn giữ cùng luật với khung/ảnh soi cục bộ (`nhat_ky`): 60 ngày; có video đánh giá
    MỚI NHẤT là `hong` hoặc có ca khoanh ⇒ 180 ngày (ca khoanh cần tải lại được nguồn để chạy lại). Tuổi tính từ lần cập nhật trạng thái cuối muộn nhất."""
    rows = conn.execute(
        "SELECT v.trang_thai, v.cap_nhat_luc, CASE WHEN EXISTS (SELECT 1 FROM tl_ca_khoanh c WHERE c.video_log_id = v.video_log_id) THEN 'hong' "
        "ELSE (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) END AS dg "
        "FROM tl_job_video v WHERE json_extract(v.nguon, '$.kieu') = 'may' AND json_extract(v.nguon, '$.file_id') = ?", (file_id,)).fetchall()
    if not rows or any(r["trang_thai"] not in TRANG_THAI_CUOI_VIDEO for r in rows):
        return False
    ngay = nhat_ky.NGAY_GIU_FILE_HONG if any(r["dg"] == "hong" for r in rows) else nhat_ky.NGAY_GIU_FILE
    return bay_gio - max(r["cap_nhat_luc"] for r in rows) > ngay * 86400


def _ghi_da_don(conn, token: str, file_id: str, bay_gio: float) -> None:
    """SAU khi trash thành công: phiên `da_don` + cờ `da_don:true` trong JSON `nguon` của mọi video dùng file (FE ẩn "Bản gốc"). Một commit."""
    conn.execute("UPDATE tl_phien_tai SET trang_thai='da_don', dang_don_tu=NULL, cap_nhat_luc=? WHERE token=? AND trang_thai='dang_don'", (bay_gio, token))
    for r in conn.execute("SELECT id, nguon FROM tl_job_video WHERE json_extract(nguon, '$.kieu') = 'may' AND json_extract(nguon, '$.file_id') = ?",
                          (file_id,)).fetchall():
        d = json.loads(r["nguon"])
        d["da_don"] = True
        conn.execute("UPDATE tl_job_video SET nguon=? WHERE id=?", (json.dumps(d, sort_keys=True), r["id"]))
    conn.commit()


def _don_file_da_dung(conn, drive, bay_gio: float) -> int:
    """File nhập đã dùng: trash khi mọi lượt dùng nó đã ở trạng thái cuối và quá hạn giữ. Khoá `dang_don` TRƯỚC (chặn lượt mới dùng lại file
    giữa lúc trash), kiểm LẠI sau khoá, trash, RỒI MỚI ghi `da_don`."""
    n = 0
    for r in conn.execute("SELECT token, file_id, cap_nhat_luc FROM tl_phien_tai WHERE trang_thai='da_dung'").fetchall():
        if not _het_han_giu(conn, r["file_id"], bay_gio) or not _giu(conn, r["token"], "da_dung", bay_gio):
            continue
        try:
            if not _het_han_giu(conn, r["file_id"], bay_gio):  # lượt mới vừa dùng lại file giữa lúc đọc và khoá
                _tra(conn, r["token"], "da_dung", r["cap_nhat_luc"])
                continue
            _rac(drive, r["file_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("thay logo tải từ máy: dọn file nhập đã dùng lỗi (%s)", mo_ta_loi(e))
            _tra(conn, r["token"], "da_dung", r["cap_nhat_luc"])
            continue
        _ghi_da_don(conn, r["token"], r["file_id"], bay_gio)
        n += 1
    return n


def _quet_theo_the(conn, drive) -> dict:
    """Phiên có thể hoàn tất SAU khi bị đánh `bo_do` (URL phiên sống ~1 tuần > hạn dọn 24 h) ⇒ file xuất hiện muộn. Mỗi thư mục vào: liệt kê
    con, lọc phía client theo `appProperties.tl_phien`; token `bo_do`/`da_don` ⇒ trash; token KHÔNG có trong DB ⇒ chỉ log (bảo thủ)."""
    n_rac = n_la = 0
    for (thu_muc,) in conn.execute("SELECT DISTINCT thu_muc_id FROM tl_phien_tai").fetchall():
        try:
            con = drive.liet_ke_con(thu_muc, TRAN_LIET_KE_THE)
            for f in con:
                token = (f.get("appProperties") or {}).get(THE_PHIEN)
                if not token or f.get("trashed"):
                    continue
                r = conn.execute("SELECT trang_thai FROM tl_phien_tai WHERE token=?", (token,)).fetchone()
                if r is None:
                    n_la += 1
                    log.warning("thay logo tải từ máy: file %s mang thẻ phiên không có trong sổ — để nguyên", f.get("id"))
                elif r["trang_thai"] in ("bo_do", "da_don"):
                    _rac(drive, f["id"])
                    n_rac += 1
        except Exception as e:  # noqa: BLE001 — một thư mục lỗi không chặn các thư mục khác
            log.warning("thay logo tải từ máy: quét theo thẻ thư mục lỗi (%s)", mo_ta_loi(e))
    return {"rac": n_rac, "the_la": n_la}


def don_mot_luot(conn, drive, bay_gio: float | None = None) -> dict:
    """Một lượt dọn đủ 5 việc (khoá cũ · file của phiên đã bỏ · bỏ dở · đã chốt chưa dùng · file nhập đã dùng) + quét theo thẻ. Thread `tl-don-phien` gọi mỗi giờ."""
    khoi_tao(conn)
    bay_gio = bay_gio or time.time()
    kq = {"phuc_hoi": _phuc_hoi_khoa_cu(conn, bay_gio), "bo_do_co_file": _don_bo_do_co_file(conn, drive, bay_gio),
          "bo_do": _don_bo_do(conn, drive, bay_gio),
          "xong_qua_han": _don_xong_chua_dung(conn, drive, bay_gio), "da_dung": _don_file_da_dung(conn, drive, bay_gio)}
    kq["quet_the"] = _quet_theo_the(conn, drive)
    return kq
