# Marvel vs. Capcom 2 — Inventory (request #1547, game a392a0822bc4e95b)

## Authoritative owned source

The dispatcher assigned game_id `a392a0822bc4e95b`, platform `dreamcast`. Its catalog entry points to:

- `source_paths`: `/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/Marvel vs. Capcom 2.cdi`
- `format`: `cdi`
- `size`: 756,011,976 bytes

gBox `re_executable` rejects CDI images for Dreamcast executable extraction (job `477b533cb02048c4` failed with: "reading a Dreamcast disc needs a GDI, or a CHD plus chdman on this node"). The same physical share also contains a usable CHD of the same USA build:

- `game_id`: `86184244a61f816e`
- `title`: `Marvel vs. Capcom 2 - New Age of Heroes (USA)`
- `source_paths`: `collections/Sega Dreamcast/roms/Marvel vs. Capcom 2 (USA).chd`
- `resolved absolute`: `/mnt/gbox/hyperspin/Arcade/collections/Sega Dreamcast/roms/Marvel vs. Capcom 2 (USA).chd`
- `format`: `chd`
- `size`: 222,937,546 bytes
- `chd sha256`: `491273e9a1309f133c0305222d34e0c80b09554d9b64ff3d488c38c184fb77b5`
- `chd sha1`: `fa7a4551fa136daa6a0bfa721a56d83148900042`
- `chd crc32`: `32b0a259`
- `region`: `US`
- `system`: `Sega Dreamcast`
- `core`: `flycast`

This CHD is the authoritative owned source used for the executable extraction; the original `.cdi` is preserved and untouched.

## Container layout

After gBox unpacked the CHD into its local cache (`/home/ehm_eckx/samples/gbox-cache/dc/86184244a61f816e/`), the GD-ROM has three tracks:

```
3
1 0 4 2352 disc01.bin 0
2 450 0 2352 disc02.raw 0
3 45000 4 2352 disc03.bin 0
```

- Track 1: mode 2, ~1 MB
- Track 2: audio, ~100 MB
- Track 3: mode 2 data, ~1.18 GB — contains the IP.BIN / 1ST_READ.BIN and game assets

## Extracted main executable

`re_executable` produced an ELF for Ghidra from the main Dreamcast binary:

- `gBox job id`: `7f8ff688ffd34843`
- `worker`: `5289e92d8a6d40fc` (lilspark)
- `source_file`: `1ST_READ.BIN`
- `source_sha256`: `862e43cdd42fab395e2d71c8f1d9435f41af79380fe3b2820cb9ba25fe1f234f`
- `elf_sha256`: `8c55f650639fc2db138fa3f042312f221ce703e693567ae075b17f7e51ece198`
- `elf_path`: `/home/ehm_eckx/gBox/system/gbox-data/analysis/re/86184244a61f816e/1ST_READ.BIN.elf`
- `base`: `0x8C010000`
- `entry`: `0x8C010000`
- `cpu`: `sh4`
- `processor`: `SuperH4:LE:32:default`
- `elf_size`: 1,809,817 bytes

## Pending jobs for this inventory step

- `hash_game` on the CHD: `5116ab23cdcf4f8d` — completed, recorded catalog sha1/crc32.
- `re_executable` from the CHD: `7f8ff688ffd34843` — completed, ELF stored.

## Launch prerequisites

- Platform: Sega Dreamcast
- Core: `flycast` (RetroArch)
- Usable disc image format: CHD (or raw GDI); CDI is not supported for executable extraction by gBox.
- The assigned `.cdi` entry cannot be used for native analysis; use the equivalent USA CHD (`86184244a61f816e`).

## Asset expectations

Marvel vs. Capcom 2 is a 2D fighting game. Character data is expected on the GD-ROM as compressed sprite/tile/palette banks, and in `1ST_READ.BIN` as character tables and loader/decompression code. The next milestone is the `analysis` stage: import the ELF into Ghidra and locate asset loaders, compression routines, object tables, and format offsets, then document 2D sprite/tile/palette constraints.

## Next step

Start Ghidra analysis on `1ST_READ.BIN.elf` (SH-4, base `0x8C010000`) and record the resulting project / functions / strings. The first analysis goal is a focused, reproducible probe of the character loader, not a bulk decompilation dump.
