# PSO map directives + collision-surface publishing (RTS steering)

The PSO party plays deterministically from RAM (no vision LLM). This defines how
the **Mercenaries Map viewer** steers P1 like an RTS and how the PSO bot publishes
the collision surfaces it extracts, so the map agent can render a live, clickable
map and pathfind-preview over it. Proposed contract — map agent and bot converge
here. Produced by the PSO bot: `pso_map.py` (extraction + directive parsing),
`pso_coop.py` (controller consumes directives, publishes surfaces).

## Where things live (campaign runtime root)

`<config.runtime>/autoplay/pso-coop/<card_id>/` (same root as RoomMap + the
knowledge crystal). On the i9 that is `D:/gBox/runtime/autoplay/pso-coop/<id>/`.

- `pso-directive.json` — the operator's current directive (map agent / API WRITES,
  bot POLLS each tick by mtime). One active directive at a time.
- `pso-maps/<fingerprint>.json` — the extracted collision surface for one area/room
  template (bot WRITES on first entry; map viewer READS). Keyed by the same
  `room_key` fingerprint the knowledge crystal uses.
- `pso-knowledge.json` — the crystal; each room record also carries a `surface`
  summary (cell count, bounds, size, map-file name) so the crystal is the map DB
  index of every surface traversed across Episodes 1 & 2.

## Collision surface format (`pso-maps/<fingerprint>.json`, bot → viewer)

```json
{
  "version": 1,
  "fingerprint": "<room_key hash>",
  "episode": 1, "floor": 1, "room": 10,
  "geometry_identity": "<hash>",
  "size": 12.0,                      // world units per grid cell
  "bounds": {"min_x": -600, "min_z": -560, "max_x": 540, "max_z": 560},
  "cells": [[cx, cz], ...],          // walkable cells (grid coords; world = (c+0.5)*size)
  "gates": [ {"class": "TObjDoorKey", "x": -127.0, "z": 71.0, "room": 10, "flag": 7,
              "kind": "switch"}, ... ],   // doors/panels/switches/barriers + warps
  "warps": [ {"class": "TObjAreaWarpForest", "x": .., "z": .., "room": ..} ],
  "players": {"1": [x, z], "2": [x, z]}
}
```

World<->cell: `world = ((cx + 0.5) * size, (cz + 0.5) * size)`; `cell = (floor(x/size), floor(z/size))`.
A viewer click in world coords becomes a GOTO directive with that `x,z`.

## Directive format (`pso-directive.json`, viewer/API → bot)

```json
{ "id": "<unique per click>", "op": "goto|press|attack|clear",
  "x": -120.0, "z": 70.0,            // goto: world target (double-click point)
  "room": 10,                        // optional scope check
  "flag": 7,                         // press: stage-flag index to force-open
  "ptr": "80DB....",                 // attack: specific enemy object
  "episode": 1, "floor": 1,          // optional validity scope
  "ts": 1793650000.0 }
```

- **goto** — P1 A*-pathfinds over the extracted collision grid to `(x,z)`, routing
  around walls/obstacles and pressing any gate on the way (the stage-flag door
  system). Followers swarm P1 as always. Done when P1 is within reach of `(x,z)`;
  then the bot resumes autonomous-to-exit. A new `id` supersedes immediately.
- **press** — force the stage `flag` for the current area (the verified
  door-unlock), e.g. open a specific gate the operator points at.
- **attack** — prioritise the enemy at `ptr` (or nearest to `x,z`).
- **clear** (or no file / stale scope) — no operator directive: P1 runs the
  autonomous critical-path progression, heading for the area's forward
  teleporter/portal (the exit), never idling.

Validity: a directive is ignored unless it parses and (when given) its
`episode`/`floor`/`room` match the live state — a stale directive from another
area never acts (falls back to autonomous). The bot echoes the active directive
and its outcome in `stats["map_directive"]`.

## Autonomous (no directive) = navigate to the exit

With no valid directive P1 continues the deterministic progression: clear/unlock
the room's forward gate, then head for the next unvisited forward room and
ultimately the area's warp/teleporter that leaves the level (toward the boss).
This is the idle self-driving behaviour; an operator directive overrides it and,
once done/cleared, P1 resumes heading for the exit.
