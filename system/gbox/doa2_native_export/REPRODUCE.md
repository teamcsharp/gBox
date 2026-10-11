# Native DOA2 costume donor export

Promote this **source-only** directory to `system/gbox/doa2_native_export/`. Keep
module names unchanged. The entry points are `assemble_native(...)` and
`write_complete(...)` in `complete.py`; CLI modules are `generate_cache.py` and
`export.py`. Helpers import siblings through the package. The canonical gBox
dependencies are `doa2_bindings`, `doa2_geometry`, `doa2_textures`, `doa2_rig`,
`gdrom`, and `melee_models`. NumPy is required; pytest is needed for tests.
`doa2_bindings.accessory_filename(...)` must provide the strict native ACS
resolver. An older deployment without that resolver fails with an upgrade
message instead of guessing a costume filename.

Ship `.py`, this document, and `tools/native_cloth_emulate.java` only. Do not
commit an owned executable, CHR/BIN/SUP/ACS, cache, source inventory/profile,
generated GLTF, Ghidra project, `.pyc`, or `__pycache__` directory.

## Reproduce the private cache

Run these commands with the repository's `system` directory on `PYTHONPATH`.
Use an owned DOA2 LE Japan GDI. Its extracted `1ST_READ.BIN` must have SHA-256
`27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1`.

```sh
python -m gbox.doa2_native_export.generate_cache prepare \
  --gdi /private/owned/disc.gdi --cache /private/doa2-native-cache
```

The default profile is reconstructed from the owned SUP orientation graph and
the executable's native rest vectors. `--profiles /private/profiles.json` can
instead provide an existing hash-bound neutral profile map, or the native-slot
profile list used during research. These are candidate neutral coordinates;
native gameplay acceptance is tracked separately.

Preparation writes owned seeds and the extracted executable into the private
cache. Import that exact executable into a private Ghidra project using raw
binary loading, `SuperH4:LE:32:default`, base address `0x8c010000`. Ghidra's
[official headless documentation](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md)
documents the loader/base-address arguments.

```sh
/path/to/ghidra/support/analyzeHeadless /private/ghidra doa2-native \
  -import /private/doa2-native-cache/1ST_READ.BIN \
  -loader BinaryLoader -loader-baseAddr 0x8c010000 \
  -processor SuperH4:LE:32:default -noanalysis

python -m gbox.doa2_native_export.generate_cache run \
  --cache /private/doa2-native-cache \
  --headless /path/to/ghidra/support/analyzeHeadless \
  --project-directory /private/ghidra --project-name doa2-native \
  --program-name 1ST_READ.BIN
```

An existing read-only program containing the exact executable at that address
also works. Keep the Ghidra project path outside hidden directory names such as
`.hermes` or `.cache`: Ghidra rejects those project path elements. A separate
non-hidden symlink to a private project directory also works. The private
cache and owned inputs can remain in those directories. The script verifies
every mapped program byte against the extracted
executable before running. It executes the original cloth initializer,
simulation and writer, not a replacement cloth solver. The only architectural
adapters cover Ghidra SH4 floating-register banking/control and its named
matrix/trigonometric operations. This is not a claim of bit-exact hardware
trigonometry. The independently checked position tolerance is `1e-5`.

`run` invokes Ghidra read-only, saves its output to `native_execution.log`, then
verifies finite cells, aliases, dimensions, hash provenance, bounded vertex
writes and authored actor-root matrices. `verify` can recheck a copied cache:

```sh
python -m gbox.doa2_native_export.generate_cache verify \
  --cache /private/doa2-native-cache
```

Cache application and verification resolve artifact basenames independently of
Windows or Linux path separators. Copy the whole private cache directory to the
new host; absolute paths recorded by the original runner do not control reads.

The verified source has **93 grids across 47 costumes**, including **5,512
position aliases**. The other costumes need no cloth cache record. Native grid
order and cumulative CHR snapshots are preserved. Parent15 root-grid inputs
must resolve to an original authored mode4 controller; no actor pelvis/root is
invented. The generator translates the whole neutral actor to Y+2 in a virtual
studio, retaining the native no-stage floor fallback Y=1.

## Export and verify all owned costumes

```sh
python -m gbox.doa2_native_export.export \
  --gdi /private/owned/disc.gdi --cache /private/doa2-native-cache \
  --output /private/doa2-donor-exports

python -m pytest system/gbox/doa2_native_export/tests -q
```

Optional `--only TNG00 TNG01` restricts the source integration export. Optional
`--profiles` has the same meaning as cache preparation. Each output GLTF is
self-contained and paired with a detailed provenance/result report.
`verification.json` checks source hashes, all 14 donor roles, original render
bindings, shadows excluded, local joint matrices, inverse bind matrices and
distinct native draw instances. Repeated model IDs are not deduplicated.

Enumeration follows the executable's body and accessory filename tables. The
body table declares 80 archives; `BAY02.CHR` is absent from this owned disc, so
79 available archives are exported. The unavailable declaration is recorded in
`native_resource_inventory.json` and the verification summary. Native ACS
bindings are resolved independently of the CHR suffix: in particular,
`JAN02.CHR` uses `JAN_A01.ACS`. Missing required ACS files fail explicitly.

The validated source set contains **79 costume exports**, **653,970 triangles**,
**475,055 vertices**, **320 native accessory draws**, **114 deformed chain
descriptors** and **93 native-generated cloth grids**. Tengu retains its six
wing joints in addition to the 17 source core/eye joints. Original eye joints
15/16 inherit head1 and are not guessed breast/actor-root attachments.

Assembly follows native list order: special attachment frames and held props;
ordered chain writes with immediate draw snapshots; ordered cloth snapshots;
SUP seam writes; primary parts and eyes/wings. Placeholder mesh records that
have no verified draw are not exported as loose geometry. FFFF repeated-model
draws keep their separate snapshots; a model drawn both as cloth and body keeps
both actual draw instances.

## Limits retained in every result

These files are neutral **source donors**, not evidence that a ROM replacement
has passed gameplay. `gameplay_verified` remains false.

- Native cloth is frozen under its authored parent after offline generation.
  Live collision and accessory physics are not bundled as animation clips.
- Ordinary chain directions use original configured gravity/length/carry unless
  the caller supplies native world-chain records. Stage/body collision and nine
  optional dynamic normal arrays are not replayed.
- SUP seam geometry is reconstructed, but its exported two-joint skin weights
  approximate the native curved solver in later arbitrary poses.
- Native projected UV flags require a view-dependent renderer. They retain
  original UV and are reported; the verified 79-source set has no such flags.
- Combat trails/particle emitters retain original metadata in their cleared
  initialized state. No combat history or live effect meshes are fabricated.
- Shared scene props use the separate native model pool at `0x8c23d92c`; their
  ownership/state metadata is recorded. They are not selected costume CHR
  geometry and require external scene assets and context for scene export.

Source and target gameplay acceptance, animated seam/cloth quality and actual
native character replacement are separate tests owned by the swap pipeline.
