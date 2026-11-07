# RE4 Switch (HD port): inventoried through the GameCube readers

Measured 2026-11-07 on `~/gBox_alt/switch/romfs/010099A00BC1E000` (title `010099A00BC1E000`, the Mercenaries
edition gBox plays on lilspark).

## The finding that matters

RE4 Switch keeps the GameCube era tree (`bio4/em`, `bio4/st1..st4`, `bio4/ss`, `bio4/etc`) and the **same UDAS/DAT
containers** the GC disc uses. The only difference in the container layer is **endianness**:

| | GameCube / Wii | RE4 Switch (HD port) |
|---|---|---|
| UDAS fill | `0xCAB6BE20` x 8 | identical |
| entry | 32 B: type, size, 0, offset | identical shape, **little-endian** |
| terminator | `0xFFFFFFFF` in the first `0x400` | identical |
| DAT pack | count, tail, 8 pad, u32 offsets, 4-char extensions | identical shape, **little-endian** |
| first DAT at | `0x400` | `0x400`–`0x420` |

So `re4gc_inventory` gained an `endian` parameter (`'>'` default, unchanged for the GC disc; `'<'` for the HD port)
rather than a second reader. Verified on real packs: `em/em10.udas` entry 0 is type 0, size 8,863,840 at `0x420`,
followed by a type-4 sound entry; `em/em06.udas` entry 0 is exactly at `0x400`.

## What the payloads are — and what they are not

The slots inside the DAT use the same vocabulary (`BIN` mesh, `TPL` texture, `FCV`/`SEQ` motion, `EFF` effects), but
the payload layouts are **not** the GameCube ones:

* HD `BIN` starts with header size **`0x98`** (the GC writer knows `0x40` rigid / `0x60` skinned);
* HD `"TPL"` starts with **`0x12345678`** (the GX TPL magic is `0x0020AF30`).

So an HD pack is inventoried **by slot and size**, and its meshes/textures are reported as `decoded: false` with the
header/magic that says why. Nothing is parsed as if it were the GC layout — that is the line between "listed" and
"decoded", and this work only claims the first.

## The inventory (all 162 packs, 326,433,344 B, 0 errors)

```
kinds            enemy/NPC 82, player/partner 27, weapon 53
BIN meshes       2,727   (every one header 0x98)
TPL textures     1,702
motion           FCV/SEQ bytes counted per pack
sound            type-4 UDAS entries counted per pack
```

Largest packs: `em/em10.udas` 8,903,328 B (120 BIN, 75 TPL), `em/ema0.udas` 8,901,984 B (120 BIN), `em/em32.udas`
6,257,216 B (20 BIN). `em10` is the Majini the RE5 Mercenaries round fills with — the RE4 equivalent is the pack the
village spawns, and it is one of the two biggest in the title.

Manifest written on the Spark: `~/gBox_alt/re4-lab/re4switch-inventory.json` (63,998 B).

## Code

* `gbox/re4gc_inventory.py`
  * `udas_entries(data, endian='>')` — both editions; refuses a table that leaves the `0x400` header or the file.
  * `dat_entries(data, endian='>')` — both editions.
  * `pack_summary(drs, decode=False, endian='>')` — reports `edition: gamecube | hd`, and for HD lists slots/sizes
    with `decoded: false` plus the header/magic instead of guessing.
  * `switch_inventory(root, limit=0)` — walks `<romfs>/bio4/em/*.udas` and returns the manifest the GC `inventory()`
    returns in spirit: per pack kind, slots, meshes, textures, motion bytes, sound entries, errors, totals.
  * CLI: `python -m gbox.re4gc_inventory --switch-romfs <romfs> [--limit N] [--out manifest.json]`.

The GC path is untouched (`endian` defaults to `'>'`), and its 34 tests still pass.

## Why this is the right next step for "character replacement on the Switch titles"

The goal needs a per-title pipeline that *decrypts, inventories, views, extracts and replaces*. For RE4 Switch the
first two halves now exist through the same code as the GameCube title, and the third is one decoder away:

1. **decode the HD BIN** (`0x98` header) — then `rig_roles.py` (which derives joint roles from geometry) and
   `re4gc_zombies.py` (which already does the Sonic-as-ganado swap on GC) apply to this title;
2. the HD `TPL` needs its own texture reader before skins/textures can be replaced;
3. the writer must emit little-endian UDAS/DAT, which `udas_write`/`dat_write` can do with the same `endian` thread.

The merge rule that cost rounds on GC still applies here: **pad every replacement to the original slot size**, and do
not rewrite the model's bounding box.

## Reproduce

```
cd ~/gBox/system
python3 -m gbox.re4gc_inventory --switch-romfs ~/gBox_alt/switch/romfs/010099A00BC1E000 \
        --out ~/gBox_alt/re4-lab/re4switch-inventory.json
```

Tests: `system/tests/test_re4gc_inventory_switch.py` (6 cases: LE parse, endianness actually matters, GC path
unchanged, HD payload not guessed, motion slots counted, tree walked / plain directory refused).

## Reached from the app

`GET /api/decrypt-lab/arc-layout?title=re4_switch` now falls through to this inventory: `skin_swap.candidates`
answers "not extracted" for a tree with no `.arc` files, which is wrong for RE4 Switch, so the route also calls
`switch_inventory` and returns `edition`, `container`, `packs`, `pack_count`, `totals`, `bin_header_sizes` and
`payload_note`. The extraction tab therefore lists the 162 packs of an HD title through the same call it uses for the
MTF titles. The `.arc` branch is untouched - the UDAS fall-through only fires when `bio4/em` exists.