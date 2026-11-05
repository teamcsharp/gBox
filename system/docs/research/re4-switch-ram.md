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

## Still missing before MercMode can play it

`gbox.re_switch.preferred_spec` returns the Switch spec with **`playable: False`**, so MercMode will not
rotate RE4-Switch however `preferred_editions` is set — by design ("the selected edition stays visible
and never falls back silently"). To make it playable:

| field | what it feeds | status |
|---|---|---|
| round clock | `screen()`: playing / ended | **found** (above) |
| player position, facing, health | `snapshot()['player']`, walking and aiming | not measured |
| live Ganado list | `snapshot()['enemies']`, the bot's target choice | not measured |
| score / kills | `snapshot()['kills']`, round progress | not measured |

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



