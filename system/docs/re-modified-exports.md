# Resident Evil modified export work

The operator's requested result for **both** games is a randomly selected
Sonic/Mario cast, every available character/content category unlocked before
play, and on-screen inventory/equipment controls. An unchanged export, preview
model, or partial unlock routine does not satisfy that result.

## Exact targets and current native engineering tools

| Target | Identity | Implemented engineering scope | Remaining product work |
| --- | --- | --- | --- |
| RE2 GameCube | `c6adbfa00c20aaf9`, `GHAE08` | `gbox.re2gc_native`: validates 40 owned player PLDs, animations, skeletons, indexed textures and mesh indices; byte-exact no-op; hash-guarded vertex/complete mesh writer | Donor retargeting, EMD enemy geometry, collection/cast writer routing, unlocks, live inventory/equip, complete disc and gameplay proof |
| RE5 Gold PS3 USA v02.00 | `e7ca89bbeb67360d`, `BLUS30491` | `gbox.re5ps3_arc`: big-endian ARC v8 reader/writer; all 151 resources of Chris/Sheva normal packs decoded; unchanged members preserved and replacement readback checked | PS3 MOD/TEX conversion, rigged donor retargeting, collection/cast routing, complete unlock categories, live inventory/equip, complete folder-game export and gameplay proof |

Neither module is registered as a complete `char_coverage.WRITERS` capability.
Their tests prove native format operations, not a playable Sonic/Mario cast.
`native_engineering.plan(game_id)` and `.prompt()` include these exact-port
instructions so Hermes and SparkDeux do not repeat the wrong-port investigation.

## RE2 source and commands

The source is a GCZ and `GCDisc` reads it directly. Do not report "missing ISO"
when the catalog resolves to a readable GCZ. On the control plane the owned
source is under the configured HyperSpin library:
`collections/Nintendo GameCube/roms/Resident Evil 2 (USA).gcz`.

```sh
python -m gbox.re2gc_native "$OWNED_GCZ" --out new-inventory.json
```

This reads and validates every PLD and requires the known executable identity:
`main.dol`, 800672 bytes,
SHA256 `71401bd622ab5a09e40d5cd6feb07f3725d7a24356fb0cf133e3991c941e2a05`.
The disc has 1824 files: 40 PLD, 181 PLW and 116 EMD files. Only the PLD set is
claimed by this reader. N64 `46eec2fc627c8f58` and PSX `2d8ef2bdbd4a58fd` are
different ports; their addresses and acceptance receipts do not apply.

For an isolated native edit, extract the exact PLD with `GCDisc.read(member)`.
Supply an explicit edit recipe and its source hash:

```json
[{"object":0,"group":"triangles","vertex":0,"xyz":[100,200,-300]}]
```

```sh
python -m gbox.re2gc_native source.pld --edit-json edits.json \
  --expected-sha256 "$SOURCE_SHA256" --out new-model.pld
```

This is an engineering probe, **not** a Sonic/Mario conversion. It creates a new
file exclusively, preserves the source, and reports readback separately from
gameplay. `Model.replace_mesh(objects, expected_sha256=..., texture=...)` accepts
complete local-space primitive groups in the reader's schema, preserves all
native object/rig slots and animation bytes, and enforces original MD1/TIM
allocations. A retargeter must fit donor geometry into the actual target joint
spaces and prove the result. No larger loader budget has been inferred.

MD1 offsets start after its 12-byte header. This matches the
[OpenBiohazard2 MD1 reader](https://github.com/OpenBiohazard2/OpenBiohazard2/blob/master/fileio/md1.go)
and the owned GameCube bytes. The PLD section directory is at the end of the
file; it must not be included in the TIM payload. Unknown bytes and aliases are
preserved on a no-op or direct vertex edit.

## RE5 source and commands

List the catalog's owned 7z first. Extract the exact `PS3_GAME/PARAM.SFO`,
`PS3_GAME/USRDIR/EBOOT.BIN`, and required
`nativePS3/Image/Archive/*.arc` members into an isolated directory. The source
archive contains 1201 ARC files; a listing is not full geometry coverage.

```sh
python -m gbox.re5ps3_arc uPl00ChrisNormal.arc --out new-chris-inventory.json
python -m gbox.re5ps3_arc original.arc --member 'pawn\pl\pl00\model\pl00' \
  --type-hash 58a15856 --replace validated-model.bin \
  --expected-sha256 "$SOURCE_SHA256" --out new-character.arc
```

Use the **exact** member name/type from the inventory; identical names with
different resource types are distinct. Header counts for a MOD are explicitly
not a geometry reader. Replacement resources must already be semantically
validated. Unknown flags/name padding and unrelated compressed payloads stay
unchanged. A larger replacement is appended and only its own table entry is
redirected. Full game loading must still be tested.

Owned sample identities:

| File | SHA256 |
| --- | --- |
| PARAM.SFO | `c736989af229f1696e676af2f1aafc3716e0f254e3b544decb23cfec4b3b30aa` |
| EBOOT.BIN (SELF, not decrypted ELF) | `a0c06e58f8c590ee27ab0fee90d97de5973623a8e38f5f67f626719a590bbb2c` |
| uPl00ChrisNormal.arc | `51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867` |
| uPl01ShebaNormal.arc | `27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f` |

ARC v8 has an 8-byte big-endian header and 80-byte records. Decoded size is
`size_word >> 3`, preserving low-three-bit flags. Payloads are stored when the
two sizes match, otherwise zlib; retail samples use a 16 KiB window. Do not use
the RE6/Xbox 360 LZX codec, 3DS ARC header, or Xbox texture tiling.

## Unlock and sidebar acceptance

The existing `re5` save tool implements seven categories but has
`live_checked=false`; its coverage explicitly leaves Mercenaries characters and
stages unconfirmed. Code existence is not evidence that a save is unlocked.
Neither target currently has a verified `game_unlocks.profile_for` entry or a
`re_inventory` backend. Do not register either until the exact owned build has
verified routines and a rollback path.

1. Reuse hash-identified Ghidra/REA projects for the **correct executable**.
   Identify initialization, menu eligibility, progress flags, item lists and
   equip routines. Keep decompilation out of the Play path.
2. Enumerate every content category, including hidden modes, characters,
   costumes, stages, items and extras. Mark unknowns explicitly. Trace and test
   the fields/routines rather than copying another port's addresses.
3. Use isolated save overlays or backed-up monotonic edits. Verify native
   checksums, exact code bytes and readback. Preserve player settings/mods.
4. Register an exact-revision inventory backend with read/give/remove/set/equip
   operations and item IDs. Route sidebar writes to the running session's
   worker; do not send them to another computer. Non-weapon items need their
   native use semantics, not guessed equip pointers.
5. Persist a random seed and exact Sonic/Mario donor-to-target mapping. Include
   every cast slot the operator requested; report missing enemy/cutscene slots
   explicitly instead of claiming a player-only replacement is the full cast.
6. Build and read back the complete modified game, preserving source files.
   Package required save/unlock sidecars with explicit startup behavior. A
   runtime sidebar is a gBox feature, not something embedded in an ISO.
7. On an idle authorized test worker, verify a fresh boot, each discovered
   character/mode, the visible native cast, movement/animations, inventory and
   equip changes, a second launch, and rollback. Preserve operator games.

Relevant requests: RE2 cast #2339 / unlock #2037; RE5 cast #1885 / unlock #2041.
Keep full requests open until their product/runtime criteria pass. The bounded
inventory children #2323/#2327 can close with an honest inventory and explicit
unknowns; they do not require inventing missing unlock evidence.

## Focused verification

```sh
GBOX_RE2GC_SOURCE="$OWNED_GCZ" GBOX_RE5PS3_ARCS="$EXTRACTED_ARC_DIRECTORY" \
  python -m pytest tests/test_re2gc_native.py tests/test_re5ps3_arc.py \
  tests/test_native_engineering.py tests/test_re2psx_inventory.py -q
```

Owned bytes remain local. The tests include malformed extents, decompression
limits, aliases, exact source guards, changed geometry/resources, unrelated-byte
preservation and source immutability. They do not launch games.
