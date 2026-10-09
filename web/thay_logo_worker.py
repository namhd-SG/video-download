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
TRAN_CHO_AGY = 5  # pha 1 chỉ tải trước khi số video đang chờ agy < trần này — relay tắt thì không dồn file gốc vào đĩa
TRAN_GIAY_PHA_1 = 180
CHU_KY_DON_GIAY = 600
TRAN_GIAY_MIN, HE_SO_TRAN_GIAY = 600, 10  # trần thời gian tiến trình con = max(10 phút, 10 × độ dài video)


def co_job_tai_dang_chay(jobs_db: Path) -> bool:
    """CHỈ ĐỌC `jobs.db`. Bận = cùng tập trạng thái `web/models.py` coi là worker đang bận (`running`, `dang_mo`, `dang_giai`).
    Không đọc được (khoá, thiếu file) ⇒ coi như ĐANG BẬN: nhường là hướng an toàn."""
    try:
        with sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True, timeout=2) as c:
            return c.execute("SELECT count(*) FROM jobs WHERE trang_thai IN ('running', 'dang_mo', 'dang_giai')"
                             ).fetchone()[0] > 0
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
                 tai_len: Callable[[Path, int], str], ffmpeg: str, python: str = sys.executable, nghi_giay: float = 10.0,
                 tran_dia_gb: float = TRAN_DIA_GB, relay_bind: str | None = None,
                 cong: Callable[[], str | None] | None = None, nhip_cong_giay: float = 60.0):
        """`cong`: cổng cấu hình chạy ở ĐẦU thread worker (gọi Drive ⇒ không được chạy trong lifespan của app). Trả None = qua;
        chuỗi = bị cấm vĩnh viễn (dừng hẳn); ném lỗi = chưa kiểm được (thử lại sau `nhip_cong_giay`)."""
        self.log_db, self.jobs_db, self.data = Path(log_db), Path(jobs_db), Path(data_dir)
        self.hop = HopThu(self.data / "thay_logo_hop_thu")
        self.tai_ve, self.tai_len, self.ffmpeg, self.python = tai_ve, tai_len, ffmpeg, python
        self.nghi, self.tran_dia_gb = nghi_giay, tran_dia_gb
        self._dung = threading.Event()
        self._thread: threading.Thread | None = None
        self._con: subprocess.Popen | None = None
        self._lan_cuoi = "chua_chay"
        self.relay_bind = relay_bind
        self.relay = None
        self._don_luc = 0.0
        self._cong, self.nhip_cong = cong, nhip_cong_giay
        self._cong_qua, self._cong_cam, self._cong_thu_luc, self._cong_ly_do = cong is None, False, None, None

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
        if self.relay_bind:  # không có địa chỉ ⇒ không mở listener (không mặc định)
            from web.thay_logo_relay_server import RelayServer
            try:
                self.relay = RelayServer(self.relay_bind, lambda: self.hop)
            except ValueError as e:
                log.warning("thay logo relay: KHÔNG mở listener — %s", e)
            else:
                if not self.relay.start():
                    self.relay = None

    def stop(self, timeout: float = 15.0) -> None:
        """Không bao giờ chờ vô hạn: tắt listener relay, TERM tiến trình con, KILL nếu cần, join có trần."""
        self._dung.set()
        if self.relay is not None:
            self.relay.stop()
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
                    "relay_mo": self.relay is not None,
                    "cho_agy_cu_nhat_giay": hang_doi.tuoi_cho_agy_cu_nhat(conn)}
        finally:
            conn.close()

    @property
    def ly_do_khong_nhan(self) -> str | None:
        """Lý do worker bị CẤM nhận việc vĩnh viễn (cổng cấu hình); None = đang nhận, hoặc chưa kiểm xong / lỗi tạm."""
        return self._cong_ly_do if self._cong_cam else None

    def dat_cam(self, ly_do: str) -> None:
        """Đặt cổng về CẤM (cả khi đã qua trước đó — ví dụ phát hiện lúc sắp tạo thư mục bộ mới)."""
        self._cong_cam, self._cong_qua, self._cong_ly_do = True, False, ly_do
        self._lan_cuoi = f"cong_creative: {ly_do}"

    def _cho_cong(self) -> bool:
        """True = được nhận việc. Chưa qua cổng thì `luot_cuoi` = lý do (admin thấy ở `trang_thai()`), KHÔNG chạy `mot_luot`."""
        if self._cong_qua:
            return True
        if self._cong_cam or (self._cong_thu_luc is not None and time.monotonic() - self._cong_thu_luc < self.nhip_cong):
            return False
        self._cong_thu_luc = time.monotonic()
        self._lan_cuoi = "cong_creative: dang_kiem"  # Drive treo ⇒ admin vẫn thấy lý do worker chưa nhận việc
        try:
            ly_do = self._cong()
        except Exception as e:  # noqa: BLE001 — Drive lỗi tạm: không kết luận gì, thử lại có nhịp
            log.warning("thay logo: chưa kiểm được cổng Creative (%s) — thử lại sau %ss", type(e).__name__, self.nhip_cong)
            self._lan_cuoi = f"cong_creative: chua_kiem_duoc ({type(e).__name__})"
            return False
        if ly_do:
            log.warning("thay logo: %s — worker KHÔNG nhận việc", ly_do)
            self.dat_cam(ly_do)
            return False
        self._cong_qua = True
        return True

    def _chay(self) -> None:
        while not self._dung.is_set():
            if not self._cho_cong():
                self._dung.wait(self.nghi)
                continue
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
        if co_job_tai_dang_chay(self.jobs_db):  # nhường cả pha 1 (tải về + giải mã) lẫn pha 2
            return "nhuong_lane_tai"
        conn = self._mo()
        try:
            self._don_dinh_ky(conn)
            self._pha_1(conn)
            if not self.ram_du():
                return "cho_ram"
            return self._pha_2(conn)
        finally:
            conn.close()

    def _don_dinh_ky(self, conn) -> None:
        if time.time() - self._don_luc >= CHU_KY_DON_GIAY:
            self._don_luc = time.time()
            log.info("thay logo: dọn file nhật ký %s", nhat_ky.don_dep(conn, self.data / "thay_logo"))

    def _scratch(self, vid: int) -> Path:
        d = self.data / "thay_logo_scratch" / str(vid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ket_thuc(self, conn, vid: int, trang_thai: str, **truong) -> None:
        """Trạng thái cuối ⇒ dọn scratch + hộp thư của video đó."""
        hang_doi.dat(conn, vid, trang_thai, **truong)
        shutil.rmtree(self.data / "thay_logo_scratch" / str(vid), ignore_errors=True)
        self.hop.xoa_viec(vid)

    def _pha_1(self, conn) -> None:
        if len(hang_doi.danh_sach(conn, "cho_agy")) >= TRAN_CHO_AGY:
            return
        r = hang_doi.lay_mot(conn, "cho")
        if r is None:
            return
        try:
            goc = self.tai_ve(json.loads(r["nguon"]), self._scratch(r["id"]))
        except Exception as e:
            log.warning("thay logo: tải video %s lỗi: %s", r["id"], e)
            self._ket_thuc(conn, r["id"], "loi", loi_text=f"Không tải được video nguồn ({type(e).__name__}).")
            return
        cmd = ["nice", "-n", str(NICE), self.python, "-m", "tiktok_music_downloader.thay_logo.dat_viec_cli",
               "--video", str(goc), "--hop", str(self.hop.goc), "--job-id", str(r["id"])]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=TRAN_GIAY_PHA_1, start_new_session=True)
            ts = json.loads((p.stdout or "").strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, IndexError, json.JSONDecodeError) as e:
            log.warning("thay logo: trích khung video %s hỏng (%s): %s", r["id"], type(e).__name__,
                        getattr(e, "stderr", "") or "")
            self._ket_thuc(conn, r["id"], "loi", loi_text="Không đọc được video (file hỏng hoặc định dạng lạ).")
            return
        if not ts.get("n"):
            self._ket_thuc(conn, r["id"], "loi", loi_text="Không đọc được khung nào.")
        else:
            hang_doi.dat(conn, r["id"], "cho_agy", cho_agy_tu=time.time(), duong_dan_goc=str(goc), thong_so=json.dumps(ts))

    def _pha_2(self, conn) -> str:
        hoc_mau_agy, _ = _cv()
        from types import SimpleNamespace
        for r in hang_doi.danh_sach(conn, "cho_agy"):
            try:  # một dòng hỏng (file gốc mất, khung.json thiếu…) không được chặn cả hàng đợi
                if self.hop.doc_ket_qua(r["id"]) is None:
                    continue
                ts = SimpleNamespace(**json.loads(r["thong_so"]))
                boxes, man_ket = hoc_mau_agy.doc_ket_qua(ts, self.hop, r["id"])
                if not Path(r["duong_dan_goc"]).is_file():
                    raise FileNotFoundError("mất file gốc trong scratch")
            except Exception as e:
                log.warning("thay logo: video %s không chạy pha 2 được: %s", r["id"], e)
                self._ket_thuc(conn, r["id"], "loi", loi_text=f"Không chạy tiếp được ({type(e).__name__}).")
                continue
            hang_doi.dat(conn, r["id"], "dang_chay")
            self._chay_con(conn, r, ts, boxes, man_ket)
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
        tran = max(TRAN_GIAY_MIN, HE_SO_TRAN_GIAY * nguon.so_khung / (nguon.fps or 30.0))
        self._con = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self._ket_thuc_con(conn, r, d, ra, tran)

    def _ket_thuc_con(self, conn, r, d, ra, tran) -> None:
        try:
            out, err = self._con.communicate(timeout=tran)
        except subprocess.TimeoutExpired:
            _gui_nhom(self._con, signal.SIGKILL)
            self._con.communicate()
            self._ket_thuc(conn, r["id"], "loi", loi_text=f"Quá trần thời gian xử lý ({int(tran)}s).")
            return
        finally:
            self._con = None
        if self._dung.is_set():  # bị TERM vì tắt máy chủ ⇒ để nguyên `dang_chay`, quét khởi động lần sau làm lại
            return
        try:
            kq = json.loads((out or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            log.warning("thay logo: tiến trình con video %s không trả kết quả: %s", r["id"], (err or "")[-2000:])
            self._ket_thuc(conn, r["id"], "loi", loi_text="Xử lý video bị lỗi.")  # chi tiết chỉ ở log máy chủ
            return
        if kq.get("trang_thai") == "render" and kq.get("dau_ra"):
            try:
                file_id = self.tai_len(Path(kq["dau_ra"]), r["job_id"])
            except Exception as e:
                log.warning("thay logo: tải lên Drive video %s lỗi: %s", r["id"], e)
                self._ket_thuc(conn, r["id"], "loi", video_log_id=kq.get("video_log_id"),
                               loi_text=f"Không tải được bản thay lên Drive ({type(e).__name__}).")
                return
            nhat_ky.cap_nhat_video(conn, kq["video_log_id"], drive_file_id_ra=file_id)
            self._ket_thuc(conn, r["id"], "xong", video_log_id=kq["video_log_id"], drive_file_id_ra=file_id)
        elif kq.get("trang_thai") == "cho_nguoi":
            self._ket_thuc(conn, r["id"], "cho_nguoi", video_log_id=kq.get("video_log_id"))
        else:
            log.warning("thay logo: video %s lỗi xử lý: %s", r["id"], kq.get("loi"))
            self._ket_thuc(conn, r["id"], "loi", video_log_id=kq.get("video_log_id"), loi_text="Xử lý video bị lỗi.")


# ---------------------------------------------------------------- dựng từ cấu hình máy (app.py gọi)
def thu_muc_cua_bo(log_db: Path, job_id: int, goc_id: str, drive, kiem_creative=None) -> str:
    """Id thư mục đầu ra của bộ `job_id` (tìm-hoặc-tạo). Không tra được ⇒ ném (video bị đánh `loi`), KHÔNG rơi về thư mục gốc."""
    from tiktok_music_downloader.thay_logo import thu_muc_bo

    conn = nhat_ky.mo(log_db)
    try:
        hang_doi.khoi_tao(conn)
        return thu_muc_bo.tim_hoac_tao(conn, job_id, goc_id, drive, kiem_creative)
    finally:
        conn.close()


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
    from tiktok_music_downloader.thay_logo.drive_tl import DriveTLThat, ly_do_creative
    from tiktok_music_downloader.thay_logo.thu_muc_bo import CongCreativeCam
    from tiktok_music_downloader.watermark import find_ffmpeg

    thu_muc, drive, ffmpeg = os.environ.get(ENV_THU_MUC_RA, ""), DriveUploader(), find_ffmpeg()
    if not thu_muc or not drive.is_configured() or not ffmpeg:
        log.warning("thay logo: BẬT nhưng thiếu cấu hình (thư mục ra=%s, drive=%s, ffmpeg=%s) — không chạy worker",
                    bool(thu_muc), drive.is_configured(), bool(ffmpeg))
        return None
    drive_tl = DriveTLThat(drive)  # KHÔNG gọi mạng ở đây (lifespan của app): cổng Creative chạy ở đầu thread worker

    from tiktok_music_downloader.nguon import TRAN_DUNG_LUONG_BYTE

    def tai_ve(nguon: dict, d: Path) -> Path:  # cùng trần dung lượng video của lane tải
        return drive.download_file(nguon["file_id"], d / "goc.mp4", max_bytes=TRAN_DUNG_LUONG_BYTE)

    log_db = data_dir / "thay_logo_log.db"

    ref: list = []  # worker, gán sau khi dựng (tai_len cần nó để đặt cổng về CẤM)

    def tai_len(p: Path, job_id: int) -> str:  # tải vào thư mục con của bộ (tìm-hoặc-tạo)
        try:
            dich = thu_muc_cua_bo(log_db, job_id, thu_muc, drive_tl, lambda: ly_do_creative(drive_tl, thu_muc))
        except CongCreativeCam as e:
            ref[0].dat_cam(str(e))
            raise
        return drive_tl.tai_len(p, dich)

    from web.thay_logo_relay_server import ENV_BIND
    w = ThayLogoWorker(data_dir / "thay_logo_log.db", jobs_db, data_dir, tai_ve=tai_ve, tai_len=tai_len, ffmpeg=ffmpeg,
                          relay_bind=os.environ.get(ENV_BIND) or None,
                          cong=lambda: ly_do_creative(drive_tl, thu_muc))
    ref.append(w)
    return w
