# CP00 clean start — in progress

Session identity: DeepSeek    Branch: ds-pso-cp00-clean-start-20261110    Commits: (this branch)

Goal: all four (unblocks everything else)

Measured:
- i9 plane at claim time: one running session, `83202f53e9cd4aa5-54da9e9d8a764de8` (`pso_guilddoor_moved`,
  `agent_owned: true`); one queued Linux-only `launch_game` `4b176dbab90240cb` from 04:50.
- Stop: cancelled `4b176dbab90240cb` (state now `failed`, "cancelled by the operator"), queued
  `session_op`/`stop_game` for the parked session (job `1e745d692ac14a30`, `state: succeeded`,
  `output.ended: true`), and `/api/sessions?include_ended=false` is now empty.
- Baseline on `8032491f` (Windows i9, Python 3.11): every `system/tests/test_pso*.py` →
  **45 failed, 1,329 passed, 132 skipped** (389.8 s). The guide's baseline at the same commit is 45 / 1,333 / 133 on
  JAYBUILTFINAL (Python 3.12); the 45 failures are the same set of files, the 4 passes / 1 skip are the environment
  difference, recorded rather than hidden.
- Open `ds-pso-*` branches at claim time: 23. No `ds-pso-cp*` branch existed on origin.

Inferred: none yet.

Live: no session needed for CP0; the stop above leaves the i9 with no running game.

GPU: n/a for CP0 (no local model involved).

Credit: see the lane's last recorded figure; no paid API calls this round.

Tests: the baseline above; the per-branch merge-tree results go below as they are rewritten.

Needs: the RE session's merge of the cleaned branches; the operator's answer to `CP00-operator-question.md`.

Next: rewrite every open branch onto `origin/main` with its lane-log text moved into `system/docs/pso-checkpoints/`.
