# Round 277: the room database covers all of Episode I, and the maps are visible

## Every floor in the database

`room_db` now builds floors **1-14**: **244 rooms**, each with its centre, bounds, cell list, height range, contents and connections. That is the same
record shape the minimap, the planner and the audit read, so all three now work across the whole episode.

## The gallery

`render_gallery.py` draws every floor on one canvas, rooms labelled and shaded by floor height, with the audit's reachability under each title:

![Episode I gallery](ep1-gallery.png)

Reading it back, the level design becomes obvious in a way the 3D view never showed:

* **Forest 1** - one winding loop, 11 rooms, fully navigable;
* **Cave 1** - a spine with side rooms hanging off it, 22 rooms;
* **Mines 2** - a long corridor chain, 24 rooms, every cell reachable;
* **Cave 2** - visibly fragmented into many small rooms, consistent with layout 00 not being the live variant;
* **Dragon arena** - a single **circular** room of 3,489 cells, fully enclosed;
* **De Rol Le** - a **grid platform** of 256 cells;
* **Dark Falz** - **three separate arenas**, which is the shape of a multi-phase fight;
* **Vol Opt** - 3 rooms, only 376 of 1,014 reachable, consistent with a walled arena;
* **Ruins 3** - 10 very large rooms, 15,131 of 15,824 cells reachable.

## Why this is the layer the operator asked for

*"The 2D map is the 3D game"* - and now every floor has one, at cell resolution, with heights, so:

* the bot can plan across a whole floor instead of towards a coordinate;
* a click on the minimap becomes a legal order anywhere in the episode;
* an enemy's position can be judged against real geometry, which is what the height problem needed;
* the boss arenas, previously blank, have shapes.

## State

| item | state |
|---|---|
| floors in the room database | **1-14, 244 rooms** |
| gallery | rendered, all 14 floors |
| fully navigable floors | 1, 5, 7, 11, 12 |
| game focus | false - in-game play still waits for it |
| remaining goal item | CP19, one continuous unattended episode |
