# Browser automation lifecycle

All GBox headless test/evidence browsers use `scripts/browser_lifecycle.py`.
Node callers use `scripts/browser_lifecycle.cjs`; the earlier
`tests/build_report_browser.cjs` is a compatibility import. Install the `test`
extra for the Node harness's Python supervisor, or the `browser` extra for
Playwright evidence. `GBOX_BROWSER_PYTHON` selects that interpreter explicitly.

The per-user coordinator is `%TEMP%/gbox-browser-managed` on Windows, shared
across checkouts. A SQLite transaction admits a bounded number of sessions and
FIFO waiters. It applies backpressure rather than launching another browser
when its slots, queue, or memory admission budget are occupied.

Each lease has a new disposable profile, UUID ownership marker, client and
supervisor PID/creation times, browser identity, observed child identities,
resources and outcome. No user profile or existing browser is adopted. Node
tests reuse a page within their callback; Playwright screenshot batches reuse
one browser with a separate context per shot. Separate tests retain isolation.

On Windows the supervisor creates the browser suspended, assigns it to an
unnamed Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, then resumes it.
The handle is not inherited. Closing or crashing the supervisor terminates the
owned job hierarchy, including renderers that outlive their browser root. This
uses the documented [Windows Job Object lifetime behavior](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
Failure to assign the job aborts startup; there is no unprotected fallback.

The client owns a stdin lease. EOF, explicit close, client death (PID and creation
time checked independently), cancellation, signals and deadlines all cause
cleanup. CDP requests reject on timeout/socket close; callbacks have a lifetime
deadline. The supervisor force-closes its owned tree after graceful close.
The profile is removed only under the managed profile directory, with a matching
marker and no live recorded processes. If Windows kills both client and
supervisor, the kernel still closes the browser job; the next lease recovers
the remaining disposable profile. Cleanup failures remain visible in the registry.

POSIX uses a dedicated process group on normal cleanup/client loss. A supervisor
itself killed with SIGKILL has no Windows kernel job guarantee: a still-live
registered browser is detected as an orphan and occupies its quota, preventing
unbounded replacements. This repair's hard supervisor-crash guarantee and test
are specifically for Windows.

Sandboxing is enabled by default, including real Windows Edge tests. The earlier
Node helpers passed `--no-sandbox` unconditionally without a recorded requirement.
Playwright's own Chromium launch defaults also disable its sandbox unless opted
in ([official launch API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox));
the evidence tool now connects to our already sandboxed managed browser instead.
Only an explicitly configured non-Windows environment may set
`GBOX_BROWSER_NO_SANDBOX=1`, together with a nonempty
`GBOX_BROWSER_NO_SANDBOX_REASON` documenting its container restriction. Windows
rejects that setting. Startup failure never silently retries without a sandbox.

Debugging uses an ephemeral port bound to `127.0.0.1`, a private disposable
profile, and a validated local websocket target. The manager does not expose
CDP on the LAN or use a fixed shared port. CDP is privileged: local same-user
processes can access the endpoint while its lease is active.

| Setting | Default | Purpose |
| --- | --- | --- |
| `GBOX_BROWSER_MAX_SESSIONS` | 2 | Modest parallel UI tests without one browser per test worker |
| `GBOX_BROWSER_MAX_QUEUE` | 4 × session limit | Bounded pending work |
| `GBOX_BROWSER_QUEUE_TIMEOUT_S` | 120 | Admission deadline |
| `GBOX_BROWSER_STARTUP_TIMEOUT_S` | 30 | Browser startup deadline |
| `GBOX_BROWSER_TIMEOUT_S` | 600 | Maximum lease/callback lifetime |
| `GBOX_BROWSER_RPC_TIMEOUT_MS` | 30000 | Node CDP request deadline |
| `GBOX_BROWSER_BUDGET_MB` | smaller of 2048 MB or 10% of RAM | Additional-session memory backpressure |
| `GBOX_BROWSER_SESSION_MB` | 0 (disabled) | Optional hard memory limit for a single owned tree |
| `GBOX_BROWSER_STATE` | per-user temp coordinator | Explicit pool override; keep consistent across production callers |
| `GBOX_CHROME` | installed Edge/Chrome or bundled Chromium | Browser executable |

The defaults fit the measured UI workload (under 0.8 GB sampled aggregate working
set per session in the Windows soak). Larger legitimate workloads may configure
the limits. The memory budget governs admission; it is not a global hard RSS cap.
Only a configured per-session hard limit terminates that session for excess memory.
The coordinator records RSS, sampled peak RSS/handles, cumulative CPU time and
process identities. `events.jsonl` rotates at 1 MiB with three backups. Historical
lease records remain available in `leases.sqlite3`.

Read-only diagnostics:

```powershell
python scripts/browser_lifecycle.py status
python scripts/browser_diagnostics.py --out browser-inventory.json
```

Safe legacy orphan cleanup, after reviewing the inventory:

```powershell
python scripts/browser_diagnostics.py --close-orphans --out browser-cleanup.json
```

That command rechecks executable, same user, headless root, exact legacy
`gbox-tk-*`/`gbox-72-*` profile directly under the current user's Temp directory,
dead/reused parent PID, and creation times. It closes only that root and its
same-profile descendants. It preserves **all legacy profile contents**. It
never kills Edge by name, touches Electron/user browsers or stops GBox jobs.
Update older checkouts before running their browser tests: pre-fix code does
not call this manager.

Validation commands (Windows):

```powershell
python -m pytest tests/test_browser_lifecycle.py tests/test_browser_diagnostics.py tests/test_ui_evidence.py -q
node --test tests/test_browser_lifecycle.cjs tests/test_tasks_scroll.cjs tests/test_chat_conversation_composer.cjs tests/test_build_report_image.cjs tests/test_mod_sort_preview.cjs
$env:GBOX_BROWSER_SOAK_CYCLES='20'
$env:GBOX_BROWSER_LONG_TEST_MS='30000'
node --test tests/test_browser_lifecycle.cjs
```

The crash tests kill only child workers/supervisors created by those tests. They
check process identity, profile recovery, queue serialization, timeout/cancel,
task failure, missing browser executable and optional memory-limit enforcement.
