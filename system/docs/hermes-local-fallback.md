# Hermes local fallback and the Spark helper

Operator instruction (2026-10-13): when Hermes runs out of credit online, keep it working on the local model,
running tools and dispatching tasks from the inbox, and use the Spark for any grunt work that helps Hermes.

This has three parts:

1. **A GPU local route** (`spark-local`). It is Hermes's last resort. The route supervisor switches to it only when
   every paid route is cooling down or out of credit, or when the operator sets *local only*. It switches back by
   itself as soon as a paid route recovers.
2. **A proxy in the gBox service** in front of the Spark's Ollama (`/api/llm/local/v1`). It fixes message shapes,
   runs one call at a time, gives way while the operator plays on the Spark, fits the context and logs tokens.
3. **The Spark helper** (`/api/grunt`). It runs LLM-free chores at idle priority, one at a time, and stops when
   the operator plays on the Spark or a build runs.

The CPU-only llama.cpp route (`llamacpp`, Qwen3.6-35B-A3B on the CPU) stays excluded
(`hermes_quota.EXCLUDED_PROVIDERS`). Nothing here starts the llama.cpp server. `EhmBird` also stays excluded: the same
Ollama models are now reached through the proxy, which fixes EhmBird's failure (below).

## The local route

| | |
|---|---|
| Provider | `spark-local`, a Hermes custom provider (OpenAI-compatible) |
| Endpoint | `http://127.0.0.1:8765/api/llm/local/v1`, served by the gBox service on the Spark |
| Model | `gpt-oss:20b` by default (`[hermes.local] model`) |
| Code | `gbox/hermes_local.py` (policy), `gbox/hermes_feedback.py` (`adjust_routes`) |

### Default model: gpt-oss:20b

The default is `gpt-oss:20b`:

- It is the best tool caller among the Spark's Ollama models. It was trained for function calling, and Ollama
  returns its tool calls natively. Earlier `usage_audit` runs through Ollama completed on it.
- It is fast on the GB10. As a mixture of experts it has 21B weights, of which about 3.6B are active per token, in
  MXFP4. Generation runs at several times the speed of a dense 27B model on the Spark's 273 GB/s unified memory.
  Prompt prefill is much faster too, and that matters because Hermes prompts are long (system prompt plus MCP tool
  schemas).
- It supports a 128k context. The proxy asks for 64k (`context_tokens = 65536`), which leaves room for Hermes's
  prompt and stays small next to a streamed game: about 13 GB of weights plus a few GB of KV cache.
- It has a think level (low, medium, high). Local runs use `medium` to save time.

The alternative is `qwen3.8:27b-mtp-q4_K_M`. It is dense 27B, slower, and its chat template caused the EhmBird 500s.
The proxy fixes those, so it can be selected with `model = "qwen3.8:27b-mtp-q4_K_M"`. The `gemma4` models also work,
but they are weaker tool callers.

### When it is used

`hermes_feedback.adjust_routes` is the route supervisor, a Hermes cron script that runs every 5 minutes. It calls
`hermes_local.choose(paid_routes, cooldowns, ...)`:

- **paid**: at least one paid route is not cooling. The supervisor rotates among the paid routes as before. The
  local route is never put in a paid route's `fallback_providers`, so a paid run never finishes on the small model.
- **local**: every paid route is cooling (quota, out of credit, usage limit) or the operator set local only. Cron
  runs on `spark-local` alone (`fallback_providers: []`).
- **back to paid**: as soon as a paid route's cooldown ends, the next supervisor pass rotates to it. That happens
  only between agent runs: a running local run keeps its route. The supervisor also checks OpenRouter's credit
  endpoint while an OpenRouter route cools under a scheduler backoff. A positive balance observed after the failure
  ends that cooldown early (`_lift_recovered_credit`). A provider's measured reset time is never lifted.
- Failed paid runs are never resumed on the local route (`hermes_recovery.recover`). Emulation root-cause
  investigations are not dispatched in local mode (`hermes_task_mode.dispatch_request` refuses). Their reports stay
  in the queue for a paid route.

`feedback.json` records `local_mode: {active, reason, since, next_paid_at}` for the status views.

### Hermes config the supervisor sets

The supervisor changes these keys with `hermes config set`, the existing route mechanism, and only when they differ:

| Mode | Key | Value |
|---|---|---|
| local | `custom_providers` | The existing list plus `{name: "spark-local", base_url: "http://127.0.0.1:8765/api/llm/local/v1", api_key: "gbox-local", model: "gpt-oss:20b"}`. An existing EhmBird entry is used as the shape template, without its key. Other entries are kept unchanged. This is set once. |
| local | `cron.model_provider` | `spark-local` |
| local | `cron.model` | `gpt-oss:20b` |
| local | `fallback_providers` | `[]` |
| paid | `cron.model_provider` / `cron.model` | The chosen paid route |
| paid | `fallback_providers` | The other paid routes that are not cooling (never `spark-local` or `llamacpp`) |

`api_key: "gbox-local"` is a placeholder. The proxy accepts loopback callers without the gBox token, so no secret is
written into Hermes's config. Any other caller needs the token.

### Local only

To make Hermes use only the local route, use either of these:

- `POST /api/hermes/local {"local_only": true}`. This writes `<dispatch state>/local-mode.json`, and the supervisor
  applies it on its next pass.
- `[hermes.local] local_only = true` in `gbox.toml`.

`GET /api/hermes/local` shows the model, whether Hermes is on the route now and why, and the proxy's counters.

## The proxy (`gbox/llm_proxy.py`)

| Endpoint | Purpose |
|---|---|
| `POST /api/llm/local/v1/chat/completions` | Chat completions, streaming or not. Tool calls pass through both ways. |
| `GET /api/llm/local/v1/models` | The model and its context length, for Hermes's context detection. |
| `GET /api/llm/local/status` | Gate, queue and totals. The Hermes queue tick reads it. |

Each call goes through these steps:

1. **Operator gate.** While the operator plays a game on the Spark (a running session on the Spark's worker that is
   not an agent's test session), the call gets `503` with `Retry-After: 120`. The first refusal also asks Ollama to
   unload the model (`keep_alive: 0`), which frees the GPU memory for the game.
2. **One at a time.** Calls queue for a single slot, up to 8 waiting (`queue_limit`) and up to 15 minutes
   (`queue_wait_s`). Beyond that they get `503`. The gate is checked again after the wait. A caller that went away
   while queued is skipped.
3. **Message fixes** (`fix_messages`):
   - `developer` becomes `system` and `function` becomes `tool`. Unknown roles become `user`.
   - Several leading system messages are merged into one.
   - A later system message becomes a `[system note]` user message, because Qwen templates reject a system message
     that is not first.
   - List content is flattened to text. Images are named, not sent, because the model reads text only.
   - When no user query exists, a `Continue.` user turn is added. **This is the EhmBird failure.** Qwen's template
     raises *"No user query found in messages"* (HTTP 500) when a compacted cron conversation holds only
     system/assistant/tool messages. The turn goes right after the system prompt when the conversation ends in a
     tool chain, so call, results and next step stay adjacent. It goes last when the conversation ends with a
     finished assistant reply.
4. **Context cap** (`cap_context`). The prompt is estimated at 3 characters per token and fitted to
   `context_tokens - max_output_tokens - 512`:
   - The system prompt and the task's first user message are kept.
   - The oldest turns are dropped whole: an assistant tool call and its results go together.
   - A note in the system prompt says how many messages were left out.
   - If one message is still too large, the longest contents are cut in the middle, tool results first.
5. **Ollama native API.** The call goes to `/api/chat`, because Ollama's OpenAI-compatible endpoint cannot set
   `num_ctx` and would silently cut a long Hermes prompt to Ollama's default context. The request and answer are
   translated, streaming included:
   - Tool-call arguments become JSON objects on the way to Ollama and JSON strings on the way back, with `call_` ids.
   - Tool results carry `tool_name`.
   - Thinking is returned as `reasoning_content`.
   - Usage is reported in the final chunk.
6. **Log.** One line per call goes to `<dispatch state>/local-llm-calls.jsonl`, rotated at 4 MB. It records tokens in
   and out, queue wait, duration, fixes, trimming, tool calls, and refusals.

## What the local model is given (`hermes_work_queue.tick`)

On the local route, the queue changes its dispatch:

- **Capacity 1.** It also does not dispatch while the proxy reports the operator gate (`waiting_for_operator`).
- **Small tasks only** (`hermes_local.dispatch_size`):

  | Small | Large (stays queued for a paid route) |
  |---|---|
  | Favorite inventory stages | Native character replacement and repairs |
  | Tickets whose text names a narrow fix: one file, labels, tooltips, docs, tests, logs, config, inventories | Session observers |
  | | Favorite analysis, reader, writer and runtime stages |
  | | Tickets naming reader, writer, emulation, Ghidra, rig or similar work, or more than two files |
  | | Long tickets |
  | | Tickets with three or more attempts |

  A request can force either size with `context.hermes_size = "small" | "large"`.
- **A tighter prompt** (`hermes_local.local_prompt`): a 20-tool-call budget with the last 6 reserved (paid runs get
  45 and 10), at most one source file plus its test, reads of 80 lines or fewer, and an explicit way out. If the work
  turns out large, the run posts its findings and stops, and the ticket waits for a paid model. The reasoning effort
  is `medium`.
- **Marked PRs.** A run dispatched on the local route publishes a **draft** PR carrying the `local model` label, with
  a body headline that names the model and a test summary (for example *Test summary: 12 passed, 1 skipped*).
  If an existing PR is updated by a local run, it is put back to draft (`hermes_delivery._mark_local`).

## The Spark helper (`gbox/spark_grunt.py`)

The helper is a registry of chores with per-chore cooldowns. It runs one chore at a time in one thread at nice 19
and idle I/O class, and subprocesses run through `nice`/`ionice`. It runs only when the Spark is free: no game the
operator plays on the Spark, and no build job running. A chore checks `give_way()` between steps. When the Spark
becomes busy, the chore stops and the job it submitted is cancelled. The helper starts with the service on the Spark
(Linux) after a 3-minute delay. It never calls a model, merges a PR, or starts a game on the operator's PC.

| Chore | Cooldown | What it does |
|---|---|---|
| `triage_inbox` | 10 min | Classifies new open requests (launch failure, crash, regression, character, UI, feature). It notes likely duplicates and related failed jobs on the request. Urgent kinds go into the queue's `triage_priority`, which always ranks after the operator's own priority list. The first pass only records the backlog. |
| `draft_pr_tests` | 30 min | Takes the oldest open Hermes draft PR whose head was not tested. It fetches the head into a detached scratch worktree, runs the focused tests (the changed test files plus `tests/test_<changed module>*.py`), and posts the result on the PR and its request. It never merges. |
| `fingerprints` | 30 min | Runs one `assimilate op=fingerprint` job for a favorite queue game without a usable fingerprint, and stores the result on the queue item. |
| `character_readiness` | 6 h | Runs `characters op=readiness`: the replacement readiness and compatibility index backfill. |
| `collect_characters` | 1 h | Runs one `characters op=collect` for a favorite or recently played game that has a registered reader and no collection. |
| `mod_manifests` | 2 h | Writes SHA-256 manifests of built mod folders to `gbox-data/built_mod_manifests/`. It skips unchanged markers and hashes at most 4 GB per pass. |
| `warm_indexes` | 30 min | Rebuilds the asset, character and built-mod indexes ahead of use. |
| `hot_cache` | 1 h | Queues recently played and favorite games for promotion to the hot cache tier. Moves happen only when the node is idle. |
| `verify_launch_fixes` | 1 h | For a launch-failure ticket resolved in the last 14 days, runs one `evidence_capture` on an allowed node and posts the result on the ticket. Allowed nodes are `i9-NUC` and the Spark, each only when online, ticked for background testing, idle (Windows: 15 minutes without input) and not running a game. `JAYBUILTFINALE` and `GBOX_OPERATOR_WORKER` are never used. |

Status and control:

- `GET /api/grunt` returns the current chore ("Spark helper: testing a Hermes draft PR"), why the helper waits, and
  each chore's last result, error count and next run.
- `POST /api/grunt {"enabled": false}` pauses the helper. `{"run": "<chore>"}` makes a chore due now; it still waits
  for an idle Spark.
- In `gbox.toml`, `[hermes.grunt]` sets `disabled = [...]`, `cooldowns = {chore = seconds}`, `verify_nodes` and
  `never_nodes`.

## Status in the Tasks window

The Providers strip (Visual tab) and table (Technical tab) show:

- **A local-mode banner.** It reads *"Hermes is on the local model"* with the reason and the next paid retry, or
  *"Local fallback ready"* on standby. It also shows the model, model calls, tokens, runs served, calls held while
  the operator played, and calls trimmed to fit.
- **The `spark-local` route card.** It carries the *local model* tag, with calls, tokens and runs, read from Hermes's
  agent log and the proxy log.
- **The Spark helper card.** It shows *"Spark helper: doing X"* or why it waits, and the last finished chore. The
  Technical tab adds a table with every chore's last run and result.

`GET /api/hermes/providers` carries the `local` and `grunt` blocks.

## Configuration (`gbox.toml`)

```toml
[hermes.local]
enabled = true
model = "gpt-oss:20b"            # or "qwen3.8:27b-mtp-q4_K_M"
context_tokens = 65536
max_output_tokens = 8192
reasoning_effort = "medium"      # gpt-oss think level when a call names none
local_only = false
queue_limit = 8
retry_after_s = 120              # Retry-After while the operator plays on the Spark
tool_budget = 20

[hermes.grunt]
enabled = true
disabled = []                    # e.g. ["verify_launch_fixes"]
verify_nodes = ["i9-NUC", "spark"]
never_nodes = ["JAYBUILTFINALE"]
```

## Tests

| File | What it covers |
|---|---|
| `tests/test_hermes_local_route.py` | Route eligibility, rotation back, local only, credit recovery, the supervisor's Hermes config writes, `llamacpp` exclusion, recovery never using the local route, and the Providers view's local block |
| `tests/test_llm_proxy.py` | Message fixes (including the EhmBird case against Qwen's template rule), context cap, tool calls both ways, streaming, concurrency 1, a full queue, the operator gate with model unload, and the endpoint with loopback and token auth |
| `tests/test_spark_grunt.py` | The registry (one chore per tick, cooldowns, persistence, force, disable, give-way, errors), the build and operator gates, triage, draft PR tests, verification node rules, job cancel on give-way, fingerprints, manifests, and the `/api/grunt` endpoint |
| `tests/test_hermes_local_dispatch.py` | The dispatch size policy, the local prompt, PR marking, and local-mode queue ticks |
| `tests/test_hermes_providers_view.cjs` | The local banner and the Spark helper card |
