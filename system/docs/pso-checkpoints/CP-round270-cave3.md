# Round 270: into Cave3 hunting the boss warp, and orders made floor-scoped

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, now **floor 5 (Cave3)**.

## The route to the Dragon, walked as far as the warp allows

`boss_warp` cannot respawn the boss because it places the character past the spawn trigger. The legitimate route is the Caves, so the warp ladder
was used to reach the last of them:

```
floor_warp "3" -> Cave1   (floor 3)
floor_warp "4" -> Cave2   (floor 4)
floor_warp "5" -> Cave3   (floor 5)
```

Each step also explained a rejection seen earlier: `floor_warp` answers **422 with a body** of
`{"ok": false, "reason": "an area transition is already in progress"}` when the previous load has not settled. It is a timing race, not a validation
error, and a retry after a few seconds succeeds. That distinguishes it from the genuine 422 caused by sending an integer `target`, which the request
model rejects before the handler runs.

## Cave3, as loaded

| entity | count | nearest |
|---|---|---|
| `TODoorCave02` | 33 | 78 units |
| `TObjContainerItem` | 38 | 180 units |
| `TObjDoorKey` | 5 | 276 units |
| `TODoorCave03` | 4 | 240 units |
| `TOCapsuleAncient01` | 3 | 290 units |

**No warp entity exists in Cave3 yet** - consistent with PSO's rule that the boss teleporter appears once the area is cleared. That is the remaining
work in this area, and it is gameplay rather than tooling.

## A bug found by the warp ladder: orders leaked across floors

A click on floor 11 had written an order for (40, 130). After the warps, the bot was still walking toward those coordinates **in Cave3**, where they
mean nothing - it was moving 20 units per 3 seconds in a direction chosen by a different area's geometry.

Orders are now **floor-scoped**: the minimap records which floor the click happened on and sends it with the order, and self-play ignores an order
whose floor is not the floor it is standing on. Verified with a deliberately stale order:

```
17:17:27 === self-play v2 on floor 5, 0 rooms, visited [...]
17:17:39 ignoring an order for floor 3 while on floor 5
17:17:39 no map for floor 5 - wandering toward (-457,-253)
```

## State

| item | state |
|---|---|
| floor | 5, Cave3 |
| boss warp | not present yet - appears after the area is cleared |
| room map | none for Cave3 (only Forest 1 and 2 are extracted) |
| bot behaviour | wandering with the height-aware planner, obeying same-floor orders |
| HP | 31/62 |
| focused | true, moving 20 units per 3 s |
