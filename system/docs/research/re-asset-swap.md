# RE asset replacement: the mine / grenade / skin slots (measured 2026-11-05)

Measured on the extracted RE5 Switch RomFS (`gbox_alt/switch/romfs/010018100CD46000`). MT Framework `.arc`
archives store their entry names as ASCII, so the slots are identifiable without a decoder.

## The slots

| slot | RomFS path | entries inside |
|---|---|---|
| bomb / mine 1 | `nativeNXx64/ImgNX/Archive/uWp06.arc` | `pawn\wp\wp06\model\wep06_00_BM`, `sound\se\wp\oto\wp06\wp06_bomb_near` |
| bomb / mine 2 | `uWp07.arc` | `pawn\wp\wp07\model\wep06_01_BM` |
| mine (object) | `uWp0a.arc` | `pawn\wp\wp0a\model\om4e00_BM`, `sound\se\wp\oto\wp0a\wp0a_bomb_near` |
| Chris | `uPl00Chris{Normal,Plain,Ep1,ArmorA,ArmorB,ArmorF,Cos1..Cos4}.arc` | `pawn\pl\pl00\model\...`, `sound\se\pl\oto\pl00\...` |
| Sheva | `uPl01Sheba{...}.arc` | `pawn\pl\pl01\model\evf0100_01_BM` |
| Jill | `uPl02Jill{...}.arc` | `pawn\pl\pl02\model\evf0210_01_BM` |

Each `uWpXX.arc` also carries `pawn\wp\wpXX\motion\wpXX` (animation) and its `sound\se\wp\...` effects, so a slot
is model + motion + sound together.

## The swap primitive (built, verified)

`POST /api/decrypt-lab/swap {title, from_path, to_path, build}` writes asset B's bytes over asset A's RomFS path
in a LayeredFS overlay (`gbox-cache/mods/<title>/<build>/romfs/<path>` + `.gbox-mod.json`), so the game keeps
asking for the slot it expects. Verified on RE5: `wp42_bomb_near <- wp42_bomb_far_x12` -> 200, 39,544 B, bytes
identical to the source; traversal -> 400, missing asset -> 404. This is the correct mechanism for whole-file
assets (textures, `.adpcm` sounds, and any file the game addresses by path).

## The constraint that decides the next build

A whole-`.arc` swap does **not** work for models: the game looks up `pawn\pl\pl00\model\...` inside the file it
loads for slot pl00, so a file containing `pl02` entries fails the lookup. Closing this needs either

1. **arc repacking** - keep the destination slot's entry table/names and rewrite the model entries' data with the
   source character's data, or
2. **RAM-level model id reassignment** at runtime, which is what a live skin swap ultimately wants.

## Arc repacking (built, verified)

`gbox/mt_arc.py` reads and rebuilds the format. Measured layout (version 7, four archives, entry data at 0x8000,
entries contiguous, last entry's end == file size):

```
0x00 "ARC\0"   0x04 u16 version   0x06 u16 entry count
0x08 count * 0x50 records: +0x00 name (64 B, NUL-terminated)  +0x40 u32 hash (constant 0x241f5deb)
                           +0x44 u32 size  +0x48 u32 tag  +0x4C u32 offset
data area at the next 0x8000 boundary; payloads are zlib streams
```

`POST /api/decrypt-lab/arc-swap {title, arc_path, entry, donor_arc, donor_entry, build}` patches one entry inside
the destination arc and stages the rebuilt archive through LayeredFS.

Verified: `uWp06.arc` entry `pawn\wp\wp06\model\wep06_00_BM` replaced with `uWp0a.arc`'s
`pawn\wp\wp0a\model\om4e00_BM` (21,022 B) -> HTTP 200, rebuilt file 563,617 B, re-parsed as version 7 with all 25
entries, the slot keeping its name and holding the donor payload (zlib `78 9c` head); every untouched entry stayed
byte-identical. The same call with a character donor is the skin swap; with an enemy donor it is the zombie swap.

## `_BM` / `_MM` / `_NM` are textures, which makes these swaps safe

The entry payload is a zlib stream; decompressed, the donor begins `54 45 58 00` — **`TEX\0`**, the texture format
(each entry inflates cleanly: 21,022 -> 24,116 bytes). So `wep06_00_BM` is the base map, `_MM` the mask map and
`_NM` the normal map of that slot, and the mesh lives in a separate entry.

That is good news for the operator's asks: swapping a `_BM` entry is a **reskin/retexture** of an object, and every
TEX payload has the same container, so there is no skeleton- or vertex-count compatibility problem — a mine can
wear another object's texture, a character's clothing can be retextured, and a character's base map can be
replaced with another character's. A *mesh* swap (entry without the map suffix) is the riskier one and needs
compatible skeletons.


