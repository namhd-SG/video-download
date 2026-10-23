"""Truy vấn hop 1 (theo chữ ký) và hop 2 (từ caption thật GĐ1). Không mạng."""
from __future__ import annotations

from tiktok_music_downloader.tim_trend.cham import ChuKy
from tiktok_music_downloader.tim_trend.mo_rong import sinh_mo_rong
from tiktok_music_downloader.tim_trend.truy_van import TruyVan, sinh_truy_van

CK_COLLAGE = ChuKy(7, ">=3", "nguoi", "tron", "tao_dang", False)
CK_CATWALK = ChuKy(1, "1", "nguoi", "san_dien", "catwalk", False)

# Caption thật GĐ1 (nguồn S5–S7, 22/10)
CAPTIONS_GD1 = [
    "lookbook ai kolase multi pose foto potret",
    "lookbook ai kolase multi pose foto potret template",
    "Tren AI ubah foto menjadi kolase 7 pose",
    "Tren AI ubah foto menjadi kolase 7 pose!",
    "TUTORIAL MEMBUAT TREND FOTO POSE DI CAPCUT #capcut",
    "Tutorial Pembuatan Gratis",
    "AI collage 7 poses",
    "Viral Tren AI 7 Pose Hijab",
]


def test_collage_sinh_tu_vung_cau_truc_truoc():
    tv = sinh_truy_van(CK_COLLAGE, [TruyVan("black two piece set", "san_pham", "en")], toi_da=10)
    assert tv[0].text == "7 pose ai trend" and tv[0].nhom == "cau_truc"
    assert tv[-1].nhom == "san_pham"


def test_catwalk_khong_sinh_tu_vung_ghep_anh():
    tu_agy = [TruyVan("ai fashion collage", "chu_de", "en"), TruyVan("AI Catwalk", "chu_de", "en"),
              TruyVan("multi pose lookbook", "chu_de", "en"), TruyVan("ai model walk", "chu_de", "en")]
    texts = [t.text for t in sinh_truy_van(CK_CATWALK, tu_agy, toi_da=20)]
    assert texts[0] == "ai catwalk"
    assert not any(k in t.lower() for t in texts for k in ("collage", "multi pose", "kolase"))
    assert sum(t.lower() == "ai catwalk" for t in texts) == 1   # trùng không phân biệt hoa thường bị bỏ
    assert "ai model walk" in texts


def test_cat_o_toi_da():
    assert len(sinh_truy_van(CK_COLLAGE, [], toi_da=2)) == 2


def test_mo_rong_ra_ten_trend_ban_dia():
    texts = [t.text for t in sinh_mo_rong(CAPTIONS_GD1, da_dung={"7 pose ai trend"}, toi_da=20)]
    assert "kolase multi pose" in texts or "kolase 7 pose" in texts
    assert any("kolase" in t for t in texts)
    assert not any(w in t.split() for t in texts for w in ("tutorial", "pembuatan", "gratis", "capcut", "membuat"))


def test_mo_rong_mot_caption_le_khong_sinh_gi():
    assert sinh_mo_rong(["lookbook ai kolase multi pose foto potret"], set(), toi_da=10) == []


def test_mo_rong_bo_truy_van_da_dung():
    texts = [t.text for t in sinh_mo_rong(CAPTIONS_GD1, da_dung={"Tren AI ubah foto menjadi kolase 7 pose"}, toi_da=50)]
    assert "tren ai ubah foto menjadi kolase 7 pose" not in texts


def test_mo_rong_bo_original_sound_va_manh_1_ky_tu():
    """Pha 4 23/10: caption 'Original sound / suara asli - X' và 'created by' sinh truy vấn rác 's suara asli', 'pose created by'."""
    caps = ["kolase 7 pose ©s suara asli - Rina", "kolase 7 pose 's suara asli - Dewi",
            "7 pose created by @aa", "7 pose created by @bb"]
    texts = [t.text for t in sinh_mo_rong(caps, set(), toi_da=20)]
    assert "kolase 7 pose" in texts
    assert not any(w in t.split() for t in texts for w in ("s", "suara", "asli", "created", "by"))
