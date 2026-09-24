"""Tự chia cụm theo lượt — nháp (`chia_lan`/`cum_nhap`/`video_cum_nhap`),
nhật ký sửa (`thao_tac_duyet`) và đường DUY NHẤT biến nháp thành cụm THẬT.
Bảng sống trong `web/models.py` (`init_db`); đây là câu hỏi/ghi trên chúng.

Luật quyền sở hữu giống `models_cum`: mọi hàm nhận `chu` KHÔNG có mặc định và
lọc theo nó NGAY TRONG SQL. `chu` luôn là email người gọi.

KHÔNG ĐỤNG `web/models_cum.py` (địa phận phase khác). `duyet_kieu`/`duyet_het`
CẦN hành vi tương đương `models_cum.tao_cum` (trùng tên ⇒ cụm có sẵn) +
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
from pathlib import Path

from web import models_cum
from web.models import _connect, _now

# Tập ĐÓNG cho `chia_lan.trang_thai`, `video_cum_nhap.lan` và
# `thao_tac_duyet.loai`. Kiểm ở Python, không CHECK constraint — lý do ở
# đầu tệp `web/models.py::_THAO_TAC_DUYET_SCHEMA`.
TRANG_THAI_CHIA_LAN = ("cho_hinh", "de_xuat", "da_duyet", "huy")
LAN_VIDEO = ("kieu", "huong_dan", "nghi")
LOAI_THAO_TAC = ("chap_nhan", "duyet_het", "gop", "doi_ten", "chuyen",
                 "ngoai_chu_de", "tra_ve", "hoan_tac", "xoa_kieu", "doi_insight")

# Loại có thể LÙI LẠI bằng `hoan_tac` — `chap_nhan` không đổi gì để lùi,
# `doi_insight` đổi nhãn (không đổi cấu trúc video) nên không nằm trong luồng
# hoàn tác cấu trúc của phase này, và `hoan_tac`/`duyet_het` không tự lùi
# chính nó (duyệt đã đi qua `cum` thật — ngoài phạm vi "hoàn tác nháp").
_HOAN_TAC_DUOC = ("gop", "doi_ten", "chuyen", "ngoai_chu_de", "tra_ve", "xoa_kieu")


def _lan_cua_toi(conn, chia_lan_id: int, chu: str):
    return conn.execute(
        "SELECT * FROM chia_lan WHERE id = ? AND chu = ?", (chia_lan_id, chu)).fetchone()


# ---------------------------------------------------------------------------
# Tạo lượt + ghi đề xuất (tầng hình gọi sau khi phân tích xong — phase 2)
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
        job = conn.execute("SELECT usecase, insight_goc, nguoi_tao FROM jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if job is None or job["nguoi_tao"] != chu:
            return None
        usecase = job["usecase"]
        insight_goc = job["insight_goc"]
        cur = conn.execute(
            "INSERT INTO chia_lan (job_id, chu, trang_thai, truc, usecase, insight_goc, "
            "phien_ban_prompt, tao_luc) VALUES (?, ?, 'cho_hinh', ?, ?, ?, ?, ?)",
            (job_id, chu, truc, usecase, insight_goc, phien_ban_prompt, _now()))
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
                cur = conn.execute(
                    "INSERT INTO cum_nhap (chia_lan_id, nhom, kieu, thu_tu) VALUES (?, ?, ?, ?)",
                    (chia_lan_id, nhom["nhom"], kieu["kieu"], thu_tu))
                thu_tu += 1
                if ids:
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
        # xoá bởi hai câu DELETE phía trên; hồi sinh nó là hồi sinh rác).
        conn.execute(
            "UPDATE chia_lan SET trang_thai = 'de_xuat', the_he = the_he + 1 WHERE id = ?",
            (chia_lan_id,))
        # Chốt tên hiển thị của MỌI kiểu vừa ghi — xem `_cap_nhat_ten_cum`.
        _cap_nhat_ten_cum(conn, chia_lan_id)
    return {"da_o_cum": sorted(da_o_cum)}


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
                "SELECT id, nhom, kieu, thu_tu FROM cum_nhap WHERE chia_lan_id = ? "
                "ORDER BY thu_tu, id", (chia_lan_id,)).fetchall():
            nhoms[r["id"]] = {"cum_nhap_id": r["id"], "nhom": r["nhom"], "kieu": r["kieu"],
                              "thu_tu": r["thu_tu"], "video_ids": []}
        huong_dan: list[str] = []
        nghi: list[str] = []
        bi_bo: list[str] = []
        # Cần phân biệt HAI ca cùng để lại một hàng "mồ côi" (`lan='kieu'`,
        # `cum_nhap_id=NULL` sau khi FK `ON DELETE SET NULL` chạy lúc kiểu
        # chứa nó được DUYỆT): video đã có NHÀ THẬT (`video_cum` — chính nó
        # vừa được duyệt, hoặc đã ở đó từ một nháp song song khác, `da_o_cum`)
        # thì im lặng bỏ qua (đã báo ở nơi khác, đúng lúc nó xảy ra); video
        # KHÔNG có nhà nào (id giả, hoặc bị loại/đổi chủ sau khi đề xuất) mới
        # là `bi_bo` thật — trước đây CẢ HAI ca lẫn lộn, rơi mất khỏi kết quả.
        video_cum_cua_chu = {r["video_id"] for r in conn.execute(
            "SELECT video_id FROM video_cum WHERE chu = ?", (lan["chu"],)).fetchall()}
        for r in conn.execute(
                "SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap "
                "WHERE chia_lan_id = ? ORDER BY video_id", (chia_lan_id,)).fetchall():
            if r["lan"] == "kieu" and r["cum_nhap_id"] in nhoms:
                nhoms[r["cum_nhap_id"]]["video_ids"].append(r["video_id"])
            elif r["lan"] == "huong_dan":
                huong_dan.append(r["video_id"])
            elif r["lan"] == "nghi":
                nghi.append(r["video_id"])
            elif r["video_id"] not in video_cum_cua_chu:
                bi_bo.append(r["video_id"])
    return {**dict(lan), "kieu": list(nhoms.values()), "huong_dan": huong_dan, "nghi": nghi,
            "bi_bo": bi_bo}


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


def _kieu_trung_ten(conn, chia_lan_id: int) -> set[int]:
    """`cum_nhap_id` mà `kieu` (chuẩn hoá + casefold, khoá `models_cum._khoa_ten`)
    TRÙNG với ít nhất một `cum_nhap` KHÁC còn sống trong CÙNG lượt.

    Dùng để đặt tên cụm: tên cụm mặc định là `"<insight gốc> <kiểu>"`; CHỈ
    khi ≥2 kiểu trong cùng lượt trùng tên chuẩn hoá thì các kiểu đó (và chỉ
    chúng) mới ghép thêm `nhom` — `"<insight gốc> <nhom> <kiểu>"` — để không
    sinh ra một lời mời "gộp" trỏ vào một cụm mà chính `duyet_het` vừa tạo
    trong CÙNG lượt gọi (câu hỏi "gộp vào cụm có sẵn" lẽ ra chỉ để bắt trùng
    với cụm cũ THẬT, không phải bắt trùng giữa hai kiểu anh em).

    CHỈ gọi từ `_cap_nhat_ten_cum` — xem đó để biết vì sao quyết định này
    không còn được tính lại ngay lúc duyệt.
    """
    dem: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, kieu FROM cum_nhap WHERE chia_lan_id = ?",
                          (chia_lan_id,)).fetchall():
        khoa = models_cum.chuan_hoa_chu(r["kieu"]).casefold()
        dem.setdefault(khoa, []).append(r["id"])
    return {cid for ids in dem.values() if len(ids) > 1 for cid in ids}


def _cap_nhat_ten_cum(conn, chia_lan_id: int) -> None:
    """Tính lại VÀ LƯU `ten_cum` (tên hiển thị dùng lúc duyệt — kèm luật
    chèn nhóm khi trùng, `_kieu_trung_ten`) cho MỌI kiểu còn sống của lượt.

    Gọi ngay sau bất kỳ thao tác nào đổi TẬP `(nhom, kieu)` của lượt
    (`ghi_de_xuat`, `doi_ten`, `gop`, `xoa_kieu`, và hoàn tác ba thao tác đó)
    — CHỐT một lần tại điểm ghi, thay vì để `duyet_kieu`/`duyet_het` tự tính
    lại. Trước đây tính lại NGAY LÚC DUYỆT làm tên trôi theo THỨ TỰ duyệt:
    duyệt từng kiểu một qua nhiều lần gọi riêng lẻ xoá dần các hàng
    `cum_nhap`, nên tập "đang trùng" nhìn từ một lần gọi SAU luôn hẹp hơn lần
    gọi TRƯỚC — cùng một kiểu ra hai tên khác nhau tuỳ nó được duyệt trước
    hay sau (ca đo được: duyệt một cặp trùng tên từng-cái-một qua `duyet_kieu`
    cho ra "Vest couple" rồi "couple" trần, thay vì "Vest couple"/"Đồng phục
    couple" ổn định như `duyet_het` xử cả cặp trong MỘT lần gọi).
    """
    trung = _kieu_trung_ten(conn, chia_lan_id)
    for r in conn.execute("SELECT id, nhom, kieu FROM cum_nhap WHERE chia_lan_id = ?",
                          (chia_lan_id,)).fetchall():
        ten = (models_cum.chuan_hoa_chu(f"{r['nhom']} {r['kieu']}") if r["id"] in trung
               else models_cum.chuan_hoa_chu(r["kieu"]))
        conn.execute("UPDATE cum_nhap SET ten_cum = ? WHERE id = ?", (ten, r["id"]))


def _giai_quyet_kieu(conn, chia_lan_id: int, cum_nhap_id: int, chu: str,
                     chi_cua: str | None, usecase: str, insight_goc: str,
                     xac_nhan: set[int], da_tao_trong_luot: dict[tuple[str, str], int]) -> dict:
    """Lõi "duyệt một kiểu", dùng chung bởi `duyet_kieu` (một nhóm) và
    `duyet_het` (vòng lặp mọi nhóm còn lại) TRÊN CÙNG một kết nối/transaction.

    Tên hiển thị dùng ở đây là `cum_nhap.ten_cum` — đã CHỐT một lần lúc ghi
    (`_cap_nhat_ten_cum`), KHÔNG tính lại ở đây (xem lý do tại đó).

    `da_tao_trong_luot`: `{(usecase.casefold, insight_con.casefold): cum_id}`
    của MỌI cụm đã tạo/dùng TRONG CHÍNH lượt gọi `duyet_het` này (rỗng cho
    `duyet_kieu`, vốn chỉ giải quyết một kiểu). Cần vì tên đã CHỐT của hai
    kiểu khác nhau đôi khi khác NHAU Ở MẶT CHỮ nhưng trùng nhau ở casefold —
    ví dụ hai biến thể hoa/thường của cùng một kiểu trong cùng nhóm ghép ra
    "Vest couple"/"Vest Couple" (chữ kiểu giữ NGUYÊN cách viết gốc của từng
    hàng), hoặc tên ghép nhóm+kiểu của một hàng trùng NGUYÊN VĂN kiểu đơn của
    một hàng khác. Không có bước tra map này, hàng xử lý SAU sẽ thấy cụm hàng
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
    # `_cap_nhat_ten_cum` (cột thêm sau, mặc định NULL) — trên đường thi công
    # bình thường mọi hàng cum_nhap đều có `ten_cum` vì mọi điểm ghi đều gọi
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
              xac_nhan_gop: list[int] | None = None) -> dict | None:
    """Duyệt MỘT kiểu nháp thành cụm thật (hoặc gộp vào cụm có sẵn) — lối DUY
    NHẤT từ nháp sang `cum`. `None` ⇒ lượt không phải của `chu`.

    `usecase`/`insight_goc` bỏ trống ⇒ dùng giá trị đã lưu ở `chia_lan`.
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
        ket = _giai_quyet_kieu(conn, chia_lan_id, cum_nhap_id, chu, chi_cua, u, g, xac_nhan, {})
        if ket.get("loi"):
            return None
        if "trung" in ket:
            return {"trung_cum_co_san": [ket["trung"]]}
        luc = _now()
        conn.execute(
            "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, "
            "chi_tiet_json, luc, the_he) VALUES (?, ?, 'duyet_het', ?, ?, ?, ?)",
            (chia_lan_id, chu, len(ket["gan"]), json.dumps(ket, ensure_ascii=False), luc,
             lan["the_he"]))
        # Duyệt được BẤT CỨ GÌ là một điểm CHỐT: bump `the_he` ngay ở đây làm
        # MỌI thao tác sửa nháp trước đó (dù chưa từng bị hoàn tác) mang
        # `the_he` CŨ, nên bộ lọc `AND the_he = ?` của `_op_hoan_tac` loại hết
        # chúng — hoàn tác không còn cách nào lùi XUYÊN QUA một lần duyệt.
        # Trước bản vá này, `chuyen`/`gop` một video/kiểu RỒI DUYỆT đúng chỗ
        # đó RỒI `hoan_tac` cố phục hồi một `cum_nhap.id` đã bị xoá thật khi
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
    trùng — xem `_kieu_trung_ten`) không hợp lệ (`kiem_nhan` raise) bị báo lại
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
    # Đổi tên đổi CHÍNH tập (nhom, kieu) mà tên hiển thị lúc duyệt dựa vào —
    # chốt lại ngay, đừng để `ten_cum` cũ (của cái tên vừa bị thay) trôi tới
    # lúc duyệt.
    _cap_nhat_ten_cum(conn, chia_lan_id)
    n = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
                     "AND cum_nhap_id = ?", (chia_lan_id, cum_nhap_id)).fetchone()[0]
    return n, {"cum_nhap_id": cum_nhap_id, "truoc": {"nhom": row["nhom"], "kieu": row["kieu"]},
              "sau": {"nhom": nhom_moi, "kieu": kieu_moi}}


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
    # Xoá nguồn có thể làm MẤT một va chạm tên (nguồn là "anh em" trùng tên
    # duy nhất của một kiểu khác) — chốt lại tên hiển thị cho các kiểu còn
    # sống.
    _cap_nhat_ten_cum(conn, chia_lan_id)
    return len(video_ids), {"tu_cum_nhap_id": tu_cum_nhap_id, "den_cum_nhap_id": den_cum_nhap_id,
                            "video_ids": video_ids, "tu_nhom": tu["nhom"], "tu_kieu": tu["kieu"],
                            "tu_thu_tu": tu["thu_tu"]}


def _hang_video_cum_nhap(conn, chia_lan_id, video_ids):
    if not video_ids:
        return []
    marks = ",".join("?" * len(video_ids))
    return [dict(r) for r in conn.execute(
        f"SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap "
        f"WHERE chia_lan_id = ? AND video_id IN ({marks})",
        [chia_lan_id, *video_ids]).fetchall()]


def _op_chuyen(conn, chia_lan_id, chu, lan, video_ids: list[str] | None,
              den_cum_nhap_id: int, **_):
    """Chuyển các video (đang ở BẤT KỲ làn nào trong lượt) sang kiểu
    `den_cum_nhap_id`."""
    if not video_ids:
        return None
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (den_cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    truoc = _hang_video_cum_nhap(conn, chia_lan_id, video_ids)
    if not truoc:
        return None
    conn.executemany(
        "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
        "WHERE chia_lan_id = ? AND video_id = ?",
        [(den_cum_nhap_id, chia_lan_id, r["video_id"]) for r in truoc])
    return len(truoc), {"video_ids": [r["video_id"] for r in truoc],
                        "den_cum_nhap_id": den_cum_nhap_id, "truoc": truoc}


def _op_ngoai_chu_de(conn, chia_lan_id, chu, lan, video_ids: list[str] | None, **_):
    """Đưa các video sang làn "nghi ngoài chủ đề" — bỏ khỏi mọi kiểu."""
    if not video_ids:
        return None
    truoc = _hang_video_cum_nhap(conn, chia_lan_id, video_ids)
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
    chỗ chỉ nhận video KHÔNG đang ở một kiểu nào (đó là việc của `chuyen`)."""
    if not video_ids:
        return None
    if conn.execute("SELECT 1 FROM cum_nhap WHERE id = ? AND chia_lan_id = ?",
                    (den_cum_nhap_id, chia_lan_id)).fetchone() is None:
        return None
    marks = ",".join("?" * len(video_ids))
    truoc = [dict(r) for r in conn.execute(
        f"SELECT video_id, cum_nhap_id, lan FROM video_cum_nhap WHERE chia_lan_id = ? "
        f"AND video_id IN ({marks}) AND lan != 'kieu'",
        [chia_lan_id, *video_ids]).fetchall()]
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
    # Cùng lý do ở `_op_gop`: xoá một kiểu có thể gỡ va chạm tên của một kiểu
    # khác.
    _cap_nhat_ten_cum(conn, chia_lan_id)
    return len(video_ids), {"cum_nhap_id": cum_nhap_id, "nhom": row["nhom"], "kieu": row["kieu"],
                            "thu_tu": row["thu_tu"], "video_ids": video_ids}


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


def _op_hoan_tac(conn, chia_lan_id, chu, lan, **_):
    """Hoàn tác thao tác sửa CẤU TRÚC gần nhất CHƯA bị lùi của lượt này
    (`_HOAN_TAC_DUOC`). `chap_nhan` không đổi gì để lùi; `duyet_het`/
    `hoan_tac`/`doi_insight` nằm ngoài phạm vi hoàn tác nháp của phase này.

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
    if loai == "gop":
        conn.execute(
            "INSERT INTO cum_nhap (id, chia_lan_id, nhom, kieu, thu_tu) VALUES (?, ?, ?, ?, ?)",
            (chi_tiet["tu_cum_nhap_id"], chia_lan_id, chi_tiet["tu_nhom"], chi_tiet["tu_kieu"],
             chi_tiet["tu_thu_tu"]))
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ? WHERE chia_lan_id = ? AND video_id = ?",
            [(chi_tiet["tu_cum_nhap_id"], chia_lan_id, vid) for vid in chi_tiet["video_ids"]])
        so = len(chi_tiet["video_ids"])
    elif loai == "doi_ten":
        conn.execute("UPDATE cum_nhap SET nhom = ?, kieu = ? WHERE id = ?",
                    (chi_tiet["truoc"]["nhom"], chi_tiet["truoc"]["kieu"],
                     chi_tiet["cum_nhap_id"]))
        so = conn.execute("SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? "
                          "AND cum_nhap_id = ?",
                          (chia_lan_id, chi_tiet["cum_nhap_id"])).fetchone()[0]
    elif loai == "xoa_kieu":
        conn.execute(
            "INSERT INTO cum_nhap (id, chia_lan_id, nhom, kieu, thu_tu) VALUES (?, ?, ?, ?, ?)",
            (chi_tiet["cum_nhap_id"], chia_lan_id, chi_tiet["nhom"], chi_tiet["kieu"],
             chi_tiet["thu_tu"]))
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = 'kieu' "
            "WHERE chia_lan_id = ? AND video_id = ?",
            [(chi_tiet["cum_nhap_id"], chia_lan_id, vid) for vid in chi_tiet["video_ids"]])
        so = len(chi_tiet["video_ids"])
    else:   # chuyen · ngoai_chu_de · tra_ve — đều lưu `truoc: [{video_id,cum_nhap_id,lan}]`
        conn.executemany(
            "UPDATE video_cum_nhap SET cum_nhap_id = ?, lan = ? "
            "WHERE chia_lan_id = ? AND video_id = ?",
            [(r["cum_nhap_id"], r["lan"], chia_lan_id, r["video_id"])
             for r in chi_tiet["truoc"]])
        so = len(chi_tiet["truoc"])
    if loai in ("gop", "doi_ten", "xoa_kieu"):
        # Chỉ ba loại này đổi TẬP (nhom, kieu) của lượt — `chuyen`/
        # `ngoai_chu_de`/`tra_ve` chỉ di chuyển VIDEO giữa các kiểu đã có sẵn,
        # không đụng danh tính kiểu nào, nên không cần chốt lại tên.
        _cap_nhat_ten_cum(conn, chia_lan_id)
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
}

# Trường BẮT BUỘC cho từng `loai` (hop-dong-thao-tac.md). Thiếu HẲN một
# trường ở đây (route lọc `None` ra khỏi payload trước khi tới đây, nên
# "thiếu" và "gửi None" là một) khiến hàm `_op_*` tương ứng thiếu tham số vị
# trí bắt buộc ⇒ `TypeError` ⇒ 500 nếu không được chặn sớm. Kiểm ở đây, TRƯỚC
# KHI mở transaction, biến nó thành `ValueError` (400) rõ ràng.
# `video_ids` còn bị đòi khác-rỗng (hợp đồng: "≥1") vì hàm `_op_*` coi rỗng và
# thiếu là một (`if not video_ids: return None` ⇒ 409 "đích không hợp lệ"),
# nhưng ở TẦNG THAM SỐ thì rỗng và thiếu nên cùng là 400 "thiếu trường".
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
}


def _kiem_truong_bat_buoc(loai: str, tham_so: dict) -> None:
    for ten in _TRUONG_BAT_BUOC.get(loai, ()):
        gia_tri = tham_so.get(ten)
        if gia_tri is None or (ten == "video_ids" and not gia_tri):
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

    `duyet_het` không được áp qua đường này — đó là việc của `duyet_kieu`/
    `duyet_het` (đi qua `cum` thật), không phải một thao tác sửa nháp.
    """
    if loai not in LOAI_THAO_TAC:
        raise ValueError(f"loại thao tác không hợp lệ: {loai!r}")
    if loai == "duyet_het":
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

def xay_payload_lo(db_path: Path, cum: dict, chu: str, chi_cua: str | None,
                   thu: int) -> dict:
    """Dựng `{v, items, nhan}` cho lô `thu` của cụm THẬT `cum` — hợp đồng
    `nhan` (plans/260923-1558-tai-theo-cum/hop-dong-nhan.md), 8 quy tắc.

    Trước bản vá này, `app.js::nhanTuCum` tự ghép nhãn này ở CLIENT; giờ dựng
    lại Ở SERVER để `nhan` (thứ mang tên kiểu sang taxonomy Creative Desk)
    không bao giờ phụ thuộc vào một bản JS cũ còn cache trong trình duyệt
    người dùng.

    `cum` là kết quả `models_cum.lay_cum`/`_cum_hoac_404` (đã kiểm quyền sở
    hữu + tính `so_lo`) — hàm này KHÔNG tự truy vấn bảng `cum` (không sửa
    được `models_cum.py` ở phase này), chỉ đọc thẳng `video_cum`/`videos`/
    `jobs`, dùng ĐÚNG khoá lọc sở hữu (`da_loai_luc IS NULL` + phạm vi
    `chi_cua`) mà `models_cum._VIDEO_CON_THAY` áp dụng, để số video một lô
    không bao giờ lệch số `liet_ke_cum` đã đếm.

    Thứ tự cắt lô PHẢI khớp `app.js::videoCuaCum` + `chiaLo` (video CŨ nhất
    trước, cắt block `LO_TOI_DA`, RỒI mới lọc video chưa lên Drive) — lọc
    Drive trước khi cắt sẽ làm ranh giới lô trôi so với những gì người dùng
    đã thấy trên UI trước khi bấm.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT v.video_id, v.title, v.url, v.drive_file_id FROM video_cum vc "
            "JOIN videos v ON v.video_id = vc.video_id "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            "WHERE v.da_loai_luc IS NULL AND (? IS NULL OR j.nguoi_tao = ?) "
            "AND vc.chu = ? AND vc.cum_id = ? "
            "ORDER BY v.tao_luc ASC, v.video_id ASC",
            (chi_cua, chi_cua, chu, cum["id"])).fetchall()
    toan_bo = [dict(r) for r in rows]
    lo = toan_bo[(thu - 1) * models_cum.LO_TOI_DA: thu * models_cum.LO_TOI_DA]
    items = [{"f": v["drive_file_id"], "n": v["title"] or v["video_id"], "u": v["url"]}
             for v in lo if v["drive_file_id"]]
    nhan = {"usecase": cum["usecase"], "insight": cum["insight"], "template": "Goc",
            "cum_id": cum["id"], "lo": {"thu": thu, "tong": cum["so_lo"]}}
    return {"v": 1, "items": items, "nhan": nhan}
