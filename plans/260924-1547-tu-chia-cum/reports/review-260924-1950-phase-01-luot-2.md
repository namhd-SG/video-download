# Review phase 01, round 2: cef7221 (feat/tu-chia-cum-p1-nhap-nhat-ky), 24/09 19:50

Advisory only. I edited no code and did not commit, stash or push.
- Mutations ran in a scratch local clone checked out at cef7221 (`scratchpad/r2`), not in the worktree. After the runs, `git status --porcelain` in the worktree was empty.
- The suite at HEAD, re-run in the clone: **573 passed, 0 skipped**.
- Each mutation was applied, the targeted tests were run, then the file was restored with `git checkout -- .`.
- Scope is the five items (H1, H2, H3, M6, M7), the naming rule, and admin 404.

## Verdict table

| Item | Fixed in code | Proving test | Mutation → result | New defect |
|---|---|---|---|---|
| H1 undo stack | models_chia.py:685-689 (`da_lui = 0`), :730 (set `da_lui=1`); models.py `da_lui` column | test_hoan_tac_gop_hai_lan_… · test_hoan_tac_doi_ten_hai_lan_… | drop `da_lui = 0` → **RED** (2 failed) | **N1**: an IntegrityError is still reachable (see below) |
| H2 state guard | models_chia.py:399-408, called at :426 (duyet_kieu), :469 (duyet_het), :805 (ap_thao_tac, which includes hoan_tac) | test_ap_thao_tac_va_duyet_tu_choi_khi_luot_da_duyet | remove the guard in ap_thao_tac → **RED** (1); remove it in duyet_het → **RED** (1) | N1 (undo across a partial approve) |
| H2 generation | `the_he` bump :163-165, filter :688; logged on every row (:268, :438, :500, :812) | test_hoan_tac_khong_lui_xuyen_the_he_sau_ghi_de_xuat_moi | drop the `the_he` filter → **RED**; drop the bump → **RED** | — |
| H2 `huy` | :108 | test_ghi_de_xuat_khong_hoi_sinh_luot_huy | `in ("da_duyet",)` → **RED** | — |
| H3 JS handoff | app.js `moTabTrong` (sync `window.open("about:blank")`), `dieuHuongTab`, `moLoCum` (open before the await; on catch `tab.close()` plus a toast; `"loi"`), click-handler `.catch` on both callers | test_loi_payload_dong_tab_trong_va_bao_ly_do_khong_nuot_im + existing browser tests | remove `tab.close()` → **RED**; remove `if(!tab) return "chan"` → **RED** (10); **insert `await` before `window.open` → GREEN**; **remove caller `.catch` → GREEN** | N3 (ordering not pinned), N7 |
| M6 twin-DB | models_cum.py:158 `cum_trung` public, :172 alias `_cum_trung = cum_trung`; models_chia.py:365 calls the public name | test_duyet_kieu_tuong_duong_tao_cum_va_gan_video_tren_hai_db_song_sinh | swap usecase/insight in INSERT → **RED**; `k.casefold()` → GREEN; drop `da_loai_luc` filter → GREEN; drop `chi_cua` filter → GREEN (and **GREEN across both chia suites**) | N4 |
| M7 golden via old JS | tests/js/payload-ban-giao-cu.js runs `git show 97c6f3b:web/static/app.js` through node; test_web_chia.py:350 compares strings with `separators=(",",":")` and no `sort_keys` | test_payload_server_khop_byte_voi_ban_js_cu_tren_cung_cum | reorder `nhan` keys → **RED**; reorder top-level keys → **RED**; reorder item keys → **RED**; filter Drive before cutting lots → **RED**; drop the `title or video_id` fallback → **GREEN** (135 cum/chia tests) | N5 |
| Naming rule | `_kieu_trung_ten` :274-290, used at :321-322 | test_duyet_het_hai_kieu_cung_ten_o_hai_nhom_… + test_…khong_trung_ten_giu_nguyen… (control) | no folding → **RED**; fold every kiểu → **RED** (5) | N6 (edge cases) |
| Admin 404 | `ap_thao_tac`/`duyet_*` take `nguoi_tao` as `chu`, `_lan_cua_toi` filters on `chu`; only GET passes `la_admin` | test_lay_chia_cua_job_admin_xem_duoc_nhung_khong_sua_duyet_thay | route passes the owner when admin: /thao-tac → **RED**; /duyet → **RED**; `_lan_cua_toi` ignores `chu` → **RED** (3) | — |

## New defects

**N1 (High, blocks the H1 claim "no IntegrityError"). Undo still crosses an approval inside the same generation.** The guard only fires once the whole lot is `da_duyet`. `duyet_kieu` on one kiểu does not bump `the_he` and does not seal earlier ops, so those ops are still on the undo stack. I reproduced three cases with a probe on HEAD:
- **P1:** `chuyen` video 1 a→b, then `duyet_kieu(a)`, then `hoan_tac` → **`sqlite3.IntegrityError: FOREIGN KEY constraint failed`**. The undo restores `cum_nhap_id=a`, but row a was deleted when it was approved. The route only catches `ValueError`, so the user gets a **500**.
- **P2:** `gop` a→b, then `duyet_kieu(b)` (videos 1 and 2 go into real cluster 1), then `hoan_tac` succeeds. Kiểu `a` comes back as pending with video 1, which is already in cluster 1. `cum` itself is safe because D14b later reports it as `da_o_cum`, but the draft lies.
- **P3:** `doi_ten` a→a2, then `duyet_kieu(a)`, then `hoan_tac` → a silent no-op (`so_video: 0`). It still uses up a stack entry and writes a `hoan_tac` row (D15 noise).
- Fix: add `the_he = the_he + 1` in `duyet_kieu`/`duyet_het` whenever anything was approved. The existing filter at :688 then makes every earlier op non-undoable. Log the `duyet_het` row with the old `the_he`. Add P1 and P2 as tests: after a partial approve, undo → 400 "nothing to undo".

**N2 (Medium, contract drift from the M5 fix).** hop-dong-thao-tac.md:48 says: empty usecase/insight in both the body and `chia_lan` ⇒ 400. In practice, `duyet_het` with neither set returns **200** `{"cum":[], "loi_ten":[{…"usecase phải 1..80 ký tự"}] }` (probe P7), because the per-kiểu `try` now catches the lot-level `kiem_nhan` error. `duyet_kieu` still returns 400, so the two approve modes disagree. No test pins the `duyet_het` case. Fix: validate `u`/`g` once before the loop (raise → 400), or change the contract.

**N3 (Medium, H3 not pinned).** The property that matters for Safari is "`window.open` runs synchronously inside the click, before any await". Adding `await new Promise(r=>setTimeout(r,0))` before `moTabTrong()` leaves **all 18 tests GREEN**.
- The harness's `apiGet` does not log to `nhatKy`, so the order open→fetch is never asserted.
- Removing the caller `.catch` is also GREEN.
- Playwright Chromium allows popups regardless of timing, so no automated test can see this.
- Fix: push `"GET …/payload"` into `nhatKy` and assert `["open","GET…","POST …/da-mo"]`. Also assert that `"open"` is already in `nhatKy` synchronously after calling `moLoCum(...)` without awaiting it.
- Safari manual check: **CHƯA ĐO (not measured)**.

**N4 (Medium, M6 twin test is only half an anti-drift test).**
- It compares 4 hard-coded columns, on one clean input ("couple", "Dance", "Badaboum"), on the happy path only.
- A new column added to `cum` would not be seen.
- It does not pin normalization drift (casefold mutation GREEN) or filter drift (`da_loai_luc` GREEN in the twin test; `chi_cua` GREEN across **all** chia tests).
- The `chi_cua` filter is the one ownership/scope filter on the approve path, and `ghi_de_xuat` does not validate video ids against the job. So a trust-boundary filter currently has no test.
- Fix: take column lists from `PRAGMA table_info` minus id/tao_luc/cum_id. Parametrize with messy input (`"  COUPLE "`), a removed (`da_loai`) video, and a video from another owner's job with `chi_cua` set.

**N5 (Low, M7).**
- The `title||video_id` fallback is unpinned (every fixture title is set). Fix: make one fixture title `None`/`""`.
- The test **fails** (it does not skip) without git history. I saw `CalledProcessError git show 97c6f3b` in a `git archive` copy. CI (build.yml) does not run pytest today, so this is latent. Shallow clones would break it.
- The 3 glue lines (`filter(drive).map(itemBanGiao)`, `lo.length || 1`) are hand-copied, not taken verbatim from the old `moLoCum`. The old code passed `lo.length` with no `|| 1`. That only matters when there are 0 lots, and 0 lots is unreachable because the route returns 400.

**N6 (Low, naming-rule edges).** Probes on HEAD:
- **P4:** the same colliding pair approved one at a time with `duyet_kieu` gets the names `"Vest couple"` and then plain `"couple"`. The second no longer collides once the first leaves `cum_nhap`. So names depend on approval order, and differ from what `duyet_het` produces.
- **P5:** the same nhóm and a case-variant kiểu (`couple`/`Couple` in "Vest") fold to the same name. `duyet_het` then **prompts a merge into cluster 1 created in the same call**, which the contract says must "never" happen.
- **P6:** a folded name equals a sibling's literal kiểu (`"Vest couple"`), with the same result as P5.
- Fix: compute the collision set over folded names, iterate until there is no collision, or dedupe at `ghi_de_xuat`. For P4, snapshot the collision set at `ghi_de_xuat` (store it) instead of recomputing on the live rows.

**N7 (Low, JS).**
- (a) The `PhienHetHan` path in `moLoCum` closes the tab but returns `"mo"`. `moHetLoCum` then goes on to lot 2 and opens a blank tab again, and closes it again, for every lot. If that second open gets blocked, the toast wrongly says "Đã mở 1/N bộ". Return a distinct value such as `"het_phien"`.
- (b) If the user closes the blank tab while the fetch is in flight, `dieuHuongTab` still runs and `da-mo` is recorded for a tab that never loaded. Check `tab.closed` before navigating.

**N8 (Low).** The internal callers in models_cum (:175, :193) still use `_cum_trung`, and test_web_cum.py:347 monkeypatches `_cum_trung`. Today the alias points to the same function, so nothing is wrong. But a future patch or test on one name won't apply to the other. Switch the internal callers to `cum_trung`.

## Confirmed OK
- H1: two undos walk back through two distinct ops. Once nothing is left, the route returns 400 (test_thao_tac_route_400_khi_hoan_tac_khong_con_gi). A refused undo writes no log row, so D15 is not inflated by repeated clicks.
- H2: every edit and approve, `hoan_tac` included, is gated on `de_xuat`. Undo cannot cross a `ghi_de_xuat`. `huy` is terminal.
- H3: the popup-blocked check is still meaningful. `window.open("about:blank")` returning null triggers the `"chan"` return before any await, and the mutation that removes it goes RED. The error path closes the tab and shows the real reason.
- M7 is genuinely old JS through node, byte-for-byte with no `sort_keys`, and key order is pinned at all three levels.
- Naming rule: only colliding kiểu get folded (both directions mutation-RED). The normal two-nhóm case does not trigger a same-call merge prompt.
- Non-owner admin gets 404 on /thao-tac and /duyet, and can only view through GET.

## Recommended actions
1. N1: bump `the_he` on approve, plus tests for P1 and P2. This is required, because the commit message claims it.
2. N2: decide between 400 and `loi_ten` for an empty lot-level insight, then align the code or hop-dong.
3. N3 and N4: tighten the tests (assert the order in the harness; column-agnostic twin test with messy input, removed videos and `chi_cua`).
4. N5 to N8: can follow in the phase-3 PR.

## Unresolved questions
- Q1: For P4, should the folded name be decided once at proposal time (stable), or recomputed at approve time? This is a design call for ĐP.
- Q2: Safari is still not measured for H3. Who runs the manual check before phase 3 ships the UI?

Status: DONE_WITH_CONCERNS
Summary: H1, H2, M7, the naming rule and admin 404 are fixed, and each has a test that goes RED under mutation. But undo still crosses a partial approve inside one generation, which gives a FK IntegrityError → 500 (N1). The H3 ordering and the M6 filter equivalence are not pinned by tests.
NHẸ ĐI:
- No UI calls `/thao-tac` or `/duyet` in phase 1; phase 3 will. So N1 is only reachable through the API.
- D14b still keeps real `cum`/`video_cum` safe in P2 (no cluster corruption).
- The P1 500 rolls back cleanly; there is no partial write.
- The `chi_cua` filter exists in code; only its test is missing.
- Nothing here is on prod.
OK to open PR: no. Fix N1 first: a one-line `the_he` bump in `duyet_kieu`/`duyet_het` plus 2 tests. N2 needs a decision; the rest can ride along.
