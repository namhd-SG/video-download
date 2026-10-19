"""Canh relay agy: báo Discord khi có video chờ máy định vị logo quá lâu mà CHƯA có kết quả (chốt L2 agy R2b).

Điều kiện theo TUỔI VIỆC, không theo "relay có hỏi /viec không": relay vẫn sống, vẫn hỏi /viec mỗi 20 s mà agy lỗi/hết quota (relay dự
phòng không nộp lỗi) thì vế "không relay nào hỏi" luôn sai ⇒ canh câm suốt 3 giờ tới khi worker chốt `loi`. Video đã có `ket_qua.json`
mà còn `cho_agy` là đang xếp hàng render — KHÔNG tính (agy R1b PB3).

Thứ tự ghi mốc (luật `guard-marker-and-claim-write-ordering.md`): mốc "đã báo" chỉ ghi SAU khi gửi được; gửi trượt ⇒ không ghi, vòng sau
báo lại. "Chưa cấu hình webhook" (`gui` trả None) KHÁC "gửi trượt" (False): chưa cấu hình ⇒ không ghi mốc, chỉ log MỘT lần mỗi tiến trình
(không ồn vô hạn ở máy chưa đặt webhook). Mốc báo động bắn lại sau `NHAC_LAI_GIAY` nếu video vẫn kẹt — không tự tắt sau lần báo đầu.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Callable

log = logging.getLogger(__name__)

ENV_WEBHOOK = "THAY_LOGO_DISCORD_WEBHOOK"
CHO_TOI_DA_GIAY = 15 * 60  # M = 15 phút (plan P6: N = 5 phút × 3 — một nhịp lỡ không báo)
NHAC_LAI_GIAY = 60 * 60   # vẫn kẹt sau 1 giờ ⇒ báo lại
# Cloudflare trước Discord CHẶN User-Agent mặc định `Python-urllib` (403, "error code: 1010" — review PR3 đo 16/10). Discord yêu cầu khuôn
# "DiscordBot (url, version)".
USER_AGENT = "DiscordBot (https://video.nobidigital.asia, 1.0) VideoDesk-thay-logo"
LUI_DAU_GIAY, LUI_TOI_DA_GIAY = 60.0, 600.0  # gửi trượt ⇒ giãn cách 60 s → gấp đôi → tối đa 10 phút (không dội Discord mỗi vòng 10 s)

SCHEMA = "CREATE TABLE IF NOT EXISTS tl_canh_relay (video_id INTEGER PRIMARY KEY, luc REAL NOT NULL);"


def khoi_tao(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def video_ket(conn, hop, bay_gio: float, cho_toi_da: float = CHO_TOI_DA_GIAY) -> list[tuple[int, float, bool]]:
    """[(video_id, giây đã chờ, đến hạn báo)] — mọi video `cho_agy`, hộp thư CHƯA có kết quả, chờ ≥ `cho_toi_da`. `đến hạn báo` = chưa
    báo trong `NHAC_LAI_GIAY` gần đây. Tin báo đếm TẤT CẢ video kẹt (không chỉ video mới), chỉ gửi khi có ít nhất một video đến hạn."""
    khoi_tao(conn)
    da_bao = {r[0]: r[1] for r in conn.execute("SELECT video_id, luc FROM tl_canh_relay")}
    out = []
    for r in conn.execute("SELECT id, cho_agy_tu FROM tl_job_video WHERE trang_thai = 'cho_agy' AND cho_agy_tu IS NOT NULL"):
        tuoi = bay_gio - float(r[1])
        if tuoi < cho_toi_da:
            continue
        try:
            if hop.doc_ket_qua(r[0]) is not None:
                continue
        except Exception:  # hộp thư hỏng một việc: không đoán là "kẹt"
            continue
        out.append((r[0], tuoi, bay_gio - da_bao.get(r[0], -1e18) >= NHAC_LAI_GIAY))
    return out


IM_SAU_GIAY = 120  # relay hỏi mỗi 20 s; quá 2 phút không hỏi ⇒ coi là IM (USER CHỐT 19/10)
SO_VIDEO_LIET_KE = 3  # liệt 3 video lâu nhất, còn lại ghi "+N" — tin luôn ngắn, xa trần 2000 ký tự của Discord
TRAN_DISCORD = 2000
TRANG_THAY_LOGO = "https://video.nobidigital.asia/thay-logo.html"  # domain thật của Video Desk (sau Cloudflare Access)


def _thoi_gian(giay: float) -> str:
    """25″ · 18′ · 1 giờ 5′ — dưới 1 phút ghi GIÂY (tin cũ làm tròn 30 s thành "0 phút trước")."""
    g = max(0, int(giay))
    if g < 60:
        return f"{g}″"
    if g < 3600:
        return f"{g // 60}′"
    return f"{g // 3600} giờ {g % 3600 // 60}′"


def _relay(ten: str, tuoi: float | None) -> str:
    if tuoi is None:
        return f"{ten} chưa hỏi từ lúc mini chạy"
    return f"{ten} im {_thoi_gian(tuoi)}" if tuoi >= IM_SAU_GIAY else f"{ten} hỏi {_thoi_gian(tuoi)} trước"


def ket_luan(tuoi_relay: dict) -> tuple[str, str, str]:
    """(biểu tượng, kết luận, làm gì) — MỘT kết luận theo tuổi lần hỏi việc gần nhất của 2 relay (chưa từng hỏi = im)."""
    def im(k):
        t = tuoi_relay.get(k)
        return t is None or t >= IM_SAU_GIAY
    if not im("chinh"):
        return "🟠", "relay vẫn hỏi, nghi agy lỗi/hết quota", "xem log relay chính, kiểm quota agy"
    if not im("du_phong"):
        return "🟠", "dự phòng đang thay mà vẫn kẹt, nghi agy ca-n", "bật relay chính, kiểm agy ca-n"
    return "🔴", "không máy nào đang định vị", "kiểm máy dev + ca-n"


def _ten_luot(ten: str | None, job_id: int) -> str:
    """Tên lượt do người dùng đặt: bỏ ký tự định dạng markdown + xuống dòng, cắt 40 ký tự (mention đã tắt ở payload)."""
    t = " ".join((ten or "").translate({ord(c): " " for c in "*_~`|>\\\n\r"}).split())
    if not t:
        return f"lượt #{job_id}"
    return t if len(t) <= 40 else t[:39] + "…"


def thong_tin_luot(conn, video_ids) -> dict[int, tuple[int, str | None]]:
    """{video_id: (job_id, ten_bo)} cho các video kẹt — để tin ghi «tên lượt» #mã video và link mở thẳng lượt."""
    ids = list(video_ids)
    if not ids:
        return {}
    dau = ",".join("?" * len(ids))
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        f"SELECT v.id, v.job_id, j.ten_bo FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id WHERE v.id IN ({dau})", ids)}


def noi_dung(ket: list[tuple[int, float, bool]], tuoi_relay: dict, luot: dict | None = None) -> str:
    """Tin 3 dòng (USER CHỐT 19/10 phương án C): kết luận · trạng thái relay + video kẹt · làm gì + link mở thẳng lượt lâu nhất."""
    luot = luot or {}
    xep = sorted(ket, key=lambda k: -k[1])
    lau = xep[0][1]
    bt, kl, lam = ket_luan(tuoi_relay)
    dau = f"1 video kẹt {_thoi_gian(lau)}" if len(xep) == 1 else f"{len(xep)} video kẹt (lâu nhất {_thoi_gian(lau)})"
    nhom: dict[int, list[str]] = {}
    ten: dict[int, str] = {}
    for vid, _, _ in xep[:SO_VIDEO_LIET_KE]:
        jid, tb = luot.get(vid, (0, None))
        ten.setdefault(jid, _ten_luot(tb, jid) if jid else "")
        nhom.setdefault(jid, []).append(f"#{vid}")
    ds = " · ".join((f"«{ten[j]}» " if ten[j] else "") + ", ".join(v) for j, v in nhom.items())
    if len(xep) > SO_VIDEO_LIET_KE:
        ds += f" · +{len(xep) - SO_VIDEO_LIET_KE}"
    jid_lau = luot.get(xep[0][0], (0, None))[0]
    link = f"{TRANG_THAY_LOGO}?luot={jid_lau}" if jid_lau else TRANG_THAY_LOGO
    chu = (f"{bt} **Thay logo: {dau} — {kl}**\n"
           f"{_relay('Chính', tuoi_relay.get('chinh'))} · {_relay('Dự phòng', tuoi_relay.get('du_phong'))} · {ds}\n"
           f"👉 {lam} · {link}")
    return chu[:TRAN_DISCORD]


def gui_webhook(chu: str, url: str | None = None) -> bool | None:
    """None = chưa cấu hình webhook; True = gửi được; False = đã cấu hình mà trượt (mạng / Discord từ chối)."""
    url = url if url is not None else os.environ.get(ENV_WEBHOOK, "")
    if not url:
        return None
    req = urllib.request.Request(url, data=json.dumps({"content": chu, "allowed_mentions": {"parse": []}}).encode(),  # tên lượt có "@everyone" không ping cả kênh
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:  # mã HTTP giúp phân định (403 = bị chặn trước Discord, 404 = webhook sai, 429 = bị giới hạn)
        log.warning("canh relay: gửi Discord trượt (HTTP %s)", e.code)
        return False
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("canh relay: gửi Discord trượt (%s)", type(e).__name__)
        return False


_da_bao_chua_cau_hinh = False
_lui = {"den": 0.0, "giay": LUI_DAU_GIAY}  # giãn cách sau lần gửi trượt (bộ nhớ tiến trình; KHÔNG ghi mốc báo khi trượt)


def thu_canh(conn, hop, tuoi_relay: dict, gui: Callable[[str], bool | None] = gui_webhook, bay_gio: float | None = None) -> bool | None:
    """Một lượt canh. Trả kết quả gửi (None = không có gì để báo HOẶC chưa cấu hình). Không ném."""
    global _da_bao_chua_cau_hinh
    try:
        luc = time.time() if bay_gio is None else bay_gio
        ket = video_ket(conn, hop, luc)
        if not any(den_han for _, _, den_han in ket):
            return None
        if luc < _lui["den"]:  # đang giãn cách sau lần trượt trước
            return None
        kq = gui(noi_dung(ket, tuoi_relay, thong_tin_luot(conn, [v for v, _, _ in ket])))
        if kq is None:
            if not _da_bao_chua_cau_hinh:
                log.warning("canh relay: %d video kẹt chờ định vị nhưng CHƯA cấu hình %s — không báo được", len(ket), ENV_WEBHOOK)
                _da_bao_chua_cau_hinh = True
            return None
        if kq:  # mốc SAU khi gửi được; trượt ⇒ không ghi ⇒ báo lại sau giãn cách
            conn.executemany("INSERT OR REPLACE INTO tl_canh_relay (video_id, luc) VALUES (?,?)", [(v, luc) for v, _, _ in ket])
            conn.commit()
            _lui.update(den=0.0, giay=LUI_DAU_GIAY)
        else:
            _lui["den"] = luc + _lui["giay"]
            _lui["giay"] = min(LUI_TOI_DA_GIAY, _lui["giay"] * 2)
        return kq
    except Exception:
        log.exception("canh relay: lượt canh lỗi")
        return False
