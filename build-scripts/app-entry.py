"""Frozen-app entry point: launches the Tkinter GUI.

This file runs ONLY inside the PyInstaller-frozen .app. Dev mode uses
`tiktok-music-dl-gui` from pyproject.toml, which calls `gui:main` directly
and bypasses this entry.
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# PRE-IMPORT SETUP — must run before any application or playwright import.
# DO NOT add imports above this section.
# ---------------------------------------------------------------------------

# 1. Hard guard against fork-bomb regression.
#
# A frozen .app should never receive Python-interpreter flags as argv. The
# original bug spawned `subprocess.Popen([sys.executable, "-m", "playwright",
# "install", "chromium"])`, which in the frozen bundle resolves sys.executable
# to the .app binary itself. The child .app then ignored `-m ...` and re-opened
# the GUI, which re-triggered bootstrap, ad infinitum.
#
# This guard exits any frozen child invoked with an interpreter flag (any
# argv[1] starting with "-"). It is defense-in-depth: even if a future code
# path regresses to spawning sys.executable, the bomb terminates after the
# first child instead of multiplying.
if getattr(sys, "frozen", False) and len(sys.argv) > 1 and sys.argv[1].startswith("-"):
    sys.exit(0)

# 2. Pin PLAYWRIGHT_BROWSERS_PATH to a persistent location.
#
# Playwright's transport (playwright/_impl/_transport.py:connect) does:
#     if getattr(sys, "frozen", False):
#         env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
# which stores browsers next to the bundled driver. But PyInstaller's bundle
# root is a TEMPORARY _MEIPASS dir wiped on process exit — Chromium would be
# re-downloaded (~150 MB) on every launch. By setting the env var here BEFORE
# playwright loads, Playwright's `setdefault` is a no-op and our persistent
# path wins.
def _set_persistent_browsers_path() -> None:
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return  # respect explicit user/CI override
    from pathlib import Path
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Caches" / "ms-playwright"
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    else:
        path = Path.home() / ".cache" / "ms-playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)


_set_persistent_browsers_path()

# ---------------------------------------------------------------------------
# Normal imports below this line.
# ---------------------------------------------------------------------------

import multiprocessing
from pathlib import Path

# When frozen by PyInstaller, sys._MEIPASS points at the bundle's Resources.
if getattr(sys, "frozen", False):
    bundle_root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # Defensive — PyInstaller normally handles this, but be explicit.
    src_path = bundle_root / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))


def main() -> None:
    multiprocessing.freeze_support()  # macOS .app safety (no-op here; kept defensively)
    from tiktok_music_downloader.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
