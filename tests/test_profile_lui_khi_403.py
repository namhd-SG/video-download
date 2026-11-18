"""Cờ `VIDEODL_PROFILE_LUI_KHI_403` (ĐP-bc gật 18/11, mặc định TẮT): job trang profile gặp 403 lúc goto, CHƯA
giải captcha ở lượt này ⇒ dời profile cũ sang bên (không xoá), chạy lại MỘT lần trên profile MỚI, log
"[profile-giai] job=N 403 ⇒ profile moi". Đã tự giải trong lượt ⇒ giữ profile, chỉ log. Cờ tắt ⇒ như trước."""
from __future__ import annotations

import pytest

from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader.utils import VideoRef
from web import models, profile_theo_job
from web import queue as queue_mod

URL_PROFILE = "https://www.tiktok.com/@nguoi.dung"
LOI_403 = "Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://www.tiktok.com/@nguoi.dung\nCall log: ..."


class _LoiGotoGia(Exception):
    """Đứng thay `playwright._impl._errors.Error` — so theo chuỗi thông điệp."""


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for ten in (profile_theo_job.ENV_PROFILE_CAPTCHA, profile_theo_job.ENV_PROFILE_HEADFUL,
                profile_theo_job.ENV_PROFILE_LUI_KHI_403):
        monkeypatch.delenv(ten, raising=False)
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 1)
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda _s: None)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "data" / "jobs.db"
    models.init_db(p)
    return p


def _bat(monkeypatch, lui=True):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    if lui:
        monkeypatch.setenv(profile_theo_job.ENV_PROFILE_LUI_KHI_403, "1")


def _scraper(monkeypatch, cac_luot):
    """Mỗi lời gọi `scrape_music_page` lấy một phần tử: Exception ⇒ ném; số ⇒ trả từng đó ref;
    "giai_ok" ⇒ đánh dấu đã tự giải (như `_tu_giai_neu_bi_chan`) rồi trả 3 ref."""
    goi: list[dict] = []

    def fake(url, **kw):
        goi.append({"profile_dir": kw.get("profile_dir"),
                    "co_du_lieu_cu": _co_du_lieu(kw.get("profile_dir"))})
        hanh = cac_luot[len(goi) - 1]
        if hanh == "giai_ok":  # vòng này tự giải qua (như `_tu_giai_neu_bi_chan`) và ra link
            tk = kw["thong_ke_feed"]
            tk["da_giai"] = tk.get("da_giai", 0) + 1
            hanh = 3
        if isinstance(hanh, Exception):
            raise hanh
        from pathlib import Path
        (Path(kw["profile_dir"]) / "Default").mkdir(exist_ok=True)  # trình duyệt để lại dữ liệu
        return [VideoRef(f"7{i:018d}", f"https://www.tiktok.com/@a/video/7{i:018d}") for i in range(hanh)]

    monkeypatch.setattr(scraper_mod, "scrape_music_page", fake)
    return goi


def _co_du_lieu(pd):
    from pathlib import Path
    return pd is not None and (Path(pd) / "Default").exists()


def _dong(caplog):
    return [r.getMessage() for r in caplog.records if "[profile-giai]" in r.getMessage()]


def _fetch(db, jid):
    return queue_mod._fetch_refs(URL_PROFILE, max_videos=10, cookies_path=None, db_path=db, job_id=jid)


def _du_lieu_cu(db, jid):
    """Profile đã dùng (có `Default`) — như lượt 2+ ngoài đời."""
    d = profile_theo_job.chuan_bi_profile_job(db, jid)
    (d / "Default").mkdir()
    (d / "Default" / "Cookies").write_text("cu")
    return d


def test_403_lui_ve_profile_moi_mot_lan(monkeypatch, db, caplog):
    _bat(monkeypatch)
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    cu = _du_lieu_cu(db, jid)
    goi = _scraper(monkeypatch, [_LoiGotoGia(LOI_403), 3])
    caplog.set_level("INFO", logger=queue_mod.log.name)
    refs = _fetch(db, jid)
    assert len(refs) == 3
    assert len(goi) == 2
    assert goi[0]["co_du_lieu_cu"] is True
    assert goi[1]["profile_dir"] == str(cu) and goi[1]["co_du_lieu_cu"] is False, "lượt 2 phải là profile MỚI"
    assert f"[profile-giai] job={jid} 403 ⇒ profile moi" in _dong(caplog)
    assert "nguoi.dung" not in "".join(_dong(caplog))
    # Profile cũ KHÔNG xoá ngay: dời sang bên, còn nguyên dữ liệu.
    ben = sorted(cu.parent.glob(f"{jid}.cu403-*"))
    assert len(ben) == 1 and (ben[0] / "Default" / "Cookies").read_text() == "cu"


def test_403_lan_hai_thi_nem_khong_lui_tiep(monkeypatch, db):
    _bat(monkeypatch)
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    _du_lieu_cu(db, jid)
    goi = _scraper(monkeypatch, [_LoiGotoGia(LOI_403), _LoiGotoGia(LOI_403)])
    with pytest.raises(_LoiGotoGia):
        _fetch(db, jid)
    assert len(goi) == 2


def test_da_giai_trong_luot_thi_khong_lui(monkeypatch, db, caplog):
    _bat(monkeypatch)
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    cu = _du_lieu_cu(db, jid)
    # Tự giải chạy SAU goto ⇒ 403 lúc goto chỉ có thể rơi vào VÒNG SAU của cùng lượt (vòng đào sâu).
    monkeypatch.setattr(queue_mod, "SO_VONG_DAO_SAU", 2)
    goi = _scraper(monkeypatch, ["giai_ok", _LoiGotoGia(LOI_403), 3])
    caplog.set_level("INFO", logger=queue_mod.log.name)
    with pytest.raises(_LoiGotoGia):
        _fetch(db, jid)
    assert len(goi) == 2, "đã giải ⇒ không chạy lại"
    assert (cu / "Default" / "Cookies").read_text() == "cu" and goi[1]["profile_dir"] == str(cu), \
        "giữ nguyên profile vừa giải"
    assert not list(cu.parent.glob(f"{jid}.cu403-*"))
    assert f"[profile-giai] job={jid} 403 sau khi giai ⇒ giu profile" in _dong(caplog)
    assert f"[profile-giai] job={jid} 403 ⇒ profile moi" not in _dong(caplog)


@pytest.mark.parametrize("captcha,lui", [(True, False), (False, True), (False, False)])
def test_co_tat_thi_nem_nguyen_loi_khong_lui(monkeypatch, db, caplog, captcha, lui):
    if captcha:
        monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    if lui:
        monkeypatch.setenv(profile_theo_job.ENV_PROFILE_LUI_KHI_403, "1")
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    goc = _LoiGotoGia(LOI_403)
    goi = _scraper(monkeypatch, [goc, 3])
    caplog.set_level("INFO", logger=queue_mod.log.name)
    with pytest.raises(_LoiGotoGia) as ei:
        _fetch(db, jid)
    assert ei.value is goc and len(goi) == 1
    assert not any("profile moi" in d for d in _dong(caplog))
    assert not list((db.parent / "profiles").glob(f"{jid}.cu403-*")) if (db.parent / "profiles").exists() else True


def test_loi_khac_403_khong_lui(monkeypatch, db):
    _bat(monkeypatch)
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    goi = _scraper(monkeypatch, [_LoiGotoGia("Page.goto: Timeout 30000ms exceeded."), 3])
    with pytest.raises(_LoiGotoGia):
        _fetch(db, jid)
    assert len(goi) == 1


def test_la_loi_http_luc_goto():
    assert queue_mod._la_loi_http_luc_goto(Exception(LOI_403))
    assert not queue_mod._la_loi_http_luc_goto(Exception("net::ERR_HTTP_RESPONSE_CODE_FAILURE"))  # không phải goto
    assert not queue_mod._la_loi_http_luc_goto(Exception("Page.goto: net::ERR_CONNECTION_RESET"))


# ---- dọn theo lối hiện có ----

def test_xoa_profile_job_don_ca_profile_cu_da_doi(db):
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    _du_lieu_cu(db, jid)
    ben = profile_theo_job.doi_profile_cu_sang_ben(db, jid)
    profile_theo_job.chuan_bi_profile_job(db, jid)
    khac = profile_theo_job.chuan_bi_profile_job(db, jid + 1)  # job khác (tiền tố số trùng) không bị đụng
    assert profile_theo_job.xoa_profile_job(db, jid) is True
    assert not ben.exists() and not profile_theo_job.thu_muc_profile_job(db, jid).exists()
    assert khac.exists()


def test_bo_quet_don_profile_cu_cua_job_da_ket_thuc(db):
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    _du_lieu_cu(db, jid)
    ben = profile_theo_job.doi_profile_cu_sang_ben(db, jid)
    (ben / profile_theo_job.TEN_KHOA_WORKER).unlink()  # khoá của tiến trình này còn sống ⇒ bộ quét giữ
    models.finish_job(db, jid, "done")
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert not ben.exists() and dem["da_xoa"] >= 1


def test_bo_quet_giu_profile_cu_cua_job_dang_chay(db):
    jid = models.create_job(db, URL_PROFILE, 10, "a@x.vn")
    _du_lieu_cu(db, jid)
    ben = profile_theo_job.doi_profile_cu_sang_ben(db, jid)
    dem = profile_theo_job.quet_profile_mo_coi(db)
    assert ben.exists() and dem["giu"] >= 1
