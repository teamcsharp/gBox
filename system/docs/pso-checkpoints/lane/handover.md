# Lane-log text of `ds-pso-handover-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `448fbe45`.

----

---

# Handover to the RE session — the PSO lane, 2026-11-10 (later session)

Doc-only branch (`ds-pso-handover-20261110`), on main, so this status can be merged without any code branch. Everything
below was measured on the i9, locally, against the owned `GPOE8P` disc image and the Ghidra project at
`D:\gBox\ghidra-pso`; **no live session was touched and lilspark was never contacted** (the hard rule in the hand-off).

## The branches, in merge order

`->` means "stacked on" (the later branch contains the earlier one); `(main)` means it applies to main directly.

| # | branch | commit | what it does | tests measured |
|---|---|---|---|---|
| 1 | `ds-pso-steering-tests-20261110` (main) | `5773d4be` | the **4** red `test_pso_steering_evidence.py` tests: the telemetry bug (`_observe_boss` unguarded write) fixed, tests rewritten to the P1/P2 party model; main 45 failed → branch 41, the diff exactly those 4 | 45→41 failures on the PSO tree |
| 2 | `ds-pso-steer-tests2-20261110` (main) | `275c0bdf` | the **5** red `test_pso_steer.py` tests: `pso_kbwalk.steer_calibrate`/`steer_walk` implemented (points and advances, re-derives the facing from travel, refuses a dead binding or a non-turning hold) | 5 passed; PSO tree 40 failed/1,306 passed (the pre-existing reds, unchanged) |
| 3 | `ds-pso-floor-map-20261110` (main) | `6cb1c828` | **P2b §7.2 solved**: the floor → area/layout resolver (`FUN_80207E88`, two 36-entry tables `0x804C8FC0`/`0x804C9270`); `pso_floor_map` with `derive`/`verify`, `tools/verify_pso_floors.py` PASS on the disc | 7 passed |
| 4 | `ds-pso-floor-editor-20261110` -> 3 | `2be3617f` | the `.bss` floor record explained (environment parameters, not maps) and `pso_editor.sets_for_floor` ("edit Forest 1" by floor id) | 22 passed |
| 5 | `ds-pso-class-registry-20261110` (main) | `a18da08e` | **A3 solved**: the placement class registry at `0x805D3138` (148 named classes; 44 of 60 used ids, **84.4% of placements**); `tools/verify_pso_classes.py` PASS | 13 passed |
| 6 | `ds-pso-editor-page-20261110` -> 5 | `262b117c` | **P6b's page**: `pso_editor_api` (sets/placements/SVG preview/preview/build) + `clients/web/pso-editor.html`, registered in `server.py`; registry labels; a real disc build proven (`verification.verified: true`) | 34 passed |
| 7 | `ds-pso-travel-gate-20261110` (main) | `4b872480` | **A7 first pass**: `SET_TARGET`/`BEGIN_TRAVEL`/`WARP` are unguarded; the 13 callers decompiled; the pad needs a route that is not a vtable | doc only |
| 8 | `ds-pso-vtables-20261110` -> 7 | `e2d5191e` | the vtable convention (first word = registry slot) and the measured absence of the pad's class | doc only |
| 9 | `ds-pso-vtable-census-20261110` -> 5 | `9bf56a16` | the census in code (`VTABLES`/`derive_vtables`/`verify_vtables`) and its correction: **no named placement class is a C++ object** | 13 passed |
| 10 | `ds-pso-sda-20261110` (main) | `28def085` | the small-data bases (`r13 = 0x805CA600`, `r2 = 0x805CFD00`) and `pso_sda.globals_used` (4,803 r13 globals) | 5 passed |
| 11 | `ds-pso-memcard-20261110` (main) | `1438cf10` | **A10 first pass**: the memory-card reader; the lane's card has three PSO entries and **none has data blocks** (why SELECT CHARACTER shows NO DATA) | 6 passed |
| 12 | `ds-pso-floor-warp-20261110` (main) | `712f4a7f` | the **dev `floor_warp` mods op** (PM plan §4.3), refused for a non-floor target, labelled dev-only | 7 passed |
| 13 | `ds-pso-actor-dump-20261110` (main) | `92ee3e4d` | A7's data route is empty (no city event set) and `pso_actor_dump` — the one-call live discriminator for the pad's handler field | 4 passed |
| 14 | `ds-pso-gvr-write-20261110` (main) | `e84af16c` | **A8's texture half**: the GVR writer, RGBA8 exact + CMPR (mean error 0.1 on a disc texture) | 11 passed |
| 15 | `ds-pso-tree-endian-20261110` (main) | `8090217d` | **A8's tree half**: `write_tree(e=">")` reproduces a real 64-node GC body tree | 4 passed |
| 16 | `ds-pso-body-platform-20261110` (main) | `e1abfc4b` | the platform-aware body read/rewrite (same size/tree as the original) | 3 passed |
| 17 | `ds-pso-swap-gc-20261110` -> 14 + 16 | `8e967628` | **A8 wired**: `build_swap(platform="gc")` — big-endian tree/BML, flat part paths, GVR CMPR textures, proven end-to-end with a stand-in for the Blender rigging | 84 passed (with the body/gvr/ninja suites) |

Merge advice: 1 and 2 are independent and unblock the "no new failures" rule (they fix 9 of the PSO tree's reds). 3/4,
5/6, 7/8/9, 14/15/16→17 are the four stacks; 10-13 are standalone small tools.

## What is still missing, and why

- **P1 (the surface)**: the static work is exhausted and documented - the pad is not an object of any named class (no
  vtable), no code compares class names, and the city has no event set. The remaining discriminator is a live actor dump
  (`pso_actor_dump.actor_dump(reader, entities, cls="TObjCity")`), one call in a live window, and after that either a
  hard-coded special case or the Guild quest flow as the only route. **A10's save study is blocked** because the lane's
  card has no save data, so a character has to be created (or a real save supplied) first.
- **P6a's in-game proof** needs a live Forest 1: `floor_warp target=1` now exists for that (labelled dev), and the
  moved-object mod is already built.
- **A8 (hot swap)** needs one real run with Blender for the rigging (Blender is not installed on this machine) plus a
  boot; the fit gate (`pso_swapfit.compare`) is already there and tested.
- **The editor page** needs a `gbox.service` restart to appear at `/pso/editor` (new module + a `server.py` line - the
  RE session's call, not mine).

## Baseline honesty

Every branch's tests are additive except branch 1 and 2, which turn 9 known-red tests green and change nothing else;
`test_pso_steer.py` no longer fails, and the PSO tree's remaining 40 failures are the pre-existing set (unchanged
membership). Where a branch needed another's code it is marked as stacked rather than duplicating it.
