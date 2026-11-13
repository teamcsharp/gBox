# Day 1 — a bounded, cancellable controller, and what the live audit found

**Scope:** the first sprint in `PSO_ENGINEERING_AND_AUTOPLAY_RECOVERY.md` §11, answering the failures in
`WHY-IT-STANDS-STILL.md`: a branch that can hold the loop for minutes, no watchdog that runs before every branch,
operator takeover that waits for an iteration, and no evidence ledger.

**Result:** the controller exists, is bounded by construction, and is proven twice — by a 27-test suite and by a live
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
python -m pytest tests/test_pso_bounded.py -q     →  27 passed
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

### 3.4 The finding: the motion model — resolved by settling the measurement

The first five live calibrations disagreed with each other (`up` read dead in four of five; a tap appeared to swing the
heading 60–170°). The reason was **momentum**: the position was read the moment the input job acknowledged, while the
character was still coasting. `docs/research/pso-calibrate.py` fixes that by polling until two consecutive reads agree
before every sample, and the picture is now stable and repeatable (4 samples per key, 09:11–09:12):

| primitive | up | down | left | right |
|---|---|---|---|---|
| one tap (down+up in one job) | 7.82 (7.00–8.00) | 7.99 (7.55–8.00) | 7.98 (7.85–8.00) | 7.99 (7.59–8.00) |
| five taps in one batch | 15.85 (3.17/tap) | 15.52 (3.10/tap) | 15.74 (3.15/tap) | 15.51 (3.10/tap) |
| hold 0.30 s | 38.88 | — | — | — |

Three facts, all new:

* **every direction key works** — a tap moves 7.8–8.0 units with a spread of under a unit. The earlier "dead `up`" was
  the character pressed against geometry, not a dead binding;
* **a tap is the only primitive with a predictable distance.** A 0.30 s hold moves **38.9 units**, because the release
  job lands about a second after the down job: the hold is really ~1.3 s of running. Its displacement depends on job
  latency, which is exactly what a controller must not depend on;
* **a batch of taps is not 5× a tap** — it moves about 15.5 units (~3.1/tap), because each 35 ms press restarts the
  movement. Batching is a way to nudge, not a way to step.

So movement is now `VectorMotion(primitive="tap")`: one tap per tick, each tap's world displacement re-measured and put
back into the key table, which is what handles the camera-relative mapping. Live result, first attempt:

```
walk to 498,-261:  86 units away  ->  arrived within 6 units after 16 ticks
                    final distance 4.9      overruns 0   stalls 0   ledger 17 entries verified
```

That is the first walk in this project that closed a real distance under controller-only input without a position
write. The heading-based model (`HeadingMotion`) remains in the library and tested, but nothing in these runs justified
using it: `heading_deg` moved unpredictably while position was reliable.

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

### 3.6 Switch verification, live

A 110 s `play` run found `TObjDoorKey` at `80DB5DF0`, closed from **106 to 10.2 units** in controller input only, and
pressed A three times. The stage-flag array's sha256 was **identical before and after all three presses**:

```
seq 40  press a  'press TObjDoorKey at 11.6 units (attempt 1)'  flags 975bea3eef -> 975bea3eef
seq 41  press a  'press TObjDoorKey at 11.0 units (attempt 2)'  flags 975bea3eef -> 975bea3eef
seq 42  press a  'press TObjDoorKey at 10.2 units (attempt 3)'  flags 975bea3eef -> 975bea3eef
```

The run then **stopped** with `failure-play-20261113-090706.json`: the switch named, the three distances, and the 39
ticks that led there. That is the behaviour §9 asks for and the old loop never had — it called a switch pressed as
soon as A was sent, then walked into a door that had never opened. Because the array is saturated (§3.5), the
no-change result is not yet evidence about the switch itself; what it proves is that the verifier does not invent a
success.

---

## 4. What is not done, stated plainly

* **The motion model is solved for this control plane, by measurement.** Taps move a predictable 7.8–8.0 units and
  the tap-vector model closed 86 → 4.9 units in 16 ticks. The remaining gap is not steering; it is the room graph and
  the switch/door chain.
* **No switch→flag evidence in this session** — see 3.5. The verifier is implemented, tested and ran live; it has
  nothing clean to verify against.
* **The movement watchdog counted turning as standing still.** The first live `play` run recorded three recoveries
  while the character was turning to face the next waypoint. Turning is now liveness (position *or* heading change);
  a bot that only turns is caught by the objective clock instead.
* **No combat evidence.** The sequencer is implemented and tested; this room has no enemies (the live profile shows
  one enemy on the floor, out of reach).
* **G1/G4–G8 are untouched.** No acceptance gate is claimed.

## 5. Next round (in order)

1. **Fresh session without global writes.** Relaunch, drive the menus, and confirm `groups_set_bits` is all zero
   except the city's own flags before leaving town. Record the array as the session's opening state.
2. **Primitive calibration on open ground.** ✅ Done — `docs/research/pso-calibrate.py`, results in §3.4: every tap
   7.8–8.0 units, holds unusable on this channel, batches do not accumulate.
3. **One switch→flag→door chain.** Nearest `TLazerFenceSw`, bounded approach, press, flag read before/after, then walk
   the linked door and record the room change. Failure means a fixture with the distances.
4. **City → Forest 1 with controller input only** (walk to the warp trigger, activate it, choose the destination), so
   the fresh session reaches a switch without a position write.
5. **Wire the same evidence into the combo path**: action-state at `ptr+0x326` before/after each hit.

## 6. Reproduce

```
cd system
python -m pytest tests/test_pso_bounded.py -q
cd docs/research
python pso-bounded.py walk --to 498 -261 --seconds 45      # calibration + bounded walk
python pso-bounded.py play --seconds 90                    # progression policy + switch verification
```

Ledgers, fixtures and the flag audit are written to `D:\gBox\pso-ds\bounded\` (game-session data, never committed).
