# CP00 clean start — done (steps 1-5)

Session identity: DeepSeek    Branch: ds-pso-cp00-clean-start-20261110    Commits: `6a44d458` + this evidence update

Goal: all four (unblocks everything else)

## Steps 1-2: the i9 plane (done, measured)

- One running session at claim time: `83202f53e9cd4aa5-54da9e9d8a764de8` (`pso_guilddoor_moved`, `agent_owned: true`,
  up since 12:55 — the one CP0 names).
- Stop: `POST /api/jobs` `session_op`/`stop_game` → job `1e745d692ac14a30`, `state: succeeded`, `output.ended: true`,
  teardown 0.469 s. `/api/sessions?include_ended=false` is now **empty**.
- Stale queued job `4b176dbab90240cb` (`launch_game`, `require_os: linux`, from 04:50): cancelled →
  `state: failed`, error "cancelled by the operator". `/api/jobs` shows no queued Linux job.
- Every call carried `x-gbox-actor: agent` and the token from `system/gbox-data/api_token` (never printed).

## Step 3: every open `ds-pso-*` branch merges clean (done, measured)

23 branches rebased onto `origin/main` (`8032491f`), each branch's lane-log text moved to
`system/docs/pso-checkpoints/lane/<topic>.md`, its edit to `system/docs/ds-pso-lane-2026-11-10.md` dropped, and the
branch force-pushed with `--force-with-lease` (**none was merged**, checked with `git branch -r --merged origin/main`
first).

`git merge-tree --write-tree origin/main origin/<branch>` exits **0 for 24/24** (the 23 open branches plus this
checkpoint's own branch):

| branch | tip after the rewrite |
|---|---|
| `ds-pso-actor-dump-20261110` | `3eca417a` |
| `ds-pso-body-platform-20261110` | `71cecb67` |
| `ds-pso-body-swap-20261110` | `c7374eea` |
| `ds-pso-class-registry-20261110` | `c68e3487` |
| `ds-pso-classes-family-20261110` | `9fa927cf` |
| `ds-pso-cp00-clean-start-20261110` | `6a44d458` |
| `ds-pso-editor-page-20261110` | `7aa11623` |
| `ds-pso-editor-page2-20261110` | `814a229f` |
| `ds-pso-floor-editor-20261110` | `404dd9b0` |
| `ds-pso-floor-map-20261110` | `c6ddeb1b` |
| `ds-pso-floor-warp-20261110` | `0442a9fe` |
| `ds-pso-gvr-write-20261110` | `1a652cf2` |
| `ds-pso-handover-20261110` | `e09df930` |
| `ds-pso-memcard-20261110` | `3b563b23` |
| `ds-pso-reconcile-20261110` | `5f8f0e12` |
| `ds-pso-sda-20261110` | `4f9ec3e7` |
| `ds-pso-steering-tests-20261110` | `596cb9a6` |
| `ds-pso-steer-tests2-20261110` | `29ab722a` |
| `ds-pso-swapfit-ui-20261110` | `740c6041` |
| `ds-pso-swap-gc-20261110` | `de29ab4e` |
| `ds-pso-travel-gate-20261110` | `21b0c1bf` |
| `ds-pso-tree-endian-20261110` | `793e74b1` |
| `ds-pso-vtable-census-20261110` | `9ef79647` |
| `ds-pso-vtables-20261110` | `2171b625` |

One branch needed a **code** conflict resolved rather than being left: `ds-pso-floor-editor-20261110` conflicted on
`system/tests/test_pso_editor.py` because main had added three `ascii_map` tests at the same place the branch added its
floor tests. Both sides are kept (29 lines from main, 21 from the branch); the rebased branch runs
`test_pso_editor.py` + `test_pso_floor_map.py` green (**25 passed**). Everything else rebased with only lane-log replays,
resolved by taking main's version of that file.

## Step 5: the operator question (done)

`system/docs/pso-checkpoints/CP00-operator-question.md`, and the RE session has been told it is waiting.

## Step 4: the duplicate registry (done)

`ds-pso-cp00-classes-20261110` @ `a1053cac`, evidence `CP00-classes.md`: `pso_classes.py` stays the module (anchor-derived
lookup, plus `family`, `label`, the vtable census and the real section-table mapping) and now carries the branch's
`PINNED_ADDRESS = 0x805D3138` / `PINNED_NAMES` (240 slots, **148 named**) as cross-check data; the derived table equals
the pinned list on every one of the 240 slots. `pso_class_registry.py` is not added (it never was on main) and nothing
imports it. Both test sets live on: `test_pso_classes.py` 12 and the ported `test_pso_class_registry.py` 6 — **18
passed**, 47 with the editor/setdata/offset suites.

## Baseline (measured, so every checkpoint can be compared)

Every `system/tests/test_pso*.py` on `8032491f`, Windows i9, Python 3.11:
**45 failed, 1,329 passed, 132 skipped** (389.8 s). The guide's baseline at the same commit is 45 / 1,333 / 133 on
JAYBUILTFINAL (Python 3.12) — the same 45 failures, the difference is the environment (4 passes, 1 skip), recorded
rather than hidden.

## Needs

- the RE session's review/merge of the 23 cleaned branches;
- the operator's answer recorded above.

Next: CP1 (the local coder model on the 3090) once a live window is allowed.
