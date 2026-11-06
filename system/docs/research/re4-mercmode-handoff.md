# RE4 Switch in MercMode: handoff

2026-11-06. The state of RE4 Switch (title id `010099A00BC1E000`) in MercMode, what is proven, and what remains. This is
the document request #8573 asked for; the longer analysis lives in
`RE4 Switch in MercMode what's needed to finish.md` and the corrections in `re4-state-handover.md`.

## Proven, with evidence

| what | evidence |
|---|---|
| The game boots and renders on Citron | sessions on lilspark, frames 960x540, brightness steady 58.5–58.7 at the title |
| **Input reaches the game** | A at the title changed **86.2%** of the frame's pixels within 3 s; `POST /api/sessions/{sid}/input` with send_input rows is the route that works |
| A Mercenaries round is reachable by the documented route | walked with a frame inspected at each step: title → main menu (**cursor starts on LOAD**, exactly as warned) → `ddown` x4 → A → EXTRAS → `ddown` x2 → A → THE MERCENARIES → A x3 → loading → live round (Leon, village, "Eliminate as many Ganados as you can before your evac chopper arrives!") |
| The round is live, not a still | two frames 12 s apart differed |
| The save is safe | `switch_saves` snapshot: 1,047,200 B, sha256 `13908f63f08a791f` recorded before any input |
| Gate 1 fixed: the correct game id | `RE4_GAME_ID` was hashing a filename the library does not hold (`…[010099A00BC1E000].nsp` → `c89d2c2e…`, an id no catalog entry has), so ROM access was verified against a file that never existed and MercMode resolved RE4 to the **GameCube** disc. It now hashes the real path → **`270a15eb98dab4d7`**, pinned by a test. |
| Gate 5: the driver's menu functions | ported from branch `re4-switch-driver-20261104`: `screen` / `step` / `wandered` / `pressed`, `warm_probe`, `RE4Switch`. `screen()` returns inert until the TW scan lands, so it never presses blind. |
| Gate 4: the RAM map scaffold | `profiles/gamedata/010099A00BC1E000-ram.json` with `mercs.ready: false` — present, not claiming to be measured. |
| Not taken from that branch | its `SWITCH_CITRON_TITLES` change (RE4 only); main keeps all three Citron titles |

## What still stands between this and MercMode rotation

The bot has no working senses for this title yet:

1. **Player anchor** — `re4_switch.snapshot()` returns `player: None`, `enemies: []`, `timer: None`, so `screen` can
   never say `playing` and `adopt` can never accept an RE4 round. The lead is `module + 0xb25d78` (a Ghidra address of
   `0xc25d78` **minus 0x100000**; the module ends at `0xb2e738`, so the earlier read of `0xc25d78` was past its end and
   the zeros meant nothing). Health was seen at `+0x3c2` of that object and a measured value was 1336, so the expected
   range `0x1..0x64` is wrong too.
2. **Enemy list** — `units()` returns 5 spawn markers, not Ganados. Best lead: class `0xaed3b0`, 26 objects at health 1000.
3. **Round state** — clock, score and kills are unread; the kill-score routine is located in code (`FUN_002cccc0`) with
   no live read.
4. **Brain** — `Bot.tick()` returns nothing on main; the branch has a first cut that turns with the d-pad, which is item
   select in this game, so it must use `lleft`/`lright` and steer closed-loop (measured turn rates varied 16–42 °/s).
5. **MercMode wiring** — `titles` is `["re5"]` and `preferred_editions` names only re5, so RE4 is neither selected nor
   edition-resolved until those are set (and the ROM receipt lasts 30 minutes, so `prepare` must run near the launch).

## Order to finish it

Steps 2 and 3 of the guide are **done** (save backed up, input verified, route walked to a live round). The rest:

1. Read `module+0xb25d78` during a round and prove the object it points at loses health when shot (widen the range).
2. Find the live Ganado list (candidate class `0xaed3b0`): count rises as Ganados spawn, health falls when shot.
3. Clock by pointer, then score and kills; make `snapshot`/`screen`/`progress` correct through loading, playing, death
   and results.
4. Port the branch `Bot`, steering with `lleft`/`lright` and closed-loop on the measured angle.
5. Turn MercMode on: `ready: true`, flip the playable flag, set `preferred_editions`, `titles = [re4, re5]`,
   `keep_warm = 0`, run `prepare`.
6. Soak: 10 rounds across RE4 and RE5 unattended.

The blocker on 1–4 is the Spark slot: one Switch emulator at a time, and the operator's RE5 rotation is using it.
