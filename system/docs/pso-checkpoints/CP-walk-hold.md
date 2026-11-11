# Walking beats tapping: hold the stick, do not tap it

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

The first forest driver pressed `up` between attacks as a **tap**: `win_send_keys` with
`[{down}, {up}]` in one batch. At 30 fps that is roughly two frames of stick deflection, so the character attacked in place.

The measurement, same 8-unit cell analysis and the same session:

| | tap driver | hold driver |
|---|---|---|
| recording | 15 min, 2913 samples | 4 min, 810 samples |
| cells | **10** | **130** |
| edges | 9 | 157 |
| distance | **64 units** | **1813 units** |
| bounds | 44 x 42 | 203 x 252 |
| components | 1 | 1 |
| replay waypoints | 2 | 28 |

Fifteen minutes of tapping covered ten cells; four minutes of holding covered a hundred and thirty. The driver now holds a random
direction for 0.6-1.4 s (`down` event, sleep, `up` event - two calls, because `win_send_keys` sends whatever batch it is handed),
re-centres the camera with L, and attacks 3-6 times between moves.

**Why this matters for the product:** any bot that walks by tapping a stick will look like it is playing while standing still, and its
recorded routes will be a dot. The walk graph is the honest signal - cells and edges per minute - and it is the number to watch when
tuning a driver, not the screenshot.
