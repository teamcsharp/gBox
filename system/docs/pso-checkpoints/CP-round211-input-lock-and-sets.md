# Round 211: the input lock is now impossible to bypass, room-to-room exploration works, and the set-file format is decoded

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## I broke the rule, and then made it impossible to break

While walking the character west to follow the operator's "the only exit is west", my ad-hoc script called `hold()` directly and
**sent input while `operator_active` was true**. That is exactly the fight the operator reported, and it was my own helper bypassing the
lock, not the lock failing.

Fixed at the lowest level: **`pso_input.py` is now the only way bot code presses a key.** `hold`/`tap` check the operator lock before
every press and declare the action window. Verified by self-test:

```
simulated operator active -> tap sent nothing, log: "operator has the controller: holding off"
```

`explore.py` and `flip_switches.py` now import those locked helpers (`explore.hold is pso_input.hold: True`,
`flip.hold is pso_input.hold: True`), so no script can accidentally bypass arbitration again.

## Room-to-room exploration works

`explore.py` implements the operator's loop: rooms come from the collision-graph room map, each entered room is marked visited, and the
bot steers to the nearest unvisited one, flipping switches it passes and watching the entity table for a warp class. Measured on the
live game:

```
12:39:45 entered room 8 at (-94,343); visited [8]
12:39:55 heading for unvisited room 6 centre (-59,92)
12:40:27 entered room 6 at (-68,86); visited [6, 8]
12:40:37 heading for unvisited room 1 centre (141,-194)
```

**Room 8 -> room 6 in 42 seconds**, through a real doorway, with no teleport.

## The level set format is decoded

* set class id = **registry index x 256** (verified: id 4352 = index 17 = `TOSwitchAttackSub`);
* positions are three **little-endian floats at +0x10 / +0x14 / +0x18**;
* **all 150/150 records decode** in both `map_forest01d.dat` and `map_forest01ad.dat`.

The two `TOSwitchAttackSub` records come out at **(-520, 700, -500)** and **(-400, 250, -100)** - the operator's two switches, matching
the earlier independent decode exactly. `TObjAreaWarpForest` (index 205, the forest teleporter) is **not** in either forest set file, so
the teleporter only becomes visible in the entity table once its room is streamed - which is why exploring matters.

## The operator's map correction

The minimap shows this room has **one exit, to the west** (green door marker). My explorer routes by room centres, so it can steer at a
wall. The fix is to prefer the minimap's green door markers as exits: `minimap_extract2.py` already extracts them (green clusters in the
corner map), so the next version of the explorer takes the exit marker's bearing as the intermediate target instead of the room centre.

## State

All bot processes stopped; controller with the operator. Player around (-65, -39), HP 40, floor 1.
