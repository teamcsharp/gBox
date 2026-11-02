# PSO interactive 2D map — data + directive contracts

Status: v1 (2026-11-02). Owner of the **map feed + client renderer + directive write path**: the
PSO-map build. Owner of the **nav** (reading RAM, publishing the surface, and *consuming* the
directives below): the sibling PSO-nav agent (`pso_coop*`). This doc is the handshake between them.

The whole map is built from the game's RAM — no vision, no screenshots. Players, enemies, switches,
doors, the walkable surface and the stage flags all come out of memory (the nav agent already reads
them each tick; the feed re-serves them read-only).

Pipeline:

```
RAM  --(pso_coop, each tick)-->  telemetry.stats.pso_map   --\
                                 pso-knowledge.json (crystal) --> /api/pso/map/<sid> --> pso-map.js (canvas)
                                 stage-flag RPC (read_memory) --/
operator click on canvas --> POST /api/sessions/<sid>/pso-directive --> pso_coop consumes (A* to target)
```

---

## 1. Operator → bot: PSO directives

The operator clicks the map; the client POSTs a structured directive. The nav agent polls it and
makes **P1 (the sole navigator / leader)** act on it. P2+ are swarm-followers and need no directive.

### Endpoints

- `POST /api/sessions/<sid>/pso-directive` — write the newest directive (operator/agent).
- `GET  /api/sessions/<sid>/pso-directive` — read the newest directive + the kind catalogue.

Both require the normal bearer auth (`Authorization: Bearer <token>`); `x-gbox-actor` is recorded as
the source. Only the **newest** directive per session is kept (newest-wins, like the Mercenaries
directive channel). The store is in-memory, bounded, TTL ~10 min.

### Directive payloads (POST body)

All coordinates are **PSO world coordinates** (the same `x` / `z` the nav agent reads from the player
and object structs — right-handed, +y up). `y` is optional; the floor plane is `x`/`z`.

```jsonc
// Double-click an open point on the walkable surface → navigate there (RTS move order).
{ "kind": "goto",   "x": -233.2, "z": 128.3, "floor": 1, "room": 10 }   // floor/room optional, advisory

// Single-click a switch / floor panel → go stand on it and press it.
{ "kind": "press",  "switch_id": "sw_5_12" }                 // preferred: the id from the feed
{ "kind": "press",  "x": -210.0, "z": 95.0 }                 // or a world position

// Click an enemy → the swarm attacks it (P1 leads, P2+ follow fire).
{ "kind": "attack", "enemy_id": "ene_5_3" }                  // preferred: the id from the feed
{ "kind": "attack", "x": -180.0, "z": 60.0 }

// Click a door / barrier → go to it (and open it once its switch condition is met).
{ "kind": "open",   "door_id": "door_5_1" }
{ "kind": "open",   "x": -250.0, "z": 300.0 }

// Clear the manual order → resume autonomous play (continue to the exit teleporter when idle).
{ "kind": "clear" }
```

`kind` is required and one of `goto | press | attack | open | clear`. For `press`/`attack`/`open`,
supply **either** the id (`switch_id` / `enemy_id` / `door_id`) **or** a world `x`+`z`. Unknown fields
are ignored. Out-of-range / non-finite coordinates are rejected (422).

### GET response

```jsonc
{
  "directive": {                 // null when none is set
    "seq": 42,                   // monotonic; the nav agent acts only when seq changes
    "kind": "goto",
    "x": -233.2, "z": 128.3, "floor": 1, "room": 10,
    "switch_id": null, "enemy_id": null, "door_id": null,
    "at": 1793652200.1,          // unix seconds
    "until": 1793652800.1,       // TTL expiry
    "source": "operator"         // the x-gbox-actor that posted it
  },
  "kinds": ["goto", "press", "attack", "open", "clear"]
}
```

### How the nav agent should consume it (pso_coop)

1. Poll `GET /api/sessions/<sid>/pso-directive` (or read it alongside your existing directive poll).
2. Track `directive.seq`. When it changes, latch the new order for **P1**.
3. Resolve the target:
   - `goto {x,z}` → A* to that world point on the extracted surface.
   - `press {switch_id|x,z}` → path to the switch, stand/press (reuse the panel logic).
   - `attack {enemy_id|x,z}` → set P1's combat target; the swarm already follows P1.
   - `open {door_id|x,z}` → path to the door; open when its gate flag is satisfied.
   - `clear` (or no directive, or an expired one) → resume autonomous-to-exit: continue to the
     area's portal / teleporter to leave the level.
4. A directive never presses a key by itself — it changes *what P1 decides*, so all your normal
   safeguards (line-of-sight, blast distance, stuck recovery) stay in force.
5. When you reach / complete the order, you may echo progress in `telemetry.stats.pso_map.target`
   (see §3) so the operator sees it land on the map.

---

## 2. The map feed: `GET /api/pso/map/<sid>`

Read-only. Aggregates (in priority order): the live `telemetry.stats.pso_map` block the nav agent
emits (§3), the persisted crystal surface/objects (§4), and an optional bounded stage-flag read.
Degrades gracefully — any missing layer is simply omitted. Model shape:

```jsonc
{
  "schema": "gbox.pso.map/1",
  "sid": "...", "seq": 123, "live": true, "age_s": 0.4, "title": "Phantasy Star Online ...",
  "episode": 1, "floor": 1, "room": 10, "fingerprint": "d5fd7034...",
  "units": "pso",
  "bounds": [minx, minz, maxx, maxz],       // world extent of the rendered area (from the surface)
  "surface": { ...see §4.surface... } | null,
  "rooms":    [ { "id":"r_10", "room":10, "center":[x,z], "fingerprint":"..." } ],
  "switches": [ { "id":"sw_5_12", "x":..,"z":..,"flag_index":12, "pressed":true|false|null, "opens":"door_5_1" } ],
  "doors":    [ { "id":"door_5_1", "x":..,"z":..,"type":"TObjDoor", "flag_index":13, "open":true|false|null, "to_room":11 } ],
  "warps":    [ { "id":"warp_5_1", "x":..,"z":..,"kind":"area_warp", "to":"floor_2" } ],
  "exit":     { "x":..,"z":..,"kind":"teleporter" } | null,
  "enemies":  [ { "id":"ene_5_3", "x":..,"z":..,"cls":"TObjEneBm3", "class":"Booma", "alive":true, "hp":120 } ],
  "players":  [ { "slot":1, "role":"leader", "x":..,"z":..,"y":..,"hp":33, "heading":82.1, "room":10 },
                { "slot":2, "role":"swarm",  "x":..,"z":..,"hp":38, "room":10 } ],
  "path":     [ [x,z], [x,z], ... ],        // P1's current A* path (from the nav agent)
  "target":   { "x":..,"z":..,"kind":"goto" } | null,
  "objective": "head to TObjLazerFenceNorm",
  "learned_areas": [ { "fingerprint":"...", "episode":1, "floor":1, "room":10,
                       "has_surface":true, "switches":3, "doors":1 } ],
  "stage_flags": { "floor":1, "group_hex":"00 80 ...", "read":true } | null,
  "generated": 1793652200.1
}
```

The client polls this (~1–2 Hz) and re-renders. `seq` lets it skip unchanged frames.

---

## 3. nav agent → feed: the live `pso_map` telemetry block  (please emit this)

Add a `pso_map` dict to the autoplay telemetry `stats` each tick (it rides the existing
`POST /api/autoplay/telemetry/<sid>`; nothing new to wire). The feed serves it as the live layer.
Everything is RAM-derived and already in hand on the worker:

```jsonc
"pso_map": {
  "schema": "gbox.pso.map/1",
  "area": { "episode":1, "floor":1, "room":10, "fingerprint":"d5fd7034..." },
  "surface_ref": "d5fd7034...",             // which crystal surface applies (usually = fingerprint)
  "surface": { ...optional inline; see §4.surface... },   // omit if already persisted to the crystal
  "players": [ { "slot":1, "role":"leader", "x":..,"z":..,"y":..,"hp":33, "heading":82.1, "room":10 },
               { "slot":2, "role":"swarm",  "x":..,"z":..,"hp":38, "room":10 } ],
  "enemies": [ { "id":"ene_5_3", "x":..,"z":..,"cls":"TObjEneBm3", "class":"Booma", "alive":true, "hp":120 } ],
  "objects": [ { "id":"sw_5_12",  "kind":"switch", "x":..,"z":..,"flag_index":12, "state":"pressed", "opens":"door_5_1" },
               { "id":"door_5_1", "kind":"door",   "x":..,"z":..,"type":"TObjDoor", "flag_index":13, "state":"locked", "to_room":11 },
               { "id":"warp_5_1", "kind":"warp",   "x":..,"z":..,"warp_kind":"area_warp", "to":"floor_2" },
               { "id":"exit_5",   "kind":"exit",   "x":..,"z":..,"warp_kind":"teleporter" } ],
  "path":   [ [x,z], [x,z], ... ],          // P1's current A* path toward its target/exit
  "target": { "x":..,"z":..,"kind":"goto" }, // what P1 is currently heading for (order or autonomous)
  "objective": "head to TObjLazerFenceNorm"
}
```

If you cannot emit the block yet, the feed still synthesizes players from
`stats.steering_evidence_json` (it reads each player's latest `after` pose), and takes `episode`,
`floor`, `forward_room` and `forward_fallback_target` from the existing stats — so the map shows
players + room + objective from day one. Enemies/switches/doors and the surface appear as soon as
either the `pso_map` block or the crystal (§4) carries them.

`state` strings: switches `pressed|unpressed`; doors `open|locked`; use `null`/omit when unknown.

---

## 4. The crystal (`pso-knowledge.json`): the growing full-map DB

Path: `<config.runtime>/autoplay/pso-coop/<card_identity>/pso-knowledge.json`
(`KnowledgeStore`, keyed by room **fingerprint** = `pso_coop_nav.room_key`). Today each record holds
the forward-gate recipe (`gate`, `forward_flags`, `floor`, `room`, `base`). Please extend each
record (via the existing `KnowledgeStore.remember(fingerprint, **info)`) with the **walkable surface
and static objects** so the feed can render learned areas even when they are not live, and so the
operator can browse the whole explored map:

```jsonc
// pso-knowledge.json  ->  rooms[<fingerprint>]  += :
{
  // ...existing gate/forward_flags fields stay as-is...
  "surface": {
    "origin": [x0, z0],      // world coords of grid cell (col=0,row=0) corner
    "cell": 50.0,            // world units per grid cell (square)
    "cols": 64, "rows": 64,  // grid size
    "walk_b64": "<base64>",  // cols*rows bits, row-major, MSB-first, 1 = walkable; OR:
    "cells": [[x,z], ...],   // fallback: sampled walkable world points (point cloud)
    "bounds": [minx, minz, maxx, maxz]
  },
  "switches": [ { "id":"sw_5_12", "x":..,"z":..,"flag_index":12, "opens":"door_5_1" } ],
  "doors":    [ { "id":"door_5_1", "x":..,"z":..,"type":"TObjDoor", "flag_index":13, "to_room":11 } ],
  "warps":    [ { "id":"warp_5_1", "x":..,"z":..,"kind":"area_warp", "to":"floor_2" } ],
  "exit":     { "x":..,"z":..,"kind":"teleporter" }
}
```

`walk_b64` is preferred (compact, scales); `cells` is an acceptable fallback. The feed reads whatever
is present. Static object positions live here; their **live** open/pressed state comes from the
`pso_map` block (§3) or the stage-flag read (§5).

---

## 5. Stage-flag read (feed side, optional overlay)

The feed can resolve door/switch open|pressed live by reading the verified 3OE2 stage-flag array
directly (read-only `read_memory` RPC, not admission-gated), using the flag layout reverse-engineered
in `pso_coop_gates.py`:

- `STAGE_FLAG_BASE = 0x80515CC8`, 18 groups × 32 bytes; `group = floor` (0..17).
- flag `index` (0..255): byte = `base + group*32 + index//8`, mask = `0x80 >> (index%8)` (MSB-first).

The feed reads the 32-byte group for the live floor (one bounded read, cached ~1 s) and, for any
switch/door whose `flag_index` is known from the crystal/`pso_map`, sets `pressed`/`open` from the
bit. When the RPC channel is unavailable it is simply skipped and live state falls back to the
`pso_map` block. This never writes memory.

---

## 6. Coordinate transform (map ↔ world)

The renderer works entirely in **world (x,z)**. Pixel↔world is an affine mapping derived from the
view camera (centre, radius, rotation) exactly as the Mercenaries tactical map does
(`project` / `unproject`). The initial camera is fitted to `bounds` (the surface extent). So a click
at canvas pixel `(px,py)` becomes world `(x,z) = unproject(view, px, py)` and is sent verbatim as the
`goto` target — no separate calibration is needed as long as the feed's `bounds`/positions and the
nav agent's A* operate in the **same world units** the player/object structs use. They do.
