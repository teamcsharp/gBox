# Lane-log text of `ds-pso-steering-tests-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `5773d4be`.

----

## Step: the 4 failing tests in `test_pso_steering_evidence.py` (2026-11-10, branch `ds-pso-steering-tests-20261110`)

The hand-off (`DEEPSEEK-HANDOFF-2026-11-10.md` section 2A: "fix the 4 failing tests in
`system/tests/test_pso_steering_evidence.py` first. They fail on plain main ... Those 4 are yours").

**Why they failed.** They were written against the pre-swarm party model (`44fbc5d9f`, which gave a quiet slot its
own bounded margin connector). The later party change (`589cd8f6`, "P1 is the sole navigator; P2+ are dumb
swarm-followers") gives slot 2 to `swarm_follow` unconditionally, so a follower's steering source is now
`swarm_spread`, `margin_attempts[2]` is never created, and a crowded follower always emits a step-off turn - exactly
the three assertions the old tests made about P2. The margin-recovery path still exists, for **P1**
(`pso_coop.py` call sites 3443/3493/3562).

**The one real defect they exposed - fixed in code.** `test_telemetry_write_failure_never_changes_command_or_tick_result`
was right: a stats view that refuses a write aborted the whole tick (`_observe_boss` writes `st["boss_present"]`
directly, and a dozen more direct writes follow it in the tick's call graph). `pso_coop` now runs the body of
`Controller.tick` on a `_Telemetry` dict - a real dict seeded from the live sink, where a refused key is dropped -
and merges the keys back into the live sink afterwards, best-effort (`Controller.tick` wrapper + `_tick`). A broken
recorder can now lose a number, never a command, a delivery or the tick's result. The test was strengthened to prove
exactly that: two identical controllers, one with a `BrokenStats` sink, must return the same result and send the same
commands, and the live sink must be handed back untouched.

**The tests, re-pointed at the current model** (each keeps its contract, only the slot changes):
- margin tick: the verified connector now belongs to **P1** (`nav_state()` in the test file); the same fields are
  asserted - exact keys/duration `.04`, waypoint `[22.5, 27.5]`, `geometry_layer floor`, `requested_speed 2`,
  before/after pose, the two snapshot reads, the timing ordering and `pre_pose_exact_sample_time_known is False`.
- deferred delivery: `InputDeferred` still propagates, the row is `delivery_interrupted` with no after-observation,
  and the margin bound was not consumed (`margin_attempts[1]['attempts'] == 0`).
- telemetry: see above.
- "held, no movement" became `test_a_follower_at_station_records_no_fabricated_steering`: a follower inside the
  no-action band (`SWARM_SPREAD .. SWARM_FOLLOW_RADIUS`) emits only camera resets, records no steering evidence and
  starts no margin bound. (The tick still returns True because the camera resets are delivered; the contract this
  test pins is the evidence, not that return.)

**Result, measured on the two files, `b49c7e2f` vs the branch:**
`test_pso_steering_evidence.py` + `test_pso_margin_controller.py`: main **17 failed, 6 passed, 1 skipped** -> branch
**13 failed, 10 passed, 1 skipped**. The four are green; no new failure.

**Found on the way, and not mine to change:** `test_pso_margin_controller.py` carries **13** failures on plain main
(not in the hand-off's known-red list). They are the same design drift - P2 margin expectations - plus two P1
combat-recovery cases (`test_missing_projection_never_uses_generic_combat_route`, `test_model_goal_cannot_replace_
known_layout_missing_projection`). They are left untouched so the PSO lane can decide their intent; the count is
identical before and after this branch.
