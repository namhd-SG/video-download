"""Đợt 2A — áp bản đã thay logo vào bộ + hoàn tác (`thay_logo/ap_vao_bo.py`) trên Drive GIẢ, DB là FILE thật (không :memory:).

Bất biến vết (kiểm sau MỖI thao tác ghi Drive): KHÔNG lúc nào bộ có đồng thời bản trong bộ G hợp lệ + bản mới M của G. Lỗi tiêm ở MỖI
bước (trước và SAU khi Drive đã làm) rồi chạy lại `quet_do_dang` phải ra đúng trạng thái cuối, đúng một bản mới, không dời thừa."""
import json
import time

import pytest
from drive_gia_thay_logo import DriveGiaTL

from tiktok_music_downloader.thay_logo import ap_vao_bo, hang_doi, nhat_ky
from tiktok_music_downloader.thay_logo.drive_tl import DriveTLKhongQuyen, duong_dan_ten

A = "a@x"
CREATIVE, TU_TIM, F1 = "CREATIVE00" + "r" * 10, "TUTIMFOLD0" + "t" * 10, "FOLDERBO1" + "f" * 12
DAU_RA = "DAURAFOLD0" + "o" * 10
BAN = {1: "BANCOPY0001" + "a" * 10, 2: "BANCOPY0002" + "b" * 10}
RA = {1: "RAFILE0001" + "x" * 10, 2: "RAFILE0002" + "y" * 10}
TEN = {1: "v1.mp4", 2: "v2.mp4"}


def _chu(ids):
    return {i: (A, A) for i in ids}


class San:
    """Sân: Shared Drive D1 (Creative/Tự tìm/<bộ F1> có 2 bản trong bộ; thư mục đầu ra ở gốc) + `thay_logo_log.db` có một lượt
    `vao_bo` hai video đã xong + Đạt (dựng bằng hàm ghi THẬT `hang_doi.tao_job`)."""

    def __init__(self, tmp_path, n=2):
        self.db = tmp_path / "thay_logo_log.db"
        d = self.drive = DriveGiaTL()
        d.them_thu_muc(CREATIVE, "Creative")
        d.them_thu_muc(TU_TIM, "Tự tìm", CREATIVE)
        d.them_thu_muc(F1, "N.1AAAA - bộ thử", TU_TIM)
        d.them_thu_muc(DAU_RA, "Thay logo - đầu ra")
        self.vi_pham: list[str] = []
        d.sau_thao_tac.append(self._kiem_bat_bien)
        nguon = []
        for i in range(1, n + 1):
            d.them_file(BAN[i], TEN[i], F1, md5=f"MD5-{i}", size=100 * i, properties={"videodesk_src": f"SRC{i}" + "s" * 12})
            d.them_file(RA[i], f"thay-logo-{i}.mp4", DAU_RA, md5=f"MD5-RA{i}", size=90 * i)
            nguon.append({"kieu": "vao_bo", "video_id": f"V{i}", "file_id": BAN[i], "folder_id": F1, "ma_bo": "N.1AAAA",
                          "md5": f"MD5-{i}", "size": str(100 * i), "ten": TEN[i], "chu_video": A, "file_id_nguon": f"SRC{i}" + "s" * 12})
        conn = self.mo()
        self.job = hang_doi.tao_job(conn, A, nguon, ten_bo="N.1AAAA")
        self.vids = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (self.job,))]
        for i, vid in enumerate(self.vids, 1):
            log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
            nhat_ky.ghi_danh_gia(conn, log_id, A, "dat")
            hang_doi.dat(conn, vid, "xong", video_log_id=log_id, drive_file_id_ra=RA[i])
        conn.close()

    def mo(self):
        conn = nhat_ky.mo(self.db)
        hang_doi.khoi_tao(conn)
        return conn

    def _kiem_bat_bien(self, drive, ten, arg):
        for g in BAN.values():
            gm = drive.muc.get(g)
            if not gm or gm["trashed"] or F1 not in gm["parents"]:
                continue
            m = [x["id"] for x in drive.muc.values() if F1 in x["parents"] and not x["trashed"]
                 and (x.get("appProperties") or {}).get(ap_vao_bo.THE_GOC) == g]
            if m:
                self.vi_pham.append(f"sau {ten}({arg}): bộ có cả {g} và {m}")

    # --- thao tác ---
    def ap(self):
        conn = self.mo()
        try:
            return ap_vao_bo.dat_lich_ap(conn, self.job, A, _chu)
        finally:
            conn.close()

    def hoan_tac(self):
        conn = self.mo()
        try:
            return ap_vao_bo.dat_lich_hoan_tac(conn, self.job, A)
        finally:
            conn.close()

    def chay(self, **kw):
        conn = self.mo()
        try:
            ap_vao_bo.chay_luot(conn, self.drive, self.job, **kw)
            ap_vao_bo.nha_khoa(conn, self.job)
        finally:
            conn.close()

    def quet(self, **kw):
        conn = self.mo()
        try:
            return ap_vao_bo.quet_do_dang(conn, self.drive, **kw)
        finally:
            conn.close()

    def hang(self):
        conn = self.mo()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM tl_ap_bo ORDER BY id")]
        finally:
            conn.close()

    # --- đo Drive ---
    def song_trong_bo(self):
        return {k: v for k, v in self.drive.muc.items() if F1 in v["parents"] and not v["trashed"] and v["mimeType"] != "application/vnd.google-apps.folder"}

    def ban_moi_trong_bo(self):
        return {k: v for k, v in self.song_trong_bo().items() if ap_vao_bo.THE_AP in (v.get("appProperties") or {})}

    def thu_muc(self, ten):
        return [k for k, v in self.drive.muc.items() if v["name"] == ten and v["mimeType"] == "application/vnd.google-apps.folder"]


@pytest.fixture
def san(tmp_path):
    return San(tmp_path)


def _da_ap_dung(san, n=2):
    """Trạng thái cuối của áp: G ở bản gốc (ngoài Creative), đúng một M mỗi G trong bộ, tên = tên G, không mang dấu nguồn."""
    [goc] = san.thu_muc("Thay logo - bản gốc")
    [sub] = san.thu_muc(ap_vao_bo.ten_thu_muc_bo_goc("N.1AAAA", F1))
    assert san.drive.muc[goc]["parents"] == ["D1"] and san.drive.muc[sub]["parents"] == [goc]
    assert "Creative" not in duong_dan_ten(san.drive, sub)
    moi = san.ban_moi_trong_bo()
    assert len(moi) == n, moi
    for i in range(1, n + 1):
        assert san.drive.muc[BAN[i]]["parents"] == [sub] and not san.drive.muc[BAN[i]]["trashed"]
        [m] = [v for v in moi.values() if v["appProperties"][ap_vao_bo.THE_GOC] == BAN[i]]
        assert m["name"] == TEN[i] and "properties" not in m and m["md5Checksum"] == f"MD5-RA{i}"
    assert [h["buoc"] for h in san.hang()] == ["xong"] * n
    assert san.vi_pham == []


# ---------------------------------------------------------------- đường thẳng
def test_ap_doi_goc_truoc_roi_copy_ban_moi_vao_bo(san):
    kq = san.ap()
    assert (kq["ap_id"], kq["so_video"], kq["bo_qua"]) == (san.job, 2, [])
    h = san.hang()
    assert [(x["chieu"], x["buoc"], x["lan"]) for x in h] == [("ap", "moi", 1)] * 2  # chiều ý định ghi TRƯỚC mọi lời gọi Drive
    assert san.drive.goi == []
    san.chay()
    _da_ap_dung(san)
    assert san.drive.so_lan("doi_cha") == 2 and san.drive.so_lan("sao_chep") == 2
    the = {v["appProperties"][ap_vao_bo.THE_AP] for v in san.ban_moi_trong_bo().values()}
    assert the == {ap_vao_bo.the_lan(x["id"], 1) for x in h}
    # thứ tự: G rời bộ TRƯỚC khi M vào bộ (với từng video)
    goi = [(t, a) for t, a in san.drive.goi if t in ("doi_cha", "sao_chep")]
    for i in (1, 2):
        assert goi.index(("doi_cha", BAN[i])) < goi.index(("sao_chep", RA[i]))


def test_hoan_tac_doi_ten_doi_ban_moi_ra_roi_tra_goc_ve(san):
    san.ap()
    san.chay()
    moi = {k: dict(v) for k, v in san.ban_moi_trong_bo().items()}
    san.drive.goi.clear()
    assert san.hoan_tac()["so_video"] == 2
    san.chay()
    [dh] = san.thu_muc(ap_vao_bo.TEN_DA_HOAN_TAC)
    for i in (1, 2):
        assert san.drive.muc[BAN[i]]["parents"] == [F1]
    for mid, m in moi.items():
        assert san.drive.muc[mid]["parents"] == [dh] and san.drive.muc[mid]["name"] == "HOAN-TAC-" + m["name"]
        assert not san.drive.muc[mid]["trashed"]
    assert san.ban_moi_trong_bo() == {}
    assert [h["buoc"] for h in san.hang()] == ["da_hoan_tac"] * 2 and san.vi_pham == []
    assert san.drive.so_lan("doi_cha") == 4 and san.drive.so_lan("doi_ten") == 2 and san.drive.so_lan("vao_thung_rac") == 0


def test_ap_lai_sau_hoan_tac_dung_lai_hang_tang_lan(san):
    san.ap(); san.chay(); san.hoan_tac(); san.chay()
    ids = [h["id"] for h in san.hang()]
    assert san.ap()["so_video"] == 2  # KHÔNG 409, KHÔNG vỡ UNIQUE
    h = san.hang()
    assert [x["id"] for x in h] == ids and [(x["chieu"], x["buoc"], x["lan"], x["ban_moi_id"], x["loi"]) for x in h] == [("ap", "moi", 2, None, None)] * 2
    san.chay()
    _da_ap_dung(san)


def test_ap_lai_khong_nham_ban_moi_lan_truoc_bi_keo_lai_vao_bo(san):
    """Áp → hoàn tác → ai đó kéo bản HOAN-TAC của lần 1 về lại bộ → áp lần 2, chết ngay sau khi dời G ⇒ quét phải ra đúng một bản mới
    MỚI (thẻ lần 2), không nhận bản lần 1. ĐỘT BIẾN: dùng lại hàng mà không tăng `lan` (thẻ trùng lần trước) ⇒ ĐỎ."""
    san.ap(); san.chay(); san.hoan_tac(); san.chay()
    cu = next(iter(k for k, v in san.drive.muc.items() if v["name"].startswith("HOAN-TAC-") and v["appProperties"][ap_vao_bo.THE_GOC] == BAN[1]))
    san.drive.muc[cu]["parents"] = [F1]
    san.ap()
    san.drive.loi_sau[("doi_cha", BAN[1])] = RuntimeError("chết sau khi dời G")
    san.chay()
    san.quet()
    h1 = san.hang()[0]
    assert h1["buoc"] == "xong" and h1["ban_moi_id"] != cu
    moi = [v for v in san.song_trong_bo().values() if v["name"] == TEN[1]]
    assert len(moi) == 1 and moi[0]["appProperties"][ap_vao_bo.THE_AP] == ap_vao_bo.the_lan(h1["id"], 2)


def test_bam_ap_lan_hai_khi_da_ap_thi_409(san):
    san.ap(); san.chay()
    with pytest.raises(ap_vao_bo.LoiAp) as e:
        san.ap()
    assert e.value.ma == 409


def test_ap_khi_dang_khoa_409_hoan_tac_chua_ap_409(san):
    with pytest.raises(ap_vao_bo.LoiAp) as e:
        san.hoan_tac()
    assert e.value.ma == 409
    san.ap()  # khoá còn giữ (chưa chạy) ⇒ hoàn tác / áp lại đều 409
    with pytest.raises(ap_vao_bo.LoiAp) as e:
        san.hoan_tac()
    assert e.value.ma == 409


# ---------------------------------------------------------------- lỗi tiêm ở mỗi bước + quét chạy lại
BUOC_AP = ["lay_muc", "tim_con_theo_ten", "tao_thu_muc", "doi_cha", "tim_theo_the", "sao_chep", "liet_ke_con"]


@pytest.mark.parametrize("buoc", BUOC_AP)
def test_ap_loi_tam_o_moi_buoc_quet_lai_ra_dung(san, buoc):
    san.drive.loi[(buoc, "*")] = TimeoutError("treo")
    san.ap()
    san.chay()
    assert all(h["buoc"] != "xong" and "Tiếp tục" in (h["loi"] or "") for h in san.hang())
    assert san.vi_pham == []
    del san.drive.loi[(buoc, "*")]
    assert san.quet()["khoa_cu_xoa"] == 0
    _da_ap_dung(san)


@pytest.mark.parametrize("buoc,id_", [("doi_cha", BAN[1]), ("sao_chep", RA[1]), ("tao_thu_muc", "*")])
def test_ap_chet_sau_khi_drive_da_lam_quet_lai_khong_lam_thua(san, buoc, id_):
    """Drive đã làm xong rồi tiến trình chết trước khi ghi DB. ĐỘT BIẾN: bỏ probe parents trước dời ⇒ doi_cha giả ném ⇒ ĐỎ; bỏ thẻ
    (copy không tìm theo thẻ trước) ⇒ hai bản mới ⇒ ĐỎ."""
    san.drive.loi_sau[(buoc, id_)] = RuntimeError("chết")
    san.ap()
    san.chay()
    san.quet()
    _da_ap_dung(san)
    assert san.drive.so_lan("doi_cha") == 2 and san.drive.so_lan("sao_chep") == 2
    assert len(san.thu_muc("Thay logo - bản gốc")) == 1


@pytest.mark.parametrize("buoc,ai", [("doi_ten", "M"), ("doi_cha", "M"), ("doi_cha", "G"), ("tim_theo_the", None)])
def test_hoan_tac_chet_o_moi_buoc_quet_lai_ra_dung(san, buoc, ai):
    """ĐỘT BIẾN: bỏ probe trước dời ở hoàn tác (M hoặc G) ⇒ doi_cha giả ném khi chạy lại ⇒ ĐỎ; bỏ probe tên ⇒ HOAN-TAC-HOAN-TAC- ⇒ ĐỎ."""
    san.ap(); san.chay()
    m1 = san.hang()[0]["ban_moi_id"]
    san.hoan_tac()
    if ai is None:
        san.drive.loi[(buoc, F1)] = TimeoutError("treo")
    else:
        san.drive.loi_sau[(buoc, m1 if ai == "M" else BAN[1])] = RuntimeError("chết")
    san.chay()
    san.drive.loi.clear()
    san.quet()
    assert [h["buoc"] for h in san.hang()] == ["da_hoan_tac"] * 2
    assert san.drive.muc[m1]["name"] == "HOAN-TAC-" + TEN[1] and san.drive.muc[BAN[1]]["parents"] == [F1]
    assert san.ban_moi_trong_bo() == {} and san.vi_pham == []
    assert san.drive.so_lan("doi_cha") == 2 + 4 and san.drive.so_lan("doi_ten") == 2


# ---------------------------------------------------------------- kiểm tầng Drive trước áp (N2, N6)
@pytest.mark.parametrize("sua", ["md5", "size", "thu_muc_them", "thung_rac"])
def test_ban_trong_bo_doi_tu_luc_chup_thi_bo_qua_khong_dong_gi(san, sua):
    """ĐỘT BIẾN: bỏ kiểm md5/size/parents ⇒ ĐỎ."""
    m = san.drive.muc[BAN[1]]
    if sua == "md5":
        m["md5Checksum"] = "KHAC"
    elif sua == "size":
        m["size"] = "1"
    elif sua == "thu_muc_them":
        m["parents"] = [F1, TU_TIM]
    else:
        m["trashed"] = True
    san.ap()
    san.chay()
    h = san.hang()
    if sua == "thung_rac":  # G trong thùng rác = "mất" ⇒ không tự đoán
        assert h[0]["buoc"] == "can_nguoi"
    else:
        assert h[0]["buoc"] == "bo_qua" and "đã đổi" in h[0]["loi"]
    assert ("doi_cha", BAN[1]) not in san.drive.goi and h[1]["buoc"] == "xong"  # video khác vẫn chạy


def test_bo_co_file_khac_cung_ten_thi_bo_qua(san):
    """ĐỘT BIẾN: bỏ kiểm tên trùng ⇒ ĐỎ."""
    san.drive.them_file("KHACTEN0001" + "z" * 10, TEN[1], F1)
    san.ap()
    san.chay()
    h = san.hang()[0]
    assert h["buoc"] == "bo_qua" and "cùng tên" in h["loi"] and ("doi_cha", BAN[1]) not in san.drive.goi


def test_ban_copy_mang_dau_nguon_thi_lui_tra_goc_ve(san):
    """Copy mang `properties.videodesk_src` theo (Drive thật CHƯA đo) ⇒ trash bản mới, trả G về, video `loi`. ĐỘT BIẾN: bỏ kiểm ⇒ ĐỎ."""
    san.drive.copy_mang_properties = True
    san.drive.muc[RA[1]]["properties"] = {"videodesk_src": "SRCX" + "s" * 12}
    san.ap()
    san.chay()
    h = san.hang()
    assert (h[0]["chieu"], h[0]["buoc"]) == ("lui", "loi") and "dấu nguồn" in h[0]["loi"]
    assert san.drive.muc[BAN[1]]["parents"] == [F1] and san.drive.muc[h[0]["ban_moi_id"]]["trashed"]
    assert h[1]["buoc"] == "xong" and san.vi_pham == []


def test_ten_trung_xuat_hien_trong_luc_copy_thi_lui(san):
    """TOCTOU: file cùng tên vào bộ giữa bước kiểm và bước copy ⇒ đếm lại sau copy bắt được. ĐỘT BIẾN: bỏ đếm tên sau copy ⇒ ĐỎ."""
    def chen(drive, ten, arg):
        if ten == "sao_chep" and arg == RA[1] and "CHEN0001" + "z" * 12 not in drive.muc:
            drive.them_file("CHEN0001" + "z" * 12, TEN[1], F1)
    san.drive.sau_thao_tac.append(chen)
    san.ap()
    san.chay()
    h = san.hang()[0]
    assert (h["chieu"], h["buoc"]) == ("lui", "loi") and "duy nhất" in h["loi"]
    assert san.drive.muc[BAN[1]]["parents"] == [F1] and san.drive.muc[h["ban_moi_id"]]["trashed"] and san.vi_pham == []


def test_lui_chet_giua_chung_van_di_tiep(san):
    san.drive.copy_mang_properties = True
    san.drive.muc[RA[1]]["properties"] = {"videodesk_src": "SRCX" + "s" * 12}
    san.drive.loi_sau[("vao_thung_rac", "*")] = RuntimeError("chết sau trash")
    san.ap()
    san.chay()
    assert san.hang()[0]["chieu"] == "lui" and san.hang()[0]["buoc"] != "loi"
    san.quet()
    h = san.hang()[0]
    assert h["buoc"] == "loi" and san.drive.muc[BAN[1]]["parents"] == [F1] and san.vi_pham == []


def test_vi_pham_bat_bien_co_san_thi_go_ban_moi(san):
    san.ap()
    conn = san.mo()
    rid, lan = conn.execute("SELECT id, lan FROM tl_ap_bo ORDER BY id").fetchone()
    conn.close()
    san.drive.them_file("LACHNHAP01" + "z" * 10, "x.mp4", F1, app_properties={ap_vao_bo.THE_AP: ap_vao_bo.the_lan(rid, lan)})
    san.chay()
    h = san.hang()[0]
    assert (h["chieu"], h["buoc"]) == ("lui", "loi") and san.drive.muc["LACHNHAP01" + "z" * 10]["trashed"]
    assert san.drive.muc[BAN[1]]["parents"] == [F1]


@pytest.mark.parametrize("sua", ["404", "cha_la"])
def test_ban_trong_bo_mat_hoac_sai_cho_thi_can_nguoi_khong_dong_gi(san, sua):
    san.ap(); san.chay()
    san.hoan_tac()
    if sua == "404":
        del san.drive.muc[BAN[1]]
    else:
        san.drive.muc[BAN[1]]["parents"] = [TU_TIM]
    so_ghi = sum(san.drive.so_lan(t) for t in ("doi_cha", "doi_ten", "vao_thung_rac", "sao_chep"))
    conn = san.mo()
    ap_vao_bo.chay_luot(conn, san.drive, san.job)
    conn.close()
    h = san.hang()[0]
    assert h["buoc"] == "can_nguoi"
    so_ghi_moi = sum(san.drive.so_lan(t) for t in ("doi_cha", "doi_ten", "vao_thung_rac", "sao_chep"))
    assert so_ghi_moi - so_ghi == 3  # chỉ hàng kia (đổi tên + dời M + trả G); hàng mất không dời gì


# ---------------------------------------------------------------- cổng Creative (N1) · quyền SA
def test_thu_muc_ban_goc_trong_creative_thi_dung_ca_luot(san):
    """ĐỘT BIẾN: bỏ `ly_do_creative` trên thư mục bản gốc ⇒ G bị dời vào cây Creative ⇒ ĐỎ."""
    san.ap()
    san.chay(cha_goc=lambda folder_id: TU_TIM)
    assert san.drive.so_lan("doi_cha") == 0 and san.drive.so_lan("sao_chep") == 0
    assert all(h["buoc"] == "moi" and "Creative" in h["loi"] for h in san.hang())


def test_sa_thieu_quyen_dung_ca_luot(san):
    san.drive.loi[("doi_cha", BAN[1])] = DriveTLKhongQuyen(BAN[1])
    san.ap()
    san.chay()
    assert all(h["loi"] == ap_vao_bo.THONG_DIEP_THIEU_QUYEN for h in san.hang()) and san.drive.so_lan("sao_chep") == 0


# ---------------------------------------------------------------- tầng DB
def test_chi_video_dat_cua_chinh_minh_va_so_xac_nhan_chu(tmp_path):
    s = San(tmp_path)
    conn = s.mo()
    ap_vao_bo.khoi_tao(conn)
    conn.execute("INSERT INTO tl_danh_gia (video_id, member, ket_qua, loai_loi, luc) SELECT video_log_id, ?, 'hong', 'khac', ? "
                 "FROM tl_job_video WHERE id=?", (A, time.time() + 5, s.vids[1]))
    conn.commit()
    kq = ap_vao_bo.phan_loai(conn, s.job, A, lambda ids: {"V1": (A, None)})
    assert [x["ly_do"] for x in kq["bo_qua"]] == [ap_vao_bo.LY_DO_SO_CHU, "chưa Đạt"] and kq["lam"] == []
    kq = ap_vao_bo.phan_loai(conn, s.job, A, lambda ids: {"V1": ("b@x", A), "V2": (A, A)})
    assert kq["bo_qua"][0]["ly_do"] == ap_vao_bo.LY_DO_SAI_CHU
    conn.close()
    with pytest.raises(ap_vao_bo.LoiAp) as e:
        conn = s.mo()
        ap_vao_bo.dat_lich_ap(conn, s.job, A, lambda ids: {"V1": (A, None), "V2": (A, A)})
    assert e.value.ma == 403 and s.hang() == []  # cả lượt bị từ chối: không hàng, không khoá
    conn.close()


def test_nguon_khong_phai_vao_bo_khong_bao_gio_ap(tmp_path):
    s = San(tmp_path)
    conn = s.mo()
    for vid in s.vids:
        conn.execute("UPDATE tl_job_video SET nguon=? WHERE id=?", (json.dumps({"kieu": "link", "file_id": BAN[1]}), vid))
    conn.commit()
    with pytest.raises(ap_vao_bo.LoiAp) as e:
        ap_vao_bo.dat_lich_ap(conn, s.job, A, _chu)
    conn.close()
    assert e.value.ma == 409 and s.hang() == []


# ---------------------------------------------------------------- khoá: try/finally + quét khởi động
def test_thread_nem_giua_chung_van_nha_khoa(san, monkeypatch):
    """ĐỘT BIẾN: bỏ `try/finally` nhả khoá ⇒ khoá kẹt ⇒ lượt sau 409 ⇒ ĐỎ."""
    san.ap()

    def no(*a, **k):
        raise RuntimeError("lỗi lạ")
    monkeypatch.setattr(ap_vao_bo, "chay_luot", no)
    ap_vao_bo.chay_nen(san.mo, san.drive, san.job).join(10)
    conn = san.mo()
    assert conn.execute("SELECT count(*) FROM tl_ap_bo_khoa").fetchone()[0] == 0
    conn.close()
    monkeypatch.undo()
    assert san.ap()["so_video"] == 2  # "Tiếp tục" chạy được ngay


def test_quet_khoi_dong_xoa_khoa_cu_giu_khoa_luot_dang_song(san):
    san.ap()  # khoá còn đó như tiến trình chết giữa lượt
    conn = san.mo()
    conn.execute("UPDATE tl_ap_bo_khoa SET luc = luc - 100")
    conn.execute("INSERT INTO tl_ap_bo_khoa VALUES ('BOKHAC0001zzzzzzzzzz', 999, ?)", (time.time() + 50,))
    conn.commit()
    conn.close()
    kq = san.quet()
    assert kq == {"hang_chay_tiep": 2, "khoa_cu_xoa": 0}
    _da_ap_dung(san)
    conn = san.mo()
    assert [r[0] for r in conn.execute("SELECT folder_id FROM tl_ap_bo_khoa")] == ["BOKHAC0001zzzzzzzzzz"]
    conn.close()


def test_quet_bo_qua_bo_dang_co_luot_song(san):
    san.ap()
    kq = san.quet(moc=time.time() - 100)  # khoá lấy SAU mốc ⇒ lượt đang sống, để yên
    assert kq["hang_chay_tiep"] == 0 and san.drive.goi == []


def test_trang_thai_theo_tien_do(san):
    conn = san.mo()
    assert ap_vao_bo.trang_thai(conn, san.job)["trang_thai"] == "chua_ap"
    conn.close()
    san.ap()
    conn = san.mo()
    assert ap_vao_bo.trang_thai(conn, san.job)["trang_thai"] == "chay"
    conn.close()
    san.drive.loi[("doi_cha", BAN[2])] = TimeoutError("treo")
    san.chay()
    conn = san.mo()
    t = ap_vao_bo.trang_thai(conn, san.job)
    assert t["trang_thai"] == "do_dang" and t["so_da_ap"] == 1 and [v["ten"] for v in t["tung_video"]] == [TEN[1], TEN[2]]
    conn.close()
    san.drive.loi.clear()
    san.ap(); san.chay()
    conn = san.mo()
    t = ap_vao_bo.trang_thai(conn, san.job)
    assert t["trang_thai"] == "xong" and t["so_da_ap"] == 2 and t["xong_luc"]
    assert ap_vao_bo.ban_da_ap(conn) == {BAN[1], BAN[2]}
    conn.close()


# ---------------------------------------------------------------- script khôi phục (DB mất)
def _script():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "thay_logo_ap_bo_khoi_phuc.py"
    spec = importlib.util.spec_from_file_location("thay_logo_ap_bo_khoi_phuc", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_khoi_phuc_dung_tu_drive_khi_db_mat(san, capsys):
    """DB rỗng (xoá file) ⇒ script vẫn ghép đúng cặp gốc↔mới THEO `tl_ap_goc`, dry-run không dời gì, `--thuc-hien` trả về như hoàn tác.
    ĐỘT BIẾN: bỏ `tl_ap_goc` khỏi bản mới ⇒ không ghép được ⇒ ĐỎ."""
    san.ap(); san.chay()
    moi = {v["appProperties"][ap_vao_bo.THE_GOC]: k for k, v in san.ban_moi_trong_bo().items()}
    san.db.unlink()
    sc = _script()
    so_ghi = sum(san.drive.so_lan(t) for t in ("doi_cha", "doi_ten", "tao_thu_muc"))
    assert sc.main(["--bo", F1], drive=san.drive) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert sum(san.drive.so_lan(t) for t in ("doi_cha", "doi_ten", "tao_thu_muc")) == so_ghi
    ke = sc.lap_ke_hoach(san.drive, [F1])
    assert {(k["ban_goc"], k["ban_moi"], k["g_o"]) for k in ke} == {(BAN[i], moi[BAN[i]], "ban_goc") for i in (1, 2)}
    assert sc.main(["--bo", F1, "--thuc-hien"], drive=san.drive) == 0
    [dh] = san.thu_muc(ap_vao_bo.TEN_DA_HOAN_TAC)
    for i in (1, 2):
        assert san.drive.muc[BAN[i]]["parents"] == [F1]
        m = san.drive.muc[moi[BAN[i]]]
        assert m["parents"] == [dh] and m["name"] == "HOAN-TAC-" + TEN[i]
    assert san.vi_pham == [] and sc.lap_ke_hoach(san.drive, [F1]) == []
    assert sc.thuc_hien(san.drive, ke) == 2  # chạy lại: probe ⇒ không dời thừa, không ném
