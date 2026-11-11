# Playing PSO through gBox: what works, what does not, and the one platform bug left

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

## Works (all verified live, 2026-11-10 ~20:45-21:00)

| item | evidence |
|---|---|
| **gBox binds the operator's controller as Player 1** | the restart with `GBOX_DOLPHIN_VPAD=off` made `_want_vpad` return False; `_argv`'s fallback called `pad_bind` (`probe_pads -> {1: (...)}`), and the written INI is `# gBox: Player 1 bound to XInput slot 1 ...` / `Device = XInput/1/Gamepad` |
| **a launch is admitted while the operator is at the PC** | the Tasks-menu designation `allow_while_active` (its own comment: *"2026-11-10: 'play PSO on the i9 despite me being on the PC'"*) skips the five-minute idle wait; the launch was admitted at 84 % CPU against the 90 % budget |
| **the game runs docked in gBox** | the render window is a child of `gBox.exe` (title `gBox`, pid 28176) - there is no top-level "Dolphin ..." window, so window capture must target the **app** window; the operator played in-game as "Deb" Lv 1, HUmar |

## Does not work: the session RPC is unresponsive while the game plays

Every debugger read during live play failed:

```
POST /api/sessions/<sid>/rpc -> HTTP 504
{"detail": "Session did not acknowledge the action. Its outcome may be unknown; check the game before issuing another action."}
```

Consequences measured:

* the **route recorder** (`docs/research/pso-route.py`) got **0 samples** in 7 minutes of trying;
* the **random-build cycler** (`docs/research/pso-random-build.py`) queued `pso_loadout` jobs that never ran (45 s timeout each, 4 queued jobs cancelled afterwards so nothing applied unexpectedly).

**Hypothesis (not yet tested):** Dolphin's GDB stub services reads only when the core is stopped, so a session in full-speed play never acknowledges; the adapter should either pause around a read or use a non-stopping channel. The test is cheap and does not disturb the operator's input: `session_op pause` -> `read_memory` -> `session_op resume`, plus one `read_memory` while playing as the control.

## Built and waiting on that RPC

* **random build cycling** - `pso_random_build.py`: every N seconds pick a not-recently-used high-tier GC weapon and mag from curated lists and apply them with `pso_loadout op=drop` (names resolved against the owned disc; unknown names refused by the plane, never equipped). Dry-run tested: two cycles logged, both `timeout` because of the RPC bug above.
* **route learning** - `pso_route.py record` samples `pso_ram` positions (player slot table `0x8050EA10`, actor + 0x38/0x3C/0x40) plus the pad at 8 Hz; `convert` simplifies them (Douglas-Peucker) into an autoplay mission of `navigate {to: [x, z]}` steps - the bot walking the route the operator walked.
* **input learning** - `pso_record_operator.py` needs no plane at all: it samples the operator's pad (the `pad_bind` alive slot) at 30 Hz and, at the end, writes `D:\\gBox\\pso-ds\\operator-timeline-*.json` and a learned mission via `pso_learn_play`.

**So the operator's two new asks are implemented and blocked on exactly one thing:** a session RPC that answers while the game is running.
