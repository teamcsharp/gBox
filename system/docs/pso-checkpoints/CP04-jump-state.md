# CP04 jump state — blocked (the i9's worker does not claim `launch_game`; nothing was left running)

Session identity: DeepSeek    Branch: ds-pso-cp04-jump-state-20261110    Commits: this branch
Goal: 2, 3, 4

## What was built (usable next time)

`system/tools/pso_boot.py` - the driver CP4 was missing (nothing in the tree bound `pso_boot_walk` to the plane):

* `Plane`: token from `system/gbox-data/api_token`, `x-gbox-actor: agent` on every call; sessions, catalog, rpc
  (`read_memory {address,length}`), input (`{"events":[{"key":..,"frames":..}]}`), jobs, wait;
* `Reader`: `.u8/.u16/.u32/.f32/bytes` over `read_memory`, which is the interface `pso_boot_walk.state(reader)` and
  `pso_ram` expect;
* commands: `launch`, `walk` (the MULTI MODE press script with RAM checkpoints), `state`, `save-state`,
  `install-jumpstates`, `launch-jump`, `stop`.

Smoke-tested against the live plane: auth accepted, `/api/sessions` returns 0 sessions, `/api/catalog/<gid>` returns the
PSO entry, and the input/rpc body shapes are the ones `server.py` expects.

## Why it is blocked

The launch never reached the i9, in two different ways, both measured:

1. **`POST /api/games/<gid>/launch?node=i9-NUC&debug=true` queues for linux.** The route treats `debug=true` as "the
   Spark's full debugger" and sets `require_os: linux` (job `cde17ce652c14f31`). That is exactly the wrong-PC class of
   launch the hard rules forbid, so it was **cancelled immediately** (`state: failed`).
2. **`node=i9-NUC&debug=false` resolves to the right worker but is never claimed.** Job `0e2469727c204653` came back
   with `require_worker: 83202f53e9cd4aa5` (`i9-NUC`, `os: windows`, `online: true`, `last_seen` seconds old) - and the
   job stayed `queued` for over two minutes while the worker reported no `current_job`. It was cancelled
   (`state: failed`), so nothing is running.

Earlier in this session the same worker claimed a `session_op` job within seconds (the stop of the parked session,
`1e745d692ac14a30`), so the claim loop is alive for `session_op` but not taking `launch_game`. That points at the
worker's launch gate (e.g. its local build/provision state) rather than at the plane.

## State of the i9 now

- no running sessions (`/api/sessions?include_ended=false` is empty);
- no queued jobs (the two mismatched launches and the stale morning job are all `failed`);
- nothing was launched, so no menu was left open and no window was moved.

## Needs (RE session)

- the i9 worker's `launch_game` claim path: why a `require_worker` job for an online Windows worker stays queued. That is
  a `gbox.service`-side question, which this session must not restart (hand-off rule).
- once it claims, `python system/tools/pso_boot.py launch` then `walk` does CP4's steps 1-2; `save-state` and
  `install-jumpstates` do 3-4.

## Per CP4's "if blocked"

CP4 says: if this fails, record the error and do CP6-CP9 offline - they need no session. That is the plan for the next
rounds: CP6 (the remaining P2 formats, starting with the `.evt` opcodes) and CP9's offline half (the `CARD*` callers that
CP03 already exported).

Tests: none changed (tool only). CP0 baseline unchanged: 45 failed / 1,329 passed / 132 skipped.

Next: CP6 offline (the `.evt` interpreter/opcodes) while the launch path is the RE session's to unblock.
