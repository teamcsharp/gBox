# Round 263: the bot kills on Forest 2, explores six rooms, and the floor recorder is armed

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, floor 2.

## The bot is playing, and killing

```
16:52:07 === self-play v2 on floor 2, 14 rooms, visited [0, 1, 6, 8]
16:52:07 entered room 3 at (-488,288)
16:52:16 locking target TObjEneBeast at 13 units (hp 28)
16:52:47 entered room 4 at (194,455)
16:52:57 target TObjEneBeast down
16:52:57 nothing to fight - walking to room 12 (480,534)
```

**`target TObjEneBeast down`** - the target lock plus attack-while-stepping killed an enemy on Forest 2. Six of the fourteen rooms have been
visited (0, 1, 3, 4, 6, 8), and the loop then moved on to room 12 by itself.

That single line is the first end-to-end success of the combat work: lock, pursue, hit, confirm death, continue exploring.

## The evidence recorder for CP17

CP17's accept test needs a floor change **observed as it happens**, which cannot be reconstructed afterwards. `floor_series.py` now samples the
floor id and position four times a second and writes:

* a **`FLOOR_CHANGE`** row with the exact position and elapsed time whenever the floor id differs from the previous sample;
* a `jump` row when the character moves more than 25 units between samples (which reveals warps and fast travel);
* a heartbeat every ten seconds so the series has continuity.

It is running now, so the next transition - whether the operator walks a teleporter or the bot does - is captured with its position.

## Combat learning is accumulating

`combat-demos.jsonl` holds **24 hit records** so far, each with the distance, height difference, bearing and cadence at the moment of damage. That
is the operator's play translated into numbers the bot can use, and it is what already showed that their build one-shots Forest enemies at 11-69
units.

## What is running

| process | role |
|---|---|
| `selfplay2` | fights, kills, explores the fourteen Forest 2 rooms |
| `floor_series` | records floor changes as evidence |
| `learn_combat` | records the geometry of every hit |
| `warp_watch` | records the first sighting of any warp entity |
| `mag_roll`, `weapon_rule` | mag and weapon rotation |

## State

| item | state |
|---|---|
| floor | 2, six of fourteen rooms visited |
| kills by the bot | **at least one confirmed** (`target ... down`) |
| combat records | 24 hits |
| floor changes captured | none yet (recorder armed) |
| character | HP full, cannot die |
