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

## The rank was in RAM all along (2026-11-07)

The same source documents both Mercenaries structures, offsets included:

```
MercResultInfo (MercSysWk + 0x00)          MercSysWork (0xCC bytes)
  score      0x00   final score              score 0x24   combo 0x28   comboTimer 0x2C
  time       0x04   1/100 s remaining        killCnt 0x34  kill 0x38   bonusKill 0x3C
  maxCombo   0x08                            maxCombo 0x40  bonusScore 0x44  addTime 0x4C
  kill       0x0C                            bonusTimer 0x50  mode 0x58  stage 0x5C
  mode       0x10                            flags 0x60      ClearScore 0x78
  rank       0x14   0..5 = N, D, C, B, A, S
  hiScore    0x18   hiMode 0x1C   newRecord 0x20
```

`rank` is the field this system has been inferring from screenshots - the `rank_not_verified` ticket class, sixty open
analyses. It is a small integer the game keeps itself, so a round can now carry `rank`/`rank_name` (and `hiScore`,
`newRecord`, `stage`, `character`) as **RAM evidence** instead of a reading of the results screen.

`gbox/re4_merc_ram.py` reads it: `result_info`, `work_state`, `rank_name`, `plausible`, `find_base`. Two details matter:

* the **base is a parameter**, because the static symbol addresses and this system's live GameCube anchors disagree
  (`EmMgr` is `.bss:0x802DE700` in the symbol map but `0x8027DF20` in `re4_editions.py`, verified live). Reading through a
  caller-supplied base keeps the layout useful without importing an address that may belong to another build;
* `find_base` **checks candidates** instead of trusting one: a rank outside 0..5, a mode outside the five characters, a
  stage outside the four stages, or a combo in the thousands make an address implausible and the next candidate is tried.
  The test that found this was written the other way round first (`rank is not None`, which accepted 9) - a number is not
  a rank, and the code now says so.

Symbols worth knowing from the map (`config/G4BE08/symbols.txt`, 7,395 functions and 5,402 objects with addresses):
`MercSysWk .bss:0x80271AEC (0xCC)`, `EmMgr .bss:0x802DE700 (0x38)`, `Global .bss:0x802E0478 (0x8680)`,
`SystemSave .bss:0x802E8AF8 (0x38)`, `pG .sdata:0x80314BC8`, `pSys .sdata:0x80314BCC`.