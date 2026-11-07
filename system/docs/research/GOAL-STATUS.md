# Where the objective stands — evidence per requirement

Written 2026-11-07 (round 24 of this session). Every line points at code, a test or a measurement, not at an intention.
Where something is missing it says so.

## (a) Decrypt a title's data

| title | state | where |
|---|---|---|
| RE4 Switch (HD port) | **done** — UDAS/DAT little-endian containers, DDS surfaces, FEN zlib archives | `re4gc_inventory` (`udas_entries`, `dat_entries`, `switch_inventory`), `re4hd_tex` |
| RE5 / RE6 Switch | done earlier — MTF `.arc` | `mt_arc`, `skin_swap`, existing routes |
| RE4 GameCube | done earlier — UDAS/DAT big-endian | `re4gc_inventory`, `re4gc_models` |
| RE4 VR (Quest) | paks open; **Oodle needs a supplied decoder** (`oo2core_9_win64.dll`) | `ue_pak`, `docs/research/re4-vr-extraction.md` |

## (b) Rip and inventory every asset, with a view/extract/replace flow

| asset class | inventory | view | replace |
|---|---|---|---|
| models — RE4 Switch | **162 packs, 2,727 BIN slots, 0 errors** | **3D view** (`model-geometry` falls through to `re4hd_models`) | **`pack-swap` route**, `plan_swap`, `morph_bin` |
| models — RE4 GC / MTF titles | existing inventories | existing 3D view | existing writers |
| textures — RE4 Switch | **1,702 `TPL` descriptors**; **680 DDS surfaces in 8 archives, 0 refused** | **PNG preview** (`/texture.png`), DXT3/DXT5 | read/edit path open; **texture-id → archive-entry join missing** |
| environments | stage packs listed (`st1` 34 entries, `st2` 42); room data | — | — |
| sound effects | **not decoded.** `bio4/snd` identified as CRI: 112 `.acb` (`@UTF`) + 112 `.awb` (`AFS2`); header fields read, entry map and payload codec **not** established | — | — |

The extraction tab (lab) now has **25 `/api/decrypt-lab` routes**, including the HD-specific `arc-layout`, `pack-slots`,
`pack-swap`, `textures` and `texture.png`.

## (c) Replace assets at runtime

| target | state | evidence |
|---|---|---|
| RE5 Switch — clothes / skin / cast / zombies | **working** (texture-map level) | `mercmode-panel-swaps.md`, live builds |
| RE5 Switch — mine / grenade objects | working at texture level; **a donor mesh breaks the load** | `decrypt_lab` comment, measured 2026-11-05 |
| RE4 Switch — enemy *shape* | **working**: vertices morphed onto a donor's surface are drawn | `re4switch-morphed-ganados-*.jpg` |
| RE4 Switch — enemy *mesh replacement* | **does not work**: a rebuilt mesh is accepted by every offline check and **ignored by the engine** | `re4-switch-mod-boot.md` (rounds 17–23) |
| RE4 Switch — uniform transforms | **working**: every Ganado slot scaled, round plays | `re4switch-scaled-ganados-drawn.jpg` |
| RE4 GC — Sonic as player and as every ganado pack | **working** (58 of 60 enemy packs) | `HANDOFF.md`, `re4gc_zombies` |

## (d) The same machinery, reusably

* `re4hd_models`: `bin_read` / `bin_bones` / `bin_info`, `bin_write` (**2,188 of 2,188 decodable slots re-encode
  byte-identically**), `bin_from` (+ `encoding="strip"`, ~50 % smaller), `pad_to`, `simplify`, `rank_targets`,
  `plan_swap`, `morph_to` / `morph_bin`. 66 tests.
* `re4gc_inventory`: endian-aware UDAS/DAT (`'>'` GC, `'<'` HD), `switch_inventory`, `bin_slots`, `pack_patch`
  (162/162 packs byte-identical when patched with their own bytes). 9 tests.
* `re4hd_tex`: descriptor + DDS + FEN, `fen_entry`, `fen_texture`, `fen_textures`. 14 tests.

## The lab page

3D views, tables, RAM hex scanning, inbox triage and live bot perception were already there; this session added the HD
port's packs, slots, meshes and textures to the same page and the two routes that act on it.

## Reports (RE only when killed, hurt, or a bullet misses)

Implemented earlier and unchanged: `mercs/round_reports.has_incident` gates on death / damage / misses, and the incident
bundle carries the bounded RAM witness (`mercs/incident.py`; Switch emulators have **no** save state, so the RAM witness
is the designed substitute). Also fixed this session: a library that was still loading no longer files a ticket
(`_library_not_ready`), and the two stale tickets were closed with evidence.

## MercMode sidebar panel — the four requested actions

All four exist in the PiP panel and are backed by routes: `data-mm-swap="plain"` (remove clothes), `"clothes"` (swap
clothes), `"to-zombie"` (character → zombie), `"from-cast"` (zombies → cast, via the whole-set `zombie-cast` route), plus
the object swap and the combined "player → zombie, enemies → cast". Verified at the API level on the live RE5 tree; the
panel's own test suite passes (21/21).

## What is NOT achieved

1. **A clean character (Sonic/Mario/DOA) standing in for a Switch enemy.** The engine ignores a rebuilt mesh; the morph
   bends the shape but yields a distorted blob. This is the same wall RE5 Switch reached; RE4 GameCube is where a real
   rigged model works.
2. **Sound effects.** CRI containers identified, not decoded.
3. **RE4 Switch in the MercMode rotation.** The walk from title to a round works (logged, twice), but `snapshot()` has no
   RAM anchors, so the bot cannot aim or fire and `mercs.ready` stays false. The bot also has no rule for the story save
   list's confirm overlay beyond cancelling it.
4. **Mercenaries 3D.** Drivers exist (`merc3d_3ds`, `merc3d_bot`, `merc3d_strategy`); no work this session.
5. **RE4 VR playable.** Android arm64 + OpenXR; extraction works, runtime does not exist on the Spark.
6. **Texture replacement on RE4 Switch** (clothes/skins): the DDS path is open, the descriptor→archive join is not.
7. **RE4 Switch `em11`–`em17` slot identity** is no longer in doubt (the packs are drawn) but which slot is the *body*
   is not mapped; the morph reached all 240 slots at once, so this no longer blocks a shape change.

## The honest one-line summary

The RE4 Switch pipeline now decrypts, inventories, views (**3D meshes and textures**) and replaces at the level the
engine accepts: same-topology vertex edits and uniform transforms, with byte-identical round-trips proving the writer
understands the format. A clean character swap on these titles is still blocked by the engine's refusal to draw a
rebuilt mesh — measured, not assumed — and the work that would change that (part-table rules) has not been attempted.
