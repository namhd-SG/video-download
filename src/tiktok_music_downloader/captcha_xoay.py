"""Tool TỰ GIẢI captcha xoay của TikTok trước khi gọi người (M5, sau cờ `VIDEODL_TU_GIAI_CAPTCHA`, mặc định TẮT).

USER CHỐT 17/11 16:21 gỡ ranh giới ĐP-606 cho phần này ("thứ tôi cần là được việc"): tool được tự phát chuột
để giải captcha; người giải tay qua popup là DỰ PHÒNG khi tool trượt.

Trang: `.captcha-verify-container` có 2 `<img alt="Captcha">` (vòng ngoài, hình trong) + nút
`#captcha_slide_button` trong rãnh. Ước góc: `captcha_xoay_uoc_goc.uoc_goc`. Kéo nút theo quỹ đạo giống người
(hãm dần, vượt nhẹ rồi về, rung y nhỏ), nhả, chờ captcha đóng. Trượt ⇒ TikTok tự nạp ảnh mới ⇒ thử lại, tối
đa `SO_LAN_THU`. Không đọc/ghi gì ngoài trang; không gửi ảnh ra mạng.

Trạng thái đo: ánh xạ kéo→góc ĐO trên trang thật (17/11); bộ ước góc kiểm OFFLINE trên 4 mẫu thật + ảnh tổng
hợp; CHƯA có lượt kéo thật nào được chấm (lệnh thử sống chờ user duyệt) ⇒ cờ mặc định TẮT.
"""
from __future__ import annotations

import base64
import logging
import os
import random
from typing import Callable

log = logging.getLogger("ttmd")

ENV_TU_GIAI = "VIDEODL_TU_GIAI_CAPTCHA"
_GIA_TRI_BAT = ("1", "true", "yes", "on")

SEL_HOP = ".captcha-verify-container"
SEL_ANH = '.captcha-verify-container img[alt="Captcha"]'
SEL_NUT = "#captcha_slide_button"
SO_LAN_THU = 3
CHO_KET_QUA_MS = 3500

DA_QUA = "da_qua"            # captcha đã đóng sau khi nhả
KHONG_CO = "khong_co"        # không thấy captcha xoay (loại khác hoặc không bị chặn) ⇒ để đường cũ lo
TRUOT = "truot"              # thử hết số lần mà captcha vẫn còn ⇒ người làm dự phòng
LOI = "loi"                  # lỗi đọc trang/ảnh/thiếu thư viện ⇒ người làm dự phòng


def tu_giai_dang_bat() -> bool:
    return os.environ.get(ENV_TU_GIAI, "").strip().lower() in _GIA_TRI_BAT


def quy_dao_keo(d: float, rng: random.Random) -> list[tuple[float, float]]:
    """Các điểm (dx, dy) tương đối điểm nhấn, kết thúc ĐÚNG tại (d, ~0). Hãm dần (ease-out bậc 3), vượt
    1–4 % rồi lùi về đích, rung y ≤ 1,5 px. Không có dx âm (nút không đi lùi quá điểm xuất phát)."""
    n = rng.randint(18, 28)
    vuot = 1.0 + rng.uniform(0.01, 0.04)
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = i / n
        e = 1 - (1 - t) ** 3
        pts.append((max(0.0, d * e * vuot), rng.uniform(-1.5, 1.5)))
    for k in range(1, 4):  # lùi về đích
        pts.append((d * vuot + (d - d * vuot) * k / 3, rng.uniform(-0.8, 0.8)))
    pts[-1] = (d, 0.0)
    return pts


def _doc_anh(page) -> tuple[bytes, bytes] | None:
    anh = page.locator(SEL_ANH)
    if anh.count() < 2:
        return None
    out = []
    for i in range(2):
        src = anh.nth(i).get_attribute("src") or ""
        if not src.startswith("data:") or "," not in src:
            return None
        out.append(base64.b64decode(src.split(",", 1)[1]))
    return out[0], out[1]


def _mot_lan(page, rng: random.Random, uoc) -> bool | None:
    """Một lần kéo. True = captcha đóng; False = còn; None = không đọc được trang."""
    anh = _doc_anh(page)
    nut = page.locator(SEL_NUT).bounding_box() if page.locator(SEL_NUT).count() else None
    if anh is None or nut is None:
        return None
    rong_ray = page.evaluate(
        "s => { const b = document.querySelector(s); return b ? b.parentElement.parentElement"
        ".getBoundingClientRect().width : 0; }", SEL_NUT)
    if not rong_ray or rong_ray <= nut["width"]:
        return None
    kq = uoc.uoc_goc(anh[0], anh[1])
    d = uoc.khoang_keo_px(kq.theta_do, rong_ray, nut["width"])
    log.info("[tu-giai] lech=%.1f do_tin=%.2f d=%.1f px", kq.lech_do, kq.do_tin, d)
    x0, y0 = nut["x"] + nut["width"] / 2, nut["y"] + nut["height"] / 2
    page.mouse.move(x0 - rng.uniform(15, 40), y0 + rng.uniform(5, 15), steps=rng.randint(4, 8))
    page.mouse.move(x0, y0, steps=rng.randint(3, 6))
    page.wait_for_timeout(rng.randint(80, 220))
    page.mouse.down()
    page.wait_for_timeout(rng.randint(60, 160))
    for dx, dy in quy_dao_keo(d, rng):
        page.mouse.move(x0 + dx, y0 + dy)
        page.wait_for_timeout(rng.randint(10, 28))
    page.wait_for_timeout(rng.randint(120, 300))
    page.mouse.up()
    page.wait_for_timeout(CHO_KET_QUA_MS)
    return page.locator(SEL_HOP).count() == 0


def thu_tu_giai(page, so_lan: int = SO_LAN_THU, rng: random.Random | None = None,
                nap_uoc: Callable[[], object] | None = None) -> str:
    """Thử tự giải captcha xoay đang hiện trên `page`. Trả DA_QUA | KHONG_CO | TRUOT | LOI. Không ném
    (trừ BaseException không phải Exception): mọi lỗi ⇒ LOI để đường người dự phòng chạy tiếp."""
    rng = rng or random.Random()
    try:
        if page.locator(SEL_NUT).count() == 0 or page.locator(SEL_ANH).count() < 2:
            return KHONG_CO
        if nap_uoc is None:
            from tiktok_music_downloader import captcha_xoay_uoc_goc as uoc  # cv2/numpy: gói tuỳ chọn
        else:
            uoc = nap_uoc()
        for lan in range(1, so_lan + 1):
            ok = _mot_lan(page, rng, uoc)
            log.info("[tu-giai] lan=%d/%d ket_qua=%s", lan, so_lan, {True: "qua", False: "con", None: "khong_doc"}[ok])
            if ok:
                return DA_QUA
            if ok is None:
                return LOI if lan == 1 else TRUOT
            page.wait_for_timeout(rng.randint(1200, 2500))  # chờ ảnh mới nạp
        return TRUOT
    except Exception as exc:  # noqa: BLE001 — tự giải là đường phụ, không được làm vỡ job
        log.warning("[tu-giai] lỗi %s — để người giải", type(exc).__name__)
        return LOI
