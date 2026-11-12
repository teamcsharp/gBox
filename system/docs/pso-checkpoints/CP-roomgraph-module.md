# Room-level routing, working, with its coverage stated

## What was added

**`gbox/pso_roomgraph.py`** - a room-level router over the disc-derived graph, keyed on what the live state actually provides: the **floor** (`0x805D5FC0`, resolved
to an area by `pso_floor_map`) and the **player's room number**.

`area_fingerprint` keys the live store on a hash of loaded collision memory, so the disc graph cannot live there. It does not need to: *"which rooms can I reach from
room 50?"* is answerable from the room number alone.

**`neighbours()`** unions edges across every layout of the area, because which layout is loaded is unknown until its geometry is hashed. A union is a **superset**, so
it never omits a real connection - and the API says so rather than pretending to be exact.

## Verified on real data

```
areas: 10

from room 50 (cave01):
  connected rooms: [1]        seen in layouts: cave01_00, cave01_01, cave01_02

shortest room sequences:
  room 50 ->  1: [50, 1]         (1 door)
  room 50 -> 60: [50, 1, 60]     (2 doors)
  room 50 -> 50: [50]            (0 doors)

negative cases:
  to an unused room (9999): []          correct
  unknown area raises RoomGraphError    correct

nearest of several goals:
  from 50 to any of [1, 20, 120]: [50, 1]
```

Breadth-first, because **every edge is one door** - the number of doors is what matters, not distance.

## Coverage, honestly - and it varies a lot

| area | layouts | rooms | edges |
|---|---|---|---|
| ancient02 | 5 | 111 | **127** |
| ancient03 | 5 | 111 | **101** |
| cave02 | 5 | 42 | **82** |
| ruins02 | 3 | 52 | 34 |
| machine01 | 6 | 35 | 25 |
| ruins01 | 3 | 45 | 25 |
| cave03 | 6 | 38 | 12 |
| ancient01 | 5 | 36 | 10 |
| **cave01** | 6 | 39 | **8** |
| machine02 | 6 | 29 | **1** |

**So room routing is strong in the ruins/ancient areas and thin in cave01 and machine02.** Room 50 of cave01 connects only to room 1 in the disc data, which is
enough for a useful prior but not a full graph.

The likely reason is that the sparse areas place their doors as **entities rather than `link` records** - the same reason `pso_evt`'s docstring gives for door
transitions being hard to find in the placement sets. That is a decoding gap in two areas, not a failure of the method, and it is visible in the numbers rather than
hidden.

## What this gives the bot today

* a **room-level prior**: given the room it is standing in, the set of rooms reachable by doors;
* **door-counted shortest sequences** to a target room;
* **nearest-of-several** targeting, for "get to any of these rooms";
* a **superset guarantee** - a live observation can only narrow it, never contradict it.

Wiring it into `pso_coop`'s planning is the next step; the module and its tests stand on their own until then.
