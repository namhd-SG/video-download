"""Tự chia cụm theo lượt — nháp (`chia_lan`/`cum_nhap`/`video_cum_nhap`),
nhật ký sửa (`thao_tac_duyet`) và đường DUY NHẤT biến nháp thành cụm THẬT.
Bảng sống trong `web/models.py` (`init_db`); đây là câu hỏi/ghi trên chúng.

Luật quyền sở hữu giống `models_cum`: mọi hàm nhận `chu` KHÔNG có mặc định và
lọc theo nó NGAY TRONG SQL. `chu` luôn là email người gọi.

Module này KHÔNG gọi thẳng `models_cum.tao_cum`/`models_cum.gan_video`.
`duyet_kieu`/`duyet_het` CẦN hành vi tương đương `models_cum.tao_cum` (trùng tên ⇒ cụm có sẵn) +
`models_cum.gan_video` (chuyển video) — nhưng viết LẠI hai câu INSERT đó ngay
trên kết nối của module này, thay vì gọi thẳng hai hàm kia, vì cả hai hàm gốc
tự mở `_connect` riêng (= transaction riêng của CHÚNG NÓ). Duyệt cần khoan gộp
cho tới khi có `xac_nhan_gop` (tên trùng cụm có sẵn phải hỏi trước) và kiểm
LẠI trong CÙNG transaction duyệt xem video đã có cụm chưa (vì hai nháp song
song có thể cùng chứa một video) atomic với việc tạo cụm/gán video — gọi
`tao_cum` rồi `gan_video` như hai lời gọi rời sẽ mở hai transaction rời, và
giữa hai lời gọi đó một nháp khác có thể chen vào, đúng lỗ kiểm-lại-trong-cùng-
transaction sinh ra để chặn. Đổi lại, module này dùng lại các hàm THUẦN/hằng số CÔNG
KHAI của `models_cum` (`kiem_nhan`, `ten_insight_con`, `chuan_hoa_chu`,
`LO_TOI_DA`) và hàm SO TRÙNG công khai (`cum_trung`, đọc-only, không sửa DB) để
câu SQL và khoá so trùng luôn khớp hệt #13 — không có một bản sao có thể trôi
theo thời gian.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from web import models_cum, models_dac_diem
from web.models import _connect, _now

# Tập ĐÓNG cho `chia_lan.trang_thai`, `video_cum_nhap.lan` và
# `thao_tac_duyet.loai`. Kiểm ở Python, không CHECK constraint — lý do ở
# đầu tệp `web/models.py::_THAO_TAC_DUYET_SCHEMA`.
TRANG_THAI_CHIA_LAN = ("cho_hinh", "de_xuat", "da_duyet", "huy")
LAN_VIDEO = ("kieu", "huong_dan", "nghi")
# `duyet_kieu` = duyệt MỘT kiểu, `duyet_het` = "Duyệt tất cả" (một dòng cho
# cả lượt gọi) — hai giá trị riêng để nhật ký phân biệt được hai cú bấm.
# `tach` = tạo một kiểu MỚI từ video chọn tay (mirror `_op_doi_ten` cho tên
# hàng mới); `gop_nhom` = gộp NHIỀU kiểu vào một kiểu đích trong MỘT cú bấm
# (mirror `_op_gop` với danh sách nguồn); `doi_ten_nhom` = đổi tên MỘT nhóm
# (mọi kiểu của nhóm đó) trong MỘT cú bấm, atomic — mirror `_op_doi_ten` áp
# cho từng hàng của nhóm thay vì một hàng; `huy_luot` = huỷ lượt (không hoàn
# tác được — xem `_HOAN_TAC_DUOC`).
LOAI_THAO_TAC = ("chap_nhan", "duyet_het", "duyet_kieu", "gop", "doi_ten", "chuyen",
                 "ngoai_chu_de", "tra_ve", "hoan_tac", "xoa_kieu", "doi_insight",
                 "tach", "gop_nhom", "doi_ten_nhom", "huy_luot")

# Loại có thể LÙI LẠI bằng `hoan_tac` — `chap_nhan` không đổi gì để lùi,
# `doi_insight` đổi nhãn (không đổi cấu trúc video) nên không nằm trong luồng
# hoàn tác cấu trúc này, `hoan_tac` không tự lùi chính nó, hai loại duyệt
# (`duyet_kieu`/`duyet_het`) không bao giờ lùi được (duyệt đã đi qua `cum`
# thật — ngoài phạm vi "hoàn tác nháp"), và `huy_luot` không lùi được (huỷ là
# điểm dừng, không phải một bước có thể quay lại).
_HOAN_TAC_DUOC = ("gop", "doi_ten", "chuyen", "ngoai_chu_de", "tra_ve", "xoa_kieu",
                  "tach", "gop_nhom", "doi_ten_nhom")

# Loại thao tác coi là SỬA CÁCH CHIA — dùng làm phần tử chung cho HAI câu hỏi
# KHÁC NHAU dưới đây; đọc kỹ trước khi thêm/bớt một loại vào tuple này, vì hai
# nơi dùng nó lọc THEO HAI CÁCH khác nhau (xem hai chỗ gọi):
#   - bộ đếm HIỂN THỊ D15 (`lay_chia::so_thao_tac`) chỉ đếm những dòng còn
#     "sống" kể từ lần `ghi_de_xuat` GẦN NHẤT — dùng `_HOAN_TAC_DUOC` (tuple
#     này TRỪ `hoan_tac`, vì `hoan_tac` không tự lùi chính nó) CỘNG lọc
#     `da_lui = 0 AND the_he >= the_he_nhap` (mốc `the_he_nhap` RIÊNG, chỉ
#     bump lúc `ghi_de_xuat`, KHÔNG bump lúc duyệt — xem
#     `web/models.py::init_db`);
#   - cửa CHẶN ghi đè nháp (`nhap_de_xuat`/`NhapBiChan`, xem
#     `LOAI_CHAN_GHI_DE_NHAP` dưới đây) dùng tuple này NGUYÊN VẸN (kể cả
#     `hoan_tac`) CỘNG `duyet_kieu`/`duyet_het`, KHÔNG lọc `da_lui`/`the_he`.
# Nhật ký (`thao_tac_duyet`) vẫn ghi ĐỦ mọi dòng bất kể loại ở cả hai nơi —
# hai bộ lọc trên chỉ đổi cách ĐẾM/CHẶN, không đổi cách GHI. `doi_insight`
# (điền usecase/insight gốc), `chap_nhan` (xem qua, không đổi gì) và
# `huy_luot` (bỏ lượt) đều KHÔNG nằm trong tuple này: chia tay cũng phải điền
# insight/huỷ, nên đó không phải công sửa CÁCH CHIA.
LOAI_SUA_CACH_CHIA = ("gop", "gop_nhom", "doi_ten", "doi_ten_nhom", "chuyen", "tach",
                      "ngoai_chu_de", "tra_ve", "xoa_kieu", "hoan_tac")

# Loại CHẶN ghi đè nháp (`nhap_de_xuat` — `NhapBiChan`) — RỘNG HƠN và ĐO
# KHÁC bộ đếm hiển thị D15 ở trên:
#   - rộng hơn ở TẬP LOẠI: cộng thêm `duyet_kieu`/`duyet_het` — duyệt MỘT
#     PHẦN (còn kiểu khác ở lại nháp) vẫn là công người dùng đã bỏ ra, không
#     được một lượt nhập đề xuất khác xoá mất;
#   - khác ở CÁCH LỌC: KHÔNG lọc `da_lui`/`the_he` — một `tach` bị `hoan_tac`
#     lùi lại vẫn phải chặn (người dùng ĐÃ sửa tay, không phải một nháp còn
#     trắng), và một `duyet_kieu` một phần luôn nằm ở THẾ HỆ CŨ (nó tự bump
#     `the_he` ngay sau khi ghi — xem `duyet_kieu`/`duyet_het`) nên lọc theo
#     thế hệ hiện tại sẽ BỎ SÓT đúng ca cần chặn nhất.
LOAI_CHAN_GHI_DE_NHAP = LOAI_SUA_CACH_CHIA + ("duyet_kieu", "duyet_het")


def _lan_cua_toi(conn, chia_lan_id: int, chu: str):
    return conn.execute(
        "SELECT * FROM chia_lan WHERE id = ? AND chu = ?", (chia_lan_id, chu)).fetchone()


# ---------------------------------------------------------------------------
# Tạo lượt + ghi đề xuất (tầng hình gọi sau khi phân tích xong)
# ---------------------------------------------------------------------------

def tao_chia_lan(db_path: Path, job_id: int, chu: str, phien_ban_prompt: str,
                 truc: str | None = None) -> int | None:
    """Mở một lượt chia MỚI cho `job_id` của `chu`.

    `usecase`/`insight_goc` khởi tạo từ CHÍNH `jobs` — không nhận qua tham
    số: trang tạo job hỏi hai ô này lúc TẠO JOB, và `doi_insight` ghi NGƯỢC
    vào `jobs` mỗi khi sửa lúc chia. "Chia lại" (mở lượt chia thứ hai cho
    cùng job) nhờ vậy tự thấy giá trị mới nhất mà không phải gõ lại.

    Trả `None` nếu job không tồn tại HOẶC không phải của `chu` — CHỈ chủ job
    tạo được lượt chia cho job của mình (admin xem được nháp người khác qua
    `lay_chia_theo_job(la_admin=True)`, nhưng không tạo/sửa/duyệt thay).
    """
    with _connect(db_path) as conn:
        return _tao_chia_lan_tren(conn, job_id, chu, phien_ban_prompt, truc)


def _tao_chia_lan_tren(conn, job_id: int, chu: str, phien_ban_prompt: str,
                       truc: str | None) -> int | None:
    """Thân của `tao_chia_lan` trên một kết nối CÓ SẴN — để `nhap_de_xuat`
    tạo lượt và ghi nháp trong CÙNG một transaction."""
    job = conn.execute("SELECT usecase, insight_goc, nguoi_tao FROM jobs WHERE id = ?",
                       (job_id,)).fetchone()
    if job is None or job["nguoi_tao"] != chu:
        return None
    cur = conn.execute(
        "INSERT INTO chia_lan (job_id, chu, trang_thai, truc, usecase, insight_goc, "
        "phien_ban_prompt, tao_luc) VALUES (?, ?, 'cho_hinh', ?, ?, ?, ?, ?)",
        (job_id, chu, truc, job["usecase"], job["insight_goc"], phien_ban_prompt, _now()))
    return int(cur.lastrowid)


def ghi_de_xuat(db_path: Path, chia_lan_id: int, chu: str, nhoms: list[dict],
                huong_dan: list[str] | None = None,
                nghi: list[str] | None = None) -> dict | None:
    """Thay TOÀN BỘ nháp của lượt `chia_lan_id` bằng đề xuất mới của tầng hình.

    `nhoms`: `[{"nhom": str, "kieu": [{"kieu": str, "video_ids": [id,...]}]}]`.
    `huong_dan`/`nghi`: id video xếp thẳng vào hai làn không-kiểu ("thẻ hướng
    dẫn", làn nghi ngoài chủ đề) — mặc định rỗng: không có tầng hình thì hai
    làn này luôn rỗng, không suy ra cụm giả từ caption.

    Trả `None` nếu lượt không phải của `chu`. `ValueError` nếu lượt đã
    `da_duyet`/`huy` — nháp không được ghi đè lên kết quả đã chốt, và một lượt
    đã huỷ không được "sống lại" thành `de_xuat` chỉ vì có đề xuất mới tới:
    `huy` là điểm dừng, không phải một trạng thái đi qua được.

    Video đã nằm trong một cụm THẬT của `chu` (bảng `video_cum`) bị loại khỏi
    mọi danh sách trên trước khi ghi, trả riêng ở khoá `da_o_cum`. Không đề
    xuất "chuyển" một video mà chính người dùng đã tự tay xếp cụm trước khi
    tầng hình kịp phân tích xong.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _ghi_de_xuat_tren(conn, chia_lan_id, chu, nhoms, huong_dan, nghi)


def _ghi_de_xuat_tren(conn, chia_lan_id: int, chu: str, nhoms: list[dict],
                      huong_dan: list[str] | None, nghi: list[str] | None) -> dict | None:
    """Thân của `ghi_de_xuat` trên một kết nối ĐÃ mở transaction ghi — người
    gọi lo `BEGIN IMMEDIATE`/commit."""
    lan = _lan_cua_toi(conn, chia_lan_id, chu)
    if lan is None:
        return None
    if lan["trang_thai"] in ("da_duyet", "huy"):
        raise ValueError(
            f"lượt này đã '{lan['trang_thai']}' — không ghi đè nháp lên kết quả đã chốt")

    da_o_cum: set[str] = set()

    def loc(ids):
        ra = []
        for vid in dict.fromkeys(ids or []):
            if conn.execute("SELECT 1 FROM video_cum WHERE video_id = ? AND chu = ?",
                            (vid, chu)).fetchone():
                da_o_cum.add(vid)
            else:
                ra.append(vid)
        return ra

    # "Thay toàn bộ": xoá nháp cũ của lượt này trước khi ghi nháp mới —
    # `ghi_de_xuat` là lần chạy tầng hình MỚI NHẤT thắng, không cộng dồn.
    conn.execute("DELETE FROM video_cum_nhap WHERE chia_lan_id = ?", (chia_lan_id,))
    conn.execute("DELETE FROM cum_nhap WHERE chia_lan_id = ?", (chia_lan_id,))

    thu_tu = 0
    for nhom in nhoms:
        for kieu in nhom.get("kieu", []):
            ids = loc(kieu.get("video_ids", []))
            if not ids:
                # Kiểu rỗng sau khi lọc KHÔNG vào nháp: nó không có gì để
                # duyệt, và nếu nằm lại nó vẫn tham gia luật va chạm tên
                # (`_chot_ten_moi_kieu`) — ép tiền tố nhóm/hậu tố số lên
                # một kiểu thật trùng tên với nó.
                continue
            cur = conn.execute(
                "INSERT INTO cum_nhap (chia_lan_id, nhom, kieu, thu_tu) VALUES (?, ?, ?, ?)",
                (chia_lan_id, nhom["nhom"], kieu["kieu"], thu_tu))
            thu_tu += 1
            # `ON CONFLICT` giữ đúng luật "một video một chỗ trong một
            # lượt" NGAY CẢ KHI lời gọi này tự liệt một video ở hai
            # nhóm/làn — phần liệt SAU thắng, khớp cách PK sẽ xử nếu
            # ai đó chèn tay hai lần.
            conn.executemany(
                "INSERT INTO video_cum_nhap (video_id, chia_lan_id, cum_nhap_id, lan) "
                "VALUES (?, ?, ?, 'kieu') "
                "ON CONFLICT(video_id, chia_lan_id) DO UPDATE SET "
                "cum_nhap_id = excluded.cum_nhap_id, lan = excluded.lan",
                [(vid, chia_lan_id, int(cur.lastrowid)) for vid in ids])

    for lan_ten, nguon in (("huong_dan", huong_dan), ("nghi", nghi)):
        ids = loc(nguon)
        if ids:
            conn.executemany(
                "INSERT INTO video_cum_nhap (video_id, chia_lan_id, cum_nhap_id, lan) "
                "VALUES (?, ?, NULL, ?) "
                "ON CONFLICT(video_id, chia_lan_id) DO UPDATE SET "
                "cum_nhap_id = NULL, lan = excluded.lan",
                [(vid, chia_lan_id, lan_ten) for vid in ids])

    # Bump `the_he`: một đề xuất MỚI mở một thế hệ mới — `hoan_tac` sau
    # đây (H2b) chỉ được lùi thao tác của thế hệ HIỆN TẠI, không được lùi
    # xuyên qua đề xuất vừa bị GHI ĐÈ ở trên (dữ liệu của thế hệ cũ đã bị
    # xoá bởi hai câu DELETE phía trên; hồi sinh nó là hồi sinh rác). Cũng bump
    # `the_he_nhap` CÙNG giá trị mới (SQLite tính vế phải của MỌI cột trong
    # một câu SET trên giá trị hàng TRƯỚC câu UPDATE, nên `the_he + 1` ở đây
    # và ở `the_he` là CÙNG một số) — mốc RIÊNG cho bộ đếm D15, xem
    # `web/models.py::init_db` (`the_he_nhap`).
    conn.execute(
        "UPDATE chia_lan SET trang_thai = 'de_xuat', the_he = the_he + 1, "
        "the_he_nhap = the_he + 1 WHERE id = ?",
        (chia_lan_id,))
    # Chốt tên hiển thị của MỌI kiểu vừa ghi — xem `_chot_ten_moi_kieu`.
    _chot_ten_moi_kieu(conn, chia_lan_id)
    return {"da_o_cum": sorted(da_o_cum)}


# ---------------------------------------------------------------------------
# Video nào được vào một lượt chia + nhập đề xuất của tầng hình (CLI trên mini)
# ---------------------------------------------------------------------------

# Điều kiện SQL (trên `videos` bí danh `v`) quyết định video nào của một job
# được đưa vào một lượt chia — MỘT chỗ cho mọi nơi hỏi câu đó: liệt video gửi
# tầng hình phân tích (ảnh rời máy), và lọc id lúc nhập nháp. Mỗi mục là
# `(lý do bị loại, điều kiện để ĐƯỢC vào)`; lý do dùng để đếm trong báo cáo.
# Loại thêm một loại video khỏi lượt chia = thêm MỘT dòng vào tuple này; vd
# khi có cột mốc video đã dọn khỏi Drive thì thêm dòng
# `("da_don_drive", "v.drive_don_luc IS NULL"),`.
# `da_o_cum`: video đã nằm trong một cụm THẬT của CHỦ JOB (người chia lượt
# này — cùng luật sở hữu với `ghi_de_xuat`) không được phân tích lại: duyệt
# không bao giờ chuyển nó, nên gửi ảnh nó đi chỉ tốn tiền và để ảnh rời máy vô
# ích. `ghi_de_xuat::loc` vẫn tự kiểm lại (hai nháp song song).
DIEU_KIEN_VAO_LUOT_CHIA = (
    ("da_loai", "v.da_loai_luc IS NULL"),
    ("da_o_cum", "NOT EXISTS (SELECT 1 FROM video_cum vc JOIN jobs jc ON jc.id = v.job_id "
                 "WHERE vc.video_id = v.video_id AND vc.chu = jc.nguoi_tao)"),
)


def video_vao_luot_chia(conn, job_id: int) -> list:
    """Các video của `job_id` được đưa vào lượt chia (lọc theo
    `DIEU_KIEN_VAO_LUOT_CHIA`), cũ nhất trước. Hàng có `video_id`,
    `description`."""
    dieu_kien = " AND ".join(("v.job_id = ?", *(d for _, d in DIEU_KIEN_VAO_LUOT_CHIA)))
    return conn.execute(
        f"SELECT v.video_id, v.description FROM videos v WHERE {dieu_kien} "
        "ORDER BY v.tao_luc, v.video_id", (job_id,)).fetchall()


def dem_bi_loc_theo_ly_do(conn, job_id: int) -> dict[str, int]:
    """`{lý do: số video của job KHÔNG qua điều kiện đó}` — một video trượt
    hai điều kiện được đếm ở cả hai."""
    return {ly_do: conn.execute(f"SELECT COUNT(*) FROM videos v WHERE v.job_id = ? "
                                f"AND NOT ({d})", (job_id,)).fetchone()[0]
            for ly_do, d in DIEU_KIEN_VAO_LUOT_CHIA}


class NhapBiChan(ValueError):
    """Lượt chia hiện tại của job không nhận đề xuất mới — ghi đè sẽ xoá công
    người dùng đã bỏ ra trên nháp."""


def nhap_de_xuat(db_path: Path, job_id: int, phien_ban_prompt: str, truc: str | None,
                 nhoms: list[dict], huong_dan: list[str], nghi: list[str],
                 dac_diem: list[dict]) -> dict | None:
    """Nhập MỘT đề xuất của tầng hình cho `job_id`, trong MỘT transaction:
    chọn/tạo lượt chia, ghi cache nhãn (`models_dac_diem`), ghi nháp
    (`ghi_de_xuat`). Trượt ở bất kỳ bước nào ⇒ không ghi gì.

    Người chia = người tạo job (chỉ chủ job chia được job của mình).

    Chọn lượt: lượt MỚI NHẤT của chủ job đang `cho_hinh`, hoặc đang `de_xuat`
    mà CHƯA có dòng nhật ký nào thuộc `LOAI_CHAN_GHI_DE_NHAP` ⇒ dùng lại
    (nháp mới thay nháp cũ) — usecase/insight gốc đã điền trên lượt đó (qua
    `doi_insight`) được GIỮ NGUYÊN vì đường dùng lại không đụng tới hai cột đó
    (chỉ `phien_ban_prompt`/`truc`). Đang `de_xuat` và ĐÃ có dòng sửa/duyệt
    (người dùng đã đổi tên/gộp/tách/duyệt một phần..., kể cả một sửa đã bị
    `hoan_tac` lùi lại) ⇒ `NhapBiChan` — chỉ điền usecase/insight gốc không
    nên khoá việc chạy lại tầng hình, mọi thứ khác thì có. Không có
    lượt, hoặc lượt mới nhất đã `da_duyet`/`huy` ⇒ mở lượt mới ("chia lại").

    Id không thuộc job ⇒ `ValueError` (tệp sai, không phải chuyện lọc). Id của
    job nhưng bị `DIEU_KIEN_VAO_LUOT_CHIA` loại (vd vừa bị loại sau lúc liệt)
    ⇒ bỏ khỏi nháp, trả ở `bo_vi_loc`. `None` ⇒ không có job.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT nguoi_tao FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return None
        chu = job["nguoi_tao"]
        cua_job = {r["video_id"] for r in conn.execute(
            "SELECT video_id FROM videos WHERE job_id = ?", (job_id,)).fetchall()}
        duoc_vao = {r["video_id"] for r in video_vao_luot_chia(conn, job_id)}

        moi_id = [v for n in nhoms for k in n["kieu"] for v in k["video_ids"]]
        moi_id += [*huong_dan, *nghi, *(d["video_id"] for d in dac_diem)]
        la = sorted(set(moi_id) - cua_job)
        if la:
            raise ValueError(f"{len(la)} id không thuộc job {job_id}: {', '.join(la[:10])}")
        bo_vi_loc = sorted((set(moi_id) & cua_job) - duoc_vao)

        def loc(ids):
            return [v for v in ids if v in duoc_vao]

        nhoms = [{"nhom": n["nhom"], "kieu": [{"kieu": k["kieu"], "video_ids": loc(k["video_ids"])}
                                              for k in n["kieu"]]} for n in nhoms]

        lan = conn.execute(
            "SELECT id, trang_thai FROM chia_lan WHERE job_id = ? AND chu = ? "
            "ORDER BY tao_luc DESC, id DESC LIMIT 1", (job_id, chu)).fetchone()
        dung_lai = None
        if lan is not None and lan["trang_thai"] in ("cho_hinh", "de_xuat"):
            # Cửa CHẶN dùng `LOAI_CHAN_GHI_DE_NHAP` (RỘNG HƠN + KHÔNG lọc
            # `da_lui`/`the_he` — xem comment tại định nghĩa nó): điền
            # usecase/insight gốc (`doi_insight`) không được tính vào đây,
            # nếu không user chỉ cần điền hai ô đó là script máy dev không
            # chạy lại được nữa (phải `huy_luot`); nhưng một `tach` dù đã bị
            # `hoan_tac` lùi lại, hay một `duyet_kieu` một phần, vẫn phải
            # chặn — đó là công người dùng đã bỏ ra, không phải nháp trắng.
            marks_chan = ",".join("?" * len(LOAI_CHAN_GHI_DE_NHAP))
            so_sua = conn.execute(
                f"SELECT COUNT(*) FROM thao_tac_duyet WHERE chia_lan_id = ? AND loai IN "
                f"({marks_chan})", (lan["id"], *LOAI_CHAN_GHI_DE_NHAP)).fetchone()[0]
            if lan["trang_thai"] == "de_xuat" and so_sua:
                raise NhapBiChan(
                    f"lượt {lan['id']} đã có {so_sua} thao tác sửa/duyệt — không ghi đè nháp")
            dung_lai = int(lan["id"])
        if dung_lai is not None:
            chia_lan_id = dung_lai
            conn.execute("UPDATE chia_lan SET phien_ban_prompt = ?, truc = ? WHERE id = ?",
                         (phien_ban_prompt, truc, chia_lan_id))
        else:
            chia_lan_id = _tao_chia_lan_tren(conn, job_id, chu, phien_ban_prompt, truc)

        models_dac_diem.ghi(conn, dac_diem)
        ket = _ghi_de_xuat_tren(conn, chia_lan_id, chu, nhoms, loc(huong_dan), loc(nghi))
        so_video = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ?",
                                (chia_lan_id,)).fetchone()[0]
    return {"chia_lan_id": chia_lan_id, "tao_moi": dung_lai is None, "so_video": so_video,
            "da_o_cum": ket["da_o_cum"], "bo_vi_loc": bo_vi_loc}


def lay_chia(db_path: Path, chia_lan_id: int, chu: str, la_admin: bool = False) -> dict | None:
    """Toàn bộ nháp của một lượt: các nhóm/kiểu kèm video, cộng hai làn
    "hướng dẫn"/"nghi". `None` nếu lượt không phải của `chu` (trừ `la_admin`:
    admin XEM được nháp của người khác — KHÔNG sửa/duyệt, chỗ đó vẫn khoá theo
    `chu` thật ở `ap_thao_tac`/`duyet_kieu`/`duyet_het`)."""
    with _connect(db_path) as conn:
        lan = conn.execute("SELECT * FROM chia_lan WHERE id = ?", (chia_lan_id,)).fetchone() \
            if la_admin else _lan_cua_toi(conn, chia_lan_id, chu)
        if lan is None:
            return None
        nhoms: dict[int, dict] = {}
        for r in conn.execute(
                "SELECT id, nhom, kieu, ten_cum, thu_tu FROM cum_nhap WHERE chia_lan_id = ? "
                "ORDER BY thu_tu, id", (chia_lan_id,)).fetchall():
            # `ten_cum` = đúng tên lúc duyệt sẽ dùng (cùng lưới an toàn
            # `ten_cum or kieu` của `_giai_quyet_kieu`).
            nhoms[r["id"]] = {"cum_nhap_id": r["id"], "nhom": r["nhom"], "kieu": r["kieu"],
                              "ten_cum": r["ten_cum"] or r["kieu"],
                              "thu_tu": r["thu_tu"], "video_ids": []}
        huong_dan: list[str] = []
        nghi: list[str] = []
        bi_bo: list[str] = []
        # Video đã có NHÀ THẬT (`video_cum` của chính `chu` lượt này — duyệt
        # xong, hoặc gán TAY trong lúc nháp còn mở) coi như XONG: ẩn khỏi CẢ
        # BA làn `kieu`/`huong_dan`/`nghi`, bất kể hàng `video_cum_nhap` của nó
        # còn mang `lan` gì. Trước đây chỉ lọc cho hàng "mồ côi"
        # (`lan='kieu'`, `cum_nhap_id=NULL` sau khi FK `ON DELETE SET NULL`
        # chạy lúc kiểu chứa nó được duyệt) — một video gán tay vào cụm thật
        # trong khi hàng nháp của nó còn mang `lan='huong_dan'`/`'nghi'` (chưa
        # từng đi qua nhánh mồ côi) vẫn lọt vào làn cũ, khiến nút "cả làn"
        # (vd `hd-ngoai-chu-de`) kéo theo nó và bị chặn ở
        # `_kiem_video_ids_thao_tac` cho CẢ những video còn lại trong làn.
        # KHÔNG đưa video này vào `bi_bo` — `bi_bo` nghĩa là "lạc, cần chú ý",
        # còn video này đã có nhà, không lạc gì cả; chỉ ẩn, không báo riêng.
        video_cum_cua_chu = {r["video_id"] for r in conn.execute(
            "SELECT video_id FROM video_cum WHERE chu = ?", (lan["chu"],)).fetchall()}
        # Video người dùng đã LOẠI khỏi thư viện (`/videos/loai`, kể cả bấm từ
        # chính màn này) cũng biến khỏi mọi làn — cùng luật với
        # `DIEU_KIEN_VAO_LUOT_CHIA` cho lượt mới; lượt đã có thì lọc lúc đọc.
        da_loai = {r["video_id"] for r in conn.execute(
            "SELECT vcn.video_id FROM video_cum_nhap vcn JOIN videos v ON v.video_id = vcn.video_id "
            "WHERE vcn.chia_lan_id = ? AND v.da_loai_luc IS NOT NULL", (chia_lan_id,)).fetchall()}
        for r in conn.execute(
                "SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap "
                "WHERE chia_lan_id = ? ORDER BY video_id", (chia_lan_id,)).fetchall():
            if r["video_id"] in video_cum_cua_chu or r["video_id"] in da_loai:
                continue
            if r["lan"] == "kieu" and r["cum_nhap_id"] in nhoms:
                nhoms[r["cum_nhap_id"]]["video_ids"].append(r["video_id"])
            elif r["lan"] == "huong_dan":
                huong_dan.append(r["video_id"])
            elif r["lan"] == "nghi":
                nghi.append(r["video_id"])
            else:
                bi_bo.append(r["video_id"])
        # Bộ đếm nghiệm thu D15 — đếm dòng SỬA CÁCH CHIA còn "sống" (chưa bị
        # `hoan_tac` lùi) kể từ lần `ghi_de_xuat` GẦN NHẤT (`the_he_nhap`,
        # mốc RIÊNG — xem `web/models.py::init_db`): dùng `_HOAN_TAC_DUOC` (=
        # `LOAI_SUA_CACH_CHIA` TRỪ `hoan_tac` — `hoan_tac` không tự lùi chính
        # nó nên tự động không được đếm) CỘNG `da_lui = 0 AND the_he >=
        # the_he_nhap`. `>=`, KHÔNG `=`: `duyet_kieu`/`duyet_het` bump
        # `the_he` (để KHOÁ hoàn tác xuyên qua duyệt — xem `co_the_hoan_tac`
        # ngay dưới, vẫn dùng `the_he` đúng nghĩa CŨ) nhưng KHÔNG bump
        # `the_he_nhap` (không mở nháp mới) — lọc `the_he = the_he` (bằng)
        # sẽ làm một dòng sửa TRƯỚC lúc duyệt một phần (nay mang `the_he` CŨ,
        # nhỏ hơn `the_he` hiện tại) rơi khỏi bộ đếm dù công đó còn "sống".
        # Ví dụ: `gop` ⇒ 1; `gop` rồi `hoan_tac` ⇒ 0 (dòng `gop` bị đánh
        # `da_lui=1`); `gop`, `hoan_tac`, `gop` lại ⇒ 1 (dòng `gop` MỚI còn
        # sống); `gop`, `doi_ten`, `duyet_kieu` MỘT kiểu khác (bump `the_he`,
        # không bump `the_he_nhap`) ⇒ vẫn 2 (không tụt về 0 như trước khi có
        # `the_he_nhap`). Nhật ký (`thao_tac_duyet`) vẫn ghi ĐỦ mọi dòng bất
        # kể loại — chỉ cách ĐẾM đổi, không phải cách GHI. Xem
        # `LOAI_CHAN_GHI_DE_NHAP` cho câu hỏi KHÁC ("có được ghi đè nháp
        # không") — hai câu hỏi lọc khác nhau.
        marks_sua = ",".join("?" * len(_HOAN_TAC_DUOC))
        so_thao_tac = conn.execute(
            f"SELECT COUNT(*) FROM thao_tac_duyet WHERE chia_lan_id = ? AND loai IN ({marks_sua}) "
            f"AND da_lui = 0 AND the_he >= ?",
            (chia_lan_id, *_HOAN_TAC_DUOC, lan["the_he_nhap"])).fetchone()[0]
        # Cùng điều kiện chọn dòng của `_op_hoan_tac` — nút "Hoàn tác" chỉ bật
        # khi bấm vào thật sự có thứ để lùi (không suy từ `so_thao_tac`:
        # `doi_insight`/duyệt ghi nhật ký nhưng không lùi được).
        marks = ",".join("?" * len(_HOAN_TAC_DUOC))
        co_the_hoan_tac = conn.execute(
            f"SELECT 1 FROM thao_tac_duyet WHERE chia_lan_id = ? AND loai IN ({marks}) "
            f"AND da_lui = 0 AND the_he = ? LIMIT 1",
            (chia_lan_id, *_HOAN_TAC_DUOC, lan["the_he"])).fetchone() is not None
    return {**dict(lan), "kieu": list(nhoms.values()), "huong_dan": huong_dan, "nghi": nghi,
            "bi_bo": bi_bo, "so_thao_tac": so_thao_tac, "co_the_hoan_tac": co_the_hoan_tac}


def lay_chia_theo_job(db_path: Path, job_id: int, chu: str, la_admin: bool = False) -> dict | None:
    """Lượt chia MỚI NHẤT của `job_id` — cho `GET /chia/{job_id}`.

    `la_admin=False` (mặc định): chỉ lượt CỦA `chu`. `la_admin=True`: lượt mới
    nhất của job này BẤT KỂ ai tạo — admin xem được nháp người khác, route
    vẫn tự khoá sửa/duyệt theo `chu` thật ở tầng thao tác/duyệt.

    Một job có thể có nhiều lượt chia (chia lại), và trang chỉ cần lượt mới
    nhất; lượt cũ vẫn còn trong DB cho việc tra cứu/nhật ký, không bị xoá.
    """
    with _connect(db_path) as conn:
        if la_admin:
            row = conn.execute(
                "SELECT id, chu FROM chia_lan WHERE job_id = ? "
                "ORDER BY tao_luc DESC, id DESC LIMIT 1", (job_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT id, chu FROM chia_lan WHERE job_id = ? AND chu = ? "
                "ORDER BY tao_luc DESC, id DESC LIMIT 1", (job_id, chu)).fetchone()
    if row is None:
        return None
    return lay_chia(db_path, int(row["id"]), row["chu"], la_admin=la_admin)


# ---------------------------------------------------------------------------
# Duyệt — lối DUY NHẤT từ nháp sang `cum`/`video_cum` thật.
# ---------------------------------------------------------------------------

def _ap_doi_insight_neu_co(conn, chia_lan_id: int, chu: str, lan,
                           usecase: str | None, insight_goc: str | None) -> tuple[str, str]:
    """`duyet` nhận `usecase`/`insight_goc` TÙY CHỌN trong body: có ⇒ ghi
    như một `doi_insight` NGAY TRONG transaction duyệt rồi mới dùng (hết
    race giữa ô nhập và nút duyệt); không có ⇒ đọc từ `chia_lan` đã lưu."""
    u_cu, g_cu = lan["usecase"], lan["insight_goc"]
    if usecase is None and insight_goc is None:
        return u_cu, g_cu
    u = models_cum.chuan_hoa_chu(usecase) if usecase is not None else u_cu
    g = models_cum.chuan_hoa_chu(insight_goc) if insight_goc is not None else g_cu
    if (u, g) == (u_cu, g_cu):
        # KHÔNG đổi gì thật ⇒ không ghi thêm một dòng nhật ký giả — UI thường
        # gửi kèm usecase/insight MỖI lượt duyệt (ô nhập luôn có sẵn giá trị
        # cũ), và đếm "mỗi bấm = 1 dòng" ở nhật ký sẽ bị thổi phồng nếu một cú
        # bấm duyệt luôn kéo theo một `doi_insight` vô nghĩa.
        return u, g
    conn.execute("UPDATE chia_lan SET usecase = ?, insight_goc = ? WHERE id = ?",
                (u, g, chia_lan_id))
    # Ghi CẢ `jobs`: "chia lại" đọc usecase/insight từ ĐÓ (xem `tao_chia_lan`),
    # không phải từ lượt chia cũ — thiếu dòng này thì mỗi lượt chia mới lại
    # bắt gõ lại từ đầu. `AND nguoi_tao = ?`: chỉ ghi NGƯỢC vào job của chính
    # `chu` — một lượt chia không (còn) thuộc job đó (không nên xảy ra sau khi
    # `tao_chia_lan` khoá theo chủ job, nhưng đây là lớp chặn thứ hai ngay tại
    # điểm ghi) không được đổi mặc định của người khác.
    conn.execute("UPDATE jobs SET usecase = ?, insight_goc = ? WHERE id = ? AND nguoi_tao = ?",
                (u, g, lan["job_id"], chu))
    conn.execute(
        "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, chi_tiet_json, luc, "
        "the_he) VALUES (?, ?, 'doi_insight', 0, ?, ?, ?)",
        (chia_lan_id, chu, json.dumps({"usecase": u, "insight_goc": g}, ensure_ascii=False),
         _now(), lan["the_he"]))
    return u, g


def _khoa_ten(ten: str) -> str:
    """Khoá so trùng tên: chuẩn hoá khoảng trắng + casefold (khoá
    `models_cum._khoa_ten`)."""
    return models_cum.chuan_hoa_chu(ten).casefold()


def _giai_va_cham_ten(hang, ten: dict[int, str]) -> None:
    """Luật đặt tên cụm, SỬA TẠI CHỖ `ten` (`{cum_nhap_id: tên cuối}`).

    Tên cụm mặc định là `"<insight gốc> <kiểu>"`. Khi ≥2 hàng của cùng lượt
    có cùng TÊN CUỐI (so bằng `_khoa_ten`), mọi hàng trong nhóm trùng đó ghép
    thêm `nhom` — `"<insight gốc> <nhom> <kiểu>"`. Tên ghép có thể lại trùng
    tên cuối của một hàng khác (vd "Vest"/"couple" thành "Vest couple", trùng
    kiểu đơn "Vest couple" của nhóm khác) ⇒ lặp tới khi mọi nhóm trùng còn
    lại chỉ gồm hàng đã ghép nhóm. Mục đích: `duyet_het` không tự gộp hai
    kiểu khác nhau vào một cụm, và không bao giờ hỏi "gộp vào cụm vừa tạo
    trong CHÍNH lượt gọi này" (câu hỏi gộp chỉ để bắt trùng với cụm THẬT có
    từ trước).

    Trần vòng lặp: mỗi vòng chạy tiếp chỉ khi đã đổi ít nhất một hàng từ tên
    chưa ghép sang tên ghép, và hàng đã ghép không đổi nữa ⇒ tối đa
    `len(hang) + 1` vòng.

    Va chạm CÒN LẠI khi mọi hàng dính vào đã ghép nhóm (luật ghép nhóm hết
    cách tách) chia hai ca — xem `_them_hau_to_so`:
      - CÙNG một kiểu (cùng `nhom` VÀ cùng `kieu` theo `_khoa_ten`, vd
        "Vest"/"couple" và "Vest"/"Couple"): giữ nguyên, lúc duyệt tự gộp
        vào MỘT cụm (không hỏi) — đúng là một kiểu.
      - kiểu KHÁC nhau mà tên ghép trùng nhau ("A"/"B couple" và "A
        B"/"couple" cùng ra "A B couple"): không được âm thầm gộp ⇒ thêm hậu
        tố số.

    CHỈ gọi lúc `ghi_de_xuat` (`_chot_ten_moi_kieu`); `doi_ten` có luật riêng,
    chỉ đổi hàng vừa đổi (`_chot_ten_sau_doi_ten`).
    """
    ghep = {r["id"]: _ten_ghep(r) for r in hang}

    def ghep_nhom(ids) -> bool:
        doi = False
        for i in ids:
            if ten[i] != ghep[i]:
                ten[i] = ghep[i]
                doi = True
        return doi

    for _ in range(len(hang) + 1):
        theo_khoa: dict[str, list[int]] = {}
        for i, t in ten.items():
            theo_khoa.setdefault(_khoa_ten(t), []).append(i)
        doi = False
        for ids in theo_khoa.values():
            if len(ids) > 1 and ghep_nhom(ids):
                doi = True
        if not doi:
            break
    _them_hau_to_so(hang, ten)


def _them_hau_to_so(hang, ten: dict[int, str]) -> None:
    """Tách va chạm còn lại giữa các kiểu KHÁC nhau bằng hậu tố số, SỬA TẠI
    CHỖ `ten`. Trong mỗi nhóm trùng tên cuối, kiểu đứng đầu (theo `thu_tu`,
    `id`) giữ tên; mỗi kiểu khác nhận `"<tên> N"` với N nhỏ nhất (từ 2) mà
    tên đó CHƯA có trong lượt — kể cả một kiểu có sẵn tên như thế (vd kiểu
    đơn "A B couple 2"). Các hàng cùng một kiểu (biến thể hoa/thường cùng
    nhóm) nhận CÙNG hậu tố, vẫn tự gộp lúc duyệt.

    Trần: mỗi vòng tách hẳn một nhóm trùng (tên mới luôn chưa ai dùng) ⇒
    tối đa `len(hang) + 1` vòng; trong `len(hang) + 1` ứng viên N luôn có một
    tên trống. Vượt trần ⇒ `ValueError` (không bao giờ gộp thay).
    """
    danh_tinh = {r["id"]: (_khoa_ten(r["nhom"]), _khoa_ten(r["kieu"])) for r in hang}
    thu_tu = {r["id"]: (r["thu_tu"], r["id"]) for r in hang}
    tran = len(hang) + 1
    for _ in range(tran):
        theo_khoa: dict[str, list[int]] = {}
        for i, t in ten.items():
            theo_khoa.setdefault(_khoa_ten(t), []).append(i)
        nhom_trung = next((ids for ids in theo_khoa.values()
                           if len({danh_tinh[i] for i in ids}) > 1), None)
        if nhom_trung is None:
            return
        cac_kieu: list[tuple] = []
        for i in sorted(nhom_trung, key=thu_tu.__getitem__):
            if danh_tinh[i] not in cac_kieu:
                cac_kieu.append(danh_tinh[i])
        goc = ten[min(nhom_trung, key=thu_tu.__getitem__)]
        da_dung = set(theo_khoa)
        for kieu in cac_kieu[1:]:
            moi = next((f"{goc} {n}" for n in range(2, tran + 2)
                        if _khoa_ten(f"{goc} {n}") not in da_dung), None)
            if moi is None:
                raise ValueError(f"không tách được tên cụm trùng '{goc}' bằng hậu tố số")
            da_dung.add(_khoa_ten(moi))
            for i in nhom_trung:
                if danh_tinh[i] == kieu:
                    ten[i] = moi
    raise ValueError("không tách được các tên cụm trùng trong lượt bằng hậu tố số")


def _ten_ghep(r) -> str:
    return models_cum.chuan_hoa_chu(f"{r['nhom']} {r['kieu']}")


def _chot_ten_moi_kieu(conn, chia_lan_id: int) -> None:
    """Tính VÀ LƯU `ten_cum` (tên dùng lúc duyệt — luật `_giai_va_cham_ten`)
    cho MỌI kiểu của lượt. CHỈ gọi từ `ghi_de_xuat`.

    Sau lúc đó tên của một kiểu CHỈ đổi khi `doi_ten` đụng tới nó (xem
    `_chot_ten_sau_doi_ten`); duyệt, gộp, xoá, chuyển KHÔNG tính lại tên kiểu
    nào, và `hoan_tac` trả lại đúng tên cũ đã lưu trong nhật ký. Tính lại cả
    lượt trên tập hàng CÒN SỐNG làm tên trôi: một lần duyệt/gộp/xoá làm mất
    "anh em" trùng tên của một kiểu, và lần tính lại sau đó gỡ tiền tố nhóm
    của kiểu còn lại — cùng một kiểu ra hai tên khác nhau tuỳ thứ tự thao
    tác (ca đo được: duyệt riêng "Vest couple" rồi đổi tên một kiểu không
    liên quan làm "Đồng phục couple" thành "couple" trần).
    """
    hang = conn.execute("SELECT id, nhom, kieu, thu_tu FROM cum_nhap WHERE chia_lan_id = ?",
                        (chia_lan_id,)).fetchall()
    ten = {r["id"]: models_cum.chuan_hoa_chu(r["kieu"]) for r in hang}
    _giai_va_cham_ten(hang, ten)
    conn.executemany("UPDATE cum_nhap SET ten_cum = ? WHERE id = ?",
                     [(t, i) for i, t in ten.items()])


def _chot_ten_sau_doi_ten(conn, chia_lan_id: int, cum_nhap_id: int) -> dict[str, str | None]:
    """Tính lại `ten_cum` của ĐÚNG hàng vừa `doi_ten` (X) — hàng DUY NHẤT được
    đổi tên; mọi hàng khác giữ nguyên `ten_cum` đã lưu, bất kể `thu_tu`.

    Tên của X, so với tên ĐÃ LƯU của mọi hàng khác (`_khoa_ten`):
      - có hàng CÙNG một kiểu với X (cùng `nhom` VÀ `kieu` theo `_khoa_ten` —
        biến thể hoa/thường cùng nhóm) ⇒ X lấy ĐÚNG tên đã lưu của hàng đó
        (hàng đầu theo `thu_tu`, `id`), để lúc duyệt hai hàng tự gộp;
      - không thì tên trần; trùng ⇒ tên ghép nhóm; vẫn trùng ⇒ tên ghép +
        hậu tố `" N"` nhỏ nhất (từ 2) chưa có trong lượt. Trong
        `len(hang) + 1` ứng viên luôn có một tên trống; không có ⇒
        `ValueError` (không bao giờ gộp thay).
    Luật "ghép nhóm CẢ HAI hàng trùng" (`_giai_va_cham_ten`) chỉ chạy lúc
    `ghi_de_xuat`, trước khi tên được chốt.

    Trả `{str(cum_nhap_id): ten_cum_truoc}` của X — lưu vào nhật ký để
    `hoan_tac` trả lại ĐÚNG tên cũ thay vì tính lại.
    """
    hang = conn.execute(
        "SELECT id, nhom, kieu, thu_tu, ten_cum FROM cum_nhap WHERE chia_lan_id = ? "
        "ORDER BY thu_tu, id", (chia_lan_id,)).fetchall()
    x = next(r for r in hang if r["id"] == cum_nhap_id)
    khac = [r for r in hang if r["id"] != cum_nhap_id]
    ten_khac = {r["id"]: r["ten_cum"] or models_cum.chuan_hoa_chu(r["kieu"]) for r in khac}
    danh_tinh_x = (_khoa_ten(x["nhom"]), _khoa_ten(x["kieu"]))
    cung_kieu = next((r for r in khac
                      if (_khoa_ten(r["nhom"]), _khoa_ten(r["kieu"])) == danh_tinh_x), None)
    if cung_kieu is not None:
        moi = ten_khac[cung_kieu["id"]]
    else:
        da_dung = {_khoa_ten(t) for t in ten_khac.values()}
        ghep = _ten_ghep(x)
        ung_vien = [models_cum.chuan_hoa_chu(x["kieu"]), ghep,
                    *(f"{ghep} {n}" for n in range(2, len(hang) + 3))]
        moi = next((t for t in ung_vien if _khoa_ten(t) not in da_dung), None)
        if moi is None:
            raise ValueError(f"không tách được tên cụm trùng '{ghep}' bằng hậu tố số")
    conn.execute("UPDATE cum_nhap SET ten_cum = ? WHERE id = ?", (moi, cum_nhap_id))
    return {str(cum_nhap_id): x["ten_cum"]}


def _giai_quyet_kieu(conn, chia_lan_id: int, cum_nhap_id: int, chu: str,
                     chi_cua: str | None, usecase: str, insight_goc: str,
                     xac_nhan: set[int], da_tao_trong_luot: dict[tuple[str, str], int]) -> dict:
    """Lõi "duyệt một kiểu", dùng chung bởi `duyet_kieu` (một nhóm) và
    `duyet_het` (vòng lặp mọi nhóm còn lại) TRÊN CÙNG một kết nối/transaction.

    Tên hiển thị dùng ở đây là `cum_nhap.ten_cum` — đã CHỐT lúc ghi
    (`_chot_ten_moi_kieu`/`_chot_ten_sau_doi_ten`), KHÔNG tính lại ở đây
    (xem lý do tại `_chot_ten_moi_kieu`).

    `da_tao_trong_luot`: `{(usecase.casefold, insight_con.casefold): cum_id}`
    của MỌI cụm đã tạo/dùng TRONG CHÍNH lượt gọi `duyet_het` này (rỗng cho
    `duyet_kieu`, vốn chỉ giải quyết một kiểu). Cần cho va chạm CÒN LẠI mà
    `_giai_va_cham_ten` để nguyên — hai hàng đã ghép nhóm mà tên vẫn trùng ở
    casefold: biến thể hoa/thường của cùng một kiểu trong cùng nhóm ("Vest
    couple"/"Vest Couple"), hoặc hai kiểu có tên ghép trùng nhau ("A"/"B
    couple" và "A B"/"couple"). Không có bước tra map này, hàng xử lý SAU sẽ thấy cụm hàng
    TRƯỚC vừa tạo (cùng transaction, cùng lượt gọi) qua `cum_trung` và hỏi
    "gộp" — đúng điều hợp đồng cấm ("không bao giờ hỏi gộp vào cụm vừa tạo
    trong cùng lượt duyệt"); phải tự gộp thẳng, không hỏi.

    Trả một trong ba hình dạng:
      - `{"loi": "khong_tim_thay"}` — `cum_nhap_id` không thuộc lượt này.
      - `{"trung": {...}}` — tên trùng cụm có sẵn, CHƯA có xác nhận gộp trong
        `xac_nhan` ⇒ KHÔNG tạo/gán gì, nhóm ở NGUYÊN trong nháp.
      - `{"cum_nhap_id", "cum_id", "da_co", "gan", "da_o_cum", "bi_bo"}` — đã
        giải quyết xong (có thể `gan == []` nếu mọi video của nhóm đã ở cụm
        khác); nhóm bị XOÁ khỏi nháp trong ca này.

    `kiem_nhan` raise `ValueError` khi tên (usecase/insight gốc/kiểu — hay tên
    ghép nhóm+kiểu khi trùng) sai hợp đồng độ dài; người gọi (`duyet_het`) bắt
    lỗi này TỪNG KIỂU để một cái tên xấu không kéo sập cả lô duyệt.
    """
    nhom_row = conn.execute(
        "SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
        (cum_nhap_id, chia_lan_id)).fetchone()
    if nhom_row is None:
        return {"loi": "khong_tim_thay"}

    # `kieu` trần là lưới an toàn cho một hàng cũ chưa từng đi qua
    # `_chot_ten_moi_kieu` (cột thêm sau, mặc định NULL) — trên đường thi công
    # bình thường mọi hàng cum_nhap đều có `ten_cum` vì `ghi_de_xuat` luôn gọi
    # hàm đó.
    kieu_dung = nhom_row["ten_cum"] or nhom_row["kieu"]
    u, g, k = models_cum.kiem_nhan(usecase, insight_goc, kieu_dung)
    insight_con = models_cum.ten_insight_con(g, k)

    video_ids = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM video_cum_nhap WHERE chia_lan_id = ? "
        "AND cum_nhap_id = ? AND lan = 'kieu'", (chia_lan_id, cum_nhap_id)).fetchall()]

    # Kiểm LẠI video đã có cụm ngay trong transaction duyệt — một nháp SONG
    # SONG có thể đã đưa video này vào một cụm thật ngay trước lượt duyệt
    # này. Video đó KHÔNG bị chuyển lần nữa; trả lại ở `da_o_cum`.
    da_o_cum, con_lai = [], []
    for vid in video_ids:
        if conn.execute("SELECT 1 FROM video_cum WHERE video_id = ? AND chu = ?",
                        (vid, chu)).fetchone():
            da_o_cum.append(vid)
        else:
            con_lai.append(vid)

    # Cùng bộ lọc sở hữu/còn-trong-thư-viện mà `models_cum.gan_video` áp dụng
    # (video đã "loại" hoặc không thuộc phạm vi `chi_cua` thì không được gán).
    # Phần KHÔNG lọt (id giả từ `ghi_de_xuat`, hoặc đã bị loại/đổi chủ sau khi
    # đề xuất) bị BỎ QUA — báo lại ở `bi_bo`, không được lặng lẽ biến mất
    # (trước đây không ai đọc `con_lai - hop_le`, video rơi mất không dấu vết).
    bi_bo: list[str] = []
    if con_lai:
        marks = ",".join("?" * len(con_lai))
        hop_le = {r["video_id"] for r in conn.execute(
            f"SELECT v.video_id FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.video_id IN ({marks}) AND v.da_loai_luc IS NULL "
            f"AND (? IS NULL OR j.nguoi_tao = ?)",
            [*con_lai, chi_cua, chi_cua]).fetchall()}
        bi_bo = [v for v in con_lai if v not in hop_le]
        con_lai = [v for v in con_lai if v in hop_le]

    # THỨ TỰ BẮT BUỘC: lọc TRƯỚC, chỉ tạo/gán khi còn ≥1 video lọt qua cả hai
    # bộ lọc trên — không bao giờ sinh một cụm rỗng (tên máy đặt không vào
    # `cum` nếu không có video nào đi kèm).
    if not con_lai:
        conn.execute("DELETE FROM cum_nhap WHERE id = ?", (cum_nhap_id,))
        return {"cum_nhap_id": cum_nhap_id, "cum_id": None, "da_co": None,
                "gan": [], "da_o_cum": da_o_cum, "bi_bo": bi_bo}

    # Khoá SO TRÙNG trong PHẠM VI lượt gọi này — xem docstring trên
    # `da_tao_trong_luot`. Kiểm map này TRƯỚC khi hỏi `cum_trung` (bảng
    # thật): một cụm đã tạo/dùng trong CHÍNH lượt gọi này không bao giờ được
    # hỏi lại "gộp", bất kể `xac_nhan`.
    khoa_trong_luot = (models_cum.chuan_hoa_chu(u).casefold(),
                       models_cum.chuan_hoa_chu(insight_con).casefold())
    cum_id_trong_luot = da_tao_trong_luot.get(khoa_trong_luot)
    if cum_id_trong_luot is not None:
        cum_id, da_co = cum_id_trong_luot, True
    else:
        trung_id = models_cum.cum_trung(conn, chu, u, insight_con)
        if trung_id is not None and trung_id not in xac_nhan:
            return {"trung": {"cum_nhap_id": cum_nhap_id, "cum_id": trung_id,
                              "ten": insight_con, "so_video": len(con_lai)}}
        if trung_id is not None:
            cum_id, da_co = trung_id, True
        else:
            cur = conn.execute(
                "INSERT INTO cum (chu, usecase, insight_goc, kieu, tao_luc) VALUES (?, ?, ?, ?, ?)",
                (chu, u, g, k, _now()))
            cum_id, da_co = int(cur.lastrowid), False
    da_tao_trong_luot[khoa_trong_luot] = cum_id

    # Cùng câu SQL (`ON CONFLICT` theo khoá `(video_id, chu)`) mà
    # `models_cum.gan_video` dùng — "một video một cụm mỗi người" giữ nguyên
    # dù đường vào là duyệt nháp thay vì kéo tay.
    conn.executemany(
        "INSERT INTO video_cum (video_id, chu, cum_id) VALUES (?, ?, ?) "
        "ON CONFLICT(video_id, chu) DO UPDATE SET cum_id = excluded.cum_id",
        [(vid, chu, cum_id) for vid in con_lai])
    conn.execute("DELETE FROM cum_nhap WHERE id = ?", (cum_nhap_id,))

    return {"cum_nhap_id": cum_nhap_id, "cum_id": cum_id, "da_co": da_co,
            "gan": con_lai, "da_o_cum": da_o_cum, "bi_bo": bi_bo}


def _giai_quyet_kieu_vao_cum(conn, chia_lan_id: int, cum_nhap_id: int, chu: str,
                             chi_cua: str | None, cum_id_dich: int) -> dict:
    """Duyệt MỘT kiểu bằng cách gộp video vào một cụm THẬT ĐÃ CÓ
    (`gop_vao_cum_id` của `/duyet`) thay vì tạo/tìm cụm theo tên (D13/D16) —
    dùng khi user tự chọn "gộp vào cụm có sẵn" mà tên không trùng (khác
    `_giai_quyet_kieu`, hàm này KHÔNG bao giờ trả `{"trung": ...}`: đích đã
    được người dùng CHỌN TAY, không cần hỏi lại).

    Cụm đích PHẢI của CHÍNH `chu` (D17) — cụm của người khác ⇒ `ValueError`
    (400). Video đã có cụm thật bị bỏ qua, y hệt `duyet_kieu` thường (D14).
    `usecase`/`insight_goc` không trống (D18) đã được người GỌI kiểm TRƯỚC
    khi gọi hàm này — không nới lỏng riêng cho đường này (ĐP-169)."""
    nhom_row = conn.execute(
        "SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
        (cum_nhap_id, chia_lan_id)).fetchone()
    if nhom_row is None:
        return {"loi": "khong_tim_thay"}
    if conn.execute("SELECT 1 FROM cum WHERE id = ? AND chu = ?",
                    (cum_id_dich, chu)).fetchone() is None:
        raise ValueError(f"cụm {cum_id_dich} không tồn tại hoặc không phải của bạn")

    video_ids = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM video_cum_nhap WHERE chia_lan_id = ? "
        "AND cum_nhap_id = ? AND lan = 'kieu'", (chia_lan_id, cum_nhap_id)).fetchall()]

    # Cùng kiểm lại + cùng lọc thư viện mà `_giai_quyet_kieu` áp dụng — xem
    # docstring ở đó.
    da_o_cum, con_lai = [], []
    for vid in video_ids:
        if conn.execute("SELECT 1 FROM video_cum WHERE video_id = ? AND chu = ?",
                        (vid, chu)).fetchone():
            da_o_cum.append(vid)
        else:
            con_lai.append(vid)

    bi_bo: list[str] = []
    if con_lai:
        marks = ",".join("?" * len(con_lai))
        hop_le = {r["video_id"] for r in conn.execute(
            f"SELECT v.video_id FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.video_id IN ({marks}) AND v.da_loai_luc IS NULL "
            f"AND (? IS NULL OR j.nguoi_tao = ?)",
            [*con_lai, chi_cua, chi_cua]).fetchall()}
        bi_bo = [v for v in con_lai if v not in hop_le]
        con_lai = [v for v in con_lai if v in hop_le]

    if con_lai:
        conn.executemany(
            "INSERT INTO video_cum (video_id, chu, cum_id) VALUES (?, ?, ?) "
            "ON CONFLICT(video_id, chu) DO UPDATE SET cum_id = excluded.cum_id",
            [(vid, chu, cum_id_dich) for vid in con_lai])
    conn.execute("DELETE FROM cum_nhap WHERE id = ?", (cum_nhap_id,))

    return {"cum_nhap_id": cum_nhap_id, "cum_id": cum_id_dich, "da_co": True,
            "gan": con_lai, "da_o_cum": da_o_cum, "bi_bo": bi_bo}


def _chia_lan_xong_neu_het_kieu(conn, chia_lan_id: int, luc: str) -> None:
    con = conn.execute("SELECT COUNT(*) FROM cum_nhap WHERE chia_lan_id = ?",
                       (chia_lan_id,)).fetchone()[0]
    if con == 0:
        conn.execute("UPDATE chia_lan SET trang_thai = 'da_duyet', duyet_luc = ? WHERE id = ?",
                    (luc, chia_lan_id))


def _kiem_trang_thai_de_xuat(lan) -> None:
    """`ap_thao_tac`/`duyet_kieu`/`duyet_het` chỉ được chạy khi lượt đang
    `de_xuat`. Sửa/duyệt một lượt `da_duyet` hồi sinh dữ liệu đã chốt (vd một
    `hoan_tac` sau khi đã `duyet_het` đẩy một kiểu cũ trở lại nháp trong khi
    lượt vẫn báo `da_duyet` — nhật ký/trạng thái lệch nhau mà không ai thấy);
    sửa một lượt `cho_hinh` đi trước cả tầng hình; và một lượt `huy` là điểm
    dừng, không phải chỗ còn thao tác được."""
    if lan["trang_thai"] != "de_xuat":
        raise ValueError(
            f"lượt đang '{lan['trang_thai']}' — chỉ sửa/duyệt được nháp khi đang 'de_xuat'")


def _kiem_insight_khong_trong(usecase: str | None, insight_goc: str | None) -> None:
    """`usecase`/`insight_goc` là thuộc tính của CẢ LƯỢT, không phải của
    riêng một kiểu — trống (cả trong body request lẫn giá trị đã lưu ở
    `chia_lan`, sau khi `_ap_doi_insight_neu_co` đã áp mọi giá trị body) thì
    KHÔNG kiểu nào duyệt được. Phải chặn NGAY một lần cho cả lượt (400)
    TRƯỚC khi xử tới từng kiểu — không được để rơi vào `loi_ten` của một kiểu
    như một lỗi TÊN riêng (kiểu vẫn có thể có tên hợp lệ), và `duyet_kieu`
    lẫn `duyet_het` phải trả cùng một câu chữ cho cùng một tình huống."""
    if not usecase or not insight_goc:
        raise ValueError(
            "usecase/insight gốc của lượt còn trống — điền usecase và insight gốc trước khi duyệt")


def duyet_kieu(db_path: Path, chia_lan_id: int, cum_nhap_id: int, chu: str,
              chi_cua: str | None, usecase: str | None = None,
              insight_goc: str | None = None,
              xac_nhan_gop: list[int] | None = None,
              gop_vao_cum_id: int | None = None) -> dict | None:
    """Duyệt MỘT kiểu nháp thành cụm thật (hoặc gộp vào cụm có sẵn) — lối DUY
    NHẤT từ nháp sang `cum`. `None` ⇒ lượt không phải của `chu`, hoặc
    `cum_nhap_id` không thuộc lượt (không ghi gì, kể cả `doi_insight`).

    `usecase`/`insight_goc` bỏ trống ⇒ dùng giá trị đã lưu ở `chia_lan`.

    `gop_vao_cum_id`: user tự CHỌN TAY một cụm có sẵn (khác D13, vốn chỉ hỏi
    khi TÊN trùng) — xem `_giai_quyet_kieu_vao_cum`. D18 (insight/usecase
    không trống) áp TRƯỚC đường này y hệt đường thường, không nới lỏng riêng.
    """
    xac_nhan = set(xac_nhan_gop or [])
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        lan = _lan_cua_toi(conn, chia_lan_id, chu)
        if lan is None:
            return None
        _kiem_trang_thai_de_xuat(lan)
        # Kiểm id TRƯỚC `_ap_doi_insight_neu_co`: trả `None` (404) sau khi đã
        # ghi `doi_insight` thì transaction vẫn COMMIT phần đó — một yêu cầu
        # bị từ chối không được để lại dấu nào.
        if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                        (cum_nhap_id, chia_lan_id)).fetchone() is None:
            return None
        u, g = _ap_doi_insight_neu_co(conn, chia_lan_id, chu, lan, usecase, insight_goc)
        _kiem_insight_khong_trong(u, g)
        if gop_vao_cum_id is not None:
            ket = _giai_quyet_kieu_vao_cum(conn, chia_lan_id, cum_nhap_id, chu, chi_cua,
                                           gop_vao_cum_id)
        else:
            ket = _giai_quyet_kieu(conn, chia_lan_id, cum_nhap_id, chu, chi_cua, u, g, xac_nhan, {})
        if ket.get("loi"):
            return None
        if "trung" in ket:
            return {"trung_cum_co_san": [ket["trung"]]}
        luc = _now()
        conn.execute(
            "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, "
            "chi_tiet_json, luc, the_he) VALUES (?, ?, 'duyet_kieu', ?, ?, ?, ?)",
            (chia_lan_id, chu, len(ket["gan"]), json.dumps(ket, ensure_ascii=False), luc,
             lan["the_he"]))
        # Duyệt được BẤT CỨ GÌ là một điểm CHỐT: bump `the_he` ngay ở đây làm
        # MỌI thao tác sửa nháp trước đó (dù chưa từng bị hoàn tác) mang
        # `the_he` CŨ, nên bộ lọc `AND the_he = ?` của `_op_hoan_tac` loại hết
        # chúng — hoàn tác không còn cách nào lùi XUYÊN QUA một lần duyệt.
        # Thiếu bump này, `chuyen`/`gop` một video/kiểu RỒI DUYỆT đúng chỗ đó
        # RỒI `hoan_tac` sẽ cố phục hồi một `cum_nhap.id` đã bị xoá thật khi
        # duyệt ⇒ `sqlite3.IntegrityError` (khoá ngoại) — route chỉ bắt
        # `ValueError` nên lộ ra thành 500 thay vì 400.
        conn.execute("UPDATE chia_lan SET the_he = the_he + 1 WHERE id = ?", (chia_lan_id,))
        _chia_lan_xong_neu_het_kieu(conn, chia_lan_id, luc)
    return {"cum_id": ket["cum_id"], "da_co": ket["da_co"], "gan": ket["gan"],
            "da_o_cum": ket["da_o_cum"], "bi_bo": ket["bi_bo"]}


def duyet_het(db_path: Path, chia_lan_id: int, chu: str, chi_cua: str | None,
             usecase: str | None = None, insight_goc: str | None = None,
             xac_nhan_gop: list[int] | None = None) -> dict | None:
    """Duyệt TẤT CẢ kiểu nháp CÒN LẠI của lượt, trong MỘT transaction và MỘT
    dòng nhật ký (mỗi bấm = một dòng, kể cả khi "Duyệt tất cả" xử lý nhiều
    kiểu cùng lúc).

    Kiểu nào trùng tên cụm có sẵn mà chưa được xác nhận thì KHÔNG duyệt, báo
    lại ở `trung_cum_co_san` và Ở LẠI trong nháp; các kiểu còn lại vẫn duyệt —
    "duyệt tất cả" vẫn nên đi được phần an toàn thay vì kẹt cứng vì một cái
    tên trùng.

    Một kiểu có tên (usecase/insight gốc/kiểu, hay bản ghép nhóm+kiểu khi
    trùng — xem `_giai_va_cham_ten`) không hợp lệ (`kiem_nhan` raise) bị báo lại
    ở `loi_ten` (kèm `cum_nhap_id` + lý do) và BỎ QUA — ở NGUYÊN trong nháp
    cho tới khi người dùng sửa tên — thay vì làm sập TOÀN BỘ transaction.
    """
    xac_nhan = set(xac_nhan_gop or [])
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        lan = _lan_cua_toi(conn, chia_lan_id, chu)
        if lan is None:
            return None
        _kiem_trang_thai_de_xuat(lan)
        u, g = _ap_doi_insight_neu_co(conn, chia_lan_id, chu, lan, usecase, insight_goc)
        _kiem_insight_khong_trong(u, g)
        nhom_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cum_nhap WHERE chia_lan_id = ? ORDER BY thu_tu, id",
            (chia_lan_id,)).fetchall()]
        trung: list[dict] = []
        chi_tiet: list[dict] = []
        loi_ten: list[dict] = []
        tong_gan = 0
        # Chia sẻ MỘT map "đã tạo/dùng trong lượt gọi này" xuyên suốt vòng
        # lặp — xem docstring `_giai_quyet_kieu` (`da_tao_trong_luot`).
        da_tao_trong_luot: dict[tuple[str, str], int] = {}
        for cum_nhap_id in nhom_ids:
            try:
                ket = _giai_quyet_kieu(conn, chia_lan_id, cum_nhap_id, chu, chi_cua, u, g,
                                       xac_nhan, da_tao_trong_luot)
            except ValueError as exc:
                loi_ten.append({"cum_nhap_id": cum_nhap_id, "ly_do": str(exc)})
                continue
            if ket.get("loi"):
                continue
            if "trung" in ket:
                trung.append(ket["trung"])
                continue
            chi_tiet.append(ket)
            tong_gan += len(ket["gan"])
        if chi_tiet:
            luc = _now()
            conn.execute(
                "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, "
                "chi_tiet_json, luc, the_he) VALUES (?, ?, 'duyet_het', ?, ?, ?, ?)",
                (chia_lan_id, chu, tong_gan,
                 json.dumps({"cum": chi_tiet, "trung_cum_co_san": trung, "loi_ten": loi_ten},
                            ensure_ascii=False),
                 luc, lan["the_he"]))
            # Cùng lý do bump ở `duyet_kieu`: có ít nhất MỘT kiểu được duyệt
            # trong lượt gọi này là đủ để CHỐT thế hệ — hoàn tác sau đó không
            # còn lùi xuyên qua được, kể cả với các kiểu KHÁC (chưa duyệt,
            # còn `trung_cum_co_san` hoặc `loi_ten`) của cùng lượt.
            conn.execute("UPDATE chia_lan SET the_he = the_he + 1 WHERE id = ?", (chia_lan_id,))
            _chia_lan_xong_neu_het_kieu(conn, chia_lan_id, luc)
    return {"cum": chi_tiet, "trung_cum_co_san": trung, "loi_ten": loi_ten}


# ---------------------------------------------------------------------------
# Thao tác sửa nháp (POST /chia/{id}/thao-tac) — mỗi hàm `_op_*` VALIDATE
# đích trước khi ghi bất cứ gì, rồi trả `(so_video, chi_tiet) | None`.
# `None` ⇒ thao tác TRƯỢT ⇒ `ap_thao_tac` không ghi dòng nhật ký nào: một
# thao tác không ghi được nhật ký thì coi như KHÔNG xảy ra — và ngược lại,
# không thao tác nào được phép ghi dữ liệu MÀ không kèm một dòng nhật ký.
# ---------------------------------------------------------------------------

def _op_chap_nhan(conn, chia_lan_id, chu, lan, cum_nhap_id: int, **_):
    """Chấp nhận một kiểu ĐÚNG như đề xuất — không đổi dữ liệu, chỉ ghi nhận
    người dùng đã xem qua (đếm vào nhật ký như một cú bấm)."""
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    n = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
                     "AND cum_nhap_id = ?", (chia_lan_id, cum_nhap_id)).fetchone()[0]
    return n, {"cum_nhap_id": cum_nhap_id}


def _op_doi_ten(conn, chia_lan_id, chu, lan, cum_nhap_id: int, kieu: str,
                nhom: str | None = None, **_):
    row = conn.execute("SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                       (cum_nhap_id, chia_lan_id)).fetchone()
    if row is None:
        return None
    kieu_moi = models_cum.chuan_hoa_chu(kieu)
    if not kieu_moi:
        return None
    nhom_moi = models_cum.chuan_hoa_chu(nhom) if nhom else row["nhom"]
    conn.execute("UPDATE cum_nhap SET nhom = ?, kieu = ? WHERE id = ?",
                (nhom_moi, kieu_moi, cum_nhap_id))
    # Đổi tên là điểm DUY NHẤT sau `ghi_de_xuat` được tính lại tên — và chỉ
    # cho CHÍNH hàng này. Tên cũ của nó đi vào nhật ký để `hoan_tac` trả lại
    # đúng.
    ten_cum_truoc = _chot_ten_sau_doi_ten(conn, chia_lan_id, cum_nhap_id)
    n = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
                     "AND cum_nhap_id = ?", (chia_lan_id, cum_nhap_id)).fetchone()[0]
    return n, {"cum_nhap_id": cum_nhap_id, "truoc": {"nhom": row["nhom"], "kieu": row["kieu"]},
              "sau": {"nhom": nhom_moi, "kieu": kieu_moi}, "ten_cum_truoc": ten_cum_truoc}


def _kiem_video_ids_thao_tac(conn, chia_lan_id, chu, video_ids, *, lan_khong_hop_le=()):
    """Kiểm TRƯỚC KHI GHI cho bốn thao tác di chuyển video theo id
    (`tach`/`chuyen`/`ngoai_chu_de`/`tra_ve`): MỌI video trong `video_ids`
    phải hợp lệ, hay từ chối CẢ yêu cầu — trước đây mỗi hàm `_op_*` tự lọc
    video không hợp lệ rồi âm thầm chạy tiếp trên phần còn lại, làm một danh
    sách TRỘN (vài video hợp lệ + vài không) chỉ áp một phần mà người gọi
    không biết (409 chỉ trả khi TOÀN BỘ danh sách bị lọc).

    Video KHÔNG hợp lệ khi: (a) ĐÃ nằm trong một cụm THẬT của `chu`
    (`video_cum` — duyệt hoặc gán tay; hàng nháp của nó có thể vẫn còn "mồ
    côi" `lan='kieu'`, xem `_hang_video_cum_nhap`); (b) không có hàng
    `video_cum_nhap` nào của LƯỢT NÀY (id giả, hoặc đã bị loại/đổi chủ sau
    khi đề xuất); (c) mang `lan` nằm trong `lan_khong_hop_le` — tham số
    này KHÁC NHAU theo op gọi: `ngoai_chu_de` truyền `("nghi",)` (đã ở nghi
    rồi là SAI, không phải no-op im lặng nữa — hợp đồng chỉ có MỘT trạng
    thái "nghi"); `tra_ve` truyền `("kieu",)` (đang ở một kiểu là việc của
    `chuyen`, không phải `tra_ve`); `tach`/`chuyen` không truyền gì (mọi làn
    đều là đích hợp lệ của hai op đó); hoặc (d) THUỘC lượt này nhưng đã bị
    LOẠI khỏi thư viện (`videos.da_loai_luc`) — chỉ xét id thuộc lượt, để id
    của người khác không bao giờ nhận mã riêng này.

    Trả `None` nếu MỌI video hợp lệ (không ghi gì — người gọi tự đọc lại
    hàng để thao tác). Trả `{"tu_choi": "video_da_o_cum_that",
    "video_ids": [...]}` (lý do RIÊNG, đủ để UI báo đúng — xem route/UI) nếu
    CÓ video thuộc lý do (a), ngay cả khi danh sách còn lẫn lý do khác — đây
    là lý do người dùng cần biết nhất, "sao không di chuyển được" trên video
    còn đang hiện trong nháp. Sau đó `{"tu_choi": "video_da_loai",
    "video_ids": [...]}` cho lý do (d). Trả `{"tu_choi": "khong_hop_le"}`
    (giữ nguyên câu chữ cũ) cho lý do (b)/(c)."""
    unique_ids = list(dict.fromkeys(video_ids or []))
    if not unique_ids:
        return None
    marks = ",".join("?" * len(unique_ids))
    trong_luot = {r["video_id"]: r["lan"] for r in conn.execute(
        f"SELECT video_id, lan FROM video_cum_nhap WHERE chia_lan_id = ? "
        f"AND video_id IN ({marks})", (chia_lan_id, *unique_ids)).fetchall()}
    da_o_cum = {r["video_id"] for r in conn.execute(
        f"SELECT video_id FROM video_cum WHERE chu = ? AND video_id IN ({marks})",
        (chu, *unique_ids)).fetchall()}
    da_o_cum_that = sorted(v for v in unique_ids if v in da_o_cum)
    if da_o_cum_that:
        return {"tu_choi": "video_da_o_cum_that", "video_ids": da_o_cum_that}
    # (d) Video đã bị LOẠI khỏi thư viện (Drive → Thùng rác) vẫn còn hàng
    # `video_cum_nhap` của lượt — `lay_chia` chỉ ẨN nó khỏi mọi làn. Không chặn
    # ở đây thì một lệnh dock đến SAU lượt Loại (tab cũ, hoặc bấm trong lúc Loại
    # đang gửi) vẫn chuyển/tách nó vào kiểu ⇒ sinh một kiểu RỖNG trên UI mà duyệt
    # xong chỉ báo `bi_bo`.
    # CHỈ id thuộc lượt này (`trong_luot`): `da_loai_luc` là cột toàn cục, báo
    # mã riêng cho id của người khác sẽ cho bất kỳ ai dò "video X có trong kho
    # và đã bị loại". Id ngoài lượt rơi xuống `khong_hop_le` như mọi id lạ.
    da_loai = sorted(r["video_id"] for r in conn.execute(
        f"SELECT video_id FROM videos WHERE da_loai_luc IS NOT NULL "
        f"AND video_id IN ({marks})", unique_ids).fetchall() if r["video_id"] in trong_luot)
    if da_loai:
        return {"tu_choi": "video_da_loai", "video_ids": da_loai}
    khong_hop_le = [v for v in unique_ids
                    if v not in trong_luot or trong_luot[v] in lan_khong_hop_le]
    if khong_hop_le:
        return {"tu_choi": "khong_hop_le"}
    return None


def _op_tach(conn, chia_lan_id, chu, lan, video_ids: list[str] | None, nhom: str, kieu: str,
            **_):
    """Tách các video (đang ở BẤT KỲ làn nào trong lượt, như `_op_chuyen`)
    sang một `cum_nhap` MỚI (nhóm/kiểu chuẩn hoá bằng `chuan_hoa_chu`,
    `thu_tu` sau hàng lớn nhất hiện có). Tên hàng mới tính NHƯ `_op_doi_ten`
    (D19: chỉ hàng vừa tạo, không đụng tên hàng khác).

    Danh sách TRỘN (vài video hợp lệ + vài không, xem
    `_kiem_video_ids_thao_tac`) bị từ chối CẢ YÊU CẦU — không tách phần hợp
    lệ rồi lặng lẽ bỏ phần còn lại."""
    kieu_moi = models_cum.chuan_hoa_chu(kieu)
    nhom_moi = models_cum.chuan_hoa_chu(nhom)
    if not video_ids or not kieu_moi or not nhom_moi:
        return None
    tu_choi = _kiem_video_ids_thao_tac(conn, chia_lan_id, chu, video_ids)
    if tu_choi is not None:
        return tu_choi
    truoc = _hang_video_cum_nhap(conn, chia_lan_id, chu, video_ids)
    if not truoc:
        return None
    thu_tu_max = conn.execute(
        "SELECT MAX(thu_tu) FROM cum_nhap WHERE chia_lan_id = ?", (chia_lan_id,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO cum_nhap (chia_lan_id, nhom, kieu, thu_tu) VALUES (?, ?, ?, ?)",
        (chia_lan_id, nhom_moi, kieu_moi, (thu_tu_max if thu_tu_max is not None else -1) + 1))
    cum_nhap_id = int(cur.lastrowid)
    conn.executemany(
        "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
        "WHERE chia_lan_id = ? AND video_id = ?",
        [(cum_nhap_id, chia_lan_id, r["video_id"]) for r in truoc])
    # Tên hàng MỚI — chỉ hàng này, giống `_op_doi_ten` (D19).
    _chot_ten_sau_doi_ten(conn, chia_lan_id, cum_nhap_id)
    return len(truoc), {"cum_nhap_id": cum_nhap_id, "nhom": nhom_moi, "kieu": kieu_moi,
                        "video_ids": [r["video_id"] for r in truoc], "truoc": truoc}


def _op_gop(conn, chia_lan_id, chu, lan, tu_cum_nhap_id: int, den_cum_nhap_id: int, **_):
    """Gộp nhóm `tu_cum_nhap_id` vào `den_cum_nhap_id` — mọi video của nhóm
    nguồn chuyển sang nhóm đích, nhóm nguồn biến mất khỏi nháp."""
    if tu_cum_nhap_id == den_cum_nhap_id:
        return None
    tu = conn.execute("SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                      (tu_cum_nhap_id, chia_lan_id)).fetchone()
    den = conn.execute("SELECT id FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                       (den_cum_nhap_id, chia_lan_id)).fetchone()
    if tu is None or den is None:
        return None
    video_ids = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM video_cum_nhap WHERE chia_lan_id = ? AND cum_nhap_id = ?",
        (chia_lan_id, tu_cum_nhap_id)).fetchall()]
    conn.execute(
        "UPDATE video_cum_nhap SET cum_nhap_id = ? WHERE chia_lan_id = ? AND cum_nhap_id = ?",
        (den_cum_nhap_id, chia_lan_id, tu_cum_nhap_id))
    conn.execute("DELETE FROM cum_nhap WHERE id = ?", (tu_cum_nhap_id,))
    # KHÔNG tính lại tên kiểu nào (xem `_chot_ten_moi_kieu`); `tu_ten_cum`
    # để `hoan_tac` hồi sinh nguồn với đúng tên nó có.
    return len(video_ids), {"tu_cum_nhap_id": tu_cum_nhap_id, "den_cum_nhap_id": den_cum_nhap_id,
                            "video_ids": video_ids, "tu_nhom": tu["nhom"], "tu_kieu": tu["kieu"],
                            "tu_thu_tu": tu["thu_tu"], "tu_ten_cum": tu["ten_cum"]}


def _op_gop_nhom(conn, chia_lan_id, chu, lan, cum_nhap_ids: list[int] | None,
                den_cum_nhap_id: int, **_):
    """Gộp NHIỀU kiểu (`cum_nhap_ids`) vào MỘT kiểu đích trong MỘT cú bấm =
    MỘT dòng nhật ký (D15) — mirror `_op_gop` với danh sách nguồn thay vì
    một. VALIDATE mọi nguồn tồn tại trước khi đổi bất cứ gì (mọi `_op_*` phải
    vậy); một nguồn không thuộc lượt ⇒ từ chối CẢ thao tác, không gộp một
    phần."""
    ids = [i for i in dict.fromkeys(cum_nhap_ids or []) if i != den_cum_nhap_id]
    if not ids:
        return None
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (den_cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    hang = {}
    for tu_id in ids:
        row = conn.execute("SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                           (tu_id, chia_lan_id)).fetchone()
        if row is None:
            return None
        hang[tu_id] = row
    nguon = []
    tong = 0
    for tu_id in ids:
        row = hang[tu_id]
        video_ids = [r["video_id"] for r in conn.execute(
            "SELECT video_id FROM video_cum_nhap WHERE chia_lan_id = ? AND cum_nhap_id = ?",
            (chia_lan_id, tu_id)).fetchall()]
        conn.execute(
            "UPDATE video_cum_nhap SET cum_nhap_id = ? WHERE chia_lan_id = ? AND cum_nhap_id = ?",
            (den_cum_nhap_id, chia_lan_id, tu_id))
        conn.execute("DELETE FROM cum_nhap WHERE id = ?", (tu_id,))
        nguon.append({"cum_nhap_id": tu_id, "nhom": row["nhom"], "kieu": row["kieu"],
                     "thu_tu": row["thu_tu"], "ten_cum": row["ten_cum"], "video_ids": video_ids})
        tong += len(video_ids)
    # KHÔNG tính lại tên kiểu nào (như `_op_gop`); mỗi nguồn giữ `ten_cum` của
    # nó để `hoan_tac` hồi sinh đúng.
    return tong, {"den_cum_nhap_id": den_cum_nhap_id, "nguon": nguon}


def _op_doi_ten_nhom(conn, chia_lan_id, chu, lan, nhom_cu: str, nhom_moi: str, **_):
    """Đổi tên MỘT NHÓM — đổi `nhom` của MỌI `cum_nhap` của lượt khớp
    `nhom_cu` (so ĐÚNG chuỗi sau chuẩn hoá khoảng trắng — `chuan_hoa_chu`,
    KHÔNG casefold — đúng cách trang JS gom nhóm: `nhomsOf`/bộ lọc dùng
    `k.nhom === nhom`, so chuỗi CHÍNH XÁC) trong MỘT dòng nhật ký, MỘT
    transaction (atomic — khác vòng lặp `doi_ten` phía client trước đây, N
    request rời cho N kiểu của một nhóm, có thể trượt giữa chừng để lại nhóm
    đổi tên một nửa).

    So theo `_khoa_ten` (casefold) từng SAI trước đây: hai nhóm hiển thị
    RIÊNG trên UI vì khác hoa/thường (vd "tp"/"TP", hai thẻ khác nhau trên
    màn) lại bị server coi là MỘT khi đổi tên, đổi luôn cả nhóm "khác" mà
    người dùng không hề chạm tới.

    Tên từng hàng bị đổi tính lại NHƯ `_op_doi_ten` (D19: chỉ hàng của
    NHÓM đó, không đụng tên hàng ngoài nhóm) — gọi `_chot_ten_sau_doi_ten`
    cho từng hàng SAU KHI đã đổi `nhom` của CẢ nhóm, để hàng nào so trùng
    "cùng kiểu" cũng thấy đúng `nhom` mới của các hàng anh em.

    Không có hàng nào khớp `nhom_cu`, hoặc `nhom_moi` rỗng sau chuẩn hoá ⇒
    `None` (cùng luật "khong_hop_le" các `_op_*` khác dùng)."""
    nhom_moi_chuan = models_cum.chuan_hoa_chu(nhom_moi)
    if not nhom_moi_chuan:
        return None
    nhom_cu_chuan = models_cum.chuan_hoa_chu(nhom_cu)
    hang = conn.execute("SELECT id, nhom, ten_cum FROM cum_nhap WHERE chia_lan_id = ?",
                        (chia_lan_id,)).fetchall()
    khop = [r for r in hang if models_cum.chuan_hoa_chu(r["nhom"]) == nhom_cu_chuan]
    if not khop:
        return None
    conn.executemany("UPDATE cum_nhap SET nhom = ? WHERE id = ?",
                     [(nhom_moi_chuan, r["id"]) for r in khop])
    # `truoc`: MỘT dòng cho MỖI hàng bị đổi — `nhom_truoc`/`ten_cum_truoc` để
    # `hoan_tac` trả lại đúng của TỪNG hàng (không suy ngược từ `nhom_cu`, vì
    # tên nhóm gốc trên mỗi hàng có thể lệch dấu cách/hoa-thường dù cùng khoá
    # `_khoa_ten`).
    truoc = []
    for r in khop:
        ten_cum_truoc = _chot_ten_sau_doi_ten(conn, chia_lan_id, r["id"])[str(r["id"])]
        truoc.append({"cum_nhap_id": r["id"], "nhom_truoc": r["nhom"],
                     "ten_cum_truoc": ten_cum_truoc})
    marks = ",".join("?" * len(khop))
    n = conn.execute(
        f"SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? AND cum_nhap_id IN ({marks})",
        (chia_lan_id, *[r["id"] for r in khop])).fetchone()[0]
    return n, {"nhom_moi": nhom_moi_chuan, "truoc": truoc}


def _hang_video_cum_nhap(conn, chia_lan_id, chu, video_ids):
    """Hàng `video_cum_nhap` của các `video_ids` — BỎ những video ĐÃ nằm
    trong một cụm THẬT của `chu` (`video_cum`), kể cả khi hàng nháp của nó
    còn "mồ côi" (`lan = 'kieu'`, `cum_nhap_id = NULL` sau khi kiểu chứa nó
    được DUYỆT — FK `ON DELETE SET NULL` chỉ lo cột `cum_nhap_id`, không tự
    đổi `lan`). Không lọc thì `tach`/`chuyen`/`ngoai_chu_de` có thể kéo một
    video ĐÃ DUYỆT trở lại nháp — dữ liệu `video_cum` không đổi, nhưng màn
    nháp báo sai và ghi thêm một dòng nhật ký vô nghĩa cho một video không
    còn thuộc phạm vi sửa của lượt này."""
    if not video_ids:
        return []
    marks = ",".join("?" * len(video_ids))
    return [dict(r) for r in conn.execute(
        f"SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap "
        f"WHERE chia_lan_id = ? AND video_id IN ({marks}) "
        f"AND video_id NOT IN (SELECT video_id FROM video_cum WHERE chu = ?)",
        [chia_lan_id, *video_ids, chu]).fetchall()]


def _op_chuyen(conn, chia_lan_id, chu, lan, video_ids: list[str] | None,
              den_cum_nhap_id: int, **_):
    """Chuyển các video (đang ở BẤT KỲ làn nào trong lượt) sang kiểu
    `den_cum_nhap_id`. Danh sách TRỘN bị từ chối CẢ YÊU CẦU — xem
    `_kiem_video_ids_thao_tac`."""
    if not video_ids:
        return None
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (den_cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    tu_choi = _kiem_video_ids_thao_tac(conn, chia_lan_id, chu, video_ids)
    if tu_choi is not None:
        return tu_choi
    truoc = _hang_video_cum_nhap(conn, chia_lan_id, chu, video_ids)
    if not truoc:
        return None
    conn.executemany(
        "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
        "WHERE chia_lan_id = ? AND video_id = ?",
        [(den_cum_nhap_id, chia_lan_id, r["video_id"]) for r in truoc])
    return len(truoc), {"video_ids": [r["video_id"] for r in truoc],
                        "den_cum_nhap_id": den_cum_nhap_id, "truoc": truoc}


def _op_ngoai_chu_de(conn, chia_lan_id, chu, lan, video_ids: list[str] | None, **_):
    """Đưa các video sang làn "nghi ngoài chủ đề" — bỏ khỏi mọi kiểu.

    Video ĐÃ ở làn "nghi" rồi là KHÔNG HỢP LỆ cho chính op này — hợp đồng chỉ
    có MỘT trạng thái "nghi" (`hop-dong-thao-tac.md`), không có trạng thái
    "đã xác nhận bỏ khỏi lượt" riêng, nên gọi lại op này trên video đã ở
    nghi không phải là một no-op im lặng mà là một yêu cầu SAI (`tu_choi`,
    xem `_kiem_video_ids_thao_tac`, `lan_khong_hop_le=("nghi",)`) — và một
    danh sách TRỘN (vài video hợp lệ + vài đã ở nghi) bị từ chối CẢ yêu cầu,
    không âm thầm chỉ chuyển phần hợp lệ."""
    if not video_ids:
        return None
    tu_choi = _kiem_video_ids_thao_tac(conn, chia_lan_id, chu, video_ids,
                                       lan_khong_hop_le=("nghi",))
    if tu_choi is not None:
        return tu_choi
    truoc = _hang_video_cum_nhap(conn, chia_lan_id, chu, video_ids)
    if not truoc:
        return None
    conn.executemany(
        "UPDATE video_cum_nhap SET cum_nhap_id = NULL, lan = 'nghi' "
        "WHERE chia_lan_id = ? AND video_id = ?",
        [(chia_lan_id, r["video_id"]) for r in truoc])
    return len(truoc), {"video_ids": [r["video_id"] for r in truoc], "truoc": truoc}


def _op_tra_ve(conn, chia_lan_id, chu, lan, video_ids: list[str] | None,
              den_cum_nhap_id: int, **_):
    """Trả video đang ở làn "hướng dẫn"/"nghi" VỀ một kiểu — khác `chuyen` ở
    chỗ chỉ nhận video KHÔNG đang ở một kiểu nào (đó là việc của `chuyen`,
    `lan_khong_hop_le=("kieu",)` ở `_kiem_video_ids_thao_tac`).

    Cùng luật loại-trừ với `_hang_video_cum_nhap`: video ĐÃ nằm trong một cụm
    THẬT của `chu` không được kéo trở lại nháp, dù hàng của nó đang mang
    `lan='nghi'` (vd sau một `ngoai_chu_de` gọi TRÊN video đã duyệt trước khi
    có luật lọc này). Danh sách TRỘN bị từ chối CẢ YÊU CẦU."""
    if not video_ids:
        return None
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (den_cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    tu_choi = _kiem_video_ids_thao_tac(conn, chia_lan_id, chu, video_ids,
                                       lan_khong_hop_le=("kieu",))
    if tu_choi is not None:
        return tu_choi
    marks = ",".join("?" * len(video_ids))
    truoc = [dict(r) for r in conn.execute(
        f"SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap WHERE chia_lan_id = ? "
        f"AND video_id IN ({marks}) AND lan != 'kieu' "
        f"AND video_id NOT IN (SELECT video_id FROM video_cum WHERE chu = ?)",
        [chia_lan_id, *video_ids, chu]).fetchall()]
    if not truoc:
        return None
    conn.executemany(
        "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
        "WHERE chia_lan_id = ? AND video_id = ?",
        [(den_cum_nhap_id, chia_lan_id, r["video_id"]) for r in truoc])
    return len(truoc), {"video_ids": [r["video_id"] for r in truoc],
                        "den_cum_nhap_id": den_cum_nhap_id, "truoc": truoc}


def _op_xoa_kieu(conn, chia_lan_id, chu, lan, cum_nhap_id: int, **_):
    """Xoá một đề xuất kiểu — video của nó KHÔNG biến mất khỏi lượt, rơi về
    làn "nghi" (cần xem lại), đúng luật FK `ON DELETE SET NULL` chỉ lo phần
    `cum_nhap_id`, còn `lan` phải tự tay cập nhật ở đây."""
    row = conn.execute("SELECT * FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                       (cum_nhap_id, chia_lan_id)).fetchone()
    if row is None:
        return None
    video_ids = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM video_cum_nhap WHERE chia_lan_id = ? AND cum_nhap_id = ?",
        (chia_lan_id, cum_nhap_id)).fetchall()]
    conn.execute(
        "UPDATE video_cum_nhap SET cum_nhap_id = NULL, lan = 'nghi' "
        "WHERE chia_lan_id = ? AND cum_nhap_id = ?", (chia_lan_id, cum_nhap_id))
    conn.execute("DELETE FROM cum_nhap WHERE id = ?", (cum_nhap_id,))
    # Cùng luật ở `_op_gop`: không tính lại tên; lưu `ten_cum` cho `hoan_tac`.
    return len(video_ids), {"cum_nhap_id": cum_nhap_id, "nhom": row["nhom"], "kieu": row["kieu"],
                            "thu_tu": row["thu_tu"], "ten_cum": row["ten_cum"],
                            "video_ids": video_ids}


def _op_doi_insight(conn, chia_lan_id, chu, lan, usecase: str | None = None,
                    insight_goc: str | None = None, **_):
    if usecase is None and insight_goc is None:
        return None
    u = models_cum.chuan_hoa_chu(usecase) if usecase is not None else lan["usecase"]
    g = models_cum.chuan_hoa_chu(insight_goc) if insight_goc is not None else lan["insight_goc"]
    conn.execute("UPDATE chia_lan SET usecase = ?, insight_goc = ? WHERE id = ?",
                (u, g, chia_lan_id))
    # Chỉ ghi ngược vào job của CHÍNH `chu` — xem lý do ở
    # `_ap_doi_insight_neu_co` (lớp chặn thứ hai, cùng luật).
    conn.execute("UPDATE jobs SET usecase = ?, insight_goc = ? WHERE id = ? AND nguoi_tao = ?",
                (u, g, lan["job_id"], chu))
    return 0, {"usecase": u, "insight_goc": g}


def _op_huy_luot(conn, chia_lan_id, chu, lan, **_):
    """Huỷ lượt — cho phép NGAY CẢ KHI đã duyệt một phần (video đã thành cụm
    thật đứng ngoài phạm vi của lượt: `DIEU_KIEN_VAO_LUOT_CHIA['da_o_cum']`
    loại chúng khỏi lượt chia lại kế tiếp). KHÔNG hoàn tác được — không nằm
    trong `_HOAN_TAC_DUOC` — vì `huy` là điểm dừng, không phải một bước có
    thể quay lại (giống lý do `huy` không "sống lại" ở `ghi_de_xuat`).
    `ap_thao_tac` đã tự khoá `trang_thai == 'de_xuat'` trước khi gọi hàm này,
    nên không cần kiểm lại ở đây."""
    conn.execute("UPDATE chia_lan SET trang_thai = 'huy' WHERE id = ?", (chia_lan_id,))
    return 0, {}


def _op_hoan_tac(conn, chia_lan_id, chu, lan, **_):
    """Hoàn tác thao tác sửa CẤU TRÚC gần nhất CHƯA bị lùi của lượt này
    (`_HOAN_TAC_DUOC`). `chap_nhan` không đổi gì để lùi; `duyet_kieu`/
    `duyet_het`/`hoan_tac`/`doi_insight` nằm ngoài phạm vi hoàn tác nháp này.

    Undo là một NGĂN XẾP, không phải "luôn áp lại dòng mới nhất": `AND da_lui
    = 0` loại các dòng ĐÃ được một `hoan_tac` trước đó xử lý — thiếu điều kiện
    này, undo lần hai chọn lại ĐÚNG dòng của lần một, áp lại y hệt (phục hồi
    sai, hoặc `IntegrityError` khi hai lần `gop` cùng chèn một `cum_nhap.id`).
    Ghi `da_lui = 1` cho dòng vừa lùi ở CUỐI hàm — cùng transaction với chính
    việc lùi, nên không có khe hở nửa-lùi.

    Không lùi xuyên thế hệ: `AND the_he = ?` giới hạn trong đúng thế hệ HIỆN
    TẠI của nháp — một `ghi_de_xuat` mới đã XOÁ sạch `cum_nhap`/
    `video_cum_nhap` cũ (xem `ghi_de_xuat`); lùi một thao tác của thế hệ trước
    sẽ chèn lại dữ liệu đã bị xoá, đè lên hoặc xung đột với đề xuất hiện tại.
    """
    marks = ",".join("?" * len(_HOAN_TAC_DUOC))
    hang = conn.execute(
        f"SELECT * FROM thao_tac_duyet WHERE chia_lan_id = ? AND loai IN ({marks}) "
        f"AND da_lui = 0 AND the_he = ? "
        f"ORDER BY id DESC LIMIT 1", (chia_lan_id, *_HOAN_TAC_DUOC, lan["the_he"])).fetchone()
    if hang is None:
        return None
    chi_tiet = json.loads(hang["chi_tiet_json"])
    loai = hang["loai"]
    # `hoan_tac` KHÔNG tính lại tên nào: nó trả lại đúng `ten_cum` đã lưu
    # trong dòng nhật ký gốc (`.get` — dòng ghi trước khi nhật ký mang khoá
    # này thì để NULL, lưới `ten_cum or kieu` lúc duyệt lo phần còn lại).
    if loai == "gop":
        conn.execute(
            "INSERT INTO cum_nhap (id, chia_lan_id, nhom, kieu, thu_tu, ten_cum) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chi_tiet["tu_cum_nhap_id"], chia_lan_id, chi_tiet["tu_nhom"], chi_tiet["tu_kieu"],
             chi_tiet["tu_thu_tu"], chi_tiet.get("tu_ten_cum")))
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ? WHERE chia_lan_id = ? AND video_id = ?",
            [(chi_tiet["tu_cum_nhap_id"], chia_lan_id, vid) for vid in chi_tiet["video_ids"]])
        so = len(chi_tiet["video_ids"])
    elif loai == "doi_ten":
        conn.execute("UPDATE cum_nhap SET nhom = ?, kieu = ? WHERE id = ?",
                    (chi_tiet["truoc"]["nhom"], chi_tiet["truoc"]["kieu"],
                     chi_tiet["cum_nhap_id"]))
        conn.executemany(
            "UPDATE cum_nhap SET ten_cum = ? WHERE id = ? AND chia_lan_id = ?",
            [(ten, int(cid), chia_lan_id)
             for cid, ten in chi_tiet.get("ten_cum_truoc", {}).items()])
        so = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
                          "AND cum_nhap_id = ?",
                          (chia_lan_id, chi_tiet["cum_nhap_id"])).fetchone()[0]
    elif loai == "xoa_kieu":
        conn.execute(
            "INSERT INTO cum_nhap (id, chia_lan_id, nhom, kieu, thu_tu, ten_cum) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chi_tiet["cum_nhap_id"], chia_lan_id, chi_tiet["nhom"], chi_tiet["kieu"],
             chi_tiet["thu_tu"], chi_tiet.get("ten_cum")))
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
            "WHERE chia_lan_id = ? AND video_id = ?",
            [(chi_tiet["cum_nhap_id"], chia_lan_id, vid) for vid in chi_tiet["video_ids"]])
        so = len(chi_tiet["video_ids"])
    elif loai == "tach":
        # `truoc` trả video về đúng {cum_nhap_id, lan} chúng có TRƯỚC khi bị
        # tách (như `chuyen`/`ngoai_chu_de`/`tra_ve`) RỒI mới xoá hàng mới —
        # thứ tự bắt buộc: xoá trước thì FK `ON DELETE SET NULL` sẽ ghi đè
        # NULL lên chỗ vừa phục hồi.
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = ? "
            "WHERE chia_lan_id = ? AND video_id = ?",
            [(r["cum_nhap_id"], r["lan"], chia_lan_id, r["video_id"])
             for r in chi_tiet["truoc"]])
        conn.execute("DELETE FROM cum_nhap WHERE id = ?", (chi_tiet["cum_nhap_id"],))
        so = len(chi_tiet["truoc"])
    elif loai == "gop_nhom":
        so = 0
        for ng in chi_tiet["nguon"]:
            conn.execute(
                "INSERT INTO cum_nhap (id, chia_lan_id, nhom, kieu, thu_tu, ten_cum) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ng["cum_nhap_id"], chia_lan_id, ng["nhom"], ng["kieu"], ng["thu_tu"],
                 ng.get("ten_cum")))
            conn.executemany(
                "UPDATE video_cum_nhap SET cum_nhap_id = ? WHERE chia_lan_id = ? AND video_id = ?",
                [(ng["cum_nhap_id"], chia_lan_id, vid) for vid in ng["video_ids"]])
            so += len(ng["video_ids"])
    elif loai == "doi_ten_nhom":
        conn.executemany("UPDATE cum_nhap SET nhom = ? WHERE id = ?",
                         [(r["nhom_truoc"], r["cum_nhap_id"]) for r in chi_tiet["truoc"]])
        conn.executemany(
            "UPDATE cum_nhap SET ten_cum = ? WHERE id = ? AND chia_lan_id = ?",
            [(r["ten_cum_truoc"], r["cum_nhap_id"], chia_lan_id) for r in chi_tiet["truoc"]])
        marks = ",".join("?" * len(chi_tiet["truoc"]))
        so = conn.execute(
            f"SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
            f"AND cum_nhap_id IN ({marks})",
            (chia_lan_id, *[r["cum_nhap_id"] for r in chi_tiet["truoc"]])).fetchone()[0]
    else:   # chuyen · ngoai_chu_de · tra_ve — đều lưu `truoc: [{video_id,cum_nhap_id,lan}]`
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = ? "
            "WHERE chia_lan_id = ? AND video_id = ?",
            [(r["cum_nhap_id"], r["lan"], chia_lan_id, r["video_id"])
             for r in chi_tiet["truoc"]])
        so = len(chi_tiet["truoc"])
    # Đánh dấu dòng GỐC đã bị lùi — đây là điều kiện `da_lui = 0` phía trên
    # dựa vào. Không có dòng này, undo kế tiếp lại chọn trúng đúng dòng này
    # lần nữa.
    conn.execute("UPDATE thao_tac_duyet SET da_lui = 1 WHERE id = ?", (hang["id"],))
    return so, {"hoan_tac_id": hang["id"], "loai_goc": loai}


_AP_THAO_TAC = {
    "chap_nhan": _op_chap_nhan,
    "doi_ten": _op_doi_ten,
    "gop": _op_gop,
    "chuyen": _op_chuyen,
    "ngoai_chu_de": _op_ngoai_chu_de,
    "tra_ve": _op_tra_ve,
    "xoa_kieu": _op_xoa_kieu,
    "doi_insight": _op_doi_insight,
    "hoan_tac": _op_hoan_tac,
    "tach": _op_tach,
    "gop_nhom": _op_gop_nhom,
    "doi_ten_nhom": _op_doi_ten_nhom,
    "huy_luot": _op_huy_luot,
}

# Trường BẮT BUỘC cho từng `loai` (hop-dong-thao-tac.md). Thiếu HẲN một
# trường ở đây (route lọc `None` ra khỏi payload trước khi tới đây, nên
# "thiếu" và "gửi None" là một) khiến hàm `_op_*` tương ứng thiếu tham số vị
# trí bắt buộc ⇒ `TypeError` ⇒ 500 nếu không được chặn sớm. Kiểm ở đây, TRƯỚC
# KHI mở transaction, biến nó thành `ValueError` (400) rõ ràng.
# `video_ids`/`cum_nhap_ids` còn bị đòi khác-rỗng (hợp đồng: "≥1") vì hàm
# `_op_*` coi rỗng và thiếu là một (`if not video_ids: return None` ⇒ 409
# "đích không hợp lệ"), nhưng ở TẦNG THAM SỐ thì rỗng và thiếu nên cùng là 400
# "thiếu trường".
_TRUONG_BAT_BUOC: dict[str, tuple[str, ...]] = {
    "chap_nhan": ("cum_nhap_id",),
    "doi_ten": ("cum_nhap_id", "kieu"),
    "gop": ("tu_cum_nhap_id", "den_cum_nhap_id"),
    "chuyen": ("video_ids", "den_cum_nhap_id"),
    "ngoai_chu_de": ("video_ids",),
    "tra_ve": ("video_ids", "den_cum_nhap_id"),
    "xoa_kieu": ("cum_nhap_id",),
    "doi_insight": (),
    "hoan_tac": (),
    "tach": ("video_ids", "nhom", "kieu"),
    "gop_nhom": ("cum_nhap_ids", "den_cum_nhap_id"),
    "doi_ten_nhom": ("nhom_cu", "nhom_moi"),
    "huy_luot": (),
}
# Trường DẠNG DANH SÁCH đòi khác-rỗng — xem chú thích trên `_TRUONG_BAT_BUOC`.
_TRUONG_DANH_SACH_BAT_BUOC_KHAC_RONG = ("video_ids", "cum_nhap_ids")


def _kiem_truong_bat_buoc(loai: str, tham_so: dict) -> None:
    for ten in _TRUONG_BAT_BUOC.get(loai, ()):
        gia_tri = tham_so.get(ten)
        if gia_tri is None or (ten in _TRUONG_DANH_SACH_BAT_BUOC_KHAC_RONG and not gia_tri):
            raise ValueError(f"thao tác '{loai}' thiếu trường bắt buộc '{ten}'")


def ap_thao_tac(db_path: Path, chia_lan_id: int, chu: str, loai: str,
                **tham_so) -> dict | None:
    """Áp MỘT thao tác sửa nháp + ghi nhật ký — CÙNG một transaction: thao
    tác không ghi được nhật ký thì coi như KHÔNG xảy ra, và ngược lại.

    Trả `None` nếu lượt không phải của `chu`. Trả `{"tu_choi": "khong_hop_le"}`
    khi ĐÍCH của thao tác không tồn tại/không thuộc lượt (mọi trường bắt buộc
    ĐÃ có mặt, nhưng giá trị không trỏ tới gì thật) — không có dòng nhật ký
    nào được ghi: mọi hàm `_op_*` VALIDATE đích trước khi đổi bất cứ gì, nên
    nhánh trượt luôn thoát TRƯỚC câu ghi đầu tiên và transaction đóng lại
    không có gì để commit ngoài chính nó (rỗng). `ValueError` khi loại không
    hợp lệ, khi thiếu HẲN một trường bắt buộc, hoặc khi lượt không đang ở
    trạng thái `de_xuat` — ba ca này là lỗi YÊU CẦU, khác lỗi "đích không tồn
    tại" ở trên.

    Một số `_op_*` (`tach`/`chuyen`/`ngoai_chu_de`/`tra_ve`, xem
    `_kiem_video_ids_thao_tac`) tự trả THẲNG một dict `{"tu_choi": ...}` với
    lý do RIÊNG (vd `"video_da_o_cum_that"` kèm `"video_ids"`) thay vì `None`
    — hàm này chuyển tiếp NGUYÊN VẸN dict đó, không bọc lại thành câu chữ
    chung `"khong_hop_le"`.

    `duyet_kieu`/`duyet_het` không được áp qua đường này — đó là việc của hai
    hàm cùng tên (đi qua `cum` thật), không phải một thao tác sửa nháp.
    """
    if loai not in LOAI_THAO_TAC:
        raise ValueError(f"loại thao tác không hợp lệ: {loai!r}")
    if loai in ("duyet_kieu", "duyet_het"):
        raise ValueError("dùng POST /chia/{id}/duyet để duyệt, không phải /thao-tac")
    _kiem_truong_bat_buoc(loai, tham_so)
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        lan = _lan_cua_toi(conn, chia_lan_id, chu)
        if lan is None:
            return None
        # `hoan_tac` cũng đi qua cổng này: không lùi được một lượt đã
        # `da_duyet`/`huy` — gop rồi duyệt hết rồi hoàn tác không được phép
        # chạy, để lại lượt `da_duyet` với một kiểu nháp sống lại bên trong.
        _kiem_trang_thai_de_xuat(lan)
        ket = _AP_THAO_TAC[loai](conn, chia_lan_id, chu, lan, **tham_so)
        if ket is None:
            return {"tu_choi": "khong_hop_le"}
        if isinstance(ket, dict) and "tu_choi" in ket:
            return ket
        so_video, chi_tiet = ket
        conn.execute(
            "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, "
            "chi_tiet_json, luc, the_he) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chia_lan_id, chu, loai, so_video, json.dumps(chi_tiet, ensure_ascii=False), _now(),
             lan["the_he"]))
    return {"so_video": so_video, "chi_tiet": chi_tiet}


# ---------------------------------------------------------------------------
# Payload `nhan` dựng Ở SERVER cho một lô của một cụm THẬT.
# ---------------------------------------------------------------------------

# Luật item của BÊN NHẬN — meta-ads `frontend/src/lib/videodesk-handoff.ts`
# (`DRIVE_FILE_ID_RE`, `HTTP_URL_RE`; `parseHandoffItems` bỏ CẢ LÔ, không
# ack, khi chỉ một item sai). Cùng luật đường chọn tay áp ở client
# (`app.js::itemHopLeBenNhan`). `fullmatch`/`match` thay cho `^…$` của JS:
# `$` của Python còn khớp trước một ký tự xuống dòng cuối chuỗi.
_DRIVE_FILE_ID_BEN_NHAN = re.compile(r"[A-Za-z0-9_-]{10,128}")
_LINK_GOC_BEN_NHAN = re.compile(r"https?://", re.IGNORECASE)


def _item_hop_le_ben_nhan(drive_file_id, url) -> bool:
    """Bên nhận đòi đúng CHUỖI (không ép kiểu) khớp hai luật trên."""
    return (isinstance(drive_file_id, str) and _DRIVE_FILE_ID_BEN_NHAN.fullmatch(drive_file_id)
            is not None and isinstance(url, str) and _LINK_GOC_BEN_NHAN.match(url) is not None)


def _video_trong_lo(conn, cum: dict, chu: str, chi_cua: str | None, thu: int) -> list[dict]:
    """Video của lô `thu` (TRƯỚC khi lọc Drive).

    Thứ tự cắt lô PHẢI khớp `app.js::videoCuaCum` + `chiaLo` (video CŨ nhất
    trước, cắt block `LO_TOI_DA`, RỒI mới lọc video chưa lên Drive) — xem
    ghi chú đầy đủ ở `xay_payload_lo`.
    """
    rows = conn.execute(
        "SELECT v.video_id, v.title, v.url, v.drive_file_id FROM video_cum vc "
        "JOIN videos v ON v.video_id = vc.video_id "
        "LEFT JOIN jobs j ON j.id = v.job_id "
        "WHERE v.da_loai_luc IS NULL AND (? IS NULL OR j.nguoi_tao = ?) "
        "AND vc.chu = ? AND vc.cum_id = ? "
        "ORDER BY v.tao_luc ASC, v.video_id ASC",
        (chi_cua, chi_cua, chu, cum["id"])).fetchall()
    toan_bo = [dict(r) for r in rows]
    return toan_bo[(thu - 1) * models_cum.LO_TOI_DA: thu * models_cum.LO_TOI_DA]


def xay_payload_lo(db_path: Path, cum: dict, chu: str, chi_cua: str | None,
                   thu: int) -> dict:
    """Dựng `{v, items, nhan}` cho lô `thu` của cụm THẬT `cum` — hợp đồng
    `nhan` (plans/260923-1558-tai-theo-cum/hop-dong-nhan.md), 8 quy tắc.

    `nhan` (thứ mang tên kiểu sang taxonomy Creative Desk) phải dựng Ở
    SERVER, không phải ghép ở CLIENT (`app.js::nhanTuCum`) — ghép ở client
    làm nó phụ thuộc vào một bản JS cũ còn cache trong trình duyệt người
    dùng.

    `cum` là kết quả `models_cum.lay_cum`/`_cum_hoac_404` (đã kiểm quyền sở
    hữu + tính `so_lo`) — hàm này KHÔNG tự truy vấn bảng `cum`, chỉ đọc
    thẳng `video_cum`/`videos`/`jobs`, dùng ĐÚNG khoá lọc sở hữu
    (`da_loai_luc IS NULL` + phạm vi `chi_cua`) mà
    `models_cum._VIDEO_CON_THAY` áp dụng, để số video một lô không bao giờ
    lệch số `liet_ke_cum` đã đếm.

    Thứ tự cắt lô PHẢI khớp `app.js::videoCuaCum` + `chiaLo` (video CŨ nhất
    trước, cắt block `LO_TOI_DA`, RỒI mới lọc video chưa lên Drive) — lọc
    Drive trước khi cắt sẽ làm ranh giới lô trôi so với những gì người dùng
    đã thấy trên UI trước khi bấm.

    Item nào sai luật bên nhận (`_item_hop_le_ben_nhan`: chưa lên Drive, Drive
    id sai hình dạng, link gốc không phải http(s)) bị BỎ khỏi lô — một item
    sai làm bên nhận bỏ cả lô.
    """
    with _connect(db_path) as conn:
        lo = _video_trong_lo(conn, cum, chu, chi_cua, thu)
    items = [{"f": v["drive_file_id"], "n": v["title"] or v["video_id"], "u": v["url"]}
             for v in lo if _item_hop_le_ben_nhan(v["drive_file_id"], v["url"])]
    nhan = {"usecase": cum["usecase"], "insight": cum["insight"], "template": "Goc",
            "cum_id": cum["id"], "lo": {"thu": thu, "tong": cum["so_lo"]}}
    # `so_video` = số video của lô TRƯỚC khi lọc, đếm cùng lượt với `items` —
    # mẫu số của nhãn "x/N" phải cùng thời điểm với tử số. KHÔNG thuộc hợp
    # đồng gửi Creative Desk: `app.js::moLoCum` tách nó ra trước khi mã hoá URL.
    return {"v": 1, "items": items, "nhan": nhan, "so_video": len(lo)}
