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

from tiktok_music_downloader.thay_logo import ap_vao_bo, canh_relay, hang_doi, nhat_ky, nhip_relay, tai_len_phien, tu_ap_vao_bo
from tiktok_music_downloader.thay_logo import de_khi_biet_bat, khoanh
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
# Swap macOS cấp ĐỘNG: `vm.swapusage total` là phần đã cấp, không phải trần ⇒ máy RAM rộng (ca-n 24 GB, đo 19/10: free 74%,
# swap 2048M dùng 648M) vẫn có `free` swap < 1 GiB mà không thiếu bộ nhớ. RAM trống ≥ 60% hoặc chưa cấp swap ⇒ miễn vế swap.
RAM_RONG_MIEN_SWAP_PCT = 60
NICE = 10
TRAN_CHO_AGY = 5  # pha 1 chỉ tải trước khi số video đang chờ agy < trần này — relay tắt thì không dồn file gốc vào đĩa
# agy trượt: relay nộp lỗi (mã enum) về hộp thư, mini đếm. Lỗi TẠM THỜI (agy 503, hết quota, mạng chớp) trên main chỉ làm video chờ rồi tự lành,
# nên KHÔNG được phán `loi` sớm: cần ĐỦ TRAN_LOI_AGY lỗi VÀ lỗi đầu đã cách ≥ GIAN_CACH_LOI_AGY_GIAY (relay thử lại mỗi ~20 s nên
# riêng số lần thì chỉ ~1 phút). Ngoại lệ: `model_khong_nhan` (model bị gỡ) là lỗi cứng không phụ thuộc video/thời điểm ⇒ `loi` ngay lần 1.
TRAN_LOI_AGY = 3
GIAN_CACH_LOI_AGY_GIAY = 15 * 60
MA_LOI_CUNG = "model_khong_nhan"
# Video đứng `cho_agy` quá hạn này mà chưa có kết quả ⇒ relay chết / không chạy. 3 giờ: dài hơn nhiều so với 2 lô agy nối tiếp
# (trần 900 s mỗi lô + hàng chờ ≤ TRAN_CHO_AGY), nên không giết nhầm hàng đang xếp; đủ ngắn để sáng hôm sau người dùng thấy lỗi rõ.
HAN_CHO_AGY_GIAY = 3 * 3600
LY_DO_HET_HAN_AGY = "Máy nhận diện logo (relay) không phản hồi — hãy tạo lượt mới sau khi máy đó chạy lại."
LY_DO_LOI_AGY = {  # câu cố định cho từng mã lỗi (mã lạ ⇒ câu chung); chi tiết chỉ ở log máy chủ
    "model_khong_nhan": "Máy nhận diện logo báo model không còn dùng được — cần quản trị đổi cấu hình.",
    "het_gio": "Máy nhận diện logo xử lý quá lâu (hết giờ) và vẫn lỗi sau hơn 15 phút thử lại.",
}
LY_DO_LOI_AGY_CHUNG = "Máy nhận diện logo (agy) vẫn lỗi sau hơn 15 phút thử lại."
TRAN_GIAY_PHA_1 = 180
CHU_KY_DON_GIAY = 600
CHU_KY_DON_PHIEN_GIAY = 3600  # thread `tl-don-phien` (nguồn "Tải từ máy"): dọn phiên bỏ dở + file nhập đã dùng
NGUONG_CONG_LOI_ERROR = 10  # số lần kiểm cổng Creative trượt LIÊN TIẾP thì nâng log từ warning lên error (một lần)
TRAN_GIAY_MIN, HE_SO_TRAN_GIAY = 600, 10  # trần thời gian tiến trình con = max(10 phút, 10 × độ dài video)


NGUON_DA_DOI_CAU = "Bản trong bộ đã đổi từ lúc tạo lượt — tạo lượt mới."


class NguonVaoBoDaDoi(Exception):
    """File tải về của nguồn "Đã vào bộ" không khớp md5 đã chụp lúc tạo lượt."""


def kiem_md5_nguon_vao_bo(nguon: dict, duong_dan) -> None:
    """md5 của file ĐÃ TẢI phải bằng `nguon["md5"]` (ảnh chụp lúc tạo lượt). Thiếu md5 trong ảnh chụp cũng coi là lệch (không có gì để tin)."""
    import hashlib
    h = hashlib.md5()  # noqa: S324 — đối chiếu checksum Drive (md5Checksum), không dùng cho bảo mật
    with open(duong_dan, "rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    if not nguon.get("md5") or h.hexdigest() != str(nguon["md5"]).lower():
        raise NguonVaoBoDaDoi(f"md5 file tải {h.hexdigest()} khác ảnh chụp {nguon.get('md5')}")


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
    """`memory_pressure` free ≥ 30% VÀ (swap trống ≥ 1 GiB, miễn khi free ≥ 60% hoặc chưa cấp swap). Không đo được ⇒ coi như
    THIẾU (không chạy pha nặng)."""
    try:
        mp = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        free = int(re.search(r"free percentage:\s*(\d+)", mp).group(1))
        sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=10).stdout
        swap_tong = float(re.search(r"total = ([\d.]+)M", sw).group(1))
        swap_trong = float(re.search(r"free = ([\d.]+)M", sw).group(1))
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        log.warning("thay logo: không đo được RAM/swap — không chạy pha nặng lượt này")
        return False
    if free < RAM_FREE_TOI_THIEU_PCT:
        return False
    return free >= RAM_RONG_MIEN_SWAP_PCT or swap_tong == 0 or swap_trong >= SWAP_TRONG_TOI_THIEU_MB


def _gui_nhom(con: subprocess.Popen, sig) -> None:
    try:
        os.killpg(con.pid, sig)
    except ProcessLookupError:
        pass


class ThayLogoWorker:
    def __init__(self, log_db: Path, jobs_db: Path, data_dir: Path, *, tai_ve: Callable[[dict, Path], Path],
                 tai_len: Callable[[Path, int], str], ffmpeg: str, python: str = sys.executable, nghi_giay: float = 10.0,
                 tran_dia_gb: float = TRAN_DIA_GB, relay_bind: str | None = None,
                 cong: Callable[[], str | None] | None = None, nhip_cong_giay: float = 60.0, drive_tl=None):
        """`cong`: cổng cấu hình chạy ở ĐẦU thread worker (gọi Drive ⇒ không được chạy trong lifespan của app). Trả None = qua;
        chuỗi = bị cấm vĩnh viễn (dừng hẳn); ném lỗi = chưa kiểm được (thử lại sau `nhip_cong_giay`)."""
        self.log_db, self.jobs_db, self.data = Path(log_db), Path(jobs_db), Path(data_dir)
        self.hop = HopThu(self.data / "thay_logo_hop_thu")
        self.tai_ve, self.tai_len, self.ffmpeg, self.python = tai_ve, tai_len, ffmpeg, python
        self.drive_tl = drive_tl  # adapter Drive dùng chung: route chụp md5/size nguồn "Đã vào bộ" lúc tạo lượt (None ⇒ route báo 503)
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
        self._cong_loi_lien_tiep = 0
        self._thread_don_phien: threading.Thread | None = None

    def _mo(self) -> sqlite3.Connection:
        conn = nhat_ky.mo(self.log_db)
        hang_doi.khoi_tao(conn)
        return conn

    # ---------------------------------------------------------------- vòng đời
    def start(self) -> None:
        conn = self._mo()
        try:
            log.info("thay logo: quét khởi động %s", hang_doi.quet_khoi_dong(conn))
            log.info("thay logo: đè khi biết chỗ = %s (THAY_LOGO_DE_KHI_BIET=%r)", "BẬT" if de_khi_biet_bat(os.environ.get(
                "THAY_LOGO_DE_KHI_BIET")) else "TẮT", os.environ.get("THAY_LOGO_DE_KHI_BIET"))
        finally:
            conn.close()
        self._thread = threading.Thread(target=self._chay, name="thay-logo-worker", daemon=True)
        self._thread.start()
        if ap_vao_bo.dang_bat() and self.drive_tl is not None:  # cờ TẮT ⇒ không đụng Drive, khoá cũ để nguyên
            moc = time.time()  # khoá lấy TRƯỚC mốc này là của tiến trình trước (đã chết) ⇒ quét xong thì xoá
            threading.Thread(target=self._quet_ap, args=(moc,), name="tl-ap", daemon=True).start()
        if self.drive_tl is not None:  # KHÔNG phụ thuộc cờ TL_TAI_TU_MAY (tắt cờ để lui không được làm kẹt file) và KHÔNG gắn vào `mot_luot`
            self._thread_don_phien = threading.Thread(target=self._chay_don_phien, name="tl-don-phien", daemon=True)
            self._thread_don_phien.start()
        if self.relay_bind:  # không có địa chỉ ⇒ không mở listener (không mặc định)
            from web.thay_logo_relay_server import RelayServer
            try:
                self.relay = RelayServer(self.relay_bind, lambda: self.hop)
            except ValueError as e:
                log.warning("thay logo relay: KHÔNG mở listener — %s", e)
            else:
                if not self.relay.start():
                    self.relay = None

    # ---------------------------------------------------------------- áp vào bộ (thread `tl-ap`, không chung hàng xử lý video)
    def _quet_ap(self, moc: float) -> None:
        """Khởi động: chạy tiếp mọi lượt áp/hoàn tác dở theo phép đo Drive, rồi xoá khoá cũ (Drive gọi ở đây, không trong lifespan)."""
        try:
            conn = self._mo()
            try:
                log.info("thay logo áp: quét dở dang %s", ap_vao_bo.quet_do_dang(conn, self.drive_tl, moc))
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 — Drive lỗi lúc khởi động: hàng giữ chiều, người dùng bấm "Tiếp tục"
            log.exception("thay logo áp: quét dở dang lỗi")

    # ---------------------------------------------------------------- dọn nguồn "Tải từ máy" (thread `tl-don-phien`, riêng hoàn toàn)
    def _chay_don_phien(self) -> None:
        """Mỗi giờ: dọn phiên bỏ dở, quét theo thẻ, dọn file nhập đã dùng. Thread RIÊNG chứ không nằm trong `_don_dinh_ky`/`mot_luot`: `mot_luot`
        thoát sớm khi hết đĩa / nhường lane tải, và `_chay` không gọi nó khi cổng Creative chưa qua — dọn sẽ TẮT ÂM THẦM, phiên `mo` đọng,
        trần chờ khoá người dùng. Lỗi một lượt không giết thread."""
        while not self._dung.is_set():
            try:
                conn = self._mo()
                try:
                    kq = tai_len_phien.don_mot_luot(conn, self.drive_tl)
                finally:
                    conn.close()
                if any(v for v in kq.values() if not isinstance(v, dict)) or any(kq["quet_the"].values()):
                    log.info("thay logo: dọn tải từ máy %s", kq)
            except Exception:  # noqa: BLE001 — lượt sau thử lại
                log.exception("thay logo: dọn tải từ máy lỗi")
            self._dung.wait(CHU_KY_DON_PHIEN_GIAY)

    def bat_dau_ap(self, job_id: int) -> threading.Thread:
        """Route gọi SAU khi đã ghi chiều ý định + lấy khoá bộ; thread nhả khoá trong `finally`."""
        return ap_vao_bo.chay_nen(self._mo, self.drive_tl, job_id)

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
        if self._thread_don_phien is not None:
            self._thread_don_phien.join(timeout=2.0)  # đang giữa một lời gọi Drive thì không chờ: thread daemon, lượt sau khởi động làm tiếp

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
        except Exception as e:  # noqa: BLE001 — Drive lỗi tạm: không kết luận gì, thử lại có nhịp (fail-closed: không nhận việc)
            self._cong_loi_lien_tiep += 1
            if self._cong_loi_lien_tiep == 1:
                log.warning("thay logo: chưa kiểm được cổng Creative (%s) — thử lại sau %ss", type(e).__name__, self.nhip_cong)
            elif self._cong_loi_lien_tiep == NGUONG_CONG_LOI_ERROR:  # đúng MỘT lần: đừng ồn mỗi nhịp, nhưng đừng để im vô hạn
                log.error("thay logo: cổng Creative vẫn chưa kiểm được sau %d lần liên tiếp (%s) — worker KHÔNG nhận việc, cần người xem",
                          self._cong_loi_lien_tiep, type(e).__name__)
            self._lan_cuoi = f"cong_creative: chua_kiem_duoc ({type(e).__name__})"
            return False
        self._cong_loi_lien_tiep = 0  # kiểm được (qua hoặc cấm) ⇒ chuỗi lỗi tạm đứt
        if ly_do:
            log.warning("thay logo: %s — worker KHÔNG nhận việc", ly_do)
            self.dat_cam(ly_do)
            return False
        self._cong_qua = True
        return True

    def _chay(self) -> None:
        while not self._dung.is_set():
            self._canh_relay()  # TRƯỚC MỌI cổng (cả cổng cấu hình Drive): canh không cần Drive, cổng nào cũng không được làm nó câm
            if not self._cho_cong():
                self._dung.wait(self.nghi)
                continue
            self._tu_ap()  # TRƯỚC cổng đĩa / nhường lane tải: chỉ gọi Drive, không tốn CPU — đĩa đầy không được hoãn việc trả về bộ
            try:
                self._lan_cuoi = self.mot_luot()
            except Exception:  # một video hỏng không được giết worker
                log.exception("thay logo: lượt lỗi")
                self._lan_cuoi = "loi_luot"
            self._dung.wait(self.nghi)

    # ---------------------------------------------------------------- tự trả video Đạt về bộ gốc
    def _chu_cua(self, video_ids: list[str]) -> dict:
        from web.thay_logo_routes import chu_video_vao_bo  # nạp muộn: routes không import worker, nhưng giữ worker nạp nhẹ
        r = chu_video_vao_bo(self.jobs_db, video_ids)
        if r is None:  # jobs.db tạm không đọc được ⇒ lỗi TẠM, vòng sau thử lại
            raise ap_vao_bo.LoiAp(503, "Chưa kiểm được chủ video — thử lại sau.")
        return r

    def _tu_ap(self) -> None:
        """Một lượt quét `tu_ap_vao_bo` (cờ `TL_AP_VAO_BO` tắt hoặc Drive chưa cấu hình ⇒ không làm gì). Không bao giờ ném."""
        drive = self.drive_tl
        if not ap_vao_bo.dang_bat() or drive is None or not drive.dang_cau_hinh():
            return
        try:
            conn = self._mo()
            try:
                tu_ap_vao_bo.thu_tu_ap(conn, self._chu_cua, self.bat_dau_ap)
            finally:
                conn.close()
        except Exception:
            log.exception("thay logo: vòng tự áp vào bộ lỗi")

    def _canh_relay(self) -> None:
        """Báo Discord khi có video chờ máy định vị quá lâu mà chưa có kết quả. Chỉ khi worker có relay listener (mini). Không ném."""
        if self.relay_bind is None:
            return
        try:
            conn = self._mo()
            try:
                canh_relay.thu_canh(conn, self.hop, nhip_relay.NHIP.tuoi())
            finally:
                conn.close()
        except Exception:
            log.exception("thay logo: vòng canh relay lỗi")

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
            self._quet_cho_agy(conn)
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
            log.info("thay logo: dọn video giữ để sửa %s", khoanh.don_video_sua(conn, self.data))

    def _scratch(self, vid: int) -> Path:
        d = self.data / "thay_logo_scratch" / str(vid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ket_thuc(self, conn, vid: int, trang_thai: str, **truong) -> None:
        """Trạng thái cuối ⇒ dọn scratch + hộp thư của video đó."""
        hang_doi.dat(conn, vid, trang_thai, **truong)
        shutil.rmtree(self.data / "thay_logo_scratch" / str(vid), ignore_errors=True)
        self.hop.xoa_viec(vid)

    def _quet_cho_agy(self, conn) -> None:
        """Video `cho_agy` không được kẹt vô hạn. Có kết quả ⇒ để pha 2 xử lý (kết quả thắng lỗi). Chưa có kết quả:
          · lỗi cứng `model_khong_nhan` ⇒ `loi` ngay; các lỗi khác ⇒ `loi` khi đủ TRAN_LOI_AGY lần VÀ cách lỗi đầu ≥ GIAN_CACH_LOI_AGY_GIAY;
          · đứng quá HAN_CHO_AGY_GIAY (relay không phản hồi) ⇒ `loi` với lý do khác.
        Dùng trạng thái `loi` sẵn có; trạng thái chỉ đổi qua `_ket_thuc` (ghi DB xong mới dọn hộp thư)."""
        bay_gio = time.time()
        for r in hang_doi.danh_sach(conn, "cho_agy"):
            try:
                if self.hop.doc_ket_qua(r["id"]) is not None:
                    continue
                loi, ly_do = self.hop.doc_loi(r["id"]), None
                if loi and (loi["ma_cuoi"] == MA_LOI_CUNG
                            or (loi["so"] >= TRAN_LOI_AGY and bay_gio - loi["dau_luc"] >= GIAN_CACH_LOI_AGY_GIAY)):
                    log.warning("thay logo: video %s — agy trượt %d lần (mã cuối %s)", r["id"], loi["so"], loi["ma_cuoi"])
                    ly_do = LY_DO_LOI_AGY.get(loi["ma_cuoi"], LY_DO_LOI_AGY_CHUNG)
                elif r["cho_agy_tu"] is not None and bay_gio - r["cho_agy_tu"] > HAN_CHO_AGY_GIAY:
                    log.warning("thay logo: video %s đứng cho_agy quá %d giây — relay không phản hồi", r["id"], HAN_CHO_AGY_GIAY)
                    ly_do = LY_DO_HET_HAN_AGY
                if ly_do is None:
                    continue
                if self.hop.doc_ket_qua(r["id"]) is not None:  # đọc lại ngay trước khi chốt: thu hẹp race với relay vừa nộp kết quả
                    continue
                self._ket_thuc(conn, r["id"], "loi", loi_text=ly_do)
            except Exception as e:  # một dòng hỏng không chặn các dòng sau
                log.warning("thay logo: quét cho_agy video %s lỗi (%s): %s", r["id"], type(e).__name__, e)

    def _pha_1(self, conn) -> None:
        if len(hang_doi.danh_sach(conn, "cho_agy")) >= TRAN_CHO_AGY:
            return
        r = hang_doi.lay_mot(conn, "cho")
        if r is None:
            return
        try:
            nguon = json.loads(r["nguon"])
            goc = self.tai_ve(nguon, self._scratch(r["id"]))
            if nguon.get("kieu") == "vao_bo":
                kiem_md5_nguon_vao_bo(nguon, goc)
        except NguonVaoBoDaDoi as e:  # bản trong bộ khác ảnh chụp lúc tạo lượt: KHÔNG xử lý (đợt áp sẽ đối chiếu chính ảnh chụp này)
            log.warning("thay logo: video %s — %s", r["id"], e)
            self._ket_thuc(conn, r["id"], "loi", loi_text=NGUON_DA_DOI_CAU)
            return
        except Exception as e:
            log.warning("thay logo: tải video %s lỗi (%s): %s", r["id"], type(e).__name__, e)
            self._ket_thuc(conn, r["id"], "loi", loi_text="Không tải được video nguồn từ Drive.")
            return
        cmd = ["nice", "-n", str(NICE), self.python, "-m", "tiktok_music_downloader.thay_logo.dat_viec_cli",
               "--video", str(goc), "--hop", str(self.hop.goc), "--job-id", str(r["id"])]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=TRAN_GIAY_PHA_1, start_new_session=True)
            ts = json.loads((p.stdout or "").strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, IndexError, json.JSONDecodeError) as e:
            log.warning("thay logo: trích khung video %s hỏng (%s): %s", r["id"], type(e).__name__,
                        getattr(e, "stderr", "") or "")
            self._ket_thuc(conn, r["id"], "loi", loi_text="Không đọc được video này (file hỏng hoặc định dạng lạ).")
            return
        if not ts.get("n"):
            self._ket_thuc(conn, r["id"], "loi", loi_text="Không đọc được hình trong video.")
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
                log.warning("thay logo: video %s không chạy pha 2 được (%s): %s", r["id"], type(e).__name__, e)
                self._ket_thuc(conn, r["id"], "loi", loi_text="Máy không xử lý tiếp được video này.")
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

    def _giu_video(self, r, video_log_id, ra) -> bool:
        """Giữ video gốc (+ bản ra) cho người xem lại / khoanh — dời ra khỏi scratch TRƯỚC `_ket_thuc` (hàm đó dọn scratch ở mọi nhánh).
        Chỉ gọi ở nhánh thành công. Giữ trượt thì job vẫn xong (màn khoanh tải lại từ Drive sau); trả False + log, không im lặng."""
        if not video_log_id:
            return False
        try:
            khoanh.giu_video(self.data, video_log_id, Path(r["duong_dan_goc"]), ra)
            return True
        except OSError as e:
            log.warning("thay logo: không giữ được video %s để sửa (%s): %s", r["id"], type(e).__name__, e)
            return False

    def _ket_thuc_con(self, conn, r, d, ra, tran) -> None:
        try:
            out, err = self._con.communicate(timeout=tran)
        except subprocess.TimeoutExpired:
            _gui_nhom(self._con, signal.SIGKILL)
            self._con.communicate()
            self._ket_thuc(conn, r["id"], "loi", loi_text="Xử lý quá lâu nên đã dừng.")
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
                log.warning("thay logo: tải lên Drive video %s lỗi (%s): %s", r["id"], type(e).__name__, e)
                self._ket_thuc(conn, r["id"], "loi", video_log_id=kq.get("video_log_id"),
                               loi_text="Không tải được bản đã thay lên Drive.")
                return
            nhat_ky.cap_nhat_video(conn, kq["video_log_id"], drive_file_id_ra=file_id)
            self._giu_video(r, kq.get("video_log_id"), Path(kq["dau_ra"]))
            self._ket_thuc(conn, r["id"], "xong", video_log_id=kq["video_log_id"], drive_file_id_ra=file_id)
        elif kq.get("trang_thai") == "cho_nguoi":
            self._giu_video(r, kq.get("video_log_id"), None)
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
                          cong=lambda: ly_do_creative(drive_tl, thu_muc), drive_tl=drive_tl)
    ref.append(w)
    return w
