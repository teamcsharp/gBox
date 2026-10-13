# Dead Or Alive ++ (arcade, Tecmo TPS) character pipeline

Ticket #1340 (GAP: character writer for Dead Or Alive ++ (Japan)). Catalog: `a19b4e641b155364` "Dead Or Alive ++
(Japan)" = MAME `doapp` (parent; "Japan/USA/Export", region set in the test menu), `59c55e95af61abbe` = `doappk`
(Korea clone, only the two program ROMs differ). It is **arcade PlayStation hardware without a disc**: Tecmo TPS
(ZN-1 board, BIOS set `coh1002m`, MAME driver `zn2p`, `src/mame/sony/zn.cpp`). There is no SLPS executable and no
ISO9660; everything lives in the 0x2800000-byte `bankedroms` region the CPU sees through an 8 MiB window at
0x1f000000 (bank byte written to 0x1fb00006).

| Stage | State | Where |
| --- | --- | --- |
| Inventory (identity, files, fighter index) | done, verified against the owned ROMs | `gbox/doapp_inventory.py`, `gbox/zn_tps_boot.py` |
| Format analysis | file table, model container, mesh sections, renderer located | this document |
| Reader (rigged GLB) | blocked on the skeleton (see Status); format-level parsers done | `gbox/doapp_models.py` |
| Writer | not started (constraints in Status) | — |

## Owned source

`collections/Mame/roms/doapp.zip` (13.7 MB) + `coh1002m.zip` (BIOS `m534002c-61.ic353`, CPU-board CAT702 `mg01`) on
the HyperSpin share (`//10.89.1.125/HyperSpin Attraction/Arcade/collections/Mame/roms`). All MAME dat SHA1s match.

## The program is encoded, the file table is inside it

`bankedroms[0:0x88880]` = `0x0000020b`, the SCEI licence string, then an encoded image (entropy 7.95). The TPS BIOS
decodes it into RAM 0x80010000..0x80097e18 and jumps to 0x800107d8. The BIOS strings name the modules
(`decode.c`, `decodesce.c`, `decodetecmo2.c`, `ramsec.c`): the decode exchanges bytes with the two CAT702 security
chips over SIO0 (mg01 on the CPU board, mg05 on the ROM board), selected through `znsecsel` 0x1fa10300 (bit 2 / bit 3,
active low). The kernel itself is stored encoded in the BIOS at 0x30000 (header 0x08100080 = 8 x 16 x 128-byte
blocks) and the BIOS routine 0xbfc0638c decodes it into RAM 0x500 with chip mg01; the game is decoded by kernel
function B0:0x63 (0x800021a8 -> 0x80001328).

`gbox/zn_tps_boot.py` reproduces this without re-implementing the cipher: a small R3000 interpreter runs the BIOS's
own code (kernel decode, then B0:0x63) against a CAT702 model taken from MAME's `cat702.cpp` (byte-level form,
checked against a clock-level model in `tests/test_zn_tps_boot.py`). ~10 M instructions, ~35-40 s of CPython. The
decoders call `rand()` for their work order (seeded from timers); the output does not depend on it.

Evidence that the decode is right: the decoded image is code (jr ra / addiu sp density across 0x10000-0x90000), the
returned entry 0x800107d8 is inside it, its loader at 0x800ff5a4 (in the plain overlay) indexes the table at
0x800515a4, and the 280 table records tile the data ROMs exactly (consecutive offsets + sizes, zero gaps except bank
boundaries) and agree with every content signature (TIM `0x10`, VAB `pBAV`, SEQ `pQES`, model containers below).

## File table (`doapp_inventory.FILE_TABLE`)

12-byte records at RAM 0x800515a4: `u8 bank (+3 pad), u32 offset in the 8 MiB bank, u32 size`; 280 entries. The
loader reads 0x800-byte units from 0x1f000000 + offset after writing the bank to 0x1fb00006. Files are packed back to
back, so a file can only be replaced in place within its own size (`file_room()` gives the bytes up to the next
file; only the last file of a 4 MiB ROM has slack).

| Files | Content |
| --- | --- |
| 0 | plain overlay (fight code + data) loaded at 0x80097e18, 0x90930 bytes |
| 1 | second overlay, 0x12721 bytes |
| 4-14, 15-25, 38-48 | per-fighter small files (tables `small_a`, `small_b`, `small_c`) |
| 27-37 | per-fighter motion banks (`motion`, 250-410 KiB, pointer table relocated at +0x1010..0x1020) |
| 49-103 | fighter models: 11 groups of 5 table slots = 4 costumes + 1 zero-size slot |
| 104-120 | stages (table at 0x80087bcc) |
| 121-133, 145-177 (odd) | VAB sound banks (`pBAV`); 146-176 (even) SEQ music (`pQES`) |
| 134-144 | per-fighter `bank_c` |
| 178-279 | TIM images (UI, portraits; 233-243 and 267-277 are per-fighter) |

## Fighters (`doapp_inventory.FIGHTERS`)

Internal fighter ids from the ranking tables at 0x80087940 (u8 id + name): 0 ZACK, 1 TINA, 2 JANN LEE, 4 HAYABUSA,
5 KASUMI, 6 GEN FU, 8 BAYMAN, 9 BASS, 11 RAIDOU, 12 LEI FANG, 13 AYANE (3, 7, 10 are unused ids whose table rows
alias Kasumi). Model file per costume: `u16` at 0x80087334 + 4 * (id * 19 + costume); costumes 0-3 are distinct
files, slot 4 is a zero-size record, 5-18 repeat costume 0. Six more one-file-per-fighter tables (`CHAR_TABLES`).
The fight loader (0x8006c300) reads player record 0x80096340 + 0x60 * player: byte 1 = fighter id, byte 2 = costume.

## Model container (files 49-102)

```
u32 tim_offset                       -> run of standard PS1 TIMs (4 bpp + CLUT) to the end of the file
14 x section, each 4-byte aligned:   u32 dest (0 = absent, 4 bytes only) ; u32 length ; payload
```

`dest` is the offset in the per-player work buffer (player 0: 0x801e8000; the 14 section pointers are stored at the
start of that buffer). Sections 0, 1, 2, 11, 13 are copied raw; 3-10 and 12 are packed and expanded by 0x8006c718
(stream of 16-bit units: odd = one s16 value, even = low half of a 32-bit value whose high half follows; `length`
is the expanded size). The expander's output starts with the marker 0x42.

* section 0 (female fighters only): SVECTOR-like 8-byte offsets (secondary/physics joints).
* sections 1, 2: u16 arrays, per drawn part the vertex count and first vertex used by the renderer
  (read at part-record +0x530 / +0x534 by 0x800ab828).
* sections 3-10, 12: meshes. `[0x42][header size][vertex block offset][group count]{count, chunk offsets[count]}`,
  vertex block = SVECTOR (s16 x, y, z, pad) to the end of the section. A chunk is `u16 count, u16 kind`
  (kinds 0x8018 / 0x8019 / 0x801a / 0x801b / 0x803a / 0x805a / 0x29 ...) followed by prebuilt GPU packets
  (e.g. 0x0c000000-tagged GT4 0x3c packets with UV / CLUT / tpage filled in), per-primitive vertex pointers into the
  transformed-vertex buffer (0x1f800000 + 8 * i, spilling to 0x802a6800 after 126 vertices) and 4.12 normals.

Renderer: 0x800ab828 (overlay) sets the bone matrix (32-byte matrices, bone index from a per-part byte table) and
calls 0x800abe94(section, count, first) which RTPT-transforms the vertex block into that buffer, then walks the chunk
list dispatching on the chunk kind.

### Vertex batches and bones (`gbox/doapp_models.py`)

Sections 1 and 2 hold 13 u16 counts / first-vertex indices per mesh slot (slot k = section 3 + k). The renderer
transforms batch p of slot k with bone matrix `BONE_SLOTS[k][p]` (the 13-byte tables at overlay 0x80103ed0; the
body uses 0x80103f2c when it has 10 groups) into the shared transformed-vertex buffer at the batch's own first index,
so primitives can join vertices of different bones (rigid one-bone-per-vertex skinning, seams included). Checked on
all 44 costume models: the batches cover every vertex of every mesh exactly, and the mesh group count equals the
batch count (one more in slots 0, 1 and 3 when those carry an extra group). Bones 0-14 are the main skeleton (15 matrices, post-processed by 0x800ad810), 15-26 are
costume accessory chains (hair, ribbons; mesh slot 7, matrices from the chain solver 0x800aa1c0 driven by the
per-fighter/costume table at 0x80103ab8). Batch extents give the local frames: bones 3/9 feet, 4/10 and 8/14 the two
arm segments, 5/11 hands (three alternative hand shapes in slots 2 and 4, one drawn per frame), 6/12 and 7/13 the two
leg segments, 0/1/2 torso / head / pelvis (labels from geometry, not from code).

## Status

* **Inventory: done.** `python -m gbox.doapp_inventory <roms dir> [--decode] [--extract DIR]`. Tests:
  `tests/test_doapp_inventory.py`, `tests/test_zn_tps_boot.py` (the owned-ROM checks run when `GBOX_DOAPP_ROMS`
  points at the directory with `doapp.zip` + `coh1002m.zip`; they decode the program, ~40 s).
* **Format: container, section expansion, meshes, batches, bones, TIMs done** (`gbox/doapp_models.py`,
  `python -m gbox.doapp_models <roms dir> tina --expand`). The expansion runs the game's own 0x8006c718 on the
  interpreter rather than a port; the per-kind chunk layouts are not decoded yet (kind 0x801b was seen to hold 0x3c GT4
  packets, then four vertex-buffer pointers and four 4.12 normals per quad).
* **Reader (rigged GLB): blocked on the skeleton.** Each bone's batch is in its own local frame and those frames are
  not aligned (thigh geometry runs along -z, shin along +z), so assembling the body needs the rest rotations and
  joint offsets. They come from the motion evaluator: motion banks (files 27-37) are four 0x404-byte curve tables
  then 265 motions of 8 bit-packed per-frame tracks, relocated by the loader at +0x1010/+0x1020; the code that turns
  a frame into the 15 bone matrices at 0x8011ca60 + 0x340 * player was not found (the functions that touch those
  matrices are the camera transform 0x800a4798, the head-look 0x800a76a0 / 0x800a791c / 0x800a6d30, the accessory
  chains and post-processing). The per-fighter data file (`small_a`, relocated by 0x8006a754, 32 sub-tables) holds
  hit spheres and move data, not bone lengths. Not registered in `characters.DEDICATED`: an unrigged or guessed pose
  would be a substitute, which gBox refuses.
* **Writer: not started.** Constraints found so far: files are packed back to back and the table that sizes them is
  inside the encoded program, so a replacement model must fit the original file size (`file_room()`), keep the
  14-section container, and expand within the player work buffer; the mod would be a rebuilt `doapp-1.217` /
  `doapp-2.218` in a mod ROM set (MAME validates ROM CRCs per set, so it needs its own set name or `-skip_gameinfo`
  with a renamed zip). Re-encoding the program is not needed for in-place replacement.

Next step for whoever continues: locate the motion evaluator (start from the per-frame player update that calls
0x800a4848 via 0x800a1510, or from readers of the motion list at character-data +0x58 / curve tables +0x5c), decode
one frame of motion 0 into the 15 matrices, and check it by transforming the batches: the seams between batches must
close. That gives the rest pose for a rigged GLB and the bone frames a writer retargets into.

## Live check for the maintainer

On the agent test PC, with the HyperSpin MAME roms reachable:

```
copy "\\10.89.1.125\HyperSpin Attraction\Arcade\collections\Mame\roms\doapp.zip" + coh1002m.zip  ->  %TEMP%\doapp\
python -m gbox.doapp_inventory %TEMP%\doapp --decode          # derived.file_table_matches_snapshot: true
python -m gbox.doapp_models %TEMP%\doapp tina --expand        # every mesh: covered == vertices
set GBOX_DOAPP_ROMS=%TEMP%\doapp && python -m pytest tests/test_doapp_inventory.py tests/test_doapp_models.py -q
```
