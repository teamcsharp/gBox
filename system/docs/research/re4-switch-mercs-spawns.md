# RE4 Switch Mercenaries spawns (request #9345)

Read-and-report. Source: the Switch RomFS `bio4/etc/omake01.esl` (sha256 `7e74dcfc4fe8fd16205ee3edf9a3bf9641a1ec4d6584e001f4bd2a812593c553`; Village r400 and Castle r402) and `omake02.esl` (sha256 `4699f8cbe8224b7297ae28ecd9cf5b2a72c4a5739dc52bb63afc5a6258616052`; Base r403 and Waterworld r404). No game file is copied into the repository. The table data is in `re4-switch-mercs-spawns.json`.

## Method

1. `gbox.re4_switch_enemies.STAGES` gives each stage's room id and ESL file. Entries are 32 bytes (the GameCube layout, little-endian); an entry belongs to a stage when its u16 at +0x18 equals the room (Village 0x400, Castle 0x402, Base 0x403, Waterworld 0x404).
2. **type** = byte at +2. **pack** = byte at +1 (the GameCube `emXX` id). **hp** = u16 at +8. These were read from the files (parser: `read_esl` plus a raw `struct` cross-check; both agree).
3. **identity** = `enemy_identity.re4_key(type, hp, em)` as it stands today. It is the repo's mapping, not a measurement, and each row says so.
4. Rows are grouped by (pack, type, hp); `count` is the number of placements in the list.

## Columns that are NOT determined (null in the JSON)

* **subtype / appearance id**: entries carry other bytes (+3, +4..+7, +0xA, +0x10..+0x17, +0x1A), but no document or code in the repository assigns them a meaning. Several vary within one (type, hp) group (for example +0xA is 0 or 0x200, and +0x1A holds small multiples of 5 in the Village and values up to 0x17c in the Castle). The `main` NSO code that reads them was not decompiled in this run. It would settle this: find the ESL loader in `main.bin` (see `re4-weapons-ram.md` for the segment map), then read which entry fields it copies to unit +0x3ce (type) and to the appearance/model selector.
* **wave / kill count**: the spawn list has no wave or kill-count field. Placements are positional (room coordinates at +0x10..+0x17), not timed. What would settle it: the Mercenaries director in `main` (what triggers a placement; the `flags` byte at +0 and the u16 at +0x1A are candidates), or a live round log of kill count against placement id. Not available under this ticket's rule against touching the game session.
* **max HP "the executable gives"**: the list's u16 at +8 is the only HP read here. Whether the executable overrides it with a per-type table was not read.
* **Switch unit type byte (`unit+0x3ce`) equals the list type**: not checked. The two values were never read together in this run; a live census (`UnitCensus`) of one round against these counts would settle it.

## Tables

### Village (room 0x0400, `omake01.esl`, 130 placements)

| type | pack | hp | placements | identity (re4_key) | level in table |
|---|---|---|---|---|---|
| 3 | em16 | 1300 | 1 | ganado | matched |
| 3 | em16 | 1400 | 14 | ganado | matched |
| 3 | em16 | 1500 | 2 | ganado | matched |
| 3 | em16 | 1600 | 2 | ganado | matched |
| 3 | em16 | 1700 | 1 | ganado | matched |
| 3 | em16 | 1800 | 29 | ganado | matched |
| 4 | em16 | 1400 | 13 | ganado | matched |
| 4 | em16 | 1600 | 3 | ganado | matched |
| 4 | em16 | 1700 | 1 | ganado | matched |
| 4 | em16 | 1800 | 22 | ganado | matched |
| 11 | em16 | 1200 | 1 | ganado | matched |
| 11 | em16 | 1400 | 5 | ganado | matched |
| 11 | em16 | 1600 | 3 | ganado | matched |
| 11 | em16 | 1700 | 1 | ganado | matched |
| 11 | em16 | 1800 | 8 | ganado | matched |
| 11 | em16 | 6500 | 3 | salvador | matched |
| 12 | em16 | 1400 | 2 | ganado | matched |
| 12 | em16 | 1500 | 1 | ganado | matched |
| 12 | em16 | 1600 | 1 | ganado | matched |
| 12 | em16 | 1700 | 1 | ganado | matched |
| 12 | em16 | 1800 | 7 | ganado | matched |
| 12 | em16 | 6500 | 3 | bella | inferred |
| 0 | em28 | 1000 | 4 | colmillos | inferred |
| 1 | em28 | 1000 | 2 | colmillos | inferred |

### Castle (room 0x0402, `omake01.esl`, 117 placements)

| type | pack | hp | placements | identity (re4_key) | level in table |
|---|---|---|---|---|---|
| 7 | em1c | 400 | 1 | zealot | matched |
| 7 | em1c | 500 | 5 | zealot | matched |
| 7 | em1c | 600 | 5 | zealot | matched |
| 7 | em1c | 700 | 11 | zealot | matched |
| 7 | em1c | 800 | 29 | zealot | matched |
| 7 | em1c | 900 | 26 | zealot | matched |
| 7 | em1c | 1000 | 10 | zealot | matched |
| 9 | em1c | 600 | 4 | zealot | matched |
| 9 | em1c | 700 | 2 | zealot | matched |
| 9 | em1c | 800 | 8 | zealot | matched |
| 9 | em1c | 900 | 10 | zealot | matched |
| 9 | em1c | 1000 | 1 | zealot | matched |
| 9 | em1c | 2200 | 1 | zealot_leader | unconfirmed |
| 9 | em1c | 2500 | 1 | zealot_leader | unconfirmed |
| 10 | em1c | 2500 | 1 | garrador | unconfirmed |
| 10 | em1c | 2600 | 1 | garrador | unconfirmed |
| 13 | em1c | 3000 | 1 | garrador_armored | unconfirmed |

### Base (room 0x0403, `omake02.esl`, 138 placements)

| type | pack | hp | placements | identity (re4_key) | level in table |
|---|---|---|---|---|---|
| 2 | em1d | 2000 | 3 | jj | inferred |
| 2 | em1d | 3000 | 2 | jj | inferred |
| 14 | em1d | 400 | 11 | militia | matched |
| 14 | em1d | 600 | 2 | militia | matched |
| 14 | em1d | 800 | 3 | militia | matched |
| 14 | em1d | 1000 | 1 | militia | matched |
| 15 | em1d | 400 | 8 | militia | matched |
| 15 | em1d | 600 | 5 | militia | matched |
| 15 | em1d | 800 | 2 | militia | matched |
| 15 | em1d | 1000 | 2 | militia | matched |
| 16 | em1d | 400 | 9 | militia | matched |
| 16 | em1d | 600 | 1 | militia | matched |
| 16 | em1d | 800 | 5 | militia | matched |
| 16 | em1d | 1000 | 2 | militia | matched |
| 17 | em1d | 400 | 9 | militia | matched |
| 17 | em1d | 600 | 3 | militia | matched |
| 17 | em1d | 800 | 1 | militia | matched |
| 17 | em1d | 1000 | 4 | militia | matched |
| 18 | em1d | 400 | 10 | militia | matched |
| 18 | em1d | 600 | 3 | militia | matched |
| 18 | em1d | 800 | 3 | militia | matched |
| 18 | em1d | 1000 | 1 | militia | matched |
| 19 | em1d | 400 | 9 | militia | matched |
| 19 | em1d | 600 | 2 | militia | matched |
| 19 | em1d | 800 | 3 | militia | matched |
| 19 | em1d | 1000 | 2 | militia | matched |
| 20 | em1d | 400 | 8 | militia | matched |
| 20 | em1d | 600 | 3 | militia | matched |
| 20 | em1d | 800 | 2 | militia | matched |
| 20 | em1d | 1000 | 3 | militia | matched |
| 21 | em1d | 400 | 9 | militia | matched |
| 21 | em1d | 600 | 3 | militia | matched |
| 21 | em1d | 800 | 2 | militia | matched |
| 21 | em1d | 1000 | 2 | militia | matched |

### Waterworld (room 0x0404, `omake02.esl`, 84 placements)

| type | pack | hp | placements | identity (re4_key) | level in table |
|---|---|---|---|---|---|
| 14 | em20 | 400 | 7 | militia | matched |
| 14 | em20 | 600 | 1 | militia | matched |
| 14 | em20 | 800 | 3 | militia | matched |
| 14 | em20 | 1000 | 1 | militia | matched |
| 15 | em20 | 400 | 6 | militia | matched |
| 15 | em20 | 600 | 1 | militia | matched |
| 15 | em20 | 1000 | 3 | militia | matched |
| 16 | em20 | 400 | 6 | militia | matched |
| 16 | em20 | 600 | 3 | militia | matched |
| 16 | em20 | 800 | 1 | militia | matched |
| 17 | em20 | 400 | 5 | militia | matched |
| 17 | em20 | 600 | 2 | militia | matched |
| 17 | em20 | 800 | 3 | militia | matched |
| 18 | em20 | 400 | 6 | militia | matched |
| 18 | em20 | 800 | 2 | militia | matched |
| 18 | em20 | 1000 | 2 | militia | matched |
| 19 | em20 | 400 | 6 | militia | matched |
| 19 | em20 | 600 | 1 | militia | matched |
| 19 | em20 | 800 | 1 | militia | matched |
| 19 | em20 | 1000 | 2 | militia | matched |
| 20 | em20 | 400 | 6 | militia | matched |
| 20 | em20 | 600 | 2 | militia | matched |
| 20 | em20 | 800 | 1 | militia | matched |
| 21 | em20 | 400 | 6 | militia | matched |
| 21 | em20 | 600 | 2 | militia | matched |
| 22 | em20 | 3500 | 3 | super_salvador | matched |
| 22 | em20 | 5000 | 2 | super_salvador | matched |

## Totals per identity

| identity | stage | placements | hp values |
|---|---|---|---|
| bella | Village | 3 | 6500 |
| colmillos | Village | 6 | 1000 |
| ganado | Village | 118 | 1200-1800 (7 values) |
| garrador | Castle | 2 | 2500-2600 (2 values) |
| garrador_armored | Castle | 1 | 3000 |
| jj | Base | 5 | 2000-3000 (2 values) |
| militia | Base | 133 | 400-1000 (4 values) |
| militia | Waterworld | 79 | 400-1000 (4 values) |
| salvador | Village | 3 | 6500 |
| super_salvador | Waterworld | 5 | 3500-5000 (2 values) |
| zealot | Castle | 112 | 400-1000 (7 values) |
| zealot_leader | Castle | 2 | 2200-2500 (2 values) |

Placement totals per stage: Village 130 (118 ganado, 3 Dr. Salvador, 3 Bella, 6 dogs `em28`), Castle 117, Base 138, Waterworld 84.

## Rows of `enemy_identity.py` (RE4 table and `re4_key`)

Confirmed (list type and HP match the key's rule; identity beyond the type is as inferred as before):

* `salvador` (type 11, hp 6500, 3 placements) and `bella` (type 12, hp 6500, 3 placements): confirmed by the Village list. The other type 11/12 entries are 1200-1800.
* `colmillos` (pack em28, types 0/1, hp 1000, 6 placements): confirmed as a separate pack in the Village list.
* `zealot_leader` (type 9, hp 2200 and 2500, one each, pack em1c): the HP separation from the ordinary type 9 (600-1000, 25 placements) is confirmed. That they are "leaders" is still a reading.
* `garrador` (type 10, hp 2500 and 2600, one each) and `garrador_armored` (type 13, hp 3000, one): the type and HP values are confirmed in the Castle list. The names stay inferred (slot 640's own 31-bone skeleton in `re4-parity.md`); nothing in the list names them.
* `jj` (type 2, hp 2000 x3 and 3000 x2, pack em1d, Base only): type and HP confirmed; the name is still inferred.
* `super_salvador` (type 22, hp 3500 x3 and 5000 x2, pack em20, Waterworld only): confirmed as the only type 22. Both HP values exist, so a rule that takes only `hp >= 5000` would drop three of the five; `re4_key` keys on the type alone and is fine.
* `militia` (types 14-21, hp 400-1000, em1d and em20): confirmed, 133 placements in Base and 79 in Waterworld.

Corrections to the evidence text:

* `ganado` (line ~444): the text says "types 3, 4, 11 and 12 at 1200-1800 health (124 placements)". The list has 118 placements at 1200-1800; the other 6 of the 124 em16 non-dog placements are the 6500 HP Dr. Salvador/Bella entries. Change to 118 (or say 124 including the six 6500 entries).
* `zealot` (line ~470): the text says "types 7 and 9 at 400-1000 health (110 placements)". The list has 112 (87 of type 7 and 25 of type 9). With the two leaders it is 114.

Not settled: that the Switch unit's type byte equals these list types, the subtype/appearance id, and any wave or kill count (see above). `re4_key` is therefore consistent with the lists but unverified against live Switch units.

## Findings: ESL loader and `unit+0x3ce` writers (main.bin static scan, request #9345)

Method: capstone over `main.bin` (mem = file offset - 0x100), bounded scans, no live process.

* **ESL file table** (rodata `0x688000` region, stride 0x18): `{name ptr, data slot ptr, 0x403}`; e.g. `0x688608` = `etc/omake00.esl` -> slot `0xb1a570`; `emleon00..09` and `omake00..08` are consecutive entries. A parallel pointer array of the name strings lives at `0xb1a518 + idx*8` (data segment).
* **File open by index**: function containing `0x4e0540` loads `name = [0xb1a518 + idx*8]` (idx <= 0x25, else a fallback string at `0x6cfcfd`), stores idx at `*(game+0x5027)`, opens it via `0x89780` and reads it via `0x8bc60`; the bytes are copied to `*(game+0x5484)` (0x2000 bytes) with `0x653c90`, or zeroed (`0x653ce0`) when the load fails. So the loaded ESL set list is a 0x2000-byte block at `game+0x5484`, selected by the byte at `game+0x5027`.
* **`unit+0x3ce` writers**: only two direct `strb [x, #0x3ce]` sites exist in the whole text segment, `0x13a508` (stores 0x16 in an AI state switch) and `0x1b1900` (stores 0, state reset). Neither copies an ESL field. The byte is also the index of a 45-entry jump table at `0x13a448` (`byte-1 <= 0x2c`) and a state bitmask test at `0x1b189c`. **So `+0x3ce` may be a unit state/action code rather than the ESL type** - the "type byte" label in `re4-switch-ram.md` is not confirmed by this scan. The ESL->unit copy is not a direct `strb` at that offset; it likely goes through a struct copy or an indexed store. **Next step**: xref readers of `game+0x5484` (add `#0x484` after `0x5000` pages / `mov w, #0x5484` constants) to find the real parser, then read which entry fields it stores.
* Not done: live census check of type vs list (requires the i9-NUC/Spark session).
* **Readers of `game+0x5484`** (constant `mov w,#0x5484` / `add x,x,#0x484` scan; candidates, not yet read): mov at `0x1b214 0x1b2e0 0x1b450 0x1ccf2c 0x1cd3b8 0x1cdb04 0x1cdb94 0x1cdbd4 0x3ac9d8 0x3ac9ec 0x3af264 0x3e2578 0x43e36c 0x44f41c 0x455688 0x455800 0x457184 0x45e9d0 0x45f7c0 0x461124 0x461158 0x46dc8c 0x47ad34 0x47b888 0x47b8fc 0x47b9ec 0x47bae0 0x4e05e4`; add-form at `0x101e9c 0x2591f4 0x2c428c 0x2c5f84 0x2c91a0 0x2cad54 0x2cb04c 0x2cfc54 0x2d006c 0x3196c4 0x329ba0 0x35859c 0x45dfc4 0x45edf8 0x45fa58..0x45fac8 0x48550c 0x505da0 0x5809b0`. The enemy-spawn parser is most likely among `0x1b2xx`, `0x1cc/0x1cd`, `0x45f-0x461` and `0x47b`.
