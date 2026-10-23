"""Tải ảnh bìa ứng viên từ CDN TikTok (URL ký sẵn, lấy từ DOM). GĐ1: 70/70 lượt HTTP 200 với UA trình duyệt, giãn 10 s.

Lỗi tải ⇒ ứng viên bị bỏ kèm lý do, không thay bằng ảnh khác.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
BYTE_TOI_THIEU = 1024   # dưới mức này là trang lỗi/ảnh rỗng, không phải ảnh bìa


def _get(url: str) -> requests.Response:
    """Đường nối mạng duy nhất; test thay hàm này."""
    return requests.get(url, headers={"User-Agent": UA}, timeout=20)


def tai_anh_bia(ds: list[tuple[str, str]], thu_muc: Path, gian_cach: float) -> tuple[dict[str, Path], dict[str, str]]:
    """`ds` = [(video_id, cover_url)]. Trả ({video_id: file}, {video_id: lý do lỗi})."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    tot: dict[str, Path] = {}
    loi: dict[str, str] = {}
    for i, (vid, url) in enumerate(ds):
        if i and gian_cach > 0:
            time.sleep(gian_cach)
        try:
            r = _get(url)
        except requests.RequestException as exc:
            loi[vid] = f"loi mang: {type(exc).__name__}"
            continue
        if r.status_code != 200 or len(r.content) < BYTE_TOI_THIEU:
            loi[vid] = f"http {r.status_code}, {len(r.content)} byte"
            continue
        p = thu_muc / f"{vid}.jpg"
        p.write_bytes(r.content)
        tot[vid] = p
    return tot, loi
