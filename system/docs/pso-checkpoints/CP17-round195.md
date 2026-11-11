# Round 195: the character is trapped in Forest 1's starting zone — the walk cannot leave it, and the gates are why

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1, floor 1

## Measured this round

1. **The pad freeze is cleared by B, and a two-step respawn restores movement**:
   ```
   Forest 1 (485.6, 368.1)  -> floor_warp 0 -> Pioneer 2 (285.8, 22.5)
                            -> floor_warp 1 -> Forest 1 (532.7, 483.3)   [the spawn pad]
                            -> B x2 + down  -> (568.8, 470.6)            [moving again]
   ```
   A same-floor `floor_warp 1` is a no-op, so the respawn must go through the town.

2. **`walk_through` verified on** (`{"on": true, "verified": true}`, `adventure_status.walk_through: true`).

3. **Every walker converges to the same region and stops there.** With the pad precondition in place, the collision navigator ran from
   `(568.8, 470.6)` toward the key door at `(201, -18)` (611 units) and oscillated:
   `611 -> 624 -> 552 -> 569 -> 599`, positions staying in `(450..580, 390..470)` - the same region every previous run ended in
   (`(485, 368)`, `(473, 394)`, `(576, 457)`).

## What that means

The character can move, the input works, the collision route exists, and it still cannot leave a ~150-unit region of Forest 1. Entity
data shows why the region is closed: within a few hundred units sit `TOBarrierEnergy01` (221, 493), `TLazerFenceSw` (526, 33),
`TObjDoor` (253, 92) and `TObjDoor` (53, 290), and the only `TOSwitchAttackSub` switches are far away at `(-520, 700, -500)` and
`(-400, 250, -100)`. **Forest 1 is gated: the zone cannot be left until a barrier/door is opened.**

CP17's "walk the collision graph" therefore needs the gate step before the door step: open the barrier or fence, then walk through the
newly opened passage to the key door, then the floor change.

## Next

1. **walk to `TOBarrierEnergy01` at (221, 493)** (271 units away, inside or at the edge of the start zone) and interact - a barrier
   usually drops when its switch is hit or when approached;
2. if the barrier needs a switch, walk to `TOSwitchAttackSub` at `(-400, 250, -100)` (the nearer of the two) and hit it;
3. then the key door and `0x805D5FC0`.

The walker itself is not the problem any more: with the pad precondition it moves reliably and measures direction correctly. What it
lacks is the game's gate logic.

State left: Forest 1 (or town after the next respawn), HP 10/40, walk_through on, randomizer past 30 cycles.
