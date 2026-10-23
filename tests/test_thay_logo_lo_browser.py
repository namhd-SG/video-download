"""Màn Lô (pha 1b bước 2) trên trình duyệt THẬT (Chromium, chặn mạng ngoài): xếp 4 nhóm theo trạng thái máy, dải màu theo `/dai`,
lưới ảnh soi chỉ tải khi bấm, xác nhận "không có logo" bằng bỏ qua (hoàn tác được).

Dữ liệu mồi một lô đủ 4 nhóm + video máy còn làm / lỗi + một lượt của người khác (không được hiện).
Ảnh chụp ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt (lo-1280.png, lo-soi-nhanh-1280.png)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from tiktok_music_downloader.thay_logo import hang_doi, khoanh, nhat_ky

NGUOI, NGUOI_KHAC = "thaylogo@dev.local", "nguoikhac@dev.local"
SO_KHUNG, FPS, KHO = 60, 30.0, (64, 96)
BOX = {"x": 20, "y": 60, "w": 30, "h": 10}

# ten: (trang_thai job, so_box mồi, [(trạng thái vết, [(khung, state, de_khi_biet)])], so_khung trong nhật ký)
# Đoạn đỏ = khung không đè trong đời một vết RENDER; vàng = đè khi biết. `/dai` chỉ tính vết render (khoanh.py dai_thoi_gian).
CA = {
    "A-hai-cho": ("xong", 3, [("render", [(5, "detected", False), (6, "hidden_sub", False), (7, "hidden_sub", False),
                                          (8, "detected", False), (30, "detected", True), (31, "filled", False), (59, "detected", False)])], SO_KHUNG),
    # video DÀI (3000 khung trong nhật ký): đoạn vàng 1 khung = 0,03% dải ⇒ chỉ thấy được nhờ bề rộng tối thiểu
    "A-mot-cho": ("xong", 2, [("render", [(0, "detected", False), (1500, "detected", True), (2999, "detected", False)])], 3000),
    # ca thật job 4 trên prod: một vết render CÓ chỗ hở (⇒ /dai trả đoạn đỏ) + một vết bị bỏ ⇒ cho_nguoi. Dải vẫn phải xám, 0 đoạn.
    "B-khong-chac": ("cho_nguoi", 2, [("render", [(10, "detected", False), (11, "hidden_sub", False), (20, "detected", False)]),
                                      ("cho_nguoi", [(40, "detected", False)])], SO_KHUNG),
    "B-thay-khong-bam": ("cho_nguoi", 3, [], SO_KHUNG),  # agy thấy box nhưng 0 vết ⇒ vẫn B (máy BIẾT có logo), không phải D
    "C-chac-1": ("xong", 2, [("render", [(0, "detected", False), (30, "filled", False), (59, "detected", False)])], SO_KHUNG),
    "C-chac-2": ("xong", 2, [("render", [(2, "detected", False), (50, "detected", False)])], SO_KHUNG),
    "D-khong-logo": ("cho_nguoi", 0, [], SO_KHUNG),
}
LY_DO = {"B-khong-chac": "1/2 watermark không tự thay được: [cụm 1, 2 box] logo nhảy loạn giữa các cảnh",
         "B-thay-khong-bam": "không có box mồi nào dùng được", "D-khong-logo": "không có box mồi nào dùng được"}


def _video(p: Path, sang_tu=0):
    import cv2
    import numpy as np
    p.parent.mkdir(parents=True, exist_ok=True)
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), FPS, KHO)
    for i in range(SO_KHUNG):
        out.write(np.full((KHO[1], KHO[0], 3), (sang_tu + i * 3) % 255, np.uint8))
    out.release()


def seed_lo(data: Path) -> dict:
    """Tạo lô "Lô thử" đủ 4 nhóm. Trả {ten: tl_job_video.id} + "_job" + "_khac" (video người khác)."""
    conn = nhat_ky.mo(data / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    ten = list(CA) + ["E-dang-chay", "F-loi"]
    job = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": f"SRC{i:02d}" + "x" * 12} for i in range(len(ten))],
                           ten_bo="Lô thử")
    ids = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (job,))]
    out = {"_job": job}
    for i, (t, vid) in enumerate(zip(ten, ids)):
        out[t] = vid
        if t == "E-dang-chay":
            hang_doi.dat(conn, vid, "dang_chay")
            continue
        if t == "F-loi":
            hang_doi.dat(conn, vid, "loi", loi_text="Xử lý video bị lỗi.")
            continue
        tt, so_box, vets, so_khung = CA[t]
        log_id = nhat_ky.bat_dau_video(conn, nguon_video=f"v{i}")
        tp = data / f"track-{log_id}.json.gz"
        with gzip.open(tp, "wt") as f:
            json.dump([[{"frame": k, "state": s, **BOX, **({"de_khi_biet": True} if dk else {})} for k, s, dk in e] for _, e in vets], f)
        conn.execute("UPDATE tl_video SET kho=?, fps=?, so_khung=?, duong_dan_track=? WHERE id=?",
                     (f"{KHO[0]}x{KHO[1]}", FPS, so_khung, str(tp), log_id))
        if tt == "cho_nguoi":  # chuỗi lõi đúng khuôn duong_ong.KetQuaVideo.ly_do — trang đổi sang câu thường bằng T.lyDoDeHieu
            conn.execute("UPDATE tl_video SET loi_text=? WHERE id=?", (LY_DO[t], log_id))
        for k, (ttv, _) in enumerate(vets):
            conn.execute("INSERT INTO tl_vet (video_id, vet, trang_thai, pct_render) VALUES (?, ?, ?, 50)", (log_id, k, ttv))
        for b in range(so_box):
            conn.execute("INSERT INTO tl_box_moi (video_id, khung, x, y, w, h, nguon) VALUES (?,?,?,?,?,?,'agy')",
                         (log_id, b * 10, BOX["x"], BOX["y"], BOX["w"], BOX["h"]))
        conn.commit()
        _video(khoanh.duong_video(data, log_id, "goc"), sang_tu=10 * i)
        if tt == "xong":
            _video(khoanh.duong_video(data, log_id, "ra"), sang_tu=10 * i + 5)
        hang_doi.dat(conn, vid, tt, video_log_id=log_id)
    # "Lô cũ": video máy đã xong mà vết đã dọn (không đọc được /dai) + video còn đang chạy ⇒ không xếp nhóm được video nào
    jc = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": f"CU{i:02d}" + "x" * 14} for i in range(2)], ten_bo="Lô cũ")
    vc = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (jc,))]
    lc = nhat_ky.bat_dau_video(conn, nguon_video="cu")
    conn.execute("UPDATE tl_video SET kho=?, fps=?, so_khung=?, duong_dan_track=? WHERE id=?",
                 (f"{KHO[0]}x{KHO[1]}", FPS, SO_KHUNG, str(data / "track-da-don.json.gz"), lc))  # tệp không tồn tại
    conn.commit()
    hang_doi.dat(conn, vc[0], "xong", video_log_id=lc)
    hang_doi.dat(conn, vc[1], "dang_chay")
    out["_lo_cu"] = jc
    jk = hang_doi.tao_job(conn, NGUOI_KHAC, [{"kieu": "drive", "file_id": "KHAC" + "x" * 16}], ten_bo="Lô người khác")
    vk = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (jk,)).fetchone()[0]
    lk = nhat_ky.bat_dau_video(conn, nguon_video="khac")
    hang_doi.dat(conn, vk, "xong", video_log_id=lk)
    out["_khac"] = vk
    conn.close()
    return out


# ---------------------------------------------------------------- máy chủ + trình duyệt
import os  # noqa: E402
import socket  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang  # noqa: E402

from web import app as app_mod  # noqa: E402

_ID: dict = {}


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web import models
    from web.auth import require_user
    from tiktok_music_downloader.watermark import find_ffmpeg
    if find_ffmpeg() is None:
        pytest.skip("không có ffmpeg (ảnh soi dựng lười cần ffmpeg)")
    tmp = Path(tempfile.mkdtemp(prefix="videodl-thaylogo-lo-"))
    models.init_db(tmp / "jobs.db")
    _ID.update(seed_lo(tmp))
    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH", "COOKIES_DIR", "worker_thay_logo")}
    app_mod.DATA_DIR, app_mod.DB_PATH, app_mod.COOKIES_DIR = tmp, tmp / "jobs.db", tmp / "cookies"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", tmp
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)


@pytest.fixture
def trinh_duyet():
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch(args=ARGS_CHAN_MANG)
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    yield br
    br.close()
    pw.stop()


def _mo(br, goc, rong=1280):
    ctx = br.new_context(viewport={"width": rong, "height": 900})
    p = ctx.new_page()
    loi_js: list[str] = []
    yeu_cau: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    p.on("request", lambda r: yeu_cau.append(r.url))
    mo_trang(p, f"{goc}/thay-logo-lo.html?lo={_ID['_job']}", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelector('#lo-danh-sach .lo-dong') !== null")
    return p, loi_js, yeu_cau


def _chup(p, ten):
    p.evaluate("document.querySelectorAll('img').forEach(i => { i.loading = 'eager'; })")
    p.wait_for_function("[...document.images].every(i => i.complete)")
    d = os.environ.get("VIDEODL_ANH_THAY_LOGO")
    if d:
        Path(d).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(d) / ten), full_page=True)


def _dong(p):
    """[(vid, nhóm)] theo thứ tự hiển thị — dòng từng video và nút của nhóm gộp."""
    return p.evaluate("""[...document.querySelectorAll('#lo-danh-sach > .lo-dong')].map(r => [Number(r.dataset.vid), r.querySelector('.lo-nut').textContent])""")


# ---------------------------------------------------------------- xếp nhóm
def test_xep_nhom_theo_trang_thai_may_va_so_box(may_chu, trinh_duyet):
    goc, _ = may_chu
    p, loi_js, _ = _mo(trinh_duyet, goc)
    dong = _dong(p)
    # A: nhiều chỗ trước (2 chỗ rồi 1 chỗ) · B: 2 video so_box>0 — kể cả video 0 vết · không có video máy còn làm / lỗi / người khác
    assert dong == [[_ID["A-hai-cho"], "Xem 2 chỗ"], [_ID["A-mot-cho"], "Xem 1 chỗ"],
                    [_ID["B-thay-khong-bam"], "Khoanh logo"], [_ID["B-khong-chac"], "Khoanh logo"]], dong
    gop = p.evaluate("[...document.querySelectorAll('.lo-nhom .lo-dong-gop .lo-nut')].map(b => b.textContent)")
    assert gop == ["Soi nhanh 2 video", "Xác nhận 1 video"]
    tom = p.locator("#lo-tom-tat").inner_text()
    assert "cần bạn: 4 video, 3 chỗ" in tom and "máy còn làm 1 · lỗi 1" in tom and "9 video" in tom
    nut_sua = p.evaluate("[...document.querySelectorAll('#lo-danh-sach > .lo-dong > .lo-nut')].map(b => b.disabled && b.title.includes('bước sau'))")
    assert nut_sua == [True] * 4  # nút sang Sửa: mờ + chú thích (màn Sửa là bước sau)
    assert p.evaluate("[...document.querySelectorAll('.lo-dong-gop .lo-nut')].every(b => !b.disabled)")  # nút mở nhóm vẫn bấm được
    assert str(_ID["_khac"]) not in str(dong)
    ly_do = lambda k: p.locator(f'.lo-dong[data-vid="{_ID[k]}"] .lo-ten').inner_text()  # noqa: E731
    assert "Máy không tìm thấy logo cũ đủ rõ để bám theo." in ly_do("B-thay-khong-bam")
    assert "Logo cũ đổi chỗ liên tục" in ly_do("B-khong-chac") and "watermark" not in ly_do("B-khong-chac")  # không in chữ kỹ thuật
    _chup(p, "lo-1280.png")
    assert loi_js == []


def test_dai_mau_dung_vi_tri_va_cho_nguoi_xam_khong_to_doan(may_chu, trinh_duyet):
    goc, _ = may_chu
    p, _, _ = _mo(trinh_duyet, goc)
    doan = p.evaluate(f"""[...document.querySelectorAll('.lo-dong[data-vid="{_ID['A-hai-cho']}"] .lo-doan')].map(s => {{
        const d = s.parentElement.getBoundingClientRect(), r = s.getBoundingClientRect();
        return [s.classList.contains('lo-doan-do') ? 'do' : 'vang', +s.dataset.tu, +s.dataset.den, (r.left - d.left) / d.width]; }})""")
    assert [d[:3] for d in doan] == [["do", 6, 7], ["vang", 30, 30]]
    assert abs(doan[0][3] - 6 / SO_KHUNG) < 0.005 and abs(doan[1][3] - 30 / SO_KHUNG) < 0.005
    # đoạn 1 khung của video 3000 khung (0,03% dải, < 1 px) vẫn thấy: rộng ≥ 3 px
    assert p.evaluate(f"""document.querySelector('.lo-dong[data-vid="{_ID['A-mot-cho']}"] .lo-doan-vang').getBoundingClientRect().width""") >= 3
    # B-khong-chac: /dai CÓ đoạn đỏ (khung 11 trong vết render) — điều kiện để phép kiểm dưới phân định được — mà dải phải xám, 0 đoạn
    assert p.evaluate(f"fetch('/api/thay-logo/videos/{_ID['B-khong-chac']}/dai').then(r => r.json()).then(d => d.doan.length)") > 0
    b = f'.lo-dong[data-vid="{_ID["B-khong-chac"]}"] .lo-dai'
    assert p.evaluate(f"document.querySelector('{b}').classList.contains('lo-dai-xam')")
    assert p.locator(f"{b} .lo-doan").count() == 0


# ---------------------------------------------------------------- ảnh soi
def test_soi_nhanh_chi_tai_khi_bam_va_du_ba_anh_moi_video(may_chu, trinh_duyet):
    goc, _ = may_chu
    p, loi_js, yeu_cau = _mo(trinh_duyet, goc)
    p.wait_for_timeout(300)
    assert not [u for u in yeu_cau if "/soi" in u]  # vào trang: KHÔNG gọi /soi
    p.get_by_role("button", name="Soi nhanh 2 video").click()
    p.wait_for_function("document.querySelectorAll('.lo-nhom-C .lo-soi-anh').length === 6")
    p.evaluate("document.querySelectorAll('.lo-soi-anh').forEach(i => { i.loading = 'eager'; })")
    p.wait_for_function("[...document.querySelectorAll('.lo-nhom-C .lo-soi-anh')].every(i => i.complete && i.naturalWidth === 480)")
    goi_soi = [u for u in yeu_cau if u.endswith("/soi")]
    assert sorted(goi_soi) == sorted(f"{goc}/api/thay-logo/videos/{_ID[k]}/soi" for k in ("C-chac-1", "C-chac-2"))
    _chup(p, "lo-soi-nhanh-1280.png")
    assert loi_js == []


def test_xac_nhan_khong_co_logo_bo_qua_roi_hoan_tac(may_chu, trinh_duyet):
    goc, tmp = may_chu
    p, loi_js, _ = _mo(trinh_duyet, goc)
    p.get_by_role("button", name="Xác nhận 1 video").click()
    p.wait_for_function("document.querySelectorAll('.lo-nhom-D .lo-soi-anh').length === 3")
    assert p.get_by_role("button", name="Có logo", exact=True).is_disabled()
    p.get_by_role("button", name="Đúng là không có logo").click()
    p.wait_for_selector(".lo-nhom-D >> text=Đã xác nhận không có logo")
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    try:
        assert conn.execute("SELECT bo_qua_luc FROM tl_job_video WHERE id=?", (_ID["D-khong-logo"],)).fetchone()[0] is not None
        p.get_by_role("button", name="Hoàn tác").click()
        p.wait_for_selector(".lo-nhom-D >> text=Đúng là không có logo")
        assert conn.execute("SELECT bo_qua_luc FROM tl_job_video WHERE id=?", (_ID["D-khong-logo"],)).fetchone()[0] is None
    finally:
        conn.close()
    assert loi_js == []


# ---------------------------------------------------------------- ảnh bìa + giao diện tối
def test_anh_bia_tu_khung_goc_cho_dong_can_nguoi_va_khong_goi_cho_nhom_gop(may_chu, trinh_duyet):
    """Video "Tải từ máy"/Drive không có `/thumbs` ⇒ bìa lấy khung 10% bản gốc qua `/khung-tai` CHỈ cho dòng từng video (A/B)."""
    goc, _ = may_chu
    p, loi_js, yeu_cau = _mo(trinh_duyet, goc)
    p.evaluate("document.querySelectorAll('img').forEach(i => { i.loading = 'eager'; })")
    co_bia = ("A-hai-cho", "B-khong-chac", "B-thay-khong-bam")
    for k in co_bia:
        p.wait_for_function(f"""(() => {{ const i = document.querySelector('.lo-dong[data-vid="{_ID[k]}"] .lo-bia img');
            return i && i.complete && i.naturalWidth > 0; }})()""")
    # A-mot-cho: nhật ký ghi 3000 khung, tệp chỉ 60 ⇒ máy chủ không trích được ⇒ ảnh lỗi bị gỡ, ô bìa trống (không ảnh vỡ)
    p.wait_for_function(f"""document.querySelector('.lo-dong[data-vid="{_ID['A-mot-cho']}"] .lo-bia img') === null""")
    bia = sorted(u.split("/videos/")[1] for u in yeu_cau if "/khung-tai/" in u)
    assert bia == sorted(f"{_ID[k]}/khung-tai/{int(n * 0.1)}?ban=goc" for k, n in
                         (("A-hai-cho", SO_KHUNG), ("A-mot-cho", 3000), ("B-khong-chac", SO_KHUNG), ("B-thay-khong-bam", SO_KHUNG)))
    assert loi_js == []


def test_giao_dien_toi_doc_duoc(may_chu, trinh_duyet):
    goc, _ = may_chu
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script("localStorage.setItem('videodl-theme', 'dark')")
    p = ctx.new_page()
    mo_trang(p, f"{goc}/thay-logo-lo.html?lo={_ID['_job']}", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelector('#lo-danh-sach .lo-dong') !== null")
    assert p.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    nen = p.evaluate("getComputedStyle(document.body).backgroundColor")
    chu = p.evaluate("getComputedStyle(document.querySelector('.lo-ten')).color")
    sang = lambda c: sum(int(x) for x in c[c.index('(') + 1:c.index(')')].split(',')[:3]) / 3  # noqa: E731
    assert sang(nen) < 60 < 180 < sang(chu), (nen, chu)  # nền tối, chữ sáng
    _chup(p, "lo-toi-1280.png")


# ---------------------------------------------------------------- lô cũ / lỗi tạm
def test_lo_cu_video_mat_vet_duoc_dem_ra_khong_bien_mat_im_lang(may_chu, trinh_duyet):
    goc, _ = may_chu
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{goc}/thay-logo-lo.html?lo={_ID['_lo_cu']}", dem_mang_ngoai(ctx))
    p.wait_for_selector("#lo-danh-sach >> text=Chưa có video nào máy làm xong để duyệt.")
    tom = p.locator("#lo-tom-tat").inner_text()
    assert "1 video máy đã xong nhưng không còn dữ liệu để xếp nhóm" in tom and "máy còn làm 1" in tom, tom
    assert p.locator("#lo-danh-sach .lo-dong").count() == 0
    assert loi_js == []


def test_xac_nhan_loi_tam_roi_thu_lai_thanh_cong_xoa_cau_loi(may_chu, trinh_duyet):
    goc, tmp = may_chu
    p, loi_js, _ = _mo(trinh_duyet, goc)
    lan = []

    def chan_lan_dau(route):
        lan.append(1)
        route.fulfill(status=500, body="loi") if len(lan) == 1 else route.continue_()
    p.route("**/bo-qua", chan_lan_dau)
    p.get_by_role("button", name="Xác nhận 1 video").click()
    p.wait_for_function("document.querySelectorAll('.lo-nhom-D .lo-soi-anh').length === 3")
    p.get_by_role("button", name="Đúng là không có logo").click()
    p.wait_for_function("!document.getElementById('lo-loi').hidden")
    assert "Không lưu được" in p.locator("#lo-loi").inner_text()
    p.get_by_role("button", name="Đúng là không có logo").click()
    p.wait_for_selector(".lo-nhom-D >> text=Đã xác nhận không có logo")
    assert p.evaluate("document.getElementById('lo-loi').hidden") and len(lan) == 2
    p.get_by_role("button", name="Hoàn tác").click()  # trả DB về như cũ cho các test khác dùng chung máy chủ
    p.wait_for_selector(".lo-nhom-D >> text=Đúng là không có logo")
    assert loi_js == []
