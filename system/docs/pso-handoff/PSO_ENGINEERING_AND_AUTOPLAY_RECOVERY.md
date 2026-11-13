# PSO Episode I & II — Engineering mandate for DeepSeek / gBox

**Objective:** Build a memory-first, non-visual, deterministic PSO autoplayer that traverses the actual game with controller inputs, activates required switches, defeats enemies with correctly timed combos, clears rooms, and reaches the next floor. Reverse engineering is the means; verified floor completion is the deliverable.

## 1. Critical diagnosis from `WHY-IT-STANDS-STILL.md`

The worker reports: 25,980 Ghidra functions in `pso_v3.elf`; Forest 1 and Forest 2 collision grids with 90,986 and 98,671 safe cells; A* routes; successful controller walking (60.8→9.5 units); PMT weapon reach 13–30 units and half-angle 26–45 degrees; successful approach to a `TLazerFenceSw` (214→12 units) followed by an A press. **None of these proves the switch changed a flag, opened the linked door, or advanced the floor.** The worker also reports a three-minute repeated interaction with no movement, a stuck branch bypassing the unstick logic, 79 containers outranking progression objects, and operator demonstrations not recorded. These are direct failures of execution architecture, state validation, and learning infrastructure.

**Stop reporting “game understood” or “switch solved” from object naming or input issuance.** Report observed pre-state → controller input → post-state, with persistent evidence. A read-back of a manually written stage flag is not evidence that a controller interaction works.

## 2. Non-negotiable separation of concerns

- **Offline reverse-engineering/compiler:** parse owned disc files and placements; decompile relevant game logic; generate room graph, switch/door dependencies, collision, triggers, spawn waves, action tables and provenance. It may inspect memory and debug in controlled test sessions.
- **Runtime sensor:** read the 2D map data, player world coordinates/heading/animation, live enemy instances and HP, active objects, room ID, event flags, door state, action palette, controller state, and area transition. No vision model is used for decision-making.
- **World-state reconciler:** combine static placements with live instantiated objects; attach object IDs, transforms, room membership, state, and confidence. Distinguish *known*, *observed*, and *hypothesized* dependencies.
- **Planner:** produce explicit objective chains (e.g. defeat spawn wave → unlock door; press switch → unlock door; activate monument → later Ruins access; walk to warp → next area). Containers are optional and must not starve progression.
- **Executor:** own one controller and issue small bounded actions; validate motion and interaction results; yield after every action; accept immediate operator takeover.
- **Recorder/test harness:** store frame/time-stamped inputs, before/after RAM snapshots, route decisions, enemy HP deltas, flag deltas, room transitions, success/failure labels, and savestate/test-fixture references. Promote verified sequences into reusable skills.

## 3. Exact map variation count — do not guess

PSO uses a combination of **shared geometric room/area assets**, **placement sets**, **randomized route/room configurations**, **enemy and object placement variations**, and **quest-specific overrides**. A fixed statement such as “exactly three maps” is not a defensible count for *all* GameCube Episode I & II areas and quests. The answer must be derived for the exact executable/disc build and game mode. The number of placement variants is not necessarily the number of distinct geometry assets, room graph topologies, or runtime permutations.

**Required census:** For each Episode I and II area and quest mode, enumerate all referenced `gsl_set_*`/placement records and selection indices, room/door links, enemy and switch placement sets, and quest overrides. Hash normalized collision and room graphs separately from placement layouts. Identify the runtime selection function in Ghidra, its inputs (difficulty, mode, quest, seed/section ID if proven), and the selected set from RAM. Produce a table with `area`, `mode`, `geometry variants`, `placement variants`, `unique room graphs`, `selector function`, `runtime index`, `proof`. Where selection is not established, report **unknown** rather than invent a number. Confirm by repeated starts and by forced *test-only* variant selection, never by visually guessing the map.

## 4. 2D map and progression graph

Reverse-engineer the *actual automap* and its backing game state. The HUD/2D map is a presentation of a deeper world representation; read that representation directly rather than using pixels. Establish coordinate transform between world, collision mesh, map-space, room IDs, and entities by comparing three or more known landmarks and moving the player in controlled tests.

Represent each room as a graph node and each door/warp as a conditional edge. Edges carry predicates such as `enemy_wave_cleared`, `switch_42_active`, `laser_barrier_off`, `required_monument_active`, or `unconditional`. Represent triggers and switches as actionable objects with stable identity, location, activation radius, interaction type (press, stand-on, attack, scripted), linked flag(s), and downstream doors. **Not every apparent switch uses the same interaction**, and not every door is unlocked by a switch. Investigate enemy-gated red doors, multi-switch gates, laser barriers, pressure pads, and event-scripted transitions separately.

On every new room: (1) scan all live entities and objective flags, (2) determine the shortest *valid* route toward the next floor, (3) expand the first unsatisfied prerequisite, (4) select the nearest reachable required object or enemy, (5) act and verify. Do not choose a target because it is close if it is not on the dependency chain. Track explored rooms, visited edges, blocked edges, switch outcomes, and newly spawned waves.

## 5. Reverse-engineer event causality, not just class names

Use Ghidra cross-references and controlled memory breakpoints to trace: switch A interaction → handler → flag write → door state update → collision/portal enabling; enemy death → wave counter → next spawn/door unlock; warp activation → destination room/area change. For each chain, record relevant executable function address/name, object structure offsets, flag bits, scene/placement IDs, preconditions and observed deltas. Class names `TObjDoorKey`, `TLazerFenceSw`, `TObjDoor`, `Warp*` are *candidate semantics*, not proof of what each instance does.

Keep two explicitly separate modes:
- **Normal-play validation:** only controller inputs may cause traversal, combat, or switch activation. No teleport, no global gate-flag writing, no auto-kill, no stage warp.
- **Assisted/operator mode:** the user's requested auto-unlock can remain an independent configurable feature, including when the operator plays. Never use its success as proof that the normal autoplayer learned a door dependency.

## 6. Motion controller: eliminate the three-minute trap

The present `walk_to` and `route_walk` functions are not permitted to monopolize the loop. Use a single tick-based scheduler, with one bounded steering/movement action per tick, a wall-clock deadline, and a cancellation token. Check operator takeover before and after every input. A global watchdog must run independently of every branch, including interaction, combat, menus, and loading.

Each motion tick records `position_before`, `heading_before`, `input`, `duration`, `position_after`, `heading_after`, `distance_to_waypoint`, `collision`, and `objective_progress`. On no motion, immediately release inputs and diagnose: wrong heading, action lock, obstruction, controller not accepted, menu focus, collision, or stale player pointer. Replan from current position using the collision/navmesh, not a blind four-direction wander. Recover with a measured short reverse/lateral maneuver and alternate valid waypoint. After bounded retries, stop and report a reproducible failing case rather than silently looping or teleporting. A movement watchdog is necessary but **objective/room-state progress** is the acceptance criterion.

## 7. Combat: PSO's action palette and three-hit combo

The GameCube game has **customizable action slots**, not one universal attack key. Normal, Heavy, and Extra attacks can be bound to A/B/X and alternate slots with R. The same A button can be context-sensitive for switches, talk, pickup, and teleport. **Read the active action palette and context before sending inputs**. Never assume `A` is always an attack or always an interaction.

A normal PSO combo contains up to **three timed attack actions**. The second/third presses must occur in the valid animation/cancel window; blindly pressing or holding a button does not reliably chain. Reverse-engineer the player's attack animation state, combo stage, timing window, weapon class and recovery; build per-weapon-family calibrated timings from controller-input traces and memory observations. Start with `Normal → Normal → Normal` and `Normal → Heavy → Heavy` tests. Verify each swing was accepted by animation-stage progression and that an enemy HP delta or other hit event occurred. Track whiffs, interruptions, knockback, range/arc, airborne targets, and target acquisition.

**Default policy:** attempt a complete three-hit combo on a reachable, safely engaged enemy whenever feasible, because it is core gameplay. **Safety exception:** if the third swing would be interrupted or cause avoidable damage, use a two-hit disengage and retry; this is established PSO combat practice, not a failure to understand combos. Ranged weapons/techniques and flying or temporarily invulnerable targets require appropriate actions. Do not attack indefinitely when no damage is registered; change weapon, range, heading, or target after a bounded failed trial. Confirm target death and wave-clear flag, then return to the door objective.

## 8. Operator demonstrations must become machine-readable learning data

The worker admits it did not capture the operator's Dragon victory or level clear. That must not happen again. Implement continuous capture for operator and agent-controlled sessions (with explicit ownership), including input edges, action palette, animation/combo state, player pose, enemy pose/HP, room/map IDs, switches, doors, flags, and area transitions. Timestamp each sample and correlate to game frames. Export compact event traces, not just video or prose summaries.

Segment successful traces into reusable skills: `approach_switch`, `activate_switch`, `clear_wave`, `three_hit_combo`, `kite_enemy`, `use_warp`, `fight_dragon_phase`, `exit_floor`. For each skill store preconditions, controller sequence/timing, expected state transitions, termination condition, and failure recovery. Replay from matching savestates or controlled starting conditions; score against operator demonstrations. A saved note or an LLM assertion that it “learned” is not learning until a new run reproduces the behavior.

## 9. Runtime decision policy (reference pseudocode)

```python
while session_is_owned_and_active():
    s = read_and_validate_game_state()  # RAM / native map, not pixels
    watchdog.tick(s)                     # independent of task branch
    if operator_took_control():
        release_all_inputs(); yield_control(); continue
    if s.is_loading_or_menu:
        handle_verified_transition(s); continue
    if not s.player_alive:
        recover_using_game_rules(s); continue

    objective = planner.next_unsatisfied_goal(s.world_graph, s.flags)
    if objective is None:
        record_success_or_unknown(s); continue

    if objective.type == 'clear_enemy_wave':
        target = combat.select_reachable_live_enemy(s)
        action = combat.next_bounded_action(target, s)  # timed 3-hit skill
    elif objective.type == 'activate_switch':
        action = interact.next_bounded_action(objective, s)
    elif objective.type in ('traverse_door', 'use_warp'):
        action = navigation.next_bounded_action(objective, s)
    else:
        action = investigation.one_bounded_probe(objective, s)

    before = capture_semantic_snapshot(s)
    execute_controller_action(action, max_duration_s=0.5)
    after = read_and_validate_game_state()
    evidence.record(before, action, after)
    planner.reconcile(before, action, after)
    if not planner.measurable_progress() and planner.retry_budget_exceeded():
        save_failure_fixture_and_escalate()  # never loop silently
```

The 0.5-second bound is an initial engineering target, not a measured universal input cadence. Calibrate from the actual frame rate and gBox input latency.

## 10. Mandatory acceptance ladder

1. **G0 — Control ownership:** one bot, one controller relay, no duplicate loops, operator takeover immediately releases keys.
2. **G1 — Correct map variant:** current placement index, room graph, player and enemy positions, doors, switches and warps identified from memory; no vision dependency.
3. **G2 — Navigation:** 20 varied point-to-point routes across multiple rooms using controller only; no teleport or position writes; no unbounded stalls.
4. **G3 — Switch causality:** one switch approached and activated; specific flag changes; linked door state changes; player physically traverses it. Repeat from reset.
5. **G4 — Enemy-gated door:** detect wave, perform real attacks, confirm HP/deaths, detect door unlock, walk through.
6. **G5 — Three-hit combo:** 10 consecutive attempted combos with three verified action-stage transitions, measured hits/HP deltas, and a documented exception/recovery path for interruption.
7. **G6 — Floor clear:** unattended Forest 1 → Forest 2, including required switches and waves, with no debug bypass. Repeat across every enumerated relevant variant.
8. **G7 — Demonstration learning:** capture one operator room-clear and replay equivalent behavior from a matching state; show a before/after failure-rate comparison.
9. **G8 — Campaign:** Forest, Caves, Mines, Ruins, bosses, required monuments and later areas as appropriate to mode, using the same framework.

Do not substitute “changed area once every five minutes” for G6: that metric can be gamed by a warp/teleport and is not a proof of room completion. Report wall-clock elapsed, stuck events, door interactions, combos attempted/completed, enemies killed, flags changed, room transitions, and any interventions.

## 11. First engineering sprint — required deliverables before more free-running

**Day 1:** Remove blocking nested walk loops; add global objective watchdog and per-action cancellation; disable container-priority starvation. Build a deterministic live snapshot JSON with player, room, 2D map coordinate, enemies, doors, switches, flags, action palette and objective. Implement a per-tick event ledger.

**Day 2:** Trace one exact switch→flag→door chain and one enemy-wave→door chain. Prove each with a saved before/after memory diff and controller trace. No global flag hacks in the acceptance session.

**Day 3:** Calibrate 3-hit combo input timing from animation state and enemy HP. Record and replay one operator demonstration. Run the first unattended Forest 1→Forest 2 test and publish the full trace, including any failure fixture.

These are **priorities**, not promises that reverse engineering will necessarily finish within 72 hours. The worker must report blockers with a minimal reproducible test, not continue a wandering session for days.

## 12. Direct instruction to DeepSeek

> Stop the existing open-ended autoplay experiment. The immediate failure is not lack of a vision model or lack of geometry; it is lack of an integrated, cancellable, state-verified controller. Read the operator's uploaded diagnosis and this mandate. First prove that the active action palette, room/door graph, switch flags, live enemies, and combo animation states can be read from RAM. Then implement bounded controller actions and global objective-progress monitoring. Trace one switch-to-door causal chain and one wave-to-door causal chain, with verified controller-only results. Capture operator demonstrations and turn them into executable, replayable skills. Do not call a switch successful merely because A was pressed, or call a floor complete because a stage flag was manually written. Do not claim an exact number of map variants until you have enumerated the exact build's placement tables and selector logic. Report a compact evidence ledger after each reproducible test: pre-state, action, post-state, expected/observed delta, failure cause, code commit, next test. Your next milestone is a repeated unattended Forest 1→Forest 2 traversal, not more time spent meandering in the first room.

## 13. External game references and confidence

- Official GameCube instruction manual: https://www.gamesdatabase.org/Media/SYSTEM/Nintendo_GameCube/Manual/formated/Phantasy_Star_Online_Episode_I_-_II_Plus_-_2004_-_Sega.pdf — customizable action palette, context-sensitive A, three attacks and timing.
- GameFAQs PSO Episode I & II walkthrough: https://gamefaqs.gamespot.com/gamecube/516243-phantasy-star-online-episode-i-and-ii/faqs/30988 — enemy-gated doors, switch types, laser barriers, multi-switch doors and monuments.
- GameFAQs Forces FAQ: https://gamefaqs.gamespot.com/gamecube/516243-phantasy-star-online-episode-i-and-ii/faqs/23933 — combo tactics and the two-hit safety exception.
- GameFAQs Ranger guide: https://gamefaqs.gamespot.com/gamecube/516243-phantasy-star-online-episode-i-and-ii/faqs/25578 — attack palette and normal/heavy/extra combos.

**Evidence limits:** These public references describe game mechanics, not the specific executable's memory offsets or a complete enumerated count of layout variants. The worker's `WHY-IT-STANDS-STILL.md` is a self-report of implementation/tests; its claims must be independently reproduced against the current code and active game build.
