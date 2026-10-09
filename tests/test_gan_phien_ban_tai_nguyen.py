"""`?v=<băm nội dung>` trên mọi .css/.js nội bộ của các trang HTML.

Ca thật 09/10: sau deploy #72, trình duyệt member nhận `thay-logo.html` mới mà `thay-logo.css` cũ (không request nào
tới origin) ⇒ tab "Dán link Drive" mất kiểu. URL đổi theo nội dung là cách duy nhất không phụ thuộc tầng cache.
"""
from __future__ import annotations

import hashlib
import os
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from fastapi import FastAPI  # noqa: E402
from test_thay_logo_relay import _Client  # noqa: E402
from thay_logo_may_chu import MayChu  # noqa: E402

from web import app as app_mod  # noqa: E402
from web import gan_phien_ban_tai_nguyen as gpb  # noqa: E402

_TAG = re.compile(r'<(?:link|script)\b[^>]*\b(?:href|src)="([^"]+)"')
_NGOAI = re.compile(r"^(?:[a-z]+:|//)")


def _bam(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:gpb.DO_DAI_BAM]


@pytest.fixture(scope="module")
def tinh():
    """Mount tĩnh THẬT của app (cùng lớp, cùng thư mục) dựng riêng — không chạy lifespan/worker của app chính."""
    mount = next(r for r in app_mod.app.routes if getattr(r, "name", "") == "static")
    app = FastAPI()
    app.mount("/", mount.app, name="static")
    mc = MayChu(app)
    yield _Client(mc)
    mc.dung()


def test_app_dung_lop_tinh_co_phien_ban():
    """ĐỘT BIẾN: trả `app.mount` về `StaticFiles` thường ⇒ ĐỎ (và các test qua `tinh` cũng đỏ)."""
    mount = next(r for r in app_mod.app.routes if getattr(r, "name", "") == "static")
    assert isinstance(mount.app, gpb.StaticCoPhienBan)
    assert os.path.samefile(mount.app.directory, app_mod.STATIC_DIR)


def test_chi_gan_cho_tai_nguyen_noi_bo_co_that(tmp_path):
    (tmp_path / "a.css").write_bytes(b"body{}")
    (tmp_path / "b.js").write_bytes(b"1")
    html = ('<link rel="stylesheet" href="a.css" />'
            '<link rel="stylesheet" href="/a.css" />'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X" />'
            '<script src="//cdn.example.com/b.js"></script>'
            '<script src="b.js"></script>'
            '<script src="khong-co.js"></script>'
            '<script src="b.js?v=cu"></script>'
            '<script src="../ngoai.js"></script>')
    ra = gpb.gan_phien_ban(html, tmp_path)
    assert f'href="a.css?v={_bam(b"body{}")}"' in ra
    assert f'href="/a.css?v={_bam(b"body{}")}"' in ra
    assert f'src="b.js?v={_bam(b"1")}"' in ra
    # CDN / không có file / đã có query / thoát thư mục: giữ NGUYÊN chữ
    for giu in ('href="https://fonts.googleapis.com/css2?family=X"', 'src="//cdn.example.com/b.js"',
                'src="khong-co.js"', 'src="b.js?v=cu"', 'src="../ngoai.js"'):
        assert giu in ra, giu


def test_doi_noi_dung_thi_v_doi(tmp_path):
    f = tmp_path / "a.css"
    f.write_bytes(b"cu")
    truoc = gpb.gan_phien_ban('<link href="a.css">', tmp_path)
    f.write_bytes(b"moi")
    sau = gpb.gan_phien_ban('<link href="a.css">', tmp_path)
    assert truoc != sau and f"?v={_bam(b'moi')}" in sau


@pytest.mark.parametrize("duong,ten", [("/", "index.html"), *[(f"/{t}", t) for t in gpb.TRANG_GAN_PHIEN_BAN]])
def test_trang_that_qua_mount_moi_css_js_noi_bo_deu_co_v(tinh, duong, ten):
    """ĐỘT BIẾN: `StaticCoPhienBan.get_response` gọi thẳng `super()` (bỏ viết lại) ⇒ ĐỎ."""
    r = tinh.get(duong)
    assert r.status_code == 200
    ra = r.content.decode()
    tat_ca = _TAG.findall(ra)
    noi_bo = [u for u in tat_ca if not _NGOAI.match(u) and re.search(r"\.(?:css|js)(?:\?|$)", u)]
    assert noi_bo, f"{ten}: không thấy tài nguyên nội bộ nào — mẫu tìm sai?"
    for u in noi_bo:
        ten_tep, _, q = u.partition("?")
        assert q == f"v={gpb.bam_tep(app_mod.STATIC_DIR / ten_tep.lstrip('/'))}", (ten, u)
    goc = (app_mod.STATIC_DIR / ten).read_text(encoding="utf-8")
    assert [u for u in tat_ca if _NGOAI.match(u)] == [u for u in _TAG.findall(goc) if _NGOAI.match(u)]  # CDN giữ nguyên


def test_thay_logo_html_tro_dung_css_va_tab_link(tinh):
    ra = tinh.get("/thay-logo.html").content.decode()
    assert re.search(r'href="thay-logo\.css\?v=[0-9a-f]{10}"', ra)
    assert re.search(r'src="thay-logo-tab-link\.js\?v=[0-9a-f]{10}"', ra)


def test_trinh_duyet_giu_html_cu_van_nhan_ban_moi_khong_304(tinh):
    """Ca thật: trình duyệt giữ HTML cũ gửi If-None-Match = ETag file trên đĩa. 304 ⇒ nó tiếp tục dùng HTML cũ (không ?v).
    ĐỘT BIẾN: trang đi qua `super().get_response` ⇒ 304 ⇒ ĐỎ."""
    import email.utils
    tep = app_mod.STATIC_DIR / "thay-logo.html"
    st = tep.stat()
    etag = '"' + hashlib.md5(f"{st.st_mtime}-{st.st_size}".encode(), usedforsecurity=False).hexdigest() + '"'
    hdr = {"if-none-match": etag, "if-modified-since": email.utils.formatdate(st.st_mtime + 60, usegmt=True)}
    r = tinh.get("/thay-logo.html", headers=hdr)
    assert r.status_code == 200 and b"thay-logo.css?v=" in r.content
    # đối chứng: một file KHÔNG thuộc danh sách trang vẫn đi nhánh tĩnh thường (có 304) — chứng minh header trên có hiệu lực
    css = app_mod.STATIC_DIR / "thay-logo.css"
    sc = css.stat()
    etag_css = '"' + hashlib.md5(f"{sc.st_mtime}-{sc.st_size}".encode(), usedforsecurity=False).hexdigest() + '"'
    assert tinh.get("/thay-logo.css", headers={"if-none-match": etag_css}).status_code == 304


def test_url_kem_v_phuc_vu_dung_file(tinh):
    """URL có ?v phải ra đúng file (StaticFiles bỏ query) — nếu không, gắn ?v là làm vỡ trang."""
    r = tinh.get("/thay-logo.css?v=0123456789")
    assert r.status_code == 200 and r.content == (app_mod.STATIC_DIR / "thay-logo.css").read_bytes()
