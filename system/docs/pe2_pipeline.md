# Parasite Eve II (PS1): reader, Aya export and writer (#559), and what #840 needs

Everything below comes from the operator's own Disc 1 CHD (`Parasite Eve II (USA) (Disc 1).chd`, game id
`1b8acc6f11536a68`) and its boot EXE `SLUS_010.42`, disassembled with capstone. Nothing was downloaded.

Modules: `gbox/pe2_inventory.py` (disc, archive, LZ codec), `gbox/pe2_models.py` (model format, GLB export,
`characters.DEDICATED` entry `pe2`), `gbox/pe2_swap.py` (writer, routed by `characters op=use`, listed in
`char_coverage.WRITERS`). Tests: `tests/test_pe2_inventory.py`, `tests/test_pe2_models.py`, `tests/test_pe2_swap.py`.
The owned-disc tests run when `PE2_DISC` (a CHD, or a folder with the extracted files) or the Spark mount path exists.

## Disc and archive

| file | size | role |
|---|---|---|
| `SLUS_010.42` | 366,592 | boot EXE (PS-X EXE, text 0x80010000, size 0x59000) |
| `INIT.BS` | 12,104 | second-stage code |
| `STAGE0.HED` | 7,040 | index of STAGE0.CDF |
| `STAGE0.CDF` | 61,523,968 | the field game: rooms, Aya, weapons, enemies, menus, text, music |
| `STAGE1..3.CDF` | 93 / 50 / 36 MB | event/cut-scene streams with their own (id, sectors) tables |
| `INTER0.STR` | 221 MB | movies |

**STAGE0.HED** = three 0x28-byte records (bit 31 set), then `(u32 file id, u32 start sector)` pairs in ascending
sector order up to `0xFFFFFFFF`; a file runs to the next pair's sector. 864 files. The ids are decimal classes:
0..44 boot/pictures, 102xx..106xx Aya's outfit models, 10301..10332 weapons, 110xx voice banks, 2xxxx messages and
item pictures, 30xxx stills, 40xxx music (`hMPK`), 50xxx weapon code + sounds, 1xxxxx..6xxxxx rooms
(area * 100000 + room * 100), 80xxxx / 90xxxx menus.

An earlier Hermes run (workspace on the Spark, never pushed) had a different reading: a classified u16 table and a
13 MB "STF1 character geometry container". Neither holds: the HED is the flat pair list above, and the 13 MB region
in file 21000 is streamed audio (`STM` records, form-2 style sectors), not models.

**Chunks.** Each file is a chain of chunks; a chunk starts on a sector with a 16-byte header
`u8 type, u8 flag (1 more / 0xFF last), u16 bytes used in the last sector, u32 sectors, u32 RAM address, u32 0`.
The EXE's dispatcher is at 0x80022CF0 (jump table 0x80013294):

| type | meaning | handler |
|---|---|---|
| 0 | LZ data unpacked to the RAM address | 0x80010024 |
| 1 | LZ VRAM image: `(u16 x, u16 y, u32 offset)` entries until x = 0xFFFF; each is a 64x256 column sent as eight 64x32 LZ strips | 0x800248B4 |
| 2 | LZ CLUT: `u16 x, y, h, w`, data at +16 | 0x800246B0 |
| 3 | raw RAM copy | (inline) |
| 4 | streamed-audio table | (inline) |
| 5 | MDEC picture (BS v2 header `0x3800`) | (inline) |
| 6 | sound pack (`hSPK` / `hONE`) | 0x80053280 |
| 7 | text | - |

**LZ** (0x80010024 / 0x80010398): MSB-first bits; `1` + 8 bits = literal; `0` + 8-bit ring position (0 = end) +
4-bit length = copy length + 2 bytes from that absolute position of a 256-byte ring whose write pointer starts at 1.
The EXE fetches one byte eagerly after the end marker, so the next stream starts at `bitpos // 8 + 1`.
`pe2_inventory.lz_encode` produces streams the EXE's decoder reads (round-trip tests, and the image strips decode
back to the exact page).

## Aya

The field overlay (file 0, unpacked to 0x80093800) maps the outfit byte at RAM 0x80073BAE (1..5) through the table
at 0x800938CC (`04 03 02 05 06`) to file `10000 + 100 * n`. Events store 1 (0x800BC4C4) and 2 (0x800BC4EC).

| outfit | file | look (from the rendered models) | body header (EXE table, SLUS offset 0x58124) |
|---|---|---|---|
| 1 | 10400 | purple jacket, jeans | 0x8011B078 |
| 2 | 10300 | blue jacket, black shorts | 0x8011ACE8 |
| 3 | 10200 | black T-shirt, jeans | 0x8011C210 |
| 4 | 10500 | T-shirt, jeans, headphones | 0x8011C2E4 |
| 5 | 10600 | same bytes as 10500 | 0x8011C2E4 |

Each file = CLUT chunk (rows 245..246), image chunk (columns at VRAM x 384 and 448, y 256: one 8-bit page),
and the model unpacked to 0x80115770 (it must end below 0x8011D1C0, where the weapon overlays load).

**Model format** (instance builder 0x80041700, relocator 0x800409D0, bone renderer 0x80010848, handlers 0x80010F08 /
0x800110A0 / 0x800112DC / 0x800113E8 / 0x80011530). Absolute pointers; header (36 bytes):
`u32 0 (relocated flag), u32 packet bytes (GT3 0x28 / GT4 0x34 per primitive), u32 seam packet bytes, u32 bones,
u32 vertex-counts*, vertices*, normals*, bones*, primitive stream*`.
Bones 0x24 bytes (`s16 R[9]` 4.12 identity at rest, pad, `s32 T[3]` from the parent, `s16 parent`, pad).
Vertices `s16 x,y,z,pad` bone-local, contiguous per bone. Normals `s16` 4.12. Stream: groups
`[code, 0, count << 16 | words]`; `0xFFFFFFFE` ends each bone and the seam section, `0xFFFFFFFF` ends the stream.
0x38 = lit textured triangle, 0x78 = quad, 0xC8 = seam vertex (vertex, normal, packet XY slot, packet RGB slot),
0x39 / 0x79 = seam triangle / quad over the per-vertex screen table (vertex * 4). The seam packet slots follow
`base + 8 + 12k` (XY) and `base + 4 + 12k` (RGB) with GT3 = 0x28 and GT4 = 0x34 per primitive: checked on all 442
entries of file 10200. Four 1-bone sub-models per file are her hands (gun grips).

Proof: `pe2_models.serialize_tables` rebuilds the bone, count, vertex, normal and stream tables and the header of all
four distinct outfit models **byte for byte**, and the export renders the expected outfits with correct textures.

Aya in the collection: `characters op=collect` on PE2 → `pe2_aya` (outfit 1) + `pe2_aya_<outfit>`, 19 joints
`j00..j18`, roles hip j01, chest j03, head j04, clav/upper/fore/hand j09..j12 (left) and j05..j08 (right),
thigh/shin/foot j16..j18 (left) and j13..j15 (right). Left/right comes from the face direction, as for PE1.
~1.67 m, faces +Z.

## Writer (`gbox/pe2_swap.py`)

Same pipeline as `pe_swap` (PE1): `sm64_swap.load_rig` + `retarget` onto Aya's rest skeleton, then:

- triangles on one bone → 0x38, paired into 0x78 quads when two share an edge with the same UVs (the GPU draws a GT4 as
  the same two triangles, so the picture doesn't change and packet bytes drop by about a third); triangles across
  bones → 0x39 seam triangles with a 0xC8 entry per corner, like Aya's own joints;
- budgets: tables fit between her bone table and her header (the EXE points at the header, so it can't move), packet
  bytes and seam packet bytes no larger than hers, at most 1024 vertices (the per-vertex screen table is 4 KB on the
  draw call's stack, 0x800418C0). Over budget → Blender decimation when the node has Blender, otherwise per-bone
  vertex clustering;
- texture: one 256x256 8-bit page (tpage 0xB6) + one 256-colour CLUT (row 245); the blink/mouth frames stored after the
  header (eyes at page (0,78) 50x16, mouth at (12,104) 28x20, found by matching) are refilled from the new page so the
  game's face animation re-uploads the character's own pixels; the hand sub-models are collapsed to a point;
- the outfit file's chunks are re-encoded in their original order inside the file's own sectors (HED unchanged) and
  written into a raw copy of the disc with EDC/ECC recomputed (`psxdisc.RawBin`).

Mario (collection `mario`, 752 triangles) on the owned Disc 1, on this PC (no Blender): every outfit fits without
decimation (323 GT4 + 106 GT3 + 43 seam triangles, 21,036 of 22,344 packet bytes, 19.6 of 22.8 KB tables, texture
at full size). 163 sectors changed, only in files 10200..10600; SLUS, INIT.BS, HED and every other file are unchanged;
all rewritten sectors have valid EDC/ECC; the modded image reads back through `pe2_models` as Mario on all five outfits.

**Not verified yet:** the game running it. Things that could still differ in game: whether anything else reads Aya's
vertex offsets (shadow, muzzle position), the hands (collapsed; the character's own hands ride bones 8/12), and real-time
event scenes in STAGE1..3, which may carry their own Aya models (not touched). FMVs are video and stay Aya. Disc 2
(`5318e0449fee32b2`, `SLUS_010.43`) is routed with the same code but its files were not read in this run.

**Live check (agent test PC):**
`characters op=use character=mario game="Parasite Eve II (USA) (Disc 1)"` → builds `pe2_mario` and launches it. Start a
new game (outfit 1, the Akropolis tower), walk, draw the gun and fire, open the menu; then load a save with another
outfit. Expected: Mario on Aya's skeleton and animations, his face texture blinking cleanly. Report the first crash or
garbage frame with the room.

## #840: why it failed, and the generic PS1 path

**The failure in the screenshot** (Jobs tab, worker `188f14088d874b01`, This PC): `launch_game 4c7d0f1482b84542`
succeeded at 4:27, `graphics` succeeded at 4:30, then `session_op 76ab053a9d2149fc` failed at 4:33 with
`KeyError: '188f14088d874b01-4c7d0f1482b84542'`. `tools.session_op` looks the session up in the worker's in-memory
`SESSIONS` dict (`ad, _ = SESSIONS[inp.session_id]`, gbox/tools.py line 738, also 717 / 729) with no check, so any op
on a session the worker no longer holds raises a bare `KeyError`. A worker holds a session only in that process: a
worker restart (the same list shows `worker JAYBUILTFINALE restarted while running` at 2:59) or a later `launch_game`
(which pops previous sessions in `_close_previous_games`) leaves the server still showing the session as live. Earlier rows (`d877627cb2da4d73-5b0e6c5e6c004d72`, 2:53) are the same error. Fix to make:
`session_op` should answer "this session is no longer running on <worker> (the worker restarted or another game
replaced it): relaunch" and mark the session ended on the server, instead of a raw `KeyError`. Not changed in this
branch (runtime code outside this ticket's scope); confidence high on the mechanism, medium on which of the two
triggers hit at 4:33 (the worker's log for that minute would say).

**"Load any PS1 game and replace the model I pick-whip"** is not one feature on the PS1. There is no common model
format: every game packs models its own way (PE2 alone needed a chunk archive, two LZ variants, a custom
skinned-primitive format with seam packets, an 8-bit VRAM page and an EXE pointer that pins the header). What exists:

- **any game, now:** `characters op=overlay` draws the chosen character over the player in the desktop app;
- **native swaps:** Parasite Eve (Aya), Parasite Eve II (Aya, this branch, in-game check pending), Final Fantasy VII
  (Cloud), SmackDown! 2 (any wrestler), Metal Gear Solid / VR Missions (HUcast donor only, experimental). Syphon Filter
  (the game in the screenshot) has no reader or writer;
- **per new game:** a reader (archive + model format, from the EXE) → collection export with roles → a writer with the
  game's budgets. The PE2 tooling (capstone disassembly of the EXE, chunk walkers, LZ codec, `psxdisc.RawBin`) is
  reusable, but every title still needs its own format work.
- **a generic route worth building next:** pick-whip gives the on-screen model; on PS1 the model the GPU draws comes
  from a fixed RAM block for many games (PE2: 0x80115770 / header 0x8011C210). A generic "find the player's model in RAM
  from a GPU-command capture, then patch RAM live with `write_memory`" path would cover games whose model is a known
  primitive format without a disc rebuild, but each format still needs its decoder; it does not exist yet.

**This PC's readiness:** reading the CHD, building the PE2 mod and verifying it all ran locally (Python 3.12, numpy,
Pillow, capstone; no chdman needed: the CHD v4 reader in `frame_rip` made the raw image). Blender is not installed here,
so bigger donors than Mario fall back to vertex clustering instead of proper decimation.
