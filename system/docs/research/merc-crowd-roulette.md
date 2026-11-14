# Periodic crowd tactics

The shared crowd scheduler becomes due 120 seconds after the current round and
player lifetime starts. Ordinary crowd rings and scatters do not reset that
clock. Hit, grab/QTE, traversal and boss defenses keep their existing priority.
Once due, an additional volley uses its own cadence, with at least six seconds
since the last ring. The shared flash gap and tight-crowd checks still apply to
any additional flash. An enemy marked dangerous does not suppress a due volley
merely because the ordinary defensive ring remains in cooldown.

A full reactive flash ring may fulfill an overdue flash volley when its crowd,
owner, capability and clearance checks pass. It remains the same emergency
operation, with no added native call. Its record explicitly says
`coalesced: reactive_flash` and retains the source event. Only its full verified
receipt increments `crowd_roulette_coalesced`; an uncertain or refused ring
cannot satisfy the clock. A coalesced hit/QTE does not create another mine
demand, because that event already has its own mine response. Existing native
pending, mine escape and remote-bomb gates also apply to this accounting.

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

A chosen request is logged before submission. `executed` requires a verified,
confirmed receipt with the full requested native detonation count and the
actual selected effect.
Partial, missing, mismatched and refused receipts do not count as execution.
An uncertain request is not replayed; the next periodic opportunity starts a
new 120-second interval. A positively unsubmitted busy refusal instead retries
after ten seconds, provided it reports no prepared actors or effects. Async
results stay attached to their original lifetime,
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

## 2026-11-13 suppression evidence

Spark archive `analysis/merc-tuning-20261113/re5-4d2c-swarm-admission-1794586007.json`
records 59 reactive requests, 52 deployed rings and an overdue periodic tactic
waiting for the shared 90-second cooldown. The previous scheduler deliberately
excluded reactive rings from its clock, so repeated successful defense could
postpone periodic selection indefinitely. This repair accounts for that existing
defense honestly; it does not claim an additional damaging swarm.

RE4's ordinary scatter and inventory throws remain disabled by their separate
title switches; its ring offers verified hand and flash effects. RE5/RE6 native
rings and scatters currently advertise flash only. RE6's inventory throw burst
has separate equipment, floor and existing-bomb gates; its burst constant is a
minimum speed, while the configured native throw mod defaults to 20x. No actual
20x throw cadence is established by scheduler tests. In RE5, the live throw path
also repeatedly aborted because the grenade did not reach the character's hand;
that equipment failure is independent of periodic scheduling.
