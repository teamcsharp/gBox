# Native inspection plan — RE3 "Operation Mad Jackal" (GameCube, GLEE08)

Status: **research plan (not a RAM map yet)**. No GameCube RE3 address below is asserted as
measured; every RE3 field is a *target to derive*, and is marked `TBD-derive`. The only concrete
addresses quoted are from the **RE4 GameCube** tooling we are told to reuse, and they are cited to
their source files. This document is the reviewable plan artifact requested in ticket #3348; it is
deliberately free of fabricated constants so a later run can execute the extraction and fill the map.

## 1. Scope and target

| field | value |
|---|---|
| request | #3348 — Mercenaries "Operation Mad Jackal" playable in MercMode |
| preferred platform | **GameCube RE3 (Dolphin)** |
| catalog game_id | `2e2acf3bfe6e5fd3` |
| executable revision | **GLEE08** (NTSC-U; to be confirmed from the ISO header) |
| secondary targets | PSX `53dd9167ed1df355`, Dreamcast `b172dc2d23549d59` (deferred) |
| reuse | RE4 GameCube Dolphin RAM tooling (same Dolphin MEM1 model) |

The request is explicit: *"preferred: reuse the RE4 Dolphin RAM tooling."* RE4 GC and RE3 GC share
the same memory architecture (Dolphin MEM1 at `0x80000000`, 32 MiB), so the `DolphinAdapter` /
`DolphinProcMem` / `ram_dump` plumbing is directly reusable; only the field **offsets** differ and
must be re-derived for GLEE08.

## 2. Tooling to reuse (verified, exact)

From `gbox/` on this request's branch:

- `gbox/adapters.py:2291` `DolphinAdapter` — standalone Dolphin; `gbox/adapters.py:2734` wires
  `DolphinProcMem` for RAM mods straight into Dolphin's RAM mapping.
- `gbox/ram_dump.py:47` `SHM_SIZES = {0x80000000: 0x2000000}` — Dolphin MEM1 = 32 MiB at `0x80000000`;
  `gbox/ram_dump.py:150/195` read the whole region in one go through `/proc/<pid>/mem` (Linux/Spark).
- `gbox/debug.py:134` `DolphinProcMem` — Windows Dolphin process-memory view (memory engine path).
- `gbox/re4_merc_bot.py:97-98` the RE4 anchors that prove the model:
  `EMMGR 0x8027DF20`, `P_PLAYER 0x802B9780`, `MERC_TIMER 0x80279308`, `MERC 0x8021392C`;
  player `*0x802B3044` with `+0x94` position and `+0xA4` facing (`re4_merc_bot.py:10`);
  `rd()` = `0x80000000 | (addr & 0x1FFFFFF)` (`re4_merc_bot.py:241`).
- `gbox/mercs/titles/re4_gc.py` — the Driver shape RE3 GC will mirror (`map_id`, `snapshot`,
  `screen`, `brain`, `prompt_source`, `progress`, `frame`).

These are the *template* and *plumbing*. None of these addresses are RE3 addresses.

## 3. Extraction procedure (bounded steps)

1. **Pin the binary.** Identify the owned GC RE3 image for `2e2acf3bfe6e5fd3`, extract the boot
   executable (`boot.dol`, the Dolphin executable that loads into MEM1), and record its **SHA256**
   and the confirmed product code `GLEE08` from the disc header. (Same step the request mandates for
   the Xbox branch: "cite RAM addresses / Ghidra functions with the exact executable revision and
   SHA256.") Use the existing `gbox/build_export.py` / `entity_probe.py` extraction route; do not
   vendor upstream content.

2. **Boot to Mad Jackal, snapshot the RAM.** On the Spark's flatpak Dolphin (2% audio; never
   JAYBUILTFINALE), reach "Operation Mad Jackal" and `ram_dump` the MEM1 at a known screen. Capture
   three differential dumps: (a) title/Mercenaries-character-select, (b) in-route idle, (c) route
   running (timer counting down, enemy on screen). The *diffs* localize the mutable state.

3. **Locate candidate fields by differential search**, not guessing:
   - player position/rotation: f32 triples that move with input;
   - player HP, timer, money (score/point counter), selected character id;
   - enemy slots: a table/array of entity structs whose count changes with nearby zombies
     (mirror RE4's `EMMGR 0x8027DF20` + slot-scan pattern in `gbox/re4_merc_bot.py:307`).

4. **Confirm each candidate live** before it is written to a map: freeze/poke the address and
   observe the HUD/entity change, then record the offset as verified. Only verified offsets enter
   the map; unconfirmed candidates stay in a `candidates:` list, never in the `verified:` map.

5. **Route + unlock:** determine the start path to Mad Jackal (save flag / menu route) and the
   per-character unlock gates (request #1 above). These are separate from the RAM map and are
   recorded as procedures, not addresses, until verified.

## 4. RAM map targets (to derive for GLEE08)

| symbol | meaning | RE3 addr | RE4 anchor (reuse template) |
|---|---|---|---|
| player pos | f32 x/y/z | `TBD-derive` | `*0x802B3044 +0x94` |
| player rot | f32 yaw (facing) | `TBD-derive` | `*0x802B3044 +0xA4` |
| player hp | health | `TBD-derive` | `re4_merc_bot.snapshot` hp |
| enemies | entity table + count | `TBD-derive` | `EMMGR 0x8027DF20` |
| timer | Mercs countdown | `TBD-derive` | `MERC_TIMER 0x80279308` |
| money/score | points | `TBD-derive` | `MERC 0x8021392C +0x28` |
| character | active character id | `TBD-derive` | — (RE4 has no roster id) |

## 5. Combat driver targets (after the map exists)

- Tank-control movement + auto-aim fire (request #2/3): map the pad-read + aim routine for RE3 GC
  (RE4 analog: `GAME_PAD 0x80287E90`, aim routine `0x8014415C`, `AIM_PITCH 0x80218738` in
  `gbox/re4_merc_bot.py`). Derive the RE3 equivalents and record them with the trigger
  (turnaround = stick-down + X, QTE reaction, trick/long/turnaround shots).
- Emulation of the >100-match aim training belongs to the *driver*, gated behind the reviewed map.

## 6. Acceptance checks (the gate before `playable=True`)

1. Extracted binary SHA256 recorded; product code confirmed `GLEE08`.
2. Every address in the final map is **live-verified** (freeze/poke changes the observable state),
   cited to `(GLEE08, sha256=...)`; no `TBD-derive` entries remain.
3. Regression tests: a test that a `Driver` snapshot for RE3 GC returns the mapped fields from a
   canned RAM fixture, plus a test that `re3` entry stays `playable=False` until the map is reviewed
   (guards against fabrication — see below).
4. Route + unlock procedure written as a verified step list.

## 7. Non-fabrication guard (this plan is enforced by a test)

`tests/test_re3_gc_inspection_plan.py` asserts the plan's map has **no unresolved `TBD-derive`**
before any RE3 GC `playable=True`, and that any address committed to a map is accompanied by a
`GLEE08` + SHA256 citation. This is the same honest posture as the existing `gbox/mercs/titles/re3_psx.py`
(`snapshot` returns `{}`, no invented addresses): the entry stays `playable=False` until a reviewed
map lands.
