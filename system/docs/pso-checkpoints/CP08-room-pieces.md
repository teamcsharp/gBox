# CP08 room pieces — blocked on the Dreamcast data (measured: the CHD is version 4, unreadable here)

Session identity: DeepSeek    Branch: ds-pso-cp08-room-pieces-20261110    Commits: this branch
Goal: 2 (P6c)

## The data CP8's steps assume

CP8 step 1 says *"Decode the `r.rel` section table: Forest 1 has 17 sections of 40 bytes, root at `0x3114`"*. That is
**Dreamcast-side** data (CP7.3 measured that the GameCube disc has no Forest 1 `r.rel`; its Forest 1 is
`map_forest01d.dat` + `map_forest_*.bin`).

The only Dreamcast PSO image on this machine is

```
D:\gBox\cache\daba7a3b195dcf6b\Phantasy Star Online Ver. 2 (USA).chd   785,313,172 bytes
```

and **it cannot be read here**:

* its header is `4d 43 6f 6d 70 72 48 44` ("MComprHD"), header length `0x6C`, **version 4** (bytes at `0x0C..0x0F`);
* **ffmpeg 8.1** (installed) refuses it: `Error opening input: Invalid data found when processing input` - its `chd`
  demuxer handles version 5, not version 4;
* **7z, MAME and chdman are all absent** from the i9 (checked by `Get-Command` and a recursive search of
  `D:\gBox\runtime\retroarch*`).

So neither the section table nor `c.rel` can be read from the Dreamcast side today. Writing a CHD v4 reader in Python is a
project of its own (v4 hunk format, LZMA/zlib/flac codecs, the CD metadata block) and is not attempted here; the honest
options are for the RE session:

1. **install `chdman`** (MAME) on the i9 and run `chdman extractcd -i <chd> -o out.gdi`, then read the Dreamcast ISO9660
   (there is no DC disc reader in the tree either - `gbox.gcdisc` is GameCube only);
2. **restate CP8's accept on GameCube data**, which is what this lane has actually decoded: `Scene/map_aancient01_00n.rel`
   gives **167 index runs, 38,689 index values, 12,896 render triangles** against a **11,549-triangle** collision
   companion (`map_aancient01_00c.rel`), read by `gbox/pso_nrel.py` with a **byte-identical structural round trip**
   (CP6.2 branch `b7201875`, tests `tests/test_pso_nrel.py` 6 passed). Its room origins would come from the float arrays at
   `0x3834`/`0x858` (CP6.2) rather than from an `r.rel` section table.

## What CP8 can do now, entirely offline

The GC-shaped decode already answers the *spirit* of CP8's accept for one area: a reader that lists geometry with a
triangle count, cross-checkable against a collision file. What it does not have is the **per-room origins** (the `r.rel`
section transforms), because the GC side's equivalent (the `Scene/*r.rel` files that do exist for the ancient area) has
not been decoded yet - that is CP6.2's "vertices not yet interpreted" remainder, not a Dreamcast dependency.

## Needs

- the RE session's decision: install `chdman` for the Dreamcast data, or restate CP8 on the GameCube `Scene/*.rel` set (the
  lane's evidence supports the second today);
- no live session is required either way.

Tests: none changed.

## Round 76: CP8's accept, done in its GameCube form - every room's footprint and origin read from its `r.rel`

Option 2 from round 71 was taken, and it works better than expected. Each GameCube `Scene/map_<area>_<room>r.rel` opens
with **four 3-float points** - the room's footprint corners:

```
Scene/map_aancient01_00r.rel   (-100, 0, -150) (-100, 0, 150) (100, 0, -150) (100, 0, 150)   -> 200 x 300, origin (0,0,0)
Scene/map_aancient01_03r.rel   (-75, 0, -20)  (-55, 0, -20)  (-55, 0, 20)   (-75, 0, 20)    ->  20 x  40, origin (-65,0,0)
Scene/map_aancient01_04r.rel   (150, 0, 55)   (175, 0, 55)   (175, 0, 95)   (150, 0, 95)    ->  25 x  40, origin (162.5,0,75)
```

**New `gbox/pso_rooms.py`:** `room_quad(data)` -> `{corners, origin, size, min, max, y, flat, slope}` and
`rooms(names, read)` -> `[{name, origin, size}]`.

The measurement that mattered: a flatness check was wrong. **12 of the 141 real `r.rel` files are *sloped*** - `map_boss05r.rel`
spans y 1.23..7.00, `map_jungle03_00r.rel` spans -40..15, `map_darkfalz00r.rel` 4..5 - so a non-flat quad is data, and the
reader now records `flat`/`slope` instead of refusing it. (A footprint with zero x or z extent *is* refused.)

**Tests:** `tests/test_pso_rooms.py` **5 passed** - the axis-aligned footprint, the sloped-quad case, the zero-area refusal,
the truncation refusal, and the real disc (141 rooms parsed, the measured `00`/`04` values, and exactly **12** sloped rooms).

**CP8's accept, restated on this data:** *"a reader that lists the rooms with their origins"* - done for the GameCube areas
(141 rooms, origins and sizes measured). *"a test that a known door entity lands on a section boundary"* - not yet: that
needs the area's placement set joined to these rectangles, which is a small follow-up on this branch (the entities come from
`pso_setdata`'s records and the join is a point-in-rectangle test).
