"""Tải ảnh bìa: thành công / HTTP lỗi / ảnh rỗng / lỗi mạng. Mạng được thay bằng giả."""
from __future__ import annotations

import requests

from tiktok_music_downloader.tim_trend import anh_bia


class _R:
    def __init__(self, code, content):
        self.status_code, self.content = code, content


def test_tai_anh_bia(tmp_path, monkeypatch):
    tra = {"u1": _R(200, b"x" * 5000), "u2": _R(403, b"cf"), "u3": _R(200, b"tiny")}

    def gia(url):
        if url == "u4":
            raise requests.ConnectionError("dut")
        return tra[url]

    monkeypatch.setattr(anh_bia, "_get", gia)
    monkeypatch.setattr(anh_bia.time, "sleep", lambda s: None)
    tot, loi = anh_bia.tai_anh_bia([("1", "u1"), ("2", "u2"), ("3", "u3"), ("4", "u4")], tmp_path, gian_cach=10)
    assert set(tot) == {"1"} and tot["1"].read_bytes() == b"x" * 5000
    assert loi == {"2": "http 403, 2 byte", "3": "http 200, 4 byte", "4": "loi mang: ConnectionError"}
