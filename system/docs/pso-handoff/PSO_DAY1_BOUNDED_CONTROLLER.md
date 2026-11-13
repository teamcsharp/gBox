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

## 6. Round 2 — a clean session, and the city is the next wall

The session was replaced (`docs/research/pso-session.py`: stop, launch, drive the menus, report the flags). The new
session starts with the **entire stage-flag array at zero** (`floor 0`, all 18 groups `0/256`), which is what §3.5
said was needed for switch evidence:

```
session 29d05fb902974b97-8431536cedea416a   in the world at (229.0, 254.0) room 10   hp 68/68
floor 0   set bits per group [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
sha256   1a0295f4bf5986c5f74eca9153a6a4cb10b073a01a76ba4a457fd862c78966a4
```

That is the opening state a G3 test needs: any bit that changes after a switch press is attributable to that press.

**The city is the wall, not the switch.** The character is in the Pioneer 2 lobby (room 10) and the way to Forest 1 is
the warp door at `(254, 25)` and the platform at `(360, 26)`. Ninety-five taps of tap-vector steering and fifty-four
taps of relative steering both failed to cross the plaza: the character ends up bouncing between `(105,154)` and
`(131,160)`, ~170 units from the door, because the plaza railing sits between the lobby and the warp and the
controller has no map of the city. Only the Forest collision grids are decoded (`forest-maps.json` holds
`map_forest01c` and `map_forest02c`); the city map the handoff mentions (5,626 walkable / 4,959 safe cells) was not
kept in the analysis directory.

Two things came out of that failure and are now in the code:

* **moving is not closing.** A walk that oscillates still moves more than the movement epsilon every tap, so the
  movement watchdog never fires: 95 taps, zero stalls, 198 units from a 260-unit target. There is now a per-objective
  "no closing" budget (`max_no_close_ticks`), and it works live: `walk coordinate not closed for 41 ticks (still 170
  units away); the character is moving without approaching it`, then a fixture and a stop.
* **rotation is not liveness.** Every blocked tap in the plaza still rotated the character by ~90°, so the earlier
  "turning counts as liveness" rule let a completely wedged character look alive for 138 taps. The watchdog is back
  to translation only, and a test pins it.

The input mapping itself is still not fully characterised: `heading_deg` changes by ~90° per tap when the keys
alternate, and the same `left` tap rotated the character clockwise in one session and anticlockwise in another (camera
mode). `RelativeTapMotion` therefore learns the lateral sign from the first turn that increases the error instead of
assuming one.

**Next:** decode `map_city00_00c.rel` into the same safe-cell grid the Forest route uses, route to the warp door, then
activate the warp and reach Forest 1 with controller input only. The switch→flag probe is ready for the first switch
after that.

### 6.1 The city grid, and a corner taps cannot leave

The city collision mesh is now decoded by `docs/research/pso-citymap.py` from the owned disc image (identity pinned:
`Scene/map_city00_00c.rel`, 70,144 bytes, sha256 `6d5f5d5d…`): **1,497 triangles → 50,933 walkable / 47,779 safe
cells** at the same 2.5-unit cell the Forest router uses, written to `D:\gBox\pso-ds\city-map.json`. The same cell
size matters: the first grid was built at 10 units and `MapRouter` (which assumes 2.5) reported "no route" through a
component that obviously contained both endpoints.

A route from the lobby to the warp door is **60 waypoints**, and following it moved the character from `(163,164)` to
`(229,-9)` — past the railing that had stopped every straight-line attempt — in one 150-second run with 0 overruns and
0 failures. The last stretch then wedged the character in a corner at `(349.6,-45.0)`, and that produced the most
useful single measurement of the round:

| escape attempt | result |
|---|---|
| 40 taps, every direction, three minutes | position moved **0.0 units** |
| one `left` hold, 0.45 s | position moved **33 units**, out of the corner |

So the watchdog recovery is a **hold**, not a tap. A hold's distance is non-deterministic (it depends on release
latency) which is why movement uses taps — but for an escape, a large immediate displacement is exactly what is
needed. The same reasoning applies when the character *is* moving but cannot close: the no-close budget now spends up
to three hold escapes (`Bounds.max_escapes`) before it reports a failure, and each escape is a ledger line with the
pocket's tick count.

Live, that is the difference between stopping and progressing: the corner that ended one run at `(349.6,-45.0)` was
left by the escapes, and the next run walked from `(300,-43)` through `(278,-20)` and `(323,-5)` — out of the pocket
and into the warp area — ending 48 units from the pad with 0 overruns and 0 failures. It has not reached the pad yet;
that is where the next round starts.

## 8. Round 3 — speed, and the first verified switch→flag chain

The operator asked for maximum speed. Measured, then fixed:

| bottleneck | measured | fix | result |
|---|---|---|---|
| input path | `session_op` job **0.53–1.22 s**; app input queue **15–31 ms** | `SessionWorld` posts to `/api/sessions/{sid}/input` with the job path as fallback | 60× less latency per input |
| emulator speed | 56 fps (0.9×) → **160 fps (2.7×)** with fast-forward | `session_op fast_forward {"on": true}` | 2.7× game time |
| state read after input | **0.65–1.0 s** (the worker services the input pump first) | movement actions are measured by the *next* tick's read; interaction presses keep an immediate read | 1.0 → 0.17 s per tick |
| budgets in ticks | 150 ticks = 150 s at 1/s, 30 s at 5/s | budgets are now **seconds** (`max_objective_s`, `max_no_close_s`) | behaviour independent of loop speed |
| objective flip-flop | two doors swapping nearest re-ran A* over 90,986 cells every tick | the policy keeps its current objective while it is still a candidate of the same rank | 1 → 4.8 ticks/s |
| room flicker | room flipped 10→11→10 nine times at a boundary, resetting every progress clock | a room only counts when it is held for two ticks | false progress removed |

Measured after the fixes: **57 ticks in 12 s**, then **191 ticks in 40 s (4.8/s)** with 0 overruns and every ledger
chain verified.

**The warp worked.** From the city pad at `(360,26)`, one A press moved the character from floor 0 (room 20, 31
entities) to **Forest 1 — floor 1, 91 entities**, with the stage-flag array still at all zeros:
`sha256 1a0295f4…`, 18 groups, 0 bits. That is a clean arrival, no global writes, controller input only.

**G3, part one: two switches pressed, two flags set.** In that clean session:

| press | switch | distance | flag array sha256 | bits on floor 1 |
|---|---|---|---|---|
| `play-20261113-100018` seq 123 | `TObjDoorKey` at `80DB54C0` | 12.3 units | `1a0295f4…` → `c4e4b92f…` | **7** |
| `play-20261113-101432` seq 140 | `TObjDoorKey` at `80DB5650` | 12.7 units | `c4e4b92f…` → `73bf9c70…` | 7, **6** |

Read back from the live array: `group 1: set bits [6, 7]`, all other groups zero. Every one of those presses was
controller input, and the verifier refused to call press 1 a success for two attempts — the flag write landed after
the read, which is why `flag_wait_s` exists.

**What is not done:** G3's last step, walking through the door those flags open and recording the room change. The
character reached the room 10/11 boundary (the flicker above) but the door crossing is not yet captured; that is the
first task of the next round, followed by G4 (enemy-gated door) and G5 (combo verification).

## 9. Round 4 — the switch→flag link, read from the switch itself

Round 3 proved two presses changed two bits. Round 4 closes the other half of that claim: **the switch carries its own
flag index** at `+0xC8`, and it is exactly the bit that changed.

| switch | `+0xC8` flag index | bit that changed | match |
|---|---|---|---|
| `TObjDoorKey` `80DB54C0` | **7** | floor 1, bit 7 | yes |
| `TObjDoorKey` `80DB5650` | **6** | floor 1, bit 6 | yes |

Read back live (`switch-flag-correlation-20261113-102305.json` in the ledger directory): the array holds exactly
`[{group 1, index 6}, {group 1, index 7}]`, and those two switches declare those two indices. That is a controller
press → a named switch → a declared flag index → that bit set, with the middle step read independently of the flag
array. The same field gives the other switches their indices (30, 31, 32, 33, 8, 60, 61) and the energy barrier 10 —
the map of what each one controls.

**A doorway was crossed.** From `(-144, 276)` a walked path took the character through the door at
`(-133.8, 271.7)` and the room settled **11 → 10** (three consecutive reads agree). What is *not* yet proven is that
this door opened *because of* bits 6/7: plain `TObjDoor` actors carry no flag index (their `+0xC8` holds pointer-like
data), so the door↔flag link must be made through gates that do — the `TLazerFenceSw` / laser-fence pairs. The crossing
is recorded as a traversal, not yet as a linked-door transition.

**Two bugs found and fixed by doing this:**

* a verified switch was targeted again after ~60 s, because the "recently pressed" window compared a persisted
  timestamp against a monotonic clock. Verification is now permanent for the session (`pressed` means done), which
  stopped the bot walking 111 units back to a switch whose bit was already set;
* a closed door is *wall* to the collision mesh, so the router goes around it even after its flag opens it. Doors are
  now approached along a route to a point 18 units short and then walked through directly.

**Still open:** long-range navigation orbits in the Forest. Measured on a 500-unit route: 138 ticks, a median 7.6 units
per tick (the taps work), ~1,050 units of path for 105 units of net progress, and five room transitions back and forth.
The steering is a frame-relative rule — `up`/`left`/`right` chosen from the last movement direction — and it does not
survive repeated reversals. The next step is a hill-climbing controller that checks each tap against the *waypoint*
distance and flips the key that made it worse, instead of inferring a frame.

```
cd system
python -m pytest tests/test_pso_bounded.py -q
cd docs/research
python pso-calibrate.py --samples 4 --batch 5                 # the primitive measurement
python pso-session.py status                                  # session, player, stage-flag audit
python pso-session.py restart --force                         # stop, launch, boot to a character
python pso-bounded.py walk --to 360 26 --seconds 60 --map D:\gBox\pso-ds\city-map.json   # the city warp pad
python pso-bounded.py play --seconds 45 --map D:\gBox\pso-ds\forest-maps.json --map-name forest01
python pso-citymap.py --route 105,160 254,25                  # decode the city grid and route it
```

Ledgers, fixtures and the flag audit are written to `D:\gBox\pso-ds\bounded\` (game-session data, never committed).
