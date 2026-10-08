"""Worker job "Thay logo" — RIÊNG, không chung hàng đợi/lane với 2 lane tải (ĐP-1508).

Một luồng nền; mỗi lượt:
  1. Cổng đĩa: ổ chứa dữ liệu trống < TRAN_DIA_GB ⇒ không nhặt gì.
  2. Pha 1 (nhẹ): một video `cho` ⇒ tải nguồn về scratch, trích 7 khung vào hộp thư relay ⇒ `cho_agy` (bắt đầu đếm tuổi chờ).
  3. NHƯỜNG lane tải: `jobs.db` (mở CHỈ ĐỌC) có job `running` ⇒ không chạy pha nặng lượt này. RAM free < 30% hoặc swap trống
     < 1 GiB ⇒ cũng không.
  4. Pha 2 (nặng): video `cho_agy` đã có toạ độ ⇒ tiến trình con `nice -n 10` (`chay_mot_video`) có trần thời gian ⇒ tải file ra
     lên Drive ⇒ `xong` | `cho_nguoi` | `loi`. Video gốc không bao giờ bị sửa.
Tải về / tải lên được TIÊM (`tai_ve`, `tai_len`) để test không cần Drive.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky
from tiktok_music_downloader.thay_logo.hop_thu import HopThu

# `hoc_mau_agy` / `nguon_khung` cần OpenCV. `web/app.py` import file này lúc khởi động, nên OpenCV chỉ được nạp KHI tính năng bật
# (`_cv`): máy chưa cài opencv vẫn chạy Video Desk bình thường — tính năng đơn giản là không dựng được (log lý do).


def _cv():
    from tiktok_music_downloader.thay_logo import hoc_mau_agy
    from tiktok_music_downloader.thay_logo.nguon_khung import NguonKhungVideo
    return hoc_mau_agy, NguonKhungVideo

log = logging.getLogger("videodl.thay_logo")
TRAN_DIA_GB = 5.0
# Cổng RAM (agy tach-worker-R1b Q1): mini swap đã 3,5/5 GiB khi chưa có worker này (đo 09/10 00:24). Dưới ngưỡng ⇒ không chạy pha nặng.
RAM_FREE_TOI_THIEU_PCT, SWAP_TRONG_TOI_THIEU_MB = 30, 1024
NICE = 10
TRAN_GIAY_MIN, HE_SO_TRAN_GIAY = 600, 10  # trần thời gian tiến trình con = max(10 phút, 10 × độ dài video)


def co_job_tai_dang_chay(jobs_db: Path) -> bool:
    """CHỈ ĐỌC `jobs.db`. Không đọc được (khoá, thiếu file) ⇒ coi như ĐANG BẬN: nhường là hướng an toàn."""
    try:
        with sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=2) as c:
            return c.execute("SELECT count(*) FROM jobs WHERE trang_thai='running'").fetchone()[0] > 0
    except sqlite3.Error as e:
        log.warning("thay logo: không đọc được jobs.db (%s) — nhường lượt này", type(e).__name__)
        return True


def ram_du() -> bool:
    """`memory_pressure` free ≥ 30% VÀ swap trống ≥ 1 GiB. Không đo được ⇒ coi như THIẾU (không chạy pha nặng)."""
    try:
        mp = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        free = int(re.search(r"free percentage:\s*(\d+)", mp).group(1))
        sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=10).stdout
        swap_trong = float(re.search(r"free = ([\d.]+)M", sw).group(1))
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        log.warning("thay logo: không đo được RAM/swap — không chạy pha nặng lượt này")
        return False
    return free >= RAM_FREE_TOI_THIEU_PCT and swap_trong >= SWAP_TRONG_TOI_THIEU_MB


def _gui_nhom(con: subprocess.Popen, sig) -> None:
    try:
        os.killpg(con.pid, sig)
    except ProcessLookupError:
        pass


class ThayLogoWorker:
    def __init__(self, log_db: Path, jobs_db: Path, data_dir: Path, *, tai_ve: Callable[[dict, Path], Path],
                 tai_len: Callable[[Path], str], ffmpeg: str, python: str = sys.executable, nghi_giay: float = 10.0,
                 tran_dia_gb: float = TRAN_DIA_GB):
        self.log_db, self.jobs_db, self.data = Path(log_db), Path(jobs_db), Path(data_dir)
        self.hop = HopThu(self.data / "thay_logo_hop_thu")
        self.tai_ve, self.tai_len, self.ffmpeg, self.python = tai_ve, tai_len, ffmpeg, python
        self.nghi, self.tran_dia_gb = nghi_giay, tran_dia_gb
        self._dung = threading.Event()
        self._thread: threading.Thread | None = None
        self._con: subprocess.Popen | None = None
        self._lan_cuoi = "chua_chay"

    def _mo(self) -> sqlite3.Connection:
        conn = nhat_ky.mo(self.log_db)
        hang_doi.khoi_tao(conn)
        return conn

    # ---------------------------------------------------------------- vòng đời
    def start(self) -> None:
        conn = self._mo()
        try:
            log.info("thay logo: quét khởi động %s", hang_doi.quet_khoi_dong(conn))
        finally:
            conn.close()
        self._thread = threading.Thread(target=self._chay, name="thay-logo-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        """Không bao giờ chờ vô hạn: TERM tiến trình con, KILL nếu cần, join có trần."""
        self._dung.set()
        con = self._con
        if con is not None and con.poll() is None:
            # Cả NHÓM tiến trình (tiến trình con + ffmpeg cháu nó sinh): giết riêng tiến trình con thì ffmpeg thành mồ côi.
            _gui_nhom(con, signal.SIGTERM)
            try:
                con.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _gui_nhom(con, signal.SIGKILL)
                con.wait(timeout=5)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def trang_thai(self) -> dict:
        conn = self._mo()
        try:
            return {"song": bool(self._thread and self._thread.is_alive()), "luot_cuoi": self._lan_cuoi,
                    "cho_agy_cu_nhat_giay": hang_doi.tuoi_cho_agy_cu_nhat(conn)}
        finally:
            conn.close()

    def _chay(self) -> None:
        while not self._dung.is_set():
            try:
                self._lan_cuoi = self.mot_luot()
            except Exception:  # một video hỏng không được giết worker
                log.exception("thay logo: lượt lỗi")
                self._lan_cuoi = "loi_luot"
            self._dung.wait(self.nghi)

    # ---------------------------------------------------------------- một lượt
    def ram_du(self) -> bool:
        return ram_du()

    def dia_trong_gb(self) -> float:
        return shutil.disk_usage(self.data).free / 1e9

    def mot_luot(self) -> str:
        if self.dia_trong_gb() < self.tran_dia_gb:
            return "cho_dia"
        conn = self._mo()
        try:
            self._pha_1(conn)
            if co_job_tai_dang_chay(self.jobs_db):
                return "nhuong_lane_tai"
            if not self.ram_du():
                return "cho_ram"
            return self._pha_2(conn)
        finally:
            conn.close()

    def _scratch(self, vid: int) -> Path:
        d = self.data / "thay_logo_scratch" / str(vid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pha_1(self, conn) -> None:
        r = hang_doi.lay_mot(conn, "cho")
        if r is None:
            return
        try:
            hoc_mau_agy, NguonKhungVideo = _cv()
            goc = self.tai_ve(json.loads(r["nguon"]), self._scratch(r["id"]))
            n = hoc_mau_agy.dat_viec(NguonKhungVideo(str(goc)), self.hop, r["id"])
        except Exception as e:
            hang_doi.dat(conn, r["id"], "loi", loi_text=f"tải/trích khung: {type(e).__name__}: {e}"[:500])
            return
        if n == 0:
            hang_doi.dat(conn, r["id"], "loi", loi_text="không đọc được khung nào")
        else:
            hang_doi.dat(conn, r["id"], "cho_agy", cho_agy_tu=time.time(), duong_dan_goc=str(goc))

    def _pha_2(self, conn) -> str:
        hoc_mau_agy, NguonKhungVideo = _cv()
        for r in hang_doi.danh_sach(conn, "cho_agy"):
            nguon = NguonKhungVideo(r["duong_dan_goc"])
            kq_agy = hoc_mau_agy.doc_ket_qua(nguon, self.hop, r["id"])
            if kq_agy is None:
                continue
            boxes, man_ket = kq_agy
            hang_doi.dat(conn, r["id"], "dang_chay")
            self._chay_con(conn, r, nguon, boxes, man_ket)
            return "da_xu_ly"
        return "ranh"

    def _chay_con(self, conn, r, nguon, boxes, man_ket) -> None:
        d = self._scratch(r["id"])
        (d / "boxes.json").write_text(json.dumps([b.__dict__ for b in boxes]))
        ra = d / f"thay-logo-{r['id']}.mp4"  # tên này lên Drive
        cmd = ["nice", "-n", str(NICE), self.python, "-m", "tiktok_music_downloader.thay_logo.chay_mot_video",
               "--video", r["duong_dan_goc"], "--boxes", str(d / "boxes.json"), "--out", str(ra), "--db", str(self.log_db),
               "--files", str(self.data / "thay_logo"), "--nguon-video", r["nguon"], "--ffmpeg", self.ffmpeg,
               "--job-id", str(r["job_id"])] + ([] if man_ket is None else ["--man-ket", "1" if man_ket else "0"])
        tran = max(TRAN_GIAY_MIN, HE_SO_TRAN_GIAY * nguon.so_khung() / (nguon.fps or 30.0))
        self._con = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self._ket_thuc_con(conn, r, d, ra, tran)
        finally:
            if not self._dung.is_set():
                cur = conn.execute("SELECT trang_thai FROM tl_job_video WHERE id=?", (r["id"],)).fetchone()
                if cur and cur["trang_thai"] in ("xong", "cho_nguoi", "loi"):
                    shutil.rmtree(d, ignore_errors=True)  # gốc đã có trên Drive; scratch không giữ quá một video

    def _ket_thuc_con(self, conn, r, d, ra, tran) -> None:
        try:
            out, err = self._con.communicate(timeout=tran)
        except subprocess.TimeoutExpired:
            _gui_nhom(self._con, signal.SIGKILL)
            self._con.communicate()
            hang_doi.dat(conn, r["id"], "loi", loi_text=f"quá trần thời gian {int(tran)}s")
            return
        finally:
            self._con = None
        if self._dung.is_set():  # bị TERM vì tắt máy chủ ⇒ để nguyên `dang_chay`, quét khởi động lần sau làm lại
            return
        try:
            kq = json.loads((out or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            hang_doi.dat(conn, r["id"], "loi", loi_text=f"tiến trình con không trả kết quả: {(err or '')[-300:]}")
            return
        if kq.get("trang_thai") == "render" and kq.get("dau_ra"):
            try:
                file_id = self.tai_len(Path(kq["dau_ra"]))
            except Exception as e:
                hang_doi.dat(conn, r["id"], "loi", video_log_id=kq.get("video_log_id"),
                             loi_text=f"tải lên Drive: {type(e).__name__}: {e}"[:500])
                return
            nhat_ky.cap_nhat_video(conn, kq["video_log_id"], drive_file_id_ra=file_id)
            hang_doi.dat(conn, r["id"], "xong", video_log_id=kq["video_log_id"], drive_file_id_ra=file_id)
            ra.unlink(missing_ok=True)
        elif kq.get("trang_thai") == "cho_nguoi":
            hang_doi.dat(conn, r["id"], "cho_nguoi", video_log_id=kq.get("video_log_id"))
        else:
            hang_doi.dat(conn, r["id"], "loi", video_log_id=kq.get("video_log_id"), loi_text=str(kq.get("loi", ""))[:500])


# ---------------------------------------------------------------- dựng từ cấu hình máy (app.py gọi)
ENV_BAT, ENV_THU_MUC_RA = "THAY_LOGO_BAT", "THAY_LOGO_DRIVE_THU_MUC_RA"


def dung_tu_env(data_dir: Path, jobs_db: Path) -> "ThayLogoWorker | None":
    """Công tắc tính năng: TẮT mặc định. Chỉ dựng worker khi `THAY_LOGO_BAT=1` VÀ có thư mục Drive đầu ra VÀ Drive (service
    account) đã cấu hình VÀ tìm thấy ffmpeg; thiếu gì thì ghi log lý do và trả None (Video Desk chạy như chưa có tính năng)."""
    if os.environ.get(ENV_BAT) != "1":
        return None
    try:
        _cv()
    except ImportError as e:
        log.warning("thay logo: BẬT nhưng thiếu thư viện (%s) — không chạy worker", e.name)
        return None
    from tiktok_music_downloader.gdrive_upload import DriveUploader
    from tiktok_music_downloader.watermark import find_ffmpeg

    thu_muc, drive, ffmpeg = os.environ.get(ENV_THU_MUC_RA, ""), DriveUploader(), find_ffmpeg()
    if not thu_muc or not drive.is_configured() or not ffmpeg:
        log.warning("thay logo: BẬT nhưng thiếu cấu hình (thư mục ra=%s, drive=%s, ffmpeg=%s) — không chạy worker",
                    bool(thu_muc), drive.is_configured(), bool(ffmpeg))
        return None

    def tai_ve(nguon: dict, d: Path) -> Path:
        return drive.download_file(nguon["file_id"], d / "goc.mp4")

    def tai_len(p: Path) -> str:
        kq = drive.upload_file(p, parent_folder_id=thu_muc)
        if not kq.ok:
            raise RuntimeError(kq.reason or kq.outcome)
        return kq.file_id

    return ThayLogoWorker(data_dir / "thay_logo_log.db", jobs_db, data_dir, tai_ve=tai_ve, tai_len=tai_len, ffmpeg=ffmpeg)
