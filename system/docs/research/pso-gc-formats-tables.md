# PSO GC (GPOE8P) — text tables, item tables, per-area map data

Formats proven against the real disc, not the fingerprint. Every number below was computed by the
probe shown next to it (or by the module named at the cited line).

**Source of truth.** Read-only disc image
`D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz`,
`GCDisc(...).files` = **3510 files**, `game_id` `GPOE8P`. Nothing is extracted into the repo; only
sizes, offsets and hashes are quoted. All probes below ran with
`sys.path.insert(0, r"C:\_tools\gBox\system")`.

**Endianness is per-container on this disc** (this is the single most common way to mis-parse PSO GC
data): the disc/FST, `.rel` scene files, `.pr2` headers, `ItemPMT` and `.cpt` headers are big-endian;
`.dat` placement sets, `.evt` scripts, AFS tables and NJCM chunks are **little-endian**.

```python
import sys, struct; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
from gbox import psotext, psomap, psoitems
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
d.read("TextEnglish.pr2")[:8]      # b'\x00\x01\xa5L\xf4p\x96\xa3'  -> size 107852, key 0xF47096A3
```

## 1. PR2 / PR3 text archives

`system/gbox/psotext.py:47-49` is the whole container: **BE u32 decompressed size, BE u32 key, then
cipher(PRS(data))**. The cipher is the PSO v2 stream cipher (`psotext.py:8-44`), applied to the PRS
stream before decompression, not after.

### 1.1 The cipher, exactly as implemented

```python
# psotext.py:10-38 (abridged; the arithmetic is verbatim)
k = [0]*57; esi, ebx, edi = 1, seed & 0xFFFFFFFF, 0x15; k[56] = k[55] = ebx
while edi <= 0x46E:                 # 55-word lagged Fibonacci setup
    edx = edi % 55; ebx = (ebx - esi) & 0xFFFFFFFF; edi += 0x15
    k[edx] = esi; esi, ebx = ebx, k[edx]
for _ in range(4): self._mix()      # 4 warm-up passes; self.pos = 56
def _mix(self):                     # k[i] -= k[i+0x1F] for i 1..0x18, then k[i] -= k[i-0x18] for 0x19..0x37
def next(self):
    if self.pos == 56: self._mix(); self.pos = 1
    v = self.k[self.pos]; self.pos += 1; return v
def crypt(self, data, endian="<"):  # XOR of BE words (GC) / LE words (DC), zero-padded to 4 bytes
```

Proof the key is the seed and the stream is consumed word-by-word: `pr2_decode` (`psotext.py:47`)
with `endian=">"` produces a PRS stream whose `prs_decompress` output is **exactly** `size` bytes long
for all ten text files — no padding, no truncation. Declared size == PRS output size:

| file | file bytes | header size | key | PRS out | sha256(decoded) |
|---|---|---|---|---|---|
| `TextEnglish.pr2` | 45,408 | 107,852 | 0xF47096A3 | 107,852 | `46453bd0c717b691…` |
| `TextFrench.pr2` | 42,836 | 100,816 | 0xF47096F3 | 100,816 | `2dce35166035f029…` |
| `TextGerman.pr2` | 43,217 | 99,912 | 0xF470A653 | 99,912 | `4d936da2c2b20bd2…` |
| `TextJapanese.pr2` | 43,358 | 108,300 | 0xF4709653 | 108,300 | `fd4606aced17044b…` |
| `TextSpanish.pr2` | 42,050 | 98,160 | 0xF470A6A3 | 98,160 | `bc308b5b19a8cbef…` |
| `TextEnglish.pr3` | 109 | 5,828 | 0xF47096A3 | 5,828 | `cac7c5ded30cbcf9…` |
| `TextFrench.pr3` | 112 | 5,830 | 0xF470A603 | 5,830 | `64691e907876f33d…` |
| `TextGerman.pr3` | 111 | 5,830 | 0xF470A653 | 5,830 | `040563e503f898d4…` |
| `TextJapanese.pr3` | 114 | 5,836 | 0xF4709653 | 5,836 | `2d5ae79f21c4b6da…` |
| `TextSpanish.pr3` | 111 | 5,830 | 0xF470A6A3 | 5,830 | `6b58b14b74a03282…` |

The five languages do not share a key, so the key is a per-file build artefact, not a build constant.

### 1.2 PR2 payload layout (proven)

The decoded PR2 is **little more than four regions**, all offsets from the payload start:

| region | English offsets | contents |
|---|---|---|
| `[0, arr0)` | `0x00000–0x17810` | NUL-terminated latin-1 strings, 4-byte aligned, back to back |
| `[arr0, root)` | `0x17810–0x1A490` | `2848` × BE u32 string pointers (index into the blob) |
| `[root, n-8)` | `0x1A490–0x1A544` | `45` × BE u32 **column starts** (each a position inside the pointer array) |
| `[n-8, n)` | `0x1A544–0x1A54C` | `{u32 arr0-8, u32 root}` |

```python
dec  = psotext.pr2_decode(d.read("TextEnglish.pr2"), ">")
n    = len(dec); rd = lambda o: struct.unpack_from(">I", dec, o)[0]
root = rd(n-4); ncol = (n-8-root)//4          # 45
starts = [rd(root+4*i) for i in range(ncol)]
arr0 = min(starts)                            # 0x17810
total = (root-arr0)//4                        # 2848
```

The same shape comes out of **all five languages**, and every one of the 2848 pointers is valid
(`p < arr0` and `dec[p-1] == 0`, or `p == 0`):

| language | arr0 | root | columns | string pointers | valid pointers |
|---|---|---|---|---|---|
| English | `0x17810` | `0x1A490` | 45 | 2848 | 2848 |
| French | `0x15C94` | `0x18914` | 45 | 2848 | 2848 |
| German | `0x1590C` | `0x1858C` | 45 | 2848 | 2848 |
| Japanese | `0x179D0` | `0x1A650` | 45 | 2848 | 2848 |
| Spanish | `0x15234` | `0x17EB4` | 45 | 2848 | 2848 |

**The pointer table yields 2848 strings, in 45 columns, in every language** (2355 distinct string
offsets in English — several columns reuse the same string). Column lengths for English:

```
[831, 759, 88, 88, 19, 20, 47, 13, 6, 39, 287, 111, 24, 7, 82, 37, 29, 21, 84, 19, 3, 3, 45,
 5, 13, 4, 30, 4, 45, 2, 7, 15, 6, 3, 2, 1, 14, 1, 6, 1, 2, 5, 1, 8, 11]
```

Column meaning is visible from the strings: col 0 = item names (831), col 1 = item descriptions (759),
col 2 = enemy names (`Unknown`, `Hildebear`, `Hildeblue`), col 3 = `Unknown`, `Hildelt`, `Hildetorr`,
col 10 = UI help text. The **first five English strings** (col 0, entries 0–4) are `Monomate`,
`Dimate`, `Trimate`, `Monofluid`, `Difluid`, and the first two descriptions (col 1) begin
`"Health recovery\nfluid. Restores HP.\nRestoration is\nbased upon \ndifficulty level."`.

### 1.3 `psotext.collections()` disagrees with the GC payload

`psotext.collections` (`psotext.py:52-78`) takes its root from `len(text)-16`, the Dreamcast PRS
convention. On GC PR2 that word is `0x1A444`, which is **inside the pointer array**, so the walk treats
pointer words as column starts and returns `62 columns, 28140 strings, 2804 non-empty` — all garbage.
The correct GC root is the **last** word (`n-4`), not `n-0x10`. Callers that need GC text must use the
layout in §1.2; `pr2_decode` itself is correct and is what `psoitems.catalog_gc` uses (`psoitems.py:132`).

### 1.4 PR3 is not a string archive (semantics unproven)

PR3 decodes with the same container (`psotext.py:47`) but the payload is a **fixed 0x20-byte header
followed by `count` BE u16 values**, with `count == (filesize-0x20)/2` exactly:

| file | payload | header `{u32,u32,u32,u32,u32,…}` | u16 entries | `0x0001` count |
|---|---|---|---|---|
| `TextEnglish.pr3` | 5,828 | `0x20000000, 0x0B52(=2898), 1, 0, 0x1A544` | 2898 | 2896 |
| `TextFrench.pr3` | 5,830 | `0x20000000, 0x0B53, 1, 0, 0x189C8` | 2899 | 2897 |
| `TextGerman.pr3` | 5,830 | `0x20000000, 0x0B53, 1, 0, 0x18640` | 2899 | 2897 |
| `TextJapanese.pr3` | 5,836 | `0x20000000, 0x0B56, 1, 0, 0x1A704` | 2902 | 2900 |
| `TextSpanish.pr3` | 5,830 | `0x20000000, 0x0B53, 1, 0, 0x17F68` | 2899 | 2897 |

Two facts are solid: the first header word is byte-reversed `0x20` (the writer emitted the header size
little-endian, alone), and the 5th word is **that language's PR2 payload size − 8** (English 0x1A544 =
107,852−8; French 0x189C8 = 100,816−8; German 0x18640 = 99,912−8; Japanese 0x1A704 = 108,300−8;
Spanish 0x17F68 = 98,160−8) — PR3 is chained to the end of its PR2 sibling. Everything else — what the
u16 table means, why entry 0 is `0x5E00`/`0x5720`/`0x563E`/`0x5E6C`/`0x5488` and entry 2 is `2` — is
**unproven**. `psotext.collections` on a PR3 payload returns 0 columns, which is the honest answer:
there is no string pointer table in it.

## 2. `.cpt` — ciphered PRS containers

Only two on the disc. Both use the **PR2 container verbatim**: BE u32 size, BE u32 key,
PSO-v2 cipher over a PRS stream.

| file | file bytes | header size | key | PRS out | first 32 bytes of payload |
|---|---|---|---|---|---|
| `PlyLevelTbl.cpt` | 11,774 | 28,928 | 0xF35D62CE | 28,928 | `00×12 03 04 05 02 01 06 00 00 00 00 00 32 04 05 04 02 01 05 00 00 00 00 00 C8` |
| `PlyMotionNpcTown.cpt` | 7,948 | 13,696 | 0x334C237C | 13,696 | `00 00 00 00 BC 6A E1 8A BF 29 B6 4E 00 00 00 00 00 00 00 02 BD BC 20 92 BF 07 5B F6 00 00 00 00` |

`raw = d.read("PlyLevelTbl.cpt"); size, key = struct.unpack_from(">II", raw, 0)`, then
`prs_decompress(PSOV2Cipher(key).crypt(raw[8:], ">"))[:size]` → 28,928 bytes.

### 2.1 `PlyLevelTbl.cpt` is a 12-block × 200-level table — proven

Stride **12 bytes**: `{u8 a,b,c,d,e,f, u16 0, u32 cumulative EXP}` (the EXP word at +8 is 4-byte
aligned because the record start is). `28,928 = 12 × 2,400 + 128`; each 2,400-byte block is a 200-level
table. The 128-byte trailer is a table of 13 block offsets
(`14,400, 16,800, 9,600, 24,000, 19,200, 21,600, 2,400, 4,800, 7,200, 12,000, 0, 26,400, 28,800` — i.e.
`0…11 × 2,400` in a permuted class order, plus the end offset) followed by the same 0x20-byte
descriptor as the scene `.rel` files (§3.1): `{28864, 13, 1, 0, 28848, 0, 0, 0}`. The 12 blocks are
most plausibly the 12 player classes; that mapping is **inferred, not proven**.

The EXP column is **identical in all 12 blocks** (`all(block == block0)` is True) and strictly
increasing inside a block for all 200 records: `0, 50, 200, 450, 800, 1250, …`. Records 0–13 satisfy
`EXP(n) = 50·n²` exactly; from n=14 the real curve takes over (`9848, 11427, 13252, …`) and
`EXP(199) = 83,227,800`. The six leading bytes are small (0–10 over the whole file, 0–8 within a block)
and differ per block, e.g. block 0 record 1 = `03 04 05 02 01 06`, block 1 record 1 = `02 05 05 03 01
06`; their meaning (stat growth / class availability) is **unproven**. So: **a level→EXP table of u32s,
replicated per class, is proven**; what the six per-level bytes encode is not.

### 2.2 `PlyMotionNpcTown.cpt` — container proven, payload unproven

13,696 bytes of float-heavy data (`-0.0143, -0.6634, 0.0, 0.0, -0.0233, -0.6064, 0.0, 2.0, …` at the
start, i.e. small rotations/translations and a leading 0/2 count field). It is the decompressed base of
`PlyMotionNpcTown.rel` (21,920 bytes, which starts `00 00 00 00 BC 6A E1 8A …` — the same bytes) so the
`.rel` is the loaded form and the `.cpt` its packed form. The animation record layout is **unproven**.

## 3. Scene `*.rel` — Sega DataView relocatable data

These are **not** GameCube `R_DOLPHIN` REL modules (`gcdisc.rel_sections`, `gcdisc.rel_link` do not
apply — a scene `.rel` has no `{u32 id, u32 next, u32 prev, u16 nsec, …}` OSModule header; its first
word is section data). They are Sega's DataView "REL": a flat data image with **file-relative
pointers** plus a trailing offset table that the loader uses to fix the pointers up.

### 3.1 The trailing 0x20 bytes, decoded (all six scene files)

The last 0x20 bytes are **8 big-endian words**:

```
{u32 data_end, u32 reloc_count, u32 1, u32 0, u32 root, u32 0, u32 0, u32 0}
```

* `data_end` — end of the data image; `psomap.collision` uses it as the upper bound of the 0x18-entry
  table (`psomap.py:23`). `root` — offset of the root pointer table, read by `psomap.rel_root` at
  `len(data)-0x10` (`psomap.py:13-15`). **Both are needed**: `data_end` bounds the scans, `root` starts
  them. `reloc_count` — number of **u16** entries in a table stored immediately after `data_end` and
  **before** the 0x20-byte trailer, zero-padded to a 32-byte boundary.

Proof of the padding rule (gap = `(n-0x20) - data_end`, `round32(x) = (x+31)//32*32`):

| file | size | data_end | reloc_count | root | gap | 2·count | round32 |
|---|---|---|---|---|---|---|---|
| `Scene/map_forest01c.rel` | 72,096 | `0x0117E0` | 208 | `0x0117CC` | 416 | 416 | 416 |
| `Scene/map_forest01r.rel` | 12,896 | `0x003120` | 137 | `0x003114` | 288 | 274 | 288 |
| `Scene/map_forest01t.rel` | 8,416 | `0x0020A0` | 5 | `0x002084` | 32 | 10 | 32 |
| `Scene/map_forest01n.rel` | 728,768 | `0x0AEA20` | 6,708 | `0x0023F0` | 13,440 | 13,416 | 13,440 |
| `Scene/map_cave01_00c.rel` | 363,776 | `0x058AE0` | 256 | `0x058AD4` | 512 | 512 | 512 |
| `Scene/map_ruins01_00c.rel` | 421,152 | `0x066960` | 451 | `0x066954` | 928 | 902 | 928 |

The last 0x40 bytes of `Scene/map_forest01c.rel` (n = 72,096):

```
0x11960  00 06 00 06 00 06 00 06 00 06 00 06 00 06 00 06   <- reloc table tail (u16 == 6)
0x11970  00 06 00 06 00 06 00 06 00 06 00 06 00 06 00 0C   <- last u16 is 12
0x11980  00 01 17 E0 | 00 00 00 D0 | 00 00 00 01 | 00 00 00 00   data_end, count=208, 1, 0
0x11990  00 01 17 CC | 00 00 00 00 | 00 00 00 00 | 00 00 00 00   root, 0, 0, 0
```

Independent corroboration that `reloc_count` counts **pointers**, not objects: `map_forest01c.rel` has
69 meshes, each contributing 3 relocated words (table entry → mesh, mesh → vertices, mesh → faces)
plus 1 for the root → `69·3 + 1 = 208` = `reloc_count` exactly. The `.cpt` level table fits the same
picture (count 13, a 13-entry offset table, one 0x20-byte descriptor). What the individual u16 values
mean (absolute offsets within a section vs. deltas — they are neither monotonic nor 4-byte aligned) is
**unproven**.

### 3.2 `c.rel` collision — fully proven

Layout (`psomap.py:18-37`): root table → 0x18-byte entries, 0-terminated;
mesh `{u32 nv, xyz f32 verts*, u32 nf, faces*}`; face = 36 bytes
`{u16 v0,v1,v2,flags, f32 nx,ny,nz, 16 unread bytes}`. `psomap.collision(data, be=True)` on
`Scene/map_forest01c.rel` returns 1455 triangles from 69 meshes, 164 of them `flags & 0x8000`.

| file | size | root | mesh table `rd(root)` | `(root-mesh)/0x18` | meshes | triangles | `flags&0x8000` | Y extent | X extent | Z extent |
|---|---|---|---|---|---|---|---|---|---|---|
| `Scene/map_forest01c.rel` | 72,096 | `0x117CC` | `0x1113C` | 70 | 69 | **1,455** | 164 (11.3 %) | −23.03 … 215.18 | −683.39 … 685.23 | −654.00 … 659.56 |
| `Scene/map_cave01_00c.rel` | 363,776 | `0x58AD4` | `0x582C4` | 86 | 85 | **7,934** | 1,008 (12.7 %) | −10.00 … 159.20 | −441.02 … 3,166.02 | −2,141.02 … 438.40 |
| `Scene/map_ruins01_00c.rel` | 421,152 | `0x66954` | `0x65B2C` | 151 | 150 | **8,798** | 2,496 (28.4 %) | −120.00 … 160.00 | −1,349.00 … 975.00 | −1,340.00 … 940.00 |

In all three the 0x18 table starts at `rd(root)` and spans **meshes + 1** entries up to `root`
(70 × 0x18 = 0x690 = `0x117CC-0x1113C`), the +1 being the zero terminator that ends the walk.
Forest 1's first mesh is at `0x234` (`nv=11, nf=12`), its last at `nv=46, nf=52`.
`flags & 0x8000` (`psomap.TRIGGER_FLAG`, `psomap.py:10`) marks part of each map as event volumes
rather than walls: 164/1,455 Forest 1 faces (11.3 %), 1,008/7,934 Cave (12.7 %) and 2,496/8,798 Ruins
(28.4 %). Ruins' coordinates are integer-valued on a grid; forest/cave are free-form.

### 3.3 `n.rel` and `r.rel` do **not** follow `psomap.render_objects`

`psomap.render_objects` (`psomap.py:107-122`) expects a root `{u32 sections, f32, u32 table}`, 60-byte
sections and 48-byte entries. On GC neither file matches, and the function fails loudly:

| file | `rel_root` | words there | `render_objects(be=True)` |
|---|---|---|---|
| `Scene/map_forest01r.rel` | `0x3114` | `0x2E6C, 0x0, 0x11` | `struct.error`: wants 510,042,116 bytes (reads `0x2E6C` = 11,884 as the section count) |
| `Scene/map_forest01n.rel` | `0x23F0` | `0x666D7432 ('fmt2'), 0x60, 0x00100000` | `struct.error`: wants 1,048,580 bytes (reads the ASCII tag as the count) |
| `Scene/map_aforest01n.rel` | `0xAEBB4` | `'fmt2', 0x60, 0x110000` | same failure |

**`r.rel` actual layout (proven arithmetic, unproven semantics).** Root is
`{u32 section_table, u32 0, u32 section_count}` — the field order is the *reverse* of the Dreamcast
convention. 17 sections × 40 bytes = 680 = `0x2A8`, and `0x2E6C + 0x2A8 = 0x3114` = the root offset
exactly. Section record (40 bytes):

| off | type | meaning (observed) |
|---|---|---|
| +0x00 | u16 | section id, 2 … 0x12 (17 values, sequential) |
| +0x02 | u16 | constant `5` in all 17 |
| +0x04 | f32 | x (e.g. −519.90, −293.76, …) |
| +0x08 | f32 | 0.0 in all 17; +0x10 is 16 zero bytes in all 17 |
| +0x0C | f32 | z (−560.00, −454.16, …) |
| +0x20 | f32 | 68.79 … 322.97 (radius-like, **unproven**) |
| +0x24 | u32 | offset of the section's data inside `r.rel` (436, 1108, 1748, 2612, … 11,828) |

The section payload at +0x24 starts `{u32 22, u32 0x190, f32 x, f32 0, f32 z, …}` — its own `(x, 0, z)`
copied from the record — then `1.0, 1.0, 1.0` and a run of `(x, 0, z)` float triples. It is a
room/origin table, **not** an `NJS_OBJECT` list; the section positions do **not** coincide with
`c.rel`'s 69 bounding-sphere centres (different counts, different coordinates).

**`n.rel` is the geometry file and comes in two header variants.** 27 of the 159 `Scene/*n.rel` files
begin with **texture-name strings** (NUL-terminated, 4-byte aligned), e.g. `Scene/map_aforest01n.rel`
(729,216 B): `ts_256k_koke02`, `fo_064a_kinoko`, `fo_064k_takikire01`, `fo_256k_ishi01`,
`fo_256k_ishijime03`, `fo_512k_takigake01`, … But **`Scene/map_forest01n.rel` does not** — it starts
with a table of 16-byte records, and its first printable run of ≥6 chars is at `0x2AB8` (`Bq}wB `):

```
00000  00 00 2A 74 00 00 00 00 00 00 00 00 00 20 00 00   {u32 0x2A74, 0, 0, 0x00200000}
00010  00 00 2E B4 00 00 00 00 00 00 00 00 00 20 00 00   {u32 0x2EB4, 0, 0, 0x00200000}
00020  00 00 30 D4 …                                      then 0x30D4, 0x3394, 0x3774, 0x3B54 …
```

So "texture names first" is a **per-file variant** (27/159) and `map_forest01n.rel` is not one of them;
it is also the only Forest-1 file whose `a`-twin has a different size (728,768 vs 729,216). Twins that
*are* byte-identical: `map_forest01c.rel`/`map_aforest01c.rel` (sha256 prefix `0e7bc121a41e`), `…r.rel`
(`0a5604d68520`), `…t.rel` (`f9d30d560834`), `map_cave01_00c/n/r` (`9036f786420a`, `bbb058a950b4`,
`7671b7102225`).

Both `n.rel` variants end at a `fmt2` chunk header — `Scene/map_forest01n.rel` at `0x23F0`:
`'fmt2' | u32 0x60 | u32 0x00100000 | f32 800.0 | u32 0x20B0 | u32 0x2660`, followed at `0x2420` by
another 16-byte-record table (`0xAE6A0, 0xAE6B0, 0xAE6C0, 0xAE6D4, …`). Reading `n.rel` geometry
requires decoding that chunk system, which is **unproven**; `render_objects` cannot be used as-is.

### 3.4 `t.rel` — a chunked file shared by the whole game

There are only **two** scene `t.rel` files on the disc — `Scene/map_forest01t.rel` and
`Scene/map_aforest01t.rel` — both 8,416 bytes and byte-identical. (`Effect_nt.rel`, 480 B, merely ends
in the letters `t.rel`.) So `t.rel` carries **no per-area data** despite living in `Scene/`.
`Scene/map_forest01t.rel` starts with ASCII chunk tags:

```
00000  42 47 58 49 00 08 00 00 1C E0 00 03 00 0C 00 00   "BGXI", 0x800, 0x1CE00003, 0x000C0000
00010  56 50 54 52 08 18 00 00 09 00 00 00 00 20 00 20   "VPTR", 0x818, 9, 0x00200020
00020  52 F5 C6 92 BE 71 C2 71 C6 92 DB 17 E7 59 DF 17   u16 stream: 0x52F5, 0xC692, 0xBE71, …
```

after which: a u16 array of packed values (mostly `0x8xxx`/`0xCxxx`/`0xDxxx` — looks like quantised
vertex/UV pairs), a byte table of values 0–5 from ≈`0x1EC0`, and at `0x2060` a 9-word directory
(u16 view: `0x000C, 0, 0, 0, 0, 0x0830, 0x0018, 0, 0, 0x1030, 0, 0x1860, 0xFFFF, …`) that the root
table (`0x2084`, 7 words, one non-zero entry = `0x2060`) points at. Meaning **unproven**; since both
files are identical, whatever it describes (fog, light, texture animation) is global, not per area.

## 4. `.dat` area placement sets

263 `.dat` files; the scene sets sit at the **root** of the FST, not in `Scene/`:
`map_forest01d.dat` 10,200 B, `map_forest01ad.dat` 10,200 B, `map_cave01_00d.dat` 13,532 B,
`map_cave01_00ad.dat` 13,532 B.

**Proven 1 — 68-byte record stride.** `10,200 = 150 × 68` and `13,532 = 199 × 68` exactly, and the
internal structure repeats on that period. **Proven 2 — little-endian floats.**
`map_forest01d.dat` at `0x10`: `9C 8F F1 43 | 5D 8F 81 41 | E8 64 4B 44` = `483.12, 16.195, 813.58`.
Read big-endian the same bytes are denormals, so the placement sets are LE while every other table on
the disc is BE.

**Candidate 3 — the 68-byte record splits into a 33-byte and a 35-byte sub-entry.** In the first nine
records a LE u32 `23` sits at both `+0x00` and `+0x21`, which is exactly the 33/35 split; the marker is
**not** present in the other 141 records, so the split is a candidate, not a proof:

```
rec 0  +0x00 17 00 00 00 | +0x04 AF 07 01 00 | +0x08 74 48 00 00 | +0x0C 01 00 00 00
       +0x10 9C 8F F1 43 | +0x14 5D 8F 81 41 | +0x18 E8 64 4B 44 | +0x1C 0 | +0x20 00
       +0x21 17 00 00 00 | +0x25 0 | +0x29 05 00 24 42 | +0x2D 01 00 80 3F | +0x31 02 00 80 3F
       +0x35 09 00 00 00 | +0x39 00…00 | +0x40 20 BA FA 8C
rec 1  +0x44 17 00 00 00 | +0x48 B1 07 01 00 | +0x4C 78 48 00 00 | +0x50 01 00 00 00
       +0x54 92 1B BC 43 | +0x58 5D 8F 81 41 | +0x5C 2E 7A 22 44 …
```

Byte offsets of the **first position-like float triplets**: `0x10` in every record
(`rec0 @ 0x10`, `rec1 @ 0x54`, `rec2 @ 0x98`, …). First triplet per file:

| file | first triplet (x, y, z) | XZ/Y range over all records' `+0x10` triplets |
|---|---|---|
| `map_forest01d.dat` | `483.12, 16.20, 813.58` | X −708.6…1082.2, Z −999.2…1067.4, Y −6.5…700.0 |
| `map_forest01ad.dat` | `−485.03, 178.20, 59.80` | X −708.6…1082.2, Z −999.2…1067.4, Y −6.5…178.2 |
| `map_cave01_00d.dat` | `0.00, 0.53, −110.00` | X −1610…1170, Z −1880…277.8, Y −20.0…105.1 |

The second word group holds two ascending id counters — `+0x04`: `67503, 67505, 67504, 67506`;
`+0x08`: `18548, 18552, 18550, 18554` (cave: `198488, 198489, 198490, 198491` / `18267, 18268, …`).
`+0x0C` is `1` for the first six records of every file. The words at `+0x40` (and `+0x7C`, `+0xB8`, …)
are `0x8CFABA20, 0x8CFAC020, 0x8CFAC1D0, 0x8CFAC280, …`, cave `0x8CFA2CC0, 0x8CFA2D70, …` — all inside
the GameCube main-RAM window `0x8C…`, i.e. they look like **pre-linked runtime pointers** rather than
offsets; that reading is **unproven**.

**`d.dat` vs `ad.dat` — the difference that can be proven.** `map_cave01_00d.dat` and
`map_cave01_00ad.dat` are **byte-identical** (13,532 B, sha256 prefix `75ea26f33b17`) — the `a`-twin of
Cave 1-1 is a duplicate, not a variant. `map_forest01d.dat` and `map_forest01ad.dat` have the **same
size and same record shape** but **all 150 records differ** (2,409 bytes differ overall) — same
structure, edited values: Forest 1's `d` sits near ground level (y ≈ 16.20) while its `ad` twin starts
at y ≈ 178.20 / 136.63, so `ad` is a different placement of the same object set, not a different
format. This matches the `a`-family pattern of §3.3 — for most areas the `a`-files are exact
duplicates; Forest 1's `n.rel` and `d.dat` are the exceptions.

**Not decoded:** the meaning of `0x17`/`23`, of the 33/35 split, of the six leading bytes per
half-record, and of the `0x8CFA…` words. The 68-byte stride and the LE float triplets at `+0x10` are
the reliable handles.

## 5. `.evt` event scripts

Exactly 5 on the disc. **Little-endian**, header `{u32 code_start, u32 0x10, u32 count, u32 0}` —
for `map_ruins01_00_jm.evt` (336 B): `struct.unpack_from("<4I", b, 0)` → `276, 16, 13, 0`, and
`276 == 16 + 13·20`.

| file | size | code_start | count | record bytes | code bytes |
|---|---|---|---|---|---|
| `map_boss02jm.evt` | 44 | 36 | **1** | 20 | 8 |
| `map_boss05jm.evt` | 44 | 36 | **1** | 20 | 8 |
| `map_jungle01_off.evt` | 216 | 156 | **7** | 140 | 60 |
| `map_jungle05_00_jm.evt` | 412 | 316 | **15** | 300 | 96 |
| `map_ruins01_00_jm.evt` | 336 | 276 | **13** | 260 | 60 |

`code_start = 0x10 + 20·count` holds for all five. **The record stride is 0x14 (20) bytes, not 0x10**,
and the byte offset is the **last** field of the record, not the first:

| off | type | value in `map_ruins01_00_jm.evt` rec 0…3 |
|---|---|---|
| +0x00 | u32 | event id: 101, 1011, 102, 1021, 501, 5011, 502, 601, 1601, … |
| +0x04 | u32 | constant `0x00010000` (two u16: 0, 1) in every record |
| +0x08 | u16 | group: 10, 10, 10, 10, 50, 50, 50, 60, 60, 100, 160, … |
| +0x0A | u16 | index within the group: 1, 2, 3, 4, 1, 2, 3, 1, … |
| +0x0C | u32 | 30, 100, 100, 100, 150, 100, 1, 30, 60, 100, … (meaning **unproven**) |
| +0x10 | u32 | **byte offset of this event's code inside the code block**: 0, 6, 19, 32, 33, 39, 45 |

Every one of those offsets lands on an opcode byte of the code block. The code block is a small
bytecode: `0x0C <u32 event_id>` (a jump/call to another event — the same ids as the table),
`0x0A <u16>`, `0x01`, terminated by `0xFF`/`0xFF 0xFF` (`map_jungle01_off.evt` ends `… 01 FF FF`).
`map_ruins01_00_jm.evt` code at `0x114`:

```
0C FD 03 00 00 | 01 | 0A 06 00 | 01 | 01 | 0C 93 13 00 00 | 01 | 0A 0E 00 | 0A 0D 00 | 01
0x0C id=1021    0x01  0x0A 6     0x01 0x01  0x0C id=5011     0x01  …                   …  0xFF
```

The opcode set beyond `0x01/0x0A/0x0C/0xFF` is **unproven** (only 5 files, 368 bytes of code total).

## 6. `.tam` and `bm.bin`

### 6.1 `.tam` — 137 files, 27 distinct sizes, 42 … 986 bytes

`Scene/map_forest02.tam` (158 B) as BE u16: header `1, 24, 1, 0, 20, 0, 0, 0`, then at `0x1C` the pair
`(2, 124)`, then 4-byte groups ending `00 01 00 2F | 00 01 00 30 | 00 01 00 31 | 00 01 FF FF` — a
`u16`-pair list with `0xFFFF` as the terminator and a small constant (1) as the first element.
`Scene/map_cave02_04.tam` (986 B) as BE u16: header `1, 144, 7, 0, 1, 33`, then `f32 0.0, 1.0, 1.0` at
`0x10`, then 4-byte groups (`(4,3)`, `(5,0x41)`, `(6,0x88)`, `(9,0x63)`, `(10,0x63)`, …) whose second
element grows. The `144` header word is not `(986-0x20)/k` for any k, so it is not a byte length.

Both are plausibly texture/animation lookup tables (`tam` = texture animation map) but no element has
been tied to a texture or frame count, so the semantics are **unproven**. What is proven: big-endian
u16 groups, a `0xFFFF` terminator in the small file, and the size census — 137 files in 27 distinct
sizes, with `130`, `306`, `538`, `622` and `886` bytes having 12 files each, `150` and `986` having 10,
and `362` having 9.

### 6.2 `bm.bin` — 111 files, magic `vr1b`

`struct.unpack_from(">4I", d.read("Scene/map_forest01bm.bin"), 0)` → `(0x76723162, 0x10, 1, 4)`, i.e.
`"vr1b", 16, 1, 4`; `map_cave02_04bm.bin` (272 B) gives `"vr1b", 0x11, 1, 1, 0, 2, …`. So the header
is `{char[4] "vr1b", u32 count, u32 1, u32 4|1, u32 0, u32 2, …}` and every `bm.bin` on the disc starts
with `vr1b`. The bodies do not share a stride: `map_forest01bm.bin`'s 384-byte body after the 0x10
header is `16 × 24` (fields at +0/+4/+8/+12/+16/+20, first field ascending `0, 10, 20, 35, 44, …`) or
`32 × 12` (in which case field 1 is an ascending index `2,3,4,5,6,7,8,9`); `map_cave02_04bm.bin`'s
256-byte body fits neither (it is `16 × 16`). Record layout is therefore **unproven**; only the magic,
the count word and the BE-u32 field style are established.

## 7. Item and text tables

### 7.1 `ItemPMT.prs` — the item parameter table

`15,673` bytes on disc, PRS-compressed only (no cipher), `prs_decompress` → **63,680 bytes**. It ends
with the **same 8-word section descriptor as the scene `.rel` files**:
`{0xF6A0 = 63,136 (data_end), 0xF5 = 245 (count), 1, 0, 0xF628 = 63,016 (root), 0, 0, 0}`.

The root table is `(0xF6A0-0xF628)/4 = 30` words; the first five are the five item families that
`psoitems.catalog` reads (`psoitems.py:45`): `0` → `0xF078` weapons (array of per-class
`{u32 n, u32 data*}`), `1` → `0xEF90` frames, `2` → `0xEFA0` barriers, `3` → `0xEFB0` units,
`4` → `0xEFA8` mags. The rarity byte table is at `0xBE9C` = `*(root+0x2C)` (`psoitems.py:55`).

Field layout **as implemented** (`psoitems.py:86-120`, GC branch, `dc = False`): record strides
`0x28` weapons, `0x1C` frames/barriers, `0x10` units, `0x18` mags, `0x14` tools; the first `u32` of a
record is the name id (index into `TextEnglish.pr2` column 0), `0xFFFFFFFF` skips; stars come from
`p[star_start + iid - 0x94]` clamped to the next table; weapon fields at `+base_size (8)`:
`usability_flags u16, atp_min u16, atp_max u16, atp_required u16, mst_required u16, ata_required u16`,
then `max_grind u8 @+0x16`, `special_id u8 @+0x18`, `ata u8 @+0x19`.

**Actual count: 1,257 catalogue rows.** `catalog(pmt, pr2_decode(TextEnglish.pr2), ">", 0)` →
Weapons 788, Armor 258, Tools 145, Mags 66; kinds Barrier 133, Unit 72, Mag 66, Frame 53, weapon
class 0E 43, class 0D 23, …; first rows `000100 "Saber"` (class 01, 0★, atp 40–55, max_grind 35),
`000101 "Brand"` (1★), `000102 "Buster"` (2★). Item codes are the first 3 data bytes
(`psoitems.py:3-5`): weapon `00 cc ii`, frame `01 01 ii`, barrier `01 02 ii`, unit `01 03 ii`,
mag `02 ii 00`, tool `03 cc ii`.

### 7.2 The companion archives

| file | size | what it actually is |
|---|---|---|
| `ItemRTT.prs` | 420,996 | PRS → **852,928** bytes starting `47 56 4D 48` = `"GVMH"` — a GVM texture archive, **not** a parameter table. Internal GVM parse out of scope here (**unproven**). |
| `ItemKT.afs` | 1,566,720 | `AFS\0`, **379** entries, **little-endian** TOC `(offset, size)`; first entries `(4096,1596) (6144,1548) (8192,1561) (10240,1534)`, all in range. |
| `ItemTexture.afs` | 1,695,744 | `AFS\0`, **324** entries, LE TOC, data 2,048-aligned from 4,096. |
| `ItemModel.afs` | 1,005,568 | `AFS\0`, **303** entries, LE TOC `(4096,1425) (6144,2599) (10240,1303) (12288,1742)`. |

AFS is little-endian even on this big-endian disc (same conclusion as
`system/gbox/pso3_inventory.py:38-45`), and entry data starts on a 2,048-byte boundary (`4096, 6144,
8192, 10240, 12288`), so the gap `8 + 8·count → 4096` is padding after the TOC.

### 7.3 The text catalogue

`psoitems.catalog_gc` (`psoitems.py:130-132`) joins `ItemPMT.prs` with `TextEnglish.pr2`: 1,257 rows
get their names from PR2 column 0 (831 names), which is why the catalogue has more rows than names —
several item ids share a name and `"????"`/empty names are filtered (`psoitems.py:122`).

## 8. What could not be decoded

| format | status |
|---|---|
| `*.pr3` u16 body | header proven (0x20 B, `count=(len-0x20)/2`, chained to PR2 size−8); table semantics **unproven** (2896/2898 words are `0x0001`) |
| `PlyLevelTbl.cpt` six leading bytes per level | **unproven** (small values 0–10, differ per class block) |
| `PlyMotionNpcTown.cpt` animation records | container proven, record layout **unproven** |
| scene `.rel` reloc-table u16 semantics | count/padding proven, values neither monotonic nor aligned → **unproven** |
| `n.rel` `fmt2` chunk system / geometry | `render_objects` fails; chunk layout **unproven** |
| `r.rel` section payload | table proven (17 × 40 B), payload meaning **unproven** |
| `t.rel` `BGXI`/`VPTR` chunks | tags and directory proven, encoding **unproven** |
| `.dat` field meanings | stride 68, LE floats at +0x10 proven; 33/35 split, ids, `0x8CFA…` words **unproven** |
| `.evt` opcode set beyond `0x01/0x0A/0x0C/0xFF` | **unproven** (368 bytes of code across 5 files) |
| `.tam`, `bm.bin` record semantics | **unproven** (see §6) |
| `ItemRTT.prs` inner GVM | **unproven** (file is a texture archive, not a table) |

Recomputed from the disc in this session: §1.1–§1.2, §2.1, §3.1–§3.2, §4 (stride/floats), §5, §7.1.
