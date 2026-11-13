# RE5 native mine departure audit — 2026-11-13

Village round `1bdc96ce25874b29b9d2c6340b083d01`, after native arming fix d56,
lasted 126.10 seconds and ended in defeat: 35 kills, 17,400 points, and 333.88 seconds on the game timer.
Native telemetry recorded 27 placed mines, 15 trigger observations and 17 removals
(2 unattributed). A removal alone is not an explosion or damage credit.

At 1794571361.149 the latest ring's escape route passed an older owned mine,
generation 415 at (-8680.24,769.79,4163.78). Its player clearance fell 344.7→294.1→257.0→227.6 cm.
The route itself contained (-8671,767,4211), almost over that mine. Escape
clearance still measured only the most recent batch. At 1361.603 the room-map
postprocessor changed the mine run into wall-follow movement.

At 1794571367.283 the latest-batch escape was marked complete with 1504.8 cm
clearance, but older armed mine generation 295 at (-8364.3,720,4537.91) was 251.8 cm away.
At 1367.533 its native trigger latch was set, its primary collider was disabled,
and its proximity collider pointer was null. HP fell 342→1, with the player
303.6 cm from that mine. A second owned mine generation 415 triggered in the same sample.
This is strong temporal/geometric evidence of a mine-related downing, not a
native damage-owner attribution. The final death occurred later, at 1381,
with HP 1→0 and a nearby enemy. Zero legacy `mine_blast_hp_loss` is not proof
of safety: those counters intentionally do not infer damage from native removal.

The native update at RVA 0x81F700 (Ghidra 0x0091F700) sets the trigger latch and
executes the explosion branch. Its cleanup removes the proximity collider
at unit+0x28C8 and calls virtual+0x270 to disable the primary collider. The observed
trigger/disabled/null combination therefore supports branch execution beyond
an actor merely disappearing. It does not identify which explosion damaged whom.

The final pad snapshots are marked `pre_decision` and come from transport-held
state. Phase/reason fields describe the latest published bot decision; they must
not be presented as a same-instant input acknowledgement.

## Changes and validation

`Mines.native_sites` now includes earlier standing mines, receipt hazards and
the current census. Completion requires clearance from every site. The final
`re5_native_mine_escape.guard` runs after aim/wall rewrites, validates actual
movement against every mine, native floor, room collision and known stage
hazards, and publishes requested/applied controls plus route and clearance.
Its route search uses verified floor adjacency and may start with a bounded,
collision-checked sideways step out of overlapping margins. It cannot invent
an off-mesh action link. Failure to find supported escape is reported explicitly.

Grab/QTE input and active native equipment/healing synchronization remain in
control. During a boosted shot or its tail, the guard releases the trigger and
keeps movement neutral until the animation lock ends, then departs. It does
not perpetuate rapid fire while waiting for a movement opportunity.

128 focused tests passed across native mine escape, native scheduling/census,
legacy mine compatibility and final stage movement safety. These are offline
regressions; subsequent live rounds must establish actual survival improvement.
The integrated native scheduler now defers new mines during a weapon handover
and rechecks that admission before native calls. New automatic weapon attachment
requests likewise wait while a native mine escape is active; an existing native
transaction still completes. The final coherent safety/equipment/flight suite
passed 171 tests after these admission and integration changes.

Spark evidence directory:
`/home/ehm_eckx/gBox/system/gbox-data/analysis/merc-tuning-20261113/`:

- `re5-d56-village-1bdc96ce-round.json`: full completed round.
- `re5-d56-village-1bdc96ce-mine-audit.json`: trigger, damage and final-round audit.
- `re5-d56-village-1bdc96ce-old-mine-escape-window.json`: 1354–1369 focused flight window.

Native source export:
`/home/ehm_eckx/gBox_alt/analysis/merc-full/re5-674c8828-20261113/0091f700.json`.
