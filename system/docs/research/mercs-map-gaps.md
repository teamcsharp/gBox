# Mercs stage maps: per-stage gaps (#9528)

Generator: `scripts/mercs_map_gen.py` (commit b09da5c1), format `gbox.mercs_map/1`,
units mm, y-up. Canonical output: `gbox-data/mercs/maps/<title>/<stage>.json`.
`gbox-data/` is gitignored by repository policy, so the full maps are generated on
demand; a bounded sample and a machine-readable manifest are committed under this
directory (`mercs-map-manifest.json`, `mercs-map-sample-re4-waterworld.json`,
`mercs-map-sample-re5-ancient-ruins.json`).

## How each map field was obtained (RE4 / RE5)

| field | source | parser |
|---|---|---|
| walls (segments with y0/y1 heights) | committed room_map tables `gbox/data/re4_switch_room_map/<room>.json` (RE4), `gbox/data/re5_switch_room_map/<room>.json` (RE5); each with a recorded sha256 in the map's `source` block | `scripts/mercs_map_gen.py` SAT-segment reader |
| walkable floor (cell grid + polygons) | committed nav tables `gbox/data/re4_switch_nav/<room>.json`, `gbox/data/re5_switch_nav/<room>.json` | same script; origin research `docs/research/re4-switch-mercs-collision.md` (#9342) |
| doorways / chokepoints | nav crossing points (RE4) / wall flag `WALKED` (RE5); chokepoint widths measured from wall gaps | same script |
| cover | room_map segments with low height, filtered per derivation note in each map's `derivation` block | same script |
| spawns | nav table `spawns.count` / `reachable` only | same script |
| route graph (named places, edges, blocked cells) | nav polygons + bonus places; grid A* between places | same script |

## Per-stage status

| title | stage (room) | static map | gaps |
|---|---|---|---|
| re4 | Waterworld (r404) | yes | spawn positions undetermined (nav carries count only; the `.esl` set lists would settle it); named places are grid blocks + bonuses, not the game's room names; walls are all-storey SAT segments merged, per-storey floors not separated |
| re4 | Village (r401) | yes | same as above |
| re4 | Base (r402) | yes | same as above |
| re4 | Castle (r403) | yes | same as above |
| re5 | Ancient Ruins (s403) | yes | spawn positions not in the Havok table; the stage's enemy layouts (`s40N_emNN`) would settle it; floor Y is an estimate from the nav height field, not measured from collision |
| re5 | The Mines (s401) | yes | same as above |
| re5 | Missile Area (s402) | yes | same as above |
| re5 | Public Assembly (s404) | yes | same as above |
| re5 | Ship Deck (s405) | yes | same as above |
| re5 | Village (s406) | yes | same as above |
| re5 | Prison (s407) | yes (6.0 MB map — largest stage) | same as above |
| re5 | re5 bus stage per `docs/research/re5-bus-nav.md` | see nav research | nav-only, not yet folded into this format |

Full per-stage element counts (walls / floor polygons / doorways / chokepoints /
cover / route nodes+edges) and source sha256 hashes for all 11 generated maps
(4 RE4 + 7 RE5 stages) are in `mercs-map-manifest.json`.

## RE6 (Switch) — no committed collision table

**Status: not determined, by absence of source data.**

- No collision table is committed for the RE6 Switch Mercenaries stages
  (rooms `s1200`..`s1209`): only a NavMesh and greybox research exist
  (`system/docs/research/re5-switch-qte-map.md`-style nav work plus the greybox
  research under this directory).
- Walls, floor, doorways/chokepoints, cover and spawns for RE6 are therefore
  **not determined** — the generator emits an RE6 gap block with exactly this
  wording for every title run.
- What would settle it: a **Havok/collision parser run over the RE6 RomFS on
  lilspark** to produce committed `gbox/data/re6_switch_room_map/s120N.json`
  tables (same SAT layout as the RE4/RE5 room_map files), after which
  `scripts/mercs_map_gen.py --title re6` (once the re6 title is added) builds
  RE6 maps in the same `gbox.mercs_map/1` format without changing the format.
- Until that capture lands, RE6 stays a documented gap, not a guess: no value is
  written into a measured column for RE6 stages.

## Known floor-Y limitation (RE4 / RE5)

Floor Y values are derived from the nav height field and are estimates, not
measured collision heights. The nav capture that would measure them (per-stage
collision Y samples) is the same Havok parser run as above.

## Not yet done (acceptance still open)

- Runtime consumption of the map format by the bot core (`system/gbox/mercs/core/`)
  and the MercMode / RE subset comparison against main (known red: RE5 Switch
  bonus / giveup / smooth / rampage / threat).
