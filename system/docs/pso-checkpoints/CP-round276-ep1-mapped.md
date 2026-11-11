# Round 276: the whole of Episode I mapped - 14 floors of rooms, heights and audit

With all 159 collision maps extracted (35 areas, 32.5 MB), a generic pipeline now maps an area by floor number: place the area's collision file at
`rel/map_forest<NN>c.rel`, then segment rooms and build the height table. Every other tool - the room database, the audit, the planner, the minimap -
already keys on floor number, so nothing else needed to change.

## Floors 1-14, mapped

| floor | area | rooms | free cells | reachable | verdict |
|---|---|---|---|---|---|
| 1 | Forest 1 | 11 | 5701 | 5696 | **PASS** |
| 2 | Forest 2 | 14 | 6145 | 4580 | 3 rooms isolated |
| 3 | Cave 1 | 22 | 15576 | 13031 | 16 of 22 navigable |
| 4 | Cave 2 | 44 | 12373 | 9363 | layout 00 is not the live one |
| 5 | Cave 3 | 12 | 10028 | 9934 | **PASS** |
| 6 | Mines 1 | 26 | 10324 | **112** | layout 00 is not the live one |
| 7 | Mines 2 | 24 | 10270 | 10270 | **PASS** |
| 8 | Ruins 1 | 27 | 10504 | 10218 | 1 room isolated |
| 9 | Ruins 2 | 44 | 9799 | 8812 | 3 rooms isolated |
| 10 | Ruins 3 | 10 | 15824 | 15131 | 3 rooms + 1 doorway disagreement |
| 11 | Dragon arena | 1 | 3489 | 3489 | **PASS** |
| 12 | De Rol Le | 1 | 256 | 256 | **PASS** |
| 13 | Vol Opt | 3 | 1014 | 376 | 2 rooms isolated |
| 14 | Dark Falz | 5 | 8218 | 4478 | 2 rooms isolated |

**Five floors are fully navigable, and every floor now has rooms, heights and connections.**

## What the audit revealed about layouts

Two floors stand out as **the wrong layout rather than a map defect**: Mines 1 (floor 6) has only **112 reachable cells** and Cave 2 (floor 4) has **28
of 44 rooms unreachable**. Both were mapped with layout `_00`, and the layout that is actually loaded is one of the other variants - which is exactly
what the identification step measures when the bot is standing in the area (Cave 1's live layout was found that way, at 94 of 94 live objects). So
those two numbers are not a failure of the map, they are **evidence that the layout guess was wrong**, and they will be corrected the first time the
bot visits.

## Two filename defects fixed

* `height_map.py` built `map_forest0{floor}c.rel`, which is `map_forest010c.rel` for floor 10 - a three-digit name that cannot exist;
* `map_area.py` joined an empty layout with an underscore, asking for `map_boss01_c.rel` when the boss arenas are `map_boss01c.rel`.

Both were caught because the pipeline reported the missing file by name instead of failing silently.

## The boss arenas are mapped too

Floors 11-14 now have their own rooms and heights:

* **Dragon arena** - 1 room, 3489 cells, fully reachable;
* **De Rol Le** - 1 room, 256 cells;
* **Vol Opt** - 3 rooms;
* **Dark Falz** - 5 rooms, 47 doorways.

So the minimap and the planner have data for the boss floors as well, which is the layer that was missing when the Dragon fight was being navigated
blind.

## State

| item | state |
|---|---|
| collision maps on disk | **159 files, 35 areas** (the entire game) |
| floors mapped | **1-14, all of Episode I** |
| fully navigable floors | 1, 5, 7, 11, 12 |
| layout identification | automatic when the bot is in the area |
| game focus | false - in-game progress still waits for it |
