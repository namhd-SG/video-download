"""Phần chạy TRONG LUỒNG WORKER của lượt giải captcha (job `dang_mo` → `dang_giai` → ...).

Playwright (sync) buộc mọi lời gọi lên `page`/`cdp` phải từ luồng đã tạo ra chúng (đo #8) ⇒ cả
lượt giải — mở trình duyệt, ống khung, phát chuột, quét tiếp — chạy ở đây; luồng web chỉ nói
chuyện với `PhienGiai` (RAM). Hợp đồng API và máy trạng thái: xem `web/giai_captcha.py`.

Quy tắc của vòng giải:
  · Luồng worker CHỈ ngủ bằng `page.wait_for_timeout` — callback CDP (khung, `Fetch.requestPaused`)
    chỉ chạy bên trong một lời gọi Playwright; ngủ bằng `time.sleep` thì trang treo.
  · Vòng phát không đọc DOM (đọc DOM làm lệch nhịp tới 32 ms, đo #9).
  · Mọi lời gọi Playwright trong `dang_*` nằm trong try: lỗi (kể cả `TargetClosedError`) ⇒ đóng
    sạch ⇒ `cho_xac_minh`, luồng worker SỐNG.
  · Đóng context TRƯỚC khi UPDATE sang `cho_xac_minh`/`failed`.
  · Ranh giới ĐP-606: tool KHÔNG phát sự kiện chuột/wheel nào người không tạo. Sự kiện cuối cùng
    tool phát là sự kiện của người; sau lệnh `da_giai` tắt screencast + nhả khoá + đóng SSE TRƯỚC
    khi `_auto_scroll` (sự kiện của tool, như `bfbafc1`) chạy, và nếu vẫn thấy dấu hiệu bị chặn thì
    KHÔNG cuộn.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from tiktok_music_downloader import scraper
from tiktok_music_downloader.utils import VideoRef
from web import giai_captcha as gc
from web import models, profile_theo_job
from web import models_giai_captcha as mgc

log = logging.getLogger("videodl.web")

# Ngủ khi CHƯA có page (chờ người xem). Tách ra để test thay bằng đồng hồ giả.
ngu: Callable[[float], None] = time.sleep

LOAI_REFS = "refs"
LOAI_CHO_XAC_MINH = "cho_xac_minh"
LOAI_FAILED = "failed"


@dataclass
class KetQuaGiai:
    loai: str                          # LOAI_*
    ly_do: str | None = None
    refs: list[VideoRef] | None = None


def _cho_xac_minh(ly_do: str) -> KetQuaGiai:
    return KetQuaGiai(LOAI_CHO_XAC_MINH, ly_do)


# ---------------------------------------------------------------------------
# Ngăn điều hướng + khung + trang mới
# ---------------------------------------------------------------------------

class GacDieuHuong:
    """Giữ trang đứng trên đường dẫn của profile.

    Lớp 1 (theo cấu tạo): `Fetch.enable` chỉ cho `Document` ở giai đoạn Request, trên CÙNG CDP
    session với screencast; request điều hướng main-frame tới nơi khác thì `Fetch.fulfillRequest`
    204 ⇒ trang đứng yên, khung lạ không bao giờ sinh ra. Request ở frame khác (iframe) và cùng
    đích thì `continueRequest` — KHÔNG bỏ sót request nào (bỏ sót ⇒ trang treo).
    Lớp 2: `Page.frameNavigated` cùng session; main-frame đã sang nơi "lạ" ⇒ cờ `trang_la` ⇒
    khung bị bỏ và lượt giải kết thúc `roi_mien`.

    Chế độ LOG (mặc định, `gc.DIEU_HUONG_LOG`): ghi host + đường dẫn (cắt query, ĐP-592) của MỌI
    điều hướng main-frame, chỉ chặn KHÁC MIỀN — đường dẫn khác cùng miền cho qua, để job thật đầu
    tiên cho biết TikTok có xác minh bằng redirect cùng miền không. Chế độ CHẶN: chặn cả đường dẫn khác.
    """

    def __init__(self, cdp, phien: gc.PhienGiai, ref_url: str, frame_id: str | None, che_do: str):
        sp = urlsplit(ref_url)
        self.cdp = cdp
        self.phien = phien
        self.netloc = sp.netloc.lower()
        self.path = sp.path
        self.frame_id = frame_id
        self.che_do = che_do
        self.trang_la = False
        self.so_chan = 0
        self.so_cho_qua = 0

    def bat(self) -> None:
        self.cdp.on("Fetch.requestPaused", self._khi_tam_dung)
        self.cdp.on("Page.frameNavigated", self._khi_dieu_huong)
        self.cdp.send("Fetch.enable", {"patterns": [{"resourceType": "Document",
                                                     "requestStage": "Request"}]})
        self.cdp.send("Page.enable")

    def tat(self) -> None:
        self.cdp.send("Fetch.disable")

    def _la_dich_ban_dau(self, url: str) -> bool:
        sp = urlsplit(url)
        return sp.netloc.lower() == self.netloc and sp.path == self.path

    def _la_cung_mien(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() == self.netloc

    def _khi_tam_dung(self, p: dict) -> None:
        rid = p.get("requestId")
        if rid is None:
            return
        try:
            la_main = (p.get("resourceType", "Document") == "Document"
                       and (self.frame_id is None or p.get("frameId") == self.frame_id))
            if not la_main:
                self.cdp.send("Fetch.continueRequest", {"requestId": rid})
                return
            url = p["request"]["url"]
            sp = urlsplit(url)
            chan = (not self._la_cung_mien(url)
                    or (self.che_do == gc.DIEU_HUONG_CHAN and not self._la_dich_ban_dau(url)))
            if not self._la_dich_ban_dau(url):
                # Chỉ host + đường dẫn, KHÔNG query (ĐP-592).
                log.info("[giai] điều hướng main-frame host=%s path=%s %s",
                         sp.hostname, sp.path, "CHẶN" if chan else "cho qua (chế độ log)")
            if chan:
                self.so_chan += 1
                self.cdp.send("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 204,
                                                      "responseHeaders": []})
            else:
                self.so_cho_qua += 1 if not self._la_dich_ban_dau(url) else 0
                self.cdp.send("Fetch.continueRequest", {"requestId": rid})
        except Exception:  # noqa: BLE001 — request đã tạm dừng thì phải được giải quyết, không treo trang
            log.warning("[giai] xử lý request tạm dừng lỗi — thử chặn", exc_info=True)
            try:
                self.cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
            except Exception:  # noqa: BLE001
                pass

    def _khi_dieu_huong(self, p: dict) -> None:
        try:
            frame = p.get("frame") or {}
            if frame.get("parentId") is not None:
                return
            url = frame.get("url", "")
            if url.startswith("about:blank"):
                return
            la = (not self._la_cung_mien(url)
                  or (self.che_do == gc.DIEU_HUONG_CHAN and not self._la_dich_ban_dau(url)))
            if la:
                self.trang_la = True
                sp = urlsplit(url)
                log.warning("[giai] trang đã rời miền/đường dẫn: host=%s path=%s", sp.hostname, sp.path)
        except Exception:  # noqa: BLE001
            log.debug("[giai] frameNavigated lỗi", exc_info=True)


def _bat_khung(cdp, phien: gc.PhienGiai, guard: GacDieuHuong) -> None:
    def khi_khung(p: dict) -> None:
        try:
            if not guard.trang_la:
                phien.dat_khung(p["data"], p.get("metadata") or {})
        except Exception:  # noqa: BLE001
            log.debug("[giai] ghi khung lỗi", exc_info=True)
        finally:
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]})
            except Exception:  # noqa: BLE001
                pass

    cdp.on("Page.screencastFrame", khi_khung)
    cdp.send("Page.startScreencast", {"format": "jpeg", "quality": gc.KHUNG_JPEG_QUALITY,
                                      "maxWidth": gc.KHUNG_MAX_WIDTH, "everyNthFrame": 1})


class _DongTrangMoi:
    """CDP Input là trusted ⇒ `target=_blank` / `window.open` qua được chặn popup: đóng ngay
    mọi page không phải page chính, đếm và log host + đường dẫn (cắt query)."""

    def __init__(self) -> None:
        self.so_dong = 0

    def __call__(self, trang) -> None:
        self.so_dong += 1
        try:
            sp = urlsplit(trang.url)
            log.info("[giai] đóng trang mới host=%s path=%s", sp.hostname, sp.path)
        except Exception:  # noqa: BLE001
            pass
        try:
            trang.close()
        except Exception:  # noqa: BLE001
            log.debug("[giai] đóng trang mới lỗi", exc_info=True)


def _ve_trang_profile(page, profile_url: str, ref_path: str) -> None:
    """Về lại trang profile: `reload`; nếu SPA đã đổi đường dẫn bằng pushState (không qua
    Fetch/`frameNavigated`) thì `goto(profile_url)`."""
    if urlsplit(page.url).path != ref_path:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
    else:
        page.reload(wait_until="domcontentloaded", timeout=30_000)


# ---------------------------------------------------------------------------
# Vòng giải
# ---------------------------------------------------------------------------

def _vong_giai(page, cdp, phien: gc.PhienGiai, guard: GacDieuHuong, profile_url: str,
               han: float) -> tuple[str, str | None]:
    """Vòng phát chuột của người. Trả ("da_giai"|"dung", None) hoặc ("cho_xac_minh", lý_do).

    Mỗi nhịp: kiểm hết giờ/rời miền · huỷ gesture dở · lệnh của người · phát các sự kiện tới
    hạn (đúng thứ tự, đúng toạ độ, đúng nhịp) · ngủ bằng `page.wait_for_timeout`.
    """
    nut_giu = False            # NÚT TRÁI trên trang đang bị nhấn (theo những gì ĐÃ phát)
    han_xa: float | None = None
    while True:
        bay_gio = gc.dong_ho()
        if guard.trang_la:
            return "cho_xac_minh", gc.LD_ROI_MIEN
        if bay_gio >= han:
            return "cho_xac_minh", gc.LD_HET_GIO
        phien.kiem_thieu_lo(bay_gio)

        huy = phien.lay_huy()
        if huy is not None and nut_giu:
            # Gesture dở khi nút ĐANG nhấn (ĐP-606 chốt (a)): KHÔNG phát sự kiện nào (nhả chuột là
            # bước NỘP lần thử — tool tự nhả là tự làm một bước giải). Tải lại trang để đặt lại
            # trạng thái kéo + captcha mới; tối đa `TRAN_TAI_LAI_MOI_LUOT` lần mỗi lượt.
            nut_giu = False
            phien.so_gesture_bo_do += 1
            if phien.so_lan_tai_lai >= gc.TRAN_TAI_LAI_MOI_LUOT:
                return "cho_xac_minh", gc.LD_GESTURE_QUA_NHIEU
            phien.so_lan_tai_lai += 1
            log.info("[giai] job %s: gesture dở (%s) — tải lại trang lần %d/%d", phien.job_id, huy,
                     phien.so_lan_tai_lai, gc.TRAN_TAI_LAI_MOI_LUOT)
            _ve_trang_profile(page, profile_url, guard.path)
            phien.thong_bao("bi_ngat", ly_do=huy, so_lan_tai_lai=phien.so_lan_tai_lai)

        lenh = phien.xem_lenh()
        if lenh is not None:
            # Phát nốt những gì người đã gửi TRƯỚC lệnh (bị trễ D) rồi mới làm theo lệnh.
            if han_xa is None:
                han_xa = bay_gio + gc.XA_LENH_TOI_DA_GIAY
            if not phien.con_hang() or bay_gio >= han_xa:
                phien.lay_lenh()
                return lenh, None

        for ev in phien.den_han(bay_gio):
            cdp.send("Input.dispatchMouseEvent", gc.tham_so_cdp(ev))
            if ev.k == "down":
                nut_giu = True
            elif ev.k == "up":
                nut_giu = False

        ms = gc.TICK_VONG_GIAY * 1000
        ke = phien.diem_ke_tiep()
        if ke is not None:
            ms = min(ms, max(1.0, (ke - gc.dong_ho()) * 1000))
        page.wait_for_timeout(ms)


def _quet_sau_giai(page, cdp, guard, phien, db_path: Path, job: dict, profile_url: str,
                   max_videos: int) -> KetQuaGiai:
    """Sau lệnh `da_giai`. Thứ tự CỐ ĐỊNH (ĐP-606): tắt screencast → nhả khoá + đóng SSE khung →
    ĐỔI sang `running` → tải lại trang ĐÚNG MỘT lần (lệnh của người) → nếu còn dấu hiệu bị chặn
    thì DỪNG, không `_auto_scroll` → ngược lại quét MỘT lượt như `bfbafc1`."""
    job_id = job["id"]
    try:
        cdp.send("Page.stopScreencast")
    except Exception:  # noqa: BLE001 — tắt trượt thì ctx đóng cũng dừng; không chặn việc quét
        log.debug("[giai] Page.stopScreencast lỗi", exc_info=True)
    try:
        guard.tat()
        cdp.detach()
    except Exception:  # noqa: BLE001
        log.debug("[giai] gỡ ngăn điều hướng lỗi", exc_info=True)
    phien.dong("running")
    if not phien.cho_sse_dong(gc.CHO_SSE_DONG_GIAY,
                              lambda g: page.wait_for_timeout(max(1.0, g * 1000))):
        log.warning("[giai] job %s: SSE khung chưa đóng sau %.0f s — quét tiếp", job_id,
                    gc.CHO_SSE_DONG_GIAY)
    if not mgc.chuyen_trang_thai(db_path, job_id, "dang_giai", "running", ly_do=None):
        return _cho_xac_minh("trang_thai_doi")

    so_trang = {"n": int(job.get("so_trang") or 0)}

    def dem_trang() -> None:
        so_trang["n"] += 1
        try:
            models.set_job_pages(db_path, job_id, so_trang["n"])
        except Exception:  # noqa: BLE001 — mất con số này không được làm hỏng lượt quét
            log.warning("job %s: không ghi được số trang index", job_id)

    da_chan = {"v": False}

    def kiem(feed_luot: dict) -> bool:
        da_chan["v"] = gc.sau_giai_van_bi_chan(feed_luot)
        return not da_chan["v"]

    # SPA đã đổi đường dẫn bằng pushState ⇒ không reload được đúng trang ⇒ vào lại như lượt thường.
    ve_dung_trang = urlsplit(page.url).path == guard.path
    refs = scraper.quet_tren_trang(
        page, profile_url, max_videos=max_videos * 2, dem_trang=dem_trang,
        thong_ke_feed={}, tai_lai_truoc_khi_cuon=ve_dung_trang, kiem_truoc_khi_cuon=kiem,
    )
    if da_chan["v"]:
        return _cho_xac_minh(gc.LD_CAPTCHA_CHUA_XONG)
    return KetQuaGiai(LOAI_REFS, None, refs)


def _phien_tren_ctx(ctx, db_path: Path, job: dict, phien: gc.PhienGiai, cookies_path: str | None,
                    che_do: str) -> KetQuaGiai:
    job_id = job["id"]
    profile_url = job["url"]
    if cookies_path:
        # Cookie phiên MẤT khi đóng context (đo #3) ⇒ nạp lại từ jar của chủ job mỗi lượt mở.
        ctx.add_cookies(scraper._load_cookies(Path(cookies_path)))
    # Context persistent mở sẵn một tab about:blank: dùng nó, để `len(ctx.pages) == 1`.
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    trang_moi = _DongTrangMoi()
    ctx.on("page", trang_moi)
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
    except scraper.PWTimeout:
        log.warning("[giai] job %s: mở trang quá giờ", job_id)
        return _cho_xac_minh(gc.LD_MO_TRANG_TRUOT)
    # Đường dẫn tham chiếu = `page.url` SAU goto (redirect tiktok.com → www.).
    ref_url = page.url
    cdp = ctx.new_cdp_session(page)
    frame_id = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    guard = GacDieuHuong(cdp, phien, ref_url, frame_id, che_do)
    guard.bat()                       # Fetch SAU goto, TRƯỚC startScreencast
    _bat_khung(cdp, phien, guard)

    # Khung đầu hợp lệ về mới sang `dang_giai` (đồng hồ 5 phút chỉ chạy từ đó).
    han_khung = gc.dong_ho() + gc.CHO_KHUNG_DAU_GIAY
    while phien.lay_khung() is None:
        if guard.trang_la:
            return _cho_xac_minh(gc.LD_ROI_MIEN)
        if gc.dong_ho() >= han_khung:
            return _cho_xac_minh(gc.LD_KHONG_CO_KHUNG)
        page.wait_for_timeout(50)
    if not mgc.chuyen_trang_thai(db_path, job_id, "dang_mo", "dang_giai"):
        return _cho_xac_minh("trang_thai_doi")
    con_lai = gc.con_lai_tu_moc(mgc.vao_luc(db_path, job_id), gc.CUA_SO_GIAI_GIAY)
    phien.dat_trang_thai("dang_giai", con_lai)

    ket, ly_do = _vong_giai(page, cdp, phien, guard, profile_url, gc.dong_ho() + con_lai)
    log.info("[giai] job %s: vòng giải kết thúc (%s) — tre_qua_D=%d tre_phat_worker=%d D=%d ms "
             "gesture_bo_do=%d tai_lai=%d trang_moi_dong=%d chan_dieu_huong=%d", job_id, ly_do or ket,
             phien.tre_qua_d_tong(), phien.tre_phat_worker_tong(), phien.d_ms,
             phien.so_gesture_bo_do, phien.so_lan_tai_lai,
             trang_moi.so_dong, guard.so_chan)
    if ket == "dung":
        return KetQuaGiai(LOAI_FAILED, gc.LD_DUNG_KHONG_CAPTCHA)
    if ket == "da_giai":
        return _quet_sau_giai(page, cdp, guard, phien, db_path, job, profile_url,
                              max_videos=int(job.get("tong") or 1))
    return _cho_xac_minh(ly_do or gc.LD_LOI_TRINH_DUYET)


def _dong_ctx(ctx, browser, profile_path: Path, dang_loi: bool) -> None:
    """Đóng context/browser rồi nhả khoá profile. Lỗi đóng (`Exception`) chỉ LOG, không ném:
    `_chay` gọi hàm này ở `finally`, nên lúc đó hoặc đã có lỗi gốc đang bay (`dang_loi` — lỗi
    đóng không được đè nó), hoặc `_phien_tren_ctx` đã trả kết quả — ném ở đây là vứt kết quả
    đó: job đã sang `running` với link trong tay bị `chay_luot_giai` kéo về `cho_xac_minh`."""
    try:
        try:
            ctx.close()
            if browser is not None:
                browser.close()
        except Exception as loi_dong:  # noqa: BLE001
            log.warning("[giai] đóng context lỗi %s (%s: %s) — %s",
                        "sau lỗi gốc" if dang_loi else "sau khi đã có kết quả",
                        type(loi_dong).__name__, loi_dong,
                        "giữ lỗi gốc" if dang_loi else "giữ kết quả")
    finally:
        scraper._nha_profile_dir(profile_path)


def _chay(db_path: Path, job: dict, phien: gc.PhienGiai, cookies_path: str | None,
          headless: bool, user_agent: str, che_do: str) -> KetQuaGiai:
    job_id = job["id"]
    profile_path = profile_theo_job.chuan_bi_profile_job(db_path, job_id)
    # Chỉ mở trình duyệt khi có người giữ khoá (popup mở SSE ngay sau khi bấm nút; chờ ngắn để
    # khỏi chạy đua giữa "worker nhặt job" và "popup nối xong").
    if not phien.cho_nguoi_giu(gc.CHO_NGUOI_XEM_GIAY, ngu):
        return _cho_xac_minh(gc.LD_KHONG_AI_XEM)
    with scraper.sync_playwright() as pw:
        browser, ctx = scraper._open_context(pw, headless=headless, proxy=None,
                                             profile_dir=profile_path, user_agent=user_agent)
        dang_loi = False
        try:
            return _phien_tren_ctx(ctx, db_path, job, phien, cookies_path, che_do)
        except BaseException:
            dang_loi = True
            raise
        finally:
            _dong_ctx(ctx, browser, profile_path, dang_loi)


def chay_luot_giai(db_path: Path, job: dict, cookies_path: str | None, *,
                   headless: bool = True, user_agent: str | None = None) -> KetQuaGiai:
    """Chạy một lượt giải cho job vừa được nhặt ở `dang_mo`. Lỗi trong lượt giải (`_chay`) được quy
    về `cho_xac_minh`, không ném. CÓ ném: lỗi đọc/ghi DB (`chon_ua_job`, ghi trạng thái) và mọi
    `BaseException` — người gọi (`process_job`) đưa job về `cho_xac_minh`/`interrupted`. Phiên RAM
    luôn được đóng và bỏ khỏi sổ, kể cả khi ném.

    Trả `KetQuaGiai`: `refs` (đã sang `running`, người gọi tải tiếp) hoặc job đã được đưa về
    `cho_xac_minh` / `failed` (người gọi dừng)."""
    job_id = job["id"]
    phien = gc.lay_hoac_tao_phien(job_id, job["nguoi_tao"], "dang_mo", worker_giu=True)
    phien.dat_trang_thai("dang_mo")
    # `kq is None` trong `finally` ⇔ một lỗi đang bay ra TRƯỚC khi có kết quả. Hai nguồn: `Exception`
    # từ `chon_ua_job` (DB) — trước đây nằm ngoài try nên phiên sót trong sổ với `worker_giu` —, và
    # `BaseException` đi xuyên `_chay` (`_chay` đã đặt `dang_loi`, đóng ctx — lỗi đóng chỉ log — và
    # nhả khoá profile rồi ném lại). Ở đây chỉ dọn RAM (đóng phiên ⇒ popup nhận `ket_thuc`, bỏ khỏi
    # sổ); trạng thái DB do `queue.process_job` ghi.
    kq: KetQuaGiai | None = None
    try:
        ua = user_agent or models.chon_ua_job(db_path, job_id, scraper.random_user_agent)
        try:
            kq = _chay(db_path, job, phien, cookies_path, headless, ua, gc.che_do_dieu_huong())
        except Exception as exc:  # noqa: BLE001 — L13: lỗi trong `dang_*` ⇒ cho_xac_minh, luồng worker sống
            log.warning("[giai] job %s: lỗi trong lượt giải (%s) — về cho_xac_minh", job_id,
                        type(exc).__name__, exc_info=True)
            kq = _cho_xac_minh(gc.LD_LOI_TRINH_DUYET)
        if kq.loai == LOAI_CHO_XAC_MINH:
            if not mgc.chuyen_trang_thai(db_path, job_id, ("dang_mo", "dang_giai", "running"),
                                         "cho_xac_minh", ly_do=kq.ly_do):
                log.warning("job %s: không chuyển được về cho_xac_minh (trạng thái đã đổi)", job_id)
        elif kq.loai == LOAI_FAILED:
            mgc.chuyen_trang_thai(db_path, job_id, ("dang_mo", "dang_giai"), "failed", ly_do=kq.ly_do)
    finally:
        try:
            if kq is None:
                phien.dong(LOAI_CHO_XAC_MINH, gc.LD_LOI_TRINH_DUYET)
            elif kq.loai != LOAI_REFS:
                phien.dong(kq.loai, kq.ly_do)
        finally:
            gc.bo_phien(job_id, phien)
    return kq
