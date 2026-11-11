# Round 249: placing a piece from the map - validation in the loop, refusals included

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (eighteenth round).

## The loop the operator asked for

They wanted the level editor to be the top-down map with everything layered on it. This round closes the last interaction:

* tick **place** in the side panel, type the **record** to clone, click a room;
* the viewer validates the point against that floor's room graph, appends the record to an **edited copy** of the set file, and reports
  either `placed in room N (d units)` or `refused: <why>`.

## Verified against the live endpoint

```
POST /api/place {floor:1, record:3, x:-300, z:400}
  -> ok true, room 7, 7.1 units,
     "appended record 150 as a copy of record 3 (TOSymbolchatColli) at (-300.0,0.0,400.0)
      records 150 -> 151 | size 10200 -> 10268 (0 bytes remainder)"

POST /api/place {floor:1, record:3, x:1082, z:1030}
  -> ok false, "outside the walkable rooms (nearest room 6 at 673.3 units)"
```

The refusal is the important behaviour: the same point where a real sensor sits in the void cannot be used to drop a piece by accident, and
the reason names the nearest room and the distance so the mistake is diagnosable.

## What the editor now is, end to end

| layer | how it is built | evidence |
|---|---|---|
| **rooms** | erode + grow + flood over the collision mesh | 11 rooms Forest 1, 14 Forest 2, validated against the known graph |
| **doorways** | cells whose neighbour belongs to another room | 61 / 76 edges |
| **placements** | 68-byte set records, class + position | 150 / 196 objects decoded |
| **inspect** | click a room | room id, cells, centre, object counts |
| **edit** | place mode + click | validated append, refusal outside rooms |

All of it offline, all of it from data the game ships, and none of it writing to the game's original files - the edited copies live in
`rel/edited/` until the PM's unmerged build path installs one.

## Also this round

CP3's second-model labelling batch continues unattended (32+ of 82 at last check, ~25 s each).

## Files

* `map_viewer.py` - `/api/place`, place mode, record picker, refusal display
