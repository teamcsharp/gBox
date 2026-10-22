# PSO Episode III - C.A.R.D. Revolution (USA): unlock research (#2210)

Owned build: `game_id=5b5ecb4c36a13584`, disc code `GPSE8P`, main executable `PsoV3.dol`
(`sha256 b02c3091542afc82fc62a1ddbe5f575f70aff6225778be1c12e0652bf47e82c2`).

This is **not** the Episode I and II Plus build (`GPOE8P`) that the existing
`gbox/pso_gc_*.py` tools target, so no existing address, guard or save layout is reused.

## Static analysis (Spark, 2026-10-20)

* De-paired ELF for Ghidra: `sha256 708174dfe09fe729a08b0dfd2d4696cee8bacdcde10cd177255158d41efc601d`
* Ghidra project `pso3` (headless, `PowerPC:BE:32:default`): 23911 functions, 8876 strings
* `analysis.json sha256 9fe3f1c7826614ad33ba960e722c04cd153c178cb13831655babaca4835a0de6`
* `psov3.c sha256 0617cf4ae330486d6c6a52bff8f39b0cfeb4431837cfaba3839f50619526fc9b`

### Save layout found in the owned build

| kind | value | address |
|---|---|---|
| Episode III history | `psohistory.sfd` | 0x803fadf8 |
| Episode III history (alt) | `psohistory_e.sfd` | 0x803fae08 |
| Episode III character file | `PSO3_CHARACTER` / `CHARACTER_FILE` | 0x80452ed8 |
| Episode III system file | `PSO3_SYSTEM` / `SYSTEM_FILE` | 0x80452f2c |
| Episode III guidecard | `PSO3_GUILDCARD` / `GUILDCARD_FILE` | 0x80453008 |
| Episode I and II data readable here | `PSO_CHARACTER` / `PSO_SYSTEM` / `PSO_GUILDCARD` | 0x80452f84 |
| DLC data present | `PSOV2/DOWNLOAD` | 0x8045305c |

### Lock-relevant entry points to trace next

| address | symbol | role |
|---|---|---|
| 0x803dce10 | `TItemLockCountCtrl` | lock counter / lock state UI |
| 0x803ddb2c | `TLockOnCursor` | cursor lock-on handling |
| 0x803df5a8 | `TObjQuestColALock` | quest column lock (challenge unlock) |
| 0x803df604 | `TObjQuestColALock2` | quest column lock variant |
| 0x803dda4c | `Block Select` | block/count select UI |

### Category inventory (see `profiles/gamedata/5b5ecb4c36a13584-unlock.json`)

* `characters`: 17 names in the Episode III name table (0x8046e11c..0x8046e84c) - `static_candidate`
* `hidden_characters`: no separate hidden roster proven - `unknown`
* `modes`: tournament, city tournament, challenge quest, battle-result packs, title side
  selection, auction/title results - `static_candidate`
* `levels`, `stages`, `costumes`, `items`: no table proven yet - `unknown`
* `extras`: Episode III guidecard, Episode III history save - `static_candidate`

No entry is marked `verified`: nothing has been observed being selected and played.

## State of the implementation

`gbox/pso3_unlocks.py` is a revision-guarded research profile registered in
`gbox.game_unlocks.profile_for` and its `pre_launch` hook. It writes no save, patches no
RAM and claims no unlock; the fast Play path reports `research_pending`.

## Next step (exact)

Trace `TItemLockCountCtrl` (0x803dce10), `TLockOnCursor` (0x803ddb2c) and
`TObjQuestColALock` (0x803df5a8) plus the Episode III save flags in Ghidra project
`pso3`; then, on an idle worker (i9-NUC or Spark, 2% audio) with an isolated memory
card, boot the owned disc and select/play every catalogued character and mode, test a
second launch and a rollback of the original card image.
