# The blueprint look: every Mercenaries stage and asset as a UE blockout, with a toggle

2026-11-09. The operator: "I want all the levels and assets to be rendered in this UE-blueprint look with a toggle to
turn it off and on in the mod panel. This is something I want across mercenary titles and be able to see these games
with grid blueprints."

This note is the second pass after [re5-stage-greybox.md](re5-stage-greybox.md) (s400 alone, one crate). It covers
the live result of that first overlay, the fix it asked for (mirrored labels), the survey and the overlay set of all
eight RE5 Switch stages with the objects they place, the MercMode toggle that plays such a set, the mod-panel switch,
and what the RE4 and RE6 lanes must measure to produce the same thing with the same module shape.

Honesty rules as in the task guide: a boot is not acceptance, an offline render is not a live frame. Everything in
§2-§3 is offline (structural checks, CPU pictures); §1 names the one live frame there is.

| | |
|---|---|
| Writer | `system/gbox/re5_stage_greybox.py` - unchanged entry points plus `scene_folders`, `Surface.mirror_share` / `upside_share`, `glyph_flags`, `placed_objects`, `measure_objects`, `build_prop_textures`, `prop_label`, `build_all`, `preview_set`; CLI `survey`, `build`, `props`, `all`, `preview`, `prop`, `verify` |
| Tests | `system/tests/test_re5_stage_greybox.py` (21, synthetic fixtures), `test_mercmode_blueprint_look.py` (10), `test_switch_mods_blueprint.py` (4), `tests/test_blueprint_look.cjs` (4), 2 new in `test_bot_logic_sidebar.cjs`, 2 new in `test_re5_modifiers.cjs` |
| Toggle | `gbox/mercmode.py` `DEFAULT['blueprint_look']`, `BLUEPRINT_FEATURE`, `effective_mod`, `same_build`; `gbox/screensaver.py` `_start` / `round_boundary` / `MercModeSettings`; `gbox/mercmode_tool.py`; `gbox/worker.py` feature `mercmode_blueprint_look`; `gbox/switch_mods.py` `op=blueprint` (`blueprint_build`) |
| Panel | `clients/web/viz/blueprint-look.js` (shared), the switch in `re5-modifiers.js` ("MercMode look") and `bot-logic-sidebar.js` (under "Live mods"); loaded by `web/index.html`, `desktop/index.html`, `desktop/mini.html`, `web/mercs-live.html` |
| Inputs (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\stage\inputs\s400.arc .. s407.arc` (536,924,607 bytes) and `inputs\uom\uOm*.arc` (71: the first note's 32 plus 39 more, 51,882,701 bytes), copied read-only from `spark:~/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive/` one file at a time; every copy's SHA-256 matched the host's (`sha256sum` both sides, 79 files) |
| Output (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\assets\stage-greybox-all-v1\` - `romfs\nativeNXx64\ImgNX\Archive\*.arc`, `receipt.json`, `sNNN-textures.png`, `sNNN-view.png`, `objects-textures.png` |

## 1. What the first boot showed, and the handedness fix

`stage-greybox-s400-v1` (`s400.arc` `f26d2836…`, 159 BC7 albedos) booted and rendered on lilspark in session
`ae02be4bd9974915-32e89a55f69c46db`, build `recovery-greybox-s400-pool-test-20261109` (frame artifact `0b92a401…`,
reported by the coordinator): Public Assembly's walls in the grey metre grid with their labels ("06 m x 03 m",
"03 m x 0.3 m", "0.7 m"), the floor in the blue grid with "256" labels, lighting and shadows intact, 286 kills into the
round, no hang. **The BC7 / `mtf_tex.replace_image` path is proven on 1024² and 2048×1024 surfaces with 11-12 mips and
on alpha-tested surfaces.** The crate (`prop-box-crate-v1`) was in the same build and did not stop the load; whether
it draws as a box is not judged.

One flaw: **several wall labels read mirrored.** Cause: the texture's UV mapping is the mirror image of the screen's
on some surfaces. The writer now measures it per triangle: with `T = ∂world/∂u`, `B = ∂world/∂v` (the Jacobian
`_charge` already computes for the tile span) and `N` the geometric normal of the winding (CCW seen from outside, the
measured convention), the image is upright to a viewer outside the surface when `(T × B) · N < 0` - the screen's
right × down points into the screen, along `−N` - and mirrored when `(T × B) · N > 0`. A vertical flip is the same
handedness flip as a horizontal one (it is a horizontal mirror plus a rotation, and labels rotate with the UVs
anyway), so this one sign is the whole invariant. Per texture `Surface.mirror_share` is the area-weighted share of
mirrored triangles; `plan` sets `mirror` (share > 0.5: the glyphs are drawn flipped left-right, `_glyphs`) and `both`
(0.25 ≤ share ≤ 0.75: the dominant reading in the middle and the other at 0.6 size under it, so one always reads).
The grid itself is untouched - only the glyphs change.

Measured on the real s400 (not the fixture): 34 textures upright, 10 mirrored, **115 of both hands**, many at exactly
0.50 - walls modelled with both faces (the back face carries the mirrored texture whatever the writer does; the
two-way label is the right answer there, not a flip). The four big ground sheets are upright (`y_jimetesuB_BM` 0.011,
`y-s114-jimetesuDa_BM` 0.0, `y-s114-jimetesuF_BM` 0.0, `y-s114-dobusoko_BM` 0.215), which agrees with the frame
(floor labels readable, walls not); the sign convention cannot be pinned further from one frame, so if a live frame
shows a label backwards on a texture of share > 0.75 or < 0.25, the constant is on the wrong side and
`MIRROR_SHARE` flips - the receipt gives every texture's share. Of the labels the frame showed mirrored:
`y-s114-roujokabeAe_BM` 0.511 and `y-s114-basue_BM` 0.582 are now flipped, `s102_T_kabe67_BM` 0.472,
`y-s114-aoiekabeA_BM` 0.314, `y-s114-danyakuhako_BM` 0.485, `y-s114-sirotans_BM` 0.31, `om_hiraA01_01_BM` 0.5 get
both readings, `y-s114-itibaCa_BM` 0.204 and `y-s114-roujokabeAdd_BM` 0.0 stay upright (if one of those two was the
backwards one, the frame would have been of its back face).

The CPU renderer (`_rasterise`) shares the convention (row 0 of the decoded image at v = 0, as `replace_image`
writes it and as the live Sonic and Mario atlases confirmed), so a head-on CPU view of a wall is the same check the
game would give, minus that one assumption. Run on s400 (scratch `headon.py`: the largest mesh drawing one texture,
viewed from outside along `−N`, screen right × down = into the screen, screen down = world down):

| texture | mirror_share | v1 (`f26d2836…`, the archive that played live) | this set |
|---|---:|---|---|
| `y-s114-suramubackA_BM` | 0.964 | "m 80 x m 02" - **backwards**: the live flaw, reproduced offline | "20 m x 08 m" (glyphs flipped) |
| `y-s114-kabe71_BM` | 0.153 | "16 m x 05 m" | "16 m x 05 m" (glyphs plain) |

(`s400-headon-v1-*.png` and `s400-headon-*.png` in the overlay folder, §3. A first version of the script built
right = up × forward, which turns the whole view half a turn; it made both read upside down and was corrected before
these pictures were taken.)

A second rule from the same Jacobian covers walls whose v grows upwards (the image's top row at their foot): on
side-facing triangles the image's up is `−B`, which points down in the world where `B.y > 0`. `Surface.upside_share`
is that area share, and `glyph_flags` turns the glyphs half a turn (`turn`) when it is over 0.75 on a texture with at
least a quarter of its area on walls. Near one half (posts, double-sided pieces) any choice is wrong for half the
surface, so nothing is turned; floors are never turned (no up for every viewer). Mirror + turn is a vertical flip;
the four cases (u right / left × v down / up) all come out upright on a planar wall (unit test). On s400 the big
walls measure `upside_share` 0.0-0.01 (v grows down, as artists map walls), and four small pieces are turned
(`y_siroki_BM` 0.786, `y-s114-em1a00_BM` 0.784, `y_keikouA_BM` 0.97, `y_syokukaidanA_BM` 1.0).

## 2. The eight stages: survey

Repeated per archive as the first note required. `survey_stages.py` (scratch) ran `mt_arc` identity, the `_BM`
formats, an fvf survey (float3 position at +0, s8 normal at +12 of unit length, half2 UV at +20, checked on every
vertex), `measure`, and the layouts. Every archive rebuilds byte-identically (`mt_arc.build(parse(x)) == x`).

The first column block is the survey with the s400 method as it was (scope `scr01`, `_BM` names, six formats); the
second is the final writer on the same archive (all scenery folders, `_BM-NN` names, nine formats). Numbers from the
receipts, not estimated.

| stage | bytes | entries | survey (s400 method): albedos / meshes / skipped / unbound | scenery folders (final) | albedos written | floor / wall / other / sky | models / meshes / triangles | skipped (format) | unbound meshes | notes |
|---|---:|---:|---|---|---:|---|---|---|---:|---|
| s400 Public Assembly | 75,672,496 | 590 | 159 / 1,312 / 3 / 0 | `scr00`, `scr01` | 159 | 25 / 101 / 31 / 2 | 44 / 1,312 / 213,712 | 3 (`37607D20`, in `tuikaita`, `yataikabe`) | 0 | the first note's numbers |
| s401 The Mines | 51,892,738 | 356 | 47 / 303 / 2 / 37 | `scr00`, `scr01` | 48 | 5 / 28 / 15 / 0 | 22 / 343 / 98,855 | 0 | 0 | 35 bindings into `scr00` albedos, 3 into `_BM-62`; `s103_denkyu01_BM` (light bulb, unbound) kept native |
| s402 Village | 42,742,279 | 458 | **0** / 0 / 0 / 0 | **`scr00` only** | 80 | 18 / 38 / 23 / 1 | 42 / 838 / 182,369 | 0 | 0 | the s400 scope finds nothing here |
| s403 Ancient Ruins | 76,272,279 | 450 | 80 / 587 / 0 / 8 | `scr00`, `scr01` | 80 | 24 / 48 / 8 / 0 | 13 / 588 / 282,288 | 0 | 8 | the 8 meshes bind three `_NUKI` textures (`s-nuki00`, `s-s302enkei`, `s-wara`) in a format `mtf_tex` does not parse: left native, `albedo_unparsed` |
| s404 Experimental Facility | 46,531,283 | 322 | 40 / 535 / 0 / 0 | `scr00`, `scr01` | 38 | 11 / 11 / 15 / 1 | 5 / 535 / 165,681 | 0 | 0 | `g-s404-dummysmoke_BM`, `g-s404-shadowcast_BM` (unbound, sprite / shadow) kept native |
| s405 Missile Area | 99,443,101 | 663 | 33 / 179 / 2 / 299 | `scr00`-`scr07` and **`stage\s314\scr\scr01`** | 158 | 14 / 56 / 88 / 0 | 53 / 772 / 346,951 | 0 (`2D30A6AF`, `33C09993` measured; the `36D0D7A7` mesh sits in `s307_01_Shadow`, whose MRL does not parse) | 0 | albedo names `_BM-00` .. `_BM-97`; 58 of the 88 "other" are per-area copies (`box_01`, `machine`, `silver_pipe`, `roofparts`, `o-s307_BM-NN` in each `scrNN`) that no parsed material binds - drawn as the checker, harmless if unused |
| s406 Ship Deck | 75,165,100 | 646 | 79 / 597 / 0 / 0 | `scr00`, `scr01` | 79 | 10 / 48 / 21 / 0 | 108 / 597 / 396,336 | 0 | 0 | the biggest geometry |
| s407 Prison | 69,205,331 | 506 | 81 / 1,363 / 33 / 0 | `scr00`, `scr01` | 81 | 14 / 41 / 23 / 3 | 40 / 1,396 / 254,920 | 0 (`2C207F5E` ×32, `2D30A6AF` ×1 measured) | 0 | `y_407_daidokoroA/B_BM`, `y_s407_ugari_BM` unbound (kitchen pieces; MRL `tyuubo` does not parse): the checker with `?? m` |

Every stage's own `s4NNh_scr` / `s4NNh_eff` (hit and effect geometry) and the shadow pieces have MRLs `mtf_mrl` refuses
(texture commands outside their one-entry table, as on s400): no drawn albedo, nothing to write.

What changed in the writer because of the survey:

- **Scope.** `scene_folders(arc)` = every `stage\sNNN\scr\scrNN\` folder holding a MOD, so s402 (scr00) and s405
  (scr01..07 + s314) are covered; `stage_scope('s400')` remains for the s400 case and the tests.
- **Albedo names.** `ALBEDO_NAME = _BM(-\d+)?$`: s401 binds `_BM-62`, s405 `_BM-00` .. `_BM-97` (the same BC7
  container, the suffix is a Maya export index). The albedo set is the union of the named BC7 TEX in the scenery
  folders and every TEX a scenery material binds in the albedo slot (`0xCD06F`), wherever it lives under `stage\`.
- **Vertex formats.** Three more follow the measured layout and were added to `STAGE_LAYOUT` with the evidence:
  `0x2C207F5E` (28 B; +24 half2 second UV), `0x2D30A6AF` (28 B; +24 half2), `0x33C09993` (32 B; +24 half2, +28
  RGBA8 with alpha 255) - normal of unit length on 100 % of their vertices (99.3 % on s407's `0x29F0B449`, the
  measured format), UVs finite and under 64. `0x37607D20` (s400, 3 meshes: normal unit length on 24.6 %, UVs not sane)
  and `0x36D0D7A7` (s405, one 73-vertex mesh, stride 20, normal 0 %) fail the check and stay skipped.
- **Unbound textures.** An albedo no measured material binds is drawn only when its name says sky / roof / floor /
  wall, or as the checker with the `?? m` label otherwise; a name that says sprite, light or shadow
  (`EFFECT_WORDS`) keeps it native and lists it under `kept_native_textures`.
- **Objects.** `placed_objects(arc)` reads the stage's `*_IDo00_Ins` (static scenery, class `uIm`,
  `mpInfo.mName` = `om0816_IDo00_U001`, `om083fF_…`, `OM100C_…`) and `soft\<mode>\*_IDF00/01_Ins` (interactive,
  `mUnitClass` = `uOm0886`) and names the archives (`uOmNNNN.arc`, lower-case hex as the host spells them). s400
  gives the first note's 32; all eight stages place **73 distinct archives**, 71 of which exist on the host as plain
  files (`uOm08b8` and `uOm0912` exist only as variants `uOm08b8Eff.arc` / `uOm08b8_Limited.arc` /
  `uOm0912_s119Tram.arc`; which one a stage loads is not known, they are left alone).

| stage | object archives placed |
|---|---|
| s400 | 002b 0100 0805 0811 0816 0818 082b 083f 0840 0847 0848 0849 084a 084b 084c 0857 0859 0867 0886 0889 088a 0890 0894 0933 0934 094b 094e 094f 100c 1103 1315 f201 |
| s401 | 0100 084b 0875 0886 0889 088a 0890 08ae f201 |
| s402 | 0100 0811 0816 0858 087b 087d 0883 0884 088b 08a7 08c6 08c9 08d3 08d5 08dc 101b |
| s403 | 0100 087b 088b 08e0 0952 0953 f200 |
| s404 | 0100 0886 088d 08b8* 08bd 0933 0934 0967 0968 f201 |
| s405 | 0100 0704 070d 0886 088d 0894 08c8 090f 102a 102b |
| s406 | 0100 0886 088d 08bd 08de 0925 100f f201 |
| s407 | 002a 002b 0100 083e 0845 084b 0857 0859 0889 088a 0890 08dc 0912* 0934 0957 1009 100a 102e 1103 |

`*` only as a variant archive on the host.

## 3. The overlay set `stage-greybox-all-v1`

`python -m gbox.re5_stage_greybox all --inputs … --uom … --out …` writes every stage through `build` and every
placed object archive through `build_prop_textures` (albedos only: the orange prop grid, one cell per metre of the
measured tile span, the object's reading as the label - `prop_label`: `kibako` → CRATE, `taru` → BARREL, `reddrum`
→ DRUM, `takarabako` → CHEST, `sunadokei` → HOURGLASS, unknown romaji upper-cased), geometry untouched except the
crate, which goes through `build_prop_box` first (the in-place box the first note proved offline and that did not
stop the live load) and then the texture pass. Of the 73 archives placed, 71 are on the host and 68 are written;
skipped: `uOmf200` / `uOmf201` (ladder behaviour, no model), `uOm070d` (its models bind no BC7 albedo), `uOm08b8` /
`uOm0912` (only variant archives on the host). Every unchanged entry is byte-identical (checked per archive by the
writers); `verify` runs on every stage; a second, independent run into another folder in another process gave the
same SHA-256 for every file (the rebuild-identical check).

| file | SHA-256 (written) | bytes | source SHA-256 | changed entries | textures | glyphs upright / mirrored / both (turned) |
|---|---|---:|---|---:|---:|---|
| `s400.arc` | `8c7ec9d96bd4cda09ff3798b55f3fce1d06ab3cbc2e9cf659d895449f69521b1` | 31,076,592 | `246e3dd40beffcac…` | 159 of 590 | 159 (other 31, wall 101, floor 25, sky 2) | 34 / 10 / 115 (4) |
| `s401.arc` | `5228b0a02f5ab22c10b1500b76adf426499fe1791d92f86fb3ceb6fd60f8297d` | 33,036,817 | `213fcc38b25072be…` | 48 of 356 | 48 (floor 5, wall 28, other 15) | 14 / 4 / 30 (3) |
| `s402.arc` | `9235dbef6c98d163b00cccb5aede698320827d4e69ffba834494a1af4e613a7a` | 25,327,672 | `4b2d5c557a363d62…` | 80 of 458 | 80 (wall 38, other 23, floor 18, sky 1) | 40 / 7 / 33 (5) |
| `s403.arc` | `40896df833c570a080fff7f4ef9d0c61f7f7858c0d7d4813219a4d79cd3173b0` | 31,885,079 | `069a12c2ff79dddd…` | 80 of 450 | 80 (floor 24, wall 48, other 8) | 19 / 4 / 57 (1) |
| `s404.arc` | `c2c5d67597e252b5f48fd315ce0eb03dc8c8d6ce7a02d5d43253c500f473203b` | 21,565,850 | `cb2c8d8184c89bb0…` | 38 of 322 | 38 (wall 11, other 15, floor 11, sky 1) | 12 / 5 / 21 (0) |
| `s405.arc` | `5571093c534e0dc43a3059ab55179aff17f102beae626295ca2fcea7355b3cec` | 34,759,634 | `2466a7a73a792c7e…` | 158 of 663 | 158 (wall 56, floor 14, other 88) | 88 / 4 / 66 (6) |
| `s406.arc` | `f6c966fa7b3ff548d702b239fd01ff4f6bb1b4f20738b6930c6d35c5d0a6d7e6` | 34,694,313 | `b821641cc4246b88…` | 79 of 646 | 79 (other 21, wall 48, floor 10) | 24 / 1 / 54 (0) |
| `s407.arc` | `e97c289f0355b6f5aea137842b9fe0755ec9ede7c86ac2abba5530159210cecc` | 29,438,591 | `59b6535037a238de…` | 81 of 506 | 81 (other 23, wall 41, floor 14, sky 3) | 34 / 5 / 42 (3) |
| 68 object archives (`uOm*.arc`) | see receipt.json `files` | 92,261,430 | | 105 | 104 albedos | |

Object archives skipped: `uOm070d.arc` (no object model of the archive binds a BC7 albedo); `uOm08b8.arc` (archive not present locally); `uOm0912.arc` (archive not present locally); `uOmf200.arc` (no object model of the archive binds a BC7 albedo); `uOmf201.arc` (no object model of the archive binds a BC7 albedo).

Rebuild check: a second independent run (C:\_tools\gBox\.scratch-merc-recovery\stage\rebuild-check) gave the same SHA-256 for every file.

Pictures: `sNNN-textures.png` (every written albedo of the stage, mip 0), `sNNN-view.png` (the stage from above,
orthographic, the written albedos on the native LOD-0 geometry, flat shade, 120,000 triangles at most - not the
game's lighting), `objects-textures.png` (every written object albedo), and `s400-headon-<texture>.png` (four s400 walls seen
head-on from outside, the check of §1). The 2048×1024 sky tints and the two-way labels are visible on the sheets.

What a live frame must show: every stage in blue / grey grid tiles with metre labels under native light; labels
reading forwards on walls that read backwards in the s400-v1 frame (two-way labels on double-sided walls); every
placed object - barrels, crates, drums, chests, hourglasses, stalls, cars, trees, awnings - in the orange grid with
its label, breaking as before; enemies, players and effects untouched; the sky a flat tint. Failure signs: a black
screen or hang on one stage only (that archive; bisect by variant with `build --override`), a photo surface left
(that stage's `kept_native_textures` / `albedo_unparsed`, or an effect model), a backwards label on a texture of
share far from 0.5 (`MIRROR_SHARE`), an object still photo-textured (its archive skipped, or a variant archive).

Boot order, cheapest information first: s400 again (the fixed labels, the crate's texture pass) → s402 (the
scr00-only scope) → s405 (the `_BM-NN` names, the s314 piece, the new formats) → the rest; the objects ride along
with whichever stage places them. One build holds them all: `switch_mods op=blueprint` below writes the set over a
copy of the playing build.

## 4. The toggle

**Setting.** `blueprint_look: bool` in `gbox.mercmode.DEFAULT` (false), strictly boolean (`normalize`,
`MercModeIn`, `MercModeSettings`), worker feature `mercmode_blueprint_look` (`gbox/worker.py`; the route refuses it
with 409 for a paired PC whose worker lacks the feature and never relays it there, like `repeat_queue`).

**Companion.** `switch_mods op=blueprint game_id=52d15709be0fda1a build=<build> changes={<RomFS path>: {artifact:
<sha256>}, …}` creates or refreshes `<build>-blueprint`: a copy of the build's overlay files (`copy_build`) with the
manifest's archives written over them (`write_files`). Idempotent: a file whose SHA-256 already matches is not
rewritten (an `artifact` key *is* the content's hash, so nothing is fetched for it), the source's files are re-copied
where the companion's differ, companion files that are neither the source's nor the manifest's are removed, so the
companion is always "source + manifest"; the source build is never written. The brief spelled the name
`<build>+blueprint`; `+` is outside `switch_mods.NAME` (Eden's add-on folder names) and the queue's mod pattern, so
the realisation is `-blueprint` (`BLUEPRINT_SUFFIX`, one constant in `switch_mods` and in `mercmode`). While a session
runs the companion the edit waits in `.gbox-pending/` and lands at the title's next start, as every edit does. The
manifest is `receipt.json` → `files` of the overlay set: upload each archive with `POST /api/artifacts`, pass
`{path: {"artifact": sha256}}`.

**Scheduler.** `mercmode.effective_mod(cfg, mod)` is the build a round plays for a queue entry's `mod`: the
companion while the setting is on, the entry's own build when off; `default_mod` applies it to every pick, so the
queue keeps the plain names and `_start` launches the companion (`local_build_ok`, as any DJ build). At the round
boundary the "same build already loaded, no restart" rule compares the running build with the head's *effective*
build (`mercmode.same_build`): flipping the toggle therefore restarts the title at the next boundary into the other
build, and nothing changes in the round being played. If this PC's build index knows the plain build but not the
companion yet (`op=blueprint` not run for it), `_start` plays the plain build, records `blueprint_fallback` in the
run and audits `mercmode.blueprint_missing`; `same_build` honours the fallback so there is no restart loop. A queue
entry without a build (the stock game) has no companion and plays as it is: make one from an empty `new_build` and
queue that build.

**What needs what.** The control-plane side (`mercmode.py`, `screensaver.py`, `switch_mods.py`, `mercmode_tool.py`,
`worker.py`) takes effect at a service restart (the 05:00 cron or by hand when nothing plays); nothing in the bot or
the worker's hot-reload set changed. The panels are static files (F5 / app reload).

**Panel.** `clients/web/viz/blueprint-look.js` reads the PC's row from `GET /api/mercmode` (by the run's session id,
then the worker id, then the PC name) and sets `POST /api/mercmode {host, blueprint_look}` - the route every other
MercMode setting uses (`mercmode.js`); no new route. The RE5 modifiers panel shows it as the fieldset "MercMode look"
and the bot-logic sidebar under "Live mods", both labelled "Blueprint look (grid textures on the level)" with the
note "applies at the next round · MercMode on <PC>", disabled until the setting is known (an older PC, no owning PC,
or a failed read) and confirmed from the route's fresh status, never from the click.

## 5. Across titles: what the RE4 and RE6 lanes produce

The same toggle plays any title's companion: `op=blueprint` and `effective_mod` know only RomFS paths and build
names. What a lane must deliver is an overlay set with the same receipt shape (`files` {RomFS path: sha256, bytes,
source_sha256, kind}, per-archive `textures` rows with `variant`, `cells`, `label`, `glyphs`, `mirror_share`,
`payload_sha256`, `live_verified: false`, what must be seen, failure signs), produced by a module of the same shape:

| step | title-agnostic (reuse from `re5_stage_greybox`) | title-specific (measure first) |
|---|---|---|
| open the stage container | - | the archive format and its byte-identical rebuild (`mt_arc` for MT Framework titles; RE4 Switch: `UDAS`/`DAT` of `stN/rNNN.udas`, see re4-switch-model-replacement.md §2) |
| decode the geometry | `Surface`, `_charge` (areas, up / side / down shares, UV→world Jacobian, handedness), `classify`, `grid_cells`, `span_label`, `plan` | positions / normals / UVs / triangles per mesh: the vertex formats (an fvf survey per archive: position offset, normal unit length, UV sanity, like `survey_stages.py`), the index decoding (RE5: strips in `mtf_author.mesh_triangles`; RE4: runs with no index buffer - type 5 list, 6 strip, 8 quads) |
| find which texture a mesh draws | - | the material → albedo binding (RE5/RE6: MRL slot hash `0xCD06F`, `mtf_mrl.inspect_bindings`; RE4: material byte 12 = diffuse image index → the TPL's `(pack id, index)` → `imagepackhd/<pack>.pack.fen`) |
| draw the grid | `grid_image`, `_glyphs`, `_label`, `PALETTE`, the mirror / both-ways rule | - |
| write the texture back | - | the container and format: RE5 Switch albedos are BC7 in the `mtf_tex` layout (`replace_image`); **RE6 Switch albedos are `0x2B` BC3 holding Y'CbCr** (re6-switch-handover.md §0.1) - `re6_switch_tex.encode_albedo`, not `mtf_tex`; **RE4 Switch textures are DDS DXT3 / DXT5 with full mip chains inside a zlib `pack.fen`** - a BC2 / BC3 encoder plus the pack writer, and the alpha must be kept as here |
| the objects | `prop_label`, `measure_objects`'s shape | the stage's object list (RE5: XFS layouts, `placed_objects`; RE6: its own `scr` / `soft` layouts, to be read; RE4: the room's `.udas` already holds its models, so "objects" are the room's own meshes) |
| the set | `build_all`'s receipt, `preview_set`, `verify`'s rules (every unchanged entry byte-identical, header / mips / size / alpha unchanged) | the romfs paths of the set |

Order of measuring for a lane, as it was done here: (1) copy the stage archives read-only and prove the container
rebuilds byte-identically; (2) list where the scenery lives (folders, counts of model / material / texture entries);
(3) the texture formats of the albedos and whether the title's own encoder round-trips them (a flat-colour probe
texture first, as RE6 did with `re6sw_probe_albedo_solid`); (4) the fvf survey per archive, skipping what fails the
unit-normal / sane-UV check; (5) the bindings, so `unbound_materials` is zero or explained; (6) build one stage,
verify, boot it alone, read the labels for handedness; (7) the rest. RE6's known blockers: the `0x2B` colour path is
fixed on paper only (not live-verified), and its stage loads on the Spark crash (the save-aside recovery is
approved). RE4's: no texture writer for `pack.fen` exists yet and the bot cannot fight a round there.

## Reproduce

```powershell
$py = 'C:\_tools\gBox\.venv-session-audit\Scripts\python.exe'
cd C:\_tools\gBox-wt-blueprint
$env:PYTHONPATH = 'system'
& $py -m gbox.re5_stage_greybox survey  INPUTS\s405.arc --stage s405 > s405-survey.json
& $py -m gbox.re5_stage_greybox all     --inputs INPUTS --uom INPUTS\uom --out OUT\stage-greybox-all-v1 --no-preview
& $py -m gbox.re5_stage_greybox all     --inputs INPUTS --uom INPUTS\uom --out OUT\rebuild-check --no-preview   # compare the two receipts' files
foreach ($s in 's400','s401','s402','s403','s404','s405','s406','s407') { Start-Process $py -ArgumentList "-m gbox.re5_stage_greybox preview --out OUT\stage-greybox-all-v1 --stage $s" }
& $py -m gbox.re5_stage_greybox preview --out OUT\stage-greybox-all-v1 --objects
& $py -m gbox.re5_stage_greybox preview --out OUT\stage-greybox-all-v1 --merge
& $py -m gbox.re5_stage_greybox verify  --original INPUTS\s405.arc --candidate OUT\stage-greybox-all-v1\romfs\nativeNXx64\ImgNX\Archive\s405.arc
```

A stage build takes two to four minutes (BC7 encodes through `ispc_texcomp`); the CPU view about a millisecond a
triangle (capped at 120,000). Tests: `PYTHONPATH="system;system/tests" -m pytest -q system/tests/test_re5_stage_greybox.py
system/tests/test_mercmode_blueprint_look.py system/tests/test_switch_mods_blueprint.py` and `node --test
system/tests/test_blueprint_look.cjs system/tests/test_re5_modifiers.cjs system/tests/test_bot_logic_sidebar.cjs`
(two failures in `test_re5_modifiers.cjs` / `test_mercs_clock.cjs` about the desktop shell's `#pipmenu` predate
this work and fail on `origin/main` too).

## Not done, and why

- **No boot of the set.** Offline by the brief; the s400-v1 frame is the only live evidence, and the handedness
  sign rests on it plus the renderer's convention (§1).
- **Objects boxed:** only the crate. The in-place box needs an allocation large enough for 24 vertices / 29 index
  words per part and was proved on the crate's layout only; every other object keeps its geometry and gets the grid
  on its albedos, which is the look the operator asked for.
- **A per-mesh UV edit** (exact grid everywhere, upright labels on both faces of a double-sided wall): a MOD edit
  beyond this pass.
- **Light maps, normal and mask maps** native by design; **effect sheets** (`tx*_BM`, `effect\…`) native; the two
  variant object archives not located; `uOmf200` / `uOmf201` have no model.
- **RE4 / RE6 sets:** §5 is the specification; nothing for them is written here.
