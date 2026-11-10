# PSO lane — hand-off brief (2026-11-10, i9-NUC)

Whoever picks this up: everything below was measured on the live `GPOE8P` disc and the i9-NUC, and every claim names the
evidence. The lane doc (`docs/ds-pso-lane-2026-11-10.md`) has the round-by-round record; this file is the state, the
blockers and the next steps.

## Where the objective stands, package by package

| package | state | evidence |
|---|---|---|
| **P2** decode every disc format + per-area catalogue under `docs/research/` | **done** | `docs/research/pso-gc-areas.md` (72 areas, 1,000 files, 784,070 triangles, 18,785 placements, 0 decode failures), `pso-gc-formats-{containers,models,textures,tables}.md`, `pso_setdata`/`pso_areas` with round-trip tests |
| **P2b** executable mapped with `pso_ram.py` | **done for what P1/P3-P5 needed**; one open address | `docs/research/pso-gc-executable.md`, `gbox/pso_ram.py`; `0x8028f508` (the model-walk crash from round 35) is not yet identified |
| **P1** boot to the field by real presses | **boot to town: done. Field: blocked** | six frame-verified presses to Pioneer 2 (`pso_boot_walk.BOOT_STEPS`); MULTI MODE two-player co-op; **no route to Forest 1 found** — see "P1 is the blocker" |
| **P6a** map writer | **done and proven in game** | `gbox/pso_map_write.py` + round trips; `pso_editor` + CLI; a moved placement is read back from the running game: `TObjCityDoor_Guild` at **(235.0, 173.0)** after the writer moved it from (185,173) — see round 49 |
| **P6b** editor page | **backend done, no page** | `gbox/pso_editor.py` (+8 tests): discovers 574 editable sets, lists records, normalises edits, previews, builds |
| **P7a** player-model writer | **builds models; swap rigging not done** | `pso_player.build` runs end to end on this disc (7 meshes, skeleton, 7 GVR textures); `pso_gc_paths` + NJCM endianness fixed |
| **P7b** hot swap | **visible, not correct** | a HUcast body inside a HUmar pack renders deformed; a HUnewearl body **crashes** at `PC 0x8028f508`. `gbox/pso_swapfit` predicts which (`pso_swapfit.compare`) |
| **P3-P5** traversal, bosses, campaign | **not started** | blocked on P1's field leg |

## P1 is the blocker, and here is exactly why

Boot to Pioneer 2 is reproducible. Two players in the city is reproducible. Movement is reproducible. What is missing is a
way to the surface:

* the **single-player intro conversation cannot be exited** — retested with the keyboard walker (round 37), 20 A presses at
  2.2 s, and movement attempts inside the `mode 17` gaps: all negative. It shows as `mode 5` alternating with `17` and no
  player movement. The **skip-button sweep** (round 45) closes the rest of the controller: `Y`, `X`, `Z`, `B`, `L`, `R`,
  `START`+`A`, `A`+`START`, `BBB`, and 30 s of no input all leave the mode at `5`. Whatever ends that scene, it is not a
  button.
* **none of rooms 10, 20, 30, 40 has a counter that answers `A`** — the guild has not been found, and the city's room
  graph is mapped in `docs/research/pso-gc-pioneer2-rooms.md`.
* every other candidate for leaving the city has been ruled out: the room-40 teleporter pad (nine positions, `A`, a
  2.5-unit approach, both players present), the lobby pedestal (decorative), `TObjCityDoor_Guild` (inert).

**Next concrete steps for P1**, in the order I would try them:

1. Walk **through** the central dome's large doorways rather than past them (a doorway is a volume; several passes went
   beside the opening). The dome is around `(157,102)` in room 20.
2. Explore **room 30 beyond its entrance** — entered at `(-169,46)`, walked only to `(-236,18)`.
3. Look for the guild in the executable: the quest/teleport code path would name the room id it requires. `0x8028f508`
   is already an open P2b address; the quest state machine is the other.

## P6a's proof — done (round 49)

The missing measurement was the **room-local to world offset**, and it is `(+228, +291)` for the whole `city00` area. It was
found from the two co-op spawn points (both records + the constant = the spawn positions) and validated exactly: **10 of
`map_city00_00o.dat`'s 28 records land on live entities at distance 0.0** — all four lobby doors, both spawns and every
`TObject` in the room. The door kinds came out of the same match: `0x46` Shop, `0x47` Guild, `0x48` Warp, `0x49` Med.

With that, the proof itself took one boot: `pso_guilddoor_moved` moves the Guild door record from world `(185,173)` to
`(235,173)`, and the running game reports **`TObjCityDoor_Guild` at `(235.0, 173.0)`** while the other three doors are
untouched. `pso_editor.world_position()` shows both coordinate spaces in the editor and its CLI (`list --world`).

Two methods were ruled out on the way, and are worth not repeating: **world-position matching** (no record sits at a city
entity's world position — the spaces differ) and **memory scans from the lobby** (the placement data is not resident as
floats there; the scanner itself was validated against the player's coordinates, 4 hits each).

## Live environment state (so nobody has to rediscover it)

* gBox server + worker on **i9-NUC** (`python -m gbox --config gbox.toml serve --worker` from `C:\_tools\gBox\system`);
  bearer token `system/gbox-data/api_token`; worker id is in `D:\gBox\pso-ds\worker.txt`, session in `session.txt`.
* the last session booted `pso_city_npc_moved` and is **parked in the intro** of a single-player boot; the Dolphin window
  needs `win.restore` before any keyboard input, and the in-game menu being open looks exactly like "movement is broken".
* every launch needs **five minutes without operator input**; a pad press resets that clock, which is why verify-a-launch
  rounds cost ~10 minutes of wall clock.
* the launch `mod` is a **query parameter**: `POST /api/games/{gid}/launch?node=<worker>&mod=<build>` — a JSON body field
  is silently ignored.
* helper scripts (not in git) live in `D:\gBox\pso-ds\`: `walklib.py` (two-player movement), `pad.py`/`api.py`/`live.py`/
  `shot.py`/`win.py` (control plane), `pso_demo_rec.py` (operator demonstration recorder), `qi0_scan.py` (the RAM scanner),
  `qk0_offset.py` (the offset search).
* mods built and on disk: `pso_objmove_forest01_l0_r60`, `pso_hotswap_humar_to_hucast`, `pso_hotswap2_both`,
  `pso_hotswap_humar_to_hunewearl`, `pso_city_npc_moved` (all under `D:\gBox\cache\mods\436e0bb84d5337d1\`).

## Tests

Green on `main` at hand-off: `test_pso_boot_walk` (10), `test_pso_gc_paths` (12), `test_pso_quick` (7),
`test_pso_editor` (8), `test_pso_swapfit` (7), `test_pso_kbwalk` (12), `test_pso_greedy` (4),
`test_pso_push_through` (3), `test_pso_pad2` (8), `test_pso_explore` (5), `test_pso_write` (6), `test_pso_map_write`,
`test_pso_setdata`, `test_pso_areas`, `test_pso_ram`, `test_pso_entities`, `test_pso_move`, `test_pso_menu_walk`,
`test_pad_bind` (5), `test_pso_coop_pads` (7), `test_pso_player_textures` (6).

## What I would tell the PM in one paragraph

The decode, the writer and the model-build side of this lane are in good shape and tested; the *live* side is where the
time goes, and it is one problem: **getting a party from Pioneer 2 onto the surface**. That has resisted ~20 rounds because
the game hides it behind a conversation that cannot be exited and a guild I have not located; everything else about the
city (its rooms, doors, boundary bands, and the fact that its placement coordinates are room-local) is now documented.
If the next session solves that one thing, P3-P5, P6a's proof and P7b's hot-swap proof all become reachable in a few rounds
each.
