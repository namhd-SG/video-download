"""Mã dừng `fb_chan_dang_nhap` đã nối đủ các bảng: `utils`, `_LY_DO_RONG_LA_LOI`, `bao-thieu.js::NHAN_THEO_LY_DO` (KHÔNG có
trong `MA_CHAY_LAI_DUOC`), `stop-reason-text.js`, nhãn thẻ gọn, ví dụ nguồn ở trang Hướng dẫn. JS chạy bằng node thật
(SKIP khi máy không có node), giống `tests/js/*.js` còn lại."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tiktok_music_downloader import utils as utils_mod
from web import queue as queue_mod

RAI = Path(__file__).resolve().parent
STATIC = RAI.parent / "web" / "static"


def _doc(ten: str) -> str:
    return (STATIC / ten).read_text(encoding="utf-8")


def _node(*args) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    r = subprocess.run([node, *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_ma_dung_trong_utils_va_ly_do_rong_la_loi():
    """ĐỘT BIẾN (iii): bỏ `STOP_FB_CHAN_DANG_NHAP` khỏi `_LY_DO_RONG_LA_LOI` ⇒ ĐỎ."""
    assert utils_mod.STOP_FB_CHAN_DANG_NHAP == "fb_chan_dang_nhap"
    assert "fb_chan_dang_nhap" in queue_mod._LY_DO_RONG_LA_LOI


def test_nhan_thieu_ca_bat_buoc_16_tren_30_tuong_dang_nhap_khac_null():
    """ĐỘT BIẾN (iii): bỏ `fb_chan_dang_nhap` khỏi `NHAN_THEO_LY_DO` ⇒ `nhanThieu(...)` về null ⇒ ĐỎ."""
    ra = json.loads(_node(str(RAI / "js" / "nhan-thieu-fb.js"), str(STATIC / "bao-thieu.js")))
    assert ra["nhan_tuong"] is not None and ra["nhan_tuong"]["lop"] == "thieu"
    assert "đăng nhập" in ra["nhan_tuong"]["chu"]
    assert ra["nhan_du_so"] is not None
    assert ra["nhan_khong_ma"] is None
    assert ra["chay_lai"] is None                      # chạy lại vô ích: KHÔNG có nút


def test_khong_co_trong_ma_chay_lai_duoc_va_co_trong_nhan_theo_ly_do():
    js = _doc("bao-thieu.js")
    chay_lai = re.search(r"MA_CHAY_LAI_DUOC = new Set\(\[(.*?)\]\)", js, re.S).group(1)
    nhan = re.search(r"NHAN_THEO_LY_DO = Object.freeze\(\{(.*?)\}\)", js, re.S).group(1)
    assert "fb_chan_dang_nhap" not in chay_lai and re.search(r"\bfb_chan_dang_nhap:", nhan)


def test_cau_giai_thich_va_nhan_the_gon_co_ma():
    ra = json.loads(_node("-e", (
        "global.window={};"
        "const s=require('fs').readFileSync(process.argv[1],'utf8');"
        "eval(s.replace('const STOP_REASON_TEXT','globalThis.STOP_REASON_TEXT'));"
        "console.log(JSON.stringify({t:STOP_REASON_TEXT.fb_chan_dang_nhap,e:STOP_REASON_TEXT.source_empty}));"),
        str(STATIC / "stop-reason-text.js")))
    assert "Facebook" in ra["t"] and "cookie" in ra["t"]
    assert "hoặc nền tảng ẩn tab này khi chưa đăng nhập" in ra["e"]                  # vế thêm cho `source_empty`
    assert re.search(r"\bfb_chan_dang_nhap:", _doc("the-luot-gon.js"))


def test_vi_du_nguon_facebook_trang_o_trang_huong_dan():
    assert re.search(r"\bfacebook_trang:", _doc("huong-dan.js"))
    assert 'data-tran="video_trang_facebook"' in _doc("huong-dan.html")
