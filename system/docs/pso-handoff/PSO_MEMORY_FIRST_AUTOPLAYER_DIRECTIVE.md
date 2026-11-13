# PSO Episode I & II — Memory-First Autoplayer Correction Directive

## Mission
Stop aimless roaming. Build a deterministic, memory-driven game-state controller for PSO Episode I & II (GameCube/Dolphin). **Do not use a vision model for navigation, switch recognition, door recognition, or combat.** Rendering is only for optional operator inspection. Read game data and emulated RAM, and issue normal virtual GameCube controller inputs for walking, attacks, and interactions. Do not teleport the player or blindly write progression flags in the gameplay acceptance test.

## Existing work to reuse, not rewrite
The previous handoff reports Ghidra analysis of `pso_v3.elf`, collision geometry and A* grids, RAM entity classes (`TObjDoorKey`, `TLazerFenceSw`, `Warp*`), door-stage flags, weapon parameters from `ItemPMT.prs`, and verified controller-based walking. The newer session log's Git history reports that `gsl_set_*` placement archives have been decoded and a rebuilt PSO disc booted. Verify the current branch and actual code paths before claiming these are integrated. The session log primarily covers another gBox task and is **not** direct evidence that the current PSO autoplay loop works.

## Architecture — strict separation
1. **Static asset importer:** Extract stage/room identifiers, placements, object IDs/types, transforms, and collision/navmesh from the existing disc decoder. Produce versioned JSON/SQLite keyed by disc hash, area, floor, and actual map variant. Do not assume exactly three variants until verified.
2. **Live RAM observer:** Read player position/heading/room, entities and their class/position/health, switch states, door states, enemy-wave states, and warp transitions. Identify build and pointer generation; reject stale pointers. Every field must have a documented source and confidence.
3. **Semantic graph:** Represent rooms as nodes and doors as edges with predicates. Example: `door_12.open_when = switch_7.active AND wave_3.cleared`. Maintain evidence for every dependency; mark unknown relationships as unknown rather than guessing. Reconcile static placements with dynamically spawned entities.
4. **Goal planner:** Determine the next required condition for reaching the floor exit. Recursively resolve blocked doors into actionable goals: clear wave, reach/activate switch, traverse door, enter warp. Use A* only for geometric movement to a chosen goal; A* is not a progression planner.
5. **Input executor:** Single owner of the virtual pad. Move via short closed-loop controller pulses; align to the target; issue the mapped action/attack button; release; reread RAM. Do not equate proximity with activation. Verify target state changed. Physical operator control immediately preempts the bot.
6. **Persistent knowledge and tests:** Save decoded graph, discovered object semantics, successful interactions, input calibration, and failed attempts as fixtures. Reload this database on restart. A language model may plan engineering work, but the runtime action loop must be deterministic and independently testable.

## Mandatory switch/door discovery experiment
On a reproducible Forest floor:
- Enumerate every loaded entity with class, stable identifier (where available), room, position, and raw state fields. Join each to the decoded placement records, including dormant or not-yet-spawned placements.
- Identify a visible-in-game switch **without relying on screenshots for the bot**: find candidate switch objects from class/vtable and placement tables. Compare memory before and after a manual activation once, using a controlled savestate/test fixture where available.
- Trace the switch activation handler and associated door state or event flag in Ghidra. Record which door(s) it affects and whether activation requires a controller press, a proximity trigger, a floor pad, an enemy wave, or a scripted event.
- Repeat for one enemy-clear door and one floor warp. Capture pre/post RAM evidence. Do not generalize all door types from a single sample.
- Emit a machine-readable `objects.json`, `door_dependencies.json`, and a short evidence report with addresses/offsets specific to the verified executable revision.

## Runtime decision loop (pseudocode)
```
while session_active:
    state = read_validated_ram_snapshot()
    if operator_has_control(): release_all_inputs(); continue
    graph = reconcile_static_placements_and_live_state(state)
    objective = planner.next_unsatisfied_dependency(graph, floor_exit)
    if objective is None: report_unknown_dependency_and_probe(); continue
    if objective.kind == 'enemy': navigate_to_attack_position(); perform_calibrated_attack(); verify_hp_delta_or_death()
    elif objective.kind == 'switch': navigate_to_interaction_position(); face_target(); press_mapped_action_once(); verify_switch_state()
    elif objective.kind == 'door': navigate_to_portal(); verify_room_transition()
    elif objective.kind == 'warp': navigate_to_warp(); perform_required_interaction_if_any(); verify_floor_transition()
    else: investigate_specific_unknown_with_bounded_probe()
    log_action_and_state_delta()
```

## Combat requirements
- Treat attack and interact as context-sensitive actions whose actual mapped buttons and game states must be measured; do not assume every switch and attack uses identical inputs.
- Derive reach/angle from verified weapon data; check current weapon, target class, distance, facing, obstruction, animation state, and cooldown before attacking.
- Measure combo timing in game frames from player animation/action state and enemy HP changes. Do not spam 132 swings to obtain 10 hits and call it mastery.
- For fliers, verify whether a ranged weapon is required for the current class and loadout. The handoff's observed melee failures do not prove every flying enemy is universally melee-immune.
- On an unsuccessful attack, change one controlled variable (range, angle, weapon, or timing), not the entire strategy.

## Anti-stall contract
- Every tick must have an explicit goal, target ID, expected state transition, and deadline. Waiting is valid only for a named animation, spawn, or transition and a bounded duration.
- If displacement stays below tolerance after two movement pulses: stop, release input, diagnose collision/heading, replan once. Do not oscillate indefinitely.
- If the same room/objective recurs three times without a new flag, kill, switch activation, or room transition: mark `STALLED`, dump a structured state/graph/last-actions report, and switch to targeted reverse engineering. Never continue wandering.
- If a switch candidate is within reach but not activated, test the correct interaction button and action readiness, then inspect its activation handler. Do not simply walk past it.
- If no candidate objective is known, enumerate static placements and active/dormant entities and identify the missing semantic relation. Do not substitute random roaming.

## Acceptance gates
1. **Object census:** On one known Forest variant, produce a complete, reproducible list of switches, doors, warps, and enemy triggers, including confidence and unknowns. Compare static placements with live RAM.
2. **Single switch:** From a fixed start, approach one switch using pad input, activate it, and confirm the switch and affected door state changed. Pass 5/5 resets.
3. **Single enemy gate:** Clear a known enemy wave with verified HP/destroyed counts and confirm the door unlock. Pass 5/5 resets.
4. **Room transition:** Reach the newly unlocked doorway and confirm room ID changes. Pass 5/5 resets.
5. **Floor:** Complete Forest 1 to Forest 2 unattended, no position writes, no vision, no manual intervention, and no unexplained idle loop. Pass 3/3 runs across distinct starts.
6. **Generalization:** Repeat on other verified map variants, then Forest 2/Dragon, Caves, Mines, Ruins. Only after this should Ultimate balancing and level-editor features be expanded.

## Engineering process
- Freeze and tag the current working implementation. Use a separate branch/worktree, and avoid multiple bots or controller relays controlling one Dolphin session.
- Audit existing `pso_*` modules and the `gsl_set_*` decoder before creating replacements. Produce an integration matrix: implemented, live-verified, missing, and unreliable.
- Make one change per experiment; add a synthetic unit test plus a live evidence receipt. Track actual elapsed time, transitions/minute, switches activated, doors opened, enemies killed, stall count, and failed input count.
- No unsupported `DONE` claims. `A* exists`, `entity recognized`, `button pressed`, `flag changed`, and `door traversed` are separate acceptance criteria.
- First deliverable: a concise report showing one identified switch, its controlling door, exact activation mechanism, and one fully verified pad-driven switch-to-door transition. Do not spend more runtime on free exploration until this passes.
