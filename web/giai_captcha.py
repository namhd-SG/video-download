"""Giải captcha TikTok NGAY TRONG popup Video Desk — phần dùng chung (hằng số, logic thuần,
phiên RAM) và HỢP ĐỒNG API. Sau cờ `VIDEODL_PROFILE_CAPTCHA` (mặc định TẮT).

Người (chủ job hoặc admin) nhìn khung ảnh trang TikTok đang mở trên máy chủ rồi thao tác chuột
trong popup; máy chủ chuyển ĐÚNG thao tác đó qua CDP vào trang. Tool KHÔNG tự giải, không sinh
sự kiện chuột nào người không tạo ra, không làm mượt / nội suy / làm tròn toạ độ (ĐP-529/602/606).

Máy trạng thái của job profile (cột `jobs.trang_thai`):

    running ──(feed rỗng | không đo được feed)──▶ cho_xac_minh ──POST /giai──▶ cho_giai
    cho_giai ──(worker nhặt, TRƯỚC pending)──▶ dang_mo ──(khung đầu về)──▶ dang_giai
    dang_giai ──lệnh da_giai──▶ running (quét tiếp CÙNG context) ──(vẫn bị chặn)──▶ cho_xac_minh
    dang_giai ──lệnh dung──▶ failed (feed_rong_khong_captcha)
    dang_mo / dang_giai ──(hết 5′ | lỗi Playwright | rời miền | khung không về | không ai xem)──▶ cho_xac_minh
    cho_xac_minh ──quá 24 giờ──▶ failed (xac_minh_qua_han)
    cho_xac_minh / cho_giai ──DELETE /jobs/{id}──▶ cancelled (xoá thư mục profile)
    boot sweep: cho_giai / dang_mo / dang_giai ──▶ cho_xac_minh

HỢP ĐỒNG API (UI gọi; mọi route cần đăng nhập — `require_user`; chủ job được xét TRƯỚC admin):

  Chung — mọi route dưới đây:
    · cờ TẮT                         ⇒ 409 "Tính năng giải captcha trong popup đang tắt."
    · job không tồn tại              ⇒ 404
    · không phải chủ job, không admin ⇒ 403
    · sai trạng thái job             ⇒ 409, thông điệp riêng theo trạng thái (không nói "đã bắt đầu tải")

  POST /jobs/{id}/giai                      — "Tôi giải ngay"
      body: không có.   200: {"trang_thai": "cho_giai", "giai_con_luot": <số lần còn lại>}
      409: job không ở `cho_xac_minh` · hết lượt (trần `TRAN_GIAI_NGAY` = 3 lần/job, thông điệp riêng).

  GET  /jobs/{id}/giai/khung?token=<chuỗi 8–64 ký tự [A-Za-z0-9_-]>   — SSE (text/event-stream)
      Job phải ở `cho_giai` | `dang_mo` | `dang_giai`, ngoài ra 409. `token` do popup tự sinh
      (`crypto.randomUUID`) MỖI LẦN mở popup; khoá điều khiển gắn với token.
      Người đầu tiên mở kết nối lấy quyền điều khiển (`vai: "dieu_khien"`), người/tab sau chỉ xem
      (`vai: "chi_xem"`). Quyền nhả khi CHÍNH kết nối đó ngắt; cùng token nối lại (EventSource tự
      nối) thì giữ nguyên số thứ tự lô. Người chỉ-xem KHÔNG nhận email của ai. Ping 15 giây.
      Sự kiện (`event:` → `data:` JSON):
        · trang_thai {"trang_thai": "cho_giai"|"dang_mo"|"dang_giai", "vai": "dieu_khien"|"chi_xem",
                      "co_nguoi_giu": bool, "con_lai_giay": int|null (chỉ có ở dang_giai),
                      "so_lan_tai_lai": int, "ky": int, "vi_tri": int (chỉ ở cho_giai, nếu biết)}
          `ky` = KỲ hiện tại của lượt giải; tăng mỗi lần máy chủ huỷ gesture (mọi lý do). Popup gắn kỳ này
          vào mọi lô/lệnh huỷ; kỳ đổi ⇒ popup đánh số lô lại từ 0.
          — gửi khi đổi, và nhắc lại mỗi ~5 giây để popup chỉnh đồng hồ.
        · khung       {"seq": int, "jpeg": "<base64>", "deviceWidth": int, "deviceHeight": int,
                      "pageScaleFactor": number}  — chỉ khung MỚI NHẤT; kết nối mới nhận ngay khung hiện có.
        · bi_ngat     {"ly_do": str, "so_lan_tai_lai": int} — gesture dở bị huỷ, trang đã tải lại (kéo lại từ đầu).
        · ket_thuc    {"trang_thai": str, "ly_do": str|null} — lượt giải đã đóng (`running` sau "Đã giải xong",
                      `cho_xac_minh`, `failed`, `cancelled`…); luồng đóng ngay sau đó.

  POST /jobs/{id}/giai/chuot                — chuyển chuột của người (chỉ khi job ở `dang_giai`)
      body: {"token": str, "ky": int, "seq": int>=0, "khung_w": number>0, "khung_seq": int|null,
             "su_kien": [{"k": "down"|"move"|"up"|"wheel", "x": number, "y": number, "t": number (ms,
                          performance.now() của popup), "buttons": int (PointerEvent.buttons NGUYÊN),
                          "dx"?: number, "dy"?: number, "delta_mode"?: 0}, ...]}   (1–64 sự kiện/lô)
      `x`,`y` theo pixel của ảnh khung đang hiển thị (`khung_w` = naturalWidth, KHÔNG làm tròn);
      `khung_seq` (tuỳ chọn) = `seq` của khung đang hiển thị, thiếu ⇒ dùng khung mới nhất.
      `seq` là số thứ tự LÔ trong một KỲ, bắt đầu từ 0, liên tiếp; nhiều lô bay song song được, máy chủ
      sắp lại theo `seq` (lô tới sớm được đệm tới khi đủ, xa đến đâu cũng vậy, tối đa 128 lô; thiếu lô
      > 2 giây ⇒ huỷ gesture ⇒ kỳ mới). `ky` khác kỳ hiện tại ⇒ 409 `ky_cu`, lô KHÔNG được phát.
      200: {"ok": true, "trung": bool} (trung=true: `seq` đã nhận rồi, bỏ qua — an toàn để thử lại).
      400: số không hữu hạn / ngoài khung / `delta_mode`≠0 / thiếu hoặc quá 64 sự kiện — lô bị bỏ (số `seq`
           của nó coi như đã dùng), gesture đang dở bị HUỶ.   422: body sai dạng (FastAPI).
      409: token không giữ khoá (hoặc email khác) / job không ở `dang_giai` / chưa có khung.
           `{"detail": {"ma": "ky_cu", "ky": <kỳ hiện tại>, "thong_diep": str}}`: lô của kỳ cũ (tạo trước
           một lần huỷ) — không phát; popup chờ `trang_thai` mang kỳ mới. Thiếu `ky` ⇒ 400 (popup cũ).
      429: quá 50 lô/giây.   Sự kiện `buttons & ~1` (nút phải/giữa) bị bỏ, không phát.

  POST /jobs/{id}/giai/lenh                 — body {"token": str, "lenh": "da_giai"|"dung"|"huy_gesture",
                                                    "ky": int (bắt buộc với huy_gesture),
                                                    "den_seq": int (giao thức cũ — nhận nhưng bỏ qua)}
      Chỉ người đang giữ khoá, chỉ khi job ở `dang_giai`. 200: {"ok": true}; kết quả theo SSE `ket_thuc`.
      `huy_gesture`: popup đã tự bỏ gesture đang dở (không gửi `up`). Máy chủ không phát sự kiện nào;
                 nút đang nhấn ⇒ tải lại trang (SSE `bi_ngat`, tính vào trần tải lại); không ⇒ chỉ bỏ
                 hàng đợi; sang KỲ mới ⇒ mọi lô của kỳ cũ tới muộn ⇒ 409 `ky_cu`, không phát. `ky` khác kỳ
                 hiện tại ⇒ 409 `ky_cu` (lệnh cũ / bản sao muộn — không huỷ nhầm kỳ mới). Thiếu `ky` ⇒ 400.
                 Popup không gửi sự kiện chuột nào từ lúc bỏ gesture tới khi lệnh này trả 200.
      `da_giai`: máy chủ phát nốt các sự kiện đã nhận, tắt screencast, nhả khoá, đóng SSE, RỒI mới tải
                 lại trang MỘT lần và quét tiếp (vẫn bị chặn ⇒ `cho_xac_minh` "captcha_chua_xong").
      `dung`   : job `failed` ("feed_rong_khong_captcha"), không tải video nào.

  Thay đổi ở API cũ: `DELETE /jobs/{id}` rút được cả `cho_xac_minh`/`cho_giai`; job ở `cho_xac_minh`,
  `cho_giai`, `dang_mo`, `dang_giai` mang thêm `giai_con_luot` (số lần "Tôi giải ngay" còn lại).

Mọi hằng số dưới đây là THAM SỐ, đặt một chỗ (đổi ở đây, không rải trong code).
"""
from __future__ import annotations

import logging
import math
import random
import os
import itertools
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger("videodl.web")

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

# Đồng hồ đơn điệu dùng cho mọi lịch trong gói này. Gọi qua `giai_captcha.dong_ho()` (tra
# thuộc tính lúc gọi) để test thay bằng đồng hồ GIẢ.
dong_ho: Callable[[], float] = time.monotonic

CUA_SO_GIAI_GIAY = 300             # cửa sổ giải 5 phút (USER chốt)
CHO_XAC_MINH_QUA_HAN_GIO = 24      # `cho_xac_minh` quá hạn này ⇒ failed `xac_minh_qua_han` (CHƯA CÓ NỀN)
TRAN_GIAI_NGAY = 3                 # trần "Tôi giải ngay" mỗi job (CHƯA CÓ NỀN)
TRAN_TAI_LAI_MOI_LUOT = 2          # reload do gesture dở, mỗi lượt `dang_giai`
TRE_PHAT_NGUONG_GIAY = 0.05        # phát muộn hơn lịch chừng này ⇒ đếm `tre_phat_worker` (CHƯA ĐO ngưỡng)
TRAN_MAU_TRE = 4096                # trần mẫu độ trễ phát mỗi lượt giải (reservoir; đủ cho p95 ổn định)
LY_DO_HUY_POPUP = "popup_huy"      # lý do huỷ gesture khi popup gửi lệnh `huy_gesture` (đi kèm SSE `bi_ngat`)
THIEU_LO_TOI_DA_GIAY = 2.0         # lô thiếu quá lâu ⇒ huỷ gesture
KHUNG_MAX_WIDTH = 800              # `maxWidth` screencast
KHUNG_JPEG_QUALITY = 60
# Hai số dưới CHƯA ĐO (ĐP-704 b): chọn để popup kịp nối SSE sau khi worker nhặt job; đo ở job thật đầu tiên.
CHO_NGUOI_XEM_GIAY = 15.0          # `dang_mo`: chờ người giữ khoá (popup mở SSE sau khi bấm nút)
CHO_KHUNG_DAU_GIAY = 20.0          # `dang_mo`: chờ khung đầu hợp lệ
CHO_SSE_DONG_GIAY = 2.0            # sau `da_giai`: chờ SSE khung đóng hẳn trước khi quét
XA_LENH_TOI_DA_GIAY = 2.0          # trước lệnh: phát nốt hàng đợi tối đa chừng này
TICK_VONG_GIAY = 0.010             # nhịp tối đa của vòng worker (chỉ ngủ bằng page.wait_for_timeout)
LO_TOI_DA_SU_KIEN = 64
LO_TOI_DA_MOI_GIAY = 50
CHO_LO_TOI_DA = 128                # lô đệm chờ khe tối đa (≈ 50 lô/s × 2 s + dư); KẾ THỪA, CHƯA ĐO ở job thật
# Trần trên đếm CẢ mốc huỷ `None` (lô 400) lẫn lô thật. `seq` KHÔNG có trần trên: lô `seq` rất xa vẫn được đệm (nhận
# "ok"), rồi hụt quá `THIEU_LO_TOI_DA_GIAY` thì huỷ — bộ nhớ bị chặn bởi trần này chứ không bởi `seq`.
LECH_LICH_TOI_DA_GIAY = 10.0       # sự kiện hẹn phát xa hơn thế ⇒ đồng hồ popup lệch, bỏ lô
MAC_DINH_GOM_LO_POPUP_MS = 40      # phía popup (để UI dùng; máy chủ không phụ thuộc)

# D = độ trễ phát cố định. #10 (03/10): RTT tuần tự p50 128 / p90 183 / p99 225 ms, jitter liên
# tiếp p90 79 ms; neo ở sự kiện đầu gesture nên D phải phủ jitter (~80) + độ lệch do gom lô 40 ms
# ⇒ 120. Là số của MỘT máy/mạng/thời điểm ⇒ chỉnh được bằng env, không sửa code.
ENV_D_MS = "VIDEODL_CAPTCHA_D_MS"
D_MAC_DINH_MS = 120
D_TOI_THIEU_MS = 40
D_TOI_DA_MS = 1000
_D_DA_CANH_BAO: set[str] = set()

ENV_DIEU_HUONG = "VIDEODL_GIAI_DIEU_HUONG"
DIEU_HUONG_LOG = "log"    # job TikTok thật đầu tiên: ghi host+path, chặn khác miền, cho đổi đường dẫn cùng miền
DIEU_HUONG_CHAN = "chan"  # siết: chặn mọi điều hướng khác (host, đường dẫn) ban đầu
# TikTok có thể xác minh bằng redirect cùng miền, và 204 sẽ chặn nhầm ⇒ mặc định LOG
# cho tới khi có job thật cho thấy không cần.
DIEU_HUONG_MAC_DINH = DIEU_HUONG_LOG

# Lý do (cột `ly_do_dung`) khi job rời/vào các trạng thái giải.
LD_FEED_RONG = "feed_rong"
LD_KHONG_DO_DUOC_FEED = "khong_do_duoc_feed"
LD_QUA_HAN = "xac_minh_qua_han"
LD_DUNG_KHONG_CAPTCHA = "feed_rong_khong_captcha"
LD_CAPTCHA_CHUA_XONG = "captcha_chua_xong"
LD_KHONG_AI_XEM = "khong_ai_xem"
LD_HET_GIO = "het_gio_giai"
LD_LOI_TRINH_DUYET = "loi_trinh_duyet"
LD_MO_TRANG_TRUOT = "mo_trang_truot"
LD_ROI_MIEN = "roi_mien"
LD_KHONG_CO_KHUNG = "khong_co_khung"
LD_GESTURE_QUA_NHIEU = "gesture_bo_do_qua_nhieu"
LD_KHOI_DONG_LAI = "khoi_dong_lai"        # boot sweep, cờ BẬT: lượt giải dở lúc chết ⇒ `cho_xac_minh`
LD_LOI_HE_THONG = "loi_he_thong"          # lỗi rơi ra vòng worker giữa lượt giải ⇒ `cho_xac_minh`
# Boot sweep, cờ TẮT (ĐP-706): job còn ở trạng thái giải ⇒ `interrupted`. Cờ tắt thì không còn lối
# ra tự động nào (không nhặt `cho_giai`, không quét quá hạn 24 giờ) ⇒ để nguyên là treo vô hạn.
LD_TINH_NANG_GIAI_TAT = "tinh_nang_giai_tat"

TRANG_THAI_GIAI = ("cho_xac_minh", "cho_giai", "dang_mo", "dang_giai")
TRANG_THAI_CO_PHIEN = ("cho_giai", "dang_mo", "dang_giai")

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def doc_d_ms(env: dict | None = None) -> int:
    """D (ms) từ `VIDEODL_CAPTCHA_D_MS`: số nguyên, kẹp vào [40, 1000]. Giá trị lạ hoặc không
    đọc được ⇒ 120 và đúng MỘT dòng WARNING cho mỗi giá trị (không lặp mỗi lượt giải)."""
    tho = (os.environ if env is None else env).get(ENV_D_MS)
    if tho is None or tho.strip() == "":
        return D_MAC_DINH_MS
    try:
        gia_tri = int(tho.strip())
    except (ValueError, OverflowError):
        if tho not in _D_DA_CANH_BAO:
            _D_DA_CANH_BAO.add(tho)
            log.warning("%s=%r không đọc được thành số nguyên — dùng mặc định %d ms",
                        ENV_D_MS, tho[:40], D_MAC_DINH_MS)
        return D_MAC_DINH_MS
    kep = min(max(gia_tri, D_TOI_THIEU_MS), D_TOI_DA_MS)
    if kep != gia_tri and tho not in _D_DA_CANH_BAO:
        _D_DA_CANH_BAO.add(tho)
        log.warning("%s=%d ngoài [%d, %d] — kẹp về %d ms",
                    ENV_D_MS, gia_tri, D_TOI_THIEU_MS, D_TOI_DA_MS, kep)
    return kep


def che_do_dieu_huong() -> str:
    gia_tri = os.environ.get(ENV_DIEU_HUONG, "").strip().lower()
    return gia_tri if gia_tri in (DIEU_HUONG_LOG, DIEU_HUONG_CHAN) else DIEU_HUONG_MAC_DINH


def token_hop_le(token: object) -> bool:
    return isinstance(token, str) and _TOKEN_RE.fullmatch(token) is not None


# ---------------------------------------------------------------------------
# Quyết định "cần người xác minh" (thuần)
# ---------------------------------------------------------------------------

def ly_do_can_xac_minh(thong_ke_feed: dict, ly_do_dung: str | None, so_refs: int,
                       max_videos: int) -> str | None:
    """Job profile vừa quét xong một lượt: có phải TikTok đòi xác minh không?

    · `feed_rong`          — mọi phản hồi feed đo được đều 0 byte (`ly_do_dung == "feed_rong"`,
                             chỉ đặt khi CHƯA đủ video): bất kể còn lạc một link `/video/`.
    · `khong_do_duoc_feed` — KHÔNG có phản hồi feed nào (0/0), bất kể số link (trang bị chặn bằng
                             HTML không gọi feed). Đủ `max_videos` link rồi thì không phải bị chặn.
    None = không đòi xác minh (đường cũ).
    """
    if ly_do_dung == LD_FEED_RONG:
        return LD_FEED_RONG
    if (thong_ke_feed.get("rong", 0) == 0 and thong_ke_feed.get("co_du_lieu", 0) == 0
            and so_refs < max_videos):
        return LD_KHONG_DO_DUOC_FEED
    return None


def sau_giai_van_bi_chan(thong_ke_feed: dict) -> bool:
    """Sau "Đã giải xong" + tải lại: cùng tín hiệu feed đã đưa job vào `cho_xac_minh`
    (rỗng ở mọi phản hồi, hoặc không đo được feed nào) ⇒ vẫn bị chặn."""
    return thong_ke_feed.get("co_du_lieu", 0) == 0


# ---------------------------------------------------------------------------
# Sự kiện chuột, đổi đơn vị, kiểm đầu vào
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SuKien:
    """Một sự kiện chuột của người, toạ độ ĐÃ ĐỔI sang CSS px của viewport trang.
    `t` = `performance.now()` của popup (ms)."""
    k: str
    x: float
    y: float
    t: float
    buttons: int
    dx: float = 0.0
    dy: float = 0.0


class LoiGiai(Exception):
    """Lỗi có mã HTTP; `huy_gesture=True` ⇒ gesture đang dở của người này phải bị huỷ."""

    def __init__(self, ma: int, thong_diep: str, huy_gesture: bool = False):
        super().__init__(thong_diep)
        self.ma = ma
        self.thong_diep = thong_diep
        self.huy_gesture = huy_gesture


class LoiKyCu(LoiGiai):
    """409 `ky_cu`: lô/lệnh mang KỲ cũ — tạo trước một lần huỷ gesture (máy chủ đã bỏ mọi thứ của kỳ đó và
    đánh số lại từ 0). Không phát, không làm mốc. Người gọi trả `{"ma": "ky_cu", "ky": <kỳ hiện tại>}`."""

    def __init__(self, ky_hien_tai: int):
        super().__init__(409, "Thao tác thuộc lượt kéo đã bị huỷ — đồng bộ lại rồi kéo lại từ đầu.")
        self.ky = ky_hien_tai


def doi_don_vi(x: float, y: float, khung_w: float, device_w: float) -> tuple[float, float]:
    """Toạ độ theo ảnh khung → CSS px của viewport: MỘT hệ số `deviceWidth / khung_w` cho cả x và y.

    Đây là ĐỔI ĐƠN VỊ, không phải làm tròn: phần lẻ giữ nguyên (Chromium tự cắt khi tạo
    `clientX`). KHÔNG cộng `scrollOffset` — CDP Input tính theo VIEWPORT và khung screencast
    cũng là viewport (đo #13: cuộn 400 rồi nhấn `y=50` ⇒ trang nhận `clientY=50`)."""
    he_so = device_w / khung_w
    return x * he_so, y * he_so


_K_HOP_LE = ("down", "move", "up", "wheel")


def _la_so_huu_han(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def kiem_su_kien(raw: object, khung_w: float, khung_h: float, device_w: float) -> SuKien | None:
    """Kiểm MỘT sự kiện từ popup. Trả `SuKien` đã đổi đơn vị; `None` = bỏ (nút phải/giữa).
    Sai ⇒ `LoiGiai(400, ..., huy_gesture=True)`."""
    if not isinstance(raw, dict):
        raise LoiGiai(400, "Sự kiện chuột không đúng dạng.", True)
    k = raw.get("k")
    if k not in _K_HOP_LE:
        raise LoiGiai(400, "Loại sự kiện chuột không hợp lệ (down/move/up/wheel).", True)
    x, y, t, buttons = raw.get("x"), raw.get("y"), raw.get("t"), raw.get("buttons")
    if not (_la_so_huu_han(x) and _la_so_huu_han(y) and _la_so_huu_han(t)):
        raise LoiGiai(400, "Toạ độ/thời điểm phải là số hữu hạn.", True)
    if t < 0:
        raise LoiGiai(400, "Thời điểm sự kiện không được âm.", True)
    if not isinstance(buttons, int) or isinstance(buttons, bool) or not 0 <= buttons <= 31:
        raise LoiGiai(400, "`buttons` phải là số nguyên 0–31 (PointerEvent.buttons).", True)
    if not (0 <= x <= khung_w and 0 <= y <= khung_h):
        raise LoiGiai(400, "Điểm nằm ngoài khung — thao tác bị huỷ.", True)
    dx = dy = 0.0
    if k == "wheel":
        dm = raw.get("delta_mode", 0)
        if not isinstance(dm, int) or isinstance(dm, bool) or dm != 0:
            raise LoiGiai(400, "Chỉ nhận wheel theo pixel (delta_mode = 0).", True)
        dx, dy = raw.get("dx", 0), raw.get("dy")
        if not (_la_so_huu_han(dx) and _la_so_huu_han(dy)):
            raise LoiGiai(400, "wheel cần dx, dy là số hữu hạn.", True)
    if buttons & ~1:
        return None  # nút phải/giữa: bỏ, không phát
    cx, cy = doi_don_vi(x, y, khung_w, device_w)
    return SuKien(k=k, x=cx, y=cy, t=float(t), buttons=buttons, dx=float(dx), dy=float(dy))


# Bộ đếm KỲ toàn tiến trình: một lượt giải có thể trải NHIỀU đối tượng `PhienGiai` (phiên bị bỏ khi mọi SSE đóng lúc
# `cho_giai` rồi tạo lại khi nối lại — `don_phien_roi`), mà popup chỉ nhận kỳ TĂNG. Đếm theo từng phiên thì phiên tạo
# lại bắt đầu từ 0 ⇒ popup đang ở kỳ cao hơn bị `ky_cu` mọi lô tới hết lượt. Chỉ cần tăng ngặt, không cần liên tiếp.
# Hạt giống = mili-giây hiện tại: kỳ vẫn tăng QUA các lần khởi động lại tiến trình (kẽ hẹp: restart xong, ai đó bấm
# "Tôi giải ngay" trước khi tab cũ tự nối lại SSE ⇒ tab cũ vào lượt mới với kỳ cao). Điều kiện: tiến trình cũ cấp ÍT kỳ
# hơn số mili-giây từ lúc nó khởi động tới lúc restart — luôn đúng ở nhịp người (một kỳ mỗi lần huỷ/phiên, cách nhau cỡ
# giây; restart mất vài giây). ≈1,8e12 < 2^53: an toàn với số JS.
def _tao_dem_ky() -> itertools.count:
    return itertools.count(time.time_ns() // 1_000_000)


_DEM_KY = _tao_dem_ky()


def _ky_ke_tiep() -> int:
    return next(_DEM_KY)


def la_su_kien_nut(ev: SuKien) -> bool:
    """Sự kiện có thao tác NÚT (nhấn, nhả, kéo khi giữ nút trái) — khác rê chuột."""
    return ev.k in ("down", "up") or (ev.k == "move" and bool(ev.buttons & 1))


def tham_so_cdp(ev: SuKien) -> dict:
    """`Input.dispatchMouseEvent` cho MỘT sự kiện của người — `buttons` NGUYÊN từ người (move
    hover ⇒ `buttons: 0`), chỉ nút trái. Không thêm trường nào ngoài những gì người tạo ra."""
    if ev.k == "down":
        return {"type": "mousePressed", "x": ev.x, "y": ev.y, "button": "left",
                "buttons": ev.buttons, "clickCount": 1}
    if ev.k == "up":
        return {"type": "mouseReleased", "x": ev.x, "y": ev.y, "button": "left",
                "buttons": ev.buttons, "clickCount": 1}
    if ev.k == "wheel":
        return {"type": "mouseWheel", "x": ev.x, "y": ev.y, "deltaX": ev.dx, "deltaY": ev.dy,
                "buttons": ev.buttons}
    return {"type": "mouseMoved", "x": ev.x, "y": ev.y,
            "button": "left" if ev.buttons & 1 else "none", "buttons": ev.buttons}


# ---------------------------------------------------------------------------
# Lịch phát lại
# ---------------------------------------------------------------------------

class ThongKePhat:
    """Số đo phát chuột của MỘT lượt giải, dùng CHUNG qua mọi `BoPhatLai` của lượt đó (đổi token thay
    bộ lịch nhưng không được làm mất số): tổng sự kiện đã phát, số lần nhả chuột đã phát, và mẫu độ trễ
    phát (giây, `bây giờ − lịch`) giữ bằng reservoir có trần `TRAN_MAU_TRE` — một reservoir liền mạch
    nên phân phối đúng dù đổi token giữa lượt. Seed cố định ⇒ kết quả lặp lại được.

    `gesture_nop` là số lần người thực sự NHẢ chuột (`up` đã phát) = số lần nộp thử một cú kéo. Đây là
    PROXY, KHÔNG phải số bước captcha: worker không đọc DOM captcha nên không đếm được số bước thật.
    """

    def __init__(self, tran: int = TRAN_MAU_TRE, seed: int = 0):
        self.tran = tran
        self.so_phat = 0
        self.gesture_nop = 0
        self.tre_max = 0.0
        self.mau: list[float] = []
        self._rng = random.Random(seed)

    def ghi(self, tre_giay: float, la_up: bool) -> None:
        self.so_phat += 1
        if la_up:
            self.gesture_nop += 1
        if tre_giay > self.tre_max:
            self.tre_max = tre_giay
        if len(self.mau) < self.tran:
            self.mau.append(tre_giay)
        else:
            j = self._rng.randrange(self.so_phat)
            if j < self.tran:
                self.mau[j] = tre_giay


def tom_tat_tre(mau: list[float]) -> tuple[int, int] | None:
    """(p50, p95) theo nearest-rank, đơn vị ms làm tròn xuống. Mẫu rỗng ⇒ None."""
    if not mau:
        return None
    xs = sorted(mau)

    def hang(p: float) -> int:
        return int(xs[max(0, math.ceil(p * len(xs)) - 1)] * 1000)

    return hang(0.50), hang(0.95)


class BoPhatLai:
    """Lịch phát với độ trễ cố định D (thuần: không I/O, đồng hồ do người gọi đưa vào).

    Lịch phát của sự kiện i = `t_i + anh_xa + D_hieu_luc` — `anh_xa` đặt ở sự kiện ĐẦU của một
    đợt (đồng hồ popup → đồng hồ máy chủ), nên cả đợt DỜI PHA ĐỀU và mọi khoảng thời gian giữ
    nguyên đúng như người tạo ra. Sự kiện tới trễ hơn lịch ⇒ nâng `D_hieu_luc` lên đúng độ
    trễ đó (không bao giờ giảm trong một đợt) và đếm `tre_qua_D`: ĐÚNG MỘT khoảng dài ra tại chỗ
    trễ, mọi khoảng sau đó bằng khoảng gốc (ĐP-609 câu 1). CẤM nén (phát ngay), nội suy, làm tròn.

    "Đợt" = từ lúc hàng đợi rỗng và không có nút đang nhấn, tới lúc nó lại rỗng.
    """

    def __init__(self, d_ms: float, thong_ke: ThongKePhat | None = None):
        self.d = d_ms / 1000.0
        self.thong_ke = thong_ke if thong_ke is not None else ThongKePhat()
        self._hang: deque[tuple[float, SuKien]] = deque()
        self._anh_xa: float | None = None
        self._d_hieu_luc = self.d
        self._lich_cuoi = -math.inf
        self.nut_giu_nguon = False       # luồng của NGƯỜI đang giữ nút (theo thứ tự đã nhận)
        self._cho_down_moi = False       # sau huỷ gesture: bỏ tàn dư của gesture cũ tới khi có `down` mới
        self.tre_qua_D = 0
        # Sự kiện PHÁT muộn hơn lịch > `TRE_PHAT_NGUONG_GIAY` vì chính worker trễ (renderer bận, reload
        # chặn): bị phát dồn, nhịp bị nén — dời pha chỉ phủ lô tới trễ do MẠNG. Chỉ đếm để đo ở job
        # thật đầu tiên (review F2), chưa đổi cách phát.
        self.tre_phat_worker = 0
        self.so_bo = 0                   # sự kiện bị bỏ (tàn dư gesture đã huỷ / `up` mồ côi)

    def nhan_lo(self, events: list[SuKien], t_toi: float) -> None:
        for ev in events:
            if self._cho_down_moi:
                if ev.k == "down":
                    self._cho_down_moi = False
                elif ev.k == "up":
                    self._cho_down_moi = False
                    self.so_bo += 1
                    continue
                elif ev.buttons & 1:
                    self.so_bo += 1
                    continue
            if ev.k == "up" and not self.nut_giu_nguon:
                self.so_bo += 1  # `up` không có `down` đi trước (tàn dư nút phải đã bỏ…)
                continue
            if ev.k == "move" and (ev.buttons & 1) and not self.nut_giu_nguon:
                # Kéo (nút trái đang nhấn) mà không có `down` đi trước: tàn dư của gesture đã huỷ khi
                # chính lô chứa `down` bị từ chối — lúc huỷ chưa có `down` nên `_cho_down_moi` không bật
                # (captchahf R16b). Popup không bao giờ gửi move có nút khi chưa mở gesture.
                self.so_bo += 1
                continue
            if self._anh_xa is None or (not self._hang and not self.nut_giu_nguon):
                self._anh_xa = t_toi - ev.t / 1000.0
                self._d_hieu_luc = self.d
            tre = t_toi - (ev.t / 1000.0 + self._anh_xa)
            if tre > self._d_hieu_luc:
                self._d_hieu_luc = tre
                self.tre_qua_D += 1
            lich = max(ev.t / 1000.0 + self._anh_xa + self._d_hieu_luc, self._lich_cuoi)
            if lich - t_toi > LECH_LICH_TOI_DA_GIAY:
                raise LoiGiai(400, "Đồng hồ popup lệch bất thường.", True)
            self._lich_cuoi = lich
            self._hang.append((lich, ev))
            if ev.k == "down":
                self.nut_giu_nguon = True
            elif ev.k == "up":
                self.nut_giu_nguon = False

    def den_han(self, bay_gio: float) -> list[SuKien]:
        """Các sự kiện tới hạn tại `bay_gio`, ĐÚNG thứ tự đã nhận."""
        ra: list[SuKien] = []
        while self._hang and self._hang[0][0] <= bay_gio:
            lich, ev = self._hang.popleft()
            if bay_gio - lich > TRE_PHAT_NGUONG_GIAY:
                self.tre_phat_worker += 1
            self.thong_ke.ghi(max(0.0, bay_gio - lich), ev.k == "up")
            ra.append(ev)
        return ra

    def diem_ke_tiep(self) -> float | None:
        return self._hang[0][0] if self._hang else None

    def con_hang(self) -> bool:
        return bool(self._hang)

    def co_nut_chua_phat(self) -> bool:
        """Có thao tác nút sẽ MẤT nếu huỷ ngay: nút đang giữ ở luồng người, hoặc sự kiện nút đã nhận mà chưa phát."""
        return self.nut_giu_nguon or any(la_su_kien_nut(ev) for _, ev in self._hang)

    def huy(self) -> None:
        """Bỏ mọi sự kiện chưa phát; ánh xạ đồng hồ làm lại ở sự kiện kế. Nút đang giữ ở luồng
        người ⇒ bỏ tàn dư của gesture đó (move có nút, `up`) tới khi có `down` mới."""
        self._cho_down_moi = self.nut_giu_nguon
        self._hang.clear()
        self.nut_giu_nguon = False
        self._anh_xa = None
        self._lich_cuoi = -math.inf


# ---------------------------------------------------------------------------
# Phiên giải (RAM) của một job
# ---------------------------------------------------------------------------

class PhienGiai:
    """Trạng thái RAM của MỘT lượt giải: khoá điều khiển theo token, hàng đợi lô, ô nhớ khung,
    hàng đợi lệnh, thông báo cho SSE. Luồng web (route, SSE) và luồng worker cùng chạm vào đây ⇒
    mọi thay đổi qua `self.khoa`. Worker KHÔNG đụng DB qua đối tượng này."""

    def __init__(self, job_id: int, chu: str, trang_thai: str = "cho_giai",
                 d_ms: float | None = None):
        self.job_id = job_id
        self.chu = chu
        self.khoa = threading.RLock()
        self.d_ms = doc_d_ms() if d_ms is None else d_ms
        # --- trạng thái hiển thị
        self.trang_thai = trang_thai
        self.han_mono: float | None = None
        self.so_lan_tai_lai = 0
        self.so_gesture_bo_do = 0
        self.da_dong = False
        self.ly_do_dong: str | None = None
        self.trang_thai_cuoi: str | None = None
        self.worker_giu = False
        self.phien_ban = 0
        self._thong_bao: deque[tuple[int, dict]] = deque(maxlen=32)
        self._so_thong_bao = 0
        # --- khoá điều khiển (token → email), nhả theo kết nối SSE
        self.token: str | None = None
        self.email: str | None = None
        self._token_cuoi: str | None = None   # token giữ khoá lần cuối (nối lại cùng token ⇒ giữ `expected_seq`)
        self._so_ket_noi_token = 0
        self.so_sse = 0
        # --- lô chuột
        self.expected_seq = 0
        # KỲ: tăng ở ĐÚNG MỘT chỗ — `_huy_gesture_unlocked`. Lô/lệnh mang kỳ khác ⇒ `LoiKyCu` (409 `ky_cu`).
        # `seq` đếm lại từ 0 mỗi kỳ. Popup gắn kỳ LÚC GỬI ⇒ lô tạo trước một lần huỷ luôn mang kỳ cũ, tới lúc
        # nào cũng bị chặn ở đây — kể cả request đã lên dây từ trước sự cố.
        self.ky = _ky_ke_tiep()
        # Kỳ MỚI NHẤT do một lần huỷ BỎ thao tác nút chưa phát sinh ra (0 = chưa có). Chỉ tăng, không bao giờ xoá:
        # popup so với kỳ nó đang biết ⇒ biết cú kéo đã gửi (và đã được 200) có bị mất không, kể cả khi đọc muộn hoặc
        # hai lần huỷ liền nhau trong một nhịp SSE. Gửi trong `trang_thai` và phản hồi `huy_gesture`.
        self.ky_mat_nut = 0
        # `None` = MỐC HUỶ: lô `seq` đó bị từ chối (400) ⇒ huỷ gesture ĐÚNG lúc xả tới `seq` này, không
        # sớm hơn — lô trước nó (vd chứa `down`) có thể còn đang bay vì popup POST song song.
        self._cho_lo: dict[int, list[SuKien] | None] = {}
        self._cho_lo_tu: float | None = None
        # Số đo phát của cả lượt: một đối tượng, mọi bộ lịch (kể cả sau đổi token) ghi vào cùng chỗ.
        self.thong_ke_phat = ThongKePhat()
        # Số lần huỷ gesture theo lý do, cả lượt (đếm ở `_huy_gesture_unlocked` — chỗ duy nhất mọi lần huỷ đi qua).
        self.huy_theo_ly_do: dict[str, int] = {}
        self.bo_phat = BoPhatLai(self.d_ms, self.thong_ke_phat)
        self._tre_cu = 0                      # `tre_qua_D` của các token đã qua (bộ lịch bị thay khi đổi token)
        self._tre_phat_cu = 0                 # `tre_phat_worker` của các token đã qua
        self._co_huy: str | None = None
        self._lan_post: deque[float] = deque()
        # --- khung (chỉ giữ khung mới nhất)
        self.khung_seq = 0
        self.khung: dict | None = None
        self._dw_theo_seq: deque[tuple[int, float, float]] = deque(maxlen=128)
        # --- lệnh người
        self._lenh: deque[str] = deque()

    # ----- khoá điều khiển ------------------------------------------------
    def nhan_khoa(self, token: str, email: str) -> bool:
        """Một kết nối SSE mới mang `token`. True = kết nối này đang GIỮ quyền điều khiển."""
        with self.khoa:
            if self.token is None:
                if token != self._token_cuoi:
                    # Token MỚI lấy khoá: số thứ tự lô và ánh xạ đồng hồ làm lại; gesture dở của
                    # token cũ bị huỷ (worker quyết có phải tải lại không).
                    if self._token_cuoi is not None:
                        self._huy_gesture_unlocked("doi_token")   # tính `ky_mat_nut` rồi mới xoá đệm, seq về 0
                    else:
                        # Phòng thủ: token đầu tiên của phiên — trạng thái khởi tạo đã sạch sẵn (seq 0, đệm rỗng).
                        self.expected_seq = 0
                        self._cho_lo.clear()
                        self._cho_lo_tu = None
                    self._tre_cu += self.bo_phat.tre_qua_D
                    self._tre_phat_cu += self.bo_phat.tre_phat_worker
                    self.bo_phat = BoPhatLai(self.d_ms, self.thong_ke_phat)
                self.token, self.email, self._token_cuoi = token, email, token
                self._so_ket_noi_token = 1
                self._doi()
                return True
            if token == self.token and email == self.email:
                self._so_ket_noi_token += 1  # cùng token nối lại khi kết nối cũ chưa bị phát hiện ngắt
                return True
            return False

    def nha_khoa(self, token: str, email: str) -> None:
        """Kết nối SSE mang `token` vừa ngắt. Nhả khoá khi KẾT NỐI CUỐI của token đó ngắt."""
        with self.khoa:
            if self.token == token and self.email == email:
                self._so_ket_noi_token -= 1
                if self._so_ket_noi_token <= 0:
                    self.token = self.email = None
                    self._so_ket_noi_token = 0
                    self._doi()

    def la_giu(self, token: str, email: str) -> bool:
        with self.khoa:
            return self.token is not None and token == self.token and email == self.email

    def co_nguoi_giu(self) -> bool:
        with self.khoa:
            return self.token is not None

    def _nha_het(self) -> None:
        self.token = self.email = None
        self._so_ket_noi_token = 0

    # ----- lô chuột -------------------------------------------------------
    def kiem_tan_suat(self, bay_gio: float) -> None:
        with self.khoa:
            while self._lan_post and bay_gio - self._lan_post[0] > 1.0:
                self._lan_post.popleft()
            if len(self._lan_post) >= LO_TOI_DA_MOI_GIAY:
                raise LoiGiai(429, "Gửi chuột quá dày — chậm lại.")
            self._lan_post.append(bay_gio)

    def nhan_lo(self, token: str, email: str, seq: int, events: list[SuKien],
                bay_gio: float | None = None, ky: int | None = None) -> str:
        """Nhận lô `(ky, seq)`: "ok" hoặc "trung" (đã nhận rồi). Giữ lô tới sớm tới khi đủ thứ tự, xa đến đâu
        cũng vậy (trần cũ `seq > expected + 64 ⇒ 400` làm popup hỏng vĩnh viễn) — trong trần `CHO_LO_TOI_DA`.
        `ky` khác kỳ hiện tại ⇒ `LoiKyCu`. `ky=None` chỉ dành cho lời gọi nội bộ/test (API luôn truyền)."""
        t_toi = dong_ho() if bay_gio is None else bay_gio
        with self.khoa:
            if not self.la_giu(token, email):
                raise LoiGiai(409, "Bạn không giữ quyền điều khiển (người/tab khác đang giải).")
            if ky is not None and ky != self.ky:
                raise LoiKyCu(self.ky)
            if seq < self.expected_seq:
                return "trung"
            if seq in self._cho_lo:
                return "trung"
            if seq != self.expected_seq and len(self._cho_lo) >= CHO_LO_TOI_DA:
                self._huy_gesture_unlocked("qua_nhieu_lo_cho")
                raise LoiKyCu(self.ky)
            self._cho_lo[seq] = list(events)
            if self._cho_lo_tu is None and seq != self.expected_seq:
                self._cho_lo_tu = t_toi
            self._xa_cho_lo(t_toi)
            return "ok"

    def kiem_ky(self, ky: int) -> None:
        """Lô mang kỳ khác ⇒ `LoiKyCu` NGAY, trước khi kiểm nội dung lô: lô kỳ cũ có điểm ngoài khung mà nhận 400 thì
        popup coi là lô của kỳ hiện tại bị từ chối và bỏ cú kéo đang dở của kỳ MỚI (không gửi `up` ⇒ nút kẹt)."""
        with self.khoa:
            if ky != self.ky:
                raise LoiKyCu(self.ky)

    def bo_lo(self, token: str, email: str, seq: int, bay_gio: float | None = None,
              ky: int | None = None) -> None:
        """Lô `seq` bị từ chối (400): số thứ tự của nó coi như ĐÃ DÙNG (nếu không, mọi lô sau nó kẹt
        chờ tới khi quá 2 giây) VÀ gesture dở bị huỷ — đặt thành mốc huỷ trong dãy `seq`, áp khi xả
        tới đúng chỗ (review F1: huỷ ngay khi lô `down` trước nó chưa tới thì huỷ không trúng gì, rồi
        `down`… `up` tới sau vẫn được phát — trang nhận một lần kéo thiếu đoạn giữa rồi NỘP)."""
        t_toi = dong_ho() if bay_gio is None else bay_gio
        with self.khoa:
            if not self.la_giu(token, email) or seq < self.expected_seq or seq in self._cho_lo:
                return
            if ky is not None and ky != self.ky:
                return                     # lô kỳ cũ: kỳ đó đã bị huỷ, không làm mốc gì nữa
            if seq != self.expected_seq and len(self._cho_lo) >= CHO_LO_TOI_DA:
                self._huy_gesture_unlocked("qua_nhieu_lo_cho")
                return
            self._cho_lo[seq] = None
            if self._cho_lo_tu is None and seq != self.expected_seq:
                self._cho_lo_tu = t_toi
            self._xa_cho_lo(t_toi)

    def _xa_cho_lo(self, t_toi: float) -> None:
        while self.expected_seq in self._cho_lo:
            lo = self._cho_lo.pop(self.expected_seq)
            self.expected_seq += 1
            if lo is None:
                self._huy_gesture_unlocked("lo_bi_tu_choi")
            elif lo:
                try:
                    self.bo_phat.nhan_lo(lo, t_toi)
                except LoiGiai:
                    # Lô đã rời `_cho_lo` mà (một phần) chưa vào `_hang` ⇒ truyền nó để tính có mất thao tác nút không.
                    self._huy_gesture_unlocked("lo_khong_hop_le", lo_dang_xa=lo)
        if not self._cho_lo:
            self._cho_lo_tu = None

    def kiem_thieu_lo(self, bay_gio: float) -> None:
        """Worker gọi mỗi nhịp: lô thiếu quá `THIEU_LO_TOI_DA_GIAY` ⇒ huỷ gesture, bỏ qua chỗ hụt."""
        with self.khoa:
            if self._cho_lo_tu is not None and bay_gio - self._cho_lo_tu > THIEU_LO_TOI_DA_GIAY:
                # Chỉ huỷ ⇒ sang kỳ mới (seq về 0, đệm xoá). KHÔNG nhảy mốc tới `max+1`: nhảy mốc biến lô CŨ kế
                # tiếp (còn đang thử lại) thành "đúng thứ tự" và phát nó — lỗ đo được ở reviewer #51.
                self._huy_gesture_unlocked("thieu_lo")

    def huy_gesture(self, ly_do: str) -> None:
        with self.khoa:
            self._huy_gesture_unlocked(ly_do)

    def _huy_gesture_unlocked(self, ly_do: str, lo_dang_xa: list[SuKien] | None = None) -> None:
        """Huỷ gesture dở VÀ sang kỳ mới: mọi lô/lệnh của kỳ cũ (kể cả lô đang đệm, lô còn đang thử lại tới
        sau) không bao giờ được phát; popup học kỳ mới qua `trang_thai` (≤ 1 nhịp SSE) và đánh số lại từ 0.
        Đây là CHỖ DUY NHẤT đổi kỳ — mọi lý do huỷ (đổi token, hụt lô, lô bị từ chối, popup huỷ, đệm tràn)
        đều đi qua đây. Nối lại SSE cùng token không huỷ ⇒ không đổi kỳ ⇒ cú kéo đang dở vẫn tiếp tục.

        `ky_mat_nut` tính TRƯỚC khi xoá: nút đang giữ ở luồng người, sự kiện nút đã nhận chưa phát (`_hang`), lô đang
        chờ sau chỗ hụt (`_cho_lo`), lô đang xả dở (`lo_dang_xa`). Lô `None` (400) KHÔNG tính: popup không nhận 200
        cho nó nên tự biết (lô có nút) — tính nó sẽ báo nhầm lô chỉ rê."""
        mat_nut = (self.bo_phat.co_nut_chua_phat()
                   or any(lo and any(la_su_kien_nut(e) for e in lo) for lo in self._cho_lo.values())
                   or (lo_dang_xa is not None and any(la_su_kien_nut(e) for e in lo_dang_xa)))
        self.bo_phat.huy()
        self.huy_theo_ly_do[ly_do] = self.huy_theo_ly_do.get(ly_do, 0) + 1
        self._co_huy = ly_do
        self.ky = _ky_ke_tiep()
        if mat_nut:
            self.ky_mat_nut = self.ky
        self.expected_seq = 0
        self._cho_lo.clear()
        self._cho_lo_tu = None
        self._doi()

    def lay_huy(self) -> str | None:
        with self.khoa:
            ly_do, self._co_huy = self._co_huy, None
            return ly_do

    def den_han(self, bay_gio: float) -> list[SuKien]:
        with self.khoa:
            return self.bo_phat.den_han(bay_gio)

    def diem_ke_tiep(self) -> float | None:
        with self.khoa:
            return self.bo_phat.diem_ke_tiep()

    def con_hang(self) -> bool:
        with self.khoa:
            return self.bo_phat.con_hang() or bool(self._cho_lo)

    def tre_qua_d_tong(self) -> int:
        """Số lần sự kiện tới trễ hơn lịch D trong cả lượt giải (để log, hiệu chỉnh D về sau)."""
        with self.khoa:
            return self._tre_cu + self.bo_phat.tre_qua_D

    def so_do_luot(self) -> dict[str, int | None]:
        """Số đo của lượt để log — chỉ số, không mang dữ liệu khách. `popup_huy` đếm mọi lệnh huỷ của popup
        (kể cả lúc không nhấn nút, khác `so_gesture_bo_do`); `huy_khac` mọi lý do khác trừ đổi token."""
        with self.khoa:
            tk = self.thong_ke_phat
            tt = tom_tat_tre(tk.mau)
            return {
                "so_phat": tk.so_phat,
                "gesture_nop": tk.gesture_nop,
                "tre_phat_p50_ms": tt[0] if tt else None,
                "tre_phat_p95_ms": tt[1] if tt else None,
                "tre_phat_max_ms": int(tk.tre_max * 1000) if tk.so_phat else None,
                "popup_huy": self.huy_theo_ly_do.get(LY_DO_HUY_POPUP, 0),
                "huy_khac": sum(n for ld, n in self.huy_theo_ly_do.items()
                                if ld not in (LY_DO_HUY_POPUP, "doi_token")),
            }

    def tre_phat_worker_tong(self) -> int:
        """Số sự kiện phát muộn > `TRE_PHAT_NGUONG_GIAY` so với lịch vì worker trễ, cả lượt giải."""
        with self.khoa:
            return self._tre_phat_cu + self.bo_phat.tre_phat_worker

    # ----- khung ----------------------------------------------------------
    def dat_khung(self, jpeg_b64: str, meta: dict) -> None:
        """Ghi đè ô nhớ bằng khung mới nhất."""
        with self.khoa:
            self.khung_seq += 1
            dw = float(meta.get("deviceWidth") or 0)
            dh = float(meta.get("deviceHeight") or 0)
            self.khung = {"seq": self.khung_seq, "jpeg": jpeg_b64, "deviceWidth": int(dw),
                          "deviceHeight": int(dh),
                          "pageScaleFactor": meta.get("pageScaleFactor", 1)}
            self._dw_theo_seq.append((self.khung_seq, dw, dh))
            self._doi()

    def lay_khung(self) -> dict | None:
        with self.khoa:
            return self.khung

    def kich_thuoc_thiet_bi(self, khung_seq: int | None) -> tuple[float, float] | None:
        """(deviceWidth, deviceHeight) của khung mà popup đang hiển thị; thiếu ⇒ khung mới nhất."""
        with self.khoa:
            if not self._dw_theo_seq:
                return None
            if khung_seq is not None:
                for s, dw, dh in self._dw_theo_seq:
                    if s == khung_seq and dw > 0 and dh > 0:
                        return dw, dh
            _s, dw, dh = self._dw_theo_seq[-1]
            return (dw, dh) if dw > 0 and dh > 0 else None

    # ----- lệnh -----------------------------------------------------------
    def dat_lenh(self, token: str, email: str, lenh: str) -> None:
        with self.khoa:
            if not self.la_giu(token, email):
                raise LoiGiai(409, "Bạn không giữ quyền điều khiển (người/tab khác đang giải).")
            if self.trang_thai != "dang_giai" or self.da_dong:
                raise LoiGiai(409, "Lượt giải không còn ở bước đang giải.")
            self._lenh.append(lenh)

    def huy_gesture_cua_nguoi_giu(self, token: str, email: str, ky: int | None = None) -> tuple[int, int]:
        """Lệnh `huy_gesture` (R15b KHÉP): popup tự bỏ gesture (`pointercancel`/`lostpointercapture`/
        `blur`) và KHÔNG gửi `up` — nhả chuột là bước nộp lần thử (ĐP-529/602). Không có lệnh này thì
        máy chủ không biết: chỉ HỤT `seq` mới huỷ (`kiem_thieu_lo`), còn popup im lặng thì nút kẹt nhấn.
        Đi đúng đường huỷ có sẵn (ĐP-606 (a)): worker không phát sự kiện nào; nút đang nhấn ⇒ tải lại
        trang, tính vào trần `TRAN_TAI_LAI_MOI_LUOT`; nút không nhấn ⇒ chỉ bỏ hàng đợi.

        `ky` = kỳ popup đang biết lúc gửi. Khác kỳ hiện tại ⇒ `LoiKyCu`: máy chủ đã huỷ và sang kỳ mới sau
        lần popup học kỳ — lệnh này là bản sao muộn / lệnh cũ, chạy nữa là huỷ nhầm gesture của kỳ mới. Đúng
        kỳ ⇒ huỷ và sang kỳ mới: mọi lô của kỳ cũ (đang bay, bị abort vì timeout rồi tới muộn) thành
        `ky_cu`, không phát — thay cho `den_seq` của giao thức cũ (`den_seq` popup vẫn gửi, máy chủ bỏ qua)."""
        with self.khoa:
            if not self.la_giu(token, email):
                raise LoiGiai(409, "Bạn không giữ quyền điều khiển (người/tab khác đang giải).")
            if self.trang_thai != "dang_giai" or self.da_dong:
                raise LoiGiai(409, "Lượt giải không còn ở bước đang giải.")
            if ky is not None and ky != self.ky:
                raise LoiKyCu(self.ky)
            self._huy_gesture_unlocked(LY_DO_HUY_POPUP)
            return self.ky, self.ky_mat_nut        # chụp trong khoá: phản hồi không trả cặp lệch nhau

    def xem_lenh(self) -> str | None:
        with self.khoa:
            return self._lenh[0] if self._lenh else None

    def lay_lenh(self) -> str | None:
        with self.khoa:
            return self._lenh.popleft() if self._lenh else None

    # ----- trạng thái cho SSE --------------------------------------------
    def dat_trang_thai(self, trang_thai: str, con_lai_giay: float | None = None) -> None:
        with self.khoa:
            self.trang_thai = trang_thai
            self.han_mono = None if con_lai_giay is None else dong_ho() + con_lai_giay
            self._doi()

    def con_lai_giay(self) -> int | None:
        with self.khoa:
            if self.trang_thai != "dang_giai" or self.han_mono is None:
                return None
            return max(0, int(self.han_mono - dong_ho()))

    def thong_bao(self, loai: str, **du_lieu) -> None:
        with self.khoa:
            self._so_thong_bao += 1
            self._thong_bao.append((self._so_thong_bao, {"loai": loai, **du_lieu}))
            self._doi()

    def thong_bao_moi(self, sau_so: int) -> list[tuple[int, dict]]:
        with self.khoa:
            return [(n, d) for n, d in self._thong_bao if n > sau_so]

    def dong(self, trang_thai_cuoi: str, ly_do: str | None = None) -> None:
        """Lượt giải kết thúc: nhả khoá, SSE nhận `ket_thuc` rồi tự đóng."""
        with self.khoa:
            self.da_dong = True
            self.trang_thai_cuoi = trang_thai_cuoi
            self.ly_do_dong = ly_do
            self._nha_het()
            self._lenh.clear()
            self._cho_lo.clear()
            self.bo_phat.huy()
            self._doi()

    def _doi(self) -> None:
        self.phien_ban += 1

    def anh_chup(self, token: str | None, email: str) -> dict:
        with self.khoa:
            giu = token is not None and self.la_giu(token, email)
            return {
                "trang_thai": self.trang_thai,
                "vai": "dieu_khien" if giu else "chi_xem",
                "co_nguoi_giu": self.token is not None,
                "con_lai_giay": self.con_lai_giay(),
                "so_lan_tai_lai": self.so_lan_tai_lai,
                "ky": self.ky,
                "ky_mat_nut": self.ky_mat_nut,
            }

    def cho_nguoi_giu(self, toi_da_giay: float, cho: Callable[[float], None]) -> bool:
        """Chờ tới khi có người giữ khoá (tối đa `toi_da_giay`). `cho(giay)` là cách ngủ do người
        gọi chọn — worker truyền một hàm ngủ phù hợp với việc nó đang có/không có page."""
        han = dong_ho() + toi_da_giay
        while True:
            if self.co_nguoi_giu():
                return True
            if dong_ho() >= han:
                return False
            cho(0.05)

    def cho_sse_dong(self, toi_da_giay: float, cho: Callable[[float], None]) -> bool:
        han = dong_ho() + toi_da_giay
        while True:
            with self.khoa:
                if self.so_sse <= 0:
                    return True
            if dong_ho() >= han:
                return False
            cho(0.02)


# ---------------------------------------------------------------------------
# Sổ phiên (RAM, theo tiến trình)
# ---------------------------------------------------------------------------

_PHIEN: dict[int, PhienGiai] = {}
_KHOA_PHIEN = threading.Lock()


def lay_phien(job_id: int) -> PhienGiai | None:
    with _KHOA_PHIEN:
        return _PHIEN.get(job_id)


def lay_hoac_tao_phien(job_id: int, chu: str, trang_thai: str = "cho_giai", *,
                       worker_giu: bool = False) -> PhienGiai:
    """`worker_giu=True` (worker nhận phiên) đặt cờ TRONG `_KHOA_PHIEN`: gán sau khi nhả khoá thì
    `don_phien_roi` (SSE cuối ngắt) chen vào giữa, thấy cờ còn False, bỏ phiên khỏi sổ ⇒ popup nối
    lại tạo phiên MỚI, worker chờ người trên phiên cũ ⇒ `khong_ai_xem` oan, mất một lượt."""
    with _KHOA_PHIEN:
        p = _PHIEN.get(job_id)
        if p is None or p.da_dong:
            p = PhienGiai(job_id, chu, trang_thai)
            _PHIEN[job_id] = p
        if worker_giu:
            p.worker_giu = True
        return p


def bo_phien(job_id: int, phien: PhienGiai | None = None) -> None:
    """Bỏ phiên khỏi sổ (chỉ khi đúng đối tượng `phien` nếu được truyền)."""
    with _KHOA_PHIEN:
        if phien is None or _PHIEN.get(job_id) is phien:
            _PHIEN.pop(job_id, None)


def don_phien_roi(job_id: int, phien: PhienGiai) -> None:
    """SSE cuối cùng của phiên ngắt: nếu worker chưa nhận phiên này thì bỏ (không để phiên mồ
    côi nằm trong sổ cho một job đã bị rút)."""
    with _KHOA_PHIEN:
        if _PHIEN.get(job_id) is phien and phien.so_sse <= 0 and not phien.worker_giu:
            _PHIEN.pop(job_id, None)


def so_phien() -> int:
    with _KHOA_PHIEN:
        return len(_PHIEN)


def con_lai_tu_moc(vao_trang_thai_luc: str | None, cua_so_giay: float,
                   bay_gio: datetime | None = None) -> float:
    """Số giây còn lại của một cửa sổ đếm từ cột `vao_trang_thai_luc` (ISO UTC). Cột rỗng/hỏng ⇒
    nguyên cửa sổ (nghiêng về cho người thêm thời gian, không cắt oan)."""
    if not vao_trang_thai_luc:
        return float(cua_so_giay)
    try:
        moc = datetime.fromisoformat(vao_trang_thai_luc)
    except ValueError:
        return float(cua_so_giay)
    if moc.tzinfo is None:
        moc = moc.replace(tzinfo=timezone.utc)
    ban_gio = bay_gio or datetime.now(timezone.utc)
    return max(0.0, cua_so_giay - (ban_gio - moc).total_seconds())
