# Round 200: the 140-unit wall is an actual door (253, 92), and the receding horizon reached it twice

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`; character returned to Pioneer 2, randomizer at **28 cycles**

## The wall has a name

Two independent runners - the integrated flat-route walk (round 199) and the new **receding-horizon flat planner** (this round) - both
stopped at **~140 units from the key door** with the character pressed against a wall, and the screenshot from that spot shows a stone
door with the camera inside its surface. The entity table has **`TObjDoor` at (253, 92)**, about 17 units from where the character
stood: a **closed ordinary door**, not the key door, is the last obstacle.

The receding-horizon planner (flat cells cached once, BFS re-planned every three waypoints) converged much better than the one-shot
route:

```
round 32: 518 units  (209.1, 499.8)
round 36: 471 units  (201.7, 453.0)
round 40: 417 units  (191.6, 398.9)     x aligned with the door (201), heading south
round 44: 368 units  (117.5, 372.9)     best of the run
final position: (265.1, 16.1, 107.0) = 140 units from the door
```

`door_open.py` then reached that door, logged **"passed through"**, and the character was suddenly 56 units past it - but the
empirical approach kept overshooting afterwards and the loop chased its own tail (distances 56 -> 182 -> 241 -> 162).

## What that means for CP17

- **Navigation: solved** (flat route + receding horizon, ~600 units, converged to 140 units twice).
- **The last obstacle is a sequence of doors**: the character must open `TObjDoor` at (253, 92), walk through, and repeat until the
  key door at (201, -18), then press A there for the floor change.
- `door_open.py` proves the interaction works ("passed through" and a 56-unit jump), so the missing piece is a controller that
  approaches *each door* in turn without overshooting: short 0.4 s strides, stop within 10 units, A, push, confirm the jump, and
  re-plan to the next door.

## Stable

- randomizer: **28 cycles**, `Equipment randomized`, no inventory growth;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- inputs: external keys and worker `send_input` both work after `B x2` off a pad.
