"""Route hộp thư relay agy cho job "Thay logo" (plan.md §3e; ĐP-1495: route TRỌN trong file này, ráp vào `app.py` bằng
`dang_ky_route(app, ...)` lúc tích hợp).

Máy dev KÉO việc qua ba route, xác thực bằng token RIÊNG của relay (biến môi trường `THAY_LOGO_RELAY_TOKEN`, KHÔNG có giá trị mặc
định). Thiếu token ⇒ mọi route trả 503 (đóng, không mở). Route này không dùng phiên đăng nhập member và không cấp quyền gì khác.
"""
from __future__ import annotations

import hmac
import json
import logging
import math
import os
import re as _re
import sqlite3 as _sqlite3
from datetime import datetime as _datetime, timedelta as _timedelta
from contextlib import closing
from pathlib import Path
from typing import Callable

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from tiktok_music_downloader.thay_logo import hang_doi, link_da_kiem, nguon_drive, nhat_ky
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLThat
from tiktok_music_downloader.thay_logo.hop_thu import HopThu, LoiHopThu

log = logging.getLogger(__name__)

ENV_TOKEN = "THAY_LOGO_RELAY_TOKEN"
TIEN_TO = "/api/thay-logo/relay"


TOKEN_TOI_THIEU = 32


def _kiem_token(authorization: str | None = Header(default=None)) -> None:
    dung = os.environ.get(ENV_TOKEN, "")  # đọc LÚC GỌI: đổi/xoá token có hiệu lực không cần khởi động lại
    if len(dung) < TOKEN_TOI_THIEU:  # thiếu HOẶC quá ngắn ⇒ coi như chưa cấu hình: đóng, không mở với token yếu
        raise HTTPException(503, "relay chưa cấu hình token")
    gui = (authorization or "").removeprefix("Bearer ").strip()
    if not gui or not hmac.compare_digest(gui.encode(), dung.encode()):
        raise HTTPException(401, "sai token relay")


def _http(loi: LoiHopThu) -> HTTPException:
    return HTTPException(loi.ma, str(loi))


def dang_ky_route(app: FastAPI, lay_hop_thu: Callable[[], HopThu]) -> None:
    """`lay_hop_thu` trả hộp thư LÚC GỌI (test và app có thể đổi thư mục dữ liệu)."""

    @app.get(f"{TIEN_TO}/viec", dependencies=[Depends(_kiem_token)])
    def relay_viec() -> dict:
        return {"viec": lay_hop_thu().viec_cho()}

    @app.get(f"{TIEN_TO}/anh/{{anh}}", dependencies=[Depends(_kiem_token)])
    def relay_anh(anh: str) -> Response:
        try:
            du_lieu = lay_hop_thu().doc_anh(anh)
        except LoiHopThu as e:
            raise _http(e) from None
        if du_lieu is None:
            raise HTTPException(404, "không có ảnh")
        return Response(du_lieu, media_type="image/jpeg")

    @app.post(f"{TIEN_TO}/ket-qua/{{job_id}}", status_code=204, response_model=None, dependencies=[Depends(_kiem_token)])
    def relay_ket_qua(job_id: int, du_lieu=Body(...)) -> None:
        try:
            lay_hop_thu().nop_ket_qua(job_id, du_lieu)
        except LoiHopThu as e:
            raise _http(e) from None


# ============================================================================ route cho MEMBER (trang Thay logo)
# Xác thực bằng `require_user` có sẵn (JWT Cloudflare Access, cùng nguồn với `jobs.nguoi_tao`). Mỗi video chỉ NGƯỜI TẠO job hoặc admin
# được xem / đánh giá (USER §0: "người tạo job tự duyệt").

TRAN_CHO_MOI_NGUOI = 100  # video chưa xong của một người — chặn làm ngập hàng đợi / đĩa (code-reviewer 09/10)
TRAN_VIDEO_MOT_JOB = TRAN_CHO_MOI_NGUOI  # USER CHỐT: không trần theo bộ — một lượt dùng được cả phần chỗ chờ của người đó
TRAN_TRANG_VIDEO = 300  # số dòng tối đa mỗi lần trả của /videos
TRAN_QUET_VIDEO = 5000  # trần số dòng đọc khi lọc theo nền tảng (chống quét cả bảng)


def drive_ids_cua(jobs_db, email: str, ids: list[str]) -> set[str]:
    """Trong `ids`, những `drive_file_id` thuộc thư viện CỦA `email` — cùng định nghĩa sở hữu với `web/models.py:list_videos`
    (video thuộc người tạo job đã tải nó). Mở `jobs.db` CHỈ ĐỌC; không đọc được ⇒ tập rỗng (từ chối là hướng an toàn)."""
    if not ids:
        return set()
    try:
        with _sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5) as c:
            rows = c.execute("SELECT v.drive_file_id FROM videos v JOIN jobs j ON j.id = v.job_id WHERE j.nguoi_tao = ? "
                             f"AND v.drive_file_id IN ({','.join('?' * len(ids))})", [email, *ids]).fetchall()
    except _sqlite3.Error:
        return set()
    return {r[0] for r in rows}


def thong_tin_thu_vien(jobs_db, ids: list[str]) -> dict[str, dict] | None:
    """Ghép thư viện: `drive_file_id` → {video_id, title, nen_tang, chu}. `jobs.db` mở CHỈ ĐỌC; không đọc được ⇒ `None` (khác `{}` =
    đọc được mà không khớp) và ghi log. Hàm này KHÔNG phân quyền: id của một lượt có thể nằm trong thư viện NGƯỜI KHÁC (dán link
    Drive tới file tool đã tải cho người đó), nên người gọi phải tự so `chu` với người tạo lượt — xem `_thu_vien_cua_chu`."""
    out: dict[str, dict] = {}
    if not ids:
        return out
    try:
        with closing(_sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5)) as c:
            for i in range(0, len(ids), 500):
                lo = ids[i:i + 500]
                for fid, vid, title, nen_tang, chu in c.execute(
                        "SELECT v.drive_file_id, v.video_id, v.title, j.nen_tang, j.nguoi_tao FROM videos v LEFT JOIN jobs j "
                        f"ON j.id = v.job_id WHERE v.drive_file_id IN ({','.join('?' * len(lo))})", lo):
                    out[fid] = {"video_id": vid, "title": title, "nen_tang": nen_tang, "chu": chu}
    except _sqlite3.Error as e:
        log.warning("thay logo: không đọc được thư viện %s (%s)", jobs_db, type(e).__name__)
        return None
    return out


def _thu_vien_cua_chu(tv: dict[str, dict], fid: str | None, nguoi_tao: str) -> dict | None:
    """Mục thư viện của `fid` CHỈ KHI nó thuộc thư viện của người tạo lượt; khác chủ ⇒ `None`, dòng đó coi như ngoài thư viện
    (tên lấy từ sổ `tl_link_kiem` của chính người tạo). Bỏ phép so này thì A dán link file của B sẽ thấy title/nền tảng/video_id
    của B."""
    t = tv.get(fid) if fid else None
    return t if t is not None and t.get("chu") == nguoi_tao else None


def _moc_thoi_gian(gia_tri: str | None, ten: str, cuoi_ngay: bool = False) -> float | None:
    """`tu`/`den`: số giây epoch HỮU HẠN HOẶC ngày `YYYY-MM-DD` (giờ máy chủ; `den` tính HẾT ngày đó). Sai khuôn / ngoài miền ⇒ 400."""
    if gia_tri is None or gia_tri == "":
        return None
    loi = HTTPException(400, f"{ten} phải là YYYY-MM-DD hoặc số giây hữu hạn")
    try:
        so = float(gia_tri)
    except ValueError:
        so = None
    if so is not None:
        if not math.isfinite(so):
            raise loi
        return so
    try:
        d = _datetime.strptime(gia_tri, "%Y-%m-%d")
        return (d + _timedelta(days=1 if cuoi_ngay else 0)).timestamp()
    except (ValueError, OverflowError, OSError):
        raise loi from None


TEN_BO_TOI_DA = 80
_DRIVE_ID = _re.compile(r"^[A-Za-z0-9_-]{10,120}$")


class TaoJobThayLogo(BaseModel):
    drive_file_ids: list[str] = Field(min_length=1, max_length=TRAN_VIDEO_MOT_JOB)
    ghi_chu: str = Field(default="", max_length=500)
    ten_bo: str | None = None  # bắt buộc, nhưng kiểm tay để thiếu/sai đều trả 400 cùng một khuôn


def _kiem_ten_bo(ten: str | None) -> str:
    t = (ten or "").strip()
    if not t or len(t) > TEN_BO_TOI_DA or not t.isprintable():
        raise HTTPException(400, f"tên bộ bắt buộc, 1–{TEN_BO_TOI_DA} ký tự")
    return t


class DanhGia(BaseModel):
    ket_qua: str
    loai_loi: str | None = None
    ghi_chu: str = Field(default="", max_length=2000)


class KiemLink(BaseModel):
    links: list[str] = Field(max_length=200)  # mỗi phần tử có thể chứa nhiều dòng; trần 20 LINK kiểm sau khi tách dòng


_SQL_DANH_SACH = """
SELECT v.id, v.job_id, v.nguon, v.trang_thai, v.cho_agy_tu, v.cap_nhat_luc, v.loi_text, v.drive_file_id_ra, j.nguoi_tao,
       j.ten_bo, j.tao_luc AS tao_luc_bo,
       t.giay_xu_ly, t.man_ket_agy,
       (SELECT max(net_la_pho_bien) FROM tl_vet x WHERE x.video_id = v.video_log_id) AS can_soi_ky,
       (SELECT max(pct_render) FROM tl_vet x WHERE x.video_id = v.video_log_id) AS pct_render,
       (SELECT count(*) FROM tl_box_moi b WHERE b.video_id = v.video_log_id) AS so_box,
       (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) AS danh_gia,
       t.duong_dan_sheet IS NOT NULL AS co_sheet
FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id LEFT JOIN tl_video t ON t.id = v.video_log_id
"""


def dang_ky_route_member(app: FastAPI, lay_log_db: Callable[[], object], require_user, la_admin,
                         lay_worker: Callable[[], object | None],
                         thu_vien_cua: Callable[[str, list[str]], set[str]],
                         lay_jobs_db: Callable[[], object] | None = None,
                         lay_drive: Callable[[], object] | None = None) -> None:
    """`lay_log_db` trả đường dẫn `thay_logo_log.db` LÚC GỌI; `lay_jobs_db` (tuỳ chọn) trả `jobs.db` để ghép thư viện — mặc định nằm cạnh `thay_logo_log.db`; mỗi request mở kết nối mới và tự đóng. `lay_worker` trả None khi
    tính năng TẮT ⇒ không nhận lượt mới (409), vẫn xem/đánh giá được kết quả cũ. `lay_drive` (tuỳ chọn) trả `DriveTL` cho `kiem-link`;
    mặc định dựng `DriveTLThat()` từ cùng cấu hình môi trường với worker."""

    def _mo() -> _sqlite3.Connection:
        conn = nhat_ky.mo(lay_log_db())
        hang_doi.khoi_tao(conn)
        return conn

    def _video_cua(conn, vid: int, email: str):
        r = conn.execute(_SQL_DANH_SACH + " WHERE v.id = ?", (vid,)).fetchone()
        if r is None:
            raise HTTPException(404, "không có video này")
        if r["nguoi_tao"] != email and not la_admin(email):
            raise HTTPException(403, "chỉ người tạo lượt hoặc quản trị")
        return r

    @app.post("/api/thay-logo/jobs", status_code=201)
    def tao_job(body: TaoJobThayLogo, email: str = Depends(require_user)) -> dict:
        w = lay_worker()
        if w is None:
            raise HTTPException(409, "Tính năng thay logo đang tắt trên máy chủ.")
        if getattr(w, "ly_do_khong_nhan", None):  # cổng cấu hình đã CẤM hẳn; chi tiết thư mục chỉ admin thấy (admin/worker)
            raise HTTPException(409, "Tính năng thay logo tạm tắt do cấu hình máy chủ — báo quản trị.")
        if not all(_DRIVE_ID.match(f) for f in body.drive_file_ids):
            raise HTTPException(400, "mã file Drive sai khuôn")
        ten_bo = _kiem_ten_bo(body.ten_bo)
        ids = list(dict.fromkeys(body.drive_file_ids))
        # Member chỉ được thay logo video trong thư viện CỦA MÌNH: service account đọc được mọi file nó được chia sẻ, nên
        # không kiểm thì biết ID là lấy được bản copy video của người khác. Admin được dán ID bất kỳ.
        trong = thu_vien_cua(email, ids)  # id thuộc thư viện CỦA người tạo — dùng chung cho cổng quyền và nhãn nguồn
        if not la_admin(email) and not _ids_duoc_phep(email, ids, trong):
            raise HTTPException(403, "Chỉ chọn được video trong thư viện của bạn hoặc link bạn đã kiểm trong 24 giờ qua — nếu dán link lâu rồi, bấm Kiểm link lại.")
        conn = _mo()
        try:
            # Khoá ghi TRƯỚC khi đếm: hai POST cùng lúc của một người không cùng đọc "chưa có chờ" rồi cùng tạo (vượt trần).
            # `tao_job` tự commit ⇒ khoá nhả ngay sau khi lượt được ghi; nhánh 429 phải rollback để nhả.
            conn.execute("BEGIN IMMEDIATE")
            if hang_doi.dem_dang_cho_cua(conn, email) + len(ids) > TRAN_CHO_MOI_NGUOI:
                conn.rollback()
                raise HTTPException(429, f"Bạn đang có quá nhiều video chờ (tối đa {TRAN_CHO_MOI_NGUOI}).")
            # `kieu` chỉ là NHÃN nguồn (thẻ bộ đọc nó); worker tải theo `file_id` cho mọi kiểu. Ngoài thư viện của người tạo
            # ⇒ "link" (đến qua sổ kiem-link, hoặc admin dán id) — ghi "drive" cho mọi id làm thẻ bộ nói "Thư viện" sai sự thật.
            nguon = [{"kieu": "drive" if f in trong else "link", "file_id": f} for f in ids]
            jid = hang_doi.tao_job(conn, email, nguon, body.ghi_chu, ten_bo)
        finally:
            conn.close()
        return {"job_id": jid}

    def _jobs_db():
        return Path(lay_jobs_db()) if lay_jobs_db else Path(lay_log_db()).parent / "jobs.db"

    @app.get("/api/thay-logo/bo")
    def danh_sach_bo(email: str = Depends(require_user)) -> dict:
        """Bộ (= job) của người gọi, admin: mọi người. Đếm từ `tl_job_video` theo `job_id`."""
        if not os.path.exists(lay_log_db()):
            return {"bo": []}
        dk, tham = ("", []) if la_admin(email) else (" WHERE j.nguoi_tao = ?", [email])
        conn = _mo()
        try:
            rows = conn.execute(
                "SELECT j.id AS job_id, j.ten_bo, j.tao_luc, j.thu_muc_ra_id, j.nguoi_tao, count(v.id) AS tong, "
                "coalesce(sum(v.trang_thai = 'xong'), 0) AS xong, coalesce(sum(v.trang_thai = 'cho_nguoi'), 0) AS cho_nguoi, "
                "coalesce(sum(v.trang_thai = 'loi'), 0) AS loi, "
                "coalesce(sum(v.trang_thai = 'xong' AND v.dg IS NULL), 0) AS cho_duyet, "
                "coalesce(sum(v.trang_thai = 'xong' AND v.dg = 'dat'), 0) AS dat, "
                "coalesce(sum(v.trang_thai = 'xong' AND v.dg = 'hong'), 0) AS hong "
                "FROM tl_job j LEFT JOIN (SELECT t.*, (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = t.video_log_id "
                "ORDER BY luc DESC LIMIT 1) AS dg FROM tl_job_video t) v ON v.job_id = j.id"
                f"{dk} GROUP BY j.id ORDER BY j.id DESC LIMIT 200", tham).fetchall()
            # Nguồn của bộ = tập `kieu` của MỌI video: một kiểu ⇒ kiểu đó; trộn (vd thư viện + link) ⇒ "nhieu". Lấy video đầu
            # làm đại diện thì lượt trộn hiện sai nguồn.
            cac_kieu: dict[int, set] = {}
            ids_trang = [r["job_id"] for r in rows]
            for r in conn.execute(f"SELECT job_id, nguon FROM tl_job_video WHERE job_id IN ({','.join('?' * len(ids_trang))})",
                                  ids_trang):
                try:
                    k = json.loads(r["nguon"]).get("kieu")
                except (ValueError, AttributeError):
                    k = None
                cac_kieu.setdefault(r["job_id"], set()).add(k)
            kieu = {j: (next(iter(ks)) if len(ks) == 1 else "nhieu") for j, ks in cac_kieu.items()}
        finally:
            conn.close()
        return {"bo": [{"job_id": r["job_id"], "ten_bo": hang_doi.ten_bo_hien_thi(r["job_id"], r["ten_bo"]),
                        "nguon_kieu": kieu.get(r["job_id"]), "tao_luc": r["tao_luc"], "tong": r["tong"], "xong": r["xong"],
                        "cho_duyet": r["cho_duyet"], "cho_nguoi": r["cho_nguoi"], "loi": r["loi"], "dat": r["dat"],
                        "hong": r["hong"], "thu_muc_ra_id": r["thu_muc_ra_id"], "nguoi_tao": r["nguoi_tao"]} for r in rows]}

    def _ten_tu_link(lo: list[dict], tv: dict) -> dict[tuple[str, str], str | None]:
        """{(email người tạo lượt, file_id): tên} cho dòng KHÔNG có trong thư viện CỦA người tạo lượt nhưng CHÍNH người tạo đã kiểm qua `kiem-link`."""
        theo_nguoi: dict[str, list[str]] = {}
        for d in lo:
            if d["_fid"] and _thu_vien_cua_chu(tv, d["_fid"], d["nguoi_tao"]) is None:
                theo_nguoi.setdefault(d["nguoi_tao"], []).append(d["_fid"])
        if not theo_nguoi:
            return {}
        conn = _mo()
        try:
            link_da_kiem.khoi_tao(conn)
            return {(e, f): t for e, ids in theo_nguoi.items() for f, t in link_da_kiem.ten_da_kiem(conn, e, ids).items()}
        finally:
            conn.close()

    @app.get("/api/thay-logo/videos")
    def danh_sach(email: str = Depends(require_user), job_id: int | None = Query(default=None, ge=1, le=2**63 - 1),
                  trang_thai: str | None = None, nen_tang: str | None = None, tu: str | None = None, den: str | None = None,
                  truoc_id: int | None = Query(default=None, ge=1, le=2**63 - 1)) -> dict:
        """`truoc_id`: con trỏ keyset — chỉ lấy dòng có `v.id` < giá trị đó; lấy từ `truoc_tiep` của lần trước."""
        if not os.path.exists(lay_log_db()):  # tính năng chưa từng chạy ⇒ đừng tạo DB chỉ vì có người mở trang
            return {"videos": [], "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False}
        moc_tu, moc_den = _moc_thoi_gian(tu, "tu"), _moc_thoi_gian(den, "den", cuoi_ngay=True)
        dk, tham = [], []
        if not la_admin(email):  # CỔNG QUYỀN: member chỉ thấy video của lượt do mình tạo — mọi bộ lọc bên dưới chỉ THU HẸP thêm
            dk.append("j.nguoi_tao = ?")
            tham.append(email)
        if trang_thai is not None and trang_thai not in hang_doi.TRANG_THAI:
            raise HTTPException(400, f"trang_thai phải thuộc {sorted(hang_doi.TRANG_THAI)}")
        for cot, gia_tri in (("v.job_id", job_id), ("v.trang_thai", trang_thai)):
            if gia_tri is not None:
                dk.append(f"{cot} = ?")
                tham.append(gia_tri)
        if moc_tu is not None:
            dk.append("j.tao_luc >= ?")
            tham.append(moc_tu)
        if moc_den is not None:
            dk.append("j.tao_luc < ?")
            tham.append(moc_den)
        out: list[dict] = []
        truoc, da_quet, het, thu_vien_loi = truoc_id, 0, False, False
        while len(out) <= TRAN_TRANG_VIDEO and da_quet < TRAN_QUET_VIDEO:
            # Không lọc nền tảng ⇒ một lô 301 dòng là đủ (dòng 301 chỉ để biết còn nữa). Có lọc ⇒ đọc lô nối lô (keyset theo
            # `v.id`) tới khi đủ 301 dòng khớp hoặc hết dữ liệu — `nen_tang` nằm ở `jobs.db` nên không lọc được trong SQL.
            dk_lo, tham_lo = list(dk), list(tham)
            if truoc is not None:
                dk_lo.append("v.id < ?")
                tham_lo.append(truoc)
            conn = _mo()
            try:
                rows = conn.execute(_SQL_DANH_SACH + (" WHERE " + " AND ".join(dk_lo) if dk_lo else "") + " ORDER BY v.id DESC LIMIT ?",
                                    [*tham_lo, TRAN_TRANG_VIDEO + 1]).fetchall()
            finally:
                conn.close()
            lo = []
            for r in rows:
                d = {k: r[k] for k in r.keys()}
                d["ten_bo"] = hang_doi.ten_bo_hien_thi(r["job_id"], r["ten_bo"])
                try:
                    d["_fid"] = json.loads(r["nguon"]).get("file_id")
                except (ValueError, AttributeError):
                    d["_fid"] = None
                lo.append(d)
            tv = thong_tin_thu_vien(_jobs_db(), sorted({d["_fid"] for d in lo if d["_fid"]}))
            if tv is None:
                if nen_tang:  # lọc theo nền tảng mà không có thư viện ⇒ trả rỗng sẽ NÓI DỐI "không có video nào"
                    raise HTTPException(503, "Không đọc được thư viện video để lọc theo nền tảng.")
                thu_vien_loi, tv = True, {}
            ten_link = _ten_tu_link(lo, tv)
            for d in lo:
                fid = d.pop("_fid")
                t = _thu_vien_cua_chu(tv, fid, d["nguoi_tao"]) or {}  # file thư viện người KHÁC ⇒ coi như ngoài thư viện
                d["ten_video"] = (t.get("title") or "Video không tên") if t else None  # có hàng mà title NULL ⇒ vẫn có tên để hiện
                if not t and (d["nguoi_tao"], fid) in ten_link:  # video nhập từ link Drive: không ở thư viện, tên lấy từ sổ lúc kiểm
                    d["ten_video"] = ten_link[(d["nguoi_tao"], fid)] or "Video từ link Drive"
                d["anh_bia"] = f"/thumbs/{t['video_id']}" if t.get("video_id") else None
                d["nen_tang"] = t.get("nen_tang")
                if not nen_tang or d["nen_tang"] == nen_tang:
                    out.append(d)
            da_quet += len(rows)
            if len(rows) <= TRAN_TRANG_VIDEO:
                het = True  # hết dữ liệu
                break
            truoc = rows[-1]["id"]
        if len(out) > TRAN_TRANG_VIDEO:
            out, con_nua = out[:TRAN_TRANG_VIDEO], True
            truoc_tiep = out[-1]["id"]
        elif het:
            con_nua, truoc_tiep = False, None
        else:  # dừng vì chạm trần quét, chưa đủ dòng khớp: còn nữa CHỈ KHI thật còn dòng chưa đọc
            conn = _mo()
            try:
                dk_c, tham_c = [*dk, "v.id < ?"], [*tham, truoc]
                con_nua = conn.execute(_SQL_DANH_SACH + " WHERE " + " AND ".join(dk_c) + " LIMIT 1", tham_c).fetchone() is not None
            finally:
                conn.close()
            truoc_tiep = truoc if con_nua else None
        return {"videos": out, "con_nua": con_nua, "truoc_tiep": truoc_tiep, "thu_vien_loi": thu_vien_loi}

    @app.post("/api/thay-logo/videos/{vid}/danh-gia", status_code=204, response_model=None)
    def danh_gia(vid: int, body: DanhGia, email: str = Depends(require_user)) -> None:
        conn = _mo()
        try:
            r = _video_cua(conn, vid, email)
            if r["trang_thai"] != "xong":
                raise HTTPException(409, "chỉ đánh giá video đã thay xong")
            log_id = conn.execute("SELECT video_log_id FROM tl_job_video WHERE id=?", (vid,)).fetchone()[0]
            try:
                nhat_ky.ghi_danh_gia(conn, log_id, email, body.ket_qua, body.loai_loi, body.ghi_chu)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
        finally:
            conn.close()

    @app.get("/api/thay-logo/videos/{vid}/sheet.jpg")
    def anh_soi(vid: int, email: str = Depends(require_user)) -> Response:
        conn = _mo()
        try:
            _video_cua(conn, vid, email)
            p = conn.execute("SELECT t.duong_dan_sheet FROM tl_job_video v JOIN tl_video t ON t.id = v.video_log_id "
                             "WHERE v.id=?", (vid,)).fetchone()
        finally:
            conn.close()
        if not p or not p[0] or not os.path.isfile(p[0]):
            raise HTTPException(404, "chưa có ảnh soi")
        with open(p[0], "rb") as f:
            return Response(f.read(), media_type="image/jpeg")

    @app.get("/api/thay-logo/logo.png")
    def logo_mac_dinh(email: str = Depends(require_user)) -> Response:
        p = os.path.join(os.path.dirname(hang_doi.__file__), "tai_nguyen", "logo_A2_tam_nen.png")
        with open(p, "rb") as f:
            return Response(f.read(), media_type="image/png")

    @app.get("/api/thay-logo/admin/worker")
    def trang_thai_worker(email: str = Depends(require_user)) -> dict:
        if not la_admin(email):
            raise HTTPException(403, "chỉ quản trị")
        w = lay_worker()
        return w.trang_thai() if w is not None else {"song": False, "luot_cuoi": "tinh_nang_tat"}

    # ------------------------------------------------------------------ nguồn "Dán link Drive": kiểm link + quyền dùng id đã kiểm
    def _ids_duoc_phep(email: str, ids: list[str], trong: set[str]) -> bool:
        """Member: MỌI id phải thuộc thư viện của mình (`trong` = `thu_vien_cua(email, ids)`), HOẶC do CHÍNH mình kiểm qua
        `kiem-link` trong 24 h (`link_da_kiem`). Id thô không qua bước kiểm ⇒ False (đường duy nhất vào là có nhật ký ai thêm gì)."""
        con_lai = [i for i in ids if i not in trong]
        if not con_lai:
            return True
        conn = _mo()
        try:
            link_da_kiem.khoi_tao(conn)
            return link_da_kiem.con_han(conn, email, con_lai) == set(con_lai)
        finally:
            conn.close()

    @app.post("/api/thay-logo/kiem-link")
    def kiem_link(body: KiemLink, email: str = Depends(require_user)) -> dict:
        """Mỗi dòng link ⇒ một kết quả (`nhan` | `khong_mo_duoc` | `khong_hop_le` | `loi_tam`); xem `thay_logo/nguon_drive.py`.
        Chỉ ĐỌC Drive. Id file nhận được ghi vào sổ của CHÍNH người gọi để `POST /jobs` chấp nhận trong 24 h."""
        w = lay_worker()
        if w is None:
            raise HTTPException(409, "Tính năng thay logo đang tắt trên máy chủ.")
        if getattr(w, "ly_do_khong_nhan", None):  # cùng cổng với POST /jobs: cấu hình đang CẤM thì đừng nhận link để rồi không dùng được
            raise HTTPException(409, "Tính năng thay logo tạm tắt do cấu hình máy chủ — báo quản trị.")
        if sum(len(x) for x in body.links) > 40_000:
            raise HTTPException(400, "Nội dung dán quá dài.")
        dong = nguon_drive.tach_dong(body.links)
        if not dong:
            raise HTTPException(400, "Chưa có link nào.")
        if len(dong) > nguon_drive.TRAN_LINK_MOT_LUOT:
            raise HTTPException(400, f"Mỗi lần kiểm tối đa {nguon_drive.TRAN_LINK_MOT_LUOT} link.")
        drive = lay_drive() if lay_drive else DriveTLThat()
        if not drive.dang_cau_hinh():
            raise HTTPException(409, "Máy chủ chưa nối được Google Drive — báo quản trị.")
        kq = nguon_drive.kiem_cac_link(drive, dong)
        muc = nguon_drive.muc_duoc_nhan(kq["ket_qua"])
        conn = _mo()
        try:
            link_da_kiem.khoi_tao(conn)
            link_da_kiem.ghi_da_kiem(conn, email, muc)
        finally:
            conn.close()
        return {**kq, "da_ghi_nhan": len(muc)}
