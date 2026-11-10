# Pioneer 2 in PSO GameCube — the room ids, measured

Everything here was measured on the live US `GPOE8P` disc (i9-NUC, 2026-11-10) by walking a character and reading the
game's own state, not inferred from the disc. It exists because the city is where P1's route starts and its rooms are
identified in RAM only by a `u16` at actor `+0x28`.

## The area table, for reference

`gbox.pso_areas.EPISODE1` reads the DOL's area list from `LIST_AREA_TABLE` (`PsoV3.dol+0x431C04`):

```
city00, forest01, forest02, cave01, cave02, cave03, machine01, machine02, ancient01, ancient02, ancient03, boss01
```

and `ZONES` additionally carries `lobby`. `FLOOR_LAYOUTS` pairs an episode with a floor number: `(1, 0)`, `(1, 1)`, `(1, 2)`
-- so **floor 0 is the city**, floor 1 is Forest 1, and so on. `pso_ram.FLOOR` (`0x805D5FC0`) is that number, which makes
"am I in the field yet?" a single `u32` read.

## Room ids seen in the city

| room id | what is there | evidence |
|---|---|---|
| **10** | the **lobby**: both co-op players spawn here; four `TObjCityDoor_*` entities; the teleporter pedestal | spawn position, `pic-lobby.jpg` |
| **20** | the **plaza**: `TObjNpcCloakroomBase`, `TObjNpcConnoisseur`, `TObjNpcFemaleFat/Macho/Tall`, `TObjNpcMaleDwarf/Old`, `TObjNpcSoldierBase/Macho`, `TObjNpcExpertBase` | 9 NPC entities with room 20, `pk1-room20.jpg` |
| **30** | the **shop floor**: `Connoisseur`, `MaleMacho`, `FemaleMacho`, `MaleFat`, `FemaleTall` | 5 NPC entities with room 30 |
| **40** | a **large interior containing a round teleporter structure and the hospital**: two `TObjNpcNurseBase` at (213,-293) and (266,-214), and a circular pad near the origin | `pl3-room40.jpg` |
| **41** | the **Principal's office**: `ExpertBase` x2, `GovernorBase`, `SecretaryBase`; the single-player intro cutscene plays here | 4 NPC entities with room 41, `pz-now.jpg` |

Rooms with **no** `TObjCityDoor_*` of their own (20, 30, 40, 41) are entered through *geometry*, not through a door object:
their entrances are archways in the level, and the only door entities in the table are the four that belong to room 10.

## Doors are positions, and the city shares one world space

Walking onto a door's coordinates changes the room **with no button press**:

| walked to | from | result |
|---|---|---|
| `(185, 173)` `TObjCityDoor_Guild` | room 10 | room **20** (the plaza) |
| `(185, 173)` | room 20 | room **10** (back to the lobby) |
| `(254, 25)` `TObjCityDoor_Warp` | room 10 | room **40** |

The second row is the important one: **the same coordinate works in both directions**, so the city's sub-rooms share a
single world space and a doorway is a position rather than a special exit object. A route therefore needs coordinates
plus the room they belong to, and nothing more -- which is what `gbox.pso_kbwalk.walk_path` now records per leg
(`room_before`, `room_after`, `transition`).

## Open: the teleporter does not answer

The round teleporter structure in room 40 was approached from `(300,25)`, `(257,-40)`, `(210,25)`, `(257,90)`,
`(229,10)`, `(229,-10)`, `(255,0)`, `(200,0)` and finally `(252,-3)` with a 2.5-unit tolerance, and `A` was pressed on
arrival. **No destination menu appeared** and the mode byte stayed in the town family the whole time. The walker also
could not reach `(229, 0)` -- it stalled at `(252,-2.7)` -- which suggests the pad's centre is not walkable and the
interaction is from its rim.

So: either the trigger is tighter than these positions, the pad needs both players present (P2 was in room 10), or the
city teleporter is not how an offline multiplayer party reaches the surface at all and the route is the Hunter's Guild
quest. Next round should test the "both players on the pad" case before concluding anything about the trigger.

## Method notes

* `pso_entities.entities()` reads every actor with its room; `Counter(e["room"] for e in entities)` is enough to tell
  which sub-areas are loaded, because the city's rooms coexist in the table.
* A character can be steered with `win_send_keys` on the keyboard bindings only; the virtual pad's analog stick never
  reaches the game (round 19). The Dolphin window must be foreground.
* Room transitions are visible in RAM as a `u16` change, so a route can prove where it is at every step.

## Walked routes (measured, not guessed)

The city is one large connected area; the `room` id changes at specific thresholds. Only four transitions have actually
been walked, and each is a **position to cross with movement**, not a place to stand:

| from | to | crossed at | how it was found |
|---|---|---|---|
| room 10 (lobby), from the spawn | room 20 | walking `(170,190) -> (120,120)`, crossing around `(106,101)` | greedy walker legs, room id read each leg |
| room 20 | room 10 | walking to `(185,173)` from the west | round 22: the same coordinate working both ways |
| room 10 | room 40 (teleporter room / hospital) | walking onto `(254,25)`, the `TObjCityDoor_Warp` coordinate | round 23 |
| room 10 | -- | `TObjCityDoor_Guild` at `(185,173)` is **inert**: four approaches arrived on it, `A` included, no change | round 29 |

A passable route to the west end of the city, every leg walked under control:

```
(170,190) -> (120,120)   crosses into room 20
          -> (23,-34)    through the gap south of the terrace
          -> (-77,29)
          -> (-224,-26)  the west end
```

## What is at the west end

The shopping district and the medical exterior: lit shopfronts signed **GURHAL** / **LICENSED**, a counter with a keeper
behind it, the `TObjNpcCloakroomBase` NPC at `(-267,-24)`, and a night street with a white-coated NPC in front of a large
lit entrance. Pressing `A` at the counter or at the cloakroom does **not** open a dialogue -- the mode byte stays in the
town family, so the character is across the counter rather than in front of the keeper.

So **the Hunter's Guild is not at the west end**. What is left to try: the two room-10 doors never walked
(`TObjCityDoor_Med` at `(194,-93)`, `TObjCityDoor_Shop` at `(-165,148)`) and whatever the central dome's large doorways
lead to.

## The lobby / room-20 transition is a zone, not a line

Round 39 walked the boundary from both sides in one session and found that it is not a threshold to hit but a **band the
room id flips inside**:

```
room 20 (95,55) -> (115,105) -> (140,150)   became room 10 at (142,152)
room 10 (142,152) -> (180,40)               became room 20 again at (93,51)
room 20 (105,136)                            stuck inside the band, room 20
```

So the crossing lives somewhere around **(95-142, 50-152)** and either room can be the current one while the character is
inside it. Two consequences for a route:

* a waypoint that skims the band will flip the room under the walker, which is exactly what happened twice this round;
* getting to a *specific* room means approaching it from well outside the band, not from a nearby waypoint.

Adjacency found the same way: walking from `(-149,12)` toward `(-20,60)` entered **room 30** at about `(-169,46)` and came
back to room 20 -- so room 30 (the shop floor) borders room 20 on that side, not room 10.

## Where the guild search stands

| candidate | status |
|---|---|
| `TObjCityDoor_Guild` (185,173) in room 10 | **inert**: four approaches arrived on it, `A` included |
| `TObjCityDoor_Warp` (254,25) in room 10 | works -- leads to room 40 (the teleporter room / hospital) |
| `TObjCityDoor_Med` (194,-93) in room 10 | **not yet reached**: every attempt skims the boundary band and flips into room 20 |
| `TObjCityDoor_Shop` (-165,148) in room 10 | not yet reached |
| the central dome's large doorways in room 20 | not yet walked |
| the west-end counter + cloakroom NPC (-267,-24) | no dialogue from the front; it is the shopping district |

## The city graph (walked, room by room)

Every edge below was walked at least once, in the direction stated, with the room id read from RAM at each leg:

| edge | crossing | direction walked |
|---|---|---|
| room 10 <-> room 20 | the band around `(95-142, 50-152)` | both ways |
| room 10 -> room 40 | `TObjCityDoor_Warp` `(254,25)` | in |
| room 10 -> room 40 | `TObjCityDoor_Med` `(194,-93)` | in, arriving at about `(203,-32)` |
| room 20 -> room 40 | about `(200,-94)` | in (the same door seen from room 20's side) |
| room 40 -> room 20 | about `(167,60)` | out |
| room 20 <-> room 30 | about `(-169,46)` | in and back |

Two things fall out of that table:

* **room 40 is a hub**, reachable from room 10 two ways and from room 20 one way, and it exits into room 20. It contains
  both the medical exterior (the red-cross door, `qf0-meddoor.jpg`) and the round teleporter structure, which is why the
  "Warp" and "Med" doors both lead there -- they are not two rooms, they are two entrances to one.
* **walking back out of room 40 is not symmetric.** Arriving at the `Med` door's coordinates from inside room 40 leaves
  the character in room 40 (`(192,-90)`), while walking to `(200,60)` crosses into room 20. So a route must use the exit
  it can actually leave by, not the door it came in through.

### Not found yet

No walked edge leads to a room the lane has not already seen (10, 20, 30, 40), and none of those contains a counter that
answers `A`. The guild is therefore behind something not yet walked -- the most likely candidates being the central
dome's large doorways that were walked *past* rather than *into*, and room 30's own far side.

## Room 10's object map (28 records, world coordinates)

Now that the offset is measured (`+228, +291`) and confirmed in game, `map_city00_00o.dat` can be read as a map. Every
record, its class, and the live entity that stands there:

| idx | kind | class | world (x, z) | live entity / notes |
|---|---|---|---|---|
| 0 | 0x02000040 | 64 | (212, -289) | `TObjNpcNurseBase` (4.5) |
| 1 | 0x02000040 | 64 | (-165, 278) | `TObjNpcMaleMacho` (8.7) -- shop keeper pair |
| 2 | 0x02000040 | 64 | (-231, 240) | `TObjNpcMaleFat` (11.4) |
| 3 | 0x02000040 | 64 | (-202, 266) | `TObjNpcFemaleMacho` (12.3) |
| 4-7 | 0x02000000 | 0 | (229, 254), (231, 267), (230, 241), (233, 229) | **player spawns** -- P1 and P2 use 4 and 5 |
| 8 | 0x02000043 | 67 | (360, 26) | `TObject` (0.0) |
| 9 | 0x00000045 | 69 | (0, -1730) | `TObject` (0.0) -- far south, on the x=0 corridor to the office at (0,-2015) |
| 10 | 0x02000040 | 64 | (187, 333) | `TObjNpcCloakroomBase` (11.8) |
| 11 | 0x02000040 | 64 | (-251, -32) | `TObjNpcCloakroomBase` (17.5) |
| 12 | 0x02000045 | 69 | (0, -60) | `TObject` (0.0) |
| 13-16 | 0x02000041 | 65 | (-334,-116), (-320,-154), (-258,-206), (-294,-183) | **no entity** -- walked there in round 50, street furniture |
| 17 | 0x02000049 | 73 | (193.5, -93.5) | `TObjCityDoor_Med` (0.0) |
| 18 | 0x02000046 | 70 | (-165, 147.5) | `TObjCityDoor_Shop` (0.0) |
| 19 | 0x02000040 | 64 | (-127, 248) | `TObjNpcConnoisseur` (9.1) |
| 20 | 0x02000047 | 71 | (185, 173) | `TObjCityDoor_Guild` (0.0) -- **inert** |
| 21 | 0x02000048 | 72 | (254, 25) | `TObjCityDoor_Warp` (0.0) -- the one working door |
| 22-25 | 0x02000000 | 0 | (286, 22), (295, 39), (295, 6), (305, 22) | four more spawns, clustered at the Warp door |
| 26 | 0x02000044 | 68 | (308, 211) | `TObject` (0.0) |
| 27 | 0x02000057 | 87 | (228, 291) | the only class-87 object in the set -- at the lobby's centre, i.e. the **teleporter pedestal** |

### What the map settles and what it suggests

* **Only one door works.** `0x48` (Warp) transitions to room 40; `0x47` (Guild), `0x46` (Shop) and `0x49` (Med) are placed
  identically and do not. Med only became reachable from the *room-20 side* in an earlier round, so a door record is not
  by itself a portal.
* **The southwest cluster is furniture.** Walking into it (round 50) found no entities at all: the four class-65 records
  are street fittings, not the guild.
* **`0x45` at `(0, -60)` and `(0, -1730)`** are the only `TObject`s on the central axis, and the single-player office sits
  at `(0, -2015)`. That corridor is the most promising unexplored line in the city.
* **Nothing in this set is a counter that answers `A`.** The guild, if it is an object at all, is not placed by
  `map_city00_00o.dat`.
