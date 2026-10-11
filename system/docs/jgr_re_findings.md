# Jet Grind Radio (USA) — Dreamcast model container reconnaissance

Disc: `Jet Grind Radio (USA)` (game_id `4187aeab4d67638c`, dreamcast, CHD in the `hyperspin`
library). Extracted to GD-ROM tracks with `chdman extractcd` for read-only analysis (the same
route the DOA2 lane uses for `1de2e7634f3161ff`).

## Disc layout (ISO9660, via gbox.gdrom.GDRom)

423 files. The browser front-end (DPWWW/DPETC/DPTEX/DPSS/DPFONT) is the Dream Passport shell;
the game itself lives under `JETRADIO/` (328 files: 231 `.adx` audio, 96 `.afs` archives, 25 `.pvr`).

Character data archives (sizes from the ISO directory):

| file | size | contents |
|------|------|----------|
| `JETRADIO/PLAYER.AFS` | 14 143 488 | player models + textures |
| `JETRADIO/ENEMY.AFS`  |  4 970 496 | enemy character models + textures |

## AFS archive format (PLAYER.AFS)

Header: `AFS\0` + uint32 LE `count` + `count` × interleaved (uint32 offset, uint32 size) pairs,
which is the standard CRI AFS layout. For PLAYER.AFS, `count` = 34. Each size is exact, and every
entry starts on the next 0x800 boundary.

(Correction: the first reader split the table into `count` offsets followed by `count` sizes. That
mixed sizes in with offsets and made 17 of the 34 entries disappear. The pair reading tiles the
archive with no overlaps.)

Entries in table order: 16 × (`PLAY` model, `PTEX` texture set) pairs for the 16 player
characters, plus 1 × `main` (shared container, entry 16) and 1 × `EFTX` (effect textures,
entry 17). ENEMY.AFS (54 entries) uses another layout: alternating raw GBIX texture sets and
model blobs that start `11 25 02 00` / `11 21 02 00` / `13 25 04 00`.

## PLAY / PTEX container header

A `PLAY` chunk is **not** a Ninja NJCM chunk (no `NJCM`/`NMDM`/`NJTL` magic anywhere in the first
200 KB; this is a JGR-specific container):

```
"PLAY" + uint32 N + N × (uint32 value, uint32 kind)
```

The first PLAY chunk (offset 524288) has N = 12, with records
`(108,1) (40060,1) (140868,1) (87120,1) (112852,1) (117412,2) (43408,3) (789344,4) (789024,5)
`(143036,6) (792768,7) (812880,0)` — relative sub-object offsets grouped by `kind`. `PTEX` uses the
same shape (`PTEX` + N + records; first PTEX has N = 0x194 = 404).

## PTEX texture sets (decoded)

After the PTEX header table (404 records in the first set, meaning not yet known), the data
holds standard Dreamcast PVR textures, starting at +0x1000. Each one is a `GBIX` chunk (global
texture index) followed by a `PVRT` chunk. They are 4-byte aligned and run back to back, and the
last one ends exactly at the entry end. `gbox.ninja.pvr_decode` decodes all of them as-is:
89 textures in 16 PTEX sets plus the EFTX set. Formats seen: VQ (3), VQ + mipmaps (4), small VQ
(0x10) and twiddled (1), in RGB565, ARGB4444 and ARGB1555. Character 0's set: a 256×256 VQ body
atlas (face, teal outfit, striped sleeves and pouches), a 128×128 face-expression sheet with 4
expressions, and two 64×64 textures. GBIX 760 shows up in every set, probably a shared texture.
A vision model checked both large textures and found coherent character art, not noise.

## PLAY model trees (decoded)

A `PLAY` chunk is a raw **Ninja chunk-model object tree** without the `NJCM` wrapper. Every pointer
is relative to the start of the PLAY chunk. `NJS_OBJECT` is 0x34 bytes (evalflags, model, pos[3],
ang[3], scl[3], child, sibling). `NJS_CNK_MODEL` (vlist, plist, center[3], radius) is stored after
its polygon and vertex lists. Polygon lists use standard chunk types: `0x13` material, `0x08`
texture id, `0x40`/`0x41` strips. Vertex lists use `0x22`, `0x23` and `0x29` (XYZ + normal) with
cache base indices, so weighted joints reuse vertices across nodes, the same way SA2 and PSO do.
`gbox.ninja.NJ`'s walker parses these trees unchanged.

The container-header records of kind 1-3 are the model roots. The first record is a root table,
not an object, and kinds 4-7 hold motion and other data. Every one of the 16 PLAY chunks has:

- 4 body roots with a **20-node** skeleton: 2 detail levels × 2 variants, about 1,400-2,100
  triangles at the high level and about 650-1,000 at the low level;
- 1 shadow volume (11-17 vertices, no strips);
- 1 small accessory tree (usually 4 nodes).

On character 0, the high-detail body (root `+0x15450`) stands upright (Y up) and is 17.5 units
tall, with its feet at y = 0.12. Its texture ids 0/1 bind to PTEX textures 0/1. A flat-shaded
render of 8 characters was checked by a vision model, which judged all 8 to be coherent humanoids
with no exploded or scrambled triangles. `export_play_glb` writes a package plus a self-contained
skinned GLB with the PTEX textures embedded.

## Native collection (gbox.characters)

`characters.DEDICATED` routes Jet Grind Radio / Jet Set Radio (Dreamcast) to the `jgr` reader, so
favouriting the game or running `characters op=collect` extracts its roster with no game launch.
`jgr.roster()` lists the 16 PLAY/PTEX pairs of PLAYER.AFS as `jgr_char00`..`jgr_char15`. The
characters' real names are not read from the disc yet. `jgr.extract_run` exports each character's
high-detail body (the 20-node root with the most triangles) with its PTEX textures.

All 16 bodies share one tree (`jgr.BODY_PARENTS`). node001 is the pelvis, and both legs and the
spine branch from it. Each arm has a clavicle, shoulder, elbow and wrist. Characters 02 and 12 are
bound with an arm raised above the head. The generic `tree_roles` can't read this rig, so
`jgr.body_roles` checks the exported skin against `BODY_PARENTS` and the +X left side, then returns
the fixed `BODY_ROLES` map (15 roles). On the owned disc, all 16 entries pass `verify_entry`, map
15 roles through `rig_from_gltf` and are marked retargetable.

## Open questions (follow-up work)

- **Motion data** (kinds 4-7, about 650 KB in the kind-6 record): not decoded yet.
- **Texture-id binding** to PTEX order is assumed for ids 0-2; the PTEX header table (404
  records) may remap them per variant.
- **Writer and bone map**: rebuild a PLAY tree from a library character, mapped onto the 20-node
  skeleton, then verify the swap in-game at the operator's saved moment.

`gbox/jgr.py` implements the verified parts: `afs_entries`, `chunks`, `entry_size`,
`container_header`, `inventory`, `play_model_roots`, `play_model`, `play_summary`,
`export_play_glb`, `ptex_textures`, `decode_texture` and `export_texture_set`. The earlier
`play_subobjects`/`decode_submesh` helpers slice records by header address and are superseded by
the tree walk. Tests (`tests/test_jgr.py`) gate on the owned disc and skip when it is absent, the
same fixture pattern as the DOA2 suite.

## Swap writer (#1155, work in progress, not routed to `characters op=use`)

`jgr.build_swap` / `build_mod` / `use` port the SA2 chunk-model writer. They use `ninja_swap.fit`, `ninja.cnk_model_lists` with the original vertex chunks kept, `pvr_like` for PTEX texture 0, and `jgr.replace_entries`, which rewrites the entry in place in its AFS room. `patch_gdi` then works unchanged.
- PLAYER.AFS fills its disc extent (6906 sectors, PROMO.AFS follows). Each PLAY's AFS room is its size plus 52–2036 bytes of padding, so the new body must fit inside the bytes the old body frees.
- Character 00's body (root +0x15450) frees 42,634 bytes: model structs 456, vertex lists 27,036, strips 15,142. No other root shares those offsets exactly. The kept vertex lists take 27,036 of that. Amy Rose at 299 triangles adds 10,780 bytes (measured with `cnk_model_lists`), so the totals should fit.
- Measured result: the encode still comes out 13–14 KB over the room (826,992 > 813,056) even at 300 triangles. Next step: log the holes `encode` computes against these totals. Most likely another root's lists partly overlap the body's ranges, and `shared` then re-protects them. It could also be fragmentation around the node structs. Fix that before routing `use` (the routing patch is kept at `~/.hermes/cache/scratch/jgr_use_routing.patch`). Use `/usr/bin/blender` (arm64) for decimation: `/usr/local/bin/blender` is x86-64.

## Swap writer: space allocation fixed (#1155, run 3)

- Cause of the 13.9 KB overflow: each node's lists were placed in their own hole first, and the 2-byte
  padding between a node's plist and vlist split every hole in two. Anything that didn't fit was appended
  past the entry, where PLAY 00 has only 152 bytes of AFS padding (812,904 bytes used of 813,056 room).
- `pack_blobs` now sizes every blob first, merges the padding gaps, and places blobs home-first, then
  best-fit-decreasing, then 2000 seeded random restarts. The AFS padding is used only as a last resort.
- Character 00 has 20 holes totalling 42,672 bytes (largest 5652/5296/4256/4244). At 300 triangles, five lists
  are over 2.8 KB but only four holes can take them, and the smallest pair (2852 + 2828) misses the 5652 hole
  by 28 bytes. That is why BUDGETS now continues 270/240/200.
- Owned-disc result: Amy Rose fits at 269 triangles. The PLAY entry stays at 812,904 bytes, PLAYER.AFS keeps
  its length and offsets, only entries 0 and 1 (PLAY/PTEX 00) change, and the patched GD-ROM re-reads
  byte-equal. Root 0x15450 decodes with 20 bones and 269 triangles (originally 2054).
- Caveat for in-game checks: on the modded data `body_root` picks tree 0x9c7c (1834 triangles, untouched).
  That is a second full-size body in PLAY 00. If gameplay draws 0x9c7c instead of 0x15450, the swap won't
  show, and 0x9c7c needs the same treatment.
