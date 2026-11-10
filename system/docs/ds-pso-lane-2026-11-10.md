# The DeepSeek PSO lane: round 1 — the disc's map data, the set archives, and the executable (2026-11-10)

My lane is `DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md` §0d: PSO Episode I & II, decrypted and broken down, then a map
editor and character hot-swap. This is the first round doc, as the guide asks ("the first round doc is due after your
first package step"). Work is on the i9-NUC, in a worktree off `C:\_tools\gBox`, branch `pso-disc-breakdown-20261110`.

**Round 1 changed the picture in one important way.** The guide (§4 P2) names `map_*_n.rel` / `c.rel` for geometry and
collision and `d.dat` / `e.dat` for the object and enemy sets. The collision part is right. The **placement part was
pointing at the wrong files**: the loose `map_*d.dat` at the disc root are not what the game loads — the executable
names three archives, `gsl_set_object.gsl`, `gsl_set_enemy.gsl` and `gsl_set_event.gsl`, and the real per area,
per layout placement sets live inside them as `map_<area>_<layout>o.dat` / `e.dat` / `.evt`. That is now decoded, and
the map writer edits it.

Also: the placement record is 68 bytes, and its `kind` field is `flags | class_index`, proven over 22,521 records.

## 1. What I decoded (new this round)

| Format | What was unknown | What it is now | Proof |
|---|---|---|---|
| **The placement set archives** `gsl_set_object.gsl` (144 entries), `gsl_set_enemy.gsl` (150), `gsl_set_event.gsl` (143) | Nothing in this tree read them; the guide pointed at the loose `.dat` files | The executable names all three (twice each in `PsoV3.dol`: `0x43DE08`, `0x43DE1C`, `0x43DE30` and again in the archive-name table). Each entry is one area+layout's set: object (`…o.dat`), enemy (`…e.dat`), event (`….evt`), plus `_off` and `_gj` variants. Forest 1 alone has **6 object-set layouts** (`map_forest01_00o.dat` … `_05o.dat`, 71–120 placements each) and 6 enemy sets | `gbox.pso_map_write.set_archive_files` / `read_set`; the DOL string table in `pso-gc-executable.md` §5 |
| `map_*_<layout>o.dat` — the **object placement record** | Never decoded anywhere in this tree | A bare array of **68-byte (0x44), little-endian records**. Fields named: `kind`, `set_id`, `group_id`, `amount`, `x/y/z` (LE f32), `flags_a/b/c`, `angle`, `scale_x/y`, `link`, `extra_a/b`, `stamp`. `gbox.pso_setdata` reads, patches and rewrites them **byte-identically** | 141 loose + 144 archive set files parse; **every one rebuilds byte-identically**. 22,521 archive placements + 18,785 loose |
| **`kind` = `flags \| class_index`** | The field was an opaque number | The low byte is the object **class index**; everything above it is flags. Proven by the census: over 22,521 placements the high bits take only **12** values (all sparse bit sets: `0x100`, `0x200`, `0x20000`, `0x2000000`, `0x8000000` and their combinations) while the low byte spans **108 distinct class indices 0..220** — and `PsoV3.dol` carries **315 `TObj*` class-name strings** for the registry those indices address | `pso_setdata.kind_class` / `kind_flags` / `kind_report`; `tests/test_pso_map_write.py::test_real_disc_object_sets_are_68_byte_records_with_a_byte_class` |
| The position triple is **world space** | A guess from the byte pattern | Proven by a second, independent decoder: the record's `(x,y,z)` matches the area's own collision-surface height at `(x,z)` within 25 units for **70/71** Cave 1, **72/74** Ruins 1 and 48/62 Pioneer 2 placements, median error **0.00** on Cave 1 and Ruins 1 | `gbox.psomap.collision` vs `gbox.pso_setdata.records`, probe in §4 |
| Which area file is which zone | `ancient*` vs `ruins*` was ambiguous | `ancient01/02/03` = **Episode I Ruins 1/2/3**; `ruins01/02` = **Episode II VR Temple** Alpha/Beta; `space01/02` = VR Spaceship; `jungle01..07` = CCA; `seabed01/02`; `labo00` | The zones' own narration text: `map_ancient_e.bin` is the Ep I Ruins story ("these weapons are from Pioneer 1 … they must have already entered the ruins"); `map_ruin_e.bin` is "VR test field … final Temple area cleared"; `map_space_e.bin` is the VR Spaceship version |
| The `a*` areas | Looked like real campaign areas | **Not campaign areas.** Every `a*` area carries the base area's collision (identical triangle counts: `aforest01` 1,455 = `forest01` 1,455; `acave01` 43,266 = `cave01` 43,266) and **zero placement sets** — they are the alternate/Battle layouts | `gbox.pso_areas` catalogue |
| The area **order** the game uses | A guess by file name | `PsoV3.dol`+`0x431C04` holds the area-archive table in load order (`gsl_city`, `gsl_forest01`, `gsl_forest02`, …). `gbox.pso_areas.LIST_AREA_TABLE` is that table verbatim | 39 contiguous `gsl_*.gsl` strings in the DOL |
| **Which binary is the game** | The guide says "`main.dol` on the disc" | **`main.dol` is a 213,952-byte AppSwitcher stub** (`sha256 318a96bd…`). The game is the loose file **`PsoV3.dol`, 5,233,088 bytes, `sha256 1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a`** — the same digest `gbox/pso_gc_live.py` already pins | Hash computed on the disc; matches the repo's `DOL_SHA256` |
| The executable's code map | 175 RAM addresses scattered through `gbox/pso_*.py`, untested and unproven | **34/34** known code addresses resolve in a Ghidra analysis of the real binary (25,981 functions), **17 of them against byte-exact prologues** read through the DOL's own section table. `gbox/pso_ram.py` now names them with a `read_memory` reader and synthetic-memory tests | `docs/research/pso-gc-executable.md` §3; 0 mismatches |
| `.evt` event scripts | Only a header guess | **Little-endian**, header `{u32 code_start, u32 0x10, u32 count, u32 0}`, record stride **0x14 (20)**, and `code_start == 0x10 + 20·count` on all 5 loose files (counts 1, 1, 7, 15, 13) | `docs/research/pso-gc-formats-tables.md` §5 |
| The Scene `.rel` files | Read but not described | **Sega DataView, not GameCube R_DOLPHIN REL.** The trailing `0x20` is 8 BE words `{u32 data_end, u32 reloc_count, u32 1, u32 0, u32 root, 0, 0, 0}`, with `reloc_count` zero-padded u16 entries between `data_end` and the trailer. For `map_forest01c.rel` that is 208 = 69 meshes × 3 pointers + 1 | `pso-gc-formats-tables.md` §3; `psomap.collision` + `rel_root` read exactly these two words |

New module **`gbox.pso_areas`** produces the guide's requested catalogue: **72 areas, 1,000 area files with sizes and
sha256, 784,070 collision triangles, 18,785 loose placements, 0 decode failures**, written to
`docs/research/pso-gc-areas.md` plus a JSON catalogue for the editor.

New module **`gbox.pso_map_write`** is P6a's writer: it moves / adds / deletes placements, in a loose set file or
inside a set archive, through the same disc builder the shipped PSO builds use (`gbox.filemods.build_image`), then
re-opens the built image and proves the edit and that every other record is byte-identical.

### The build this round actually produced

```
map_forest01_00o.dat: 109 placements  (gsl_set_object.gsl entry at 0x4800)
  moved record 60 (kind 0x92, class 0x92) from (-16.6, 24.5, -102.0) to (133.4, 30.5, -102.0)
build  pso_objmove_forest01_l0_r60
image  D:\gBox\cache\mods\436e0bb84d5337d1\pso_objmove_forest01_l0_r60\Phantasy Star Online Episode I & II Plus (USA).iso
verified: 1 edit checked, 109 records in the set, 0 failures
unchanged-record compare: 109 / 109 records, 0 unexpected differences
gsl_set_object.gsl 1,683,456 / 1,683,456 bytes, differing byte offsets: [22528, 22529, 22530, 22531, 22534]
FST entries changed: none
```

Five bytes differ in a 1.6 MB archive (X and Y floats; Z was unchanged so its bytes match), and no FST entry moved —
the strongest form of "one object moved, nothing else touched".

**The built disc boots.** Dolphin 2609 (JIT64 SC, Direct3D 11, HLE) opens the rebuilt image and the game's boot chain
(BIOS -> `main.dol` AppSwitcher -> `PsoV3.dol`) runs to PSO's "CREATED BY SONIC TEAM" splash, so the rebuilt FST and
executable are valid and the edited archive is being read at boot with no error. Frame:
`D:\gBox\pso-ds\frames\built-disc-t2.png` (kept on `D:`, not in git — it is a game asset). **What is not yet done is
the in-game look at the moved object**: that needs the P1 menu walk (§6), because nothing reaches Forest 1 from a
cold boot here yet.

## 2. What I fixed

- `gbox/ninja.py` read the `NJCM` chunk size with `self.e`, i.e. **big-endian on GameCube**, although the chunk size
  is little-endian on both platforms (`gbox/pso_gc.py:njcm_payload` has always read it correctly). On a GC body it
  read `0xB0520000` as the size and survived only because the slice clamped at EOF, so any `NJCM` that is not the last
  thing in its buffer (a BML entry, a copy followed by a `POF0`) over-read into its neighbour. Fixed to `<I` with an
  explicit clamp, and the reason recorded in the code.
- `gbox/psomap.py` `collision()` raised `IndexError` on `Scene/map_boss01swc.rel`, a real disc file whose traversal
  table points at a record that is not a mesh. It now bound-checks every mesh and face and skips what it cannot read;
  `strict=True` still raises when a short read must fail. Forest 1 is unchanged at **1,455 triangles**, the number the
  repo verified on 2026-10-05, so the verified geometry did not move.
- `gbox/psomap.py` `_selftest()` had been **failing on main**: it built one synthetic file and ran it through both the
  GameCube and the Dreamcast readers, but the two face records differ (36 bytes indexing a per-mesh vertex array vs 68
  bytes with vertices inline), so the Dreamcast pass could never succeed. It now has one fixture per layout, and also
  asserts that a file whose table points at a non-mesh yields nothing instead of raising.
- `gbox/gcdisc.py` `dol_to_elf()` gained `gekko=True`, which runs `depair()` over the executable sections so Ghidra's
  stock PowerPC language sees `lfs`/`stfs` instead of Gekko paired-single opcode-4 noise.

## 3. Bugs found and **not** fixed (they need their owners' decisions)

These came out of the doc work and matter for P7a and for area rendering. I did not touch them because each changes
behaviour the bots rely on today; they are recorded here so the next round can take them deliberately.

1. **`gbox/pso_gc.py:159` `gvr_decode`'s `flags & 8` "internal palette" branch is wrong for this disc.** No chunk that
   has bit 3 set carries palette bytes (0 of 1,219), and every CI4/CI8 texture (42 of 42) raises `ValueError` as a
   result. Bit 3 is the **alpha/transparency** flag (98.6 % agreement with "has an `a=0` texel" on CMPR); the palette
   is external, in a `.GVP` (`GVPL` magic). See `pso-gc-formats-textures.md`.
2. **`gbox/pso_player.py` and `gbox/pso_enemy.py` are written for the Dreamcast disc.** They read `PSO/PLCTEX.AFS`
   and `PSO/BM_ENE_BM1_SHARK_A.BML`; this disc has **no `PSO/` directory at all** and the files are lowercase at the
   root (`plCtex.afs`, `bm_ene_*_body_low.bml`). `pso_enemy.PACKS`' 16 pack names are all absent. `pso_player.build`
   cannot run on this disc as written. This is the first thing P7a has to fix.
3. **`gbox/psomap.render_objects()` is Dreamcast-only** and mis-reads the GC `r.rel`/`n.rel`. The tables doc has
   already partly decoded the GC `r.rel` root (`{u32 table, u32 0, u32 count}` with 40-byte sections; Forest 1
   `r.rel`: table `0x2E6C`, 17 sections, 17×40 = `0x2A8` landing exactly on the root at `0x3114`). `n.rel`'s root is
   an ASCII `fmt2` chunk, still undecoded. Any code path that calls `render_objects` on GC Scene data is broken today.
4. **`gbox/psotext.collections` uses the Dreamcast pointer-table convention** (root at `n-0x10`) and returns garbage on
   the GC `PR2` (62 columns / 28,140 strings). The GC root is the **last word** (`n-4`). With that, all five languages
   give the same shape: 45 columns, 2,848 pointers, column 0 = 831 item names.
5. `tests/test_pso_enemy.py::test_collect_reports_the_enemy_slots` **fails on main** (`AttributeError: 'types.SimpleNamespace'
   has no attribute 'deliver'` at `gbox/characters.py:2094`). Verified pre-existing by reverting my changes and rerunning.

## 4. Evidence

The `.dat` position proof (collision floor vs placement Y, on the real disc):

```
map_cave01_00d.dat   recs=199  over_floor= 71  |dy|<25= 70  median= 0.00
map_ruins01_00d.dat  recs=131  over_floor= 74  |dy|<25= 72  median= 0.00
map_city00d.dat      recs= 96  over_floor= 62  |dy|<25= 48  median= 4.90
map_forest01d.dat    recs=150  over_floor= 37  |dy|<25= 24  median= 1.88
```

(Forest 1's loose set extends past its `c.rel` footprint — x up to 1,082 against a collision box of ±685 — so only 37
of its 150 placements land over the collision mesh at all. That is a property of those files, not of the decoder; the
archive set `map_forest01_00o.dat` is the one the game loads, and it is the file the build above edits.)

The 17 code guards, read out of `PsoV3.dol` through its own section table:

```
0x801BB330  OK  '9421fff07c0802a6'  ORIGINAL_UPDATE (player update, tail-chained by the dispatcher)
0x801057A8  OK  '9421ffe07c0802a6'  F_CREATE
0x80103748  OK  '9421fff07c0802a6'  F_DELETE
0x801B9F40  OK  '9421ffe07c0802a6'  F_EQUIP
0x801B9D50  OK  '9421fff07c0802a6'  F_UNEQUIP
0x801B8310  OK  '9421fff07c0802a6'  F_INVENTORY
0x80192DC4  OK  '9421fff07c0802a6'  laser-fence update
  + 0x801D4F14, 0x801D5764, 0x801B3038, 0x801B63AC, 0x8010C740, 0x8010CCB0, 0x80102AC0,
    0x801B8E68, 0x8010B46C, 0x8010B198                          14 more, all matching
0 mismatches
```

## 5. Tests

`tests/test_pso_setdata.py` (10), `tests/test_pso_areas.py` (7), `tests/test_pso_ram.py` (9),
`tests/test_pso_map_write.py` (9) — **35 passed** in the worktree, including the real-disc round trips (skipped when
the image is not on the host). The existing PSO suites are unchanged in behaviour: `test_pso_gc.py`,
`test_pso_gc_reader.py`, `test_pso_gc_inventory.py`, `test_pso3_inventory.py`, `test_pso_map.py`,
`test_pso_geometry.py`, `test_pso_enemy.py`, `test_pso_faces.py`, `test_pso_gc_swap.py`, `test_pso_face_build.py`
pass except the one pre-existing `test_pso_enemy` failure in §3.

## 6. What I could not do yet, and why

1. **The in-game look at the moved object.** P6a's writer is proven byte-for-byte but "the game loads and shows it"
   needs the P1 menu walk to reach Forest 1. That is the next round's first pair of items, in this order: P1's RAM
   state (now testable through `gbox.pso_ram`), then the same build booted and a frame captured.
2. **`n.rel` render geometry.** `c.rel` collision is decoded and proving itself; the render geometry is the one map
   file family left. `r.rel` is part-decoded (17 sections of 40 bytes); `n.rel`'s root is a `fmt2` chunk.
3. **The class registry ordering.** 315 `TObj*` names exist; the table mapping a placement's class index to one of
   them is not located. That is the highest-value decompile left for the editor (it turns a number into "door",
   "warp", "switch", "Booma").
4. **The floor → map-index resolver** (`FUN_80207E88`, 104 bytes) — decompiling it would bind every floor to its area
   and layout without a live load, and would explain Forest 2 resolving to both `forest02` and `aforest02`.
5. **No live session this round.** Everything above is offline decode plus the binary. P1 and every accept test that
   needs Dolphin are round 2+.
6. **Two owned `GPOE8P` executables.** The base Plus disc's `PsoV3.dol` is 5,233,088 bytes (sha256 `1f80fb82...`,
   the build every address in this round belongs to); the Return To Ragol V1.0.3 mod's is 5,236,992 bytes
   (`60fa7646...`). `pso_ragol_unlock.OWNED_EXECUTABLE_SIZE = 5236992` is correct for its own build, not a
   typo - checked against the owned ISO. Address work for Return To Ragol has to be re-derived.

## Round 2 (2026-11-10, later) — P1 started live: the boot-screen id is RAM-readable

> **Superseded in part by round 3.** The byte is real and its transitions are real, but it is a **coarse mode**, not a
> screen id: it reads `1` on the title main menu *and* on SELECT CHARACTER. Read round 3 before relying on it.

The blocker of record is that the campaign "never leaves the title on its own: it does not press Start at PRESS START
... with the screen read from RAM (the menu state bytes), not from frames". This round found the menu state byte and
drove the first press from it, in a live session.

### The live session

- gBox control plane on the i9 at `http://127.0.0.1:8765` (started from this checkout: `python -m gbox --config
  gbox.toml serve --worker`), worker `i9-NUC` `7246f3becd6f47b7` online.
- `POST /api/games/436e0bb84d5337d1/launch?node=7246f3becd6f47b7` → job `ac1aab64c26240b9` → session
  **`7246f3becd6f47b7-ac1aab64c26240b9`**, `gBox Dolphin` 2609, JIT64 SC / Vulkan / HLE, disc `GPOE8P`.
- Note for next time: `debug=true` is **Linux-gated** (`require_os: linux`, so a Windows worker never claims it), and
  it is not needed — the Windows Dolphin adapter always sets `Dolphin.General.GDBPort` and builds `DolphinProcMem`, so
  a plain launch on the i9 has `read_memory`/`write_memory`.

### `gbox.pso_ram` proven against a real session

Read through the read-only `read_memory` RPC (the reply is a hex string; `address` must be a **decimal int**, not
`0x…`). At the title/attract state: `PHASE 0x804FE120 = 10`, `FLOOR 0x805D5FC0 = 0`, `EPISODE = 0`,
`TRAVELLING = 0`, the four player slots `0`, `ENTITY_TABLE = 0`. The map reads cleanly and rejects nothing, which is
the first live confirmation of round 1's `pso_ram.py`.

### The boot-screen id (new, and the thing P1 needs)

`0x80516303` is a **u8 boot-screen id**; `0x805145F7` mirrors it (equal in every sample, so a read can be refused when
they disagree). Values proven by driving transitions and reading the result back:

| id | screen | how it was established |
|---|---|---|
| **3** | **PRESS START** | the title with the literal "PRESS START" text (`p1-seq-11-start.jpg`) |
| **1** | the title main menu (ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE) | `p1-d-now2.jpg` |
| **9** | the ONLINE GAME submenu ("Online Game" / "Options" tabs) | `p1-seq-8-a.jpg` |
| 0 | transient (unset, or a fade) | seen between screens |
| 4 | the title with its menu closed | seen before any press |

The decisive transition, reproduced **three times in a row**: at `3`, a `start` press takes the id to `1`.

**`PHASE` at `0x804FE120` does not distinguish the title from the menus** — it read `0` in both. That is why the old
bot sat on the title: the only "menu" signal the tree had was frames, and the frames path is not RAM state. This round
also confirmed that `PHASE` cycles on its own at the title (`10` attract → `9` → `0`), so a bot keyed on it alone
cannot tell "attract" from "menu".

### New module `gbox.pso_menu_walk.py` (+ `tests/test_pso_menu_walk.py`, 7 tests)

- `screen(reader)`, `describe(reader)` — the id, its name, and whether the game is at PRESS START / in the main menu.
  `screen()` **refuses a torn read** when the id and its mirror disagree.
- `press_start(reader, press)` — the first P1 step. It refuses to press START on any screen that is not PRESS START
  (pressing START in a menu confirms the highlighted item, which is how the walk lost its place during this round), it
  presses once, it waits for the id to move, and it reports the trace with `ok` only when the main menu was reached.
- `MAIN_MENU_ITEMS` records the menu order; the cursor index variable is **not** identified yet.

Live, through the module: `describe` read `{"screen": 1, "name": "main_menu"}` and `press_start` correctly did
nothing (`from_press_start: false`), and in the PRESS START state the same call took `3 → 1`.

`gbox/pso_ram.py` gained `BOOT_SCREEN`, `BOOT_SCREEN_MIRROR` and `boot_screen(reader)`, so the RAM map stays in one
place.

### What went wrong, and what it means for P1

1. **Frames are not a usable feedback loop here.** `/api/sessions/{sid}/frame.jpg` serves the last still a worker
   uploaded, and with no viewer attached that still never refreshes (two reads 2 s apart came back byte-identical while
   the game was animating). `gbox.remote_desktop.window_still(pid)` grabs a fresh window image on this machine and is
   what the round used for the few visual confirmations. P1 must not depend on frames at all — the guide says so, and
   the mechanics agree.
2. **A single-byte before/after diff is mostly noise.** `0x80506274` looked exactly like the cursor (it went 3 → 1 on
   one `dup` press) and is a logo counter: polled with no input it oscillates 3/1. The screen id was found with
   constancy-filtered whole-RAM snapshots (4 samples, 24 MB each, 13.8 s; 87.7 % of RAM constant within 0.4 s), and
   then only accepted because driving START moved it and driving it back did not.
3. **The virtual-pad input channel stopped taking effect** after roughly twenty presses in that session: the game
   kept animating and the RAM still read, but `dup`/`ddown`/`a`/`b` no longer changed anything, and an explicit
   all-keys-up release did not recover it. Whether that is the worker's input pump, a stuck ViGEm report or PSO
   ignoring a pad it saw hold a button is **unresolved**. The next round's walk must therefore assert every step from
   RAM and re-assert/release the pad, instead of assuming a press landed. This is exactly the failure mode the guide
   warns about ("a dead autobot looks like a standing character").

### Not done

The rest of P1 — the offline character/file screens, Pioneer 2, the Hunter's Guild, Forest 1, and both players — is
not walked. The cursor variable inside a menu is not identified, only the screen id. So P1 is **in progress**, not
accepted: the accept test is three cold launches reaching Forest 1 with both players, and this round reached the
title main menu from PRESS START by a RAM-decided press, reproducibly.

## Round 3 (2026-11-10, later still) — the offline branch walked; the "screen id" corrected; the pad precondition

Round 2 shipped `0x80516303` as PSO's "boot-screen id" (3 PRESS START, 1 main menu, 9 ONLINE submenu). **That
interpretation was wrong** and is now corrected. The walk itself went much further than round 2, though: with input
working, real presses reached the offline character screen.

### The walk, live, by real presses

Session `dbc5ff9be4ca416c-c91e5802a9844b37` on the i9-NUC (Dolphin 2609, Vulkan, `GPOE8P`), virtual pad bound:

```
PRESS START  ->  title main menu  ->  OFFLINE GAME  ->  SELECT GAME MODE  ->  SELECT CHARACTER
                 (ONLINE / OFFLINE /   (SINGLE MODE /      (SLOT A, four
                  OPTIONS / WEBSITE)    MULTI MODE)          "NO DATA" slots)
```

Frames (labels only; no decision uses them): `p1b-02-after-start.jpg` (main menu, ONLINE GAME highlighted),
`p1b-03-offline.jpg` (SELECT GAME MODE, SINGLE MODE highlighted, "B Cancel / A Confirm"),
`p1b-04-single.jpg` (SELECT CHARACTER, SLOT A). Back out with `B` returned to each previous screen. This is further
than the campaign has ever driven PSO from a cold boot, and it is the branch P1 needs (offline → character → Pioneer 2).

### The correction: `0x80516303` is a coarse mode, not a screen id

| value | screens it was read on |
|---|---|
| 0 | the title (attract / PRESS START) |
| 1 | **the title main menu AND SELECT CHARACTER** |
| 9 | SELECT GAME MODE |
| 22 | a cancel out of SELECT GAME MODE |

`1` on two different screens is the whole point: the byte changes when the screen changes, so it is a useful
*transition* signal, but **a walk must never use it to decide which screen is up**. Round 2's four values were real
observations; the "screen id" reading of them was not.

### What a walk needs instead, and the failure that showed the way

A screen signature built from the bytes that actually move between two known screens — never a window picked by eye.
Tried the eye first: a fixed 1 KiB window (`0x80516000`, `0x80516200`, `0x80514500`) scored **0.99 similarity between
all four screens**, because those windows are almost entirely zero. The diff-derived approach is in the module
(`stable` → `stable_diff` → `signature` → `similarity`), all tested, with `signature()` refusing any byte that is not
constant while it is taken.

### The precondition that made round 2 look like a walk and round 3 start dead

The virtual pad is what makes presses land without focus. Bound, Dolphin's `User/Config/GCPadNew.ini` carries
`Options/Always Connected = True` and `Device = XInput/<slot>/Gamepad`. **Unbound**, the adapter silently falls back to
the keyboard (`_setup_vpad()` returns `None` when `VGamepad()` cannot take an XInput slot), `win_send_keys` reports
`{"sent": 0}` while the window is minimised, and every press is dropped — a game that looks alive and ignores you.
Three stale `Xbox 360 Controller for Windows` devices from earlier sessions were the cause; restarting the worker
released them and the next launch bound a pad. `pso_menu_walk.verify_pad_binding()` checks the ini, and the rule is now
in the module docstring: **check the pad binding before trusting a walk.**

Two more operational facts worth keeping:

- A launch as an agent on a Windows worker is admitted through `background_testing.admission_reason`, which needs
  `idle_seconds >= 300`, and **the worker's idle clock resets on gBox's own pad input** — so a relaunch right after a
  walking session waits five minutes. Plan the walk as one session.
- Dolphin launches minimised (`si.wShowWindow = 7`) and `remote_desktop.window_still` returns `None` for a minimised
  window. `ShowWindow(SW_RESTORE)` first makes capture work. A zero page in RAM is not a broken reader: `0x80000000`
  reads `GPOE8P` and `0x8000C000` the DOL's first instruction even when every game global is still zero.

### Not done

No RAM discriminator for the screen yet (the signature API exists and is tested; it needs one live diff pass per
screen boundary), so the walk still needs a frame or a scripted sequence to know where it is. Pioneer 2, the Hunter's
Guild and Forest 1 are not reached. P1 remains in progress.

### The next blocker, found at SELECT CHARACTER

The character screen shows **four `NO DATA` slots**, and the memory card this session used
(`Dolphin User/GC/MemoryCardA.USA.raw`, 16 MiB) does hold a PSO directory entry (`GPOE8P` at `0x20C0`) but **no
character**. So P1's "character select (or create)" cannot select: it has to create one — through the in-game name
entry, class, costume and section-ID screens — or the run has to start from a save that already holds a character.
That is a decision for the operator (a prepared save is far cheaper than automating PSO's name entry), and it is the
first thing the next round needs settled.

## Round 4 (2026-11-10) — a character created by pad, Pioneer 2 reached, and `pso_ram` fixed against a real player

P1's blocker was that the memory card held no character, so the walk could not leave SELECT CHARACTER. This round
created one with the virtual pad and walked into Pioneer 2.

### The memory card really had no character

Both cards on this machine (`Dolphin User/GC/MemoryCardA.USA.raw`, 16 MiB, and the gameplay-demo card) carry PSO
directory entries — `PSO_SYSTEM`, `PSO_CHARACTER`, `PSO_GUILDCARD`, game code `GPOE`, company `8P` — but the
`PSO_CHARACTER` entry's block pointer and size fields read zero, and the game itself showed four `NO DATA` rows.
PSO's own verdict is the authority: there was no usable character. Creating one was the only way forward, so that is
what this round did.

### Character creation, all by virtual-pad presses

```
PRESS START -> main menu -> OFFLINE GAME -> SELECT GAME MODE (SINGLE MODE)
  -> SELECT CHARACTER (SLOT A, NO DATA) -> "Want to create a new Character?" YES
  -> CHARACTER SELECT (HUmar) -> FACE editor -> A opens CHARACTER CREATION
  -> CHARACTER NAME (on-screen keyboard, typed "BQF") -> OK
  -> TYPE HUmar / CHARACTER NAME BQF / SECTION ID ORAN -> A CONFIRM
  -> SELECT EPISODE (EPISODE 1) -> Pioneer 2
```

Frames: `p1c-21-after-start.jpg` (the create prompt), `p1c-45-wait.jpg`..`p1c-57-wait.jpg` (the intro, then the class
list), `p1e-03-a.jpg` (the CHARACTER CREATION menu), `p1f-00-name.jpg` (the keyboard), `p1g-99-ok.jpg` (name entered),
`p1h-00-created.jpg` (the confirm summary), `p1h-02-wait.jpg` (SELECT EPISODE), `p1i-01-pioneer2.jpg` (**Pioneer 2**,
Principal Tyrell: "Are you BQF, the Hunter? I'm Principal Tyrell.").

The on-screen keyboard is a grid navigated with the d-pad. The technique that works: clamp the cursor to a known cell
first (`ddown` ×12 then `dleft` ×20 lands on `BS`), then move row by row and column by column. My column mapping was
**two cells off** and produced `BQF` where `DSH` was intended — harmless (the name is now BQF) but recorded so the
next attempt is exact: target column + 2.

### `pso_ram` was wrong about the class name, and the live player showed it

`pso_ram.player()` read the class name as a string **at** `actor+0x00`. On this build `+0x00` is a **pointer**: the
live P1 actor at `0x80DA62A0` holds `0x80446F20` there, and `0x80446F20` is the ASCII `TObjPlayer`. So every player
read returned `None` — the module refused a real player because it was looking at the pointer instead of through it.

Fixed: `OFF_CLASS_POINTER` with `player_class(reader, ptr)` following the pointer, refusing a pointer outside the RAM
window or one that does not land on printable text (so a stale slot still cannot be reported as a player). Tests
updated to put the name behind a pointer, with a new test for the bad-pointer and empty-text cases.

**Live, through the fixed reader**, in Pioneer 2:

```json
{"1": {"cls": "TObjPlayer", "hp": 40, "hp_max": 40, "x": 0.0, "y": -5.4e-07, "z": -2015.0,
       "room": 41, "control_mode": 1, "action_state": 1, "hit_records": 1}}
```

and `snapshot()` reports `floor 0 / Pioneer2 / episode 1`. The HUD in the frame agrees (HP 40/40, TP 29/29, Lv 1, name
BQF), so the RAM map and the screen agree on a real player for the first time.

### Where P1 now stands

The walk reaches Pioneer 2 and the state reader sees the player. What is left for P1's accept test is the town-to-field
leg — the Hunter's Guild counter, the quest/area choice, the telepipe/warp into Forest 1 — and then the same three
cold launches with both players. The character now exists on the card, so a relaunch does not have to create one again.

### Next

1. Pioneer 2 -> the Hunter's Guild -> "Forest 1" -> the field, by pad, with `pso_ram` as the state reader.
2. Player 2: the second controller and the second character (or the same card's second slot).
3. Then P6a's in-game proof (the moved object seen in Forest 1) and P6b (the editor page).

## Round 5 (2026-11-10) — walking on the player's own RAM position, and what was blocking input

P1 needed the character to walk in Pioneer 2. Movement turned out to be the interesting part: buttons reached the game
and the analog stick did not.

### What the input paths actually do (measured, not assumed)

| path | result |
|---|---|
| Virtual pad **buttons** | reach PSO **even with the Dolphin window minimised** — the START in-game menu opened while the window was iconic, which is exactly what `_setup_vpad` exists for |
| Virtual pad **analog stick** (`left_joystick` full deflection) | **no effect**: neither the camera (C-stick) nor the character moved over several seconds of holding |
| Keyboard path (`win_send_keys`, Dolphin focused) | **moves the character**: holding the down key took the player from `(-5.9, -1965.7)` to `(16.6, -1936.2)`, and right from there to `(33.4, -1968.3)`, read back from `pso_ram` |

So in this session the pads' buttons get in and its sticks do not. I could not settle *why* (the ini binds
`XInput/0/Gamepad` with `Always Connected`, `VGamepad` reports a free slot when created here, and XInput slot 0 read
from my own process shows neutral even while the worker's pad is driving buttons) — that is recorded as an open
question rather than papered over. **What matters for P1 is that a movement path exists and is measurable**, and the
walker below works with whichever hold path moves.

Two live traps, both of which look like "the game is ignoring me":

- The **in-game START menu blocks movement**. A burst of walking that mysteriously does nothing is usually a menu.
- A hold that produces no movement looks identical to a wall, a dropped pad or a stuck menu. The walker reports it
  instead of pressing forever.

### New module `gbox/pso_move.py` (+6 tests)

Closed-loop walking on the player's own RAM position: hold a direction, read the position back, keep the axis that
helped and drop the one that did not, stop on arrival, and give up after four holds with no progress with a reason.
`direction_to` picks the dominant axis first; `distance` is planar (PSO's vertical axis is not what walking covers).
All of it is injected (`position()`, `hold()`), so the tests run against a model game — including one where the
"right" key also drifts in z, which the loop still closes because it re-reads instead of trusting a direction.

### Live result

```
start   (36.8, -1961.5)          target (81.8, -2006.5)   distance 63.6
hold 1  (29.8, -2001.5)  52.3    hold 3  (50.9, -2017.9)  33.0
hold 2  (31.5, -2038.9)  59.9    hold 4  (52.9, -2008.2)  29.0
hold 5..7 unchanged                      -> "no progress in 4 holds (a menu open, a wall, or no input)"
```

It moved the character **63.6 -> 29.0 world units** and then stopped at an obstacle, which is the behaviour the module
promises. Better than the numbers: the aim point happened to be where **Irene**, the Principal's secretary, stands, and
pressing A there started the mission briefing ("Well, let me brief you on your mission.") — the next step the Principal
tells the player to take.

### Where P1 stands

PRESS START -> menus -> offline -> character creation -> Pioneer 2 is all by real presses, the character moves by
closed loop on RAM feedback, and the walk reaches the person who hands out the first mission. What is left is the
guild/mission choice and the telepipe into Forest 1, then the same with a second player.

### Next

1. Finish the Irene briefing, take the guild counter's mission, walk into the teleporter, and confirm `FLOOR` becomes
   1 with the Forest collision loaded — that is P1's field arrival.
2. Then the second player (second virtual pad, second character) and the three cold launches.
3. Then P6a's in-game proof and P6b.

## Round 6 (2026-11-10) — the operator took the pad: what was blocking their controller, and the recorder that now learns from it

The operator said the game was taking too long, that they would play it themselves, and asked for the system to learn
from it. This round is that: their controller was not being seen by gBox, and that is now fixed at the capture layer.

### The controller is on XInput slot 1, and gBox watches slot 0

`gbox/padstate.py:watch_xinput` mirrors **XInput pad 0 only**, and `DolphinWinAdapter` binds `XInput/<vpad slot>` into
`GCPadNew.ini`. On this PC there are two XInput devices:

| slot | what it reports |
|---|---|
| 0 | idle: `buttons 0x0`, all sticks exactly 0, a live packet counter |
| 1 | **the operator's controller**: live packets and real analog values (`lx -126, ly 574, rx -369, ry 351`) |

Slot 0 is an **idle virtual pad left behind by an earlier session** — the same thing that made round 3's
`verify_pad_binding` claim a pad was bound when the operator's own controller was the device that mattered. So
`watch_xinput` (and therefore the controller glyph and the built-in gameplay memory) never saw the operator play: the
game may move, gBox sees nothing.

`XBOX Synthetic Gamepad Bus` (`SWD\SYNTHETICGAMEPADENUM\SYNTHETICGAMEPAD0`) is also reported by Windows in **Error**
state, which is the likely source of the phantom slot-0 device. Not touched: it needs elevation and a device change
mid-session is not worth the risk while the operator is playing.

### What was done

1. **A slot-agnostic demonstration recorder** (`D:\gBox\pso-ds\pso_demo_rec.py`, running as a background job) writes
   JSONL every 0.2 s with: **all four XInput slots** (buttons + both sticks + both triggers, with a `changed` flag on
   the slot whose state moved), the control plane's pad snapshot, and the game state from RAM — `phase`, `floor`,
   `episode`, `travelling`, and the player's `x/y/z`, `room`, `hp`, `hp_max`, `action`, `hit`. Once a second it adds
   the **entity list** (class census plus every `TObjCityDoor_*` with its world position), so a recorded run is also a
   map of the area and a route the walker can replay.
   Output: `D:\gBox\pso-ds\demos\dbc5ff9be4ca416c-c91e5802a9844b37.jsonl`.
2. A per-slot pad logger (`D:\gBox\pso-ds\pso_padwatch.py`) runs alongside it and writes `pads.jsonl`, one line per
   observed change with its slot, so the slot question is settled by evidence rather than by a guess.
3. The Dolphin binding was briefly repointed to `XInput/1` and then **reverted**: the live state shows the operator's
   play reaching the game (Forest 1, HP 20/40 then back to 40/40, room 11 -> 16, position moving), so the binding
   works and changing it mid-session risked breaking a working pad. The backup is `GCPadNew.ini.bak-slot0`.

### Where the game is now

The operator has already taken the save into the field — `FLOOR 1` (Forest 1), room 11/16, entities
`TObjContainerItem` x4 and `TObjLazerFenceNorm` x1 in the recorded samples. **That is P1's field arrival, reached by
the operator's own play**, which is the thing the guide's accept test asks for and what my scripted walk had not yet
managed.

### Next

1. Fix `padstate.watch_xinput` to auto-detect the active slot (and/or let the adapter pick the operator's pad for
   operator play), so the glyph, the built-in gameplay memory and any learner see the same input this recorder does.
2. Turn a recorded demo into a **route fixture** for `gbox.pso_move` (waypoints per area) with a test on the captured
   JSONL, so the operator's walk is replayed rather than re-derived.
3. Keep the recorder running for the whole session; the JSONL is the training set.

## Round 7 (2026-11-10) — the operator's chord: Select + L1 + R1 randomizes the character's equipment

The operator asked for a chord they can hit *while playing*: **Select + L1 + R1** randomizes the build and equipment of
the character. Three pieces were needed and all three are in.

### 1. The pad watcher followed the wrong pad

`padstate.watch_xinput` mirrored **XInput slot 0 only**. On this PC slot 0 is a leftover virtual pad that sits at
exactly zero forever, while the operator's real controller reports live packets and analog values on **slot 1** — so
their input never reached the control plane, and no chord of theirs could ever fire. `operator_slot()` now picks the
first slot that reports a button or a moved stick (falling back to 0), and `watch_xinput` uses it. This also explains
round 3's false `verify_pad_binding` result and why the controller glyph and the built-in gameplay memory were blank
while the operator was playing.

### 2. A per-session, three-key chord

`padstate` had one hardcoded chord (`Select + A`, and the edge test looked for literally `b`). It now has
`CHORD_BY_SESSION` / `chord_keys(sid)` / `set_chord(sid, keys)`, and `chord_step` fires when the chord is completed by
a *new* press of any non-Select key. Verified: `{select,l,r}` fires when the third key lands, does **not** fire on
L1+R1 alone, and does **not** repeat while the chord is held.

### 3. The action: `gbox/pso_quick.py` (+7 tests)

The class-scoped randomizer (`pso_modes`) needs `character_class`, which the GameCube build does not expose
(`pso_controls` returns `character_class: None` for GC), so a chord wired to it would need a hardcoded class or fail.
`pso_quick.randomize_equipment` instead takes random **rares** from the owned-disc catalog (weapons, armour, shields,
units) and gives + equips them one at a time, reporting what the game accepted and what it refused — a class the
character cannot use shows up as a refusal, not as a crash. The catalog comes from the server and falls back to the
cached `gbox-data/pso/items-gc-v3.json`. `chord_action()` never raises into the watcher.

Wiring: for a PSO session, `tools.py` calls `padstate.set_chord(sid, {"select","l","r"})` and points
`padstate.CHORD[sid]` at `pso_quick.chord_action`; every other title keeps Select + A for autoplay.

Input tests still pass (78 passed, 1 skipped, including `test_pso_controls`, `test_gamepads`, `test_padmap`,
`test_autoplay_input_takeover`).

### Note on the session

Control was handed back to the bot. The recorder (`D:\gBox\pso-ds\pso_demo_rec.py`) is still running and captures
all four XInput slots plus the RAM state, so operator play from here on is still training data.

## Round 8 (2026-11-10) — the cold-boot walk as a script, and the pad binding that stops it running

### `gbox/pso_boot_walk.py` (+7 tests)

The guide's P1 turned into a module: a deterministic press script from the title to Pioneer 2, with checkpoints taken
only where RAM can actually prove something (round 3 established that `0x80516303` is a coarse mode, not a screen id,
so a walk must not pretend the byte names a menu):

| step | keys | checkpoint |
|---|---|---|
| `press_start` | START | the mode leaves the attract family, or a player appears |
| `offline_game` | `ddown`, A | none (the cursor move is not observable) |
| `single_mode` | A | the mode is no longer SELECT GAME MODE (9) |
| `slot_a` | A | ditto |
| `accept_new` | `dup`, A | none (answers "create a new Character?" when it appears) |
| `episode_one` | A | **FLOOR 0 with a player** = Pioneer 2 |

`walk()` stops the moment a player exists in Pioneer 2, reports every step's state, and never retries a step that did
nothing -- it names it. `reach_title()` handles the one honest exception: the attract movie and the PRESS START title
both read mode `0`, and START is the right button in both, so it presses START up to a bound to skip the movie and says
how many presses it took. `in_field()` is the accept-evidence reader (floor / in_town / in_field / entities).

Tests model the boot screen by screen, including: a title that does not advance (one press, then a named failure), an
A that does nothing on SELECT GAME MODE, the attract needing several START presses, and starting the walk after the
title press.

### The live run failed, and the reason is the pad binding again

Cold launch on the restarted worker: session `68d6f3754e7e495a-904a3dfc34324503`. `reach_title` worked -- one START
press took the mode `0 -> 1`, the title menu. Then `walk()` ran its five steps and **the mode never left `1`**: the
presses were not reaching the game.

`GCPadNew.ini` again binds `XInput/0/Gamepad`, and the slots are the same as before the restart:

```
slot 0  buttons 0x0  lx 0      ly 0        <- the phantom virtual pad, exactly zero forever
slot 1  buttons 0x0  lx -160   ly 1387     <- the operator's real controller
```

So `_setup_vpad` did not put a working pad in slot 0 this launch either, and Dolphin is reading the phantom. This is
now the single blocker for P1's live accept test (and for the operator's own chord to be useful): **Dolphin must be
bound to the slot that reports activity, not to slot 0.** Two candidate fixes for next round:

1. `DolphinWinAdapter._setup_vpad` should bind `XInput/<slot of the pad that reports activity>` when its own virtual
   pad cannot take a slot, instead of writing a slot the game will not see.
2. Or free slot 0 first: the phantom is a leftover ViGEm pad. `XBOX Synthetic Gamepad Bus` in the device list is in
   **Error** state and is the likely provider; disabling it (needs elevation) should let the real pad renumber to 0
   and make both the game and `watch_xinput` work without further changes.

Nothing was pressed on the operator's behalf after they handed control back beyond this cold-boot attempt.

## Round 9 (2026-11-10) — the pad binding fixed, and a cold boot from the disc to Pioneer 2 by gBox's own presses

Round 8's run died because Dolphin read `XInput/0`, a phantom virtual pad that reports exactly zeros forever, while the
operator's controller was on slot 1 and gBox's own virtual pad did not exist. This round fixed the binding and then
**cold-booted the disc into Pioneer 2 with gBox's presses**, asserting every step from RAM.

### What the probe showed

A virtual pad **can** be created and Windows sees it: `VGamepad()` reported slot 2 and the sentinel trigger appeared at
slot 2 while `0` stayed all-zero and `1` showed the operator's resting controller (`lx -160, ly 1387`). So the failure
was never ViGEm -- it was the launch choosing a slot nothing reports on.

### `gbox/pad_bind.py` (+5 tests) and the adapter

The fallback path (no virtual pad) now binds the pad that **actually reports** instead of trusting `XInput/0`:

* `alive(state)` decides what "a real device" is by **any non-zero field**, not by XInput's deadzone. The operator's
  stick drifts below that deadzone, and a phantom is *exactly* zero in every field, including forever.
* `choose_slot(pads, created=...)` prefers gBox's own pad when it exists (it may be idle and about to be used), else the
  lowest live slot, else None (leave the INI untouched).
* `bind_device` / `bind_note` rewrite GCPad1's `Device` line once and record why in a comment.

`DolphinWinAdapter._argv` calls it on the no-vpad path, so a machine with a phantom in slot 0 gets a working pad.

### The relay: your pad reaches the game through gBox's pad

The two configurations are mutually exclusive -- Dolphin reads one device. With the **virtual pad** bound the bot can
press (the keyboard path cannot: `win_send_keys` returns `sent: 0` because Windows refuses `SetForegroundWindow` from a
background process, which is why that path silently drops everything). So the operator's own controller is now
**relayed**: `padstate.watch_xinput` already diffs their pad every 1/30 s, and with `padstate.RELAY[sid]` set (the worker
sets it when the adapter has a virtual pad) each change is also posted to the session's input queue, which the worker
sends to that pad. Their presses reach the game *and* the chord still fires from the physical pad directly.

### The cold boot, live

Session `066193032ad04374-b89e4b8bbbe64952`, `GCPadNew.ini` = `Options/Always Connected = True` +
`Device = XInput/0/Gamepad` (gBox's pad, slot 0 -- the phantom was freed by the worker restarts):

```
mode 0 (attract) -> one START press -> mode 1 (title menu)        presses land
walk: offline_game, single_mode, slot_a  -> mode walked 1/0/1
SELECT CHARACTER: BQF  Type HUmar  ID ORAN  (the character from round 4, still on the card)
A on the row -> "Wrote to Memory Card A" -> Pioneer 2, Principal Tyrell
```

RAM at the end: `TObjPlayer hp 40/40 at (0, -2015) room 41`, `FLOOR 0` (Pioneer 2), `episode 1`, **29 entities**
(`in_field` = `{in_town: true, player: {...}, entities: 29}`).

That is P1's boot-to-town leg done end to end by gBox's presses: attract skipped, title menu, offline branch, character
select with the saved character, memory-card write, Pioneer 2. It is **not** P1's accept test yet -- that needs Forest 1
and both players, three cold launches.

### Still open

* The walk's step list still assumes the *creation* branch (`accept_new` presses `dup`+A). With a character on the card
  the correct step is a bare A on the row; the module should check the card (a `TObjPlayer`-less SELECT CHARACTER with a
  saved slot cannot be told from RAM yet) or simply try A and fall back to create.
* Forest 1: from Pioneer 2 the route is the Hunter's Guild door (`TObjCityDoor_Guild` at `185, 173` room 10, read from
  the entity list) and then the teleporter; the walker needs to get through the room transitions.

## Round 10 (2026-11-10) — the town leg is blocked by the analog stick, and the dialogue trap that hid it

The plan was Pioneer 2 -> the Hunter's Guild -> Forest 1. Two things stopped it, both found by measurement.

### 1. The analog stick does not reach PSO, even with gBox's own pad bound

Buttons reach the game (A advances dialogue, START opens the menu). Sticks do not: holding ``up``/``down``/``left``/
``right`` for a second each left the player at ``(0.0, -2015.0) room 41`` every time, and the C-stick did not turn the
camera either. The decisive check was reading XInput **while the worker was holding the stick**: the slot that gBox's
pad occupies showed no change at all (`during hold, distinct states: 1`). So the stick never reaches the pad that
Dolphin reads -- this is not a game-state problem and not a deadzone problem.

That also means round 5's "keyboard moves him" result was the *keyboard* path all along, and that path is now unusable
(`win_send_keys` returns `sent: 0` because Windows refuses `SetForegroundWindow` from a background process). **Movement
is therefore currently impossible for the bot**, which blocks the town-to-field leg, P3's traversal, and anything else
that needs walking. It is the top item for the next round and it is a vpad/stick-write bug, not a RE question.

Candidate causes to check, in order: whether ``DolphinWinAdapter.send_input`` is even taking the vpad branch (a press
that advances dialogue proves *some* path works, and XInput showing nothing during a stick hold suggests that path is
not the vpad); whether ``VGamepad._render`` is called at all for a stick-only batch (``apply`` only renders at the end
when ``rows`` is non-empty, and ``up`` is in ``KEYS``); and whether the ini's ``Main Stick/*`` lines survived the
fallback INI rewrite.

### 2. The Principal dialogue loops, which made the stick look like it was working

Pressing A repeatedly at the end of Principal Tyrell's conversation **restarts** it: after the last line the game
returns to free movement, and the next A re-talks to him from where the character stands. So a loop of A presses keeps
the game in dialogue forever, and movement tests run during it are meaningless -- the first few stick tests in this
round were run inside the dialogue and could not have failed for the right reason.

The lesson is the same shape as the walk's: a press with no observable effect must not be repeated. The boot script's
step list is fine (it presses A once per step and lets the ``in_town`` checkpoint judge), but any interactive step
outside it needs the same discipline.

### What was verified this round

* Buttons reach PSO through the current binding (A advances dialogue, START opens the in-game menu).
* The stick does not, measured at the XInput layer rather than inferred from the game.
* `gbox.pso_entities` still reads all 29 Pioneer 2 objects live, including `TObjCityDoor_Guild` at (185, 173) room 10
  and `TObjCityDoor_Warp` at (254, 25) room 10 -- the route the town leg needs is already available.
* An attempt to add a `select_character` helper was reverted: RAM cannot distinguish "saved character" from "empty
  slot" at SELECT CHARACTER (both read ``mode 1`` with no player), so it had no honest verification signal, and the
  existing step list already covers both branches by pressing A and then answering the create prompt.

## 7. Next

1. **Movement.** Fix the virtual pad's analog stick: it is written into pad_win but never appears on the pad (XInput
   shows no change during a hold), so the bot cannot walk at all. This blocks the town leg, P3 and every traversal
   accept test. Buttons are fine, so the fix is in the stick path -- send_input taking the vpad branch, _render
   running for a stick-only batch, or the INI's Main Stick/* lines.
2. Then Pioneer 2 -> the Hunter's Guild door (185,173 room 10) -> the teleporter -> Forest 1, with gbox.pso_move
   closing the loop on the player's RAM position.
3. Then the three cold launches with both players, then P6a's in-game proof, P6b, P7a and the demo -> route fixture.
