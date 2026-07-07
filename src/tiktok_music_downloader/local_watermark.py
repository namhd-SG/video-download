"""Batch-apply watermarks to existing mp4 files in a local folder.

This is the "no download" pipeline: user already has the videos on disk; we
just walk a source folder, copy each mp4 to a mirrored path under the output
folder, and run the same `watermark.apply_watermark` post-process on it.
Source files are never modified. Failures on a single file don't abort the
batch.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from tiktok_music_downloader.watermark import WatermarkConfig, apply_watermark

log = logging.getLogger("ttmd")


def iter_mp4s(source: Path, recursive: bool) -> list[Path]:
    """Return sorted mp4 paths under `source`. Hidden / dotfiles skipped."""
    pattern = "**/*.mp4" if recursive else "*.mp4"
    out: list[Path] = []
    for p in source.glob(pattern):
        if p.is_file() and not p.name.startswith("."):
            out.append(p)
    return sorted(out)


def watermark_folder(
    source_dir: Path,
    output_dir: Path,
    cfg: WatermarkConfig,
    *,
    recursive: bool = True,
    progress=None,
) -> tuple[int, int, list[str]]:
    """Walk source, copy → watermark each mp4 into a mirrored path under output.

    Returns (processed, skipped, failed_relpaths). Mirrors the
    `downloader.download_all` signature so the GUI's stat-card pipeline reuses
    its progress.note("downloaded"|"skipped"|"failed") events unchanged.
    """
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if source_dir == output_dir:
        raise ValueError(
            "Source and output folders must differ — pick a separate output "
            "folder so the original files stay intact."
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    files = iter_mp4s(source_dir, recursive)
    log.info("found %d mp4 file(s) in %s%s",
             len(files), source_dir, " (recursive)" if recursive else "")

    processed = 0
    skipped = 0
    failed: list[str] = []

    def _note(kind: str) -> None:
        if progress is not None and hasattr(progress, "note"):
            progress.note(kind)

    for src in files:
        rel = src.relative_to(source_dir)
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and target.stat().st_size > 0:
            log.info("⊙ skip (already exists) %s", rel)
            skipped += 1
            _note("skipped")
            if progress is not None:
                progress.update(1)
            continue

        try:
            # Copy first so the source file is never touched. apply_watermark
            # mutates its target in-place (writes a .wm.mp4 sibling then
            # atomic-renames over the input).
            shutil.copy2(src, target)
            if not cfg.is_empty:
                ok = apply_watermark(target, cfg)
                if not ok:
                    log.warning(
                        "watermark failed for %s — keeping un-watermarked copy",
                        rel,
                    )
            processed += 1
            _note("downloaded")
            log.info("✓ %s", rel)
        except Exception as exc:  # noqa: BLE001
            failed.append(str(rel))
            _note("failed")
            log.error("✗ %s: %s", rel, exc)
            target.unlink(missing_ok=True)
        finally:
            if progress is not None:
                progress.update(1)

    return processed, skipped, failed
