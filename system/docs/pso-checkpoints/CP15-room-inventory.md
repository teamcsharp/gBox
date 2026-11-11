# CP15 room inventory — step 4 answered (the lobby sets are floor 15, not city rooms; measured)

Session identity: DeepSeek    Branch: ds-pso-cp15-room-inventory-20261110    Commit: this branch
Goal: 4 (P1), and the close document's lobby lead

## The question CP15 step 4 makes a precondition

> *"Before you walk to any door in the `map_lobby_01..10` sets, check that those sets are loaded in the offline city at
> all. ... Fifteen `map_lobby_*` sets with colour and soccer variants look like the **online lobbies**, not city rooms.
> This is inferred, not measured. So confirm residency before you walk."*

## Measured, from the executable's own floor table

`gbox/pso_floor_map` reproduces the two 36-entry tables (`FUN_80207E88`, `0x804C8FC0` / `0x804C9270`). Reading every
floor:

* **floor 0 = `map_city00`, layouts `("map_city00_00",)`** - the offline city loads exactly one layout and it contains no
  lobby name.
* **floor 15 = `map_lobby_01`, layouts = 15 entries**: `map_lobby_01` … `map_lobby_10`, `map_lobby_red_be00`,
  `map_lobby_yellow_be00`, `map_lobby_green_be00`, `map_soccer11`, `map_soccer12` - the ten lobbies, the three colour
  variants and the two soccer maps, exactly the fifteen sets the close document listed.
* **no other floor claims a lobby** (checked all 36).

And on the disc those fifteen sets exist as files, `SET/map_lobby_01o.dat` … `SET/map_lobby_soccer02o.dat` (15 `.dat`
files, matching the 15 layouts).

## What that means for P1

The lobby sets are **floor 15**, a floor of their own - not rooms of the offline city. So a walk to one of their
`TObjDoorKey` doors **cannot be reached from the offline city's floor 0**: the city loads `map_city00_00` only, and the
lobby area is entered as floor 15 (online, or through the transition that sets floor 15). The close document's lead was
right to flag the inference, and the measurement retires the "walk to a lobby door from the city" route for the offline
city.

What remains for P1, in the guide's own order:

1. the operator's answer to the CP00 question;
2. **both players inside room 40's teleporter ring** (never tested - round 26 tested the lobby pedestal);
3. the live actor dump (`pso_actor_dump`) of `TObjCityDoor_Warp` against `_Guild`, then CP7's decompile of the differing
   handler for the condition it checks;
4. do **not** walk the lobby sets offline (this file).

## Tests

`tests/test_pso_floor_map.py` **9 passed** - the seven pre-existing plus two now pinning this measurement:

* `test_the_offline_city_is_floor_zero_with_one_layout` - floor 0 is `map_city00`/`map_city00_00`, no lobby;
* `test_the_fifteen_lobby_sets_are_floor_fifteen_not_city_rooms` - floor 15's 15 layouts split 10 + 3 + 2, and floor 15
  is the only floor that claims a lobby.

## Needs

- nothing from the operator for this measurement;
- for the remaining P1 route, a live window (CP4's launch path is still the RE session's to unblock) or the operator's
  answer.

Next: CP15 step 2's "both players inside room 40's teleporter ring" needs a live session; offline, the next best is CP6.2
(`n.rel` geometry) or CP15 step 3's handler decompile once the actor dump exists.
