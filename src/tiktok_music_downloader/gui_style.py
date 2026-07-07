"""Centralised Tk/ttk style: dark theme, fonts, color palette, log tag config.

Everything visual lives here so `gui.py` can focus on behaviour.
The `clam` ttk theme is forced because it honours `Style.configure(...)` on
all widget classes (the macOS `aqua` theme silently ignores most custom
styling on ttk.Button, ttk.Entry, etc.).
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Palette — dark, neutral, with TikTok-ish accent.
# ---------------------------------------------------------------------------
BG_WINDOW = "#1c1c20"       # window background
BG_SURFACE = "#26262c"      # cards / labelframes
BG_ELEVATED = "#2f2f36"     # inputs / hovers
BORDER = "#3a3a42"
TEXT = "#ececf1"
TEXT_DIM = "#9ea0aa"
TEXT_FAINT = "#6b6d77"

ACCENT = "#ff3b5c"          # primary button (Start)
ACCENT_HOVER = "#ff5570"
ACCENT_DISABLED = "#7a3540"

# Log + status colors (semantic)
INFO = "#9ea0aa"
HEADER = "#7faaff"
SUCCESS = "#4ade80"
WARNING = "#fbbf24"
ERROR = "#f87171"

# Status pill background by state
STATUS_BG = {
    "Idle":         "#3a3a42",
    "Setting up":   "#3b82f6",
    "Scraping":     "#3b82f6",
    "Downloading":  "#8b5cf6",
    "Done":         "#10b981",
    "Error":        "#ef4444",
    "Setup failed": "#ef4444",
}

# ---------------------------------------------------------------------------
# Fonts — system font where possible.
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    FONT_UI = ("SF Pro Text", 12)
    FONT_UI_BOLD = ("SF Pro Text", 12, "bold")
    FONT_TITLE = ("SF Pro Display", 16, "bold")
    FONT_STAT_LABEL = ("SF Pro Text", 10)
    FONT_STAT_VALUE = ("SF Pro Display", 20, "bold")
    FONT_LOG = ("SF Mono", 11)
    FONT_BUTTON = ("SF Pro Text", 13, "bold")
elif sys.platform == "win32":
    FONT_UI = ("Segoe UI", 10)
    FONT_UI_BOLD = ("Segoe UI", 10, "bold")
    FONT_TITLE = ("Segoe UI", 14, "bold")
    FONT_STAT_LABEL = ("Segoe UI", 9)
    FONT_STAT_VALUE = ("Segoe UI", 18, "bold")
    FONT_LOG = ("Consolas", 10)
    FONT_BUTTON = ("Segoe UI", 11, "bold")
else:
    FONT_UI = ("DejaVu Sans", 10)
    FONT_UI_BOLD = ("DejaVu Sans", 10, "bold")
    FONT_TITLE = ("DejaVu Sans", 14, "bold")
    FONT_STAT_LABEL = ("DejaVu Sans", 9)
    FONT_STAT_VALUE = ("DejaVu Sans", 18, "bold")
    FONT_LOG = ("DejaVu Sans Mono", 10)
    FONT_BUTTON = ("DejaVu Sans", 11, "bold")


def apply_styles(root: tk.Tk) -> ttk.Style:
    """Force clam theme and configure ttk styles + window background."""
    root.configure(bg=BG_WINDOW)
    style = ttk.Style(root)
    style.theme_use("clam")

    # Default ttk widgets — dark backgrounds.
    style.configure(".",
                    background=BG_WINDOW, foreground=TEXT,
                    fieldbackground=BG_ELEVATED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER,
                    font=FONT_UI)
    style.configure("TFrame", background=BG_WINDOW)
    style.configure("TLabel", background=BG_WINDOW, foreground=TEXT)
    style.configure("TLabelframe", background=BG_WINDOW, foreground=TEXT_DIM,
                    bordercolor=BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=BG_WINDOW,
                    foreground=TEXT_DIM, font=FONT_UI_BOLD)
    style.configure("TCheckbutton", background=BG_WINDOW, foreground=TEXT,
                    focuscolor=BG_WINDOW)
    style.map("TCheckbutton",
              background=[("active", BG_WINDOW)],
              foreground=[("disabled", TEXT_FAINT)])

    # Entries / Spinboxes — elevated bg, roomier padding for a softer feel, and
    # an accent border on focus so the active field reads clearly.
    for cls in ("TEntry", "TSpinbox"):
        style.configure(cls,
                        fieldbackground=BG_ELEVATED, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT, padding=(8, 6))
        style.map(cls,
                  fieldbackground=[("disabled", BG_SURFACE)],
                  bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)],
                  darkcolor=[("focus", ACCENT)])

    # Combobox — clam theme alone leaves the dropdown looking like macOS aqua
    # (light gray pill on our dark UI). Force the value display + arrow well to
    # match Entry styling, and patch the popup listbox via the Tk option DB.
    style.configure("TCombobox",
                    fieldbackground=BG_ELEVATED, background=BG_ELEVATED,
                    foreground=TEXT, arrowcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    selectbackground=BG_ELEVATED, selectforeground=TEXT,
                    padding=(8, 6))
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_ELEVATED),
                               ("disabled", BG_SURFACE)],
              foreground=[("readonly", TEXT), ("disabled", TEXT_FAINT)],
              background=[("readonly", BG_ELEVATED), ("active", BORDER)],
              selectbackground=[("readonly", BG_ELEVATED)],
              selectforeground=[("readonly", TEXT)],
              arrowcolor=[("disabled", TEXT_FAINT)])

    # Popup listbox (rendered by Tk, not ttk — option DB only).
    root.option_add("*TCombobox*Listbox.background", BG_ELEVATED)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.font", FONT_UI)

    # Secondary button (Browse) — flat, roomier, subtle hover lift.
    style.configure("TButton",
                    background=BG_ELEVATED, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    focuscolor=BG_WINDOW, relief="flat",
                    padding=(13, 8))
    style.map("TButton",
              background=[("active", BORDER), ("pressed", BORDER),
                          ("disabled", BG_SURFACE)],
              foreground=[("disabled", TEXT_FAINT)])

    # Primary button (Start) — accent.
    style.configure("Primary.TButton",
                    background=ACCENT, foreground="#ffffff",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                    focuscolor=ACCENT, relief="flat",
                    padding=(24, 11), font=FONT_BUTTON)
    style.map("Primary.TButton",
              background=[("active", ACCENT_HOVER),
                          ("disabled", ACCENT_DISABLED)],
              foreground=[("disabled", "#e0c8ce")])

    # Progress bar — thicker, accent troughs.
    style.configure("Big.Horizontal.TProgressbar",
                    background=ACCENT, troughcolor=BG_SURFACE,
                    bordercolor=BG_SURFACE, lightcolor=ACCENT, darkcolor=ACCENT,
                    thickness=14)

    # Stat card styles (used by StatCard frame children) — flat 1px border.
    style.configure("Card.TFrame", background=BG_SURFACE,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    relief="solid", borderwidth=1)
    style.configure("StatLabel.TLabel", background=BG_SURFACE,
                    foreground=TEXT_DIM, font=FONT_STAT_LABEL)
    style.configure("StatValue.TLabel", background=BG_SURFACE,
                    foreground=TEXT, font=FONT_STAT_VALUE)

    # Header title.
    style.configure("Title.TLabel", background=BG_WINDOW,
                    foreground=TEXT, font=FONT_TITLE)
    style.configure("Progress.TLabel", background=BG_WINDOW,
                    foreground=TEXT_DIM, font=FONT_UI)
    # Hint / tip label — muted but still readable (a touch brighter than faint).
    style.configure("Hint.TLabel", background=BG_WINDOW,
                    foreground="#8b8d97",
                    font=(FONT_UI[0], max(FONT_UI[1] - 1, 10)))
    # Highlighted tip — amber text in a subtle box, for attention-worthy notes.
    style.configure("Tip.TLabel", background=BG_SURFACE, foreground=WARNING,
                    font=(FONT_UI[0], FONT_UI[1], "bold"), padding=(14, 9))
    # Section header inside a Labelframe — flat 1px border (no clam bevel).
    style.configure("Section.TLabelframe", background=BG_WINDOW,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    relief="solid", borderwidth=1)
    style.configure("Section.TLabelframe.Label", background=BG_WINDOW,
                    foreground=TEXT, font=FONT_UI_BOLD)

    return style


def configure_log_tags(text: tk.Text) -> None:
    """Per-line color tags on the activity log Text widget."""
    text.tag_configure("info",    foreground=INFO)
    text.tag_configure("header",  foreground=HEADER, font=FONT_UI_BOLD)
    text.tag_configure("success", foreground=SUCCESS)
    text.tag_configure("warning", foreground=WARNING)
    text.tag_configure("error",   foreground=ERROR)


def classify_log(msg: str) -> tuple[str, str]:
    """Return (tag, icon) for a log line based on content.

    Pure function — easy to test, no Tk dependency.
    """
    low = msg.lower()
    if "error" in low or msg.startswith("✗") or " ✗ " in msg:
        return "error", "✗"
    if "warning" in low or "skip" in low or "rate-limit" in low or "cooling" in low:
        return "warning", "⚠"
    if msg.startswith("✓") or " ✓ " in msg or "done" in low or "ready" in low \
            or "installed" in low or "collected" in low:
        return "success", "✓"
    if "scraping" in low or "downloading" in low or "first launch" in low \
            or "batch of" in low:
        return "header", "▶"
    return "info", "•"
