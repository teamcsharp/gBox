# Round 252: one command proves the whole level editor

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (twentieth round).

## `editor_selftest.py` - 10 checks, all passing

```
=== level editor self-test
  [PASS] Forest 1 rooms          (11 rooms)
  [PASS] Forest 2 rooms          (14 rooms)
  [PASS] Forest 1 doorways       (61 edges)
  [PASS] Forest 2 doorways       (76 edges)
  [PASS] Forest 1 objects        (150 objects)
  [PASS] Forest 2 objects        (196 objects)
  [PASS] place inside a room accepted        (room 7 at 7.1 units)
  [PASS] structure verified after the placement  (150 -> 151 records, 150/150 byte-identical)
  [PASS] place in the void refused           (673.3 units from room 6)
  [PASS] edited file still well-formed on disk

10/10 checks passed
```

Every layer is exercised against the live viewer: both floors' rooms and doorways, both floors' object sets, a real placement accepted with
its structure verified, a void placement refused with a reason, and the file on disk re-checked independently of the request that wrote it.

That last distinction matters: the final check does **not** trust the placement response - it runs the structural validator itself against the
file on disk and the shipped original.

## What the editor is, in one line

**Map -> rooms -> doorways -> placements -> inspect -> place -> validate -> prove.** Every arrow is measured, and none of it needs a game
until boot acceptance.

## One honest note about the self-test

Each run appends a record to `rel/edited/map_forest01d.dat` (the file grows by 68 bytes per accepted placement). That is correct behaviour for
a test that exercises placement, but it means the edited file is a scratch artefact - the pinned original plus a growing tail - not something
to install. Installation belongs to the PM's CP11 build path, which starts from a clean copy.

## Files

* `editor_selftest.py` - the 10-check suite
* `set_check.py`, `set_edit.py`, `map_viewer.py`, `rooms_mesh2.py`, `room_contents.py` - the chain it tests
