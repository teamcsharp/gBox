# CP0 evidence: the clean start (2026-11-10 night, the DeepSeek session)

What CP0 asked for (`DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md`): every open `ds-pso-*` branch merging clean, one
registry, no stale queued launch and no parked agent session, the operator question written down, and the PSO test
baseline not worse.

## 1. The branches: all 16 are on `main`

Each branch carried its own CP0 commit (its lane-log text moved to `system/docs/pso-checkpoints/lane/<topic>.md`), so no
branch needed rewriting and none was force-pushed. They were merged into `main` with plain `--no-ff` merge commits
(local `main`, 2026-11-10 18:20-18:40 CDT):

| branch | tip | merge commit |
|---|---|---|
| `ds-pso-steering-tests-20261110` | `596cb9a6` | `453ad9b8` |
| `ds-pso-steer-tests2-20261110` | `29ab722a` | `e6799e85` |
| `ds-pso-floor-map-20261110` | `c6ddeb1b` | `ef225c97` |
| `ds-pso-floor-editor-20261110` | `404dd9b0` | `66198719` |
| `ds-pso-class-registry-20261110` | `c68e3487` | `cfaaaa54` |
| `ds-pso-editor-page-20261110` | `7aa11623` | `34f064f3` |
| `ds-pso-travel-gate-20261110` | `21b0c1bf` | `a84d69ee` |
| `ds-pso-vtables-20261110` | `2171b625` | `c0b6edaf` |
| `ds-pso-vtable-census-20261110` | `9ef79647` | `6182d740` |
| `ds-pso-sda-20261110` | `4f9ec3e7` | `bdd6851c` |
| `ds-pso-memcard-20261110` | `3b563b23` | `0219216c` |
| `ds-pso-floor-warp-20261110` | `0442a9fe` | `2be18b5e` |
| `ds-pso-actor-dump-20261110` | `3eca417a` | `998024f3` |
| `ds-pso-gvr-write-20261110` | `1a652cf2` | `7e3be8e4` |
| `ds-pso-tree-endian-20261110` | `793e74b1` | `8852d9eb` |
| `ds-pso-body-platform-20261110` | `71cecb67` | `97f590fb` |

`git merge-tree --write-tree main <branch>` exited 0 for all 16 before the merges (checked with git 2.38.1).

### The conflicts that did appear, and how they were resolved

Four merges hit textual conflicts; all were in the shared research docs, plus one duplicated module and its test:

- `docs/research/pso-gc-executable.md` (4 times): the branches were written at different times, so some carried the
  older "the floor resolver is not mapped yet" text while `main` already had it decoded. Rule: **keep the newer decoded
  text**; where two different new sections landed at the same anchor (5b the small-data areas, 5c the vtable census)
  keep **both**. All rewrites are UTF-8 clean (checked: no mojibake).
- `docs/research/pso-travel-and-gate.md` (add/add): `main` had the travel-gate text, the vtables branch added a new
  section; both kept.
- `gbox/pso_class_registry.py` and `tests/test_pso_class_registry.py` (add/add): the later branch's copy is the earlier
  one plus the vtable census (verified by diff: 202 -> 223 lines, and the test file adds 60 lines); took the superset,
  then restored the editor's `FAMILIES`/`family` block that the vtable-census copy predated (`pso_editor.placements`
  needs it) and fixed `pso_editor._mark_for`'s stale `CLASS_NAMES.get` (the merged registry exposes `name()`).

## 2. One registry, cross-checked

`gbox/pso_classes.py` stays the module: the self-calibrating reader (it finds the table from the `TObjCityDoor_Shop`
anchor). `gbox/pso_class_registry.py` stays the pinned table (address `0x805D3138`, 240 slots, 148 named, the vtable
census, the family grouping). CP0's cross-check is `tests/test_pso_registries_agree.py`: both sides agree on the anchor
name and slot (`0x46`), the pinned list is the measured 240/148, and both mask a placement kind to the same class.

## 3. The plane: no stale queued launch, no parked agent session

- The stale `launch_game` `4b176dbab90240cb` the checkpoint named is **failed**, not queued (`GET /api/jobs/4b176dbab90240cb`
  on the i9 plane, 2026-11-10 18:22 CDT: `state: failed`, `worker_id: null`). Nothing to cancel.
- The agent-owned PSO session (`83202f53e9cd4aa5-2db839b720154c70`) was **playing** (started 18:14 CDT) when the
  check-in ran, and the local model was gated on the operator playing, so it was left alone: stopping a live session is
  not CP0's to do.

## 4. Tests

The CP0 command: every `system/tests/test_pso*.py` plus `test_pad_bind.py`, on Python 3.11 (this checkout), 2026-11-10
18:40-18:55 CDT, 115 files.

| tree | failed | passed | skipped |
|---|---|---|---|
| baseline `8032491f` (13:35) | 45 | 1,333 | 133 |
| `main` with all 16 branches merged | 41 | 1,399 | 132 |
| the 14 files above, after the two merge fixes (56 s) | **36** | 157 | 9 |

The 41 were the baseline's own files (margin_controller 13, combat_routing 4, field_margin 3, lifecycle 3,
reload_admission 3, coop_setup 2, equipment_hooks 2, runtime_repair 2, combat_range 1, enemy 1, planner_transport 1,
recorded_evidence 1 - 36) **plus** 5 merge regressions the fixes above remove (test_pso_editor 4, test_pso_offset 1).
Re-running those 14 files after the fixes gives **36 failed / 157 passed / 9 skipped**: exactly the baseline's 36 (the
45 less the 9 the two test branches fix), no new failure. `test_pso_steer.py` (5) and `test_pso_steering_evidence.py`
(4) are green now, which is the two test branches doing what their commits said.

## 5. What is still open in CP0

- **The operator question** is written in `CP00-operator-question.md` and asked in the session (2026-11-10 night). P1's
  lobby route waits on it.
- CP1 (the local coder model on the 3090) is still unstarted: `ollama.available = false`, and the 3090 has only Dolphin
  on it. That is the next checkpoint.

## CP4+ branches (added after this evidence was written)

The lane kept publishing `ds-pso-*` branches after the 16 above. CP1-3's were merged the same night (see the hand-off
log): `ds-pso-cp01-local-model-20261110`, `ds-pso-cp02-gold-set-20261110`, `ds-pso-cp03-labelling-20261110` - all
three merged clean, and with them `system/docs/pso-checkpoints/CP01-local-model.md`, `CP02-gold-set.md`,
`CP03-labelling.md`, `gbox/pso_llm.py` (+ `tests/test_pso_llm.py`, 7 passed) and the export/label tools.

At the 2026-11-10 19:15 check, **26 more `ds-pso-*` branches were open** (cp04 jump state, cp06 evt/nrel, cp07
model/object/scene loaders, cp08 room pieces, cp09 save data, cp10 Forest 1, cp11 editor page, cp12 rigged swap, cp13
library donors, cp15 room inventory, cp16 stick, cp17 walk graph, body-swap, classes-family, swap-gc, swapfit-ui,
editor-page2, cp-status, handover, reconcile, cp00-classes/clean-start). They are the lane's CP4+ work and are reviewed
and merged as each checkpoint's evidence lands; none was force-pushed.
