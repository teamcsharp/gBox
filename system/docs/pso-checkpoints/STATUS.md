# PSO checkpoints: status for the RE session (round 61, 2026-11-10)

Session identity: DeepSeek    Branch: ds-pso-cp-status-20261110    Commits: this branch
Goal: the status of every checkpoint worked under `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`

This is the review index: one line per checkpoint branch with its tip, its evidence file, and its state. Every branch
was re-audited against `origin/main` after main advanced by twelve commits (the grenade-checkpoints merge): **all 36
`ds-pso-*` branches exit 0 from `git merge-tree --write-tree origin/main <branch>`** (checked in round 49).

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP0 clean start | `ds-pso-cp00-clean-start-20261110` | `c67a2531` | `CP00-clean-start.md` | **done** - plane cleaned (parked session stopped, stale Linux launch cancelled), the then-open 23 branches rebased and force-pushed (24/24 merge-tree clean), operator question filed |
| CP0 step 4 registry | `ds-pso-cp00-classes-20261110` | `a1053cac` | `CP00-classes.md` | **done** - one module (`pso_classes`), pinned address `0x805D3138` + the 148-name list folded in as cross-checks, `test_pso_classes.py` 12 + ported `test_pso_class_registry.py` 6 green |
| CP1 local model | `ds-pso-cp01-local-model-20261110` | `70241e28` | `CP01-local-model.md` | **partial** - 14B up on the 3090 (100 % GPU, 54.83 tok/s, `/api/workers` available), the 30-32B candidates not pulled |
| CP2 gold set | `ds-pso-cp02-gold-set-20261110` | `1f3be478` | `CP02-gold-set.md` | **done** - both models scored on all 30 proven functions; **0.04 role rate each**, neither is a namer; 14B chosen (same accuracy, 8.6x faster) |
| CP3 labelling | `ds-pso-cp03-labelling-20261110` | `a80c2ddc` | `CP03-labelling.md` | **done** - export + resumable labeller, 82 rows at 1,621 functions/hour, 3090 at 68 %, $0.00/label; labels accepted only as string-proven leads |
| CP4 jump state | `ds-pso-cp04-jump-state-20261110` | `62a66013` | `CP04-jump-state.md` | **blocked (by design)** - the launch is held by `CPU > 70 %` and then `"Waiting for five minutes without operator input"`; driver `system/tools/pso_boot.py` and the boot walk are ready; recipe recorded |
| CP6.1 evt container | `ds-pso-cp06-evt-opcodes-20261110` | `0ebe1ec4` | `CP06-evt.md` | **done (container)** - the count comes from the header; `build == data` for 143/143 archive event files; **opcodes still open** (need the interpreter) |
| CP6.2 n.rel geometry | `ds-pso-cp06-nrel-20261110` | `11402321` | `CP06-nrel.md` | **partial** - `fmt1`/`fmt2` dispatch, the 0x18-byte tagged index, and the `fmt2` block (1,112 twelve-byte records, 87 groups) are mapped; the triangle-count comparison is not |
| CP7.1 model-walk crash | `ds-pso-cp07-model-walk-20261110` | `05ce01ad` | `CP07-model-walk.md` | **done** - `0x8028f508` is `lfs f0,0x8(r4)` inside `FUN_8028f2a0`; `pso_swapfit` checks that field from the file (11 tests) |
| CP7.2 object loader | `ds-pso-cp07-object-loader-20261110` | `d08f4f09` | `CP07-object-loader.md` | **done** - `FUN_801057a8` -> `FUN_8010542c` dispatches on the **payload type** through five constructors at `0x8049eee8`; class id only gates/registers; coverage measured 0.512 disc-wide with the hole invariant |
| CP7.3 scene loader | `ds-pso-cp07-scene-loader-20261110` | `503ed538` | `CP07-scene-loader.md` | **done** - `FUN_801fb798` composes `<area>r.rel`/`n.rel` from the floor resolver; `FUN_802066bc` dispatches `n.rel` by its 4-byte magic; GC has no Forest 1 rel (Dreamcast-side) |
| CP9 save data | `ds-pso-cp09-save-data-20261110` | `02584281` | `CP09-save-data.md` | **mostly done** - real card found, reader fixed (block fields were read at 0x3A), `PSO_CHARACTER` at block 17/11, storage proven encoded, **cipher fully transcribed** (permutation + subtractive ring); only the **runtime seed** is missing, readable only in a live session |
| CP15 step 4 | `ds-pso-cp15-room-inventory-20261110` | `5cdafed5` | `CP15-room-inventory.md` | **done** - the fifteen lobby sets are **floor 15**, not city rooms; floor 0 has one layout; the "walk to a lobby door" route is retired by measurement |

## The only live dependency

**CP4's window.** Both gates are understood and recorded: queue the launch only when the worker's `idle_seconds` is
already **>= 300** (a queued launch does not accumulate idle time - measured in round 57), with CPU < 70 %. The moment a
session exists: `python system/tools/pso_boot.py walk` (RAM-checked boot script) -> `save-state` -> `install-jumpstates`;
the same window yields CP9's seed read (the object at `r13-0x4694`'s `+0x118`) and then CP9's byte-flip accept test.

## Tests

The CP0 baseline on `8032491f` was **45 failed / 1,329 passed / 132 skipped** (Windows i9, Python 3.11; the guide's figure
is 45/1,333/133 on Python 3.12 - same 45 failures). No branch changed that set: the checkpoint branches are additive and
their own tests are green (CP0's 18, CP2's 7, CP4's driver smoke, CP7.1's 11, CP7.2's 6, CP9's 8, CP15's 9).

## Needs

- the RE session's review/merge of the thirteen checkpoint branches above;
- a CP8 decision: extract the Dreamcast `.chd` (no `chdman`/DC reader on the machine) or restate CP8's accept against the
  GameCube `Scene/*.rel` files;
- nothing else: CP5/CP10/CP16 need the same live window as CP4.
