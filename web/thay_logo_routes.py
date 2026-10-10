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
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from tiktok_music_downloader.thay_logo import ap_vao_bo, hang_doi, link_da_kiem, nguon_drive, nhat_ky
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


class MucVaoBo(BaseModel):
    """Một video chọn từ tab "Đã vào bộ": máy dùng BẢN TRONG BỘ (`ban_copy_id`), không dùng file nguồn thư viện (có thể đã dọn)."""
    video_id: str = Field(min_length=1, max_length=120)
    ban_copy_id: str = Field(min_length=1, max_length=120)


class TaoJobThayLogo(BaseModel):
    drive_file_ids: list[str] = Field(default_factory=list, max_length=TRAN_VIDEO_MOT_JOB)
    vao_bo: list[MucVaoBo] = Field(default_factory=list, max_length=TRAN_VIDEO_MOT_JOB)
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
       t.duong_dan_sheet IS NOT NULL AS co_sheet,
       t.duong_dan_truoc IS NOT NULL AS co_truoc, t.duong_dan_sau IS NOT NULL AS co_sau, t.box_logo AS box_logo_json
FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id LEFT JOIN tl_video t ON t.id = v.video_log_id
"""


def dang_ky_route_member(app: FastAPI, lay_log_db: Callable[[], object], require_user, la_admin,
                         lay_worker: Callable[[], object | None],
                         thu_vien_cua: Callable[[str, list[str]], set[str]],
                         lay_jobs_db: Callable[[], object] | None = None,
                         lay_drive: Callable[[], object] | None = None) -> None:
    """`lay_log_db` trả đường dẫn `thay_logo_log.db` LÚC GỌI; `lay_jobs_db` (tuỳ chọn) trả `jobs.db` để ghép thư viện — mặc định nằm cạnh `thay_logo_log.db`; mỗi request mở kết nối mới và tự đóng. `lay_worker` trả None khi
    tính năng TẮT ⇒ không nhận lượt mới (409), vẫn xem/đánh giá được kết quả cũ. `lay_drive` (tuỳ chọn, cho test) trả `DriveTL` cho `kiem-link`;
    mặc định dùng `worker.drive_tl` — CÙNG adapter worker dùng để tải/chụp nguồn (dựng `DriveTLThat()` chỉ khi worker không có)."""

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
        if not all(_DRIVE_ID.match(f) for f in body.drive_file_ids) or not all(_DRIVE_ID.match(m.ban_copy_id) for m in body.vao_bo):
            raise HTTPException(400, "mã file Drive sai khuôn")
        ten_bo = _kiem_ten_bo(body.ten_bo)
        ids = list(dict.fromkeys(body.drive_file_ids))
        vao_bo = list({m.ban_copy_id: m for m in body.vao_bo}.values())
        if not ids and not vao_bo:
            raise HTTPException(422, "chưa chọn video nào")
        if len(ids) + len(vao_bo) > TRAN_VIDEO_MOT_JOB:
            raise HTTPException(422, f"tối đa {TRAN_VIDEO_MOT_JOB} video mỗi lượt")
        # Member chỉ được thay logo video trong thư viện CỦA MÌNH: service account đọc được mọi file nó được chia sẻ, nên
        # không kiểm thì biết ID là lấy được bản copy video của người khác. Admin được dán ID bất kỳ.
        trong = thu_vien_cua(email, ids)  # id thuộc thư viện CỦA người tạo — dùng chung cho cổng quyền và nhãn nguồn
        if ids and not la_admin(email) and not _ids_duoc_phep(email, ids, trong):
            raise HTTPException(403, "Chỉ chọn được video trong thư viện của bạn hoặc link bạn đã kiểm trong 24 giờ qua — nếu dán link lâu rồi, bấm Kiểm link lại.")
        # Bản trong bộ: chủ = người tạo lượt đã tải video đó (`jobs.nguoi_tao`, cùng định nghĩa với `list_videos`). `video_vao_bo.chu`
        # (nullable) chỉ để ĐỐI CHIẾU: có giá trị mà khác `nguoi_tao` ⇒ 403; NULL ⇒ cho qua. Admin được tạo lượt cho video người khác
        # (lượt chỉ đọc; việc ÁP vào bộ sẽ chặn theo `chu_video`). Kiểm TRƯỚC khi gọi Drive: không có quyền ⇒ không tốn lời gọi Drive.
        # Admin được TẠO lượt vao_bo cho video người khác là lựa chọn của lane; KHÔNG mở quyền ÁP vào bộ người khác — áp vẫn chỉ chủ video (đợt 2).
        ban = _ban_vao_bo_cua(_jobs_db(), None if la_admin(email) else email, vao_bo) if vao_bo else {}
        # Ảnh chụp nguồn (md5/size/folder) lúc tạo lượt: đợt áp vào bộ đối chiếu với nó trước khi thay bản trong bộ.
        so_moi = len(ids) + len(vao_bo)
        conn = _mo()
        try:
            # Trần kiểm HAI lần: (1) sơ bộ, không khoá, TRƯỚC Drive — quá trần thì không tốn lời gọi Drive nào;
            # (2) chính thức trong khoá ghi bên dưới (chống hai POST cùng lúc).
            if hang_doi.dem_dang_cho_cua(conn, email) + so_moi > TRAN_CHO_MOI_NGUOI:
                raise HTTPException(429, f"Bạn đang có quá nhiều video chờ (tối đa {TRAN_CHO_MOI_NGUOI}).")
            _chan_ban_da_trong_luot(conn, ban)  # sơ bộ: bản đã nằm trong lượt khác ⇒ 409 trước khi tốn lời gọi Drive
            # Chụp TRƯỚC khoá ghi: lời gọi Drive có hạn tới ~60 s, giữ BEGIN IMMEDIATE trong lúc đó là chặn mọi POST /jobs khác.
            chup_vao_bo = _chup_nguon_vao_bo(getattr(w, "drive_tl", None), ban) if ban else []
            # Khoá ghi rồi kiểm LẠI ngay trước khi tạo: hai POST cùng lúc không cùng đọc "chưa có chờ" (vượt trần), và Drive chậm
            # thì lượt khác có thể đã giữ bản trong bộ này trong lúc chờ. `tao_job` tự commit ⇒ khoá nhả ngay; lỗi ⇒ rollback.
            conn.execute("BEGIN IMMEDIATE")
            if hang_doi.dem_dang_cho_cua(conn, email) + so_moi > TRAN_CHO_MOI_NGUOI:
                conn.rollback()
                raise HTTPException(429, f"Bạn đang có quá nhiều video chờ (tối đa {TRAN_CHO_MOI_NGUOI}).")
            try:
                _chan_ban_da_trong_luot(conn, ban)
            except HTTPException:
                conn.rollback()
                raise
            # `kieu` chỉ là NHÃN nguồn (thẻ bộ đọc nó); worker tải theo `file_id` cho mọi kiểu. Ngoài thư viện của người tạo
            # ⇒ "link" (đến qua sổ kiem-link, hoặc admin dán id) — ghi "drive" cho mọi id làm thẻ bộ nói "Thư viện" sai sự thật.
            nguon = [{"kieu": "drive" if f in trong else "link", "file_id": f} for f in ids] + chup_vao_bo
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
                    ng = json.loads(r["nguon"])
                    d["_fid"], d["_vid"] = ng.get("file_id"), (ng.get("video_id") if ng.get("kieu") == "vao_bo" else None)
                except (ValueError, AttributeError):
                    d["_fid"], d["_vid"] = None, None
                co_truoc, co_sau = d.pop("co_truoc"), d.pop("co_sau")  # pop CẢ HAI trước khi `and` (short-circuit làm rò khoá thô)
                d["co_truoc"], d["co_truoc_sau"] = bool(co_truoc), bool(co_truoc and co_sau)
                d["box_logo"] = _box_logo(d.pop("box_logo_json"))
                lo.append(d)
            # Nguồn thư viện: ghép theo `drive_file_id`. Nguồn "Đã vào bộ": `file_id` là bản trong bộ (không có trong thư viện)
            # ⇒ ghép theo `video_id` đã chụp lúc tạo lượt.
            tv = thong_tin_thu_vien(_jobs_db(), sorted({d["_fid"] for d in lo if d["_fid"] and not d["_vid"]}))
            tv_vb = thong_tin_theo_video(_jobs_db(), sorted({d["_vid"] for d in lo if d["_vid"]}))
            if tv is None or tv_vb is None:
                if nen_tang:  # lọc theo nền tảng mà không có thư viện ⇒ trả rỗng sẽ NÓI DỐI "không có video nào"
                    raise HTTPException(503, "Không đọc được thư viện video để lọc theo nền tảng.")
                thu_vien_loi, tv, tv_vb = True, {}, {}
            # Tên từ sổ link chỉ cho dòng ghép theo file_id (bản trong bộ đã có tên qua `video_id`).
            ten_link = _ten_tu_link([d for d in lo if not d["_vid"]], tv)
            for d in lo:
                fid, vid_nguon = d.pop("_fid"), d.pop("_vid")
                # Bản trong bộ: ghép theo `video_id` đã chụp (chủ đã kiểm lúc tạo lượt). Theo file_id: CHỈ khi thuộc thư viện
                # của người tạo lượt — file thư viện người KHÁC ⇒ coi như ngoài thư viện.
                t = (tv_vb.get(vid_nguon) if vid_nguon else _thu_vien_cua_chu(tv, fid, d["nguoi_tao"])) or {}
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
        # MỘT nguồn Drive: adapter của worker (cùng credential/uploader với lúc tải và chụp nguồn "Đã vào bộ"); `lay_drive` chỉ để test.
        drive = lay_drive() if lay_drive else (getattr(w, "drive_tl", None) or DriveTLThat())
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
    # ======================================================== đợt 1b: ảnh trước/sau + tab "Đã vào bộ" (route MỚI, thêm cuối)
    @app.get("/api/thay-logo/videos/{vid}/khung/{ten}")
    def anh_truoc_sau(vid: int, ten: str, email: str = Depends(require_user)) -> Response:
        """`truoc.jpg` / `sau.jpg` của video — cùng cổng quyền `_video_cua` (chủ lượt hoặc admin). Chưa có ⇒ 404."""
        if ten not in ("truoc.jpg", "sau.jpg"):
            raise HTTPException(404, "không có ảnh này")
        conn = _mo()
        try:
            _video_cua(conn, vid, email)
            p = conn.execute("SELECT t.duong_dan_truoc, t.duong_dan_sau FROM tl_job_video v JOIN tl_video t ON t.id = v.video_log_id "
                             "WHERE v.id=?", (vid,)).fetchone()
        finally:
            conn.close()
        duong = (p[0] if ten == "truoc.jpg" else p[1]) if p else None
        if not duong:
            raise HTTPException(404, "chưa có ảnh trước/sau")
        try:  # file có thể vừa bị dọn giữa lúc kiểm và lúc mở ⇒ 404, không 500
            with open(duong, "rb") as f:
                return Response(f.read(), media_type="image/jpeg")
        except OSError:
            raise HTTPException(404, "chưa có ảnh trước/sau") from None

    @app.get("/api/thay-logo/da-vao-bo")
    def da_vao_bo(email: str = Depends(require_user)) -> dict:
        """Video ĐÃ VÀO BỘ của chính người gọi (admin: tất cả), nhóm theo bộ. Chủ = `jobs.nguoi_tao` của video (không dùng
        `video_vao_bo.chu`). `da_trong_luot` = video này đã có trong một lượt thay logo còn hiệu lực (chưa lỗi)."""
        chu = None if la_admin(email) else email
        try:
            hang = _doc_da_vao_bo(_jobs_db(), chu)
            bi_cat = len(hang) > TRAN_DONG_DA_VAO_BO  # đọc dư 1 dòng để biết danh sách còn dài hơn trần
            hang = hang[:TRAN_DONG_DA_VAO_BO]
        except _sqlite3.Error as e:
            log.warning("thay logo: không đọc được sổ đã-vào-bộ (%s)", type(e).__name__)
            raise HTTPException(503, "Chưa đọc được danh sách bộ — thử lại sau ít phút.") from None
        trong_ban, trong_nguon, da_ap = set(), set(), set()
        if os.path.exists(lay_log_db()):
            conn = _mo()
            try:
                trong_ban, trong_nguon = _nguon_dang_trong_luot(conn, chu)
                da_ap = ap_vao_bo.ban_da_ap(conn) if ap_vao_bo.dang_bat() else set()  # cờ tắt ⇒ không tạo bảng tl_ap_bo
            finally:
                conn.close()
        nhom: dict[str, dict] = {}
        for r in hang:
            b = nhom.setdefault(r["folder_id"], {"ma_bo": r["ma_bo"], "folder_id": r["folder_id"], "vao_bo_luc": r["thay_luc"],
                                                  "videos": []})
            b["vao_bo_luc"] = min(b["vao_bo_luc"], r["thay_luc"])
            b["videos"].append({
                "video_id": r["video_id"], "ban_copy_id": r["ban_copy_id"], "ten_video": r["title"] or "Video không tên",
                "anh_bia": f"/thumbs/{r['video_id']}", "nen_tang": r["nen_tang"], "vao_bo_luc": r["thay_luc"],
                "da_trong_luot": r["ban_copy_id"] in trong_ban | trong_nguon or (r["drive_file_id"] in trong_nguon if r["drive_file_id"] else False),
                "da_ap": r["ban_copy_id"] in da_ap})
        return {"bo": sorted(nhom.values(), key=lambda b: b["vao_bo_luc"], reverse=True), "bi_cat": bi_cat}

    # ======================================================== đợt 2A: áp vào bộ + hoàn tác (route MỚI, thêm cuối; cờ `TL_AP_VAO_BO`)
    # Route trả 202 sau khi kiểm TẦNG DB + lấy khoá bộ + ghi chiều ý định; Drive chạy ở thread `tl-ap` của worker (không trong request:
    # 50 video × vài lời gọi Drive vượt trần ~100 s của Cloudflare). Cờ TẮT ⇒ 404 (như route không tồn tại), không đụng DB/Drive.
    ID_LUOT = PathParam(ge=1, le=2**63 - 1)

    def _cong_ap() -> None:
        if not ap_vao_bo.dang_bat():
            raise HTTPException(404, "Not Found")

    def _worker_ap():
        w = lay_worker()
        drive = getattr(w, "drive_tl", None) if w is not None else None
        if drive is None or not callable(getattr(w, "bat_dau_ap", None)) or not drive.dang_cau_hinh():
            raise HTTPException(503, "Máy chủ chưa nối được Google Drive — báo quản trị.")
        return w

    def _chu_cua(video_ids: list[str]) -> dict:
        r = chu_video_vao_bo(_jobs_db(), video_ids)
        if r is None:
            raise HTTPException(503, "Chưa kiểm được chủ video — thử lại sau ít phút.")
        return r

    def _chi_chu_luot(job_id: int, email: str) -> None:
        """Quyền TRƯỚC mọi thứ khác (kể cả kiểm Drive): người không phải chủ lượt nhận 403/404, không nhận 503 lộ cấu hình máy chủ."""
        if not os.path.exists(lay_log_db()):
            raise HTTPException(404, "không có lượt này")
        conn = _mo()
        try:
            chu = ap_vao_bo.chu_job(conn, job_id)
        except ap_vao_bo.LoiAp as e:
            raise HTTPException(e.ma, str(e)) from None
        finally:
            conn.close()
        if chu != email:
            raise HTTPException(403, "chỉ người tạo lượt được áp vào bộ / hoàn tác")

    def _khoi_chay(w, job_id: int) -> None:
        try:
            w.bat_dau_ap(job_id)
        except Exception:  # thread không khởi được ⇒ nhả khoá ngay (chiều ý định đã ghi; "Tiếp tục" chạy lại theo phép đo)
            log.exception("thay logo áp: không khởi được thread cho lượt %s", job_id)
            conn = _mo()
            try:
                ap_vao_bo.nha_khoa(conn, job_id)
            finally:
                conn.close()
            raise HTTPException(500, "Không khởi chạy được — thử lại.") from None

    @app.post("/api/thay-logo/bo/{job_id}/ap", status_code=202)
    def ap_vao_bo_post(job_id: int = ID_LUOT, email: str = Depends(require_user)) -> dict:
        """Áp video Đạt của CHÍNH người gọi vào bộ (cũng là nút "Tiếp tục" khi lượt trước dở). Admin cũng không áp thay."""
        _cong_ap()
        _chi_chu_luot(job_id, email)
        w = _worker_ap()
        conn = _mo()
        try:
            kq = ap_vao_bo.dat_lich_ap(conn, job_id, email, _chu_cua)
        except ap_vao_bo.LoiAp as e:
            raise HTTPException(e.ma, str(e)) from None
        finally:
            conn.close()
        _khoi_chay(w, job_id)
        return kq

    @app.post("/api/thay-logo/bo/{job_id}/hoan-tac", status_code=202)
    def ap_vao_bo_hoan_tac(job_id: int = ID_LUOT, email: str = Depends(require_user)) -> dict:
        _cong_ap()
        _chi_chu_luot(job_id, email)
        w = _worker_ap()
        conn = _mo()
        try:
            kq = ap_vao_bo.dat_lich_hoan_tac(conn, job_id, email)
        except ap_vao_bo.LoiAp as e:
            raise HTTPException(e.ma, str(e)) from None
        finally:
            conn.close()
        _khoi_chay(w, job_id)
        return kq

    @app.get("/api/thay-logo/bo/{job_id}/ap")
    def ap_vao_bo_get(job_id: int = ID_LUOT, email: str = Depends(require_user)) -> dict:
        """Tiến độ áp/hoàn tác của bộ — chủ lượt hoặc admin (admin CHỈ ĐỌC: `la_chu=false`, không có số video áp được)."""
        _cong_ap()
        if not os.path.exists(lay_log_db()):
            raise HTTPException(404, "không có lượt này")
        conn = _mo()
        try:
            try:
                chu = ap_vao_bo.chu_job(conn, job_id)
            except ap_vao_bo.LoiAp as e:
                raise HTTPException(e.ma, str(e)) from None
            if chu != email and not la_admin(email):
                raise HTTPException(403, "chỉ người tạo lượt hoặc quản trị")
            kq = ap_vao_bo.trang_thai(conn, job_id)
            ma_bo = sorted({v["nguon"].get("ma_bo") for v in ap_vao_bo.cac_video(conn, job_id)
                            if v["nguon"].get("kieu") == "vao_bo" and v["nguon"].get("ma_bo")})
            so, moi_chan = None, 0
            if chu == email:
                try:
                    pl = ap_vao_bo.phan_loai(conn, job_id, email, _chu_cua)
                    # Bộ đã áp: video MỚI bị chặn (hoàn tác trước), hàng dở/dùng lại vẫn áp được — đếm tách để UI vẽ đúng nút.
                    moi_chan = sum(1 for x in pl["lam"] if x[2] == "moi") if pl["da_ap"] else 0
                    so = len(pl["lam"]) - moi_chan
                except HTTPException:
                    so = None  # jobs.db tạm không đọc được: tiến độ vẫn trả, nút áp chờ lần sau
        finally:
            conn.close()
        return {**kq, "la_chu": chu == email, "ma_bo": ", ".join(ma_bo), "so_du_dieu_kien": so,
                "so_moi_bi_chan": moi_chan}


# ============================================================================ trợ giúp đợt 1b (module-level; gọi LÚC CHẠY)
TRAN_DONG_DA_VAO_BO = 3000  # trần số bản sao đọc cho tab "Đã vào bộ" (chống quét cả sổ)


def _box_logo(chuoi: str | None) -> dict | None:
    """JSON {x,y,w,h} tỉ lệ 0–1 lưu trong nhật ký ⇒ dict; hỏng/ngoài miền ⇒ None (hộp duyệt rơi về không phóng to)."""
    if not chuoi:
        return None
    try:
        b = json.loads(chuoi)
        v = {k: float(b[k]) for k in ("x", "y", "w", "h")}
    except (ValueError, TypeError, KeyError):
        return None
    if not all(math.isfinite(x) and 0.0 <= x <= 1.0 for x in v.values()) or v["w"] <= 0 or v["h"] <= 0:
        return None
    return v


def thong_tin_theo_video(jobs_db, video_ids: list[str]) -> dict[str, dict] | None:
    """Như `thong_tin_thu_vien` nhưng ghép theo `video_id`: → {video_id: {video_id, title, nen_tang}}. Không đọc được ⇒ None."""
    out: dict[str, dict] = {}
    if not video_ids:
        return out
    try:
        with closing(_sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5)) as c:
            for i in range(0, len(video_ids), 500):
                lo = video_ids[i:i + 500]
                for vid, title, nen_tang in c.execute(
                        "SELECT v.video_id, v.title, j.nen_tang FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
                        f"WHERE v.video_id IN ({','.join('?' * len(lo))})", lo):
                    out[vid] = {"video_id": vid, "title": title, "nen_tang": nen_tang}
    except _sqlite3.Error as e:
        log.warning("thay logo: không đọc được thư viện theo video_id %s (%s)", jobs_db, type(e).__name__)
        return None
    return out


def _doc_da_vao_bo(jobs_db, nguoi_tao: str | None) -> list[dict]:
    """Bản sao trong bộ của các video thuộc `nguoi_tao` (None = mọi người). `jobs.db` mở CHỈ ĐỌC; lỗi sqlite ném lên."""
    dk, tham = ("", []) if nguoi_tao is None else (" WHERE j.nguoi_tao = ?", [nguoi_tao])
    with closing(_sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5)) as c:
        c.row_factory = _sqlite3.Row
        rows = c.execute(
            "SELECT b.video_id, b.ban_copy_id, b.folder_id, b.ma_bo, b.thay_luc, v.title, v.drive_file_id, j.nen_tang "
            "FROM video_vao_bo_ban b JOIN videos v ON v.video_id = b.video_id JOIN jobs j ON j.id = v.job_id"
            f"{dk} ORDER BY b.thay_luc DESC, b.ban_copy_id LIMIT ?", [*tham, TRAN_DONG_DA_VAO_BO + 1]).fetchall()
    return [dict(r) for r in rows]


def _nguon_dang_trong_luot(conn, nguoi_tao: str | None) -> tuple[set[str], set[str]]:
    """(các `ban_copy_id`, các `file_id` thư viện) đã nằm trong một lượt chưa lỗi của `nguoi_tao` (None = mọi người)."""
    dk, tham = ("", []) if nguoi_tao is None else (" AND j.nguoi_tao = ?", [nguoi_tao])
    ban, thu_vien = set(), set()
    for (nguon,) in conn.execute("SELECT v.nguon FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id "
                                 f"WHERE v.trang_thai != 'loi'{dk}", tham):
        try:
            n = json.loads(nguon)
        except ValueError:
            continue
        if isinstance(n, dict) and n.get("file_id"):
            (ban if n.get("kieu") == "vao_bo" else thu_vien).add(n["file_id"])
    return ban, thu_vien


def _ban_vao_bo_cua(jobs_db, nguoi_tao: str | None, muc: list[MucVaoBo]) -> dict[str, dict]:
    """Mỗi `(video_id, ban_copy_id)` phải là bản sao của video THUỘC `nguoi_tao` (None = admin, bất kỳ). Một mục không đạt ⇒ 403 cho
    cả lượt (không phân biệt "của người khác" với "không có" — không lộ sự tồn tại). Trả {ban_copy_id: {video_id, folder_id, ma_bo}}."""
    if not muc:
        return {}
    dk, tham = ("", []) if nguoi_tao is None else (" AND j.nguoi_tao = ?", [nguoi_tao])
    try:
        with closing(_sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5)) as c:
            c.row_factory = _sqlite3.Row
            rows = c.execute(
                "SELECT b.video_id, b.ban_copy_id, b.folder_id, b.ma_bo, j.nguoi_tao AS chu_video, v.drive_file_id AS file_id_nguon, "
                "vb.chu AS chu_so "
                "FROM video_vao_bo_ban b JOIN videos v ON v.video_id = b.video_id JOIN jobs j ON j.id = v.job_id "
                "LEFT JOIN video_vao_bo vb ON vb.video_id = b.video_id "
                f"WHERE b.ban_copy_id IN ({','.join('?' * len(muc))}){dk}", [m.ban_copy_id for m in muc] + tham).fetchall()
    except _sqlite3.Error as e:
        log.warning("thay logo: không đọc được sổ đã-vào-bộ (%s)", type(e).__name__)
        raise HTTPException(503, "Chưa kiểm được video đã vào bộ — thử lại sau ít phút.") from None
    co = {r["ban_copy_id"]: dict(r) for r in rows}
    for m in muc:
        r = co.get(m.ban_copy_id)
        if r is None or r["video_id"] != m.video_id or (r["chu_so"] and r["chu_so"] != r["chu_video"]):
            raise HTTPException(403, "Chỉ chọn được video đã vào bộ của bạn.")
    return {m.ban_copy_id: co[m.ban_copy_id] for m in muc}


SO_LUONG_CHUP_DRIVE = 6  # số lời gọi Drive song song khi chụp nguồn
HAN_CHUP_GIAY = 50.0      # hạn CHUNG cho cả đợt chụp (< 60 s: dưới trần của Cloudflare/trình duyệt); hết hạn ⇒ 503, không tạo lượt


def _chan_ban_da_trong_luot(conn, ban: dict[str, dict]) -> None:
    """Một bản trong bộ chỉ được nằm trong MỘT lượt chưa lỗi (của bất kỳ ai): lượt thứ hai cùng bản ⇒ 409. So với CẢ hai tập: bản trong bộ
    có thể đã vào lượt khác qua đường link (kiểu `link`, file_id = ban_copy_id) — chiều ngược (dán link một bản đang giữ) KHÔNG chặn ở đây."""
    if ban and set(ban) & set().union(*_nguon_dang_trong_luot(conn, None)):
        raise HTTPException(409, "Một số video đã nằm trong một lượt thay logo khác — chọn video khác hoặc đợi lượt đó xong.")


def _chup_nguon_vao_bo(drive, ban: dict[str, dict]) -> list[dict]:
    """Chụp lúc TẠO lượt (đợt áp vào bộ đối chiếu với ảnh chụp này): md5 + size + thư mục cha của bản trong bộ, đọc từ Drive.
    Chụp SONG SONG với hạn chung `HAN_CHUP_GIAY`; hết hạn hoặc Drive lỗi tạm ⇒ 503 (không tạo lượt). Bản đã vào thùng rác / không
    còn trong thư mục bộ / không có md5 ⇒ 400 (video đã chọn không còn hợp lệ)."""
    if not ban:
        return []
    if drive is None:
        raise HTTPException(503, "Chưa đọc được Drive — thử lại sau ít phút.")
    from concurrent.futures import ThreadPoolExecutor, wait
    from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongThay
    pool = ThreadPoolExecutor(max_workers=min(SO_LUONG_CHUP_DRIVE, len(ban)), thread_name_prefix="tl-chup")
    try:
        viec = {ban_id: pool.submit(drive.lay_muc, ban_id) for ban_id in ban}
        _, chua_xong = wait(viec.values(), timeout=HAN_CHUP_GIAY)
        if chua_xong:
            log.warning("thay logo: chụp nguồn vào-bộ quá %.0fs (%d/%d xong)", HAN_CHUP_GIAY, len(viec) - len(chua_xong), len(viec))
            raise HTTPException(503, "Chưa hỏi được Drive lúc này — thử lại sau ít phút.")
        out = []
        for ban_id, r in ban.items():
            try:
                m = viec[ban_id].result()
            except DriveTLKhongThay:
                raise HTTPException(400, "Bản trong bộ của một video đã chọn không còn nữa.") from None
            except Exception as e:  # noqa: BLE001 — Drive lỗi/timeout: chưa chụp được ⇒ không tạo lượt (khác "bản đã mất")
                log.warning("thay logo: không đọc được bản trong bộ %s (%s)", ban_id, type(e).__name__)
                raise HTTPException(503, "Chưa hỏi được Drive lúc này — thử lại sau ít phút.") from None
            if m.get("trashed") or r["folder_id"] not in (m.get("parents") or []) or not m.get("md5Checksum") or not m.get("size"):
                raise HTTPException(400, "Bản trong bộ của một video đã chọn đã đổi hoặc không còn — tải lại danh sách rồi chọn lại.")
            out.append({"kieu": "vao_bo", "video_id": r["video_id"], "file_id": ban_id, "folder_id": r["folder_id"],
                        "ma_bo": r["ma_bo"], "md5": m["md5Checksum"], "size": str(m["size"]), "ten": m.get("name") or "",
                        "chu_video": r["chu_video"], "file_id_nguon": r["file_id_nguon"]})
        return out
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # lời gọi Drive đang treo không giữ request lại


def chu_video_vao_bo(jobs_db, video_ids: list[str]) -> dict[str, tuple[str | None, str | None]] | None:
    """{video_id: (jobs.nguoi_tao, video_vao_bo.chu)} đọc LÚC ÁP (không tin ảnh chụp). `jobs.db` mở CHỈ ĐỌC; lỗi ⇒ None (route 503)."""
    out: dict[str, tuple[str | None, str | None]] = {}
    if not video_ids:
        return out
    try:
        with closing(_sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=5)) as c:
            for i in range(0, len(video_ids), 500):
                lo = video_ids[i:i + 500]
                for vid, nguoi_tao, chu in c.execute(
                        "SELECT v.video_id, j.nguoi_tao, vb.chu FROM videos v JOIN jobs j ON j.id = v.job_id "
                        f"LEFT JOIN video_vao_bo vb ON vb.video_id = v.video_id WHERE v.video_id IN ({','.join('?' * len(lo))})", lo):
                    out[vid] = (nguoi_tao, chu)
    except _sqlite3.Error as e:
        log.warning("thay logo áp: không đọc được chủ video (%s)", type(e).__name__)
        return None
    return out
