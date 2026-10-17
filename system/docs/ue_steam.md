# ue_steam: Unreal Engine Steam games (paks, actor + animation inventory, GLB export)

Ticket #96: "Ghidra able to decompile and gather the actor data and animation data of Steam games". `ue_steam` is a
registry tool (Windows worker, where the Steam library is), offered to the in-app agent (`agent.ue_steam`), Hermes and
MCP (`job_ue_steam`). Modules: `gbox/ue_steam.py` (ops, safety), `gbox/ue_pak.py` (pak reader), `gbox/ue_asset.py`
(package headers), `gbox/ue_mesh.py` (SkeletalMesh -> GLB).

## Safety rules (unchanged, now enforced before any archive is opened)

- Never launches, attaches to or injects into the game. Everything is static file reading.
- Refuses any game with anti-cheat indicators (BattlEye, EasyAntiCheat, XignCode, ...) or a running game process.
  The scan walks file *and folder* names to depth 4 (skipping Content trees), so `<Game>/Binaries/Win64/BattlEye`
  is caught. PUBG (578080) is installed on the PC and is refused for exactly that folder.
- The install is read-only: paks are opened `rb`; extracted files go to a work dir (default
  `<data_dir>/ue_steam/<appid>`), and a work dir inside the install is refused.
- AES-encrypted paks are reported as "needs the game's AES key" and the tool stops. gBox holds and guesses no keys.
- Oodle: only an `oo2core_*_win64.dll` the game itself ships (next to the shipping exe or under
  `Engine/Binaries/ThirdParty/Oodle`) is loaded, with ctypes, and only from inside the game folder.

## Ops

| op | input | result |
|---|---|---|
| status | appid | engine version, anti-cheat check, pak count (no hashing) |
| analyze | appid | Ghidra symbol inference for movement/animation classes (from #171) |
| pak_index | appid | pak files with sizes |
| list_files | appid, paths, max_files | merged pak entries (patch `_P` paks override), size / compression / encryption |
| inventory | appid, paths, max_packages | `inventory.json` manifest (artifact `ue_inventory.json`) + counts and samples |
| extract (alias extract_assets) | appid, paths (required), extensions, max_files | raw files under `<work>/files/<in-pak path>` |
| export | appid, paths, max_files | `<work>/glb/<Mesh>.glb` (+ `.json` report) per SkeletalMesh, `<Skeleton>.skeleton.json` per Skeleton |

`paths` are globs or substrings of the in-pak path (`Game/Content/Characters/*`, `SK_Mannequin`). `engine="4.27"`
overrides the detected engine (needed only when the launcher exe has no release string; the pak version then gives a
guess, flagged as such).

Engine detection order: `Engine/Build/Build.version`, then the launcher exe in the game root
(`UE4+Release-4.27` UTF-16 string + VS_FIXEDFILEINFO patch), then the largest exe, then the pak version.

### Inventory manifest (`gbox.ue_inventory/1`)

`assets` groups exports by kind, each row with package path, export name, class, serial size, `.uexp` / `.ubulk`
sizes and `uses` (assets the package imports):

- `skeletal_mesh` (SkeletalMesh), `skeleton` (Skeleton), `physics_asset`
- `animation` (AnimSequence, AnimMontage, AnimComposite, BlendSpace(1D), AimOffsetBlendSpace(1D), PoseAsset,
  AnimStreamable) with the Skeleton they target
- `anim_blueprint` (AnimBlueprintGeneratedClass) with its native/BP parent
- `blueprint_class` (BlueprintGeneratedClass) with super class

`actors` lists blueprint classes whose super chain reaches Character / Pawn (or a native `*Character` / `*Pawn` class:
`pawn`) or that reference a SkeletalMesh / AnimBlueprint (`skeletal_actor`), with the meshes and anim blueprints they
use. That is the actor -> mesh -> skeleton -> animation map the ticket asked for.

## What works, per version

| archive / asset | status |
|---|---|
| pak v1-v7 (UE 4.0-4.21), legacy index | list + read (stored, zlib, gzip) |
| pak v8 (4.22 one-byte method index, 4.23-4.24 four-byte) | list + read; footer size tells them apart (189 vs 221 bytes) |
| pak v9 (4.25) | list + read; a *frozen* index (bIndexIsFrozen) is reported unsupported |
| pak v10/v11 (4.25-4.27, UE5 paks) | primary index, bit-packed encoded entries, non-encoded entry list, full directory index; without a full directory index entries are listed by path hash |
| AES-encrypted index | stops: key needed |
| AES-encrypted entries (e.g. only .uasset headers encrypted) | listed, counted as `packages_encrypted`, not read |
| Oodle | game's own oo2core DLL only; UE 4.27+/UE5 games link Oodle statically -> unsupported (reported per entry) |
| LZ4 | only if the `lz4` Python package is installed |
| IoStore .utoc/.ucas | containers listed (entries, flags, compression, encryption); zen package reading is the next stage |
| package headers (summary, names, imports, exports) | UE4 (all object versions) and UE5 legacy packages up to object version 1013; unversioned packages use the engine's object version |
| SkeletalMesh -> GLB | UE 4.24-4.27, tagged properties: LOD0 positions, normals, UV0, indices, up to 8 influences (strongest 4 kept in the GLB, renormalised), reference skeleton as glTF joints with inverse bind matrices; LOD0 inline or streamed (.ubulk / end of package) |
| Skeleton | reference skeleton (names, parents, local transforms) as JSON |

Export blockers, reported per asset in `blockers`:

- UE 4.0-4.18: cooked mesh data predates SplitModelAndRenderData (FStaticLODModel with chunks).
- UE 4.19-4.23: cooked LOD layout predates inlined/streamed LODs (SerializeRenderItem_Legacy).
- `PKG_UnversionedProperties` packages (opt-in 4.26+ cook, default in UE5): the property stream needs the engine's
  class schema, so the start of the native mesh data cannot be located.
- UE5 meshes (double-precision transforms, new section fields) and IoStore packages.
- AnimSequence track data (compressed curves, ACL / per-track codecs) is inventoried and extracted raw, not decoded.

Coordinates: Unreal (left-handed, Z-up, centimetres) -> glTF (right-handed, Y-up, metres) with
`(x, y, z) -> (x, z, y) * 0.01`; triangle order is kept (the mirror flips the winding to glTF's counter-clockwise).

## Live check on this PC (2026-10-13, read-only)

| game (appid) | engine / pak | result |
|---|---|---|
| Deadlink (1676130) | 4.27.2, v11, stored | 18,581 packages, 0 failures: 143 SkeletalMesh, 68 Skeleton, 1,587 animations, 57 AnimBlueprints, 90 pawn blueprints; all 143 meshes and 68 skeletons parse; SK_Mannequin GLB: 23,297 vertices, 68 joints, 1.83 m tall, normals agree with winding |
| Redemption Reapers (2139300) | 4.27.2, v11, zlib | 55/55 meshes and 55 skeletons parse (8-influence meshes included) |
| Danger Zone (604740) | pak v4 (guess 4.19), zlib | inventory works; export reports the 4.19 blocker |
| Nigate Tale (1048350) | 4.27.2, v11 | index readable but every .uasset entry is AES-encrypted: key needed |
| Crab Champions (774801) | 4.27.2, v11, Oodle | no oo2core DLL shipped (static Oodle): reported unsupported |
| Ghostrunner, Bright Memory Infinite | encrypted index | key needed, stops |
| PUBG (578080) | 4.16 | refused: TslGame/Binaries/Win64/BattlEye |

Tests: `tests/test_ue_pak.py`, `tests/test_ue_mesh.py`, `tests/test_ue_steam.py` build every pak layout, packages
and a skinned mesh in memory (`tests/ue_synth.py`); no game data is committed.

Format references: Unreal Engine source layouts (IPlatformFilePak.h, PackageFileSummary.cpp, SkeletalMesh render
data) cross-checked against the open-source CUE4Parse reader (Apache-2.0); no code was copied.
