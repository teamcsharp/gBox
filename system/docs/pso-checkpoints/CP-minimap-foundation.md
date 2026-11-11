# The minimap-first foundation: live map viewer, click-to-command, operator arbitration

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `e731ee594dde4a89-cae9dad929a34d17`

## What the operator asked for in this round

1. the **minimap is the foundation** of the level system (rooms, doorways, enemies, portals are all on it);
2. a **live map viewer** to watch runs and **click the map to command the bot**, click an enemy to target it;
3. the bot must **get to a region's exit and progress linearly** instead of meandering;
4. **never fight the operator**: stop on operator input, resume only after **3 seconds** idle;
5. **record everything the operator does** so it becomes training data.

## What is running now

| component | state | what it does |
|---|---|---|
| `map_viewer.py` | **http://127.0.0.1:8801/** | live top-down map: rooms from the collision graph, doors coloured by RAM state (green = unlocked/cleared, red = locked, blue = key door), enemies as triangles with HP, player as an arrow, live minimap inset, click = waypoint, shift-click = target enemy |
| `map_bot.py` | running, obeying the lock | follows the viewer's orders over the flat collision graph, fights an enemy within 35 units using attack-while-stepping, backs off when HP <= 12 |
| `pso_operator.py` | running | samples position at 8 Hz; motion the bot did not cause sets `operator-lock.json`; every bot send is gated by `guard()`; the bot resumes only after 3 s without operator motion |
| `demo_recorder.py` | recording to `D:\gBox\pso-ds\demos\demo-<stamp>\` | 2 Hz state (position, facing, floor, HP, every door state, every enemy) + a frame every 2 s with its minimap markers + `path.json` waypoints |

Verified live: a POST to `/api/goto` with `{x:240,z:300}` was picked up by the bot as an order, and the operator lock reported
`operator_active: true, moved: 6.9` while the operator moved the character - so the bot stayed off the controller exactly as asked.

## The linear level structure (the room graph)

`room_graph.py` cuts the flat floor at every door (r = 22 units) and labels the resulting components as rooms, with doors as edges:

```
room 0 (1166 cells, centre 326,372)  <-door 66 (253,92) UNLOCKED->  room 1 (994 cells, centre 141,-194)
room 1 contains the key door 47 (201,-18)   -> destination
other doors: 17 joins rooms 1,3 (state 240); 27 joins 5,4 (0); 31 joins 7,2 (0); 32 joins 2,3 (0);
             52 joins 1,4; 58 joins 8,6; 63 joins 7,6; 67 joins 0,8
```

This is the "room -> door -> room" chain the operator described: no exploration is needed if the bot walks the graph.

## The door unlock flag (carried over, verified)

`+0x18C` on each `TObjDoor`: **0 = locked**, **2 = unlocked by clearing the room**, **224 = key door**, **240 = special**. Door 66 flipped
to 2 after the room's `TObjEneBm5Wolf` was killed, and `pso_doors.History` logs every transition to `door-history.jsonl`.

## Honest gaps

- the bot **does not yet learn** from the recorded demonstrations - the recorder captures them, but no policy is trained on them;
- the **level editor** (top-down assembly of new biomes from the map) is not built;
- the door 66 collider still refuses passage at z = 107 even at state 2, so the room graph is computed but the physical passage is not
  yet proven.

## Next build order

1. minimap -> world calibration so viewer clicks, minimap markers and entity positions all agree in one coordinate frame;
2. trainer: read `demos/*/path.json` + `state.jsonl`, extract the operator's room-to-room transitions and the actions taken at each
   door, and produce the waypoint/decision table the bot follows;
3. level editor: rooms and doors as the top-down canvas, with item/enemy/portal layers on top.
