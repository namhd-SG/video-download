"""Gọi agy (máy dev) để BÓC TRƯỜNG nhìn thấy trên ảnh và để gợi ý từ khoá chủ đề/sản phẩm. agy không chấm điểm.

Nghiệm thu một lượt agy bằng NỘI DUNG đích, không bằng mã thoát: agy trả rc=0 cả khi sai tên model (luật agy-collaboration).
Lượt agy in JSON ra stdout thay vì ghi file (sự cố GĐ1 22/10) vẫn đọc được: lấy khối ```json cuối cùng trong log.
Mục agy bỏ sót ⇒ ảnh đó vắng trong kết quả ⇒ không được xếp hạng (không đoán).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .truong import CHU_THE, HANH_DONG, LOAI_NEN, TruongAnh, tu_json
from .truy_van import TruyVan

MODEL_MAC_DINH = os.environ.get("TIM_TREND_AGY_MODEL", "gemini-3.8-flash-low")
LO_TOI_DA = 40          # GĐ1: 33 và 40 ảnh/lượt đều đủ mục
GIAY_TOI_DA = 15 * 60

_KHOI_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def goi_agy(prompt: str, add_dir: Path, model: str, giay: int = GIAY_TOI_DA) -> str:
    """Đường nối duy nhất ra agy; test thay hàm này. Trả stdout+stderr để còn cứu JSON in ra log."""
    agy = shutil.which("agy")
    if agy is None:
        raise RuntimeError("không tìm thấy agy trên PATH — công cụ chỉ chạy ở máy dev có agy")
    kq = subprocess.run([agy, "-p", prompt, "--add-dir", str(add_dir), "--model", model, "--mode", "accept-edits",
                         "--dangerously-skip-permissions", "--print-timeout", f"{giay // 60}m"],
                        capture_output=True, text=True, timeout=giay + 60)
    return (kq.stdout or "") + "\n" + (kq.stderr or "")


def _doc_json(dich: Path, log: str) -> dict | None:
    if dich.exists():
        try:
            return json.loads(dich.read_text())
        except json.JSONDecodeError:
            pass
    khoi = _KHOI_JSON.findall(log)
    for k in reversed(khoi):
        try:
            return json.loads(k)
        except json.JSONDecodeError:
            continue
    return None


def _prompt_truong(anh: list[Path], dich: Path) -> str:
    ten = " ".join(a.name for a in anh)
    return (
        "Khong chay lenh shell. Khong hoi lai. Khong cham diem. "
        f"Dung tool doc file mo TUNG anh sau trong thu muc {anh[0].parent}/ : {ten} . "
        "Chi ghi dieu NHIN THAY trong anh, khong suy tu ten file. "
        f"Ghi JSON vao {dich} : {{items:[{{id:<ten file bo .jpg>, "
        "so_ban_sao: so nguyen = so lan CUNG MOT nguoi (cung mat, cung toc) xuat hien trong anh "
        "(1 neu chi 1 nguoi; 0 neu khong co nguoi; nhieu nguoi KHAC nhau thi van ghi 1), "
        f"chu_the: {'|'.join(CHU_THE)}, loai_nen: {'|'.join(LOAI_NEN)}, hanh_dong: {'|'.join(HANH_DONG)}, "
        "la_luoi: bool (anh chia thanh nhieu o vuong ro rang), "
        "la_tutorial: bool (tutorial, giao dien app, chu huong dan lon), "
        "chu_ocr: chu lon doc duoc tren anh hoac \"\", mo_ta: <=15 tu}]}. "
        f"Phai du {len(anh)} muc."
    )


def boc_truong(anh: list[Path], thu_muc_ra: Path, model: str = MODEL_MAC_DINH,
               ten: str = "agy-truong") -> dict[str, TruongAnh]:
    """Bóc trường cho mọi ảnh (chia lô ≤ LO_TOI_DA, mọi ảnh phải cùng thư mục). Trả {id: TruongAnh} cho mục đọc được.

    File đích bị XOÁ trước mỗi lượt: lượt agy trượt không được đọc nhầm kết quả của lượt trước còn nằm trên đĩa.
    """
    ra: dict[str, TruongAnh] = {}
    for i in range(0, len(anh), LO_TOI_DA):
        lo = anh[i:i + LO_TOI_DA]
        dich = thu_muc_ra / f"{ten}-{i // LO_TOI_DA}.json"
        dich.unlink(missing_ok=True)
        log = goi_agy(_prompt_truong(lo, dich), lo[0].parent, model)
        (thu_muc_ra / f"{ten}-{i // LO_TOI_DA}.log").write_text(log)
        du_lieu = _doc_json(dich, log) or {}
        hop_le = {a.stem for a in lo}
        for muc in du_lieu.get("items", []):
            t = tu_json(muc)
            if t.id in hop_le:   # agy bịa id ngoài lô ⇒ bỏ
                ra[t.id] = t
    return ra


def goi_y_tu_khoa(anh: list[Path], thu_muc_ra: Path, model: str = MODEL_MAC_DINH) -> list[TruyVan]:
    """Từ khoá chủ đề/sản phẩm EN/ES/PT do agy gợi ý từ khung video đầu vào (bổ sung cho nhóm cấu trúc tất định)."""
    dich = thu_muc_ra / "agy-tu-khoa.json"
    dich.unlink(missing_ok=True)   # như boc_truong: lượt agy trượt không được đọc nhầm kết quả lượt trước
    prompt = (
        "Khong chay lenh shell. Khong hoi lai. "
        f"Dung tool doc file mo cac anh {' '.join(a.name for a in anh)} trong thu muc {anh[0].parent}/ "
        "(khung cua 1 video TikTok). Viet tu khoa nhu nguoi dung that go tren TikTok de tim video CUNG DANG (cach dung, "
        "bo cuc, hieu ung AI neu co), khong dich may moc. "
        f"Ghi JSON vao {dich} : {{nhan_dang: <=12 tu mo ta dang video, "
        "chu_de: {en:[4], es:[4], pt:[4]}, san_pham: {en:[2], es:[2], pt:[2]}}."
    )
    log = goi_agy(prompt, anh[0].parent, model)
    (thu_muc_ra / "agy-tu-khoa.log").write_text(log)
    du_lieu = _doc_json(dich, log) or {}
    ra: list[TruyVan] = []
    for nhom in ("chu_de", "san_pham"):
        for lang, ds in (du_lieu.get(nhom) or {}).items():
            if lang in ("en", "es", "pt") and isinstance(ds, list):
                ra += [TruyVan(str(t).strip(), nhom, lang) for t in ds if str(t).strip()]
    return ra
