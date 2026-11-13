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
