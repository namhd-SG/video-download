"""CLI trên mini cho tầng hình (chạy ở máy dev, gọi qua ssh).

    python -m web.nhap_cum_cli cho-chia
    python -m web.nhap_cum_cli liet <job_id> [--nhan-ver V] [--caption-ver V]
    python -m web.nhap_cum_cli ten-co-san <job_id>
    python -m web.nhap_cum_cli ghi-dac-diem <job_id> <tệp.json | ->
    python -m web.nhap_cum_cli ghi <job_id> <tệp.json | ->

Vì sao CLI thay vì route HTTP: route trên mini nằm sau Cloudflare Access (JWT),
máy dev chỉ có ssh. Mọi lệnh đi qua ĐÚNG các hàm `models_chia` mà route dùng —
không có câu SQL ghi nháp thứ hai ở đây.

Kết quả (JSON) ra stdout; lời nhắn cho người đọc ra stderr, để stdout luôn
parse được. Mã thoát: 0 xong · 2 sai cú pháp lệnh/tham số · 3 không có job ·
4 tệp sai (không parse được, sai schema, id lạ) · 5 lượt đang có sửa tay, không
ghi đè · 6 lỗi DB.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from web import lifecycle, models, models_chia, models_cum, models_dac_diem

MA_OK = 0
MA_CU_PHAP = 2          # argparse tự trả mã này
MA_KHONG_CO_JOB = 3
MA_TEP_SAI = 4          # tệp không parse được / sai schema / id lạ
MA_NHAP_BI_CHAN = 5     # lượt hiện tại không nhận nháp mới (đã sửa tay)
MA_LOI_DB = 6

# Cùng chỗ `web/app.py::DB_PATH` — không import `web.app` vì nó dựng cả ứng
# dụng FastAPI chỉ để đọc một hằng số.
DB_MAC_DINH = Path(__file__).resolve().parent / "data" / "jobs.db"


class LoiTep(ValueError):
    """Tệp nhập không đúng hình dạng đã hẹn."""


def _in(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _bao(msg: str) -> None:
    print(msg, file=sys.stderr)


# --- đọc --------------------------------------------------------------------

def _cho_chia(db: Path) -> int:
    """Job `done` chưa có lượt chia nào ở `de_xuat`/`da_duyet`."""
    with models._connect(db) as conn:
        rows = conn.execute(
            "SELECT j.id, j.url, j.nguoi_tao FROM jobs j WHERE j.trang_thai = 'done' "
            "AND NOT EXISTS (SELECT 1 FROM chia_lan c WHERE c.job_id = j.id "
            "AND c.trang_thai IN ('de_xuat', 'da_duyet')) ORDER BY j.id").fetchall()
    _in([{"job_id": r["id"], "url": r["url"], "nguoi_tao": r["nguoi_tao"]} for r in rows])
    return MA_OK


def _anh_cua(db: Path, video_id: str) -> list[str]:
    """Đường dẫn TƯƠNG ĐỐI (từ thư mục chứa DB) của poster + khung phụ ĐANG CÓ
    trên đĩa — poster trước, khung theo thứ tự phần trăm."""
    goc = db.parent
    cac = [lifecycle.thumb_path_for(db, video_id)]
    cac += [lifecycle.khung_phu_path_for(db, video_id, pt) for pt in lifecycle.KHUNG_PHU_PHAN_TRAM]
    return [str(p.relative_to(goc)) for p in cac if p.is_file()]


def _liet(db: Path, job_id: int, nhan_ver: str | None, caption_ver: str | None) -> int:
    with models._connect(db) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            _bao(f"không có job {job_id}")
            return MA_KHONG_CO_JOB
        tong = conn.execute("SELECT COUNT(*) FROM videos WHERE job_id = ?",
                            (job_id,)).fetchone()[0]
        rows = models_chia.video_vao_luot_chia(conn, job_id)
        bi_loc = models_chia.dem_bi_loc_theo_ly_do(conn, job_id)
        # Lượt chia MỚI NHẤT của chủ job + số dòng nhật ký — cùng câu hỏi
        # `models_chia.nhap_de_xuat` dùng để quyết từ chối, để máy dev từ chối
        # TRƯỚC khi kéo ảnh / gọi agy thay vì trả tiền rồi mới bị chặn lúc ghi.
        lan = conn.execute(
            "SELECT c.id, c.trang_thai, (SELECT COUNT(*) FROM thao_tac_duyet t "
            "WHERE t.chia_lan_id = c.id) AS so_thao_tac FROM chia_lan c "
            "WHERE c.job_id = ? AND c.chu = ? ORDER BY c.tao_luc DESC, c.id DESC LIMIT 1",
            (job_id, job["nguoi_tao"])).fetchone()
        ids = [r["video_id"] for r in rows]
        nhan = models_dac_diem.doc_nhan(conn, ids, nhan_ver) if nhan_ver else {}
        caption = models_dac_diem.doc_caption(conn, ids, caption_ver) if caption_ver else {}
    _in({"job_id": job_id, "url": job["url"], "nguoi_tao": job["nguoi_tao"],
         "trang_thai": job["trang_thai"], "usecase": job["usecase"],
         "insight_goc": job["insight_goc"], "so_video_cua_job": tong,
         "so_bi_loc": tong - len(rows), "bi_loc_theo_ly_do": bi_loc,
         "luot_moi_nhat": dict(lan) if lan else None,
         "video": [{"video_id": r["video_id"], "anh": _anh_cua(db, r["video_id"]),
                    "description": r["description"] or "",
                    "nhan": nhan.get(r["video_id"]), "caption": caption.get(r["video_id"])}
                   for r in rows]})
    return MA_OK


def _ten_co_san(db: Path, job_id: int) -> int:
    """`cum.kieu` người tạo job đã duyệt — "tên ưu tiên nếu khớp" cho prompt
    chuẩn hoá. Job có insight gốc ⇒ chỉ cụm cùng insight gốc (so casefold +
    chuẩn hoá khoảng trắng); chưa có ⇒ mọi cụm của người đó."""
    with models._connect(db) as conn:
        job = conn.execute("SELECT nguoi_tao, usecase, insight_goc FROM jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if job is None:
            _bao(f"không có job {job_id}")
            return MA_KHONG_CO_JOB
        rows = conn.execute("SELECT insight_goc, kieu FROM cum WHERE chu = ? ORDER BY id",
                            (job["nguoi_tao"],)).fetchall()
    insight = models_cum.chuan_hoa_chu(job["insight_goc"] or "")
    loc = bool(insight)
    if loc:
        khoa = insight.casefold()
        rows = [r for r in rows if models_cum.chuan_hoa_chu(r["insight_goc"]).casefold() == khoa]
    else:
        _bao("không lọc theo insight (job chưa có insight gốc)")
    kieu = list(dict.fromkeys(models_cum.chuan_hoa_chu(r["kieu"]) for r in rows))
    _in({"job_id": job_id, "usecase": job["usecase"], "insight_goc": job["insight_goc"],
         "loc_theo_insight": loc, "kieu": kieu})
    return MA_OK


# --- ghi --------------------------------------------------------------------

def _khong_trung_khoa(cap):
    """`json.loads` lặng lẽ giữ khoá SAU khi một object có khoá trùng — một id
    video lặp hai lần phải là lỗi, không phải một video biến mất."""
    ra = {}
    for k, v in cap:
        if k in ra:
            raise LoiTep(f"khoá trùng trong tệp: '{k}'")
        ra[k] = v
    return ra


def _chu(x, ten: str) -> str:
    if not isinstance(x, str) or not models_cum.chuan_hoa_chu(x):
        raise LoiTep(f"{ten} phải là chuỗi khác rỗng")
    return models_cum.chuan_hoa_chu(x)


def _ds_id(x, ten: str) -> list[str]:
    if not isinstance(x, list) or not all(isinstance(v, str) and v.strip() for v in x):
        raise LoiTep(f"{ten} phải là danh sách id (chuỗi)")
    return [v.strip() for v in x]


def _kiem_dac_diem(ds) -> list[dict]:
    """`[{"video_id", "phien_ban_prompt": "nhan:…|caption:…", "nhan": {…}}]`."""
    if not isinstance(ds, list):
        raise LoiTep("dac_diem phải là danh sách")
    ra = []
    for d in ds:
        if not isinstance(d, dict) or not isinstance(d.get("nhan"), dict):
            raise LoiTep("mỗi dac_diem phải có 'video_id', 'phien_ban_prompt', 'nhan' (object)")
        ra.append({"video_id": _chu(d.get("video_id"), "video_id"),
                   "phien_ban_prompt": _chu(d.get("phien_ban_prompt"), "phien_ban_prompt"),
                   "nhan": d["nhan"]})
    return ra


def kiem_tep_ghi(obj) -> dict:
    """Kiểm + chuẩn hoá tệp `ghi`. Hình dạng:

        {"phien_ban_prompt": str, "truc": str | null,
         "nhoms": [{"nhom": str, "kieu": [{"kieu": str, "video_ids": [str]}]}],
         "huong_dan": [str], "nghi": [str],
         "dac_diem": [{"video_id": str, "phien_ban_prompt": "nhan:…|caption:…",
                       "nhan": {…}}]}

    Mỗi id video xuất hiện ĐÚNG MỘT lần trên toàn bộ kiểu + hai làn."""
    if not isinstance(obj, dict):
        raise LoiTep("tệp phải là một object JSON")
    thieu = {"phien_ban_prompt", "nhoms", "huong_dan", "nghi", "dac_diem"} - set(obj)
    if thieu:
        raise LoiTep(f"thiếu khoá: {', '.join(sorted(thieu))}")
    truc = obj.get("truc")
    if truc is not None:
        truc = _chu(truc, "truc")
    if not isinstance(obj["nhoms"], list):
        raise LoiTep("nhoms phải là danh sách")
    nhoms = []
    for n in obj["nhoms"]:
        if not isinstance(n, dict) or not isinstance(n.get("kieu"), list):
            raise LoiTep("mỗi nhóm phải có 'nhom' và danh sách 'kieu'")
        kieus = []
        for k in n["kieu"]:
            if not isinstance(k, dict):
                raise LoiTep("mỗi kiểu phải là object")
            kieus.append({"kieu": _chu(k.get("kieu"), "kieu"),
                          "video_ids": _ds_id(k.get("video_ids"), "video_ids")})
        nhoms.append({"nhom": _chu(n.get("nhom"), "nhom"), "kieu": kieus})
    huong_dan = _ds_id(obj["huong_dan"], "huong_dan")
    nghi = _ds_id(obj["nghi"], "nghi")
    moi_id = [v for n in nhoms for k in n["kieu"] for v in k["video_ids"]] + huong_dan + nghi
    trung = sorted({v for v in moi_id if moi_id.count(v) > 1})
    if trung:
        raise LoiTep(f"{len(trung)} id xuất hiện hơn một lần: {', '.join(trung[:10])}")
    dac_diem = _kiem_dac_diem(obj["dac_diem"])
    return {"phien_ban_prompt": _chu(obj["phien_ban_prompt"], "phien_ban_prompt"),
            "truc": truc, "nhoms": nhoms, "huong_dan": huong_dan, "nghi": nghi,
            "dac_diem": dac_diem}


def _doc_tep(tep: str):
    van_ban = sys.stdin.read() if tep == "-" else Path(tep).read_text(encoding="utf-8")
    return json.loads(van_ban, object_pairs_hook=_khong_trung_khoa)


def _ghi_dac_diem(db: Path, job_id: int, tep: str) -> int:
    """Ghi CHỈ hàng cache `video_dac_diem` (`{"dac_diem": [...]}`), transaction
    riêng — gọi ngay sau khi nhãn/cờ caption qua phép kiểm máy, TRƯỚC chuẩn
    hoá: phần đã trả tiền agy không được mất theo một bước sau trượt."""
    try:
        obj = _doc_tep(tep)
        if not isinstance(obj, dict) or set(obj) != {"dac_diem"}:
            raise LoiTep("tệp phải là object đúng một khoá 'dac_diem'")
        hang = _kiem_dac_diem(obj["dac_diem"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, LoiTep) as exc:
        _bao(f"tệp sai: {exc}")
        return MA_TEP_SAI
    with models._connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
            _bao(f"không có job {job_id}")
            return MA_KHONG_CO_JOB
        cua_job = {r["video_id"] for r in conn.execute(
            "SELECT video_id FROM videos WHERE job_id = ?", (job_id,)).fetchall()}
        la = sorted({h["video_id"] for h in hang} - cua_job)
        if la:
            _bao(f"tệp sai: {len(la)} id không thuộc job {job_id}: {', '.join(la[:10])}")
            return MA_TEP_SAI
        try:
            n = models_dac_diem.ghi(conn, hang)
        except ValueError as exc:
            conn.rollback()
            _bao(f"tệp sai: {exc}")
            return MA_TEP_SAI
    _in({"so_hang": n})
    _bao(f"đã ghi {n} hàng cache")
    return MA_OK


def _ghi(db: Path, job_id: int, tep: str) -> int:
    try:
        du_lieu = kiem_tep_ghi(_doc_tep(tep))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, LoiTep) as exc:
        _bao(f"tệp sai: {exc}")
        return MA_TEP_SAI
    try:
        ket = models_chia.nhap_de_xuat(db, job_id, **du_lieu)
    except models_chia.NhapBiChan as exc:
        _bao(f"không ghi: {exc}")
        return MA_NHAP_BI_CHAN
    except ValueError as exc:
        _bao(f"tệp sai: {exc}")
        return MA_TEP_SAI
    if ket is None:
        _bao(f"không có job {job_id}")
        return MA_KHONG_CO_JOB
    _in(ket)
    _bao(f"đã ghi nháp lượt {ket['chia_lan_id']}: {ket['so_video']} video · "
         f"bỏ vì đã ở cụm {len(ket['da_o_cum'])} · bỏ vì bị lọc {len(ket['bo_vi_loc'])}")
    return MA_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m web.nhap_cum_cli")
    p.add_argument("--db", type=Path, default=DB_MAC_DINH)
    sub = p.add_subparsers(dest="lenh", required=True)
    sub.add_parser("cho-chia")
    s = sub.add_parser("liet")
    s.add_argument("job_id", type=int)
    s.add_argument("--nhan-ver")
    s.add_argument("--caption-ver")
    s = sub.add_parser("ten-co-san")
    s.add_argument("job_id", type=int)
    for ten in ("ghi-dac-diem", "ghi"):
        s = sub.add_parser(ten)
        s.add_argument("job_id", type=int)
        s.add_argument("tep")
    a = p.parse_args(argv)
    if not a.db.is_file():
        # Không để `_connect` lặng lẽ tạo một DB rỗng rồi trả "0 job".
        _bao(f"không thấy DB: {a.db}")
        return MA_LOI_DB
    # KHÔNG gọi `init_db` ở đây: CLI chạy trên DB đang phục vụ, migration là
    # việc của ứng dụng lúc khởi động — một lệnh đọc không được tự ALTER TABLE.
    try:
        if a.lenh == "cho-chia":
            return _cho_chia(a.db)
        if a.lenh == "liet":
            return _liet(a.db, a.job_id, a.nhan_ver, a.caption_ver)
        if a.lenh == "ten-co-san":
            return _ten_co_san(a.db, a.job_id)
        if a.lenh == "ghi-dac-diem":
            return _ghi_dac_diem(a.db, a.job_id, a.tep)
        return _ghi(a.db, a.job_id, a.tep)
    except sqlite3.Error as exc:
        _bao(f"lỗi DB: {exc}")
        return MA_LOI_DB
    except ValueError as exc:
        # Phiên bản prompt sai tiền tố ở `liet` (`models_dac_diem`).
        _bao(f"tham số sai: {exc}")
        return MA_CU_PHAP


if __name__ == "__main__":
    sys.exit(main())
