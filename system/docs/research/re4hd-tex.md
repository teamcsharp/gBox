# RE4 Switch (HD) textures: the descriptor, and the archive the pixels live in

Measured 2026-11-07 on `~/gBox_alt/switch/romfs/010099A00BC1E000`. Code: `system/gbox/re4hd_tex.py`.

## Two things, and they are not the same file

A character pack's `TPL` slot **is not a GameCube TPL**. The GC one is magic `0x0020AF30` (GX, big-endian, carries its
own image table and pixel data). The HD slot is a 96-byte little-endian descriptor with magic `0x12345678`.
And it does **not** carry pixels: a 256x256 CMPR surface is 32 KB, the slot is 96 B.

## The descriptor (1,702 slots in 162 packs, 0 refused)

```
0x00 u32  magic 0x12345678                        all 1,702 slots
0x04 u32  version 1                               all
0x08 u32  16                                      all
0x20 u32  width (u16) | height (u16)              779 "image" slots; 0 high half on the other 923
0x24 u32  format 14                               image slots (the GX CMPR number); 0 on the others
0x28 u32  data offset 0x48                        image slots; 0 on the others
0x48      payload: u32 type 0x10, u32 texture id  observed ids across 0..191 (108 distinct)
```

The split is real and worth naming, because reading the second class as pictures is exactly the mistake that produces
`88x0` and `104x0` dimensions:

| class | count | what it says |
|---|---|---|
| `image` | **779** | width/height/format and the texture **id** the pack wants |
| `reference` | **923** | same container, format 0, no data offset — no dimensions and no id to report |

Dimensions among the image slots: 64x128 (180), 64x64 (174), 128x128 (142), 256x128 (68), 32x128 (66), 256x256 (62).

## The archive: `bio4/imagepackhd` — 1,813 `.pack.fen`, 6,144,462,613 B

```
u32 uncompressed size, then a zlib stream (78 9c)
```

The declared size equals the decompressed length **exactly** on every file checked (1.8 MB → 4.2 MB, 4.4 MB → 10.3 MB,
14.0 MB → 34.6 MB of file → body). `gbox.re4hd_tex.fen_open` refuses a stream whose declared size lies.

The decompressed body opens with two u32 counts and then a 64-bit offset table. **The entry map is established:**

* `count_b` **is** the entry count — `len(offsets) == count_b` on 40 of 40 archives, and on a further 60 archives
  (3,831 entries) every archive produced a consistent map with **0 failures**;
* the entries are the slices between consecutive offsets and the **last one ends exactly at the body end**;
* entry sizes: min 512 B, median 49,408 B, max 5,592,576 B; 1,788 of 3,831 entries are ≥ 64 KB.

Not understood: `count_a` (6 / 9 / 19 for bodies holding 3 / 13 / 89 entries, so it is not the entry count). It is
reported as-is and used to index nothing.

## What is still missing

1. **The surface codec.** Format 14 is the GX CMPR number, which on a Switch title is plausible but unproven — the
   pixel bytes have not been decoded into an image. Nothing here claims a texture preview.
2. **The id → entry mapping.** A descriptor names id 46; which of 1,813 packs and which entry that is, is not yet
   established. That is the join that turns "the pack wants texture 46" into bytes.
3. **The replacement path.** Once (1) and (2) exist, a skin swap is: decode → substitute → re-encode CMPR → write the
   entry in place → re-deflate the FEN → pad to the original file size (the rule the GameCube work paid for).

## API

```python
from gbox import re4hd_tex as T
info = T.tex_info(slot_bytes)          # kind image|reference, w/h/format/id, surface_bytes, carries_pixels
out  = T.fen_open(fen_bytes)           # declared_size, body, count_a, count_b, offsets, entries[]
data = T.fen_entry(fen_bytes, index)   # one entry's bytes
```

`tex_info` reports `carries_pixels: False` and says "descriptor only" whenever the slot is smaller than the surface it
names — the check that keeps a 96-byte descriptor from being mistaken for a picture.

Tests: `system/tests/test_re4hd_tex.py` (9 cases: image descriptor, reference slot, a GC TPL named as such, unknown
magic, a short slot, an offset outside the slot, the FEN size check, the entry map, a non-zlib stream).

## The pixels are plain DDS (2026-11-07)

The surface codec this note listed as missing is **not a private codec at all**. Every entry of an `imagepackhd`
archive is a 16-byte wrapper followed by a **DDS** file:

```
entry: u32 dds_bytes, u32 -1, u32 archive_number, u32 0     (16 B; a 64-byte variant exists)
       then "DDS " + the standard 0x7C header: height, width, mip count, pixel format
```

Verified over the first 8 archives: **680 textures, 0 refused**, formats **DXT3 (428)** and **DXT5 (252)**, dimensions
32x32 through 1024x1024, mip chains 9-11. 240 of the 680 carry the longer wrapper (the DDS is located by its magic
rather than assumed at 16, which is why they parse at all).

**And they decode to real images.** PIL opens the extracted DDS directly - two 256x256 DXT3 surfaces from
`00000009.pack.fen` render as stone and bark/wall detail maps:

![a decoded RE4 Switch texture](evidence/re4switch-texture-256.png)

That changes what a skin replacement needs. It is no longer "write a codec":

1. **Read** a texture: `re4hd_tex.fen_texture(archive, index)` -> header + the DDS bytes.
2. **Edit or substitute** it: any DDS tool, or `PIL` -> `save(..., "DDS")`.
3. **Write it back**: re-wrap, re-deflate the FEN, and patch the archive in place - the same rule as the model packs,
   the entry must be the entry's own size (or the whole archive re-deflated and the file-size field updated).

What is still open is the **join**: a pack descriptor names an id in 0..191 (108 distinct for the 162 em packs) and
nothing yet says which `(archive, entry)` that id is. The likely route is the descriptor's own `width x height` and
format against the DDS headers - a small search space once the descriptor's id is understood - and it is the next
piece of this line.