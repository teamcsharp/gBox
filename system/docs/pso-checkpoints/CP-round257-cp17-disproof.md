# Round 257: goal unblocked, self-play running, and CP17's exit theory disproved with evidence

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, live, floor 1.

## The goal is unblocked

It had been blocked for two different reasons in sequence:

1. **no PSO session** for 22 rounds (the real blocker — an agent-launched session is `agent_owned` and receives no input);
2. then the **round cap**: `"Goal reached its configured limit of 256 rounds"`.

The operator started the game from the app, and on their instruction I raised the cap to **500 rounds** and resumed:

```
phase: active    roundsStarted: 257 / 500    activation: armed
```

## Self-play is running

`selfplay.py` — fight, loot, then walk to the next unexplored room from the mesh room graph:

```
16:01:26 === self-play on floor 1, 11 rooms in the graph, visited [0, 1]
16:01:27 entered room 5 at (159,5)
16:01:36 enemy TObjEneLappy at 27 units - engaging
```

Every room entered, fight and pickup is written to `selfplay.jsonl` with timestamps, so a run is reviewable rather than asserted.

## CP17: the exit theory is disproved, with evidence

The plan was to reach Forest 1's exit at **(133,−48)** — the coordinate where the operator's own recording showed the floor changing — and
record the floor id going 1 → 2 on foot.

What actually happened, from `evidence/cp17-floor-series.jsonl`:

```
leg -> (135,-45): arrived=True  44s 239 units, floor 1, at (130,-47)
leg -> (135,-45): arrived=True   0s   0 units, floor 1, at (130,-47)
```

**The character stood 3 units from the recorded point and the floor stayed 1.** Then a scan for warp entities in the whole table found
**none at all** — `"no warp class in the entity table on this floor"`.

So two things are now established rather than assumed:

* **(133,−48) is not a step-on trigger** — walking onto it changes nothing;
* **the area warp is not resident on this floor** in the room the character was in, so it cannot be activated by proximity or by pressing A
  there.

The earlier certifiable property still holds (the route to that point is 9 clear legs, 999 units, 37 s), but the point itself is not the exit.

## What replaces the theory

The warp must be found where the game actually spawns it. `warp_watch.py` now scans the entity table every two seconds and records the first
sighting of any warp class with its position, floor and distance to the player (`warp-sightings.jsonl`). Combined with self-play walking the
eleven rooms, that is the mechanism that will locate the real exit instead of another guessed coordinate.

## What is running

| process | role |
|---|---|
| `selfplay` | fights, loots, walks room to room; logs everything |
| `warp_watch` | records the first sighting of any warp entity |
| `mag_roll --loop` | mag every 120 s, level 75–200 random |
| `weapon_rule --loop` | newest weapon fills all five slots |

The `walk_through` patch stays **off** (it was what lifted the character every second).
