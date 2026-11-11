# Lane-log text of `ds-pso-floor-warp-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `712f4a7f`.

----

## Round 58 (2026-11-10, later session) — the dev floor warp as a mods op (`floor_warp`)

Working locally; no lilspark, no live session.

The PM's plan (DEEPSEEK-PSO-PROGRESS-2026-11-10 §4.3) asked for `gbox.pso_fence.warp_to_floor` to be exposed as a
`pso_mods` op `floor_warp`, "as a development tool" for P6a's in-game proof, P7b's area-change test and the area
survey, with all such evidence labelled "reached by warp (dev)" and never counted for P1/P3/P5.

**Added to `gbox/pso_live.py`:**
* `floor_warp` joins `OPS` (a write op: it asks the game to travel);
* the dispatch runs **before** the GameCube handle is built, so it needs no game state beyond the adapter:
  `target` must be a floor number (`0` is the city, `1` Forest 1, ...), anything else is a `ValueError` ("floor_warp
  needs target=<floor number>"), and a valid one calls `pso_fence.warp_to_floor(ad, floor)` - the native
  `SET_TARGET`/`BEGIN_TRAVEL`/`WARP` path that is already live-verified, not a new mechanism.
* `gbox/pso_mods_tool.py`'s op description names it, with the dev-only caveat inline.

**Tests** (`tests/test_pso_floor_warp.py`, 7): the op reaches `warp_to_floor` with the adapter and floor, floor 0 is
accepted, four bad targets (`""`, `forest`, `-1`, `1.5`) are refused before any travel, and the op-set membership
(`OPS` yes, `READS` no). `test_pso_live`, `test_pso_gc_adventure` and the new file together: **36 passed**.

**What this unblocks in a live window:** the editor's in-game proof and the swap/area experiments can now be reached by
`floor_warp target=N` through the normal tool surface instead of a bespoke script, and the warp is honest about what it
is (a dev shortcut, never P1 acceptance).
