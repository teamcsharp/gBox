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

Header: `AFS\0` + uint32 LE `count` + `count`×uint32 offsets + `count`×uint32 sizes
(standard CRI AFS). For PLAYER.AFS, `count` = 34.

The offset table alternates large offsets (character chunks) and small offsets; filtering by magic
yields 17 character chunks in table order — 8 × `PLAY` (models), 8 × `PTEX` (texture sets), 1 ×
`main` (shared container). This matches the 8 playable characters shipped in PLAYER.AFS.

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

## Open questions (follow-up work)

- **File sizing semantics**: the AFS size table does not tile the archive cleanly under either the
  "offset+size per index" or "interleaved (offset,size) pairs" reading; sizes ~7–14 MB overlap.
  Likely uncompressed sizes vs. stored sizes, or a second table region. Needs byte-level
  confirmation before a mesh writer can target exact allocations (the DOA2 lane hit the same issue
  with CHR vs. SUP budgets).
- **Mesh vertex/triangle format**: the sub-objects referenced by the PLAY record table are not yet
  decoded (JGR's variant of the Ninja layout). This is where a Ghidra pass on `1ST_READ.BIN`
  (model loader) is needed, as done for DOA2.
- **Texture decode**: PTEX holds PVR texture sets; whether `gbox.ninja.pvr_decode` applies directly
  (or a JGR PVR variant) is unverified.

`gbox/jgr.py` implements the verified parts: `afs_entries`, `chunks`, `container_header`, and
`inventory`. Tests (`tests/test_jgr.py`) gate on the owned disc and skip when it is absent, the same
fixture pattern as the DOA2 suite.
