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

---

# Map agent side (server feed + client) — built 2026-11-02

The bot half above (extraction, `pso-directive.json` polling, `stats["map_directive"]`) is in
`pso_map.py` + `pso_coop.py`. The viewer half is `gbox/pso_map_feed.py` (server) and
`clients/web/viz/pso-map.js` (the 2D map in the session side column). Both converge on the formats
above — this section records exactly what the server serves and how the client steers.

## Server: `gbox/pso_map_feed.py`

Finds the live run's campaign root (`<config.runtime>/autoplay/pso-coop/<card_id>/` — the dir whose
`pso-directive.json` / `pso-knowledge.json` / `pso-maps/` was written most recently) and exposes:

- `GET /api/pso/map/<sid>` — the live **map model** the client renders. Read-only, bounded.
- `GET /api/sessions/<sid>/pso-directive` — the current `pso-directive.json` (or `null`).
- `POST /api/sessions/<sid>/pso-directive` — the operator's click. Stamps a fresh `id` + `ts`,
  **validates with `pso_map.parse_directive`** (so the file is exactly what the bot consumes), and
  atomically writes `<root>/pso-directive.json`. 503 when there is no live PSO run; 422 on a bad
  directive. This is the only write; everything else is read-only.

### Map model (`GET /api/pso/map/<sid>` response)

```jsonc
{
  "schema": "gbox.pso.map/1", "sid": "...", "seq": 123, "live": true, "age_s": 0.4,
  "title": "Phantasy Star Online ...", "units": "pso",
  "episode": 1, "floor": 1, "room": 10, "fingerprint": "<room_key>", "size": 12.0,
  "bounds": [min_x, min_z, max_x, max_z],        // surface bounds (else fitted from the players)
  "cells": [[cx, cz], ...],                      // the bot's walkable grid cells (world = c*size)
  "gates": [ { "class": "TObjDoorKey", "x":..,"z":.., "room":10, "flag":7, "kind":"switch",
               "set": false } ],                 // "set" = the live stage-flag bit (pressed/open)
  "warps": [ { "class":"TObjAreaWarpForest", "x":..,"z":.., "room":10 } ],
  "players": [ { "slot":1, "role":"leader", "x":..,"z":.., "hp":33, "heading":82.1, "room":10 },
               { "slot":2, "role":"swarm",  "x":..,"z":.., "hp":38, "room":10 } ],
  "enemies": [],                                 // reserved: {ptr,x,z,cls,class,alive,hp} when the bot publishes them
  "map_directive": { "op":"goto", "state":"navigating", "x":..,"z":.. } | null,  // echoes stats["map_directive"]
  "objective": "TObjLazerFenceNorm",             // stats["forward_fallback_target"]
  "learned_areas": [ { "fingerprint":"...", "episode":1,"floor":1,"room":10, "cell_count":42,
                       "bounds":[...], "gates":2, "warps":1 } ],   // the crystal's surface index (browse)
  "stage_flags": { "floor":1, "read":true, "group_hex":"00 04 ..." } | null,
  "generated": 1793652200.1
}
```

Layers merged, with graceful degradation (any missing layer is omitted):
1. telemetry (`gbox.screensaver.telemetry_get`): `episode`/`floor`, `map_surface_fingerprint` (which
   `pso-maps/<fp>.json` to read), `map_directive`, `forward_fallback_target`, and the live player
   poses from `steering_evidence_json` (P1 leader, P2+ swarm);
2. the current area's surface file `<root>/pso-maps/<fingerprint>.json` (cells + size + bounds +
   gates + warps);
3. the crystal `<root>/pso-knowledge.json` → `learned_areas` (every surface summary ever recorded);
4. a bounded, cached live stage-flag read (read_memory RPC) that fills each gate's `set` bit
   (`STAGE_FLAG_BASE 0x80515CC8`, group = floor, MSB-first — the `pso_coop_gates.py` layout).

Even with only telemetry (no surface yet) the model already carries the players, floor, room and
objective, so the client shows them immediately and the surface/gates fill in once the bot publishes.

## Client: `clients/web/viz/pso-map.js` (`GBoxPsoMap`)

A dock section ("PSO map") in the session side column, gated to PSO titles (like "PSO controls"),
mounted/detached beside the Mercenaries tactical map. It polls `GET /api/pso/map/<sid>` (~1.5 Hz
while open, backing off when the endpoint is not up yet) and draws, in **world (x,z)**:

- the walkable surface as the floor (each `cells` cell is a world rect `c*size .. (c+1)*size`); the
  surrounding void reads as walls/obstacles — the real navigable space;
- gates: switches as circles, doors as squares; **green** when `set` (pressed/open), amber/red when
  not, grey when unknown;
- warps/teleporters as diamonds; players as arrows (P1 the bold leader, P2+ the swarm);
- P1's active GOTO as a dashed line from P1 to the `map_directive` target + a crosshair.

Click-to-command (writes `pso-directive.json` via the POST above):

- **double-click an open spot** → `{op:"goto", x, z, room, episode, floor}` (the click pixel →
  world via the same `unproject` the camera uses; scope fields let the bot reject a stale click);
- **click a gate/switch** → `{op:"press", flag, ...scope}` (force that stage-flag: open the gate);
- **click an enemy** (when enemies are published) → `{op:"attack", ptr, ...scope}`;
- **"Resume autonomous" button** → `{op:"clear"}` (P1 goes back to heading for the exit teleporter).

Zoom (wheel) / pan (drag) reuse the tactical map's world↔pixel transform; it fits the area on the
first frame and re-fits when the area (`fingerprint`) changes. Client changes are F5-applicable; the
feed + directive endpoints need a `gbox.service` restart to go live — until then the client degrades
(keeps polling, shows "Waiting for the PSO map feed…").

---

# Live-motion layer — "are they moving, and toward what?" (2026-11-03)

The operator kept seeing the party *sitting still* and asked for a map where motion (or its absence)
is obvious at a glance. The original layer above drew the collision surface + a single player from
`steering_evidence_json` — but that stream carries ONLY P1 and can lag many minutes, so the map showed
one stale, frozen dot; and when geometry is unverified (`map_surface_skip`) no surface publishes at
all, leaving an empty void. This layer fixes that, feed + client, without touching `pso_coop`.

## Feed (`gbox/pso_map_feed.py`) — new model fields

- **`players` now come from RAM, both of them.** `players_from_memory(sid, peek, actor, now)` reads the
  party slot pointer table at `PLAYER_PTR_TABLE 0x8050EA10` (P1..P4 object pointers, 4×u32 BE in one
  read), then each live object's world pose (`x/y/z` = big-endian f32 at object `+0x38/+0x3C/+0x40`).
  Bounded + cached ~4 Hz, read-only (never perturbs the bot). This is the authoritative, always-live,
  BOTH-players source; `steering_evidence_json` is used only to enrich HP by slot, and as a fallback
  (then the surface file). `model.players_source` ∈ `memory|steering|surface|none` says which won.
- **`forward`** — the bot's own progress/stuck telemetry, surfaced so the map can show it:
  `{room, rooms_visited, time_since_new_room_s, stuck, fallback_target, fallback_dist, fallback_action,
    floor_advances, nav_target_dist, nav_route_cells, nav_route_exact, nav_blocked, boss_active,
    boss_weakpoint_x, boss_weakpoint_z}`. `model.room` falls back to `forward.room` when no surface.
- **`plan`** — the run plan, i.e. the learned room-adjacency graph + critical path. The crystal file
  lives on the WORKER (`<runtime>/autoplay/pso-coop/<id>/pso-knowledge.json`) and is **not reachable
  from the control-plane server**, so this is read from telemetry `stats["pso_plan"]` (published by
  `pso_coop`), `null` until the bot publishes it. Expected shape (map agent ⇄ nav agent contract):
  `{ "area": "<area_fingerprint>", "floor": 5, "episode": 1, "current_room": 2, "target_room": 5,
     "crit_path": [2,5,12,...], "edges": {"2": {"<door_key>": 5}, ...},
     "forward_room": 2, "forward_rooms_visited": 2 }`
  (`current_room` = P1's room; `target_room` = `_path_next(current_room)`; `crit_path` =
  `KnowledgeStore.critical_path(area)`; `edges` = `KnowledgeStore.area_edges(area)`.)

## Client (`clients/web/viz/pso-map.js`)

- **Motion trails** — a fading world-space tail behind each player dot (P1 bold). A dot with a tail is
  moving; a dot with no tail is sitting still. Computed in the client from successive `players` poses,
  so it works regardless of what the bot reports.
- **MOVING / STUCK banner** — a big colored bar above the map. GREEN **MOVING → `<objective/target>`**
  when the dots are moving; RED **STUCK · not moving** (dots frozen, client-detected over a ~2.5 s
  window) or **STALLED · no new room** (bot's `forward.stuck`), with the stationary seconds, the
  fallback objective and distance-to-goal. This is the glanceable answer to "are they stuck?".
- **Plan strip** — the critical path as a left→right chain of room pills: visited rooms dimmed, the
  current room highlighted, the `target_room` ringed, the last pill flagged as the GOAL/exit. Before a
  route is learned it reads "Exploring floor N — building the map · K rooms seen · in room R". This is
  the "how the run is planned / toward the goal" view; it lights up once `stats["pso_plan"]` is
  published and degrades to the exploring note otherwise.

All client changes are F5-applicable. The feed changes (memory players, `forward`, `plan`) need a
`gbox.service` restart to go live; the `plan` strip additionally needs `pso_coop` to publish
`stats["pso_plan"]` (coordinate with the nav agent).
