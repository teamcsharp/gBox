# Round 251: the editor now proves its own output structure before claiming a placement

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (nineteenth round).

## The risk this addresses

Last round's hand-off recorded: *"no edited set file has ever been booted by the game"*. Runtime acceptance still needs a session, but the
offline half of that risk - "is the edited file even well-formed" - can be answered, and now is, automatically.

## `set_check.py` - the invariants the format actually shows

1. size is an exact multiple of 68 (no header, no trailer);
2. every class id has a zero low byte (`index << 8`, as every shipped record does);
3. every position triple is finite and within bounds;
4. every class index resolves to a registry name or to an index the shipped files already use;
5. against an original: the count grows by exactly the additions and **every original record survives byte-identical**.

Measured:

```
map_forest01d.dat (shipped): 150 records, 10200 bytes
  unnamed class indices used: [6]
  PASS: every structural invariant holds

edited/map_forest01d.dat:    151 records, 10268 bytes
  against map_forest01d.dat: 150 -> 151 records (+1), 150/150 original records byte-identical
  PASS: every structural invariant holds
```

**150/150 original records byte-identical** is the strongest statement available without booting the file.

## And it is wired into the editor, not just available

`POST /api/place` now runs the checker on the file it just wrote and refuses to report success unless the structure passes:

```
place at (-300,400)  -> ok true, room 7, 7.1 units,
                        "structure_ok": true,
                        "structure": ["against map_forest01d.dat: 150 -> 151 records (+1),
                                      150/150 original records byte-identical",
                                      "PASS: every structural invariant holds"]

place at (1082,1030) -> ok false, "outside the walkable rooms (nearest room 6 at 673.3 units)"
```

So the editor has **two gates**: the placement must land inside a walkable room, and the resulting file must satisfy every structural
invariant while preserving all original records. A malformed edit cannot come back as a success.

## What still needs a game

Boot acceptance: whether the game loads an edited set and shows the placed object. That is one session away, and the file it will be asked to
load is now provably well-formed.

## Files

* `set_check.py` - the structural validator (`python set_check.py <file> [original]`)
* `map_viewer.py` - `/api/place` runs it and reports `structure_ok`
