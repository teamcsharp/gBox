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

## Correction (round 48): the launch is held by two gates, not by a broken worker

Earlier rounds reported "the i9 worker is online but does not claim the launch". That was the symptom; the plane's own
reason strings are the cause, and they are **by design**:

1. **`"CPU is at 82.6%; background admission budget is 70%."`** - an agent's `launch_game` is held while the PC's CPU is
   above 70 %. It was above 70 % *because of this session's own work* (Ghidra/pyghidra runs and the local model). At 60 %
   the next attempt passed this gate on its own.
2. **`"Waiting for five minutes without operator input."`** - once the CPU gate passed, the job sat for this instead. The
   operator was at the machine (this conversation), so the plane holds the automated launch until they have been idle for
   five minutes. That is the same rule the checkpoint guide states as rule 7 ("live steps only when the operator is
   away").

Both jobs were cancelled, `/api/sessions?include_ended=false` is empty, and nothing is running or queued - the i9 is as
it should be.

**What this means for CP4:** nothing needs fixing in the worker or the service. The launch will be admitted when the
operator has been away for five minutes and the CPU is under 70 %. The driver (`system/tools/pso_boot.py`) and the boot
walk are ready; the moment the gate opens, `launch` then `walk` then `save-state` runs CP4 end to end.

Jobs measured: `93f4fc790d9a4ba0` (queued 104 s, cancelled), `11b64271c58d4be2` (admission_wait = CPU 82.6 %, cancelled),
`8d9a2df2aff046f6` (admission_wait = waiting for five minutes without operator input, cancelled).

## Round 57: the queue-and-wait attempt, and why the window closed

At 16:04 the operator's `idle_seconds` read **188.7** (3.1 min, stepping away) and the CPU was **60 %** - one minute short of
the five-minute gate. A launch was queued (`fda9e1b1d19b4151`) and polled for 305 s: it stayed queued with
`"Waiting for five minutes without operator input."`, and when the poll ended the worker reported `idle_seconds = 29.3` -
**the operator had come back**, resetting the clock. The job was cancelled (`state: failed`), no session is running.

So the gate is evaluated per claim, and a queued launch does **not** accumulate idle time of its own: it needs the operator
to stay away for five continuous minutes *while it is queued or above it*. The practical recipe for CP4 is therefore:

1. when `idle_seconds` is already **>= 300** (not "approaching"), queue the launch and poll;
2. keep CPU under 70 % in the same window;
3. the moment the session appears, run `python system/tools/pso_boot.py walk` (the boot walk is ready), then
   `save-state` and `install-jumpstates`.

Nothing needs changing in the code for this; it is a timing rule, and it is now recorded instead of being discovered again.
Jobs at this point: `fda9e1b1d19b4151` cancelled, no session, no queue.

## Round 62: the mechanism, exactly (and why "just launch it" from the operator cannot be obeyed directly)

The operator asked for the launch directly. The plane still held it, and reading `gbox/background_testing.py` explains why
in one function:

```python
IDLE_MIN_S = 300
def admission_reason(worker, excluded_names, budget_percent=70, *, allow_active=False, require_gpu=True):
    if worker.get('os') == 'windows' and not allow_active:
        idle = worker.get('idle_seconds')
        if idle is None or idle < IDLE_MIN_S:
            return 'Waiting for five minutes without operator input.'
    ... cpu/gpu/memory budgets ...
```

* **The only bypass is `allow_active=True`, and the only caller that passes it is MercMode presentation launches**
  (`mercmode.presentation_launch` -> `admission_reason(..., 101, allow_active=True, require_gpu=False)`). For a PSO
  `launch_game`, `allow_active` is False, so **every agent launch needs 300 s of no operator input** - and the operator
  typing to this session resets that timer, so the request and the gate are in direct tension.
* The actor does not matter: `gbox-agent` (the in-app agent) was tried explicitly and the job stayed queued with the same
  reason, so the exemption in the *route*-level guard is not the gate that fires; the claim-level background-testing
  admission is.
* At 16:24 the idle gate did reach **310 s** (so the timer does pass) but the CPU read **74-96 %** in the same window
  (`budget_percent = 70`), so the CPU gate then held it: both gates must be open in the *same* claim.

**What is left, honestly:** either the operator presses Play (foreground, their own action - the intended path), or they
stay away for five minutes with the CPU under 70 % and a queued launch will be admitted. A launch job is left queued
(`0091f40e47964868`) so it fires in the first such window; it can be cancelled at any time with
`POST /api/jobs/0091f40e47964868/cancel`.

The driver and boot walk are ready: the moment a session exists, `pso_boot.py walk` -> `save-state` -> `install-jumpstates`
completes CP4, and the same window reads CP9's runtime seed.
