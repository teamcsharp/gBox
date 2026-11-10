# Handover: Resident Evil 6 on the i9 client lane (2026-11-10)

For the PM. Scope: everything done on RE6 (Switch) on the i9 NUC (`i9-NUC`), what is proven, how to reproduce it,
what is blocked, and what a reviewer should look at. The RE4 and decrypting work is summarised at the end; the full
round-by-round log is `ds-i9-client-lane-and-hot-swap-requests-20261109.md` and the one-page status is
`i9-client-lane-status-20261110.md`.

## 1. Status at a glance

| Capability | State | Evidence |
|---|---|---|
| RE6 Mercenaries round on the i9 | **works** | results screen `evidence/re6-20261110/round-results-urbach-chaos.jpg` |
| Character swap builds (single / multi arc) | **works** | `character-select-4char.jpg`, `swap-verify-loading.jpg` |
| Whole-model character swap (Leon as Chris) | **works, clean render** | round 35 log; `chris-live.jpg` in `.tmp` (not copied) |
| Hot reload (in-place file swap between rounds, one session) | **works** | `hotreload-round2-game-body.jpg`, `hotreload-round3-donor-body.jpg` |
| MercMode sidebar drives launch-ready swap builds | **works** | `screensaver.py` + `skin_swap.py` changes, commits below |
| Enemy model swap (cast models as enemies) | **mesh works, textures missing** | `enemy-cast-models-untextured.jpg`, `enemy-two-white-one-original.jpg` |
| Native effects (flash / grenade ring) on the i9 | **not possible** | requires Linux Switch NCE; reported by the intervention channel |
| Test status | 77 passed, 3 skipped | Switch readers/extractors/tool/mods suites |

## 2. What exists on the i9 now

- **Worker**: `i9-NUC` runs `gbox worker --server http://10.89.1.246:8765 --name i9-NUC` from the gbox venv with
  `PYTHONPATH=C:\_tools\gBox\system`. It restarted once (round 39) after a stuck build job; the exact command line is in
  the log. It takes jobs from the Spark control plane and every registry tool is exposed to MCP as `job_<name>`.
- **Yuzu**: portable at `D:\gBox\runtime\switch` (yuzu 1734), configured in `gbox.local-i9-nuc.toml`. Debug sessions
  (GDB stub) come from `launch_game` with `debug=true`; the RAM screen reader `gbox.mercs.titles.re6_switch` works over
  the stub.
- **Game**: RE6 `game_id 115f9cdbba115432`, title id `01002A000CD48000`, base NSP in `D:\gBox\cache\115f9cdbba115432`.
- **Builds** in `D:\gBox\cache\mods\115f9cdbba115432\` (ephemeral - see §6): update-only, clean34, hands-only,
  bodies-only2, heads2, swap1, roster-v1/v2, bisect pairs, cast-swap variants, `leon-as-chris`, `helena-as-chris`,
  `skin-*` (generated), `swap-verify-r37`.

## 3. How a RE6 round is produced (reproduction)

1. **Base build**: the update's five ExeFS files on the base NSP - `switch_mods op=write` with
   `exefs/{main,main.npdm,rtld,sdk,subsdk0}` from the extracted update ExeFS. This build runs a full Mercenaries round;
   the update's *RomFS payload* is not needed (see §5).
2. **Overlay** (optional): a RomFS arc swap built by `gbox.skin_swap` (`random_swap_build` / `cast_swap_build`) with
   `base_build=<base build>` so it inherits the ExeFS.
3. **Launch**: `launch_game` with `mod=<build>` (add `debug=true` when the RAM reader/inputs are needed).
4. **Screen**: the worker's unlock watcher reports `already_unlocked`; the title opens the main menu.
5. **Navigate**: `title`/`press_any_button`/`title_locked` -> A; `main_menu` -> A; `play_game` cursor 3 -> A;
   `extra_content` cursor 1 -> A; mercs menu -> A; `select_stage` -> A; `select_player` -> A; answer the
   **CONTINUE?** prompt with `right`+`A` (NO) -> the stage loads. `alert_ok` (autosave notice) is A.
6. **Hot reload**: at the results screen, overwrite the arc in the build directory **in place** (any valid arc length),
   then start the next round in the same session. Verified with `uPl00LeonUsa.arc` 1,455,481 -> 1,626,591 -> 1,455,481.

The navigation driver used for the captures is `.tmp/drive_play.py` (snapshot-driven: it waits for `timer > 0` and then
captures without pressing anything). It is not committed - it is a session tool; the state names above are what it keys
on.

## 4. The three verified swap scenarios

1. **Texture-group swaps (RE5-style)** do not apply to RE6 player arcs: `uPl00LeonUsa.arc` has four `\model\` entries
   all named `pl0000` with no `_BM/_MM/_NM` names, so `swap_arc` cannot group them.
2. **Whole-model swaps work**: `model_swap.swap_models(slot, donor)` replaces the model payload
   (the zlib-compressed `MOD`), and a Leon slot wearing Chris's model runs a round with a correct render
   (`recovery-re6-leon-as-chris-20261109`).
3. **Multi-arc rosters** (bisected live):
   - update ExeFS only: runs;
   - 1 head arc: runs;
   - 7 heads (all but Helena): runs;
   - 18 hands: runs and renders cleanly;
   - 9 bodies: runs, but the swapped body mesh renders broken (the donor bodies are re-encoded smaller);
   - 34 arcs (7 heads + 18 hands + 9 bodies): runs a full round;
   - 9 heads (with Helena): deadlocks after "Save successful";
   - 36 arcs (all but bodies): hangs at loading;
   - 45 arcs: `Unmapped ReadBlock` crash during load.
   - **Helena's head/accessory donor (`uPl01HeadHelenaUsa.arc`, `AcHead`) is the unstable one** - exclude it.

## 5. Hard-won constraints a reviewer must know

- **The update ExeFS is mandatory** for the unlocked 1.0.2 menu on the i9; the base 1.0.0 image does not carry the
  unlock layout (no signature, no UI units, flag write has no effect).
- **The update's RomFS payload is not needed.** The BKTR patch data resists extraction (region 2 decodes, region 8 does
  not, under every CTR/plaintext/XTS scheme tried), and the game does not need it: base RomFS + update ExeFS plays.
- **A saved in-progress round breaks a swapped build**: the CONTINUE? prompt deadlocks. Delete the save
  (`...\nand\user\save\...\01002A000CD48000\SAVEDATA`) before a swap run; the unlock watcher re-applies the flag.
- **Native effects (flash, grenade ring) require Linux Switch NCE**; the Windows/Yuzu lane reports that explicitly.
  The event channel itself rides **autoplay (bot) runs only** - a plain launch has none.
- **Builds are pruned aggressively.** The durable source is the Spark's content-addressed store by sha256
  (45/45 roster donors restored and verified in round 22).

## 6. Open items (RE6)

1. **Textured enemy reskins.** The model swap works; the swapped enemies render white/checkered. Four approaches failed:
   append the cast maps, replace the enemy's texture slots in place (sorted and in arc order), rename under the unit
   prefix. Findings: the model payload is a zlib-compressed `MOD`; its material records are twelve fixed `0x80`-byte
   names (`pl_nuki`, `pl_skin*`, `pl_base*`) with **no texture reference**, and no `uPlTex` entry carries those names.
   Conclusion: the material -> texture binding is the **unit's asset list**, not an arc edit. Next: find where a unit
   declares the arcs it loads.
2. **Helena donors**: re-export or drop them from the roster.
3. **Donor body quality**: the re-encoded body arcs render broken; a clean body swap needs correct donor assets or a
   `MOD`-level rebuild.
4. **RE6 grenade ring**: needs a GDB-stub RAM spawn plus RE6 addresses (native path is Linux-only).

## 7. For the PM to check

- The hot-reload pair (`hotreload-round2-game-body.jpg` / `hotreload-round3-donor-body.jpg`) against the definition:
  same path, in-place replacement, next round shows new content, two frames of one session, no restart.
- The 34-arc roster build playing a round (`round-results-urbach-chaos.jpg`) versus the 45-arc crash - i.e. the
  bisect conclusions in §4.
- The enemy-texture conclusion in §6: it needs a decision (unit asset-list research vs accepting mesh-only reskins).
- `screensaver.py`/`skin_swap.py` sidebar wiring: `default_mods[title]` must name a base build for a sidebar reskin to
  be launch-ready.

## 8. Files and commits (this lane, RE6-relevant)

Modules: `system/gbox/skin_swap.py` (`_seed_from_base`, `model_swap_arc`, `_attach_donor_textures`, `_character_code`,
`cast_swap_build`/`random_swap_build` `base_build`), `system/gbox/model_swap.py` (`keep_tag`),
`system/gbox/screensaver.py` (per-title base build), `system/gbox/switch_arc.py`,
`system/gbox/switch_romfs_materialize.py`, `system/gbox/switch_romfs_extract.py`, `system/gbox/switch_extract.py`,
`system/gbox/tools.py` (`switch_decrypt`), plus tests under `system/tests/`.

Recent commits on `main` (all pushed): `de3f6a9e`, `26e17653`, `68849fb2`, `604570c0`, `b9764b53`, `af5e0452`,
`f895008d`, `d6be233c`, `1f5dff78`, `3e29d5e2`, `9a0f1d7e`, `eda1f764`, `a17934d2`, `7ceec5a7`, `8f4227b0`.

## 9. RE4 and decrypting, in one paragraph each

**RE4**: `Resident Evil 4 [switch]` (`270a15eb98dab4d7`) boots on the i9 from its 12.08 GB update NSP, reaches the title
(60 FPS) and main menu, and `recovery-re4-sonic-on-leon-v1` applies (the build replaces `bio4/em/pl08.udas` + a texture
pack) - NEW GAME starts and the intro cutscenes play at 10-18 FPS. The in-game village frame was not captured (no key
tried skips the intro); next routes are the Mercenaries character preview or a save state.

**Decrypting**: `switch_nca`, `switch_romfs`, `switch_bktr`, `switch_patch`, `switch_arc`, `switch_extract`,
`switch_romfs_materialize`, `switch_romfs_extract` and the `switch_decrypt` registry tool read this library's
containers on a client with only `prod.keys` (the shipped hactool fails on them). Verified on the 18.8 GB RE6 base:
60,645-file RomFS walk, file extraction, 56 arcs/313.7 MB materialised for swaps. Throughput measured at ~245 MB/s
sequential; 8 threads were slower, so the work is I/O/open-bound and scales by dispatching more containers, not by
threads or GPUs.
