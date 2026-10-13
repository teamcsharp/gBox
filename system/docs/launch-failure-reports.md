# Launch failure reports

Operator rule: *when a game fails to load, file a report automatically, and get that report investigated and resolved
so games load fluidly.* `gbox/launch_failures.py` does this on the control plane. Nobody has to press anything.

```
failed launch ──> one ticket per signature ──> first remedy (where safe) ──> Hermes investigation (priority 1)
   (job / crash)    repeats = occurrences        recorded on the ticket        fix + draft PR with screenshots
                                                                                     │ PR merged, deploy has it
ticket closed with the frame <── verification launch on an idle node <─────────────────┘
ticket reopened with the evidence <── (failed)        operator launch that keeps running also verifies
```

## What counts as a failure

* A `launch_game` or `session_swap` job that ends `failed`, `invalid` or `rejected`. The result handler and the swap
  thread report it at once. A loop every minute also scans the last hour, which catches jobs failed by a worker restart,
  a timeout or a server restart.
* A session that the worker reports ended with a non-zero exit code within **60 s** of starting (`CRASH_WINDOW_S`).
  The launch "succeeded", but the game never really loaded. The worker sends the emulator's log tail with that exit.

The following are **not** reported:

* Jobs cancelled by the operator (`cancel`, or "cancelled by the operator" / "cancelled with its parent").
* Intentional stops: any `stop_game` job for the session, an exit with `via` (a single-game switch or a swap), or a
  replaced session.
* Agent test launches (`agent_use`: evidence captures, Hermes reproductions). Their own task reports these.
* Jobs that belong to an inbox request (`parent_request_id`).
* Examine 3D capture sessions.
* The launch that a session swap ran. The swap reports it, with that launch's evidence attached.
* The automatic remedy's own relaunch. Its result goes on the ticket that started it.

## One ticket per signature

Signature = `game_id + mod + adapter + error class` (`signature()`). The first failure files an inbox request with
`source: automation` and `context.launch_failure: true` (also `auto_report`, so it is a top-level inbox item). Its
title looks like this:

`Launch failed: Dead or Alive 2 (doa2_roster_59d8ed0e) on JAYBUILTFINALE: retroarch content not running after 30s`

A repeat adds an "Occurred again (N times)" reply with the new logs and does not create a second ticket. A repeat
reopens the ticket if the ticket was closed, or if the fix was already deployed and being verified.

Each ticket has these sections:

* **What failed**: game, mod, node, emulator, job, and when it failed.
* **Error**.
* **Diagnosis**: the error class and what it usually means.
* **Automatic remedy**.
* **Timings**: queue wait and run time, plus the worker's per-stage `timings` (from `launch-failure.json`).
* **Mod and staging**: the mod, the staged folder, `cached_on`, the staging receipt, and the stage the launch reached.
* **Previous session blocking the launch**: when a running game was in the way, its title, session id, emulator and
  state.
* **Session** and **Launch jobs the swap ran**: for swaps and crashes.
* **Logs**: the last lines of the job progress and of the emulator log.
* **Recent jobs on this node / for this game**.

The following files are attached:

* `job-progress.txt`.
* The worker's `worker.log`.
* `emulator-log.txt`: the worker attaches the emulator's log when `launch_game` fails, and RetroArch also puts its log
  tail in the error.
* `launch-failure-evidence.json`: every fact above, plus the catalog entry.
* The session's last frame (`last-frame.png`), if a crashed session had one.

## Error classes and first remedies

| Class | Recognised by | Automatic remedy |
|---|---|---|
| `previous_game_blocking` | "The previous game (X) could not be saved" | none. gBox never stops a running game; the ticket names the blocker |
| `content_timeout` | "started but content not running after Ns" | relaunch once with a 90 s boot timeout (`launch_game boot_timeout_s`) |
| `missing_bios` | BIOS / firmware / keys missing | none (the launch already installs known BIOS files) |
| `mod_fetch` | mod fetch / staging / hash / marker errors | re-stage the mod (`prepare_mod`, does not touch a running game), then relaunch once |
| `emulator_crash` | "X exited N", access violation, a crash within 60 s of starting | relaunch once |
| `missing_file` | ROM not reachable / FileNotFoundError | none |
| `worker_restarted` | worker or server restarted mid-launch | relaunch once |
| `worker_unavailable` | rejected: worker can't run it, outdated or offline | none |
| `state_restore` | a swap could not restore the saved moment | none |
| `timeout` | timed out | relaunch once |
| `unknown:<hash>` | anything else (grouped by the normalised error text) | none |

A relaunch happens only when all of the following are true:

* Remedies are on.
* The failure was a `launch_game` (a swap would replace the running game).
* The failure is at most 3 minutes old.
* The PC is online and runs no game.
* No other launch started on that PC or for that game since.
* This signature has not been relaunched automatically in the last 30 minutes.

When any of these is false, the ticket says why nothing was relaunched. Each attempt and its result is a reply with a
`task_step`. A relaunch that works does not close the ticket. It is evidence, and the investigation continues for a
permanent fix.

## Investigation

A new or reopened ticket is put first in the Hermes work queue's operator priority list
(`hermes_work_queue.set_priority`, under the queue lock) and is marked `in_progress`.

* With the managed work queue (`no_agent` controller), the queue's next tick dispatches it. The `inbox` item carries
  `launch_failure: true`, so its prompt is the launch failure task rather than the native character task. The verify
  loop then records the dispatched job id on the ticket ("Hermes work queue dispatched job …").
* With the legacy controller, the ticket is dispatched at once (`hermes_task_mode.dispatch_request(task=…)`), and the
  reply names the Hermes job id.

The task tells Hermes to:

* Read the ticket.
* Find the root cause.
* Fix it in code, with a focused test.
* Publish it as a draft PR with screenshots of the game loading (`evidence_capture` on an idle node).
* Never touch a game the operator is playing.
* Leave the ticket `in_progress`.

If Hermes cannot be reached, the ticket stays `open` and says so. The work queue picks open launch failure tickets up
on its next pass.

## Verify and resolve (the loop)

Every minute, each unverified ticket moves through these states:

1. **investigating**: waits for a "PR #N merged to main as <sha>" reply (posted by `hermes_merges.reconcile`).
2. **merged**: waits until the Spark's deploy carries the commit. That means `gbox-data/deployed-main.txt` contains it
   (`git merge-base --is-ancestor` in `~/gBox-src` or the Hermes repository) and there is no
   `deploy-restart-pending`. A machine with no deploy record verifies 45 minutes after the merge.
3. **awaiting_verify**: starts a verification launch of the same game and mod. This is an `evidence_capture` job
   (`inputs: []`, no saved moment, one shot 20 s after boot), which does the following:
   * It runs in an agent-owned test session at 2% volume.
   * It never uses a node with a running game or recent input.
   * It stops its own session.
   * It runs on the failing PC when that PC is idle (idle for at least 5 minutes, ticked for background testing, and
     running no game). Otherwise it uses any idle node.
   * Each of these defers the verification by 10 minutes: another capture is running, no node is idle, the capture
     yielded, or the server restarted.
4. **verifying**: a capture with a frame that is not black closes the ticket (`done`) with that frame attached. A
   failed launch or only black frames reopens the ticket with the error and frames, and queues the investigation again.

At any stage, an **operator launch** of the same game and mod also counts as verification, and closes the ticket with
its last frame. The launch must have started after the last failure and kept running for 60 s without a crash code.
Agent and evidence sessions do not count.

A closed ticket leaves the Hermes priority list.

## In the clients

The ledger stamps `launch_report = {request_id, number, status, state, verified, label, text}` on the newest failed job
and on the game's catalog entry. The Mods page builds carry `launch_report` from `launch_failures.index()`.

* **Desktop launch bar** (`clients/web/viz/launch-bar.js`): a failed launch's red line shows **Reported as #N, being
  investigated**, or **Fixed, verified (#N)** in green. The bar reads the failed job again after 2.5 s, 6 s and 15 s
  until the report is filed. A click on the badge opens the request in Requests.
* **Mods page cards** (web and desktop, `mods-gallery.js`): the failed build shows the same badge as a button. It
  opens the request (inline under the card on the web, in Requests on the desktop).
* **Web Library cards** show the badge after "launch failed: …". The web launch screen adds it to the failure line.
* **App-side auto reports** (`POST /api/requests/auto-mod-failure` with the failed launch/swap `job_id`) land on the
  same ticket as a reply with the app's screenshot. They do not open a second ticket. A failed `launch_game` is no
  longer also filed as "Auto report: launch_game failed".

UI evidence: `tests/fixtures/ui_evidence/launch_failures.json` (`python scripts/ui_evidence.py --clients clients
--fixtures tests/fixtures/ui_evidence/launch_failures.json --out <dir>`).

## API

| Call | What |
|---|---|
| `GET /api/launch-failures[?game_id=]` | tickets, newest first, with remedies, Hermes job, PR, verification; plus settings |
| `GET /api/launch-failures?job_id=<id>` | the report a launch job was filed under (or why it was skipped) |
| `POST /api/launch-failures/backfill {"days": 7, "dry_run": false}` | file the failed launches of the last N days, grouped the same way (no relaunches for old failures); `dry_run` lists the groups |
| `POST /api/launch-failures/tick` | run one verify-and-resolve pass now |
| `POST /api/launch-failures/settings {"auto_remedy", "investigate", "verify"}` | switch each stage off or on |

`GBOX_LAUNCH_FAILURES=0` disables the background loop. The immediate hooks and the API still work.

Store kinds:

* `launch_failure`: one record per signature, holding the ticket, occurrences, remedies, Hermes, PR, verify and
  verified fields.
* `launch_failure_job`: one entry per job id (or `session:<sid>`) once it has been handled or skipped.

Tests: `tests/test_launch_failures.py` covers classification, signatures and dedupe, skips, the crash window, the
blocker, remedies and their safety rules, the queueing call, the verify loop with fake jobs and sessions, backfill,
the server wiring and the Mods entry. `tests/test_launch_failure_badges.cjs` covers the launch bar badge and its
follow-up reads, the Mods card badge, and the wiring in both clients.
