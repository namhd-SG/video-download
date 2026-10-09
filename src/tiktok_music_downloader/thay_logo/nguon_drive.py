"""Nguồn "Dán link Drive" của Thay logo: đổi mỗi dòng link thành id, hỏi Drive (qua `drive_tl.DriveTL`, CHỈ ĐỌC) xem là file hay thư mục
và có dùng được không.

Quy ước đã chốt với user (brainstorm-xu-ly-theo-bo §7):
  - link THƯ MỤC chỉ lấy video nằm TRỰC TIẾP trong thư mục (một cấp, không đệ quy); thư mục con chỉ được đếm để báo "bỏ qua k thư mục con";
  - nhận mọi file/thư mục mà tài khoản máy đọc được (không đòi file thuộc thư viện của member) — mọi lượt đi qua bước kiểm này để
    có nhật ký ai đã thêm gì (`link_da_kiem`);
  - chỉ ĐỌC: không có lời gọi ghi/xoá/chia sẻ nào ở đây.

Mỗi dòng ra MỘT kết quả có `trang_thai`:
  nhan            dùng được (file: `ten`,`size`; thư mục: `ten` + `videos` + `bo_qua_*`)
  khong_mo_duoc   Drive 403/404 ⇒ tài khoản máy chưa được chia sẻ (kèm email máy ở cấp ngoài cùng của phản hồi)
  khong_hop_le    link sai / không phải video mp4,mov / quá 500 MB / thư mục không có video / quá 300 video
  loi_tam         Drive lỗi tạm (mạng, 5xx, hết hạn mức, quá giờ) — KHÔNG đoán là "chưa chia sẻ"; bấm Kiểm lại
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import parse_qs, urlsplit

from tiktok_music_downloader.nguon import TRAN_DUNG_LUONG_BYTE
from tiktok_music_downloader.thay_logo.drive_tl import MIME_THU_MUC, DriveTL, DriveTLKhongQuyen, DriveTLKhongThay

log = logging.getLogger(__name__)

TRAN_LINK_MOT_LUOT = 20
TRAN_VIDEO_THU_MUC = 300
TRAN_LIET_KE = 5000      # số mục (cả file lẫn thư mục con) đọc tối đa trong một thư mục; hơn ⇒ từ chối, không đoán
TRAN_GIAY_CA_LUOT = 45   # hạn CHUNG cho cả lượt kiểm (dưới ~100 s của Cloudflare); link chưa xong khi hết hạn ⇒ `loi_tam`, các link xong rồi vẫn trả
SO_LUONG_SONG_SONG = 4
TRAN_MB = TRAN_DUNG_LUONG_BYTE // (1024 * 1024)
DUOI_VIDEO = (".mp4", ".mov")
MIME_VIDEO = frozenset({"video/mp4", "video/quicktime"})

_MAU_ID = re.compile(r"^[A-Za-z0-9_-]{10,120}$")
_MAU_DUONG = re.compile(r"/file/d/([A-Za-z0-9_-]+)|/folders/([A-Za-z0-9_-]+)")
_HOST_DRIVE = frozenset({"drive.google.com"})


def tach_id(dong: str) -> str | None:
    """Id Drive trong một dòng link, hoặc None nếu không phải link Drive. Nhận /file/d/<id>, /drive/folders/<id>, /drive/u/0/folders/<id>,
    open?id=<id>, uc?id=<id>. Link Google Docs/Sheets/Slides KHÔNG nhận (không phải video)."""
    dong = dong.strip()
    if not dong.lower().startswith(("http://", "https://")):
        return None
    try:
        u = urlsplit(dong)
        host = (u.hostname or "").lower()
    except ValueError:
        return None
    if host not in _HOST_DRIVE:
        return None
    m = _MAU_DUONG.search(u.path)
    cand = (m.group(1) or m.group(2)) if m else (parse_qs(u.query).get("id") or [None])[0]
    return cand if cand and _MAU_ID.match(cand) else None


def tach_dong(links: list[str]) -> list[str]:
    """Mỗi phần tử có thể chứa nhiều dòng; bỏ dòng trống, giữ thứ tự."""
    return [d.strip() for chuoi in links for d in str(chuoi).splitlines() if d.strip()]


def _cat(ten: str, n: int = 200) -> str:
    return ten if len(ten) <= n else ten[: n - 1] + "…"


def _la_video(m: dict) -> bool:
    if m.get("mimeType") == MIME_THU_MUC:
        return False
    mime = m.get("mimeType") or ""
    if mime in MIME_VIDEO:
        return True
    # đuôi .mp4/.mov ĐƠN ĐỘC không đủ: file `x.mp4` mà mime là pdf/ảnh vẫn không phải video
    return (m.get("name") or "").lower().endswith(DUOI_VIDEO) and (mime.startswith("video/") or mime == "application/octet-stream")


def _byte(m: dict) -> int | None:
    try:
        n = int(m.get("size"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


KHONG_PHAI_VIDEO = f"Không phải video mp4/mov, hoặc nặng quá {TRAN_MB} MB."


def danh_gia_file(m: dict) -> str | None:
    """None = dùng được; chuỗi = lý do lời thường vì sao không. KHÔNG chứa tên file: file không dùng được có thể là của người khác
    mà tài khoản máy đọc được — không đưa tên nó ra cho member."""
    if m.get("trashed"):
        return "Mục này đang nằm trong thùng rác Drive."
    if not _la_video(m):
        return KHONG_PHAI_VIDEO
    n = _byte(m)
    if n is None:
        return "Không đọc được dung lượng của file này."
    if n > TRAN_DUNG_LUONG_BYTE:  # CỔNG ÂM THẦM: bỏ kiểm này thì worker mới từ chối ở bước tải (đã tốn một chỗ trong hàng chờ)
        return KHONG_PHAI_VIDEO
    return None


def _kq(dong: str, trang_thai: str, **them) -> dict:
    return {"link": _cat(dong, 300), "trang_thai": trang_thai, **them}


def _kiem_mot(drive: DriveTL, dong: str, fid: str | None) -> dict:
    if fid is None:
        return _kq(dong, "khong_hop_le", ly_do="Đây không phải link Google Drive. Dán link file hoặc thư mục Drive.")
    try:
        m = drive.lay_muc_day_du(fid)
        if m.get("mimeType") != MIME_THU_MUC:
            ly_do = danh_gia_file(m)
            if ly_do:
                return _kq(dong, "khong_hop_le", id=fid, kieu="file", ly_do=ly_do)
            return _kq(dong, "nhan", id=fid, kieu="file", ten=_cat(m.get("name") or ""), size=_byte(m))
        if m.get("trashed"):
            return _kq(dong, "khong_hop_le", id=fid, kieu="thu_muc", ten=_cat(m.get("name") or ""),
                       ly_do="Thư mục này đang nằm trong thùng rác Drive.")
        con = drive.liet_ke_con(fid, TRAN_LIET_KE + 1)
    except (DriveTLKhongThay, DriveTLKhongQuyen):
        return _kq(dong, "khong_mo_duoc", id=fid, ly_do="Máy chưa mở được mục này.")
    ten = _cat(m.get("name") or "")
    if len(con) > TRAN_LIET_KE:
        return _kq(dong, "khong_hop_le", id=fid, kieu="thu_muc", ten=ten, ly_do=f"Thư mục có quá nhiều mục (hơn {TRAN_LIET_KE}). Chia nhỏ thư mục rồi dán lại.")
    videos, thu_muc_con, khac = [], 0, 0
    for c in con:
        if c.get("trashed"):
            continue
        if c.get("mimeType") == MIME_THU_MUC:  # CHỈ ĐẾM, không đi vào: thư mục con KHÔNG lấy video (user chốt)
            thu_muc_con += 1
        elif danh_gia_file(c) is None:
            videos.append({"id": c["id"], "ten": _cat(c.get("name") or ""), "size": _byte(c)})
        else:
            khac += 1
    videos.sort(key=lambda v: v["ten"].casefold())
    thong_ke = {"bo_qua_thu_muc_con": thu_muc_con, "bo_qua_khac": khac}
    if not videos:
        return _kq(dong, "khong_hop_le", id=fid, kieu="thu_muc", ten=ten, **thong_ke,
                   ly_do=f"Thư mục không có video mp4/mov nào nằm trực tiếp trong đó (tối đa {TRAN_MB} MB mỗi video).")
    if len(videos) > TRAN_VIDEO_THU_MUC:
        return _kq(dong, "khong_hop_le", id=fid, kieu="thu_muc", ten=ten, **thong_ke,
                   ly_do=f"Thư mục có {len(videos)} video — tối đa {TRAN_VIDEO_THU_MUC} một lần. Chia nhỏ thư mục rồi dán lại.")
    return _kq(dong, "nhan", id=fid, kieu="thu_muc", ten=ten, videos=videos, **thong_ke)


def _kiem_an_toan(drive: DriveTL, dong: str, fid: str | None) -> dict:
    try:
        return _kiem_mot(drive, dong, fid)
    except Exception as e:  # noqa: BLE001 — một link hỏng không được kéo sập cả lượt kiểm; lý do thật chỉ vào log
        log.warning("thay logo: kiểm link %s lỗi tạm (%s)", fid, type(e).__name__)
        return _kq(dong, "loi_tam", id=fid, ly_do="Chưa hỏi được Drive lúc này. Bấm Kiểm lại sau ít phút.")


def kiem_cac_link(drive: DriveTL, links: list[str]) -> dict:
    """`links` đã qua `tach_dong`. Trả {"ket_qua": [...theo thứ tự], "trung_bo": n, "email_may": str|None}.
    Id trùng (cùng file dán hai lần, hai dạng link khác nhau) chỉ kiểm một lần; mỗi kết quả mang `dong_so` = chỉ số MỌI dòng đầu vào
    cùng id đó (để nút "Bỏ" gỡ đúng các dòng, không so chuỗi). Dòng không phải link Drive thì mỗi dòng một kết quả.
    Cả lượt có MỘT hạn chung `TRAN_GIAY_CA_LUOT`: link chưa xong khi hết hạn ⇒ `loi_tam`."""
    muc: list[list] = []  # [dong, fid, [chỉ số dòng]]
    theo_id: dict[str, list] = {}
    trung = 0
    for i, dong in enumerate(links):
        fid = tach_id(dong)
        if fid is not None and fid in theo_id:
            theo_id[fid][2].append(i)
            trung += 1
            continue
        m = [dong, fid, [i]]
        muc.append(m)
        if fid is not None:
            theo_id[fid] = m
    pool = ThreadPoolExecutor(max_workers=SO_LUONG_SONG_SONG)
    try:
        futs = [pool.submit(_kiem_an_toan, drive, d, f) for d, f, _ in muc]
        wait(futs, timeout=TRAN_GIAY_CA_LUOT)
        kq = []
        for fu, (dong, fid, so) in zip(futs, muc):
            r = fu.result() if fu.done() else _kq(dong, "loi_tam", id=fid, ly_do="Drive trả lời quá lâu. Bấm Kiểm lại sau ít phút.")
            r["dong_so"] = so
            kq.append(r)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    email = drive.email_dich_vu() if any(k["trang_thai"] == "khong_mo_duoc" for k in kq) else None
    return {"ket_qua": kq, "trung_bo": trung, "email_may": email}


def muc_duoc_nhan(ket_qua: list[dict]) -> list[tuple[str, str, int | None]]:
    """(id file, tên, size) mà member được phép đưa vào lượt sau khi kiểm: file nhận + mọi video của thư mục nhận. Tên/size lấy từ
    kết quả ĐÃ XÁC MINH với Drive (không từ client). KHÔNG có id thư mục."""
    out: list[tuple[str, str, int | None]] = []
    for k in ket_qua:
        if k.get("trang_thai") != "nhan":
            continue
        if k.get("kieu") == "file":
            out.append((k["id"], k.get("ten") or "", k.get("size")))
        else:
            out.extend((v["id"], v.get("ten") or "", v.get("size")) for v in k.get("videos") or [])
    return out


def ids_duoc_nhan(ket_qua: list[dict]) -> list[str]:
    return [i for i, _, _ in muc_duoc_nhan(ket_qua)]
