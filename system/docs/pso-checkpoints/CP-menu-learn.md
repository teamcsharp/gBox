# Learning PSO's menus, and getting faster at them

Session identity: DeepSeek    Branch: ds-pso-menu-learn-20261110    Commits: this branch
Goal: 2

## What the operator asked for

> "I need the game to learn from menus and navigate them fast and quick and learn to do them faster and faster"

`pso_menu_observer` already recognises a screen from a frame and `next_key` picks one conservative press - correct but slow: one
capture round-trip per press. What was missing is the **learning** layer, and that is what this branch adds.

## `gbox/pso_menu_learn.py`

* **`TransitionGraph`** - `(screen, key) -> screen` with a learned `delay` per edge, visit/failure counters, BFS `route(start, goal)`,
  `timings(route)`, and JSON save/load. `record` keeps the **smallest delay that has worked**; `failed` lengthens an edge that did not
  reproduce; `shrink(factor)` lowers every edge toward a floor.
* **`MenuLearner`** - `look()`, `step(key)` (observe, press, wait the edge's delay, observe, record), `play(keys, verify)` **as one
  macro** (timed presses, no capture between them, one verification at the end), `explore(rounds)`, `learn_route(start, goal)` and
  `speed_run(keys, verify, runs)` which replays the same route repeatedly and shrinks the delays after every **successful** run.

The property that makes the speedup safe: a delay is only kept short while the screen still changes. A run that is too fast is
**detected** (verification fails), the edge is lengthened, and the improvement is not kept.

## Proven offline - `tests/test_pso_menu_learn.py`, 7 passed

A fake menu machine (`attract -> menu -> offline -> licence -> charsel -> field`) applies a key only after its own latency, so the
tests exercise real timing rather than sleep-and-hope:

1. the graph records what a key does and prefers the fastest success;
2. exploration finds the five-key route `start, ddown, start, start, start` to the field;
3. replaying it reaches the field with **five presses and one capture** (not five captureround-trips);
4. each successful run shrinks the delays - the second run of the same route is faster;
5. a replay forced below the machine's latency **fails verification**, and the edge is charged a failure and lengthened;
6. the graph survives save/load;
7. an unreachable goal raises rather than guessing.

## What is wired but not yet trustworthy: the live screen id

`docs/research/pso-menu-live.py` + `pso-key-sender.ps1` drive the real game from the **keyboard** using GCPad1's fallback from
Dolphin's INI (`Start = RETURN`, `A = X`, `B = Z`, `D-pad = T/G/F/H`, stick `UP/DOWN`), with one persistent PowerShell sender so a
press is a pipe write rather than a process spawn. It captures the window, fingerprints it (16x12 grey, quantised), waits for the
screen to hold still, and feeds the learner.

**Measured problem:** the attract loop is a *movie*. Ten presses produced seventeen "screens", i.e. the fingerprint followed the
animation. A stability gate helps only when a genuine menu holds still; the attract never does. So **live learning must identify
screens semantically** - `pso_menu_observer.observe(frame)` returns the recognised menu and cursor from text masks at 1031x580 or
16:9 - not by hashing pixels. That is the next step: capture at the observer's expected size and use `menu`/`option_index` as the
screen id.

**One thing this round proved that matters:** the keyboard does reach the game - the title/menus respond to `RETURN`/`X` while the
window is foreground. The input path for menus is therefore available to the operator and to the bot without any virtual pad.
