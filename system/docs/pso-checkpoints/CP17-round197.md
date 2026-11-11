# Round 197: a flat-only route crossed Forest 1 - the largest live progress yet - and an adjacent Booma stopped the last 140 units

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1, floor 1, HP 20/40

## The flat route works

`flat_route.py` recomputes the per-cell floor heights (the same rule `psomap.walkable_cells` uses internally but does not return),
measures each cell's steepest step to a walkable neighbour, and routes only over cells whose worst step is <= 2.5 units:

```
walkable 5701, flat 5328 (93.5%)
flat route: 106 waypoints, 1050 units   (spawn -> key door)
```

Following it with the calibrated walker made the **largest live movement of the session**:

```
start (605.7, 437.2) -> wp8 (468,482) -> wp16 (408,497) -> wp24 (366,539) -> wp32 (289,548)
-> wp48 (208,495) -> wp56 (198,403) -> wp64 (222,157) -> wp80 (223,291) -> finish (253.6, 147.5)
```

That is roughly **600 units across the map**, where every earlier walker turned back within ~150 units of the spawn. A second
short flat leg from there reached `(226.7, 117.9)` and the empirical walker then got to **137-165 units from the door**.

## What stopped the last stretch

At `(232, 110)` both input paths send successfully and the character does not move at all - and the screenshot shows why: **a Booma is
standing against the character**, occupying its space. That is the "no direction moves" signature, not a slope and not a pad.

Killing it failed: the face-and-strike loop struck at 3, 9 and 13 units with angles of 7, -1 and -14 degrees and the Booma stayed at
**60/60**. The character's own state explains it: HP hovered at 10-20 of 40, so it is being knocked around faster than it can finish an
attack; `pso_controls stat name=hp` reports `before: 40, shown_now: 40` but the actor's live HP stays 20/40 (the stat op does not heal
the live field), and there is no healing item in reach.

## Next

1. **heal for real** before the last leg: hospital in Pioneer 2 (`TObjCityDoor_Med`), or a mate (the pack had a Monomate at slot 3 on
   the fresh character), or accept a death and let `survival` revive at partial HP before the fight;
2. then kill the adjacent Booma and walk the last ~140 units on the flat route;
3. press A at the door and read `0x805D5FC0`.

The navigation problem is solved for practical purposes; what remains is one fight at a disadvantage.
