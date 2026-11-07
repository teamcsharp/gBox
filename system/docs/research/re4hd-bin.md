# RE4 Switch (HD port) BIN meshes â€” decoded

Status: **the HD BIN decodes and re-encodes.** `gbox/re4hd_models.py` reads one BIN slot into bones, positions, UVs,
colours, weight sets, per-vertex weight indices and typed primitive runs, with a structural self-check that raises
`BINError` instead of returning a plausible-looking mesh.  The writer (`bin_write`/`bin_from`/`pad_to`, Â§10) is
byte-identical on every slot the reader accepts.

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
| 0x10 | u64\* | vertex colours, **RGBA8, 4 B/vertex** | span = exactly 4Â·n (+<32 B pad to the next table) in every decoded slot; content is constant 0xFFFFFFFF or 0x01010101 |
| 0x18 | u64\* | UVs, **2 Ã— f32, 8 B/vertex** | span = exactly 8Â·n; all values in [0,1] on a 1/256 grid |
| 0x20 | u64\* | weight sets, **8 B/record, GC record layout** | see Â§3 |
| 0x28 | u32 | packed (0x00020101, 0x000320BC, 0x00210A0A â€¦) | **unknown** |
| 0x30 | u64\* | **material + primitive table**, last section of the file | see Â§4 |
| 0x38 | u32 | 0x80000000 / 0xA0000N00 (GX-attribute shaped) | **unknown** |
| 0x3C | u16 | small count 1..8 | **unknown** |
| 0x40 | u16 Ã—2 | (4\|5\|6, small count) | **unknown** |
| 0x48 | u64\* | positions, **3 Ã— f32, 12 B/vertex** | see Â§2 |
| 0x50 | u64\* | second per-vertex stream, 12 B/vertex â€” **not** claimed as normals, see Â§6 | span = exactly 12Â·n in every decoded slot; two encodings |
| 0x58 | u16 | **vertex count** (the high u16 repeats it) | see Â§2 |
| 0x5C | u32 | 0x20030818 (most) / 0x20010801 (em06 class) â€” the variant selector that goes with the 0x50 encoding | correlation only, **not proved** |
| 0x60, 0x68 | u64\* | present in 65 / 100 of 122 probed BINs, 32..96 B | **unknown** |
| 0x70 | u64\* | **weight index, u16 per vertex** | `max(0x70) < 0x20 record count` in every decoded slot; all zero for single-bone props |
| 0x78 | u64\* | byte-identical to the 0x70 array | duplicate reference (measured identical) |
| 0x80, 0x84 | u32 | a pair of pointers, always exactly `0x70-56` / `0x78-56` | they point **inside** the 0x48/0x50 arrays, so they are not table starts; **meaning unknown** |
| 0x98 | â€” | **bone table**, 16 B/record: `u8 id, u8 parent, 2 pad, 3 Ã— f32 translation` | see Â§5 |

Sections are 32-byte aligned in the file; a table's span is "up to the next table start", and the span is checked
against `count Ã— stride` (a mismatch of one vertex is refused).

## 2. Vertex count and positions (`0x58`, `0x48`)

`n = u16 at 0x58`. Positions are `n` consecutive `f32 xyz` triples from `0x48` and then stop dead â€” the walk
stops on the first triple that is not a vertex. Measured: the number of consecutive triples equals `0x58`
exactly on every slot tried (em06 5630, em21 2725, em10 slots 158/256/351/392/394 = 59/531/1482/1618/305).

Cross-check against the GameCube disc (same slot, GC reader):

| slot | HD vertex count | GC positions | GC positions found in the HD array |
|---|---|---|---|
| em21.udas 0 | 2725 | 1007 | 1007 / 1007 |
| em10.udas 351 | 1482 | 581 | 581 / 581 |
| em10.udas 256 | 531 | 232 | 232 / 232 |
| em10.udas 158 | 59 | 25 | 25 / 25 |

So the HD file holds *the same geometry*, split per corner (more vertices) and reordered â€” the unique HD
position set equals the GC position set. The bounding boxes are therefore identical, e.g. em10.158
x âˆ’30.91..44.75, y âˆ’27.64..27.64, z âˆ’376.17..121.52 on both editions.

## 3. Weight sets (`0x20`) and weight indices (`0x70`)

The weight record is the **GC record, byte for byte**: `b0, b1, b2, cnt, w0, w1, w2, pad` (8 Ã— u8). em06 record 0
is `19 00 00 01 64 00 00 00` = one bone (25) at 100 %; record 1 is `18 19 00 02 50 13 00 00` = bones 24 and 25 at
80 % / 19 % â€” the classic RE4 pair weight (which sums to 99, so the reader accepts any 1..100 sum).

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
0x24  nprim Ã— (u16 type, u16 nverts)
```

Records are 32-byte aligned **relative to the table start**; the record stride is `round_up(0x24 + 4*nprim, 32)`.
The primitive vertex counts **partition the whole vertex array**: vertices are consumed sequentially in
material/primitive order and every vertex is used exactly once.

Primitive types (fitted over 8 slots with a residual of 0, and cross-checked against the header count and the GC
triangle count):

| type | kind | triangles |
|---|---|---|
| 5 | triangle list | n / 3 |
| 6 | triangle strip | n âˆ’ 2 (alternating winding) |
| 8 | quads | n / 2 |

## 5. Bones (`0x98`)

16-byte records up to the weight table at `0x20`, trailing all-zero records trimmed:
`u8 id, u8 parent, 2 pad, 3 Ã— f32 translation` (parent-relative, bind pose â€” same convention as the GC BIN).

Invariants checked: ids are non-decreasing and step by at most 1 (a second root may repeat an id, e.g. em10.394
slot 10 = `(9, 0xFF, â€¦)`), every parent is `< id` or 0xFF, and the table has a root. Bone counts match the GC disc
exactly where the same pack exists: em21 = 32, em10.351 = 10, em10.394 = 39, em10.256 = 2, em10.158 = 1.

A BIN whose bone table starts above id 0 is a **part of a shared skeleton** (its weight records index the shared
palette, not the local table); the reader recognises that and skips the table-local index check.

**Sanity check against `gbox/rig_roles.py`**: feeding the decoded bind-pose joints and parents in gives all 16
humanoid roles for em21 (32 bones) and 14 for em06 (34 bones, no hands), i.e. the mirrored arm/leg pairs and the
spine come out right â€” a wrong parent chain or a wrong translation layout would not produce that.

## 6. What is decoded with numbers (real packs, read-only)

Full self-check passed; "height" is the y extent of the bind pose in the file's own units (cm).

| pack / slot | bytes | vertices | triangles | bones | materials | bbox (min .. max) | height |
|---|---|---|---|---|---|---|---|
| em06.udas 0 | 228,768 | 5,630 | 4,202 | 34 | 3 | (âˆ’1316.7, âˆ’9.2, âˆ’145.1) .. (1316.9, 1635.1, 476.3) | 1644.3 |
| em21.udas 0 | 112,384 | 2,725 | 1,843 | 32 | 3 | (âˆ’167.4, âˆ’49.8, âˆ’713.7) .. (168.7, 1024.0, 992.9) | 1073.8 |
| em10.udas 158 | 2,848 | 59 | 41 | 1 | 2 | (âˆ’30.9, âˆ’27.6, âˆ’376.2) .. (44.8, 27.6, 121.5) | 55.3 |
| em10.udas 256 | 22,080 | 531 | 379 | 2 | 4 | (âˆ’90.1, âˆ’75.7, âˆ’296.6) .. (175.9, 205.1, 619.2) | 280.8 |
| em10.udas 351 | 62,208 | 1,482 | 822 | 10 | 33 | (âˆ’392.3, âˆ’37.5, âˆ’705.3) .. (392.3, 354.8, 739.6) | 392.3 |
| em10.udas 392 | 66,080 | 1,618 | 1,068 | 3 | 10 | (âˆ’899.3, âˆ’161.6, âˆ’71.1) .. (486.0, 89.5, 71.4) | 251.1 |
| em10.udas 394 | 13,472 | 305 | 217 | 39 | 1 | (âˆ’838.4, 1456.6, âˆ’62.6) .. (âˆ’707.3, 1568.6, 33.4) | 112.0 |

Triangle counts and material counts equal the GameCube disc's for the same slot (em21 1,843 / 3; em10.158 41 / 2;
em10.256 379 / 4; em10.351 822 / 33; em10.392 1,068 / 10; em10.394 217 / 1). The HD port re-split the vertices;
the topology is the same.

Note the units are the file's: em21 is 10.7 m tall and em06 16.4 m, so those two are *not* humanoid enemies at
1 unit = 1 cm â€” em10's props (55 cm, 112 cm, 251 cm, 392 cm) are the ones that read as centimetres. Do not assume
a scale without checking a known character.

## 7. Coverage over the whole tree

2,727 BIN slots in 162 packs were run through the reader (read-only, on the Spark):

* **2,188 slots decode** with every self-check passing (1,873,779 vertices, 1,313,085 triangles, largest rig 225
  bones).
* **539 slots are refused** with a named reason. They are not silently mis-decoded. Classes:
  * ~66 `no HD material record` â€” the 0x30 table does not start with the record marker (a second table variant);
  * ~150 `weight record â€¦ references bone â€¦` â€” the weight records index a palette that is not the local table and
    the table starts at id 0, so the shared-skeleton heuristic does not fire;
  * ~250 `primitive vertex counts sum to X, the BIN declares Y` â€” the material walk stops short (an unrecorded gap
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
* The 539 refused slots above (see Â§7 for the classes).
* `gbox/rig_roles.py` / `gbox/re4gc_zombies.py` are **not** wired to this reader; the roles do derive from the
  decoded rig (see Â§5), which is the gate the GC pipeline needed, but the swap itself is out of scope here.

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

## 10. Writer (2026-11-07)

The write half now lives beside the decoder in `gbox/re4hd_models.py`:

* `bin_write(m, verify=False)` â€” re-encode a decoded `Bin`.
* `bin_from(bin_, *, pos=..., uv=..., colors=..., tris=..., bones=..., weights=..., weight_idx=..., aux=...)`
  â€” build a BIN whose geometry comes from another source, returning bytes the decoder accepts.
* `pad_to(data, size)` â€” pad a replacement to the original slot size, or refuse if it is bigger.

### 10.1 How `bin_write` stays byte-exact

`bin_read` now keeps every section verbatim in `Bin.raw["sections"]` (plus the bone table in `Bin.raw["bones"]`,
the original order/starts, and signatures of the decoded bones and materials). `bin_write` writes those bytes back
and rebuilds only a section whose live values differ from what was decoded:

| live value | section rebuilt |
|---|---|
| `Bin.pos`, `Bin.uv`, `Bin.colors`, `Bin.weight_idx` | the fixed-stride arrays (the decoded tail after `n` vertices is kept) |
| `Bin.weights` | the 8-byte weight-set records |
| `Bin.aux` | the 0x50 stream (its own `Stream.raw` is the source of truth) |
| `Bin.bones` | the 16-byte bone records |
| `Bin.mats` | the material/primitive records, per-material headers preserved |

Nothing else is re-derived. The packed header words (`0x28`, `0x38`, `0x3C`, `0x40`, `0x5C`), the `0x60`/`0x68`
tables, the `0x80`/`0x84` pointers and the bytes after the last material record are copied. A header field whose
target did not move is not even rewritten, so its exact byte stays. (One measured quirk the writer handles: the
synthetic BINs alias `0x70`/`0x78` at one offset, while every real BIN measured keeps two separate copies; the
layout writes an aliased table once and keeps both fields pointing at it.)

### 10.2 Round-trip result over the real tree

Run read-only on the Spark (`~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/em/*.udas`), decoding each BIN with
`bin_read`, re-encoding with `bin_write`, comparing bytes:

| packs | BIN slots | decode | **byte-identical** | mismatch | refused |
|---:|---:|---:|---:|---:|---:|
| 162 | 2,727 | 2,188 | **2,188 (100 % of decoded)** | **0** | 539 |

That is 78,011,456 original bytes re-emitted exactly in 1.2 s. The refusal classes are unchanged from Â§7 (66 no
material record, ~250 primitive-count, ~200 shared-palette weight, plus bone-order refusals), i.e. the writer did
not change which files the decoder accepts.

Structure measured while checking the writer, useful for anyone reading a slot by hand:

* every decoded file is a multiple of 32 bytes; sections are contiguous from 0x98 to EOF (no gaps, no tail);
* every table start is `0x98 + 32k` (so `offset % 32 == 24`), and the first table is always `0x20` (weights);
* 432 slots use `0x5C = 0x20010801` with neither `0x60` nor `0x68`; the 1,756 `0x20030818` slots all have `0x68`
  (`extra_b`), and 958 of those also have `0x60` (`extra_a`).

**What mismatched and how it was resolved.** The real tree produced no mismatch on the final writer. The first
pass did fail on the synthetic fixture: `make_bin` points `0x70` and `0x78` at the same array, and a layout that
wrote each header field independently duplicated that table (+32 bytes, shifting every later section). Fixed by
treating equal decoded starts as one table. Separately, the synthetic multi-material fixture was not padding its
records to their 32-byte stride; that was a bug in the fixture, not the writer. No mismatch was papered over by
normalising both sides: the acceptance is raw bytes out == raw bytes in.

### 10.3 The two GameCube rules, carried over

1. **Pad every replacement to the original slot size.** `pad_to(data, size)` appends zero bytes (the GameCube
   `swap_ganados` path appends `b"\0"`) and raises `BINError` when the replacement is larger instead of truncating
   it. The reason is the same on Switch: the title reads the model in place, so a shorter file leaves the
   original's tail readable and the game draws the ORIGINAL mesh out of it even though the new header is valid.
   The measured slot sizes are 32-byte multiples, and trailing zeros do not disturb the decoder (the primitive walk
   stops at the first non-record), so padding is inert data.
2. **Never rewrite the model's bounding box.** The writer emits the positions the caller supplies; it never scales,
   recentres or clamps them to a box. The packed words that carry bounds/flags (`0x28`, `0x38`, `0x3C`, `0x40`) are
   preserved verbatim, so whatever box the surrounding slot carries is untouched. A rewritten box freezes the title
   (measured on the GameCube work). The HD 0x98 BIN has no explicit bbox field to rewrite, which makes the rule
   easy to honour and easy to violate by "helpfully" normalising positions â€” don't.

### 10.4 Source swap: measured result

The swap shape is:

```python
from gbox import re4hd_models as H
dst = H.bin_read(dst_slot_bytes)          # the slot whose header/bones/material headers are kept
src = H.bin_read(src_slot_bytes)          # the geometry donor
out = H.bin_from(dst, pos=src.pos, uv=src.uv, colors=src.colors, tris=src.tris)
assert len(out) <= len(dst_slot_bytes)
slot = H.pad_to(out, len(dst_slot_bytes))
```

When the source has the slot's vertex count and topology (`tris=None` or equal to `dst.tris`), the primitive
records are kept byte-for-byte and only the arrays are replaced. Otherwise `bin_from` spreads the source triangles
over the slot's material headers in proportion to their decoded triangle counts, emits type-5 lists in sequential
vertex order, and gathers the per-vertex arrays into that same order. Corners are duplicated (one vertex per
triangle corner), which is how the HD format already stores split vertices.

Read-only experiment on two real slots:

| | dst `pl00.udas` slot at 1,088 | src `em10.udas` slot at 2,481,504 |
|---|---:|---:|
| bytes | 142,336 | 22,080 |
| vertices / triangles | 3,425 / 2,519 | 531 / 379 |
| materials / bones | 14 / 119 | 4 / 2 |
| rebuilt result | **48,960 B**, 1,137 verts, 379 tris, 14 mats, primitive total 1,137 | |
| checks | bbox equals the source bbox, bones equal the destination's, `pad_to` = 142,336 B and re-decodes | |

The material triangle split for that run was
`[67, 64, 64, 8, 4, 7, 6, 83, 3, 31, 7, 7, 4, 24]` (sum 379), so every slot material header survived with at
least one primitive. A same-count run on the same character slot (translate its own positions, keep topology)
returned exactly 142,336 B with the material/primitive records and the packed header words byte-identical, and the
decoded bbox followed the translated positions â€” the writer did not touch a stored box.

The failure mode is honest: on a tiny 2,848-byte slot the 379-triangle source rebuilt to 46,016 B and `pad_to`
refused it (`replacement is 46016 B but the slot holds 2848 B`). A swap needs a destination slot with room, or a
smaller source/decimation pass.

### 10.5 What a character swap still needs

* **Textures are a separate problem.** The HD TPL magic is `0x12345678`, not the GX `0x0020AF30`, and it is **not
  decoded**. `bin_from` keeps the destination's material headers (material id, uv_set, markers) so the slot's
  texture bindings are at least not invented, but there is no TPL reader/writer and no materialâ†’texture mapping
  yet. A full skin swap needs both.
* **Skinning/retarget is not done.** `bin_from` keeps the slot's bone table, but the rebuilt vertices get a
  single-bone 100 % weight set by default. Source weights can be passed (`weights=`, `weight_idx=`) only if they
  already index the destination bone table; the GC retarget (`re4gc_enemies.retarget` / `rig_roles`) has not been
  wired to the HD rig.
* **Fitting.** The fresh rebuild duplicates a vertex per triangle corner, so a source with as many triangles as the
  destination can overflow the slot. Deduplication, strip encoding, a fitting ladder (collapse spare parts,
  thin primitives, smaller textures, as `re4gc_zombies.swap_ganados` does) and a size check before `pad_to` are
  still needed for a general swap.
* **The 0x50 stream** written for new geometry is zeros; its semantics are still unproven (Â§8). If the title uses
  it for normals/lighting, rebuilt meshes may shade wrong until that stream is understood.
* **In-game proof.** Nothing was deployed or restarted this round. The gate reached is: the rebuilt BIN decodes
  with every structural check, reports the new vertex/triangle/material numbers, and fits the original slot after
  `pad_to`. The Switch title has not been asked to draw it.
* **The 539 refused slots** still cannot be written because they cannot be decoded; the writer's 100 % mark is
  100 % of the 2,188 accepted slots, not of the tree.

## 11. Writing the pack back: the mod step (measured 2026-11-07)

`re4gc_inventory.pack_patch(data, bin_index, replacement, endian="<")` writes one BIN slot back in place.
`bin_slots(data, endian)` lists the slots with their pack offsets (`bin` = position among BIN slots, `slot` = DAT
index, which differ because a pack interleaves BIN with EFF/TPL/FCV).

A patch must be **exactly the slot's size** — the same rule the GameCube work paid for. Rewriting the DAT/UDAS tables
is deliberately not done: real packs leave 960 B before the first entry, up to 18 KB between entries, and trailing
bytes after the last (em10: 19,744 B), so a table rebuild would have to reproduce all of it to stay faithful. A
same-size patch needs none of it.

Verified on the real tree:

| check | result |
|---|---|
| every pack patched with its own slot bytes | **162 / 162 byte-identical**, 0 changed |
| in-pack swap: dst slot #75 (241,216 B, 5,892 verts, 38 bones) <- donor #119 (2,400 verts, 1,664 tris) | rebuilt 202,656 B, padded to 241,216 B |
| other slots after the swap | **119 / 120 byte-identical** (only the target changed) |
| the swapped slot re-decoded | 4,992 verts, 1,664 tris, 38 bones, bbox follows the donor |
| the pack re-inventoried | no errors |

**The size constraint this exposes.** A rebuilt mesh holds one vertex per triangle corner, so its size scales with
the donor's triangle count, not the destination's. Swapping a heavy donor into a light slot produces a file that cannot
fit (measured: a 66,080 B slot asked for 485,600 B). A real swap therefore needs either a donor with few enough
triangles or the fitting ladder (dedupe / strip encoding) before `pad_to`. That is the next piece of work, and it is
the reason a "Sonic as the ganado" build has to pick its target slot with the triangle budget in mind.

Written artifact: `~/gBox_alt/re4-lab/em10-swapped.udas` (sha256 `562b1ba4…`), a real pack with one mesh replaced,
ready to drop into a LayeredFS build's `romfs/bio4/em/`.

**In-game (2026-11-07):** that pack was put in a LayeredFS overlay and the title booted with it - title screen and
save-select screen, every other slot byte-identical. The swapped geometry has NOT been seen rendering yet; see
`re4-switch-mod-boot.md` for what was seen and the load-save route that should reach an enemy next.
## The fitting ladder's first rung: strip encoding (2026-11-07)

A rebuilt mesh has no index buffer, so a list stores one vertex per triangle corner and its size grows with the
donor's triangle count. That is the constraint that made a 66,080 B slot ask for 485,600 B. A **type-6 triangle strip**
reuses the two vertices of the shared edge, and it is the only compression this format offers.

`bin_from(..., encoding="strip")` emits strips per material record. The decay rule matters: the decoder emits
`(s[i], s[i+1], s[i+2])` for even `i` and `(s[i+1], s[i], s[i+2])` for odd, so a triangle may only join at a parity
whose orientation it already has. Requiring that keeps every face's winding - a naive stripifier flips every other
face, which renders half a character inside-out - and the result is checked against the source's triangle set before
it is returned (a strip that would change the mesh raises instead of shipping).

Measured on real `em10` slots:

| template slot | donor (verts / tris) | list | strip | saving |
|---|---|---|---|---|
| #0, 2,848 B | 2,400 / 1,664 | 200,064 B (4,992 verts) | **101,856 B (2,494 verts)** | **49 %** |
| #116, 2,016 B | 5,892 / 4,038 | 485,056 B (12,114 verts) | **251,520 B (6,170 verts)** | **48 %** |

So strips roughly halve a rebuilt mesh - and **still do not fit those specific slots**, because the donor is far too
rich for them. The next rung is therefore not another encoding: it is choosing the pair by budget (a triangle-light
donor, or a target slot with room), which is now a measurable decision rather than a guess:

```
rebuilt_vertices(source_tris)  ~=  tris + 2 * strips     # measured 1.5 verts/triangle on these donors
rebuilt_bytes                  ~=  rebuilt_vertices * ~41 B
```
### Choosing the pair by budget: `rank_targets` (measured 2026-11-07)

`re4hd_models.rank_targets(pack, donor, encoding="strip")` rebuilds one donor against **every** BIN slot of a pack and
reports which can hold it, so a swap is aimed instead of guessed.

A real donor - `em21` slot 0, **2,725 verts / 1,843 tris**, a character-sized mesh - ranked against all 120 BIN slots
of `em10.udas` in **0.8 s**:

| result | count |
|---|---|
| fits | **2** |
| too_big | 94 |
| undecodable (the decoder's own refusal classes) | 24 |

```
slot 543 (bin  76):  119,584 B into 228,768 B = 52%   (2,873 verts, 1,843 tris)
slot 541 (bin  75):  119,776 B into 241,216 B = 50%   (2,875 verts, 1,843 tris)
largest refusing:    115,200 B needed vs  98,624 B  = 117%
```

Two things follow, and they are the practical answer for "Sonic as the ganado":

1. **Only the pack's two biggest meshes can host a character-sized donor.** The cliff is sharp - the next slot down
   needs 117 % of its own size - so a character swap into `em10` has exactly two candidate targets, and both are
   ~50 % full at strip encoding. There is real headroom in those two.
2. **A lighter donor widens the set.** The 94 refusals are a budget statement, not a bug: a donor with fewer triangles
   (or a decimated one) fits more slots, and the cost model says how many
   (`rebuilt_vertices � tris + 2�strips`, `bytes � verts � 41`).

That makes the next rung concrete: either target slots 541/543, or add a decimation step so a rich donor fits more of
the pack.
## The swap is one call now: `plan_swap` (2026-11-07)

Rounds 8 to 18 each re-derived the same five steps by hand - rebuild, check the size, simplify, pad, patch - and each
experiment paid an emulator boot to discover something the arithmetic already knew. `re4hd_models.plan_swap` is that
sequence as one call:

```python
out = plan_swap(pack_bytes, donor_bin, slots=[32, 24, 2, 3])   # or slots=None for every slot it can reach
out["pack"], out["swapped"], out["report"]                     # patched bytes + a per-slot verdict
```

Verified on the real `em11` pack with the dog as donor:

```
one call -> swapped 4 of 4
   bin  2: 792 tris, 59,136 B, fill 88%, simplified
   bin  3: 981 tris, 63,584 B, fill 95%, simplified
   bin 24: 1198 tris, 80,064 B, fill 99%, simplified
   bin 32: 1599 tris, 97,632 B, fill 99%, simplified
whole pack: 33 slots -> 26 swapped, 3 too_big, 4 undecodable
```

A donor that already fits is **not** simplified behind the caller's back; a donor that does not is simplified to a
budget that fits, and the surviving vertices carry the donor's UVs and colours (`simplify` reports which original
vertex each merged vertex stands for - without that the rebuild was handed a donor-length UV list and refused every
budget, which is how this bug was found).

That last number is the useful one for planning: **a character-sized donor can now enter 26 of em11's 33 slots** in one
call, where round 17 measured zero.

## Sound: identified, not decoded (2026-11-07)

The goal names sound effects and this title keeps them in CRI containers: `bio4/snd` has **112 `.acb` + 112 `.awb`**
(+ one `.acf`), the `.acb` beginning `@UTF` and the `.awb` beginning `AFS2`.

Read from the headers: version `0x0401`, offset size 2, id size 0, an entry count (65 / 78 / 17 for `core`, `bio4bgm`,
`bio4midi`), alignment 32, subkey 0, and a u16 table whose values run 1..count. Attempts to treat those as offsets, and
to find the payloads by `HCA ` / `@UTF` magic, both failed - `core.awb` has neither magic anywhere - so the entry map
and the payload codec are **not** established. `gBox` has no CRI reader to reuse. This is a real gap, recorded rather
than guessed at; the next step is a proper `@UTF`/`AFS2` reference rather than more guessing from hex.