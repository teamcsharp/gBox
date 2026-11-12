# Live grid: recorder built and proven, recording blocked by one relaunch

## What changed, measured

**Input is cheap now.** Re-measuring the cost of one press through `/api/sessions/<sid>/input`, which earlier left the RPC unreadable for 25 s:

```
baseline read: 0.014s
down:          0.003s  {"queued":1}
up:            0.007s  {"queued":1}
first poll:    0.000s  OK
```

**0.0 s recovery** - no blindness. The 25 s episode was a transient condition, not a property of input.

**But input does not move the character on this session.** Sixteen key presses left the player at exactly (-188.4, -729.0), travelled **0.0 units**:

```
4/16 keys -> (-188.4, -729.0)
8/16 keys -> (-188.4, -729.0)
12/16 keys -> (-188.4, -729.0)
16/16 keys -> (-188.4, -729.0)
```

The reason is already established: this session started at **07:15:19**, before `pad_route.py` was deployed at 07:36, so it is on the **keyboard** path - and keyboard input needs the game window in front, which it is not while it plays in the PiP. The presses are queued and dropped.

## What was built anyway - and verified

`routes/live-grid` recorder: samples positions, builds an **8-unit cell grid**, records **edges as observed moves** (consecutive samples that cross into an adjacent cell - not guesses), persists to JSON, and routes with A*.

Because the live trail could not be recorded, its logic was verified on a trail **whose answer is known** - an L-shaped walk:

```
trail points: 21
cells: 11   edges: 20 directed
route (0, 0) -> (5, 5)
  path: 11 cells, manhattan 10
  every step is a recorded edge: True
  length matches the shortest possible: True

isolated cell (55, 55): route = None   (correct)
```

**The grid, the edge recording and the A* are correct**, including the negative case: an unreachable cell returns no route rather than a straight line.

## So the state of path-guiding

| path | state |
|---|---|
| **disc collision** (51 rooms, routes at 1.08x) | works, but needs per-room instance transforms to map onto live positions - **undecoded** |
| **live-coordinate grid** (this round) | **recorder and router proven**; needs a drivable session to populate |
| knowledge store (room graph, critical path) | empty; needs walking |

Both remaining paths converge on the same prerequisite: **a session where input reaches the game**.

## The single action that unblocks it

**Relaunch PSO once.** The new session picks up the deployed `pad_route.py`, binds Player 1 to the virtual pad, and `send_input` becomes focus-free - which is what makes the character drivable, the grid recordable, and the bot able to act at all.

That is the same fix as before, and it is still unexercised because every session since has predated it.
