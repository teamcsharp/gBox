# Round 193: the worker's input path is the reliable sender now; CP17's walk still oscillates

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, character back in Pioneer 2, randomizer at **27 cycles**

## The important discovery

My external `win_send_keys` calls **stopped reaching the game** while the screen looked completely normal (Forest 1, HUD, no menu):
every probe reported no movement for ten minutes. The **worker's own input** still works:

```
session_op send_input events=[{"key":"start"...}]  -> the menu opened (panel: BQF Lv 1, Total EXP 10pt, 300 Meseta)
session_op send_input events=[{"key":"down"...}]   -> (578.3,582.1) -> (506.9,552.2)   moved
                       ... "left"                  -> -> (433.7,533.6)                  moved
                       ... "right"                 -> -> (505.4,550.5)                  moved
                       ... "up"                    -> no movement (blocked at that spot)
```

So there are two input paths and they fail independently: the external one depends on the OS focus and can go dead while the game is
fine, and the worker's `send_input` (which does its own `give_focus` + wait-for-front) kept working. **Future drivers should use
`session_op send_input`,** with the external key path only as a fallback.

## What still fails

A calibrated worker-driven walk oscillated instead of converging over 130 strides:

```
stride 20: 562 units (key=left)   stride 60: 559 (left)   stride 100: 532 (up)   stride 130: 571 (right)
positions bounced between (456..566, 414..451)
```

With four keys calibrated and re-calibrated every five strides, the chosen key flips between left, right and up while the distance
stays in a 520-580 band. The character is moving, the calibration is measured, and it still does not close on the door - so the
remaining problem is the control law (intercept and stride length), not the data and not the input.

## Proven and stable

- randomizer: **27 cycles**, every 300 s, rare weapon + mag, generated item replaced in place, inventory not growing;
- CP18: the Dragon's HP reached 0/1300 from RAM and its entity despawned (round 179);
- collision graph + route + calibration all work on Forest 1 (`map_forest01c.rel`, 5,701 walkable cells).

## Next

1. a control law that closes: predicted intercept (enemy/waypoint position + character velocity), stride length scaled to remaining
   distance, and a hard re-target when the distance stops falling;
2. do it over `session_op send_input` (this round's finding) rather than external keys;
3. then the door: press A once at the door, push through, and read `0x805D5FC0`.
