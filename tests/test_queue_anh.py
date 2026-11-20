"""Nối dây hàng đợi cho chế độ tải ảnh: cổng cờ, truyền `loai` xuống nguồn, tách ref video/ảnh, đường ảnh.

Chạy trên `jobs.db` thật trong tmp_path; nguồn, bộ tải ảnh và `download_all` được thay bằng giả có kiểm soát,
Drive là uploader giả. Không mạng, không ffmpeg, không ngủ thật.

Đột biến (áp tạm ⇒ test nêu tên ĐỎ, hoàn nguyên ⇒ XANH):
  * `_fetch_refs` và `la_link_le` gọi `chon_nguon` mà bỏ đối số loại (và không truyền `loai` cho `liet_ke`):
    `test_job_anh_truyen_loai_xuong_nguon`, `test_la_link_le_theo_loai_cua_job` đỏ.
  * Xoá khối cổng cờ ở đầu `process_job`: `test_co_tat_job_anh_failed_khong_goi_nguon` đỏ.
  * Trong `_JobProgress.note` bỏ lời gọi `verify_video_stream` (coi mọi tệp là có luồng hình):
    `test_ca_hai_tep_video_khong_co_luong_hinh_la_loi_khong_la_xong` đỏ.
  * Trong `queue_anh.tai_cac_bai_anh` đưa `increment_job_counts(xong_delta=1)` lên TRƯỚC lời gọi `hook(...)`:
    `test_xong_chi_tang_sau_khi_hook_upload_ok` đỏ.
  * Trong `giai_captcha_worker._quet_sau_giai_than` bỏ `**kw_loai(...)` khỏi lời gọi `quet_tren_trang`:
    `test_captcha_worker_truyen_loai_cua_job_toi_lan_quet` đỏ.
  * Trong `tai_cac_bai_anh` xếp mọi lỗi thành `LOAI_LOI_NGUON` (khung xám) :
    `test_phan_loai_loi_nguon_xam_tep_hong_do` đỏ.
"""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader import tai_anh
from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.utils import STOP_HET_DIA, STOP_TAI_ANH_TAT, VideoRef
from web import lifecycle, models
from web import queue as queue_mod
from web import queue_anh
from web.queue import _hoan_tat_tu_refs, process_job

_UPLOAD_OK = UploadResult(outcome=UploadOutcome.SUCCESS, file_id="f1", drive_id="d1")


def _anh_jpeg(i: int = 1) -> bytes:
    buf = io.BytesIO()
    Image.effect_noise((200, 150), 50 + i).convert("RGB").save(buf, "JPEG")
    return buf.getvalue()


def ref_anh(id_bai: str, k: int = 2) -> VideoRef:
    return VideoRef(video_id=f"anh-tt-{id_bai}", url=f"https://nguon.invalid/{id_bai}", loai="anh",
                    anh_urls=tuple((f"https://cdn.invalid/{id_bai}/{i}",) for i in range(k)))


def ref_video(id_video: str) -> VideoRef:
    return VideoRef(video_id=id_video, url=f"https://www.tiktok.com/@x/video/{id_video}")


class UploaderGia:
    """Drive giả đủ cho `on_bai_anh_verified`; `hong_bai` = id thư mục bài mà tệp đầu bị từ chối."""

    def __init__(self, hong_bai: str | None = None):
        self.hong_bai = hong_bai

    def is_configured(self):
        return True

    def create_job_folder(self, job_id):
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="F-job", drive_id="D", web_view_link="http://x")

    def create_folder(self, name, parent_id=None):
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=f"F-{name}", drive_id="D")

    def upload_file(self, path, parent_folder_id=None):
        if self.hong_bai and parent_folder_id == f"F-{self.hong_bai}":
            return UploadResult(outcome=UploadOutcome.FAILED, reason="Forbidden")
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=f"T-{parent_folder_id}-{path.name}", drive_id="D")

    def trash_file(self, file_id):
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=file_id)


class NguonGia:
    """Nguồn giả: ghi lại kwargs mỗi lần `liet_ke`."""

    def __init__(self, refs):
        self.refs, self.goi = refs, []

    def liet_ke(self, url, **kw):
        self.goi.append(kw)
        return list(self.refs)


class NghiGia:
    """Thay `JitterThrottle`: không ngủ, đếm số lần chờ."""
    so_cho = 0

    def __init__(self, *a, **kw):
        pass

    def wait(self):
        NghiGia.so_cho += 1


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "jobs.db"
    models.init_db(p)
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()
    yield p
    lifecycle.set_uploader(None)
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()


@pytest.fixture(autouse=True)
def _khong_ngu(monkeypatch):
    NghiGia.so_cho = 0
    monkeypatch.setattr(queue_anh, "JitterThrottle", NghiGia)
    monkeypatch.setattr(queue_anh.time, "sleep", lambda _s: None)


def _tai_gia(monkeypatch, *, hut: dict | None = None):
    """`tai_mot_bai` giả: ghi ảnh thật vào `thu_muc/<bai_id>/NN.jpg`; `hut[bai_id]` = KetQuaTaiBai lỗi."""
    hut = hut or {}
    goi: list[str] = []

    def tai(ref, thu_muc, proxy=None, *, kiem_video=None, lay=None):
        goi.append(ref.video_id)
        if ref.video_id in hut:
            return hut[ref.video_id]
        d = Path(thu_muc) / ref.video_id
        d.mkdir(parents=True, exist_ok=True)
        tep = []
        for i in range(1, len(ref.anh_urls) + 1):
            p = d / f"{i:02d}.jpg"
            p.write_bytes(_anh_jpeg(i))
            tep.append(p)
        return tai_anh.KetQuaTaiBai(True, ref.video_id, thu_muc_bai=d, tep=tuple(tep))

    monkeypatch.setattr(tai_anh, "tai_mot_bai", tai)
    return goi


def _job(db, url="https://www.tiktok.com/@nguoi.dung", tong=10, loai="anh", nen_tang="tiktok"):
    jid = models.create_job(db, url, tong, "chu@dev.local", nen_tang=nen_tang, loai_tai=loai)
    return jid, models.get_job(db, jid)


def _hang(db, cot="loai"):
    with sqlite3.connect(db) as c:
        return [r[0] for r in c.execute(f"SELECT {cot} FROM videos ORDER BY video_id")]


# ---------------------------------------------------------------------------
# Cổng cờ ở đầu process_job
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("loai", ["anh", "ca_hai"])
def test_co_tat_job_anh_failed_khong_goi_nguon(db, tmp_path, monkeypatch, loai):
    monkeypatch.delenv("VIDEODL_TAI_ANH_BAT", raising=False)
    goi = []
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda *a, **k: goi.append(a) or pytest.fail("đã mở nguồn"))
    monkeypatch.setattr(queue_mod, "_fetch_refs", lambda *a, **k: pytest.fail("đã liệt kê"))
    jid, job = _job(db, loai=loai)

    process_job(db, tmp_path / "dl", tmp_path / "ck", job)

    j = models.get_job(db, jid)
    assert j["trang_thai"] == "failed" and j["ly_do_dung"] == STOP_TAI_ANH_TAT
    assert goi == []


def test_co_tat_job_video_van_chay(db, tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODL_TAI_ANH_BAT", raising=False)
    nguon = NguonGia([])
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda *a, **k: nguon)
    jid, job = _job(db, loai="video")
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)
    assert len(nguon.goi) == 1
    assert models.get_job(db, jid)["ly_do_dung"] != STOP_TAI_ANH_TAT


# ---------------------------------------------------------------------------
# `loai` của job tới nguồn; job video gọi y hệt cũ
# ---------------------------------------------------------------------------

def test_job_anh_truyen_loai_xuong_nguon(db, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_TAI_ANH_BAT", "1")
    nguon, cho_hoi = NguonGia([]), []
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda url, loai="video": cho_hoi.append(loai) or nguon)
    jid, job = _job(db, loai="ca_hai")
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)
    assert nguon.goi and all(kw.get("loai") == "ca_hai" for kw in nguon.goi)
    assert cho_hoi and set(cho_hoi) == {"ca_hai"}, "mọi lần chọn nguồn (kể cả la_link_le) phải theo loại của job"


def test_job_video_goi_nguon_va_download_all_y_het_cu(db, tmp_path, monkeypatch):
    nguon = NguonGia([ref_video("1"), ref_video("2")])
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda url, loai="video": nguon)
    nhan = []
    monkeypatch.setattr(queue_mod, "download_all",
                        lambda refs, out, **kw: nhan.append((list(refs), sorted(kw))) or (0, 0, []))
    jid, job = _job(db, loai="video")
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)
    assert len(nguon.goi) == 1 and "loai" not in nguon.goi[0]
    assert len(nhan) == 1 and [r.video_id for r in nhan[0][0]] == ["1", "2"]
    assert "loai" not in nhan[0][1]


def test_la_link_le_theo_loai_cua_job():
    url = "https://www.tiktok.com/@nguoi.dung/photo/7000000000000000001"
    assert queue_mod.la_link_le(url, "anh") is True
    assert queue_mod.la_link_le(url, "video") is False       # mặc định ≡ hôm nay: `/photo/` không phải link video
    assert queue_mod.la_link_le(url) is False


def test_loc_trung_mot_lan_chi_giu_loai_cua_job(db):
    jid, job = _job(db, loai="anh")
    refs = [ref_video("1"), ref_anh("9")]
    dung: dict = {}
    assert [r.video_id for r in queue_mod._loc_trung_mot_lan(db, job, refs, dung, "anh")] == ["anh-tt-9"]
    assert [r.video_id for r in queue_mod._loc_trung_mot_lan(db, job, refs, {}, "video")] == ["1"]
    assert len(queue_mod._loc_trung_mot_lan(db, job, refs, {}, "ca_hai")) == 2


# ---------------------------------------------------------------------------
# Job ảnh: đếm theo bài, 0 hàng video
# ---------------------------------------------------------------------------

def test_job_anh_dem_theo_bai_xong_loi_va_khong_co_hang_video(db, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_TAI_ANH_BAT", "1")
    lifecycle.set_uploader(UploaderGia(hong_bai="anh-tt-C"))
    a, b, c = ref_anh("A", 3), ref_anh("B"), ref_anh("C")
    hut_b = tai_anh.KetQuaTaiBai(False, b.video_id, loai_loi=tai_anh.LOI_NGUON, ly_do="bài gỡ")
    _tai_gia(monkeypatch, hut={b.video_id: hut_b})
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda url, loai="video": NguonGia([a, b, c]))
    monkeypatch.setattr(queue_mod, "download_all", lambda *x, **k: pytest.fail("job ảnh thuần không có ref video"))
    jid, job = _job(db, tong=7, loai="anh")

    process_job(db, tmp_path / "dl", tmp_path / "ck", job)

    j = models.get_job(db, jid)
    assert (j["xong"], j["loi"], j["loi_tiktok"], j["tong"], j["tim_thay"]) == (1, 2, 1, 7, 3)
    assert j["trang_thai"] == "done"
    assert _hang(db) == ["anh"] * 3, "bài A đủ 3 tệp là 3 hàng; B, C hụt không để lại hàng nào"
    assert set(_hang(db, "bai_id")) == {"anh-tt-A"}
    assert models.sources_for_videos(db, ["anh-tt-A"], None) == {"anh-tt-A": ["https://www.tiktok.com/@nguoi.dung"]}
    assert not (tmp_path / "dl" / str(jid) / "anh-tt-A").exists(), "local sạch"


def test_job_anh_moi_bai_deu_hut_thi_failed(db, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_TAI_ANH_BAT", "1")
    b = ref_anh("B")
    _tai_gia(monkeypatch, hut={b.video_id: tai_anh.KetQuaTaiBai(False, b.video_id, loai_loi=tai_anh.LOI_HE_THONG,
                                                                  ly_do="tệp ảnh hỏng")})
    monkeypatch.setattr(queue_mod, "chon_nguon", lambda url, loai="video": NguonGia([b]))
    jid, job = _job(db)
    process_job(db, tmp_path / "dl", tmp_path / "ck", job)
    assert models.get_job(db, jid)["trang_thai"] == "failed"


# ---------------------------------------------------------------------------
# ca_hai: video qua download_all, ảnh qua đường ảnh
# ---------------------------------------------------------------------------

def _chay_ca_hai(db, tmp_path, monkeypatch, refs, *, fake_download, hook_video=None):
    monkeypatch.setattr(queue_mod, "download_all", fake_download)
    jid, job = _job(db, loai="ca_hai", nen_tang="instagram")
    models.claim_next_pending_job(db)
    job = models.get_job(db, jid)
    _hoan_tat_tu_refs(db, tmp_path / "dl", job, refs, {}, None, hook_video or (lambda **kw: _UPLOAD_OK))
    return jid


def _download_gia(nhan, *, verify_ok=True, tu_choi_dia=False):
    def fake(refs, out, cookies_path=None, progress=None, **kw):
        nhan.append([r.video_id for r in refs])
        out.mkdir(parents=True, exist_ok=True)
        for r in refs:
            if tu_choi_dia and kw["truoc_moi_file"](r):
                return 0, 0, []
            (out / r.filename).write_bytes(b"x")
            progress.note("downloaded")
        return len(refs), 0, []
    return fake


def test_ca_hai_video_qua_download_all_anh_qua_duong_anh(db, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **k: True)
    lifecycle.set_uploader(UploaderGia())
    goi_anh = _tai_gia(monkeypatch)
    nhan: list = []
    jid = _chay_ca_hai(db, tmp_path, monkeypatch, [ref_video("11"), ref_anh("A"), ref_video("12"), ref_anh("B")],
                       fake_download=_download_gia(nhan))
    assert nhan == [["11", "12"]], "download_all chỉ nhận ref video"
    assert goi_anh == ["anh-tt-A", "anh-tt-B"]
    j = models.get_job(db, jid)
    assert (j["xong"], j["loi"], j["tim_thay"], j["trang_thai"]) == (4, 0, 4, "done")
    assert sorted(_hang(db, "video_id")) == ["anh-tt-A-01", "anh-tt-A-02", "anh-tt-B-01", "anh-tt-B-02"]


def test_ca_hai_tep_video_khong_co_luong_hinh_la_loi_khong_la_xong(db, tmp_path, monkeypatch):
    """Cổng luồng hình của nhánh video vẫn y nguyên trong job `ca_hai`: tệp chỉ-tiếng đếm lỗi, hook không chạy."""
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **k: False)
    lifecycle.set_uploader(UploaderGia())
    _tai_gia(monkeypatch)
    hook_video: list = []
    jid = _chay_ca_hai(db, tmp_path, monkeypatch, [ref_video("11"), ref_anh("A")],
                       fake_download=_download_gia([]),
                       hook_video=lambda **kw: hook_video.append(kw) or _UPLOAD_OK)
    j = models.get_job(db, jid)
    assert (j["xong"], j["loi"]) == (1, 1), "ảnh xong; video không luồng hình = lỗi"
    assert hook_video == []


def test_ca_hai_het_dia_o_buoc_video_thi_anh_khong_chay(db, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **k: True)
    lifecycle.set_uploader(UploaderGia())
    goi_anh = _tai_gia(monkeypatch)

    class Dia:
        ok, reason = False, "dia_day"

    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda _p: Dia())
    jid = _chay_ca_hai(db, tmp_path, monkeypatch, [ref_video("11"), ref_anh("A")],
                       fake_download=_download_gia([], tu_choi_dia=True))
    j = models.get_job(db, jid)
    assert j["trang_thai"] == "failed" and j["ly_do_dung"] == STOP_HET_DIA
    assert goi_anh == [], "đã dừng ở bước video ⇒ đường ảnh không được chạy"


def test_het_dia_giua_cac_bai_anh_dung_job(db, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **k: True)
    lifecycle.set_uploader(UploaderGia())
    goi_anh = _tai_gia(monkeypatch)

    class Dia:
        def __init__(self, ok):
            self.ok, self.reason = ok, "dia_day"

    tra = iter([True, False])           # bài 1 đủ chỗ, tới bài 2 hết đĩa
    monkeypatch.setattr(queue_mod, "check_disk_guard", lambda _p: Dia(next(tra)))
    monkeypatch.setattr(queue_mod, "download_all", lambda *a, **k: pytest.fail("không có ref video"))
    jid, job = _job(db, loai="anh")
    models.claim_next_pending_job(db)
    _hoan_tat_tu_refs(db, tmp_path / "dl", models.get_job(db, jid), [ref_anh("A"), ref_anh("B")], {}, None,
                      lambda **kw: _UPLOAD_OK)
    j = models.get_job(db, jid)
    assert goi_anh == ["anh-tt-A"]
    assert (j["xong"], j["trang_thai"], j["ly_do_dung"]) == (1, "failed", STOP_HET_DIA)


# ---------------------------------------------------------------------------
# tai_cac_bai_anh: thăm lại đúng một lần, xong sau hook, phân loại lỗi, throttle
# ---------------------------------------------------------------------------

class Ghi:
    def __init__(self):
        self.loi, self.sighting = [], []

    def ghi_loi(self, ref, ly_do, *, loai):
        self.loi.append((ref.video_id, loai))

    def ghi_sighting(self, ref):
        self.sighting.append(ref.video_id)


def _chay_anh(db, tmp_path, refs, ghi, **kw):
    jid, _ = _job(db)
    return jid, queue_anh.tai_cac_bai_anh(refs, job_id=jid, db_path=db, thu_muc=tmp_path / "dl",
                                          ghi_loi=ghi.ghi_loi, ghi_sighting=ghi.ghi_sighting, **kw)


def _ket_qua_het_han(bai_id):
    return tai_anh.KetQuaTaiBai(False, bai_id, loai_loi=tai_anh.LOI_NGUON, ly_do="403", can_tham_lai=True)


def test_bai_can_tham_lai_tham_dung_mot_lan_roi_tai_lai(db, tmp_path, monkeypatch):
    lifecycle.set_uploader(UploaderGia())
    ref = ref_anh("A")
    moi = VideoRef(video_id=ref.video_id, url=ref.url, loai="anh", anh_urls=(("https://cdn.invalid/moi/0",),))
    lan = {"n": 0}

    def tai(r, thu_muc, proxy=None, *, kiem_video=None, lay=None):
        lan["n"] += 1
        if r is ref:
            return _ket_qua_het_han(r.video_id)
        d = Path(thu_muc) / r.video_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "01.jpg").write_bytes(_anh_jpeg())
        return tai_anh.KetQuaTaiBai(True, r.video_id, thu_muc_bai=d, tep=(d / "01.jpg",))

    monkeypatch.setattr(tai_anh, "tai_mot_bai", tai)
    tham: list = []
    ghi = Ghi()
    _, kq = _chay_anh(db, tmp_path, [ref], ghi, tham_lai=lambda r, p: tham.append(r) or moi)
    assert len(tham) == 1 and lan["n"] == 2
    assert (kq.xong, kq.loi) == (1, 0) and ghi.sighting == [ref.video_id]


def test_tham_lai_van_403_la_loi_nguon_va_khong_tham_lan_hai(db, tmp_path, monkeypatch):
    ref = ref_anh("A")
    monkeypatch.setattr(tai_anh, "tai_mot_bai", lambda r, t, p=None, **k: _ket_qua_het_han(r.video_id))
    tham: list = []
    ghi = Ghi()
    _, kq = _chay_anh(db, tmp_path, [ref], ghi, tham_lai=lambda r, p: tham.append(1) or r)
    assert len(tham) == 1
    assert (kq.xong, kq.loi) == (0, 1) and ghi.loi == [(ref.video_id, "tiktok")]


def test_chua_co_ham_tham_lai_coi_nhu_hut_phia_nguon(db, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_anh, "_THAM_LAI", {})
    monkeypatch.setattr(tai_anh, "tai_mot_bai", lambda r, t, p=None, **k: _ket_qua_het_han(r.video_id))
    ghi = Ghi()
    _, kq = _chay_anh(db, tmp_path, [ref_anh("A")], ghi)
    assert (kq.xong, kq.loi) == (0, 1) and ghi.loi == [("anh-tt-A", "tiktok")]


def test_dang_ky_tham_lai_duoc_dung_theo_nen_tang_cua_bai(db, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_anh, "_THAM_LAI", {})
    da_goi: list = []
    queue_anh.dang_ky_tham_lai("tt", lambda r, p: da_goi.append(r.video_id))     # trả None = bài đã gỡ
    monkeypatch.setattr(tai_anh, "tai_mot_bai", lambda r, t, p=None, **k: _ket_qua_het_han(r.video_id))
    ghi = Ghi()
    _, kq = _chay_anh(db, tmp_path, [ref_anh("A")], ghi)
    assert da_goi == ["anh-tt-A"] and kq.loi == 1 and ghi.loi == [("anh-tt-A", "tiktok")]
    with pytest.raises(ValueError):
        queue_anh.dang_ky_tham_lai("zz", lambda r, p: r)


def test_xong_chi_tang_sau_khi_hook_upload_ok(db, tmp_path, monkeypatch):
    _tai_gia(monkeypatch)
    jid, _ = _job(db)
    thay: list = []

    def hook(*, job_id, ref, tep, db_path=None):
        thay.append(models.get_job(db, job_id)["xong"])        # `xong` TẠI LÚC hook chạy
        return UploadResult(outcome=UploadOutcome.SUCCESS if len(thay) == 1 else UploadOutcome.FAILED,
                            file_id="f", reason="Forbidden")

    monkeypatch.setattr(queue_anh.lifecycle_anh, "on_bai_anh_verified", hook)
    ghi = Ghi()
    kq = queue_anh.tai_cac_bai_anh([ref_anh("A"), ref_anh("B")], job_id=jid, db_path=db, thu_muc=tmp_path / "dl",
                                   ghi_loi=ghi.ghi_loi, ghi_sighting=ghi.ghi_sighting)
    assert thay == [0, 1], "lúc hook chạy bài đầu `xong` phải còn 0; hook trượt ⇒ không tăng"
    assert (kq.xong, kq.loi) == (1, 1)
    j = models.get_job(db, jid)
    assert (j["xong"], j["loi"]) == (1, 0), "`loi` của job do `ghi_loi` (nối vào _JobProgress) tăng, không phải ở đây"
    assert ghi.loi == [("anh-tt-B", "he_thong")] and ghi.sighting == ["anh-tt-A"]


def test_phan_loai_loi_nguon_xam_tep_hong_do(db, tmp_path, monkeypatch):
    nguon_hut = tai_anh.KetQuaTaiBai(False, "anh-tt-A", loai_loi=tai_anh.LOI_NGUON, ly_do="bài gỡ")
    he_thong = tai_anh.KetQuaTaiBai(False, "anh-tt-B", loai_loi=tai_anh.LOI_HE_THONG, ly_do="tệp ảnh hỏng")
    _tai_gia(monkeypatch, hut={"anh-tt-A": nguon_hut, "anh-tt-B": he_thong})
    ghi = Ghi()
    _chay_anh(db, tmp_path, [ref_anh("A"), ref_anh("B")], ghi)
    assert ghi.loi == [("anh-tt-A", "tiktok"), ("anh-tt-B", "he_thong")]


def test_qua_progress_that_loi_tiktok_chi_dem_loi_nguon(db, tmp_path, monkeypatch):
    """Đi qua `_hoan_tat_tu_refs` thật: cột `loi_tiktok` (khung xám) chỉ đếm lỗi nguồn, tệp hỏng không vào đó."""
    monkeypatch.setenv("VIDEODL_TAI_ANH_BAT", "1")
    _tai_gia(monkeypatch, hut={
        "anh-tt-A": tai_anh.KetQuaTaiBai(False, "anh-tt-A", loai_loi=tai_anh.LOI_NGUON, ly_do="bài gỡ"),
        "anh-tt-B": tai_anh.KetQuaTaiBai(False, "anh-tt-B", loai_loi=tai_anh.LOI_HE_THONG, ly_do="tệp hỏng")})
    lifecycle.set_uploader(UploaderGia())
    jid, job = _job(db)
    models.claim_next_pending_job(db)
    _hoan_tat_tu_refs(db, tmp_path / "dl", models.get_job(db, jid),
                      [ref_anh("A"), ref_anh("B"), ref_anh("C")], {}, None, lambda **kw: _UPLOAD_OK)
    j = models.get_job(db, jid)
    assert (j["xong"], j["loi"], j["loi_tiktok"]) == (1, 2, 1)


def test_throttle_truoc_moi_bai_va_nghi_lo(db, tmp_path, monkeypatch):
    lifecycle.set_uploader(UploaderGia())
    _tai_gia(monkeypatch)
    nghi: list = []
    cho: list = []

    class T:
        def wait(self):
            cho.append(1)

    ghi = Ghi()
    _chay_anh(db, tmp_path, [ref_anh("A"), ref_anh("B"), ref_anh("C")], ghi, throttle=T(),
              kich_thuoc_lo=2, nghi_lo_giay=60.0, nghi_lo=nghi.append)
    assert len(cho) == 3 and nghi == [60.0], "nghỉ lô đúng một lần sau 2 bài, throttle trước từng bài"


def test_cong_ip_truoc_goi_moi_bai_va_dung_khi_cong_tu_choi(db, tmp_path, monkeypatch):
    _tai_gia(monkeypatch)
    lifecycle.set_uploader(UploaderGia())

    class Cong:
        def __init__(self):
            self.n = 0

        def truoc_goi(self):
            self.n += 1
            return "tran_gio" if self.n == 2 else None

    cong, ghi = Cong(), Ghi()
    _, kq = _chay_anh(db, tmp_path, [ref_anh("A"), ref_anh("B"), ref_anh("C")], ghi, cong=cong)
    assert cong.n == 2 and kq.ly_do_dung == "tran_gio" and kq.xong == 1


# ---------------------------------------------------------------------------
# Captcha-worker: `loai` của job tới lời gọi quét
# ---------------------------------------------------------------------------

def _quet_ghi_loai(monkeypatch, worker, ghi):
    def quet(page, url, max_videos=200, scroll_pause=1.5, idle_rounds=12, dem_trang=None, thong_ke_feed=None,
             tai_lai_truoc_khi_cuon=False, kiem_truoc_khi_cuon=None, loai="video"):
        ghi.append(loai)
        return []
    monkeypatch.setattr(worker.scraper, "quet_tren_trang", quet)


@pytest.mark.parametrize("loai", ["anh", "ca_hai"])
def test_captcha_worker_truyen_loai_cua_job_toi_lan_quet(monkeypatch, db, loai):
    import test_giai_captcha_may_trang_thai as t
    h, _ = t._da_giai_harness(monkeypatch, db, [t.RespFeed(rong=False)])
    h.job["loai_tai"] = loai
    ghi: list = []
    _quet_ghi_loai(monkeypatch, t.worker, ghi)
    h.chay()
    assert ghi == [loai]


def test_captcha_worker_job_video_khong_them_kwarg_loai(monkeypatch, db):
    import test_giai_captcha_may_trang_thai as t
    h, _ = t._da_giai_harness(monkeypatch, db, [t.RespFeed(rong=False)])
    kw_nhan: list = []

    def quet(page, url, **kw):
        kw_nhan.append(sorted(kw))
        return []

    monkeypatch.setattr(t.worker.scraper, "quet_tren_trang", quet)
    h.chay()
    assert kw_nhan and "loai" not in kw_nhan[0]


def test_captcha_worker_ham_quet_chua_biet_loai_thi_job_anh_loi_ro(monkeypatch, db):
    """Chưa có `loai` ở hàm quét ⇒ KHÔNG lặng lẽ quét ra video cho job ảnh."""
    import test_giai_captcha_may_trang_thai as t
    h, _ = t._da_giai_harness(monkeypatch, db, [t.RespFeed(rong=False)])
    h.job["loai_tai"] = "anh"
    da_quet: list = []
    monkeypatch.setattr(t.worker.scraper, "quet_tren_trang", lambda page, url, **kw: da_quet.append(1) or [])
    kq = h.chay()       # worker nuốt lỗi lượt giải ⇒ job về chờ xác minh, không trả refs video
    assert da_quet == [] and kq.loai != "refs"


def test_bai_anh_chua_co_url_thi_tham_bai_truoc_khi_tai(db, tmp_path, monkeypatch):
    """Trang liệt kê chỉ thấy anchor `/photo/` ⇒ ref ảnh `anh_urls=()`: phải thăm bài lấy URL rồi mới tải, KHÔNG tải
    ref rỗng (sẽ ra "bài không có ảnh" sai phía nguồn).
    Đột biến: bỏ nhánh `if ref.anh_urls:` trong `_tai_va_tham_lai` (luôn tải trước) ⇒ test ĐỎ."""
    import dataclasses
    goi = _tai_gia(monkeypatch)
    ref_rong = dataclasses.replace(ref_anh("A"), anh_urls=())
    tham: list = []
    ghi = Ghi()
    _chay_anh(db, tmp_path, [ref_rong], ghi,
              tham_lai=lambda r, p: tham.append(r.video_id) or ref_anh("A"))
    assert tham == ["anh-tt-A"], "thăm bài đúng một lần, TRƯỚC khi tải"
    assert goi == ["anh-tt-A"] and len(goi) == 1, "chỉ tải ref đã có URL, không tải ref rỗng"


def test_tham_lai_theo_job_bai_instagram_mang_cookie_cua_job(monkeypatch):
    from tiktok_music_downloader import nguon_instagram
    nhan: list = []
    monkeypatch.setattr(nguon_instagram, "tham_lai",
                        lambda ref, proxy=None, *, cookies_path=None: nhan.append(cookies_path) or ref)
    ref_ig = VideoRef(video_id="anh-ig-Cx9AbZ12", url="https://www.instagram.com/p/Cx9AbZ12/", loai="anh")
    assert queue_anh.tham_lai_theo_job("/jar/ig.txt")(ref_ig, None) is ref_ig
    assert nhan == ["/jar/ig.txt"]


def test_tiktok_va_facebook_da_dang_ky_tham_lai_luc_nap():
    from tiktok_music_downloader import nguon_facebook_trang, tiktok_anh
    assert queue_anh._THAM_LAI["tt"] is tiktok_anh.tham_lai
    assert queue_anh._THAM_LAI["fbp"] is nguon_facebook_trang.tham_lai
