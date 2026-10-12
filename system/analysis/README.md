# Analysis — Sonic 1 and 2 (Genesis, 2MB hack)

Request 1345 (0b30e8e87ba14438), game_id 48d757e779e88504.

## Goal of this stage
Locate the Nemesis art decompressor and the sprite mapping / DPLC tables in the
owned ROM, and prove the art pipeline with a small format probe that decodes a
Nemesis stream to 4bpp tiles and dumps a PNG.

## ROM identity
- File: `work/rom/Sonic 1 and 2.bin` (2,097,152 bytes)
- sha256: `a755e0ae96df4b881f52e347ac450ce2207f8403667e06de5da0ef9fb499d99d`
- Base: Sonic 2 (GM 00001051-01, JUE), expanded to 2 MB with Sonic 1 levels.

## Tools in this directory
- `find_nemesis.py` — Ghidra script (Jython) run against the ROM with the
  `68000:BE:32:default` language. It looks for the Nemesis decompressor entry
  signature, reports callers, and lists word-aligned candidate Nemesis stream
  headers.
- `nemesis_probe.py` — standalone Python format probe. It uses the bit-exact
  `clownnemesis-tool` decoder to extract a Nemesis stream from the ROM and write
  a PNG tile sheet. This validates the 4bpp art pipeline end-to-end without
  writing a re-encoder first.
- `clownnemesis-tool` — Linux x86_64/aarch64 build of
  https://github.com/Clownacy/clownnemesis (v1.1-ish, built from source). The
  binary is included as a convenience; the source and build script are listed
  below so the workspace can rebuild it.

## Pipeline constraints (Genesis 2D)
- Tiles: 8×8 pixels, 4 bits per pixel (16 colors incl. transparent index 0).
- Tile storage: 32 bytes per tile, 4 interleaved bitplanes (Genesis planar).
- Nemesis compression: variable-length prefix codes + inline runs; optional
  XOR mode (high bit of header word).
- Sprite display: mapping tables assemble tiles into frames; DPLC tables tell
  the VDP which pattern IDs to load. These tables are found via the decompressor
  xrefs in stage 2/3.

## Nemesis stream discovery
`nemesis_probe.py --scan` finds word-aligned streams whose header word decodes
exactly to the declared tile count. Representative verified streams:

| offset   | xor  | tiles | note |
|----------|------|-------|------|
| 0x004b42 | no   | 10    | small object art |
| 0x00d49a | yes  | 64    | first successfully dumped stream |
| 0x078aa2 | yes  | 32    | mid-ROM art block |
| 0x07beb4 | yes  | 457   | large enemy/boss art candidate |

## Evidence artifacts
- `probe_0xd49a.nem` — raw Nemesis stream bytes from offset 0xd49a.
- `probe_0xd49a.bin` — decoded 4bpp tile bytes (64 tiles = 2,048 bytes).
- `probe_0xd49a.png` / `probe_0xd49a_v2.png` — PNG tile sheet for visual
  inspection.

## Build / rebuild clownnemesis
```bash
git clone --recursive https://github.com/Clownacy/clownnemesis.git
cd clownnemesis
mkdir build && cd build
cmake ..
make -j$(nproc)
cp clownnemesis-tool /path/to/workspace/analysis/
```

## Next step (stage 3: reader)
With the decompressor location from Ghidra and the verified Nemesis decoder,
identify the mapping/DPLC table format and build a small native asset reader
that extracts a chosen character frame as an editable PNG/bitmap. The target
roster is Sonic/Tails/Eggman and the S1/S2 enemy set.
