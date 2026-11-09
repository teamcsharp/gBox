# RE5 Switch: out of the bus (Public Assembly), 2026-11-09

Live 21:30 UTC, RE5 Switch No Mercy on lilspark, stage Public Assembly: the operator double-clicked the map 5 m east of
the bus and the bot ran the bus's length east and west for two minutes (positions a second apart in
`gbox-data/mercs/map-goals.log`: 471,50,-273 -> 68,50,-88 -> 503,50,-282 -> 82,50,-90 ...), the mark never reached,
46 `stand_breaks`. Operator: "the bot should never stand still", "the character is stuck in the bus again".

Branch `wt-re5-bus-nav-20261109`, built and measured offline on the stage's own mesh with a kinematic player
(`system/tests/test_re5_switch_bus_nav.py`). Nothing here was run against the game: the numbers below are the bot's
reasoning on a model of the stage, and the live check is in §6.

## 1. The geometry, measured

Source: the tactical stage layout the control plane serves, `GET /api/autoplay/tactical/stage/010018100CD46000.nav2187.ddff0959`
(1,636 points, 2,187 triangles, 1,222 wall edges, 0 cross links, 45 climbs). It is byte-for-byte the PS3 layout already in
the repo, `system/tests/fixtures/tactical_map/BLUS30491-public-assembly.stage.json` (only the key's title differs), so the
tests build the mesh from that file: links are the shared edges that are not in `walls`. A climb row is
`[x, z, y low, y high]` (`tactical.climbs_of`): the fourth value is the top of the near-vertical face.

**The bus interior** (the positions in the log are in it, `NavMesh.member` 734 and 732): ten floor triangles at
y 48-51 - 731, 817, 732, 733, 658, 659, 657, 734, 735, 730, west to east - an interior 7.6 m long and 2.5 m wide, axis
heading 120 deg, from (-91..34, -38..172) at the west end to (591..705, -419..-225) at the east end. Both short ends
and both long sides are wall edges on the mesh.

**Its one opening on the mesh**: the 63 cm edge (475,50,-97)-(529,48,-130) on the NORTH side, 2.2 m from the east end,
shared by 657 (inside) and 579. From it two ramp triangles step down to the ground: 579 (centre y 35) and 578 (centre
y 21), out through the 25 cm edge (524,7,-65)-(547,7,-75) onto 340 (y 10). A 43 cm drop over about 50 cm. To `route()`
it is plain floor (neither triangle is steep - ny/|n| = 0.8 - and the centre heights differ by 14 cm, under
`STEP_DY` 110), so the route through it has no `Traversal`: the funnel's corners are the door's vertices - the jambs.

**The two "H" marks of the tactical map near the bus are not its doors.** They are the steep faces that climb from the
ground onto the bus ROOF (y ~300): climb `[270, 65, -1, 300]` is triangle 477 (264,299,68)/(246,-1,80)/(278,-1,61),
30 cm north of the bus's north wall, from ground 451 up to roof 475; climb `[724, -301, 45, 304]` is triangle 480
(708,304,-303)/(740,47,-299)/(727,45,-317), 67 cm east of the east end, from ground 655 up to roof 479. There is no
mesh link between the roof and the interior.

**The ground around**: north and west of the bus y 0-7 (the door's side), east of the back wall y 45-50 (the mark's
side: `(989,50,-441)`, the vault prompts remembered at (1007,49,-265), (1061,50,-403) etc. are low walls out there,
not bus doors).

**Routes** (`NavMesh.route`, clearance 0 = main): from the east part (471,50,-273) to the mark: `[(547,7,-75),
(825,50,-215), (989,48,-441)]` - 8.1 m against 5.4 m straight through the back wall. From the west end (68,50,-88):
`[(475,50,-97), (524,7,-65), ...]`. A spot on the ground west of the west end is NOT on the mesh (no route at all).

## 2. What each rule did wrong

Reproduced on the fixture (the World in the test: forward along his facing at 170 cm/s, B a run at 400 cm/s - the
goal log shows 3.9 m in a second -, the right stick turning at `TURN_SPEED_DEG_S`, the other left-stick directions a
step that way; the mesh's floor is where he can stand, its wall edges stop him and he slides).

1. **`_mesh_waypoint` reached the door's corner through the wall.** The route's first corner from the east part is the
   outer jamb (547,7,-75); within `MESH_WP_CM` (120 cm) of it - which happens a metre SOUTH of the door, still inside
   the bus - it was popped and the next corner (825,50,-215), beyond the north-east wall, became the heading. He ran
   into that wall for the whole minute of the run (`mesh_follows` 1707: the guard "following the route" into it),
   the never-stand backstop stepped him back 1.3 m every few seconds (`stand_breaks` 12 in 60 s) and the route sent
   him in again. Main as deployed (97d538b8, the mark driving without the wall governor): never out in 1,800 ticks.
2. **The funnel's corners are the jambs.** Even aimed well, a corner ON the edge's end is a run into the door frame
   for a body with a radius; the 25 cm outer edge made it worse.
3. **The wall governor's trail recovery reversed him along the bus.** At 21:30 the governor still applied to the mark
   (97d538b8 removed it afterwards): a stall at the wall started `_recover` with his own trail as the "observed
   movement segment" - the bus's length, the way he had just come - for `RECOVERY_S` 2 s, then the retry window
   stripped the stick and turned him to that reverse heading (`rleft` alone in the log, standing 2 s), then the wall
   memory's preempt (120 cm, 35 deg) stopped the next approach before it reached the wall. On the fixture: 1.5 s and
   more with no stick, out only by luck at 8.8 s.
4. **The never-stand step never chose the door.** Its open-floor probe compared the floor's height at the probe's end
   with his own: through the door the ground is 43 cm lower, so the ramp read as a wall and every step went back into
   the bus. The mesh guard's probe had the same flaw.
5. **Within `NAV_DIRECT_R` (3 m) the straight line took over**, even through a wall: 2.2 m from a spot behind the
   west end, the mesh was not consulted and he pushed the end wall.
6. For doors that ARE action links (ladders, drops - not this bus, but the same walker), the landing was never
   confirmed: after the prompt took him down, the cached route still began with the `Traversal` and the push at the
   portal continued from below until the next plan.

## 3. The fix (re5_switch.py, re5_switch_wall.py, re5_nav.py; all hot-reloadable modules)

- `MESH_LOOKAHEAD`: a waypoint within `MESH_WP_CM` is passed only once the NEXT one lies on open floor from him
  (`_mesh_open`: `floor_segment` with the far end at the floor's own height there); within `MESH_WP_NEAR_CM` (45 cm)
  whatever lies beyond. stats `mesh_lookahead_holds`. The same height-aware probe serves the mesh guard and the
  never-stand step (a ramp down through a door is open floor).
- `MESH_CORNER_CLEARANCE_CM` 35: `re5_nav.route(..., clearance=)` / `funnel(..., clearance)` / `shrink_portal` keep
  the funnel's corners that far in from a portal's ends; an edge narrower than twice it is crossed at its middle
  (the bus door: (502,49,-114) then (536,7,-70)). Optional, default 0: no other caller changes.
- `WALL_ROUTE_YIELD` (re5_switch_wall): a wall met while the route steers this tick (`_mesh_wp` fresh) is
  `start_route`: the bounded back-step only (2 x `WALL_BACK_S`), his heading kept, the route planned again at the
  next call, and on completion the route's own keys at once (no empty tick). The wall memory's preempt and the retry
  window do not apply to a routed push - only a measured stall counts. The trail recovery stays for walks the route
  does not steer. stats `wall_route_yields`.
- `_route_wall` / `MESH_CROSSING_PUSHES` 3: stalls aimed at one waypoint are counted (`mesh_crossing_pushes`); at
  three the crossing is refused for `MESH_AVOID_S` 120 s like a ladder that never let him through -
  `_mesh_refuse`, `route(avoid=)`, stats `mesh_crossings_refused`, `mesh_refused_last` - and another way is planned.
- `_mesh_waypoint` confirms a link's landing (his height nearer the landing's floor than the foot's, or his arrival
  on a same-height landing): the `Traversal` is passed, stats `mesh_links_taken`.
- No way out: when the plan fails and the same plan WITHOUT the refusals succeeds, `nav_status` says
  `no usable exit from this floor region toward X,Z: N crossing(s) refused` (stats `mesh_no_exit`) and the operator's
  mark closes `unavailable` with that reason (`_goal_no_exit`, stats `map_goals_no_exit`, a line in the goal log)
  instead of the line-into-the-wall loop; his own play resumes (and never stands).
- `_approach`: near the goal but with no open floor on the line to it (`nav_near_walled`), the mesh's route stays in
  charge.
- `WALL_GOV_GOAL` True: the governor applies to the mark again - it is what detects a door the game does not open.

## 4. Measured on the fixture (ticks at 30 Hz, from the mark at (989,50,-441))

| start (facing) | main as deployed | main as at 21:30 (governor on) | with the fix |
|---|---|---|---|
| the middle (300,50,-170), 120 deg | never (1,800 ticks, 12 stand_breaks) | 264 ticks, standing stretches >= 1.5 s | **34 ticks** (1.1 s) |
| the east end (503,50,-282), 110 deg | never | - | **34** |
| against the back wall (620,50,-260), 60 deg | never | - | **31** |
| the east part facing west (471,50,-273) | 54 | - | 49 |
| the west end (68,50,-88), 120 deg | 34 | - | 57 |
| the west end facing its wall (0,50,20) | 105 | - | 88 |

(From the west end main's funnel path hugs the north wall into the door; the east part is the trap.) With the fix:
no `stand_breaks`, no preempts, the stick never off for more than 0.4 s, no B without the stick forward, no quick turns.

Doors that are action links (the synthetic bus, `bus_with_links`: a 250 x 800 cm floor at y 50 with a steep-face drop
of 150 cm at each short end, the ground joined round the south side):
- both usable: out and at the mark in 49 ticks, `mesh_links_tried` 1, `mesh_links_taken` 1, `level_changes` 1;
- the near door the Majini's only (no prompt ever): tried `MESH_LINK_TRY_S`, refused, the far door taken, the mark
  completed in 467 ticks (15.6 s), no preempts, never standing;
- both the Majini's only: both refused in 387 ticks (12.9 s), `nav_status` "no usable exit ...", the mark
  `unavailable`, `mesh_no_exit` 1.

Tests: `test_re5_switch_bus_nav.py` (16: the geometry, the funnel clearance, main's two failure modes, the fix from
six starts, the near-but-walled line, the route-yielding governor, the three link cases, the refusal's expiry);
`test_re5_switch_combo_clock.py::test_at_a_links_foot...` updated for the no-exit status. The rest of the RE5 Switch
suite: the 11 known-red tests of main only.

## 5. What is inferred, not run

- The World's player model is the bot's own model of the pad (strafe-like left-stick directions, a 160 deg/s turn);
  RE5's collision at the real door frame and whether the 43 cm step needs a prompt were not observed. If the game
  needs a prompt there, the prompt rule presses it when it shows (the push at the portal faces it); if the frame is
  narrower than the mesh edge, the clearance aims at the middle and three stalls refuse the crossing (then the mark
  closes "no usable exit" - that would be the finding to read live).
- The live 21:30 cycle (full-length runs at 4 m/s, `lup,b` westward) is not reproduced exactly: the 1 Hz goal log
  cannot resolve which of the trail recovery, the stand step and the guard's stick-while-turning made each run. The
  fixture reproduces the mechanism (the corner through the wall, the reversal, the standing turn), not the trace.

## 6. How to verify live

Stats of the RE5 bot (`GET /api/autoplay/telemetry/{sid}`, `stats`), a Public Assembly round, the bot inside the bus
(the tactical map, or `player` in the goal log between x -90..705, z -420..170 at y 50):
- `nav_status` "route" while he walks; `mesh_lookahead_holds` growing as he nears the door (the corner held);
- `wall_hits` with `wall_route_yields` equal to them and `wall_preempts` NOT growing; `wall_recoveries` small; the
  log's `hold` never `rleft`/`rright` alone for consecutive seconds;
- `stand_breaks` not growing while he is in the bus;
- out of the bus: his `player` y falls from 50 to 7-10 at x 520-560, z -60..-80 (the ramp) - the log line a second
  later has him outside;
- if the door is a prompt in the game: `prompts_seen_traverse` +1 and `level_changes` +1 at that spot;
- if the door refuses him: `mesh_crossing_pushes` to 3, `mesh_crossings_refused` +1, `mesh_refused_last` naming
  502,49,-114, then either another route or `nav_status` "no usable exit ..." and the mark's state `unavailable` in
  `gbox-data/mercs/map-goals.log` (event `state`, reason the same text) - report that to the operator rather than a
  loop;
- for ladders and drops anywhere: `mesh_links_tried`, `mesh_links_taken`, `mesh_links_refused`.

Deploy: the four modules are tracked by the hot reload (loaded at worker start); the new bot attributes are read with
`setdefault`/`getattr` defaults and `re5_nav.route(clearance=)` has a `TypeError` fallback for a half-reloaded worker.
Re-enable MercMode before stopping any test session (docs: RE4 Switch state 2026-11-06).
