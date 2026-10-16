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


def noi_dung(ket: list[tuple[int, float, bool]], tuoi_relay: dict) -> str:
    def moc(g):
        return "chưa hỏi từ lúc mini chạy" if g is None else f"{round(g / 60)} phút trước"
    lau = max(t for _, t, _ in ket)
    return (f"⚠ Video Desk · Thay logo: {len(ket)} video chờ máy định vị logo ≥ {CHO_TOI_DA_GIAY // 60} phút mà chưa có kết quả "
            f"(lâu nhất {round(lau / 60)} phút). Relay chính hỏi việc {moc(tuoi_relay.get('chinh'))}; relay dự phòng "
            f"{moc(tuoi_relay.get('du_phong'))}. Relay im ⇒ kiểm máy dev / ca-n; relay vẫn hỏi ⇒ nghi agy lỗi hoặc hết quota.")


def gui_webhook(chu: str, url: str | None = None) -> bool | None:
    """None = chưa cấu hình webhook; True = gửi được; False = đã cấu hình mà trượt (mạng / Discord từ chối)."""
    url = url if url is not None else os.environ.get(ENV_WEBHOOK, "")
    if not url:
        return None
    req = urllib.request.Request(url, data=json.dumps({"content": chu}).encode(),
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
        kq = gui(noi_dung(ket, tuoi_relay))
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
