# RE4 Castle wall navigation, 2026-11-13

Observed round `aa770748789a40b9b1ec9c1eb194ef2e`, session
`b445b3e9a1404bd5-0f4914115f35450e`. The requested stage label was Waterworld;
the captured navigation geometry was Castle, room `r402`, mesh
`re4.2632-4093-7ebde3aaaa25ec9b`. These must not be conflated.

The player stood at `(6241.9, 3073.2, -22228.5)` **millimetres**, member triangle
3903, yaw approximately -1.725. The active `bonus-ITA[29]` target was
`(-4500, 12000, -22100)`, a Waterworld (`r404`) time bonus, absent from Castle.
Its horizontal distance is 10.7427m, matching the active goal description. The
Castle route with 350mm clearance returns no path to that foreign objective.
The capture counted 191 missing mesh routes and 2081 direct movement ticks.
One incident lasted 14.4 seconds with 5.2mm travelled and 3mm net displacement.
Later the bot did move and climb; this was repeated wall pressure, not a
permanent game freeze.

The snapshot does not prove whether the stale picker or a menu-stage hint
initially introduced the wrong goal. It does prove that the goal survived an
actual geometry change and that a failed route was converted to direct movement.
A subsequent Castle ITA[1] endpoint was a combo pickup incorrectly selected and
labelled as a time bonus.

The fix scopes automatic bonus state to the goal round, room and mesh signature,
invalidates old automatic objectives when that identity changes, and selects only
`time_bonus` records. A player outside the selected mesh's floor cannot create a
new goal. Leaving the floor during a same-room native traversal does not cancel
the current objective. Explicit operator goals are retained.

A missing route can use a direct path only if the mesh proves continuous floor.
The combat caller respects an empty walker result. An outer movement guard runs
after bonus and combat rewrites, checks the actual tank-control heading against
continuous floor and the room's SAT body-clearance map, and measures actual
displacement under sent movement. After 1.2 seconds with less than 180mm of
progress it blocks that local heading for six seconds. Recovery turns in place
until the observed heading aligns with proved floor; it never invents a backstep.
Gun aiming, non-controllable game sequences and fresh owned verified native
traversal retain their original controls. Nonmovement door/action taps are not
overridden by a previous recovery.

`walk_failure` records the round/player/generation/mesh owner, position and
anchor, held keys, heading, elapsed time, net displacement, route point and route
status. The ordinary navigation-incident recorder continues to collect the
surrounding combat and movement samples.

Evidence on Spark: `gbox-data/analysis/merc-tuning-20261113/` contains
`re4-current-wall-capture.json`, `re4-current-wall-incidents.json`,
`re4-current-wall-geometry.json`, `re4-current-wall-31s.json` and
`re4-aa770748-wall-root-cause.json`. Regression tests use the shipped Castle and
Waterworld meshes and the captured coordinates, plus synthetic walls, ledges,
stationary pressure, real movement, lifecycle changes and native traversal.
Live effectiveness still requires observation after the root agent's deployment.

## Base portal initiation and interrupted round b96ab135

After activation of `c1a97781`, session `e41fad8986bf40a5-d56f40bae064467a`
recorded Base round `b96ab13521f44b0ba3753d1bd5afbe7b`. Three `r403` ladder
portals were refused after four to five seconds. Incidents 0001 and 0002 retain
accepted Y pulses, alternating left/right controls, positions and local geometry.
This was not an absent interaction-button command.

Offline replay against the shipped SAT/AEV data reproduced the final guard's
reversal at `(41900, 20536.1, 15012.1)` mm, yaw `-2.20474267`, and
`(51545.9, 20536.1, 26070.7)` mm, yaw `0.584307015`. The old walker aimed
1.5 m beyond the portal while still up to 1.2 m from its approach. At the first
position the actual probe brushed a wall at 182 mm clearance (300 mm required);
at the second its endpoint had no floor. The guard correctly refused those
directions, but the conflicting approach repeatedly turned back into them.
The exported first ladder approach itself is only 180 mm from the SAT railing.

The repair chooses a stand point on the approach floor with continuous floor
and SAT body clearance, aligns before each short step, then faces the portal
and pulses Y without translation. Fresh actor/round/mesh-owned approach commands
prevent an earlier recovery turn from replacing that stationary interaction.
Every actual forward step still passes the ordinary floor and collision checks.
Approach and interaction attempts are bounded; a native traversal already in
progress is allowed to finish before another prompt attempt. `walk_portal`
records the state, timestamp, stand point, portal and remaining distance.

Validation: 148 tests passed across portal approach, walker, movement safety,
bonus routing, doors, native traversal and navigation. The two measured poses
reach stationary Y in the offline movement replay without stepping through
the gap. **Live ladder descent remains unverified.** A button request or safe
approach does not establish that the game accepted the traversal.

The same round later stopped advancing its clock after the first Mine Thrower
equip: timer 157.91 seconds, score 20,410 and 20 kills stayed unchanged. It ended
at `1794581550.87` with outcome **interrupted**, not a completed win or death.
The 674.5-second record contains 641.9 seconds stationary, including a 596.7-second
stretch; final HP was 1680. Eight ordinary trigger requests and three unconfirmed
aim-book attempts do not prove marksmanship; the telemetry attributed 18 kills
to rings. The frozen interval must not count as successful survival. The equip
freeze is a separate investigation from portal initiation.

Durable evidence stays on Spark under `gbox-data/analysis/merc-tuning-20261113/`:
`re4-b96-offline-crossing-replay.json`, `re4-b96-frozen-live.json` and its JPEG,
`post-c1a97781-b96-termination.json`, and `post-c1a97781-round-audit.jsonl`.
The complete run is
`gbox-data/mercs/round_maps/010099A00BC1E000/Base/20261113-084116-b96ab135.json`;
the incident reports are in the same title's `unknown/navigation_incidents`
directory, named with the full round ID and `-0001.json` / `-0002.json`.
