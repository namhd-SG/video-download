# PyInstaller spec for TikTok Music Downloader — cross-platform.
# Build: pyinstaller build-scripts/tiktok-music-downloader.spec --noconfirm
#
# Produces: .app bundle on macOS, plain dist folder + .exe on Windows/Linux.
# Chromium is NOT bundled — too brittle / large. The app calls
# `playwright install chromium` on first launch via bootstrap.py.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
ASSETS = Path("../assets")
# Platform icon (PyInstaller silently skips if path is None / missing).
ICON_FILE = None
if IS_MAC and (ASSETS / "icon.icns").exists():
    ICON_FILE = str(ASSETS / "icon.icns")
elif IS_WIN and (ASSETS / "icon.ico").exists():
    ICON_FILE = str(ASSETS / "icon.ico")

block_cipher = None

# Playwright ships a Node driver + scripts that must be carried into the bundle.
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# yt_dlp uses dynamic extractor imports; collect them defensively.
ytdlp_hidden = collect_submodules("yt_dlp")

# gdown (Drive folder downloads) + requests (FB direct MP4 fetch) were added
# after the first build. requests is imported lazily inside a function so
# PyInstaller's static analysis misses it; gdown pulls bs4/filelock at runtime.
# collect_all grabs package code AND data files (cacert, etc.) for each.
gdown_datas, gdown_bins, gdown_hidden = collect_all("gdown")
req_datas, req_bins, req_hidden = collect_all("requests")
bs4_hidden = collect_submodules("bs4")

# Pillow used by watermark text rendering; PyInstaller usually picks it up
# but explicit listing avoids surprises on Windows.
pil_hidden = collect_submodules("PIL")

hiddenimports = (
    pw_hidden + ytdlp_hidden + pil_hidden
    + gdown_hidden + req_hidden + bs4_hidden
    + [
        "tiktok_music_downloader",
        "tiktok_music_downloader.bootstrap",
        "tiktok_music_downloader.cli",
        "tiktok_music_downloader.downloader",
        "tiktok_music_downloader.gdrive",
        "tiktok_music_downloader.gui",
        "tiktok_music_downloader.gui_helpers",
        "tiktok_music_downloader.gui_style",
        "tiktok_music_downloader.local_watermark",
        "tiktok_music_downloader.scraper",
        "tiktok_music_downloader.scraper_fb",
        "tiktok_music_downloader.utils",
        "tiktok_music_downloader.watermark",
        "tenacity",
        "tqdm",
        "typer",
        "click",
        "requests",
        "gdown",
        "filelock",
    ]
)

# Bundle the static ffmpeg binary so watermarking works on machines without a
# system ffmpeg. macOS .app launched from Finder gets a minimal PATH that
# misses Homebrew, and team Macs may not have ffmpeg at all. The binary is
# x86_64 (evermeet.cx static build) — runs natively on Intel and via Rosetta
# on Apple Silicon. find_ffmpeg() probes sys._MEIPASS for it at runtime.
_ffmpeg_src = Path("../assets/ffmpeg-static/ffmpeg")
extra_binaries = []
if _ffmpeg_src.exists():
    extra_binaries.append((str(_ffmpeg_src), "."))

a = Analysis(
    ["app-entry.py"],
    pathex=["../src"],
    binaries=pw_binaries + extra_binaries + gdown_bins + req_bins,
    datas=pw_datas + gdown_datas + req_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tiktok-music-dl-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="tiktok-music-dl-gui",
)

# macOS-only .app bundle. PyInstaller silently ignores BUNDLE on Windows/Linux
# but constructing it there with an .icns icon path raises an error, so we
# gate the whole call.
if IS_MAC:
    app = BUNDLE(
        coll,
        name="TikTok Music Downloader.app",
        icon=ICON_FILE,
        bundle_identifier="ai.astronex.tiktok-music-downloader",
        info_plist={
            "CFBundleName": "TikTok Music Downloader",
            "CFBundleDisplayName": "TikTok Music Downloader",
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "0.2.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15.0",
        },
    )
