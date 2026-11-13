# Day 1 — a bounded, cancellable controller, and what the live audit found

**Scope:** the first sprint in `PSO_ENGINEERING_AND_AUTOPLAY_RECOVERY.md` §11, answering the failures in
`WHY-IT-STANDS-STILL.md`: a branch that can hold the loop for minutes, no watchdog that runs before every branch,
operator takeover that waits for an iteration, and no evidence ledger.

**Result:** the controller exists, is bounded by construction, and is proven twice — by a 26-test suite and by a live
run on the running GameCube session. The live audit also found two things that change the plan: the motion model is
not yet right, and this session's stage-flag array is contaminated, so it cannot produce switch→door evidence.

Code: `gbox/pso_bounded.py`, `gbox/pso_evidence.py`, `docs/research/pso-bounded.py` (runner),
`tests/test_pso_bounded.py`. Nothing here writes memory; the runner has no unlock/warp path at all.

---

## 1. The shape that replaces `endless.py`'s play loop

`Automaton.tick()` has one fixed order, and the order is the point:

1. **operator ownership** — `OperatorGuard` (fresh `operator-playing.flag`, stale after 15 s) is checked *before*
   anything else; on takeover every direction is released and the tick returns `preempted`;
2. **watchdog** — movement (position or heading) and objective progress, before any branch is chosen;
3. **one plan** from the progression policy (`warp > live enemy wave > switch > door > optional container`);
4. **exactly one action**, clipped to the bound, applied through the world adapter with a hard deadline;
5. **post-state**, then the delta, then a hash-chained ledger line;
6. **takeover checked again after the input** — the longest the operator can be ignored is one action.

Nothing calls `walk_to`, `route_walk` or `unstick`. A wedge is four rotating recovery actions, and after that the run
stops with a failure fixture naming the position and the objective — it does not keep walking.

| §9/§6 requirement | implementation | test |
|---|---|---|
| one bounded action per tick | `Bounds(action_s=0.5)`, `Action.clipped` | `test_tick_issues_exactly_one_action_...` |
| detect a branch that overruns | `Automaton._execute` measures elapsed, records `overrun` | `test_a_tick_that_overruns_its_bound_...` |
| takeover before and after every input | two `OperatorGuard.active` checks per tick | `..._before_the_tick_...`, `..._after_an_input_...` |
| watchdog before every branch | `Watchdog.observe` first in `tick()` | `test_a_wedged_character_...`, `..._no_objective_progress_...` |
| no silent looping | recovery budget, per-objective tick budget, failure fixture | both failure tests |
| containers are optional | rank 4, `optional_limit` streak | `test_containers_are_optional_...` |
| switch success is a flag change | `_verify_switch` reads the native array around the press | `test_switch_press_records_...`, `..._changes_nothing_...`, `..._never_changes_a_flag_...` |
| combo verified by HP, not by presses | `ComboSequencer.observe` | `test_a_combo_is_three_spaced_presses_...`, `..._takes_no_damage_...` |
| evidence, not prose | canonical snapshot + hash-chained JSONL | `test_snapshot_is_deterministic_...`, `test_ledger_..._detects_tampering` |

**The switch verifier is the answer to "pressed A, therefore solved".** `_verify_switch` runs after a press, compares
the 576-byte stage-flag array before and after, and only a changed bit marks the switch done. Three presses with no
change end the run with a fixture that names the switch and the distance of every attempt. A world that cannot read
flags never records a success at all.

**Calibration is a first-class step.** `calibrate()` taps each direction once (twice if the first reads dead), records
what actually moved in the ledger, and reports which motion model the session matches. `HANDOFF.md` §5.2 is the
reason: the control loops were written before the primitives were measured, and a 4× over-rotation per correction
produced the zigzag the operator watched for hours.

---

## 2. Offline evidence

```
python -m pytest tests/test_pso_bounded.py -q     →  26 passed
```

The tests drive a simulated world that is adversarial on purpose: key→world directions, a wall that blocks, an enemy
that refuses damage, an operator who takes the pad mid-action, and a world adapter that ignores its deadline. They
assert behaviour, not implementation: one action per tick, no tick over the bound, release on takeover, a bounded
number of recoveries and then a fixture, a switch press with no flag change reported as *no change*, and a ledger whose
tampered line no longer verifies.

One environment note: pytest's `tmp_path` creates its directory with mode 0o700, and on this Windows host that
directory carries a DACL the confined test process cannot even list. The tests use their own `workdir` fixture, so
they run in both the confined and normal environments.

---

## 3. Live evidence — 2026-11-13, session `29d05fb902974b97-dd9c53f0fd8b4d1f`

### 3.1 Ownership (G0)

The open-ended experiment was still running: PID 46320, `python endless.py`, parent already gone, driving the pad
through ~100 `session_op` jobs per three minutes. It was stopped. Afterwards the pad was released and the character
stayed at `(464.7, -279.3)` for three consecutive reads, and the job stream went to zero new jobs. From then on the
bounded runner was the only writer.

### 3.2 Operator preemption, live

A 30 s walk was running; `operator-playing.flag` was written eight seconds in and removed six seconds later. The
runner's log and ledger:

```
[09:05:32]   tick 4: preempted - operator takeover after the input
[09:05:33]   tick 5: preempted - operator takeover
...                                      (ticks 5-8 stood down, no input sent)
[09:05:54] done: ticks 16, overruns 0, ledger 17 entries verified
```

The first `preempted` is the **post-action** check: the takeover happened while the action was in flight, the pad was
released and the tick yielded. That is the half of the requirement the old loop never had.

### 3.3 Boundedness and the calibrated tick

Input jobs cost **0.53–1.22 s** each (20 measured; a `hold` needs two jobs, down then release). State and memory reads
over the RPC channel cost **31 ms**. So the first live run, with `Bounds.tick_s = 1.6`, recorded **19 overruns in 19
ticks** — the scheduler was right to call that a defect, and the defect was in the bound, not the loop. After
calibrating `tick_s = 3.0`, the same walk ticked 16–24 times with **0–1 overruns** per run, one ledger line per tick,
and the chain verified every time (`~26 entries verified`).

Representative run (`D:\gBox\pso-ds\bounded\walk-20261113-090518.jsonl`): 16 ticks, 12 actions, 0 overruns, 0 stalls,
final distance 39.1 units from a target 60 units away, no memory writes, no position writes.

### 3.4 The finding: the motion model is not right yet

Calibration is already earning its place. Five live calibration passes:

| pass | `up` | `down` | `left` | `right` | heading swing, left / right tap |
|---|---|---|---|---|---|
| 1 | dead | (2.36, 1.83) | (2.85, 5.01) | (−2.17, −1.58) | −63°, −158° |
| 2 | dead | (3.82, −0.75) | (3.82, −0.62) | (−0.74, 3.37) | −44°, −165° |
| 3 | dead | dead | dead | (0.95, 4.54) | —, −151° |
| 4 | dead | (−3.71, 1.34) | (−4.95, −3.25) | (−0.60, 1.95) | −88°, +135° |
| 5 | (1.14, −3.81) | (−1.66, 0.56) | (−3.41, 2.96) | (−0.66, −2.32) | −65°, −148° |

Three facts come out of this, and none of them is in the old documentation:

* **the key→world mapping is camera-relative and rotates**, exactly as `pso_kbwalk` says — so a fixed vector table
  is wrong within a second, and the same key can read "dead" against geometry;
* **a tap can rotate the character by 60–170°**, not the documented 8–11°. Either the reported `heading_deg` is not the
  character's facing, or a tap is not the primitive the old measurement assumed. This must be resolved by a dedicated
  measurement before any steering loop is tuned further;
* **a single tap is not enough to declare a key dead** (pass 4 has `up` moving after pass 1 called it dead); the
  calibration now takes a second sample and picks the better one.

The controller's structure does not depend on which model wins — motion is one bounded action per tick either way —
but its convergence does, so the runner currently keeps the heading model (the one that measurably closed 60.8 → 9.5
units) and the vector model stays in the library, tested, for a build whose keys are fixed.

### 3.5 The finding: this session cannot produce switch→door evidence

Read of the native array `0x80515CC8`, 18 groups × 32 bytes (`D:\gBox\pso-ds\bounded\flag-audit-20261113-090602.json`):

```
floor pointer 0x805D5FC0 = 1        player.room = 8
group 0: 256/256 bits set           group 1: 256/256           group 2: 256/256
groups 3..17: 0/256
```

Groups 0–2 are *entirely* `0xff`: the old loop's `unlock_floor` / `open_all_gates` wrote a whole 32-byte group for
every floor it visited. Every gate on three floors is open, so a press that appears to "open" a door here proves
nothing — and a press that changes nothing cannot be distinguished from a switch whose flag was already set.

There is also a reporting bug worth fixing while this is fresh: the play loop logs
`AUTO-UNLOCK: door within 45 units - flipping floor 8 stage flags` using **`player.room`** as the floor, while
`unlock_floor` itself reads the native floor pointer (`1`). The write went to the right group; the log named a
different one. That is exactly the pre-state → action → post-state mismatch the mandate says to eliminate.

**Consequence:** G3 (switch causality) and G6 (floor clear) need a **fresh session** — no `open_all_gates`, no
`unlock_floor`, no automatic arming — and the flag array must be read before and after every interaction. This is the
first task of the next round.

---

## 4. What is not done, stated plainly

* **The motion model is not solved.** The character moves and the loop never blocks, but a 60-unit walk ends 39 units
  away rather than within 8. The next step is a dedicated primitive calibration (open ground, ten samples per key,
  single tap versus a five-tap batch) and then either a corrected heading model or a per-tick re-calibrated vector
  model — not another steering algorithm written from guesswork.
* **No switch→flag evidence in this session** — see 3.5. The verifier is implemented and tested; it has nothing clean
  to verify against.
* **No combat evidence.** The sequencer is implemented and tested; this room has no enemies (the live profile shows
  one enemy on the floor, out of reach).
* **G1/G4–G8 are untouched.** No acceptance gate is claimed.

## 5. Next round (in order)

1. **Fresh session without global writes.** Relaunch, drive the menus, and confirm `groups_set_bits` is all zero
   except the city's own flags before leaving town. Record the array as the session's opening state.
2. **Primitive calibration on open ground.** Per key: five single taps and one five-tap batch, positions and heading
   before/after; publish the distributions. Decide the motion model from that table.
3. **One switch→flag→door chain.** Nearest `TLazerFenceSw`, bounded approach, press, flag read before/after, then walk
   the linked door and record the room change. Failure means a fixture with the distances.
4. **Wire the same evidence into the combo path**: action-state at `ptr+0x326` before/after each hit.

## 6. Reproduce

```
cd system
python -m pytest tests/test_pso_bounded.py -q
cd docs/research
python pso-bounded.py walk --to 498 -261 --seconds 45      # calibration + bounded walk
python pso-bounded.py play --seconds 90                    # progression policy + switch verification
```

Ledgers, fixtures and the flag audit are written to `D:\gBox\pso-ds\bounded\` (game-session data, never committed).
