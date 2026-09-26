#!/usr/bin/env python3
"""Tầng hình — chạy trên MÁY DEV, người dùng bấm tay. Vỏ bash: `scripts/phan-tich-hinh.sh`.

Mỗi lượt tải (job): liệt video (qua CLI mini) → kéo poster/khung → agy vision
gán nhãn → agy chấm caption lệch chủ đề → agy chuẩn hoá 2 tầng nhóm→kiểu →
kiểm máy → ghi nháp lên mini (một transaction). Nhãn và cờ caption cache trên
mini theo phiên bản prompt RIÊNG của từng loại: chạy lại (đổi trục, chia lại)
không trả tiền lại cho phần đã có.

KHÔNG có `--yes` ⇒ THỬ KHÔ: in kế hoạch rồi thoát, không kéo ảnh, không gọi
agy, không ghi gì.

Mã thoát: 0 xong · 2 sai cú pháp · 3 ĐO HỎNG (ssh/CLI mini/agy không sinh tệp
đích — chưa biết kết quả) · 4 KẾT QUẢ KHÔNG ĐẠT (có tệp, trượt phép kiểm; không
ghi gì) · 5 TỪ CHỐI (nguồn không phải TikTok công khai, hoặc nháp đang có sửa tay).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_DAY = Path(__file__).resolve().parent
sys.path.insert(0, str(_DAY))

import agy_lenh  # noqa: E402
import mini as mini_mod  # noqa: E402


def _nap_kiem():
    """`kiem-ket-qua.py` có gạch nối (tên do kế hoạch đặt) ⇒ nạp theo đường dẫn."""
    spec = importlib.util.spec_from_file_location("kiem_ket_qua", _DAY / "kiem-ket-qua.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kiem = _nap_kiem()

MA_OK, MA_CU_PHAP, MA_DO_HONG, MA_KHONG_DAT, MA_TU_CHOI = 0, 2, 3, 4, 5

# Ảnh rời máy sang Google khi gọi agy ⇒ chỉ video TikTok CÔNG KHAI.
NGUON_CHO_PHEP = "https://www.tiktok.com/"
TRUC = ("trang_phuc_dam_dong", "trang_phuc_nguoi_chinh", "boi_canh")
# Số video mỗi lượt gọi vision (≤3 ảnh/video ⇒ ≤60 ảnh/lượt). Chọn, chưa đo
# trần thật của agy.
LO_NHAN = 20
MINI_SSH_MAC_DINH = "nobi_auto@100.109.39.103"
MINI_REPO_MAC_DINH = "~/Projects/video-download"
# Trần một lượt agy: `--print-timeout 25m` cộng một phút lề.
AGY_TIMEOUT_GIAY = 26 * 60


class DoHong(Exception):
    """Phép đo / đường ống hỏng — chưa có kết quả để phán."""


class KhongDat(Exception):
    """Có kết quả nhưng trượt phép kiểm máy — không ghi gì."""


class TuChoi(Exception):
    """Lượt không được phép chạy/ghi."""


def nguon_duoc_phep(url) -> bool:
    return isinstance(url, str) and url.startswith(NGUON_CHO_PHEP)


@dataclass(frozen=True)
class PhienBan:
    nhan: str
    caption: str
    chuan_hoa: str

    @classmethod
    def tu_thu_muc(cls, thu_muc: Path) -> "PhienBan":
        return cls(*(agy_lenh.phien_ban(loai, thu_muc) for loai in ("nhan", "caption", "chuan_hoa")))

    def cho_chia_lan(self) -> str:
        return f"{self.nhan};{self.caption};{self.chuan_hoa}"


def _cli_json(m, args: list[str], stdin: bytes | None = None):
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


def lap_ke_hoach(m, job_id: int, pb: PhienBan) -> KeHoach:
    d = _cli_json(m, ["liet", str(job_id), "--nhan-ver", pb.nhan, "--caption-ver", pb.caption])
    tu_choi = None if nguon_duoc_phep(d["url"]) else \
        f"nguồn không phải TikTok công khai ({d['url']}) — ảnh không được rời máy"
    return KeHoach(job_id, d["url"], tu_choi, d["video"], d["so_bi_loc"])


def in_ke_hoach(kh: KeHoach, out: Callable[[str], None]) -> None:
    if kh.tu_choi:
        out(f"job {kh.job_id}: TỪ CHỐI — {kh.tu_choi}")
        return
    co, khong = kh.co_anh, kh.khong_anh
    out(f"job {kh.job_id}: {len(kh.video)} video vào lượt (bị lọc {kh.so_bi_loc}) · "
        f"có ảnh {len(co)} · không có ảnh nào k={len(khong)}")
    if khong:
        out(f"  bỏ khỏi lượt vì không có ảnh ({len(khong)}): "
            f"{', '.join(v['video_id'] for v in khong)}")
    can_cap = kh.can_caption
    rong = sum(1 for v in can_cap if not v["description"].strip())
    out(f"  nhãn: cache {len(co) - len(kh.can_nhan)} · cần gán {len(kh.can_nhan)} "
        f"({sum(len(v['anh']) for v in kh.can_nhan)} ảnh) · caption: cache "
        f"{len(co) - len(can_cap)} · rỗng⇒khong_ro {rong} · cần chấm {len(can_cap) - rong}")
    out(f"  ước tính {kh.so_goi_agy()} lượt gọi agy")


def _agy(argv, tep_ra, chay_agy, dang):
    try:
        return agy_lenh.chay(argv, tep_ra, chay_agy, dang)
    except agy_lenh.KhongCoTepDich as exc:
        raise DoHong(str(exc)) from exc


def chuyen_chia(obj: dict, ids: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """Đầu ra chuẩn hoá (đã qua `kiem_chia`) ⇒ `(nhoms, huong_dan, nghi)` cho
    `ghi`. Tên lấy theo bản KHAI trong `nhom` (gán so casefold); kiểu không có
    video nào bị bỏ — không đề xuất một kiểu rỗng."""
    khoa = kiem.khoa_ten
    ten_that: dict[tuple[str, str], tuple[str, str]] = {}
    for nhom, ds in obj["nhom"].items():
        for k in ds:
            ten_that.setdefault((khoa(nhom), khoa(k)), (nhom, k))
    video_cua: dict[tuple[str, str], list[str]] = {t: [] for t in ten_that}
    huong_dan, nghi = [], []
    for vid in ids:
        g = obj["gan"][vid]
        if "lan" in g:
            (huong_dan if g["lan"] == "huong_dan" else nghi).append(vid)
        else:
            video_cua[(khoa(g["nhom"]), khoa(g["kieu"]))].append(vid)
    nhoms: dict[str, list[dict]] = {}
    for t, (nhom, k) in ten_that.items():
        if video_cua[t]:
            nhoms.setdefault(nhom, []).append({"kieu": k, "video_ids": video_cua[t]})
    return [{"nhom": n, "kieu": ks} for n, ks in nhoms.items()], huong_dan, nghi


def chay_luot(m, kh: KeHoach, pb: PhienBan, scratch: Path, chay_agy, agy_bin: str,
              truc: str, out: Callable[[str], None], thu_muc_prompt: Path) -> dict | None:
    scratch.mkdir(parents=True, exist_ok=True)
    scratch = scratch.resolve()
    co_anh = kh.co_anh
    ids = [v["video_id"] for v in co_anh]
    if not co_anh:
        out(f"job {kh.job_id}: 0 video có ảnh — không phân tích, không ghi nháp")
        return None
    out(f"job {kh.job_id}: bắt đầu — {len(co_anh)} video có ảnh, scratch {scratch}")
    ten = _cli_json(m, ["ten-co-san", str(kh.job_id)])
    out(f"  tên có sẵn: {len(ten['kieu'])} kiểu"
        + ("" if ten["loc_theo_insight"] else " (không lọc theo insight)"))

    # 1. Ảnh — chỉ của video CHƯA có nhãn cache.
    can_nhan = kh.can_nhan
    duong = [d for v in can_nhan for d in v["anh"]]
    thu_muc_anh = scratch / "anh"
    try:
        m.keo_anh(duong, thu_muc_anh)
    except mini_mod.LoiMini as exc:
        raise DoHong(str(exc)) from exc
    co = sum((thu_muc_anh / d).is_file() for d in duong)
    out(f"  kéo ảnh: {co}/{len(duong)}")
    if co != len(duong):
        raise DoHong(f"kéo được {co}/{len(duong)} ảnh")

    # 2. Nhãn vision theo lô.
    nhan = {v["video_id"]: v["nhan"] for v in co_anh if v["nhan"] is not None}
    moi_nhan: dict[str, dict] = {}
    for i in range(0, len(can_nhan), LO_NHAN):
        lo = can_nhan[i:i + LO_NHAN]
        tep_ra = scratch / f"nhan-{i // LO_NHAN + 1}.jsonl"
        argv, _ = agy_lenh.lenh_nhan(
            scratch, [{"video_id": v["video_id"], "anh": [str(thu_muc_anh / d) for d in v["anh"]]}
                      for v in lo], tep_ra, agy_bin, thu_muc_prompt)
        hang = _agy(argv, tep_ra, chay_agy, "jsonl")
        loi = kiem.kiem_nhan(hang, {v["video_id"] for v in lo},
                             {v["video_id"]: len(v["anh"]) for v in lo})
        out(f"  nhãn lô {i // LO_NHAN + 1}: {len(hang)} dòng / {len(lo)} video · {len(loi)} lỗi")
        if loi:
            raise KhongDat("\n".join(loi))
        moi_nhan.update({h["video_id"]: h for h in hang})
    nhan.update(moi_nhan)
    out(f"  nhãn: cache {len(nhan) - len(moi_nhan)} · mới {len(moi_nhan)} · tổng {len(nhan)}/{len(ids)}")

    # 3. Cờ caption — caption rỗng là "không có bằng chứng", không gọi agy.
    can_cap = kh.can_caption
    moi_cap = {v["video_id"]: {"caption_lech_chu_de": "khong_ro"}
               for v in can_cap if not v["description"].strip()}
    co_chu = {v["video_id"]: v["description"] for v in can_cap if v["description"].strip()}
    if co_chu:
        tep_ra = scratch / "caption.json"
        argv, _ = agy_lenh.lenh_caption(scratch, kh.url, co_chu, tep_ra, agy_bin, thu_muc_prompt)
        obj, trung = _agy(argv, tep_ra, chay_agy, "json")
        loi = kiem.kiem_caption(obj, set(co_chu), trung)
        out(f"  caption: {len(obj)} cờ / {len(co_chu)} video · {len(loi)} lỗi")
        if loi:
            raise KhongDat("\n".join(loi))
        moi_cap.update({v: {"caption_lech_chu_de": c} for v, c in obj.items()})
    out(f"  caption: cache {len(co_anh) - len(can_cap)} · rỗng⇒khong_ro "
        f"{len(can_cap) - len(co_chu)} · chấm mới {len(co_chu)}")

    # 4. Chuẩn hoá — thẻ chữ đi thẳng làn hướng dẫn, không qua agy.
    huong_dan = [v for v in ids if nhan[v].get("the_chu") is True]
    ids_chia = [v for v in ids if nhan[v].get("the_chu") is not True]
    nhoms: list[dict] = []
    nghi: list[str] = []
    if ids_chia:
        tep_ra = scratch / "chia.json"
        argv, _ = agy_lenh.lenh_chuan_hoa(scratch, truc, {v: nhan[v] for v in ids_chia},
                                          ten["kieu"], tep_ra, agy_bin, thu_muc_prompt)
        obj, trung = _agy(argv, tep_ra, chay_agy, "json")
        loi = kiem.kiem_chia(obj, set(ids_chia), trung)
        out(f"  chuẩn hoá: {len(obj.get('nhom', {}))} nhóm · {len(obj.get('gan', {}))} gán / "
            f"{len(ids_chia)} video · {len(loi)} lỗi")
        if loi:
            raise KhongDat("\n".join(loi))
        nhoms, hd_them, nghi = chuyen_chia(obj, ids_chia)
        huong_dan += hd_them

    # 5. Kiểm cả nháp rồi mới ghi.
    tat_ca = [v for n in nhoms for k in n["kieu"] for v in k["video_ids"]] + huong_dan + nghi
    loi = kiem.kiem_tap_id(tat_ca, set(ids), "nháp")
    if loi:
        raise KhongDat("\n".join(loi))
    tep = {"phien_ban_prompt": pb.cho_chia_lan(), "truc": truc, "nhoms": nhoms,
           "huong_dan": huong_dan, "nghi": nghi,
           "dac_diem": [{"video_id": v, "phien_ban_prompt": pb.nhan, "nhan": n}
                        for v, n in moi_nhan.items()]
           + [{"video_id": v, "phien_ban_prompt": pb.caption, "nhan": c}
              for v, c in moi_cap.items()]}
    du_lieu = json.dumps(tep, ensure_ascii=False).encode("utf-8")
    (scratch / "ghi.json").write_bytes(du_lieu)
    try:
        rc, ra, err = m.cli(["ghi", str(kh.job_id), "-"], du_lieu)
    except mini_mod.LoiMini as exc:
        raise DoHong(str(exc)) from exc
    if rc == 4:
        raise KhongDat(f"mini từ chối tệp: {err.strip()[:300]}")
    if rc == 5:
        raise TuChoi(err.strip()[:300])
    if rc != 0:
        raise DoHong(f"mini `ghi` rc={rc}: {err.strip()[:300]}")
    ket = json.loads(ra)
    out(f"  ĐÃ GHI nháp lượt {ket['chia_lan_id']}: {ket['so_video']} video · "
        f"{sum(len(n['kieu']) for n in nhoms)} kiểu · hướng dẫn {len(huong_dan)} · nghi {len(nghi)}"
        f" · bỏ vì đã ở cụm {len(ket['da_o_cum'])} · bỏ vì bị lọc {len(ket['bo_vi_loc'])}")
    if kh.khong_anh:
        out(f"  bỏ k={len(kh.khong_anh)} video không có ảnh: "
            f"{', '.join(v['video_id'] for v in kh.khong_anh)}")
    return ket


def _chay_agy_that(argv: list[str]) -> int | None:
    try:
        return subprocess.run(argv, timeout=AGY_TIMEOUT_GIAY).returncode
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        raise DoHong(f"không chạy được agy: {exc}") from exc


def main(argv: list[str] | None = None, *, chay_agy=None, chay_lenh=None,
         out: Callable[[str], None] = print) -> int:
    p = argparse.ArgumentParser(prog="phan-tich-hinh.sh", description=__doc__.split("\n\n")[0])
    p.add_argument("--luot", type=int, help="chỉ xử một lượt tải (job id)")
    p.add_argument("--yes", action="store_true", help="làm thật (mặc định: thử khô)")
    p.add_argument("--truc", choices=TRUC, default=TRUC[0])
    p.add_argument("--scratch", type=Path, help="thư mục tạm (mặc định: tạo mới trong $TMPDIR)")
    p.add_argument("--mini-db", type=Path, help="dùng DB CỤC BỘ này thay vì ssh (thử khô / test)")
    p.add_argument("--ssh", default=os.environ.get("MINI_SSH", MINI_SSH_MAC_DINH))
    p.add_argument("--repo-mini", default=os.environ.get("MINI_REPO", MINI_REPO_MAC_DINH))
    p.add_argument("--thu-muc-prompt", type=Path, default=_DAY)
    try:
        a = p.parse_args(argv)
    except SystemExit as exc:
        return MA_CU_PHAP if exc.code else MA_OK

    pb = PhienBan.tu_thu_muc(a.thu_muc_prompt)
    m = (mini_mod.MiniCucBo(a.mini_db) if a.mini_db else
         mini_mod.MiniSsh(a.ssh, a.repo_mini, chay_lenh or mini_mod.chay_that,
                          ssh_bin=os.environ.get("SSH_BIN", "ssh")))
    agy_bin = os.environ.get("AGY_BIN", "agy")
    chay_agy = chay_agy or _chay_agy_that
    out(f"phiên bản prompt: {pb.cho_chia_lan()}")
    try:
        jobs = [a.luot] if a.luot is not None else \
            [int(j["job_id"]) for j in _cli_json(m, ["cho-chia"])]
        out(f"{len(jobs)} lượt tải cần xử: {', '.join(map(str, jobs)) or '(không có)'}")
        ke_hoach = [lap_ke_hoach(m, j, pb) for j in jobs]
    except DoHong as exc:
        out(f"ĐO HỎNG: {exc}")
        return MA_DO_HONG
    for kh in ke_hoach:
        in_ke_hoach(kh, out)
    tu_choi = [kh.job_id for kh in ke_hoach if kh.tu_choi]
    out(f"tổng: {len(ke_hoach) - len(tu_choi)} lượt chạy được · từ chối {len(tu_choi)} · "
        f"ước tính {sum(kh.so_goi_agy() for kh in ke_hoach if not kh.tu_choi)} lượt gọi agy")
    if not a.yes:
        out("THỬ KHÔ: không kéo ảnh, không gọi agy, không ghi gì. Thêm --yes để làm thật.")
        return MA_TU_CHOI if tu_choi else MA_OK

    goc = a.scratch or Path(tempfile.mkdtemp(prefix="phan-tich-hinh-"))
    for kh in ke_hoach:
        if kh.tu_choi:
            continue
        try:
            chay_luot(m, kh, pb, goc / f"job-{kh.job_id}", chay_agy, agy_bin, a.truc, out,
                      a.thu_muc_prompt)
        except DoHong as exc:
            out(f"ĐO HỎNG (job {kh.job_id}): {exc}")
            return MA_DO_HONG
        except KhongDat as exc:
            out(f"KHÔNG ĐẠT (job {kh.job_id}) — không ghi gì:\n{exc}")
            return MA_KHONG_DAT
        except TuChoi as exc:
            out(f"TỪ CHỐI GHI (job {kh.job_id}): {exc}")
            tu_choi.append(kh.job_id)
    return MA_TU_CHOI if tu_choi else MA_OK


if __name__ == "__main__":
    sys.exit(main())
