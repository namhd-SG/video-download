"""First-run: ensure Playwright Chromium is installed."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Where Playwright stores browsers by default on macOS:
# ~/Library/Caches/ms-playwright
# Override via PLAYWRIGHT_BROWSERS_PATH at runtime.

LogFn = Callable[[str], None]


def _default_browsers_path() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _expected_chromium_revision() -> str | None:
    """Read the chromium revision Playwright expects from its bundled manifest.

    Returns None if manifest can't be located (defensive — caller falls back to
    loose detection). The manifest lives at
    `<playwright_pkg>/driver/package/browsers.json` and is bundled by
    `collect_all("playwright")` in the PyInstaller spec.
    """
    try:
        import json
        import playwright

        manifest = (
            Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        )
        data = json.loads(manifest.read_text())
        for entry in data.get("browsers", []):
            if entry.get("name") == "chromium":
                rev = entry.get("revision")
                return str(rev) if rev is not None else None
    except Exception:  # noqa: BLE001 — manifest absent/malformed → loose detection
        return None
    return None


def chromium_installed() -> bool:
    """True if the chromium revision Playwright expects is on disk.

    Version-aware: avoids the trap where a stale `chromium-XXXX/` from a
    previous Playwright install passes a loose check but fails at runtime
    with "Executable doesn't exist at .../chromium-YYYY/...".
    """
    base = _default_browsers_path()
    if not base.exists():
        return False
    expected = _expected_chromium_revision()
    if expected is not None:
        return (base / f"chromium-{expected}").is_dir()
    # Manifest unreadable — fall back to loose detection (any chromium-*).
    return any(p.name.startswith("chromium-") for p in base.iterdir() if p.is_dir())


def _playwright_install_cmd() -> list[str]:
    """
    Build the `playwright install chromium` command.

    CRITICAL: In a PyInstaller-frozen .app, `sys.executable` is the .app
    binary itself, NOT a Python interpreter. Spawning it with `-m playwright`
    re-launches the GUI instead of running the installer — creating an
    infinite app-launch loop (fork bomb).

    Fix: invoke Playwright's bundled Node driver directly. The driver path
    resolves to a Node binary + cli.js inside the playwright package, which
    is bundled by `collect_all("playwright")` in the PyInstaller spec.
    Works identically in dev and frozen mode.
    """
    from playwright._impl._driver import compute_driver_executable

    node_path, cli_js = compute_driver_executable()
    return [str(node_path), str(cli_js), "install", "chromium"]


def install_chromium(log: LogFn) -> bool:
    """
    Run `playwright install chromium`. Returns True on success.
    Streams stdout lines to log() so callers can show progress.
    """
    target = _default_browsers_path()
    log(f"First launch: downloading Chromium (~150 MB) → {target}")
    try:
        cmd = _playwright_install_cmd()
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: cannot resolve Playwright driver: {exc}")
        return False
    # Ensure the subprocess sees the same PLAYWRIGHT_BROWSERS_PATH we resolved,
    # even if a caller forgot to set it. Inherited env keeps everything else.
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(target))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    except FileNotFoundError as exc:
        log(f"ERROR: cannot invoke Playwright: {exc}")
        return False

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    rc = proc.wait()
    if rc != 0:
        log(f"ERROR: playwright install exited {rc}")
        return False
    log("Chromium installed. Ready to scrape.")
    return True


def ensure_chromium(log: LogFn) -> bool:
    """Idempotent: install only if not present."""
    if chromium_installed():
        return True
    return install_chromium(log)
