"""Kế hoạch một lượt tầng hình: đọc từ mini (qua CLI) những gì CẦN làm cho
một job, quyết TỪ CHỐI trước khi có ảnh nào rời máy hay lượt agy nào bị tính
tiền, và in kế hoạch đó ra (thử khô dùng nguyên phần này).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import agy_lenh
import mini as mini_mod

MA_OK, MA_CU_PHAP, MA_DO_HONG, MA_KHONG_DAT, MA_TU_CHOI = 0, 2, 3, 4, 5

# Ảnh rời máy sang Google khi gọi agy ⇒ chỉ video TikTok CÔNG KHAI.
NGUON_CHO_PHEP = "https://www.tiktok.com/"
# Số video mỗi lượt gọi vision (≤3 ảnh/video ⇒ ≤60 ảnh/lượt). Chọn, chưa đo
# trần thật của agy.
LO_NHAN = 20


class DoHong(Exception):
    """Phép đo / đường ống hỏng — chưa có kết quả để phán."""


class KhongDat(Exception):
    """Có kết quả nhưng trượt phép kiểm máy — không ghi nháp."""


class TuChoi(Exception):
    """Lượt không được phép chạy/ghi."""


def nguon_duoc_phep(url) -> bool:
    return isinstance(url, str) and url.startswith(NGUON_CHO_PHEP)


@dataclass(frozen=True)
class PhienBan:
    """Phiên bản prompt + model của từng loại lượt gọi. Model caption đi theo
    model chuẩn hoá (cùng làn chữ)."""
    nhan: str
    caption: str
    chuan_hoa: str
    model_nhan: str = agy_lenh.MODEL_NHAN
    model_chuan_hoa: str = agy_lenh.MODEL_CHUAN_HOA

    @classmethod
    def tu_thu_muc(cls, thu_muc: Path, model_nhan: str | None = None,
                   model_chuan_hoa: str | None = None) -> "PhienBan":
        mn = model_nhan or agy_lenh.MODEL_NHAN
        mc = model_chuan_hoa or agy_lenh.MODEL_CHUAN_HOA
        return cls(agy_lenh.phien_ban("nhan", thu_muc, mn),
                   agy_lenh.phien_ban("caption", thu_muc, mc),
                   agy_lenh.phien_ban("chuan_hoa", thu_muc, mc), mn, mc)

    def cho_chia_lan(self) -> str:
        return f"{self.nhan};{self.caption};{self.chuan_hoa}"


def cli_json(m, args: list[str], stdin: bytes | None = None):
    try:
        rc, ra, loi = m.cli(args, stdin)
    except mini_mod.LoiMini as exc:
        raise DoHong(str(exc)) from exc
    if rc != 0:
        raise DoHong(f"mini `{args[0]}` rc={rc}: {loi.strip()[:300]}")
    try:
        return json.loads(ra)
    except json.JSONDecodeError as exc:
        raise DoHong(f"mini `{args[0]}` trả không phải JSON: {ra[:200]!r}") from exc


@dataclass
class KeHoach:
    job_id: int
    url: str
    tu_choi: str | None
    video: list[dict]
    so_bi_loc: int
    bi_loc_theo_ly_do: dict[str, int]

    @property
    def co_anh(self) -> list[dict]:
        return [v for v in self.video if v["anh"]]

    @property
    def khong_anh(self) -> list[dict]:
        return [v for v in self.video if not v["anh"]]

    @property
    def can_nhan(self) -> list[dict]:
        return [v for v in self.co_anh if v["nhan"] is None]

    @property
    def can_caption(self) -> list[dict]:
        return [v for v in self.co_anh if v["caption"] is None]

    def so_goi_agy(self) -> int:
        """Ước tính: vision theo lô + một lượt caption (nếu có caption chữ cần
        chấm) + một lượt chuẩn hoá (nếu còn video có ảnh)."""
        return (math.ceil(len(self.can_nhan) / LO_NHAN)
                + int(any(v["description"].strip() for v in self.can_caption))
                + int(bool(self.co_anh)))


def _ly_do_tu_choi(d: dict) -> str | None:
    if not nguon_duoc_phep(d["url"]):
        return f"nguồn không phải TikTok công khai ({d['url']}) — ảnh không được rời máy"
    lan = d.get("luot_moi_nhat")
    # Cùng luật `models_chia.nhap_de_xuat` dùng để từ chối lúc ghi — hỏi ở
    # đây để không kéo ảnh / trả tiền agy cho một nháp chắc chắn bị chặn.
    if lan and lan["trang_thai"] == "de_xuat" and lan["so_thao_tac"] > 0:
        return (f"lượt chia {lan['id']} đang 'de_xuat' với {lan['so_thao_tac']} thao tác "
                f"sửa/duyệt — không ghi đè công người dùng")
    return None


def lap_ke_hoach(m, job_id: int, pb: PhienBan) -> KeHoach:
    d = cli_json(m, ["liet", str(job_id), "--nhan-ver", pb.nhan, "--caption-ver", pb.caption])
    for v in d["video"]:
        # Nhãn cache khai `so_khung` khác số ảnh ĐANG có (khung phụ bổ sung
        # sau) ⇒ coi như chưa có: nhãn đó đã không nhìn đủ ảnh.
        if v["nhan"] is not None and v["nhan"].get("so_khung") != len(v["anh"]):
            v["nhan"] = None
    return KeHoach(job_id, d["url"], _ly_do_tu_choi(d), d["video"], d["so_bi_loc"],
                   d.get("bi_loc_theo_ly_do", {}))


def in_ke_hoach(kh: KeHoach, out: Callable[[str], None]) -> None:
    if kh.tu_choi:
        out(f"job {kh.job_id}: TỪ CHỐI — {kh.tu_choi}")
        return
    co, khong = kh.co_anh, kh.khong_anh
    ly_do = kh.bi_loc_theo_ly_do
    out(f"job {kh.job_id}: {len(kh.video) + kh.so_bi_loc} → {len(kh.video)} video vào lượt · "
        f"bỏ {kh.so_bi_loc} (đã loại {ly_do.get('da_loai', 0)} · "
        f"đã ở cụm {ly_do.get('da_o_cum', 0)}) · có ảnh {len(co)} · "
        f"không có ảnh nào k={len(khong)}")
    if khong:
        out(f"  bỏ khỏi lượt vì không có ảnh ({len(khong)}): "
            f"{', '.join(v['video_id'] for v in khong)}")
    can_cap = kh.can_caption
    rong = sum(1 for v in can_cap if not v["description"].strip())
    out(f"  nhãn: cache {len(co) - len(kh.can_nhan)} · cần gán {len(kh.can_nhan)} "
        f"({sum(len(v['anh']) for v in kh.can_nhan)} ảnh) · caption: cache "
        f"{len(co) - len(can_cap)} · rỗng⇒khong_ro {rong} · cần chấm {len(can_cap) - rong}")
    out(f"  ước tính {kh.so_goi_agy()} lượt gọi agy")
