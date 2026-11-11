# Round 203: the door handler reaches the door but cannot get within interaction range, and my jump test is too weak

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, character in Pioneer 2, randomizer at **47 cycles**

## What changed and what it showed

1. **Door trigger raised from 30 to 45 units**: the handler now fires at the wall (the character hovers 31-33 units from `TObjDoor`
   (253, 92), just outside the old 30).
2. **`try_door` now closes to interaction range first** (short empirical strides until <= 9 units), which exposed the real problem:
   **the character cannot get closer than ~19-25 units to that door**. The closing step fails (`ok=False`) every time:

   ```
   door TObjDoor at (253,92) dist=21  -> closed to 21 (ok=False) -> A does nothing
   door TObjDoor at (253,92) dist=25  -> closed to 25 (ok=False) -> A does nothing
   ```

   Something (a gap, a ledge, or the door standing at a different height) keeps the character ~20 units away, where the A prompt does
   not exist. So the intermediate door may not be a door the character can use from this side at all - it may need a switch
   (`TOSwitchAttackSub` or `TLazerFenceSw` at (526, 33)) or be scenery.

3. **A bug in my own verification**: "a door opened" fired several times while the character was 19-25 units away, because the jump
   test accepted any move > 8 units - and a normal stride moves 7-10. The jump test must be > 15 units **and** only count when the A
   press preceded it, otherwise it reports doors that never opened.

## Where the run stands

The composed controller (flat receding route + any-door handler) took the character from the spawn (532, 483) to a best of
**153 units** from the key door (round 85), then oscillated at the 140-280 band, and at the wall it correctly identified and
approached `TObjDoor` (253, 92) but could not interact.

## Concrete next steps

1. **fix the jump test** (A-triggered only, > 15 units) so the door handler stops reporting false openings;
2. **identify what `TObjDoor` (253, 92) actually is**: read its interactable state or find the switch that opens the passage - a
   `TLazerFenceSw` (526, 33) or `TOSwitchAttackSub` are the candidates already in the entity table;
3. **or route around it**: the flat graph says the door area is walkable, so the wall may be the *door frame*; a route that passes
   beside it (not through it) may reach the key door without any interaction.

## Stable

- randomizer: **47 cycles**, `Equipment randomized`, no inventory growth;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- inputs: both paths work after `B x2` off a pad; ATP boost persists.
