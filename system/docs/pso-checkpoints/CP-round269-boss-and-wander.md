# Round 269: the boss cannot be warped back in, and why - plus the wrong-room bug that made the bot walk into walls

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, now **floor 3 (Cave1)**.

## The boss: a warp cannot respawn it

`boss_warp target=dragon` reported:

```
"You are already in Dragon / Sil Dragon's area."
```

The floor was 11 and the arena was **empty** - no boss entity. Re-warping gives the same answer. The reason is structural: **`boss_warp` places the
character INSIDE the arena, past the spawn trigger**, and a boss only spawns when the character crosses that trigger on the way in. Earlier in this
session the Dragon *did* appear, and it appeared exactly because the bot **walked into the arena from floor 3**.

So the legitimate route to a Dragon fight is: complete Caves 1-3, walk into the boss teleporter that appears, and the boss spawns.

## Floor 3 is Cave1, and floor_warp takes a STRING

Two facts learned by trying:

* `floor_warp` with `{"target": 3}` returns **422** - the request model rejects an integer, so the handler never sees it;
* `floor_warp` with `{"target": "3"}` works:

```
{"ok": true, "warped": true, "from": 11, "floor": 3, "name": "Cave1", "message": "loading area Cave1"}
```

and the plane's own resolver confirms the naming: floor 3 is `map_cave01` with **six layout variants** (`map_cave01_00` .. `_05`) - exactly the
"maybe three different layouts" the operator described, doubled.

## The bug behind "walking into a wall"

`rooms()` fell back to **Forest 1's room graph** whenever the current floor had no mesh of its own. On Cave1 the bot was therefore planning towards
Forest 1 room centres that do not exist in that area - a fiction it followed into geometry.

Two fixes:

1. a floor with no mesh now returns **zero rooms** instead of another floor's;
2. with no rooms, self-play **explores**: a random bearing 90-220 units out, planned with the height-aware planner, repeated. It cannot invent
   destinations, and the warp watcher still looks for the real exit.

Measured after the fix:

```
17:14:06 === self-play v2 on floor 3, 0 rooms, visited [...]
17:14:15 following the map order to (40,130)
17:14:16   order route: 220 cells -> 12 legs
focused: True | moved 19.22 units in 2.5 s
```

## Why Cave1 has no room data yet

The collision maps extracted so far are `map_forest01c.rel` and `map_forest02c.rel` only. Cave1's map would be `map_cave01_0Xc.rel`, and extracting
it needs the plane's `mods` extract operation, which is a **job** - and jobs are the one thing the operator-owned session will not dispatch. So the
bot can still move and fight there using the order system and wandering, but it cannot plan room-by-room until that extraction is possible.

## State

| item | state |
|---|---|
| floor | 3, Cave1 (6 layouts per the resolver) |
| room graph | none - correctly reported as 0 rooms |
| bot | playing: focused, moving 19 units per 2.5 s, following the order |
| boss | cannot be warped in; needs Caves 1-3 completed |
| warp watcher | still running, will catch the boss warp when one appears |
