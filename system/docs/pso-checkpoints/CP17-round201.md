# Round 201: three long runners, best 130 units, and the wall is still the closed door at (253, 92)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`

## Three controllers in one round, all measured

| runner | result |
|---|---|
| receding-horizon flat planner (cached flat set, BFS every 3 waypoints) | converged 596 -> 376 units, ended by its budget |
| door-sequence controller (approach within 10, A, push, verify jump) | wandered near the spawn: with no long-range plan the approach alone cannot cover 500+ units |
| **empirical stride walker + fight-on-stall + pad clear** | **best 130 units** - the closest yet - then oscillated between `(231,110)` and `(273,122)` for 160 strides |

The empirical walker is the fastest (16 units per stride) and the most resilient (it fought off an adjacent Booma mid-run), but it
cannot finish: it bounces between the door and the wall at z ~ 107-145.

## The last obstacle, precisely

The key door is at `(201, -18)`. The character cannot get south of **z ~ 107**, which is exactly where **`TObjDoor` (253, 92)** sits ~20
units to its west. Every route ends against that door. `door_open.py` did once log "passed through" with a 56-unit jump, so the
interaction works - the missing piece is a controller that:

1. stands **facing** the door (the door's A prompt needs the character near and oriented);
2. presses A and pushes with a **verified jump**;
3. repeats for the next door, and only then continues to the key door.

The empirical walker aims at the *key door* and only ever brushes the intermediate door, so it never presses A at the right moment.

## Stable

- randomizer: running, 28+ cycles, no inventory growth;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- inputs: both paths work after `B x2` off a pad; ATP boost persists across the session.

## What CP17 needs now, concretely

One small controller addition: when a `TObjDoor`/`TObjDoorKey` is within 30 units **and the walker stalls**, turn toward it, press A,
push, and require the jump - instead of pressing A only when the *key* door is within 9 units (which never happens because the
intermediate door blocks the way).
