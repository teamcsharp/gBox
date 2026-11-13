# RE6 time run before combo scoring

The operator's current rule is to build the round clock to at least five minutes,
then pursue combo scoring. This uses the current clock, not a latch: collection
resumes below 300 seconds while an eligible time bonus remains.

## Evidence and scope

Spark's `gbox-data/analysis/merc-tuning-20261113/` contains
`re6-dd05-five-round-cycle-audit.json` and
`re6-dd05-five-round-swarm-admission.json`. All five recorded rounds had zero time
pickups. Long bomb escapes and stationary combat were also present; the policy
change does not establish that bonus priority was the sole cause.

The old decision path refused the run whenever a visible enemy was within 600cm.
Separately, `_bonus_wait` postponed it above 120 seconds when a combo kill was due
and any enemy anywhere remained alive. Automatic doctrine `fight` also blocked
all detours, and `hunt` could pursue enemies before the bonus run. These gates
conflicted with the time-first objective even with a valid route and no close
blocker.

## Behavior

- Below 300 seconds, an eligible native `kind == 'time'` bonus precedes ordinary
  distant combat and automatic fight/hunt directives. Unknown/nonfinite clocks
  do not establish a five-minute bank; numeric zero is handled as a low clock.
- At exactly 300 seconds or more, combat/combo policy takes over. Combo pickup
  paths also wait while the low-clock time run has an eligible target. A skipped
  unreachable bonus does not suppress all other play during its retry interval.
- Explicit commands and map goals retain priority. The reader's pre-read
  sequence preserves its contract that a new explicit command is delivered once
  even after its TTL. Unknown reader provenance is never demoted to automatic.
- The existing 300cm blocker, recent damage/hazard, critical heal, held/QTE,
  active throwable, and native remote-bomb escape gates remain ahead of the run.
  The final floor/grade/all-bomb movement guard still validates issued movement.
- Time bonuses still require approach and melee. A failed native route never
  becomes direct movement. This change does not prove active NAV ownership or
  add geometry, native writes, health changes, timer changes, or pickups.

`bonus_priority` reports the current policy; existing `phase`, `act`, and `why`
identify the actual run or the defensive action that won. These are intent,
not proof of collection. Native bonus disappearance and the existing pickup
bookkeeping remain the collection observations.

## Validation

`test_re6_bonus_priority.py` exercises the complete tick with distant/close foes,
overdue combo pacing, threshold crossing in both directions, automatic and
explicit command expiration, unknown reader ownership, critical healing,
grab/ranged-hit responses, a live remote-bomb hazard, map goals, failed routes,
and time-versus-combo identity. The new pre-fix tests reproduced 16 policy
failures; no running game was modified during development. Live pickup rate and
survivability still require observation after deployment.

The combined decision, fire, floor and wall regression run passed 397 tests
with one optional native-image skip. No rank or successful pickup is inferred
from those planner checks.
