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

## Round 10 (2026-11-10) — the town leg did not happen: a looping conversation and an unproven movement failure

The plan was Pioneer 2 -> the Hunter's Guild -> Forest 1. It did not get there, and the more useful result is a
correction: an earlier draft of this round claimed "the analog stick does not reach PSO". **That is not proven.**

### What happened

After the cold boot in round 9 the character stands in front of Principal Tyrell, whose tutorial conversation is many
pages long. Then:

1. Pressing A repeatedly advances it, but **every A pressed after the last line restarts the conversation** -- the
   character is still standing in front of him, so A talks again. A loop of A presses therefore never exits, and the
   game stays in dialogue, where movement is locked.
2. All of this round's movement tests (stick up/down/left/right for a second each, keyboard `up`, D-pad `down`) ran
   during that dialogue and reported the player at `(0.0, -2015.0) room 41` every time. **A locked game cannot move, so
   none of those results says anything about the stick.**
3. Five `b` presses and one more walk changed nothing either, so B does not close this conversation.

The frames say it plainly: `p1v-00-state.jpg`, `p1w-01-cdown.jpg`, `p1x-keyboard.jpg` all show the same speech bubble,
"Go talk to my secretary. Irene will help you." -- the last line of the conversation, still up.

### What *is* proven, and what is not

| claim | status |
|---|---|
| Buttons reach PSO through the current binding (A advances dialogue, START opens the in-game menu) | **proven** |
| XInput shows no change in any slot while the worker holds a stick through `/input` | **proven** (12 samples over 1.5 s, one distinct state) |
| Therefore the worker's stick write never reaches a pad | **not proven** -- the pad it would write to is the one whose buttons do work, so either the vpad is not the path in use, or the stick branch is not reached |
| The analog stick does not work in PSO | **not proven** -- every test of it was run with movement locked |
| Movement works at all right now | **unknown** -- it has not been tested outside the dialogue |

### What this means for the next round

The order of work changes. Fix the **dialogue trap** first, because until the character is free every movement result is
noise:

1. Find a RAM signal for "a conversation is open" (candidates: `control_mode` at actor+`0x324`, `action_state` at
   `+0x326`, `hit_records` at `+0xA8` -- sample them during the conversation and after it) so a driver can know when to
   stop pressing A. Without it, any interactive step is a guess.
2. Then measure movement once, properly: hold a direction for two seconds with the character free and read the
   position. Only then call the stick broken or working.
3. Then the town leg: `TObjCityDoor_Guild` at (185, 173) room 10, then `TObjCityDoor_Warp` at (254, 25), then Forest 1.

`gbox.pso_entities` still reads all 29 Pioneer 2 objects live, so the route itself is already available; what is missing
is a way to know the party is free to walk.

### Method note (the same lesson twice)

This is round 3's mistake in a different place: round 3 nearly shipped a byte as a "screen id" because it changed when
the screen changed, and this round nearly shipped "the stick is broken" because the character did not move while the
game was in a conversation. Both were measurements of the *wrong state*. A negative result needs the same evidence bar as
a positive one, and "nothing happened" is the easiest result to misread.

## Round 11 (2026-11-10) — the conversation signal found, and the relay that was starving the bot

### The signal round 10 said was missing: `mode 5` / `17` is a conversation

Watching `0x80516303` while Principal Tyrell's tutorial ran gives the missing "a conversation is open" signal:

| mode | meaning |
|---|---|
| **5** | a conversation page is up |
| **17** | a conversation page just advanced (it alternates with 5 as A is pressed) |
| 0 / 4 | the title / attract |
| 1 | a menu (main menu **and** SELECT CHARACTER) |
| 9 | SELECT GAME MODE |

The actor fields do **not** move during the conversation (`control_mode` 1, `action_state` 1, `hit_records` 1 the whole
time), so the boot-mode byte is the only usable signal -- which is why round 10's movement tests were meaningless: the
mode was 5/17 throughout and movement is locked there. A driver can now press A *while* the mode is 5/17 and stop the
moment it is not, instead of guessing how many pages a conversation has.

### The bug that probably caused the input stall: the relay starved the bot

Round 10 ended with the game ignoring every press (A and START both did nothing while the render and RAM stayed
healthy) -- the third appearance of this stall. The likely cause is the relay added in round 9: it forwarded *every*
change of the operator's physical pad to the session's input queue, and their pad's sticks **drift** (`lx -160,
ly 1387` at rest, changing packet by packet). A continuous flood of operator-sourced input makes `pad_takeover` treat
the operator as playing, and a playing bot yields the pad -- so gBox's own presses wait forever.

`padstate` now relays **buttons always, sticks only past a real deflection** (`RELAY_STICK = 0.3`, the same threshold
the watcher uses for `moved`). Whether that fully explains the stall is **not proven** -- a fresh session after the
change accepted input for the whole boot sequence, but the previous session had also just been restarted and started
healthy. The falsifiable test for the next round: drive ~100 presses in one session and check that input still lands.

### The boot sequence is state-dependent, and the script is not

With input working, `gbox.pso_boot_walk.walk` ran its six steps and ended **without a player**, with the mode
oscillating `1 -> 0 -> 1 -> 1 -> 0 -> 1`. The same `ddown`+A at the main menu produced SELECT GAME MODE (mode 9) in
round 4 and the title (mode 0) here. The menu remembers its cursor, so the same key sequence lands on a different item
depending on history -- a fixed press list cannot be right for both.

So the walk needs to *see* each screen before choosing the next press. The mode byte alone cannot do that (1 is two
different screens). What the round did establish is what to build: a frame-per-step driver that captures the screen at
each step (the round's frames are 110-123 KB JPEGs and readable), labels it, and records the press that moved it --
turning the walk into an evidence-backed sequence instead of my memory of round 4.

### Not done

Pioneer 2 -> Forest 1 did not happen in this round either. The pieces are all present (the route through
`TObjCityDoor_Guild` at 185,173, the walker, the conversation signal); what is missing is a boot sequence that copes
with a remembered cursor.

## Round 12 (2026-11-10) — the virtual pad was flaky, not broken; and two more tests that measured the wrong thing

### The real defect this round: `_setup_vpad` sometimes returns None

A launch right after a `stop_game` produced `GCPadNew.ini` with **no** `Options/Always Connected` and
`Device = XInput/1/Gamepad` -- the no-vpad fallback. In that session gBox cannot press at all: its only other path is
`win_send_keys`, which Windows refuses from a background process. ViGEm releases the previous session's pad
asynchronously, so the next launch's pad creation fails.

`DolphinWinAdapter._setup_vpad` now retries pad creation **three times** with a short backoff before falling back, and
says how many attempts it made. Verified: the next launch wrote `Options/Always Connected = True` +
`Device = XInput/0/Gamepad`, and gBox's presses moved the title menu's cursor.

### The stick is not broken, and two of this round's "tests" were invalid

Tracing the write end to end settled it:

* `vpad_win` calls `pad.left_joystick(x_value=_clamp(lx), y_value=_clamp(ly))` with **ints** +/-32767. `vgamepad`
  rejects floats (`TypeError: 'float' object cannot be interpreted as an integer`) and accepts ints, so the call is
  right -- my first hypothesis (wrong units) was wrong.
* A pad written that way **does** show up in XInput: `ints +/-32767 -> {lx: 32767, ly: 32767}`. So a stick write
  reaches the OS.

Two tests from earlier this turn were therefore measuring the wrong thing:

1. **The title menu responds to the D-pad, not the stick.** `ddown` moved the highlight from ONLINE GAME to OFFLINE
   GAME; a 1.5 s hold of the *stick* `down` moved nothing. That is menu behaviour, not a stick failure.
2. **The XInput probe that "proved" the stick never reaches a pad** ran in the session whose `_setup_vpad` had returned
   None -- there was no virtual pad to write to. It proved the *fallback* session has no pad, nothing more.

So the analog stick's behaviour in the field is still **unmeasured**. The one clean way to measure it is in-game with
the character free, which is exactly where every attempt has failed because the game spends that time in Principal
Tyrell's conversation.

### The boot-mode byte is coarser than the lane doc said

Newly observed values, all from this round's frames and reads:

| mode | screens seen with it |
|---|---|
| 0 | the attract, **the title main menu** (after a cursor move), **SELECT CHARACTER** |
| 1 | the title main menu (on entry), the SELECT CHARACTER confirm prompt |
| 4 | the title with the menu closed |
| 5 / 17 | a conversation |
| 9 | SELECT GAME MODE |

So `mode` cannot name a screen. Round 11's "5/17 is a conversation" still holds (nothing else has produced those
values), but the walk cannot be driven by the byte alone.

### What did advance

The character-select path is now known exactly, from frames: at SELECT CHARACTER press **A** (opens
`Confirm / Cancel / Recreate`), then **A** again (Confirm) -- the character loads from the card and the game enters
Pioneer 2. That is what round 9's cold boot did by hand, and it is three presses with two visible confirmations, so it
can be scripted with a frame check at each step.

## Round 13 (2026-11-10) — the boot to Pioneer 2 is now six verified presses, and the intro scene is the wall

### The path, press by press, each one checked against a frame

Every step below was driven by gBox's own virtual pad and confirmed by a captured frame and a RAM read:

| # | press | screen it reached |
|---|---|---|
| 1 | START (at PRESS START) | the title main menu (mode **1**) |
| 2 | `ddown` + A | **SELECT GAME MODE** (mode **9**) -- the cursor starts on ONLINE GAME |
| 3 | A | **SELECT CHARACTER** (mode 1), BQF / HUmar / ORAN on the card |
| 4 | A | the **Confirm / Cancel / Recreate** prompt, Confirm highlighted |
| 5 | A | **SELECT EPISODE** (mode 1), EPISODE 1 highlighted |
| 6 | A | the warp, then **Pioneer 2**: mode **5**, player at `(0.0, -2015.0)` room 41, 29 entities |

`gbox.pso_boot_walk.BOOT_STEPS` now carries exactly this list (it previously carried my memory of round 4, which had a
`dup` step and no confirm or episode step). Step 2 is the only one with an unambiguous RAM checkpoint -- mode 9 appears
nowhere else -- so it asserts `mode == 9` and the rest are judged by the arrival, because mode 1 is the main menu,
SELECT CHARACTER and SELECT EPISODE alike.

### The wall: the intro scene loops and nothing exits it

In Pioneer 2 the game is in Principal Tyrell's episode-1 intro, mode **5** continuously. Measured, once each, with the
mode watched after every action:

| action | result |
|---|---|
| A, 50 presses at 1 s | cycles four lines forever (below), mode stays 5 |
| B, X, Y | mode stays 5 |
| START | consumed by the scene, mode stays 5 |
| wait 4 s with no input | mode stays 5 |
| stick `down` 1.5 s and 5 s | position unchanged |
| D-pad `ddown`, `dleft`, `dup` 1.5 s | position unchanged |
| stick held **together with** A | position unchanged |

The four lines it cycles through: *"Are you BQF, the Hunter?"*, *"Go talk to my secretary. Irene will help you."*,
*"We have a bad situation... We need to act quickly."*, *"I didn't say anything."* -- so A advances a page, and once the
scene has run out A re-opens it, because the character is standing in front of the Principal.

So **the character cannot be moved while the scene is up, and the scene cannot be left by pressing anything tested**.
That combination is what has defeated every movement measurement since round 10, and it means the field leg needs a way
past this specific scene rather than another movement test.

### Next: get past the scene

Candidates, in order of promise:

1. The scene is scripted per area entry, so it may key off a **flag in the player or area structure** that a write can
   clear (P2b's `pso_ram` map has `room`, `floor`, `episode`; a "first visit" flag is the likely neighbour).
2. The scene may be **cancelled by the talk prompt's own Cancel** path -- the Confirm/Cancel widget seen at character
   select is the same widget family, and the dialog might accept `B` *only on its last page*, which a driver cannot
   detect without a frame check.
3. A **second player** (co-op) would be outside the scene's single-player framing; P1 needs player 2 anyway.

What is *not* on that list: more movement tests in this room. Eight of them have now failed for the same reason, and
none of them measured the stick.

## Round 14 (2026-11-10) — the write path opened, the scene survived it, and `gbox.pso_write` is the keeper

The round set out to end Principal Tyrell's intro scene by moving the player out of talk range. The move worked; the
scene did not care. The lasting result is the write path itself, now a tested module.

### Writes have a door, and it is a job

`POST /api/sessions/{sid}/rpc` with `op=write_memory` is refused:

```
read-only, reset, pause/resume and debug_* ops only; edits go through the write_memory job
```

The job takes `{session_id, address, hex_bytes}`, returns `{verified, via, rollback_hex}` and **is gated on five minutes
without operator input** -- the same admission rule as launching, reset by every pad press. A write issued after a
movement test sits `queued` with `admission_wait.reason = "Waiting for five minutes without operator input."`

Both behaviours are now in `gbox/pso_write.py` (+6 tests): submit, wait out the gate, require `verified`, read the bytes
back, and keep the rollback. Pointers into the live actor: position is three big-endian floats at `actor+0x38`, room is a
`u16` at `actor+0x28`.

### What the writes proved

| experiment | result |
|---|---|
| teleport the player 300 units (`z -2015 -> -1700`) | **succeeded**, `verified: true, via: process memory`; the character stayed there |
| did the scene end? | **no** -- mode stayed 5, the dialogue stayed on Principal Tyrell |
| hold the stick 6 s with an A press in the middle, sampling position every 0.25 s | **no sample moved** -- there is no free window between the four conversation lines |
| write the room id (`41 -> 10`) to force an area reload | acknowledged, then **immediately overwritten** -- the room is derived from the area state, not authoritative |
| `floor_spawn` / `boss_warp` in the PSO tooling | item spawning and a boss teleport, **not** a field warp |

So the scene is not proximity-driven, not cancelable by any input tried, and not in the fields a write can reach. The
four lines it cycles (*"Are you BQF, the Hunter?"*, *"Go talk to my secretary..."*, *"We have a bad situation..."*,
*"I didn't say anything."*) are four separate conversations in the real game, each ending with the character free -- here
A re-opens the next one immediately, and the character never gets control.

### Why this matters beyond the scene

P6a (map writer) and P7a (player-model writer) both need live writes, and both need *verified* writes with a rollback.
`gbox.pso_write` is that, and it encodes the two traps: the RPC refusal and the five-minute gate. Nothing in this round
touched game memory without a recorded rollback.

### Next

1. The scene's state has to be found in the executive/script structures, not in the actor. The mode alternates 5/17 while
   a page advances, so something *does* change per page -- a constancy-window diff across one A press, with the write job
   as the probe, is the way in.
2. Or sidestep it entirely: bring in **player 2**. The scene is single-player framing, P1 needs two players anyway, and a
   second pad plus a second card slot is ordinary co-op setup.

## Round 15 (2026-11-10) — MULTI MODE is the way past the scene, and it needs a second controller

### MULTI MODE is the door P1 has been looking for

`SELECT GAME MODE` offers SINGLE MODE and MULTI MODE. MULTI MODE selects **two characters from a card at once** -- the
frame shows `SLOT A` with the main character list beside a `TEMP CHARACTERS` list -- and prints, plainly:

> **Requires at least 2 Controllers.**

That is the offline co-op mode, it is the two-player criterion P1 has to meet anyway, and it is the one mode whose
character select does **not** start with the single-player story intro that has blocked every field attempt.

### What was wired for it

`DolphinWinAdapter._argv` now gives every PSO launch (`gecko_id` starting `GPO`) a **two-pad** `GCPadNew.ini`, built by
`pso_coop_setup.pad_ini`:

* `[GCPad1]` keeps whatever the launch decided -- `Always Connected = True` with the virtual pad, or the pad that reports
  input when there is no virtual pad;
* `[GCPad2]` is the keyboard device P2 is driven through: `D`/`R`/`M`/`Y` for A/B/X/Y, `SPACE` for Start, `NUMPAD8/2/4/6`
  for the main stick and `NUMPAD7/9/1/3` for the D-pad -- a scheme chosen so P2's keys never collide with P1's.

`tests/test_pso_coop_pads.py` (4 tests) pins the structure: one heading per pad, exactly one `Always Connected` in
GCPad1, the keyboard device and key names in GCPad2, and the builder being pure text.

### Two dead ends, measured rather than assumed

1. **The four addresses that advanced by one per page are tick counters.** `0x805D71A2`, `0x805D7542`, `0x805D75A2` and
   `0x805D772E` read `60 -> 61 -> 62` across three pages, which looked exactly like a page index. Watching them for four
   minutes with no input at all showed them climb `66 -> 68 -> 71 -> ... -> 124`, about **1.2 per second**: they are a
   clock, and the "+1 per page" was the ~1.4 s between page presses. The four write jobs queued against them were never
   admitted (the five-minute gate) and the session was stopped instead of letting them land blind.
2. **`pso_coop` through the HTTP launch route does not set up a buddy card.** `POST /api/games/{gid}/launch` with
   `{"pso_coop": true}` returned a session whose `diag.pso_coop` was `null`, and the written INI had only `[GCPad1]`.
   The flag exists on the launch tool (`pso_coop: bool = False`), so the route is dropping it -- worth a look, but the
   INI change above makes the second controller available without it.

### Not yet verified

Whether MULTI MODE actually opens with the second pad, and whether player 2 spawns in Pioneer 2 free of the intro scene.
That is the first thing the next round does; the INI change needs a fresh launch to take effect, and the live launch this
round still wrote a single-pad INI because the flag was reading `game`, which is not in `_argv`'s scope -- that bug is
fixed (the disc id is computed there already) but not yet observed working.

## Round 16 (2026-11-10) — MULTI MODE needs a device in the console's port 2, not just a second pad

MULTI MODE still refused ("Requires at least 2 Controllers.") with two pads configured and both marked
`Always Connected`. The missing piece is not in the pad bindings at all: **Dolphin's `Dolphin.ini` has no serial-interface
device table**, so the emulated console has nothing plugged into port 2 no matter how many pads are bound.

### `pso_coop_setup.si_devices`

`Dolphin.ini` in the i9-NUC profile had no `[Core]` section and no `SIDevice*` keys at all. `si_devices(ini, count=2)`
now writes `SIDevice0 = 6` and `SIDevice1 = 6` (6 = standard controller), creating `[Core]` if absent, replacing wrong
values, and keeping every other key and section untouched -- Dolphin's file, not ours, so the edit is as small as
possible.

`DolphinWinAdapter._argv` applies it whenever the launch is PSO (`gecko_id` starting `GPO`), next to the two-pad
`GCPadNew.ini`. `tests/test_pso_coop_pads.py` now has 7 tests: the two-pad INI structure, `Always Connected` on **both**
pads, P2's keyboard scheme, and `si_devices` for the empty file, the file with other keys, and the file with a wrong
value.

### Two patching mistakes, both mine, both the same shape

The adapter code has two `_argv` implementations (Linux and Windows) with near-identical text. Twice this round a
`str.replace(old, new, 1)` hit the Linux one first:

* the `si_devices` call landed twice in the Linux block (a duplicated statement) and not at all in the Windows one,
  which is why the first retest still wrote no `SIDevice*` keys;
* an earlier round's two-pad block was in fact applied to **both** adapters, so the Windows one briefly had two copies
  of the same block.

Both are cleaned up by hand now, and the state is verified: `pad_ini(vpad_ini` and `si_devices(current, 2)` appear once
per adapter, `gbox.adapters` imports, and 25 pad-related tests pass. The lesson is mechanical: in this file, anchor
edits on surrounding context, never on a single similar line, and check the occurrence count before and after.

### Not yet observed working

Whether MULTI MODE opens with the SI device table in place. The code is in and unit-tested, but the last live launch
that actually wrote `SIDevice*` has not been run -- the previous retest ran before the wiring bug was fixed. That is the
first thing the next round does, and it is a single launch plus one frame.

Everything else about this round's hypothesis is measured: two pads with `Always Connected`, both devices present, and
the game still refused, so the pad configuration was never the blocker.

## Round 17 (2026-11-10) — MULTI MODE opens, and player 1 is in

The missing piece was exactly what round 16 predicted: Dolphin's serial-interface device table. With
`SIDevice0 = 6` and `SIDevice1 = 6` written at launch (and both pads configured), the game stopped refusing:

```
SELECT GAME MODE      ddown + A   ->  MULTI MODE
                                      "Please select Player 1's character."      <-- opened
A, A                                ->  PLAYER1 marked on BQF
                                      "Please select Player 2's character."      <-- P1 accepted
```

The two frames are `pf0-multi.jpg` (the "Please select Player 1's character" screen with `MAIN CHARACTER` BQF and the
green `TEMP CHARACTERS` list) and `pf1-p2.jpg` (`PLAYER1` stamped over BQF, and the prompt now asking for Player 2).

**This is the first time the two-controller branch has opened**, after three rounds of pad configuration that were all
necessary but not sufficient: `[GCPad2]` (the pad) -> `Options/Always Connected` on it (the *input* connected) ->
`SIDevice1 = 6` (the *console* seeing it). Each layer gave a distinct, observable refusal or silence.

### What is in the module

`gbox.pso_boot_walk.MULTI_STEPS` now carries the verified five-press path to "select Player 1", with the same rule as the
single-player list: only `offline_game` has an unambiguous checkpoint (`mode == 9`), and the rest are judged by what the
screen shows. One test pins the shape, including the single `ddown` that moves SINGLE MODE -> MULTI MODE.

### Where the game is now, and what it needs

The session is parked on **"Please select Player 2's character."** with all three `TEMP CHARACTERS` slots empty. PSO's
offline multiplayer uses *temporary* characters for players 2 and up, so P2 cannot borrow BQF from the card: the next
step is the character creator for a temp character, which is the same flow round 4 walked for P1 -- race, class,
appearance, then a name typed on the on-screen keyboard, then the section ID.

That typing is the expensive part and it is why this round stops here rather than mid-creator: round 4 established the
grid technique (clamp the cursor to a known cell with `ddown`x12 + `dleft`x20, then walk; a letter's column is its
alphabet index + 2) and got the name **BQF** when DSH was intended, so the mapping needs one careful check before it is
used for a character that has to be identified later.

### Budget note

This round spent most of its steps on the launch-gate cycle: every launch needs five minutes without operator input, and
that clock is reset by the very presses a launch is being tested with. Each verify-a-launch round therefore costs about
ten minutes of wall clock for two or three frames of evidence. Worth knowing when planning the remaining P1 work.

## Round 18 (2026-11-10) — player 2 has a pad, and each player's character select only answers that player

The session is parked inside player 2's character creator with a HUmar appearance randomized. Getting there produced two
findings that will matter for every later co-op step.

### Finding 1: the P2 screen ignores P1's pad

On "Please select Player 2's character." every press of P1's virtual pad was a no-op -- `ddown`, `dright`, `A` (three of
them), all leaving the frame byte-identical. PSO's multiplayer character select answers **each player's own pad**, and P2
is the keyboard device Dolphin calls `GCPad2`. P2's `D` (its A button) opened the prompt immediately:

```
"Please select Player 2's character."
  P2 A  ->  "Want to create a new Character?"  YES / NO      (cursor on NO)
  P2 up, P2 A  ->  CHARACTER SELECT, PLAYER2, HUmar highlighted
  P2 A  ->  the class preview with B CANCEL / A OK
  P2 A  ->  CHARACTER CREATION: FACE HAIR COSTUME SKIN COLOR PROPORTION CHARACTER NAME AUTO OK
  6 x P2 down, P2 A  ->  AUTO:  "B MENU   A CHANGE"
  P2 A  ->  a new appearance
```

### Finding 2: the key names are uppercase or nothing

`win_send_keys` accepted `NUMPAD7` (`sent: 2`) and silently dropped `numpad7` (`sent: 0`). Dolphin's P2 bindings are the
uppercase spellings (`NUMPAD7`, `NUMPAD9`, `SPACE`, `D`, `R`), so a driver that lowercases them does nothing and reports
success-shaped emptiness. That is now `gbox/pso_pad2.py` (+6 tests): the mapping `pso_coop_setup.PAD2_WIN` actually
installs, a `key()` that refuses unknown buttons and lowercase numpad names, and `events`/`chord` builders in the shape
the input API wants.

### Still blocked, and where exactly

The **AUTO** sub-screen offers only "B MENU" and "A CHANGE", and B does not leave it: P2's `R` (B) and `SPACE` (START)
were both accepted by `win_send_keys` (`sent: 2`) and the screen did not change; P2's D-pad down did nothing either.
So the creator cannot yet be finished -- `CHARACTER NAME` (possibly needed) and `OK` (definitely needed) are both on the
menu behind this screen.

Next round's first move is therefore not "press more buttons": it is to check whether P2's B is really `R`, by
sending a *known* B action somewhere the game visibly responds to B (the `YES/NO` prompt takes B as cancel). If `R` is
wrong, the INI's P2 mapping is wrong and that is a one-line fix in `pso_coop_setup.PAD2_WIN`; if `R` is right, the AUTO
screen is simply not leavable by B and the creator must be driven through `FACE`/`HAIR`/... directly instead of via AUTO.

### Method note

Everything this round was done through the keyboard path (`win_send_keys`) with the window restored to the foreground,
and it worked -- unlike P1's pad, P2's pad needs no virtual pad at all. That is worth remembering: for co-op work the two
players are driven by two completely different mechanisms, and the window has to be foreground for P2 only.

## Round 19 (2026-11-10) — two players in Pioneer 2, and the movement answer

This round got past everything P1 was stuck on. Three things happened, in order.

### 1. Player 2's temp character exists: HUmar, name `3P`, GREENILL

Driven entirely through P2's keyboard pad. Two input details that cost a cycle each:

* P2's **B needs a hold** (~0.4 s). A 120 ms tap on the AUTO screen's "B MENU" did nothing; the same key held took the
  creator straight back to its menu. A and the D-pad work as short taps.
* From the name screen's keyboard, two `dright` from the opening cell lands on `3` and two `ddown` lands on `P`, so the
  name came out **3P** -- the same off-by-one shape as round 4's BQF/DSH, and again the name is only cosmetic for a temp
  character, but the offset is now recorded rather than rediscovered.

The path: `SELECT CHARACTER` (P2's pad only) -> "Want to create a new Character?" YES -> class HUmar -> preview -> A ->
`CHARACTER CREATION` (FACE/HAIR/COSTUME/SKIN/PROPORTION/NAME/AUTO/OK) -> AUTO x6 -> A (randomize) -> long B back ->
`CHARACTER NAME` -> typed `3P` -> `OK` -> summary (TYPE HUmar, NAME 3P, SECTION ID GREENILL) -> CONFIRM.

### 2. MULTI MODE loads both players into Pioneer 2 with **no cutscene**

`VERIFY CHARACTER` shows PLAYER1 (BQF) and PLAYER2 (3P) side by side and asks "Are you ready?"; **each player confirms
with their own pad** -- P2's A stamped `OK!` under PLAYER2, P1's A moved the game on to `GAME OPTION` (difficulty NORMAL,
mode NORMAL, EPISODE 1, `START GAME`). After that:

```
mode 1   floor 0   slots 2
p1 (BQF) 229.0, 254.0  room 10        <- the Pioneer 2 lobby, not the Principal's office (room 41)
p2 (3P)  231.0, 267.0  room 10
```

and the frame `pic-lobby.jpg` is **split-screen**: BQF's view on top, 3P's below, both standing in the lobby with their
own HUDs. **The single-player intro scene is simply not on this path** -- the thing ten rounds of presses, writes and
teleports could not get past is bypassed by playing the game in the mode that has two players.

### 3. Movement works -- through the keyboard, never through the virtual pad

Measured with both characters standing free in room 10, positions read from the actor table:

| driver | input | held | result |
|---|---|---|---|
| P1 | virtual pad, `up`/`down`/`left`/`right` (analog stick) | 1.2 s each | **position unchanged** |
| P1 | virtual pad, `dup`/`ddown`/`dleft`/`dright` (D-pad) | 1.2 s each | **position unchanged** |
| P1 | keyboard **arrow keys** (its INI fallback bindings) | 1.4 s each | 229,254 -> **175,254** -> 222,234 |
| P2 | keyboard `NUMPAD8`/`NUMPAD2` (its pad) | 1.4 s each | 231,267 -> **181,274** -> 233,274 |

So the virtual pad's **buttons** reach the game (every menu in this lane was walked with them) but its **analog stick
never does**, while the keyboard bindings both pads carry as fallbacks move the characters perfectly. `win_send_keys`
needs the Dolphin window foreground; that has been true all along and is why P2 could be driven this whole time.

`gbox/pso_pad2.py` now carries `MOVEMENT` / `move_key` / `move_events` for both players (+2 tests), with the measurement
table in a comment so the next reader does not repeat it.

### What this unlocks

* **P1's field leg** is now mechanical: both players can be walked, so Pioneer 2 -> the Hunter's Guild door (185,173
  room 10) -> the teleporter (254,25) -> Forest 1 is `gbox.pso_move` with a keyboard backend.
* The **movement bug** is a real gBox defect worth its own note: `vpad_win` writes the stick, XInput shows it, and the
  game acts on buttons from the same pad but not on its axes -- either Dolphin's XInput axis binding or the pad's axis
  report is wrong, and both players' fallbacks being keyboard is what hid it.

## Round 20 (2026-11-10) — a calibrated keyboard walker, and the first real movement in the lane

### `gbox/pso_kbwalk.py` (+7 tests)

Round 19 proved the keyboard moves characters and the virtual pad's stick never does. This round turned that into a
walker that does not need to be told which way is which:

* **`calibrate`** holds each key briefly, measures the world delta it produced, and returns unit vectors plus a speed.
  On the live game that measured **33.6 world units per second** and axes that are nothing like the key names suggest.
* **`best_keys`** returns the one or two keys that point at the target. Two is not a flourish: on this build `up` is
  world `-x` and `down` is almost `-z`, so a diagonal target needs both or the walk zig-zags and never converges. Keys
  whose directions oppose each other are never combined.
* **`walk_to`** is closed-loop -- every step re-reads the actor's position from RAM, caps the push at half the remaining
  distance so the last steps are short, and stops with a named reason instead of grinding: no key pointing at the target
  (recalibrate), stuck against a wall (after three sidestep attempts), or the player disappeared.

Tests model a world with skewed axes, a wall that blocks movement, a completely dead binding, and the distance-scaled
step length, so the calibration and the stuck handling are exercised without an emulator.

### The live run: 33 units of real movement, then a railing

From the Pioneer 2 lobby, P1 walked from `(240.4, 136.6)` to `(215.0, 164.4)` -- **33 units** toward the Hunter's Guild
door at `(185.0, 173.0)` -- and stopped there with 31 units remaining. The frame (`pj0-guilddoor.jpg`) shows why: the
split screen has BQF out on the plaza, past the lobby's railing, while 3P stays by the teleporter. Both are still in
room 10, so it was an obstacle, not a room change.

A second attempt exposed the weakness worth fixing next: **calibration is poisoned by walls.** Pressed against the
railing, the `left` key produced no movement at all, so it calibrated to `(0, 0, 0)` and the walker reported "no key
points at the target; recalibrate" two steps later. The camera also turns with the character, so a one-time calibration
goes stale as soon as the character changes facing.

### Next, concretely

1. **Calibrate away from walls** (or retry a key that reads zero, and its opposite, and negate), and **recalibrate** when
   a walk stalls -- the camera-relative basis changes when the character turns, so a single calibration cannot hold for a
   long path.
2. **Waypoints instead of a straight line**: the lobby's doors are all in room 10 and the geometry between them is not
   open, so the route needs intermediate points (e.g. out of the plaza opening, then along the terrace, then to the guild
   door).
3. Then the guild door -> the quest counter -> the teleporter -> Forest 1, with both players.

## Round 21 (2026-11-10) — the hardened walker arrived at the guild door, and walked straight through a different one

### `gbox.pso_kbwalk` hardened (+3 tests, 10 total)

Two weaknesses from round 20, both fixed and both tested:

* **Wall-poisoned calibration.** Pressed against the plaza railing, `left` produced no movement and calibrated to
  `(0, 0, 0)`. `calibrate` now measures the **opposite** key when one reads dead and negates it -- the axis is real, only
  that direction is blocked. A test presses against a railing and asserts the axis and its speed come out right.
* **Stale basis.** The camera turns with the character, so a calibration taken a leg ago can point the wrong way.
  `walk_to` now **recalibrates** after two consecutive no-movement steps, before it gives up (two recalibrations max),
  and still sidesteps once between attempts.
* **`walk_path`** walks a list of waypoints, recalibrating between legs -- the lobby is not an open field, so a route is a
  list of points rather than one straight line.

### Live: it arrived

```
start (208.6, 124.8)   target (185.0, 173.0)   [TObjCityDoor_Guild, read from the live entity table]
cal: up (-0.65,-0.76) 34.3 u/s    down (0.66,0.75) 32.2    left (-0.83,0.56) 33.6    right (0.58,-0.81) 33.3
walk: True arrived  end (180.8, 166.8)  steps 12
```

Twelve steps, 30 units, and the walker reported arrival within its 8-unit tolerance -- the first time in this lane that a
character has been steered to a named object by a closed loop reading its own RAM position.

### Then it walked through the wrong door, which is itself the finding

Closing the last 8 units sent P1 through a doorway: **the room changed from 10 to 20 with no button press**, and he came
out in the Pioneer 2 plaza among NPCs (`pk1-room20.jpg`) while P2 stayed in the lobby (`room 10`, the bottom half of the
split screen).

Two consequences for the route:

1. **Room transitions are triggered by walking into a door**, not by pressing A, so a walker must *expect* the room id to
   change underneath it and stop treating the current coordinates as valid.
2. **Entity coordinates are per-room.** The guild door's `(185, 173)` is a room-10 coordinate; after the transition the
   character was at `(101.9, 118.8)` in room 20 and those numbers mean nothing there. A route has to be re-read after
   every transition -- which is exactly what `walk_path`'s per-leg recalibration does for the axes, and what it does not
   yet do for the geometry.

### State

Co-op session live. P1 (BQF) in **room 20**, the Pioneer 2 plaza, at `(101.9, 118.8)`; P2 (3P) in **room 10** by the
teleporter at `(233.8, 274.5)`. Both healthy, no cutscene, movement working through the keyboard.

### Next

1. Bring P1 back through the door into room 10 (the transition works both ways) and keep the party together -- PSO co-op
   expects both players in the same room for area changes.
2. Give `walk_path` a **room-aware** wrapper: re-read the door list from the entity table after every transition and stall
   the route if the room is not the one the waypoint belongs to.
3. Then the guild counter (talk to the receptionist), the quest, and the teleporter to Forest 1.

## Round 22 (2026-11-10) — Pioneer 2's rooms share one world, the doors map to rooms, and the route can now say where it is

### The finding that changes how routes are built

P1 was in room 20 (the plaza). Walking him back to **`(185, 173)`** -- the same coordinate that had taken him *out* of
room 10 -- put him **back in room 10**:

```
start (101.9, 118.8) room 20
walk to (185.0, 173.0) -> arrived (183.3, 175.3)  room 10
```

So Pioneer 2's sub-rooms **share one world space** and a doorway is a position, not a special exit object: the same
coordinates work in both directions. That removes a whole class of "how do I get out of here" work -- a route is
coordinates plus the room they belong to.

### The doors, walked rather than guessed

| door entity | coordinate | room it leads to |
|---|---|---|
| `TObjCityDoor_Guild` | (185, 173) | **20** -- the plaza (NPCs: cloakroom, connoisseur, soldiers) |
| `TObjCityDoor_Warp` | (254, 25) | **40** -- **the teleporter room** (frame `pl3-room40.jpg`: the ringed pad is there) |

and room 41 is the Principal's office (Expert/Governor/Secretary NPCs), room 30 the shop floor (merchants), room 10 the
lobby where both players spawn.

P1 reached the teleporter room by closed-loop walking (three legs, each recalibrating), which is the first multi-leg
route the walker has run live.

### `walk_path` is now room-aware (+2 tests, 12 total)

* it records `room_before` / `room_after` per leg and marks a change as `transition` -- a door walked through is
  **not** a stall, and round 21's failure mode (a route that keeps walking in the new room as if the old coordinates
  still applied) is now visible in the report;
* `expect_room` makes a route refuse to start in a room it was not written for, because entity coordinates are per-room.

### What did not happen

The teleporter pad **did not open a destination menu** from any of four positions inside room 40 (`(300,25)`,
`(257,-40)`, `(210,25)`, `(257,90)`), and mode stayed in the town family throughout. So either the pad needs to be stepped
on more precisely than an 8-unit tolerance allows, or multiplayer's teleporter requires both players present -- P2 was
still in the lobby the whole time.

P1's accept test therefore remains open, but the *navigation* problem is now solved and instrumented; what is left is
finding the pad's trigger and getting the party together.

## Round 23 (2026-11-10) — the city mapped, the teleporter still silent

### A research doc instead of another guess

`docs/research/pso-gc-pioneer2-rooms.md` now records what the city's room ids are, measured on the live disc rather than
inferred:

| room | what |
|---|---|
| 10 | the lobby -- both co-op players spawn here, the four `TObjCityDoor_*` entities, the teleporter pedestal |
| 20 | the plaza -- nine NPCs (cloakroom, connoisseur, fat/macho/tall/dwarf/old civilians, two soldiers) |
| 30 | the shop floor -- five merchant NPCs |
| 40 | a large interior with the round teleporter structure **and** the hospital (two `TObjNpcNurseBase`) |
| 41 | the Principal's office -- Expert x2, Governor, Secretary; where the single-player intro plays |

The area table from the DOL names them `city00`, `lobby`, `forest01`, ... and `FLOOR_LAYOUTS` pairs episode 1 with floors
0, 1, 2 -- so **floor 0 is the city and floor 1 is Forest 1**, and `pso_ram.FLOOR` answers "am I in the field yet?" in one
read.

The important entry in that doc is the shared-world evidence: walking to `(185,173)` from room 10 gives room 20, and
walking to the *same* coordinate from room 20 gives room 10. A doorway is a position, not an exit object.

### The teleporter did not answer

Nine positions in room 40 -- `(300,25)`, `(257,-40)`, `(210,25)`, `(257,90)`, `(229,10)`, `(229,-10)`, `(255,0)`,
`(200,0)`, and `(252,-3)` with a 2.5-unit tolerance -- plus an `A` press on arrival. No destination menu, and the mode
byte stayed in the town family throughout. The walker could not even reach `(229, 0)`; it stalled at `(252,-2.7)`, which
says the pad's centre is not walkable and the interaction is from its rim.

So the honest state is: the pad's trigger is unknown, and one specific hypothesis remains untested -- **both players on the
pad** (P2 was in room 10 the whole time). That is the first thing to test, and it is cheap.

### Nightmare avoided

The temptation here was to use `pso_gc_extras`' `boss_warp` to drop the character into a field area and call P1 done. It
would have worked and it would have been a lie: P1's acceptance is *"boot to the field by real presses, no warp"*, and a
memory-driven area change is exactly what the guide excludes. The field leg stays open until a walk-and-menu route works.

## Round 24 (2026-11-10) — the pad is inert even underfoot, and probing replaces guessing

### Two hypotheses tested, both negative

1. **"The teleporter needs a precise approach."** P1 walked onto the pad's **centre** -- `(229.9, 0.7)` with a 3-unit
   tolerance, after approaching from the south as well as the east -- and nothing happened: mode stayed in the town family,
   no destination list, no transition. So it is not a footstep trigger and not a rim-only interaction; A had already been
   tried on the rim.
2. **"Both players on the pad."** Not testable yet: P2's route was attempted but the walker is not reliable enough over
   250+ units. Three legs took P2 from `(206.4, 369.5)` to `(204.7, 167.9)`, then to `(132.2, 152.1)` -- *away* from the
   target -- and finally into room 20. Long multi-leg routes across the lobby need waypoints that have been seen to work,
   not a straight line with recalibration.

### `gbox/pso_explore.py` (+4 tests) — probing instead of guessing

Pioneer 2's sub-areas are entered through **archways in the level**, not door objects (only room 10 has
`TObjCityDoor_*`), so the exits have to be *found*. This module does that systematically:

* `grid(centre, spacing, rings)` -- probe points around the character, **nearest first**, so a probe finds close exits
  before far ones.
* `probe(read_pos, hold, room_of, points)` -- walk each point with a bounded walk, record the room it ended in, and **stop
  at the first change**, because continuing would step into a room the caller has not planned for. Returns
  `{ok, start_room, transitions, visited, why}`; finding nothing is a result, not an exception.

The tests model a room whose archway moves the character to another room, and assert that a probe finds it, stops there,
and records every point it visited with its room -- so the next town leg is a measurement, not another guess.

### The honest position on P1

Boot to Pioneer 2 is proven and reproducible (six presses, frame-verified). Two players in the city is proven
(split-screen, both free, no cutscene). Movement is proven (keyboard path, 33 units/s, closed-loop to a named object).
The **city-to-field leg is not**: the teleporter does not respond, and the guild route has not been walked yet.

Given the round count, the next move should be the guild: probe room 20 for its archway with the new tool, take a quest,
and let the quest's own warp carry the party to Forest 1 -- which is still "real presses", so it satisfies P1's
acceptance rather than dodging it.

## Round 25 (2026-11-10) — the camera model was wrong twice, so the walker stopped modelling anything

### A probe that failed usefully

`pso_explore.probe` walked 16 grid points in room 10 looking for the guild's archway. Result: **no exit found**, and the
visit log shows why -- targets were missed by *hundreds* of units (asked for `(71.8, 64.8)`, ended at `(323.9, 189.5)`).
The probe was correct; the walker underneath it was not.

### Why both walker models were wrong

| model | assumption | why it failed |
|---|---|---|
| round 20-24 `walk_to` | each key is a fixed world direction | PSO's camera **follows the character**, so the mapping changes while he moves; calibration is stale within a second |
| round 25 `steer_walk` | left/right **turn** the character | its turn error never converged live (right 1.94, right 1.23, ... then left 1.95, left 3.11, left 2.67 repeated) |

Both are the same mistake in different clothes: a model of a camera that is not fixed.

### `greedy_walk` (+4 tests) -- model nothing

It keeps the **last observed world delta per key**, presses whichever key's most recent delta best points at the target,
then replaces that estimate with what actually happened. A rotating camera is just a change in the estimates, absorbed on
the next press. A blocked key's estimate becomes zero and loses trust automatically.

**Live, first try:** `(157.0, 167.5)` -> `(188.1, 170.1)` for a target of `(185.0, 173.0)`, arriving 4.2 units out in a
handful of steps. That is the most reliable walking this lane has had.

### Negative results this round

* The 16-point probe of room 10 found **no room transition**, so the guild archway is not within ±110 units of
  `(182, 175)` at 55-unit spacing.
* Walking *over* the guild door's coordinates again did **not** change the room: `(183.1, 198.6)` and `(189.4, 234.6)`
  both stayed in room 10, even though the same coordinate produced room 20 in rounds 21-22. The doorway is a volume that
  has to be crossed on a particular line, and standing on the coordinate is not enough.
* The character then reported "stuck: no key moved" twice around `(213, 228)` -- a corner or a wall where all four keys
  fail, which the greedy walker now names instead of grinding.

### State

P1 (BQF) in room 10 at `(217.1, 207.7)`; P2 (3P) in room 20 at the plaza. Co-op session live, both healthy.

### Next

1. The doorway has to be **crossed, not reached**: drive the character *through* the door along the line it was crossed on
   in round 21 (approach from `+z` moving toward `-z`, then keep going for a second after the coordinate).
2. Then the guild reception in room 20, a quest, and the quest's own warp to Forest 1 -- still real presses.
3. `pso_explore.probe` should use `greedy_walk` (it currently takes any `walk_to`; pass the greedy one), otherwise its
   grid results are noise.

## Round 26 (2026-11-10) — the walker crossed a room boundary, and the party is together at the pad

### A whole-city walk, with a door crossed on the way

P2 was brought from `(-19.7, -5.4)` in the **market street (room 20)** all the way to the **lobby teleporter (room 10)**
at `(230.2, 271.1)` -- about 300 units and one room transition -- using nothing but `greedy_walk`:

```
P2 start (-19.7, -5.4) room 20
  leg 1 to door: stuck at (29.2, -19.0) room 20
    push through: stuck at (38.6, 57.1) room 20
  leg 2 to door: stuck at (91.1, 24.0) room 20
    push through: stuck at (162.1, 164.8) room 10     <-- the door was crossed
  leg 1..4 to pad: progressing through the lobby
  leg 5 to pad: arrived at (230.2, 271.1) room 10
```

Two things that had not happened before:

1. **A room transition by walking**, driven by the controller rather than accidentally: the "push through" step keeps
   walking *past* the doorway coordinate when the walk reports stuck, and that is what crossed `(185,173)` from room 20
   into room 10.
2. **A ~300-unit route with obstacles** completed by the greedy walker, which reports `stuck` and is restarted rather
   than grinding. Earlier calibrating walkers could not manage 60 units.

Both players now stand at the same teleporter in room 10: P1 (BQF) at `(227.7, 262.7)`, P2 (3P) at `(236.2, 257.9)`.

### The teleporter still does not answer, and "both players" is now ruled out as the cause

With both players beside/on the pads and `A` pressed on **both** pads, no destination menu appeared and the mode byte
stayed in the town family (`po5-pads.jpg`: both views show the purple portal pedestal, no UI). So:

* the trigger is not proximity (tested at eight positions in room 40 in round 23),
* not `A` on the pad,
* not a precise approach (round 24, 2.5-unit tolerance),
* and not "both players present" -- the hypothesis this round set out to test.

What that leaves: the pad may require the party to be **exactly** on it (a 5-unit tolerance landed beside the raised
platform, not on it, and the walker reports the platform's rim as `stuck`), or the city teleporter is simply not how an
offline multiplayer party reaches the surface and the **Hunter's Guild quest** is the route.

### Method note

`walklib.py` (not in git) now gives both players a uniform `(read_pos, hold)` pair plus `walk()` and `press()`, so
two-player scripts are short: P1 presses go through the virtual pad, P2's through the keyboard, and movement for both goes
through `win_send_keys` with the window foreground. The `stuck -> keep walking past the target` idiom is what makes doors
work, and it should be folded into `greedy_walk` as an option rather than living in every driver script.

## Round 27 (2026-11-10) — doorway crossing is now a walker feature, and the lobby pedestal is decorative

### `greedy_walk` grew the two door behaviours (+3 tests, 19 walker tests total)

A doorway can fail a walk in two different ways, so there are two options now:

* **`overshoot=<units>`** -- after the walk *arrives* at the target, keep going that far past it along the approach
  direction. Needed when the walk succeeds on the door's coordinate and therefore stops beside the door: round 26 crossed
  `(185,173)` only after being told to keep walking, and round 25 walked *over* the same coordinate twice without
  crossing.
* **`push_through=<bool>`** -- when the walk is *stuck* (no key moves), re-aim `push_distance` past the goal and keep
  going, up to `pushes` times, instead of failing. Needed when the door's collision stops the character short.

Both are tested against a model room whose doorway only moves the character once it is clearly past the coordinate, so
"the walk arrived" and "the character went through" are asserted separately -- they are not the same thing, and that
distinction is exactly what took four rounds to notice.

### The lobby pedestal is not a teleporter

Both players were walked onto the pedestal at `(233,274)` with push-through -- P1 arrived `(234.2, 275.0)`, P2
`(233.2, 273.3)`, both within four units of the centre -- and `A` was pressed on both pads. No menu, mode stayed 1, and
`pp0-pushed.jpg` shows the two of them standing at the pedestal with only the purple diamond above it for company.

So the lobby's big round structure is **decorative**, and the city teleporter (room 40's pad, tested from nine positions in
rounds 23-25) remains the only candidate -- with no destination list in evidence from any approach tried.

### Ruled out so far, and what that leaves

| hypothesis | result |
|---|---|
| proximity to the room-40 pad (8 positions) | no menu |
| `A` on the pad | no menu |
| precise approach (2.5 units) | no menu |
| both players present (at the pad, `A` on both) | no menu |
| the lobby pedestal is the teleporter | it is decorative |

What is left is the **Hunter's Guild quest**: its warp to the surface is driven by a menu, which is "real presses", and it
is the one route PSO itself offers to a party that has unlocked nothing.

### A live failure worth recording

Crossing the guild door *from the lobby* failed three times, each time with the walk stuck in the corner around
`(215-254, 208-254)`: `(254.2, 214.0)`, `(240.7, 254.1)`, `(215.0, 208.1)`. P1 came *from* the market street the other way
in round 26, so the door works in that direction; the lobby side of that corner is a pocket the greedy walker cannot climb
out of without waypoints. The route needs one intermediate point on the lobby side of the door rather than a straight
line from the pad.

## Round 28 (2026-11-10) — the door was never at the coordinate I thought, and the city is one big area

### The crossing point was never `(185,173)`

Round 26's successful room change was logged as "walked toward `(185,173)` and crossed", and rounds 21-27 all assumed the
guild door *was* that coordinate. This round's log shows the crossing happened somewhere else entirely:

```
P1 (203.9, 190.9) room 10
  -> (120.0, 100.0)  stuck at (105.1, 162.8) room 10
  -> (91.0, 24.0)    stuck at (157.9, 102.9) room 20     <-- crossed between those two points
```

The lobby/market boundary is somewhere around **(105-158, 100-163)**, not at the door entity's coordinate. Every attempt
to cross *at* `(185,173)` from the lobby side -- including with `overshoot` and `push_through` -- correctly did nothing,
because there is no door there. That also explains why standing on that coordinate in round 25 changed rooms once by
accident and never again.

### `pso_explore.probe` now defaults to the walker that works

Its `walk_to` default was the calibration-based `pso_kbwalk.walk_to`, which round 25 showed produces noise (16 points,
none reached). The default is now `greedy_walk`, with a test that the probe runs end-to-end through its own default rather
than raising on a mismatched signature.

### The city is one connected area, not a set of rooms

Walking around room 20 after crossing showed:

* the **central dome** with a large red-cross door (the medical centre) and NPCs along the walls (`pq0-street.jpg`);
* an **outdoor terrace** over the city with a railing, reached without any transition (`pq1-guildhall.jpg`).

So "room 20" is a large area containing interiors *and* outdoor walkways, and the `room` id changes only at specific
thresholds. The guild is somewhere in this area -- its marker is `TObjNpcCloakroomBase`, which the entity table places at
`(-267, -24)` in room 20 -- but the straight line from the dome to that point is blocked at around `(102, 100-128)`, which
is a wall, not a walker failure.

### State

Co-op session live. P1 (BQF) in room 20 on the terrace at `(102.2, 105.2)`; P2 (3P) in room 10 at the lobby pad
`(233, 273)`. Both healthy.

### Next

1. Route around the wall: from `(102,105)` the cloakroom at `(-267,-24)` needs a waypoint on whichever axis is open --
   probe with `pso_explore.probe` (now greedy-backed) and let the exits guide the way, rather than walking at the target
   through a wall.
2. At the cloakroom end, talk to the guild receptionist, take a quest, and let the quest warp the party to the surface.
3. Then P1's accept test (three cold launches, both players, no warp), then P6a's in-game proof, P6b, P7a and the
   demo -> route fixture.

## Round 29 (2026-11-10) — the guild door is inert, and a crossing route across the city

### `TObjCityDoor_Guild` at (185,173) is not an active door

Four approaches, each ending within 5 units of the coordinate:

| approach from | arrived at | room after |
|---|---|---|
| (210, 173) | (167.8, 170.7) | 10 |
| (185, 140) | (185.6, 170.7) | 10 |
| (185, 205) | (187.5, 171.6) | 10 |
| (160, 160) | (179.3, 170.0) | 10 |

Two of those sat *on* the door's coordinate, and `A` pressed there did nothing either. So the entity is a marker, not a
portal: the only working transition in the city is the one the probe found at **(105-160, 100-163)** between the lobby
(room 10) and the big area (room 20).

### A crossing route, mapped by walking

The area west of the terrace is walled at x ≈ 102 for z from 94 to 160, but there is a gap to the south. Leg by leg
(`push_through` on, each leg restarted on `stuck`):

```
(102,105) terrace  ->  (33.5, -33.9)      through the gap in the south wall
                   ->  (-29.6, -36.7)
                   ->  (-84.6,   27.1)
                   ->  (-223.1, -24.6)    the west end of the area
                   ->  (-250.0, -44.0)    a shop counter with a keeper behind it
```

That is roughly **350 units across two halves of the city**, including a wall gap no straight line would have found. It is
also the first time a route this long has been walked under control.

### Where the guild is not

The west end is a **shop row**: `ps1-cloakroom.jpg` shows a glowing counter, a shopkeeper and stock shelves, with the
cloakroom NPC (`TObjNpcCloakroomBase`, `-267,-24`) sitting among them. Pressing `A` at the counter produced no dialogue --
the character is across the counter rather than in front of the keeper -- so shops and the guild are both in this area and
the guild's own counter has not been reached yet.

### What this round established for the next one

* A **known route** to the west end of the city, with waypoints that have been walked: `(102,105)`, `(33,-34)`, `(-84,27)`,
  `(-223,-24)`.
* The guild door entity is a dead end, so the guild has to be found inside room 20 rather than through a labelled door.
* Interacting with a counter needs the character **in front of** the keeper, not across the counter from them -- so the
  next attempts should walk *around* a counter and face the keeper before pressing `A`.

## Round 30 (2026-11-10) — P7a's blocker was a path spelling, and it is fixed

The city hunt was taking round after round, so this round went at the one P7a blocker that was already understood: the
player-model code asks for paths this disc does not have.

### The bug

`pso_player.build` and its swap path read character parts as `PSO/PL<C>BDY00.NJ`, `PSO/PL<C>HED<NN>.NJ`,
`PSO/PL<C>NJ.BML` and `PSO/PL<C>TEX.AFS` -- the Dreamcast layout. The GameCube disc `GPOE8P` has **no `PSO/` directory
at all**; the same parts are flat at the root, lower-case, with the class letter kept:

| Dreamcast (what the code asked for) | GameCube (what the disc has) |
|---|---|
| `PSO/PLABDY00.NJ` | `plAbdy00.nj` |
| `PSO/PLAHED03.NJ` | `plAhed03.nj` |
| `PSO/PLANJ.BML` | `plAnj.bml` |
| `PSO/PLATEX.AFS` | `plAtex.afs` |

That is why every `pso_player` call on this disc raised: it was reaching for a directory that does not exist.

### `gbox/pso_gc_paths.py` (+9 tests)

* `gc_path` / `dc_path` translate between the two layouts, keeping the **class letter's case** (lower-casing the whole
  name would not match `plAbdy00.nj`).
* `read_part(disc, path)` tries the GameCube name first and falls back to the Dreamcast one, so the same code works on a
  rip from either platform; a failure names **both** candidates.
* `class_parts(cls, head)` returns the four names the model code needs.
* One test checks against the **real disc catalogue** (3,510 files from the P2 pass) that `plCbdy00.nj`, `plCched00.nj`,
  `plCnj.bml` and `plCtex.afs` are all actually present -- so the translation is verified against the disc, not against a
  guess.

`pso_player.build` and the swap path now read through `read_part`. `pso_player` imports clean and the translator's tests
pass; the model build itself still needs a live disc to run end to end, which is the next step for P7a.

### Still open from P1

The city navigation stands where round 29 left it: the party is in room 20 near a shop counter, the guild door entity is
inert, and the guild counter has not been reached. That remains the one thing between this lane and a field arrival by
real presses.

## Round 31 (2026-11-10) — P7a is running now, and it fails in the right place

### The model build gets all the way to the textures

With `pso_gc_paths` from round 30 in place, `pso_player.build` was run against the disc for real. The failure moved three
times, each one a genuine format difference rather than a missing file:

| attempt | failure | what it was |
|---|---|---|
| round 30 | `FileNotFoundError PSO/PL...` | the Dreamcast path spelling — fixed by `pso_gc_paths` |
| this round, first run | `struct.error: 806354952 bytes at offset 806354944` | **GC NJCM payloads are big-endian**, `ninja.NJ` defaults to little-endian |
| this round, with the body and head parsed | `KeyError 'PSO/PLCTEX.AFS'` | three more reads bypassed the translator |
| this round, all reads translated | `ValueError: no PVRT chunk` | **the textures are GVR, not PVRT** — the Dreamcast texture path |

So the model parse now works on a real GameCube body: `plCbdy00.nj` and `plChed00.nj` both load, and the code walks the
node tree until it reaches the texture archive.

### The endianness finding

`ninja.NJ`'s docstring had this half right — the **chunk size** field is little-endian on both platforms, and a comment
already records that. What was missing is that the **node/vertex payload** is big-endian on GameCube. The probe is one
field: the root node's model offset. As little-endian it read `0x30100000` (a 806 MB offset into a 24 KB file); as
big-endian it reads `0x1030`, which points inside the chunk.

`pso_gc_paths.njcm_is_big_endian(data)` reads that field both ways and believes whichever lands inside the chunk
(both plausible -> the smaller). `nj_part(disc, path)` then reads *and* parses a part in one call, and `pso_player` uses it
for the body and the head. Three more direct reads (`textures`, `pack`, `afs_data`) were switched to `read_part` as well —
they had bypassed the translator.

Tests: the probe is asserted on synthetic payloads in both byte orders, and `njcm_payload` on the chunk framing.

### Next for P7a

The texture step wants `PVRT`, the Dreamcast format; this disc's textures are **GVR**. `pso_gc.gvr_decode` already exists
and is the decoder this lane has been using for the area textures -- the note from round 1 still stands, that its
`flags & 8` palette branch raises on 42 of the 42 CI textures on this disc, so P7a needs that fix as well as the switch.

Honest status: P7a is **not** done, but it is no longer blocked on a mystery -- it is three known pieces away (GVR decode
in the player build, the palette branch, and then writing the swapped model back).

## Round 32 (2026-11-10) — P7a's model build runs end to end on the GameCube disc

`pso_player.build(disc, cls="C", head=0, colour=0, out_dir=..., name="DSH", section_id=7)` now **succeeds** against
`GPOE8P` and returns a real manifest:

```
Manifest "DSH"
  meshes      7
  materials   (written)
  textures    7 PNGs under p7a/textures/
  skeleton    (present)
  unit_scale  0.1
```

That is the first time this lane has produced a player model from this disc, and it closes the P7a blocker that has been
open since round 1 ("`pso_player`/`pso_enemy` read a `PSO/` dir that does not exist on this disc").

### The three fixes, in the order they were needed

1. **Path spelling** (round 30): `PSO/PLABDY00.NJ` -> `plAbdy00.nj`, via `pso_gc_paths`.
2. **Byte order** (round 31): the GC NJCM node payload is big-endian while the chunk size is not; `njcm_is_big_endian`
   probes one field to tell which.
3. **Texture format** (this round): the character AFS holds **GVR** chunks (`GBIX` + `GVRT`), and the build was calling
   `ninja.pvr_decode` -- the Dreamcast PVR decoder -- which raised `no PVRT chunk`. `decode_texture_entry` routes on the
   magic: `GBIX`/`GVRT` to `pso_gc.gvr_decode`, anything else to `pvr_decode`, so a Dreamcast rip still works.

A fourth, smaller one fell out: `ninja.png` slices a **flat RGBA byte buffer**, and `gvr_decode` returns a numpy
`(h, w, 4)` array, which raised `ufunc 'add' did not contain a loop with signature (S1, uint8)`. `.tobytes()` fixes it.

### The palette worry was unfounded for player textures

The round-1 note said `gvr_decode`'s `flags & 8` palette branch raises on this disc's CI textures. Before touching that
code, all **286** entries in `plCtex.afs` were decoded: `ok 286, fail 0`. So the bug (if it still exists) is confined to
the *area* textures this lane hit in round 1, not to the character textures P7a needs. No special case was added --
guessing would have been the wrong move when a one-line experiment settles it.

### Tests (+6)

`tests/test_pso_player_textures.py` pins the routing: `GBIX` and `GVRT` entries go to the GVR decoder, a PVR entry still
goes to the Dreamcast one, and for all three magics the returned buffer is something `ninja.png` accepts (checked by the
PNG signature). The decoders are monkeypatched, so the tests need neither the disc nor numpy image work.

### What P7a still needs

The build produces the model; **writing it back into the disc is not done**. `pso_player`'s swap path
(`ninja_swap`/`build`) still has to be run and its BML rebuilt, then the disc booted to see the swapped character in
game -- the same shape as P6a, which built an object-moved disc and had it boot to the Sonic Team splash.

P1's guild counter also remains open as the only route to a field arrival by real presses.

## Round 33 (2026-11-10) — the character swap works at the file level; the launch did not use it

### The swap, verified

`plAnj.bml` is the HUmar pack (BQF's class). Its entries are `plAbdy00.nj` (body) plus twelve head/hair/cap files.
Rebuilding it unchanged is **byte-identical** (34,816 bytes), which is the foundation any swap needs -- the entry table and
the 0x800 alignment are handled correctly.

Then the real thing: replace the body entry with a **HUcast** body (`plCbdy00.nj`, 24,732 bytes):

```
rebuilt pack  63,488 bytes
body entry    24,732 bytes  == the donor, exactly
head entry    unchanged
```

A disc image was built from it and the build reports its change:

```
{"mod": "pso_hotswap_humar_to_hucast",
 "image": ".../pso_hotswap_humar_to_hucast/Phantasy Star Online Episode I & II Plus (USA).iso",
 "files": ["plAnj.bml"]}
```

So P7a/P7b now have a working **file-level** hot swap: any class's body can be dropped into another class's pack, and the
image builds with the FST updated by `gc_put_file`.

### The boot did not prove it, and the reason is mine

The launch was issued with `{"mod": "pso_hotswap_humar_to_hucast"}`, and the job's own diagnostics say the mod was **not**
applied:

```
detail.mod            ""
detail.timings.mod_s  0.0
```

The boot that followed was the base disc, so `pw0-charselect.jpg` shows BQF as a HUmar -- it proves the image boots and the
save is intact, and nothing about the swap. `LaunchIn.mod` exists and is documented as *"launch a file mod built with
file_mod (folder games, e.g. PS3)"*, so for a single-image GameCube title the modded image is probably selected another
way (the build's directory is registered per game, and the launcher may need that build named rather than the `mod` field).

That is the first thing next round: find how a single-image build is selected at launch, boot the swapped image, and look
at the character select -- which previews the model and is therefore the cleanest proof of a character swap.

### One caller bug worth recording

`bml_build` matches replacement keys **lower-cased** (`{'plabdy00.nj': ...}`); passing the on-disc spelling
(`plAbdy00.nj`) silently changed nothing but the pack's padding, so the first attempt looked like a successful rebuild
whose body had not changed. The verification (`pso_gc.bml_entry` on the rebuilt pack, compared byte-for-byte with the
donor) is what caught it -- a size-only check would have passed.

## Round 34 (2026-11-10) — the hot swap is real: the model visibly changes, and it deforms

### Two things were wrong, both now understood

1. **The launch `mod` is a query parameter, not a body field.** `POST /api/games/{gid}/launch` declares
   `mod: str = ""` alongside `node`: it is read from the query string. Round 33 sent `{"mod": ...}` as JSON and the
   server silently ignored it -- `detail.mod` came back empty and `mod_s` was 0.0. With
   `?node=<worker>&mod=pso_hotswap2_both` the detail reports `mod: pso_hotswap2_both`, and Dolphin's own command line
   (read from the process) ends with `-e "...\pso_hotswap2_both\...iso"`.
2. **The game does not read the body out of `plAnj.bml`.** Swapping the pack alone left the character preview
   pixel-identical. The disc also carries the same parts **loose at the root** (`plAbdy00.nj`, 21,308 bytes), and that is
   what the game loads. Replacing both the pack and the loose file is what changed anything.

### The visible result

| image | character-select preview |
|---|---|
| base disc | a small, correctly-posed HUmar in orange (BQF's own colours) |
| `pso_hotswap_humar_to_hucast` (pack only) | **identical** to the base -- proof the pack is not the source |
| `pso_hotswap2_both` (pack + loose body) | **the viewport fills with giant flat polygons** |

So the swap is in effect: the game is rendering the HUcast mesh as BQF. It is also **deformed**, and that part is not a
bug in the writer -- a raw mesh swap puts a mesh built for HUcast's bone layout onto a HUmar's skeleton. That is exactly
what `pso_player.build_swap` / `ninja_swap` (and the rigging pass that wants Blender) exist for: binding the donor mesh
to the host's joint roles before writing it in.

### What is proven, precisely

* the character pack rebuild is byte-exact when unchanged and exact when swapped (round 33);
* a single-image build can replace a GSL/BML file and a loose file, and the FST is updated (`gc_put_file`);
* the launch accepts the build by name and Dolphin runs that ISO (command line, in the log above);
* the running game reads the **loose** `plAbdy00.nj`, not the pack copy -- a fact this lane did not have before, and one
  that would have made any pack-only model mod invisible;
* the swapped mesh renders, and deforms, which bounds what remains: rigging, not plumbing.

### Next

1. Rig the swap: run `pso_player.build_swap`'s mapping (`body_roles`, `target_from_nj`, `ninja_swap`) so the donor mesh
   is bound to the host skeleton before write-back, and boot it for a model that is *correct* rather than visible.
2. P6a's in-game proof is still owed (the moved object has never been seen in a field).
3. P1's guild counter remains the only route to a field arrival by real presses.

## Round 35 (2026-11-10) — where a naive model swap stops working: one donor deforms, another crashes

Round 34 proved the swap reaches the game. This round asked how far a swap can go **without rigging**, by trying a donor from
the same family as the host instead of a robot.

| host | donor | result |
|---|---|---|
| HUmar (`plAbdy00.nj`, 21,308 B) | **HUcast** (`plCbdy00.nj`, 24,732 B) | the character-select viewport fills with giant polygons -- the mesh renders, bound wrong |
| HUmar | **HUnewearl** (`plBbdy00.nj`, 28,724 B) | **Dolphin: "Invalid read from 0x00000008, PC = 0x8028f508. The game probably would have crashed on real hardware."** (`qa0-hunewearl.jpg`) |

So a same-family humanoid is *not* safer than a robot. The HUcast body at least drew; the HUnewearl body makes the game
dereference a bad pointer while it walks the model -- and the two differ in more than shape: the joint layout the mesh is
written against is part of the file, and a mesh built for another class's skeleton does not just look wrong, it can be
unsafe.

That is the boundary this lane needed to find. It also says what the editor must **not** offer: "pick any model from the
collection and drop it in" is not a file copy, it is a **retarget** -- which is exactly what `pso_player.build_swap`'s
`body_roles` / `target_from_nj` / `ninja_swap` are for, and why that path wants a rigging tool.

### A concrete P2b target fell out

`0x8028f508` is not in the 34-name `known_functions` map (both candidates checked). The function at that address reads
`0x8` as a pointer during model handling, so it is the natural next decompilation target: it is where a mismatched mesh
turns into a hardware-level invalid read, and identifying it would let a writer *validate* a swap before writing a build
rather than discovering it by booting.

### Practical note for the lane

Every model build from here should be booted at least to the character select before being reported, because the failure
mode is a *crash dialog in the emulator*, not a wrong-looking model. The build pipeline can see none of it.

### Still open

* Rigging: `build_swap` with the joint-role mapping, so the swap is correct rather than merely visible.
* P6a's in-game object proof, P1's guild counter, P6b (editor page), and the demo -> route fixture.

## 7. Next

1. **Rig the swap** (`pso_player.build_swap`: `body_roles` -> `target_from_nj` -> `ninja_swap`) so a donor mesh is
   bound to the host skeleton before write-back. Round 35 showed why: a HUcast body renders deformed, and a HUnewearl
   body makes the game read an invalid pointer at PC `0x8028f508` -- a same-family donor is not safer.
2. **P2b target:** `0x8028f508` is not among the 34 named functions; it is the code that dereferences model data and
   turns a mismatched mesh into a crash. Identifying it would let a writer validate a swap before building.
3. **P6a's in-game proof** (the moved object has never been seen in a field) and **P1's guild counter** (the only
   route to a field arrival by real presses) both remain open, then P6b (editor page) and the demo -> route fixture.

Rule for this lane from now on: any model build is booted at least to the character select before being reported.
The failure mode is an emulator crash dialog, which no part of the build pipeline can see.
