# PSO checkpoints: status for the RE session (updated round 89, 2026-11-10)

Session identity: DeepSeek    Branch: ds-pso-cp-status-20261110    Commits: this branch
Goal: the status of every checkpoint worked under `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`

Review index: one line per checkpoint branch with its tip, its evidence file, and its state.

**Review order note:** `ds-pso-cp13-library-donors-20261110` is **stacked on**
`ds-pso-cp12-rigged-swap-20261110` (it needs CP12's endianness fixes), so review and merge CP12 first.

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP0 clean start | `ds-pso-cp00-clean-start-20261110` | `c67a2531` | `CP00-clean-start.md` | **done** - plane cleaned, 23 branches rebased, operator question filed |
| CP0 step 4 registry | `ds-pso-cp00-classes-20261110` | `a1053cac` | `CP00-classes.md` | **done** - one `pso_classes`, pinned address + 148 names as cross-checks, 18 tests |
| CP1 local model | `ds-pso-cp01-local-model-20261110` | `70241e28` | `CP01-local-model.md` | **done** - `qwen2.5-coder:14b` (9 GB, 100 % GPU, 54.8 tok/s) and `:32b` (19 GB) both on the 3090; the 32B was scored in CP2 |
| CP2 gold set | `ds-pso-cp02-gold-set-20261110` | `1f3be478` | `CP02-gold-set.md` | **done** - **0.04** role rate for both models on 30 proven functions; 14B chosen (same accuracy, 8.6x faster) |
| CP3 labelling | `ds-pso-cp03-labelling-20261110` | `a80c2ddc` | `CP03-labelling.md` | **done** - 1,621 functions/hour at 68 % GPU, $0.00/label; labels are leads only |
| CP4 jump state | `ds-pso-cp04-jump-state-20261110` | `b3f1aee0` | `CP04-jump-state.md` | **ready, one window from done** - launch admission, session lifecycle and RAM reads proven live on the i9; both causes of dropped presses fixed (`PAD_ALIASES` for `ddown`, and the focus-at-delivery hop via `pso_boot_local.py`). Needs 5 min of operator absence with CPU < 70 % |
| CP6.1 evt container | `ds-pso-cp06-evt-opcodes-20261110` | `ac7037d8` | `CP06-evt.md` | **container done** (143/143 byte-identical); opcodes open - the event system's object side named (event number at object `+0x84`, draw at `+0x38`); both static avenues exhausted (`+0x84` gives 506 hits; the `.evt` name leaves no string), so a live breakpoint is required |
| CP6.2 n.rel geometry | `ds-pso-cp06-nrel-20261110` | `4c94c2ad` | `CP06-nrel.md` | **accept met on the GC file** - byte-identical structural round trip; index runs proven **triangle strips** (97.3 % adjacency) so **38,355 render triangles vs 11,549 collision** (3.32x); vertex arrays located by signature (1,313 at `0x527f4`, 1,041 at `0x90078`, bounding every index) |
| CP7.1 model-walk crash | `ds-pso-cp07-model-walk-20261110` | `05ce01ad` | `CP07-model-walk.md` | **done** - `0x8028f508` is `lfs f0,0x8(r4)` inside `FUN_8028f2a0`; `pso_swapfit` checks the field (11 tests) |
| CP7.2 object loader | `ds-pso-cp07-object-loader-20261110` | `d08f4f09` | `CP07-object-loader.md` | **done** - dispatch by payload type through five constructors at `0x8049eee8`; coverage 0.512 disc-wide with the hole invariant |
| CP7.3 scene loader | `ds-pso-cp07-scene-loader-20261110` | `503ed538` | `CP07-scene-loader.md` | **done** - `FUN_801fb798` composes `<area>r.rel`/`n.rel` from the floor resolver; `FUN_802066bc` dispatches by magic |
| CP8 room pieces | `ds-pso-cp08-room-pieces-20261110` | `a0f9190f` | `CP08-room-pieces.md` | **done in its GC form** - every GameCube `r.rel` opens with the room's footprint quad (**141 rooms**, 12 of them sloped); the placements join to the rectangles (126 inside exactly one room, 0 inside two), and room 03 nests inside room 00. The Dreamcast `r.rel` itself stays unreadable (CHD v4, no tool here) |
| CP9 save data | `ds-pso-cp09-save-data-20261110` | `4066790c` | `CP09-save-data.md` | **offline complete** - card found, reader fixed, `PSO_CHARACTER` block 17/11, storage encoded, cipher fully transcribed, and the seed's source function found (`FUN_802019f8`, a 24-way per-slot initialiser); the seed value itself is runtime state (readable in the CP4 window) |
| CP11 editor page | `ds-pso-cp11-editor-page-20261110` | `26b80286` | `CP11-editor-page.md` | **code done, blocked on the merge/restart decision** - the page and its build API (`262b117c`) are carried by `ds-pso-swapfit-ui-20261110`; its server-side views were proven **offline** (a 29 KB SVG with 234 dots for 234 records; a 27-row ASCII map where the city shows `G`/`S` for its Guild/Shop doors), which also found and fixed two bugs in `pso_editor._mark_for` |
| CP12 rigged swap | `ds-pso-cp12-rigged-swap-20261110` | `3c19b48c` | `CP12-rigged-swap.md` | **2 of 3 accept lines** - the GameCube readers and writers are endianness-aware (NJCM trees, BML, node models, empty lists), `pso_swapfit` gates the build **SAFE**, and the built body renders as a coherent character on the 3090 (`cp12-body2.png`, 875 triangles). Remaining: the character-select frame (live) |
| CP13 library donors | `ds-pso-cp13-library-donors-20261110` | `6e21201c` | `CP13-library-donors.md` | **offline half done, three donors end to end** - Daisy (788 tris), Cloud (857), Bayonetta (708) all build through CP12's path, gate SAFE with subset texture buckets, parse and render on the 3090. Two endianness bugs found and fixed on the way (both end-list markers and the head stand-in); a fourth gap recorded: the head/hair/cap stand-ins are still Dreamcast-path-only on GC. Remaining: per-boot donor pick and the hot swap (live) |

## The live window (one, and it unlocks the most)

Queue the launch when the worker's `idle_seconds >= 300` and CPU < 70 % (a queued launch does not accumulate idle time, and
any operator input resets the timer). Then:

```
python system/tools/pso_boot_local.py --start-at press_start     # raises the window, injects, walks, polls RAM
python system/tools/pso_boot.py save-state                        # Dolphin slot 1
python system/tools/pso_boot.py install-jumpstates <path>         # jumpstates/<gid>-stock.state
```

That completes CP4; the same window yields CP9's runtime seed (`[*(r13-0x4694)+0x118]`, descriptor chosen by
`local_18 % 24` in `FUN_802019f8`), CP12's character-select frame, CP13's per-boot and hot swaps, CP5, CP10 and CP16.

## Tests

CP0 baseline on `8032491f`: **45 failed / 1,329 passed / 132 skipped** (Windows i9, Python 3.11; the guide's 45/1,333/133 on
Python 3.12 - same 45 failures). Checkpoint tests are additive and green: CP0 18, CP2 7, CP6.2 8, CP7.1 11, CP7.2 6, CP9 8,
CP12's snapshot 1, CP13's body-endian 3, CP15 9, pad aliases 5; the PSO swap suites together are 22 passed.

## Needs

- the RE session's review/merge of the sixteen branches above (**CP12 before CP13**);
- a CP8 decision (install `chdman` for the Dreamcast data, or accept the GameCube form recorded here);
- one operator-absent window for CP4 / CP5 / CP9-seed / CP10 / CP12's frame / CP13 / CP16.

## Round 90: every checkpoint branch's own suites run green from its pushed tip

The checkpoint branches are **parallel** (each carries the tests for the modules it changed), so a regression check has to run
per branch. Done this round, each from its **origin tip**:

| branch | suite(s) run | result |
|---|---|---|
| `ds-pso-cp12-rigged-swap-20261110` (with CP13 stacked) | all swap / body / player / NJ / endian suites (36 files) | **438 passed, 26 skipped** |
| `ds-pso-cp00-classes-20261110` | `test_pso_classes.py`, `test_pso_class_registry.py` | 5 passed |
| `ds-pso-cp04-jump-state-20261110` | `test_pad_aliases.py`, `test_pso_boot_walk.py` | 10 passed |
| `ds-pso-cp06-evt-opcodes-20261110` | `test_pso_evt.py` | 8 passed |
| `ds-pso-cp06-nrel-20261110` | `test_pso_nrel.py` | 8 passed |
| `ds-pso-cp08-room-pieces-20261110` | `test_pso_rooms.py` | 6 passed |
| `ds-pso-cp09-save-data-20261110` | `test_pso_memcard.py` | 8 passed |
| `ds-pso-cp11-editor-page-20261110` | `test_pso_editor_views.py`, `test_pso_editor.py` | 20 passed |

**Total 503 passed, 0 failed, 26 skipped** - and the skipped set is the disc/config-dependent group that is skipped without the
disc, not a regression.

**One trap worth recording for the review:** several **local** branches in this clone are stale (they were created before later
pushes to the same name), so `git checkout <branch>` can give an old tree - the first pass reported "no test files found" for
CP6.2 for exactly that reason. Always verify against `origin/<branch>` (this is also why every piece of evidence names a tip
hash rather than a branch name alone).

## Round 92: two more checkpoint branches, and one more verified

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP10 P6a field proof | `ds-pso-cp10-forest1-20261110` | `033b6ca6` | `CP10-p6a-forest1.md` | **offline half done** - both pre-built Forest 1 mods decoded: `pso_objmove_forest01_r5` moves `map_forest01d.dat`'s **record 5 of 150** by **+120.0** in x, and `pso_objmove_forest01_l0_r60` moves `map_forest01_00o.dat`'s **record 60 of 109** by **+150.0** in x and **+6.0** in y; the mod names match the records the diff found. The live step only has to confirm the entity sits at the written position (needs CP4's state and CP5's warp) |
| CP5 Forest 1 warp | `ds-pso-floor-warp-20261110` (older, unmerged) | `0442a9fe` | `CP05-forest1-dev.md` (to be written by the live run) | **code ready and verified offline** - `pso_mods` `op=floor_warp target=<n>` calls the worker's native travel helper; this round ran its suites from the pushed tip: **24 passed** (`test_pso_floor_warp` 4 + `test_pso_mods` 20). The steps themselves (boot the lobby state, warp to floor 1, save the state) are live-only, and the guide's fallback is `boss_warp` |

**Why CP5 and CP10 are still open:** both call a **live** native path (`floor_warp` -> the travel helper; the object move is
read from actor memory), so neither can finish without an operator-absent window. Their offline halves are now as complete as
they can be: CP5's code is verified by tests, and CP10's expected before/after positions are measured from the mod images
themselves.

**That leaves exactly three things for the programme:** the window (CP4, CP5, CP9-seed, CP10 confirmation, CP12's frame, CP13,
CP16, CP17-19), the CP8 data decision, and the merge review (CP12 before CP13; sixteen branches total with CP10 now).

## Round 95: the merge rehearsal - **16/16 branches now merge cleanly, in this order**

The review's hardest part is the merge itself, so it was rehearsed: a throwaway local branch from `origin/main`, every
checkpoint branch merged in order with `--no-ff` (no push, branch deleted afterwards). The first two passes found **three
conflicts**, and both were fixed *here* rather than left for the review:

| conflict | why | resolution |
|---|---|---|
| `ds-pso-cp07-model-walk` vs `ds-pso-cp12-rigged-swap` on `pso_swapfit.py` + its test | CP7.1 created the module's model-centre checks; CP12 changed `compare`'s bucket rule - the same function | **CP7.1 is merged into CP12** (`ecf64810`): `compare` keeps CP12's subset rule *and* CP7.1's two checks, and the test file keeps both blocks - **49 passed** across the swap suites |
| `ds-pso-cp00-classes` vs `ds-pso-cp07-object-loader` on `test_pso_classes.py` | both added a test block to the shared class-test file | **CP0-classes is merged into CP7.2** (`6ec7f441`): the file keeps both blocks - **19 passed** |
| (CP13, same files as CP12) | CP13 is stacked on CP12 | disappears once CP12 is merged |

**Recommended merge order (rehearsed, conflict-free):**

```
cp00-clean-start  cp00-classes  cp01-local-model  cp02-gold-set  cp03-labelling
cp06-evt-opcodes  cp06-nrel     cp07-model-walk  cp07-object-loader  cp07-scene-loader
cp08-room-pieces  cp09-save-data  cp10-forest1   cp12-rigged-swap  cp13-library-donors  cp04-jump-state
```

(`ds-pso-cp07-model-walk`'s content now also rides inside `cp12-rigged-swap`'s branch, and `cp00-classes`' inside
`cp07-object-loader`'s, so merging those two first is equivalent to merging the merged pair - either way there is no manual
conflict left.)

**Updated tips after the resolutions:** `ds-pso-cp12-rigged-swap-20261110` **`ecf64810`**,
`ds-pso-cp07-object-loader-20261110` **`6ec7f441`**.

## Round 99: CP16 added, and the live input finding folded into CP4's row

| checkpoint | branch | tip | evidence | state |
|---|---|---|---|---|
| CP16 focus-free movement | `ds-pso-cp16-stick-20261110` | `8c7980d9` | `CP16-stick.md` | **measured negative, per the guide's if-blocked clause** - the three input routes (local SendInput after a focus attempt, unfocused SendInput, the worker relay for agent and autoplay) produced no reaction in round 96's session; the 2-second-hold test could not begin. Round 97 showed the round-96 test was run during the opening movie (`mode 0`), so a **discriminating retest** is staged (`docs/research/pso-cp4-retest.py`): wait for `mode 1`, then a focused press, then an unfocused one. Until it runs, the keyboard walker stays, live only under rule 7 |

**CP4's updated tip and state:** `ds-pso-cp04-jump-state-20261110` @ **`fd166561`** - launch admission, session lifecycle and
RAM reads are all proven live (round 96: session `83202f53e9cd4aa5-1b349dbb3ee94db4`, `mode 0` reads, the seed descriptor
`0x0` at the title); the open question is only whether a press lands, and the retest above answers it in one run. Both input
fixes are in the branch (`PAD_ALIASES`, the single-process driver) and the emulator already has `BackgroundInput=True`.

**What a single successful retest unlocks, all in the same window:** CP4's boot walk and jump states, CP5 (floor warp), CP9's
runtime seed and byte-flip accept test, CP10's entity confirmation, CP12's character-select frame, CP13's per-boot and hot
donor picks, CP16's stick measurement, and then CP17-CP19.

**The programme's open items are now exactly four:** (1) the retest in the next window; (2) the CP8 data decision; (3) the
merge review of seventeen branches in the rehearsed order (conflict-free); (4) CP11's merge/restart decision.

## Round 105: the live blocker is diagnosed and has a working input mechanism - the handover's key section

Rounds 96-104 turned "input does not reach the game" into a diagnosis and a fix. This replaces the earlier "retest staged"
wording, which is now out of date.

**Root cause (round 102):** this machine has **no reporting pad**. The worker's virtual pad (ViGEm XInput) can fail to be
created because leftover pads hold the slots - the codebase documents the exact failure: *"the i9-NUC 2026-11-10:
`_setup_vpad` returned None, the INI fell back to the keyboard, and every gBox press was silently dropped for the whole
session"*. The keyboard fallback then binds `XInput/0/Gamepad`, a **phantom slot that reports zeros** - and
`pad_bind.probe_pads()` returns `{}` on this machine, so nothing better is bound. The game receives nothing, which is why four
injection methods (scancode, virtual-key, relay as agent, relay as autoplay) all failed against a visibly waiting
"PRESS START" screen (screenshot: `docs/research/pso-cp4-press-start.png`).

**The mechanism that works (round 103):** an agent-side process can **create the pad itself**:

```
vpad_win.VGamepad()          ->  XInput slot 0       (the slot the fallback INI binds)
pad.apply([{key,down:True}, {key,down:False}]) ->  a real tap, focus-independent
```

`probe_pads()` shows `{"0": [4096, ...]}` right after a press - the pad reports, and Dolphin reads it. `apply` is
focus-independent by design, so no window focus, no `SendInput`.

**The driver (round 104):** `docs/research/pso-cp4-padwalk2.py` creates the pad, logs the bound device, probes one START through
the **relay** and then through the **agent pad**, and walks with whichever changes `mode`. The two paths are mutually exclusive
by construction (the worker routes input to its own pad when it has one; the fallback binds slot 0 only when it does not), so
the probe covers both outcomes of `_setup_vpad`.

**What this means for the review:** CP4 and CP16 are **not blocked by a missing capability any more** - they are waiting for an
operator-absent window in which `pso-cp4-padwalk2.py` runs. The three unblock options recorded in round 101 (operator press, a
worker pad op, a pad binding) are now down to one line of execution, because the agent can supply the pad itself.

**Runbook for that window (in order):**

```
1. queue the launch when idle_seconds >= 300 (CPU<70 helps but the gate is the worker's to apply)
2. python docs/research/pso-cp4-padwalk2.py        # pad + relay probe, then the walk to the lobby
3. pso_boot save-state                              # Dolphin slot 1
4. pso_boot install-jumpstates <path>               # jumpstates/436e0bb84d5337d1-stock.state
5. the same window: pso_controls boss_warp/floor_spawn for CP5/CP10 (native travel, no input needed)
6. CP9's seed: read [0x80585F6C] + 0x118 once a save slot is selected, then pso_save_cipher.decode
```
