"""Hộp thư relay agy học mẫu (plan.md §3e, USER CHỐT 08/10 00:13): mini GIỮ việc, máy dev KÉO về, agy định vị, máy dev NỘP toạ độ.

Luật §3e được cài thành KIỂM ở đây, không phải lời hứa:
- Mini → máy dev chỉ có `job_id` (số nguyên) + ảnh JPEG tên UUID do mini sinh. KHÔNG một trường chữ nào (tên file, tiêu đề, mô tả)
  rời mini — chữ trong ảnh/tên file video người ngoài có thể là prompt injection.
- Máy dev → mini chỉ có TOẠ ĐỘ số đúng schema; khoá lạ, kiểu sai, giá trị ngoài 0–1000 ⇒ từ chối cả lượt nộp.
- Ảnh có trần cỡ + trần số lượng; một việc chỉ nhận MỘT lần nộp.
Không phụ thuộc FastAPI — route mỏng ở `web/thay_logo_routes.py`.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

TRAN_ANH_BYTE = 2_000_000
TRAN_ANH_MOT_VIEC = 64
TRAN_WATERMARK_MOT_ANH = 8
_UUID = re.compile(r"^[0-9a-f]{32}$")


class LoiHopThu(ValueError):
    """Đầu vào sai luật hộp thư (route trả 400/404/409 theo `ma`)."""

    def __init__(self, ma: int, thong_diep: str):
        super().__init__(thong_diep)
        self.ma = ma


def _ghi_nguyen_tu(p: Path, du_lieu: bytes) -> None:
    tam = p.with_suffix(p.suffix + ".tmp")
    tam.write_bytes(du_lieu)
    os.replace(tam, p)


class HopThu:
    def __init__(self, goc: str | Path):
        self.goc = Path(goc)
        self.goc.mkdir(parents=True, exist_ok=True)

    def _dir(self, job_id: int) -> Path:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise LoiHopThu(400, "job_id phải là số nguyên dương")
        return self.goc / str(job_id)

    def tao_viec(self, job_id: int, anh_jpeg: list[bytes]) -> list[str]:
        """Phía mini (worker) gọi. Trả UUID từng ảnh theo thứ tự đưa vào."""
        if not 1 <= len(anh_jpeg) <= TRAN_ANH_MOT_VIEC:
            raise LoiHopThu(400, f"số ảnh phải 1–{TRAN_ANH_MOT_VIEC}")
        for a in anh_jpeg:
            if len(a) > TRAN_ANH_BYTE or a[:3] != b"\xff\xd8\xff":
                raise LoiHopThu(400, "ảnh phải là JPEG ≤ trần cỡ")
        d = self._dir(job_id)
        if (d / "viec.json").exists():
            raise LoiHopThu(409, "việc đã tồn tại")
        d.mkdir(parents=True)
        ids = [uuid.uuid4().hex for _ in anh_jpeg]
        for i, a in zip(ids, anh_jpeg):
            _ghi_nguyen_tu(d / f"{i}.jpg", a)
        _ghi_nguyen_tu(d / "viec.json", json.dumps({"job_id": job_id, "anh": ids, "tao_luc": time.time()}).encode())
        return ids

    def viec_cho(self) -> list[dict]:
        """Việc chưa có kết quả, cũ trước. CHỈ job_id + danh sách UUID."""
        out = []
        for d in self.goc.iterdir():
            v = d / "viec.json"
            if d.is_dir() and v.exists() and not (d / "ket_qua.json").exists():
                m = json.loads(v.read_text())
                out.append((m["tao_luc"], {"job_id": int(m["job_id"]), "anh": list(m["anh"])}))
        return [x for _, x in sorted(out, key=lambda t: t[0])]

    def doc_anh(self, anh: str) -> bytes | None:
        if not _UUID.match(anh or ""):
            raise LoiHopThu(400, "tên ảnh sai khuôn")
        for p in self.goc.glob(f"*/{anh}.jpg"):
            return p.read_bytes()
        return None

    def nop_ket_qua(self, job_id: int, du_lieu) -> None:
        """Phía máy dev nộp. Kiểm schema CỨNG trước khi ghi một byte nào."""
        d = self._dir(job_id)
        v = d / "viec.json"
        if not v.exists():
            raise LoiHopThu(404, "không có việc này")
        if (d / "ket_qua.json").exists():
            raise LoiHopThu(409, "việc đã có kết quả")
        anh_cua_viec = set(json.loads(v.read_text())["anh"])
        items = kiem_ket_qua(du_lieu, anh_cua_viec)
        _ghi_nguyen_tu(d / "ket_qua.json", json.dumps({"items": items, "nop_luc": time.time()}).encode())

    def xoa_viec(self, job_id: int) -> None:
        """Video đã tới trạng thái cuối ⇒ bỏ ảnh + kết quả khỏi hộp thư (không để `viec_cho` quét một thư mục phình mãi)."""
        import shutil
        shutil.rmtree(self._dir(job_id), ignore_errors=True)

    def doc_ket_qua(self, job_id: int) -> dict | None:
        p = self._dir(job_id) / "ket_qua.json"
        return json.loads(p.read_text()) if p.exists() else None


def kiem_ket_qua(du_lieu, anh_hop_le: set[str]) -> list[dict]:
    """`{"items": [{"anh": uuid, "man_ket": bool, "watermarks": [{"box_2d": [4 số nguyên 0–1000]}]}]}` — không khoá thừa."""
    if not isinstance(du_lieu, dict) or set(du_lieu) != {"items"} or not isinstance(du_lieu["items"], list):
        raise LoiHopThu(400, "gốc phải đúng một khoá 'items' kiểu danh sách")
    out, da_thay = [], set()
    for it in du_lieu["items"]:
        if not isinstance(it, dict) or set(it) != {"anh", "man_ket", "watermarks"}:
            raise LoiHopThu(400, "mỗi item đúng 3 khoá: anh, man_ket, watermarks")
        if it["anh"] not in anh_hop_le or it["anh"] in da_thay:
            raise LoiHopThu(400, "ảnh không thuộc việc này hoặc lặp")
        if not isinstance(it["man_ket"], bool) or not isinstance(it["watermarks"], list):
            raise LoiHopThu(400, "man_ket phải bool, watermarks phải danh sách")
        if len(it["watermarks"]) > TRAN_WATERMARK_MOT_ANH:
            raise LoiHopThu(400, "quá nhiều watermark trong một ảnh")
        wms = []
        for wm in it["watermarks"]:
            b = wm.get("box_2d") if isinstance(wm, dict) and set(wm) == {"box_2d"} else None
            if not (isinstance(b, list) and len(b) == 4
                    and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 1000 for x in b)):
                raise LoiHopThu(400, "box_2d phải đúng 4 số nguyên 0–1000, không khoá khác")
            wms.append({"box_2d": b})
        da_thay.add(it["anh"])
        out.append({"anh": it["anh"], "man_ket": it["man_ket"], "watermarks": wms})
    return out
