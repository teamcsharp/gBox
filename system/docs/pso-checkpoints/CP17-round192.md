# CP17 round 192: every walk attempt now fails on the same three things, and the randomizer ran 20 cycles

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17` (warped back to Pioneer 2 at the end, safe)

## The operator feature is solid

`randomized` reached **cycles: 20** - twenty five-minute cycles of rare weapon + mag swaps on the class catalog, message
`Equipment randomized`, with the generated item replaced in its slot each time and the inventory not growing. That part is done and
has been stable for hours.

## The three failure modes that stop CP17's walk

1. **Enemies stop movement.** A Booma engaging the character freezes it: `steer_walk` reports
   `the forward binding is dead: nothing moved when 'up' was held`, and the position does not change for minutes at a time
   ((406.6, 390.3) for five minutes, HP 10/40, ctrl 1, action 0). Survival keeps it alive; nothing keeps it walking.
2. **Chasing mobile enemies does not converge.** With ATP 999 / ATA 400 the damage is a non-issue, but the character cannot close:
   `close_combat` spent 300 s and never got inside 6 units of either Booma. The probe-and-turn controller steps 0.4 s at a time
   while the enemy moves away; a kill only happened once, when the enemy happened to be within a long spear's reach.
3. **`walk_through` did not apply.** The attempt's log line was swallowed and `adventure_status` afterwards read
   `{"walk_through": false}`, so the collision bypass that was supposed to let the character ignore terrain was never on - which also
   explains why the frozen character stayed frozen.

## What is actually proven for CP17

- the disc -> collision graph -> `pso_walk.path` route is correct and routes around walls;
- `pso_kbwalk` calibration converges (708 -> 163 units in one run) and `steer_walk` works on short clean legs;
- combat works when the character can face a target at reach (`strike at 13 units ... all enemies down` with the ATP boost);
- the floor byte `0x805D5FC0` is read continuously and has never changed by walking.

## Next, in order of value

1. **make `walk_through` verifiable**: check the op's reply and `adventure_status.walk_through` before relying on it, then walk
   straight at the door (no collision, enemies can still hit but not pin);
2. **a proper chase**: steer in 0.8-1.0 s strides with a re-probe every stride and a predicted intercept, instead of 0.4 s steps
   against a moving target;
3. only then the door itself (press A once, push through, floor changes).

The character ends the round in **Pioneer 2** (floor 0) at HP 10/40, randomizer still cycling, so the next attempt starts from a
safe place.
