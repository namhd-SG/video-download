#!/usr/bin/env python3
"""Tầng hình — chạy trên MÁY DEV, người dùng bấm tay. Vỏ bash: `scripts/phan-tich-hinh.sh`.

Mỗi lượt tải (job): liệt video (qua CLI mini) → kéo poster/khung → agy vision
gán nhãn → agy chấm caption lệch chủ đề → agy chuẩn hoá 2 tầng nhóm→kiểu →
kiểm máy → ghi nháp lên mini (một transaction). Nhãn và cờ caption ĐÃ QUA
phép kiểm được lưu lên mini NGAY (transaction riêng, trước chuẩn hoá), theo
phiên bản prompt RIÊNG của từng loại: chạy lại (đổi trục, chia lại, hay sau
một lần chuẩn hoá trượt) không trả tiền lại cho phần đã có.

KHÔNG có `--yes` ⇒ THỬ KHÔ: in kế hoạch rồi thoát, không kéo ảnh, không gọi
agy, không ghi gì.

Mã thoát: 0 xong · 2 sai cú pháp · 3 ĐO HỎNG (ssh/CLI mini/agy không sinh tệp
đích hay sinh tệp rác — chưa biết kết quả) · 4 KẾT QUẢ KHÔNG ĐẠT (có tệp,
trượt phép kiểm; không ghi nháp) · 5 TỪ CHỐI (nguồn không phải TikTok công
khai, hoặc nháp đang có sửa tay).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

_DAY = Path(__file__).resolve().parent
sys.path.insert(0, str(_DAY))

import agy_lenh  # noqa: E402
import mini as mini_mod  # noqa: E402
from ke_hoach import (LO_NHAN, MA_CU_PHAP, MA_DO_HONG, MA_KHONG_DAT, MA_OK,  # noqa: E402,F401
                      MA_TU_CHOI, DoHong, KeHoach, KhongDat, PhienBan, TuChoi, cli_json,
                      in_ke_hoach, lap_ke_hoach, nguon_duoc_phep)


def _nap_kiem():
    """`kiem-ket-qua.py` có gạch nối (tên do kế hoạch đặt) ⇒ nạp theo đường dẫn."""
    spec = importlib.util.spec_from_file_location("kiem_ket_qua", _DAY / "kiem-ket-qua.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kiem = _nap_kiem()

TRUC = ("trang_phuc_dam_dong", "trang_phuc_nguoi_chinh", "boi_canh")
# Cùng tên biến + mặc định với `deploy/rollback-on-mini.sh`.
MINI_HOST_MAC_DINH = "nobi_auto@100.109.39.103"
MINI_REPO_MAC_DINH = "~/Projects/video-download"
# Trần một lượt agy: `--print-timeout 25m` cộng một phút lề.
AGY_TIMEOUT_GIAY = 26 * 60


def _agy(argv, tep_ra, chay_agy, dang, scratch):
    try:
        return agy_lenh.chay(argv, tep_ra, chay_agy, dang, cwd=scratch)
    except agy_lenh.KhongCoTepDich as exc:
        raise DoHong(str(exc)) from exc


def _luu_dac_diem(m, job_id: int, hang: list[dict]) -> None:
    """Lưu hàng cache (đã qua phép kiểm) lên mini, transaction riêng."""
    if not hang:
        return
    du_lieu = json.dumps({"dac_diem": hang}, ensure_ascii=False).encode("utf-8")
    try:
        rc, _, err = m.cli(["ghi-dac-diem", str(job_id), "-"], du_lieu)
    except mini_mod.LoiMini as exc:
        raise DoHong(str(exc)) from exc
    if rc == 4:
        raise KhongDat(f"mini từ chối hàng cache: {err.strip()[:300]}")
    if rc != 0:
        raise DoHong(f"mini `ghi-dac-diem` rc={rc}: {err.strip()[:300]}")


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


def _gan_nhan(m, kh: KeHoach, pb: PhienBan, scratch: Path, chay_agy, agy_bin, out,
              thu_muc_prompt) -> dict[str, dict]:
    """Nhãn của MỌI video có ảnh: cache + gán mới theo lô. Mỗi lô qua phép
    kiểm thì lưu lên mini ngay."""
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
    nhan = {v["video_id"]: v["nhan"] for v in kh.co_anh if v["nhan"] is not None}
    so_moi = 0
    for i in range(0, len(can_nhan), LO_NHAN):
        lo = can_nhan[i:i + LO_NHAN]
        tep_ra = scratch / f"nhan-{i // LO_NHAN + 1}.jsonl"
        argv, _ = agy_lenh.lenh_nhan(
            scratch, [{"video_id": v["video_id"], "anh": [str(thu_muc_anh / d) for d in v["anh"]]}
                      for v in lo], tep_ra, agy_bin, thu_muc_prompt, pb.model_nhan)
        hang = _agy(argv, tep_ra, chay_agy, "jsonl", scratch)
        loi = kiem.kiem_nhan(hang, {v["video_id"] for v in lo},
                             {v["video_id"]: len(v["anh"]) for v in lo})
        out(f"  nhãn lô {i // LO_NHAN + 1}: {len(hang)} dòng / {len(lo)} video · {len(loi)} lỗi")
        if loi:
            raise KhongDat("\n".join(loi))
        # Lưu SAU phép kiểm, không bao giờ trước.
        _luu_dac_diem(m, kh.job_id, [{"video_id": h["video_id"], "phien_ban_prompt": pb.nhan,
                                      "nhan": h} for h in hang])
        nhan.update({h["video_id"]: h for h in hang})
        so_moi += len(hang)
    out(f"  nhãn: cache {len(nhan) - so_moi} · mới {so_moi} (đã lưu) · tổng {len(nhan)}")
    return nhan


def _cham_caption(m, kh: KeHoach, pb: PhienBan, scratch: Path, chay_agy, agy_bin, out,
                  thu_muc_prompt) -> dict[str, object]:
    """Cờ caption — caption rỗng là "không có bằng chứng", không gọi agy. Cờ
    qua phép kiểm được lưu lên mini ngay.

    Trả `{video_id: cờ}` cho MỌI video có ảnh (`kh.co_anh`) — cache (đã chấm
    từ trước, đọc lại từ `v["caption"]`) CỘNG mới chấm ở lượt này — để
    `chay_luot` áp luật "caption lệch chủ đề ⇒ nghi" trên đủ cả lượt, không
    chỉ phần vừa chấm."""
    can_cap = kh.can_caption
    moi = {v["video_id"]: "khong_ro" for v in can_cap if not v["description"].strip()}
    co_chu = {v["video_id"]: v["description"] for v in can_cap if v["description"].strip()}
    if co_chu:
        tep_ra = scratch / "caption.json"
        argv, _ = agy_lenh.lenh_caption(scratch, kh.url, co_chu, tep_ra, agy_bin, thu_muc_prompt,
                                        pb.model_chuan_hoa)
        obj, trung = _agy(argv, tep_ra, chay_agy, "json", scratch)
        loi = kiem.kiem_caption(obj, set(co_chu), trung)
        out(f"  caption: {len(obj) if isinstance(obj, dict) else '?'} cờ / {len(co_chu)} video · "
            f"{len(loi)} lỗi")
        if loi:
            raise KhongDat("\n".join(loi))
        moi.update(obj)
    _luu_dac_diem(m, kh.job_id, [{"video_id": v, "phien_ban_prompt": pb.caption,
                                  "nhan": {"caption_lech_chu_de": c}} for v, c in moi.items()])
    out(f"  caption: cache {len(kh.co_anh) - len(can_cap)} · rỗng⇒khong_ro "
        f"{len(can_cap) - len(co_chu)} · chấm mới {len(co_chu)} (đã lưu)")
    cache = {v["video_id"]: v["caption"]["caption_lech_chu_de"]
             for v in kh.co_anh if v["caption"] is not None}
    return {**cache, **moi}


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
    ten = cli_json(m, ["ten-co-san", str(kh.job_id)])
    out(f"  tên có sẵn: {len(ten['kieu'])} kiểu"
        + ("" if ten["loc_theo_insight"] else " (không lọc theo insight)"))

    nhan = _gan_nhan(m, kh, pb, scratch, chay_agy, agy_bin, out, thu_muc_prompt)
    cap = _cham_caption(m, kh, pb, scratch, chay_agy, agy_bin, out, thu_muc_prompt)

    # Chuẩn hoá — thẻ chữ đi thẳng làn hướng dẫn, không qua agy.
    huong_dan = [v for v in ids if nhan[v].get("the_chu") is True]
    ids_chia = [v for v in ids if nhan[v].get("the_chu") is not True]
    nhoms: list[dict] = []
    nghi: list[str] = []
    if ids_chia:
        tep_ra = scratch / "chia.json"
        argv, _ = agy_lenh.lenh_chuan_hoa(scratch, truc, {v: nhan[v] for v in ids_chia},
                                          ten["kieu"], tep_ra, agy_bin, thu_muc_prompt,
                                          pb.model_chuan_hoa)
        obj, trung = _agy(argv, tep_ra, chay_agy, "json", scratch)
        loi = kiem.kiem_chia(obj, set(ids_chia), trung)
        if loi:
            out(f"  chuẩn hoá: {len(loi)} lỗi")
            raise KhongDat("\n".join(loi))
        out(f"  chuẩn hoá: {len(obj['nhom'])} nhóm · {len(obj['gan'])} gán / "
            f"{len(ids_chia)} video · 0 lỗi")
        nhoms, hd_them, nghi = chuyen_chia(obj, ids_chia)
        huong_dan += hd_them

    # Caption lệch chủ đề (`caption_lech_chu_de` == True) CHỈ được ĐẨY video
    # RA khỏi một kiểu vào làn nghi — không bao giờ ngược lại: `false`/
    # `khong_ro` không đổi gì, và video đã ở "hướng dẫn"/"nghi" không bị đây
    # đụng tới (vòng lặp chỉ soi `nhoms`, xem `phase-04` mục "Bổ sung trước
    # thi công").
    chuyen_nghi = 0
    nhoms_con_video: list[dict] = []
    for n in nhoms:
        kieu_con_video = []
        for k in n["kieu"]:
            o_lai, day_nghi = [], []
            for vid in k["video_ids"]:
                (day_nghi if cap.get(vid) is True else o_lai).append(vid)
            if day_nghi:
                nghi.extend(day_nghi)
                chuyen_nghi += len(day_nghi)
            if o_lai:
                kieu_con_video.append({"kieu": k["kieu"], "video_ids": o_lai})
        if kieu_con_video:
            nhoms_con_video.append({"nhom": n["nhom"], "kieu": kieu_con_video})
    nhoms = nhoms_con_video
    out(f"  caption lệch ⇒ nghi: {chuyen_nghi}")

    # Kiểm cả nháp rồi mới ghi.
    tat_ca = [v for n in nhoms for k in n["kieu"] for v in k["video_ids"]] + huong_dan + nghi
    loi = kiem.kiem_tap_id(tat_ca, set(ids), "nháp")
    if loi:
        raise KhongDat("\n".join(loi))
    tep = {"phien_ban_prompt": pb.cho_chia_lan(), "truc": truc, "nhoms": nhoms,
           "huong_dan": huong_dan, "nghi": nghi, "dac_diem": []}
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
    try:
        ket = json.loads(ra)
        so = (ket["chia_lan_id"], ket["so_video"], len(ket["da_o_cum"]), len(ket["bo_vi_loc"]))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DoHong(f"mini `ghi` rc=0 nhưng kết quả không đọc được ({exc}) — nháp CÓ THỂ "
                     f"đã ghi, kiểm trên mini: {ra[:200]!r}") from exc
    out(f"  ĐÃ GHI nháp lượt {so[0]}: {so[1]} video · "
        f"{sum(len(n['kieu']) for n in nhoms)} kiểu · hướng dẫn {len(huong_dan)} · nghi {len(nghi)}"
        f" · bỏ vì đã ở cụm {so[2]} · bỏ vì bị lọc {so[3]}")
    if kh.khong_anh:
        out(f"  bỏ k={len(kh.khong_anh)} video không có ảnh: "
            f"{', '.join(v['video_id'] for v in kh.khong_anh)}")
    # Ảnh chỉ cần trong lúc chạy; lượt trượt thì GIỮ lại (in đường dẫn) để soi.
    shutil.rmtree(scratch / "anh", ignore_errors=True)
    # Prompt + kết quả (`nhan-*.jsonl`, `caption.json`, `chia.json`, `ghi.json`)
    # KHÔNG bị dọn dù lượt THÀNH CÔNG — cố ý: đây là chỗ DUY NHẤT user tự soát
    # được "vì sao video X vào kiểu Y" sau khi nháp đã ghi lên mini.
    out(f"  đã dọn ảnh tạm: {scratch / 'anh'} — giữ prompt/kết quả để soát: {scratch}")
    return ket


def _chay_agy_that(argv: list[str], cwd: Path) -> int | None:
    try:
        return subprocess.run(argv, timeout=AGY_TIMEOUT_GIAY, cwd=cwd).returncode
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
    p.add_argument("--ssh", default=os.environ.get("VIDEODL_MINI_HOST", MINI_HOST_MAC_DINH))
    p.add_argument("--repo-mini", default=os.environ.get("VIDEODL_MINI_REPO", MINI_REPO_MAC_DINH))
    p.add_argument("--thu-muc-prompt", type=Path, default=_DAY)
    p.add_argument("--model-nhan", help=f"model vision (mặc định {agy_lenh.MODEL_NHAN}); "
                                        "không tự rơi tầng — đổi tay, phiên bản cache đổi theo")
    p.add_argument("--model-chuan-hoa", help=f"model chuẩn hoá + caption (mặc định "
                                             f"{agy_lenh.MODEL_CHUAN_HOA})")
    try:
        a = p.parse_args(argv)
    except SystemExit as exc:
        return MA_CU_PHAP if exc.code else MA_OK

    pb = PhienBan.tu_thu_muc(a.thu_muc_prompt, a.model_nhan, a.model_chuan_hoa)
    try:
        m = (mini_mod.MiniCucBo(a.mini_db) if a.mini_db else
             mini_mod.MiniSsh(a.ssh, a.repo_mini, chay_lenh or mini_mod.chay_that,
                              ssh_bin=os.environ.get("SSH_BIN", "ssh")))
    except ValueError as exc:
        out(f"tham số sai: {exc}")
        return MA_CU_PHAP
    agy_bin = os.environ.get("AGY_BIN", "agy")
    chay_agy = chay_agy or _chay_agy_that
    out(f"phiên bản prompt: {pb.cho_chia_lan()}")
    try:
        jobs = [a.luot] if a.luot is not None else \
            [int(j["job_id"]) for j in cli_json(m, ["cho-chia"])]
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
    chay = [kh.job_id for kh in ke_hoach if not kh.tu_choi]
    for i, kh in enumerate(kh for kh in ke_hoach if not kh.tu_choi):
        scratch = goc / f"job-{kh.job_id}"
        try:
            chay_luot(m, kh, pb, scratch, chay_agy, agy_bin, a.truc, out, a.thu_muc_prompt)
        except DoHong as exc:
            out(f"ĐO HỎNG (job {kh.job_id}): {exc}\n  giữ scratch để soi: {scratch}")
            _tong_ket(out, tu_choi, chay[i + 1:])
            return MA_DO_HONG
        except KhongDat as exc:
            out(f"KHÔNG ĐẠT (job {kh.job_id}) — không ghi nháp:\n{exc}\n"
                f"  giữ scratch để soi: {scratch}")
            _tong_ket(out, tu_choi, chay[i + 1:])
            return MA_KHONG_DAT
        except TuChoi as exc:
            out(f"TỪ CHỐI GHI (job {kh.job_id}): {exc}")
            tu_choi.append(kh.job_id)
    return MA_TU_CHOI if tu_choi else MA_OK


def _tong_ket(out, tu_choi: list[int], chua_chay: list[int]) -> None:
    """Dòng chót khi dừng sớm: mã thoát chỉ mang MỘT tình trạng (thứ tự nặng
    3 đo hỏng > 4 không đạt > 5 từ chối), nên các job đã bị từ chối trước đó
    và các job chưa kịp chạy phải được kể lại ở đây — không thì một lượt từ
    chối bị mã 3/4 của job sau che mất."""
    out(f"tổng kết khi dừng: từ chối {tu_choi or 'không có'} · "
        f"chưa chạy {chua_chay or 'không có'}")


if __name__ == "__main__":
    sys.exit(main())
