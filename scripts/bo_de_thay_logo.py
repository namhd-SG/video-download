#!/usr/bin/env python3
"""Bộ đề hồi quy thay logo: so MỘT lượt chạy của nhánh với lượt MỐC (bản đang chạy prod) trên cùng bộ video, áp luật lên 3 vế.

Mốc prod KHÔNG phải "đúng": nó chỉ là mốc ĐỐI CHIẾU. "Đúng" chỉ có ở khung có NHÃN NGƯỜI (`tests/kho_ca/thay_logo/khung_vang.json`).

Một lượt chạy = thư mục `<ra>/<N>/` cho mỗi video N, gồm `kq.json` (dòng của `bo-de-mot-video.sh`), `files/1/track.json.gz`,
`log.db` (bảng `tl_vet`: trạng thái từng vết) và `md5` (của `ra.mp4`, rỗng/thiếu khi video không xuất).
Khung ĐƯỢC ĐÈ ⟺ video `render` VÀ vết `render` VÀ state ∈ {detected, filled} (`cong.khung_duoc_render`, `xu_ly_video.xu_ly`).

Luật lên (mã thoát):
  (a) khung nhãn `dung`: nhánh phải đè, lệch mỗi cạnh ≤ LECH_PX so với box nhãn            — vi phạm ⇒ rc 1
  (b) nhãn `khong_duoc_de` (một khung, hoặc cả video khi `frame` = null): nhánh không được đè — vi phạm ⇒ rc 1
  đối chứng md5: video không có khung đổi và không đổi trạng thái ⇒ md5 phải trùng mốc          — lệch ⇒ rc 1
  (c) khung KHÔNG nhãn mà nhánh đổi kết quả: phải có tệp soi (người xem ảnh lớn toàn khung) phủ đủ mẫu, 0 mẫu `sai`
      — thiếu tệp / chưa đủ ⇒ rc 2 (CHỜ SOI); có mẫu `sai` ⇒ rc 1
  và phải có ≥ 1 ca lỗi được sửa (nhãn lỗi có `box_dung` mà nhánh đè trúng; hoặc mẫu soi của ca lỗi ghi `sua`) — chưa ⇒ rc 2
  rc 0 = được đề xuất lên (vẫn qua agy + ĐP). rc 3 = lượt chạy thiếu/hỏng (hạ tầng, không phải kết luận về mã).

    python scripts/bo_de_thay_logo.py so <thư mục mốc> <thư mục nhánh> [--soi soi.json] [--ra <thư mục báo cáo>]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sqlite3
import sys
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent
BO_DE = GOC / "tests/kho_ca/thay_logo/bo_de.json"
KHUNG_VANG = GOC / "tests/kho_ca/thay_logo/khung_vang.json"
DA_CHAC = ("detected", "filled")
LECH_PX = 3
SO_MAU_SOI = 20
HAT_MAU_SOI = 20261023
LOAI_LOI = ("lo_logo", "lo_mep", "che_nham", "nen_lech", "lech")


class LuotHong(Exception):
    """Lượt chạy thiếu tệp / rc ≠ 0: không kết luận được gì về mã."""


def doc_video(d: Path) -> dict:
    """{tt, md5, de: {frame: (x, y, w, h)}} — khung đè của video (nhiều vết cùng khung ⇒ giữ box vết đầu, ghi `trung`)."""
    kq_p = d / "kq.json"
    if not kq_p.exists():
        raise LuotHong(f"{d}: thiếu kq.json")
    kq = json.loads(kq_p.read_text())
    if kq.get("rc") != 0 or not isinstance(kq.get("kq"), dict):
        raise LuotHong(f"{d}: rc={kq.get('rc')} — xem stderr.log")
    tt = kq["kq"].get("trang_thai")
    md5_p, ra_p = d / "md5", d / "ra.mp4"
    md5 = md5_p.read_text().strip() if md5_p.exists() else (hashlib.md5(ra_p.read_bytes()).hexdigest() if ra_p.exists() else "")
    de: dict[int, tuple] = {}
    trung = 0
    if tt == "render":
        track = json.load(gzip.open(d / "files/1/track.json.gz"))
        with sqlite3.connect(f"file:{d / 'log.db'}?mode=ro", uri=True) as c:
            tt_vet = dict(c.execute("SELECT vet, trang_thai FROM tl_vet"))
        if len(tt_vet) != len(track):
            raise LuotHong(f"{d}: tl_vet {len(tt_vet)} vết ≠ track {len(track)} vết")
        for k, vet in enumerate(track):
            if tt_vet.get(k) != "render":
                continue
            for e in vet:
                if e.get("state") in DA_CHAC:
                    if e["frame"] in de:
                        trung += 1
                        continue
                    de[e["frame"]] = (e["x"], e["y"], e["w"], e["h"])
        if not md5:
            raise LuotHong(f"{d}: video render mà thiếu md5")
    return {"tt": tt, "md5": md5, "de": de, "trung": trung}


def doc_luot(ra: Path, ds: list[int]) -> dict[int, dict]:
    return {n: doc_video(ra / str(n)) for n in ds}


def lech(a: tuple, b: tuple) -> int:
    return max(abs(p - q) for p, q in zip(a, b))


def khung_doi(m: dict, n: dict) -> list[tuple[int, str]]:
    """Khung có kết quả khác giữa mốc m và nhánh n: (frame, kiểu) với kiểu ∈ {mat_de, them_de, doi_box}."""
    out = []
    for f in sorted(set(m["de"]) | set(n["de"])):
        a, b = m["de"].get(f), n["de"].get(f)
        if a is None:
            out.append((f, "them_de"))
        elif b is None:
            out.append((f, "mat_de"))
        elif lech(a, b) > LECH_PX:
            out.append((f, "doi_box"))
    return out


def chon_mau(doi: dict[int, list], co_nhan: set[tuple[int, int]], so: int = SO_MAU_SOI, hat: int = HAT_MAU_SOI) -> list[dict]:
    """Mẫu soi rải đều video: vòng tròn qua các video có khung đổi KHÔNG nhãn, mỗi lượt lấy một khung ngẫu nhiên (hạt cố định).
    Ít hơn `so` khung đổi ⇒ lấy hết."""
    rng = random.Random(hat)
    hang = {v: [f for f in fs if (v, f[0]) not in co_nhan] for v, fs in sorted(doi.items())}
    hang = {v: rng.sample(fs, len(fs)) for v, fs in hang.items() if fs}
    mau = []
    while len(mau) < so and any(hang.values()):
        for v in sorted(hang):
            if hang[v] and len(mau) < so:
                f, kieu = hang[v].pop()
                mau.append({"v": v, "frame": f, "kieu": kieu})
    return sorted(mau, key=lambda x: (x["v"], x["frame"]))


def so_sanh(moc: dict[int, dict], nhanh: dict[int, dict], nhan: list[dict], soi: dict | None) -> dict:
    vi_pham, sua, cho_soi = [], [], []
    for x in nhan:
        v, f, loai = x["v"], x.get("frame"), x["loai"]
        r = nhanh[v]
        if loai == "dung":
            b = r["de"].get(f)
            if b is None:
                vi_pham.append(f"(a) v{v}#{f} nhãn dung: nhánh KHÔNG đè")
            elif lech(b, tuple(x["box"])) > LECH_PX:
                vi_pham.append(f"(a) v{v}#{f} nhãn dung: lệch {lech(b, tuple(x['box']))} px > {LECH_PX}")
        elif loai == "khong_duoc_de":
            bi = sorted(r["de"]) if f is None else ([f] if f in r["de"] else [])
            if bi:
                vi_pham.append(f"(b) v{v}{'' if f is None else f'#{f}'} không được đè: nhánh đè {len(bi)} khung (đầu: #{bi[0]})")
        elif loai in LOAI_LOI:
            b = r["de"].get(f)
            if x.get("box_dung") and b is not None and lech(b, tuple(x["box_dung"])) <= LECH_PX:
                sua.append(f"v{v}#{f} {loai}")
            elif b != moc[v]["de"].get(f):
                cho_soi.append({"v": v, "frame": f, "kieu": f"ca_loi:{loai}"})
        else:
            raise ValueError(f"nhãn lạ: {x}")

    doi = {v: khung_doi(moc[v], nhanh[v]) for v in moc}
    doi = {v: fs for v, fs in doi.items() if fs}
    doi_tt = [v for v in moc if moc[v]["tt"] != nhanh[v]["tt"]]
    md5_lech = [v for v in moc if v not in doi and v not in doi_tt and moc[v]["md5"] != nhanh[v]["md5"]]
    vi_pham += [f"md5 v{v}: không khung nào đổi mà bản ra khác mốc" for v in md5_lech]

    co_nhan = {(x["v"], x.get("frame")) for x in nhan}
    mau = chon_mau(doi, co_nhan) + cho_soi
    ket_soi = {(m["v"], m["frame"]): m.get("ket_qua") for m in (soi or {}).get("mau", [])}
    chua = [m for m in mau if ket_soi.get((m["v"], m["frame"])) not in ("dung", "sai", "sua")]
    sai = [m for m in mau if ket_soi.get((m["v"], m["frame"])) == "sai"]
    vi_pham += [f"(c) v{m['v']}#{m['frame']} người soi ghi SAI" for m in sai]
    sua += [f"v{m['v']}#{m['frame']} (soi)" for m in mau if ket_soi.get((m["v"], m["frame"])) == "sua"]

    if vi_pham:
        rc, ket = 1, "KHÔNG LÊN — vi phạm"
    elif chua:
        rc, ket = 2, f"CHỜ SOI — {len(chua)}/{len(mau)} mẫu chưa có kết quả người"
    elif not sua:
        rc, ket = 2, "CHƯA LÊN — không ca lỗi nào được sửa"
    else:
        rc, ket = 0, "ĐỀ XUẤT LÊN (còn agy + ĐP)"
    return {"rc": rc, "ket": ket, "vi_pham": vi_pham, "sua": sua, "mau": mau, "video_doi": sorted(set(doi) | set(doi_tt)),
            "doi_tt": doi_tt, "md5_lech": md5_lech, "so_khung_doi": {v: len(fs) for v, fs in doi.items()}}


def bang(moc: dict, nhanh: dict, kq: dict, bo_de: dict) -> str:
    phia = {x["v"]: x["phia"] for x in bo_de["video"]}
    dong = [f"# Bộ đề thay logo — {kq['ket']} (rc {kq['rc']})", "",
            f"- video có kết quả khác mốc: **{len(kq['video_doi'])}** {kq['video_doi']}",
            f"- video đổi trạng thái: {kq['doi_tt'] or 0}", f"- đối chứng md5 lệch: {kq['md5_lech'] or 0}",
            f"- ca lỗi được sửa: {kq['sua'] or 0}", "", "| phía | video | đè (mốc → nhánh) | khung đổi |", "|---|---|---|---|"]
    for p in ("thiet_ke", "giu_kin"):
        ds = [v for v in moc if phia.get(v) == p]
        dong.append(f"| {p} | {len(ds)} | {sum(len(moc[v]['de']) for v in ds)} → {sum(len(nhanh[v]['de']) for v in ds)} | "
                    f"{sum(kq['so_khung_doi'].get(v, 0) for v in ds)} |")
    dong += ["", "## Vi phạm", *(f"- {x}" for x in kq["vi_pham"] or ["0"]), "", "## Mẫu soi (ảnh lớn toàn khung)",
             *(f"- v{m['v']}#{m['frame']} {m['kieu']}" for m in kq["mau"] or [{"v": "-", "frame": "-", "kieu": "không có khung đổi"}])]
    return "\n".join(dong) + "\n"


def chia_giu_kin(don_vi: list[dict], so_giu_kin: int, hat: int) -> list[int]:
    """Chọn video GIỮ KÍN theo ĐƠN VỊ (nhóm biến thể cùng creative ở cùng một phía — tách ra là rò đề): xáo đơn vị bằng hạt cố định,
    lấy lần lượt, mỗi thương hiệu tối đa một đơn vị (rải thương hiệu), bỏ đơn vị làm vượt `so_giu_kin`. Đơn vị `co_dinh` = thiết kế."""
    ung_vien = [u for u in don_vi if not u.get("co_dinh")]
    random.Random(hat).shuffle(ung_vien)
    chon, da_co = [], set()
    for u in ung_vien:
        if u["thuong_hieu"] in da_co or len(chon) + len(u["v"]) > so_giu_kin:
            continue
        chon += u["v"]
        da_co.add(u["thuong_hieu"])
    if len(chon) != so_giu_kin:
        raise ValueError(f"không chia đủ {so_giu_kin} video giữ kín (được {len(chon)})")
    return sorted(chon)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="lenh", required=True)
    s = sp.add_parser("so")
    s.add_argument("moc", type=Path)
    s.add_argument("nhanh", type=Path)
    s.add_argument("--soi", type=Path)
    s.add_argument("--ra", type=Path)
    a = ap.parse_args(argv)
    bo_de = json.loads(BO_DE.read_text())
    nhan = json.loads(KHUNG_VANG.read_text())["nhan"]
    ds = [x["v"] for x in bo_de["video"]]
    try:
        moc, nhanh = doc_luot(a.moc, ds), doc_luot(a.nhanh, ds)
    except LuotHong as e:
        print(f"LƯỢT HỎNG: {e}", file=sys.stderr)
        return 3
    soi = json.loads(a.soi.read_text()) if a.soi and a.soi.exists() else None
    kq = so_sanh(moc, nhanh, nhan, soi)
    txt = bang(moc, nhanh, kq, bo_de)
    print(txt)
    if a.ra:
        a.ra.mkdir(parents=True, exist_ok=True)
        (a.ra / "bao-cao.md").write_text(txt)
        (a.ra / "mau-soi.json").write_text(json.dumps({"moc": str(a.moc), "nhanh": str(a.nhanh), "mau": kq["mau"]},
                                                       ensure_ascii=False, indent=1))
    return kq["rc"]


if __name__ == "__main__":
    sys.exit(main())
