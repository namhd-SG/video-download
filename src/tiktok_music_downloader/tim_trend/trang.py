"""Trang HTML local (mở bằng `open`) cho một lần chạy: video đầu vào, truy vấn, lưới ảnh bìa theo hạng, ô copy link.

Không thư viện ngoài, không gọi mạng; ảnh đọc theo đường dẫn tương đối trong thư mục ra. Mọi chữ từ TikTok đi qua `escape`.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from .cham import NGUONG_MAC_DINH
from .luong import TIEU_DE_TRANG, KetQua

TEN_HANG = {"3": "Đúng dạng", "2A": "Đúng dạng · tutorial", "2B": "Gần (lệch 1)", "1": "Khác dạng", "0": "Khác chủ thể",
            None: "Chưa chấm được"}
_CSS = """:root{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e4e2dc;--ok:#2e7d32;--warn:#9a6b00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--ink:#ececee;--mute:#9a9aa1;--line:#2e2e33;--ok:#7bc47f;--warn:#e2b54a;--bad:#f28b82}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:26px 0 10px}
.mute{color:var(--mute)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.khung{display:flex;gap:10px;flex-wrap:wrap}.khung img{width:110px;border-radius:6px;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.uv{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:12px}
.uv img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block;background:var(--line)}.uv div{padding:6px 8px}
.warn{color:var(--warn);font-weight:600}.bad{color:var(--bad);font-weight:600}.ok{color:var(--ok);font-weight:600}
textarea{width:100%;min-height:140px;font:12px ui-monospace,monospace;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px}
button{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:8px;padding:6px 14px;cursor:pointer;font:inherit}"""


def _o_ung_vien(u: dict) -> str:
    t = u.get("truong") or {}
    co = "".join(f'<br><span class="warn">⚑ {escape(c)}</span>' for c in u.get("co", []))
    return (f'<a class="uv" href="{escape(u["url"])}" target="_blank" rel="noopener">'
            f'<img src="bia/{escape(u["video_id"])}.jpg" alt="" loading="lazy"><div>'
            f'<b>{escape(TEN_HANG.get(u["hang"], "?"))}</b> · @{escape(u["tac_gia"])}<br>'
            f'<span class="mute">{escape(str(t.get("so_ban_sao", "?")))} bản sao · {escape(str(t.get("loai_nen", "?")))}'
            f' · {escape(str(t.get("hanh_dong", "?")))}</span><br>{escape(u["caption"][:90])}{co}</div></a>')


def render(kq: KetQua, ra: Path, ten_video: str, nguong: frozenset[str] = NGUONG_MAC_DINH) -> Path:
    ck = kq.chu_ky
    khung = "".join(f'<img src="khung/{escape(p.name)}" alt="">' for p in sorted((ra / "khung").glob("*.jpg")))
    tv = "".join(f'<tr><td>{t["hop"]}</td><td>{escape(t["text"])}</td><td>{escape(t["nhom"])} · {escape(t["lang"])}'
                 f' · {escape(t["loai"])}</td><td>{t["so_link"]}</td><td class="mute">{escape(t["ghi_chu"])}</td></tr>'
                 for t in kq.truy_van)
    giu = kq.giu(nguong) if kq.tin_duoc else []
    links = "\n".join(u["url"] for u in giu)
    nhom = ""
    for h in ("3", "2A", "2B", "1", "0", None):
        ds = [u for u in kq.ung_vien if u["hang"] == h]
        if ds:
            nhom += f'<h2>{escape(TEN_HANG[h])} — {len(ds)}</h2><div class="grid">{"".join(map(_o_ung_vien, ds))}</div>'
    if kq.bi_captcha:
        tin = (f'<p class="bad">TIKTOK HỎI CAPTCHA — đã dừng ngay: {escape(kq.dung_vi)}. Không xuất link. '
               'Để IP nguội vài giờ rồi chạy lại; ảnh chụp trong chan-doan/.</p>')
    elif kq.rong:
        tin = (f'<p class="bad">KHÔNG CÓ ỨNG VIÊN NÀO sau {kq.so_lan_mo_trang} lần mở trang — feed TikTok rỗng hoặc bị chặn. '
               'Xem ảnh chụp trong thư mục chan-doan/.</p>')
    else:
        tin = ('<p class="ok">Đối chứng dương đạt ở mọi lô (khung video đầu vào ra hạng 3).</p>' if kq.tin_duoc else
           '<p class="bad">ĐỐI CHỨNG DƯƠNG TRƯỢT — máy chấm không tin được ở lần chạy này ⇒ KHÔNG xuất link. '
           f'Lô: {escape(str(kq.lo_ctrl))}</p>')
    html = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{TIEU_DE_TRANG}<style>{_CSS}</style></head><body><main>
<h1>Tìm video cùng dạng: {escape(ten_video)}</h1>
<p class="mute">Kết quả theo IP Việt Nam (chưa có proxy theo thị trường). Chấm theo ảnh bìa; ngưỡng giữ {escape(", ".join(sorted(nguong)))}
— thước người 22/10: precision 0,95 / recall 0,90 trên 70 ảnh. Mở trang TikTok {kq.so_lan_mo_trang} lần.
{('<span class="warn">Dừng sớm: ' + escape(kq.dung_vi) + '</span>') if kq.dung_vi else ''}</p>
<div class="card"><div class="khung">{khung}</div><p>Chữ ký dạng: <b>{escape(str(ck.so_ban_sao if ck else "?"))}</b> bản sao ·
chủ thể {escape(ck.chu_the if ck else "?")} · nền {escape(ck.nen if ck else "?")} · {escape(ck.hanh_dong if ck else "?")}</p>{tin}</div>
<h2>Link để dán vào Video Desk — {len(giu)}</h2>
<textarea id="links" readonly>{escape(links)}</textarea>
<p><button onclick="navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('links').value);this.textContent='Đã copy'">Copy link</button>
<span class="mute">Video Desk nhận tối đa 50 link mỗi lượt; file links-NN.txt đã chia sẵn khi vượt.</span></p>
<h2>Truy vấn đã chạy</h2><div class="card"><table><tr><th>Hop</th><th>Truy vấn</th><th>Nhóm</th><th>Link</th><th>Ghi chú</th></tr>{tv}</table></div>
{nhom}
</main></body></html>"""
    p = ra / "index.html"
    p.write_text(html)
    return p
