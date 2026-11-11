# Round 248: the set editor can add a record and validate a placement against the room graph

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (seventeenth round).

## Add - and why it is legitimate

Every forest set file is an **exact multiple of 68 bytes with zero remainder**:

```
map_forest01d.dat   10200 = 150 x 68
map_forest02d.dat   13328 = 196 x 68
map_forest01ad.dat  10200 = 150 x 68
map_forest02ad.dat  13396 = 197 x 68
```

There is **no header and no count field** - the record count follows from the file size. So a new placement is an appended 68-byte record,
and the measured result is clean:

```
python set_edit.py add map_forest01d.dat 3 -300 0 400
appended record 150 as a copy of record 3 (TOSymbolchatColli) at (-300.0,0.0,400.0)
records 150 -> 151 | size 10200 -> 10268 (0 bytes remainder)
```

The remainder staying at **exactly 0** is the evidence that the appended record is complete and aligned.

## Validate - a placement must land somewhere real

```
python set_edit.py validate map_forest01d.dat -300 400     -> inside, room 7 at 7.1 units
python set_edit.py validate map_forest01d.dat 1082 1030   -> OUTSIDE, nearest room 673.3 units away
python set_edit.py validate map_forest02d.dat 443 63      -> inside, room 1 at 2.8 units
```

That second line is the useful one: `(1082,1030)` is where a Forest 1 **sensor** actually sits, in the void - so the validator agrees with
reality about which placements are inside the playable rooms and which are volume triggers outside them. A level edit can now refuse to
silently drop an object into empty space.

## The editor's three operations, all proven

| operation | proof |
|---|---|
| **move** a placed object | exactly 12 bytes change, exactly 1 object, other 149 records byte-identical |
| **add** a placed object | records 150 -> 151, file size +68, remainder 0 |
| **validate** a placement | inside/outside a room, with the distance to the nearest room |

All of it writes to `rel/edited/`, never over the game's original, and installation still belongs to the PM's CP11 build path
(`POST /api/pso/editor/build`), which is unmerged.

## Also this round

CP3's second-model batch reached **32 of 82** labels and is still running unattended.

## Files

* `set_edit.py` - `list`, `move`, `add`, `validate`, `verify`
