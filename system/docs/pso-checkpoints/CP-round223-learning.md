# Round 223: continuous learning, the 2-minute randomizer, and Forest 2's warp found in the first minute

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 2

## "Learn everything, every time I play"

Two systems now do exactly that, and both are running:

* **`learn_live.py`** - samples the player every second (position, floor, HP, TP) and the entity table every 3 s, and turns the stream into
  events: floor changes (teleporter discoveries), HP drops (damage events with position - the hazard map), entity appear/vanish pairs
  (spawns, kills, pickups) and an accumulated route. Output: `learned/live/live-*.jsonl`, append-only, one file per run.
* **`poi.py`** - classifies what it sees (warp / switch / door / capsule / container / item / enemy / npc) and merges new sightings into
  `learned/points-of-interest.json`, keyed by floor, de-duplicated within 12 units. Run it any time; every session grows the map.

## What the first minute of learning produced

```
floor 2: 84 entities classified, 84 new points of interest
  warp       1   TObjWarpBossMulti (155.4,-500.8)      <- the exit object the set files never had
  switch     4   TOKeyGenericSw (-110.2,-460.3), TLazerFenceSw (308.6,167.2), (494.1,440.1), (176.3,547.6)
  door      12   TObjDoor (-333,-569), TObjDoor (-46,-226), TObjDoorKey (-290,-200), ...
  container 45   TObjContainerItem / TObjContainerBase
  capsule    7   TOCapsuleAncient01
  item      15   TItemEquipBase / TItemObject / TItemMoney
```

This is the answer to "where is the exit": the static set data has no warp (proven last round), but the live entity table listed one
immediately - **`TObjWarpBossMulti` at (155,-501)** on floor 2, plus four switches including a key switch. The collision for floor 2 is
already loaded, so the bot can plan a route straight to that warp.

## The randomizer

The operator asked why equipment swaps were not happening. The plane's randomizer **was** running, but at **300 s**, and the old starter
script used the wrong port and a stale session id. Set through the live channel:

```
{"on": true, "interval": 120, "categories": ["weapon","mag"], "character_class": "HUmar",
 "cycles": 1, "message": "Equipment randomized"}
```

**120 seconds, live, one cycle already applied.**

## Files

* `learn_live.py` - the continuous learner (read-only; never sends input)
* `poi.py` - points-of-interest accumulator (`learned/points-of-interest.json`)
* `session.py` `controls('randomized', {...})` - the 2-minute equipment timer
