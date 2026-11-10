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
the strongest form of "one object moved, nothing else touched". **What is not yet done is the in-game look**: that
needs the P1 menu walk (§6), because there is no way to reach Forest 1 from a cold boot by hand in this automation.

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

## 7. Next

1. P1: boot to the field by real presses, reading state only through `gbox.pso_ram`; three cold launches to Forest 1
   with both players. This is P2b's accept condition and unblocks P6a's in-game proof and all of P3-P5.
2. Then: P6a accepted (moved object seen in game), P6b (the editor page over `pso_areas` + `pso_map_write`).
3. P2b: decompile `FUN_80207E88` and locate the `TObj*` registry table.
4. P7a start: fix the Dreamcast-era paths in `pso_player`/`pso_enemy` so the player-model writer can run on this disc.
