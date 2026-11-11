# Round 261: the fight failures are a HEIGHT problem, not a combat problem

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, floor 1.

## Research first (as asked)

The Ephinea PSO wiki's Booma page, for the basic Forest enemy:

* **HP 92** (Normal) with a 60 HP variant - the enemy here reads **60 and 42**, so it is that variant;
* **behaviour**: *"Boomas will move towards players once their aggro radius has been entered or they've been struck. They'll walk directly toward
  their target and begin attacking when they reach it."*
* **hunter advice**: *"Boomas ... can recover quickly enough to counterattack between the first two swings of a combo. Because of this, it may be
  necessary to fight them with only normal attacks, or, if using a longer weapon, attack just as they come into range."*

So the correct tactic is **stand your ground and swing as it arrives**, not chase it. `fight_wiki.py` implemented exactly that: face it with a
brief step, stop, and swing in a normal-attack combo rhythm.

**It still did no damage** - and the reason was not the tactic.

## The measurement that explains every failed fight

`direction_probe.py` held each direction for half a second and measured the distance to the enemy:

```
player (295.1, -141.1)   enemy TObjEneBeast (279, 7, -136) hp 42   gap 16.7
  up     moved 23.78   gap 34.1 -> 45.1   away
  down   moved  3.85   gap 26.9 -> 23.8   toward
  left   moved  9.09   gap 12.8 -> 21.8   away
  right  moved 23.80   gap 21.8 -> 34.4   away
```

**Movement works** - every key moves the character between 3.8 and 23.8 units. But the enemy's **y is 7** while the character stands around
**11.5**: the Beast is **~4.5 units BELOW the player, on lower ground**.

Every fight attempt so far has been walking *horizontally* toward an enemy that is *vertically* out of reach. Melee does not extend downward, so
no amount of approaching, facing, swinging or chasing could ever connect. The successful kill earlier happened on flat ground.

## What this changes

The approach must be **height-aware**. The collision mesh already carries heights - `psomap.collision` returns triangles with y, and
`pso_walk` already resolves the walkable cell under the player. The route has to lead **down to the enemy's level** and then close on it,
instead of treating the floor as a plane.

Concretely, the next fight step:
1. read the enemy's full position `(x, y, z)` - already read, the y was simply ignored;
2. when `|enemy.y - player.y|` is more than about a metre, find the path to the **cell at the enemy's height** rather than its (x, z);
3. close until both the horizontal distance is within reach **and** the heights agree, then swing.

## Also this round

* the wiki's aggro rule is useful for the bot's own logic: an enemy that has been **struck** will come to the player, so a single ranged or
  missed hit can pull it onto flat ground where melee works;
* three hypotheses were eliminated before this one - input delivery, swing duration and range, and target switching - each by measurement, which
  is what narrowed it to geometry.

## State

| item | state |
|---|---|
| movement | working (4-24 units per 0.5 s hold) |
| swing | working on flat ground (verified kill) |
| fights on sloped ground | **impossible** - enemy below the player |
| rooms visited | 4 of 11 |
| warp sightings | none |
