# NUP containers (Switch 1/2) in gBox

`.nup` is the clean-room container the operator's Switch dumps use: plaintext, key-free, holding a base game, its
updates and its add-ons in one file (`exefs/`, `romfs/`, `data/` trees per package). gBox reads it natively:

* **Reference** — [SPIN0ZAi/nup-extractor](https://github.com/SPIN0ZAi/nup-extractor) (MIT): its `docs/SPEC.md` is the
  format authority, and its `legacy_python/nup/` reader is the behaviour this port follows. The Windows GUI `.exe` is
  not used: it has no job-level CLI (only hidden `--extract-here`/`--extract-to-folder` flags that unpack every package
  at once, with no metadata, selection or progress), and it cannot run on the Linux Spark.
* **gBox code** — `system/gbox/nup.py` (reader, extractor, verifier, materialiser), `system/gbox/nup_models.py` (model
  sources), `system/gbox/switch_nup.py` (catalog identity, launchability, RomFS registry).
* **Tests** — `system/tests/test_nup.py` against `system/tests/fixtures/sample_game.nup` (the reference project's own
  sample: 2 packages, 9 directories, 5 files, raw + Zstandard extents).

## Format in one screen

```
0x00  Superblock 0x80 B: "NUP\x01", header size/version, TOC offset/size/SHA-256, blob offset, file size,
        package count, flags, UUID (zero reserved)
0x80  TOC: "TOC\x01", counts, string pool offset/size, then package records (0x40), directory records (0x18),
        file records (0x50), the children uint32 array, and the UTF-8 string pool
blob  File extents, each 16-byte aligned: codec 0 = raw, codec 1 = one Zstandard frame
```

* A package is `base` (0), `update` (1) or `addon` (2/3); updates without a base in the container set
  `standalone_update` (flags bit 0).
* A directory's children are node ids: `< dir_count` is a directory, `>= dir_count` indexes files. Producers sort them
  bytewise; readers resolve paths through the records (gBox additionally accepts a case-insensitive `--subtree`).
* Per-package metadata TLVs (SPEC §5): NPDM, NACP, icon, display version, title name, publisher, build ID (ModuleId),
  source dump name, localized titles/icons.
* Conformance: verify the TOC SHA-256 before trusting anything in it, bounds-check every offset, reject unknown
  codecs/flags/kinds, and never treat a container name as a path.

## Using it

```powershell
# metadata, file list, integrity, extraction
python -m gbox.nup info        "D:\switch\Game [0400....].nup"
python -m gbox.nup list        "D:\switch\Game [0400....].nup" --limit 20
python -m gbox.nup extract     "D:\switch\Game [0400....].nup" D:\out --mode subtree --subtree exefs
python -m gbox.nup verify      "D:\switch\Game [0400....].nup" --deep
python -m gbox.nup materialize "D:\switch\Game [0400....].nup" "D:\switch\Game [0400....]"
```

`materialize` is the playable form: the base package with every update overlaid by path (SPEC Appendix A), `exefs/`
and `romfs/` at the folder root, plus `.gbox-nup.json` (title id, name, version, build id, packages, sizes). Eden's
`AppLoader_DeconstructedRomDirectory` boots that folder through the normal Switch adapter; add-ons are not overlaid
(an emulator registers DLC as separate content) and are reported.

### Library behaviour

`gbox.catalog.scan`:

* A `.nup` row carries the container's own identity — title id, title name, publisher, display version, package kind,
  generation (Switch 2 = title id `04…`) — with `launch.nup_extract_required = true`. Pressing Play on it is refused
  with the one action that fixes it, instead of handing Eden a 25 GB archive it cannot open.
* A materialised folder is one library game of its own (`format = nup_folder`, `platform_confidence = manifest`), not
  186,000 RomFS files: the scanner reads its marker, sizes it from the materialise record, and does not descend into
  it. `switch_nsp.title_id`/`launchable` and `switch_mods.title_id_for` read the marker too.
* The Extract action records the folder's RomFS in `switch-nup-romfs.json` under the node's runtime, which
  `switch_mods.base_romfs` uses as the base for LayeredFS builds (Eden's own Dump RomFS still wins when both exist).

### The `switch_nup` job

`POST /api/jobs {"tool": "switch_nup", "input": {...}}` (also exposed through MCP as any registry tool):

| op | input | result |
|---|---|---|
| `info` | `nup`, `full` | superblock/TOC identity, packages, metadata, icon hash/mime (the CLI's `--icon` adds base64) |
| `list` | `nup`, `package`, `pattern`, `limit`, `offset` | one package's file rows (path, size, codec, SHA-256) |
| `extract` | `nup`, `out`, `mode` (`all`/`package`/`subtree`), `package`, `subtree`, `overwrite` | files, bytes, renamed components |
| `materialize` | `nup`, `out` | bootable folder + marker + registered RomFS |
| `verify` | `nup`, `deep` | structural problems (sorted children, reachable tree, orphans) and, with `deep`, every file hash |
| `models` | `nup` or a materialised folder, `out`, `package`, `subtree`, `pattern` | model containers/files under `<out>/models_src` with a manifest |

Extraction streams each file, hashes it while writing, compares the container's SHA-256, and only then renames it into
place (`.gbox-part` otherwise). Paths are validated per component and must stay under the destination; Windows-invalid
characters are replaced and listed in `renamed` (Linux keeps the exact RomFS spelling).

## Models: from a NUP into the pipeline

The RE titles do not ship loose meshes, so `models` does the container step and reports the conversion step:

1. It selects every model-bearing container and loose model file under the package's `romfs/`:
   `re_chunk_000.pak*`, `*.pak`, `*.arc`, `*.pkg`, `*.cpk`, `*.bundle`, `*.assets`, `*.fpk`, `*.big`, `*.bnd`, `*.sarc`,
   and `.mesh*`/`.mod`/`.mrl`/`.mdl`/`.glb`/`.gltf`/`.fbx`/`.obj`/… files.
2. It extracts them to `<game dir>/models_src/` (paths preserved) and writes `models_src/manifest.json`:
   per-file rel path, size, content SHA-256 (the TOC's own hash), codec, magic (`KPKA` = RE Engine PAK, `ARC\0` = MT
   Framework, …), and for each container the reader that takes it next plus what that reader needs.
3. It lists the hand-off: RE Engine PAK → `gbox.re4r` (`ree-pak-cli` unpack + RE Mesh Editor in Blender); MT Framework
   ARC → `gbox.mt_arc`/`gbox.mt_model` (`gbox.re4_switch_models`, `model_swap`); an exported GLB →
   `characters op=add path=<glb>`, which registers a collection donor usable by model replacement and by other games.

For RE4 Remake on Switch 2 the remaining work is title-specific and deliberately not guessed: the PAK list for that
build, whether `ree-pak-cli` reads it, the Switch 2 mesh/tex extensions the RE Mesh Editor must accept, and then the
emulator/runtime hooks. `models` produces the extracted containers and the exact hand-off so that work starts from
real files, not assumptions.

### Live swaps

RE4/RE5/RE6's live model swaps come from the running title's memory and hooks (`gbox.mercs.titles.re*_switch*`,
`re4r`'s REFramework bridge for the PC remake). A Switch 2 title adds one layer before that: a running emulator that
gBox can drive and read (Lichii/Eden-FE/Orchid on a Windows x64 worker, or Orchid/eden-cli natively on the Spark), then
the same kind of RAM map/hook work. The NUP side above is what gives that work the decrypted ExeFS/RomFS, the build id
and the model containers it needs; the hook parity itself is the follow-up, not something a container reader can claim.

## Real containers measured (2026-11-11, read-only over SMB)

| file | size | result |
|---|---|---|
| `StarFox [0400E88025B1A000].nup` | 30,154,859,302 B | NUP v1, 2 packages (base + update 0x20000), 6 dirs, 21 files; TOC SHA OK; full parse 0.06 s; `exefs` extracted (8 files, 137,985,547 B, all hashes OK, 20 s cold over SMB) |
| `The Legend of Zelda Ocarina of TIme [04004860224DEC000].nup` | 25,020,741,061 B | NUP v1, 1 standalone update (`flags=1`), 601 dirs, 186,592 files, 21.16 MB TOC; light metadata 1.25 s, full parse 0.84 s, structural verify 0.34 s |

Both are Switch 2 title ids (`04…`). Their content is raw/Zstandard; there is no `NCZ` layer (see the correction in
`docs/research/switch2.md`).

## Limits

* NUP v1 only (major version 1). Header fields beyond 0x80 are ignored as the spec allows; unknown codec ids, flags
  and kinds are rejected rather than misread.
* No key handling anywhere: NUP content is plaintext by definition. A `.nsp`/`.xci` still goes through
  `gbox.switch_extract`/`switch_decrypt` and `prod.keys`.
* Play requires an emulator that boots a deconstructed directory; on the Spark that is Eden/Citron today for Switch 1.
  Switch 2 emulation is separate (see `docs/research/switch2.md`).
* Model conversion depends on the title's own formats; `models` reports the hand-off rather than pretending a PAK was
  converted.
