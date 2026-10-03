"""Máy khách HTTP/SSE thô cho test giải captcha (http.client, đọc dòng, không giải nén)."""
from __future__ import annotations

import http.client
import json
import time

CHU = "chu@x.vn"


def goi(port, method, path, user=CHU, body=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json"}
    if user:
        h["X-Test-User"] = user
    data = raw if raw is not None else (json.dumps(body) if body is not None else None)
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read().decode("utf-8")
    c.close()
    try:
        return r.status, json.loads(txt)
    except ValueError:
        return r.status, txt


class Sse:
    def __init__(self, port, job_id, token, user=CHU, timeout=6):
        self.c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        self.c.request("GET", f"/jobs/{job_id}/giai/khung?token={token}",
                       headers={"X-Test-User": user, "Accept": "text/event-stream"})
        self.r = self.c.getresponse()
        self.status = self.r.status
        self.tho = ""

    def doc(self, ten=None):
        """Đọc tới khi gặp sự kiện `ten` (None = bất kỳ). Trả (event, data)."""
        ev, data = None, []
        while True:
            dong = self.r.readline()
            if not dong:
                return None, None
            dong = dong.decode("utf-8")
            self.tho += dong
            dong = dong.rstrip("\r\n")
            if dong.startswith("event:"):
                ev = dong[6:].strip()
            elif dong.startswith("data:"):
                data.append(dong[5:].strip())
            elif dong == "" and (ev or data):
                if ten is None or ev == ten:
                    return ev, json.loads("\n".join(data)) if data else None
                ev, data = None, []

    def dong_ket_noi(self):
        try:
            self.c.close()
        except Exception:  # noqa: BLE001
            pass


def cho(dieu_kien, giay=5.0):
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        time.sleep(0.02)
    return dieu_kien()
