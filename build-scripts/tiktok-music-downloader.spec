# PyInstaller spec for TikTok Music Downloader (.app bundle, macOS).
# Build: pyinstaller build-scripts/tiktok-music-downloader.spec --noconfirm
#
# Chromium is NOT bundled — too brittle / large. The app calls
# `playwright install chromium` on first launch via bootstrap.py.

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Playwright ships a Node driver + scripts that must be carried into the bundle.
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# yt_dlp uses dynamic extractor imports; collect them defensively.
ytdlp_hidden = collect_submodules("yt_dlp")

hiddenimports = pw_hidden + ytdlp_hidden + [
    "tiktok_music_downloader",
    "tiktok_music_downloader.bootstrap",
    "tiktok_music_downloader.cli",
    "tiktok_music_downloader.downloader",
    "tiktok_music_downloader.gui",
    "tiktok_music_downloader.gui_helpers",
    "tiktok_music_downloader.scraper",
    "tiktok_music_downloader.utils",
    "tenacity",
    "tqdm",
    "typer",
    "click",
]

a = Analysis(
    ["app-entry.py"],
    pathex=["../src"],
    binaries=pw_binaries,
    datas=pw_datas,
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

app = BUNDLE(
    coll,
    name="TikTok Music Downloader.app",
    icon="../assets/icon.icns",
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
