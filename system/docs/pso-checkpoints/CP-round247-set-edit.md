# Round 247: the editor's write side, prototyped and proven clean at the byte level

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (sixteenth round).

## What was missing

The viewer can now show rooms, doorways and every placed object, and clicking a room lists what it holds. The one thing an editor needs and
did not have is the ability to **change** something.

## `set_edit.py` - move a placed object, on a copy, with proof

A set file is a flat array of **68-byte records**: a big-endian u16 class id at +0x00 (name via the registry at `id >> 8`) and the position as
three little-endian floats at +0x10 / +0x14 / +0x18. The editor writes only those twelve bytes.

```
python set_edit.py list   map_forest01d.dat
python set_edit.py move   map_forest01d.dat 3 -300 0 400
python set_edit.py verify map_forest01d.dat edited/map_forest01d.dat
```

## The proof, measured

```
moved record 3 (TOSymbolchatColli) from (333.4,16.2,583.5) to (-300.0,0.0,400.0)
bytes changed: 12 (expected 12) | objects changed: 1 (expected 1)

verify: records 150 vs 150 (same count: True) | differing objects: 1
  record 3 TOSymbolchatColli: (333.35, 583.55) -> (-300.0, 400.0)
file sizes: 10200 -> 10200
```

**Twelve bytes, one object, identical size, every other record byte-identical.** That is the property a level editor must have: a placement
change is a localised record edit, not a rewrite that risks the rest of the file.

## What it deliberately does not do

It writes to `rel/edited/`, never over the game's original, and it does not try to *add* a record - a new placement needs a free record slot
or an extending file, and the PM's CP11 branch already owns the build/install path (`POST /api/pso/editor/build`). The point of this prototype
was to establish the record semantics with evidence before anything is offered to the game.

## Next steps for the editor, in order

1. **add** a record (find free slots, or extend and update any count field the format carries);
2. **validate** a moved object against the room it lands in - a rock in a corridor is legal, a sensor lost in the void is not;
3. **install** the edited file through the PM's unmerged build path rather than by hand.

## Files

* `set_edit.py` - list / move / verify, writing only to `rel/edited/`
