"""Tìm video TikTok bằng Chrome CÓ CỬA SỔ (Playwright `channel="chrome"`), đọc DOM: link + ảnh bìa + caption.

Pha 0 (22/10, máy dev, không cookie): có cửa sổ ⇒ 24/53/17/24 link, headless ⇒ 0 kể cả hâm phiên ⇒ BẮT BUỘC có cửa sổ.
Hâm phiên (mở lại 1 lần trong cùng context khi lượt đầu rỗng, như `scraper.py:509`) cần thật: "kolase 7 pose" 0 → 17.
Ngân sách đếm theo LẦN MỞ TRANG, gồm lượt hâm (Pha 0 vượt 7/6 vì đếm theo kịch bản).
Cửa sổ bật lên màn hình máy dev ⇒ in báo trước khi mở, và luôn đóng trong `finally` (ĐP 22/10).
"""
from __future__ import annotations

import shutil
import tempfile
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils import parse_video_url
from .truy_van import TruyVan

DOC_DOM = """() => { const out = []; const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/video/"]')) {
    if (seen.has(a.href)) continue;
    const img = a.querySelector('img'); if (!img || !img.src) continue;
    seen.add(a.href);
    let c = a; for (let i = 0; i < 4 && c.parentElement; i++) c = c.parentElement;
    out.push({url: a.href, cover: img.src, caption: (img.alt || c.innerText || '').replace(/\\s+/g, ' ').slice(0, 300)});
  }
  const chu = document.body ? document.body.innerText.slice(0, 5000) : '';
  const hop = !!document.querySelector('#captcha_close_button, [id^="captcha"], [class*="captcha_verify"], [class*="cap-flex"]');
  return {items: out, chu: chu, hop_captcha: hop}; }"""
# Pha 4 22/10: TikTok bật captcha xoay ảnh "Drag the slider to fit the puzzle" trên trang search ⇒ lưới video không bao giờ
# tải; công cụ cũ thấy "0 link" rồi đốt hết 12/12 lượt. Gặp captcha ⇒ dừng cả lần chạy NGAY (mở thêm chỉ làm nặng cờ IP).
# Chỉ cụm ĐẶC HIỆU của hộp captcha — không dùng chữ "captcha" trần: caption video có thể chứa nó (review 23/10 L2).
DAU_CAPTCHA = ("drag the slider to fit the puzzle", "fit the puzzle", "verify to continue")


def la_captcha(chu_trang: str, co_hop_captcha: bool = False) -> bool:
    """Trang đang hiện hộp captcha TikTok: có phần tử hộp captcha, hoặc chữ hiển thị có cụm đặc hiệu của nó."""
    chu = chu_trang.lower()
    return co_hop_captcha or any(d in chu for d in DAU_CAPTCHA)
CHO_LINK_MS = 15_000
GIAY_DOI_KIEM = 2   # chu kỳ đọc lại trang khi chờ người giải captcha
SO_LAN_CUON = 6     # đủ phủ ~24 thẻ của 1 trang kết quả ở cửa sổ 1280×900


@dataclass(frozen=True)
class UngVien:
    url: str
    video_id: str
    cover_url: str
    caption: str
    tac_gia: str
    truy_van: str


class HetLuot(RuntimeError):
    """Đã dùng hết ngân sách lần mở trang TikTok cho lần chạy này."""


class LoiMoTrang(HetLuot):
    """Mở/đọc trang lỗi (timeout, trình duyệt đóng…): dừng sạch như hết lượt, giữ kết quả các hop trước."""


class BiCaptcha(HetLuot):
    """TikTok hỏi captcha: dừng như hết lượt, nhưng ghi rõ lý do để người chạy biết phải để IP nguội / tự giải."""


def url_cua(tv: TruyVan) -> str:
    if tv.loai == "tag":
        return "https://www.tiktok.com/tag/" + urllib.parse.quote(tv.text.lstrip("#").replace(" ", ""), safe="")
    return "https://www.tiktok.com/search/video?q=" + urllib.parse.quote(tv.text)


def tu_dom(muc: list[dict], truy_van: str) -> list[UngVien]:
    """Mục DOM ⇒ ứng viên. Chỉ giữ link `/@<handle>/video/<id>` (hợp đồng `links.txt` ĐK1), bỏ trùng id."""
    ra: list[UngVien] = []
    da: set[str] = set()
    for m in muc:
        url = str(m.get("url", "")).split("?")[0]
        ref = parse_video_url(url)
        cover = str(m.get("cover") or "")
        if ref is None or ref.video_id in da or not cover.startswith(("http://", "https://")):
            continue   # ảnh giữ chỗ `data:` (chưa tải lười) ⇒ không tải được; thẻ đó coi như chưa đọc
        da.add(ref.video_id)
        tac_gia = url.split("/@", 1)[1].split("/", 1)[0] if "/@" in url else ""
        ra.append(UngVien(url, ref.video_id, cover, str(m.get("caption", "")), tac_gia, truy_van))
    return ra


class ChromeTim:
    """Dùng trong `with`: mở MỘT cửa sổ Chrome cho cả lần chạy, đóng khi ra khỏi khối (kể cả khi lỗi)."""

    def __init__(self, tran_luot: int, gian_cach: float, bao: Callable[[str], None] = lambda s: print(s, flush=True),
                 chan_doan: Path | None = None, profile_ben: Path | None = None, cho_giai_giay: int = 0):
        """`profile_ben`: thư mục profile Chrome dùng lại giữa các lần chạy (cookie sau khi người giải captcha còn giữ);
        None = profile trắng mỗi lần (mặc định). `cho_giai_giay` > 0: gặp captcha thì CHỜ người giải trong cửa sổ tối đa
        bấy nhiêu giây rồi mới dừng; 0 = dừng ngay (mặc định). Cả hai mặc định TẮT — chờ user chọn (ĐP 23/10)."""
        self.tran_luot = tran_luot
        self.profile_ben = profile_ben
        self.cho_giai_giay = cho_giai_giay
        self.chan_doan = chan_doan   # thư mục chụp màn hình khi feed rỗng (bằng chứng: trang chặn, captcha, hay rỗng thật)
        self.gian_cach = gian_cach
        self.bao = bao
        self.da_mo = 0
        self._lan_cuoi = 0.0
        self._pw = self._ctx = self._page = None
        self._profile_tam: str | None = None   # profile trắng của lần chạy: xoá khi đóng (cookie TikTok không nằm lại)

    def __enter__(self) -> "ChromeTim":
        from playwright.sync_api import sync_playwright
        self.bao("⚠ Sắp mở 1 cửa sổ Chrome để tìm trên TikTok (tự đóng khi xong). Đừng đóng tay giữa chừng.")
        self._pw = sync_playwright().start()
        try:
            if self.profile_ben is not None:
                self.profile_ben.mkdir(parents=True, exist_ok=True)
            if self.profile_ben is None:
                self._profile_tam = tempfile.mkdtemp(prefix="tim-trend-")
            thu_muc = str(self.profile_ben) if self.profile_ben is not None else self._profile_tam
            self._ctx = self._pw.chromium.launch_persistent_context(
                thu_muc, channel="chrome", headless=False,
                viewport={"width": 1280, "height": 900}, args=["--window-position=0,0"])
            self._page = self._ctx.new_page()
        except Exception:
            self._dong()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._dong()

    def _dong(self) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._ctx = self._pw = self._page = None
            if self._profile_tam is not None:
                shutil.rmtree(self._profile_tam, ignore_errors=True)
                self._profile_tam = None

    def _mo(self, url: str) -> list[dict]:
        if self.da_mo >= self.tran_luot:
            raise HetLuot(f"đã mở {self.da_mo}/{self.tran_luot} trang TikTok")
        cho = self.gian_cach - (time.monotonic() - self._lan_cuoi)
        if self._lan_cuoi and cho > 0:
            time.sleep(cho)
        self.da_mo += 1   # đếm TRƯỚC: lượt goto lỗi vẫn là 1 request TikTok đã gửi
        self._lan_cuoi = time.monotonic()
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                self._page.wait_for_selector('a[href*="/video/"]', timeout=CHO_LINK_MS)
            except Exception:
                pass
            self._cuon_cho_anh()
            ket_qua = self._page.evaluate(DOC_DOM)
        except Exception as exc:
            raise LoiMoTrang(f"mở/đọc trang lỗi ở lần thứ {self.da_mo} ({type(exc).__name__})") from exc
        if la_captcha(str(ket_qua.get("chu", "")), bool(ket_qua.get("hop_captcha"))):
            self._chup(f"captcha-{self.da_mo:02d}.png")
            ket_qua = self._cho_nguoi_giai(url)
        return ket_qua["items"]

    def _cuon_cho_anh(self) -> None:
        """TikTok tải ảnh bìa lười: thẻ chưa cuộn tới có `img.src` = ảnh giữ chỗ `data:` ⇒ Pha 4 23/10 mất 88/181 và
        109/220 ứng viên (InvalidSchema lúc tải). Cuộn hết trang rồi về đầu để ảnh thật kịp gắn; không mở thêm request trang."""
        for _ in range(SO_LAN_CUON):
            self._page.mouse.wheel(0, 1600)
            self._page.wait_for_timeout(700)
        self._page.wait_for_timeout(1500)

    def _cho_nguoi_giai(self, url: str) -> dict:
        """Chờ NGƯỜI giải captcha trong cửa sổ (không tự giải, không mở trang mới, không tốn lượt mở trang).
        Hết giờ hoặc chế độ tắt ⇒ BiCaptcha."""
        ly_do = f"TikTok hỏi captcha ở lần mở trang thứ {self.da_mo} ({url})"
        if self.cho_giai_giay <= 0:
            raise BiCaptcha(ly_do)
        self.bao(f"⚠ TikTok hỏi captcha. Hãy GIẢI TRONG CỬA SỔ CHROME đang mở — chờ tối đa {self.cho_giai_giay} giây.")
        han = time.monotonic() + self.cho_giai_giay
        while time.monotonic() < han:
            time.sleep(GIAY_DOI_KIEM)
            try:
                ket_qua = self._page.evaluate(DOC_DOM)
            except Exception:   # người giải xong ⇒ trang tự tải lại ⇒ "context destroyed": đọc lại ở vòng sau
                continue
            if not la_captcha(str(ket_qua.get("chu", "")), bool(ket_qua.get("hop_captcha"))):
                self.bao("✓ Captcha đã qua, chạy tiếp.")
                if not ket_qua["items"]:   # giải xong lưới chưa kịp tải ⇒ đọc lại 1 lần, không mở trang mới
                    self._page.wait_for_timeout(3000)
                    ket_qua = self._page.evaluate(DOC_DOM)
                return ket_qua
        raise BiCaptcha(ly_do + f"; không ai giải trong {self.cho_giai_giay} giây")

    def _chup(self, ten: str) -> str:
        if self.chan_doan is None:
            return ""
        self.chan_doan.mkdir(parents=True, exist_ok=True)
        try:
            self._page.screenshot(path=str(self.chan_doan / ten))
            return ten
        except Exception as exc:   # chụp hỏng không được làm hỏng lần chạy
            return f"khong chup duoc ({type(exc).__name__})"

    def tim(self, tv: TruyVan) -> tuple[list[UngVien], str]:
        """Trả (ứng viên, ghi chú). Rỗng sau hâm phiên ⇒ ghi chú 'feed rỗng' — không coi là 'không có video'."""
        url = url_cua(tv)
        muc = self._mo(url)
        ghi_chu = ""
        if len(muc) <= 1:
            muc = self._mo(url)
            ghi_chu = "ham phien"
        ra = tu_dom(muc, tv.text)
        if not ra:
            ghi_chu = (ghi_chu + "; " if ghi_chu else "") + "feed rong sau ham phien"
            anh = self._chup(f"rong-{self.da_mo:02d}.png")
            if anh:
                ghi_chu += f"; anh {anh}"
        return ra, ghi_chu
