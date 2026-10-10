# Dead or Alive 2 — Limited Edition (Japan): native RE findings and the reader slice

Request #1135 (Ghidra decomposition / character import+replace), gap #1140 (missing native Dreamcast
character writer). Platform: Dreamcast GD-ROM, game_id `1de2e7634f3161ff`.

## Provenance (all hashes sha256, source disc read-only)

| artifact | sha256 |
|---|---|
| `Dead or Alive 2 - Limited Edition (Japan).chd` (source, never written) | chd sha1 `75fb157dc9a72ee2a3edd3db57940366de3a5ca3` (staging record) |
| `1ST_READ.BIN` (from CHD via `chdman extractcd`, 1,929,928 B) | `27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1` |
| `doa2le.elf` (wrapper ELF for Ghidra, load 0x8C010000) | `0d5e404e2a97909d0783588f5b5295cee368831e0aa26f362354c69a4649974b` |
| `DOA2/KAS00.CHR` | `63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee` |
| `DOA2/KAS00.BIN` | `49e09538244a8617c1457ed5c81b0b502f51c8392a772e9536630599dfd335d1` |
| `DOA2/KAS00.SUP` | `543fad8818d965826a5b6ee4c945794470058ec6179e60b29a0dc7a51895a987` |
| `DOA2/KASUMI.MOT` | `ed4f2476807cdde2aad940b05b7a7935b55e56704e3dcbfdd425a6e162c586be` |

Ghidra 12.1.4 headless, processor `SuperH4:LE:32:default`, analysis succeeded (118 s). `1ST_READ.BIN`
is **unscrambled** (NOP sled `0x0009` at entry; SH-4 `mov.l` literals resolve) and loads at
**0x8C010000** — consistent with `gbox.re_lab_tool`'s DC_BASE.

## Verified asset layout (this run)

- 960 files on the GD-ROM; character assets under `DOA2/` as per-costume triples
  `<KEY><NN>.BIN` (textures), `<KEY><NN>.CHR` (model+skeleton), `<KEY><NN>.SUP` (physics supplement),
  plus per-character `<NAME>.MOT` (moves).
- Costume families from the disc: KAS×9, AYA/TIN/HIK×7, GEN/LEI×6, ZAC/RYU/KTE/JAN×5,
  BAS/BAY×4, SAM×3, TNG×2, singletons LOR/MAM/PDG/WBA/YTI (variants).
- Filename string tables live at `1ST_READ+0x157424..0x158d00`; pointer tables of those strings at
  `+0x16e740..0x16f400` (e.g. `"kas00.chr"` str @0x1581d4, its pointer @0x16ea7c).
- Loader I/O goes through function-pointer tables: `FUN_8c011ee4` (open/stat/read/close via
  `PTR_FUN_8c012000..8c012020`), same pattern in `FUN_8c0121c0` (references struct @0x8c17f310) and
  `FUN_8c01c35c` (retry loop). 32 code sites reference the shared asset-name table @0x8c17e774.

### CHR container (parser in `gbox/doa2_chars.py::parse_chr`)

Header u32[9] + 3 floats: `[0]=24`, `[1]=object-ptr-array offset`, `[2]=tail offset`, `[3]=n_objects`,
`[4]=n_bones`, `[5]=0 [6]=1 [7]=1 [8]=0`, `+0x24: float×3` (character scale, Kasumi
0.18116/0.01111/0.17960). Object pointers are **absolute SH-4 work-RAM addresses** — fighters
(KAS/AYA/GEN/…) base `0x0C300000`, system CHR (EFC0/FIX) base `0x0C400000`; file offset = ptr − base.
Tail = `n_bones × {float3}` (all-zero for Kasumi; likely bind offsets/scale used elsewhere).
Verified counts: Kasumi 56 objects/55 bones, Ayane 48/45, Gen Fu 52/52, EFC0 122/75, FIX 93/2.

### SUP / MOT

SUP: u32 offset table (Kasumi: 10 records, first at +44) then float records (soft-body/physics).
MOT: u32 offset table — Kasumi lists 1004 clip offsets with repeats (shared clips), first clip at
+0x1898.

## What this run shipped

`gbox/doa2_chars.py`: read-only readers `parse_chr`, `parse_sup`, `parse_mot_table`, disc-driven
`roster()` (19 entries with costume lists) and `export()` producing a UAP-shaped manifest with
verified container+skeleton facts and per-dimension confidence (geometry honestly `missing`).
Routed as dedicated extractor `doa2` in `gbox/characters.py` DEDICATED (Dead or Alive 2, dreamcast).
Tests: `tests/test_doa2_chars.py` — 10 passed (synthetic fixtures anchored to the real KAS00.CHR
header words).

## Not yet done (next slice, in order)

1. CHR mesh objects: decode vertex/strip data (object bodies begin with 4×floats then counts —
   obj1 of KAS00 has `{0x2ee, 1, 1, 750…}`-style fields); produce real glTF geometry.
2. Texture decode for `<KEY><NN>.BIN` (no PVR GBIX/PVRT headers found — custom twiddled layout).
3. The writer: rebuilt CHR must keep **absolute pointers exact** (base+file-offset layout) and stay
   within each costume's sector budget (`gbox.gdrom.patch_gdi` in-place file mod).
4. Bone-role map (55 Kasumi bones → library roles) for retargeting; MOT clip decode.
5. Emulator verification on the Spark (Flycast/retroarch) — required before #1140 can close.
