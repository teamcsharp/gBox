# The boot test for a written model: staged, not yet run

2026-11-06. The writer produces a real archive with changed geometry; making a game draw it is the one step still open.

## What is ready

`gbox.mt_build.build_modified_arc` took the game's own `uEm6c.arc`, found `pawn\em\em6c\model\em6c00`, shrank part 0
(55 vertices, format `0x1580b60c`, stride 20) to half size, repacked the MOD and the archive, and re-read the result:

```
width      0.52 -> 0.26 cm      exactly the 0.5 asked for
model      76584 bytes, still valid, still 14 parts
archive    4,362,664 bytes, all 68 entries intact
```

The artifact is staged at `~/gBox_alt/re4-lab/em6c-modified.arc`.

## Why it has not been installed

The Spark has ONE emulator slot and the nightly rotation holds it (RE5, mod `cast-inverted`). A launch request issued
during a rotation run is queued, not executed: the session that came up after the request was the rotation's own launch,
identified by its `mod: cast-inverted` field rather than the test overlay. Two launches cannot overlap, so the test needs
a slot window rather than a retry.

A test overlay was staged under `mods/52d15709be0fda1a/mtf-geometry-write-test/romfs/nativeNXx64/ImgNX/Archive/uEm6c.arc`
and then removed again, so the rotation was never exposed to unverified geometry.

## The bisect to run when the slot is free

Two variants, one minute each, so a failure names its own cause:

1. **re-encoded but unchanged geometry.** Install an archive whose model was rebuilt from its own bytes and repacked. If the
   game fails here, the problem is the archive/MOD writer, not the new geometry.
2. **changed geometry.** Install the shrunk-part archive. If (1) booted and (2) fails, the problem is in the vertex or
   record rewrite specifically - which is a much smaller search space than the white-screen failures that stalled the
   earlier MOD swaps.

Read the result the way previous rounds had to learn to: a constant-brightness frame (about 238) means a white screen
rather than a dark one, so compare the frame's mean and variance against the rotation's own captured frames instead of
judging "it looks black".
