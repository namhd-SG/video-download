"""Thread-safe glue between worker thread and Tk UI thread."""
from __future__ import annotations

import logging
import queue


class QueueHandler(logging.Handler):
    """Push log records into a thread-safe queue for the UI thread to consume."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


class UiProgress:
    """Adapter so download_all's `progress.update(1)` updates Tk progressbar via queue."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def update(self, n: int = 1) -> None:
        self.q.put(("progress", n))
