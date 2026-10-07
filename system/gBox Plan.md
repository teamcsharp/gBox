# gBox — Master Implementation Plan

## 0. Execution Directive

You are the lead systems architect and implementation agent for **gBox**. Your job is to build the system described in this document from top to bottom as a working, testable, auditable platform. Do not substitute demos, mock success, placeholder data, or unverified claims for implementation.

Work incrementally. Every capability must have acceptance tests, artifacts, logs, and a rollback path. When a third-party tool cannot support a requested capability, record the limitation and implement the cleanest adapter/fallback rather than silently claiming success.

The system must support a Linux-hosted deployment on the machine/environment referred to by the operator as **DGX Spark** (NVIDIA DGX Spark, arm64; originally misrecorded as "DJI Spark"), plus a standalone Windows deployment/node. The operator will later provide the network path to the game library/NAS. Do not hard-code that path.

Only operate on games/assets the operator is authorized to use. Preserve provenance for extracted and transformed assets and do not build DRM/access-control circumvention into the generic workflow.

---

## 1. Product Definition

gBox is a **universal game laboratory** combining:

- Multi-platform game launching/emulation behind a common interface.
- PC/Steam game integration where practical.
- Runtime memory/state inspection.
- Ghidra-assisted static reverse engineering.
- Automated semantic discovery of game state.
- Autonomous gameplay and strategy improvement.
- A universal live asset eyedropper.
- Mesh, texture, material, skeleton, rig, animation, collision, environment and metadata extraction.
- A canonical asset representation for cross-title conversion.
- Blender integration and export to common 3D formats.
- Godot and Unreal-oriented output/import workflows.
- Mod construction, repacking/injection where supported, and validation.
- Local and online LLM orchestration through typed tools/services.
- A persistent game knowledge graph, asset library, strategy library, experiment store and audit ledger.
- Remote Linux operation plus a standalone Windows experience.

The user-facing concept is **one application**, even though execution is delegated to specialized emulator cores, reverse-engineering tools, extractors, converters and runtime adapters.

---

## 2. Non-Negotiable Design Principles

### 2.1 gBox is the harness, not a monolithic emulator

Do not merge every emulator into one codebase. Existing mature emulators are execution engines behind adapters.

### 2.2 Ghidra is an analysis service

Ghidra is used for decompilation, symbols, xrefs, structures, loaders, asset-format discovery, game-logic discovery and semantic mapping. It is not expected to be the renderer, emulator, asset editor or universal ripper.

### 2.3 LLMs never get credit merely for saying something worked

A successful operation requires evidence and validation.

**Nothing may claim that learning or modification occurred unless it can point to an artifact, an evaluation and a measurable result.**

### 2.4 Prefer narrow typed tools over unrestricted shell control

The orchestrator calls operations such as `read_memory`, `extract_character`, `decompile_function`, `open_in_blender`, or `validate_mod`. Individual workers may use CLIs internally, but the orchestration API remains structured and auditable.

### 2.5 Separate observation, reasoning and control

LLMs handle semantic interpretation, planning, hypothesis generation and strategy review. Fast deterministic components handle frame-level input, navigation execution, combat primitives and other latency-sensitive actions.

### 2.6 Preserve source truth

The NAS/game library is the source of truth. gBox indexes it rather than duplicating the full collection. Local copies are bounded cache/staging artifacts only when required.

### 2.7 Every game gets a growing Game Profile

Knowledge learned about a title persists across sessions and can be reused by autoplay, extraction, reverse engineering and modding.

---

## 3. High-Level Architecture

```text
                           G-BOX CLIENTS
                  Windows UI / Browser / Remote UI
                              |
                              v
+----------------------------------------------------------------+
|                    G-BOX CONTROL PLANE                         |
|                                                                |
|  Session Manager   Job Scheduler   Permissions   API Gateway    |
|  Orchestrator      LLM Router      Tool Registry  Event Bus     |
+-----------------------------+----------------------------------+
                              |
       +----------------------+-----------------------+
       |                      |                       |
       v                      v                       v
+-------------+       +---------------+       +---------------+
| Execution   |       | Analysis      |       | Asset Lab     |
| Nodes       |       | Services      |       | Services      |
|             |       |               |       |               |
| Emulators   |       | Ghidra        |       | Extractors    |
| PC runtime  |       | Debuggers     |       | Normalizer    |
| Input       |       | Memory/trace  |       | Blender bridge|
| Streaming   |       | RE adapters   |       | Exporters     |
+------+------+       +-------+-------+       +-------+-------+
       |                      |                       |
       +----------------------+-----------------------+
                              |
                              v
+----------------------------------------------------------------+
|                      PERSISTENT KNOWLEDGE                       |
| Game Catalog | Game Profiles | Knowledge Graph | Asset Library |
| Strategies   | Experiments   | Audit Ledger    | Artifact Store|
+----------------------------------------------------------------+
                              |
                              v
                       NAS GAME LIBRARY
```

---

## 4. Deployment Model

### 4.1 Linux / DGX Spark deployment

Run the main gBox control plane as services on Linux. It should support:

- Remote web/API access.
- Headless emulator workers where supported.
- Video/audio streaming from execution nodes.
- LLM routing.
- Background indexing and analysis jobs.
- Persistent databases and artifact storage.
- Remote access from other computers on the network.

Containerize stateless services where sensible. Hardware-sensitive emulator/GPU/debugger components may run directly on the host and register as workers.

### 4.2 Windows standalone/node

Provide a Windows build capable of:

- Running locally without the Linux host for basic functions.
- Registering with the larger gBox control plane when available.
- Hosting Windows-only tools/emulators/debuggers.
- Running the same emulator adapter protocol.
- Providing the overlay/eyedropper and local Blender bridge.
- Optionally using remote LLM and knowledge services from the Linux host.

### 4.3 Shared protocol

Linux and Windows nodes must expose the same capability-oriented protocol. A job should request a capability, not a specific machine unless necessary.

---

## 5. Game Library / NAS Catalog

The operator will supply the network path later. Build configuration for SMB/NFS/local mounted paths without assuming the final location.

### Scanner pipeline

1. Discover files/directories.
2. Detect platform and container/image format.
3. Compute hashes without modifying originals.
4. Deduplicate metadata entries.
5. Identify title, region, revision/serial where possible.
6. Associate compatible emulator/runtime adapters.
7. Register launch recipes.
8. Create/update Game Profile.
9. Index metadata in a searchable catalog.

### Catalog fields

- Game ID.
- Title.
- Platform.
- Region.
- Revision/serial.
- Source path.
- Hashes.
- Format/container.
- Emulator/runtime compatibility.
- Playable status.
- Analysis status.
- Asset mapping status.
- Autoplay readiness.
- Modding adapter status.
- Game Profile ID.

### Storage policy

Do not bulk-copy the library. Implement a bounded local cache with LRU/size policies and explicit staging receipts.

---

## 6. Universal Emulator / Runtime Adapter API

All execution backends implement a common capability interface. Not every backend must implement every capability; capability discovery is mandatory.

Minimum conceptual operations:

```text
launch_game()
stop_game()
pause()
resume()
get_frame()
get_audio()
send_input()
read_memory()
write_memory()
query_memory_map()
save_state()
load_state()
step_frames()
set_breakpoint()
remove_breakpoint()
trace_execution()
query_runtime()
stream_session()
get_capabilities()
```

Build adapters rather than forks whenever possible.

Potential backend classes include Dreamcast, GameCube/Wii, PlayStation generations, arcade/retro systems and native PC/Steam execution. Select actual projects only after checking current platform support, APIs, licenses and automation feasibility.

---

## 7. Ghidra Service

Create a headless Ghidra integration with a typed service layer.

Required capabilities:

- Import/analyze executable or module.
- Query functions/symbols.
- Decompile function.
- Find xrefs.
- Search strings/constants.
- Query/create structures and labels.
- Record inferred semantics.
- Analyze asset/resource loaders.
- Correlate static addresses with runtime observations where feasible.
- Produce patch proposals/change descriptions.
- Export analysis artifacts into the Game Profile.

Ghidra findings must include confidence and provenance. Hypotheses remain hypotheses until runtime evidence validates them.

---

## 8. Runtime Inspector and Semantic State Extractor

Build a layer that converts raw memory/runtime information into game concepts.

Examples:

```text
Player
  position
  heading
  velocity
  HP / resources
  animation/action state
  inventory/equipment

Enemy
  identity/type
  position
  heading
  HP
  state
  target
  attack range
  perception/vision information when discoverable

World
  room/zone
  doors/transitions
  collision/navigation information
  spawn points
  pickups
  mission flags
  boss state
```

Discovery should combine memory differential analysis, runtime tracing, controlled experiments, Ghidra analysis and game-specific adapters. Do not permanently feed huge unstructured memory dumps into learning systems when stable semantic features can be extracted.

---

## 9. Autonomous Gameplay System

The autoplay system is hierarchical.

```text
Mission Planner
      ↓
Strategy / Route Planner
      ↓
Room / Navigation Planner
      ↓
Combat / Interaction Controller
      ↓
Frame-Level Input Driver
```

### LLM responsibilities

- Interpret objectives.
- Generate/test hypotheses.
- Suggest strategies.
- Analyze failures.
- Compare routes.
- Decide when exploration is justified.
- Consolidate learned knowledge.

### Deterministic/algorithmic responsibilities

- Controller timing.
- Path following.
- Collision avoidance.
- Target tracking.
- Combat primitives.
- Reactive safety logic.
- Replaying known successful routes.

### Learning requirement

Do not equate episode count with progress. Runs must be evaluated and consolidated. Redundant raw data should be summarized or deleted according to policy.

---

## 10. First Autoplay Vertical Slice: Phantasy Star Online Version 2 (Dreamcast)

Use **Phantasy Star Online Version 2** as the first complete autoplay proof of concept.

Target loop:

```text
load character
→ enter target area
→ identify current map/rooms
→ navigate room graph
→ engage and clear enemies
→ collect desired items/drops
→ manage HP/resources/inventory
→ reach boss
→ defeat boss
→ record metrics
→ return/restart
→ repeat indefinitely
```

Initial semantic state should seek:

- Player XYZ/heading.
- HP/TP/status.
- Current room/area.
- Doors/transitions.
- Enemy identity, XYZ, HP and state.
- Current target and useful attack/range information.
- Inventory/equipment.
- Ground item identity when discoverable.
- Drop/rare relevance when discoverable from legitimate game state/data.
- Quest/boss/completion/death state.

Build a persistent room graph and learned-route store. Once a route is reliable, reuse it rather than forcing the LLM to rediscover it.

Success criterion: the system can complete a constrained area repeatedly without human control, recover from common deviations, record failures, and demonstrate measurable route/combat improvement.

---

## 11. Second Autoplay/World-Model Target: Metal Gear Solid VR Missions

Use this later to validate richer semantic reasoning.

The system should attempt to derive rather than manually receive:

- Mission goals.
- Player position/state.
- Guard positions and facing.
- Perception/vision constraints.
- Weapons/equipment.
- Collision/traversable geometry.
- Hazards.
- Level constraints.
- Success/failure flags.

Use these to build pathfinding and strategy optimization rather than relying solely on computer vision.

---

## 12. Universal Live Asset Eyedropper

This is a flagship gBox interaction.

### User experience

While a supported game is running:

1. Toggle **Picker Mode**.
2. Hover/click a visible object.
3. Highlight the resolved object.
4. Display identity and extraction confidence.
5. Offer actions such as:
   - Inspect runtime properties.
   - Extract visible representation.
   - Extract full object/prop.
   - Extract full character.
   - Extract rig/skeleton.
   - Extract animation set.
   - Extract room/environment.
   - Send to Blender.
   - Open in internal 3D viewer.
   - Add to gBox asset library.
   - Export supported exchange formats.

### Resolution pipeline

```text
screen coordinate
→ camera/ray or render selection
→ rendered object/draw association
→ runtime entity/component
→ resource handles
→ source/cooked assets
→ dependency graph
→ canonical asset package
```

Implement multiple strategies:

1. Engine-native/runtime semantic selection when available.
2. Graphics/render interception or frame/resource correlation where appropriate.
3. Emulator GPU/runtime inspection for emulated systems.
4. Static/runtime reverse engineering as an escalation path.

### Confidence report

Never label an extraction “complete” without evidence. Report independently:

- Entity match.
- Geometry.
- Materials.
- Textures.
- Skeleton.
- Skin weights.
- Animations.
- Collision.
- Source path/resource identity.
- Runtime behavior linkage.

---

## 13. Asset Extraction Tool Adapters

Build an adapter framework rather than hard-coding a single extractor.

Tool families to investigate and integrate where licensing/automation permits include:

### Unity-oriented

- AssetRipper.
- AssetStudio-class tooling.
- UABEA/UABE-class tooling.
- BepInEx/Harmony/MelonLoader runtime adapters.
- UnityExplorer-style runtime inspection.
- ILSpy/dnSpy-class managed-code inspection when appropriate.

### Unreal-oriented

- CUE4Parse/FModel-class asset discovery/extraction.
- UModel/UE Viewer-class inspection.
- UAssetAPI/UAssetGUI-class asset manipulation.
- UE4SS runtime integration.
- UnrealPak/repak/retoc/ZenTools-class container workflows as appropriate for engine generation.

### Generic/native/custom engines

- Ghidra.
- Runtime debugger adapters.
- QuickBMS-style archive scripting where suitable.
- Custom parsers/converters built as game/engine adapters.

Before bundling or distributing any third-party component, verify its current license and integration obligations. Prefer process/service boundaries when that reduces coupling and licensing risk.

---

## 14. Canonical Asset Representation

Do not make every converter translate directly from Game A to Tool B. Create a durable internal **Universal Asset Package (UAP)**.

A UAP can contain:

```text
manifest.json
geometry/
  meshes
  LODs
  UV sets
  normals/tangents
  vertex attributes
materials/
textures/
rig/
  bone hierarchy
  bind/rest pose
  skin weights
animations/
  clips
  timing
  root motion
  events where known
  morphs where known
collision/
scene/
  hierarchy
  transforms
  instances
  lights where supported
metadata/
  source game
  source resource IDs
  coordinate system
  game units / scale
  dependencies
  extraction method
  confidence
  provenance
```

The canonical representation must preserve information that target formats may discard.

---

## 15. Blender Bridge

Build a Blender addon/service bridge.

Required operations:

- Receive UAP packages from gBox.
- Create meshes.
- Reconstruct materials/textures as faithfully as practical.
- Create armatures.
- Apply skin weights.
- Import animation clips.
- Preserve hierarchy.
- Normalize/display correct game-space scale.
- Preserve source transforms.
- Select/highlight imported source entity.
- Update/reimport an asset without unnecessary duplication.
- Import entire environment/room.
- Return Blender object IDs and validation information to gBox.

Target experience:

```text
click character in game
→ Send to Blender
→ character appears in Blender with geometry, materials, rig and available animation
```

Environment mode:

```text
select room/region
→ resolve scene membership
→ collect dependencies
→ reconstruct hierarchy/transforms/materials
→ room appears in Blender at correct scale
```

---

## 16. Export / Conversion Layer

Support, where semantically appropriate:

- glTF/GLB.
- FBX.
- OBJ for static geometry.
- Alembic/ABC for suitable animation/cache workflows.
- Blender-native editable representation.
- Godot-oriented packages/import recipes.
- Unreal-oriented static/skeletal mesh and animation import recipes.

### Rig/animation retargeting

Implement a mapping pipeline:

```text
source skeleton
→ canonical skeleton description
→ destination bone correspondence
→ rest-pose correction
→ axis/handedness normalization
→ scale normalization
→ animation retargeting
→ validation
```

Do not assume skeleton names or proportions match across titles.

---

## 17. Cross-Title Asset Reuse and Mashups

The orchestrator must distinguish **appearance/assets** from **behavior/game logic**.

For a request such as “bring an enemy from Game A into Game B,” create a dependency analysis covering:

- Mesh.
- Skeleton.
- Animations.
- Materials/textures.
- Collision.
- Audio/effects.
- AI/controller behavior.
- Attacks/damage integration.
- Navigation assumptions.
- Spawn system.
- Resource dependencies.
- Destination-engine compatibility.

Classify each dependency as:

- Directly reusable.
- Convertible.
- Retargetable.
- Must be recreated using destination systems.
- Unsupported/unknown.

Never claim that copying model files alone reproduces an enemy.

---

## 18. Mod Construction and Game Transformation

Support tasks ranging from simple asset replacement to behavior/system changes.

Examples:

- Replace sprite/texture/model.
- Change character appearance.
- Alter spawn configuration.
- Create high-density enemy modes.
- Modify mission rules.
- Adjust entity limits when understood and safely testable.
- Build cross-title asset experiments.

Every mod operation creates a **reproducible changeset** containing:

- Source game/version/hash.
- Files/resources changed.
- Functions/addresses/structures affected when applicable.
- Assets added/removed.
- Conversion steps.
- Tool versions.
- Build/repack steps.
- Validation results.
- Rollback information.

Never modify the canonical NAS copy in place by default. Work from staged copies/overlays and produce distributable patch/change artifacts where appropriate.

---

## 19. LLM and Agent Architecture

Support both offline/local models and optional online services.

### Roles

- **Orchestrator:** owns the task plan and delegates.
- **Reverse Engineering Agent:** static/runtime hypotheses.
- **Game-State Agent:** semantic-state discovery.
- **Autoplay Strategy Agent:** route/strategy improvement.
- **Asset Agent:** dependency extraction and normalization.
- **Conversion Agent:** rigs/materials/format conversion.
- **Mod Agent:** transformation planning/building.
- **Validator Agent:** independent evaluation.
- **Knowledge Curator:** consolidation/deduplication.

Agents share structured knowledge but must not overwrite evidence with prose conclusions.

### Tool schema

Each tool declares:

```text
name
version
capabilities
input schema
output schema
supported platforms
supported engines/games
required permissions
side effects
artifacts produced
timeout/retry policy
validation method
```

### Example tool calls

```text
analyze_binary
find_function
decompile_function
read_memory
trace_runtime
identify_entity
extract_character
extract_environment
normalize_asset
retarget_animation
open_in_blender
export_asset
build_mod
launch_game
run_autoplay_episode
validate_extraction
validate_mod
```

---

## 20. Knowledge Graph and Game Profiles

Each Game Profile should accumulate relationships such as:

```text
Game
→ executable/module
→ engine/runtime
→ levels/maps
→ entities/archetypes
→ meshes
→ materials/textures
→ skeletons
→ animations
→ AI/controllers
→ functions
→ memory structures
→ spawn rules
→ collision/navigation
→ items
→ mission flags
→ extraction recipes
→ mod recipes
→ autoplay strategies
→ evidence
```

Every edge should support provenance/confidence where relevant.

---

## 21. Accountability, Evaluation and Data Lifecycle

This subsystem is mandatory before large-scale autonomous training.

### Every experiment/run records

- Run ID.
- Game/build/hash.
- Hypothesis/objective.
- Initial state.
- Actions/policy version.
- Observations.
- Outcome.
- Metrics.
- Artifacts.
- Cost/time.
- Evaluator result.
- Knowledge changes.
- Retention decision.

### Independent evaluation

The component that proposes a strategy/change must not be the sole authority deciding that it succeeded.

### Knowledge consolidation

After experiments:

- Identify novel findings.
- Detect duplicates.
- Update confidence.
- Promote validated facts.
- Deprecate contradicted facts.
- Summarize useful runs.
- Delete redundant raw data according to retention policy.

### Dashboard metrics

Prefer metrics such as:

- Evaluated runs / total runs.
- Novel validated findings.
- Strategy changes that improved performance.
- Regression rate.
- Extraction completeness.
- Reproducible mod success rate.
- Storage generated vs retained.

Do not use “number of episodes” as the primary success metric.

---

## 22. Validation Framework

### Emulator/runtime validation

- Game launches.
- Inputs work.
- Memory queries are internally consistent.
- Save/load state works where supported.
- Stream remains synchronized.

### Asset validation

- Geometry counts/bounds plausible.
- Textures resolve.
- Material slots resolve.
- Skeleton hierarchy is valid.
- Skin weights are valid.
- Animation duration/key data is valid.
- Scene transforms/scale are preserved.
- Round-trip import succeeds.

### Mod validation

- Clean build/staged game launches.
- Target behavior is observable.
- No unexpected crash during test window.
- Performance metrics recorded.
- Original files remain recoverable.

### Autoplay validation

- Objective completion rate.
- Death/failure rate.
- Route time.
- Resource usage.
- Recovery from deviation.
- Performance against prior best strategy.

---

## 23. UI Requirements

Provide one coherent gBox interface with at least:

- Game Library.
- Search/filter by platform/title/status.
- Launch/play view.
- Remote video/audio stream.
- Controller/manual takeover.
- Autoplay toggle and current objective.
- Runtime inspector.
- Memory/state inspector.
- Ghidra analysis view/linkage.
- Picker Mode overlay.
- Extraction panel.
- Asset library.
- 3D preview.
- “Send to Blender.”
- Experiment history.
- Strategy history.
- Audit/evidence view.
- Worker/node status.
- Job queue.

Manual takeover must always be straightforward during autoplay.

---

## 24. Suggested Internal Service Boundaries

```text
gbox-api
gbox-orchestrator
gbox-tool-registry
gbox-llm-router
gbox-catalog
gbox-profile-service
gbox-knowledge
gbox-artifact-store
gbox-audit
gbox-job-scheduler

gbox-execution-agent
gbox-emulator-adapters
gbox-pc-runtime-adapter
gbox-streaming
gbox-input

gbox-ghidra
gbox-runtime-inspector
gbox-debugger-adapters
gbox-semantic-state

gbox-asset-discovery
gbox-asset-extraction
gbox-uap
gbox-conversion
gbox-blender-bridge
gbox-mod-builder

gbox-autoplay
gbox-navigation
gbox-combat
gbox-evaluator
```

Do not create unnecessary network boundaries early. These are logical boundaries; start as a modular monorepo where practical and split into processes/services only when isolation, OS constraints, licensing, GPU access or scaling justify it.

---

## 25. Security and Operational Controls

- Bind remote control interfaces securely; do not expose unauthenticated emulator/debugger control to the internet.
- Separate read-only inspection from mutation permissions.
- Require explicit authorization for memory writes, binary patches and game-file modifications.
- Stage mutations in working copies/overlays.
- Maintain immutable hashes of originals.
- Log tool invocations and side effects.
- Store secrets outside source control.
- Sandbox third-party parsers where practical because game/archive files may be malformed.

---

## 26. Implementation Phases

### Phase 0 — Repository and contracts

Deliver:

- Monorepo.
- Configuration system.
- Core schemas.
- Tool registry.
- Job/event model.
- Artifact store.
- Audit ledger.
- Basic web/API shell.
- Linux + Windows worker registration.

Exit criterion: a dummy typed tool can execute remotely and produce a validated artifact/receipt.

### Phase 1 — NAS catalog and execution abstraction

Deliver:

- Network library configuration.
- Scanner/indexer.
- Metadata DB.
- Game Profiles.
- Emulator adapter interface.
- First working emulator backend.
- Video/input path.

Exit criterion: select a cataloged game remotely, launch it, view it and control it.

### Phase 2 — PSO V2 instrumentation

Deliver:

- Dreamcast backend suitable for instrumentation.
- Memory observation tooling.
- PSO V2 Game Profile.
- Semantic player/enemy/room extraction.
- Input driver.
- Run recorder.

Exit criterion: dashboard displays verified semantic state while PSO V2 runs.

### Phase 3 — PSO V2 autoplay vertical slice

Deliver:

- Room graph.
- Navigation.
- Combat primitives.
- Mission planner.
- Failure recovery.
- Evaluation/consolidation.

Exit criterion: repeated autonomous completion of a constrained PSO V2 run with measurable metrics.

### Phase 4 — Ghidra semantic bridge

Deliver:

- Headless Ghidra worker.
- Static/runtime correlation.
- Semantic hypothesis workflow.
- Knowledge-graph integration.

Exit criterion: a runtime observation can be traced to documented static structures/functions and validated.

### Phase 5 — Asset laboratory

Deliver:

- UAP specification.
- Initial engine/emulator extraction adapters.
- Texture/material/mesh extraction.
- Skeleton/animation extraction where supported.
- Internal 3D viewer.
- Blender addon/bridge.

Exit criterion: supported asset can be extracted and reconstructed in Blender with provenance.

### Phase 6 — Live eyedropper

Deliver:

- Picker overlay.
- Runtime/render object resolution.
- Highlighting.
- Dependency collection.
- Extraction confidence UI.
- “Send to Blender.”

Exit criterion: click a supported visible object and reproduce it in the viewer/Blender without manually locating files.

### Phase 7 — Environments and conversion

Deliver:

- Region/room selection.
- Scene hierarchy extraction.
- Correct transforms/scale.
- GLB/FBX/OBJ/ABC output as appropriate.
- Godot/Unreal import recipes.
- Skeleton/animation retargeting.

Exit criterion: extract a supported environment and a rigged character into a new 3D scene with documented fidelity.

### Phase 8 — Mod builder

Deliver:

- Changeset format.
- Staging/overlay system.
- Asset replacement workflow.
- Engine-specific repack/build adapters.
- Automated launch/regression testing.

Exit criterion: create, reproduce, validate and roll back a supported game modification.

### Phase 9 — Cross-title experiments

Deliver:

- Dependency classifier.
- Destination compatibility analysis.
- Conversion/retargeting workflow.
- Behavior recreation plan support.

Exit criterion: demonstrate a legally usable source asset being normalized and integrated into a separate controlled target project/game workflow with complete provenance.

### Phase 10 — Broader platform coverage

Add emulator/PC adapters iteratively from older systems through newer targets. Never claim “universal” support solely because the UI lists a platform. Capability status must reflect actual tested support.

---

## 27. Definition of Done for Any Feature

A feature is done only when:

1. It has a typed interface.
2. It has tests.
3. It produces logs/receipts.
4. Failure modes are represented explicitly.
5. Artifacts have provenance.
6. Mutations are reversible where applicable.
7. The UI reports real capability/status rather than assumptions.
8. Documentation describes how to reproduce the result.
9. A validator independently confirms the acceptance criteria.

---

## 28. Immediate Build Order

Begin implementation in this order:

1. Repository and schemas.
2. Audit/artifact infrastructure.
3. Tool registry and orchestrator.
4. Linux/Windows worker protocol.
5. NAS catalog configuration/scanner.
6. Dreamcast emulator adapter.
7. PSO V2 launch/input/frame/memory instrumentation.
8. PSO semantic-state extractor.
9. PSO room/navigation/combat vertical slice.
10. Ghidra worker and semantic bridge.
11. UAP asset schema.
12. Blender bridge.
13. First extraction adapter.
14. Picker prototype.
15. Environment extraction.
16. Conversion/export.
17. Mod builder.
18. Additional emulator and PC-engine adapters.

Do not start by integrating every emulator or every extraction utility. Prove the contracts with PSO V2 and one complete asset extraction path, then expand horizontally.

---

## 29. First-Run Configuration

On first launch, gBox should request/configure:

- Game library network path(s).
- Local cache path and size limit.
- Artifact/knowledge storage path.
- Available execution nodes.
- Blender executable/bridge availability.
- Ghidra installation/service availability.
- Local LLM endpoint(s).
- Optional online LLM provider(s) and credentials.
- Preferred emulator backends per platform.
- Permission policy for memory writes/modification.

The operator has not yet supplied the final NAS path. Leave this as configuration.

---

## 30. Deliverables Expected From the Implementation Agent

Maintain these continuously:

```text
README.md
ARCHITECTURE.md
ROADMAP.md
SECURITY.md
LICENSES-THIRD-PARTY.md

docs/
  tool-contracts.md
  emulator-adapters.md
  ghidra-service.md
  autoplay.md
  asset-uap.md
  live-picker.md
  blender-bridge.md
  mod-builder.md
  validation.md
  deployment-linux.md
  deployment-windows.md

schemas/
services/
clients/
adapters/
tests/
fixtures/
```

At the end of every implementation milestone, report:

- What was actually implemented.
- What was tested.
- Exact test results.
- What remains incomplete.
- Known limitations.
- New artifacts/files.
- Storage/data generated.
- Any third-party licensing implications discovered.
- Recommended next milestone.

Never report planned work as completed work.

---

## 31. Final Product Vision

gBox should eventually allow the operator to browse a network game collection, launch a title through the appropriate runtime, manually play or enable autonomous play, inspect the game's semantic state, click a visible object to identify and extract it, reconstruct characters or environments in Blender, convert assets through a canonical representation, build controlled modifications, test those modifications, and reuse knowledge learned about the game in future sessions.

The complexity is intentionally hidden behind one interface, but the implementation remains modular: **specialized execution engines and analysis tools below, gBox contracts and orchestration above, persistent evidence and knowledge underneath everything.**
