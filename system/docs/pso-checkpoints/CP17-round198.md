# Round 198: the flat route carried the character 600+ units twice; the heal is the last blocker and none of the quick paths work

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, character left in Pioneer 2, randomizer at **15 cycles**

## What worked, twice

The flat route (`pso-flat-route.py`, 106 waypoints over level cells) carried the character across Forest 1 again, this time at full HP
without a single trap:

```
(532.7,483.3) -> (466,483) -> (404,502) -> (363,545) -> (230,526) -> (206,485)
-> (199,400) -> (215,328) -> (229,267) -> (261,262) -> finish (105.0, 171.0)
```

That is ~600 units, and the walk finished the whole 106-waypoint list. The empirical walker then closed part of the remaining ~220
units before a Booma engaged.

## The heal problem, measured systematically

| method | result |
|---|---|
| `floor_warp` to town and back | HP unchanged (10/40 in town, 10/40 on return) |
| `pso_controls stat name=hp value=40` | `{before: 40, shown_now: 40, verified: true}` but the **actor's live HP stays 10/40**; a warp afterwards does not sync it either |
| `revive` | "Your character is already alive" |
| item menu (use a mate) | the **cursor will not move** in the item pack (d-pad tap, d-pad hold, main stick, C-stick all tried), A works, R pages the right panel |
| hospital | the town walk to `TObjCityDoor_Med` did not move the character at all |
| **level up** | the only heal observed: earlier a level-up restored HP to 40/40 |

So the one reliable heal is a **level-up**, which needs kills, which needs HP - the character is at Lv 1 with 15/50 EXP.

## What that means for CP17

The walk is solved (flat route, 600 units, twice). The remaining ~140-220 units fail because a Booma engages the character at 10 HP and
the character loses that fight. The missing piece is a reliable heal or a reliable kill at low HP - both are game-state problems rather
than control problems:

1. a kill at 10 HP would level the character and heal it fully (15 EXP needed, a Booma is worth ~15-20);
2. the item menu is the natural heal and its cursor is the one input that has never worked (A and R work in the same menu);
3. the hospital is the fallback and needs a town walk that has not yet moved the character.

## Stable

- randomizer: `cycles: 15`, `Equipment randomized`, no inventory growth;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- input paths: external keys and worker `send_input` both work once the character is off a pad; `B x2` after any warp clears the pad.
