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
- **Pages**: raw 256x256 **YUV422, twiddled**, 131,072 bytes, no header. Y is the high byte of each word. The low
  byte is U on the even texel and V on the odd one. Page 0 of a fighter with a face (model flag `0x200`/`0x300` at
  +0x12) is the expression sheet. Pure-green texels mark the strands of hair or fringe.
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
  - Rows are `x, y, z, w` in bone space, 16 bytes each, with the positions first and then the normals. The low 12
    mantissa bits of `w` are the output slot, and the rest of `w` is the weight. The game skins by accumulation: the
    first `stores` rows store `w * M @ p` and the rest add to it. Normals are stored pointing **inward**.
  - Strips: sections of `u8 material, u8 flags, 0, u8 count` headers, each followed by `count x (u16 position,
    u16 normal | 0x8000 on the last, u16 u, u16 v)`. UVs are the upper half of a float. Triangle k is
    `(k, k+1, k+2)` when k is even and `(k+1, k, k+2)` when k is odd, and faces out in the game's space. `u32 0`
    closes a section, and an empty section closes the list. `material & 3` is the page (`0x3x` opaque; `0x2x`,
    `0x4x`, `0x6x` other modes).
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

- Hair and fringe strips use green-key pages. How the game masks them was not found, so they render opaque green.
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
  - New rows are written per bone. Each vertex gets up to 4 influences. The vertex's lowest bone stores and the other
    bones add.
  - Normals are stored inward.
  - The triangles are stripified with the game's winding, after the library-to-game mirror.
  - Texture page indices go in the material byte.
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
  - Every rebuilt costume parses and skins to finite positions, with its tail in place.
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

**Not verified in game.** No session was started. Things to check when the operator plays it:

- the load (the HUMAN work buffer was never exceeded: every entry keeps its stock size)
- lighting with the inward normals
- the hook's randomness on Flycast's TMU emulation
- how the green-key and blend materials behave now that donors use opaque `0x3x` materials only
