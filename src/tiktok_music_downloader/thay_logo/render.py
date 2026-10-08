"""Render: chỉ trên các khung đã qua MỌI cổng — tô lấp vùng watermark bằng nền thật của khung lân cận, rồi dán logo A2.

Chép từ skill của user `logo-replacer/scripts/replace_logo.py` (user cho chép, `plan.md` §0): `temporal_fill`, `paste`, cửa sổ
khung trượt, ống ffmpeg giữ nguyên tiếng. Bỏ các nhánh không dùng (xoay, keyframe tay, các kiểu fill khác).
Logo mặc định = A2 "chữ trên tấm nền mờ" (USER CHỐT 08/10 14:27), co giãn 'contain' vào box nới `plate_pad` px.
Video gốc KHÔNG bị đụng: luôn ghi ra file mới.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

LOGO_A2 = Path(__file__).resolve().parent / "tai_nguyen" / "logo_A2_tam_nen.png"
PAD_TO = 3  # px tô lấp quanh box (mặc định skill)
PAD_TAM_NEN = 4  # tấm nền A2 nới quanh box — cổng phụ đề có thể hạ xuống 2 (trường `plate_pad` của khung)
CUA_SO_THOI_GIAN, DUNG_SAI_TINH = 45, 4.0
RAM_CUA_SO = 5e8  # trần bộ đệm khung (byte); mini chạy chung lane tải ⇒ nửa mức 1GB của skill


def doc_logo(duong_dan: Path = LOGO_A2) -> tuple[np.ndarray, np.ndarray]:
    """PNG RGBA ⇒ (bgr float32, alpha float32 [0,1] HxWx1), cắt viền trong suốt."""
    img = cv2.imread(str(duong_dan), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        raise ValueError(f"logo phải là PNG có kênh alpha: {duong_dan}")
    a = img[:, :, 3]
    ys, xs = np.where(a > 8)
    img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return img[:, :, :3].astype(np.float32), (img[:, :, 3:4].astype(np.float32) / 255.0)


def dan_logo_contain(frame: np.ndarray, logo: tuple[np.ndarray, np.ndarray], x: int, y: int, w: int, h: int) -> None:
    """Co logo vừa khít trong (x, y, w, h) giữ tỉ lệ, căn giữa, trộn alpha. Phần tràn khỏi khung hình bị cắt."""
    bgr, a = logo
    s = min(w / bgr.shape[1], h / bgr.shape[0])
    lw, lh = max(1, round(bgr.shape[1] * s)), max(1, round(bgr.shape[0] * s))
    interp = cv2.INTER_AREA if lw < bgr.shape[1] else cv2.INTER_CUBIC
    b = cv2.resize(bgr, (lw, lh), interpolation=interp)
    al = cv2.resize(a, (lw, lh), interpolation=interp)[:, :, None]
    lx, ly = x + (w - lw) // 2, y + (h - lh) // 2
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = max(0, lx), max(0, ly), min(W, lx + lw), min(H, ly + lh)
    if x1 <= x0 or y1 <= y0:
        return
    sb, sa = b[y0 - ly:y1 - ly, x0 - lx:x1 - lx], al[y0 - ly:y1 - ly, x0 - lx:x1 - lx]
    frame[y0:y1, x0:x1] = (sb * sa + frame[y0:y1, x0:x1].astype(np.float32) * (1 - sa)).astype(np.uint8)


class _CuaSoKhung:
    """Đọc tuần tự, giữ khung gốc i−r … i+r trong RAM (nguồn nền thật cho tô lấp)."""

    def __init__(self, cap, r: int):
        self.cap, self.r, self.buf, self.next, self.eof = cap, r, {}, 0, False

    def get(self, i: int):
        while not self.eof and self.next <= i + self.r:
            ok, f = self.cap.read()
            if not ok:
                self.eof = True
                break
            self.buf[self.next] = f
            self.next += 1
        for k in [k for k in self.buf if k < i - self.r]:
            del self.buf[k]
        return self.buf.get(i)


def _to_lap_thoi_gian(dst, win, i, che: dict[int, list[tuple]], vung, ring=8, want=3) -> float:
    """Trung vị cùng điểm ảnh ở khung lân cận mà KHÔNG box nào che và vành quanh vùng gần như đứng yên (≤ DUNG_SAI_TINH);
    phần không lấy được thì inpaint. Trả tỉ lệ điểm ảnh lấy từ khung khác. Chép `temporal_fill` của skill."""
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = vung
    rx0, ry0, rx1, ry1 = max(0, x0 - ring), max(0, y0 - ring), min(W, x1 + ring), min(H, y1 + ring)
    hole = (slice(y0 - ry0, y1 - ry0), slice(x0 - rx0, x1 - rx0))
    g_cur = cv2.cvtColor(win.buf[i][ry0:ry1, rx0:rx1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    ring_cur = np.ones(g_cur.shape, bool)
    ring_cur[hole] = False
    n_ring = ring_cur.sum()
    cands, masks = [], []
    count = np.zeros((y1 - y0, x1 - x0), np.int32)
    for d in sorted((k for k in range(-win.r, win.r + 1) if k), key=lambda k: (abs(k), k)):
        src = win.buf.get(i + d)
        if src is None:
            continue
        cov = np.zeros(g_cur.shape, bool)
        for bx, by, bw, bh in che.get(i + d, ()):
            p = PAD_TO + 2
            cov[max(0, by - p - ry0):max(0, by + bh + p - ry0), max(0, bx - p - rx0):max(0, bx + bw + p - rx0)] = True
        avail = ~cov[hole]
        if not (avail & (count < want)).any():
            continue
        rmask = ring_cur & ~cov
        if n_ring and rmask.sum() < 0.3 * n_ring:
            continue
        sw = src[ry0:ry1, rx0:rx1]
        if n_ring and np.abs(g_cur - cv2.cvtColor(sw, cv2.COLOR_BGR2GRAY).astype(np.float32))[rmask].mean() > DUNG_SAI_TINH:
            continue
        cands.append(sw[hole].astype(np.float32))
        masks.append(avail)
        count += avail
        if count.min() >= want:
            break
    got = count > 0
    if cands:
        stack = np.stack(cands)
        stack[~np.stack(masks)] = np.nan
        dst[y0:y1, x0:x1][got] = np.clip(np.nanmedian(stack[:, got], axis=0), 0, 255).astype(np.uint8)
    if not got.all():
        m = 24
        wx0, wy0, wx1, wy1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
        mask = np.zeros((wy1 - wy0, wx1 - wx0), np.uint8)
        mask[y0 - wy0:y1 - wy0, x0 - wx0:x1 - wx0][~got] = 255
        dst[wy0:wy1, wx0:wx1] = cv2.inpaint(dst[wy0:wy1, wx0:wx1], mask, 3, cv2.INPAINT_TELEA)
    return float(got.mean())


def gom_khung_render(cac_vet: list[list[dict]]) -> dict[int, list[dict]]:
    """Nhiều vết (2 watermark/video) ⇒ mỗi khung một danh sách box cần thay."""
    out: dict[int, list[dict]] = {}
    for render in cac_vet:
        for e in render:
            out.setdefault(e["frame"], []).append(e)
    return out


def render_video(video: str, khung_render: dict[int, list[dict]], dau_ra: str, ffmpeg: str,
                 logo: tuple[np.ndarray, np.ndarray] | None = None, luong: int = 2, crf: int = 18) -> dict:
    """Ghi `dau_ra` (H.264 + tiếng gốc copy). Khung không có trong `khung_render` giữ nguyên từng điểm ảnh trước mã hoá.
    Trả số đếm cho nhật ký. ffmpeg lỗi ⇒ RuntimeError (không để file dở được coi là xong)."""
    logo = logo or doc_logo()
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise ValueError(f"không mở được video: {video}")
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    che = {i: [(e["x"], e["y"], e["w"], e["h"]) for e in es] for i, es in khung_render.items()}
    r = max(1, min(CUA_SO_THOI_GIAN, int(RAM_CUA_SO / (W * H * 3) - 1) // 2))
    cmd = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", f"{fps}", "-i", "pipe:0", "-i", video, "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264",
           "-crf", str(crf), "-preset", "medium", "-threads", str(luong), "-pix_fmt", "yuv420p", "-c:a", "copy",
           "-movflags", "+faststart", dau_ra]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    win, i, nguon_that = _CuaSoKhung(cap, r), 0, []
    try:
        while True:
            f = win.get(i)
            if f is None:
                break
            f = f.copy()
            for e in khung_render.get(i, ()):
                x, y, w, h = e["x"], e["y"], e["w"], e["h"]
                vung = (max(0, x - PAD_TO), max(0, y - PAD_TO), min(W, x + w + PAD_TO), min(H, y + h + PAD_TO))
                if vung[2] > vung[0] and vung[3] > vung[1]:
                    nguon_that.append(_to_lap_thoi_gian(f, win, i, che, vung))
                p = e.get("plate_pad", PAD_TAM_NEN)
                dan_logo_contain(f, logo, x - p, y - p, w + 2 * p, h + 2 * p)
            try:
                proc.stdin.write(f.tobytes())
            except BrokenPipeError:  # ffmpeg chết sớm (đường ra hỏng, đĩa đầy…) ⇒ dừng, lỗi thật lấy từ rc + stderr bên dưới
                break
            i += 1
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:  # ffmpeg đã chết giữa chừng — mã thoát bên dưới mới là bằng chứng
            pass
        loi = proc.stderr.read().decode(errors="replace")
        rc = proc.wait()
        cap.release()
    if rc != 0:
        raise RuntimeError(f"ffmpeg rc={rc}: {loi[-500:]}")
    return {"so_khung": i, "khung_thay": len(khung_render),
            "ti_le_nen_that": round(float(np.mean(nguon_that)), 3) if nguon_that else None}
