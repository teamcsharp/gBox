# Z.AI availability and favorites work

The 2026-10-10 operator request supplied a 16:48 America/Chicago reset hint.
An actual account check already reported 2,000 five-hour credits remaining,
and GLM-5.3 accepted a completion with 15 prompt tokens and one output token.
Hermes work was dispatched from those observations, rather than waiting on the
old estimated five-hour cooldown. The live run then began extracting the owned
Dead or Alive 2 Limited Edition disc for executable/Ghidra analysis.

## Persistent jobs

- `188280e74890`: gBox Z.AI availability and work pump, every two minutes,
  `--no-agent`, script `~/.hermes/scripts/gbox-zai-availability.py`.
- `fe4aa883825e`: Z.AI favorites Ghidra and inbox #1135, a reusable genuine
  one-shot pinned to `zai / glm-5.3`, high reasoning, with previous-run continuity.

The watcher imports `gbox.hermes_availability` with Hermes's own bootstrap and
credential resolver. It does not copy keys into gBox, worktrees or reports.
It uses only the Coding Plan endpoint
`https://api.z.ai/api/coding/paas/v4`. Configuration and state survive reboot.

Observed account quota comes from the authenticated
`https://api.z.ai/api/monitor/usage/quota/limit` endpoint. This monitor endpoint
was tested against this account; its public compatibility is not assumed.
If it stops supplying usable quota data, the watcher checks availability with
one bounded completion and backs off on failure. It does not route a subscription
failure to a paid generic API endpoint.

Credit/token windows gate inference. An exhausted five-hour or weekly window
waits for the reported epoch-millisecond reset; both must be available.
Exhausted MCP/tool windows do not incorrectly disable inference. Missing reset
metadata triggers a cheap five-minute quota recheck, instead of guessing another
five-hour delay. Authentication probe failures back off fifteen minutes.
An exhausted quota never triggers a completion. Success requires a real model
response before work is re-armed and the old route cooldown is cleared.

The same work job is reused; queued/running occurrences are not duplicated.
Pending Ghidra/character analysis pauses further inference until it settles.
After each terminal session the watcher retains actual request ownership and
records its measured tokens, caches, API/tool counts and elapsed time once on
the primary report, respecting the session marker and prior reported usage.
Global Hermes parallelism remains two. Native work uses durable gBox job IDs.

## Work and acceptance

Each reasoning run reads the current favorites and inbox, advances one concrete
reader/writer or retargeting step, reuses analysis and saved patches, and reserves
its final calls for focused checks, publication and an honest checkpoint.
Initial priority is #1140, the native writer missing from favorite DOA2, including
the Amy Rose pick-whip failures. #1135 is the broader favorites/decompilation
request. Executables are extracted and hashed from owned discs; Ghidra output,
addresses, xrefs and uncertain format assumptions must be preserved as evidence.
ROM bytes and bulk decompilation artifacts are not staged into Git source PRs.

i9-NUC stays protected. Windows testing targets JAYBUILTFINALE at 2% volume,
preserving any existing game. Screenshots document real visual milestones.
An overlay, decompiled C, or a draft PR does not verify an in-engine swap.
Gameplay reports remain unfinished until deployment and saved-moment acceptance.

## Verification

Fourteen focused availability/feedback checks passed on Windows and Spark.
They include the observed credit payload, weekly reset gating, missing metadata,
failed completion despite a successful quota query, duplicate dispatch refusal,
pending native analysis, secret-free exception reporting, and actual SQLite
session usage/ownership with cache totals and idempotent metric recording.
The account's quota GET, model completion, persistent watcher, and actual
GLM-5.3 tool-using Hermes run were separately verified on Spark.

Official reference: [Z.AI Coding Plan FAQ](https://docs.z.ai/devpack/faq) and
[Z.AI error codes](https://docs.z.ai/api-reference/api-code). Live account
observations determine availability; token totals do not predict credit quota.
