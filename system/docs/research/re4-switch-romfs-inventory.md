# RE4 Switch RomFS inventory + Mercenaries/Ganado file evidence

Read-and-report inventory of `bio4/` in the Switch romfs for title `010099A00BC1E000`,
plus the files holding the five Mercenaries character models/textures and the Ganado enemy packs.
Measured 2026-11-09 on lilspark (local disk, **read-only**; no game started, no file modified).
Machine-readable twin: `re4-switch-romfs-inventory.json`.

## Method (how each column was obtained)

- **File counts/bytes** — full `os.walk` + `os.path.getsize` over every file under `bio4/` (5,275 files).
- **First-16-byte hex** — read the first 16 bytes of up to 3 files per extension; hex printed verbatim.
- **Container verification** — parsed every Mercenaries/Ganado `.udas` with the repo's own parser
  (`gbox/re4_switch_assets.py`: `Udas`/`Dat` classes) and checked `build()` round-trips byte-identical.
  `fill_hex` = first 8 bytes of the UDAS header (UDAS little-endian fill check).
- **Cross-check** — totals compared against the repo asset index `gbox/assets/010099A00BC1E000.json`.
- **Model/texture figures for pl08** — from the committed repo doc
  `docs/research/re4-switch-model-replacement.md (committed in this repo; measured 2026-11-09 on the same romfs)`; same romfs, same day. Re-verified here at container level only (see Limitations).
- **Character names** — pl08=Leon confirmed by content (live scale-change test per repo doc);
  the other four are name-suggested from the repo doc mapping table and **not** individually live-tested this run.

## Totals and cross-check

| Metric | Value |
|---|---|
| Files under `bio4/` | 5,275 |
| Total bytes | 12,934,747,107 |
| Asset-index entries | 5,275 (file-count match: **True**, byte-total match: **True**) |

## Directory tree (depth 3)

| Path | Files | Bytes |
|---|---|---|
| `bio4` | 7 | 290,845 |
| `bio4/title` | 16 | 462,016 |
| `bio4/st3` | 40 | 449,148,768 |
| `bio4/st2` | 42 | 532,854,912 |
| `bio4/ss/esy` | 25 | 4,335,680 |
| `bio4/ss/cht` | 111 | 30,211,264 |
| `bio4/ss/eng` | 110 | 30,201,136 |
| `bio4/ss/cmn` | 150 | 38,897,800 |
| `bio4/ss/ger` | 109 | 28,679,664 |
| `bio4/ss/item` | 418 | 22,702,576 |
| `bio4/ss/ita` | 109 | 28,716,912 |
| `bio4/ss/fra` | 109 | 28,738,320 |
| `bio4/ss/esp` | 109 | 28,733,808 |
| `bio4/ss/jpn` | 128 | 33,319,552 |
| `bio4/ss/chs` | 111 | 30,211,232 |
| `bio4/sv` | 1 | 458,796 |
| `bio4/font` | 67 | 157,122 |
| `bio4/iww` | 40 | 4,096 |
| `bio4/iww/homebutton2` | 1 | 136 |
| `bio4/imagepackhd` | 1813 | 6,144,462,613 |
| `bio4/snd` | 225 | 413,932,149 |
| `bio4/snd/foot/st3` | 76 | 40,036,668 |
| `bio4/snd/foot/st2` | 82 | 49,284,474 |
| `bio4/snd/foot/st0` | 4 | 759,274 |
| `bio4/snd/foot/st4` | 32 | 17,611,712 |
| `bio4/snd/foot/st5` | 64 | 30,611,961 |
| `bio4/snd/foot/st1` | 64 | 56,472,760 |
| `bio4/snd/room/st3` | 74 | 18,690,090 |
| `bio4/snd/room/st2` | 82 | 27,496,005 |
| `bio4/snd/room/st0` | 4 | 843,767 |
| `bio4/snd/room/st4` | 34 | 9,976,467 |
| `bio4/snd/room/st5` | 64 | 16,375,363 |
| `bio4/snd/room/st1` | 62 | 20,054,357 |
| `bio4/rel` | 146 | 23,909,848 |
| `bio4/etc` | 46 | 4,151,392 |
| `bio4/etc/eng` | 3 | 366,016 |
| `bio4/etc/jpn` | 3 | 256,096 |
| `bio4/bgm` | 6 | 10,296,576 |
| `bio4/em` | 162 | 326,433,344 |
| `bio4/gradients` | 6 | 19,200 |
| `bio4/text` | 12 | 128,852 |
| `bio4/movie` | 57 | 2,103,332,672 |
| `bio4/texture` | 1 | 1,152 |
| `bio4/info` | 1 | 10,628 |
| `bio4/option` | 14 | 133,984,448 |
| `bio4/option/newoption/menu` | 6 | 14,334,528 |
| `bio4/option/newoption/howto` | 8 | 99,540,480 |
| `bio4/achievement` | 17 | 44,712,672 |
| `bio4/evd` | 304 | 959,239,748 |
| `bio4/st4` | 14 | 156,700,736 |
| `bio4/ranking` | 14 | 120,508,392 |
| `bio4/st5` | 35 | 400,625,344 |
| `bio4/st1` | 34 | 401,323,968 |
| `bio4/op` | 3 | 138,720 |

## Extension histogram (by bytes) — with observed container magic

| Ext | Files | Bytes | First-16-byte hex (first example) | Example path |
|---|---|---|---|---|
| `fen` | 2117 | 7,103,702,361 | `00110e00789cecbd7f709bd779eff91a` | bio4/imagepackhd/3f0015a4.pack.fen |
| `udas` | 331 | 2,261,489,152 | `cab6be20cab6be20cab6be20cab6be20` | bio4/st3/r326.udas |
| `usm` | 57 | 2,103,332,672 | `43524944000007f8001806c000000001` | bio4/movie/r510s00.usm |
| `awb` | 433 | 698,797,207 | `41465332010402009b00000020000000` | bio4/snd/em17.awb |
| `fix` | 76 | 414,108,624 | `0000000080ac00000c00000044445320` | bio4/title/spa_press_start.fix |
| `dat` | 445 | 298,975,108 | `08000000000000000000000000000000` | bio4/ss/esy/map_obj4c.dat |
| `bin` | 242 | 24,195,976 | `98000000000000000000000050000000` | bio4/ss/cmn/itm19.bin |
| `rel` | 146 | 23,909,848 | `37000000000000000000000013000000` | bio4/rel/em48.rel |
| `acb` | 433 | 3,344,000 | `4055544600001ed8000101580000027e` | bio4/snd/em39.acb |
| `snd` | 1 | 876,832 | `20beb6ca20beb6ca20beb6ca20beb6ca` | bio4/ss/cmn/title.snd |
| `eff` | 4 | 610,976 | `0b000000400000006000000080000000` | bio4/etc/eng/event.eff |
| `tga` | 1 | 458,796 | `0000020000000000000000000002e000` | bio4/sv/dbgfont.tga |
| `t3d` | 6 | 284,362 | `426567696e204f626a65637420436c61` | bio4/uvdata.t3d |
| `esl` | 20 | 163,264 | `001b0700800011a0e8030000e10ac600` | bio4/etc/omake05.esl |
| `tpl` | 870 | 121,120 | `78563412010000001000000000000000` | bio4/ss/cht/f05a.tpl |
| `dct` | 8 | 118,307 | `44494354001000009f7dd55500000000` | bio4/text/chinese_t_win32.dct |
| `mdt` | 2 | 95,504 | `0600000030000000da00000000000000` | bio4/font/test_0.mdt |
| `fnt` | 65 | 61,618 | `20000000800000000000000000000000` | bio4/font/system_zh-tw.fnt |
| `hed` | 3 | 49,024 | `000000000090060040f2190020222600` | bio4/bgm/bio4midi.hed |
| `dds` | 7 | 20,352 | `444453207c000000071008000c000000` | bio4/gradients/gradient4.dds |
| `uwf` | 2 | 11,136 | `322e3030000e00000d000000ff0200ff` | bio4/etc/eng/event001.uwf |
| `csv` | 4 | 10,545 | `efbbbf64656661756c742c656e2c6a61` | bio4/text/resident_evil_4_prexence_data.csv |
| `ini` | 1 | 6,483 | `56455253494f4e203d2031360d0a4149` | bio4/input.ini |
| `acf` | 1 | 3,840 | `4055544600000ed80001015800000270` | bio4/snd/fen.acf |

Full per-extension first-16-byte samples (up to 3 files each) are in the JSON under `container_first16`.

## Mercenaries character packs

| Character | Pack | UDAS path | UDAS bytes | DAT slots | Header fill | Evidence |
|---|---|---|---|---|---|---|
| Leon | pl08 | `bio4/em/pl08.udas` | 1,512,608 | 133 | `cab6be20cab6be20` | confirmed by content (live-verified per repo doc) |
| HUNK | pl06 | `bio4/em/pl06.udas` | 1,284,032 | 133 | `cab6be20cab6be20` | name-suggested (repo doc mapping); container verified by content this run |
| Krauser | pl0a | `bio4/em/pl0a.udas` | 1,678,848 | 150 | `cab6be20cab6be20` | name-suggested (repo doc mapping); container verified by content this run |
| Wesker | pl0d | `bio4/em/pl0d.udas` | 1,165,152 | 133 | `cab6be20cab6be20` | name-suggested (repo doc mapping); container verified by content this run |
| Ada | pl0b | `bio4/em/pl0b.udas` | 2,008,000 | 148 | `cab6be20cab6be20` | name-suggested (repo doc mapping); container verified by content this run |

### What was measured for pl08 (Leon)

Repo doc (same romfs, same day): body model BIN at DAT slot 0 — **6,591 vertices,
4,577 triangles, 119 bones**; texture table TPL at slot 1 with
**83 image entries**, each joined to `imagepackhd/<packid>.pack.fen`
(u32 raw size + zlib level-6 → pack id, entry count, u64 offsets, 16-byte wrapper + DDS) and confirmed
DDS content. pl08 was the only pack **live-verified** (scale change visibly affected the player).

### Mapping provenance (confirmed by content vs name-suggested)

- **Confirmed by content:** container format, sizes, slot counts (this run, repo parser, round-trip = True);
  pl08 = Leon model/texture identity (repo doc live test); asset-index integrity (this run).
- **Name-suggested only:** pl06 → HUNK, pl0a → Krauser, pl0d → Wesker, pl0b → Ada (repo doc mapping
  table; packs verified as player-character packs by content: distinct slot counts
  133/150/133/148, 10–20 player-scale slot counts vs 698 for Ganado, round-trip parse OK).

## Ganado enemy packs

Eight packs `em10`–`em17` under `bio4/em/`, each a UDAS/DAT container, all parsed and round-tripped:

| Pack | Path | UDAS bytes | DAT slots | Round-trip |
|---|---|---|---|---|
| em10 | `bio4/em/em10.udas` | 8,903,328 | 698 | yes |
| em11 | `bio4/em/em11.udas` | 3,960,288 | 698 | yes |
| em12 | `bio4/em/em12.udas` | 3,848,352 | 698 | yes |
| em13 | `bio4/em/em13.udas` | 4,258,464 | 698 | yes |
| em14 | `bio4/em/em14.udas` | 4,354,304 | 698 | yes |
| em15 | `bio4/em/em15.udas` | 4,104,992 | 698 | yes |
| em16 | `bio4/em/em16.udas` | 4,016,416 | 698 | yes |
| em17 | `bio4/em/em17.udas` | 3,658,016 | 698 | yes |

Repo doc: `em16` DAT slot 476 = male Ganado villager model (2,139 vertices, 34 bones per doc).
All eight share the 698-slot count — content-confirmed as enemy packs, names not individually tested.

## Limitations / next acceptance step

- Slot-level BIN/TPL re-verification was not re-run in this pass; model/texture figures for pl08 come from the committed repo doc measured on the same romfs the same day and are re-verified here only at container level (UDAS/DAT parse + byte round-trip = True for all 5 mercs packs and 8 Ganado packs).
- pl06/pl0a/pl0d/pl0b character names are name-suggested (cross-referenced with repo doc mapping table), not individually live-tested in this run; pl08=Leon is the only live-verified mapping.
- Next step (optional, bounded): re-run slot-level `Bin`/`Tpl` parse for pl06/pl0a/pl0d/pl0b and re-derive
  vertex/triangle/bone and texture-join figures fresh, to upgrade the four name-suggested mappings to
  content-confirmed without any live gameplay (game was in play; no session was started).
