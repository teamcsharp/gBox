# PSO Episode I & II (GameCube): the executable, mapped

`DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md` §0c/P2b asked for the GameCube executable in Ghidra, every system the bot
and the mods touch named, and each address either decompiled or proven by a live RAM watch. This records what is
proven today, on the owned disc, with the evidence for each claim.

Round 1 established the binary identity, the section map, the full code-address map against byte-exact guards, and
the string tables that name the area archives, the map layouts and the object classes. The menu walk, the boss part
counters and the save layout are not mapped yet — they are listed in §7 as work, not as findings.

## 1. Which binary is the game

**`main.dol` is not the game.** The disc's boot DOL (`0x420` in the header, 213,952 bytes,
sha256 `318a96bd6b210fab10d2316f13332a2b3ef1b1dce866b57a98736cc87e88e889`) is the AppSwitcher stub. The game is
the loose FST file **`PsoV3.dol`**, 5,233,088 bytes:

```
PsoV3.dol     5233088  sha256 1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a
switcher.dol   204480  sha256 b8febb6f6f0bf6fdb181d4b4c0506510cc0ce74ff83faaff39dded8d42b0156f
switcherD.dol  112800  sha256 39c9da7a0062c96b3d19ab8f78e4d2e9ec34fe65a3921d37fd148695c1aa1ce8
iwanaga.dol   3817920  sha256 f437bc3d4c69ee134f2777e5d61d78954cca3a4552891a187a0ffb605a0d6675
iwanagaD.dol  3938432  sha256 511f7e4fc4563947b7368bebe5f135565981f38c23cf425596404d98de213d7d
```

That digest is already pinned in the tree as `gbox/pso_gc_live.py:DOL_SHA256`, which is the independent confirmation
that the addresses the repo drives live belong to this file and not to the stub.

**Two owned `GPOE8P` executables exist and they are not the same size**, so neither a size nor a hash alone
names a build. The operator also owns the Return To Ragol V1.0.3 mod (catalogue `5b5792e27be59f59`, same serial
`GPOE8P`), whose `PsoV3.dol` is **5,236,992 bytes, sha256
`60fa76460510de212c817500119ee560bb415cbf7b1c32a8f4911c2e93ead3a5`**. Everything in this document - every
address, every guard, the Ghidra program - is the **base Plus disc's** `1f80fb82...` executable.
`gbox/pso_ragol_unlock.py`'s `OWNED_EXECUTABLE_SIZE = 5236992` is therefore correct for its own build, not a
typo; a Return To Ragol session would need the addresses re-derived, which is why that module stays
`pending_research`.

`PsoV3.dol` sections (DOL header at `0x00 / 0x48 / 0x90` = file offsets, addresses, sizes; bss and entry at `0xD8`):

| # | kind | address | size | file offset |
|---|---|---|---|---|
| 0 | text | `0x8000C000` | 9,504 | `0x000100` |
| 1 | text | `0x8000F740` | 4,343,776 | `0x002620` |
| 7 | data | `0x8000E520` | 1,856 | `0x426E00` |
| 8 | data | `0x8000EC60` | 2,784 | `0x427540` |
| 9 | data | `0x80433F20` | 256 | `0x428020` |
| 10 | data | `0x80434020` | 32 | `0x428120` |
| 11 | data | `0x80434040` | 312,736 | `0x428140` |
| 12 | data | `0x804805E0` | 514,624 | `0x4746E0` |
| 13 | data | `0x805D2600` | 9,120 | `0x4F2120` |
| 14 | data | `0x805D7D00` | 38,144 | `0x4F44C0` |

Entry point `0x8000C040`, bss `0x804FE020` + `0xE3204`. Section 1 is the whole game; section 12 ends just below
`0x804FE020`, which is why `PHASE` (the first bss global the repo reads) sits immediately after the file image.

## 2. Reproducing the Ghidra program

The GameCube is a big-endian PowerPC with Gekko paired-single instructions, which stock Ghidra does not decode
(opcode 4). `gbox/gcdisc.py` has both halves of the fix:

```python
import sys; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc, dol_to_elf
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
open(r"D:\gBox\pso-ds\pso_v3.elf", "wb").write(dol_to_elf(d.read("PsoV3.dol"), gekko=True))
```

`dol_to_elf` writes one `PT_LOAD` per DOL section at its real address plus a bss segment, so an address in the
listing is the address the game uses at run time. `gekko=True` runs `depair()` over the executable segments:
`psq_l`/`psq_lu` become `lfs`/`lfsu`, `psq_st`/`psq_stu` become `stfs`/`stfsu`, and the other opcode-4 words
become `nop`. Integer and pointer data flow — which is what the format and object work needs — is untouched.

Imported with the stock `PowerPC:BE:32:default` language (Ghidra 12.1.4, `D:\gBox\runtime\ghidra_12.1.4_PUBLIC`) and
full auto-analysis, the program resolves **25,981 functions** at image base `0x8000C000`, and defines **9,789
strings**, of which 898 mention an area, archive, format or object class. The project lives at
`D:\gBox\ghidra-pso` (on `D:`, never in git).

## 3. The code map, proven by byte-exact guards

Each row was read out of `PsoV3.dol` through its own section table and compared with the guard the tree already
carries in `gbox/pso_gc_live.py` (`GUARDS`), `gbox/pso_fence.py` (`FENCE_GUARDS`) and
`gbox/pso_coop_geometry.py` (`PLAYER_FLOOR_CODE`). **17 of 17 guards match, 0 mismatches.** The Ghidra function and
its size are what auto-analysis found at that address.

| address | Ghidra function | size | guard (first 8 bytes) | what it is |
|---|---|---|---|---|
| `0x8000C040` | `entry` | 312 | — | the DOL entry point (Ghidra names it) |
| `0x8000F998` | `FUN_8000f998` | 12 | `38000001` | `BEGIN_TRAVEL` — sets the area-load request flag (`pso_fence.py:9`) |
| `0x8001E5C8` | `FUN_8001e5c8` | 8 | `806dba60` | the primitive `pso_coop_native.py:17` / `pso_gc_adventure.py:13` calls |
| `0x800791BC` | `FUN_800791bc` | 964 | `9421ff70` | the native floor-height query (964 bytes, the same size `pso_coop_geometry.PLAYER_FLOOR_CODE` pins) |
| `0x8007A448` | `FUN_8007a448` | 252 | — | the floor-query helper (252 bytes, same pin) |
| `0x80102AC0` | `FUN_80102ac0` | 32 | `9421fff0` | inventory/equip helper (`pso_gc_live.py:45`) |
| `0x80103748` | `FUN_80103748` | 88 | `9421fff0` | `F_DELETE` — object delete |
| `0x801057A8` | `FUN_801057a8` | 204 | `9421ffe0` | `F_CREATE` — object create |
| `0x8010B198` | `FUN_8010b198` | 140 | `9421fff0` | guarded routine (`pso_gc_live.py:48`) |
| `0x8010B46C` | `FUN_8010b46c` | 196 | `9421fff0` | guarded routine (`pso_gc_live.py:47`) |
| `0x8010C740` | `FUN_8010c740` | 4 | `4e800020` | `blr` thunk — the equip patch site (`pso_gc_live.py:43`) |
| `0x8010CCB0` | `FUN_8010ccb0` | 4 | `4e800020` | `blr` thunk — the second equip patch site |
| `0x80154764` | `FUN_80154764` | 36 | — | `FENCE DROP` — clears the laser collision bit (`pso_fence.py:24`) |
| `0x80154788` | `FUN_80154788` | 36 | — | `FENCE RAISE` — sets it (`pso_fence.py:25`) |
| `0x80192CCC` | `FUN_80192ccc` | 164 | — | `FENCE_STATE0` |
| `0x80192D70` | `FUN_80192d70` | 84 | — | `FENCE_STATE1` |
| `0x80192DC4` | `FUN_80192dc4` | 68 | `9421fff0` | the laser-fence update |
| `0x801B7998` | `FUN_801b7998` | 304 | — | the player updater (304 bytes, the size `pso_coop_geometry` pins) |
| `0x801B8310` | `FUN_801b8310` | 52 | `9421fff0` | `F_INVENTORY` |
| `0x801B8E68` | `FUN_801b8e68` | 600 | `9421ffd0` | guarded routine (`pso_gc_live.py:46`) |
| `0x801B9D50` | `FUN_801b9d50` | 188 | `9421fff0` | `F_UNEQUIP` |
| `0x801B9F40` | `FUN_801b9f40` | 288 | `9421ffe0` | `F_EQUIP` |
| `0x801BAB1C` | `FUN_801bab1c` | 92 | `9421ffe0` | `WARP` — executes the party area transition (`pso_fence.py:10`) |
| `0x801BB330` | `FUN_801bb330` | 420 | `9421fff0` | `ORIGINAL_UPDATE` — the player update the dispatcher tail-chains |
| `0x801D4F14` | `FUN_801d4f14` | 48 | `9421fff0` | guarded routine (`pso_gc_live.py:39`) |
| `0x801D5764` | `FUN_801d5764` | 68 | `9421fff0` | guarded routine (`pso_gc_live.py:40`) |
| `0x802077CC` | `FUN_802077cc` | 64 | `2c030011` | floor record getter (`pso_coop_geometry.py:32`) |
| `0x80207E88` | `FUN_80207e88` | 104 | `9421fff0` | floor → map index/variant selector (`pso_coop_geometry.py:33`) |
| `0x80228540` | `FUN_80228540` | 56 | `9421fff0` | `SET_TARGET` — stores the travel destination |
| `0x80229220` | `FUN_80229220` | 56 | — | stage-flag accessor (`docs/pso-progression.md:85`) |

Two addresses in the tree are **table entries, not functions**: `0x80014684 .. 0x800146BC` fall inside
`FUN_80014108` (1,832 bytes). That is correct for what `gbox/pso_crit.py` does with them — it reads them as
pointer-table slots — but it is worth knowing that a Ghidra "function at" query there returns the enclosing
function, not a routine of its own.

## 4. The data map, and what Ghidra does *not* prove

| address | width | what | Ghidra data references |
|---|---|---|---|
| `0x804FE120` | u8 | `PHASE` — the game phase/state machine | **10** |
| `0x8050EA10` | 4 × u32 | `PLAYER` — the player slot table (actor pointers) | **6** |
| `0x8050D460` | u32 | `ENTITY_TABLE` — the live object table | 0 |
| `0x80515BA0` | block | `TRAVEL_STATE`; destination floor at `+0xC` | 0 |
| `0x805D49B8` | u32 | travelling flag | 0 |
| `0x805D541C` / `0x805D5420` | u32 | floor-item table / counts **pointer** arrays | 0 |
| `0x805D4E68`, `0x805D5550`, `0x805D5650`, `0x805D6000`, `0x805D6014` | u32 | collision roots | 0 |
| `0x805D5FC0` | u32 | `FLOOR` — the current floor id | 0 |
| `0x805D6060` | u32 | the current episode (0-based) | 0 |

**Be careful with this table.** Only `PHASE` and `PLAYER` have direct Ghidra data references. The rest are reached
through a computed base (a `lis`/`addi` pair, often with a runtime index), so auto-analysis does not attribute a
reference to the exact address and a `getReferencesTo` query returns nothing. Their proof today is therefore the
**live** one the tree already carries (the session ids in `gbox/pso_gc_live.py`, `gbox/pso_fence.py`,
`gbox/pso_coop_geometry.py`), not a decompile. Do not read "0 references" as "not real", and do not read it as proof
either. `gbox/pso_ram.py` names all of them in one place with a `read_memory` interface so the next live session can
confirm them and the test suite can hold the shape.

## 5. What the strings prove

Auto-analysis defined 9,789 strings. Three groups matter to the format work:

**The area-archive table — the game's own area order.** `gsl_*.gsl` names sit in one contiguous block from
`0x431C04` (39 entries: `gsl_city.gsl`, `gsl_forest01.gsl`, `gsl_forest02.gsl`, `gsl_cave01..03`, `gsl_machine01..02`,
`gsl_ancient01..03`, `gsl_versus01..02`, `gsl_labo`, `gsl_ruins01`, `gsl_space01`, the `a*` copies,
`gsl_jungle01..07`, `gsl_seabed01..02`, then the `_multi` variants). `gbox/pso_areas.LIST_AREA_TABLE` is that list
verbatim.

**The map-layout names.** 196 `map_*` strings without an extension (`map_forest01`, `map_forest02`,
`map_aforest01`, `map_acave01_00` … `map_acave01_05`, …). The `_NN` suffix is the layout variant, which is exactly the
`Scene/map_<area>_<NN>{c,n,r}.rel` suffix the collision reader groups on — so the loader's own name list and the
Scene file naming agree, and a multi-layout area is genuinely one floor built from one of N layouts.

**The object-class registry.** **315** `TObj*` class-name strings (`TObjBoss1Crater`, `TObjVoloptPillar`,
`TObjDFHorming`, `TObjCollision`, …), the same class names the live bot reads from an actor's `+0x00` (see
`docs/pso-progression.md`). These are the names a placement's class index resolves to, once the registry table that
orders them is located.

Also present: `gsl_set_object.gsl` / `gsl_set_enemy.gsl` / `gsl_set_event.gsl` (twice each, at `0x43DE08`, `0x43DE1C`,
`0x43DE30` and again in the table), i.e. the executable names the three archives that hold the area placement sets.
It does **not** name any individual `*o.dat` / `*e.dat`; those names are assembled at run time, which is why a
string search for `map_forest01_00o.dat` in the DOL finds nothing while the archive is referenced directly.

## 6. Encrypted or checksummed

- **On the disc:** the only cipher is PSO's own v2 stream cipher over a PRS stream, used by `.pr2` / `.pr3` (the text
  archives), the `.cpt` tables and `PlyMotionNpcTown.cpt`. Key material is in the file header itself (`u32 size`,
  `u32 key`: English `0xF47096A3`, Spanish/German `0xF470A6A3`, Japanese `0xF4709653`) — see
  `gbox/psotext.py` and `docs/research/pso-gc-formats-tables.md`. Nothing else on the disc is encrypted: BML, GSL,
  AFS, NJ, GVM/GVR, REL data and DAT are all plain formats.
- **In save data:** unproven for this build. `gbox/pso_ragol_unlock.py` records that the owned executable's
  item-eligibility bitmap, level table and memory-card block offsets are still unproven, and no `checksum` /
  `crypt` string exists in `PsoV3.dol` (the only near match is the class name `TObjEneSaver`). The GameCube memory
  card's own per-block checksum is the card library's, not the game's. Treat the save layout as an open item (§7).

## 7. Not mapped yet

1. **The menu walk (P1 needs it).** The phase byte is known (`0x804FE120`, 10 → 3 → 9 through a boot) but the cursor
   and selection bytes for PRESS START, the offline/online choice, character select and the Hunter's Guild are not
   named. `gbox/pso_menu_observer.py` has behaviour for some of them; the addresses are not yet in `pso_ram.py`.
2. **The floor → map index/variant resolver.** **Decoded 2026-11-10 (branch `ds-pso-floor-map-20261110`).**
   - `FUN_80207E88(floor)` returns a `{char **names, u32 count}` entry for `floor < 0x24` from one of two 36-entry
     tables: `0x804C8FC0` (Episode 1) or `0x804C9270` (Episode 2), chosen by `FUN_8030A6A8` (it reads
     `+current_episode == 3` and two helpers).
   - The entry names `count` area/layout pairs: `names[2i]` is the area's map name and `names[2i+1]` the layout's.
     Floor 0 = (`map_city00`, `map_city00_00`); floor 3 = Cave 1 with six layouts `map_cave01_00` .. `_05`;
     floor 15 = the lobby's fifteen rooms; floor 16 = `map_vs01` with three; floors 30-33 = `map_boss05` .. `08`.
   - The Episode 2 table is the same table with the `a`-prefixed areas for floors 0-14 and identical floors 15+
     (which is why Forest 2 resolves to `forest02` or `aforest02`: it is floor 2 in either table).
   - `FUN_802077CC(0..0x11, out)` copies three words per row from an 18 x 12-byte **.bss** table at `0x80513920`,
     and `FUN_80207798(floor, a, b, c)` **writes** the same row. It is **not** map data: `FUN_802078A4` walks the
     rows, and for each live row (`word0 >= 0`) recomputes words 1 and 2 as
     `(table[word0].param * k * (rng() - bias))` through `FUN_8039C880` - a per-floor randomised **environment
     parameter** block (seeded once by `FUN_80207C60`, which copies index/param pairs from `0x8044B894` and defaults
     `word0` to `-1`), not the floor -> map binding. The floor -> map/layout names are `FUN_80207E88`'s tables
     (`0x804C8FC0` / `0x804C9270`), which are decoded and pinned in `gbox/pso_floor_map.py`.
   - `gbox/pso_floor_map.py` pins both map-name tables, exposes `floor_names` / `area_for_floor` /
     `layouts_for_floor` / `layout_name` / `area_id`, and `derive()` re-reads the table from a `PsoV3.dol`
     (`tools/verify_pso_floors.py`). It verifies against the owned disc (both tables, 36 floors each), and floors
     0-11 match `pso_areas.EPISODE1` in order.
3. **The object-class registry ordering.** 315 names exist; the table that maps a class index (the low byte of a
   placement's `kind`) to one of them is not located. That is the single highest-value decompile left for the editor,
   because it turns a marker's number into "door", "warp", "switch" or "Booma".
4. **Boss part counters.** `pso_boss_strategy` drives them from live RAM; the structures are not decompiled.
5. **Save-data layout** (§6).

## 8. Reproduce

```powershell
$env:GHIDRA_INSTALL_DIR="D:\gBox\runtime\ghidra_12.1.4_PUBLIC"
$env:JAVA_HOME="C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot"
D:\gBox\runtime\pyghidra-venv\Scripts\python.exe D:\gBox\pso-ds\analyze_pso.py
```

That script (kept with the working files on `D:\gBox\pso-ds`, not in git because it is a run artefact) builds the ELF,
imports it into a project at `D:\gBox\ghidra-pso`, runs auto-analysis and writes a JSON dump of the function census,
the known-address resolution and the string tables. The guard comparison in §3 is reproducible without Ghidra from
the disc alone:

```python
import struct, sys; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
dol = d.read("PsoV3.dol")
offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
def at(va, n):
    for i in range(18):
        if sizes[i] and addrs[i] <= va < addrs[i] + sizes[i]:
            return dol[offs[i] + va - addrs[i]: offs[i] + va - addrs[i] + n]
print(at(0x801BB330, 16).hex(), at(0x801057A8, 16).hex())
```
