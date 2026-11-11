# Round 216: why it is slow, measured - and what actually fixes it

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## The speed numbers

The operator's complaint is that watching a single room take this long is unacceptable. Measured this round:

* the character itself moves **about 45 units per second** while a direction is held - measured as **72 units in one 1.6 s stride**;
* the measure-then-stride controller (`steer2`) achieved **6.8 units/s** overall - the probing (four directions x 0.3 s before every
  stride) costs more time than the walking;
* the calibrated-then-free-refresh controller (`fast_walk2`) reached **7.0 units/s** but oscillated, because its direction table goes stale
  as the camera turns with the character;
* the drive-like-a-player controller (`drive.py`: long forward holds, short turn taps) **spun in place** at the test spot: the character
  was in a corner, the forward probes returned no movement, so the heading could never update and it kept turning.

So the bottleneck is **not** the movement speed, it is **decisions per unit travelled**, plus the fact that all three controllers assume
the character can move freely toward the target - which fails at a wall.

## What actually fixes it

1. **Fewer decisions**: hold a direction for 1.5-2 s at a time and only correct when the heading error exceeds ~20 degrees. The 45 units/s
   then becomes the effective speed instead of 7.
2. **Geometry instead of probing**: the bot should know where the free space is rather than discovering walls by bumping into them. The
   collision mesh already contains every walkable cell (`pso_walk.cells`, 5,701 cells) and the room graph groups them - a straight run over
   open cells needs no probing at all, only waypoints at the ends of free lines.
3. **The Area Map** (the operator's own suggestion) is the same information in the game's own drawing: room shape, the route line and the
   numbered waypoints. Printing it gives both the navigation lines and, later, the level editor's top-down canvas.

## Delivered this round

* `fast_walk2.py` - calibrated table refreshed for free by rotating it with each stride's own displacement (no probing between strides).
* `drive.py` - forward-hold plus turn-tap driving with a learned turn rate, which is the right shape for speed but needs free space to
  bootstrap its heading.
* The measured throughput numbers above, which decide the next step: route along open collision cells, then stride long.

## State

All bots stopped. Player around (-247, 270) in room 7 (a corner), HP 31/48.
