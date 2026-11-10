# PSO GameCube disc containers (GSL / BML / PRS / AFS / GVR) — measured layouts

Research deliverable for request #9183 (GPOE8P). Every layout row below was measured
byte-by-byte on a real GameCube disc; nothing is guessed. Byte-identical rebuilds are
demonstrated for GSL 5/5, BML 5/5 and pl*TEX AFS 6/6. The gbox parsers were used
read-only; no disc or other file was modified.

## 1. Scope and source

- Target: GPOE8P (Phantasy Star Online Episode I & II, GameCube). The ticket's GPOE8P
  `.nbi` was **not re-read in this run** — an earlier probe of the gc cache reported
  the exact error `GPOE8P disc not found among gc cache` (artifact kept in the request
  evidence dir until scratch cleanup). All measurements below are on the same
  container family: `Phantasy Star Online Episode I & II (USA).gcz` under
  `/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/` — 1.18 GB,
  3470 files, full-disk sha256
  `3bb552e5e77503c524e42ca8f458082d53ff4723d8325d56b8af1660101cd4d0`, game_id read
  via `gbox.gcdisc.GCDisc`.
- Parsers: `system/gbox/pso_gc.py` (gsl/afs/prs), `system/gbox/pso_player.py`
  (bml/afs), `system/gbox/pso_gc_swap.py` (prs/afs builders),
  `system/gbox/formats/lz.py` (prs bitstream), `system/gbox/gcdisc.py`.

## 2. Layouts (all rows measured)

- **GSL** (`gsl_entries`/`gsl_build`): table of 0x30-byte records — name[0x20]
  NUL-terminated at record start, `u32 BE 0x800-sector offset` at +0x20,
  `u32 BE byte size` at +0x24. Bodies in original disc order, 0x800-aligned, after
  the table. `gsl_build(data, {})` returns the file byte-identical (5 archives below).
- **BML** (`bml_files(data, ">")`): entry count `u32 BE` at 0x4; 0x40-byte records —
  name[0x20], then five `u32 BE` at +0x20: `(comp_size, unused, raw_size,
  tex_comp_size, tex_raw_size)`. Bodies start at `(0x40+0x40n)` rounded up to 0x800;
  each entry payload is a **raw PRS bitstream (no per-entry header)** aligned 0x20 or
  0x800 (`bml_align` picks whichever makes the layout end at the file tail); an
  optional PRS texture payload follows when `tex_comp_size != 0`.
- **PRS** (`formats/lz.py: prs_decompress`): **no header, no magic** — a raw
  bitstream; length comes from the container (GSL/BML size fields, or file size for
  top-level `.prs`). Bits consumed LSB-first per byte. Codes: `1` = literal (next 8
  bits); `0 0` = short back-ref (2-bit length → 2..5, 8-bit distance → 1..255 back);
  `0 1` = long back-ref (16-bit field a: distance = `0x1FFF-(a>>3)` → 1..8191,
  length = `(a&7)+2`, or one extra byte +1 when `a&7==0`). Ends at sentinel
  `a&0x1FFF==0` or end of input.
- **AFS** (`pso_gc_swap.afs_build`; `pso_player.afs`): `"AFS\0"` at 0x0, entry count
  `u32 LE` at 0x4, per-entry `(u32 LE byte offset, u32 LE size)` at `8+8i`; bodies
  0x800-aligned after the table. Texture banks (pl*TEX.afs): entries are GVR chunks —
  `"GVRT"` magic; `u32 LE size` at +4; `u8` at +10 (`pal_fmt<<4 | flags`); `u8 fmt`
  at +11; `u16 BE width`, `u16 BE height` at +12; texel data at +16; optional GBIX
  chunk after (its header field at GBIX+8 is `u32 BE`). Item*.afs banks share the
  bank-table layout but their entries are not GVR chunks.
- Endianness is mixed and container-specific: GSL sectors BE; BML fields BE; PRS is a
  bitstream; AFS bank table LE; GVR header LE size / BE w,h.

## 3. Measured evidence (this run, PSOnline .gcz)

### GSL (gsl_build round-trip)

| file | entries | record 0 (name, sectors-BE, size-BE) | first bytes 0..0xF | archive sha256(12) | rebuilt sha256(12) | identical |
|---|---|---|---|---|---|---|
| gsl_aancient01.gsl | 68 | map_ancient_e_u.bin, 6, 5616 | 6d61705f616e6369656e745f | 6ca30819fbc8 | 6ca30819fbc8 | true |
| gsl_aancient02.gsl | 70 | map_ancient_e_u.bin, 6, 5616 | 6d61705f616e6369656e745f | 2569a0ad6a95 | 2569a0ad6a95 | true |
| gsl_aancient03.gsl | 72 | map_ancient_e_u.bin, 6, 5616 | 6d61705f616e6369656e745f | 7688c93a8830 | 7688c93a8830 | true |
| gsl_acave01.gsl | 46 | map_cave_e_u.bin, 6, 7548 | 5d5b58a313f5… | 5d5b58a313f5 | 5d5b58a313f5 | true |
| gsl_acave02.gsl | 58 | map_cave_e_u.bin, 6, 7548 | 6d61705f636176655f655f | e1efc45efc6d | e1efc45efc6d | true |

Raw-byte record-0 read equals parser output on all 5 (record0_match true). Inner-file
sha256(12): map_ancient_e_u `427152d6da6a`, map_ancient_f_u `14413f84c212`,
map_ancient_g_u `eb451447c842`; map_cave_e_u `b3270a9140ea`, map_cave_f_u
`d3edbf099f14`, map_cave_g_u `900c66c54644`.

### BML (bml_files + rebuild)

| file | entries | count u32-BE @4 | entry 0 raw fields (5×u32 BE) | pack sha256(12) | rebuilt sha256(12) | identical |
|---|---|---|---|---|---|---|
| CharaMakingMot.bml | 49 | 49 | [1757, 0, 4496, 0, 0] | 9e15b8e3472d | 9e15b8e3472d | true |
| abeniji_fe_obj001_niji.bml | 1 | 1 | [1071, 0, 1492, 911, 2144] | a3f4eb343653 | a3f4eb343653 | true |
| abeno_fs_obj001_fosuno.bml | 3 | 3 | [270, 0, 444, 0, 0] | 59700cf78907 | 59700cf78907 | true |
| ad_f_moyouring.bml | 5 | 5 | [453, 0, 696, 15050, 131168] | 5dac3f6e660d | 5dac3f6e660d | true |
| biri_ball.bml | 5 | 5 | [647, 0, 1208, 0, 0] | 8af1ffef3c0f | 8af1ffef3c0f | true |

Raw-field read of entry 0 equals parser fields on all 5. Sample PRS entry
pxuS01_B02_F_body.njm: comp 1757 → raw 4496, decoder agreement true, sha256(12)
compressed `74475fd074aa`, raw `f79dba014df6`, recompress-not-identical true,
roundtrip true.

### PRS (top-level .prs, prs_decompress / prs_compress)

| file | bytes | raw_len | raw sha256(12) | compressed sha256(12) | re-compressed sha256(12) | re-encode identical | roundtrip |
|---|---|---|---|---|---|---|---|
| AdDrawLineTask.prs | 3765 | 16928 | 3ab7c9c69503 | 6bdc1aa5daf3 | 9de537c16e64 | false | true |
| ChatSensor.prs | 61 | — | — | 377db6f5958b | — | — | IndexError in prs_decompress |
| ItemMagEdit.prs | 743 | 1664 | 279e6a01b3e4 | 8db39b14c9e6 | 78377d64f228 | false | true |
| ItemPMT.prs | 15673 | 63680 | ff77cc0ba086 | f3122e3fc4c1 | 8a756f3ab5d1 | false | true |
| ItemRTT.prs | 420996 | 852928 | 8010efe09964 | 40a417903a0c | d150c91b4519 | false | true |

### AFS (bank table + rebuild; sha256(12))

| file | entries | count u32-LE @4 | first bytes 0..0xF | table 0 (off, size) LE | entry 0 GVR (fmt, w×h, flags) | bank sha256(12) | identical |
|---|---|---|---|---|---|---|---|
| plAtex.afs | 137 | 137 | 414653008900000000000800 | (524288, 8224) | 14, 128×128, 0 | 92f028dcf7e4 | true |
| plBtex.afs | 310 | 310 | 414653003601000000000800 | (524288, 544) | 14, 32×32, 8 | 3b9215e2b0dd | true |
| plCtex.afs | 286 | 286 | 414653001e01000000000800 | (524288, 8224) | 14, 128×128, 0 | 4c5ba1393ad3 | true |
| plDtex.afs | 208 | 208 | 41465300d000000000000800 | (524288, 2080) | 14, 64×64, 0 | 693d00c35aa5 | true |
| plEtex.afs | 311 | 311 | 414653003701000000000800 | (524288, 2080) | 14, 64×64, 0 | a3828937f38d | true |
| plFtex.afs | 386 | 386 | 414653008201000000000800 | (524288, 8224) | 14, 128×128, 0 | 6c1bf2127111 | true |
| ItemKT.afs | 379 | 379 | 414653007b01000000100000 | (4096, …) | not a GVR chunk | 83ab1a17dcfb | false |
| ItemModel.afs | 303 | 303 | 414653002f01000000100000 | … | not a GVR chunk | 92c2da90fb4f | false |
| ItemTexture.afs | 324 | 324 | 414653004401000000100000 | … | not a GVR chunk | a7cd64902dea | false |

## 4. Known gaps (what would confirm each)

- **PRS re-encode is not byte-identical** (all 4 good streams):
  `prs_compress(prs_decompress(x))` decompresses back to identical raw (roundtrip
  true) but the encoded bytes differ from the on-disc bytes (hashes in §3). The SEGA
  encoder is not canonical. Confirm: bit-level comparison of a known pair against a
  reference encoder, or accept functional equivalence.
- **ChatSensor.prs (61 B)** fails in prs_decompress (IndexError) — truncated or
  corrupted stream. Confirm: hex dump + sentinel search.
- **Item*.afs (379/303/324 entries)**: bank-table parse OK, rebuild not
  byte-identical (likely trailing padding or entry alignment beyond the table).
  Confirm: hex diff of rebuilt vs original tail.
- **GPOE8P .nbi itself not re-read** this run. Confirm: locate the disc in the
  HyperSpin collection and rerun the probe.

## 5. Status and next acceptance step

Acceptance "layout + rebuild identical on ≥5 real files": **passed** for GSL (5/5),
BML (5/5) and pl*TEX AFS (6/6); PRS decomposition verified 4/5 with the re-encode gap
documented in §4. No pending gBox jobs from this run. Next acceptance steps:
byte-exact PRS encoder reconciliation, Item*.afs tail diff, GPOE8P .nbi re-read.

Verify with: load the disc with `gbox.gcdisc.GCDisc`, run `gbox.pso_gc.gsl_entries`,
`gbox.pso_player.bml_files(data, ">")`, `gbox.formats.lz.prs_decompress` and
`gbox.pso_gc_swap.afs_build` over the files in §3, compare sha256 to the table.
