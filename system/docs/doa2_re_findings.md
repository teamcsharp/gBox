# Dead or Alive 2 — Limited Edition (Japan): native RE findings and the reader slice

Request #1135 (Ghidra decomposition / character import+replace), gap #1140 (missing native Dreamcast
character writer). Platform: Dreamcast GD-ROM, game_id `1de2e7634f3161ff`.

## Provenance (all hashes sha256, source disc read-only)

| artifact | sha256 |
|---|---|
| `Dead or Alive 2 - Limited Edition (Japan).chd` (source, never written) | chd sha1 `75fb157dc9a72ee2a3edd3db57940366de3a5ca3` (staging record) |
| `1ST_READ.BIN` (from CHD via `chdman extractcd`, 1,929,928 B) | `27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1` |
| `doa2le.elf` (wrapper ELF for Ghidra, load 0x8C010000) | `0d5e404e2a97909d0783588f5b5295cee368831e0aa26f362354c69a4649974b` |
| `DOA2/KAS00.CHR` | `63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee` |
| `DOA2/KAS00.BIN` | `49e09538244a8617c1457ed5c81b0b502f51c8392a772e9536630599dfd335d1` |
| `DOA2/KAS00.SUP` | `543fad8818d965826a5b6ee4c945794470058ec6179e60b29a0dc7a51895a987` |
| `DOA2/KASUMI.MOT` | `ed4f2476807cdde2aad940b05b7a7935b55e56704e3dcbfdd425a6e162c586be` |

Ghidra 12.1.4 headless, processor `SuperH4:LE:32:default`, analysis succeeded (118 s). `1ST_READ.BIN`
is **unscrambled** (NOP sled `0x0009` at entry; SH-4 `mov.l` literals resolve) and loads at
**0x8C010000** — consistent with `gbox.re_lab_tool`'s DC_BASE.

## Verified asset layout (this run)

- 960 files on the GD-ROM; character assets under `DOA2/` as per-costume triples
  `<KEY><NN>.BIN` (textures), `<KEY><NN>.CHR` (model+skeleton), `<KEY><NN>.SUP` (physics supplement),
  plus per-character `<NAME>.MOT` (moves).
- Costume families from the disc: KAS×9, AYA/TIN/HIK×7, GEN/LEI×6, ZAC/RYU/KTE/JAN×5,
  BAS/BAY×4, SAM×3, TNG×2, singletons LOR/MAM/PDG/WBA/YTI (variants).
- Filename string tables live at `1ST_READ+0x157424..0x158d00`; pointer tables of those strings at
  `+0x16e740..0x16f400` (e.g. `"kas00.chr"` str @0x1581d4, its pointer @0x16ea7c).
- Loader I/O goes through function-pointer tables: `FUN_8c011ee4` (open/stat/read/close via
  `PTR_FUN_8c012000..8c012020`), same pattern in `FUN_8c0121c0` (references struct @0x8c17f310) and
  `FUN_8c01c35c` (retry loop). 32 code sites reference the shared asset-name table @0x8c17e774.

### CHR container (parser in `gbox/doa2_chars.py::parse_chr`)

Header u32[9] + 3 floats: `[0]=24`, `[1]=object-ptr-array offset`, `[2]=tail offset`, `[3]=n_objects`,
`[4]=n_bones`, `[5]=0 [6]=1 [7]=1 [8]=0`, `+0x24: float×3` (character scale, Kasumi
0.18116/0.01111/0.17960). Object pointers are **absolute SH-4 work-RAM addresses** — fighters
(KAS/AYA/GEN/…) base `0x0C300000`, system CHR (EFC0/FIX) base `0x0C400000`; file offset = ptr − base.
Tail = `n_bones × {float3}` (all-zero for Kasumi; likely bind offsets/scale used elsewhere).
Verified counts: Kasumi 56 objects/55 bones, Ayane 48/45, Gen Fu 52/52, EFC0 122/75, FIX 93/2.

### SUP / MOT

SUP: u32 offset table (Kasumi: 10 records, first at +44) then float records (soft-body/physics).
MOT: u32 offset table — Kasumi lists 1004 clip offsets with repeats (shared clips), first clip at
+0x1898.

## What this run shipped

`gbox/doa2_chars.py`: read-only readers `parse_chr`, `parse_sup`, `parse_mot_table`, disc-driven
`roster()` (19 entries with costume lists) and `export()` producing a UAP-shaped manifest with
verified container+skeleton facts and per-dimension confidence (geometry honestly `missing`).
Routed as dedicated extractor `doa2` in `gbox/characters.py` DEDICATED (Dead or Alive 2, dreamcast).
Tests: `tests/test_doa2_chars.py` — 10 passed (synthetic fixtures anchored to the real KAS00.CHR
header words).

## Slice 2 (commit pending): mesh + texture decode — corrected CHR layout

**Correction to slice 1:** header word[4] and the 12-byte tail table describe **textures**, not
bones (established independently on the JAY lane from real binary bytes; re-verified here against
the owned KAS00: word[4]=55 descriptors, sizes sum exactly to the 332,800-B BIN). The slice-1
"n_bones/bind triplets" reading and the "+0x24 character scale floats" interpretation are
withdrawn — model 0's `{flags, sphere}` preamble sits at +0x24..0x3c inside the model area, and
those floats are its bounding-sphere center/radius. Kasumi has **56 models / 55 textures**, not
56 objects / 55 bones.

Verified NL1 mesh grammar (all on owned bytes, `parse_meshes` in `gbox/doa2_chars.py`):
model = 24-B `{2u32 flags, 4f sphere}` preamble, then submeshes until a `{0, vertex_count}` end
marker whose count must equal the walked inline+referenced vertex total, then zero padding.
Submesh = 80-B native material header (word0>>29==4; +32 texture id, +36 shader, +76 payload
length) + strip blocks `{flags, count}`: flags&8 = indexed list (count triples), else strip;
flags&3 = culling. Vertex records: inline 32 B `{3f pos, 3f nrm, 2f uv@+24}` (56 B for shader -2;
shader -3 packs the normal as 3 signed bytes, uv@+24), or 8-B back-references
`{0x5ff000xx, i32 rel}` to an earlier inline record in the same submesh. KAS00 shader census:
`{1:109, 0:14, 2:1, 5:6, -1:15}` submeshes. Bbox of all decoded vertices: x[-0.238,0.222]
y[-0.571,1.205] z[-1.000,0.415] — human scale, no non-finite floats, all refs resolve.

Texture decode: descriptors `[u16 w, u16 h][u8 pix, u8 fmt, u16 pad][u32 addr]`, addresses
relative to the first texture, indexing the costume `.BIN` (headerless native payloads).
pixel 0/1/2 = ARGB1555/RGB565/ARGB4444; format 1/0xD = twiddled 16-bit, 3 = 8-bit VQ
(2048-B codebook + w*h/4). `pvr_wrap` synthesizes the omitted PVRT header and decodes via
`gbox.ninja.pvr_decode`; 53/55 KAS00 textures carry real image content (std>3).

Cross-archive decode results (owned extracts, `parse_meshes` + `parse_textures` where BIN present):

| archive | models | submeshes | vertices | triangles | textures |
|---|---|---|---|---|---|
| KAS00.CHR | 56 | 145 | 11,844 | 8,672 | 55 (BIN 332,800 B, exact fit) |
| AYA00.CHR | 48 | 98 | 12,060 | 9,138 | — |
| GEN00.CHR | 52 | 108 | 9,742 | 7,444 | — |
| EFC0.CHR | 122 | 123 | 8,192 | 6,760 | — |
| FIX.CHR | 93 | 93 | 406 | 210 | — |

`export_assets` now emits per-texture PNGs, a static skinned-shape glTF (textures attached by
native texture id; weights zeroed — rig is NOT in CHR, it lives in the SUP/ACS route) and a UAP
manifest with per-dimension confidence honestly set (geometry/textures verified, skeleton missing).

## Slice 3 (commit pending): SUP seam grammar + native 17-joint rig

**Correction to slice 1's SUP reading:** the "offset table of float records (physics supplement)"
is actually the **seam/skin directory** (grammar verified on all 80 owned costume SUPs, 906 seams):

- Directory: `u32 dir_size` (= 4·(n+1), 4-aligned, == seam-0 offset), n−1 further monotonic
  starts, one 0 sentinel; `first == 0` means an empty (disabled) seam list.
- Seam record: `{u32 data_ptr, u8 bone_a, u8 bone_b, u8 model_id, u8 initialized}` with
  `data_ptr == offset+8`, bones < 44 (MOTs carry 44 tracks), then **18 floats = three interleaved
  column pairs (A_k, B_k)** — two 3×3 orthonormal bases linking the two joints' neutral
  orientations (native relation `R_a·A = R_b·B`; all owned seams carry A = identity).
  `model_id` indexes the costume CHR's models (the seam/bridge mesh).
- Disc-wide seam graph: 18 distinct joint pairs covering all 15 core joints (hands 5/11 only via
  KAS04/PDG01) + Tengu wings 17–22 (TNG only).

Reader rig (`gbox/doa2_chars.py::build_rig`): joint rotations solved from the disc-wide SUP seam
graph (anchor pelvis=2, cross-costume consistency enforced), translations from the EXE
rest-vector table `0x8c1949a0` (25 slot pointers → 17×xyz; KAS slot 5, GEN slot 6), eyes 15/16
neutral from head. **Cross-lane validation: world rest matrices match the writer lane's
independent `doa2-native-rig-v1` profiles (gbox-doa2-animation/*_profile.json) exactly — max
element delta 0.0 on all 17 joints, both KAS and GEN.** `export_assets` now emits a real
skinned-shape glTF (17 named joints chest/head/pelvis/…/right_breast_16 + skin + inverse binds);
manifest confidence `skeleton: verified`, `skin_weights: missing` (the model→joint emit map is a
render-script fact — geometry alone cannot derive it: rotation-invariant pivot test failed 0/56).

## Not yet done (next slice, in order)

1. Skin weights via the render-script emit map (`0x8c1c85f4` table; PR #8's
   `doa2_bindings.render_part_mapping` route) — then weights can attach to the reader rig.
2. MOT clip decode (1004 Kasumi clips) still open.
3. Reader-route parity with the writer lane (PR #8): fold the corrected SUP layout into
   `doa2_morphs.inspect_sup` assumptions when that branch merges.
4. Emulator verification of the reader output is N/A (read-only); the writer route's gameplay
   acceptance on JAYBUILTFINALE remains the gate for #1140.
