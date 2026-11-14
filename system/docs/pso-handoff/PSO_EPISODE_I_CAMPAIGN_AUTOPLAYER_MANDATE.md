# DeepSeek engineering mandate: complete and repeat PSO Episode I

## Mission and acceptance
Build a deterministic, RAM-observed, ROM-derived, controller-operated Phantasy Star Online Episode I campaign runner. It must start in Pioneer 2, activate the *correct* teleporter, clear Forest 1–2 and Dragon, Caves 1–3 and De Rol Le, Mines 1–2 and Vol Opt, Ruins 1–3 and Dark Falz, return to town and repeat a new full run. Verify unlock conditions and story/quest mode assumptions for this particular build; do not claim every area is immediately available. Do not merely visit floors or change area IDs: complete required combat and progression events. A 'cycle' is successful only when the game confirms the final boss defeat and the next cycle starts correctly. Do not erase the save or character to restart unless expressly required; prefer new expedition/session cycle. Respect legitimate menu and progression mechanics.

## Evidence from uploaded 2026-11-13 session (not a claim of working autonomy)
- Round 89: repeated attempts at the `TObject` at (360,26) failed. A at 1.6 and 2.6 units and walking through it produced no verified warp; agent admitted target identity was assumed. Other generic TObjects at (308,211), (0,-60), (0,-1730) were hypotheses, not verified portals.
- Round 84: 154 controller actions accumulated ~600 units movement with poor net progress because the probe oscillated.
- Round 91: 237 actions yielded only ~27 units in a spawn-pocket collision cluster. A wedge guard recorded blocked points but did not solve navigation.
- Round 92: a detour reached the first four waypoints, but later waypoints failed and the alternate TObject remained untested.
- Previous worker diagnosis: A* grids and switch RAM entities exist, but interaction loops can block for minutes; operator's demonstrated boss and level-clear traces were never recorded.
These are observations from agent logs, not independent verification of its code or reverse-engineering claims.

## Nonnegotiable architecture
1. **ROM data extraction:** Inventory disc FST and container chain (GSL/AFS/BML/PRS), area set files, object/enemy placement, collision, triggers, warp definitions, map variant selection, door and wave tables. Produce per-area machine-readable manifests, versioned with ROM hash. Do not guess number of variants; enumerate all distinct placement combinations and runtime selectors.
2. **Executable semantics:** Use Ghidra to locate area selection, teleporter activation, object classes, input dispatcher, collision, animation/attack state, enemy HP and spawn/despawn, stage progression, boss clear, save/quest flags. Trace actual reads/writes and callsites; attach address, offset, confidence, and test evidence. Decompilation function count is not semantic understanding.
3. **RAM observer:** Stable snapshots of player world pose/heading/room/area, loaded map variant, nearby object instances and activation states, enemies/HP/animation, barriers, switch flags, quest progression, warp/menu state. Distinguish raw memory, inferred fields and verified meanings. Reconcile placement coordinates to live world coordinates and 2D automap; record transforms and room IDs.
4. **Hierarchical planner:** Campaign FSM (town→biome→floor→boss→next biome→final clear→repeat); floor room/door graph; dependency graph (enemy wave→gate, switch→gate, warp→next room); geometric path planner over verified walkable space. Pick objectives from unmet progression dependencies, not nearest objects or 79 containers. Optional loot only if it serves survivability or explicit policy.
5. **Controller executor:** Single owner of controller; short nonblocking inputs with measured direction and speed, heading feedback, local obstacle avoidance, animation-aware A/menu interaction, postcondition verification. No RAM position writes, forced warps, gate-flag writes, or progression bypass in acceptance tests. Debugging may use save states and memory instrumentation, separately labeled.
6. **Combat controller:** Read action-palette binding; normal/heavy timing and attack animation state; timed three-hit combos when safe and reachable; confirm enemy HP decrease. Dodge/reposition, ranged attacks for unreachable/flying enemies, healing, boss-specific phases. Three-hit chain is a default goal, not an unconditional action during invulnerability, danger or no target.
7. **Learning from demonstrations:** Capture operator controller frames + RAM snapshots + game events with timestamps. Segment into skills (leave town, warp, clear wave, activate switch, boss phase), extract state predicates and postconditions, replay and generalize to variant placements. An operator video alone is not a reusable controller trace; start recording immediately.
8. **Progress monitor:** Every action has target, expected state change, time budget, success predicate and diagnostic error. Track distance-to-goal, graph node, objective state, enemy HP, floor transitions. Detect oscillation and repeated failure; suspend same plan, identify missing geometry or mistaken entity identity, and run targeted experiment. 'Moving' is not a success condition. Never spend another round blindly trying a speculative TObject.

## Immediate town-portal experiment (before any more long campaign runs)
A. Freeze and back up working state; single controller owner. Record current ROM hash, game mode, difficulty, quest/story flags, area unlocks, and whether Pioneer 2 is in a menu/transition state.
B. Extract Pioneer 2's *actual* teleporter/warp objects and menu handlers from disc and executable. Find runtime object pointers/vtables or interaction event hooks; correlate with automap and coordinates. `TObject` is not enough to identify a warp.
C. Have operator activate Forest teleporter once while recording controller input, object/warp state, UI/menu selections, player position and area ID before/after. If operator demonstration cannot be recorded, instrument the interaction handler and test hypotheses one at a time.
D. Reproduce with normal controller from two distinct spawn positions, five consecutive trials each; verify menu selection, load transition, Forest 1 identity, and first actionable objective. Failure produces a precise counterexample and a fix, not another free-wandering run.
E. Add town route to graph with verified obstacles and clearance, not a list of points that cross wedge clusters. Avoid treating all generic TObjects as portals.

## Floor-clear behavior
At floor entry, identify selected placement variant and room. Build accessible graph and all mandatory progression dependencies. For each room, route to each required enemy wave/switch/trigger, execute combat/interactions, verify door unlocked, traverse to next room, verify room transition. Do not assume all rooms are traversable or required; define 'each and every room' as all reachable rooms in the generated floor, and separately report optional and inaccessible rooms. Before leaving floor, ensure required rooms and events are complete. Confirm boss and area transition by authoritative state, not a changed coordinate or flag alone.

## Required tests, in order
T0: town portal 10/10 from two starts, no memory warp.
T1: Forest 1 first room objectives and door, 5/5.
T2: Forest 1→Forest 2 unattended, 3/3.
T3: Forest 1→Dragon→Caves entry, 3/3 (respect unlock rules).
T4: all Caves floors and De Rol Le; all Mines floors and Vol Opt; all Ruins floors and Dark Falz; separate reproducible logs for each.
T5: one entire campaign cycle unattended, including appropriate return to town.
T6: three complete consecutive cycles, using distinct available map variants; persist and reuse learned map/object semantics, no human assistance.
At every milestone publish a compact evidence table: build/ROM hash, area and variant, start/end state, controller input trace, objective events, blockers, tests passed/attempted. No success claim without actual recorded completion.

## Operational limits
Do not conflate area unlock cheats with gameplay completion. Do not change global game flags to simulate beating rooms. Do not restart/reboot endlessly; keep reproducible checkpoints. Stop runaway jobs after a bounded failure, produce a diagnosis and fix. Maintain tests for UI/gBox stability and one controller lease. Existing code should be reused only when measured correct; no speculative coordinate hardcoding.

## Next worker response required
1. Identify the exact ROM build and game mode.
2. Produce a **verified Pioneer 2 portal object identity and activation sequence** with evidence from ROM/Ghidra/RAM and an operator trace.
3. Demonstrate town→Forest 1, ten times, controller-only.
4. Only then continue the full campaign FSM, reporting milestone completions rather than motion statistics.
