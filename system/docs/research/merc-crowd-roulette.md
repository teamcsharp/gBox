# Periodic crowd tactics

The shared crowd scheduler becomes due 120 seconds after the current round and
player lifetime starts. Ordinary crowd rings and scatters do not reset that
clock. Hit, grab/QTE, traversal and boss defenses keep their existing priority.
Once due, it reserves the next permitted cooldown slot, preventing frequent
routine flashes from indefinitely delaying the periodic selection.

Selection requires at least two living enemies on the player's floor, a living
bot-controlled player, supported blast clearance, and no pending native mine,
remote bomb, flash request or required mine escape. It does not change movement
inputs. The title's floor, mine-clearance and escape controller remain in charge.

Each draw chooses a ring or an enemy-directed scatter and a currently available
native effect. Scatter kinds must also appear in that native controller's
separately implemented scatter set. The previous complete choice is excluded
when an alternative exists. Current production capabilities are hand and flash
for RE4, and flash for RE5/RE6. The RE5 background worker remains flash-only.
Nitrogen, unsupported launcher rounds and native mine-projectile rings are not
enabled by this scheduler. Native 20x throw animation is a separate title-specific
modification; this scheduler does not claim to apply or prove it.

A chosen request is logged before submission. `executed` requires a confirmed
receipt with positive native detonation count and the actual selected effect.
Partial, missing, mismatched and refused receipts do not count as execution.
An uncertain request is not replayed; the next periodic opportunity starts a
new 120-second interval. Async results stay attached to their original lifetime,
and cancelled results cannot create mine demands or leave the scheduler pending.
The last 24 events and scalar counters are kept in round stats.

A confirmed periodic flash can create one additional placement demand:

* RE5: a unique event requests either one or five native proximity mines. The
  event is fresh for eight seconds and must match the round, player, generation,
  position and count. The existing automine worker consumes it once, respects
  enabled/uncertain/escape/clearance gates, retains the gun, and records actual
  armed-unit receipts. Placement and measured escape remain in the native mine
  controller. A request or predicted hazard is never counted as an armed mine.
* RE6: the confirmed receipt publishes the flash timestamp expected by the
  existing remote-bomb controller. That controller retains its all-bomb census,
  old-bomb gate, native placement proof, immediate escape and five-second
  detonation deadline. The scheduler does not allocate or detonate a bomb.

The implementation is in `gbox/mercs/crowd_roulette.py`; `grenade_ring.control`
integrates its decisions and receipts. Tests cover recurring routine activity,
flash-cooldown starvation, emergency priority, native pending/escape gates,
actual effect identity, unit conversion, asynchronous cancellation and native
mine follow-up ownership. These tests establish scheduling and receipt behavior;
live effectiveness still needs a deployed round review.
