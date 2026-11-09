# RE5 Switch: Mario on the Majini — the group-aware enemy writer and its first offline candidate

2026-11-09. `gbox/re5_enemy_writer.py` builds a complete `uEm10.arc` in which the Majini model `em1000` (and its
`_mid` and `_low` variants) draws SM64 DS Mario on the native skeleton, materials and motion.

**Status 2026-11-09, later the same day.** This note was written before any boot and is kept as written below. Since
then the coordinating session reported one live result for the candidate (build
`recovery-mario-em10-v1-test-20261109`, session `a66b9d370de14727-98b48cb5b2b74d45`, Public Assembly): it loaded on
the first boot, the round played (199 kills at 9 minutes), and a gameplay frame showed two textured SM64 DS Marios
attacking the player beside a stock executioner, about 2.4 m tall, with faceted shading. That report is the
coordinator's observation; the work below and its follow-up were done offline and saw no frame. Shimmer from the
overlapping copies and culling could not be judged from the still frame.

Two statements below are superseded by [re5-enemy-cast.md](re5-enemy-cast.md): the archive DOES say which groups a
spawn can draw (entry 763 is an `MTG` montage table), and the writer now builds any library donor, the second Majini
class `uEm11`, and several donors on one model.

**Nothing here had been booted when this was written.** The candidate passes every offline structural check below and
two CPU previews.

| | |
|---|---|
| Module / tests | `system/gbox/re5_enemy_writer.py`, `system/tests/test_re5_enemy_writer.py` |
| Target | `nativeNXx64/ImgNX/Archive/uEm10.arc`, SHA-256 `1fa271890891ff31ac1aeb8d6dfc9a6d8bdcdd1ec252954b9d22a61519634a0c` |
| Donor | library `sm64ds_mario/sm64ds_mario.glb`, SHA-256 `ea509bdf870190e72c3fe9046b916a3b83d3a8058af422ad6186b11332bf12bb` (matches the handover) |
| Candidate v1 | SHA-256 `322c58a1092abbb8f6e43c7fd49550b7badd481997f2b878011a0976b524d7c7`, 83,663,646 bytes (original 82,582,897) |
| Local copy (not in Git) | `.scratch-merc-recovery/assets/mario-em10-v1/` — `romfs/…/uEm10.arc`, `receipt.json`, `preview.png`, `preview-posed.png` |
| Registered | No. No `plan()`, no dispatch, `live_verified: false`, `replacement_scope.complete: false` |

## What was measured in `uEm10.arc`

All of this was re-read from the archive bytes; the writer refuses an input where any of it differs.

- 787 entries. Every entry is a zlib-wrapped stream (`78 9c`) that recompresses byte-identically at level 6, with tag
  `0x40000000 | uncompressed size`. `mt_arc.build(parse(x)) == x`.
- MOD entries `234/235/236` are `em1000` / `em1000_low` / `em1000_mid`, MRL entries `196/197/198` carry the same
  names. `237–239` / `199–201` are the `em1001` set.
- The three variants do not differ in mesh detail but in skeleton: **92 / 35 / 58 bones**. Every role joint has the
  same bind position in all three, at different bone indices.
- **55 option groups, no group 0.** The last digit of a group id is the selection slot, the leading digits the variant.
  Each slot was confirmed from where the group's vertices sit and which material draws them:

  | slot | groups |
  |---|---|
  | head (Head/Eye/Teeth, y 125–186) | 1, 11, 101, 111, 121, 131, 201, 211 |
  | arm skin (222 is arms and bare torso) | 2, 12, 22, 32, 52, 62, 72, 82, 92, 222 |
  | leg skin (feet, or lower legs under shorts) | 3, 13, 23, 33, 43, 103, 113, 123, 133, 143 |
  | shirt | 4, 14, 54, 64, 74, 84, 104, 114, 124, 154, 164, 174, 184, 194 |
  | pants | 5, 15, 25, 55, 65, 105, 115, 125, 135, 205, 215, 225 |
  | sandals | 7 |

  `em1001` has the same list plus pants variant 35.
- 341 / 343 / 347 mesh records. Every group has records with LOD masks 1, 2 and 252 and no other mask; the header
  words at `0x90` read 500 and 1000 for `em1000`, 1000 and 1500 for `em1001`, which look like the switch distances.
- Mesh ids (`+0x26`) are a permutation of `1..count`. The table is sorted by material index. Mesh type `0xFFFF` is a
  drawn record; type `0x1020` with render mode 132 is a reduced proxy of the same part in a position-and-weights
  format with no normal or UV (for shirts and pants: the same extents with about a quarter of the vertices). It is
  read here as a depth-only record; that reading is an inference.
- Index ranges are contiguous, each followed by one `0xFFFF` the header counts and the record does not; an odd total
  is followed by one zero alignment word. Envelope table length, per-record counts and the header count at `0xA0` agree.
- Native skin never weights root bone 0. The hips hang off the pelvis (animation id 15).
- No texture is private to `em1000`: every one is also named by the `em1001` MRLs, some by `em2100`.
- ~~Nothing in the archive says which groups a spawn selects or which model set a stage draws.~~ Superseded: entry
  763 (`MTG`, 61 parts, 51 montages) lists the group combinations, and the stage layouts name the model type and the
  montage number of every spawn. See [re5-enemy-cast.md](re5-enemy-cast.md).

## Role map

`measure_roles()` derives the fifteen role bones from the bind pose alone (hierarchy and joint positions: the root's
floor-reaching trunk is the pelvis, its top-reaching trunk the spine; the chest is where the spine splits into two
lateral arms and a midline neck; a hand is the last joint stacked on the wrist; left is +X when the toes point +Z).
`role_map()` accepts the result only when it names the same bones as the RE5 animation ids. Both agree on all six
Majini models.

| role | animation id | bind position (cm) | `em1000` | `em1000_mid` | `em1000_low` | donor joint |
|---|---|---|---|---|---|---|
| hip | 15 | 0, 114, 0 | 1 | 1 | 1 | `skl_root` |
| chest | 2 | 0, 132, −1.34 | 15 | 13 | 11 | `spin` |
| head | 4 | 0, 165, −2.34 | 81 | 47 | 25 | `head:root` |
| l_upper / l_fore / l_hand | 11 / 12 / 14 | 17.2 / 43.6 / 70.4, 150.78, −3.44 | 50 / 58 / 63 | 32 / 37 / 39 | 20 / 21 / 23 | `arm_l1` / `arm_l2` / `wrist_l1` |
| r_upper / r_fore / r_hand | 6 / 7 / 9 | −17.2 / −43.6 / −70.4, 150.78, −3.44 | 17 / 18 / 20 | 15 / 16 / 18 | 13 / 14 / 16 | `arm_r1` / `arm_r2` / `wrist_r1` |
| l_thigh / l_shin / l_foot | 20 / 21 / 22 | 9.2, 101 / 57.45 / 13.5, 0 | 7 / 9 / 10 | 6 / 7 / 8 | 6 / 7 / 8 | `leg_l1` / `leg_l2` / `ankle_l1` |
| r_thigh / r_shin / r_foot | 16 / 17 / 18 | −9.2, 101 / 57.45 / 13.5, 0 | 2 / 4 / 5 | 2 / 3 / 4 | 2 / 3 / 4 | `leg_r1` / `leg_r2` / `ankle_r1` |

## Fit: the donor in the native pose

The fitted surface comes from the existing `re5_mesh_import.build_archive(pose_mode='native_segments')`. Each donor
joint lands on its native bind joint, limbs stretch to the native segment lengths, and no bind joint, inverse bind or
motion resource is edited — the RE6 `bind_mode="keep"` lesson, since native animations carry absolute locals and an
enemy's motion cannot be retargeted the way the player's root was.

The group-0 guard in `re5_mesh_import` was **not** changed. It protects the `source_proportions` / `source_reposed`
modes, which move bind joints and are the wrong tool for an enemy. The reviewed group list lives in
`re5_enemy_writer.EM1000` and is enforced there.

- Cross-section scale 9.8708, measured: native ankle height over donor ankle height, so the soles land on model y 0.
- Mario stands 237.9 cm tall against the Majini's 187.3: his head is 45 % of his height and is anchored at the native
  head joint (y 165). Bounds x ±100.0, y 0…237.9, z −37.8…51.0.
- The donor skin is rigid (one bone per vertex) and its GLB has no normals, so shading is flat per triangle.
- 1,338 vertices, 452 triangles, 15 envelopes per copy.

## Option groups: every group carries the whole donor

Which groups a spawn selects is decided outside this archive, so the writer does not bet on a slot:

- **Every native record is kept and made to draw nothing.** Its 56 bytes, vertex bytes and envelope records are
  byte-identical to the original; only its index words are rewritten to the record's own first vertex, so every strip
  is degenerate. Restart markers, face counts and vertex windows stay. This includes the depth-only proxies, so no
  Majini silhouette is left in a depth pass.
- **One new record per option group carries the complete donor** with LOD mask `0xFF`, the sandal material and mesh
  ids continuing after the native ones, inserted behind the last native record of that material so the table stays
  sorted. 55 records per model.

Whatever the game selects, the donor is drawn and no native part is. A spawn that selects five groups draws five
copies of the same vertex bytes, bones and material; they are expected to land on the same depth and colour. The CPU
sampler confirms the 55 copies are identical to 0.000000 cm under a native clip; the GPU result has not been observed.

Rejected alternatives: the donor in one group only (invisible for every spawn that does not select it — the earlier
one-mesh Sonic in group 1 played a round next to stock-looking enemies); the donor in the head groups only (vanishes
if the game hides a destroyed head); the donor split anatomically across slots (a spawn that skips a slot loses that
part, and group 222 suggests shirtless spawns exist).

Not determinable offline: the per-spawn selection, whether groups are hidden during damage or death, whether the
32-byte group-table spheres are used for culling (they are left native), and whether a stage draws `em1000` or
`em1001`.

## What v1 changes

Six entries, replaced by explicit index with `mtf_author.replace_archive_model` (`mt_arc.replace_at`):

| index | entry | change |
|---|---|---|
| 234 | `em1000` MOD | 341 native + 55 donor records, 2,329,756 → 4,711,036 bytes |
| 235 | `em1000_low` MOD | 343 + 55, 2,121,400 → 4,502,680 |
| 236 | `em1000_mid` MOD | 347 + 55, 2,267,256 → 4,648,536 |
| 108 | `gam01_007_BM` (512×256 BC7) | donor atlas, native container and mips |
| 110 | `gam01_007_NM` (BC5) | constant (128, 128) |
| 109 | `gam01_007_MM` (BC4) | constant 0 |

The MRL entries are untouched: the sandal material already samples entry 108. The other 781 entries are
byte-identical. Because the three sandal textures are shared, stock `em1001` and `em2100` Majini that wear sandals will
show the Mario atlas on them. That is a side effect, and also a marker that the overlay archive was loaded.

## Checks that were run

`verify()` runs inside every build and again on the written file from a fresh process, alongside an independent
re-parse that uses only `mt_arc` / `mt_model` / `mtf_author`:

- entry count 787 unchanged, names and hashes unchanged, 781 entries byte-identical, `mt_arc.build(parse(x)) == x`;
- each replaced entry is a wrapped zlib stream that equals `zlib.compress(raw, 6)`, tag `0x40000000 | size`;
- each model: skeleton, group table, material names, LOD distances and file trailer are the native bytes; the packed
  word re-derives as group 12 / material 12 / LOD 8 on every record; `(vertex_buffer − meshes − 56·n) = 144 · Σ counts`
  and the header count at `0xA0` equals it (4,624 / 3,127 / 3,992); vertex and face accounting close; mesh ids are
  `1..n`; the table is sorted by material; every index lies in its record's vertex window;
- every native record: 56 bytes, vertex bytes and envelope records identical to the original, and the strip decoder
  returns **0 triangles** for all 1,031 of them;
- one donor record per reviewed group in each model, identical bytes in all 55, 452 triangles each, vertices inside the
  written bounds, bones in range, weights summing to one; the per-bone vertex counts equal the donor's per-joint counts;
- textures keep their TEX container, dimensions, format and mip layout;
- the build is deterministic: the same inputs gave the same SHA-256 in separate processes.

Two CPU pictures were written next to the receipt: `preview.png` (rest pose: front, side, three-quarter, decoded from
the written MOD and the written BC7 atlas) and `preview-posed.png` (the same record under `em10_cmb` clip 3, frames
0/30/60, through `mtf_motion.sample_compare`; that clip needs no engine IK, so the mode is `sampled_fk`). The posed
body stays connected and bends at the native joints. Neither picture is the game's shading, IK or camera.

Tests: `test_re5_enemy_writer.py`, 15 tests on synthetic fixtures (a 24-bone skeleton with RE5 animation ids, no
group 0, a depth-only proxy record, a shared vertex buffer, inner strip restarts, an odd index count, MOD and MRL
sharing names) plus one opt-in test that builds the real candidate when `GBOX_RE5_UEM10_ARC` and
`GBOX_SM64DS_MARIO_GLB` are set.

## Reproduce

```powershell
$env:PYTHONPATH = 'system'
& .\.venv-session-audit\Scripts\python.exe -m gbox.re5_enemy_writer `
    --archive PATH\uEm10.arc --source PATH\sm64ds_mario\sm64ds_mario.glb `
    --out PATH\mario-em10-v1 --pose 259:3:0,30,60
```

Both input hashes are checked. `--sets em1000,em1001` also writes the sibling set (reviewed list: the same groups plus
35; built and verified offline once, not part of v1). `--secondary native` keeps the sandal normal and mask maps.
To bisect a load failure, call `author()` with a copy of `EM1000` whose `models` holds one variant.

## Before and during the first live round

Install only as a separate `recovery-mario-*` overlay through `switch_mods`, never into the live v15 build. The
measured format fixes that froze earlier loads (zlib framing, envelope count, bone-local envelopes, mesh ids) all hold
in this file. According to [the experiment record](re5-same-table-sonic.md), only the high `em1000` has loaded with a
restructured table since those fixes, and no model has been loaded with this shape.

What can go wrong, and how it would show:

1. **Load hang or black screen** (title, `NOW LOADING`, or a frozen first frame). A table with added records has not
   been loaded for `_low` / `_mid`. Use the frozen-frame check, not the screen name. Bisect by variant.
2. **Round plays, every Majini looks stock.** The class draws the `em1001` set, or these enemies are `uEm11`. Stock
   Majini with Mario-coloured sandals mean the archive loaded and the wrong set was replaced: build with
   `--sets em1000,em1001`. No coloured sandals at all means the overlay was not applied.
3. **Invisible enemies** (hits and shadows without bodies). The donor records are not drawn — LOD mask `0xFF`, mesh
   class 0 on the `_low` model, or the appended ids are not accepted — while the native records are correctly blank.
4. **Mario flickers or pops out near the screen edge.** The native group spheres are being used for culling.
5. **Spikes or a mirrored half.** Vertices behind z −19 and beyond x −90.9 use negative normalised coordinates. The
   player candidate relied on the same signed range; it is unconfirmed for this model.
6. **Shimmer on the whole body.** Overlapping copies do not resolve to one depth, or are blended.
7. **Wrong surface**: too dark, glossy or see-through means the sandal material does not suit a body.
8. **Expected, not defects of the file format:** a 2.4 m Mario with a large head above the native head hit zone; hard
   creases at elbows, knees and shoulders (rigid skin); faceted shading; no fingers or face animation; a head that
   stays when the Majini's would be destroyed; possibly no shadow.

Acceptance needs what the handover asks for any replacement: the build and session ids, the class census from RAM
(`uEm10` count), frames in which the drawn enemy is visibly Mario while fighting, advancing score and kills, and a
statement of which of the points above were seen. A boot is not acceptance and a title screen is not gameplay.
