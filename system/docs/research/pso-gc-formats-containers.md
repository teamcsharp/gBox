# PSO GC (GPOE8P) container and compression formats, proven on the disc

2026-11-10. Every number below was produced by running the repo's own readers against the owned image
`D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz` (read-only). No decoder was
changed and none was needed. Where a claim is code-derived but not measured, the line says **unproven**. Sizes,
offsets, counts and hashes only: no extracted assets live in this file.

The disc layers stack like this — GC disc header/FST → GCZ blocks → GSL or AFS archive → BML pack → PRS stream:

```
GCZ container  (0x4000-byte blocks, 89,110 of them)
└─ GC disc image 1,459,978,240 B: header @0, FST @0x52400, boot DOL @0x1e000, PsoV3.dol @1,450,489,440
   ├─ .gsl (51)    0x30-byte name/offset/size table @0, data from 0x3000
   │  └─ .bml (1,514 of them)  header 0x40 + 0x40/entry, body 0x20- or 0x800-aligned
   │     └─ PRS payload + optional PRS GVM texture archive
   ├─ .afs (32) + sound.bin   "AFS\0", LE table, 0x800-aligned entries, optional trailing name table
   └─ .prs (53)     bare Sega PRS streams (47 of 53 decode to GVMH texture archives)
```

## 0. Identity read from the image

| fact | value |
|---|---|
| game id (@0x000, 6 ASCII) | `GPOE8P` |
| title (@0x020, NUL-padded) | `PHANTASY STAR ONLINE EPISODE I&II` |
| GC disc magic (@0x01C) | bytes `C2 33 9F 3D` |
| boot DOL offset (@0x420) | `0x1E000` = 122,880; `dol()` returns 213,952 B (entry `0x8000C040`, bss `0x8003FDE0`+29,444) |
| FST offset / size (@0x424/0x428) | `0x52400` = 336,896 / 104,738 (`0x19922`); ends at 441,634 |
| FST entries / files | 3,556 entries = root + 45 dirs + 3,510 files; name table 62,066 B |
| game executable | `PsoV3.dol` @1,450,489,440, **5,233,088 B**, 10 sections, entry `0x8000C040`, bss `0x804FE020`+930,308 |
| file extents | min offset 458,752 (`browser/color.cfg`, 3,543 B); max end 1,459,978,240 = image end; Σ sizes 1,413,083,323 |
| largest files | `ending_normal.sfd` 123,500,544; `psogc_j2.sfd` 85,074,590; `psogc_j.sfd` 56,608,728; `sound.bin` 45,903,872 |
| decompressed image sha256 | `2f1c56b66f2143ed7b15a75c071116b08d6578f16b569f2e831011ad32e1f963` (streamed over all 89,110 blocks) |

`system/gbox/pso_ragol_unlock.py:31` records `OWNED_EXECUTABLE_SIZE = 5,236,992` for `PsoV3.dol`, 3,904 B more than
this image's FST entry. Which build that constant came from is **unproven**; the FST size above is measured.

Probe:

```python
import sys; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
d.game_id, d.title, len(d.files)            # 'GPOE8P', 'PHANTASY STAR ONLINE EPISODE I&II', 3510
d._r(0x1c, 4).hex()                          # 'c2339f3d'
d.files['PsoV3.dol'], len(d.dol())           # (1450489440, 5233088), 213952
```

## 1. The disc image and its FST

The GC header fields `gbox` consumes (all big-endian; `system/gbox/gcdisc.py:17-25`, shared with the fingerprinters
via `system/gbox/formats/gcfst.py:13-17`):

| offset | size | field |
|---|---|---|
| 0x000 | 6 | game id, ASCII |
| 0x01C | 4 | magic `C2 33 9F 3D` (the check `pso_gc_inventory.py:91-93` uses) |
| 0x020 | 0x40 | title, NUL-padded |
| 0x420 | u32 BE | boot DOL offset |
| 0x424 | u32 BE | FST offset |
| 0x428 | u32 BE | FST size |

### FST entry encoding (`system/gbox/formats/gcfst.py:20-39`)

12 bytes per entry, three big-endian words `A, B, C`; entry 0 is the root and the name table follows entry `n-1`
at `12*n`:

| word | file entry | directory entry |
|---|---|---|
| A | top byte = flags (0); low 24 bits = name offset into the name table | top byte = 1; low 24 bits = name offset |
| B | u32 BE absolute disc offset | parent entry index |
| C | u32 BE size | index one past this directory's subtree |

Measured:

| entry | raw 12 bytes | decoded |
|---|---|---|
| 0 (root) | `01000000 00000000 00000de4` | dir, name_off 0, parent 0, next 3,556 |
| 1 | `00000000 0c99bc44 00000fe0` | `abeniji_fe_obj001_niji.bml`, off 211,401,796, size 4,064 |
| 277 | `010017b4 00000000 000003c3` | dir `browser`, parent 0, next 963 |

The walk is a stack of `(prefix, end_index)`; a directory's `C` pops it (`gcfst.py:27-38`). 45 subdirectories,
depth spread: 1,519 files at the root, 1,355 one level down, 96 two, 395 three, 46 four, 99 five (deepest:
`browser/isao/mainte/svrimg/chg1/chg_back.png`). `parse_fst` yields 3,510 rows and `d.files` holds 3,510 keys — no
duplicate paths, so the dict does not silently drop a file.
Downstream, `GCDisc.dol()` (`gcdisc.py:46-52`) recomputes the DOL extent from its 18 section size words;
`dol_to_elf` (`gcdisc.py:55-70`), `rel_link` (`gcdisc.py:98-134`) and `depair` (`gcdisc.py:137-152`) are the
DOL/REL-to-Ghidra path for `PsoV3.dol` and the 649 `.rel` files. Those are code containers, not disc containers,
and are out of scope here.

## 2. GCZ (Dolphin CompressedBlob)

`system/gbox/gcz.py` reads the image in place; `GCDisc` only calls `GCZ.read()` and clears the block cache after
each read (`gcdisc.py:11-34`). Header = 32 bytes, `<IIQQII` (`gcz.py:42-53`), then the pointer table, then the hash
table, then one contiguous data region (`gcz.py:55-64`):

| offset | size | field | this image |
|---|---|---|---|
| 0x00 | u32 | magic `0xB10BC001` | `0xB10BC001` (`gcz.py:32`) |
| 0x04 | u32 | sub_type (0 full, 1 scrubbed) | 0 |
| 0x08 | u64 | compressed data size | 1,177,218,992 |
| 0x10 | u64 | uncompressed disc size | 1,459,978,240 (`0x57058000`) |
| 0x18 | u32 | block size | `0x4000` |
| 0x1C | u32 | block count | 89,110 |
| 0x20 | u64[n] | block pointer: bit 63 = stored raw, low 63 bits = offset in the data region | ptr[0] = 0 |
| 0x20+8n | u32[n] | Adler32 of each **stored** block | see below |
| 0x20+12n | — | data region, block *i* spans `[ptr[i], ptr[i+1])`, last ends at `compressed_data_size` | 1,069,352 |

Tables end exactly at the data region: `0x20 + 8*89110 = 712,912`, `+4*89110 = 1,069,352`, and
`1,069,352 + 1,177,218,992 = 1,178,288,344` = the file size, so there is no slack. `pso_inventory._find_data_start`
(`system/gbox/pso_inventory.py:63-77`), which probes for the first zlib stream instead of trusting the table, also
returns **1,069,352**.

Measured over all 89,110 blocks (`GCZ(path, verify_hashes=True)` plus `read_block` on every index):

| quantity | value |
|---|---|
| raw blocks (bit 63 set) | 3,815, every one exactly 16,384 B (checked by `gcz.py:104-105`) |
| zlib blocks | 85,295 |
| raw bytes / zlib bytes | 62,504,960 / 1,114,714,032, sum = 1,177,218,992 |
| blocks not inflating to 0x4000 | 0 |
| zero-length spans (`ptr[i] == ptr[i+1]`) | **0** — this image has no implied all-zero blocks |
| block 0 | ptr 0, 3,231 stored B → the disc header `GPOE8P` |
| last block | ptr 1,177,210,801, 8,191 stored B, ends at `compressed_data_size` |

The hash table is Adler32 of the **stored** bytes, not of the inflated block (`gcz.py:97-102`). Verified on 8 blocks
including raw ones: block 0 stored-hash `8629add0` = table, inflated-hash `aa4cc080` ≠ table; block 27 (raw)
`6754c39b` = Adler32 of its 16,384 stored bytes.

Two divergences worth recording, neither exercised by this image:

* `gcz.py:107-111` always calls `zlib.decompress`, so an implied zero block would raise; `pso_inventory.py:108-110`
  has the `end == prev → zero block` branch (documented at `pso_inventory.py:24-25`). 0 instances here, so reading
  every block succeeds.
* `pso_inventory.py:17-21` describes the record table as `{u32 cumulative end, u32 flags}` pairs at 0x28 while
  `gcz.py` uses a 0x20-based u64 pointer array plus a separate u32 hash array. Both agree because the offsets fit in
  32 bits: the low word of each u64 is the offset, the high word is the raw flag (`pso_inventory.py:92-94`).

```python
from gbox.gcz import GCZ
g = GCZ(r"...\Phantasy Star Online Episode I & II Plus (USA).gcz", verify_hashes=True)
g.num_blocks, g.block_size, g.data_size, g.compressed_data_size, g._data_offset
# 89110, 0x4000, 1459978240, 1177218992, 1069352
sum(1 for p in g._ptrs if p >> 63)        # 3815 raw blocks
g._block_extent(0)                        # (False, 0, 3231)
g._block_extent(27)                       # (True, 198394, 16384)
```

## 3. PRS (Sega LZSS, `system/gbox/formats/lz.py`)

`prs_decompress` (`lz.py:355-391`) is the codec every PSO GC user calls (`ninja.prs_decompress`,
`pso_gc.bml_entry` at `pso_gc.py:124`, `psoitems.py:127/132`). A control byte precedes its group of eight tokens and
is consumed **LSB first** (`ctrl & 1; ctrl >>= 1` — `lz.py:358-366`):

| control bits | token | payload | length | distance |
|---|---|---|---|---|
| `1` | literal | 1 byte | 1 | — |
| `00` | short back-reference | 1 byte | 2..5 (2 length bits, `(b<<1|b)+2`) | 1..256 (`byte - 256`) |
| `01` | long back-reference | 2 bytes LE `a` | `(a & 7) + 2` = 3..9, or `next_byte + 1` = 10..256 when `a & 7 == 0` | 1..8,191 (`(a>>3) - 8192`) |
| `01`, `a == 0` | **terminator** | — | — | — |

Bit costs (from the encoder, `lz.py:394-487`): 9 bits literal, 12 bits short reference, 18 bits long 3..9,
26 bits long 10..256. The terminator is the long form with `a = 0x0000`, i.e. distance 8,192 — out of range, which
is why `prs_decompress` can test `offset == ~0x1FFF` and stop (`lz.py:377-379`). `prs_compress` ends with
`bit(0), bit(1), b"\0\0"` (`lz.py:485-486`).

**What is PSO-GC-specific: nothing.** These are stock Sega PRS streams: LSB-first flags, no size prefix, terminated
by `a == 0`. The size is out of band — the FST entry for a loose `.prs`, `fields[2]` (dsize) for a BML payload. The
first u32 of `ItemPMT.prs` is `0x31FFFF00`, not 63,680, so no size field is hidden at offset 0.

The MSB-first variant in the same module, `prs_msb_decompress` (`lz.py:58-112`), differs in four concrete ways:
flags are read `(flag >> 7) & 1`, `flag <<= 1` (`lz.py:77-80`); the long-reference 16-bit word is **big-endian**
(`(byte()<<8)|byte()`, `lz.py:100`); the decoder is told `size` by its caller and has **no terminator** (it stops
at `size` bytes and `strict` demands exactly that, `lz.py:110-111`); and the window starts zero-filled, so references
before the output start decode as 0 (`lz.py:107`). It is the Bleach fpack codec (`cnr2.py:63-72`,
`con2_inventory.py:59-64`), not a PSO codec. The `size` is passed in from the container, e.g. the fpk entry header
`{name[0x20], u32 0, u32 offset, u32 stored, u32 original}` (`cnr2.py:13-17,44-60`) — the PRS stream itself has no
leading size field. The codec in `lz.py` that *does* carry one is `vpk0_decode` (`lz.py:568-670`: `"vpk0"` magic +
u32 BE size).

Proof, run on real files (each `prs_decompress`, then `prs_decompress(prs_compress(x))`):

| file | stored | decoded | decoded head | round-trip | recompressed |
|---|---|---|---|---|---|
| `ItemPMT.prs` | 15,673 | 63,680 | `FFFFFFFF 00000001 00010000 40400000` (item table) | True | 15,531 |
| `sega_logo.prs` | 6,449 | 164,304 | `GVMH`, header 328, flags 15, **8** textures `sega_logo01..08` | True | 6,458 |
| `Title.prs` | 295,172 | 984,192 | `GVMH`, header 808, flags 15, **21** textures (`f256_psotitle`, ...) | True | 300,395 |
| `ItemRTT.prs` | 420,996 | 852,928 | `GVMH`, header 680, flags 15, **17** textures (`edura_256pict00..11`, ...) | True | 431,447 |
| `f256_player_tex.prs` | 19,879 | 131,168 | `GVMH`, header 72, flags 15, 1 texture | True | — |

The GVMH parse is `pso_gc.gvm_list` (`pso_gc.py:184-203`), so the decoded head is itself a known format, not just
non-random bytes. Whole-disc census of the extension:

| quantity | value |
|---|---|
| `.prs` files / bytes | 53 / 4,305,207 |
| streams decoding with `prs_decompress` | 52 (all 52 end with the `00 00` terminator) |
| decoded head | 47 × `GVMH`; the other 5 decode to tables: `ItemPMT`, `AdDrawLineTask`, `ItemMagEdit`, `switcher`, `symbolchatcolli` |
| not PRS | `ChatSensor.prs`, 61 B (`00 00 00 80 E3 6B ... 35 21 54 3A`): no valid terminator, decoder raises |

The LSB-first order is visible in the bytes: `sega_logo.prs` starts `7F 47 56 4D 48 ...`. `0x7F` = seven 1-bits then
a 0, so the first seven tokens are literals taken from bytes 1..7 — `G V M H` are the first four decoded bytes. An
MSB-first reading of the same byte starts with `0`, a back-reference, which is exactly why the MSB variant cannot
read these streams. Run on the real files: `ItemPMT.prs` → `ValueError: truncated PRS stream`; `sega_logo.prs` →
`produced 34987 of 164304 bytes`; `Title.prs` / `ItemRTT.prs` → 984,192 / 852,928 bytes of zeros (not equal).

```python
from gbox.formats.lz import prs_decompress, prs_compress
raw = d.read("sega_logo.prs"); dec = prs_decompress(raw)
len(raw), len(dec), dec[:4]                  # 6449, 164304, b'GVMH'
prs_decompress(prs_compress(dec)) == dec     # True
```

## 4. GSL archives (`.gsl`, 51 on the disc)

Magic-less: the whole file is a table of 0x30-byte entries followed by the payloads (`pso_gc.py:73-107`):

| offset | size | field |
|---|---|---|
| 0x00 | 0x20 | name, NUL-padded (longest GSL name is 31 chars, so every entry is terminated) |
| 0x20 | u32 BE | offset in **0x800 sectors** → byte offset = value × 0x800 |
| 0x24 | u32 BE | size |
| 0x28 | 8 | zero |

The table ends at the first entry whose name byte is 0 (`gsl_entries`, `pso_gc.py:76-79`). Measured across all 51
archives: 3,335 entries, the first entry's offset is **12,288 = 0x3000 in every archive**, 1,514 entries are `.bml`,
total 102,166,528 B. The 0x3000 data start leaves 12,288 − 0x30·count zero bytes after the table (max count 160 →
7,680 B table).

| archive | size | entries | first (off, size) | last (off, size) | last end | zero tail | table bytes |
|---|---|---|---|---|---|---|---|
| `gsl_forest01.gsl` | 1,515,520 | 51 | 12,288, 4,340 (`map_forest_e.bin`) | 1,499,136, 14,656 (`bm_ene_npc_chao.bml`) | 1,513,792 | 1,728 | 2,448 |
| `gsl_set_object.gsl` | 1,683,456 | 144 | 12,288, 1,904 (`map_city00_00o.dat`) | 1,665,024, 17,000 (`map_seabed02_01_01o.dat`) | 1,682,024 | 1,432 | 6,912 |

`gsl_build(data, {})` is **byte-identical for all 51 archives** (measured; e.g. forest01 1,515,520 → 1,515,520 True,
set_object 1,683,456 → True). It rewrites `offset = pos // 0x800` and `size` from the same table and only emits the
trailing bytes when `replace` is empty (`pso_gc.py:99-107`), which is why the round-trip closes.

`gsl_forest01.gsl` contents (first entries): `map_forest_e.bin`, `map_forest_f.bin`, `map_forest_g.bin`,
`map_forest_j.bin`, `map_forest_s.bin`, `fe_obj_doa_kanban.bml`, `fe_obj_door.gvm`, `bm_fe_obj_komo.bml`,
`bm_o_abe_butterfly.bml`, `abeno_fs_obj001_fosuno.bml`, ... The enemy packs live only here: `bm_ene_bm1_shark_a.bml`
is entry 31 of `gsl_aversus02.gsl` at 1,466,368, 229,728 B (see §6).

```python
from gbox.pso_gc import gsl_entries, gsl_build
g = d.read("gsl_forest01.gsl"); e = gsl_entries(g)
len(e), e[0], e[-1]                 # 51, ('map_forest_e.bin', 12288, 4340), ('bm_ene_npc_chao.bml', 1499136, 14656)
gsl_build(g, {}) == g               # True
```

## 5. AFS archives (32 `.afs` + `sound.bin`)

Sega AFS, little-endian table (`pso_player.py:33-35`; the GC table is documented at `pso3_inventory.py:38-45`):

| offset | size | field |
|---|---|---|
| 0x00 | 4 | `"AFS\0"` |
| 0x04 | u32 LE | entry count |
| 0x08 | count × {u32 LE offset, u32 LE size} | TOC |
| ... | — | zero padding to the first 0x800 boundary |
| ... | entries | each entry starts on a **0x800 boundary**; gap after entry *i* = `(-size) % 0x800` zero bytes |
| ... | optional | at the next 0x800 boundary after the last entry: `count × 0x30` name records `{name[0x20], 12 bytes, u32 LE size}` |
| ... | — | zero padding to EOF |

The 33 AFS-magic files are the 32 `*.afs` plus `sound.bin` (measured by a 4-byte head census over all 3,510 files;
the other 3,477 have other magics: 343 `GVMH`, 321 `PNG`, 198 `NJCM`, 101 `GJTL`, ...). `sound.bin` is the only AFS
archive without the extension. `PlyLevelTbl.cpt` is **not** AFS — see §7.

| archive | size | entries | TOC bytes | first (off, size) | last end | tail | name table |
|---|---|---|---|---|---|---|---|
| `plAtex.afs` | 1,415,168 | 137 | 1,104 | 524,288, 8,224 | 1,413,664 | 1,504 (zeros) | none |
| `plUtex.afs` | 563,200 | 14 | 120 | 524,288, 8,224 | 561,696 | 1,504 (zeros) | none |
| `sound.bin` | 45,903,872 | 152 | 1,224 | 524,288, 512 | 45,894,432 | 9,440 | 152 records @45,895,680 |
| `ItemModel.afs` | 1,005,568 | 303 | 2,432 | 4,096, 1,425 | 988,579 | 16,989 | 303 records @989,184 |
| `ItemTexture.afs` | 1,695,744 | 324 | 2,600 | 4,096, 3,898 | 1,679,200 | 16,544 | 324 records @1,679,360 |
| `ItemKT.afs` | 1,566,720 | 379 | 3,040 | 4,096, 1,596 | 1,546,261 | 20,459 | 379 records @1,548,288 |

The 29 player/`slbgm` banks start their data at 524,288 (`0x80000`) and end flush at a 0x800 boundary after the last
entry's padding (`plAtex`: 691 × 2048 = 1,415,168); the three `Item*` archives start at 4,096 (`0x1000`) and carry the
name table. Name tables verified field by field: record count == entry count, names in **entry order**
(`player.proj/512`, `player.pool/1668`, `player.sdir/2452`, `player.samp/503872` for `sound.bin`), and the trailing
u32 equals the TOC size for every record in all four archives. The 12 bytes between name and size are not constant:
the first 8 are fixed per archive (`sound.bin` `D2 07 07 00 05 00 0F 00`, `ItemModel` `C1 07 07 00 05 00 03 00`) and
the last two u16 vary per record (`sound.bin`: `26 00 06 00` / `27 00 1E 00` / `23 00 32 00`, 38 distinct blocks in
that archive; 5 in `ItemModel`, 41 in `ItemKT`). Read as 6 u16 LE the block looks like a time (`0x07D2`=2002, 7, 5,
15, 38, 6), but that reading is **unproven**; only the record size (0x30), the order and the size word are proven.

`plAtex.afs`'s first three TOC pairs are `(524288, 8224)`, `(534528, 8224)`, `(544768, 8224)`; its size histogram is
544 × 34, 2,080 × 42, 8,224 × 60, 32,800 × 1 — so the "137 entries of 8,224-byte GVRs" note at
`pso3_inventory.py:8` is an approximation (60 of 137). `plUtex.afs` is `(524288,8224)`, `(534528,544)`,
`(536576,2080)`, ..., last `(561152,544)`; histogram 544 × 12, 2,080 × 1, 8,224 × 1. **All 137 and all 14 entries
start with `GBIX`** (none start at `GVRT`), and 8,224 decomposes exactly:

```
8,224 = GBIX(8: "GBIX" + u32 LE 8) + GVRT header(16) + texels(8,192)
GVRT size field (u32 LE @+4) = 8,200 = 8 + 8,192;  w,h = 128 x 128 (u16 BE);  fmt byte @+0x0B = 0x0E (CMPR)
```

`pso_gc.afs` / `pso_player.afs` return exactly `count` slices and each slice equals `data[off:off+size]` (checked
for every entry of `plAtex` and `plUtex`).

```python
import struct
from gbox.pso_player import afs
a = d.read("plAtex.afs"); n = struct.unpack_from("<I", a, 4)[0]
toc = [struct.unpack_from("<II", a, 8 + 8 * i) for i in range(n)]
n, toc[:3], len(afs(a)), sorted({o % 0x800 for o, s in toc})
# 137, [(524288, 8224), (534528, 8224), (544768, 8224)], 137, [0]
```

## 6. BML model packs (299 loose + 1,514 inside GSL = 1,813 packs)

Big-endian on GC; the reader is `pso_player.bml_files` with `e=">"` (`pso_player.py:226-242`, reached through
`pso_gc.bml_files/bml_build/bml_entry`, `pso_gc.py:110-129`). Magic-less header, `0x40 + 0x40·count` bytes, then the
body at `bml_start(n) = align(0x40 + 0x40·n, 0x800)` (`pso_player.py:205-207`).

File header (0x40), measured on all 299 loose packs:

| offset | size | field | observed |
|---|---|---|---|
| 0x00 | u32 | zero | 0 in 299/299 |
| 0x04 | u32 BE | entry count | 1..109 loose, 1..52 inside GSL |
| 0x08 | u32 | version-ish word, unused by every reader | `0x50010000` in 296/299; `0x50000000` in `boss06_rock_dat.bml`, `boss06_tube_dat.bml`; 0 in `bm_technic.bml` |
| 0x0C | u32 | zero | 0 in 299/299 |
| 0x10..0x3F | 48 | zero | 0 in all 298 parseable packs |

Entry (`0x40` bytes at `0x40 + 0x40·i`), fields at `+0x20` read as `>5I` by `bml_files`:

| offset | size | field | meaning (proven by decode) |
|---|---|---|---|
| 0x00 | 0x20 | name, NUL-padded | 8 payload names fill all 32 bytes (no NUL), so readers must not require one |
| 0x20 | u32 BE | `csize` | stored payload bytes |
| 0x24 | u32 BE | `f1` | **unproven**; 0 in `plAnj.bml`, `0x1B`/`0x36`/`0x51` in the shark pack, 122 distinct values over loose packs |
| 0x28 | u32 BE | `dsize` | decompressed payload bytes (0 = payload stored raw) |
| 0x2C | u32 BE | `cgvm` | stored texture-archive bytes (0 = no texture) |
| 0x30 | u32 BE | `dgvm` | decompressed texture bytes |
| 0x34 | 12 | zero | 0 in all 9,648 entries of the 1,812 big-endian packs |

Body: for each entry in order, `csize` bytes of PRS, zero pad to the pack's alignment, then (if `cgvm`) `cgvm` bytes
of PRS and pad. Alignment is 0x20 for 276 packs and 0x800 for 22 (`bml_align`, `pso_player.py:210-223`, picks the one
whose laid-out entries end at the file end).

`plAnj.bml` (loose, FST offset 1,294,143,732, 59,392 B): 13 entries, all `NJCM`, alignment 0x800, header
`0, 13, 0x50010000, 0`:

| # | name | csize | f1 | dsize | decoded |
|---|---|---|---|---|---|
| 0 | `plAbdy00.nj` | 16,226 | 0 | 21,308 | `NJCM` |
| 1 | `plAcap06.nj` | 359 | 0 | 456 | `NJCM` |
| 2..11 | `plAhai00..09.nj` | 3,250 / 2,818 / 1,632 / 1,867 / 1,898 / 1,359 / 1,381 / 4,118 / 2,820 / 2,309 | 0 | 3,532 / 3,408 / 2,364 / 2,316 / 2,220 / 1,680 / 1,744 / 4,816 / 3,104 / 3,188 | `NJCM` |
| 12 | `plAhed00.nj` | 4,284 | 0 | 4,964 | `NJCM` |

Σ csize 44,321, no textures, `bml_start(13) = 2,048`, laid-out end 59,392 = file size (tail 0), `bml_build(d,{})`
**identical**.

`bm_ene_bm1_shark_a.bml` (inside `gsl_aversus02.gsl`, entry 31, offset 1,466,368, 229,728 B): 15 entries, alignment
**0x20**, `bml_start(15) = 2,048`:

| # | name | csize | f1 | dsize | cgvm | dgvm | decoded |
|---|---|---|---|---|---|---|---|
| 0 | `bm1_s1_wala_body.nj` | 9,294 | 0x1B | 13,068 | 54,295 | 73,920 | `NJTL` + `GVMH` |
| 1 | `bm1tl_s_wala_body.nj` | 8,319 | 0x36 | 11,784 | 54,665 | 73,920 | `NJTL` + `GVMH` |
| 2 | `bm1_s_wala_body.nj` | 9,306 | 0x51 | 13,060 | 55,256 | 73,920 | `NJTL` + `GVMH` |
| 3..14 | `appear/atackl/atackr/damage/deadb/dead/leader/mihari/run/stund/wakeup/walk_bm1_s_wala_body.njm` | 2,135..3,740 | 0x51 | 3,372..5,416 | 0 | 0 | `NMDM` motions |

Σ csize 63,233, Σ cgvm 164,216, laid-out end 229,728 = file size (tail 0), `bml_build(d,{})` **identical**; every
texture archive inflates to exactly 73,920 B and starts `GVMH`.

Disc-wide census over the 1,812 packs that parse big-endian / 9,648 entries (the little-endian pack's 42 entries are
not counted here):

| quantity | value |
|---|---|
| entries whose PRS payload inflates to exactly `dsize` | 9,631 |
| entries with `csize == dsize` (the "stored raw" convention used by `pso_gc.py:124` / `pso_enemy.py:195`) | **0** |
| texture-carrying entries | 2,624, all `cgvm != dgvm`, all inflate to `dgvm` |
| `bml_build(data, {})` byte-identical | 298 of 299 loose packs; 1,514 of 1,514 packs inside GSL archives |
| exceptions | `bm_technic.bml` (17 entries) and `fe_obj_hira_kage.bml` — see below |

Two real exceptions, both worth knowing before writing a pack:

* `bm_technic.bml` (124,928 B, 17 entries, header word @0x08 = 0): every entry has `dsize = 0` and the payload is
  **stored raw**, e.g. entry 0 `eff_f_bartaturara.gj`, csize 1,920, first bytes `47 4A 43 4D 60 07 00 00` = `GJCM` +
  chunk size 1,888, `POF0` at +1,896, entry length 1,920 = 8 + 1,888 + 24. The laid-out body ends exactly at
  124,928 with alignment 0x800. The `csize != dsize ⇒ PRS` test therefore mis-fires on these 17 of 9,648 entries
  (`prs_decompress` raises `IndexError`), even though the pack parses.
* `fe_obj_hira_kage.bml` (625,632 B) is a **little-endian** BML: count 42 read as `<I` at +4, entry fields LE
  (`[161, 0, 312, 222, 608]`, `[416, 1, 700, 1928, 18528]`, ...), first name `fe_obj_hira_kage.nj`. It parses with
  `bml_files(data, "<")` (entry 0 inflates to 312 B of `NJTL`) and fails with `">"`. So 298/299 loose packs are
  big-endian and one is a Dreamcast-layout pack.

```python
import struct
from gbox.pso_player import bml_files, bml_build, bml_start, bml_align
from gbox.formats.lz import prs_decompress
b = d.read("plAnj.bml")
n = struct.unpack_from(">I", b, 4)[0]
n, bml_align(b, ">"), bml_start(n), b[:0x10].hex()   # 13, 0x800, 2048, '000000000000000d5001000000000000'
e = bml_files(b, ">")[0]
e["name"].split(b"\0")[0], e["fields"], len(prs_decompress(e["raw"]))   # b'plAbdy00.nj', [16226,0,21308,0,0], 21308
bml_build(b, {}, None, ">") == b                     # True
```

## 7. Open items (explicitly unproven) and traps

* **BML `f1`** (word at entry +0x24): not read by any module in the repo. 0 is the most common value (904 entries in
  loose packs), the shark pack uses 0x1B/0x36/0x51, GSL packs add 27, 30, 31, 32, 135, ... 122 distinct values over
  loose packs, 87 over GSL packs. Meaning **unproven**.
* **AFS 12-byte record field**: record layout, order and size word are proven; the date/time reading of the 12 bytes
  is **unproven**.
* **`bm_technic.bml`'s header word 0** and its raw-payload convention: measured, not explained.
* **`ChatSensor.prs`** (61 B) is not a PRS stream and has no known container here — **unproven**.
* **`PlyLevelTbl.cpt`** (11,774 B @746,162,788) is not AFS and not a plain PRS stream. Its head
  `00 00 71 00 F3 5D 62 CE` matches the `.pr2` shape `{u32 BE size, u32 BE key}` (`psotext.py:2,47-49`), and
  `pr2_decode(blob, ">")` yields 28,928 B, i.e. it is a ciphered stream like `TextEnglish.pr2` (45,408 B →
  107,852 B, head `Mononate`). The decoded payload format is out of scope / **unproven**. `PlyMotionNpcTown.cpt`
  behaves the same way (7,948 B → 13,696 B); `pso_gc_inventory.py:144` only calls it "compressed".
* **GCZ zero blocks**: `gcz.py` has no zero-block branch (see §2). This image has none, so it is latent, not a bug
  proven against real data.
* **`pso_ragol_unlock.py:31`'s 5,236,992-byte `PsoV3.dol`** does not match this image's 5,233,088 B.
* Do not regress the two proven writer invariants: `gsl_build(data, {}) == data` (51/51) and
  `bml_build(data, {}, None, ">") == data` (298/299 loose + 1,514/1,514 in GSL). Both depend on keeping the original
  alignment (0x800 for every GSL archive, 0x800 for 22 BML packs, 0x20 for 276) and, for GSL, the original table area
  and zero tail.
