# Nintendo Switch 2 — decryption and boot investigation

> **Correction 2026-11-11: `.nup` is not NCZ, and its TOC is at 0x80.** Reading the two real containers on the share
> (StarFox, Zelda OoT) showed both are NUP **v1** exactly as [SPIN0ZAi/nup-extractor](https://github.com/SPIN0ZAi/nup-extractor/blob/main/docs/SPEC.md)
> documents: `NUP\x01` + a 0x80-byte superblock, `TOC\x01` at **0x80**, package records, a directory tree of 601 dirs
> and 186,592 files in OoT's case, and raw/Zstandard extents. There is no `NCZ` block layer and no page at 0x90; the
> earlier "TOC at 0x90 / NCZ" reading came from scanning the wrong bytes. The containers are plaintext, so no master
> keys are needed to extract them. gBox now has the reader (`gbox/nup.py`, docs/nup.md), extraction, materialisation
> and model-source extraction; the Switch 2 *emulator* and live-hook work below is unchanged.

The operator's `\\10.89.1.125\QuickSwap2\Emulation\switch2` (mounted at `/mnt/gbox/quickswap2/Emulation/switch2`)
holds two Switch 2 titles, measured 2026-11-05:

| file | size | container |
|---|---|---|
| `Mario Kart World [0400C3F00006E000].nsp` | 21.78 GiB | **standard PFS0** of NCA files (not encrypted at the outer level) |
| `The Legend of Zelda Ocarina of TIme [04004860224DEC000].nup` | 23.30 GiB | **NUP** — the Switch 2 package format, with `TOC` and **`NCZ`**-compressed content |
| `Custom Version of Lichi for OoT.zip` | 1 GiB | a Windows build of the **Lichii** Switch 2 emulator (`lichii.exe`, `eden-cli.exe`, MSVC runtime DLLs) |

## The two containers

### `.nsp` (Mario Kart World)

Still a plain PFS0; its string table names its NCAs directly:

```
a1395cf413a0b2fd6aa36e8096beb8370.nca
922b949ef598363a79cc7e6d58d210bc3.nca
ce72222f37fcdc02f0514148d80b57ab.cnmt.nca
```

The NCAs inside are Switch 2 (title id prefix `04`, keygen 3+). Decrypting them needs the Switch 2 master keys
and title keys. The Spark's `prod.keys` has `key_area_key_application_03..09` but **no `master_key_0X` for keygen
3+**, so the title key cannot be derived yet — the emulator projects say "bring your own keys".

### `.nup` (Zelda: Ocarina of Time / StarFox)

Corrected 2026-11-11 from the real files: NUP **v1**, not a new NCZ packaging. The header walk is exactly the format
documented by [SPIN0ZAi/nup-extractor](https://github.com/SPIN0ZAi/nup-extractor/blob/main/docs/SPEC.md):

```
0x00  "NUP\x01" + 0x80-byte superblock (TOC offset/size/SHA-256, blob offset, file size, package count, UUID)
0x80  "TOC\x01" (package records, directory tree, file records, children array, string pool)
blob  raw and Zstandard file extents (no NCZ layer)
```

Zelda OoT is a single **standalone update** package (601 dirs, 186,592 files, 21.16 MB TOC, `flags=1`); StarFox has a
base and an update (6 dirs, 21 files). Both parse and extract key-free. gBox's reader (`gbox/nup.py`), extraction,
materialisation and model-source hand-off are documented in `docs/nup.md`.

> Historical note (now disproven): an earlier 2026-11-05 walk put `TOC\x01` at 0x90 and found `NCZ` magic inside the
> OoT file, and inferred an NCZ decompressor was required. The `TOC` bytes at 0x90 and the `NCZ` hits were coincidental
> content bytes; the real TOC is at 0x80. No NCZ decompressor is needed for these containers.

## The emulator landscape (from the operator's links)

| project | what it is |
|---|---|
| `zortos293/Lichii` | "VERY experimental Nintendo Switch 2 emulator" |
| `Frizti/Lichii` | another Lichii fork |
| `sylvieistaken/selevet-eglantine` | Switch 2 emulator performance build |
| `TheSneakyBadger/FEFW-Stable-with-60-FPS-Patch` | portable **Windows** build of the **Eden FE "Fortune's Weave"** fork (based on xDarkWindx/Duck912), 60 fps pre-tuned, "bring your own keys, firmware and game" |

All four are **x64 Windows** builds (`.exe`/`.dll`, MSVC runtime). The aarch64 Linux Spark cannot run them, so
booting Switch 2 on the Spark directly is not currently possible — gBox would drive one of these emulators on a
**Windows x64 worker** (the operator's Windows PCs are already gBox workers), exactly like the existing
`preferred_launch_workers` / remote-launch path.

## Progress log (2026-11-11)

* **NUP is plaintext NUP v1, and gBox reads it.** `gbox/nup.py` validates the superblock/TOC, verifies the TOC
  SHA-256, extracts raw and Zstandard extents, materialises a bootable `exefs/` + `romfs/` folder and pulls model
  sources. The share's five listings now come through `gbox.catalog` as Switch 2 rows: Donkey Kong Bananza (extracted
  dump, `040074A01BF12000`), its update, Mario Kart World (NSP), StarFox and Zelda OoT (NUPs). See `docs/nup.md`.
* **Fritchii boots a NUP.** Fritchii v5.8.4 (pinned Windows x64 release) was installed on the i9-NUC; the share's
  `prod.keys`/`title.keys` were copied to its portable `user/keys`. `lichii.exe -g "<OoT.nup>"` started the game from
  the share — window title `Fritchii | v5.8.4 | … | The Legend of Zelda Ocarina of Time (64-bit) | Nvidia`, 2.6 GB
  RAM, loading screen. No extraction step was needed. Evidence: `docs/images/switch2-oot-fritchii.png`.
* **gBox integration.** `Switch2Adapter` routes generation-2 rows to Fritchii/Lichii; NUP launches skip the Switch 1
  "extract first" preflight and the 25–30 GB cache staging. Hookshot is integrated as the native OoT engine: pinned
  setup, `--cli --prepare --game <nup>` job, `--play`, and `HOS_CONTROL`/`HOS_CONTROL_MEM` for its local control
  bridge (guest memory read/write — the eventual live-swap surface). Code `gbox/switch2.py`, docs `docs/switch2.md`.
* **Host reality.** Fritchii and Lichii are Windows x64; Hookshot ships Windows x64 and Linux x86_64. The aarch64 Spark
  cannot execute any of the three releases, so Switch 2 sessions run on a Windows worker (the i9-NUC) and are played
  there or streamed. The Spark keeps the library, NUP extraction and model pipeline.

## Progress log (2026-11-05)

* **Native aarch64 build exists.** Orchid v0.7.5 ships `orchid-v0.7.5-linux-aarch64-pgo.{AppImage,tar.gz}`.
  Extracted to `~/gBox_alt/switch2/`; both `orchid` (Qt6 GUI, needs `libQt6Charts`) and `eden-cli` (the CLI
  gBox will drive) are native aarch64 ELF. `eden-cli` exposes `-g <game>`, `-d <port>` (GDB stub) and
  `--pack-nup` — the same Eden CLI gBox already knows for Switch 1.
* **The Switch 2 keys are the "Ocean" set** (`key_area_key_ocean_00..06`, `key_area_key_application_00..12`)
  and live at `switch2/prodkeys-main/prod.keys` on the share (233 keys). Placed into
  `~/.local/share/eden/keys/prod.keys`. Switch 1 `prod.keys` (even with master_key_03..09) is NOT sufficient.
* **Mario Kart World boots and renders on the Spark.** `eden-cli -g` on a fresh Xvfb (`:92`, `+extension GLX`)
  ran the full 120 s and rendered real frames: 1280x720, >200k distinct colours, full 0-255 range, stddev ~53
  at 20-40 s. The game executes Maxwell 3D GPU commands (constant buffer binds, texture cache at ~3 GiB) with
  Switch 2 (`nx2_stub_device`) GPU ioctls partially stubbed. The title key is derived from the ticket with the
  Ocean keys (no separate title.keys needed for MK World).

## Plan (revised)

1. **Boot (mostly done).** A stable dedicated Xvfb, the Ocean keys, and `eden-cli` boot MK World on the Spark.
   Remaining: verify the Zelda `.nup` also boots, and make the display stable across boots.
2. **gBox integration.** Register `eden-cli` as a `switch2` emulator (like `switch_linux_emulator`, with the
   `-d` GDB stub for the memory hooks), so launches go through gBox's launch/stage/stream plumbing.
3. **Autoplay.** RAM-map a booted Switch 2 game (player/enemies/timer) through the GDB stub, then port the
   MercMode driver pattern.

## Plan (original)

1. **Decrypt/map (offline, on the Spark, tractable now)**
   - `switch_nup.py`: parse the NUP header (magic/version/TOC/title id), enumerate NCZ blocks, and inventory the
     TOC so the structure is mapped before full decryption.
   - extend `catalog.py` (`EXT_PLATFORM[".nup"]`, Switch 2 `04…` title ids) and `switch_nsp.catalog_fields` so the
     `switch2` library scans into the catalog.
   - obtain the Switch 2 master keys (operator's keys), then reuse the existing NCA/PFS0/NCZ machinery to decrypt.
   - implement an NCZ decompressor once the block format is confirmed against the emulator source.
2. **Boot/autoplay (needs a Windows x64 worker + the emulator)**
   - add a `switch2` emulator config that launches Lichii/Eden-FE on a Windows worker remotely, with the same
     launch/staging/stream plumbing gBox already has for Switch 1.
   - reuse the MercMode driver pattern once a game boots: RAM mapping (player/enemies/timer) on the new
     architecture, then the autobot.
