"""`python -m tiktok_music_downloader.tim_trend <video>` — chỉ chạy ở máy dev: cần agy và Chrome CÓ CỬA SỔ (headless bị TikTok
trả rỗng, đo Pha 0 22/10). Cửa sổ Chrome bật lên trong lúc chạy và tự đóng khi xong hoặc lỗi.

RANH GIỚI DỮ LIỆU (ĐP 23/10): khung hình video được gửi lên agy (dịch vụ ngoài). CHỈ dùng cho video công khai (đối thủ,
trend). KHÔNG dùng cho creative nội bộ chưa chạy ads hay dữ liệu khách.

Mã thoát: 0 có kết quả · 3 không có ứng viên · 4 TikTok hỏi captcha · 5 mở trang lỗi · 6 chữ ký không ổn định (video nhiều cảnh) · 7 đối chứng dương trượt (2 là lỗi tham số của Click).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer

from .agy_boc import MODEL_MAC_DINH
from .cham import NGUONG_MAC_DINH
from .luong import ChuKyKhongOnDinh, chay, ghi_links
from .nguon_tim import ChromeTim
from .trang import render

app = typer.Typer(add_completion=False, help=__doc__, rich_markup_mode=None)


@app.command()
def main(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, help="File video creative đầu vào"),
    ra: Path = typer.Option(Path("./tim-trend-ra"), "--ra", help="Thư mục kết quả"),
    nguong: str = typer.Option(",".join(sorted(NGUONG_MAC_DINH)), "--nguong", help="Hạng giữ, vd 3,2A"),
    so_truy_van: int = typer.Option(6, "--so-truy-van", min=1, max=20, help="Truy vấn mỗi hop"),
    hop: int = typer.Option(2, "--hop", min=1, max=3, help="Số vòng (hop 2 = mở rộng từ caption kết quả đạt)"),
    tran_luot: int = typer.Option(12, "--tran-luot", min=1, max=40, help="Trần số lần mở trang TikTok (gồm lượt hâm phiên; KHÔNG gồm tải ảnh bìa từ CDN)"),
    gian_cach: float = typer.Option(12.0, "--gian-cach", min=5.0, help="Giây giữa 2 lần mở trang TikTok"),
    model: str = typer.Option(MODEL_MAC_DINH, "--model", help="Model agy bóc trường"),
    profile_ben: Path = typer.Option(None, "--profile-ben",
                                     help="Thư mục profile Chrome dùng lại giữa các lần chạy (mặc định: profile trắng mỗi lần)"),
    truy_van: str = typer.Option("", "--truy-van",
                                 help='Key hop 1 do người đưa, ngăn bởi "|" — thay hẳn key tự sinh (vd từ hồ sơ trend)'),
    cho_giai_captcha: int = typer.Option(0, "--cho-giai-captcha", min=0, max=600,
                                         help="Giây chờ NGƯỜI giải captcha trong cửa sổ; 0 = gặp captcha là dừng (mặc định)"),
) -> None:
    """Tìm thêm video TikTok CÙNG DẠNG với video đầu vào; ra links.txt cho Video Desk + trang index.html.

    Chỉ máy dev (cần agy + Chrome có cửa sổ). RANH GIỚI DỮ LIỆU: khung hình được gửi lên agy (dịch vụ ngoài) — CHỈ dùng
    cho video công khai (đối thủ, trend); KHÔNG dùng cho creative nội bộ chưa chạy ads hay dữ liệu khách.

    Mã thoát: 0 có kết quả · 3 không có ứng viên · 4 TikTok hỏi captcha · 5 mở trang lỗi · 6 chữ ký không ổn định (video nhiều cảnh) · 7 đối chứng dương trượt (2 là lỗi tham số của Click).
    """
    hang_giu = frozenset(x.strip() for x in nguong.split(",") if x.strip())
    try:
        kq = chay(video, ra, tao_nguon=lambda: ChromeTim(tran_luot, gian_cach, chan_doan=ra / "chan-doan",
                                                        profile_ben=profile_ben, cho_giai_giay=cho_giai_captcha),
                  so_truy_van=so_truy_van, so_hop=hop, model=model,
                  truy_van_tay=[t.strip() for t in truy_van.split("|") if t.strip()] or None)
    except ChuKyKhongOnDinh as exc:
        typer.echo(f"Chữ ký dạng không ổn định — {exc}. Thử cắt video còn 1 cảnh chính rồi chạy lại.", err=True)
        raise typer.Exit(6)
    (ra / "ket-qua.json").write_text(json.dumps(asdict(kq), ensure_ascii=False, indent=1, default=str))
    tep = ghi_links(kq, ra, hang_giu)
    trang = render(kq, ra, video.name, hang_giu)
    typer.echo(f"Trang: {trang}")
    if kq.loi_trang:
        typer.echo(f"Mở/đọc trang TikTok lỗi — đã dừng ({kq.dung_vi}); kết quả các hop trước vẫn trong ket-qua.json.", err=True)
        raise typer.Exit(5)
    if kq.bi_captcha:
        typer.echo(f"TikTok hỏi captcha — đã dừng ngay ({kq.dung_vi}). Để IP nguội vài giờ rồi chạy lại; "
                   f"ảnh trong {ra / 'chan-doan'}.", err=True)
        raise typer.Exit(4)
    if kq.rong:
        typer.echo(f"KHÔNG CÓ ỨNG VIÊN NÀO sau {kq.so_lan_mo_trang} lần mở trang — feed TikTok rỗng/bị chặn; "
                   f"xem ảnh trong {ra / 'chan-doan'}.", err=True)
        raise typer.Exit(3)
    if not kq.tin_duoc:
        typer.echo("ĐỐI CHỨNG DƯƠNG TRƯỢT — không xuất links.txt (máy chấm không tin được lần này).", err=True)
        raise typer.Exit(7)
    typer.echo(f"Giữ {len(kq.giu(hang_giu))} link: {', '.join(str(p) for p in tep)}")


if __name__ == "__main__":
    app()
