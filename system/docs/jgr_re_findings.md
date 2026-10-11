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
