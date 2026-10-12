# Inventory — Sonic 1 and 2 (genesis, game_id 48d757e779e88504)

Request 1345 (0b30e8e87ba14438) — stage 1: inventory. 2026-10-12 run.

## Source identity (owned build)
- Catalog: library `hyperspin`, collection `Sega Genesis Hacks`
- rel_path: `collections/Sega Genesis Hacks/roms/Sonic 1 and 2.zip`
- Absolute (read-only CIFS mount, linux node lilspark):
  `/mnt/gbox/hyperspin/Arcade/collections/Sega Genesis Hacks/roms/Sonic 1 and 2.zip`
- Windows share view: `//10.89.1.125/HyperSpin Attraction/Arcade/collections/Sega Genesis Hacks/roms/Sonic 1 and 2.zip`
- Mount is read-only: originals cannot be mutated by tooling. Pristine copy kept in
  `originals/` of the task workspace.

## Hashes
| artifact | sha256 | other |
|---|---|---|
| Sonic 1 and 2.zip (1,027,444 B) | 49fccb41fef1a8f3faf981625258a0e426f4f153438774f9aebae27eb0a9bf30 | — |
| Sonic 1 and 2.bin (2,097,152 B) | a755e0ae96df4b881f52e347ac450ce2207f8403667e06de5da0ef9fb499d99d | md5 5fb3418f81fd4e922e7d8789eaa4e477, sha1 6651a52a04caeec071b8e469308caa5b5c4cdd2f, crc32 0x8C199C56 |

## Platform verification (label vs. file)
- Catalog says platform `genesis` (platform_confidence: collection), system label
  "Sega Genesis Hacks" (a HyperSpin collection name, not a console).
- ROM header @0x100: console "SEGA GENESIS", "(C)SEGA 1992.SEP",
  domestic/overseas titles "SONIC THE HEDGEHOG 2", serial GM 00001051-01,
  region "JUE". => genuine Genesis/Mega Drive cartridge image, big-endian word
  order (not byteswapped .smd). Platform label CONFIRMED as genesis.
- Base game: Sonic the Hedgehog 2 (rev 02 era header). Size 2 MB = 1 MB Sonic 2
  base expanded to 2 MB by the hack (Sonic 1 levels ported in).
- Header checksum stored 0x80A5; computed word-sum 0x7DAD (mismatch typical of
  un-rechecksummed hacks; genesis_plus_gx does not enforce it — not a blocker).
- No plain-ASCII level-name strings: Sonic text/tilemaps are stored compressed
  (indexed), as expected.

## Launch prerequisites
- Core: genesis_plus_gx via RetroArch (`runtimes.retroarch/genesis_plus_gx: auto-install`)
  on linux (lilspark) and RocketLauncher on the Windows node (JAYBUILTFINALE).
- BIOS: none required for genesis_plus_gx.
- Container layout: zip -> single `Sonic 1 and 2.bin`.

## Character / sprite inventory (format-level, mapping in stage 2)
Roster (Sonic 2 engine + Sonic 1 ported levels; exact object tables TBD in
analysis): Sonic, Tails, Eggman/Robotnik (and mecha), S1+S2 enemy set
(Crabmeat, Buzz Bomber, Coconuts, Chopper, Motobug, Bat Brain, Asteron, Slicer,
Orbinaut, yadrin, Crawl, etc.), zone bosses, monitors, rings, spikes, springs.
Art pipeline (Genesis 2D, not 3D):
- Sprites/tiles: 4bpp planar tile data, 8x8 cells, up to 4 palettes per sprite
  (15 colors + transparency), CRAM 64-color master palette.
- Art storage: Nemesis-compression streams (run-length, terminators 0x00FF/0x00FFxx);
  sprite mapping + DPLC (dynamic pattern load cues) tables drive per-frame tile
  assembly. Mappings are 4bpp-oriented word formats.
- Constraints for replacement: donor art must be re-encoded as Nemesis streams
  or fit existing mapping slot sizes; palettes are per-mapping lines; collision
  boxes are separate from art.

## Workspace layout (request worktree)
- path: /home/ehm_eckx/gbox-hermes-tasks/0b30e8e87ba14438/system
- branch: hermes/request-1345-*
- originals/Sonic 1 and 2.zip  (pristine)
- work/rom/Sonic 1 and 2.bin  (extracted, for probes)
- inventory/source_zip.sha256

## Next step (stage 2: analysis)
Build a Ghidra M68k project for `Sonic 1 and 2.bin` (or reuse Sonic 2 Ghidra
project if compatible — verify addresses against this 2 MB image, they will NOT
match unshifted Sonic 2 since the hack relocated/expanded), locate Nemesis
decompression routine + sprite mapping/DPLC tables, implement a small format
probe that decodes one Nemesis stream to 4bpp tiles and dumps a PNG to prove
the pipeline before writing any re-encoder.
