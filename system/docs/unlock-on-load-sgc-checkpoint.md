# Unlock-on-load checkpoint: Sonic Gems Collection (USA) — request #2236

Status: **in_progress — static-analysis milestone only. No unlock writer exists and
nothing has been runtime-verified. Nothing was written to any save, ROM or progress flag.**

## Owned revision resolved

| Item | Value |
|---|---|
| game_id | `fc5914e3ddb540c4` (platform `gamecube`) |
| Disc | `Sonic Gems Collection (USA)`, game code **G2XE8P** |
| Executable | `main.dol`, 2,065,152 bytes, sha256 `a57a1d15b993a5881b002089d4ed993da4b43f796988abdad981e9b5269675f9` |
| Ghidra project (worker) | `pop_sot_main` — `main.dol`, PowerPC:BE:32:default, sha256 `4fdd1f5cfb032f82f25fb89b730444b101d2bfc6e9eb58db455d1638d26b3e6b`, 10,959 functions |
| Bridge job | `7deba2bab2a349be` (ghidra_bridge op=status) — state `succeeded`, worker `7b23bff397df4e2e`, receipt `d26c03f7dcb94734` |

## What the save files actually are

`state_us__museumNN.stm` / `.stg` (221,248 bytes each) are **GameCube memory-card saves of
this game**, not loose assets. The header of `state_us__museum01.stm` decodes as:

```
0x00 gamecode   'G2XE8P'
0x06 u16 magic  0xFF02
0x08 banner     'SONIC GEMSB_07'
0x28 u32 ts     0x0A1BF2F8
0x40 title      'SONIC GEMS COLLECTION'
0x60 comment    ' 8: VECTORMAN'      <- per-save slot label written by the game
```

Ten `.stm` slots exist (01–10) plus six `.stg` companions (01–06). The `.stm`/`.stg` pairs
differ by 43k–125k bytes each, i.e. the `.stg` file is a second progress store, not a copy.

Disc assets that back the museum mode: `museum__museum01..12.adx` + `.sfd`,
`museum__default.prs`, `museum__deftime.prs`, `museum__mu_new.prs`, `museum__museum.afs`,
`movie__museum.sfd`, `common__moji.prs`, `text__text_e.utx`.

## Handles located in main.dol (static, reproducible)

| String | vaddr | Pointer table entry |
|---|---|---|
| `STATE_JP\MUSEUM01.STM` | `0x801CD8E0` | `0x801E4C10` |
| `STATE_US\MUSEUM01.STM` | `0x801CD9D0` | `0x801E4C38` |
| `STATE_US\MUSEUM10.STM` | `0x801CDAA8` | `0x801E4C5C` |
| `STATE_US\MUSEUM01.STG` | `0x801CE018` | `0x801E4F78` |
| `LMUSEUM\DEFTIME.PRS` | `0x801CDC27` | (no pointer) |
| `MODULE/GEMS.STR` | `0x801CE1D0` | (no pointer) |

`SONICHEROES` (`0x801CCB74`), `SONIC GEMS COLLECTION` (`0x801CCBB0`), `SONIC GEMSB_`
(`0x801CCBC8`) and `SONIC GEMS_` (`0x801CCC1C`) are banner/prefix strings, not content tables.

## Category inventory — current honest state

| Category | Status | Entry names | Evidence |
|---|---|---|---|
| characters | unknown | — | no roster table located yet |
| hidden_characters | unknown | — | `MODULE/GEMS.STR` handle exists but its record meaning is unmapped |
| modes | unknown | — | museum mode assets present; eligibility check not located |
| levels | unknown | — | 12 `museumNN.adx/.sfd` asset pairs, no unlock table mapped |
| stages | unknown | — | same |
| costumes | unknown | — | — |
| items | unknown | — | — |
| extras | unknown | — | — |

**No category has a verified entry name.** Recording `not_present` is not justified either:
this revision's content set has not been enumerated. Treat the whole table as `unknown`.

## Blockers (explicit)

1. The per-entry meaning of the state payload is **not mapped**. The 2-byte records starting
   at `0x80` of each `.stm` are still unclassified: byte0 is `0x81` throughout, byte1 is
   `0x7f` with `0x9f` at scattered offsets (`0x00c4`, `0x00ce`, `0x00d6`, `0x00dc`, `0x00de`…),
   which is consistent with a per-entry flag byte but is **not proof**.
2. The 2-byte records at `0x80` differ between the `.stm` and `.stg` variants of the same
   slot, so both stores must be mapped before any writer exists.
3. No runtime acceptance whatsoever: no boot, no character/mode selection, no second-launch
   or rollback check. Per the request, a boot screenshot is not unlock evidence.
4. `main.dol` Ghidra analysis exists on the worker but has not yet been xrefed from the
   `0x801E4C10` pointer table to the routine that reads/writes the state slots.

## What was changed in this milestone

* `system/gbox/sgc_gems_probe.py` (new) — read-only, revision-guarded probe: exact game
  code, executable digest, 16 pinned state-save digests, save-header decoder, slot-name
  parser, slot grouper, and an honest `profile_gate()`.
* `system/gbox/game_unlocks.py` — `profile_for()` now returns a `pending_research` /
  `verified: False` record for `fc5914e3ddb540c4`; `pre_launch()` reports the research
  state and scope. **`verified` is False, so no writer is reachable from the Play path.**
* `system/tests/test_sgc_gems_probe.py` (new) — focused tests (7 cases).

No ROM, save, memory-card image or existing player save was modified.

## Exact next step

Open the owned `main.dol` in the worker Ghidra project `pop_sot_main` and xref the pointer
table entry `0x801E4C38` (`STATE_US\MUSEUM01.STM`) to the routine that loads the state
slot; from there xref the writer of the `0x80`+ records and the flag byte at `0x7f`/`0x9f`
to recover (a) the per-entry record layout and (b) the eligibility test that gates the
museum menu. Then map each record to the eight categories above, implement a
revision-guarded writer against the pinned digests with backup/rollback, and only then run
the live acceptance (fresh boot, select/play every discovered character and mode, second
launch, rollback) on an idle authorised worker at 2% audio.
