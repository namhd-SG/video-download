"""ffmpeg-based watermarking: animated text overlay only.

Used by the downloader as a post-processing step. The overlay is optional;
when nothing is configured, apply_watermark() is a no-op.

This is the text-only build: the static corner logo and animated image
overlays have been removed — the only overlay is the animated text.

Note on text rendering: Homebrew ffmpeg often ships without libfreetype, so
the `drawtext` filter is unavailable. We dodge that by pre-rendering the text
to a transparent PNG via Pillow and overlaying it like any other image.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("ttmd")

# Bold TTF used by Pillow to render the watermark text. Candidates are probed
# in order (macOS → Windows → Linux); the first that loads wins. If none do,
# Pillow's bundled bitmap font is the last resort — low quality but never fails.
# Cross-platform so the same build works on Windows and macOS.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",          # macOS
    "/System/Library/Fonts/Helvetica.ttc",                        # macOS
    "C:/Windows/Fonts/arialbd.ttf",                               # Windows
    "C:/Windows/Fonts/arial.ttf",                                 # Windows
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Linux
)
TEXT_FONT_SIZE = 48
TEXT_PADDING_PX = 8
TEXT_BORDER_PX = 2

# Animation visuals — tweak constants here to change the look across the app.
ORBIT_PERIOD_SEC = 6.0     # seconds per full revolution
ORBIT_RADIUS_FRAC = 0.25   # radius = 25% of min(width, height)
DEFAULT_OPACITY = 0.35     # animated text — subtle but visible

# Animated-overlay motion patterns. Each maps to a (x_expr, y_expr) pair that
# uses placeholder vars {W} {H} {w} {h} {MIN} {RAD} {T}; _expand() substitutes
# the right ffmpeg variable names depending on overlay vs drawtext context.
PATTERNS: dict[str, tuple[str, str]] = {
    # Classic circle around the center.
    "orbit": (
        "{W}/2+{MIN}*{RAD}*cos(2*PI*t/{T})-{w}/2",
        "{H}/2+{MIN}*{RAD}*sin(2*PI*t/{T})-{h}/2",
    ),
    # Lemniscate of Gerono — infinity symbol lying flat.
    "figure-8": (
        "{W}/2+{MIN}*{RAD}*cos(2*PI*t/{T})-{w}/2",
        "{H}/2+{MIN}*{RAD}*sin(2*PI*t/{T})*cos(2*PI*t/{T})-{h}/2",
    ),
    # Horizontal ping-pong across the middle.
    "bounce": (
        "{W}/2+{MIN}*{RAD}*sin(2*PI*t/{T})-{w}/2",
        "{H}/2-{h}/2",
    ),
    # Diagonal sweep — moves on a single line from upper-left ↔ lower-right.
    "diagonal": (
        "{W}/2+{W}*0.35*sin(2*PI*t/{T})-{w}/2",
        "{H}/2+{H}*0.35*sin(2*PI*t/{T})-{h}/2",
    ),
    # Spiral — radius grows from 0 to ORBIT_RADIUS_FRAC over one period.
    "spiral": (
        "{W}/2+{MIN}*{RAD}*(mod(t\\,{T})/{T})*cos(2*PI*t/{T})-{w}/2",
        "{H}/2+{MIN}*{RAD}*(mod(t\\,{T})/{T})*sin(2*PI*t/{T})-{h}/2",
    ),
    # No motion — pinned to dead center. Cheapest, least distracting.
    "static-center": (
        "({W}-{w})/2",
        "({H}-{h})/2",
    ),
}
DEFAULT_PATTERN = "orbit"

# Vietnamese labels for the UI dropdown — keys must match PATTERNS exactly.
PATTERN_LABELS_VI: dict[str, str] = {
    "orbit":         "Xoay vòng tròn",
    "figure-8":      "Hình số 8",
    "bounce":        "Lắc ngang qua lại",
    "diagonal":      "Trượt chéo",
    "spiral":        "Xoắn ốc lan ra",
    "static-center": "Đứng yên giữa video",
}

# Output quality presets applied AFTER the overlay. These FORCE the long side to
# the target (1280 for HD, 1920 for FullHD), upscaling small sources too. The
# trade-off vs. "never upscale": every output ends up the same frame size, so
# the text overlay lands at a consistent on-screen pixel size regardless of how
# the source was filmed.
def _force_long_side_scale(long: int) -> str:
    # Branch on orientation. Use trunc(.../2)*2 to keep dimensions even (h.264).
    return (
        f"scale=w='if(gt(iw\\,ih)\\,{long}\\,trunc({long}*iw/ih/2)*2)'"
        f":h='if(gt(iw\\,ih)\\,trunc({long}*ih/iw/2)*2\\,{long})'"
    )

QUALITY_FILTERS: dict[str, str | None] = {
    "original": None,
    "fullhd":   _force_long_side_scale(1920),
    "hd":       _force_long_side_scale(1280),
}
DEFAULT_QUALITY = "hd"


def _expand(expr: str) -> str:
    """Replace placeholders with ffmpeg's overlay-filter variable names."""
    return expr.format(
        W="main_w", H="main_h", w="overlay_w", h="overlay_h",
        MIN="min(main_w\\,main_h)",
        RAD=ORBIT_RADIUS_FRAC, T=ORBIT_PERIOD_SEC,
    )


@dataclass(frozen=True)
class WatermarkConfig:
    """User-facing watermark settings. Leave fields empty/None to skip them.

    Text-only build: the single overlay is the animated text. `text_pattern`
    selects its motion; see PATTERNS.keys() for valid names. Invalid names fall
    back to DEFAULT_PATTERN.
    """
    animated_text: str | None = None
    text_pattern: str = DEFAULT_PATTERN
    output_quality: str = DEFAULT_QUALITY
    opacity: float = DEFAULT_OPACITY

    @property
    def is_empty(self) -> bool:
        """True when there's literally nothing to do — no overlay AND original res."""
        has_overlay = bool(self.animated_text)
        return not has_overlay and self.output_quality == "original"


# Common ffmpeg install locations to probe when it isn't on PATH. macOS .app
# bundles launched from Finder get a minimal PATH (/usr/bin:/bin:…) that omits
# Homebrew, so shutil.which() returns None even though ffmpeg is installed.
_FFMPEG_FALLBACK_PATHS = (
    "/opt/homebrew/bin/ffmpeg",              # Apple-silicon Homebrew
    "/usr/local/bin/ffmpeg",                 # Intel Homebrew
    "/usr/bin/ffmpeg",                       # system / linux
    "/opt/local/bin/ffmpeg",                 # MacPorts
    "C:/ffmpeg/bin/ffmpeg.exe",              # Windows common manual install
    "C:/Program Files/ffmpeg/bin/ffmpeg.exe",  # Windows
)


def find_ffmpeg() -> str | None:
    """Locate ffmpeg. Priority:
      1. Bundled binary inside the PyInstaller bundle (sys._MEIPASS) — works on
         machines with no system ffmpeg. Named `ffmpeg` (mac/linux) or
         `ffmpeg.exe` (Windows).
      2. PATH (dev / terminal launches).
      3. Common install dirs (Finder .app PATH misses Homebrew; Windows users
         often drop ffmpeg.exe under C:/ffmpeg).
    """
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for name in ("ffmpeg", "ffmpeg.exe"):
            bundled = Path(meipass) / name
            if bundled.is_file():
                return str(bundled)
    # Running from source (not frozen): use the ffmpeg binary committed in the
    # repo at assets/ffmpeg-static/ so `clone → run` works with zero setup.
    # watermark.py → tiktok_music_downloader → src → <repo root>.
    repo_ffmpeg_dir = Path(__file__).resolve().parents[2] / "assets" / "ffmpeg-static"
    for name in ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg",):
        cand = repo_ffmpeg_dir / name
        if cand.is_file():
            return str(cand)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in _FFMPEG_FALLBACK_PATHS:
        if Path(cand).is_file():
            return cand
    return None


def _render_text_png(text: str) -> Path:
    """Rasterize `text` into a fully-opaque transparent-background PNG.

    Done in Python (Pillow) because the system's ffmpeg may lack libfreetype
    and thus the drawtext filter. The rendered PNG is then used as a normal
    image overlay, which every ffmpeg build supports.

    Opacity is intentionally NOT baked in here — the filter chain applies
    `cfg.opacity` once via colorchannelmixer. Applying it in both places would
    square it (35% → ~12%), making the watermark far fainter than the UI value.
    """
    font = None
    for cand in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(cand, TEXT_FONT_SIZE)
            break
        except OSError:
            continue
    if font is None:
        # Fall back to Pillow's bundled bitmap font if no system TTF is found.
        log.warning("no system TTF found, using Pillow default (low quality)")
        font = ImageFont.load_default()

    # Measure with a draw object since getbbox() is the most reliable across
    # Pillow versions for variable-width fonts and unicode.
    tmp_img = Image.new("RGBA", (1, 1))
    bbox = ImageDraw.Draw(tmp_img).textbbox((0, 0), text, font=font, stroke_width=TEXT_BORDER_PX)
    w = bbox[2] - bbox[0] + TEXT_PADDING_PX * 2
    h = bbox[3] - bbox[1] + TEXT_PADDING_PX * 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text(
        (TEXT_PADDING_PX - bbox[0], TEXT_PADDING_PX - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=TEXT_BORDER_PX,
        stroke_fill=(0, 0, 0, 255),
    )

    fd, tmp = tempfile.mkstemp(prefix="ttmd-wm-text-", suffix=".png")
    os.close(fd)
    img.save(tmp, "PNG")
    return Path(tmp)


def _build_filter_chain(cfg: WatermarkConfig, text_idx: int | None) -> str:
    """Assemble ffmpeg -filter_complex string for the text overlay (+ scale).

    The animated text is a pre-rendered Pillow PNG kept at native size for crisp
    glyphs; it's optional and uses an input index assigned by the caller (None
    if absent).
    """
    parts: list[str] = []
    cur = "[0:v]"

    # --- Animated text (Pillow PNG, kept at native size for crisp glyphs) ---
    if text_idx is not None:
        t_pat = cfg.text_pattern if cfg.text_pattern in PATTERNS else DEFAULT_PATTERN
        x_t, y_t = PATTERNS[t_pat]
        parts.append(
            f"[{text_idx}:v]format=rgba,colorchannelmixer=aa={cfg.opacity}[text]"
        )
        parts.append(
            f"{cur}[text]overlay=x='{_expand(x_t)}':y='{_expand(y_t)}'[v_text]"
        )
        cur = "[v_text]"

    # --- Final resolution scale (HD / FullHD / original) ---
    scale_expr = QUALITY_FILTERS.get(cfg.output_quality)
    if scale_expr:
        parts.append(f"{cur}{scale_expr}[out]")
    else:
        parts.append(f"{cur}null[out]")

    return ";".join(parts)


def apply_watermark(
    video_path: Path, cfg: WatermarkConfig, ffmpeg: str | None = None,
) -> bool:
    """Apply watermark IN-PLACE to video_path. Returns True on success.

    Failure modes (ffmpeg missing, ffmpeg error) all leave the original file
    untouched and return False so the caller can decide to keep the
    un-watermarked download or surface a warning.
    """
    if cfg.is_empty:
        return True

    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg not on PATH — skipping watermark")
        return False

    has_text = bool(cfg.animated_text)
    needs_scale = cfg.output_quality != "original"
    if not (has_text or needs_scale):
        log.warning(
            "watermark enabled but no text/quality set — nothing to apply"
        )
        return False

    # Pre-render text overlay to a transparent PNG via Pillow (drawtext requires
    # libfreetype which Homebrew ffmpeg often omits).
    text_png: Path | None = None
    if has_text:
        text_png = _render_text_png(cfg.animated_text or "")

    layers = []
    if has_text:
        layers.append(f"text:'{cfg.animated_text}'/{cfg.text_pattern}")
    if needs_scale:
        layers.append(f"quality:{cfg.output_quality}")
    log.info("watermark %s: [%s]", video_path.name, ", ".join(layers))

    # Assign input indices in fixed order: video, text. Each index is None when
    # that layer is absent — the filter chain checks the same flag so the wiring
    # stays consistent.
    cmd: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                      "-i", str(video_path)]
    next_idx = 1
    text_idx = None
    if has_text and text_png is not None:
        cmd += ["-i", str(text_png)]; text_idx = next_idx; next_idx += 1

    cmd += [
        "-filter_complex", _build_filter_chain(cfg, text_idx),
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
    ]
    out_tmp = video_path.with_suffix(".wm.mp4")
    cmd.append(str(out_tmp))

    log.debug("ffmpeg cmd: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            log.error("watermark failed for %s: %s",
                      video_path.name, (proc.stderr or "").strip()[-300:])
            out_tmp.unlink(missing_ok=True)
            return False
        out_tmp.replace(video_path)
        log.info("watermarked %s", video_path.name)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("watermark exception for %s: %s", video_path.name, exc)
        out_tmp.unlink(missing_ok=True)
        return False
    finally:
        if text_png is not None:
            text_png.unlink(missing_ok=True)
