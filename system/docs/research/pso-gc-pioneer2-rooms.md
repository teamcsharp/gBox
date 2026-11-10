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
