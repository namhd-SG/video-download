"""Download videos from a public Google Drive folder, then watermark them.

Uses `gdown` for the heavy lifting — it handles Drive's quota / "scan for
virus" interstitial / pagination so we don't have to. Public-share-link
folders only; private / restricted-domain folders need OAuth which this
pipeline deliberately skips.

After the folder downloads, the caller iterates the resulting mp4s and feeds
each into `watermark.apply_watermark` (same as the local-folder pipeline).
"""
from __future__ import annotations

import io
import logging
import sys
import threading
from pathlib import Path

import gdown

log = logging.getLogger("ttmd")


class _LineForwarder(io.TextIOBase):
    """File-like sink that forwards each completed line to the ttmd logger.

    gdown prints progress to stdout/stderr; we capture both so users see
    `Retrieving folder list`, per-file progress, and any 'access denied'
    line straight in the GUI activity log instead of a silent hang.
    """

    def __init__(self):
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not s:
            return 0
        with self._lock:
            self._buf += s
            while "\n" in self._buf or "\r" in self._buf:
                # Split on whichever comes first — gdown uses \r for tqdm refresh.
                idx_n = self._buf.find("\n")
                idx_r = self._buf.find("\r")
                idx = min(i for i in (idx_n, idx_r) if i >= 0)
                line, self._buf = self._buf[:idx].rstrip(), self._buf[idx + 1:]
                if line:
                    log.info("gdown: %s", line)
        return len(s)

    def flush(self) -> None:
        with self._lock:
            if self._buf.strip():
                log.info("gdown: %s", self._buf.strip())
            self._buf = ""


def download_folder(url: str, output_dir: Path) -> list[Path]:
    """Download every file in a public Drive folder into `output_dir`.

    Captures gdown's stdout/stderr and re-logs every line so the GUI shows
    real progress (otherwise gdown 6.x looks frozen for several minutes on
    a typical folder).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("gdown: starting (folder → %s)", output_dir)

    forwarder = _LineForwarder()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = forwarder, forwarder
    raw = None
    failed = False
    try:
        raw = gdown.download_folder(
            url=url,
            output=str(output_dir),
            quiet=False,           # let gdown print so we can forward
            use_cookies=False,
            # resume=True kept failing mid-batch in gdown 6.0 with ENOENT on
            # the output dir; rely on apply_watermark's skip-if-exists check
            # downstream instead.
        )
    except Exception as exc:  # noqa: BLE001
        # gdown aborts the whole batch on the first file it can't sign (quota,
        # restricted share, virus-scan interstitial it can't bypass). Files
        # downloaded BEFORE the failing one are still on disk, so we re-scan
        # the output dir and let the caller proceed with what's there.
        failed = True
        log.error("gdown stopped early: %s", exc)
        log.info("scanning %s for files already downloaded…", output_dir)
    finally:
        forwarder.flush()
        sys.stdout, sys.stderr = real_out, real_err

    if raw:
        paths = [Path(p) for p in raw if p]
    else:
        # Rescan output recursively — covers both the empty-result and
        # mid-batch-failure cases.
        paths = sorted(p for p in output_dir.rglob("*") if p.is_file())
    if failed and paths:
        log.warning("gdown failed but %d file(s) had already landed — "
                    "continuing with those", len(paths))
    elif not paths:
        log.warning("no files retrieved — folder empty, private, or "
                    "quota-limited. Make sure the share is 'Anyone with the link'.")
    else:
        log.info("gdown: downloaded %d file(s)", len(paths))
    return paths


def iter_mp4s_under(root: Path) -> list[Path]:
    """List mp4s under `root` (recursive) sorted by name."""
    return sorted(p for p in root.rglob("*.mp4") if p.is_file())
