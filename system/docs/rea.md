# REA integration

gBox integrates the complete **139-operation REA 6.0.0 catalog** from
[morluto/rea](https://github.com/morluto/rea), not a reimplementation or a subset.
Every upstream operation is a typed, audited worker job named `rea_<upstream_name>`.
The registry, Tools view, HTTP job API, external gBox MCP and in-app LLM can all
discover and dispatch these jobs. Original input contracts, output validation,
effects, examples, observations, inferences and unknowns are retained.

## Installation and configuration

Run `python -m gbox rea-install` on each worker, or use normal `gbox setup`.
This installs only `rea-agents@6.0.0` and its npm dependencies under
`<worker runtime>/rea`. It never runs upstream's agent-registration wizard,
changes Codex/Claude settings, or installs unrelated applications. Node must
match REA's supported versions: ^22.19, ^24.11 or >=26. Installation is idempotent.
The installed package version must match the shipped catalog; mismatches are
reported unavailable, rather than silently using another interface.

gBox automatically passes the worker's existing Ghidra installation and local
JDK 21 to REA. Other existing providers can be configured in TOML:

```toml
[rea_env]
REA_ANALYSIS_PROVIDER = "auto"
# GHIDRA_INSTALL_DIR = "/absolute/path/to/ghidra"
# REA_IDA_MCP_CONFIG = "/absolute/path/to/ida-config.json"
# REA_ILSPY_CMD_PATH = "/absolute/path/to/ilspycmd"
# REA_WAKARU_COMMAND = "/absolute/path/to/wakaru"
```

Provider environment values are passed to the process, not written into
artifacts as an ambient environment dump. See upstream's installation/provider
guides for the rest of its supported environment settings. Ordinary gBox
permission gates remain in force: process launch requires `execute`, external
network access requires `network`, filesystem writes require `file_mutation`,
and target changes require `memory_write`. These are derived from upstream's
explicit effect audit. Grant a needed permission through normal deployment
configuration before using a tool that requires it.

## LLM and API usage

The in-app model first calls `rea_tools(query="javascript")`, then
`rea_tools(name="analyze_javascript_application")`. Exact discovery provides
the input contract and activates the native `rea_analyze_javascript_application`
function for the next model turn. This avoids putting 139 large schemas into
every prompt. It can also call the same tool through:

```json
{
  "name": "rea_analyze_javascript_application",
  "input": {"input_path": "C:/path/to/app", "format": "auto"},
  "node": "windows"
}
```

This is an in-app `run_tool` call. Public HTTP dispatch uses the normal API:

```json
{
  "tool": "rea_open_binary",
  "input": {"path": "C:/path/to/game.exe", "provider_id": "ghidra"},
  "require_worker": "your-worker-id",
  "parent_request_id": "the-original-request-id"
}
```

Use worker-local absolute paths. For console games, existing `re_executable`
extracts/wraps the game executable with its CPU/load addresses. Existing
`analyze_binary` and `ghidra_script` remain available for architectures outside
the REA provider's verified support.

gBox MCP exposes `job_rea_<name>` with the envelope
`{"input": <original REA arguments>, "require_worker": "...", "parent_request_id": "..."}`.
The envelope keeps routing fields outside strict and union upstream schemas.
`rea_resources` forwards upstream prompt/resource calls; REA 6.0.0 supplies six
workflow prompts through `prompts/list` and `prompts/get`. Unsupported resource
methods preserve the original MCP error rather than pretending they exist.

## Stateful analysis and evidence

### Requests against a running game

The desktop request bar captures one session, catalog title, mod and worker
snapshot for both conversation selection and submission. Requests to change a
game are attached to that exact session through its runtime RPC. Ended sessions
are reported instead of silently redirecting a request to another game on the PC.

The agent checks published controls first. If its proposed answer has no verified
live result, `live_research` captures the actual running guest image through
`re_executable source=ram`, retaining session/build/worker provenance. Related
REA and Ghidra jobs use the capture's analysis worker and guest image. SH-4,
MIPS and PowerPC use Ghidra's explicit guest processor; a REA capability check is
not reported as attachment to those unsupported native-provider architectures.
The host emulator executable is never substituted for the guest game.
Subsequent Ghidra queries pin the captured path and loaded-file SHA-256 in one
serialized server operation. Changed targets and old bridges that lack the
guarded protocol fail before scripts or queries execute. The older `re_agent`
path is not used for live requests until it forwards those target guards.

Live capture checks the running adapter's RAM capability and CPU mapping before
submitting extraction. RAM capture and explicit code-analysis jobs hold the cache
busy guard without promoting the game's ROM/mod unit to the fast drive. A live
request cannot fall back to disc unpacking after an unsupported RAM read. Within
one authenticated turn, repeated research reuses its captured image after checking
the analysis worker and the exact loaded Ghidra program. If another conversation
replaced that program, the same captured ELF is reopened. A new turn clears these
pins and authenticates its own target.

The verified DOA3 native memory provider supplies its Xbox x86 layout dynamically.
Its default analysis capture is the bounded loaded executable image, with the
verified guest entry point, rather than the whole 64 MiB heap. Other Xbox adapters
remain unsupported until they expose an equally verified guest-memory mapping.

Favorite unlock research carries persisted `idle_only`, `no_rom_copy` and
`no_automatic_launch` request limits. Attributed jobs are checked at submission
and again before a worker claims them; activity defers queued work. The agent
also checks wrapped and learned calls before execution. This scope permits
existing ELF analysis and bounded read-only queries, not arbitrary scripts,
ROM/build writers or automatic gameplay sessions. Existing ordinary build and
operator actions retain their original permissions.

RAM captures are non-atomic observations, not immutable executable revision
fingerprints. Their content-addressed images and findings remain separate from
the base title's executable metadata. The session is checked before and after
capture and again before later live operations. Existing job permissions apply.

Progress reports attachment, research, application and verification from actual
operations. Analysis alone, assistant prose, a raw write or a screenshot cannot
complete a live-change request. Broad unlock goals additionally require runtime
coverage of every requested content category. Missing implementations remain
in progress with a durable research handoff; provider or permission failures
retain their diagnostics. This workflow does not guarantee an instant patch
for every game or unsupported revision.

Each worker owns a long-lived, serialized REA MCP process. Keep related calls
on the `worker_id` returned by the first job: open a target, inspect functions,
trace relationships, compare captures, and verify reconstruction there.
The in-app agent remembers this worker automatically; explicit `node` or
`worker_id` overrides it. Parallel operations on the same session wait up to
30 seconds, then report busy rather than executing after their job has expired.

Every operation preserves the **complete original MCP result** as
`rea-result.json`, with its hash, worker, job, upstream version and operation.
The control plane independently verifies the artifact identity/hash and
upstream structured output schema before accepting the job. Upstream errors
produce invalid jobs with their original diagnostics and artifact retained.
They never become successful analyses. Large results remain in the artifact
even when the LLM's inline context is shortened.
Use `read_rea_result(sha256=<evidence_sha256>, pointer="")` to list root keys,
then navigate with RFC 6901 JSON Pointer, such as
`/result/structuredContent/result`. Lists and keys paginate with `offset`/`limit`;
strings return 6000 characters per page. Oversized list elements retain their
exact pointer so they can be inspected without silently skipping them. The
reader verifies the original artifact's content hash before selecting data.
Inline job output is bounded to 32 KiB; `_gbox_truncated` and
`_gbox_full_result` identify excerpts. This prevents large application graphs
from being repeated in every job/worker poll. The validator checks the complete
artifact, not the excerpt. Evidence is never discarded to meet the inline cap.

Use `rea_export_evidence_bundle` and `rea_import_evidence_bundle` to persist
evidence and unknowns across worker restarts. A transport crash/timeout loses
in-memory state and is reported explicitly; gBox never silently retries the
operation on a fresh target. Timeouts and cancellation close the owned REA
process. Provider cleanup is requested via EOF before terminating it. No
existing user-owned application is killed by the bridge.

## Coverage and actual verification

The complete upstream feature surface is integrated: native inspection and
decompilation, strings/calls/references/annotations, artifact graphs, managed
assemblies, Android, firmware, EVM, JavaScript/Electron, browser/network/runtime
observations, source recovery, evidence bundles, unknown tracking, comparison,
reconstruction obligations/coverage and reconstruction verification.
Integration is not a claim that every provider runs on every host or supports
every game architecture.

REA 6.0.0 itself restricts Wakaru source recovery to Linux x64, native Windows
PTY process capture is unavailable, and macOS inspection requires macOS tools.
The current live workers are Windows x64 and Linux arm64. Missing commercial
Hopper/IDA, ILSpy/JADX, browser-debug endpoints or other optional providers
continue to report their upstream requirements. No macOS/Linux x64 worker was
invented to hide these limits.

Real verification includes all 139 advertised input contracts matching the
running package, JavaScript analysis, artifact inspection, native Windows PE
Ghidra decompilation with an unchanged input executable hash, persisted unknowns
restored from an exported bundle, Linux arm64 PTY process captures and comparison,
and reconstruction verification. Matching terminal output still reports broader
unresolved environment/process assumptions; gBox preserves that `unknown`
result instead of treating it as proof of equivalence. Unsupported source
recovery is explicitly tested as invalid with its evidence retained. The LLM
discovery/activation and worker-affinity loop uses a deterministic model fixture;
it does not consume a paid model call.

Run `python -m pytest tests/test_rea.py -q` on the corresponding installed workers.
Host-specific lanes skip explicitly on other hosts. Regenerate the catalog only
when intentionally updating the pin:
`node scripts/update-rea-catalog.mjs <runtime>/rea/node_modules/rea-agents`.
The compressed catalog is shipped as package data; provider binaries and npm
dependencies are installed locally, not committed. Upstream MIT attribution is
in `REA-LICENSE` and `LICENSES-THIRD-PARTY.md`.
