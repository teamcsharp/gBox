# Harness console and freeze reports

The PiP has a game-hooked console for model/harness work. It is the first place to look when a build freezes: it shows
the emulator's own log, the session's applied build and validation, the MercMode screen/phase, the active build jobs,
and a persisted freeze witness when the frame stops changing.

## The browser panel

`clients/web/viz/pip-harness-console.js`, loaded by `index.html`. It is a child of the PiP picture:

* **⌁ harness console** header: click to collapse; `✕` hides it and leaves a `⌁ console` pill that reopens it.
* **⌖** captures a diagnostic snapshot from the server.
* the feed combines:
  * `[game]` lines tailed from the session's Eden log;
  * `[runtime]` session/build/validation and MercMode phase/screen transitions;
  * `[rom]`, `[model]`, `[harness]`, `[runtime]`, `[ghidra]` lines from the active jobs;
  * `[freeze]` when the frame stops changing;
  * a spinner, progress bar, moving scanline and typewriter lines (disabled under `prefers-reduced-motion`).
* the frame watchdog fetches `/api/sessions/{sid}/frame.jpg` every poll, hashes length plus three bytes, and after
  7 unchanged polls (~10 s) in playing/loading/select, POSTs a freeze report and colours the feed red.
* the feed is bounded at 220 lines and de-duplicates repeated poll tails.

## Server routes

Added by `gbox/harness_console.py` (`install(app, store, config, auth)` in `server.create_app`):

| route | answer |
|---|---|
| `GET /api/sessions/{sid}/harness/console?after=N` | `{seq, lines, session, ghidra, freeze}`; `lines` are the new emulator/session lines after sequence `N` |
| `POST /api/sessions/{sid}/harness/probe` | session/overlay/validation, emulator log tail and Ghidra readiness |
| `POST /api/sessions/{sid}/harness/freeze` | writes `gbox-data/harness/freeze-<sid>-<stamp>.json` with the frame witness and the console tail |
| `GET /api/sessions/{sid}/harness/freeze` | the session's freeze reports |
| `GET /api/harness/ghidra` | whether the Ghidra Bridge can attach, and why not when it cannot |

The emulator log reader keeps a byte offset per `(session, log path)` and starts at the last 64 KiB, so attaching the
console does not dump an old boot log and polling does not repeat lines.

## Using it on a freeze

1. Open the PiP; the console appears over the picture. If the round is frozen, the frame watchdog writes a report and
   the feed shows the last `[game]` and `[runtime]` lines.
2. Press **⌖** for a probe. It returns the overlay/build, validation, the 12 KiB Eden log tail and Ghidra readiness.
3. The report is beside the console under `gbox-data/harness/`. It contains the frame witness (hash, unchanged
   seconds, screen) and the last 200 console lines.
4. For a model/loader question, use the Ghidra Bridge on the title's main ELF (see `docs/ghidra-service.md`).

## What this is not

The freeze report is a **witness**, not a save state: Eden provides no checkpoint primitive. It does not yet capture a
RAM witness automatically; the `⌖` probe is the manual hook point. The Ghidra side is static analysis of the title's
main; it is not a live gdb/ptrace hook into the emulator process.
