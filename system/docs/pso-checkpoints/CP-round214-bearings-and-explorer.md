# Round 214: map bearings verified, and the explorer now follows doorways (minimap first, room graph as fallback)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, room 2

## The bearing assumption is now measured, not assumed

Exit navigation rests on "the minimap is north-up and player-centred, so a marker's bearing equals the doorway's world bearing". Compared
live at one position:

```
minimap markers:  -130.0 deg, -123.6 deg, -118.0 deg  (one blob split by the cluster threshold)
nearest world door: TObjDoor (-537.9, 180.5) at bearing -110.3 deg, 27.7 units away
marker -118.0 -> door -110.3   error 7.7 deg
```

**7.7 degrees** - the mapping holds (the spread across the three sub-clusters is the blob's own size). The bot can steer by map bearings.

## explore2: doorways, with a static fallback

`explore2.py` is the operator's loop with the map as the primary source:

1. mark the current room visited;
2. a warp class in the entity table means the teleporter - walk to it and press A;
3. a switch within 28 units - walk to it and press A;
4. otherwise pick the nearest unvisited room and take **the minimap marker whose bearing points at it**;
5. if the map shows **no** markers (an unexplored room draws blank), fall back to **the door the room graph says joins the two rooms**.

Verified dry-run in the live game (no input sent, the operator was active):

```
player (-534,-120) room 2
markers: []
target room: 3 | marker: None
connecting door: ('TObjDoor', -493, -336)
```

So even with a blank minimap the bot knows exactly which door leads on.

## Why this matters

The operator's rule was "there's only one place for this player to go" - the map's doorway. The bot now has two independent sources for that
doorway (the map's marker, and the collision-graph door edge) and takes the map first, which is the human's own view of the level.

## State

All bots stopped; the operator is playing (the lock reports `operator_active: true` throughout this round's dry runs, and no input was
sent). Files: `explore2.py`, `map_bearing_check.py`, plus the existing `door_pass2.py`, `map_exit.py`, `pso_input.py`, `pso_operator2.py`.
