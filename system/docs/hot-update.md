# Hot updates: bot reload now, sessions that survive a restart next

Operator, 2026-10-26: "Every time I look at the system, it's loading the game. Instead of playing the game, it's always
loading the game. I'm trying to reduce loading to be as short as possible to not at all."

Every deploy ran `sudo systemctl restart gbox.service` (`scripts/deploy_main.sh`). The unit runs the control plane and
the Spark's worker in one process (`python -m gbox serve --worker`, default `KillMode=control-group`,
`TimeoutStopSec=10`), so a restart killed every emulator, its Xvfb display, the stream and audio encoders and the
MercMode warm pool. MercMode then cold-launched (RE5 on RPCS3: about 50 s to playing, then the pool booted again). The
coordinator restarted five times that day, mostly for bot-logic fixes.

## Part 1: bot hot reload (implemented)

A deploy whose changed runtime files are all bot modules reloads them in the running worker. The games, streams and warm
pool keep running. Only the autobots restart, each in its own session.

```
deploy_main.sh --deploy
  activation_for <runtime files>      python -m gbox.hot_reload classify  ->  none | reload | restart
  reload:  POST /api/workers/<hostname>/bot-reload {"wait_s": 230}   (x-gbox-actor: deploy)
             gbox/bot_control.py BotControl.bot_reload -> worker tool bot_reload (gbox/tools.py)
               -> gbox/hot_reload.py reload_bots(): plan, stage, stop, swap, start, settle
  restart: the existing path (MIN_RESTART_GAP, Hermes pause, idle check, systemctl restart)
```

**What reloads** (`hot_reload.allowed`): `gbox/mercs/**` (the engine, the title drivers `titles/re5_*`, `re4_gc`,
`round_map`, `stalemate`, `tactical`, ...) plus `gbox/mercs_bot.py`, `re4_merc_bot.py`, `re4_threats.py`,
`re4_menus.py`, `re4_ram_prompts.py`, `re4_navmap.py` and `re4_collision.py`. These `gbox/mercs` modules are excluded
(`NOT_BOT`) because their state or threads outlive a bot run:

- `warm_boot`: the warm pool's observers.
- `damage`: the worker-lifetime delivery thread.
- `directives`: the chat command store that the control plane writes.
- `teamplay`: team intent.
- `evidence_sync`, `round_reports`, `reviewer`: control-plane routes and threads.
- `titles/re5_eggs`, `titles/re5_live_weapon`: supply workers started by the re5_mods tool.

Everything else needs a restart: `server.py`, `screensaver.py`, `tools.py`, `adapters.py`, `store.py`, `mercmode.py`,
the `*_mods_tool.py` files, `profiles/`, `hermes/`, `gbox.toml`, `pyproject.toml` and `hot_reload.py` itself.

**The op, step by step** (`reload_bots`):

1. **plan.** Find the loaded bot modules whose source on disk differs from what this process loaded. That baseline is
   the worker's `build_sources`, which `worker.run` hands to `hot_reload.track` and which a reload keeps current. Add
   every loaded module that bound names from one of them at import time (a top-level `from x import y` that would keep
   the old objects). If such a module is not a bot module, the op refuses with `restart: true`. Reload order puts
   dependencies first, based on the new sources' top-level imports.
2. **stage.** Run each new source in a throwaway module object first. When it imports a module from the same reload, it
   gets the staged copy. A module that fails to import refuses the reload. No bot was touched.
3. **wait.** A MercMode round preparation still walking menus, or a bot still stopping, makes the op wait (`DRAIN_S`,
   90 s). If it is still busy after that, the answer is `retry: true` and nothing has changed. `hot_reload.GATE` holds
   new autoplay starts and preparations back while the swap runs (`tools.autoplay` enters it). The reload's own restarts
   still go through.
4. **stop.** Each running autobot on a bot playbook stops at its next tick. Its run releases its inputs, and
   `_release_all` releases them again. The old run's telemetry skips its final "stopped" report, so MercMode never sees
   a gap.
5. **swap.** `importlib.reload` each module in order. The stale `__pycache__` entry is dropped first. The state named
   in `KEEP` survives:
   - the RE5 roster and stage pick
   - the RE5 coverage / DJ request object
   - learned crossings
   - the RE4 DJ requests
   - the controls lock and the lessons lock

   A kept instance of a redefined class takes the new class and keeps its data. A module can add its own `RELOAD_KEEP`
   tuple. Any exception restores every module's old dict.
6. **start.** Start each bot again with its own `AutoplayIn` and its own job context, through `tools.autoplay`, the
   same start path as always. The x-gbox-parent-job header stays the run's accepted autoplay job, so
   `mercmode.successor_autoplay` / `accept_boundary` keep taking its native round boundaries. The round count lives in
   the control plane's run (`mercmode_rounds`) and is untouched. A bot is not restarted when autoplay was stopped
   (`_AUTOPLAY_STOPS`) or the player touched the pad during the reload. Its "stopped" telemetry is posted instead. A
   session whose bot did not come back (an unexpected start error) goes to F5's path from the route: `BotControl.ensure`,
   which calls `Screensaver.restart_bot` for a MercMode run.
7. **settle.** If a restarted bot dies with an error within `settle_s` (5 s), every bot is stopped again, the old
   modules are restored and the bots restart on them. The same rollback happens when the new code no longer matches the
   session's playbook.

**What the deploy does with the answer** (`hot_reload.verdict`):

| Answer | What deploy_main.sh does |
| --- | --- |
| `reloaded` | Done, no restart. |
| `busy` | Retried 4 times, 30 s apart. Then it touches `gbox-data/deploy-reload-pending` and the next `--deploy` retries. |
| `refused` | The new bot code does not import or died at once, and the old modules keep running. It touches the pending marker, logs and exits 1 with no restart, because a restart would load the same code. |
| `failed` | Covers no route, worker offline, a worker without `bot_reload`, or a change only a restart applies. It falls back to the restart path. |

`--no-restart` on a bot-only deploy touches the reload marker instead of the restart marker. A pending restart wins over
a pending reload. The server's `_lf_deployed` treats either marker as "not live yet".

**Cost.** The gap is the bot restart only: the stop at the next tick (≤ 0.25 s for the menu loop, one engine frame in a
round), the reload (well under a second, though `titles/re5_ps3.py` is about 4300 lines) and the playbook's start. The
start re-applies the profile's early ops at once and its playing ops at its first playing tick, then hands the round to
the engine mid-round, like an F5 restart. Expect 1 to 3 s on the Spark. This has not been measured live yet. The bot's
local stats (`run["live"]`) start fresh, as after F5.

**By hand:**

```sh
T=$(cat ~/gBox/system/gbox-data/api_token)
curl -s -X POST -H "Authorization: Bearer $T" -H "x-gbox-actor: deploy" -H "Content-Type: application/json" \
  -d '{"wait_s": 230}' http://127.0.0.1:8765/api/workers/lilspark/bot-reload
# or name modules: -d '{"modules": ["gbox.mercs.titles.re5_combat"], "wait_s": 230}'
```

Agents (`hermes`, `agent`, `mcp`) are refused (403). The worker side is the `bot_reload` tool. A worker running older
code has no such tool, and the route answers 409 ("bot changes go live there with a service restart").

The first deploy of this change itself needs one restart, because `server.py`, `tools.py` and `worker.py` changed.

## Part 2: game sessions that survive a gbox.service restart (design, not implemented)

Control-plane-only changes (routes in `server.py`, scheduling in `screensaver.py`) still restart the process. The goal
is a restart that costs a stream hiccup instead of a cold launch.

### Facts on the Spark (read-only, 2026-10-26)

- gbox.service has `KillMode=control-group`. Its cgroup holds the python main process, RPCS3 (`AppRun.wrapped`), every
  `Xvfb :9x`, the stream and recording `ffmpeg`s and the audio `parec`s, all direct children of the main PID in one
  process group.
- **Dolphin is not in that cgroup.** `flatpak run` puts it in its own user scope
  (`user@1000.service/app.slice/app-flatpak-org.DolphinEmu.dolphin-emu-<pid>.scope`). It dies with gbox only because
  gBox launches it with `flatpak run --die-with-parent` (bwrap's parent-death signal).
- `kernel.yama.ptrace_scope = 0`, so a new gbox process may read and write `/proc/<pid>/mem` of a surviving same-user
  emulator. That covers RPCS3 guest reads and the Dolphin MEM1 shm view.
- `Linger=yes` and the user manager runs, so `systemd-run --user` is available.
- Today a surviving emulator would **block** the new worker: `worker.run` refuses activation while `gbox-running.json`
  lists a live PID (`worker_results.protected_sessions`: "Worker activation held: a delivered native launch still has an
  owned PID record").
- Session detail already records `pid`, `display` and `debug_port` (Standalone adapters) or `port` (RetroArch). Part 1
  adds `display_pid`, the Xvfb process. The worker's `gbox-running.json` keeps each emulator's `linux_identity`
  (boot id + start ticks) against PID reuse.

### Design

1. **Detach the session processes.** Start each session's Xvfb and emulator as a transient **user service**:
   `systemd-run --user --unit=gbox-session-<sid> --slice=gbox-sessions.slice -p StandardOutput=append:<log> ...`. A
   service rather than a scope, because with a scope the emulator's parent would still be the gbox process and
   `--die-with-parent` would still fire. Drop `--die-with-parent` for Dolphin. Real stops become `systemctl --user stop
   gbox-session-<sid>`, with the existing `_kill_tree` as the fallback. Setting `KillMode=process` on gbox.service
   alone is the smaller step. It would keep RPCS3 and Xvfb alive, but not Dolphin. It would also leave a crashed
   service's encoders unmanaged, and `systemctl stop gbox` would no longer stop games, so it should not be the end
   state. Encoders (`MjpegStream` ffmpeg, `parec`, ring recording) stay children of gbox. They pipe into it and are
   rebuilt at adoption.
2. **Shutdown must not stop sessions.** It does not explicitly today, because the cgroup kill does it. Add a separate,
   explicit "stop all sessions" (`ExecStop` helper or a `gbox-sessions.target`) for when the operator really stops
   gBox.
3. **Re-adopt at startup**, in `worker.run` before the first claim, replacing the `protected_sessions` refusal:
   - Inputs: `gbox-running.json` (sid, pid, `linux_identity`) plus the control plane's running sessions of this worker
     name (detail: adapter, pid, display, display_pid, debug_port, game, serial / rpcs3 home, launch flags).
   - When the PID is alive and its identity matches, build the adapter without launching:
     - **RPCS3LinuxAdapter.adopt**: a pid handle with `poll()` from `/proc/<pid>/stat` and terminate/kill through
       `os.kill` after an identity check, plus `Display.adopt(name, pid)`. The guest base comes from
       `rpcs3_guest_base(pid)` again. Window focus is redone. The profile lease is re-acquired for this pid.
     - **DolphinAdapter.adopt**: the shm MEM1 view is found again by pid (`ram_dump.ShmRam`). Dolphin's GDB stub accepts
       its connection at boot and, as far as known, no second one, so writes go through `/proc/<pid>/mem` on the view.
       Breakpoints wait for a relaunch.
   - Rebuild the per-session runtime: stream (`MjpegStream` on the same display), audio capture, session pump and
     observers, rewind ring and recording. Then set `SESSIONS[sid]`. Report the session as adopted to the control plane.
   - Control plane: a restart registers a new worker id. Session ids keep the old prefix, and `worker_alias` already
     routes old ids to the new worker. Registration must not end adopted sessions. `screensaver._warm_owned` and
     `mercmode.warm_adoption_owned` must accept the aliased worker id. MercMode's STATE run and warm rows are in SQLite
     and survive. The playing title's bot comes back through `Screensaver.restart_bot`. Parked warm games stay paused.
   - Orphans: an alive PID whose adoption fails is stopped (process tree plus display) and its session ended. A dead PID
     ends the session as today. Both are identity-checked.
4. **Gate the scheduler.** The MercMode / screensaver loop and launches wait until adoption has finished. Otherwise a
   cold launch races the survivors, which means two emulators and a memory spike.

### Estimate

About 7 to 10 working days for one engineer, in 2 or 3 PRs:

- Detaching the processes (user services, Dolphin without `--die-with-parent`, logs, the stop path): 1.5 to 2 days.
- `adopt()` for RPCS3 Linux and Dolphin Linux (pid handle, `Display.adopt`, guest base / shm, focus, pause state,
  profile lease): 2 to 3 days.
- Runtime rebuild, control-plane aliasing, MercMode and warm pool re-attach, and replacing `protected_sessions`: 2 to 3
  days.
- Tests plus a live drill on the Spark (restart during MercMode, RE5 playing and RE4 warm): 1 to 2 days.

Part 1 already removes the restarts for bot-only fixes, the bulk of what happened on 2026-10-26.

### Risks

- **Dolphin's GDB stub** is single-connection. A warm (GDB-halted) Dolphin whose connection drops may stay halted with
  nothing able to resume it, or resume unseen. Verify before counting on warm-pool survival. The pause may have to move
  to SIGSTOP/SIGCONT.
- **RPCS3 profile lease and `generation`** live in the gbox process. A new launch must not take an adopted RPCS3's
  profile.
- **PID reuse.** Never adopt or kill without a matching `linux_identity`.
- **Lost in-memory state.** The control plane restarts in the same process and loses live stream buffers, bot telemetry
  (F5 liveness, MercMode boundary freshness), directives, pad state and in-server jobs. MercMode must not read "no
  telemetry yet" as "ended", and F5 must tolerate a quiet bot for the first seconds.
- **Encoders and audio** restart. Expect a few seconds of frozen picture or silence at adoption.
- **Operator semantics.** "Stop gBox" must still close the games, and the never-kill-the-operator's-game guard must
  survive the change.
- **Display numbers.** Adopted Xvfb lock files keep their numbers taken. Closing one must kill by the recorded
  `display_pid`, identity-checked.
