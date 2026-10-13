"""Hộp thư relay agy học mẫu (plan.md §3e, USER CHỐT 08/10 00:13): mini GIỮ việc, máy dev KÉO về, agy định vị, máy dev NỘP toạ độ.

Luật §3e được cài thành KIỂM ở đây, không phải lời hứa:
- Mini → máy dev chỉ có `job_id` (số nguyên) + ảnh JPEG tên UUID do mini sinh. KHÔNG một trường chữ nào (tên file, tiêu đề, mô tả)
  rời mini — chữ trong ảnh/tên file video người ngoài có thể là prompt injection.
- Máy dev → mini chỉ có TOẠ ĐỘ số đúng schema (thêm `cum`: số nguyên đã kiểm, xem dưới); khoá lạ, kiểu sai, giá trị ngoài 0–1000 ⇒ từ chối cả lượt nộp.
  KHÔNG một chuỗi chữ nào từ máy dev vào mini — kể cả `label` của agy: relay đổi chữ đó thành số cụm `cum` (cùng chữ trong cùng job ⇒ cùng số).
- Ảnh có trần cỡ + trần số lượng; một LƯỢT của một việc chỉ nhận MỘT lần nộp kết quả.
- Máy dev báo agy trượt bằng `ma` thuộc danh sách CỐ ĐỊNH `MA_LOI_AGY` (enum, không chữ tự do).
Không phụ thuộc FastAPI — route mỏng ở `web/thay_logo_routes.py`.

API NHIỀU LƯỢT (cho lane lõi dùng sau). Một việc (`job_id` = id video trong hàng đợi) có tối đa `TRAN_LUOT` lượt:
  luot 1 = TÌM watermark trên khung rời (đúng như trước đây: file nằm ngay `<goc>/<job_id>/`);
  luot 2..3 = KIỂM kết quả sau render (worker đặt ảnh khung KẾT QUẢ): file nằm ở `<goc>/<job_id>/luot<N>/`, thư mục + khoá riêng.
  - `tao_viec(job_id, anh_jpeg, luot=1)`        mini đặt ảnh; luot>1 chỉ được khi lượt trước ĐÃ có kết quả. Trả UUID từng ảnh.
  - `viec_cho()`                                 [{"job_id", "anh": [uuid…], "luot"}] — mọi lượt chưa có kết quả, cũ trước.
  - `nop_ket_qua(job_id, du_lieu, luot=1)`       máy dev nộp; mỗi lượt đúng MỘT lần (lần hai ⇒ 409).
  - `doc_ket_qua(job_id, luot=1)`                None nếu lượt đó chưa có kết quả.
  - `thu_muc_luot(job_id, luot=1)`               nơi lane lõi ghi sidecar riêng của lượt (vd `khung.json` UUID↔khung).
  - `nop_loi(job_id, ma, luot=1) -> int`         máy dev báo agy trượt; trả TỔNG số lần lỗi của lượt đó. Lượt đã có kết quả ⇒ 409.
  - `so_loi(job_id, luot=1) -> int` / `doc_loi`   mini đếm (+ mã lỗi cuối) để quyết định bỏ cuộc (xem `web/thay_logo_worker.py`).
  - `xoa_viec(job_id)`                           xoá MỌI lượt của việc.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

TRAN_ANH_BYTE = 2_000_000
TRAN_ANH_MOT_VIEC = 64
TRAN_WATERMARK_MOT_ANH = 8
TRAN_LUOT = 3  # 1 = tìm, 2..3 = kiểm sau render
TRAN_CUM = 64  # số cụm tối đa mỗi việc (≤ 8 watermark × 64 ảnh vẫn là số nguyên nhỏ; chặn số khổng lồ)
_UUID = re.compile(r"^[0-9a-f]{32}$")
# Lý do agy trượt — enum CỐ ĐỊNH (§3e: dev→mini chỉ số/enum đã kiểm, không chữ tự do). Thêm mã = sửa ở đây rồi cả relay lẫn worker mini theo.
MA_LOI_AGY = ("het_gio", "agy_loi_chay", "khong_phai_json", "trang_thai_khac", "model_khong_nhan", "thieu_anh", "khong_ket_qua")


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
        self._khoa_loi = threading.Lock()  # route chạy trong threadpool: đọc-sửa-ghi bộ đếm lỗi phải nguyên tử

    def _dir(self, job_id: int) -> Path:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise LoiHopThu(400, "job_id phải là số nguyên dương")
        return self.goc / str(job_id)

    def thu_muc_luot(self, job_id: int, luot: int = 1) -> Path:
        """Lượt 1 ở ngay thư mục việc (tương thích dữ liệu cũ); lượt 2..TRAN_LUOT ở thư mục con `luot<N>`."""
        if not isinstance(luot, int) or isinstance(luot, bool) or not 1 <= luot <= TRAN_LUOT:
            raise LoiHopThu(400, f"luot phải 1–{TRAN_LUOT}")
        d = self._dir(job_id)
        return d if luot == 1 else d / f"luot{luot}"

    def tao_viec(self, job_id: int, anh_jpeg: list[bytes], luot: int = 1) -> list[str]:
        """Phía mini (worker) gọi. Trả UUID từng ảnh theo thứ tự đưa vào."""
        d = self.thu_muc_luot(job_id, luot)
        if not 1 <= len(anh_jpeg) <= TRAN_ANH_MOT_VIEC:
            raise LoiHopThu(400, f"số ảnh phải 1–{TRAN_ANH_MOT_VIEC}")
        for a in anh_jpeg:
            if len(a) > TRAN_ANH_BYTE or a[:3] != b"\xff\xd8\xff":
                raise LoiHopThu(400, "ảnh phải là JPEG ≤ trần cỡ")
        if (d / "viec.json").exists():
            raise LoiHopThu(409, "việc đã tồn tại")
        if luot > 1 and not (self.thu_muc_luot(job_id, luot - 1) / "ket_qua.json").exists():
            raise LoiHopThu(409, "lượt trước chưa có kết quả")
        d.mkdir(parents=True, exist_ok=True)
        ids = [uuid.uuid4().hex for _ in anh_jpeg]
        for i, a in zip(ids, anh_jpeg):
            _ghi_nguyen_tu(d / f"{i}.jpg", a)
        _ghi_nguyen_tu(d / "viec.json", json.dumps({"job_id": job_id, "anh": ids, "luot": luot, "tao_luc": time.time()}).encode())
        return ids

    def viec_cho(self) -> list[dict]:
        """Lượt chưa có kết quả, cũ trước. CHỈ job_id + danh sách UUID + số lượt."""
        out = []
        for job in self.goc.iterdir():
            if not job.is_dir():
                continue
            for d in [job, *sorted(job.glob("luot*"))]:
                v = d / "viec.json"
                try:
                    if v.exists() and not (d / "ket_qua.json").exists():
                        m = json.loads(v.read_text())
                        out.append((m["tao_luc"], {"job_id": int(m["job_id"]), "anh": list(m["anh"]), "luot": int(m.get("luot", 1))}))
                except (FileNotFoundError, json.JSONDecodeError):  # việc vừa bị xoá / đang ghi dở giữa lúc quét
                    continue
        return [x for _, x in sorted(out, key=lambda t: t[0])]

    def doc_anh(self, anh: str) -> bytes | None:
        if not _UUID.match(anh or ""):
            raise LoiHopThu(400, "tên ảnh sai khuôn")
        for p in [*self.goc.glob(f"*/{anh}.jpg"), *self.goc.glob(f"*/luot*/{anh}.jpg")]:
            return p.read_bytes()
        return None

    def nop_ket_qua(self, job_id: int, du_lieu, luot: int = 1) -> None:
        """Phía máy dev nộp. Kiểm schema CỨNG trước khi ghi một byte nào."""
        d = self.thu_muc_luot(job_id, luot)
        v = d / "viec.json"
        if not v.exists():
            raise LoiHopThu(404, "không có việc này")
        if (d / "ket_qua.json").exists():
            raise LoiHopThu(409, "việc đã có kết quả")
        anh_cua_viec = set(json.loads(v.read_text())["anh"])
        items = kiem_ket_qua(du_lieu, anh_cua_viec)
        _ghi_nguyen_tu(d / "ket_qua.json", json.dumps({"items": items, "nop_luc": time.time()}).encode())

    def nop_loi(self, job_id: int, ma: str, luot: int = 1) -> int:
        """Máy dev báo agy trượt (đã cấu hình mà không ra kết quả). `ma` ∈ MA_LOI_AGY. Trả tổng số lần lỗi của lượt.
        Ghi SAU khi đã kiểm việc tồn tại + chưa có kết quả: lỗi đến muộn sau một lần nộp thành công bị từ chối, không đếm."""
        if ma not in MA_LOI_AGY:
            raise LoiHopThu(400, "mã lỗi không thuộc danh sách")
        d = self.thu_muc_luot(job_id, luot)
        if not (d / "viec.json").exists():
            raise LoiHopThu(404, "không có việc này")
        with self._khoa_loi:
            if (d / "ket_qua.json").exists():
                raise LoiHopThu(409, "việc đã có kết quả")
            cu = self.doc_loi(job_id, luot)
            so, bay_gio = (cu["so"] if cu else 0) + 1, time.time()
            _ghi_nguyen_tu(d / "loi_agy.json", json.dumps(
                {"so": so, "ma_cuoi": ma, "luc": bay_gio, "dau_luc": cu["dau_luc"] if cu else bay_gio}).encode())
            return so

    def doc_loi(self, job_id: int, luot: int = 1) -> dict | None:
        """`{"so": tổng lần lỗi, "ma_cuoi": mã lỗi gần nhất, "dau_luc": giờ lỗi ĐẦU TIÊN}` hoặc None nếu chưa có lỗi nào."""
        p = self.thu_muc_luot(job_id, luot) / "loi_agy.json"
        try:
            d = json.loads(p.read_text())
            return {"so": int(d["so"]), "ma_cuoi": d["ma_cuoi"] if d["ma_cuoi"] in MA_LOI_AGY else "khong_ket_qua",
                    "dau_luc": float(d.get("dau_luc", d["luc"]))}
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def so_loi(self, job_id: int, luot: int = 1) -> int:
        d = self.doc_loi(job_id, luot)
        return d["so"] if d else 0

    def xoa_viec(self, job_id: int) -> None:
        """Video đã tới trạng thái cuối ⇒ bỏ ảnh + kết quả (mọi lượt) khỏi hộp thư (không để `viec_cho` quét một thư mục phình mãi)."""
        import shutil
        shutil.rmtree(self._dir(job_id), ignore_errors=True)

    def doc_ket_qua(self, job_id: int, luot: int = 1) -> dict | None:
        p = self.thu_muc_luot(job_id, luot) / "ket_qua.json"
        return json.loads(p.read_text()) if p.exists() else None


def kiem_ket_qua(du_lieu, anh_hop_le: set[str]) -> list[dict]:
    """`{"items": [{"anh": uuid, "man_ket": bool, "watermarks": [{"box_2d": [4 số nguyên 0–1000], "cum"?: int}]}]}` — không khoá thừa.
    `cum` tuỳ chọn: số nguyên (không bool) 0 ≤ cum < TRAN_CUM; mọi thứ khác (chuỗi, `label`…) ⇒ từ chối CẢ lượt nộp."""
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
            b = wm.get("box_2d") if isinstance(wm, dict) and set(wm) in ({"box_2d"}, {"box_2d", "cum"}) else None
            if not (isinstance(b, list) and len(b) == 4
                    and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 1000 for x in b)):
                raise LoiHopThu(400, "box_2d phải đúng 4 số nguyên 0–1000, chỉ thêm được khoá cum")
            if "cum" in wm and not (isinstance(wm["cum"], int) and not isinstance(wm["cum"], bool) and 0 <= wm["cum"] < TRAN_CUM):
                raise LoiHopThu(400, f"cum phải là số nguyên 0–{TRAN_CUM - 1}")
            wms.append({"box_2d": b, **({"cum": wm["cum"]} if "cum" in wm else {})})
        da_thay.add(it["anh"])
        out.append({"anh": it["anh"], "man_ket": it["man_ket"], "watermarks": wms})
    return out
