# PSO GC (GPOE8P) — texture formats

Texture formats of *Phantasy Star Online Episode I & II Plus (USA)*, `GPOE8P`, read out of the
disc with gBox's own code. Every number below was computed in this session; every layout claim is
either byte-verified on real files or marked **unproven**. No image data or extracted asset is
stored here — sizes, offsets, ids and hashes only.

Disc (read-only, never written): `D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz`
— `GCDisc` reports `GPOE8P PHANTASY STAR ONLINE EPISODE I&II`, 3510 files, opened with
`d = GCDisc(<that path>)` after `sys.path.insert(0, r"C:\_tools\gBox\system")`.

Extension census (3510 files): `.bml` 299, `.gvm` 343, `.gj` 101, `.gsl` 51, `.prs` 53, `.afs` 32,
`.gvp` 26, `.tp` 13, `.gvr` 5. Readers used: `system/gbox/pso_gc.py:139-208` (`gvr_header`,
`gvr_decode`, `gvm_entries`, `gvm_list`, `png_bytes`), `system/gbox/melee_models.py:99-194`
(`_rgb5a3`, `_rgb565`, `_ia8`, `_palette`, `_BLOCK`, `tex_size`, `_untile`, `decode_texture`),
`system/gbox/pso_player.py:33-35` (`afs`), `system/gbox/pso_gc_swap.py:56-131` (GVR rewrite),
`system/gbox/pso_face_build.py:279-311` (length-preserving rewrite),
`system/gbox/formats/texture.py:147-157` (`gc_tiles`, the same block order).

A **GVR chunk** is the unit everything else is built from: an optional `GBIX` chunk followed by one
`GVRT` chunk. **GVM** (`GVMH`) archives concatenate GVR chunks behind a name table; **AFS** banks
concatenate them behind an offset table; `.prs` and `.bml` carry whole PRS-compressed GVMs; `.GVP`
carries only a palette.

## 1. GVR — `GBIX` + `GVRT`

### 1.1 `GBIX` (global texture id) — 16 bytes, optional

| off | size | field | observed |
|---|---|---|---|
| 0x00 | 4 | magic `GBIX` | always |
| 0x04 | 4 | u32 **LE** chunk size | `8` in 5/5 loose `.gvr` and 286/286 `plCtex.afs` entries |
| 0x08 | 4 | u32 **BE** global texture id | e.g. `0x00186AFB` = 1600251 (`nk_h032_fish1.GVR`) |
| 0x0C | 4 | zero pad | `00 00 00 00` |

`pso_gc.gvr_header` (pso_gc.py:144) reads the id as BE at `find('GBIX')+8`; `pso_gc.gvm_entries`
(pso_gc.py:175-176) skips the chunk with `o += 8 + u32le(o+4)`, i.e. the size field counts the id
plus the 4 pad bytes, so the chunk is 16 bytes. All 7416 GVM-hosted textures report `gbix=None` —
**GVMs carry no `GBIX`**; ids appear only in loose `.gvr` files and in `pl*.afs` banks.

### 1.2 `GVRT` — 16-byte header + texels

| off | size | field | observed on this disc |
|---|---|---|---|
| 0x00 | 4 | magic `GVRT` | — |
| 0x04 | 4 | u32 **LE** chunk size = `len(chunk) - 8` | 520, 8200, 2056, 8208, 32784, 131088 … |
| 0x08 | 2 | zero | `00 00` in 7421/7421 chunks |
| 0x0A | 1 | palette format (high nibble) \| data flags (low nibble) | high nibble **0 in 7421/7421**; low nibble ∈ {0,1,8,9,10} |
| 0x0B | 1 | GX texture-format byte | 5, 8, 9, 14 (see §2) |
| 0x0C | 2 | u16 **BE** width | 8 … 512 |
| 0x0E | 2 | u16 **BE** height | 8 … 512 |
| 0x10 | n | texels, then the mip chain if bit 0 is set | — |

`gvr_header` (pso_gc.py:139-148) returns exactly these fields and puts `data = gvrt + 16`.
`tex_size(fmt, w, h)` (melee_models.py:131-133) gives the level-0 texel byte count.

Verified on the three smallest loose files:

| file | size | gbix | fmt | flags | w×h | level-0 bytes | chunk−data | RGBA sha256[0:16] |
|---|---|---|---|---|---|---|---|---|
| `nk_h032_fish1.GVR` | 544 | 1600251 | 14 CMPR | 8 | 32×32 | 512 | 512 | `0bd51a4a582006b8` |
| `indtex.gvr` | 8224 | 803000 | 14 CMPR | 0 | 128×128 | 8192 | 8192 | `0bd6ba5e05f03dfc` |
| `f032_uzu.GVR` | 2080 | 785961 | 5 RGB5A3 | 8 | 32×32 | 2048 | 2048 | `6eb5c6208f157278` |

Readings from those decodes (`gvr_decode`), (r,g,b,a): `nk_h032_fish1.GVR` px(0,0) = (0,0,0,0),
px(16,16) = (74,113,115,255), 527/1024 texels with a ≠ 0 (a cut-out sprite); `indtex.gvr` px(0,0) =
(57,44,123,255), px(64,64) = (49,80,180,255), 16384/16384 opaque (flags bit 3 clear, §1.3);
`f032_uzu.GVR` px(0,0) = (255,255,255,0), px(16,16) = (255,255,255,255), 719/1024 visible.
`nk_h032_fish3/4.GVR` are the same shape (gbix 1600250 / 1600252, 544 B) — one 3-frame sprite family.

### 1.3 What the flags nibble means — proven bit by bit

7421 GVR chunks = 7416 inside the 343 `.gvm` + the 5 loose `.gvr`. Histogram of the nibble:
`0`→3265, `1`→2937, `8`→957, `9`→236, `10`→26. Bits 2 (0x4) and the whole high nibble are never set.

| bit | value | meaning | proof (measured) |
|---|---|---|---|
| 0 | 0x1 | **mip chain follows** | 3173/3173 chunks with bit 0 have `len−0x10` exactly equal to the full mip chain (Σ `tex_size` down to 1×1); 4248/4248 without it have exactly `tex_size` → 0 mismatches. Example: 128² CMPR level 0 = 8192, chain = 8192+2048+512+128+32+32+32+32 = 11008; `map_aancient02.GVM::h128_m2_ami_01` has 11008 |
| 1 | 0x2 | **paletted (CI) texture** | set in 42/42 CI4/CI8 chunks, in 0/7379 non-CI chunks — a perfect split. Always co-occurs with bit 3 (`0xA`) |
| 2 | 0x4 | unknown | never set anywhere on the disc — **unproven** |
| 3 | 0x8 | **has transparency** (statistical, not mechanistic) | over the 7230 CMPR textures: bit 3 set → 1032/1070 (96.4 %) contain texels with a = 0; bit 3 clear → 6100/6160 (99.0 %) are fully opaque. 7132/7230 = 98.6 % consistent. For the 161 RGB5A3 textures the split is not discriminating (41/41 with bit 3 clear still have gradient alpha) — **mechanism unproven** |

Bit 3 is **not** "internal palette ahead of the texels" as `gvr_decode` assumes (pso_gc.py:159-160):
**0 of the 1219** bit-3 chunks carry extra bytes — every one has `len − 0x10` equal to `tex_size`
(bit 0 clear) or the full mip chain (bit 0 set). The 42 CI textures get their palette from a
separate `.GVP` file (§4), and consequently `gvr_decode` raises on **42/42** of them:

```
ValueError: cannot reshape array of size 65472 into shape (1024,64)   # TextureEnglish.gvm::b256_alphabet
```

because it eats 32 bytes (`2*16` for CI4) as a palette that is not there. Callers that can reach a CI
texture (`pso_gc.py:482`, `pso_gc.py:649`, `pso_faces.py:244`, `pso_face_build.py:232`) hit this on
`Texture*.gvm`, `bg_multi.GVM` and the UI `.prs` GVMs.

## 2. GX texture formats as `decode_texture` implements them

`decode_texture(data, fmt, w, h, tlut, tlut_fmt, tlut_n)` (melee_models.py:143-194) is the only GX
texel decoder in the repo; `gvr_decode` is a thin GVR wrapper around it (pso_gc.py:151-163).
Block geometry comes from `_BLOCK` (melee_models.py:127-128):

| fmt | GX name | block | bits/texel | bytes/texel | bytes/block | decode_texture branch | on this disc |
|---|---|---|---|---|---|---|---|
| 0 | I4 | 8×8 | 4 | 0.5 | 32 | :149-152 (`v*17`, grey, a=255) | 0 |
| 1 | I8 | 8×4 | 8 | 1 | 32 | :155-157 (replicate byte, a=255) | 0 |
| 2 | IA4 | 8×4 | 8 | 1 | 32 | :158-161 (low nibble I, high nibble A) | 0 |
| 3 | IA8 | 4×4 | 16 | 2 | 32 | :162-166 (low byte I, high byte A) | 0 |
| 4 | RGB565 | 4×4 | 16 | 2 | 32 | :162,167-168 (`_rgb565`) | 0 |
| 5 | RGB5A3 | 4×4 | 16 | 2 | 32 | :162,169-170 (`_rgb5a3`) | **161** |
| 6 | RGBA8 | 4×4 | 32 | 4 | 64 | :173-175 (two ARGB/RGBA halves) | 0 |
| 7 | (unassigned) | — | — | — | — | **not in `_BLOCK`** → `KeyError`, not a clean error | 0 |
| 8 | CI4 | 8×8 | 4 | 0.5 | 32 | :149-150,153-154 via `_palette` | **25** |
| 9 | CI8 | 8×4 | 8 | 1 | 32 | :155-157 via `_palette` | **1** |
| 10 | CI14x2 | 4×4 | 16 | 2 | 32 | :162,171-172 (`& 0x3FFF` index) | 0 |
| 14 | CMPR | 8×8 (2×2 DXT1 4×4) | 4 | 0.5 | 32 | :176-191 | **7234** |

So: **11 of the 12 GX formats are decoded** (0,1,2,3,4,5,6,8,9,10,14); format byte 7 has no entry.
Palette decoding goes through `_palette` (melee_models.py:122-124) with `tlut_fmt` 0 = IA8,
1 = RGB565, 2 = RGB5A3.

### 2.1 Histogram actually observed (the key evidence)

7421 GVR chunks reached through the repo's own readers — 7416 from `gvm_entries` over all 343
`.gvm`, plus the 5 loose `.gvr`:

| fmt | name | chunks | share |
|---|---|---|---|
| 14 | CMPR | 7234 | 97.5 % |
| 5 | RGB5A3 | 161 | 2.2 % |
| 8 | CI4 | 25 | 0.34 % |
| 9 | CI8 | 1 | 0.013 % |

Extending the same scan to the two other places GVMs hide (47 of 53 `.prs` are PRS-compressed GVMs;
430 GVMs are embedded in the 298 `.bml` packs) adds 1784 chunks, all still in the same four formats:
**9205 chunks total → CMPR 8912, RGB5A3 251, CI4 29, CI8 13.** Formats 0,1,2,3,4,6,10 do not occur
anywhere on this disc.

```
from gbox import pso_gc as G
from collections import Counter
c = Counter()
for k in [x for x in d.files if x.lower().endswith((".gvm", ".gvr"))]:
    chunks = G.gvm_entries(d.read(k)) if k.lower().endswith(".gvm") else [(k, d.read(k))]
    for _n, ch in chunks: c[G.gvr_header(ch)["fmt"]] += 1
print(dict(c))            # {5: 161, 8: 25, 9: 1, 14: 7234}
```

Dimensions are always square and power of two on this disc: 128² 2641, 64² 2347, 256² 1176, 32² 958,
8² 167, 512² 83, 16² 49 (Σ 7421). No mip level is ever stored for CI textures (bit 0 clear in all 42),
which is why a CI chunk is exactly `0x10 + tex_size`.

## 3. GVM archives (`GVMH`)

### 3.1 Header

| off | size | field | observed |
|---|---|---|---|
| 0x00 | 4 | magic `GVMH` | — |
| 0x04 | 4 | u32 **LE** header size `H` | 72 … 9352 |
| 0x08 | 2 | u16 **BE** entry flags | **0x000F in 343/343** — all four optional fields present |
| 0x0A | 2 | u16 **BE** texture count | 1 … 246 |
| 0x0C | 38·count | entry table | §3.2 |
| 0x0C+38·count | pad | up to `8+H` | not necessarily zero: 23/343 archives have non-zero bytes here — the engine must not read them |
| 8+H | … | GVR chunks, in entry order, with no gaps | Σ chunk lengths === file size − (8+H) for all 343 |

`H` is computed, not stored per-entry: the data offset `8+H` is the **smallest value ≥
12 + 38·count with `(8+H) mod 32 == 16`** — 0 violations over 343 archives. Examples: count 1 → 80,
2 → 112, 6 → 240, 7 → 304, 20 → 784, 87 → 3344.

`gvm_list` (pso_gc.py:184-203) takes the flags from `(data[8] | data[9]) & 0x0F`, which yields 0x0F
here, so its stride is `2+28+2+2+4 = 38` — correct for this disc, but the flag-dependent stride is
**never exercised** (every archive has all four fields).

### 3.2 Entry (38 bytes) — `pso_gc.py:188` docstring is right, plus three decoded fields

| off | size | field | observed |
|---|---|---|---|
| +0 | 2 | u16 **BE** id | equals the entry index (0…count−1) in 343/343 archives |
| +2 | 28 | char name[28], NUL padded | e.g. `k128sora`, `b256_cm_chara01` |
| +30 | 2 | u16 **BE** = `flags << 8 \| gx_format` (a copy of GVRT +0x0A/+0x0B) | 7416/7416 exact: 14 = CMPR no flags, 270 = 0x010E CMPR+mip, 2062 = 0x080E CMPR+alpha, 2053 = 0x0805 RGB5A3+alpha, 2568 = 0x0A08 CI4 |
| +32 | 2 | u16 **BE** packed dimensions | see below |
| +34 | 4 | u32 **BE** gbix | consecutive per archive, e.g. `0x0013EB9C`, `0x0013EB9D` |

The `dims` field is **not** a size pair: it is `(log2(w) − 2) << 4 | (log2(h) − 2)`, one 4-bit
exponent per axis — 7416/7416 exact. Proof: the distinct values over all 7416 entries are exactly
(1,1) 167×, (2,2) 49×, (3,3) 954×, (4,4) 2347×, (5,5) 2640×, (6,6) 1176×, (7,7) 83× — identical to
the 8², 16², 32², 64², 128², 256², 512² counts. `map_forest01s.GVM::k128sora` stores `00 55` (5,5)
for a 128×128 texture; `map_cave01_00s.GVM::am008sky` stores `00 11` (1,1) for 8×8.

### 3.3 `Scene/map_forest01s.GVM` (8,288 B) — complete

```
0x00  47 56 4d 48 48 00 00 00 00 0f 00 01 00 00 6b 31 32 38 73 6f 72 61 00 …
      GVMH        H=72 LE       F   count=1  id=0  "k128sora"
0x2A  00 0e   fmt 14 (CMPR)
0x2C  00 55   dims (5,5)  -> 128x128
0x2E  00 20 0b 61   gbix 0x00200B61 = 2100065
0x50  47 56 52 54 08 20 00 00 00 00 00 0e 00 80 00 80 …   GVRT size 8200, fmt 14, 128x128
```
count 1, one texture `k128sora`, CMPR, 128×128; chunk 8208 = 16+8192; file 8288 = 80+8208.
Decoded: sha256 `1abf59f1f84d27cd…`, mean RGBA (116.0, 171.3, 239.8, 255.0), px(0,0)=(32,121,222,255)
— a blue sky gradient.

### 3.4 `Scene/map_ruins02_02s.GVM` (33,424 B) — complete

count 2, `H` = 104, data at 112, entries end at 88 + 24 pad.

| # | name | fmt | dims word | gbix | chunk | w×h |
|---|---|---|---|---|---|---|
| 0 | `h256_bg_sora` | 14 CMPR | `0x0066` → (6,6) | `0x0013EB9C` = 1305500 | 32784 | 256×256 |
| 1 | `h32_bg_sora02` | 14 CMPR | `0x0033` → (3,3) | `0x0013EB9D` | 528 | 32×32 |

### 3.5 `ccconsole_j.GVM` (1,934,416 B) — 20 textures, `H` = 776, data at 784

`character-create` console atlas; the biggest archive on the disc that mixes the two formats in bulk.
12 × RGB5A3 256² (`chunk` 131088 = 16+131072) + 8 × CMPR:

```
b256_cm_chara01 … b256_cm_chara07   RGB5A3 256²   b256_cm_word01_j … word03_j  RGB5A3 256²
b256_cm_mat01 … b256_cm_mat03       RGB5A3 256²   y256_cc04                    RGB5A3 256²
hexback0_256, hexback1_256          CMPR   256²    hexback2_128 … hexback5_128  CMPR   128²
```
Σ chunks = 1,934,416 − 784 exactly.

Other GVM specimens used later: `player00.gvm` 32,864 B / 1 texture `hcs_test01` 256² CMPR;
`player01.GVM` 32,384 B / 9 textures (`a_core`,`a_eye`,`a_fuku01..03`,`a_hat2`,`a_kami01/02`,`a_kao`,
all CMPR 16²–128²); `player02.gvm` 32,384 B / 9 textures (`ramarl_*`); `player_footstamp.GVM`
4,240 B / 2 textures (`nk_g032_normal`, `nk_g032_robo`, RGB5A3 32²).

### 3.6 PRS and BML

47 of the 53 `.prs` files decompress (via `ninja.prs_decompress`) to a `GVMH` archive, e.g.
`f256_hyouji.prs` 151,942 B → 672,480 B holding 13 textures (9 CI8 + 4 CI4). 298 of 299 `.bml`
packs carry 430 embedded GVMs in total (`bml_files()['tex']`, PRS'd unless `fields[3] == fields[4]`).

## 4. `.GVP` — external palettes (26 files), **`GVPL` not `GVM`**

| off | size | field | observed |
|---|---|---|---|
| 0x00 | 4 | magic `GVPL` | all 26 |
| 0x04 | 4 | u32 **LE** = `len − 8` | 40 or 520 |
| 0x08 | 2 | u16 **BE** | `2` in 26/26 — constant, **meaning unproven** (it is not the CI entry width: it is 2 for both 16- and 256-entry files, and not the `pal_fmt` nibble either, which is 0 in every GVRT on the disc) |
| 0x0A | 2 | u16 **BE** | `0` in 26/26 |
| 0x0C | 4 | u32 **BE** entry count | 16 or 256 |
| 0x10 | 2·count | u16 **BE** palette entries, RGB5A3/IA8-style | 16+2·count == file size in 26/26 |

Sizes are exactly two values: **16 files of 48 B** (16 entries) and **10 files of 528 B** (256
entries). Entry 0 is `0xFFFF` (opaque white) and the last entry is `0x8000` in 26/26 files.

**What is proven — the palette binds to a CI texture of the same name.** The disc has 42 CI texture
instances over 29 distinct names; there are 26 GVP files:

* **10/10 CI8 names** have a 256-entry GVP: `b256_mainmenu`, `f128_gr`, `f256_actionpallet_a/b/c`,
  `f256_carsol`, `f256_duelcount`, `f256_hyouji_a/b/c` (CI8 = 256 palette entries, chunk
  `0x10 + 2·256` = 528).
* **15/19 CI4 names** have a 16-entry GVP (`b256_menutext01_e/j`, `f064_wordmojitex_*`,
  `f128_keyeng/jpn`, `f256_symbolsetumei_*`, `r256_symparts`). The 4 without one are near-misses
  rather than strangers: `b256_alphabet` ↔ `f256_alphabet.gvp`, `r256_symobj01/02/03` ↔
  `r256_symparts.gvp`. Mark the two near-miss bindings **unproven**.
* Palette content agrees with the width. Under the `_rgb5a3` reading, all 16-entry palettes are
  **0 % coloured** (r=g=b for every entry, alpha in 14–15 of 16), i.e. greyscale+alpha — the natural
  IA8 reading, and the GVRT `pal_fmt` nibble is 0 = IA8 for all 42 CI textures. All 256-entry
  palettes are **76–98 % coloured** (e.g. `f256_carsol` 249/256), so they must be RGB5A3. Which exact
  enum the engine passes to `GXInitTlutObj` for the 16-entry ones is **unproven**; both readings
  render greyscale for the font atlases.

**What is unproven:** the `+0x08 = 2` field; whether the engine binds a GVP by name or by texture id;
whether any GVP is shared by more than one texture (yes in practice — `b256_menutext01_e.GVP` serves
the EN/FR/DE/ES copies — but the load code was not read).

## 5. `.tp` — memory-card banner (6 × 6,144 B) and icon (7 × 2,048 B)

13 files, no header, no magic — the byte count is the whole story:

| group | files | size | arithmetic |
|---|---|---|---|
| banner | `pso_bana_cap.tp`, `pso_bana_card.tp`, `pso_bana_down.tp`, `pso_bana_f.tp`, `pso_bana_net.tp`, `psov3banner.tp` | 6,144 | **96 × 32 × 2** = 6144 (RGB5A3, 16 bpp) |
| icon | `vms_capt.tp`, `vms_down.tp`, `vms_down2.tp`, `vms_icon1.tp`, `vms_icon2.tp`, `vms_net.tp`, `vms_sys.tp` | 2,048 | **32 × 32 × 2** = 2048 (RGB5A3, 16 bpp) |

`6144 = 3 × 2048` is a coincidence of the two independent arithmetic facts, **not** a `/3`: there is
no 18-bpp/24-bpp packing here, and 2,048 is a whole 32×32 RGB5A3 image.

**Decode proven, tiling proven, pixel content unverified.** No header: interpret the file as a GX
RGB5A3 image and it comes out coherent only in 4×4 block order, i.e. exactly
`decode_texture(raw, 5, w, h, None, 2, 256)`:

| file | w×h | total variation: linear / 4×4-colmajor / **4×4-rowmajor** | seam at x=4k vs interior, linear → tiled |
|---|---|---|---|
| `vms_capt.tp` | 32×32 | 83.96 / 79.59 / **63.70** | 3.52× → 1.27× |
| `pso_bana_card.tp` | 96×32 | 97.09 / 74.82 / **57.27** | 2.17× → 1.11× |
| `psov3banner.tp` | 96×32 | 92.75 / 72.73 / **55.48** | 2.14× → 1.11× |

A linear (row-major) read leaves a 2.1–3.5× discontinuity on every 4th column; the GX block read
removes it. All 13 files are opaque-ish (mean alpha 254.8–254.9), as a banner/icon should be. Decoder:
`decode_texture(d.read("pso_bana_card.tp"), 5, 96, 32, None, 2, 256)` → `(32, 96, 4)` uint8.

## 6. Player texture banks — `pl<X>tex.afs`, `playerNN.gvm`

### 6.1 AFS container (same reader for DC and GC)

`pso_player.afs` (pso_player.py:33-35): `'AFS\0'`, u32 **LE** count, then `count × (u32 LE offset,
u32 LE size)`; `pso_gc.afs` (pso_gc.py:132-134) re-exports it. On `plCtex.afs`:

| fact | value |
|---|---|
| file | 1,986,560 B, `AFS\0`, count **286** |
| table | 8 + 8·286 = 2,296 B |
| data start | **524,288 (0x80000)**; 521,992 zero bytes between the table and the first entry |
| alignment | all 286 offsets are 0x800-aligned; inter-entry padding is `0x00` |
| last entry | ends at 1,985,056 (+1,504 B tail) |
| entry shape | every entry starts `GBIX` with size 8 and has `GVRT` at **+16** (286/286) |

Entry content of `plCtex.afs`: 283 CMPR + 3 RGB5A3, sizes only 544 (32² CMPR), 2080 (32² RGB5A3) and
8224 (128² CMPR), i.e. three fixed shapes. The 19 banks:

| bank | bytes | entries | bank | bytes | entries |
|---|---|---|---|---|---|
| `plAtex.afs` | 1,415,168 | 137 | `plHtex.afs` | 2,516,992 | 355 |
| `plBtex.afs` | 3,094,528 | 310 | `plItex.afs` | 3,747,840 | 516 |
| `plCtex.afs` | 1,986,560 | 286 | `plJtex.afs` | 2,543,616 | 386 |
| `plDtex.afs` | 1,558,528 | 208 | `plKtex.afs` | 1,972,224 | 321 |
| `plEtex.afs` | 2,082,816 | 311 | `plLtex.afs` | 2,836,480 | 333 |
| `plFtex.afs` | 2,492,416 | 386 | `plStex.afs` … `plYtex.afs` | 563,200–593,920 | 14–17 |
| `plGtex.afs` | 1,992,704 | 337 | `plZsmpnj.afs` | 5,341,184 | (NJ samples) |

A–L = the 12 GC classes; S–Y (7 banks of 14–17 textures each) are small extra sets — **unproven**
which slot each letter S…Y serves.

### 6.2 The HUcast binding in `pso_player.py`

`hucast_textures(colour, head, section_id)` (pso_player.py:41-50) returns AFS indices per Ninja
texture id, and `build()` (pso_player.py:61-101) applies it at pso_player.py:91:

| Ninja texture id | AFS index | formula (pso_player.py:43-49) |
|---|---|---|
| body 0 | `99 + section_id` | section-ID emblem, 99…108 |
| body 1…4 | `5*colour + 0…3` | torso / legs / limbs / hands |
| head 0: tex 0, 1 | `45 + 2*colour`, `46 + 2*colour` | head, visor glow |
| head 1…3: tex 0, 1 | `63 + 9*(head−1) + colour`, `5*colour + 4` | head, glow |
| head 4: tex 0, 1 | `90 + colour`, `5*colour + 4` | **marked "unverified"** in pso_player.py:16 |

Two of those blocks check out against the GC bank's own structure:

* entries 99…108 are 10 consecutive 32×32 CMPR cut-outs with consecutive gbix 507545…507554 — the
  section-ID emblem set the formula predicts.
* the bank is built from **5-entry groups** (`128²,128²,128²,64²,32²` CMPR) for indices 0…44 =
  9 colours × 5, so `5*colour + 0…3` lands on the first four of a group as the DC layout expects.
  Entries 45…89 repeat the same 5-entry rhythm for the heads (gbix 507614…, with 45 and 70 carrying
  out-of-sequence ids 507638 / 507613 — **unproven** why).

**Not proven / not portable.** The docstring (pso_player.py:11-17) describes the Dreamcast bank
"PLCTEX.AFS (110 PVRs)"; the GC bank has **286 GVR entries** in the same id space, so the tables
above are DC-era indices that happen to remain consistent for 0…108. Blocks 45…98 and 109 are
unverified on GC, and `pso_player.build` cannot run against this disc at all: it reads
`PSO/PL{cls}TEX.AFS` (pso_player.py:85, absent — the GC files are `plCtex.afs` at the root) and
decodes with `ninja.pvr_decode`, which requires a `PVRT` chunk (ninja.py:52-56) while these entries
are `GBIX`+`GVRT`.

**Still unresolved:** every class except HUcast (C). pso_player.py:88-89 explicitly falls back to
`b_ids, h_ids = list(range(5)), []` for the other 11 GC classes — ids 0…4 → AFS 0…4, a placeholder,
not a measured mapping. The GC-native per-class banks are `player00.gvm` (1 test texture),
`player01.GVM` (HUmar-style `a_*`), `player02.gvm` (`ramarl_*`) — 3 of 12 classes have a named
archive, the other 9 have only the `pl<X>tex.afs` id space.

The GC-side writer path never uses the id table: `pso_gc_swap.afs_with_atlas` (pso_gc_swap.py:106-116)
and `gvm_with_atlas` (:119-131) rewrite **every** texture in place with `gvr_like` (:71-88), which
refuses mipmapped (`flags & 1`) and palette formats 8/9/10 (pso_gc_swap.py:77-78) — on this disc
that is 3173/7421 textures rejected up front (42.8 %), all `plCtex.afs` entries eligible.

## 7. Area texture pools vs per-section archives, and the `.gj` name list

The 343 `.gvm` split cleanly by name and content:

| group | count | where | textures | formats | dims |
|---|---|---|---|---|---|
| `map_<area><NN>_<MM>s.GVM` / `map_<area><NN>s.GVM` | **101** | `Scene/` only | 234 (1–10 each; 62 have exactly 1) | **CMPR 234 (100 %)** | 256² 98, **8² 93**, 32² 17, 128² 14, 64² 12 |
| area pools `map_<area><NN>.GVM` | 72 | `Scene/` | 5,985 | CMPR 5,935, RGB5A3 50 | 128² 2352, 64² 1956, 256² 857, 32² 652, 8² 69, **512² 64**, 16² 35 |
| root archives (`player*`, `Item*`, `ccconsole_*`, `Texture*`, `bg_multi`, …) | 170 | root | 1,197 | CMPR 1,061, RGB5A3 110, **CI4 25, CI8 1** | 64² 379, 32² 285, 128² 274, 256² 221, 512² 19, 16² 14, 8² 5 |

All 26 CI textures on the disc live in root archives (`TextureEnglish/French/German/Japanese/Spanish.gvm`,
`bg_multi.GVM`); no `Scene/` archive contains a paletted texture.

* The **small** ones are the per-room/per-section sets: 224 B (`map_cave01_00s.GVM`, one 8² CMPR
  `am008sky`), 8,288 B (`map_forest01s.GVM`, one 128² sky `k128sora`), 33,424 B
  (`map_ruins02_02s.GVM`, a 256² + a 32² bg), up to 197,776 B. Their textures are named
  `<prefix><dim>_<purpose>` (`k128sora` = 空/sky, `h256_bg_sora`, `o256_an01_tenkyu01`) — always
  un-mipmapped CMPR, so the engine can mip/clamp them itself.
* The **big** ones (`Scene/map_forest01.GVM` 1,340,208 B, `map_aforest02.GVM` 1,437,504 B,
  `map_amachine02.GVM` and `map_machine02.GVM` both 1,722,672 B but not byte-identical) are the whole
  area's object-texture pool: 11–246 textures, 118,208 B – 1,722,672 B, mostly un-mipmapped CMPR — a
  mip chain would add 34 % at 128² and 34 % at 256², i.e. ~1 MB over such an archive.

**`GJTL`/`.gj` name resolution — proven.** For all **101** `Scene/*.gj` files:

* each has a sibling `*s.GVM` (0 orphans), and
* the NUL-terminated ASCII name list that starts right after the `GJTL` header is **identical, in the
  same order, to the sibling GVM's entry table** — 101/101 exact, e.g.
  `map_acave01_00s.gj` → `['am008sky']` = `map_acave01_00s.GVM`; `map_seabed02_01s.gj` →
  `['nk_g512_umi2','nk_g512_umisita2']` = that GVM's two entries. The count at `GJTL+0x0C` (BE u32)
  equals the GVMH count in 101/101. The name table begins at 0x20 for count 1 and 0x24 for count 2
  (i.e. it follows the variable-length GJTL header — the header itself is documented in
  `pso-gc-formats-models.md`).
* The big area pools are **not** what a `.gj` names: only 5 of the 95 area GVMs that have a sibling
  `.gj` share even one texture name with it.

So a GJCM material's texture index `i` resolves to GVMH entry `i` by position (the name is there for a
name-based lookup); `gvm_entries(gvm)[i][0]` returns it. The `GJTL`/`GJCM` mesh side is out of scope
here — see `pso-gc-formats-models.md`.

## 8. Consequences for the current code (numbers, not opinions)

1. **`gvr_decode`'s palette branch is wrong for this disc.** pso_gc.py:159-160 treats `flags & 8` as
   "internal palette ahead of the texels". Measured: 0/1219 bit-3 chunks carry palette bytes, and
   **42/42** CI4/CI8 chunks raise `ValueError` from `decode_texture` because 32 or 512 bytes are
   stolen from the texel stream. A correct reader is: `fmt in (8,9)` → load the palette from the
   `.GVP` of the same name (§4), `n = 16 if fmt == 8 else 256`, `data` = the whole texel block.
2. **Mipmaps are the majority of the "hard" cases, not an edge case.** 3173/7421 (42.8 %) chunks
   carry a full mip chain. `gvr_like` (pso_gc_swap.py:77) and `pso_face_build.paint`
   (pso_face_build.py:283) both bail out on `flags & 1`, so those textures can never be repainted by
   the current writers even though rewriting only level 0 would preserve the length.
3. **`decode_texture` has no format 7.** `_BLOCK[7]` is missing (melee_models.py:127-128), so a
   hypothetical format-7 texture raises `KeyError` rather than the clean `ValueError` at
   melee_models.py:192-193. No such texture exists on this disc (histogram in §2.1), so it is latent.
4. **`gvm_list`'s stride is correct here but untested by the data.** All 343 archives use flags
   0x000F; the flag-conditional stride at pso_gc.py:195 has never been exercised on real files.

## 9. Reproduce

```
import sys, struct, hashlib; sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox.gcdisc import GCDisc
from gbox import pso_gc as G
from gbox.melee_models import tex_size
d = GCDisc(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")
a = G.gvr_decode(d.read("nk_h032_fish1.GVR"))           # gbix 1600251, fmt 14, flags 8, 32x32
hashlib.sha256(a.tobytes()).hexdigest()[:16]            # '0bd51a4a582006b8'
for _n, chunk in G.gvm_entries(d.read("Scene/map_forest01s.GVM")):
    e = G.gvr_header(chunk)                             # fmt 14, 128x128, data at 0x60
    assert len(chunk) - e["data"] == tex_size(e["fmt"], e["w"], e["h"])
raw = d.read("plCtex.afs"); n = struct.unpack_from("<I", raw, 4)[0]     # 1986560, 286, data 0x80000
ents = [raw[o:o+s] for o, s in (struct.unpack_from("<II", raw, 8+8*i) for i in range(n))]
assert all(e[:4] == b"GBIX" and e.find(b"GVRT") == 16 for e in ents)
```

Related docs: `pso-gc-formats-containers.md` (GVM/AFS/PRS/BML containers),
`pso-gc-formats-models.md` (`GJTL`/`GJCM`/`.gj`, NJCM texture binding),
`pso-gc-formats-tables.md` (item/stat tables).
