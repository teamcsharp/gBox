# Super Bust-A-Move PS2: bounded offline analysis

This read-only milestone continues PR #530 / inbox #1368. It does not establish
roster-to-sprite-bank mapping, a replacement writer, a rebuilt playable image,
or native acceptance. Keep the character-replacement request open.

## Exact executable evidence

Every helper reading a fixed ELF address requires the complete 4,673,508-byte
SLUS_201.15 with SHA256
`eeb913a6eac79a58d8424dc18190310f1ae5d14d762dec5a339f44ad9870d965`.
Address conversion alone is arithmetic for that build's PT_LOAD; it is not an
identity check on an arbitrary executable.

The pinned DAT index is 153 unique paths at virtual address 0x56D780, stride
0x20. The loaded file segment is offset 0x1000, address 0x100000, size 0x471DAC.

Two original analysis claims were corrected from the owned executable:

* The decoder instruction at 0x1C5904 is `slti v1,v0,0xFEE` (word 0x28430FEE).
  The loop clears only ring bytes [0,0xFEE), not all 4096 bytes. At 0x1C5940,
  `addiu v0,zero,0xFEE` (0x24020FEE) initializes the cursor. This does not prove
  equivalence of every malformed stream to the existing inventory decoder.
* The dispatcher at 0x1C5B08 compares four bytes against **NOCM**, not zeros.
  The operand at 0x1C5B28 is GP-0x7350; ELF `.reginfo` gives GP=0x5790F0.
  The bytes at 0x571DA0 are `4e4f434d`. The equal branch copies from source+4.
  This does not mean the inventory's raw ADPCM entries go through that route.

Consequently the earlier guessed same-size/raw writer recipe is removed.
No existing inventory or codec implementation is changed by this milestone.

## Offline texture preview profile

The parser validates all declared picture headers, complete extents and trailing
data before decoding any selected picture. Limits are 16 MiB input, 64 pictures,
and 4,194,304 aggregate pixels (at most 16 MiB output for one picture). TIM2 v4,
alignment 16/128, picture format 0 and one mip level are required. Packed image
bytes may have only zero tail padding up to the next 16-byte boundary; this
matches three measured textures in the owned image. Odd-width 4bpp is rejected.

RGBA preview accepts even-width linear 4bpp with exactly 16 RGBA32 colors,
8bpp with 256 RGBA32 CSM1 colors, and direct RGBA32. It verifies the corresponding
GS pixel-storage mode; indexed preview requires CPSM=0, CSM=0 and CSA=0.
Multi-palette 4bpp textures remain available as metadata but decoding rejects
them because bank selection is not established. Unknown layouts never fall back
to a guessed first palette.

Low nibble comes first for 4bpp pixels. CSM1 8bpp palette colors swap the middle
two eight-color blocks in each group of 32. Display alpha is `min(255, 2*a)`;
transparency follows each palette/pixel alpha, not a fixed color index. These
preview rules are cross-checked against the independently authored ImageMagick
TIM2 reader (GetAlpha, deshufflePalette, ReadTIM2ImageData), pinned below. They do
not reproduce the game's GS blend/texture-function state or prove animation.

Public reference: [4d3d052dbc3839c4e31c084b3b87a8c3be48994b](https://raw.githubusercontent.com/ImageMagick/ImageMagick/4d3d052dbc3839c4e31c084b3b87a8c3be48994b/coders/tim2.c), source SHA256 `bbab6a763945fc6c6b78e47d93dfff455a37de3cd24d159ad0988f9c173df440`.

## Validation and next work

Synthetic regressions cover full and partial headers, extent mismatches, huge
dimensions before allocation, aggregate limits, palette selection rejection,
CSM1 color order, alpha saturation, transparent nonzero indices, supported zero
padding and exact executable identity. Owned tests verify the DAT index, exact
instruction words, NOCM marker and representative 4/8bpp payloads.

The offline census checks every TIM2 payload from owned ISO SHA256
`7e0c4e6e2b7c82df1fff9bee6d94291af1a1a856b4b6796f03fea2b3a3e616b6`
and records each source-payload/output hash plus unchanged source identity.
All 2,320 payloads validate structurally: 2,005 4bpp, 267 8bpp and 19 direct
32bpp textures decode; 29 multi-palette 4bpp payloads are rejected for preview.
A representative contact sheet shows coherent title art and sprite frames; it
is not a game capture or a verified roster mapping.
Acceptance is limited to the decoder profile, not character identity or a mod.
The next required work is explicit character-bank/palette mapping, a source-safe
native replacement writer, rebuilt-image validation and native gameplay proof.
