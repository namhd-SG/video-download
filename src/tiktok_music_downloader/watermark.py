"""ffmpeg-based watermarking: static corner logo + orbiting text/image.

Used by the downloader as a post-processing step. All overlays are optional;
when nothing is configured, apply_watermark() is a no-op.

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

# macOS-shipped TTF — used by Pillow to render the watermark text.
DEFAULT_FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
TEXT_FONT_SIZE = 48
TEXT_PADDING_PX = 8
TEXT_BORDER_PX = 2

# Animation visuals — tweak constants here to change the look across the app.
ORBIT_PERIOD_SEC = 6.0     # seconds per full revolution
ORBIT_RADIUS_FRAC = 0.25   # radius = 25% of min(width, height)
LOGO_MARGIN_FRAC = 0.02    # margin = 2% of min(video width, height) — scales with resolution
DEFAULT_OPACITY = 0.35     # animated text + orbiting icon — subtle but visible

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

# Output quality presets applied AFTER overlays. These FORCE the long side to
# the target (1280 for HD, 1920 for FullHD), upscaling small sources too. The
# trade-off vs. "never upscale": every output ends up the same frame size, so
# the logo and animated overlays land at a consistent on-screen pixel size
# regardless of how the source was filmed.
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

    Image takes priority over text for the animated layer when both are set.
    `pattern` selects the animated-layer motion; see PATTERNS.keys() for valid
    names. Invalid names fall back to DEFAULT_PATTERN.
    """
    logo_path: str | None = None
    logo_size_pct: int = 10
    animated_text: str | None = None
    animated_image: str | None = None
    animated_size_pct: int = 15   # animated overlay width as % of video width
    # Independent motion patterns: text and image overlays can co-exist and
    # each pick its own pattern (e.g. text orbits while the icon bounces).
    text_pattern: str = DEFAULT_PATTERN
    image_pattern: str = DEFAULT_PATTERN
    output_quality: str = DEFAULT_QUALITY
    opacity: float = DEFAULT_OPACITY

    @property
    def is_empty(self) -> bool:
        """True when there's literally nothing to do — no overlay AND original res."""
        has_overlay = bool(self.logo_path or self.animated_text or self.animated_image)
        return not has_overlay and self.output_quality == "original"


def find_ffmpeg() -> str | None:
    """Return path to ffmpeg or None if not on PATH."""
    return shutil.which("ffmpeg")


def _probe_dimensions(path: Path) -> tuple[int, int] | None:
    """Return (width, height) of the first video stream, or None on failure.

    Used to compute exact pixel sizes for logo and animated overlays. Doing the
    math in Python and feeding `scale=W:-2` is more reliable than scale2ref —
    the latter is deprecated in ffmpeg 8.x and silently flipped which input is
    the reference, producing wrong dimensions for our logo overlay.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(path)],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        w, h = out.split("x")
        return int(w), int(h)
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return None


def _render_text_png(text: str, opacity: float) -> Path:
    """Rasterize `text` into a transparent PNG and return its path.

    Done in Python (Pillow) because the system's ffmpeg may lack libfreetype
    and thus the drawtext filter. The rendered PNG is then used as a normal
    image overlay, which every ffmpeg build supports.
    """
    try:
        font = ImageFont.truetype(DEFAULT_FONT, TEXT_FONT_SIZE)
    except OSError:
        # Fall back to Pillow's bundled bitmap font if the system TTF is gone.
        log.warning("font %s missing, using Pillow default (low quality)", DEFAULT_FONT)
        font = ImageFont.load_default()

    # Measure with a draw object since getbbox() is the most reliable across
    # Pillow versions for variable-width fonts and unicode.
    tmp_img = Image.new("RGBA", (1, 1))
    bbox = ImageDraw.Draw(tmp_img).textbbox((0, 0), text, font=font, stroke_width=TEXT_BORDER_PX)
    w = bbox[2] - bbox[0] + TEXT_PADDING_PX * 2
    h = bbox[3] - bbox[1] + TEXT_PADDING_PX * 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    alpha = int(255 * opacity)
    draw.text(
        (TEXT_PADDING_PX - bbox[0], TEXT_PADDING_PX - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, alpha),
        stroke_width=TEXT_BORDER_PX,
        stroke_fill=(0, 0, 0, alpha),
    )

    fd, tmp = tempfile.mkstemp(prefix="ttmd-wm-text-", suffix=".png")
    os.close(fd)
    img.save(tmp, "PNG")
    return Path(tmp)


def _build_filter_chain(
    cfg: WatermarkConfig, video_w: int | None,
    logo_idx: int | None, text_idx: int | None, img_idx: int | None,
) -> str:
    """Assemble ffmpeg -filter_complex string from the active overlays.

    Layers stack in order: static logo → animated text → animated image. Each
    is optional and uses an input index assigned by the caller (None if absent).
    Text and image can BOTH be present and animate independently with their
    own pattern — they're applied as separate overlay filters in sequence.
    """
    parts: list[str] = []
    cur = "[0:v]"

    # --- Static logo (top-left corner) ---
    if logo_idx is not None and video_w:
        # Use scale=W:-2 with pre-computed pixel width: scale2ref's semantics
        # changed in ffmpeg 8.x and the bare scale filter is rock-solid.
        logo_w_px = max(2, int(video_w * cfg.logo_size_pct / 100))
        if logo_w_px % 2:
            logo_w_px -= 1
        parts.append(f"[{logo_idx}:v]scale={logo_w_px}:-2[logo]")
        m = f"min(main_w\\,main_h)*{LOGO_MARGIN_FRAC}"
        parts.append(f"{cur}[logo]overlay={m}:{m}[v_logo]")
        cur = "[v_logo]"

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

    # --- Animated image (user upload, scaled to % of video width) ---
    if img_idx is not None and video_w:
        i_pat = cfg.image_pattern if cfg.image_pattern in PATTERNS else DEFAULT_PATTERN
        x_i, y_i = PATTERNS[i_pat]
        anim_w_px = max(2, int(video_w * cfg.animated_size_pct / 100))
        if anim_w_px % 2:
            anim_w_px -= 1
        parts.append(f"[{img_idx}:v]scale={anim_w_px}:-2[img_sized]")
        parts.append(
            f"[img_sized]format=rgba,colorchannelmixer=aa={cfg.opacity}[img_orbit]"
        )
        parts.append(
            f"{cur}[img_orbit]overlay=x='{_expand(x_i)}':y='{_expand(y_i)}'[v_img]"
        )
        cur = "[v_img]"

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

    Failure modes (ffmpeg missing, assets missing, ffmpeg error) all leave the
    original file untouched and return False so the caller can decide to keep
    the un-watermarked download or surface a warning.
    """
    if cfg.is_empty:
        return True

    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg not on PATH — skipping watermark")
        return False

    has_logo = bool(cfg.logo_path and Path(cfg.logo_path).exists())
    has_img = bool(cfg.animated_image and Path(cfg.animated_image).exists())
    has_text = bool(cfg.animated_text)
    needs_scale = cfg.output_quality != "original"
    if not (has_logo or has_img or has_text or needs_scale):
        log.warning(
            "watermark enabled but no logo/text/icon/quality set — nothing to apply"
        )
        return False

    # Pre-render text overlay to a transparent PNG via Pillow (drawtext requires
    # libfreetype which Homebrew ffmpeg often omits). Text and image overlays
    # are independent now — both can be active and animate with their own pattern.
    text_png: Path | None = None
    if has_text:
        text_png = _render_text_png(cfg.animated_text or "", cfg.opacity)

    layers = []
    if has_logo:
        layers.append("logo")
    if has_text:
        layers.append(f"text:'{cfg.animated_text}'/{cfg.text_pattern}")
    if has_img:
        layers.append(f"icon/{cfg.image_pattern}")
    if needs_scale:
        layers.append(f"quality:{cfg.output_quality}")
    log.info("watermark %s: [%s]", video_path.name, ", ".join(layers))

    # Probe video width upfront so the filter chain can use exact pixel sizes
    # for overlays (avoids scale2ref's deprecated/flipped semantics in ffmpeg 8.x).
    dims = _probe_dimensions(video_path)
    video_w = dims[0] if dims else None
    if video_w is None and (has_logo or has_img):
        log.warning("ffprobe failed for %s — falling back to source-native sizes",
                    video_path.name)

    # Assign input indices in fixed order: video, logo, text, image. Each
    # index is None when that layer is absent — the filter chain checks the
    # same flags so the wiring stays consistent.
    cmd: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                      "-i", str(video_path)]
    next_idx = 1
    logo_idx = text_idx = img_idx = None
    if has_logo:
        cmd += ["-i", cfg.logo_path]; logo_idx = next_idx; next_idx += 1
    if has_text and text_png is not None:
        cmd += ["-i", str(text_png)]; text_idx = next_idx; next_idx += 1
    if has_img:
        cmd += ["-i", cfg.animated_image]; img_idx = next_idx; next_idx += 1

    cmd += [
        "-filter_complex", _build_filter_chain(
            cfg, video_w, logo_idx, text_idx, img_idx,
        ),
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
