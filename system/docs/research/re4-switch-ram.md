# RE4 Switch (010099A00BC1E000) RAM: the Mercenaries clock

First field of the Switch edition's RAM map, measured 2026-11-05 on **lilspark** (GB10, Citron NEO
d3df71e55, NCE, Vulkan). This is the field `re4_switch.screen()` needs to tell a live round from a
finished one; it is not yet enough for the bot to play (see "Still missing").

## Result

**The round clock is an `f32` countdown in seconds.** A round opens at `120.0` and counts down; it is
stored in a cluster of copies 0x30 bytes apart around `0x3ca8e78xxx` in the guest arena (addresses move
every boot: ASLR).

Evidence, same run:

| when | on screen | memory |
|---|---|---|
| before the scan | `01'59"10` (119.10 s) | — |
| read during the scan | — | `118.445` |
| 11.1 s later | — | `107.337` |

`118.445 → 107.337` is a drop of `11.108 s` over `11.1 s` of wall time (the scan itself ran 12.8 s and
the second read waited 10 s, so the two reads of one address are ~11 s apart). The value matches the
HUD between the two screenshots, and it tracks wall time at ~100 % emulation speed — the same speed a
`01'59"07 → 01'38"97 / 20 s` countdown measured earlier.

The whole cluster is one struct family: consecutive survivors differ by `0x30` (`0x3ca8e78710`,
`…8b90`, `…8bc0`, `…8bf0`, `…8c20`, `…8c50`, `…8c80`, `…8cb0`) with values 118.445, 118.443, 118.442,
118.441, 118.445, … — several timer slots written at slightly different moments, not one field.

## How it was found (reusable)

1. **The guest arena is `/memfd:HostMemory`, not anonymous memory.** Citron's 258 GiB of writable
   address space is mostly reservation; the live data is 8.1 GiB, of which the large pieces are
   `rw-s /memfd:HostMemory` mappings (4 GiB + 629 MiB + 733 MiB + …) plus ~2 GiB anonymous and a
   196 MiB heap. A scan that filters to "anonymous" mappings only **finds nothing** — that mistake
   cost a run.
2. **Scan only resident pages.** `/proc/<pid>/smaps` per-VMA `Rss` cuts 258 GiB of address space to
   7.6 GiB of readable data: a full pass took 12.8 s instead of 112 s (`24.5 s` for the noisy
   everything-is-a-candidate variant).
3. **Use the known starting value.** A round opens at `2'00"00`, so the candidate windows are narrow:
   centiseconds `11200..12060`, frames `6700..7240` at 60 Hz, seconds `111..121`, float seconds
   `111..121`. Random small integers are the enemy here: scanning every `u32` in `[1,20000)` over the
   arena produced **6.9 M** candidates; the narrow window produced 173 k `u32` + 32 k `f32`.
4. **Require the drop to match wall time.** Re-read the candidates after a known wait and keep only
   values that fell by that many seconds (or 100×, 60×, 30×). That is what isolated the 78 float copies
   from the rest: `0` `u32` survivors, `78` `f32` survivors.

## Static side: the main NSO (2026-11-05)

Citron's `dump_nso` (`[Debugging] dump_nso=true`) writes the module to
`<citron home>/data/citron/dump/010099A00BC1E000/nso/main-<build id>.nso` — note the nested path; a finder
that only looks at the top-level `dump/` directory misses it.

| | |
|---|---|
| build id | `82C2A04A21D3E0B850F273D4149C9003` |
| size | 30,146,816 bytes (0x100 header + image at vaddr 0) |
| sha256 | `98ca897f07b2c864a0cabfb9dd8ca46a54b88c565ba629da3b7a4b6a57a57441` |
| signature | 64 bytes at image offset **0x100000**, unique in the module |
| live check | found once at `0x3ca7d04000` ⇒ **base `0x3ca7c04000`** (the same address Citron gives RE6's main) |

`re4_switch.module_base(m)` now re-finds that base on any boot: it re-checks a cached base with one 64-byte
read and otherwise scans read-only rows in 16 MiB steps — the shape `re6_switch` uses. Exercised against a
fake memory: finds, caches, returns None when absent, and re-finds when the base moves.

Two signatures were verified on the same boot — the shallow one at image 0xc0 (first unique pattern from the
start) and the chosen one at 0x100000 — both resolving to the same base, which is a useful cross-check.

## Next: static analysis now that the module is on disk

The local model on lilspark2 (through gBox's node proxy) reviewed the plan and put it plainly: with a
verified module on disk, **disassembly and cross-referencing beats more blind memory differencing** — find
the code that writes health and the code that turns a heading, then read the offsets off the instructions
rather than inferring them from behaviour. That is the next step for facing and health; the Ganado list
follows the same way. The dump is at the path above on lilspark, and capstone is already a project
dependency.

## Facing: found (2026-11-05, fifth pass)

Method: the player is picked by **walk displacement** (the one identification that has held across boots),
then a **turn pattern** is sampled on 48 KiB windows — 1.0 s left, 2.0 s right, 1.0 s left — with a
screenshot at each moment so a dead round can't be mistaken for a flat signal (the frames changed 31 %, 25 %
and 30 % of pixels; brightness cycled 24.8 → 17.0 → 12.3 → 23.7 as the view swung between the lane and the
wall).

**The heading is a unit sin/cos pair** (radius 0.995–0.998 at every sample) that follows the input exactly:

| offset in the window | g0 | after 1.0 s left | after 2.0 s right | after 1.0 s left |
|---|---|---|---|---|
| `-0x3bb0` | — | **+42.1°** | **−40.1°** | **+40.5°** |
| `-0x3bc0` | — | +41.8° | −39.8° | +40.3° |
| `-0x35f0` | — | +39.0° | −38.3° | +36.7° |

A fourth pair (`-0x366c`: +29.4° / −50.5° / +49.2°) is the **camera**: asymmetric and smoothed, which is what
distinguishes it from the player's own heading.

Two useful numbers: the turn rate is ≈ **42°/s of hold** (not the GameCube build's 140–230°/s, so the
keyboard pad is a full deflection with a ramp), and the heading exists in at least three copies 0x10 apart —
the same "several copies" habit as the clock and the position, so a driver should read one and verify it
moves.

**Caveat, and the next step:** that window was centred on a spawn match that held the transform but *not*
the position triple, so the heading's offset **relative to the player position** is not yet known. One run
that dumps around the verified position triple (found by walk displacement) closes it.

### Anchored to the player position (same day, sixth pass)

The first pass had matched the *camera* by accident: its scan allowed `y = 40.9 ± 150`, and the camera's
position is `y ≈ 133.8` — the camera also moves when the player walks, so it passed the walk test as well.
Tightening the y tolerance to ±25 cut 22 matches to **6**, all the player's own position copies, and the
dumped window then held:

- the position `(-3809.2, 41.6, 5961.0)` at the window centre, with a copy 0x18 before it (and other copies
  further out — the same "several copies" habit as the clock);
- **four unit sin/cos pairs ≈ 0x38ac bytes before the position**, 0x10 apart, again following
  `(+16.3°, −35.3°, +18.9°)` on the left/right/left pattern.

So the facing read is `pos − 0x38ac` (scan ±0x600 around it for a radius≈1.0 pair if a copy shifts). The
turn rate differs between runs (≈42°/s in one, ≈16°/s in another), so the keyboard stick is not always at
full deflection — the bot must steer by **closed loop** on the angle, never by a fixed press duration.

Still to do on the player: health, and the pointer path (the position is heap-allocated, so a 20 Hz read
needs a static pointer in `main` rather than the ~9 s scan that finds it today — that is the static-analysis
step the signature now makes possible).


## Health: found (2026-11-05, seventh pass)

**An `int16` at `player position − 0x2478`.** Evidence from two runs sampled at 4–5 Hz:

- it is **1336** from the first frame of the round and holds there (two separate runs);
- one hit takes it **1336 → 1054 (−282)**, a single step with plateaus either side — the only value in the
  whole 48 KiB player window that moves like damage (a 280-sample scan of that window found exactly two
  plateau-and-step candidates, this being the plausible one);
- at death the struct is **freed** rather than set to 0, so the field reads garbage (e.g. −5292) — the bot
  must treat a negative or wildly out-of-range value as dead, not as a health figure.

### What it is not (negative results worth keeping)

- **Not in the ±1 MB around the clock** (the GameCube build keeps health at `pG+0x4FB0`; this port does not):
  no monotonic int16 across 20 samples spanning a death.
- **Not the 2060 value** at `pos − 0x361b8`: it tracked 2060 for 34 s and then jumped 2060 → −6435 → 0 → 2061
  → 4278 as the memory was recycled. Two copies moving together is not evidence of health.
- **Not monotonic across a whole round**: health resets with the struct at death, so a "falls across all
  samples" test misses it — the test has to be *plateau and a few steps*, which is what isolated it.

## Ganados: entities found, coordinate frame unresolved (2026-11-05, eighth pass)

`snapshot()['enemies']` is the last big field before the driver. What the passes established:

- **Enemy structs exist and move at walking speed.** Scanning for "position triple + a unit sin/cos heading
  somewhere in the 0x4000 bytes before it" found 143 structured candidates, and **three of them moved 231,
  352 and 266 units over 3 s** (77–117 units/s) while everything else stood still. That is a Ganado walking,
  not an effect: effects and vectors in the same scan jumped 5000–8400 units in the same 3 s.
- **They are not in the player's coordinate frame.** Those movers sit at `(±500)` around the origin, while
  the player's position field reads `(-3668, 41, 6021)` — about 7000 units away. A proximity filter
  (±25 m around Leon) therefore finds only Leon, and a "walking speed + closing on Leon" filter returns
  **exactly one** entity: Leon (155.7 units, y = 40.9), which is the sanity check that the filter itself works.

So the likely shape is **room-local entity coordinates** against a world-space player field (RE4 streams
rooms), and comparing them needs the room transform or the player's own local position. Next measurement:
read the player struct for a *second* position triple and test it against the enemy frame; if it matches,
both are readable in one frame and `S_ENEMY` follows.

Two filters worth keeping from the failed passes: a mover must be **50–1200 units per 3 s** (walking, not
physics), and its `y` must stay in **10–300** (a character's feet, not a direction vector's zero).

## Ganados: the entity table (2026-11-05, ninth pass)

Chasing the pointers instead of the frame paid off. The steps:

1. Character-like triples anywhere in the arena (not just near Leon): 508,487 candidates, 106,185 distinct —
   far too many, because bones and props move like characters too.
2. Walking-speed filter (50–1200 units per 3 s, `y` 10–300): 10,687 "movers". Still far too many, but they
   **cluster in one region** (`0x5d4b37…`) at a regular **0x40-byte stride** — the entries are records in a
   table, not free-standing structs.
3. Pointer scan for words referencing the first movers: 372 hits, arranged as **two mirrored pointer arrays**
   (≈155 and ≈153 pointers, stride 0x40) — `0xfb16e077c158…` and `0x005d4b37c158…`.

So RE4 keeps its units in a **0x40-byte record table in room-local coordinates** — the analogue of RE5/RE6's
`sUnit` lines (`docs/research/re5-switch-ram.md`: "line N at +0x268 + 0x30 N"). That is what made the
"two frames" look contradictory: the table is room-local, the player's own position field is world.

Two filters from this pass are not enough on their own: the walking-speed test still admits 10,687 entries,
so the table needs its **liveness/type field** read (every record must carry flags and a class like RE5's
`sBioUnit`) before `snapshot()['enemies']` can be written.

Next: (a) dump one record fully and correlate its 0x40 bytes with a known enemy (position matches a mover,
flags non-zero, a type id); (b) find the pointer *to the table* inside `main`'s writable data so the bot can
read it at 20 Hz instead of scanning — that turns this table into `S_ENEMY`.

## Correction (2026-11-05, tenth pass): that table is a float array, not units

Dumping the 0x40-stride "records" showed overlapping float runs — `158.86, 292.90, 167.87, 317.81, 50.78,
142.40, 313.43, 59.91, 170.57, 313.94 …` — i.e. one dense float buffer sampled every 0x40 bytes, so the
"triple every 0x40" is an artifact of the scan, not a record layout. The 878-entry chains and the mirrored
pointer arrays are consistent with an animation/matrix buffer. **No pointer from `main`'s writable data
reaches it**, which a real unit table would have.

So the previous section's "entity table found" was wrong. What survives is only the negative knowledge:
enemies are not found by looking for 0x40-byte records of positions.

## Next: find units by the player's own layout

The player's struct gives a much more specific signature than "a position triple": **health `int16` at H and
the position triple at H + 0x2478** (both measured, with the heading a further −0x1434 from the position).
Scanning for that pair — a small int followed 0x2478 bytes later by three plausible floats — should list
every character that shares the class, player included. That is the next measurement.

## Correction 2 (2026-11-05, eleventh pass): offsets do not transfer between position copies

The player has several position triples in memory. Reading the *supposed* field offsets from the copy whose
health validates (see below) gave:

| copy | health at −0x2478 | heading pair at −0x38ac |
|---|---|---|
| `0x005d559cafe0` | **1336** (plausible) | **garbage** (`8.4e-44, 1.4e-45`, radius 0.000) |

So `−0x2478` holds for this copy while `−0x38ac` does not. Combined with the earlier observation that the
turn-following sin/cos pair was found in a window centred on the **camera** copy (the run whose centre held
`(-3587.7, 133.8, 6058.6)` and a 3×3 basis), the honest reading is:

- the "facing" reported earlier is very likely the **camera's yaw**, which follows the stick directly;
- the player's own heading is still unmapped, and its offset is not `−0x38ac` from every position copy.

**Rule for every future offset:** first validate the copy (`health@−0x2478` in 100–3000), then read the field
from *that* copy — and re-validate each boot. A three-field test (position + health + heading) was tried and
returned 2849 "units", almost all of them float-buffer artifacts with a constant `hp = 1267`, because a float
buffer happily satisfies a permissive int16 test.

## Method trap (2026-11-05, twelfth pass): title screen vs round

Two probes this round ran against a **title screen**, because the launcher boots to the title and never
enters a round: one "found" a game struct holding a 60–121 float (a menu/demo timer) and the next found no
player at all. Both results were invalid, and both cost a run. Every structural probe must therefore enter a
round first — the pattern in `map_game2.sh` (launch → menus → 3 × A → probe) — and should assert a live
round before reading anything.

## Globals found so far (conditional)

- `main+0x1206498` → a heap struct (`0x005d34d23000` in one boot). At the **title** that struct held a
  60–121 float at `+0x1C4`; in a **round** it holds no direct or one-hop pointer to the player (the single
  one-hop hit landed at `player+0x39300`, i.e. past the player position, not a player struct base).
  So the offset is real, but what the struct *is* in a round is still unproven.
- `main+0xaf1460` → an array of pointers into 0xC4-byte records. Their records hold no position triples, so
  this is an effect/animation table, not units.

## The unit array (2026-11-05, thirteenth pass): real, but not yet indexed

`main+0x113d568` holds a **contiguous array of pointers, stride 0x18**, into structures 0x10C8 bytes apart,
each with a further pointer at `+0x108` into a sub-array at 0x1F0 stride. That is the closest thing to a unit
list found so far: every entry's chain lands in the region that holds Leon's position copy.

**The containment test that was supposed to name Leon was invalid**: it asked whether `body <= player <
body + 0x14000`, but the units are only 0x10C8 apart, so a 0x14000 window contains a dozen of them and
almost every entry "matched" (positions `+0x9990 … +0x7e70`, one per entry). A valid test must compare
*exact* offsets — read the position field inside each unit and require it to equal the player's, rather than
asking whether it falls somewhere in a large span.

What is still unknown about this array: which entry is the player, the offset of the position within a unit
(the candidates are all in 0x7e70–0x9990, but that spread is the artifact above), and whether the array's
length is fixed (48 entries read; entry 35 held `0x019000000002`, i.e. a non-pointer, so it is not a dense
list of live units as read).

## Static attempts (2026-11-05, fourteenth pass): what the module does and does not give

1. **The dumped file is compressed.** `main-82C2A04A….nso` has NSO flags `0x3F`, i.e. all three segments are
   LZ4-compressed, so its strings are not readable as bytes and a file-based xref search finds nothing.
   The *loaded* module is decompressed, so the analysis has to run against live memory.
2. **The HUD text is not in the module.** Searching the loaded module (text 0x0–0x656000, rodata
   0x656000–0xae2000) for `mission start`, `the mercenaries`, `you are dead`, `press any button` found
   nothing; only lowercase `mission` appears (3× in rodata, likely identifiers). `PRESS` *was* found, but at
   `main+0x2c89390` — inside the guest heap, i.e. text the game loaded at runtime. So string-xrefs cannot
   reach the gameplay code.
3. **No ADRP+ADD/LDR references to the game-struct globals were resolved** (`main+0x1206468`,
   `+0x1206498`, `+0x113d568`, `+0xaf1460`) — 0 code sites. Either those globals are reached by another
   pattern (literal loads `LDR Xd, [pc+imm]`, or through a second pointer), or my three-instruction window
   is too small. The matcher, not the module, is the weak part.

**Instrument change for next round:** stop inferring from bytes and use the emulator's own debugger. Citron
exposes a GDB stub (`yuzu_runtime.set_debug_config(use_gdbstub=True, gdbstub_port=…)`, and gBox already has
`gbox.debug.GdbDebugger`), so a watchpoint on the health-validated player position would catch the code that
*writes* it — the movement/tick function — and from there the unit struct and its list. That is the
"read the structure off the code" step with a debugger instead of a matcher.

## Correct module layout (2026-11-05, fifteenth pass) — and why earlier "globals" were wrong

The existing RE6 tooling (`~/gBox_alt/scratch/agent/re6sw/tools`, written for exactly this) reads the dump
header correctly: three `{file_offset, ?, size}` triples at **0x10 / 0x20 / 0x30**, not the pairs I assumed.
`nsodis.py` reports:

```
text 0 + 0x655850   rodata 0x656000 + 0x48bbcc   data 0xae2000 + 0x4a738   (481 dynsyms)
```

**The module ends at `0xb2e738`.** So `main+0x113d568`, `+0x1206468` and `+0xaf1460` — the offsets I called
"unit array", "game globals" and "pointer array" in earlier rounds — are **beyond the module**: they are heap
addresses that merely happened to sit above the module base in the address space. Every claim built on those
labels was wrong, and that is why no code referenced them (93,950 ADRPs, 0 xrefs — the matcher was right
that time, the targets were not module data).

Also corrected: the dump is **not** compressed. `mission` (0x6e286f), `Ganado` (0x6c3cf6) and `model`
(0x6c087f) are readable in the file; my earlier "compressed, flags 0x3F" conclusion came from searching only
exact uppercase HUD strings that this build does not contain.

### A pipeline that works

Scanning only the real data segment for 8-byte values that point into the guest heap at objects holding a
position triple found module globals at `data+0x00488`, `+0x004c0`, `+0x00f440` … `+0x02bb68`, each with the
position at a stated offset inside the target. Those offsets are *module* offsets, so `addrrefs.py` can now
name the code that reads them — which is the step that was impossible while the targets were heap addresses.

Next: run the same scan inside a Mercenaries round (the pass above ran at the title, so its objects are
menu/UI), then `addrrefs.py <dump> <lo> <hi>` on the globals it finds to get the accessing code.

## The static pipeline works end to end (2026-11-05, sixteenth pass)

In a Mercenaries round the data-segment scan found 30 globals, including two that are absent at the title —
`data+0x04f00` and `data+0x04f18`, both pointing at heap objects with a position at `+0x250` (the round's own
objects, not menu ones).

Resolving those to code needed one fix: the scan prints offsets **within** the data segment, while
`addrrefs.py` wants **module** offsets (`0xae2000 + off`). With that corrected:

- `0xaf1440` (a title global) → **one access at code `0x1cccec`**
- the two round globals → no direct code access (written through a pointer, as expected for a manager)

Disassembling `0x1cccec` shows what `0xaf1440` actually is:

```
001cccec: adrp x9, #0xaf1000
001cccf0: add  x9, x9, #0x440      ; x9 = 0xaf1440
001cccf4: sxtb x8, w8
001cccf8: ldr  x8, [x9, x8, lsl #3] ; load a pointer from a table indexed by a byte
001cccfc: b    #0x1ccd08
```

It is a **jump table** (a switch on a byte), not a unit list — my "unit-like target" test matched it because
the table's targets are code that happens to contain float triples. Lesson: "target holds a float triple" is
not a unit test; a unit target must also carry the health field at `−0x2478` and move over time.

The value of this pass is the pipeline itself, which now demonstrably runs
*modules data → globals → `addrrefs` → disassembly* for RE4. Next: filter the globals with the real unit test
(health + motion), then disassemble the code that reads the surviving ones.

## Ghidra is open on the module (2026-11-05, seventeenth pass)

The static route now has its real engine. What was needed:

1. **Build a loadable ELF from the dump** with the existing tool:
   `nso2elf.py main-82C2A04A….nso re4main.elf` → 11,781,944-byte ELF, four `PT_LOAD`s matching the module
   (text `0x0`, rodata `0x656000`, data `0xae2000` + bss, `PT_DYNAMIC` at `0xb24b20`).
2. **Point gBox at Ghidra.** The bridge reported *"needs the operator's Ghidra on this worker: set ghidra_home
   (or GHIDRA_INSTALL_DIR)"*. Ghidra is installed at **`/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC`**; with
   `conf.ghidra_home` set, `ghidra_bridge.unavailable()` returns `None` and the PyGhidra venv
   (`gbox-data/runtime-linux-aarch64/pyghidra-venv`, pyghidra 3.1.0) starts the bridge server.
3. **Import/analyse** via `session.request('open', {'binary_path': …})`:

```
language AARCH64:LE:64:v8A   image_base 0x00100000   functions 11839
```

**Address rule:** Ghidra addresses = module offset **+ 0x100000** (the ELF's image base), so a module offset
`0x1cccec` is `0x2cccec` in Ghidra, and the round globals at `0xaf1f00` are `0xbf1f00`.

Decompiling `nnMain` (module `0x4f8300` → Ghidra `0x5f8300`) and following its calls is the next step, along
with `xrefs_to` on the round globals. Both need one long-lived session: `open` takes ~4 minutes for the
30 MB module, so a batch script must do the open and every query in a single process.

## First decompiled findings (2026-11-05, eighteenth pass)

With Ghidra open on `re4main.elf` (11,839 functions), `xrefs_to` and `decompile` now answer questions
directly. Three results:

**1. The Mercenaries scoring function — `FUN_002cccc0` (module `0x1cccc0`).**
It takes `(unit, type, flag)`, clamps the type to ≤0x31, indexes a table `(&PTR_DAT_00bf1440)[type]`, reads a
difficulty byte from the game state (`*(byte *)(game + 0x5037)`, clamped to ≤6), multiplies by a float table
(`PTR_DAT_00c26760 + difficulty*4 + type*0x1c`), applies ×10/×5/×2 by mode (`game + 0x503c`), doubles for
low difficulty (`game + 0x84f0 < 2`), and returns **29999** for type 0x2e when `*(int *)(game + 0x984) == 1`.
That is the kill-score routine, and it names the **game-state global: module `0xb25d78`** (Ghidra
`PTR_PTR_00c25d78`) with fields at `0x5037`, `0x503c`, `0x84f0`, `0x984`.

**2. Unit-state code — `switchD_0020844c::caseD_0` (function `0x00213870`).**
Operates on `param_1` as a **unit pointer**: `*(param_1 + 0x4c4) |= 0x100` (flags), `*(char *)(param_1 +
0x116)` (state: 0/1/other), and uses `param_1 + 0xb4`, `+0xa4`, `+0x3d0` as vectors passed to
`FUN_005e0cb0`, plus a pointer at `+0x428` whose `+0x8c` is read. This is the per-unit state machine, so the
unit structure's field offsets are now readable from code rather than guessed from memory.

**3. The jump table at `0xaf1440` is a score/parameter table**, not a unit list — consistent with the
round-12 finding, now confirmed by the decompiled index expression.

**Next:** `xrefs_to` the function that *contains* the switch (`FUN_0020844c`) to find the caller that loops
over units — that caller holds the unit list, which is the missing `S_ENEMY`. Then read the list's stride and
count off the loop, and the driver can be written against code-derived offsets.

## Following the game state (2026-11-05, nineteenth pass)

- `xrefs_to 0x00c25d78` (the game-state global, module `0xb25d78`): **40 readers** — this is the live
  manager everything consults, not a dead table.
- `xrefs_to 0x0020844c` (the unit-state function): **0 xrefs** — it is reached indirectly (through a vtable or
  a switch), so a call-graph walk cannot reach its caller that way.
- Decompiled `FUN_00417870` (first game-state reader): C++ object code with vtable dispatch
  (`(**(code **)(*plVar4 + 0x90))()`), fields on the object at `+0x544` (flags), `+0x656`, and sub-objects
  reached through `param_1[0x127]` (`+0x938`), `param_1[0x128]` (`+0x940`), `param_1[0x12a]` (`+0x950`),
  `param_1[0x12e]` (`+0x970`). The `+0x938` sub-object also appears in the score function, so it is a shared
  manager handle rather than a per-unit field.

**Next static lead:** `xrefs_to 0x002cccc0` — the **score function's callers**. A kill-scoring routine is
called for one unit at a time, so its caller is exactly where the unit list is walked. That is a single,
well-defined query, unlike continuing to follow vtables.

## A unit table and the health offset, read off the code (2026-11-05, twentieth pass)

`FUN_004cd1c0` (Ghidra `0x004cd1c0`) is the damage routine, and it names both things the memory scans
could not pin down:

```c
lVar5 = *(long *)(DAT_0136a400 + param_3 * 8 + 0x10);      // unit table: stride 8, +0x10 bias
if (lVar5 != 0 && FUN_002b1950(lVar5) == 1) {
  iVar4 = FUN_002cccc0(lVar5, *(byte *)(lVar5 + 0x3ce), 0);  // damage by unit type
  iVar4 = *(ushort *)(lVar5 + 0x3c2) - iVar4;               // HEALTH at unit+0x3c2
  *(short *)(lVar5 + 0x3c2) = (short)iVar4;
  if (iVar4 * 0x10000 < 0x10000) {                          // died
    *(undefined2 *)(lVar5 + 0x3c2) = 0;
```

So: **health is a `ushort` at `unit+0x3c2`**, type is a byte at `unit+0x3ce`, and units are addressed through
`DAT_0136a400` (module `0x126a400`) at `+0x10 + index*8`.

**Caveat, verified:** in a live Mercenaries round that table reads **all zeros** (0x30 bytes, twice, with the
screenshot confirming `MISSION START` and a running clock). The same function also calls
`FUN_003809e0(..., "D:/Prj_ESUFOUR/Trunk/project/esufour/code/src/flag_rsf.h", 0x22)` — a flag/RSF subsystem,
so this table most likely belongs to a scripted mode rather than Mercenaries.

**Testable consequence:** if health is `unit+0x3c2` and the memory-measured health is at `position-0x2478`,
then the unit base must be `position-0x283a`. Reading that base and checking `+0x3ce` (type), `+0x116`
(state), `+0x4c4` (flags) and `+0xa4`/`+0xb4` (vectors) verifies or kills the whole layout in one run — it was
attempted but the round had ended, so it is the first thing to do next.

## The cross-check failed (2026-11-05, twenty-first pass): memory fields vs code layout

Test as planned: with a round confirmed live (`MISSION START`, `01'59"10`), read the implied unit base
`position−0x283a` and check the fields the decompiled code actually uses:

| field from code | expected | read at `position−0x283a` |
|---|---|---|
| `+0x3c2` ushort (health) | 1336 | 1336 — **circular**: `0x283a = 0x2478+0x3c2`, so this is the same field by construction |
| `+0x3ce` byte (type) | ≤0x31 | 36 (plausible) |
| `+0x116` byte (state) | 0, 1 or 2 | **79** — impossible |
| `+0x4c4` uint (flags) | non-zero bits | **0** — impossible |
| `+0xa4`, `+0xb4` vec3 | position-ish floats | **0, 0, 0** |

So the two pictures disagree. Either the struct base is not `position−0x283a`, or — more likely — **the field
I have been calling the player's position is not a unit field at all**. That matters: the "health at
`position−0x2478`" finding rests on the same assumption, and its single observed drop (1336→1054) may have
been coincidence. Position, facing and health all need re-derivation against the code's unit layout rather
than the other way round.

A structural scan for unit-shaped objects (health `+0x3c2`, type `+0x3ce`, state `+0x116`, flags `+0x4c4`,
8-byte aligned, 2 GiB of resident heap) returned only table noise — regular arithmetic runs such as
`hp = 4, 8, 12, …` with `type = 0x0a, 0x0e, 0x12, …` — so that signature is not selective enough either.

**What would settle it in one step:** a write watchpoint on the position field. It answers "which code writes
this" directly, which is exactly what the static route cannot do here because the writer is reached through
vtables and no xref points at the field. That is the next instrument to use, even though it is not static.

## Unit enumeration found in the accessor (2026-11-05, twenty-second pass)

`FUN_001068a0` (Ghidra `0x001068a0`, containing the `ldrsh w9, [x0, #0x3c2]` at `0x6974`) is a **list walk**,
and it is the clearest unit-enumeration shape found so far:

```c
uVar5 = *(ulong *)(param_1 + 0x78);            // list head, on a manager object
while (uVar5 != 0xffffffffffffffff) {          // -1 sentinel
  puVar8 = (ulong *)(uVar5 & 0xfffffffffffffffe);   // tagged pointer: bit 0 is a tag
  if ((uVar5 & 1) == 0) {
    if (((uint)puVar8[5] >> 5 & 1) != 0) break;     // node flags at +0x28
    lVar4 = *(long *)puVar3;                        // PTR_DAT_00c25d88
    if ((0 < *(short *)(lVar4 + 0x3c2)) && ...)     // health gate, code-derived offset
  }
  uVar5 = FUN_00106c10(lVar4, puVar8);              // advance
}
```

So the units are an **intrusive singly-linked list**: head at manager `+0x78`, nodes reached through a
**tagged pointer** (low bit masked off), terminated by `-1`, each node carrying flags at `+0x28` and a byte
class at `+0x1b` (compared against `0xf` and the mask `0x4016`). That is what to walk live to get
`snapshot()['enemies']` — no scanning required.

**Inconclusive live check:** `PTR_DAT_00c25d88` (module `0xb25d88`) resolved to `base+0xafb398`, i.e. a
*static singleton in module data*, with `+0x3c2 = 0`. That was read with no round running, so it neither
confirms nor disproves that the same offset is a unit's health; it does say the global is a manager, not the
player. Repeating the read **during a round** (expect a non-zero `+0x3c2`) is the next check, together with
walking `manager+0x78` and printing each node's `+0x28` flags and `+0x1b` class.

### Disproved: the list is not at `game_state + 0x78` (2026-11-05, twenty-third pass)

Tested in a live round: `game_state = *(base+0xb25d78) = 0x3ca871ee08`, and `*(game_state+0x78) = 0x3ca8100930`
— which is **inside the module's text** (`base+0x4fc930`), and the word it "points" at is ARM64 code
(`0xd65f03c02a1f03e0`). So the object the accessor walks is *not* the game state; `+0x78` is a code pointer
here, not a list head. The accessor's `param_1` is a different manager whose pointer is still unknown.

Method note: the walk first failed with "no main" because **two Citron instances** were running (one left on
the game list by an earlier experiment) and the script took the first pid. Any probe must select the process
whose command line names the title (`010099a00bc1e000`), not just `AppDir/bin/citron`.

## Units found by vtable (2026-11-05, twenty-fourth pass) — the class anchor

Following the score routine's callers: `FUN_0018f470` is called **only through a DATA slot** at module `0xae7078`,
so it is a **virtual method**. The pointer run around that slot is a vtable:

```
vtable 0xae7050 .. 0xae71a0  (43 slots)
  [0] 0x8eba0   [1] 0x8ef90   [2] 0xb290   [3] 0xb2a0
  [4] 0x2b6420  [5] 0x8f470 ← FUN_0018f470 (health +0x3c2, target +0x82c)
  [6] 0x8efa0   [7] 0x8e980   [8] 0x8e9a0  ...
```

So an instance's first word is `base + 0xae7050`. Scanning the guest arena for that value in a live Mercenaries
round (7.28 GB over 218 regions) found **10 instances = 5 objects, each visible through two shared mappings**:

```
0x005d55a77ad0 hp=1800 type=0x00 state=1 target=0
0x005d55a78b98 hp=1400 type=0x00 state=1 target=0
0x005d55a79c60 hp=1800 type=0x00 state=1 target=0
0x005d55a7ad28 hp=1400 type=0x00 state=1 target=0
0x005d55a7bdf0 hp=1800 type=0x00 state=1 target=0
```

Health reads 1800/1400 at exactly the code-derived `+0x3c2`, which corroborates both the offset and the class.
**This is the unit access path the driver needs** — no table indexing, just the vtable identity.

Next: (a) tell the player apart from the Ganados (position/heading within the object, or the object the camera
follows), (b) confirm the mapping duplication so a scan does not double-count, (c) then write `snapshot()` with
`player` + `enemies` from this scan, which is what `playable: True` needs.

### The driver now enumerates units (2026-11-05, twenty-fifth pass)

`gbox/mercs/titles/re4_switch.py` gained a real unit path:

* `VTABLE_OFF = 0xAE7050`, `UNIT_HP/TYPE/STATE = 0x3C2/0x3CE/0x116`.
* `RE4Switch.units(m)` scans the guest regions in 16 MiB chunks for `base + VTABLE_OFF`, keeps objects whose
  first word is that vtable, and caches the addresses; later calls only revalidate the cached ones, so a
  snapshot does not rescan the arena.
* `snapshot(m)` returns `units: [{addr, hp, type, state}]` alongside the engine's usual keys.
* Duplicate mappings are collapsed by an object-content fingerprint. **0x80 bytes was too narrow** — a fake-arena
  test showed two distinct units with identical leading bytes being collapsed into one; 0x600 bytes fixed it
  (2 units, hp 1800 and 1400, and the cache path verified).

Verified with a fake memory arena (scan, snapshot, cache). Not yet verified against a live adapter, and two
pieces are still missing before `playable: True`: **which unit is the player** and **the round timer**.

### Live verification of the driver snapshot (2026-11-05, twenty-sixth pass)

`RE4Switch.snapshot()` was run against the live game through a shim exposing exactly the driver's memory
surface (`regions()`, `read_memory()`) — so the verified code is the driver's, not a probe's:

```
main 0x003ca7c04000  snapshot units: 5
  unit 0x005d55a77ad0 hp=1800 type=0 state=1
  unit 0x005d55a78b98 hp=1400 type=0 state=1
  unit 0x005d55a79c60 hp=1800 type=0 state=1
  unit 0x005d55a7ad28 hp=1400 type=0 state=1
  unit 0x005d55a7bdf0 hp=1800 type=0 state=1
second snapshot (cached): True
```

**Two dedupe bugs were found by testing, not by reading code:**

1. An 0x80-byte fingerprint collapsed two distinct units whose leading bytes matched (found with a fake arena).
2. Widening it did **not** collapse the arena's duplicate views, because those are *separate copies*, not one
   physical page — their pointer words differ. The identity is the unit's own id at **`+0x110`** (distinct per
   unit: 32, 34, 36, 38, 40), so dedupe uses `(+0x110, hp, type)` and the count came out right: **5**.

Still missing for `playable: True`: which of the five is the player, and the round timer.

### Class census: which objects carry health (2026-11-05, twenty-seventh pass)

Scanning 7.29 GB for objects whose first word is a module-data pointer (a vtable), then reading `+0x3c2`:

| vtable (module) | objects | `+0x3c2` values |
|---|---|---|
| `0xaed3b0` | **26** | all 1000 |
| `0xae8b10` | 12 | all 1000 |
| `0xaed470` | 12 | all 1000 |
| **`0xae7050`** (ours) | 10 (=5×2) | **1800 / 1400, varied** |
| `0xaee5e0` | 8 | all 1000 |
| `0xaf91b8` | 6 | 53, 57, 61 … |
| others | 2–6 each | mixed |

Two readings matter:

* Our class (`0xae7050`) is the **only one with varied, unit-like health** (1800 / 1400) — but its five objects never
  lost a point over 24 s with Ganados closing in, and their `+0x82c` target stayed null, so they are **not the
  active combat units**; they belong to some subsystem that reuses the same base layout (or an inactive group).
* `0xaed3b0` has **26 objects at exactly 1000**, which is the right order of magnitude for a Mercenaries crowd.

So the class identity is a *family*: many classes share the `+0x3c2` health slot because they inherit the same
base. The discriminators must be behavioural (who moves toward the player, who loses health when hit), not
structural.

### Correction: `0xae7050` objects are spawn markers, not live units (2026-11-05, twenty-eighth pass)

The class carries a position at **`+0x4d0`** (a copy at `+0x4dc`), and one object sat at `(-3540, 190, 5880)` —
the spawn neighbourhood. But holding `w` moved **none** of the five, and their coordinates are spawn-shaped
(`7830,1190,23050`, `12770,1190,16720`, `1180,190,-1980` — large round values, several pairs sharing `y`):

| unit | id | hp | position (+0x4d0) |
|---|---|---|---|
| `0x5d55a77ad0` | 32 | 1800 | `(-3540, 190, 5880)` |
| `0x5d55a78b98` | 34 | 1400 | `(7830, 1190, 23050)` |
| `0x5d55a79c60` | 36 | 1800 | `(-4020, 190, -6930)` |
| `0x5d55a7ad28` | 38 | 1400 | `(12770, 1190, 16720)` |
| `0x5d55a7bdf0` | 40 | 1800 | `(1180, 190, -1980)` |

So these are **spawn/marker definitions** with a health-shaped field, not the characters. `RE4Switch.units()`
currently returns them and must **not** be treated as enemies; it needs retargeting to a class that moves.

Also unresolved: in this run the `w` press moved nothing *anywhere*, so input delivery itself needs a
screenshot-verified check before the next motion test is trusted.

## SAVEDATA (for the "Unlock on load" ticket)

The title's save is reachable and editable, which is what the inbox ticket *"Unlock on load: Resident Evil 4"*
needs:

```
…/nand/user/save/0000000000000000/<account>/010099A00BC1E000/SAVEDATA000/savegame00.sav   1,047,200 bytes (0xFFAA0)
…/SAVEDATA000/ExtraData0, ExtraData1                                                       512 bytes each
…/SAVEDATA000/savegame00.sav.fresh-bak                                                     an untouched backup
```

* the file is **zeros until `0x1e40`**; the progress data begins at **`0x1e43`**
* diffing the current save against `fresh-bak` gives **32,448 differing bytes in 274 runs** (largest runs at
  `0x1e43`, `0x1ebc`, `0x1fa8`, `0x2218`, `0x239c`) — this is the region a game writes as it progresses
* **no simple checksum**: none of `u32@0x30/0x20/0x10/0x00` equals a word sum from `0x34/0x40/0x20/0x10/0x04`,
  so RE4 does not follow RE6's `SAVE_CHECKSUM=0x30 / SAVE_SUM_FROM=0x34` convention. A checksum (or a
  signature/MAC) must be located before any edit, or the game will reject the save.

`gbox/switch_saves.py` is the reusable part: it finds a title's save files, snapshots the largest with a hash,
and reports exactly which byte runs differ between two saves — verified above (RE4 4 files, RE5 8, RE6 13).

## Still missing before MercMode can play it

`gbox.re_switch.preferred_spec` returns the Switch spec with **`playable: False`**, so MercMode will not
rotate RE4-Switch however `preferred_editions` is set — by design ("the selected edition stays visible
and never falls back silently"). To make it playable:

| field | what it feeds | status |
|---|---|---|
| round clock | `screen()`: playing / ended | **found** (above) |
| player position | `snapshot()['player']` | **found**, confirmed spawn-fixed |
| facing | steering, aiming | **found** (unit sin/cos pair; offset to the position still to anchor) |
| health | `snapshot()['player']['hp']` | **found** (`int16` at pos − 0x2478; freed at death) |
| live Ganado list | `snapshot()['enemies']`, the bot's target choice | not measured |
| score / kills | `snapshot()['kills']`, round progress | not measured |
| module base / signature | every read, and the hooks | **done** (below) |

Then `re4_switch` needs `snapshot()` / `screen()` implemented (it is a skeleton returning empty), a
signature that re-finds the structs after ASLR (the RE6 map in `docs/research/re6-switch-ram.md` does
this by dumping `main` with Citron's `dump_nso` and scanning for 64 read-only bytes), and only then
`playable: True` plus `preferred_editions: {re4: switch}` for the host.

The next measurement is the **player**: with the clock found, a round can be sampled at two known
times while the player is stationary and then moved, and the position triple that changes by the walked
distance is the player's. Enemies follow from the same struct family (the GC driver's `re4_threats`
shows the shape to expect, but not the offsets).

## Player: candidates (measured 2026-11-05, second pass)

Method that works: **stand, walk forward, back, forward, back** (1.5 s each, four samples), then keep
triples that (a) sit away from the origin and keep their scale — `hypot(x, z) > 300` and within ±50 %
across samples, (b) move 80..800 units on each forward step, (c) return within 35 units on each back
step, and (d) move mostly horizontally.

Two lessons from the passes that failed:

- **A triple that collapses to ~0 at rest is a velocity, not a position.** The first filter ("moved and
  returned to its start") matched 69 k of them, because a velocity is ~0 standing and large while walking,
  so "returned" is trivially true. The near-origin test is what separates them.
- **The player and the camera on him are 80–160 units apart, at foot and chest height.** The best pair,
  captured at spawn before any input:

  | address (this boot) | A = (x, y, z) | steps fwd | returns |
  |---|---|---|---|
  | `0x005d559cadf0` | `(-3586.7, 133.8, 6056.5)` | 119.8 / 161.0 | 8.2 / 11.7 |
  | `0x005d559cafe0` | `(-3668.2, 40.9, 6021.7)` | 114.9 / 156.6 | 1.6 / 2.4 |

  They sit 128 units apart, both track the walk, and their heights differ by ~93 units — the shape of a
  player position and the camera/head above it, not two independent entities. Addresses move every boot.

**Confirmed 2026-11-05 (third pass).** At a fresh boot the low triple reappeared at exactly
`(-3668.2, 40.9, 6021.7)` — three copies 12 bytes apart (`0x005d559cafe0`, `…cafec`, `…caff8`), i.e. a struct
holding consecutive position triples — while the *camera's* triple from the previous round did **not**
recur. A value fixed at spawn while the camera settles differently is the player, not the camera. So:

- **player position = the low triple** (feet/ground height, y ≈ 41 at spawn), struct at
  `0x005d559cafe0` on this boot with copies at `+0xC` and `+0x18`;
- the higher triple (y ≈ 134) is the camera/head that follows him.

The host addresses came out the same in consecutive boots (`0x005d559c…`), unlike the clock's
`0x3ca8e78…` which is reached through the guest heap: do not assume either is stable — the driver must
re-find both (that is what the signature in "Still missing" is for).

Walk displacements measured in the same run (RE4 is tank-controlled: `a`/`d` **turn**, `w` walks):
strafe-turn 47 units, forward 121 units, the two vectors anti-parallel in world space — expected after a
90° turn, and consistent with the same struct being moved by input rather than by an animation.

**Not yet measured:** facing (the turn is what would give it), health, and the Ganado list.

### Fourth pass (2026-11-05): identification by walking displacement, and what it did not give

Picking the candidate by **walk displacement** works and is worth keeping: over a 0.8 s walk the player's
family moved **147.94 units** in three separate boots, while the closest decoy moved 4110 (a camera-like
smoothing value) and was rejected. Match on 60–400 units, not on turn response — a first attempt that
scored candidates by turn-change picked a junk object whose walk delta was 8×10⁹.

Windows dumped around the family (`…bafe0`, 48 KiB each) at still / after a left turn / after a right
turn / after a walk / two damage samples gave **no clean facing angle**: the only floats that moved with
the turn are small (|d| ≈ 0.25–0.4, many of them, similar for both directions) — the shape of smoothed
camera/animation values, not a raw heading. Possibilities to test next, in order: heading stored as a
sin/cos pair (`d` up to 1.0 on each, related by the angle), a packed 16-bit angle (turn left 0.6 s ≈
1.4 rad ⇒ ~4 500 units of a 0..65535 turn), or a heading outside the 48 KiB window.

**Health:** no int16 in the window fell across two damage samples — either no damage landed in that round
(the player stood behind the fence) or health is not a small int16 here. Next: read the HUD-adjacent
values while deliberately taking hits, and check float and int32 shapes too.

**Lesson for the next measurements:** identify the player by walk displacement, keep his window from
several boots, and diff *between* boots as well — the family's address is not stable
(`0x005d559c…`, `0xfea03e5b…` seen), so the driver must re-find it by the spawn triple every round.




## Round 99 (2026-11-05): RE4 boots under Citron, and the game-state global is only live in-game

**RE4 is launchable and renders on the Spark.** After `mercmode op=prepare` (the ROM-access receipt expires after
30 minutes - `valid_preparation` allows `0 <= now-checked <= 1800`), the inventory reports `re4 playable=True`. A
launch with catalog id `270a15eb98dab4d7` came up under **citron** and the captured frame held steady at brightness
58.5-58.7 for two minutes. So the decryption, the launch path and the video capture are all fine for this title; what
is missing is the bot's ability to drive its menus, not the emulator.

**The pointer-to-pointer lead is real but empty at the title screen.** Reading 32 bytes at module+`0xc25d78` through
`POST /api/decrypt-lab/scan {mode:"module"}` returned eight zero cells (module base this boot `0x3ca7c04000`). That is
the expected result *outside* a round: the global is populated once the game state exists, which is exactly what the
driver needs it for.

**The ordering problem:** no anchor means `Bot.tick()` cannot drive, and no driving means no round, so no anchor.
Breaking it does not need the anchor - it needs pad presses through the menu chain (title -> main menu -> Mercenaries
-> character -> stage -> start), which gBox can send without a RAM map. Boot control can then take over from the
round's own start, and the global gets sampled while it is live.

## Round 101 (2026-11-06): RE4's blocker is input at the emulator, not the RAM map

RE4 boots and renders under **citron**, and `mercmode prepare` makes it `playable=True`. What fails is *input*:

- `session_op {op:"send_input"}` reports `{"sent": 6}` and `succeeded` - no keys skipped - while the captured frame is
  byte-identical (`diff 0.00`) before and after.
- citron's window **is** focused (`xdotool getwindowfocus` returns the same window id on display `:100` before and
  after activation), so this is not the RPCS3 "no focused window" failure.
- its keyboard bindings are the same as eden's, field order aside:
  `player_0_button_a="toggle:0,code:67,engine:keyboard"` vs eden's `"engine:keyboard,code:67,toggle:0"` - identical
  codes (a=67, b=88, plus=77) and engine.
- even a **window hotkey** never arrives: `xdotool key f11` on citron's own display changes nothing (`diff 0.25`, the
  idle animation), and neither does a pad press afterwards.

So no XTEST key reaches citron at all, while the same paths drive eden (the RE5/RE6 bots play through them). The
difference is inside the emulator's input plumbing on this host, not in gBox's key table, focus handling or bindings.

**Next step:** bypass X focus entirely with the virtual pad gBox already has for exactly this case - `gbox/vpad_linux.py`
(uinput), whose header says xdotool/XTEST "has no focused window to land on" for emulators that read a real device.
That is also the honest reason the RE4 anchor (`module+0xc25d78`) still reads as zeros: no input, no round, and the
global only exists once gameplay does.

## Round 102 (2026-11-06): three input paths tried, none reaches citron

| path | result |
|---|---|
| XTEST to the focused window (`xdotool key`, window activated first) | frame unchanged (`diff 0.04-0.25`) |
| XTEST targeted at the window (`xdotool key --window <id>`) | unchanged (`0.38`) |
| a real **uinput keyboard** (evdev device, so SDL cannot dismiss it as synthetic) | unchanged (`0.26`) |

The uinput device itself was created successfully - the first attempts failed with EINVAL because `uinput_user_dev`
must be its full size (80 + 8 + 4 + 4*(64*4) bytes with the abs arrays); after fixing that the kernel accepted it.

Window survey on citron's display `:100`: the Qt shell is `1280x720` ("citron Nightly | ... | resident evil 4"), the
render surface is also `1280x720`, and the several `citron-neo: The switch fell off` children are `1x1`/`853x1`/`853x24`
- none of them receive key events, and neither does the 1280x720 pair.

So citron on this host accepts no keyboard input from outside: not synthetic X events, not a real evdev device. The
next thing to inspect is the emulator's own video/input backend for this launch (`SDL_VIDEODRIVER` in its environment,
and whether Qt/SDL sets its "active" state without a window manager on the Xvfb display) rather than gBox's key path,
which is proven on eden.
