# Round 217: the lock was blocking the bot's own strides - the real cause of the glacial pace

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## The bug that made everything slow

While testing whether the character could move at all, four consecutive directions gave:

```
up     sent=True   moved 14.5
down   sent=False  moved 0.0     <- refused by the lock
left   sent=False  moved 0.0     <- refused
right  sent=False  moved 0.0     <- refused
```

The operator lock was classifying **the bot's own deceleration** as operator motion: `note_bot_input(seconds + 0.25)` declared the action
window, the key was released at `seconds`, but the character kept sliding to a stop just after it - so the watcher saw motion outside the
window and shut the bot down for the full 3 s idle period. Every other stride was being refused.

**Fix**: the declared window now includes the deceleration (`seconds + 1.0`) and the watcher's grace went from 0.20 s to **0.55 s**.
Immediately after:

```
up     sent=True   moved 14.5
down   sent=True   moved 20.6
left   sent=True   moved 21.1
right  sent=True   moved 20.4
```

All four directions execute. At 0.4 s per hold that is **35-50 units per second** of real movement - the character was never slow, the
arbitration was eating most of the inputs. This also explains the "oscillating" controllers of the previous rounds: half their strides were
silently discarded.

## The route planner is genuinely fast

`nav_fast.py` routes over the 5,701 free collision cells and then string-pulls the path:

```
start (-185,-17) -> goal (141,-194)
raw BFS waypoints: 149   after string-pull: 9   route length 1230 units   planned in 0.15s
```

**149 -> 9 legs**, each a clear straight run (for example `(-125,15) -> (-125,295)`), planned in 0.15 s. Decisions per unit travelled drop
by 16x.

## What is still slow, honestly

The long-stride driver (`drive_route.py`) still measured **0.4 units/s** on its last run: 9 units in 20.8 s with 11 turns. With input now
flowing, the remaining fault is the driver's stubborness - it only ever tries forward and small turns, so a wall in front of it becomes an
endless turn loop instead of a decision. The fix is stall-triggered calibration: when two forward strides fail, measure the four directions
once (about 1.2 s), pick the best and stride long. That keeps the fast path fast and pays the probe cost only at a wall.

## Files

* `nav_fast.py` - free-cell routing plus string-pulling (`plan()` gives raw and simplified counts)
* `drive_route.py` - long-stride driver over the planned legs, with the diagonal corner escape
* `fast_walk2.py`, `drive.py` - the two earlier speed attempts, kept for reference
* `pso_input.py` - action windows now include deceleration; `pso_operator2.GRACE` = 0.55 s
