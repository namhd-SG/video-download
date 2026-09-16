"""Khoá các bất biến của bộ chọn format yt-dlp."""
from pathlib import Path

from tiktok_music_downloader.downloader import _ydl_opts


def _branches() -> list[str]:
    """Các nhánh yt-dlp sẽ thử lần lượt, tách bởi '/'.

    Nhánh ghép `a+b` vẫn là một nhánh; phần video của nó là vế trước dấu '+'.
    """
    return _ydl_opts(Path("/tmp"), None, None)["format"].split("/")


def test_every_format_branch_requires_a_video_stream():
    """Không nhánh nào được nhận một mục CHỈ có tiếng.

    Một bài photo/slideshow của TikTok chỉ có đúng một format — `vcodec=none,
    acodec=mp3`. Nhánh đuôi không ràng buộc (`best` trần) nhận nó, và yt-dlp
    báo THÀNH CÔNG cho một file .mp3 không phải video. Đo 10/09 trên
    #trendanos80: 151 trong 259 "downloads" là .mp3/.m4a theo đúng đường đó.

    Bỏ `[vcodec!=none]` khỏi bất kỳ nhánh nào ⇒ test này phải ĐỎ.
    """
    for branch in _branches():
        video_part = branch.split("+")[0]
        assert "vcodec" in video_part, (
            f"nhánh {branch!r} không ràng buộc luồng video ⇒ nhận được "
            f"mục chỉ-có-tiếng và báo thành công"
        )


def test_output_template_names_files_by_video_id():
    """Tên file = <id>.<ext>.

    Việc lọc trùng giữa các thư mục dựa vào tên file chính là video-id; đổi
    template sang %(title)s là phá âm thầm mọi phép lọc trùng đã tải.
    """
    assert _ydl_opts(Path("/tmp"), None, None)["outtmpl"].endswith("%(id)s.%(ext)s")


# ---------------------------------------------------------------------------
# Jar Netscape: hai ca làm hỏng ÂM THẦM, cả hai đều không ném lỗi.
# ---------------------------------------------------------------------------

def test_a_cookie_carrying_a_tab_never_reaches_the_jar(tmp_path):
    """Netscape phân cột bằng TAB. Cookie mang TAB trong giá trị sinh ra dòng
    sai số cột, và yt-dlp KHÔNG ném lỗi — nó in NGUYÊN dòng đó (kèm sessionid
    đầy đủ) ra stderr rồi chạy tiếp. stderr của dịch vụ đổ vào videodl.log
    trên máy dùng chung."""
    import json
    from tiktok_music_downloader import downloader

    j = tmp_path / "c.json"
    j.write_text(json.dumps([
        {"name": "sessionid", "value": "BI_MAT_CO_TAB\tXYZ", "domain": ".tiktok.com",
         "path": "/", "expires": 0},
        {"name": "sid_tt", "value": "BINH_THUONG", "domain": ".tiktok.com",
         "path": "/", "expires": 0},
    ]), encoding="utf-8")

    jar = downloader._write_netscape_cookies(j)
    noi_dung = jar.read_text(encoding="utf-8")
    jar.unlink(missing_ok=True)

    assert "BI_MAT_CO_TAB" not in noi_dung, "cookie mang TAB phải bị bỏ, không được ghi"
    assert "BINH_THUONG" in noi_dung, "cookie lành phải vẫn được ghi"
    assert all(len(d.split("\t")) == 7 for d in noi_dung.splitlines()
               if d and not d.startswith("#")), "mọi dòng phải đúng 7 cột"


def test_an_unparsable_expiry_does_not_blow_up_the_jar_writer(tmp_path):
    """`expires` đi qua `_normalize_cookie` nguyên xi (chỉ `expirationDate` mới
    được ép kiểu), nên bản xuất ghi ISO làm `int()` ném. Lời gọi này nằm trong
    một `except` nuốt lỗi rồi chạy tiếp KHÔNG cookie — job vẫn "xong" với ít
    video hơn hẳn và không ai biết vì sao."""
    import json
    from tiktok_music_downloader import downloader

    j = tmp_path / "c.json"
    j.write_text(json.dumps([
        {"name": "sessionid", "value": "tok", "domain": ".tiktok.com",
         "path": "/", "expires": "2026-12-01T00:00:00Z"},
    ]), encoding="utf-8")

    jar = downloader._write_netscape_cookies(j)   # không được ném
    noi_dung = jar.read_text(encoding="utf-8")
    jar.unlink(missing_ok=True)

    assert "tok" in noi_dung
