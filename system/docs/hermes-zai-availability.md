# Z.AI availability and favorites work

## Optional task supervision

The existing build supervisor supports `supervision_provider: "zai"` in
`hermes-dispatch/build-supervisor.json`. It pins GLM-5.3, reviews recent
Spark2 checkpoints, and leaves implementation guidance on existing requests.
The default remains Nous. The Tasks switch, single-run lock, 24-turn limit,
eight-minute run budget, and durable report delivery apply to either provider.

Z.AI supervision checks the operator's provider-scope policy before reading
the task snapshot and again before launching. It also requires a quota observation
no older than ten minutes, available inference windows, and a successful probe
from the existing availability watcher. A fallback to another provider blocks
launch. A public-source-only restriction must be explicitly lifted by the operator
before private task supervision can run; selecting Z.AI does not change that policy.

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
The no-agent watcher still rechecks the account endpoint every five minutes
while waiting or during a long run. It sends no inference probe while a known
quota is exhausted, and no additional probe while the work job is active.
This can detect quota reset cards or plan changes before a previously reported
deadline. Existing watcher state is migrated to the same cheap recheck cadence.
Exhausted MCP/tool windows do not incorrectly disable inference. Missing reset
metadata triggers a cheap five-minute quota recheck, instead of guessing another
five-hour delay. Authentication probe failures back off fifteen minutes.
Malformed or missing quota measurements remain unknown; nonfinite values and
opaque fields are excluded. An exhausted quota never triggers a completion. Success requires a real model
response before work is re-armed and the old route cooldown is cleared.
Model-probe 429 failures retain numeric business codes and observed Retry-After
metadata, and cool the route as well as the watcher. Quota codes 1308, 1310 and
1316–1321 are distinguished from transient request throttling. Unobserved retry
times are bounded scheduler backoff, never claimed account reset times. The
credential resolver restores its prior endpoint environment after the check.

The same work job is reused; queued/running occurrences are not duplicated.
Pending Ghidra/character analysis pauses further inference until it settles.
After each terminal session the watcher uses the shared finalized usage
accountant. It confirms ownership from successful tool receipts and records
measured primary and helper-model tokens, including caches, once on the report.
Existing tool counts, turns and elapsed time are preserved. The ordinary
feedback supervisor also runs this accountant even while another agent is busy
or every provider is cooling down. See `hermes-job-reliability.md` for evidence
and retry rules.
Global Hermes parallelism remains two. Native work uses durable gBox job IDs.

Unpinned request investigations also use the shared provider recovery queue in
`hermes_recovery`. Intentional Z.AI benchmark/work pins retain their existing
availability watcher instead of silently borrowing another service. A provider
failure checkpoint preserves the actual session and request ownership; it does
not invent a completion or token balance. See `hermes-throughput.md` for the
bounded failover rules and status fields.

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
