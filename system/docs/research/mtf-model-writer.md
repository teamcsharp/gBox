# MT Framework model writer (Switch: RE4, RE5, RE6)

Goal: emit a valid `MRL` model file for a Switch MT Framework title, so a model from the collection (Sonic, Mario,
DOA, anything with a rig) can replace a character or enemy slot from a LayeredFS overlay instead of rebuilding the game.

All numbers below are measured on the Spark against the extracted RE5 tree
(`~/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive`); none are taken from documentation.

## 1. Two facts a writer depends on, both verified

### 1.1 An .arc entry's tag carries the uncompressed length

Every model entry in `uPl00ChrisNormal.arc` decompresses to a length that equals the entry's `tag & 0x00FFFFFF`:
**24 of 24** entries matched exactly (1,426 B compressed → 19,920 B, 109,070 → 393,332, and so on). The upper byte of
the tag selects the kind of payload (textures and models use different values). So a writer must set
`tag = (kind << 24) | len(uncompressed)` and zlib-compress the payload; gBox's `mt_arc.replace_at` already writes data
with an optional tag.

### 1.2 Model payloads are `MRL` containers; textures are `TEX`

`zlib.decompress(entry.data)[:4]` distinguishes them:

| magic | example entries | meaning |
|---|---|---|
| `MRL\0` | `pawn\pl\pl00\model\evf0000`, `pl0000`, `pl0001`, `pl0500`, `wp0600` | model / mesh container |
| `TEX\0` | `pawn\pl\pl00\model\evf0000_01_NM`, `pl00Detail_DM_HQ` | texture |

A character archive carries each model group twice: a small entry (1–6 KB) and a large one (100–500 KB)
(e.g. `evf0000` at 19,920 and 393,332 uncompressed). The small one is the header/description and the large one the
geometry stream.

## 2. The `MRL` header, as far as it is decoded

`evf0000` (19,920 B) begins:

```
0000: 4d 52 4c 00   "MRL\0"
0004: 22 00 00 00   version = 34
0008: 0c 00 00 00   12
000c: 13 00 00 00   19
0010: 1f e5 e0 7b   a hash
0018: 28 00 00 00   40  -> offset of the resource path string
0020: b0 06 00 00   1712 (0x6b0) -> where the geometry data begins
0028: eb 5d 1f 24   0x241f5deb - the same hash constant .arc entry records carry
0040: "pawn\pl\pl00\model\evf0000_01_NM"   the path string at offset 40
```

Answers still needed, in this order:
1. what 12 and 19 count (blocks? LODs? materials?);
2. the offset table layout between 0x40 and 0x6b0;
3. the bone/skeleton block (bind pose, parents) and the skin weights;
4. the vertex stream layout at 0x6b0 (attribute masks, strides, index width);
5. the material list and how a material names its textures (the path string at 0x40 suggests names, not indices).

## 3. The build order (each step has a test that fails loudly)

1. **Parse**: read the header, the offset table and the geometry block of a real model into a structure, and assert
   the header fields against the file length.
2. **Round-trip**: re-serialise that structure and require the bytes to be identical to the original
   (`bytes(out) == original`) for several models - a text-heavy character (`pl0000`), a small one (`pl0001`) and a
   weapon (`wp0600`). Nothing is written to a game until this passes for all of them.
3. **Edit**: change one vertex position and one texture path, round-trip again, and confirm the parse sees the change.
   This proves the writer owns the fields rather than copying bytes.
4. **Import**: take a fitted GLB (rig in the target's bone names, as `re4gc_enemies.retarget` produces for RE4 GC) and
   write it into the slot's bone set.
5. **Boot test**: a LayeredFS overlay with the written model, launched under eden, must reach `screen=playing` with a
   visible round. **A donor mesh written approximately hangs the title's load** - measured twice on object archives,
   with and without retagged materials - so this step is the only acceptance that matters.

## 4. Why this is the highest-leverage piece

RE4 (Switch), RE5 and RE6 all read this same container, so one correct writer unlocks model replacement on three
titles at once, and it is the missing half of the zombie-replacement work: the fitting side exists
(`re4gc_enemies.retarget`, the client retarget editor, `char_swap.glb_merge_joints`), and the collection already holds
1,163 rigged characters (21 Sonic including `sa1_sonic` at 74 joints, 41 Render96 Mario, 103 DOA).

Mercenaries 3D (MTF Mobile) and RE4 VR (UE4, Quest/Android) are different formats and are not covered by this writer.
