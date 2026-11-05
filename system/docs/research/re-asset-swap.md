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
   source character's data (an MT Framework `.arc` writer: `ARC\0` magic, version, entry table, payloads), or
2. **RAM-level model id reassignment** at runtime, which is what a live skin swap ultimately wants.

(1) is bounded and reusable for mines, grenades and skins; (2) belongs with the MercMode RAM map.
