# 007 - GoldenEye (Europe) inventory

This run resolves the exact owned N64 build, verifies its integrity, and
catalogues the ROM layout so the next stage can pin the hard-coded asset
offsets for the European cartridge.

## Owned source

* Path: `collections/Nintendo 64/roms/Europe/007 - GoldenEye (Europe).zip`
  in the HyperSpin library (`/mnt/gbox/hyperspin/Arcade`)
* ZIP size: 10,794,599 bytes; ZIP SHA-256:
  `c0d34cfe6a13c77c446d7c31944f715cce1c3769ee0c5fd610a6ec85c9fb1cac`
* ROM member: `007 - GoldenEye (Europe).z64` (12 MiB, byteswapped .v64
  data inside a `.z64` wrapper)
* Normalised big-endian .z64 SHA-256:
  `40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de`
* Header: title `GOLDENEYE`, cart ID `GE`, region byte `0x50` (Europe),
  version `0x00`, entry PC `0x80000400`
* Boot checksum: CIC-NUS-6102 CRC1/CRC2 matches stored values
  `0414CA61` / `2E57B8AA`

## What the module does

`gbox/goldeneye_inventory.py` reads the ROM via `gbox.n64_rom.read`,
validates the header and CIC-6102 checksum, extracts the boot code region,
computes a coarse 64 KB entropy/zero map of the whole ROM, and records
launch prerequisites and a high-level character/texture/animation
inventory.

`tests/test_goldeneye_inventory.py` runs the inventory against the owned
source and asserts the build is the Europe cartridge with a valid boot
checksum.

## Container / asset layout

GoldenEye uses a flat ROM; it has no central file table.  Asset offsets
(model block, stage setups, textures, animations, sounds) are hard-coded
in the executable and differ between regions.  The module records
candidate USA-offset landmarks from community documentation but marks
them as unverified for the GEP build; the analysis stage must locate and
verify them for this exact cartridge.

## Launch prerequisites

* Core: `parallel_n64`
* Runtime: RetroArch `parallel_n64` (auto-install per catalog) or
  RocketLauncher on a Windows node
* Audio on agent Windows tests: 2%
* ROM must be big-endian .z64 with a valid CIC-6102 checksum

## Next step

`analysis`: build a MIPS (R4300i, big-endian) Ghidra project from the boot
segment / whole ROM, locate the model-block and stage-setup asset loaders,
and pin their offsets for the Europe build.  Then implement a small,
actionable probe that reads at least one character model header.
