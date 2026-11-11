# Lane-log text of `ds-pso-steer-tests2-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `275c0bdf`.

----

## Round 47 (2026-11-10, later session) — the steering model: `steer_calibrate` / `steer_walk` (the 5 red tests in `test_pso_steer.py`)

Working locally on the i9; nothing on lilspark, no live session, no service touched.

`system/tests/test_pso_steer.py` (added in `b024fc1a`) tests `pso_kbwalk.steer_calibrate` and `pso_kbwalk.steer_walk`,
which were **never committed** - 5 of 5 red on main. The PM's plan (`DEEPSEEK-PSO-PROGRESS-2026-11-10.md` §5.A1) lists
them first: "Fix the red tests: your 5 in `test_pso_steer.py`, then the 4 steering-evidence ones."

**Implemented in `gbox/pso_kbwalk.py`**, to the tests' own contract:

- `steer_calibrate(read_pos, hold)` - the steering model, measured: one `up` probe gives the facing and the forward
  speed (`{"speed", "turn_rate", "facing", ...}`); a `left` hold then a second probe gives the turn rate, signed so
  positive is `left`. It **refuses** rather than walks blind: `RuntimeError("the forward binding is dead...")` when
  the probe moves nothing, `RuntimeError("a left/right hold does not turn the character: this is not the steering
  model")` when the second probe's facing is unchanged.
- `steer_walk(read_pos, hold, target, ...)` - points and advances: `left`/`right` turn toward the bearing for
  `|angle| / turn_rate` seconds, `up` advances by the remaining distance (capped at 0.4 s), and **the facing is
  re-derived from the travel each press**, so a turn overshoot or a blocked leg is corrected on the next step. Returns
  `{ok, end, steps, distance, facing, speed, turn_rate, trail}`.

This is the model the round-19 measurement forced (the analog stick never reaches the game, the keyboard arrows are
the only path that moves anyone, and `left`/`right` rotate rather than strafe); the module's older `calibrate`/
`walk_to` press one key at a time and cannot point a character whose target is behind it.

**Tests:** `tests/test_pso_steer.py` **5 passed** (calibration numbers, a target behind the character reached by
turning first, the overshoot corrected, and both refusals). Whole PSO tree on this branch: **40 failed, 1,306 passed,
132 skipped** (`test_pso_steer.py` no longer among them); the 40 are the pre-existing red set, unchanged - the only
file this branch touches is `pso_kbwalk.py` (additive), and nothing else imports the two new functions.

**Together with `ds-pso-steering-tests-20261110`** (the 4 `test_pso_steering_evidence.py` fixes, pushed earlier) this
closes §5.A1's two halves: 9 red PSO tests become green, no baseline failure changes.

**Remaining from the session's reconnaissance, for the next round:** A3 (the object-class registry). Found so far: the
335 `TObj*` name pointers sit in the .data section at `0x805D2600`, which is a **8-byte-stride table of name
pointers** mixing task classes (`TAdADXlogo`, `TBoss1Dragon`, `TLoadCtrl`), 226 `TObj*` names at +0, and 109 more at
+4 - but the door kinds (0x46 Shop / 0x47 Guild / 0x48 Warp / 0x49 Med) do **not** land on the door names at
(va-base)/8, so the class index is not this table's order. No code reference to the section exists in the Ghidra
project (computed offsets), so the reader must be found from the set loader instead.
