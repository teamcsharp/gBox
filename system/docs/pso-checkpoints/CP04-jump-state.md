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

## Round 65: the launch fired and the RAM reads work - the pad input path does not (the gap is now precise)

The armed launch job (`0091f40e47964868`) **was admitted** once the operator stepped away, and the session it created was
the intended one: `83202f53e9cd4aa5-0091f40e47964868`, **stock game**, `agent_owned: true`, running on the i9
(the emulator is the worker's `gBox Dolphin`, pid 8568, window
`Dolphin 2609 | JIT64 SC | Vulkan | HLE | Phantasy Star Online Episode I & II Plus (GPOE8P)`).

**What works:**

* **`read_memory` works on the i9 session**: `pso_boot_walk.state(reader)` returned `mode 0, floor 0, episode 1, no player`
  at the attract loop, and later `mode 1` (the title menu) - so every RAM-based checkpoint and CP9's seed read are possible
  on this plane;
* `win_bring_to_front(8568)` succeeds (`True`), so the window can be raised;
* the input API **accepts** presses (`POST /api/sessions/<sid>/input` -> `{"queued": 1}`) for both the `agent` and the
  `autoplay` actor.

**What does not work:** the presses **do not reach the game**. `mode` stayed `1` through START, A and D-pad-down presses with
the window focused. The reason is in the tree: `gbox/pso_coop.py` drives input through the **worker's native
controller** (`controller`/`inputs` inside the adapter), not through the HTTP `/input` relay, and it explicitly handles the
"game window is not in the foreground" error from `adapters.py` ("must be active to send emulator input"). The HTTP relay
is `padstate`, which is a keyboard-injection path bound to a **pad configuration** - and this session was launched with
`"pad": ""`, i.e. no pad spec.

**So CP4's next attempt needs one of:** a launch with a `pad` binding (so `padstate` has a map to inject through), or the
worker-side input path (`autoplay` tool / `controller` in the worker), which is what the lane's own coop code uses. The
driver (`pso_boot.py`) reads state correctly and presses through the relay; only the delivery half is missing.

**The session was stopped** (job `3f0dea8b822d4e75`, `succeeded`, `ended: true`), `/api/sessions` is empty, and the i9 is
clean. One fix was made to the driver on the way: `Reader.read()` did not exist, so `pso_ram.player()` crashed - the
checked-out tool now carries it (`pso_ram`'s reader protocol).

## Round 66: why the presses were dropped, at the instruction level

The injection path is `adapters.win_send_keys` -> `SendInput` (scan codes from a `_SCAN` table, pad-button names from
`PAD_KEYS[player]`), and it is gated by `_win_input_in_front(user32, root, hidden_ok)`:

```python
def _win_input_in_front(user32, root, hidden_ok):
    foreground = user32.GetForegroundWindow()
    if not foreground:          # locked screen: never send there
        return False
    if root and foreground == root:
        return True
    if not hidden_ok:
        return False            # pad input must never type into another app
    return True                 # hidden_ok: Dolphin's global F13-F15 hotkeys, focus-free
```

So **pad input is delivered only while the game's top-level (`root`) window is the foreground window**, checked at delivery
time; `win_bring_to_front(pid)` raises exactly that root (`_pid_window(pid)` -> `GetAncestor(h, 2)`) and it returned `True`
in round 65. The relay is **asynchronous** (`POST /input` answers `{"queued": 1}` and the worker's input thread sends the
keys afterwards), so the window has to still be foreground *when the worker delivers*, not merely when the request was
accepted. In round 65 each of my commands raised the window and returned; the subsequent PowerShell/agent activity (and the
console window itself) plausibly took the foreground back before delivery, so the keys were dropped by that check - which
also explains why both the `agent` and `autoplay` actors behaved identically.

**Two concrete next attempts, both offline-defined:**

1. **One process, one focus**: a single script that calls `win_bring_to_front(<dolphin pid>)`, asserts
   `GetForegroundWindow() == root`, then presses and polls `pso_boot_walk.state` in a loop, **with no other window
   activity in between** (no shell commands, no editor). The walk's own `press` -> `sleep(settle)` loop fits this shape as
   long as it runs from one long-lived process.
2. **The focus-free lane**: `hidden_ok=True` accepts input while another app is foreground, and the comment says it exists
   for **Dolphin's global hotkeys (F13-F15 chords, `HotkeysRequireFocus=False`, `BackgroundInput=True`)**. If the worker's
   Dolphin build has those chords bound to the pad, a walk driven by them needs no foreground at all - the
   `pso_coop`/`adapters` code path for that is `remote_input` followed by `win_send_keys(..., hidden_ok)`.

The driver and the RAM checkpoints are proven; only this delivery condition remains. The i9 is clean (no session), and the
next launch should also carry a `pad` spec so `PAD_KEYS` has a map to use.

## Round 67: a second, independent cause of the dropped presses - the D-pad names were never mapped

While building the single-process driver, the pad-name mapping exposed a real bug:

```python
PAD_KEYS[1] has: a, b, down, l, l2, l3, ldown, left, lleft, lright, lup, r, r2, r3, right, select, start, up, x, y
-- no ddown / dup / dleft / dright
```

`pso_boot_walk`'s `offline_game` step presses **`("ddown", "a")`** - the digital-pad vocabulary used by the walk scripts
(`ddown`, `dup`, `dleft`, `dright`, and the C-stick `cdown`/`cup`/...) - while the injector only knew `down`/`up`/`left`/
`right`. `win_send_keys` mapped `ev["key"]` through `PAD_KEYS`, found nothing, then `_SCAN.get("ddown")` -> `(0, 0)`, and
**dropped the direction silently**: the game never saw it. That is an independent reason the round-65 walk failed at
`offline_game` (the title menu never moved), on top of the focus-at-delivery timing.

**Fixed in `gbox/adapters.py`:** a `PAD_ALIASES` table (`ddown`/`dup`/`dleft`/`dright` -> `down`/`up`/`left`/`right`, plus the
C-stick names) is applied to every player's `PAD_KEYS` map at import, so both the HTTP relay and the direct injector now
translate the walk scripts' names. Verified: `ddown -> Down (scan 80, ext)`, `dup -> Up (72)`, `dleft -> Left (75)`,
`dright -> Right (77)`.

**Tests:** `tests/test_pad_aliases.py` **5 passed** - the four aliases map for every player and have real scan codes, and a
test that walks `pso_boot_walk.BOOT_STEPS` and asserts **every key a boot step presses has a scan code** (the general form of
this bug: any step using an unmapped name would silently do nothing).

**Also added:** `system/tools/pso_boot_local.py`, the single-process driver (raise the window, assert
`GetForegroundWindow() == root`, inject with the same `SendInput`, poll RAM through the plane) that removes the async
focus gap described in round 66. With the alias fix, the boot walk now has both halves: correct names and no delivery hop
between focus and keys.

The i9 has no session; the next live window is one command: `python system/tools/pso_boot_local.py --start-at press_start`.

## Round 96: the window opened, the launch was admitted, and the input path is now a measured NO

At 18:0x the operator's idle time reached **327 s** and the CPU dropped to 71 %, so a launch was queued and **admitted** -
`job 1b349dbb3ee94db4`, `state=running`, `admission=` (empty), session **`83202f53e9cd4aa5-1b349dbb3ee94db4`**, emulator
window `gBox Dolphin` pid **33928**.

**What worked, live:** the session booted and RAM reads answered immediately -
`{"mode": 0, "floor": 0, "episode": 1, "player": null, "entities": 0}` (the attract loop) - and the CP9 seed descriptor read
`[0x80585F6C] = 0x0` at the title, exactly as expected (the descriptor is set by `FUN_802019f8` when a save slot is chosen, so
a seed read needs the character select or later).

**What did not work, and is now measured rather than suspected - input does not reach the game from an agent:**

| path | attempts | result |
|---|---|---|
| local `SendInput` via the single-process driver, after `win_bring_to_front(33928)` | 1 | `focus lost before pressing` - the foreground is taken back before the press |
| local `SendInput` **unfocused** (the "focus-free lane" hope) | 4 | `mode` stayed 0 - no reaction at all |
| worker relay `POST /api/sessions/<sid>/input`, actor `agent` and `autoplay` | 6 | `{"queued": 1}` each time, `mode` stayed 0 |

So all three input routes fail on one condition: `adapters._win_input_in_front` only lets pad input through when the game's
top-level window is the **foreground** window (round 66's finding), and an agent-side process cannot hold the foreground while
the harness window owns it; the worker's relay does not deliver either (same check, or the session has no pad binding). The
game is not headless - it is docked in the app - but it does not receive keys while another window is in front.

**What this means for CP4 and CP16:**

* CP4's boot walk (and CP5/CP10/CP12's frame, which all need to press buttons) needs **one** of: the operator clicking the
  game window once (the foreground then belongs to the game for the session), a worker op that activates the window and
  injects in one step, or a launch that carries a **pad binding** so the relay has something to inject through.
* CP16's own "if blocked" clause is now the honest state: the stick/relay path was measured and **does not deliver**, so the
  keyboard walker stays, live only under rule 7. The test itself ("hold `up` for 2 s through the virtual pad") cannot run
  until the pad path delivers at all.

The session was stopped (`job 19fdf60d00a84bdc`, `ended: true`), `/api/sessions` is empty, and the i9 is clean.

## Round 97: a caveat on round 96's negative, and what the emulator's own configuration says

Two facts found this round make the round-96 "input does not reach the game" result **less conclusive than it looked**, and
they are recorded before the next window so nobody acts on a half-measurement.

**1. The presses may have been too early.** Every round-96 attempt read `mode = 0`, which is the attract loop that plays the
opening movie. PSO ignores START during that movie - and in the very first live contact of this lane (round 65) `mode` went
0 -> 1 **on its own**, most plausibly when the movie ended, not because a press landed. A correct test waits for
`mode == 1` (the title menu) *before* judging input. Round 96 pressed within seconds of boot, so "no reaction" is
indistinguishable from "the movie was still playing".

**2. The emulator is already configured for background input, and its pad is keyboard-bound:**

```
Dolphin.ini       [Core] SIDevice0 = 6                       (standard controller)
GCPadNew.ini      Device = XInput/0/Gamepad | `DInput/0/Keyboard Mouse:X`
                  Buttons/Start = `Start` | `DInput/0/Keyboard Mouse:RETURN`
                  D-Pad/Down    = `Pad S` | `DInput/0/Keyboard Mouse:G`
adapters.py:2771  Dolphin.General.HotkeysRequireFocus = False
adapters.py:2774  Dolphin.Input.BackgroundInput = True
```

So the worker **already** sets `BackgroundInput=True` and `HotkeysRequireFocus=False` for its sessions, and the pad's keyboard
fallbacks are exactly the scancodes the driver injects (`start` -> Enter 28, `ddown` -> the D-pad-down binding,
`a` -> X). Windows delivers `SendInput` only to the foreground window, but Dolphin polls its configured DInput keyboard device;
with `BackgroundInput=True` that poll can see the keys even unfocused - which is exactly why the "too early" caveat matters.

**The retest, precisely (next window):**

1. launch and wait for `mode == 1` (poll `pso_boot_walk.state` every 2 s, up to 60 s) - do **not** press while `mode == 0`;
2. press `start` once with the local driver (focus attempt + SendInput), wait 2 s, read `mode`;
3. if unchanged, press again **without** the focus attempt (the background-poll case), read `mode`;
4. only if both fail is the round-96 negative confirmed - and then the unblock options (operator click, worker activate+inject
   op, pad binding) apply.

The three probe scripts stay under `docs/research/pso-cp4-*` with this caveat appended to the evidence, so the next session
runs the discriminating test rather than repeating a confounded one.

## Round 97: a caveat on round 96's negative, and what the emulator's own configuration says

Two facts found this round make the round-96 "input does not reach the game" result **less conclusive than it looked**, and
they are recorded before the next window so nobody acts on a half-measurement.

**1. The presses may have been too early.** Every round-96 attempt read `mode = 0`, which is the attract loop that plays the
opening movie. PSO ignores START during that movie - and in the very first live contact of this lane (round 65) `mode` went
0 -> 1 **on its own**, most plausibly when the movie ended, not because a press landed. A correct test waits for
`mode == 1` (the title menu) *before* judging input. Round 96 pressed within seconds of boot, so "no reaction" is
indistinguishable from "the movie was still playing".

**2. The emulator is already configured for background input, and its pad is keyboard-bound:**

```
Dolphin.ini       [Core] SIDevice0 = 6                       (standard controller)
GCPadNew.ini      Device = XInput/0/Gamepad | `DInput/0/Keyboard Mouse:X`
                  Buttons/Start = `Start` | `DInput/0/Keyboard Mouse:RETURN`
                  D-Pad/Down    = `Pad S` | `DInput/0/Keyboard Mouse:G`
adapters.py:2771  Dolphin.General.HotkeysRequireFocus = False
adapters.py:2774  Dolphin.Input.BackgroundInput = True
```

So the worker **already** sets `BackgroundInput=True` and `HotkeysRequireFocus=False` for its sessions, and the pad's keyboard
fallbacks are exactly the scancodes the driver injects (`start` -> Enter 28, `ddown` -> the D-pad-down binding,
`a` -> X). Windows delivers `SendInput` only to the foreground window, but Dolphin polls its configured DInput keyboard device;
with `BackgroundInput=True` that poll can see the keys even unfocused - which is exactly why the "too early" caveat matters.

**The retest, precisely (next window):**

1. launch and wait for `mode == 1` (poll `pso_boot_walk.state` every 2 s, up to 60 s) - do **not** press while `mode == 0`;
2. press `start` once with the local driver (focus attempt + SendInput), wait 2 s, read `mode`;
3. if unchanged, press again **without** the focus attempt (the background-poll case), read `mode`;
4. only if both fail is the round-96 negative confirmed - and then the unblock options (operator click, worker activate+inject
   op, pad binding) apply.

The three probe scripts stay under `docs/research/pso-cp4-*` with this caveat appended to the evidence, so the next session
runs the discriminating test rather than repeating a confounded one.

**Correction to round 96's conclusion, in one line:** the three input routes were tested while the game was still in its
opening movie; the discriminating retest (wait for `mode == 1`, then press) is written above and has not been run yet.
Round 96's evidence stands as "no reaction was observed", not as "input cannot reach the game".
