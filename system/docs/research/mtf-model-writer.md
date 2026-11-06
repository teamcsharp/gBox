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

## 2. The `MRL` header and path table, decoded

`evf0000` (19,920 B) begins:

```
0000: 4d 52 4c 00   "MRL\0"
0004: 22 00 00 00   version = 34
0008: 0c 00 00 00   count1  (unknown meaning; 6, 9, 12, 60, 65, 123, 131 seen)
000c: 13 00 00 00   path_count = 19   <- equal to the number of path records, 9 of 9 models matched
0010: 1f e5 e0 7b   hash
0018: 28 00 00 00   40  -> where the 0x241f5deb constant block begins (0x28)
0020: b0 06 00 00   1712 (0x6b0) -> a second offset, meaning not yet decoded
0028: eb 5d 1f 24   0x241f5deb
0040: path table
```

Each path record is **88 bytes**: `char path[64]` (NUL-terminated, `0xcd` filled) + `u32 0x241f5deb` + 20 zero bytes.
The table starts at `header[0x18] + 0x18` (i.e. 0x40), and the geometry stream follows it.

### Stage 1 and 2 are done and tested

`gbox/mt_model.py` parses the header and the path table and re-emits them from the parsed fields, carrying the geometry
opaque. Round-trip test over the tree:

```
uPl00ChrisNormal.arc   9/9   byte-identical
uPl01ShebaNormal.arc  10/10  byte-identical
uWp06.arc              1/1   byte-identical
uEm6c.arc              1/1   byte-identical
                      21/21
```

and a texture payload is refused (`not an MRL model (magic b'TEX\x00')`), so the parser is not accepting anything that
merely looks plausible.

Answers still needed, in this order:
1. what `count1` counts;
2. the second header offset (0x20) and what it points at;
3. the geometry stream's layout after the table: attribute masks, strides, index width, submesh table;
4. the bone/skeleton block (bind pose, parents) and the skin weights;
5. how a material references its textures (the path table suggests by name, not index).

## 2b. The geometry stream: what the difference map shows

`pl0000` and `pl0500` in `uPl00ChrisNormal.arc` are both 198,288 B uncompressed. Comparing them byte by byte:

```
identical bytes   193,334 of 198,288   (97.5%)
runs              3,213  (identical and differing alternate)
longest identical 113,863 B at 0x03127, then 4,172 B at 0x0141c, 3,165 B at 0x02fa33
longest differing 24 B at 0x253a4, 0x25994, 0x25f84, 0x26574 ...  (0x5F0 = 1520 apart)
```

Two conclusions that constrain the writer:

1. **The path table is confirmed again.** The differing runs early in the file are 4–10 byte islands with 78-byte
   identical gaps - 78 + 10 = the 88-byte record, so neighbouring records differ only in the name text and share all
   their padding and the trailing constant.
2. **`pl0000` and `pl0500` share their mesh.** Nearly the whole body is identical, so these two entries are the same
   topology with different material/texture references (and a handful of small fields). That means the geometry stream
   is not opaque per-model data: it can be compared across models to separate topology from names.
3. **A 1520-byte (0x5F0) stride appears in the differing fields.** The same value showed up as an offset in `wp0600`'s
   geometry (0x5f0). A repeating 24-byte differing field every 1520 bytes suggests per-record structures of that size
   - the next thing to map (candidate: per-mesh or per-material records).

Still undecoded: the geometry stream's own table (attribute masks, strides, index width), the skeleton (bind pose and
parents), the skin weights, and how a material resolves its texture names. The writer cannot author geometry until
those are known; it can parse and re-emit every model exactly (21/21).

## 2c. `MOD\0` is the geometry - and it does not travel between slots

Probing `uWp06.arc`'s second `wp0600` entry (35,496 B uncompressed):

```
0000: 4d 4f 44 00   "MOD\0"
0004: d3 00 03 00   (0x000300d3)
0008: 0f 00 09 00   (0x0009000f)
000c: 1f 06 00 00   1567
0010: 0d 09 00 00   2317
0014: 87 05 00 00   1415
0018: a4 64 00 00   25764
0020: 02 00 00 00   2
0028: a4 00 00 00   164      \
0030: 6c 03 00 00   876       |  seven offsets, rising, the last (35492) one file-length short of the payload:
0038: ac 03 00 00   940       | they look like block starts
0040: 2c 08 00 00   2092      |
0048: e4 13 00 00   5092      |
0050: 88 78 00 00   30856     |
0058: a4 8a 00 00   35492    /
0060: 28 e8 9d be   -0.308    \  floats, three at a time: these read as vertex positions
0064: 22 c8 d9 3f   1.7018     |
0068: 94 22 c9 be   -0.3939   |
006c: 57 53 0e 41   8.9017    /
```

So: **`MRL\0` is the model resource** (material block + the texture path table) and **`MOD\0` is the geometry**
(header of block offsets, then vertex data). The earlier note that a "shape swap" worked was wrong: that swap moved the
MRL, so it changed materials and left the mesh.

**Measured consequence:** mine <- grenade with the MRL *and* the MOD swapped boots to a **white screen** (frame
brightness a constant 238.6, `screen=unknown`), while the MRL alone plays a full round. A MOD carries its own offsets,
vertex counts and bone/material counts, so it only fits a slot built for the same skeleton. `model_swap.swap_models`
therefore takes `geometry=False` by default, and a real Sonic/Mario import must emit a MOD matched to the target's bones.

## 2d. The MOD header, and the two stages that are now done

`gbox.mt_model` parses the geometry container too, and re-emits it byte-identically:

```
0x00  "MOD\0"
0x04  u32            0x0300d3 / 0x0200d3 / 0xd3 seen
0x08  u32            0x09000f / 0x020004 / 0x0b000b ...
0x0c  u32  vertex count of the first submesh
0x10  u32
0x14  u32
0x18  u32  geometry block size      (equals block 4's length on every model checked)
0x1c  u32  0
0x20  u32  submesh count
0x28  7 x u64 block offsets, rising; the last is 4 bytes short of the payload
      then six blocks
```

**Round-trip: 31 of 31 MOD containers across five archives are byte-identical**, and there are two header variants: the
character/weapon models start their offsets at 164, the effect models under `effect\mod\...` start at 0. The variant is
carried so both are re-emitted exactly.

What is still missing for authoring geometry: `geometry block / vertex count` is an exact integer stride for some models
(16, 20, 24, 28) and fractional for others (23.487, 19.599), so the block is not a pure vertex stream — the counts at
0x0c/0x10/0x14 and the submesh count at 0x20 do not yet describe how vertices and indices are split.

### Block 2 is a name table - and it says what a "submesh" really is

Block 2 is a table of **128-byte name records**, one per mesh part **per LOD**, padded with zeros:

```
wp0600 (9 records): reba_000_LOD2.polymsh.cls.otherPolygons.XfB_N__E
                    hontai_000_LOD2.polymsh.cls…
                    ping_001_LOD2.polymsh.cls…
                    reba_000_LOD1 … hontai_000_LOD1 … ping_001_LOD1 …
                    ping_001_LOD0 … reba_000_LOD0 … hontai_000_LOD0 …
evf0000 (12):       chris_face_skin.chris_toothes_geo.polymsh.cls.Ha_Out_Up_09.XfB_N__E16
                    chris_face_skin.chris_eyelash_Low_geo.polymsh.cls.otherPolygons.XfBAN_
                    ...
```

Two consequences:

1. the names are **Maya export artifacts** (`polymsh`, `cls`), i.e. the source part names survive in the shipping file;
2. **the header's "submesh count" is really a part x LOD count** - wp0600 reports 2 while its table holds 9 records
   (3 parts x 3 LODs), so the vertex buffer holds every LOD, which is exactly why `vertex_count * stride` never equals
   the block for most models.

### The per-part split is still not found

Block 3 is *not* a fixed-stride table of counts: every stride from 16 to 400 bytes and every field offset in it was
searched, and no field sums to the model's vertex or index count for either wp0600 or evf0000. The remaining leads are
block 0 (712 bytes for a 9-record model), block 1 (64 bytes), and the possibility that block 3 is variable-length
records. Until that is cracked a writer cannot emit geometry, only carry it.

Definitely decoded, over **31 containers in five archives**:

* **block 5 is the 16-bit index buffer** and header word **0x10 is the index count**: `len(block5) == 2 * index_count`
  on **31 of 31** (occasionally one or two indices of padding). This is the first fully closed part of the geometry.
* **block 4 is the vertex buffer**; its stride is exact only for single-LOD models (16/20/24/28 seen, 11 of 31).
* **block 2 is a name table** of 128-byte records, one per mesh part per LOD (see above).
* **block 3 is not a fixed-stride count table** — searched exhaustively, see above.

`ModFile.layout()` exposes all of it in one call (counts, stride and whether it is exact, block sizes, record counts,
header variant), and `tests/test_mt_model.py` pins the parser with synthetic payloads — including that a texture payload
is refused, that a header lying about its table is refused, and that a multi-submesh stride is reported as inexact
rather than guessed.

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
