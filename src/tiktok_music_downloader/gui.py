"""Tkinter GUI: paste URL, click Start, watch logs + progress."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from tiktok_music_downloader.bootstrap import ensure_chromium
from tiktok_music_downloader.downloader import download_all
from tiktok_music_downloader.gui_helpers import QueueHandler, UiProgress
from tiktok_music_downloader.scraper import scrape_music_page
from tiktok_music_downloader.utils import is_music_page, setup_logger

POLL_INTERVAL_MS = 100


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("TikTok Music Downloader")
        root.geometry("720x600")

        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.bootstrap_ok = False

        self._build_form()
        self._build_progress_and_log()
        self._attach_logger()
        root.after(POLL_INTERVAL_MS, self._poll_queue)
        self._kickoff_bootstrap()

    def _build_form(self) -> None:
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="x")

        ttk.Label(frm, text="TikTok music URL:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.url_var, width=80).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=2
        )

        ttk.Label(frm, text="Output dir:").grid(row=1, column=0, sticky="w")
        # Default to ~/Downloads/tiktok-music. Avoid Path.cwd() — when launched
        # from a .app via Finder, CWD is "/" (read-only under macOS SIP), which
        # makes the default "/downloads" and downloads fail with EROFS.
        self.out_var = tk.StringVar(value=str(Path.home() / "Downloads" / "tiktok-music"))
        ttk.Entry(frm, textvariable=self.out_var, width=60).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(frm, text="Browse…", command=self._pick_dir).grid(row=1, column=2, padx=4)

        ttk.Label(frm, text="Max videos:").grid(row=2, column=0, sticky="w")
        self.max_var = tk.IntVar(value=200)
        ttk.Spinbox(frm, from_=1, to=2000, textvariable=self.max_var, width=8).grid(row=2, column=1, sticky="w")

        ttk.Label(frm, text="Delay (s):").grid(row=2, column=2, sticky="e")
        self.delay_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(
            frm, from_=0.0, to=30.0, increment=0.5, textvariable=self.delay_var, width=8
        ).grid(row=2, column=3, sticky="w")

        ttk.Label(frm, text="Proxy (optional):").grid(row=3, column=0, sticky="w")
        self.proxy_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.proxy_var, width=60).grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=2
        )

        self.headful_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Show browser (headful)", variable=self.headful_var).grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(frm, text="Verbose log", variable=self.verbose_var).grid(row=4, column=2, sticky="w")

        btns = ttk.Frame(self.root, padding=(10, 0))
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="Start", command=self._start)
        self.start_btn.pack(side="left")
        frm.columnconfigure(1, weight=1)

    def _build_progress_and_log(self) -> None:
        wrap = ttk.Frame(self.root, padding=10)
        wrap.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(wrap, mode="determinate", maximum=1)
        self.progress.pack(fill="x", pady=(0, 6))
        self.log_box = tk.Text(wrap, height=18, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)

    def _pick_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.out_var.get() or str(Path.cwd()))
        if chosen:
            self.out_var.set(chosen)

    def _attach_logger(self) -> None:
        logger = setup_logger(self.verbose_var.get())
        for h in list(logger.handlers):
            if isinstance(h, QueueHandler):
                logger.removeHandler(h)
        handler = QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)

    def _kickoff_bootstrap(self) -> None:
        """On first launch, install Chromium in a worker thread."""
        self.start_btn.config(state="disabled", text="Setting up…")

        def _runner():
            ok = ensure_chromium(lambda msg: self.log_queue.put(msg))
            self.log_queue.put(("bootstrap_done", ok))

        threading.Thread(target=_runner, daemon=True).start()

    def _start(self) -> None:
        if not self.bootstrap_ok:
            self._append_log("setup not finished — please wait")
            return
        url = self.url_var.get().strip()
        if not is_music_page(url):
            self._append_log("ERROR: URL must be a TikTok /music/ page")
            return
        if self.worker and self.worker.is_alive():
            return
        self._attach_logger()
        self.progress.config(value=0, maximum=max(1, self.max_var.get()))
        self.start_btn.config(state="disabled")
        self.worker = threading.Thread(target=self._run_pipeline, args=(url,), daemon=True)
        self.worker.start()

    def _run_pipeline(self, url: str) -> None:
        try:
            refs = scrape_music_page(
                url,
                max_videos=self.max_var.get(),
                headless=not self.headful_var.get(),
                proxy=self.proxy_var.get().strip() or None,
            )
            if not refs:
                self.log_queue.put("no videos found — try Show browser (headful)")
                return
            self.progress.config(maximum=len(refs))
            downloaded, skipped, failed = download_all(
                refs,
                Path(self.out_var.get()),
                delay_seconds=self.delay_var.get(),
                proxy=self.proxy_var.get().strip() or None,
                progress=UiProgress(self.log_queue),
            )
            self.log_queue.put(
                f"DONE — downloaded={downloaded} skipped={skipped} failed={len(failed)}"
            )
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"ERROR: {exc}")
        finally:
            self.log_queue.put(("enable_start", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "progress":
                        self.progress.step(payload)
                    elif kind == "enable_start":
                        self.start_btn.config(state="normal")
                    elif kind == "bootstrap_done":
                        self.bootstrap_ok = bool(payload)
                        self.start_btn.config(
                            state="normal" if payload else "disabled",
                            text="Start" if payload else "Setup failed",
                        )
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _append_log(self, msg: str) -> None:
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
