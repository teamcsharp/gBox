# RE4 Switch (HD port) BIN meshes — decoded

Status: **the HD BIN decodes**. `gbox/re4hd_models.py` reads one BIN slot into bones, positions, UVs, colours,
weight sets, per-vertex weight indices and typed primitive runs, with a structural self-check that raises
`BINError` instead of returning a plausible-looking mesh.

Measured 2026-11-07 against the extracted RomFS
`/home/ehm_eckx/gBox_alt/switch/romfs/010099A00BC1E000` (title `010099A00BC1E000`, 162 `.udas` packs,
2,727 BIN slots).  Nothing on the Spark was written outside `~/gBox_alt/re4-lab/`.

The GameCube reader (`gbox/re4gc_models.py`) does **not** apply: the containers (UDAS/DAT) are the same as the GC
disc, but the mesh BIN is re-laid. The HD BIN header is 0x98 and every field is little-endian.

---

## 1. Header map

All offsets are in the BIN slot. "u64\*" = a 64-bit little-endian file offset whose high dword is zero in all
2,727 slots; the reader *requires* the high dword to be zero (a file that fails it is refused).

| offset | type | meaning | how it was proved |
|---|---|---|---|
| 0x00 | u32 | header size = **0x98** = bone-table offset | every slot in 2,727 starts with 0x98; the GC 0x40/0x60 is refused by name |
| 0x0C | u32 | 0x50 (100 slots) or 0 | **unknown** (constant) |
| 0x10 | u64\* | vertex colours, **RGBA8, 4 B/vertex** | span = exactly 4·n (+<32 B pad to the next table) in every decoded slot; content is constant 0xFFFFFFFF or 0x01010101 |
| 0x18 | u64\* | UVs, **2 × f32, 8 B/vertex** | span = exactly 8·n; all values in [0,1] on a 1/256 grid |
| 0x20 | u64\* | weight sets, **8 B/record, GC record layout** | see §3 |
| 0x28 | u32 | packed (0x00020101, 0x000320BC, 0x00210A0A …) | **unknown** |
| 0x30 | u64\* | **material + primitive table**, last section of the file | see §4 |
| 0x38 | u32 | 0x80000000 / 0xA0000N00 (GX-attribute shaped) | **unknown** |
| 0x3C | u16 | small count 1..8 | **unknown** |
| 0x40 | u16 ×2 | (4\|5\|6, small count) | **unknown** |
| 0x48 | u64\* | positions, **3 × f32, 12 B/vertex** | see §2 |
| 0x50 | u64\* | second per-vertex stream, 12 B/vertex — **not** claimed as normals, see §6 | span = exactly 12·n in every decoded slot; two encodings |
| 0x58 | u16 | **vertex count** (the high u16 repeats it) | see §2 |
| 0x5C | u32 | 0x20030818 (most) / 0x20010801 (em06 class) — the variant selector that goes with the 0x50 encoding | correlation only, **not proved** |
| 0x60, 0x68 | u64\* | present in 65 / 100 of 122 probed BINs, 32..96 B | **unknown** |
| 0x70 | u64\* | **weight index, u16 per vertex** | `max(0x70) < 0x20 record count` in every decoded slot; all zero for single-bone props |
| 0x78 | u64\* | byte-identical to the 0x70 array | duplicate reference (measured identical) |
| 0x80, 0x84 | u32 | a pair of pointers, always exactly `0x70-56` / `0x78-56` | they point **inside** the 0x48/0x50 arrays, so they are not table starts; **meaning unknown** |
| 0x98 | — | **bone table**, 16 B/record: `u8 id, u8 parent, 2 pad, 3 × f32 translation` | see §5 |

Sections are 32-byte aligned in the file; a table's span is "up to the next table start", and the span is checked
against `count × stride` (a mismatch of one vertex is refused).

## 2. Vertex count and positions (`0x58`, `0x48`)

`n = u16 at 0x58`. Positions are `n` consecutive `f32 xyz` triples from `0x48` and then stop dead — the walk
stops on the first triple that is not a vertex. Measured: the number of consecutive triples equals `0x58`
exactly on every slot tried (em06 5630, em21 2725, em10 slots 158/256/351/392/394 = 59/531/1482/1618/305).

Cross-check against the GameCube disc (same slot, GC reader):

| slot | HD vertex count | GC positions | GC positions found in the HD array |
|---|---|---|---|
| em21.udas 0 | 2725 | 1007 | 1007 / 1007 |
| em10.udas 351 | 1482 | 581 | 581 / 581 |
| em10.udas 256 | 531 | 232 | 232 / 232 |
| em10.udas 158 | 59 | 25 | 25 / 25 |

So the HD file holds *the same geometry*, split per corner (more vertices) and reordered — the unique HD
position set equals the GC position set. The bounding boxes are therefore identical, e.g. em10.158
x −30.91..44.75, y −27.64..27.64, z −376.17..121.52 on both editions.

## 3. Weight sets (`0x20`) and weight indices (`0x70`)

The weight record is the **GC record, byte for byte**: `b0, b1, b2, cnt, w0, w1, w2, pad` (8 × u8). em06 record 0
is `19 00 00 01 64 00 00 00` = one bone (25) at 100 %; record 1 is `18 19 00 02 50 13 00 00` = bones 24 and 25 at
80 % / 19 % — the classic RE4 pair weight (which sums to 99, so the reader accepts any 1..100 sum).

`0x70` holds one u16 index into that table per vertex. em06: 5,630 indices, max 96, table has 100 records.
em21: 2,725 indices, max 187, table has 188 records. em10.351: max 9, 12 records.

## 4. Materials and primitives (`0x30`)

The table is the last section of the file. Per material:

```
0x00  8 zero bytes
0x0B  material id                 (u8)
0x0C  uv set                      (u8)      -- 0 in every slot measured
0x0D  ff ff ff  ... 0x17 = ff               -- the record marker the reader keys on
0x18  u32 display-list size       = floor((0x24 + 4*nprim) / 32) * 32
0x1C  u32 triangle count
0x20  u32 primitive count
0x24  nprim × (u16 type, u16 nverts)
```

Records are 32-byte aligned **relative to the table start**; the record stride is `round_up(0x24 + 4*nprim, 32)`.
The primitive vertex counts **partition the whole vertex array**: vertices are consumed sequentially in
material/primitive order and every vertex is used exactly once.

Primitive types (fitted over 8 slots with a residual of 0, and cross-checked against the header count and the GC
triangle count):

| type | kind | triangles |
|---|---|---|
| 5 | triangle list | n / 3 |
| 6 | triangle strip | n − 2 (alternating winding) |
| 8 | quads | n / 2 |

## 5. Bones (`0x98`)

16-byte records up to the weight table at `0x20`, trailing all-zero records trimmed:
`u8 id, u8 parent, 2 pad, 3 × f32 translation` (parent-relative, bind pose — same convention as the GC BIN).

Invariants checked: ids are non-decreasing and step by at most 1 (a second root may repeat an id, e.g. em10.394
slot 10 = `(9, 0xFF, …)`), every parent is `< id` or 0xFF, and the table has a root. Bone counts match the GC disc
exactly where the same pack exists: em21 = 32, em10.351 = 10, em10.394 = 39, em10.256 = 2, em10.158 = 1.

A BIN whose bone table starts above id 0 is a **part of a shared skeleton** (its weight records index the shared
palette, not the local table); the reader recognises that and skips the table-local index check.

**Sanity check against `gbox/rig_roles.py`**: feeding the decoded bind-pose joints and parents in gives all 16
humanoid roles for em21 (32 bones) and 14 for em06 (34 bones, no hands), i.e. the mirrored arm/leg pairs and the
spine come out right — a wrong parent chain or a wrong translation layout would not produce that.

## 6. What is decoded with numbers (real packs, read-only)

Full self-check passed; "height" is the y extent of the bind pose in the file's own units (cm).

| pack / slot | bytes | vertices | triangles | bones | materials | bbox (min .. max) | height |
|---|---|---|---|---|---|---|---|
| em06.udas 0 | 228,768 | 5,630 | 4,202 | 34 | 3 | (−1316.7, −9.2, −145.1) .. (1316.9, 1635.1, 476.3) | 1644.3 |
| em21.udas 0 | 112,384 | 2,725 | 1,843 | 32 | 3 | (−167.4, −49.8, −713.7) .. (168.7, 1024.0, 992.9) | 1073.8 |
| em10.udas 158 | 2,848 | 59 | 41 | 1 | 2 | (−30.9, −27.6, −376.2) .. (44.8, 27.6, 121.5) | 55.3 |
| em10.udas 256 | 22,080 | 531 | 379 | 2 | 4 | (−90.1, −75.7, −296.6) .. (175.9, 205.1, 619.2) | 280.8 |
| em10.udas 351 | 62,208 | 1,482 | 822 | 10 | 33 | (−392.3, −37.5, −705.3) .. (392.3, 354.8, 739.6) | 392.3 |
| em10.udas 392 | 66,080 | 1,618 | 1,068 | 3 | 10 | (−899.3, −161.6, −71.1) .. (486.0, 89.5, 71.4) | 251.1 |
| em10.udas 394 | 13,472 | 305 | 217 | 39 | 1 | (−838.4, 1456.6, −62.6) .. (−707.3, 1568.6, 33.4) | 112.0 |

Triangle counts and material counts equal the GameCube disc's for the same slot (em21 1,843 / 3; em10.158 41 / 2;
em10.256 379 / 4; em10.351 822 / 33; em10.392 1,068 / 10; em10.394 217 / 1). The HD port re-split the vertices;
the topology is the same.

Note the units are the file's: em21 is 10.7 m tall and em06 16.4 m, so those two are *not* humanoid enemies at
1 unit = 1 cm — em10's props (55 cm, 112 cm, 251 cm, 392 cm) are the ones that read as centimetres. Do not assume
a scale without checking a known character.

## 7. Coverage over the whole tree

2,727 BIN slots in 162 packs were run through the reader (read-only, on the Spark):

* **2,188 slots decode** with every self-check passing (1,873,779 vertices, 1,313,085 triangles, largest rig 225
  bones).
* **539 slots are refused** with a named reason. They are not silently mis-decoded. Classes:
  * ~66 `no HD material record` — the 0x30 table does not start with the record marker (a second table variant);
  * ~150 `weight record … references bone …` — the weight records index a palette that is not the local table and
    the table starts at id 0, so the shared-skeleton heuristic does not fire;
  * ~250 `primitive vertex counts sum to X, the BIN declares Y` — the material walk stops short (an unrecorded gap
    between records, or a second primitive-table layout).

## 8. Unknown / not decoded

* **Normals are not decoded.** The 0x50 stream is the only per-vertex 3-vector left and it is decoded
  byte-exactly, but it comes in two encodings and its magnitude convention is not pinned down:
  * em06 class (`0x5C = 0x20010801`): three `f32` per vertex, e.g. `-13440.0, -1313.0, -9264.0`; divided by
    16384 that is a unit vector.
  * em10/em21 class (`0x5C = 0x20030818`): three `s16` in the **high half** of each 32-bit slot (low half zero),
    e.g. `-11598, -11598, 0`; divided by 16384 the first vertex is unit but over a mesh the magnitudes run
    0.7 .. 2.2, the range of a *sum of face normals* rather than a unit normal.
  Recomputing normals from the decoded triangles reaches only mean |dot| 0.68..0.86 against this stream under
  every winding convention tried, so the reader reports it as `aux` with `encoding` and the numbers in 1/16384
  units, and `Bin.normals()` **derives** geometric normals from the triangles for callers that need them.
* `0x28`, `0x38`, `0x3C`, `0x40`, `0x5C` semantics (packed flags), `0x60`/`0x68` (32..96 B tables), `0x80`/`0x84`
  (56-byte records that straddle the end of the 0x48/0x50 arrays).
* Textures: the HD "TPL" starts with `0x12345678`, not the GX `0x0020AF30`, so `gbox/re4gc_models.tpl_read` does
  not apply. Not attempted here.
* The 539 refused slots above (see §7 for the classes).
* `gbox/rig_roles.py` / `gbox/re4gc_zombies.py` are **not** wired to this reader; the roles do derive from the
  decoded rig (see §5), which is the gate the GC pipeline needed, but the swap itself is out of scope here.

## 9. Reading one slot

```python
from gbox import re4gc_inventory as I, re4hd_models as H

pack = open("em06.udas", "rb").read()
dat = pack[next(e["offset"] for e in I.udas_entries(pack, "<") if e["type"] == 0):]
m = H.load_slot(dat, 0)                 # or H.bin_read(slot_bytes)
m.info["checks"]                        # the self-check that ran
len(m.bones), m.n_verts, m.n_tris, m.bbox()
m.pos, m.uv, m.colors, m.weight_idx, m.weights, m.mats
```
