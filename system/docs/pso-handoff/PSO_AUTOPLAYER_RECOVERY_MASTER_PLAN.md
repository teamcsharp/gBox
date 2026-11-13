# PSO Episode I & II (GameCube) — Autoplayer Recovery Master Plan

**Audience:** Local DeepSeek engineering agent, gBox operator, reverse-engineering workers  
**Status:** Corrective engineering directive, 2026-11-13  
**Primary target:** Offline Episode I, Dolphin; Forest 1 → Forest 2 → Dragon, then Caves → Mines → Ruins.  
**Non-negotiable:** Movement and attacks through emulated controller input. RAM reads for perception; RAM writes only in explicitly labeled research/debug experiments, not acceptance runs.

## 0. Executive directive

STOP unconstrained autonomous wandering, repeated steering rewrites, and claims of completion based on code existing. Preserve the working build and all evidence. Implement a deterministic world-state planner with a separately calibrated controller and combat executor. Run small reproducible tests with explicit success conditions. Never let the agent run for hours without producing a state transition, artifact, or falsifiable diagnosis.

**Definition of success for phase 1:** From a known fresh Forest 1 state, unattended bot navigates with controller inputs, defeats required enemies, activates required progression mechanisms, uses the correct exit, and reaches Forest 2. Repeat successfully across multiple starts/layouts with recorded traces. No teleport/position writes.

## 1. Baseline: what the provided handoff actually demonstrates

- Ghidra processed `pso_v3.elf` and reported 25,980 functions. **This does not mean the game is fully understood or decompiled into complete usable source.**
- Forest collision geometry was extracted (`map_forest01c.rel` etc.), and an A* safe-cell grid exists. Its successful 115→5.4-unit approach used **position writes**, not legitimate movement.
- Later handoff addendum verifies real walking: 60.8→9.5 units in ten steps, after changing to measured tap-by-tap steering and ~0.22-second movement pulses. This supersedes the older claim that walking is unsolved.
- A final test reported 10 hits, five enemy kills, 14 containers destroyed, but **132 swings for 10 hits is not combat mastery**.
- The real item parameter table was decoded (`ItemPMT.prs`, 63,680 bytes, pinned fingerprint); prior use of a 10–12-unit/8-degree fallback caused repeated missed attacks. Actual table values in handoff: 13–30 units reach, 26–45-degree half-angles. Confirm exact field semantics and weapon matching before use.
- Inventory discovery deadlock was fixed via a loose slot-based finder; verify after worker restart and across savestates.
- A reported airborne enemy survived 12 melee swings at 6.2 units. Treat **melee ineffective for that tested target/position** as verified; do not generalize all flying enemies as immune without further experiments. Test handgun/ranged solution.
- Keys, doors, warps and flags are recognized, but **a complete causal room-to-room progression chain has not been demonstrated**. RAM flag read-back alone is not proof that a door is physically traversable.
- The ledger's checkmarks sometimes mean “code implemented” or “partial test,” not robust completion. Resolve discrepancies with trace-based acceptance criteria.
- Historical technical interfaces (verify before use): app `127.0.0.1:18765`, worker `:8765`, state RPC; `endless.py`, `pso_pad.py`, `controller_relay.py`, `forest-maps.json`.

## 2. Actual game rules to encode

### 2.1 Episode I progression

Episode I sequence: **Forest → Caves → Mines → Ruins**, with bosses **Dragon → De Rol Le → Vol Opt → Dark Falz**. Access to Ruins also depends on activating the **three monuments/columns in Forest 2, Caves 2 and Mines 2**. Do not assume defeating a boss or opening a door alone is sufficient. Track both current-floor and persistent progression flags. Validate how offline solo vs multiplayer and game version change gating.

### 2.2 Doors are not one mechanism

Distinguish at least: (a) enemy-wave-clear door, (b) ordinary switch-controlled door, (c) floor-pad switch, (d) multi-switch door, (e) laser barrier with matching switch, (f) boss/area warp, (g) optional loot/shortcut door. Red/flashing doors may depend on enemy spawns or entering a trigger zone, not a nearby switch. Some switches are traps or optional. For each blocked edge, discover **which event actually changes traversability**.

### 2.3 Map variations

The map has reusable room geometry and finite route/placement variations, but **“exactly three variants of every map” is a hypothesis, not a universal fact**. Different floors, quests, modes, and placement tables may vary. Identify the exact active layout by loaded modules, object placement signatures, room adjacency and seed if recoverable. Never hardcode one route and assume universal applicability.

### 2.4 Combat

PSO uses facing, range, attack arcs, attack animations, recovery and timed combo inputs. Implement **Normal / Heavy / Special** attack selection as supported by the currently equipped weapon/action palette, and verify actual input mappings. Pressing the action button repeatedly without checking animation phase and HP delta is not a valid combo strategy. Targets can move, be obstructed, be airborne, or spawn in waves. Different weapon classes and enemy hitboxes require different attack policies.

### 2.5 Difficulty and modifications

Character level and offline difficulty access are separate from map navigation. The handoff reports level 5 and an Ultimate level-80 gate in the tested configuration. Verify exact gate per mode and game build. Build a **separate modded-Ultimate test profile** (adjust character survivability, weapon power, enemy parameters or access flags in a disposable offline save) rather than waiting for organic leveling to test navigation. Keep a vanilla-baseline profile and never conflate modified progression with unmodified behavior.

## 3. Architecture: no more monolithic `endless.py`

Implement six independently testable layers:

1. **Sensor / state decoder** — frame-consistent RAM snapshot: game mode, floor, room, player position/heading/velocity, weapon and action palette, entity list, enemy HP and animation, door status, switches, warp status, spawn-wave status, current flags. Include confidence and validity checks; distinguish entity disappearance from death.
2. **Static map compiler** — decode disc/REL assets into geometry, navigation polygons, rooms, portals, collision, spawn/placement tables and interactable object IDs. Version outputs by disc SHA-256 and map asset hash.
3. **Dynamic world model** — room/portal graph, objects, triggers, persistent flags, enemy waves, known and unknown dependencies. Use tri-state `unknown/false/true`, not speculative booleans.
4. **Goal planner** — hierarchical finite-state machine / behavior tree: select objective, compute prerequisites, route to interaction, verify transition, replan only on changed state. Prefer critical-path objectives over optional boxes.
5. **Motion + interaction executor** — controller-only steering, movement, reticle/action, attack timing, weapon selection, recovery. Closed-loop input at short intervals, with collision detection and operator priority.
6. **Evidence / learning system** — replayable traces, structured demonstrations, test fixtures, metrics, persistent discoveries and regression tests. DeepSeek proposes changes; automated tests decide whether they are accepted.

**Single-writer rule:** one process owns Dolphin input; one supervisor owns session lifecycle. Operator takeover preempts at the next input pulse and sends neutral input. Every relay refreshes the session ID on relaunch. Prevent duplicate bots and relays with process locks and ownership tokens.

## 4. Reverse-engineer the map and event system, not merely the mesh

### 4.1 Asset inventory

- Hash the exact disc and extract the filesystem. Enumerate all map-related `.rel` and packed resources; record size, offsets, magic, relocation information, and references.
- Locate **room templates, placements, doors, collision, trigger volumes, switches, spawn-wave tables, warps, and stage/event scripts**. These may be in separate assets or runtime data structures; do not assume a single “decrypted map” file.
- Compare three or more controlled starts of the same floor. Diff placement tables and RAM entities to identify invariant room geometry versus variant-specific object layout.
- Document coordinate frames and transforms: local room coordinates, global coordinates, X/Y/Z axes, heading conventions, scale, floor and room identifiers. Verify with three non-collinear landmarks.
- Export machine-readable `map_manifest.json`, `rooms.json`, `portals.json`, `objects.json`, `events.json`, `navmesh.json` with source offsets and confidence.

### 4.2 Dynamic breakpoint-driven investigation

Use Dolphin debugger / watchpoints and Ghidra cross-references:

1. Stand before a closed door; snapshot nearby entities and stage flags.
2. Kill one required enemy; log writes to room/enemy counters, spawn-wave state and door state.
3. Activate a switch; log which bits and objects change and the writer call stack/PC.
4. Walk into an untriggered room; observe new entity creation and event transitions.
5. Enter warp; record the source object, transition function, destination floor and new spawn position.
6. Repeat for each door class and for the Forest 2 monument.

Name functions by *observed behavior*, not guessed labels. Record `address → evidence → hypothesis → confidence → confirming test`. Distinguish runtime pointers from stable static addresses and ensure big-endian decoding.

### 4.3 Build a dependency graph

Represent each room and door as a directed graph with conditional edges. Example:

```yaml
edge_id: forest1_room_04_to_05
from: room_04
 to: room_05
condition:
  type: enemy_waves_cleared
  room: room_04
observed_state: unknown
proof:
  before_trace: null
  after_trace: null
```

For switches, model `switch_id → flag_id → door_id`; for waves, `trigger_volume → spawn wave → defeat required enemies → door opens`. Store optional branches separately. **Do not write stage flags to bypass doors in acceptance runs.** Debug writes can help infer causality, but must be independently confirmed by normal play.

### 4.4 Route planning

Two-tier planner: (1) **room/portal graph** for global goals and prerequisites; (2) **navmesh/A*** for local paths. A 90,000-cell safe grid alone is not enough: it lacks door semantics and obstacle/actor dynamics. Apply obstacle inflation for player radius, line-of-sight checks, reachable approach points for interactables, dynamic replanning when doors change, and off-mesh transitions for warps. Target a switch's valid activation location, not merely its center coordinate.

## 5. Rebuild controller motion from calibrated primitives

**Never batch blind turn taps.** The handoff observed ~8–11 degrees per tap, anomalous first-tap heading changes, and ~14 units travel per 0.22-second pulse in one test; these are starting measurements, not global constants.

- Calibrate turn-left, turn-right, forward, backward, diagonal movement, stopping latency and attack lockout in an obstacle-free room. Record game frames, not only wall-clock time, because Dolphin runs at >1× speed.
- At each control cycle: read position + heading, choose the next waypoint, issue one short input, read back actual displacement, and update an online local control model.
- Derive movement heading from **observed displacement** when the memory heading is suspect; estimate camera-relative vs character-relative controls. Avoid corrections while pinned against obstacles.
- Detect stuck conditions by low displacement over a bounded number of input pulses; stop, back away, rotate toward a verified free sector, then replan. Never spend minutes pushing against a wall.
- Require reproducible point-to-point motion on 10, 30, 60 and 100-unit routes, plus door-threshold crossings and tight corners. Track path efficiency = actual travel / shortest feasible route, collision count and arrival error.
- Keep position writes only in a separately labeled debugger/test fixture; acceptance tests must prove actual controller locomotion.

## 6. Combat controller: hit confirmation over swing count

### 6.1 Ground-truth combat table

Build an indexed weapon table from `ItemPMT.prs`, linking equipped item ID to reach, arc, weapon family, attack animations, timing and allowed target types. Validate against actual observed damage. A weapon's theoretical reach does not guarantee a hit if the enemy is off-axis, outside the active hitbox, or the animation is interrupted.

### 6.2 Attack policy

```text
if enemy not in same reachable engagement region: navigate to engagement point
if line of sight blocked: reposition
if target airborne or melee repeatedly yields zero damage: equip tested ranged weapon
if target outside verified effective range: approach
if target outside verified attack cone: rotate in measured increments
if currently in attack/recovery animation: wait for permitted combo window
else: issue one calibrated attack press
observe enemy HP delta, hit reaction, player state and attack animation
if hit: update weapon/enemy timing model; attempt next combo input at verified window
if miss: classify range / angle / occlusion / airborne / invulnerable / input failure
if repeated failure threshold reached: switch policy or mark blocker; never spam indefinitely
```

- First tests: **one stationary box**, **one Booma**, **one wolf**, **one flier with ranged weapon**, **one three-hit combo**. Use repeatable savestates and same equipment.
- Infer combo windows experimentally from frame-indexed action traces. Sweep input intervals in small controlled ranges and record successful second/third hits. Build timing tables per weapon family; don't assume a universal interval.
- Maintain a target lock on an entity ID and use HP changes as primary success evidence. For boxes, confirm destruction/loot spawn; for enemies, confirm death state and next-wave trigger.
- Select ranged vs melee by actual efficacy; use an optional 2–5 minute swap timer **only when it does not break the encounter**.
- For the low-level Ultimate goal, distinguish *survival tuning* from *combat logic correctness*: first prove a clean Normal combat baseline, then retest in the modded Ultimate profile.

## 7. Progression planner: explicit state machine

```text
BOOT → VALIDATE_SESSION → IDENTIFY_GAME_MODE → IDENTIFY_FLOOR_AND_VARIANT
→ BUILD_WORLD_SNAPSHOT → SELECT_CRITICAL_PATH_GOAL
→ PLAN_ROOM_ROUTE → PLAN_LOCAL_ROUTE → WALK_TO_TARGET
→ (CLEAR_REQUIRED_WAVES | ACTIVATE_SWITCH | ACTIVATE_MONUMENT | USE_WARP)
→ VERIFY_GAME_STATE_TRANSITION → UPDATE_KNOWLEDGE → REPLAN
→ FLOOR_COMPLETE → NEXT_FLOOR / BOSS / NEXT_AREA
```

Priority order: (1) recover session and player survival; (2) required wave/enemy to open critical door; (3) required switch/monument; (4) critical warp; (5) optional rare/box when safe and not blocking progression. If an apparently empty room has a closed red door, search for trigger volumes and unspawned waves before wandering to unrelated objects. Treat a room as complete only when the required condition is verified.

Each goal needs: preconditions, target ID, action, timeout in **emulated frames**, expected state transition, alternate hypothesis and fallback. Never retry the identical failed action more than a bounded number of times without changing diagnosis.

## 8. Make demonstrations become actual learning

The agent's prose acknowledgment of operator notes is **not** evidence that a skill was learned. Introduce:

- **Demonstration recorder:** timestamped controller inputs, frame count, player pose, room, target ID, target HP, action/animation state, door flags and result; capture video only as secondary evidence.
- **Segmenter:** label demonstrations as `approach_box`, `face_enemy`, `combo_3`, `activate_switch`, `cross_door`, `enter_warp`, etc.
- **Skill compiler:** transform examples into parameterized executable skills with preconditions and postconditions, not free-text memory.
- **Replay evaluator:** restore the same savestate and test the new skill without human input. A skill is learned only if it reproduces the transition repeatedly.
- **Persistent knowledge base:** versioned room graphs, variant signatures, successful routes, weapon timing tables, entity semantics, and failure diagnoses. DeepSeek must retrieve this state at the start of each session.
- **Human override:** when the operator demonstrates a maneuver, pause autonomous input, record the trace, extract the skill, and schedule a replay test. Never silently continue using an old behavior after a failed replay.

Avoid full reinforcement-learning training until deterministic sensors and action primitives work. The initial problem is instrumentation and control engineering, not lack of model intelligence.

## 9. Validation gates — no advancement without evidence

| Gate | Required test | Pass criterion |
|---|---|---|
| G0 | Clean launch and one input owner | One live bot, one relay, valid session ID, no orphan processes |
| G1 | Sensor correctness | Consistent entity IDs, coordinates, HP, room, door flags across controlled tests |
| G2 | Walking | 10 waypoint routes with no position writes; ≥90% arrival within chosen tolerance |
| G3 | Box | Destroy 10 test boxes with verified destruction; bounded attacks per box |
| G4 | Combat | Kill 10 consecutive ground enemies with HP-delta traces; no unbounded spam |
| G5 | Ranged | Kill 5 airborne targets with verified weapon and damage |
| G6 | Interaction | Activate 5 switches and traverse corresponding doors using normal input |
| G7 | Room chain | Traverse 3 consecutive rooms including enemy-wave and switch dependencies |
| G8 | Forest floor | Forest 1 → Forest 2 unattended, repeat across at least 3 starts/layouts |
| G9 | Forest area | Forest 1 → Forest 2 → Dragon → verified area completion |
| G10 | Episode I | Forest → Caves → Mines → Ruins → Dark Falz with monument prerequisites |
| G11 | Ultimate mod | Repeat validated route on separate modified Ultimate profile |

These thresholds are engineering acceptance targets, not claims about current performance. Record pass/fail and traces; do not report “done” merely because a code branch exists.

## 10. Failure triage and anti-stall controls

- **Wall stare:** no displacement → check collision/heading/waypoint reachability → backoff/replan. Never continue pressing forward blindly.
- **Enemy visible but no damage:** inspect target identity, weapon, range, angle, hitbox height, line of sight, animation phase and HP; change one variable per controlled test.
- **Door stays closed:** inspect required waves, trigger volumes, switch-to-door mapping and persistent flags. Never infer from door appearance alone.
- **Switch appears pressed but no progress:** compare flag readback **and physical door state**; identify wrong switch or missing prerequisite.
- **Repeated relaunch:** preserve savestate, last 2000 frames of trace, crash reason and session ID; do not erase evidence.
- **Two agents fighting input:** supervisor kills duplicate owners and neutralizes controller before restart.
- **Map mismatch:** re-identify variant and transforms; do not reuse coordinates from another placement signature.
- **No progress after bounded attempts:** halt the gameplay worker, emit a concise blocker report with failing test, exact observations and proposed next experiment; resume only after a new hypothesis or fix.

## 11. Time-boxed implementation order

**Sprint A — Stabilize and instrument:** snapshot code and save; confirm disc/version hashes; verify gBox state schema; enforce one input writer; create deterministic savestates and trace format; fix misleading status claims.

**Sprint B — Controller and combat:** calibrate frame-based steering, reproduce point-to-point walking, verify PMT lookup and weapon selection, prove box/Booma/flier/combo tests. No full-floor runs until these pass.

**Sprint C — Progression reverse engineering:** use controlled door/switch/wave/warp experiments with breakpoints; build event dependency graph and variant signatures; prove three-room chain.

**Sprint D — Unattended Forest:** integrate hierarchical planner, failure recovery, operator takeover and replay tests. Complete Forest 1→2 and Dragon repeatedly.

**Sprint E — Expand and mod:** reuse generic primitives across Caves/Mines/Ruins; encode three monuments; implement boss-specific controllers; then separate Ultimate-mod validation and optional level designer.

Allocate work by independent testable deliverables, not “research the whole game.” Parallel agents may analyze assets, combat and event routines, but only one agent may control a given live Dolphin session.

## 12. Future level designer (after autoplay works)

The map compiler should export a normalized **room template + portal + placement + event graph** schema. A level editor can then reposition entities, change room connections and author switch/door dependencies. Start with a **read-only viewer** overlaying rooms, navmesh, objects and live player position; next build a validator for reachable critical path, required monuments, safe spawns and valid warp targets. Only then attempt a repacker/REL or asset patcher, with backups and an isolated offline build. Geometry extraction alone is not sufficient to author a valid playable level.

## 13. Required status report after every experiment

```yaml
experiment_id: G4-booma-003
build_sha: REQUIRED
disc_sha256: REQUIRED
savestate_id: REQUIRED
emulated_frames: REQUIRED
hypothesis: REQUIRED
input_actions: REQUIRED
before_state: REQUIRED
after_state: REQUIRED
observed_hp_delta: REQUIRED
observed_position_delta: REQUIRED
pass: true_or_false
failure_class: null_or_named
artifact_paths: [trace.jsonl, screenshot.png]
next_action: REQUIRED
```

A worker may claim a capability only when it supplies the trace and meets the corresponding gate. Maintain `STATUS.md` with `verified`, `partial`, `failed`, `not_started` and a direct artifact reference. Stop using broad checkmarks for partial implementations.

## 14. Immediate instructions to DeepSeek

> You are taking over an existing PSO GameCube Dolphin/gBox autoplay project. Read `HANDOFF.md`, `OPERATOR-REQUESTS.md` and this plan. Do not restart from scratch. Freeze the current working build and identify the precise runtime entry points. Your first task is to produce an evidence-based inventory of existing modules and tests, reconcile the handoff addendum with the older claims, and implement gates G0–G2. Prioritize controller-only movement and a verified state decoder. Do not perform open-ended autonomous gameplay until G0–G2 pass. Then execute G3–G7 in order. Use Ghidra/Dolphin breakpoints to discover actual door/switch/wave semantics and build a persistent dependency graph. All discoveries must be backed by traces or asset offsets. Operator demonstrations must become replayable skills with passing tests. After each experiment, publish pass/fail, evidence, next hypothesis, and elapsed emulated frames. Stop loops that make no measurable progress. Preserve the ability for the operator to take over immediately. The first product milestone is a fully unattended Forest 1 → Forest 2 run without position writes.

## 15. Research references and limits

- GameFAQs Episode I & II walkthrough: doors can be enemy-wave-gated, switch-gated, floor-pad-gated or multi-switch; laser barriers; Forest/Caves/Mines second-floor columns: https://gamefaqs.gamespot.com/gamecube/516243-phantasy-star-online-episode-i-and-ii/faqs/30988
- GameFAQs alternate walkthrough: three columns required for Ruins: https://gamefaqs.gamespot.com/gamecube/516243-phantasy-star-online-episode-i-and-ii/faqs/24695
- GameCube manual: game modes and difficulty options: https://www.gamesdatabase.org/Media/SYSTEM/Nintendo_GameCube/Manual/formated/Phantasy_Star_Online_Episode_I_-_II_Plus_-_2004_-_Sega.pdf
- StrategyWiki overview and Episode II distinctions: https://strategywiki.org/wiki/Phantasy_Star_Online_Episode_I_%26_II
- Dolphin Memory Engine: https://github.com/aldelaro5/dolphin-memory-engine
- Dolphin MemoryWatcher source: https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/MemoryWatcher.h
- GameCube DOL/REL, PowerPC and endian reference: https://reverseengineering.wiki/index.php/Platform:Nintendo_GameCube
- User-provided project evidence: `HANDOFF.md` and `OPERATOR-REQUESTS.md` (2026-11-13 upload).

**Caveat:** Public guides describe game mechanics but do not establish the exact internal data structures, addresses or layout-variant count for this specific disc. Those must be proven in the local executable and assets. No direct access to the running Dolphin/gBox environment was available when this document was authored.
