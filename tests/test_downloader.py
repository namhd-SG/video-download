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
