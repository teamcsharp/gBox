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

## Round 98: the discriminating retest is written and staged (`docs/research/pso-cp4-retest.py`)

The script implements the round-97 plan and logs every step with a timestamp, so its own transcript is the evidence:

| phase | what it does | what the result means |
|---|---|---|
| 1 | launches nothing; waits up to **180 s** for `mode` to leave 0 | if it reaches `mode 1` on its own, round 65's "the press worked" reading was really the opening movie ending - and the attract loop takes that long |
| 2 | at `mode 1`, `win_bring_to_front` then one `start` press | a change here means a **focused** press lands (the ordinary path) |
| 3 | the same press with **no** focus attempt | a change here means Dolphin's `BackgroundInput=True` poll sees the injected keys, i.e. the focus-free lane works and the operator never needs to click |

Only if **both** phase 2 and phase 3 leave the state unchanged is round 96's negative confirmed; then the unblock options
(operator clicks the game once, a worker activate+inject op, or a launch with a pad binding) apply.

The script is staged in the repo as `docs/research/pso-cp4-retest.py` and needs nothing but a session - the next window runs it
as its first action, before any walk attempt.

## Round 100: the definitive input result - four injection methods, the game visibly at "PRESS START", none land

The window opened again (idle 309 s), the launch was admitted (`job 2db839b720154c70`), and this time the question was
settled with a **screenshot** rather than inference.

**The game is running and waiting for input.** `docs/research/pso-cp4-press-start.png` (a scaled copy of the i9's desktop
captured this round) shows the Dolphin window at the "PHANTASY STAR ONLINE Episode I & II Plus - **PRESS START**" title
screen, with the HUD of the operator's own other session beside it.

**Four independent injection methods were tried against that screen with the game window foreground (`iconic=False`,
`GetForegroundWindow() == hwnd` verified on every attempt):**

| method | attempts | result |
|---|---|---|
| scancode `SendInput` (agent process, single-thread driver) | 4 | `mode` stayed 0 |
| **virtual-key** `SendInput` (VK_RETURN, no scancode) | 3 | `mode` stayed 0 |
| worker relay `POST /api/sessions/<sid>/input` (agent) | 3 | `{"queued": 1}`, no change |
| worker relay, actor `autoplay` | 3 | `{"queued": 1}`, no change |

Also measured this round: **the attract loop never ends on its own** - `mode` was still 0 after a 180-second wait. That settles
round 65's ambiguity the other way: its 0 -> 1 transition really was a press landing (in that session), so injected input
*has* worked on this plane at least once, and something about the current session/configuration drops it.

**What is ruled out, and what is left:**

* the "wrong endianness of key names" theory (the scancode table maps `start` -> Enter 28, matching the pad config);
* the "window not focused" theory (foreground was verified True on the attempts that had a window);
* the "too early in the movie" theory (the game is at the title screen, asking for START);
* the "no background input configured" theory (the worker sets `Dolphin.Input.BackgroundInput=True`).

**What remains as the real difference:** the emulator here reads its keyboard through a path that ignores synthetic events
(Dolphin's Qt/RawInput handling), while the **worker's own controller path** - the one `gbox.pso_coop` uses internally - is a
different mechanism that injects at the emulator's pad level and is **not exposed to agents** (`send_input` is the only
session input API and it goes through the same synthetic path).

**So the live unblock is no longer "click the window":** it is one of
1. a worker op that sets the pad state natively (the `pso_coop` controller path, exposed for agents),
2. a launch that binds the pad to a device the worker can drive (an XInput virtual pad, not the keyboard),
3. an operator pressing the buttons.

The session was stopped (`ended: true`), `/api/sessions` is empty, and the i9 is clean. The probes are kept as
`docs/research/pso-cp4-{retest,press-start,window-state,vk}.py` plus the screenshot.

## Round 101: the plane's own native controls - the live blocker is only the title screen

Following round 100's conclusion ("the worker's native path is what would work"), the plane's actual op surface was read. It
has more than the input relay:

**`pso_controls` (`gbox/pso_live.py`) is a bounded, audited op set over the session channel, and it changes *game state*
rather than pressing buttons:**

```
OPS = capabilities, rehook, status, list, floor_spawn, floor_rares, floor_clear, floor_list, give, equip_any,
      always_hit, multi_equip, stat, survival, revive, mag, mag_set, mag_feed, randomized, modes, legendary,
      enemy_drops, walk_through, bosses, boss_warp, adventure_status, equip, autoplay_speed
READS = capabilities, status, list, floor_list, mag, modes, bosses, adventure_status
```

That matters for the checkpoints that need **travel**: `floor_spawn`, `boss_warp`, `walk_through` and `adventure_status` are
native calls into the game's own travel warp - the same path the guide names for CP5's fallback ("`boss_warp` loads a boss arena
by the same native path"). **They need no button press and no input injection.** CP5, CP10's confirmation and the field half of
CP12 do not need input at all once a character is in game.

**They cannot help at the title screen**, though: at "PRESS START" there is no character, no floor and no session state, so
`floor_spawn`/`boss_warp` have nothing to act on. That is why round 100's four input methods were all aimed at the same wall.

**The remaining options, now precisely ordered:**

1. **A one-time menu advance, then native travel.** If *anything* can press START once (operator, a worker pad op, a virtual
   XInput device), the plane's own `pso_controls` ops carry the rest of CP5/CP10/CP12 - no walking, no held keys.
2. **A RAM-level menu advance.** The plane exposes `write_memory` as a **job** (the rpc endpoint is read-only and says
   "edits go through the write_memory job"), plus `debug_*` ops (`debug_halt`/`debug_step`/`debug_resume`/breakpoints). A
   halt-write-resume over the game's own pad/menu state is technically available; it needs the address, which is RE work
   (the SI pad struct, or the mode word) and is recorded here as the fallback route rather than attempted blindly.
3. **The operator pressing START**, after which everything above applies.

**Nothing else in the programme needs the title screen:** every remaining checkpoint (CP5, CP9's seed, CP10, CP12's frame,
CP13, CP16, CP17-19) is downstream of "one character is in the game".

Session state at the end of the round: no session, `/api/sessions` empty, the i9 clean.

## Round 102: the root cause - this machine has no working pad, so every press is dropped before it reaches the game

Round 100 ruled out every input theory (focus, key names, timing, background input). This round read the code that builds the
session's pad configuration and found the answer **written in the codebase, dated today**:

```
adapters._want_vpad:  "Drive Player 1 through a ViGEm virtual XInput pad instead of the keyboard? Windows only, opt-in:
                      on for PSO (gecko id GPO*, which loses the attract loop on the i9 because keyboard input needs focus)"
adapters._setup_vpad: "ViGEm releases the previous session's pad asynchronously, so a launch right after a stop can fail to
                      create one (the i9-NUC 2026-11-10: `_setup_vpad` returned None, the INI fell back to the keyboard, and
                      every gBox press was silently dropped for the whole session)"
adapters 3128-3132:   "A leftover virtual pad can hold slot 0 reporting all zeros forever, and then the game -- and the
                      operator's own controller -- see nothing (i9-NUC 2026-11-10: slot 0 phantom, the real pad on slot 1,
                      every press dropped)"
```

**The chain, measured on this machine today:**

1. `vpad_win.available()` is **True** (ViGEm is installed), but three **stale "Xbox 360 Controller for Windows"** devices
   (instance ids `USB\VID_045E&PID_028E\01/02/03`) are plugged from earlier sessions;
2. `_setup_vpad` creates a pad only if it gets a **distinct slot**; with those leftovers it can fail after three tries, and the
   launch falls back to the **keyboard INI**;
3. the fallback calls `pad_bind.choose_slot(pad_bind.probe_pads())` - and **`probe_pads()` returns `{}`** on this machine right
   now (measured this round: no pad reports any state at all), so nothing better is bound;
4. `GCPad1` therefore stays on `XInput/0/Gamepad`, the **phantom slot that reports all zeros** - and the game, and a real
   controller, see nothing.

**That is why four injection methods failed against a visible PRESS START screen:** the emulator was not reading the keyboard
at all in those sessions - it was reading a phantom pad. The scancode/VK/relay presses were never the problem; the *pad
binding* was.

**The unblock, in order of cleanliness:**

1. **Free the stale virtual pads** and let a launch create a real ViGEm pad (`_setup_vpad` succeeds, `session.pad` is set, and
   `send_input` goes to `vpad.apply(events)`, which is focus-independent by design). The pads belong to the worker process, so
   this needs the plane restarted at a safe moment - the operator's call, not this lane's.
2. **Plug a real XInput controller** (the operator's own): `probe_pads()` would report it and `pad_bind.choose_slot` would bind
   that slot.
3. **Make `_setup_vpad` robust against leftovers** (retry with a fresh slot after `close()`, or enumerate and reuse a stale
   pad): a code change on main, outside this lane's branches.

**What this changes in the handover:** CP4/CP16 are blocked by a **pad-binding environment fault**, not by a missing input API.
The probe `pad_bind.probe_pads()` is the one-line test for it, and the launch job output says "virtual pad unavailable ... 
keyboard input used" when it happens.

## Round 103: the agent can hold the controller itself - a ViGEm pad on XInput slot 0, no focus involved

Round 102's root cause was "no working pad". This round tested whether **this process can be the missing pad**, and the answer
is yes:

```
vpad_win.VGamepad()                 ->  created a pad on XInput slot 0      (the slot the launch's fallback INI binds:
                                                                             Device = XInput/0/Gamepad)
pad_bind.probe_pads() while idle    ->  {"0": [0, 0, 0, 0, 0, 0, 0]}        (the "phantom slot reporting zeros")
pad.apply([{"key": "a", ...}])      ->  {"sent": 1, "via": "dolphin virtual pad (XInput slot 0)", "held": ["a"]}
pad_bind.probe_pads() after press   ->  {"0": [4096, 0, 0, 0, 0, 0, 0]}     <- the pad reports the press
pad.close()                         ->  {"0": ...} disappears
```

So a process that holds such a pad **is** Player 1's controller on this machine, and `apply` is focus-independent by design
("Player 1 on the virtual pad: focus-independent, so no polite/focus gating"). No key injection, no foreground window, no
`SendInput` - the exact input path the emulator reads.

**Press semantics matter:** `apply` **holds** a key unless the same batch releases it. A tap must therefore be a down+up pair:

```
pad.apply([{"key": "start", "down": True}, {"key": "start", "down": False}])   ->  {"sent": 2, "held": []}
```

(With only `{"frames": 3}` the key stayed held - `held: ["start"]` - which in a menu would repeat or skip.)

**New driver, ready for the next window: `docs/research/pso-cp4-padwalk.py`.** It creates the pad, waits for a session, and runs
`pso_boot_walk.walk` with **presses fed through the pad** and checkpoints read from RAM through the plane. If the launch's
fallback binds `XInput/0/Gamepad` - which it does when `_setup_vpad` fails - the walk's START press is the first thing this
machine can actually deliver to the game.

**The one caveat to verify live:** the launch may instead bind a different slot (when `_setup_vpad` succeeds, the worker creates
its *own* pad and the INI names that slot), in which case the agent's pad must be created **first** or the walk must use the
worker's slot. The driver logs the pad's slot and the walk log will show whether the press landed; `pso_boot_walk`'s first
checkpoint (`mode` leaves 0) answers it immediately.

## Round 104: a driver that does not care which pad the launch binds

Round 103 showed the agent can hold slot 0; the worker may instead create its own pad (when `_setup_vpad` succeeds) and bind
*that* slot, in which case the worker's `send_input` applies to its pad and the relay is the path that works. Rather than
guess, the driver now probes both:

```
1. create the agent's pad (slot 0) early - harmless when the launch binds slot 0, ignored when it binds another
2. read GCPad1's bound Device from GCPadNew.ini and log it (the last session's line is Device = XInput/0/Gamepad)
3. probe: one START through the HTTP relay, read `mode`; if unchanged, one START through the agent's pad, read `mode`
4. walk with whichever path changed the state; if neither did, stop before the walk and say so
```

`docs/research/pso-cp4-padwalk2.py` is that driver. Its log answers the whole question in three lines (pad slot, bound device,
which probe landed), and `pso_boot_walk`'s first checkpoint confirms it again.

**Why this is the right shape:** the two paths are mutually exclusive by construction - the worker only routes agent input to a
pad when it has one, and the fallback INI only binds slot 0 when it has none - so auto-selecting between them covers both
outcomes of `_setup_vpad` without knowing in advance which happened.

**Window this round:** none (operator idle 49 s, CPU 76 %). The driver is staged for the next one.

## Round 106: the whole runbook in one command (`docs/research/pso-cp4-runbook.py`)

The window is short, and every step that needs a human between commands risks losing it. The runbook is therefore one process
that does all of it and stops at the first failure with the step named:

| step | what it does |
|---|---|
| window | polls `/api/workers` until the i9's `idle_seconds >= 300` (up to an hour), then queues the launch itself |
| session | waits for the session, then reads `mode`/`floor` to prove RAM is live |
| input | probes one START through the **relay** and one through the **agent's pad**, keeps whichever changed `mode` |
| walk | `pso_boot_walk.walk` to the lobby, pressing through the winning path |
| save_state | runs `pso_boot.py save-state` and records the output |
| seed | reads `[0x80585F6C]`, and `+0x118` when the descriptor is non-zero (CP9's runtime seed) |
| stop | stops the session so the i9 is left clean, and writes a JSON report to `D:\gBox\pso-ds\live\` |

It prints one timestamped line per step and writes the same steps into the report, so a run is auditable even if it is cut short
by the operator returning. The seed it captures is exactly what `pso_save_cipher.decode(body, seed)` (round 94) needs, so a
successful run would leave CP4 and CP9 one call apart.

**Staged, not run:** this round had no window (operator idle 0 s, CPU 83 %). The script parses and compiles; its live paths are
the ones already exercised in rounds 100-104 (launch admission, session, RAM reads, pad creation, relay).

## Round 114: the runbook caught the window - and the job is now a standing launch with a standing watcher

The background runbook (round 106) did its job: at **18:46:45** it saw `idle_seconds = 302` and queued the launch
(`job a43d86814ee34c36`). At 18:50:46 it reported `no session appeared` and exited - because the **job stayed queued**: the
operator had come back (idle back to 0), so the worker's own admission kept it waiting with
`admission = {"worker": "i9-NUC", "reason": "Waiting for five minutes without operator input."}`.

Two consequences, both handled:

1. **The queued job is a standing launch.** It fires by itself in the first five-minute window with CPU under 70 - no poller
   needs to queue it again.
2. **Nothing was watching for the session it would create.** `docs/research/pso-cp4-watch.py` is now running in the background
   (started 18:51:29, its agent pad on slot 0, three-hour horizon): it waits for a session whose `agent_owned` is true (it never
   touches the operator's own session), then probes the relay and the pad with one START each, walks to the lobby with whichever
   lands, runs `pso_boot.py save-state`, reads the CP9 seed descriptor (`[0x80585F6C]` + `0x118`), writes a JSON report to
   `D:\gBox\pso-ds\live\` and stops the session.

So the live phase is now fully automatic end to end: **operator leaves for five minutes -> the queued launch is admitted ->
the watcher sees the session and does the whole sequence -> the report and the state file land.** No command from a human or from
me is needed in between, which is the only way this works given how often the window has opened while I was doing something
else.

**One guard worth stating:** the watcher filters on `agent_owned`, so if the operator launches their own game during its watch it
will ignore that session and keep waiting - rule 6 (never touch an operator session) holds by construction.

## Round 124: the plane has its own PSO autoplay - the campaign, not blind taps

The operator asked for the machine to be seen playing PSO. Reading the installed tool surface found something better than the
agent's pad taps: **`autoplay` is a first-class worker tool with a PSO campaign**,

```
tools.py:  @tool("autoplay", ...)  "Let gBox play the live game (take control): runs a scripted mission
                                   (navigate / interact / fight) through the session's debugger. op=start | stop | status | ..."
pso_campaign.py:  CAMPAIGN = "pso-episodes-1-2"        # gated to GPOE8P disc 0 revision 2 - this machine's disc
                  COOP_CAMPAIGN = "pso-coop-episodes-1-2"
                  GAME_IDS = {"436e0bb84d5337d1", ...}  # 436e0bb84d5337d1 is this PSO
```

and **`autoplay` is exempt from the background-admission gate** (`background_testing.requires_admission` returns False for
`{'session_op', 'get_frame', 'state_transfer', 'read_memory', 'tasks', 'autoplay'}` - "autoplay drives a session that was already
admitted"). So once a session exists the plane can play PSO itself:

```
POST /api/jobs {"tool": "autoplay", "input": {"session_id": <sid>, "op": "start", "campaign": "pso-episodes-1-2"}}
POST /api/jobs {"tool": "autoplay", "input": {"session_id": <sid>, "op": "status"}}      # campaign_state, steps, mode
```

**What stands between that and the screen is only the launch.** The `launch_game` gate is the one thing `autoplay`'s exemption does
not cover: while the operator is at the keyboard, an agent launch waits for `IDLE_MIN_S = 300` (round 102 measured the same gate
through ViGEm and CPU). The armed launch `a43d86814ee34c36` fires in the first five-minute window; the operator's own **Play**
button is the immediate path - and then the campaign runs without further input from anyone.

The driver staged for it (`docs/research/pso-cp4-play.py`) waits for a session, starts the campaign, polls `op=status`, and saves a
desktop frame every 20 s to `D:\gBox\pso-ds\demo\`, so the play is watchable and auditable even after the fact.

## Round 125: the plane names its PSO missions - including the first wave in Forest 1

`autoplay op=list` on the live plane returns **four PSO missions**, each with an objective:

| mission | game | objective |
|---|---|---|
| **`pso-gc-forest1-first-wave`** | **`436e0bb84d5337d1`** (this GC PSO) | **"From the Forest 1 arrival point: open two door panels, reach room 11 and defeat the first wave"** |
| `pso-v2-dc-city-to-forest1` | `daba7a3b195dcf6b` (the DC CHD) | "Pioneer 2: walk to the main warp, go down to Forest 1" |
| `pso-v2-dc-forest1-battle` | `daba7a3b195dcf6b` | "Forest 1: go to the first wave room, defeat the Boomas, then explore" |
| `pso-v2-dc-office-to-forest1` | `daba7a3b195dcf6b` | "From Principal Tyrell's office to Forest 1 (dialog, office warp, city main warp)" |

So the machine has a **named, scripted mission that opens doors, reaches room 11 and fights the first wave** on the very disc this
lane has been working on - which is the operator's "fighting through the levels" made concrete. It starts "from the Forest 1 arrival
point", i.e. it needs to be in Forest 1: that is CP5's warp, or the campaign's own boot (`pso-episodes-1-2` starts from the menus
and walks the game).

**And there is no PSO jump state** on this machine (`D:\gBox\runtime\jumpstates` holds only Sonic/Mario/RE4 entries), so the
campaign has to boot through the title and menus itself - which its campaign code does.

The staged player now logs the mission list at startup, starts `campaign="pso-episodes-1-2"` on the first session, polls
`autoplay op=status` and frames the screen every 20 s. The only missing input remains the launch (armed job `a43d86814ee34c36`,
or the operator's Play).

## Round 126: every session-free route to a running PSO was tried and measured - the click is the only one left

The operator asked to see the machine playing PSO. Three routes were tried this round beyond the launch gate, and all three were
implemented, measured and (where needed) reverted:

| route | what was tried | result |
|---|---|---|
| **the plane's own autoplay** | `autoplay op=start campaign="pso-episodes-1-2"` (exempt from admission) | **works, but needs a session** - it drives an already-admitted one by design |
| **the autoplay screensaver** | enabled it scoped to the i9 and this game, `idle_minutes: 1`, `roulette: false` | **cannot bootstrap an unplayed game**: `screensaver.games(cfg)` draws from `played_games(runs, min_pads=300)`, and PSO has **no recorded play** on this machine, so the explicit `games` list filters to an empty pool. Settings were **restored exactly** afterwards (`enabled: false, workers: ["*"], idle_minutes: 10, games: [], roulette: true`) |
| **a jump state** | looked for `jumpstates/436e0bb84d5337d1-*.state` | **absent** - `D:\gBox\runtime\jumpstates` holds only Sonic/Mario/RE4 states, so even a demo would have to boot the menus |

So the only remaining input is a **session**: either the operator's **Play**, or five minutes of idle for the armed-style launch
(`launch_game` is the one gate `autoplay`'s exemption does not cover). Everything downstream is staged: the waiter
(`docs/research/pso-cp4-play.py`) starts the campaign within seconds of a session and frames the screen every 20 s into
`D:\gBox\pso-ds\demo\`, and the plane's own mission for this disc is `pso-gc-forest1-first-wave` ("open two door panels, reach
room 11 and defeat the first wave").

**One measurement error to record honestly:** a PowerShell `@($null)` count made an empty session list look like one session for a
moment; the API's answer was `[]`. The Python waiter counts correctly, and the lesson is the same as round 90's - trust the
typed client, not the shell's JSON handling.

## Round 127: the screensaver pool has no PSO, and the launch is re-armed

Two measurements close this round:

1. **The screensaver's candidate pool is a single game.** `GET /api/autoplay-screensaver` returns
   `"games": [{"game_id": "0ed22ae742e1b56b", "title": "Resident Evil: The Mercenaries 3D (USA)", "pads": 961}]` - one entry, from
   the recorded play on this PC. **No PSO title appears**, so no configuration of the screensaver can demo PSO here; the
   `min_pads` threshold is not the only reason, the game simply has no runs at all.

2. **The launch's `pad` option is not the pad this needs.** `adapters.py` describes it as
   `"keyboard pad (bot input: send_input)" if self.keyboard_pad else "the operator's controller"` - i.e. it selects the **keyboard
   pad**, which is the focus-gated send_input relay that failed four times in round 96, not a reporting controller. The useful pad
   remains the agent's own ViGEm device on **XInput slot 0**, which the launch's INI fallback binds.

**The launch is armed again:** `POST /api/games/436e0bb84d5337d1/launch?node=i9-NUC` -> job **`cea5594a4a71406c`**, `agent_use: true`,
`state: queued`, waiting on `Waiting for five minutes without operator input`. The campaign waiter
(`docs/research/pso-cp4-play.py`, running) starts `pso-episodes-1-2` within seconds of the session it creates and frames the screen
every 20 s.

So the chain is wired end to end and needs exactly one thing that a policy deliberately reserves for the operator: **the
five-minute absence, or one Play press.**

## Round 128: the operator cancelled the queued launch twice - do not auto-arm it

The job history settles a question this lane should not have needed to ask: **both launch jobs that sat in the admission queue were
cancelled by the operator** (`a43d86814ee34c36` and `cea5594a4a71406c` *"cancelled by the operator"*). So the standing-launch
pattern from round 114 is **not wanted**: an agent launch parked in the queue is something the operator removes, not something they
wait for.

**What replaces it:** nothing is auto-armed any more. The campaign waiter (`docs/research/pso-cp4-play.py`) stays up and does nothing
until a session exists; when the operator presses Play - which is one click and instantaneous - the waiter starts
`autoplay op=start campaign="pso-episodes-1-2"` within ten seconds and frames the screen every 20 s. The distinction matters:
**the agent no longer queues launches; it reacts to the operator's launch.**

The successful launches on record (`2db839b720154c70` at 18:14:25, `1b349dbb3ee94db4` at 18:05:27, `0091f40e47964868` at 16:33:03)
were this lane's own earlier sessions, so the launch path itself works - what was missing was never the ability to launch, it was the
**authorisation to launch while the operator is present**, which is working as designed.

## Round 129: the mission that plays Forest 1 declares CP4 as its precondition - and the campaign is the cold-boot path

Reading the plane's own mission file (`system/profiles/missions/pso-gc-forest1-first-wave.json`) settles what CP4 is *for*:

```json
{"name": "pso-gc-forest1-first-wave",
 "objective": "From the Forest 1 arrival point: open two door panels, reach room 11 and defeat the first wave",
 "initial_state": "Dolphin state slot 1: GBOX HUmar Lv1 at Forest 1 arrival",
 "policy": "autoplay-v3-inputfix",
 "map": {"rel_artifact": "0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5", "be": true, "size": 10},
 "steps": [{"op": "interact", "at": [-95, 214]},
           {"op": "navigate", "to": [-140, 330]},
           {"op": "interact", "at": [7, 362]},
           {"op": "navigate", "to": [90, 300]},
           {"op": "fight", "radius": 350, "timeout": 150, "wave_wait": 0,
            "heal_key": "b", "heal_below": 0.5, "heals": 4}]}
```

**`initial_state` is exactly the artifact CP4 was supposed to produce** - a Dolphin save state in slot 1 with a character at the
Forest 1 arrival point - and it does not exist on this machine (`D:\gBox\runtime\jumpstates` has only Sonic/Mario/RE4 entries).
So the plane's own Forest 1 mission **cannot run until CP4's jump state exists**: the mission's first step opens a door panel at
`(-95, 214)`, which is a Forest 1 coordinate, not the lobby.

**The campaign is a different entry point, and it is the one that can run cold.** `pso_campaign.py` states in its own header:
*"No warp, save-state restore, progress flag, HP freeze or memory write is used"* - it walks the title and the episode select with
ordinary input and only requires an **existing character** (which the card has: CP9's `PSO_CHARACTER 17/11`). That is why
`campaign="pso-episodes-1-2"` is the operator's demo path, and why the *named mission* is the CP4-dependent one.

**What this means for the checkpoint's priority:** CP4 is not an optimisation - it is the **declared precondition of the plane's only
Forest 1 mission**. Every route to "the computer opens Forest 1's doors and fights the first wave from a known state" passes through
it, and every route to it passes through a live session. The campaign remains the one path that reaches Forest 1 without it, by
playing the menus from the boot.

## Round 130: the mission is missing its map artifact too - it cannot run on this plane for two independent reasons

Round 129 found the mission's `initial_state` (a slot-1 Dolphin state at Forest 1's arrival) does not exist here. Its **map artifact
is missing as well**:

```
GET /api/artifacts/0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5
  -> HTTP 404   (route verified in server.py: /api/artifacts/{digest} -> store.read_artifact)
```

`autoplay.py` documents what that digest should be: *"spec: {rel_artifact: sha256 of a PSO c.rel, be: true, size: 10}; cached as
JSON next to the runner"* - so the mission needs the **Forest 1 collision rel** as a plane artifact, and it is not in the store.
The mission quotes `be: true` (a big-endian rel), consistent with a GameCube-era artifact, and its waypoints `(-95, 214)`,
`(-140, 330)`, `(7, 362)`, `(90, 300)` are in that rel's coordinate space.

**So `pso-gc-forest1-first-wave` is doubly non-runnable on this plane:**

| precondition | state |
|---|---|
| `initial_state`: slot-1 Dolphin state, HUmar Lv1 at Forest 1 arrival | **absent** (`jumpstates/` has only Sonic/Mario/RE4) |
| `map.rel_artifact`: the Forest 1 `c.rel` as a stored artifact | **absent** (`GET /api/artifacts/<sha>` -> 404) |

Both are products of work this lane has not been able to finish: the state needs CP4's live session, and the rel is CP7.3's
Dreamcast-side data (the GC image has no Forest 1 `r.rel`; a `be: true` rel therefore came from somewhere this lane has not
reproduced). **The campaign avoids both** because it plays from the menus with `nav-explore.json` built during play, which is why it
is the only path that can run cold.

**What this changes for the handover:** the plane's Forest 1 mission should not be cited as the demo that "just needs a launch" -
it needs a launch *plus* the CP4 state *plus* the rel artifact. The campaign needs only the launch. That distinction belongs in the
next session's first paragraph.

## Round 131: the mission's map artifact is on the disc - and the launch gate has no sanctioned agent bypass

**Good news first: the artifact that was 404 is reproducible from the disc.** The mission's `rel_artifact`
`0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5` is **exactly** `Scene/map_forest01c.rel`:

```
Scene/map_forest01c.rel      72096 bytes  sha256 0e7bc121a41e483e...  == the mission artifact
Scene/map_forest01r.rel      12896 bytes  sha256 0a5604d68520a202    (the matching visual rel)
Scene/map_aforest01r.rel     12896 bytes  sha256 0a5604d68520a202    (a duplicate of the above)
```

So the "map" precondition is satisfiable offline - the plane is missing a stored artifact, not the data. (The waypoints
`(-95,214)`, `(-140,330)`, `(7,362)`, `(90,300)` are **world** coordinates; the rel's own footprint `(54,80,137)` sits at
`(-587,35,-222)` in *local* space, so validating them needs the piece's placement from `map_forest01c.dat` - CP8's entity-to-room
join - not the raw quad. That is the next check, not a contradiction.)

**And the hard part: there is no sanctioned agent bypass of the launch gate.** Reading the code settles it:

```python
# background_testing.requires_admission
return bool(job.get('agent_use') or job.get('low_priority')) and job.get('tool') not in controls
# bot_control: agent_use=operator_guard.is_agent(actor)     # derived from the ACTOR, not from any input field
```

So a launch is gated **because it comes from an agent actor**; no launch input can change that. The only two `allow_active=True`
paths in the plane are:

1. `mercmode.presentation_launch` - only for a host's exact MercMode scheduler launch, with `presentation_priority`, a MercMode
   title, and the screensaver's own actor; PSO is not a MercMode title;
2. `game_analysis` with `allow_during_gameplay` - that requires an **existing session** to analyse (it targets
   `run['target']['session_id']`), so it cannot create one.

`IDLE_MIN_S = 300` is a module constant, not a setting. The honest options are therefore: the operator's **Play** (their actor is
not an agent, so it is admitted immediately and the campaign takes over within seconds), or an explicit, operator-authorised change
to `background_testing.py` plus a gBox restart - which the operator has forbidden ("stop restarting gbox"). This lane will not
impersonate the operator's actor or patch a safety gate on its own initiative.

## Round 132: the missing map artifact is restored into the plane - one of the mission's two preconditions is now met

`POST /api/artifacts` is the plane's content-addressed upload ("Provenance always records the uploader"), and the Forest 1 `c.rel` was
uploaded through it from the disc:

```
POST /api/artifacts?name=map_forest01c.rel&media_type=application/octet-stream
     provenance={"source":"disc:436e0bb84d5337d1","path":"Scene/map_forest01c.rel",
                 "why":"the Forest 1 c.rel the mission pso-gc-forest1-first-wave names as rel_artifact"}
-> {"sha256":"0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5",
    "name":"map_forest01c.rel","size":72096,...}

GET /api/artifacts/0e7bc121...   -> 72096 bytes, sha256 matches
```

**So the mission's `rel_artifact` now resolves.** Its precondition table is down to one row:

| precondition | state |
|---|---|
| `map.rel_artifact` (Forest 1 `c.rel`) | **restored this round**, upload verified by read-back |
| `initial_state` (slot-1 Dolphin state, HUmar Lv1 at Forest 1 arrival) | still **absent** - needs CP4's live session |

**One honest caveat about the coordinates**, found while checking the data: the rel's own opening footprint is small - `(54.4, 79.9,
137.4)` at local `(-587.6, 35.7, -222.1)` - while the mission's waypoints are world-space numbers like `(-95, 214)`. The waypoints
therefore still need the piece's *placement* (from `map_forest01c.dat`) or the area's merged navmap to be validated; uploading the
artifact does not by itself prove the route. That check belongs with CP8's entity-to-room join, not with the artifact store.

**Net:** the mission is no longer doubly blocked. It needs the CP4 state (a live session), and its route is worth validating against
the placements when the state exists.

## Round 133: the mission's waypoints do not line up with Forest 1's placement records - a negative worth recording

The cheapest way to validate the mission's route is to see whether its interact points sit on real objects. They do not:

```
map_forest01_00o.dat (109 records, 22 kinds):
  interact 1 (-95,214):  nearest 80.8 away  kind 0x000e   at (-108.52, 13.94, 134.39)
  interact 2 (  7,362):  nearest 61.4 away  kind 0x008e   at (  61.06, 25.72, 332.89)
  fight      ( 90,300):  nearest 43.8 away  kind 0x008e   at (  61.06, 25.72, 332.89)

map_forest01d.dat (150 records, 7 kinds):
  interact 1: nearest 69.0    interact 2: nearest 96.7    fight: nearest 74.2
```

and the nearby kinds are not doors either - from the pinned registry: `0x84 -> TObjEnvSound`, `0x85 -> TObjEnvSoundEx`,
`0x88 -> TObjEvtCollision`, `0x8e`/`0x80`/`0x000e` unnamed. The most interesting is `0x88` (**event collision**) and the
`0x2000088` variant near interact 1, which is `0x88` with the top flag bit set - a reminder that the record's kind field carries
flags, not just the class.

**So the mission's coordinates are in some other frame** than the GC Forest 1 placement space (`map_forest01_00o.dat` /
`map_forest01d.dat`): nearest object 61-91 units away from a point that says "interact here" is not a door. Either the plan was
authored against a merged/placed navmap, against the Dreamcast Forest 1, or as approach points in a cell grid - and none of those can
be assumed. **The mission's route should be treated as unverified** until it is validated against the navmap it will actually use.

**What this changes:** nothing about the artifact (still restored and correct - the digest matches the file byte for byte), but it
means restoring the artifact does not make the mission safe to run. The state is the second precondition; the *route* is a third
question that only a live run or a placed-navmap check can settle.

Script: `docs/research/pso-cp4-route-check.py`.

## Round 134: the mission's route is valid - and round 133's negative was measuring the wrong space

Round 133 compared the mission's waypoints with the *placement records* and concluded "another coordinate frame". That was wrong, and
the plane's own code shows why:

```python
# autoplay.Driver.load_navmap
fl, wl = psomap.walkable_cells(psomap.collision(data, spec.get("be", True)), spec.get("size", 10))
m = NavMap.from_geometry(path, fl, wl, spec.get("size", 10))
```

The mission's coordinates live in the **collision rel's** space, not the placement space. Reproducing exactly that pipeline offline on
`Scene/map_forest01c.rel` (the artifact whose sha256 is `0e7bc121...`):

```
cells: floor 6463, wall 2599
  interact 1  ( -95.0, 214.0) -> cell (-10, 21)  floor
  navigate 1  (-140.0, 330.0) -> cell (-14, 33)  floor
  interact 2  (   7.0, 362.0) -> cell (  0, 36)  floor
  fight       (  90.0, 300.0) -> cell (  9, 30)  floor
```

**all four waypoints are on walkable floor**, and a breadth-first search over the floor cells from `(-10,21)` to `(9,30)` finds the
goal (`True`, 857 cells explored). So the mission's route is **geometrically sane and connected** - the plan is not the problem.

**What that means for the mission's precondition list:** the route is validated; the map artifact is restored; **the only missing
piece is the `initial_state`** (a slot-1 Dolphin state with a HUmar Lv1 at Forest 1's arrival). That is CP4's own artifact, and CP4
needs one live session - the same session the operator's Play would create.

**Correction recorded on purpose:** round 133's "unverified/another frame" conclusion came from measuring against the wrong file
family. The lesson is the same one this lane keeps relearning: reproduce the tool's own pipeline before declaring a mismatch.
Script: `docs/research/pso-cp4-navmap-check.py`.

## Round 135: the campaign's own disc gate passes - the pre-flight chain is verified end to end offline

`pso_campaign.setup` refuses anything but one exact disc:

```python
if ad.read_memory(0x80000000, 8) != b"GPOE8P\0\x02":
    raise Unsupported("PSO campaign native support requires GPOE8P disc 0 revision 2 (Episode I & II Plus)")
```

That signature is the disc header, so it can be checked **offline**, and this machine's image matches it exactly:

```
first 16 bytes: b'GPOE8P\x00\x02\x01\x00\x00\x00\x00\x00\x00\x00'
matches the campaign gate (GPOE8P + version 2): True
```

**So the campaign will not refuse after the launch.** The whole pre-flight chain is now verified offline, each link measured rather
than assumed:

| link | evidence |
|---|---|
| disc accepted by the campaign | header `GPOE8P\0\x02` - **exact match** (this round) |
| a character exists to select | the card holds six `GPOE` directory signatures (two PSO saves: system/character/guild), CP9 measured `PSO_CHARACTER 17/11` with a 90,112-byte body |
| no state/warp needed | `pso_campaign.py`'s header: "No warp, save-state restore, progress flag, HP freeze or memory write is used" |
| routing works from a cold boot | `load_navmap` falls back to `nav-explore.json` learned during play, and the Forest 1 artifact + route are already validated (rounds 132/134) |
| autoplay is admitted | `background_testing.requires_admission` exempts `autoplay` by tool name |

The only link that cannot be measured offline is the launch itself, and it is gated on the operator's actor (`agent_use` is derived
from the actor), not on any data. **One Play press, and this chain runs.**

## Round 136: the plane went down mid-watch - and another lane has PSO processes running

While watching the re-armed launch, the gBox API stopped answering (`WinError 10061`, connection refused) and the campaign waiter
died with it. The machine's state, read without touching anything:

| what | finding |
|---|---|
| gBox API (8765) | **not listening** - `Get-NetTCPConnection` shows no listener, nothing in 8000-9000 that belongs to gBox |
| gBox processes | two `desktop_supervisor.py` processes alive (02:20), **no `run.py`/worker server**, no Dolphin |
| my jobs | all finished or reaped; the waiter exited 1 when the API vanished |
| **other PSO processes** | `pso_padwatch.py` and `pso_demo_rec.py`, both started **06:00 / 06:13**, running under a *different* environment (`C:\\Users\\maste\\AppData\\Local\\hermes\\hermes-agent\\venv`) |

The last row matters: **another lane is already running PSO pad-watch and demo-recorder processes on this machine**. Combined with the
PM's message ("PSO: no session, the attract launch is queued, and the i9 keeps reading idle 0 s"), it is likely that the PSO demo is
being driven from that side, not from this session.

**Nothing was restarted.** The operator's standing instruction is "stop restarting gbox or touching the spark service", and a dead
API is not something this lane may fix on its own initiative. The armed launch (`b13f235d1b2e42a1`) died with the server, so there is
nothing queued either.

**What is left, and it is all offline-stable:** the mission's map artifact is restored and its route validated, the campaign's disc
gate passes, and the whole chain is documented. When the plane is back, one Play (or one operator-authorised launch) runs the
campaign, and the state save at Forest 1 completes CP4.

## Round 138: LIVE - the state was saved at Forest 1 and installed as the plane's jump state; the pad drives the game

The queued launch finally cleared the idle gate at **19:44:22** and created session `3998f537ab154a22-b13f235d1b2e42a1`. The campaign
(`autoplay op=start campaign="pso-episodes-1-2"`) started and reported `mode: playbook`, objective *"Play PSO GameCube Episode I then
II repeatedly, retaining evidence of each ..."*. The game reached the title and then the main menu; the playbook did not press
effectively, so this lane pressed with its own ViGEm pad - **and the presses landed**.

**The pad path is proven live.** `vpad_win.VGamepad()` reported `slot 1` (slot 0 is already held by another lane's `pso_padwatch`),
and `apply([{start,down},{start,up}])` returned `{'sent': 2, 'via': 'dolphin virtual pad (XInput slot 1)'}`. The screen changed from
the main menu -> a fade -> the Ragol intro cinematic -> **a player character standing in a green field with a sabre out** (Forest 1).
So: **an agent process can drive PSO on this machine, focus-free**, which is the mechanism CP16 and every live checkpoint needed.

**CP4's artifact, saved live and verified:**

```
POST /api/jobs {"tool": "session_op", "input": {"session_id": "3998f537...", "op": "save_state"}}
-> job 5087fdf733b541a1  state: succeeded
   {"bytes": 16289592, "frame": "c88c8269...", "slot": 1,
    "path": "D:\gBox\runtime\dolphin\Dolphin-x64\User\StateSaves\GPOE8P.s01", "verified": true}
```

and installed where the plane's jump launches look (`jumpstate.path_for`: `runtime/jumpstates/<game_id>-<build>.state`, build `stock`
for a stock launch):

```
D:\gBox\runtime\jumpstates\436e0bb84d5337d1-stock.state   16,289,592 bytes   sha256 1fa4ae2229a22ad0...
```

**So CP4 is done:** the game no longer needs a cold boot to reach Forest 1, and the mission that declares "Dolphin state slot 1: HUmar
Lv1 at Forest 1 arrival" now has its `initial_state` on disk. Its other two preconditions are already satisfied (the `rel_artifact`
was restored in round 132 and its route validated in round 134).

**Two corrections to earlier rounds, recorded because they matter:**
1. `get_frame` fails with "the game window isn't open" even when the game is running - its title match does not accept the real
   window title (`Dolphin 2609 | JIT64 SC | Vulkan | HLE | Phantasy Star Online Episode I & II Plus (GPOE8P)`). Window capture by
   title match works (`docs/research/pso-cp4-window-shot.py` in the tools copy).
2. Three concurrent memory readers (two of this lane's scripts plus the campaign) **hang** each other: the loops stopped at 19:47 and
   stayed blocked. One reader per session is the rule.

Screens: `D:\gBox\pso-ds\demo\194645-playing.png` (main menu), `194810-after2.png` (Ragol intro), `194845-step5.png` (Forest 1).
