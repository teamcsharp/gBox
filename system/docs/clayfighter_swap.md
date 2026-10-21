# Clay Fighter: Sculptor's Cut (USA, N64): fighter sprite writer

`gbox/clayfighter_swap.py` (request #588) re-draws every sprite frame of one fighter with a donor from the
collection, then writes a patched copy of the ROM (header CRC recomputed) as a file mod. It also reads every fighter's
frames, so `characters op=collect` can rip all 16 fighters into the collection as `sprites` entries. Each ripped
fighter can then be the donor for any other fighter.

| | |
|---|---|
| Game | `f87ec3e2f6b266a1`, No-Intro "Clay Fighter - Sculptor's Cut (USA)", sha1 `28697FBA…8022`, CIC-6102 |
| Slots | `fighter:<name>[:flip]`: bmf, blob, bonker, booger, kiln, ewj, highfive, houngan, icky, kungpow, liberty, lockjaw, sumo, taffy, thoppy, zappa. `player` means Bad Mr. Frosty, the default player-1 cursor. `:flip` mirrors the donor. Hobo Cop (`CHAR_HOBO`) is a `nullchar` stub in this build and can't be a target |
| Donors | Any `sprites` entry: sprite_capture clips (`meta.animations[]`, `sheet.json` `frames[].sheet`), an atlas index (MVC2 `sprites[].atlas_x/atlas_y/w/h`), this module's `<slug>_sheet.json`, or a bare sheet (Tetris DS), which is split into connected opaque regions. A 3D entry falls back to its `preview.png` (background keyed out) as one static pose |
| Mod | `cache/mods/f87ec3e2f6b266a1/cfsc_<donor>_as_<fighter>/`, with the `.z64`, `frames_preview.png` (the first 36 frames as the game will draw them) and `.gbox-mod.json` (holds the writer's report) |
| Routing | `characters op=use` (`gid in clayfighter_swap.GAME_IDS` and slot `player` or `fighter:*`), `char_coverage.WRITERS`, `characters.DEDICATED["clayfighter"]` (collect / extract) |

## Format (all from the owned build)

Confidence: **high** for everything below. The frame decoder was transcribed from the game's own code (RAM
0x80005870, CHARFRAM.C). Applied to all 3,183 frames of the 16 fighters, every bit stream ends inside its frame's
stored size (rounded up to even) and every alpha record ends where the next record starts. Our encoder reproduces 144
of Bad Mr. Frosty's 185 original bit streams byte for byte; the rest differ only in tie-breaks between equal-cost
modes. Our RLE8 packer re-packs the original CharDef 117 bytes smaller, and it unpacks identically.

* **Fighter table**: ROM `0x0AB260` holds 17 u32 blob offsets (`CHAR_ROM_START`) and `0x0AB2A4` holds 17 blob ends,
  in `clayfighter_sc.ROSTER` index order. At boot (RAM 0x80004780) every blob whose first 8 bytes read `nullchar` is
  re-pointed at the first real fighter and flagged as absent.
* **Blob header** (16 u32, loader RAM 0x80003F40): `h0 = 0x0446<<16 | frames` (CharDef v4.70), `h1 = 0x40`,
  `h2` frame table, `h3` palette count, `h4` palettes, `h5` palette end, `h6` sound bank ctl (`"B1"`, alBnkfNew).
  These are offsets in the RAM image (header + unpacked CharDef). `h7` sample table and `h8` compressed CharDef are
  blob offsets; `h9` is the packed size; `h11` is the number of trailing palettes the costume-colour hook skips.
* **Blob layout**: `[0x40, h7)` frame bitmaps (contiguous, in frame order, DMA'd one at a time into 32 frame slots),
  `[h7, h8)` sound samples, then at `h8` the MPF compressed CharDef. Its header is `{u8 0x10, u8 0, u16 12,
  u32 total, u32 unpacked}`. Type 0x10 is RLE8 (RAM 0x80092434): `0xFF` ends, `c&0x80` repeats the next byte
  `(c&0x7F)+1` times, otherwise `c+1` literal bytes follow. The decompressor also has RLE16/24/32, Huffman and other
  types, but this build doesn't use them for fighters.
* **Frame table** (`h2`, 12 bytes per frame): bitmap blob offset, bitmap size (even), and the alpha record as a
  *file* offset (`RAM = rec + 0x40 - h8`; the loader fixes this up at load).
* **Palettes** (`h4`): `h3` × 64 RGBA5551 colours. The frames use almost all of them, and each row of a frame picks
  its own palette.
* **Frame bitmap**: `u8 W, u8 H, u8 X, u8 Y`. (X, Y) is the hotspot: about the horizontal centre, on the feet row.
  The header is followed by an LSB-first bit stream of runs, decoded as follows:
  * Each run starts with an 8-bit code `c`. If `c&1` is set, the next `(c>>1)+1` pixels are transparent; if not,
    they are opaque.
  * The first opaque run that starts in a new row is preceded by `P` (8 bits, the palette) and a mode (3 bits, plus
    1 more bit when the mode is ≥ 5, which adds 3).
  * Modes: 0 = 6-bit index; 1/2 = 5 bits, giving even/odd indices; 3/4 = 5 bits, giving 0–31 / 32–63; 5–8 = 4 bits,
    giving `4v+k`; 9/10 = 4 bits, giving even 0–30 / 32–62.
* **Alpha record**: 4-bit nibbles. A nibble with bit 3 set adds one octal digit to the skip count. The next nibble
  `n` sets that pixel's alpha to `25*(n+1)`. The record ends once the position reaches `H*even(W)`. Records are
  contiguous, in frame order, from `h5+0x68` to `h6`; the 0x68 bytes in front of them are small effect palettes,
  which the writer keeps.
* **Header CRC**: the reader's note that the stored pair doesn't reproduce is wrong. `gbox.romexport.n64_crc(rom,
  "6102")` gives `FA5A3DFF B4C9CDB9`, which matches the header.

## Writer strategy

1. **Geometry stays.** Every target frame keeps its W, H, hotspot and table slot. The fighter's sequences, attack and
   hit rectangles, moves and sounds live in the CharDef and are never touched, so they still line up.
2. **Frame mapping.** Donor frames are cropped to their opaque bounding box. One common scale maps the donor's
   90th-percentile height to the target's. Each canvas is letterboxed, with the donor's bottom centre on the
   hotspot; any frame that overflows at the common scale is shrunk to fit. Donor frames are dealt over the target
   frames in order when the donor has enough frames, and cycled otherwise. The target's sequence boundaries aren't
   decoded yet, so a donor's "walk" may land in the target's "kick".
3. **Colours.** Only the palettes the original frames used are rewritten. Each frame gets one palette of 64
   colours, chosen by median cut and sorted by luminance so that most rows fit the 4- and 5-bit modes. A fighter
   with more frames than palettes shares palettes across neighbouring frames. Palettes no frame uses keep their
   original colours.
4. **Encoding.** Each row gets the cheapest mode that covers its colour indices. Opaque runs never cross a row
   boundary; transparent runs may. Donor alpha between 64 and 229 becomes alpha records. If the records don't fit
   the fighter's record area, the costliest frames fall back to hard edges.
5. **Placement.** Where possible, the bitmaps go back in place (`[0x40, h7)`) and the re-packed CharDef goes back
   at `h8`. If either doesn't fit, the **whole blob is relocated** to space appended to the ROM, and
   `CHAR_ROM_START`/`END` are re-pointed. The relocated blob keeps the header, the samples at `h7` and the CharDef
   at `h8`, so every blob-relative offset and the `h8` record fix-up stay valid; the new bitmaps go after the
   CharDef. The ROM then grows to the next 4 MiB boundary. The fighter table sits inside the CRC-covered first
   MiB, so the header CRC is recomputed (`romexport.n64_crc`) in every case.

Measured on the owned ROM, with Bad Mr. Frosty re-drawn as Taffy (all 202 Taffy frames): the bitmaps take 284,522
bytes against 436,480 originally, so they fit in place, and the CharDef packs to 121,614 bytes against 146,734.
The ROM stays 16 MiB, all 185 frames decode, and the CRC is `FB77E25E 2D7265B2`. Taffy's bitmaps are also smaller
than Frosty's per frame, so the game's per-frame DMA buffers and the 32 frame slots stay within the original sizes.

What stays the original fighter's: character-select and bio portraits (these aren't in the fighter blob), the
name, voice and sounds, move set and hit boxes, and the costume tint for player 2 (the game's hook re-tints our
palettes the way it re-tints the originals).

## Tests

`tests/test_clayfighter_swap.py` has 36 tests. 30 run without the ROM: they build a 2 MiB synthetic ROM in the
game's own layout (fighter table, nullchar stub, blobs with frame bitmaps, sample table and RLE8 CharDef). They cover:

* the RLE8 round trip, including the 0xFF end code and runs longer than 127;
* a hand-packed frame and alpha record checked against an independent bit packer;
* encoder round trips at 1×1, 255-wide, 255-tall and >128-pixel rows;
* the choice between every mode;
* writer → reader with exact colours, checking that untouched CharDef bytes and the other fighters are unchanged;
* unused palettes kept, and more frames than palettes;
* more than 64 colours with soft edges and flip, plus soft-edge fallback when the record area is full;
* relocation, ROM growth and a second swap on the grown ROM;
* letterboxing on the hotspot;
* slot parsing and the four donor sources;
* export → donor, and the WRITERS / DEDICATED / CharIn registration.

The other 6 tests use the owned ROM and skip without it. They look in `GBOX_CLAYFIGHTER_ROM`,
`~/gBox_alt/gbox-cache/f87ec3e2f6b266a1/rom.z64` and `~/gBox_alt/gbox-cache/n64-rom/*.z64`, matching the sha1. They cover the
fighter table and the CRC pin, exact decoding for 3 fighters, byte-identical re-encoding, and a Frosty ← Taffy swap
that is decoded back with its CRC checked.

## Live check (not run yet)

This hasn't been run in an emulator. The agent that built it doesn't launch sessions.

1. `characters op=collect game_id=f87ec3e2f6b266a1`. Expect 16 entries, `clayfighter_bmf` … `clayfighter_zappa`
   (kind `sprites`, each with its own sheet + `_sheet.json`), and `slots` listing `fighter:bmf` … `fighter:zappa`
   plus `player`.
2. `characters op=use character=clayfighter_taffy game_id=f87ec3e2f6b266a1 slot=fighter:bmf`. This builds
   `cfsc_clayfighter_taffy_as_bmf` on the control plane and launches it. Open the mod's `frames_preview.png` first:
   it shows Taffy's frames as the game will draw them.
3. In the game, pick **Bad Mr. Frosty** on character select (his portrait is still the original). Play one round and
   check:
   * he looks like Taffy in the stance, walk, jump and attacks;
   * he stands on the floor, with the hotspot at his feet;
   * his colours are right, with no palette garbage or missing rows;
   * hits connect where Frosty's would;
   * nothing hangs while frames stream in (CHARFRAM.C "Out of frame slots").

   Then try a P2 mirror match. The costume tint should apply to the swapped fighter too.
4. The ticket's own request: `characters op=use character=ff7_cid_field game_id=f87ec3e2f6b266a1 slot=fighter:bmf`.
   Cid is a 3D entry, so he becomes a **static** pose (his preview render) in every one of Frosty's frames. For
   real animation, capture Cid as a sprite clip first (sprite_capture, save=true) and use that entry.
5. Relocation path: `slot=fighter:highfive` with a donor whose frames are larger or busier than High Five's
   (131 frames, about 0x52000 bytes of bitmap room). The report shows `relocated: true`, the ROM is 20 MiB, and
   High Five must still load and play.
