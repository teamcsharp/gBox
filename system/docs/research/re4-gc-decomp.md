# The RE4 GameCube decompilation, as a tool (2026-11-07)

`adonis-singh/re4` is a **byte-identical decompilation of `G4BE08`** - the GameCube *debug* build, "Nov 25 2004", with
the `Bio4.sym` symbols that made it possible. That is the same build this system's RE4 MercMode rotation plays
(`TITLES['re4']['map_id'] == 'G4BE08'`), which is what makes it worth integrating rather than merely interesting.

Cloned read-only at `~/gBox_alt/reference/re4-gc-decomp` (52 MB, 1,015 sources and 249 headers, ~570k lines of C/C++).
Nothing builds it or runs it here: it is read as text.

## Why it matters for this objective

A bot anchor is **a structure layout plus a base pointer**. A stripped executable gives neither; the decompilation gives
the first half, annotated with offsets on nearly every field:

```
GET /api/reference/struct?name=cEm
  include/em.h | 30 annotated fields
     hp        0x0320     hp_max    0x0322
     status    0x03C4     flag      0x03C8
     Character 0x03D0     Item_id   0x03D6
```

`cPlayer` exposes 63 annotated fields, `SYSTEM_SAVE_WORK` the save block:

```
u32 Extra_flg;      // 0x04  EXT_* bits: mercenaries characters, stages and extra content
u32 MercSysRoom[4]; // 0x10  mercenaries record per stage: score / 10 | mode << 28 | new << 31
u32 MercSysRank[2]; // 0x20  mercenaries rank bits, 3 per (stage, character), MSB first
```

That last one is the "rank not verified" problem in source form: the game itself stores rank as three bits per
(stage, character) in one of two words, with the score divided by ten in the room record.

## Routes

| route | what it answers |
|---|---|
| `GET /api/reference` | is the corpus present, how many sources/headers, what title |
| `GET /api/reference/search?q=&regex=` | every matching line with file and line number |
| `GET /api/reference/struct?name=` | one structure's annotated field offsets |
| `GET /api/reference/structs` | every structure name the headers define |

`gbox/reference.py` does the work (`available`, `search`, `find_struct`, `offsets`, `structures`), and it refuses to
invent: a field without a `// 0xNN` annotation is not reported, and a missing structure returns `found: false` rather
than an empty layout that could be mistaken for one.

## What to use it for next

1. **RE4 Switch anchors.** The port keeps GC-era layouts closely - `cEm.hp` at `0x320` is a layout, not an address. With
   the layout known, the Switch base becomes a scan: find a block whose words match `hp_max` at +2, `status` at +0x3C4
   and a plausible `Character`, and the pointer is the anchor. That is the missing piece between "the walk reaches a
   round" and "the bot can aim".
2. **Mercenaries rules.** `Extra_flg` and `MercSysRoom` explain unlocks and ranks without guessing from screenshots.
3. **The `ImagePack` semantics.** The Switch loader's `"%s\%s\%08x.pack.fen"` is a port artefact; the GC source shows
   how the original addressed textures, which is a check on the id space the port inherited.

## Tests

`tests/test_reference.py` (8) runs against a fixture tree: search across headers and sources, regex and case handling,
limits, offset parsing in order, a field without an annotation staying out of the table, and a missing corpus reported
instead of raised. One platform bug was caught: relative paths came back with `\` separators on Windows, so the module
now normalises to `/`.
