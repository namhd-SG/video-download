"""Thread-safe glue between worker thread and Tk UI thread, plus small widgets.

- QueueHandler  : pipes logging records onto a queue for the UI thread.
- UiProgress    : adapter so download_all() can push progress + per-video
                  outcome events without knowing about Tk.
- StatusPill    : little colored pill in the header showing app state.
- StatCard      : one of the four mini stat cards under the progress bar.
"""
from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import ttk

from tiktok_music_downloader.gui_style import (
    BG_SURFACE,
    STATUS_BG,
    TEXT,
    FONT_UI,
)


class QueueHandler(logging.Handler):
    """Push log records into a thread-safe queue for the UI thread to consume."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


class UiProgress:
    """Adapter so downloader can drive progress bar + stat cards via queue.

    - update(n)       : advance the progress bar by n
    - note(kind)      : record a per-video outcome ("downloaded" / "skipped" /
                        "failed") — UI tallies these into the stat cards.
    """

    def __init__(self, q: queue.Queue):
        self.q = q

    def update(self, n: int = 1) -> None:
        self.q.put(("progress", n))

    def note(self, kind: str) -> None:
        self.q.put(("stat", kind))


class StatusPill(tk.Label):
    """Header status indicator. Background color shifts with `set(state)`."""

    def __init__(self, parent: tk.Misc, state: str = "Idle"):
        super().__init__(
            parent,
            text=f"● {state}",
            bg=STATUS_BG.get(state, STATUS_BG["Idle"]),
            fg="#ffffff",
            font=FONT_UI,
            padx=14,
            pady=4,
            bd=0,
        )

    def set(self, state: str) -> None:
        self.config(
            text=f"● {state}",
            bg=STATUS_BG.get(state, STATUS_BG["Idle"]),
        )


class StatCard(ttk.Frame):
    """Mini card: label on top, numeric value below. Updated via `set(n)`."""

    def __init__(self, parent: tk.Misc, label: str, value: int = 0):
        super().__init__(parent, style="Card.TFrame", padding=(16, 10))
        # Internal labels — use tk.Label so we can pin bg even on macOS aqua.
        tk.Label(
            self, text=label.upper(),
            bg=BG_SURFACE, fg="#9ea0aa",
            font=(FONT_UI[0], 9, "bold"),
        ).pack(anchor="w")
        self._value = tk.Label(
            self, text=str(value),
            bg=BG_SURFACE, fg=TEXT,
            font=(FONT_UI[0], 20, "bold"),
        )
        self._value.pack(anchor="w", pady=(2, 0))

    def set(self, value: int) -> None:
        self._value.config(text=str(value))
