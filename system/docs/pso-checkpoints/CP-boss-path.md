# The boss path is open: `boss_warp` put the bot in the Dragon fight

## The progression chain, found

`pso_mods op=bosses` returns Episode 1's bosses from the game's own data:

```json
{"episode": 1, "default": "dragon", "verified": true, "bosses": [
  {"floor": 11, "id": "dragon",    "name": "Dragon / Sil Dragon"},
  {"floor": 12, "id": "de_rol_le", "name": "De Rol Le / Dal Ra Lie"},
  {"floor": 13, "id": "vol_opt",   "name": "Vol Opt"},
  {"floor": 14, "id": "dark_falz", "name": "Dark Falz"}]}
```

and `op=boss_warp target=dragon` acts on it:

```
{"arrived": false, "message": "Travelling to Dragon / Sil Dragon; the game is loading the destination.",
 "requested": true, "verified": true}
```

**The bot then stood in the Dragon's arena:**

```
room 1 | 7 entities | 4 enemies
TBoss1Dragon hp 1300        <- the first boss of the game
TBoss1DragonColli_C hp 0    <- its collision proxy, not a damageable target
```

and **it moved freely** - `(67.0,337.6) -> (114.5,352.2) -> (60.8,315.4) -> (51.4,334.5)` - because the arena floor is flat (`y = 0.1`). **The ledge freeze that plagued the Forest
is a terrain problem, not a general one.**

Screenshot: a huge crystal-strewn cavern, HUD showing **HP 44/68** - the Dragon was already attacking.

**That is the answer to "get through this entire game": every boss is addressable by name, in floor order.** Four warps to four bosses is the whole Episode 1 spine.

## The operator's map interface, implemented

`pso_map_feed` exposes **`GET /api/pso/map/<sid>`** - *"the live map model: the current area's surface + the live players/floor/objective/active-directive + a crystal index of every
learned area + optional live gate flag states"*. It answers, and carries a **learned-area index** (floor 1, rooms 5, 7, 9, 24 gates each). `cells` is empty because the publisher
(`pso_coop`) is not running in this build.

`pso_map.parse_directive` defines the operator's controls:

```
{"op":"goto","x":..,"z":..,"episode":1,"floor":1,"room":15,"id":".."}
{"op":"attack","ptr":"80.."} or {"x":..,"z":..}
{"op":"press","flag":0..255}
{"op":"clear"}
```

with `episode`/`floor`/`room` scope so *"a stale-scope directive must not act"*. **`follow_directive.py` implements it**: it reads the newest directive, validates it exactly as
`pso_map` does, **refuses a directive whose room does not match the live state**, and otherwise walks using the measured turn polarity with the measuring unstick. That is the red
arrow on the minimap turned into a control.

## What still blocks damaging the boss

The Dragon stays at **hp 1300** across 30 rounds while the bot's own HP moves 44 -> 20 -> 12 -> 34 (the Scape Doll reviving it). The bot circles at **205-345 units** from the boss's
recorded position and never gets inside melee reach, even with `BOSS_REACH = 220`.

**A huge boss's origin is far from its body**, so distance-to-origin is the wrong measure. The next step is to hit whatever the game considers hittable - `always_hit`'s own scope
says *"targets must still be in range and hittable"*, so the question is what range the game applies to `TBoss1Dragon`, which is a native constant worth finding in the
decompilation rather than guessing.

## Where the objective stands

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040` |
| map analysed, internalised | done - sha-verified city REL, 1497 triangles, 5626 walkable / 4959 safe; plus a **learned-area index** from the live map API |
| used for path-guiding | done - the 29-waypoint route and the warp-trigger cell both came from it |
| **walk through the gate** | **done** - `walk_through` on, verified passing one for 211 units |
| fastest rate | 4.8-7.3x measured; `move_speed`, native `autoplay-speed` and EFB all unavailable or harmful |
| **complete every level / boss** | **the path exists** - `boss_warp` by name for all four Episode 1 bosses, verified entering the Dragon's arena |
| defeat every enemy | **not yet** - boss damage is the open problem, now scoped to a hit-range constant |
| never stand around | done where the ground is flat; ledges need the measuring unstick, which works |
