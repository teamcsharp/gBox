# PSO checkpoints: status for the RE session (updated round 74, 2026-11-10)

Session identity: DeepSeek    Branch: ds-pso-cp-status-20261110    Commits: this branch
Goal: the status of every checkpoint worked under `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`

Review index: one line per checkpoint branch with its tip, its evidence file, and its state.

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP0 clean start | `ds-pso-cp00-clean-start-20261110` | `c67a2531` | `CP00-clean-start.md` | **done** - plane cleaned, 23 branches rebased, operator question filed |
| CP0 step 4 registry | `ds-pso-cp00-classes-20261110` | `a1053cac` | `CP00-classes.md` | **done** - one `pso_classes`, pinned address + 148 names as cross-checks, 18 tests green |
| CP1 local model | `ds-pso-cp01-local-model-20261110` | `70241e28` | `CP01-local-model.md` | **done** - **both** models pulled onto the 3090: `qwen2.5-coder:14b` (9.0 GB, 100 % GPU, 54.8 tok/s measured) and `qwen2.5-coder:32b` (19 GB); the 32B was scored in CP2 |
| CP2 gold set | `ds-pso-cp02-gold-set-20261110` | `1f3be478` | `CP02-gold-set.md` | **done** - **0.04 role rate** for both models on the 30 proven functions; 14B chosen (same accuracy, 8.6x faster) |
| CP3 labelling | `ds-pso-cp03-labelling-20261110` | `a80c2ddc` | `CP03-labelling.md` | **done** - 1,621 functions/hour, 3090 at 68 %, $0.00/label; labels accepted only as string-proven leads |
| CP4 jump state | `ds-pso-cp04-jump-state-20261110` | `b3f1aee0` | `CP04-jump-state.md` | **ready, one window from done** - launch admission, session lifecycle and RAM reads proven on the i9 (mode read 0 -> 1 live); **both** causes of dropped presses fixed: `PAD_ALIASES` in `adapters.py` (ddown was unmapped) and the focus-at-delivery hop (`pso_boot_local.py`). Needs 5 min of operator absence with CPU < 70 % |
| CP6.1 evt container | `ds-pso-cp06-evt-opcodes-20261110` | `e1e61925` | `CP06-evt.md` | **container done** (143/143 byte-identical rebuild); opcodes open - the event system's **object side** named (event number at object `+0x84`, draw at `+0x38`, four debug-draw helpers); the interpreter needs a live breakpoint |
| CP6.2 n.rel geometry | `ds-pso-cp06-nrel-20261110` | `4c94c2ad` | `CP06-nrel.md` | **accept met on the GC file** - byte-identical structural round trip; the index runs are **triangle strips** (97.3 % adjacency) so **38,355 render triangles vs 11,549 collision** (3.32x); vertex arrays located by signature (1,313 at `0x527f4`, 1,041 at `0x90078`, bounding every index) |
| CP7.1 model-walk crash | `ds-pso-cp07-model-walk-20261110` | `05ce01ad` | `CP07-model-walk.md` | **done** - `0x8028f508` is `lfs f0,0x8(r4)` inside `FUN_8028f2a0`; `pso_swapfit` checks the field (11 tests) |
| CP7.2 object loader | `ds-pso-cp07-object-loader-20261110` | `d08f4f09` | `CP07-object-loader.md` | **done** - dispatch by **payload type** through five constructors at `0x8049eee8`; class id gates/registers; coverage 0.512 disc-wide with the hole invariant |
| CP7.3 scene loader | `ds-pso-cp07-scene-loader-20261110` | `503ed538` | `CP07-scene-loader.md` | **done** - `FUN_801fb798` composes `<area>r.rel`/`n.rel` from the floor resolver; `FUN_802066bc` dispatches by magic |
| CP8 room pieces | `ds-pso-cp08-room-pieces-20261110` | `450ba0fb` | `CP08-room-pieces.md` | **blocked on data, decision written** - the Dreamcast image is a **CHD version 4** (ffmpeg only reads v5; no chdman/MAME/7z here), so `r.rel` cannot be read; option B is to restate CP8 on the GameCube `Scene/*.rel` data CP6.2 already decodes |
| CP9 save data | `ds-pso-cp09-save-data-20261110` | `4066790c` | `CP09-save-data.md` | **offline complete** - real card, reader fixed, `PSO_CHARACTER` block 17/11, storage encoded, **cipher fully transcribed** (permutation + subtractive ring), and the seed's source function found (`FUN_802019f8`, a 24-way per-slot initialiser); the seed itself is runtime state, readable in the CP4 window |
| CP15 step 4 | `ds-pso-cp15-room-inventory-20261110` | `5cdafed5` | `CP15-room-inventory.md` | **done** - the fifteen lobby sets are **floor 15**; floor 0 has one layout; the lobby-walk route retired by measurement |

## The live window (one, and it unlocks the most)

Queue the launch when the worker's `idle_seconds >= 300` and CPU < 70 % (a queued launch does not accumulate idle time, and
any operator input resets the timer - measured twice). Then:

```
python system/tools/pso_boot_local.py --start-at press_start     # raises the window, injects, walks, polls RAM
python system/tools/pso_boot.py save-state                        # Dolphin slot 1
python system/tools/pso_boot.py install-jumpstates <path>         # jumpstates/<gid>-stock.state
```

That completes CP4; the same window yields CP9's runtime seed (`[*(r13-0x4694)+0x118]`, descriptor chosen by
`local_18 % 24` in `FUN_802019f8`) and enables CP5, CP10 and CP16.

## Tests

CP0 baseline on `8032491f`: **45 failed / 1,329 passed / 132 skipped** (Windows i9, Python 3.11; the guide's 45/1,333/133 on
Python 3.12 - same 45 failures). Checkpoint tests are additive and green: CP0 18, CP2 7, CP7.1 11, CP7.2 6, CP6.2 8,
CP15 9, CP9 8, pad aliases 5.

## Needs

- the RE session's review/merge of the fifteen checkpoint branches above (all merge-tree clean against main);
- a CP8 decision: install `chdman` for the Dreamcast data, or accept the GameCube restatement;
- **Blender is not installed anywhere on the i9** (checked for `blender.exe` under Program Files and D:), so CP12's rigging
  cannot run here at all - it needs the RE session's machine or an install;
- one operator-absent window for CP4 / CP5 / CP9-seed / CP10 / CP16.
