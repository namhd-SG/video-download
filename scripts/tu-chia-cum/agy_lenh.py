"""Dựng lệnh `agy` cho tầng hình + ghi tệp prompt vào thư mục scratch.

Ba luật đã đo của `agy`, dựng thành CẤU TẠO ở đây thay vì nhắc nhau:

1. argv cắt prompt lớn ⇒ MỌI dữ liệu (đường dẫn ảnh, nhãn, CAPTION) đi bằng
   TỆP prompt trong scratch; argv chỉ mang một câu trỏ tới tệp đó.
2. rc=0 cả khi trượt (tên model sai, 503…) ⇒ nghiệm thu một lượt gọi bằng TỆP
   ĐÍCH có thật và parse được (`chay`), không bằng mã thoát.
3. `--effort` xung đột với tên model có hậu tố ⇒ không bao giờ truyền `--effort`.

`--add-dir` chỉ bao giờ là thư mục scratch của lượt: agy không được thấy repo
hay thư mục nào khác.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

THU_MUC_PROMPT = Path(__file__).resolve().parent

MODEL_NHAN = "gemini-3.7-flash-low"        # làn vision
MODEL_CHUAN_HOA = "gemini-3.8-flash-high"  # cơ học, chỉ chữ
MODEL_CAPTION = MODEL_CHUAN_HOA

# Tên tệp prompt + tiền tố phiên bản của từng loại lượt gọi. Tiền tố `nhan:`/
# `caption:` khớp `web/models_dac_diem.py` — hai loại cache chung một bảng.
_LOAI = {
    "nhan": ("prompt-nhan.txt", "nhan:", MODEL_NHAN),
    "caption": ("prompt-caption.txt", "caption:", MODEL_CAPTION),
    "chuan_hoa": ("prompt-chuan-hoa.txt", "chuan-hoa:", MODEL_CHUAN_HOA),
}

LOI_CAM_MOI_TRUONG = ("KHÔNG chạy lệnh nào thay đổi toolchain, npm, git config hay biến môi "
                      "trường; không cài/xoá gói; chỉ đọc tệp trong thư mục được cấp.")

# Người chạy agy: nhận argv, trả mã thoát (hoặc None nếu quá giờ). Tiêm được
# để test đếm lượt gọi mà không bao giờ chạm agy thật.
ChayAgy = Callable[[list[str]], "int | None"]


def phien_ban(loai: str, thu_muc: Path = THU_MUC_PROMPT) -> str:
    """`<tiền tố><sha256 12 ký tự của tệp prompt>@<model>`.

    Mỗi loại băm TỆP CỦA CHÍNH NÓ: sửa prompt nhãn đổi phiên bản nhãn (chạy
    lại vision) mà KHÔNG đổi phiên bản caption (cache caption còn nguyên).
    Model nằm trong phiên bản để một lượt chạy trên model khác (rơi tầng)
    không đọc nhầm cache của model kia."""
    ten, tien_to, model = _LOAI[loai]
    bam = hashlib.sha256((thu_muc / ten).read_bytes()).hexdigest()[:12]
    return f"{tien_to}{bam}@{model}"


def dung_argv(tep_prompt: Path, scratch: Path, model: str, agy_bin: str = "agy") -> list[str]:
    """argv của một lượt gọi — KHÔNG chứa dữ liệu nào, chỉ đường dẫn tệp prompt."""
    return [agy_bin, "-p",
            f"Đọc tệp {tep_prompt} và làm ĐÚNG theo hướng dẫn trong đó; chỉ ghi tệp kết quả "
            f"nêu trong đó. {LOI_CAM_MOI_TRUONG}",
            "--add-dir", str(scratch), "--model", model,
            "--mode", "accept-edits", "--dangerously-skip-permissions", "--print-timeout", "25m"]


def _viet_prompt(loai: str, scratch: Path, ten: str, tep_ra: Path, dau: list[str],
                 dong: list[dict], thu_muc: Path) -> Path:
    scratch = scratch.resolve()
    if not tep_ra.resolve().is_relative_to(scratch):
        raise ValueError(f"tệp kết quả {tep_ra} nằm ngoài scratch {scratch}")
    mau = (thu_muc / _LOAI[loai][0]).read_text(encoding="utf-8")
    than = [mau.rstrip(), "", "=== ĐẦU VÀO ===", f"TỆP KẾT QUẢ: {tep_ra.resolve()}", *dau,
            "VIDEO:", *(json.dumps(d, ensure_ascii=False) for d in dong), ""]
    tep = scratch / f"{ten}.prompt.txt"
    tep.write_text("\n".join(than), encoding="utf-8")
    return tep


def lenh_nhan(scratch: Path, lo: list[dict], tep_ra: Path, agy_bin: str = "agy",
              thu_muc: Path = THU_MUC_PROMPT) -> tuple[list[str], Path]:
    """`lo`: `[{"video_id", "anh": [đường dẫn tuyệt đối trong scratch]}]`."""
    tep = _viet_prompt("nhan", scratch, tep_ra.stem, tep_ra, [], lo, thu_muc)
    return dung_argv(tep, scratch, MODEL_NHAN, agy_bin), tep


def lenh_caption(scratch: Path, nguon: str, caption: dict[str, str], tep_ra: Path,
                 agy_bin: str = "agy", thu_muc: Path = THU_MUC_PROMPT) -> tuple[list[str], Path]:
    """Caption đi vào agy CHỈ qua tệp prompt — argv không mang chuỗi caption nào."""
    dong = [{"video_id": v, "caption": c} for v, c in caption.items()]
    tep = _viet_prompt("caption", scratch, tep_ra.stem, tep_ra,
                       [f"NGUỒN: {json.dumps(nguon, ensure_ascii=False)}"], dong, thu_muc)
    return dung_argv(tep, scratch, MODEL_CAPTION, agy_bin), tep


def lenh_chuan_hoa(scratch: Path, truc: str, nhan: dict[str, dict], ten_co_san: list[str],
                   tep_ra: Path, agy_bin: str = "agy",
                   thu_muc: Path = THU_MUC_PROMPT) -> tuple[list[str], Path]:
    dong = [{"video_id": v, **{k: x for k, x in n.items() if k != "video_id"}}
            for v, n in nhan.items()]
    dau = [f"TRỤC: {truc}", f"TÊN CÓ SẴN: {json.dumps(ten_co_san, ensure_ascii=False)}"]
    tep = _viet_prompt("chuan_hoa", scratch, tep_ra.stem, tep_ra, dau, dong, thu_muc)
    return dung_argv(tep, scratch, MODEL_CHUAN_HOA, agy_bin), tep


class KhongCoTepDich(Exception):
    """agy không để lại tệp đích parse được — phép đo hỏng, KHÔNG phải kết quả."""


def chay(argv: list[str], tep_ra: Path, chay_agy: ChayAgy, dang: str):
    """Chạy một lượt agy rồi nghiệm thu bằng tệp đích.

    `dang`: `"jsonl"` ⇒ trả `list[dict]`; `"json"` ⇒ trả `(obj, khoa_trung)`
    — `khoa_trung` là mọi khoá object xuất hiện hơn một lần (`json.loads`
    trần lặng lẽ giữ bản sau, nên một id lặp sẽ biến mất thay vì bị bắt).
    Tệp cũ cùng tên bị xoá TRƯỚC khi gọi, để một tệp sót từ lượt trước không
    bao giờ được đọc như kết quả của lượt này."""
    tep_ra.unlink(missing_ok=True)
    rc = chay_agy(argv)
    if not tep_ra.is_file():
        raise KhongCoTepDich(f"agy (rc={rc}) không sinh {tep_ra.name}")
    van_ban = tep_ra.read_text(encoding="utf-8")
    try:
        if dang == "jsonl":
            return [json.loads(d) for d in van_ban.splitlines() if d.strip()]
        trung: list[str] = []

        def gom(cap):
            ra = {}
            for k, v in cap:
                if k in ra:
                    trung.append(k)
                ra[k] = v
            return ra

        return json.loads(van_ban, object_pairs_hook=gom), trung
    except json.JSONDecodeError as exc:
        raise KhongCoTepDich(f"{tep_ra.name} không parse được: {exc}") from exc
