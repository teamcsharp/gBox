# PSO checkpoints: status for the RE session (updated round 69, 2026-11-10)

Session identity: DeepSeek    Branch: ds-pso-cp-status-20261110    Commits: this branch
Goal: the status of every checkpoint worked under `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`

Review index: one line per checkpoint branch with its tip, its evidence file, and its state. **All 14 checkpoint
branches exit 0 from `git merge-tree --write-tree origin/main <branch>`** (re-audited this round), and so do the 36
`ds-pso-*` branches at large.

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP0 clean start | `ds-pso-cp00-clean-start-20261110` | `c67a2531` | `CP00-clean-start.md` | **done** — plane cleaned, 23 branches rebased, operator question filed |
| CP0 step 4 registry | `ds-pso-cp00-classes-20261110` | `a1053cac` | `CP00-classes.md` | **done** — one `pso_classes`, pinned address + 148 names as cross-checks, 18 tests green |
| CP1 local model | `ds-pso-cp01-local-model-20261110` | `70241e28` | `CP01-local-model.md` | **partial** — 14B on the 3090 (100 % GPU, 54.8 tok/s), 30–32B not pulled |
| CP2 gold set | `ds-pso-cp02-gold-set-20261110` | `1f3be478` | `CP02-gold-set.md` | **done** — **0.04 role rate** for both models; 14B chosen (same accuracy, 8.6× faster) |
| CP3 labelling | `ds-pso-cp03-labelling-20261110` | `a80c2ddc` | `CP03-labelling.md` | **done** — 1,621 functions/hour, 3090 at 68 %, $0.00/label; labels are leads only |
| CP4 jump state | `ds-pso-cp04-jump-state-20261110` | `b3f1aee0` | `CP04-jump-state.md` | **ready, one window from done** — launch admission, session lifecycle and RAM reads proven on the i9; **both** causes of the dropped presses fixed: the `ddown` alias table in `adapters.py` and the focus-at-delivery hop (new `pso_boot_local.py`, single process). Needs 5 min of operator absence with CPU < 70 % |
| CP6.1 evt container | `ds-pso-cp06-evt-opcodes-20261110` | `e1e61925` | `CP06-evt.md` | **container done** (143/143 byte-identical rebuild); opcodes open — the event system's **object side** now named (event number at object `+0x84`, draw at `+0x38`, four debug-draw helpers); the interpreter itself needs a live breakpoint |
| CP6.2 n.rel geometry | `ds-pso-cp06-nrel-20261110` | `b7201875` | `CP06-nrel.md` | **accept met on the GC file** — byte-identical structural round trip and **12,896 render triangles vs 11,549 collision** (1.12×); vertices not yet interpreted into named points |
| CP7.1 model-walk crash | `ds-pso-cp07-model-walk-20261110` | `05ce01ad` | `CP07-model-walk.md` | **done** — `0x8028f508` is `lfs f0,0x8(r4)` inside `FUN_8028f2a0`; `pso_swapfit` checks the field (11 tests) |
| CP7.2 object loader | `ds-pso-cp07-object-loader-20261110` | `d08f4f09` | `CP07-object-loader.md` | **done** — dispatch by **payload type** through five constructors at `0x8049eee8`; class id gates/registers; coverage 0.512 disc-wide with the hole invariant |
| CP7.3 scene loader | `ds-pso-cp07-scene-loader-20261110` | `503ed538` | `CP07-scene-loader.md` | **done** — `FUN_801fb798` composes `<area>r.rel`/`n.rel` from the floor resolver; `FUN_802066bc` dispatches by magic |
| CP9 save data | `ds-pso-cp09-save-data-20261110` | `02584281` | `CP09-save-data.md` | **mostly done** — real card, reader fixed, `PSO_CHARACTER` block 17/11, storage encoded, **cipher fully transcribed**; only the runtime seed is missing (readable in the CP4 window) |
| CP15 step 4 | `ds-pso-cp15-room-inventory-20261110` | `5cdafed5` | `CP15-room-inventory.md` | **done** — the fifteen lobby sets are **floor 15**; floor 0 has one layout; lobby-walk route retired |

## The live window (one, and it unlocks the most)

Queue the launch when the worker's `idle_seconds >= 300` and CPU < 70 % (a queued launch does not accumulate idle time;
typing to the session resets the timer). Then:

```
python system/tools/pso_boot_local.py --start-at press_start     # raises the window, injects, walks, polls RAM
python system/tools/pso_boot.py save-state                        # Dolphin slot 1
python system/tools/pso_boot.py install-jumpstates <path>         # jumpstates/<gid>-stock.state
```

That completes CP4; the same window also yields CP9's runtime seed (`[*(r13-0x4694)+0x118]`) and enables CP5, CP10, CP16.

## Tests

CP0 baseline on `8032491f`: **45 failed / 1,329 passed / 132 skipped** (Windows i9, Python 3.11; the guide's 45/1,333/133 on
Python 3.12 — same 45 failures). Checkpoint tests are additive and green: CP0 18, CP2 7, CP7.1 11, CP7.2 6, CP6.2 6, CP15 9,
CP9 8, pad aliases 5.

## Needs

- the RE session's review/merge of the fourteen branches above;
- a CP8 data decision (the Dreamcast `.chd` has no extractor on this machine);
- one operator-absent window for CP4/CP5/CP9-seed/CP10/CP16.
