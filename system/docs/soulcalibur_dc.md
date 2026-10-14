# SoulCalibur (Dreamcast): disc, fighters, reader, writer and the Sonic vs Mario build

The operator asked for "the same package as request #1652 (DOA2), for Soul Calibur on Dreamcast". That means a
reader for every fighter, a native writer, and a build where half of the cast comes from Sonic Adventure 2 and half
from Super Mario 64 DS, picked at random each time a fighter is loaded.

- Reader: `gbox/soulcalibur_dc.py`, registered in `characters.DEDICATED` as `soulcalibur`.
- Writer: `gbox/soulcalibur_swap.py`. It is routed by `characters op=use`, and it is also a `cast_swap` pairs
  builder, a `char_coverage` writer and a `replacement_readiness` spec.
- Tests: `tests/test_soulcalibur_dc.py`.

## The disc

| | |
|---|---|
| Catalog | `c747331797369f74` "SoulCalibur (USA)", HyperSpin `Soul Calibur (USA).chd` (CHD **v4**, 761,082,045 bytes) |
| Other dumps | `e4ad4831b09591b6` (7z GDI), `32bdc48bc550f79b` (TOSEC GDI). Their track 3 is byte-identical to the CHD's (SHA-256 `7d39ed81...af8a2`) |
| Executable | `1ST_READ.BIN`, 3,679,460 bytes, SHA-256 `646fd82c...781fa7f`. It loads at `0x8c010000` and is SH-4 little-endian code, not scrambled |
| Layout | Track 1 (450 frames), an audio track 2 that fills up to LBA 45,000, and data track 3 at 45,000. The CHD's metadata is the old `CHT2` kind, not `CHGD` |

**CHD without chdman.** `chd.write_gdi` unpacks a v4 or v5 CD/GD-ROM CHD into a GDI set. It writes tracks at their
padded frame offsets (multiples of 4) and swaps audio back to little-endian. The high-density track goes to LBA
45000, and its first sector's Mode 1 header must address that LBA. `characters._dc_gdi` uses it when the node has no
chdman. That is how this PC opened the disc.

### Files

There are 88 files in ISO9660 on track 3. Besides the BGM streams (`*.P16/P08/P04`), every data file is an **olnk**
archive.

| File | Bytes | Holds |
|---|---|---|
| `HUMAN.DAT` | 78,500,544 | 210 entries: 21 character ids x 10 (costumes, motion, weapons) |
| `STAGE.DAT` | 42,049,600 | 23 stages |
| `HOPEN.DAT` / `KENDING.DAT` / `KGALLERY.DAT` | | openings, endings, the gallery |
| `VCSEL.DAT` | 2,610,656 | VS-screen portraits (`chara*4 + (costume & 1) + 1`, `FUN_8c0f47c0`) |
| `CINIT.DAT`, `CDATA.DAT`, `ENBU.DAT`, `KMISSION.DAT` | | init data, nested olnk (SMSB/SMSD sound tables), demo motions (archive 4), missions |

The executable's archive table is `cinit, vcsel, stage, human, enbu, hopen, cdata, kending, kgallery, kmission`.
HUMAN is archive 3. The development names `human%1x%02x.dat`, `buki%1x%02x.dat` (weapons) and `mot%03x.dat` are still
in the strings.

### Formats

- **olnk** (loader `FUN_8c0ac1a0` / `FUN_8c0ac666`): `u32 count, "olnk", u32 header bytes, u32 size, u32 0`, followed
  by `count x (u32 offset, u32 size)`. Offsets are relative to the end of the header. Empty entries have size 0.
- **Counted table** (`FUN_8c01bde0`): `u32 n, u32 header bytes, n x u32 end offset`. The header is padded to 32 bytes
  with the filler string `cc b5 c2 cc ... "32byte" ...`, and every member is padded to 32 bytes. `build_table`
  rebuilds the shipped tables byte for byte.
- **LZ** (`FUN_8c0ee76c`): a flag byte is read LSB first and has a sentinel high bit. `0xff` means seven literals and
  `0x00` ends the stream. Bit 1 is a literal. Bit 0 is a big-endian u16 `v` that copies `((v >> 11) - 1 & 31) + 1`
  bytes (2..32) from `((v - 1) & 0x7ff) + 1` bytes back (1..2048). `lz_compress` is a greedy encoder for it.
- **HUMAN group** (`FUN_8c02e37a(side, chara, costume)` loads entry `(chara - 1) * 10 + costume`):
  - Entries 0..3 are costumes and entry 4 is the motion pack.
  - Entries 5..9 are weapons, up to 3 per fighter. The weapon is chosen separately from the costume.
  - Ids 10 and 21 have no body.
  - Character ids: 1 Mitsurugi, 2 Seung Mina, 3 Taki, 4 Maxi, 5 Voldo, 6 Sophitia, 7 Siegfried, 8 Rock,
    9 Hwangseong, 11 Ivy, 12 Kilik, 13 Xianghua, 14 Lizardman, 15 Yoshimitsu, 16 Edge Master, 17 Nightmare,
    18 Astaroth, 19 Inferno, 20 Cervantes.
- **Costume** = table of 9:
  - `[0]` texture bank. This is a table of the LZ model followed by 256x256 pages.
  - `[1]` the voice bank: AICA `SOSB`/`SOSP`/`SOSD` with 4-bit ADPCM. It is identical in every costume, and the sound
    driver at `0x8c0a6dc0` uploads it.
  - `[2]` LZ cloth/chain parameters (`FUN_8c04b516`).
  - `[3]` an olnk of three small tables.
  - `[4]` face-shape data, 3104 bytes.
  - `[6]` LZ data.
- **Weapon** = table of the LZ model followed by one or two pages.
- **Pages**: raw 256x256 twiddled pages, 131,072 bytes, no header. Most texels are **YUV422**: Y is the high byte
  of each word, and the low byte is U on the even texel and V on the odd one. A page can also hold regions in other
  pixel formats, because each strip picks the format with its material byte (see Strips): hair and fringe are
  **ARGB4444**, and some decals and cloth emblems are **ARGB1555**. Read as YUV, those regions look pure green;
  that green is not a colour key. Page 0 of a fighter with a face (model flag `0x200`/`0x300` at +0x12) is the
  expression sheet.
- **Model** (after LZ):
  - Header (0x20 bytes):
    - +0x00: two dates (`HHMM MMDD`)
    - +0x08: two tail offsets (weapons only)
    - +0x12: flags
    - +0x14: position count
    - +0x16: normal count
    - +0x18: strip offset
    - +0x1c: bone count
    - +0x1e: `0x414`
  - Bone records, 32 bytes each: `u16 stores, u16 adds, u32 rows, u32 extra (cloth tables in the tail), u16 positions,
    u16 normals, 4 x s16 rest angles (1/65536 turn, R = Rz Ry Rx), 3 x s16 translation / 16000, s16 parent`.
  - Rows are `x, y, z, w` in bone space, 16 bytes each, with the positions first and then the normals. The `w`
    word packs the output slot (low 12 bits), an **add flag** (bit 15) and the weight (upper 16 bits; bits 12..14
    are 0 in every stock row). Normals are stored pointing **inward**.
  - **Skinning, as the engine runs it** (`0x8c03cea0`, read from the SH-4 code; `soulcalibur_dc.engine_skin`
    emulates it). Bones go in index order; a bone with no position rows is skipped, normals included. XMTRX is the
    bone's matrix and `ftrv` transforms the whole row:
    - Positions (`0x8c03c920`): the result is `R @ xyz + w * t`. So the stored `xyz` is the weight-premultiplied
      bone-local point `w * p`, and the bone adds `w * (R p + t)`. In all 45 costumes the bones agree on a blended
      vertex only under this reading (spread 0.5 mm, against 96 mm when `xyz` is read as unweighted).
    - The first `stores` rows go to **consecutive slots starting at row 0's slot**: the slot is read once, before
      the loop, and the pointer then moves 16 bytes per row. The slot bits of the other store rows are never read.
      The `adds` rows add at their own slot.
    - Normals (`0x8c03cba0`, lit variant `0x8c03c9ec`) have no count. Rows store to consecutive slots from row 0's
      slot until the first row with bit 15 set; from that row on, every row adds at its own slot. The translation is
      cleared. The lit variant also copies the low byte of each normal row's `z` into its output. `0x8c03ca9c` reads
      that byte as a per-vertex highlight strength; the stock values are 25..255 in steps of 25.5.
    - Header `+0x14` / `+0x16` are the position / normal slot counts. `0x8c03c998` projects that many positions.
    - Stock layout: each bone's stores are one consecutive slot run, adds carry bit 15, and every add lands on a slot
      stored earlier in the frame. `pack_model(parse_model(m)) == m` holds for every costume.
  - Strips: sections of `u8 material, u8 flags, u8 group, u8 count` headers, each followed by `count x (u16 position,
    u16 normal | 0x8000 on the last, u16 v, u16 u)`. Triangle k is `(k, k+1, k+2)` when k is even and
    `(k+1, k, k+2)` when k is odd, and faces out in the game's space. `u32 0` closes a section, and an empty section
    closes the list.
    - **Texture coordinates** (`0x8c03cc68`, the vertex emitter): `mov.l @r5+,r2` loads the two u16 as one
      little-endian u32 and stores it as the TA vertex's U float (`mov.l r2,@(16,r4)`); `shll16 r2` then stores
      the same word shifted as V (`@(20,r4)`). So the **second** u16 is the upper half of U, and the **first** is
      V. `strip_uv` and `uv_words` read and write them in that order.
    - **Material** (`0x8c03cf60` builds the polygon header): TCW = `base + (material & 3) * 0x4000 +
      (material & 0x30) << 23`. So `material & 3` is the page, and `(material >> 4) & 3` is the PVR pixel format:
      `0x3x` YUV422, `0x2x` ARGB4444, `0x0x` ARGB1555 (`material_format`, `page_rgba`). Bit `0x40` sends the strip
      to the translucent list, with TSP `0x94100000` (src alpha, inverse src alpha). The opaque list's TSP
      `0x20080000` ignores texture alpha.
    - `flags` > 0 scales U and offsets V from a per-model table (`param + 0x25c`, UV animation). The `group` byte
      is a visibility bit: the strip is drawn when bit `group` of the caller's mask is set (`0xffffffff` for the body).
  - Ivy's chain blade stores `0x7fbfffff` placeholders as some of its normals.
- **Space**: fighters face +Z, but the space is left-handed. Read in a right-handed frame, texture text comes out
  mirrored. The library frame is reached by mirroring X (`FRAME`), so the game's -X side is the fighter's left.
- **Skeleton**: bones 0..17 are shared by all 45 costumes. They are the motion skeleton, with two roots at the
  origin: 0 for the waist and upper body, and 11 for the pelvis and legs.
  - Roles: hip 11, chest 1, neck 2, clavicles 3/7, arms 4-6 (left) and 8-10 (right), legs 12-14 (left) and
    15-17 (right).
  - The head is the child of the neck that carries the most rows. On Voldo, Rock (1P), Yoshimitsu and Inferno the
    head and neck are one bone, and the exported GLB adds a `head` joint above it.
  - Further bones are cloth (sleeves, skirts, hair), face and sheath. Costume rest poses differ: some are arms-down
    and some are T-poses.

## Character select and the random costume hook

`FUN_8c02e1e6(side, costume, ...)` is the only caller of the HUMAN loader `FUN_8c02e37a`. The battle setup calls it
for both players from `player + 0x5c30` (costume) and `player + 0x5cc0` (character). The player structs are at
`0x8c24a958 + side * 0x86dc`. The select screen itself only stores those fields. The VS screen (`FUN_8c0f47c0`,
`vcsel.dat`) draws the 2D portrait of `(chara, costume & 1)`.

`soulcalibur_swap.patch_random_costume` is 44 bytes. The patch sits in the loader after its prologue and runs before
the costume is used anywhere:

- `0x8c02e38c`: `mov r6,r8 ; shll8 r8` becomes `bra 0x8c02e408 ; nop`.
- Cave A, `0x8c02e408..0x8c02e41f`, is 12 instructions. They read TMU0's TCNT0 (`0xffd8000c`, the system timer the
  SDK starts at `0x8c21fd98`) unless the costume is 2 or more.
- Cave B, `0x8c02e450..0x8c02e45f`, folds `t ^ t>>8 ^ t>>16`, keeps bit 0 as the costume, and branches back.
- Cave A then redoes `mov r6,r8 ; shll8 r8` and returns to `0x8c02e390`.

Both caves are compiler alignment padding. One follows the loader's `bra 0x8c02e638 ; nop`, and the other precedes a
32-byte-aligned branch target. No load or branch in the executable points into them (checked over the whole binary).
Extra costumes (2 and 3) are left as selected. The patch is read back and run through `simulate_random_patch`, an
interpreter of exactly those instructions.

Because the choice happens in the loader, every fighter load picks again. In VS mode that is every selection. In
arcade mode the player's fighter can also change between stages.

The DOA2 build (`docs/doa2_mixed_random.md`) works differently. It hooks the select confirm and draws from each
fighter's whole costume pool, because DOA2's render script and accessory tables follow the selected costume. Nothing
in SoulCalibur's body path follows the selection except the 2D VS portrait: the costume entry carries the model,
pages, voice and cloth data, and the weapon has its own index. Hooking the loader is therefore enough. What it does
not do:

- It does not hook the select screen itself.
- Extra costumes are not in the pool.

The container is the same OLK `olnk` format that Soul Calibur II on GameCube uses (`gbox.soulcalibur2.olk_table`).

## Reader (`characters op=collect game_id=c747331797369f74`)

The reader produces 19 entries, `sc_<name>`. Each is the fighter's 1P costume as a skinned GLB in the library frame
(+Y up, facing +Z, left +X):

- up to 4 influences per vertex
- the textures as PNGs
- all 18 body roles
- the first weapon attached: the blade at the right hand, other parts (sheath, shield, second blade) at the left hand

The weapon attachment is a rest attachment. In game, the motion places the weapon. Every one of the 45 costumes (151,076 triangles in all, each with all 18 roles) and the
fighters' 52 weapon models parse and skin (`soulcalibur_dc.coverage`). Mitsurugi 1P has 3,671 body triangles, 81 bones and
1,705 positions. `python -m gbox.soulcalibur_dc DISC.gdi OUT [fighter ...]` exports without the collection.

Limits:

- Hair and fringe strips (`0x2x` / `0x6x`) read their page region as ARGB4444, and decals (`0x0x` / `0x4x`) read
  theirs as ARGB1555. The GLB gives those materials their own decoded texture with alpha, blended when the strip is
  translucent (reader version 3; before that they came out pure green).
- The motion pack (entry 4) is not decoded.
- The weapon's in-game placement comes from motion data.

## Writer (`characters op=use`, `cast_swap`)

- **Slots**: `fighter:<name>` rebuilds every costume of the fighter. `fighter:<name>:<costume>` rebuilds one costume.
  `roster` (also `sonic vs mario`, `random`) builds the whole cast with the random hook.
- **Retarget**: the donor is fitted onto the costume's rest skeleton with `doa2_weighted_retarget.retarget`, using the
  18 roles (neck and clavicles optional) and the operator's Retarget-editor profile (`retarget_profile`). The
  Fitting pop-up gets scale, retarget, proportion, weights, decimate, encode and write events per costume.
- **Encode** (`encode_model`):
  - The stock bone records are kept, including rest angles, hierarchy, and the cloth, face and weapon bones.
  - New rows are written per bone. Each vertex gets up to 4 influences. The vertex's lowest bone stores it and the
    other bones add. Slots are numbered bone by bone, so each bone's stores are one consecutive run, as the engine
    writes them.
  - Each position row is `w * inverse(rest) @ P` with the exact `w` word the engine multiplies by (slot and flag bits
    included). Weights are rounded to the upper 16 bits, the add rows set bit 15, and the storing weight makes the
    sum 1.
  - Normals are skinned the same way as positions. Each distinct (influences, normal) pair gets one normal slot,
    with rows on every influencing bone at the same premultiplied weights: the lowest bone stores and the others
    add. Normals are stored inward (checked against the geometry: 84-93% of stock normals point into the body) and
    carry the stock model's usual highlight byte.
  - Corner normals (`corner_normals`) are the smooth geometric normal of the fitted surface: area-weighted,
    counter-clockwise faces, welded by position. Where the donor's own normal agrees with it (dot > 0.5), the
    donor's normal is kept. The SM64DS library normals agree with their own triangles only about half the time.
    Written as-is, the emulated engine lighting (`engine_light`, `0x8c03c7c0` + `0x8c03c9ec`) lit 27-31% of their
    corners backwards, against 3-6% for stock. With geometric normals it is 1.5%.
  - The model is laid out by `soulcalibur_dc.pack_model`, the same packer that rebuilds every stock model byte for
    byte.
  - The triangles are stripified with the game's winding, after the library-to-game mirror.
  - Texture page indices go in the material byte (`0x3x`, YUV422). The UV words go in the order the TA reads them:
    V first, then U (`uv_words`).
  - The tail after the strips stays at its stock offset, so the records' extra offsets still hold.
  - The vertex count must stay within the stock position and normal counts. The rows and strips must fit before the
    tail.
- **Pages**: donor textures are packed into the free pages. The face page is never used, because the game animates
  it. With more textures than pages, a page becomes a 2x2 (or larger) grid. Pages are encoded to YUV422 twiddled.
- **Budgets**: the compressed model must fit the stock entry's room. Every costume entry keeps its size and olnk
  slot, so HUMAN.DAT never grows and no other entry moves. A donor that does not fit is decimated (Blender LOD,
  0.8^k, with skin kept). In the build below only Inferno's third costume needed it (Sonic: 1,369 to 1,095
  triangles).
- **Weapons**: weapons are not touched. The motion moves each fighter's own weapon with the native hand bones, and the
  donor's hands are fitted to those bones.
- **Read-back** (`verify_build`):
  - HUMAN.DAT and 1ST_READ.BIN are compared byte for byte with the planned files.
  - Every other disc file is checked as unchanged.
  - Every rebuilt costume runs through `engine_skin`, the game's own maths. Every slot a strip draws must be stored
    in the frame, no add may read a stale slot, and the strips must stay within the header's counts. The tail must
    be in place.
  - Every untouched HUMAN entry is byte-identical.
  - The patch is checked and interpreted.

## The build: `sc_sonic_vs_mario_random`

Installed at `D:\gBox\cache\mods\c747331797369f74\sc_sonic_vs_mario_random\`:

- `sc_sonic_vs_mario_random.gdi` and its 3 tracks
- `build-report.json`
- `verification.json`
- `.gbox-mod.json`, written last, with the DOA2 roster marker's fields

It was built in `.tmp_sc_sonic_vs_mario_random` and moved into place after verification.

Costume 0 (and 2) of every fighter is a Sonic Adventure 2 character, and costume 1 (and 3) is a Super Mario 64 DS
one. All 45 costumes are rebuilt with no failures. The hook then picks costume 0 or 1 at random on every fighter load.

| Fighter | 0 (SA2) | 1 (SM64DS) | extra |
|---|---|---|---|
| Mitsurugi | Sonic | Mario | |
| Seung Mina | Amy | Peach | |
| Taki | Rouge | Yoshi | |
| Maxi | Shadow | Luigi | 2: Tails |
| Voldo | Chaos 0 | Koopa Troopa | 2: Tikal, 3: Mario |
| Sophitia | Tikal | Peach | 2: Amy |
| Siegfried | Metal Sonic | Metal Wario | 2: Super Sonic |
| Rock | Knuckles | Wario | |
| Hwangseong | Super Sonic | Luigi | |
| Ivy | Rouge | Peach | |
| Kilik | Tails | Luigi | |
| Xianghua | Amy | Mario | 2: Tails |
| Lizardman | Chaos 0 | Yoshi | |
| Yoshimitsu | Super Shadow | Ukiki | |
| Edge Master | Dr. Eggman | Wario | |
| Nightmare | Shadow | Bowser | |
| Astaroth | Dr. Eggman | Bowser | |
| Inferno | Super Shadow | Metal Wario | 2: Sonic |
| Cervantes | Knuckles | Koopa Troopa | |

The donor pools are the 12 SA2 entries and the 9 replacement-ready SM64DS humanoids (`docs/sm64ds.md`). Evidence:
`D:\gBox\research\soulcalibur\evidence\*_before_after.png`. These are offline renders of every costume, stock next to
the build read back from the disc.

### In game: v1 exploded; v2 and v3 are the fixes

**v1 (`sc_sonic_vs_mario_random`) exploded in game.** Ivy and Taki were huge stretched triangles, and Nightmare
was a blob with spikes. Its rows followed the reader's guess at the format, not the engine (see "Skinning, as the
engine runs it"):

- Stores were scattered over slots, but the engine writes each bone's stores to consecutive slots.
- Rows were not weight-premultiplied.

Through `engine_skin`, 13-60% of the slots v1 draws are never written in a frame, and adds pile onto stale
memory. Its own read-back missed this because it re-read the build with the same reader.

**v2 (`sc_sonic_vs_mario_random_v2`)** is the engine-exact skinning. In-game frames from i9-NUC
(`evidence_capture`) show whole bodies. The SM64DS donors were lit in dark, blotchy patches, because their
library normals disagree with their own faces.

**v3 (`sc_sonic_vs_mario_random_v3`)** adds the geometric normals and the skinned normal rows. In game, Luigi,
Mario, Eggman and Shadow are smoothly lit. The frames are in `D:\gBox\research\soulcalibur\evidence\v2\`, listed in
`evidence.json`.

**v3 textures were scrambled in game (#1765)**: Mario showed blocky red/blue/white patches, Cervantes as Knuckles
was a pale smear, and some costumes had black spots. The cause was the order of the strip UV words. The vertex
emitter at `0x8c03cc68` loads a corner's two UV u16 as one u32 and stores it as the TA's U float, then shifts it left
by 16 and stores it as V, so the second u16 is U. v3 wrote U first, so the game sampled every rebuilt page
transposed. Where the transposed sample hit an empty atlas cell, the result was black. The reader had the same error,
so its offline renders looked right. Its stock renders were wrong too: green feet and hair on Kilik, a green chest
and blue boots on Maxi.

The diagnostic disc `sc_diag_uv` replaced every rebuilt page with a UV gradient (R = u, G = v, B = page). Its
in-game frames (`D:\gBox\research\soulcalibur\evidence\diag_ingame\`) show each costume's own UV ramps, and
they match an offline render only with the axes swapped. The random-costume hook is not involved: the model and its
pages come from the same costume entry.

**v4 (`sc_sonic_vs_mario_random_v4`)** is v3 rebuilt with the corrected word order. Apart from the swapped UV
words, 39 of its 45 models are byte-identical to v3. The other six (the Peach costumes, plus Koopa and Sonic) also
carry this branch's double-sided and LOD changes. The offline renders are in
`D:\gBox\research\soulcalibur\evidence\v4_offline\` (`evidence.json`). They include the stock costumes and v3,
both rendered the way the game reads them.

**v4 Peach had no face.** The SM64DS library GLBs carry no normals. The retarget loader (`load_rig`) filled
them with a constant +Y, and `sm64_swap._orient` flips a material whose normals point toward its joint's centroid.
Peach's single-sided face (DS POLYGON_ATTR `0x81`) sits below her head joint's centroid, because the hair and crown
lift it, so the check turned the face inside out and the game culled it. The same check also flipped her neck and
both ponytails, and one Koopa Troopa part. Every one of those triangles agrees with its own DS normal, so the source
winding is right. A donor without normals now gets its winding's normals, flagged `normals_from_winding`, and
`_orient` leaves those parts alone. No other donor in the pool changes.

**v5 (`sc_sonic_vs_mario_random_v5`)** has 45 of 45 costumes built and verified. Compared with v4, the Peach (Seung
Mina, Sophitia, Ivy) and Koopa Troopa costumes change geometry. The other SM64DS costumes change only their normal
rows (lighting), because their donor normals are now geometric instead of +Y. Renders: `D:\gBox\research\soulcalibur\evidence\v5_offline\`.
The library Peach is the ending-cutscene model and is built to be seen from the front: with the DS's own culling,
the back of her head is open apart from the back-hair strip, so it is open in game too. Drawing her single-sided hair
from both sides would close it, at the cost of budget.

Known limits:

- The SM64DS Peach library entry (`sm64ds_peach`) is stretched before any fitting: one primitive spans 17 units
  with 5.5-unit edges. Ivy's and Seung Mina's Peach costumes show long spikes until that donor is fixed upstream.
- VS BATTLE and TEAM BATTLE wait for "PRESS 2P START". `evidence_capture` only drives the player-1 pad, so the
  in-game frames are Arcade fights, player 1 against the CPU. Both fighters still load through the patched loader.

### The HD build: `sc_sonic_vs_mario_hd_random` (#1748)

`python -m gbox.soulcalibur_swap build disc.gdi D:\gBox\cache\characters_mirror <out> sc_sonic_vs_mario_hd_random
--mario-group` on this branch's writer (TA UV order, winding normals, double-sided materials, the LOD ladder aimed
at the measured room). The Mario side is the `mario` group: Mario, Luigi, Wario, Peach, Yoshi and Bowser are the
Render96 HD models (8k to 42k triangles, reduced to 1.7k to 2.9k by the LOD ladder in two or three attempts); Koopa
Troopa, Metal Wario and Ukiki stay SM64 DS. 45 / 45 costumes built and verified, random costume hook installed.
Installed at `D:\gBox\cache\mods\c747331797369f74\sc_sonic_vs_mario_hd_random\`, marker written last,
`verified_in_game` false. Its title and `cast_source` name the `mario` group (`cast_swap.mario_side`).

Offline renders of every rebuilt costume (`scripts/sc_engine_render.py BUILT.gdi OUT "" --built-only`), front and
back: `D:\gBoxesearch\mario_donors\hd_builds\sc\` with `evidence.json`. Peach HD's head is closed from behind
(her hair is a closed mesh, so the SM64DS Peach's open back of the head does not apply and no double-sided hair is
needed). 41 of 45 look right. The two Metal Wario costumes (SIE1, INF1) are an untextured navy body, as in v5. The two
Koopa Troopa costumes (VOL1, CER1) have long black spikes from the hands past the head, as in v5: the SM64 DS donor
itself is wrong (sm64ds.md, Koopa Troopa).

Still unchecked:

- the hook's randomness on Flycast's TMU emulation, beyond the costumes seen
- how the green-key and blend materials behave now that donors use opaque `0x3x` materials only
