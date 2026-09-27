"""Cache kết quả tầng hình trong `video_dac_diem` — hai LOẠI hàng chung một bảng:

- NHÃN vision (`the_chu`, trang phục, bối cảnh…): `phien_ban_prompt` bắt đầu
  bằng `"nhan:"`.
- CỜ caption lệch chủ đề (`caption_lech_chu_de`): `phien_ban_prompt` bắt đầu
  bằng `"caption:"`.

Vì sao hai loại hàng thay vì một hàng gộp: đổi prompt nhãn (hay chuẩn hoá, hay
trục chia) KHÔNG được làm mất cờ caption đã chấm, và ngược lại — mỗi loại mang
phiên bản prompt CỦA NÓ. Khoá chính `(video_id, phien_ban_prompt)` có sẵn giữ
việc đó mà không cần migration.

Vì sao mọi hàm đọc/ghi đều kiểm TIỀN TỐ: hai loại chung một bảng, nên một câu
đọc "mọi hàng của video này" hay một phiên bản nhãn lỡ đặt tên `caption:…`
sẽ lặng lẽ đọc cờ caption như thể nó là nhãn. Chặn ở đây, không trông vào kỷ
luật của người gọi.
"""
from __future__ import annotations

import json

from web.models import _now

TIEN_TO_NHAN = "nhan:"
TIEN_TO_CAPTION = "caption:"
_TIEN_TO = (TIEN_TO_NHAN, TIEN_TO_CAPTION)


def _kiem_phien_ban(phien_ban: str, tien_to: str) -> None:
    if not isinstance(phien_ban, str) or not phien_ban.startswith(tien_to) \
            or len(phien_ban) <= len(tien_to):
        raise ValueError(f"phiên bản prompt '{phien_ban}' phải có dạng '{tien_to}<phiên bản>'")


def _doc(conn, video_ids: list[str], phien_ban: str) -> dict[str, dict]:
    if not video_ids:
        return {}
    ra: dict[str, dict] = {}
    # Chia lô để không chạm trần số tham số của SQLite với lượt vài trăm video.
    for i in range(0, len(video_ids), 500):
        lo = video_ids[i:i + 500]
        marks = ",".join("?" * len(lo))
        for r in conn.execute(
                f"SELECT video_id, nhan_json FROM video_dac_diem "
                f"WHERE phien_ban_prompt = ? AND video_id IN ({marks})",
                (phien_ban, *lo)).fetchall():
            ra[r["video_id"]] = json.loads(r["nhan_json"])
    return ra


def doc_nhan(conn, video_ids: list[str], phien_ban_nhan: str) -> dict[str, dict]:
    """`{video_id: nhãn}` đã cache dưới ĐÚNG `phien_ban_nhan` (so bằng nhau,
    không so tiền tố/mới nhất). Không bao giờ trả một hàng cờ caption."""
    _kiem_phien_ban(phien_ban_nhan, TIEN_TO_NHAN)
    return _doc(conn, video_ids, phien_ban_nhan)


def doc_caption(conn, video_ids: list[str], phien_ban_caption: str) -> dict[str, dict]:
    """`{video_id: {"caption_lech_chu_de": …}}` đã cache dưới ĐÚNG
    `phien_ban_caption`."""
    _kiem_phien_ban(phien_ban_caption, TIEN_TO_CAPTION)
    return _doc(conn, video_ids, phien_ban_caption)


def ghi(conn, hang: list[dict]) -> int:
    """Ghi `[{"video_id", "phien_ban_prompt", "nhan"}]` — hàng trùng khoá thì
    lấy bản mới (cùng phiên bản prompt ⇒ cùng câu hỏi, bản mới nhất thắng).
    Chạy trên kết nối của người gọi (không tự commit). Trả số hàng đã ghi."""
    for h in hang:
        pb = h["phien_ban_prompt"]
        tien_to = next((t for t in _TIEN_TO if isinstance(pb, str) and pb.startswith(t)), None)
        if tien_to is None:
            raise ValueError(f"phiên bản prompt '{pb}' không có tiền tố {' / '.join(_TIEN_TO)}")
        _kiem_phien_ban(pb, tien_to)
    conn.executemany(
        "INSERT INTO video_dac_diem (video_id, phien_ban_prompt, nhan_json, tao_luc) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(video_id, phien_ban_prompt) DO UPDATE SET "
        "nhan_json = excluded.nhan_json, tao_luc = excluded.tao_luc",
        [(h["video_id"], h["phien_ban_prompt"], json.dumps(h["nhan"], ensure_ascii=False), _now())
         for h in hang])
    return len(hang)
