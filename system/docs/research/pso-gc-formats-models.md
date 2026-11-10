# PSO Episode I & II Plus (GameCube) — 3D model formats

Disc: `Phantasy Star Online Episode I & II Plus (USA)`, id **GPOE8P**, catalog `436e0bb84d5337d1`, read read-only through `gbox.gcdisc.GCDisc` (GCZ, 3510 FST files). Every number below was produced by running the repo's own parsers on that image; anything not proven is marked **unproven**. The image and extracted assets are never copied into the repo — sizes, offsets and hashes only.

Ground truth used, not re-invented: `system\gbox\ninja.py` (`bml`, `njtl`, `class NJ`, `tree_nodes`, `chunk_list_len`, `pof0`, `write_tree`), `system\gbox\pso_gc.py` (`read_nj`, `njcm_payload`, `tree`, `class_roles`, `bml_files`), `system\gbox\pso_player.py` (`PLAYER_PARENTS`/`PLAYER_ROLES`, `bml_align`), `system\gbox\pso_enemy.py` (`vertex_owners`, `infer_roles`, `body_nj`), `system\gbox\pso_gc_swap.py` (`body_nj`, `render_state`), `system\gbox\formats\ninja_chunk.py` (chunk-id table).

Two endiannesses coexist in one file — the single most important fact about the format:

| layer | order | evidence |
|---|---|---|
| chunk framing (`tag[4]` + `u32` body size) | **little-endian** | `plAbdy00.nj`: size bytes `b0 52 00 00` = 21168, next chunk at 8+21168 = `0x52b8`, file 21308 = 8+21168+8+124 |
| chunk payload (node/model structs, vertex chunks) | **big-endian** | `ninja.py:4`, `pso_gc.py:12-14` |
| polygon chunks (strips, tiny, material) | **u16-swapped** | `ninja.py:242-243` |

## 1. The Ninja chunk container

### 1.1 Framing

`struct nj_chunk { char tag[4]; u32 size_le; u8 payload[size_le]; }` — payload big-endian. Walk: 8 header bytes then `size` bytes; every size in this doc is a multiple of 4, so chunks stay aligned. `pso_gc.py:218-224`: *"Chunk sizes are little-endian on GC too."*

Census of the 198 loose `.nj` (walked with `struct.unpack_from("<I", d, o+4)`):

| composition | files |
|---|---|
| `NJCM` + `POF0`, nothing before `NJCM` | **198 / 198** |

A loose player model is **one** `NJCM` chunk plus its `POF0` — no `NJTL`, no `GBIX`, no `NMDM`. Its texture names are not in the file at all; they come from `NJS_TEXLIST` records in `PsoV3.dol` found by string references (`pso_gc.tables`, `pso_gc.py:314-364`).

| file kind | layout |
|---|---|
| loose `pl<X>bdy00.nj` / `hedNN` / `haiNN` / `capNN` | `NJCM` + `POF0` |
| `.nj` inside a `bm_ene_*.bml` entry (decompressed) | `NJTL` + `POF0` + `NJCM` + `POF0` |
| `.gj` scene file | `GJTL` + `POF0` + `GJCM` + `POF0` |

| file | total | chunk table |
|---|---|---|
| `plAbdy00.nj` | 21308 | `NJCM`@0 (21168), `POF0`@0x52b8 (124) |
| `lo_abgc01_wola_body.nj` (in `bm_ene_abgc01_wola_body_low.bml`) | 23284 | `NJTL`@0 (60), `POF0`@0x44 (4), `NJCM`@0x50 (23012), `POF0`@0x5a3c (176) |
| `Scene/map_forest01s.gj` | 1944 | `GJTL`@0 (32), `POF0`@0x28 (4), `GJCM`@0x34 (1856), `POF0`@0x77c (20) |
| `Scene/map_boss05s.gj` | 14316 | `GJTL`@0 (324), `POF0`@0x14c (12), `GJCM`@0x160 (13856), `POF0`@0x3788 (92) |

The BML header's `dsize` equals the whole `NJ` length: 23284 = 8+60+8+4+8+23012+8+176, and `dsize` for `plAbdy00.nj` in `plAnj.bml` is 21308.

**Parser trap (verified):** `ninja.py:198` reads the `NJCM` size with `self.e` — **big-endian** when `be=True`, although the field is little-endian. For `plAbdy00.nj` it reads 2958163968, the slice clamps to EOF, and the tree still parses because node offsets are payload-relative: `len(NJ(body, be=True).d) == 21300` instead of 21168. Use `pso_gc.njcm_payload()` (`pso_gc.py:218-224`, `<I`) when the payload length matters.

```python
import struct, sys; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
data = d.read("plAbdy00.nj"); o = 0
while o + 8 <= len(data):
    tag, size = data[o:o+4], struct.unpack_from("<I", data, o+4)[0]
    print(f"{o:#06x} {tag} size={size} (LE) end={o+8+size:#06x}")
    o += 8 + size
```

### 1.2 `POF0` — the pointer-offset table

`POF0` lists the byte offsets of pointer fields inside the *preceding* chunk's payload, relative to that payload's start. `ninja.pof0` (`ninja.py:667-681`) is the writer and its docstring is the spec: *"2-bit size class + distance in 4-byte units (0x40 | d: 6 bits, 0x80 | d: 14 bits, 0xC0 | d: 30 bits)"*.

| first byte | extra bytes | distance | field offset |
|---|---|---|---|
| `0x40..0x7F` | 0 | `b & 0x3F` | previous + 4·d |
| `0x80..0xBF` | 1 (`u16` BE) | `u16 & 0x3FFF` | previous + 4·d |
| `0xC0..0xFF` | 3 (`u32` BE) | `u32 & 0x3FFFFFFF` | previous + 4·d |

Distances are **deltas** from the previous field, starting at 0; fields are 4-byte aligned, ascending, and the body is zero-padded to 4 bytes. `0x00` is not a legal first byte, so there is no terminator — a decoder must stop at the first zero byte or at the declared size.

| table | size | fields | encoding |
|---|---|---|---|
| `plAbdy00.nj` after `NJCM` | 124 | **104** (max 21112 < 21168) | 85 × 1-byte, 19 × 2-byte |
| `lo_abgc01_wola_body.nj` after `NJCM` | 176 | 74-node tree | mixed |
| `lo_abgc01_wola_body.nj` after `NJTL` | 4 | 3 (`40 42 43 00`) | 1-byte |
| `Scene/map_boss05s.gj` after `GJTL` | 12 | 11 (`40 42 43×9 00`) | 1-byte |
| `Scene/map_boss05s.gj` after `GJCM` | 92 | 21, incl. `82 98` (2-byte class) | both |

Fields covered, from `ninja.write_tree` (`ninja.py:655-663`) and the measured offsets: per node `model` (+4), `child` (+44), `sibling` (+48) when non-zero; per model `vlist` (+0), `plist` (+4) when non-zero. For `plAbdy00.nj` the first fields are 4, 44, 3576, 3640, 3652, 3692, 4304, 4372 — node0.model, node0.child, node0.model+4 (plist), node1.child, … exactly that set. Zero fields are omitted (`write_tree`: `if v`).

### 1.3 `NJCM` node and model structs

`NJCM`'s payload starts with the root `NJS_OBJECT` at offset 0 (`ninja.py:554-577`, `ninja.py:210-231`), 52 bytes, big-endian:

| off | type | field | read at |
|---|---|---|---|
| 0x00 | u32 | **flags** (evalflags) | `ninja.py:215-216` |
| 0x04 | u32 | model pointer | `ninja.py:221` |
| 0x08 | 3×f32 | position | `ninja.py:213` |
| 0x14 | 3×s32 | angle (32768 = 180°) | `ninja.py:213`, `:156` |
| 0x20 | 3×f32 | scale | `ninja.py:213` |
| 0x2C | u32 | child pointer | `ninja.py:214` |
| 0x30 | u32 | sibling pointer | `ninja.py:214` |

`tree_nodes` keeps bytes 0x08..0x2C verbatim as `trs` (`ninja.py:566`) and `write_tree` writes them back unchanged (`ninja.py:660`), so a writer can re-emit a node without touching its transform.

Flag bits as `ninja.py` implements them:

| bit | meaning | line |
|---|---|---|
| 1 | ignore `position` (use 0,0,0) | 215 |
| 2 | ignore `angle` | 215 |
| 4 | ignore `scale` (use 1,1,1) | 216 |
| 8 | do **not** read `model` | 221 |
| 0x10 | do **not** recurse into `child` | 227 |
| 0x20 | rotation order ZXY instead of ZYX | 216 |

Observed on `plAbdy00.nj`'s 64 nodes: `0x07` only on the root (all three TRS parts ignored), `0x04`/`0x05`/`0x0c`/`0x0d` on joints and mesh nodes, `0x1c`/`0x1d`/`0x1e` on the hidden mounts (no vertices), plus `0x0e`, `0x15`. Node 56 is the head mesh (`0x05`, model 20780), node 59 the hidden head mount (`0x1d`, `pso_gc.py:46`).

Model struct, 24 bytes (`ninja.py:222`, `pso_gc_swap.py:186-187`):

| off | type | field |
|---|---|---|
| 0x00 | u32 | vertex-list pointer (0 = none) |
| 0x04 | u32 | polygon-list pointer (0 = none) |
| 0x08 | 3×f32 | bounding centre |
| 0x14 | f32 | bounding radius |

Real values: `plAbdy00.nj` node 0 → `(0, 52, -0.009698, 8.32872, 0.399938, 0.0)` (a centre but radius 0);
node 56 → `(20344, 20340, 0, 0, 0, 0)`.

### 1.4 Chunk taxonomy and the sizes actually parsed

`formats\ninja_chunk.py:11-19` names the SDK ranges — 0 null, 1-5 bits, 8-9 tiny, 16-31 material, 32-50 vertex, 56-58 volume, 64-75 strip, 255 end — matching `NJ._vertices` (`ninja.py:233-271`) and `NJ._polys` (`ninja.py:280-329`). There is **no** `DATA_OFFSET`/`eu32` macro layer here; the only accessor is `NJ.u(fmt, off)` (`ninja.py:207-208`) with endianness from `NJ.e`.

`plAbdy00.nj`, measured:

| chunk | count | bytes each | content |
|---|---|---|---|
| `0x29` vertex entry | 15 | 200 = 4 + 49·4 | 8 vertices, stride 24 = position 3f + normal 3f |
| `0x2c` weighted vertex entry | 19 | 400 = 4 + 99·4 | 14 vertices, stride 28 = 6f + u32 Ninja flag |
| `0x13` material | 8 | 12 = 4 + 4·2 | 4 shorts of render state (`ff ff ff ff ff ff ff ff` on the body) |
| `0x08` tiny | 9 | 4 | texture id + `0x4000` flag word |
| `0x41` strip (UV) | 11 | 4 + shorts·2 | shorts = 734, 606, 378, 284, 264, 250, 200, 186, 100, 76, 14 |
| `0x04` cache-polygon-list / `0x05` draw-cached-list | 3 / 3 | 2 | defer drawing to a later node |

Totals: 15 vertex lists, 8 polygon-list pointers (3 cache stubs), 269 vertex-cache slots, **692 triangles**, 5 texture ids (0-4). The `0x04`/`0x05` pair is the weighted-model trick of `ninja.py:286-291`: strips are cached by node 0 / 26 (`plcache {0: 54, 1: 16310}`) and drawn by the nodes holding a `0x05` chunk, after all bones have written their vertices.

## 2. The big-endian data model

`pso_gc.py:12-14`: *"Chunk / POF0 sizes stay little-endian; the payload is big-endian with two swap units: node / model structs and VERTEX chunks are u32-swapped (the second vertex-chunk word is u32 count << 16 | base), POLYGON chunks are u16-swapped (strips, tiny and material chunks). gbox.ninja.NJ(be=True)."*

Chunk header word (`ninja.py:236`):

```
head = u32be;  typ = head & 0xFF;  flg = (head >> 8) & 0xFF;
size = head >> 16;   // words for vertex chunks, shorts for strip / material
```

Vertex chunk (`ninja.py:233-271`):

```
struct vtx_chunk { u32 head; u32 count_base; u8 data[size*4 - 4]; };
base = count_base & 0xFFFF; count = count_base >> 16; stride = (size*4 - 4) / count;
```

Real bytes at `plAbdy00.nj` node 2, vertex list 3700:

| offset | bytes | meaning |
|---|---|---|
| 3700 | `00 31 00 29` | type `0x29`, flags 0, size 49 words |
| 3704 | `00 08 00 3c` | count 8, base 0x3c = 60 |
| 3708 | `3f c4 42 bd 3c c4 e7 a4` | position (1.53329, 0.0240362, -1.08910) |
| 3720 | 3 f32 | normal (-0.100840, 0.00383849, -0.994895) |

Next chunk at 3900: `00 63 80 2c` / `00 0e 00 a0` → type `0x2c`, flags `0x80` (weight status 0 = start), size 99, count 14, base 160, stride `(99·4-4)/14 = 28`; the extra word at `p + stride - 4` is `low = vertex index, high = weight/255` (`ninja.py:253-267`).

Strip chunk (`ninja.py:300-327`): `u16 head`, `u16 size_shorts`, `u16 hdr` where `hdr & 0x3FFF` = strip count and `hdr >> 14` = user bits; per strip an `s16 n` (negative = flip) then per vertex `u16 index` [+ 2×s16 uv] [+ extra]. UV types are `0x41,0x42,0x44,0x45,0x47,0x48,0x4A,0x4B`, divisor 255 for `0x41/0x44/0x47/0x4A` else 1023; extra shorts 3 for `0x43/0x44/0x45`, 2 for `0x46/0x47/0x48`, plus `user·2` bytes from vertex 2 on (`ninja.py:303-320`). The player bodies use only `0x41` (flags 0x02, and 0x0b on one 14-short chunk). Tiny (types 8, 9) is 4 bytes: head with `flg` = the node's tiny flags (0x34 on the body) and a `u16` texture id, low 13 bits (`ninja.py:296-298`) — observed `34 08 | 40 01` = flags 0x34, texture 1. Material (0x10..0x3A) is `4 + size·2` bytes, skipped by size (`ninja.py:298-299`).

## 3. Animations and motion banks

### 3.1 `NMDM` — the Ninja motion chunk

9 loose `.njm` (all `Scene/map_*s.njm`) plus **762** `.njm` entries inside 121 BML packs. Header read directly (no repo parser exists for the PSO GC flavour):

| off | type | observed | note |
|---|---|---|---|
| 0x00 | char[4] | `NMDM` | |
| 0x04 | u32 LE | body size | 364 for `map_jungle02_00s.njm` (384 = 8+364+8+4) |
| 0x08 | u32 BE | **12** in 766 of 771 | offset of the per-node mdata table — **unproven** |
| 0x0C | u32 BE | frame count | 450/1000/1200/1500/1800 scenes, 20-31 enemy clips |
| 0x10 | u16 BE | **type** | 3 = position + rotation (`pso_enemy.py:8`), 7, `0x2001`, `0x2005` |
| 0x12 | u16 BE | **inp** | 2, 3, or 0x42 |
| 0x14 | 40 B | zero | **unproven** (start/end frame or reserved) |
| 0x3C | u32 BE | 76 | first `POF0`-listed field (payload+48) |

| file | bytes | LE size | mdata | frames | type | inp |
|---|---|---|---|---|---|---|
| `Scene/map_boss05s.njm` | 660 | 636 | 12 | 450 | 3 | 2 |
| `Scene/map_jungle01_00s.njm` | 500 | 476 | 12 | 1200 | 3 | 2 |
| `Scene/map_jungle02_00s.njm` | 384 | 364 | 12 | 1000 | 3 | 2 |
| `Scene/map_jungle03_00s.njm` | 500 | 476 | 12 | 1200 | 3 | 66 |
| `Scene/map_jungle04_00s.njm` | 500 | 476 | 12 | 1500 | 3 | 2 |
| `Scene/map_jungle04_01s.njm` | 500 | 476 | 12 | 1500 | 3 | 2 |
| `Scene/map_jungle04_02s.njm` | 500 | 476 | 12 | 1500 | 3 | 2 |
| `Scene/map_jungle05_00s.njm` | 464 | 444 | 12 | 1800 | 3 | 2 |
| `Scene/map_jungle06_00s.njm` | 432 | 412 | 12 | 1800 | 3 | 2 |

Over all 771 `.njm`, `(type, inp)`: (3,2) 667 · (7,3) 90 · (0x2001,2) 4 · (3,66) 3 · (0x2005,3) 2;
`mdata == 12` in 766 (the 5 exceptions are `dsize = 0` entries, §6).

Track payload: `map_jungle02_00s.njm` has 16 records of 16 bytes from payload+96, in two blocks of 8, frames
125…999, values ≈ ±131072·frame/1000 — two mirrored ramps of about ±2 turns if the value is a Ninja angle
(65536 = 360°). **The record field split is unproven** (`{u32 frame, u32 0, s32 value, u32 0}` and interleaved
key tables both fit). **No repo code decodes PSO GC motion tracks**: `pso_inventory._classify` only tags the
magic (`pso_inventory.py:156`), `pso_gc_inventory.py:14` only counts the bank, and the one NMDM reader
(`sshuffle_inventory.motion_frames`, `:150-156`) is little-endian and for Sonic Shuffle. Header proven,
tracks **unproven**.

```python
import struct
b = d.read("Scene/map_jungle02_00s.njm")
print(len(b), struct.unpack_from("<I", b, 4)[0], struct.unpack_from(">IIHH", b, 8))   # 384 364 (12,1000,3,2)
```

### 3.2 `PlyMotionData.rlc` (1491904 bytes)

Not a Ninja chunk file. Header, big-endian:

| off | type | value | meaning |
|---|---|---|---|
| 0x00 | char[16] | `RelChunkVer0.20\0` | magic + version |
| 0x10 | u32 BE | **572** | motion count (`assimilate_kb.py:67`: "572 motions") |
| 0x14 | u32 BE | 0x20 = 32 | directory start |
| 0x18 | u32 BE | 0x1200 = 4608 | first blob offset = 32 + 572·8 |
| 0x1C | u32 BE | 0 | **unproven** (flags) |
| 0x20 | 572 × {u32 offset, u32 size} | | all offsets 0x20-aligned, strictly increasing |

Verified: last record `{0x16b840, 0xb61}` → end 0x16c3a1 with file 0x16c3c0 (31 bytes tail padding), no gap or
overlap. Each blob starts with a `u32 BE` (0x0ae0 = 2784 for blob 0) then high-entropy bytes;
`ninja.prs_decompress` fails. **Blob codec unproven.**

### 3.3 `*.cpt` and `PlyMotionNpcTown.rel`

| file | header | proven | unproven |
|---|---|---|---|
| `PlyLevelTbl.cpt` (11774) | `00 00 71 00` = 28928 BE, then a stream | first u32 is 2.46× the file size → consistent with a declared decompressed size | codec: not PRS (`prs_decompress` → `IndexError`), not zlib (raw/zlib/gzip at +0/+4/+8 all fail) |
| `PlyMotionNpcTown.cpt` (7948) | `00 00 35 80` = 13696 BE, then a stream | same shape (1.72×) | same |
| `PlyMotionNpcTown.rel` (21920) | **no magic**; 21920 = 1370 × 16 | first 512 bytes read as 32 records `{u32 slot, f32, f32, u32 0}` with slots 0,2,…,28,29 repeating per 16 (e.g. `(0, -0.014336, -0.662938, 0)`, `(2, -0.091859, -0.528747, 0)`) | from byte 512 the same words are denormals/NaN, so the record reading holds only for the first 512 bytes; layout and codec **unproven** |

### 3.4 `CharaMakingMot.bml` (158720 bytes)

A normal big-endian BML: `u32 BE` count at +4 = **49**, entry headers 0x40 bytes from 0x40, body from
`bml_start(49)` = **0x1000**, alignment 0x20 (`pso_player.bml_align`). Names are character-creation motions:
`pxuS01_B02_F_body.njm`, `pxuS01_B02_W_body.njm`, `pxuS01_C01_F_body.njm`, … `pxuZ00_A05_M_body.njm`. Every
entry PRS-decompresses to `NMDM`; frames 20, 20, 29, 40 for the first four. Tracks undecoded, as §3.1.

## 4. `GJTL` — the scene texture list (101 `.gj` files)

`.gj` is the scene counterpart of `.nj`: texture list (`GJTL`, the `NJTL` analogue), then the geometry chunk
(`GJCM`, the `NJCM` analogue), each followed by a `POF0`. `GJTL` body layout (identical to `NJTL`,
`ninja.njtl` at `ninja.py:134-146`):

| off | type | value on this disc |
|---|---|---|
| 0x00 | u32 BE | **8** — offset of the entry array (8 in all 101 files) |
| 0x04 | u32 BE | count |
| 0x08 + 12·i | u32 BE | name offset |
| +4 | u32 BE | attr — **0 in all 234 names** |
| +8 | u32 BE | addr — **0 in all 234 names** |
| … | | NUL-terminated names |

The `POF0` after a `GJTL` covers exactly `count + 1` fields: the array pointer at body+0 and each entry's name
pointer at body+8+12·i. `map_forest01s.gj`: `POF0` body `40 42 00 00` → fields at 0 and 8 → values 8 and 20;
the name sits at body+20.

`Scene/map_forest01s.gj` in full (1944 bytes): `GJTL` size 32, count **1**, and the single texture name is
**`k128sora`**. That is the whole texture list of the forest01 scene file. Fleet-wide the 101 `.gj` hold
**234 names, 72 distinct**, per-file counts {1: 62, 2: 20, 5: 4, 6: 7, 7: 1, 8: 1, 9: 5, 10: 1}. The largest
list is `Scene/map_boss05s.gj` (10): `hh008_tenkyuu04_d`, `hh008_tenkyuu04_d_04`, `hh032_tenkyuu03_d`,
`hh032_tenkyuu03_d_03`, `hh256_ten_kumo01_c`, `hh256_tenkyuu01_d`, `hh256_tenkyuu01_d_01`,
`hh256_tenkyuu02_d`, `hh256_tenkyuu02_d_02`, `hh256_tenkyuu_d_kumo`. Other singles:
`Scene/map_forest02s.gj` = `k128_sora2men`, `Scene/map_cave01_00s.gj` = `am008sky`. The `_L`/`_i`/`_k`/`_m` suffixes are texture variants (**unproven** which).

`GJCM` parses with `ninja.tree_nodes(payload, 0, ">")` — the same 52-byte `NJS_OBJECT` layout as `NJCM`, root
at 0 with flags `0x0f`. `Scene/map_boss05s.gj` = **6 nodes** (root + models at 0x70, 0xfb8, 0x1ad8, 0x25d8,
0x2f18). Fleet-wide the 101 `GJCM` total 360288 bytes and 136 nodes, 1-6 per file (largest node count is
boss05s, 6; largest `GJCM` is `Scene/map_seabed01_00s.gj`, 19104 bytes, 1 node). `.gj` also appears **inside**
packs: 601 `.gj` entries across the 299 `.bml`, e.g. `b_parts_b_parts01.gj` in `bm_ene_recobox_low.bml`
(GJTL count 1, name `y64_b_p_tex`).

```python
o = 0
while o + 8 <= len(data):                                    # data = a .gj
    tag = data[o:o+4]; size = struct.unpack_from("<I", data, o+4)[0]
    if tag == b"GJTL":
        b = data[o+8:o+8+size]; arr, n = struct.unpack_from(">II", b, 0)
        for i in range(n):
            p = struct.unpack_from(">I", b, arr + 12*i)[0]
            print(b[p:b.index(b"\0", p)].decode("latin-1"))
    o += 8 + size
```

## 5. Player model banks

19 class letters carry files: `A..L` (the 12 playable classes, `pso_gc.py:43-45`) and `S..Y`. `M..Q` are
absent; `S..Y` have a body, one head and 0-1 hair models and their identity is **unproven** (no name table).
Per class: one `pl<X>bdy00.nj`, `pl<X>hedNN.nj`, `pl<X>haiNN.nj`, `pl<X>capNN.nj`, mirrored by `pl<X>nj.bml`
(big-endian, 0x800-aligned entries: `bml_align` → 0x800, `bml_start(n)` = `(0x40 + 0x40n + 0x7FF) & ~0x7FF`).

| L | class | body bytes | sha256[0:16] | nodes | verts | tris | tex ids | hed | hai | cap | BML entries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | HUmar | 21308 | `4ee024d13d1e39cd` | 64 | 269 | 692 | 5 | 1 | 10 | **2** | 13 |
| B | HUnewearl | 28724 | `bfd3b1e8db292da4` | 64 | 356 | 816 | 8 | 1 | 10 | 0 | 12 |
| C | HUcast | 24732 | `5e3e307b8ef24b09` | 64 | 311 | 804 | 5 | 5 | 0 | 0 | 6 |
| D | RAmar | 21024 | `f59d9180edc24bb1` | 64 | 244 | 694 | 5 | 1 | 10 | 10 | 22 |
| E | RAcast | 25404 | `a0af05a58435693e` | 64 | 346 | 841 | 6 | 5 | 0 | 0 | 6 |
| F | RAcaseal | 23360 | `712d61e2765747e6` | 64 | 282 | 701 | 5 | 5 | 0 | 0 | 6 |
| G | FOmarl | 27248 | `159c9b67b65d4d75` | 64 | 297 | 746 | 5 | 1 | 10 | 10 | 22 |
| H | FOnewm | 23528 | `c5ffa13be62180ed` | 64 | 303 | 735 | 5 | 1 | 10 | 10 | 22 |
| I | FOnewearl | 25184 | `4250a06c74b7f3a4` | 64 | 282 | 713 | 5 | 1 | 10 | 10 | 22 |
| J | HUcaseal | 25180 | `8b9c095850fcc391` | 64 | 325 | 816 | 4 | 5 | 0 | 0 | 6 |
| K | RAmarl | 27932 | `337c9b83e4d42bee` | 64 | 389 | 835 | 5 | 1 | 10 | 10 | 22 |
| L | FOmar | 25612 | `530ab416bfed5bb2` | 64 | 331 | 835 | 4 | 1 | 10 | 10 | 22 |
| S | — | 24472 | `82e2f69eb7abe7f5` | 64 | 304 | 728 | 4 | 1 | 1 | 0 | 3 |
| T | — | 25948 | `831ede1394adf36e` | 64 | 314 | 761 | 4 | 1 | 1 | 0 | 3 |
| U | — | 18192 | `92da8cb323c007bd` | 64 | 179 | 468 | 2 | 1 | 0 | 0 | 2 |
| V | — | 14920 | `0b73f855517c80ed` | 64 | 136 | 406 | 2 | 1 | 0 | 0 | 2 |
| W | — | 14872 | `948252d445fc5f4d` | 64 | 139 | 418 | 2 | 1 | 0 | 0 | 2 |
| X | — | 25024 | `c9fb3f37dd57eda2` | 64 | 303 | 723 | 2 | 1 | 0 | 0 | 2 |
| Y | — | 29756 | `3c4fb28cff396173` | 64 | 326 | 739 | 3 | 1 | 0 | 0 | 2 |

All 19 bodies are the 64-node tree (`pso_player.PLAYER_PARENTS`, `pso_player.py:132-134`), 64 nodes every time.
BML entry counts reconcile with the loose files (1 body + hed + hai + cap): A has 14 loose files but **13**
pack entries — `plAcap09.nj` is loose but **not** in `plAnj.bml`, which carries `plAbdy00.nj`, `plAcap06.nj`,
`plAhai00..09.nj`, `plAhed00.nj`. D/G/H/I/K/L: 22 = 1+1+10+10. Androids C/E/F/J: 6 = body + 5 heads, no
hair/cap. S..Y: 2-3.

Role map verified on `plAbdy00.nj` (`pso_player.PLAYER_ROLES`, `pso_player.py:135-137`):

```python
from gbox import pso_gc as G, pso_player as P
from gbox.pso_enemy import vertex_owners
body = d.read("plAbdy00.nj"); nj = G.read_nj(body); nodes = G.tree(body)
print(len(nodes), len(nj.bones), len(nj.vbuf), sum(len(t) for t in nj.tris.values()))   # 64 64 269 692
vo = vertex_owners(nj)
print(P.check_roles([nd["parent"] for nd in nodes], [[b["m"][k][3] for k in range(3)] for b in nj.bones],
                    P.PLAYER_ROLES, vo))                                                   # []
print({r: vo[i] for r, i in P.PLAYER_ROLES.items()})
```

`check_roles` returns `[]` and every role node draws vertices: hip 2:20, chest 25:67, head 56:8, l_upper 28:46,
l_fore 29:26, l_hand 34:31, r_upper 41:24, r_fore 42:10, r_hand 47:31, l_thigh 4:23, l_shin 5:17, l_foot 8:11,
r_thigh 13:23, r_shin 14:17, r_foot 17:11. `pso_gc.class_roles("A")` adds the three joints `neck` 55,
`l_clav` 26, `r_clav` 39 (`pso_gc.py:371,386`) and checks the mirrored clavicles and chest→neck→head chain.

**Parser trap:** `pso_player.body_roles` (`pso_player.py:154-167`) is the *Dreamcast* path — it reads the
`NJCM` size little-endian at +4 and calls `ninja.NJ(body_file)` without `be=True`. On a GC body it raises
`struct.error: ... at least 202244104 bytes` (byte-swapped 21168). Use `pso_gc.class_roles` for GC bytes.

## 6. Enemy model packs

**17** `bm_ene_*.bml` on the disc (the count `pso_enemy.py:6` states), but every path in `pso_enemy.PACKS` and
`BOOMA_PACK` is **absent** — `PSO/BM_ENE_BM1_SHARK_A.BML` and its 15 siblings: 0 files; there is no `PSO/`
directory at all (0 files, 198 `.nj` at the root). `bm_ene_bm1_shark_a.bml` therefore cannot be proven from
this image, and the 51-node Booma role map (`pso_enemy.py:59-72`) does not apply.

| pack | entries | bodies | motions |
|---|---|---|---|
| `bm_ene_abgc01_wola_body_low.bml` | 11 | 2 | 9 |
| `bm_ene_biter_body_low.bml` | 11 | 1 | 10 |
| `bm_ene_bm9_s_mericarol_low.bml` | 9 | 1 | 8 |
| `bm_ene_common_all.bml` | 1 | 1 | 0 |
| `bm_ene_gi_gue_low.bml` | 12 | 3 | 9 |
| `bm_ene_gibbles_low.bml` | 11 | 1 | 10 |
| `bm_ene_ill_gill.bml` | 11 | 1 | 10 |
| `bm_ene_lappy_ap.bml` / `_ap_es` / `_ap_hw` / `_ap_xs` / `_es` / `_hw` / `_xs` | 12 each | 2 each | 10 each |
| `bm_ene_re4_sorcerer.bml` / `_a` | 10 each | 2 each | 8 each |
| `bm_ene_recobox_low.bml` | 16 | 3 `.nj` + 3 `.gj` | 10 |

**Proof pack — `bm_ene_abgc01_wola_body_low.bml`** (211392 bytes; Booma-family analog, "wola" being the JP
name — mapping **unproven**): 11 entries, alignment 0x20: `lo_abgc01_wola_body.nj`, `lo_abgc01l_wola_body.nj`,
`atack_l_…`, `atack_r_…`, `damage_…`, `dead_…`, `odori_…`, `wait_…`, `wait2_…`, `wake_…`, `walk_…`
(`…_abgc01_wola_body.njm`). Entry fields: `{csize 16507, f1 0, dsize 23284, cgvm 60407, dgvm 65680}`, then
`{16504, 30, 23320, 61135, 65680}`; motions carry `f1 = 60`.

```python
from gbox import ninja, pso_player as P
bml = d.read("bm_ene_abgc01_wola_body_low.bml")
e = next(x for x in P.bml_files(bml, ">") if x["name"].split(b"\0")[0] == b"lo_abgc01_wola_body.nj")
raw = ninja.prs_decompress(e["raw"])            # 23284: NJTL + POF0 + NJCM + POF0
nj = ninja.NJ(raw, be=True)
print(ninja.njtl(raw, be=True))                 # ['s256_bmika01', 's256_bmika02']
print(len(nj.bones), len(nj.vbuf), sum(len(t) for t in nj.tris.values()))   # 74 270 491
```

The body has **74 nodes**, 270 vertex-cache slots, 491 triangles, 2 texture ids, and a `GVMH` archive behind it
in the same entry (65680 bytes decompressed from `cgvm` 60407). `lo_abgc01l_wola_body.nj` has the same 74-node
tree, 270 verts, 495 triangles, textures `s256_bmika01l`/`s256_bmika02l`. Part order is exactly what
`pso_enemy.py:7-8` describes for the Dreamcast packs: `NJTL` (60) + `POF0` (4) + `NJCM` (23012) + `POF0` (176).

Its 9 motions (decompressed, all `NMDM`):

| entry | bytes | LE size | mdata | frames | type | inp |
|---|---|---|---|---|---|---|
| `atack_l_…` / `atack_r_…` | 8172 / 8084 | 8108 / 8020 | 12 | 20 | 3 | 2 |
| `damage_…` | 8136 | 8076 | 12 | 20 | 3 | 2 |
| `dead_…` | 10844 | 10780 | 12 | 31 | 3 | 2 |
| `odori_…` | 8236 | 8172 | 12 | 20 | 3 | 2 |
| `wait_…` / `walk_…` | 11512 / 11512 | 11452 / 11452 | 12 | 30 | 3 | 2 |
| `wait2_…` / `wake_…` | 12500 / 13012 | 12428 / 12940 | 12 | 30 | **7** | **3** |

A 74-node body with 20-31-frame clips is 8-13 KB — ≈ 408 bytes per frame, i.e. ≈ 5.5 bytes per node-frame if all 74 nodes are keyed, consistent with `type 3` = position + rotation keys (**unproven**).

Two BML-level facts any writer needs:

* **one little-endian pack exists.** 298 of 299 `.bml` have a big-endian count; `fe_obj_hira_kage.bml` has
  `u32 LE` 42 at +4 (`u32 BE` 704643072) and `bml_files(data, ">")` raises on it.
* **`dsize == 0` means stored, not compressed.** 6 `.njm` entries in `bm_technic.bml` carry
  `{csize 376..728, f1 0, dsize 0}` and their body already starts with `NMDM`; the predicate
  `prs_decompress(raw) if csize != dsize else raw` (`pso_enemy.py:195`, `pso_gc.py:124`) tries PRS on them and
  raises `IndexError`. The correct test is `dsize == 0 → raw`.

Across the 299 packs: 461 `.nj` entries, 601 `.gj`, 762 `.njm` (121 packs have motions).

## 7. What is not proven

| # | open item |
|---|---|
| 1 | `NMDM` track records: which field is the frame and which the value, and how `mdata` (always 12) indexes per-node tables. No PSO GC motion decoder exists in the repo. |
| 2 | `.rlc` and `.cpt` payload codecs (neither PRS nor zlib). |
| 3 | `PlyMotionNpcTown.rel` from byte 512 on (the 16-byte record reading holds only for the first 32 records). |
| 4 | `GJCM` beyond "52-byte `NJS_OBJECT` tree that `tree_nodes` parses": the 0x0f/0x17 flag split, scene material chunks, and how a `.njm` selects a scene node (no mapping found). |
| 5 | `NMDM` type bits `0x2000` (6 entries) and `inp` values 66/3. |
| 6 | The identity of the extra class letters `S..Y` and of the `_L`/`_i`/`_k`/`_m` texture suffixes. |
| 7 | Why `plAcap09.nj` is loose but absent from `plAnj.bml`, and how 10 hair slots map onto 2 cap files for class A. |
| 8 | The BML `f1` field (0 on bodies, 30/60 on motions) — plausibly a frame rate or subtype. |
| 9 | `pso_enemy.PACKS` names for this disc (all 16 absent) and the Booma role map against the 74-node `abgc01_wola` tree. |

## 8. Re-running any of this

```python
import struct, sys; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
from gbox import ninja, pso_gc as G, pso_player as P
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
print(len(d.files), d.game_id)                                          # 3510 GPOE8P

data = d.read("plAbdy00.nj"); payload = G.njcm_payload(data)[1]
print(len(G.tree(data)), len(G.read_nj(data).vbuf))                     # 64 nodes, 269 verts
for nd in G.tree(data)[:3]:                                             # model: vlist, plist, centre, radius
    if nd["model"]: print(nd["model"], struct.unpack_from(">II4f", payload, nd["model"]))
for f in sorted(n for n in d.files if n.lower().endswith(".njm")):      # every motion header
    b = d.read(f); print(f, struct.unpack_from("<I", b, 4)[0], struct.unpack_from(">IIHH", b, 8))
```

Anchors for a fresh run: 198 `.nj` (all `NJCM`+`POF0`), 101 `.gj` (234 names, 136 `GJCM` nodes), 9 loose `.njm`
+ 762 in packs, 299 `.bml` (298 BE / 1 LE), 19 player letters (12 classes + `S..Y`), 17 `bm_ene_*` packs,
`plAbdy00.nj` = 21308 bytes / sha256 `4ee024d13d1e39cd…` / 64 nodes / 269 verts / 692 tris.
