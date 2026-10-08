"""Máy chủ thật (uvicorn, cổng ngẫu nhiên) cho test route thay logo — venv chính của repo KHÔNG có httpx nên không dùng TestClient
(cùng cách `tests/test_worker_khong_chet_va_cong_dia.py:may_chu`). Gọi bằng urllib."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request


class MayChu:
    def __init__(self, app):
        import uvicorn

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return
            time.sleep(0.02)
        raise RuntimeError("uvicorn không khởi động")

    def dung(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def goi(self, cach: str, duong: str, *, headers=None, json_body=None):
        """Trả (mã, thân bytes)."""
        data = None if json_body is None else json.dumps(json_body).encode()
        h = dict(headers or {})
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{duong}", data=data, headers=h, method=cach.upper())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
