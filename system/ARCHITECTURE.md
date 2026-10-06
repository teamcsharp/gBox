# Architecture

```
 Web UI / CLI ──HTTP+token──▶ Control plane (gbox serve)
                               ├─ job scheduler (capability-routed)
                               ├─ independent validator + receipts
                               ├─ audit ledger (hash chain, append-only triggers)
                               ├─ artifact store (sha256-addressed, immutable)
                               └─ catalog / profiles / knowledge edges / run records (SQLite)
                                   ▲  claim / result (HTTP poll)
                 ┌─────────────────┴─────────────────┐
           Worker (Windows)                    Worker (Linux / DGX Spark)
           tools + adapters                    tools + adapters
           ffmpeg, Steam, Blender…             emulators, Ghidra…
```

## Job lifecycle

1. Client `POST /api/jobs {tool, input}`. Input is validated against the tool's Pydantic schema. Permissions are checked against `granted_permissions`: if any are missing, the job is `rejected` and audited.
2. Workers advertise only the tools whose availability check passes on that host (`unavailable` reasons are reported too). A job goes to any worker offering its tool. It is pinned to a specific OS or worker only when necessary: session ops are routed automatically to the worker that holds the session.
3. The worker runs the tool (timeout, retries) and posts output plus artifacts with provenance.
4. **The control plane, not the worker, decides success.** It re-validates the output schema, runs the tool's `validate()` against the uploaded artifacts, stores the artifacts content-addressed, writes a Receipt, appends an audit entry, then runs `on_accept` (e.g. catalog ingest). Final states are `succeeded`, `invalid` (ran but failed validation), or `failed`.

## Persistence

- `docs(kind, id, body)` holds jobs, receipts, workers, catalog, profiles, edges, runs, and artifact metadata.
- `audit` entries are hashed as `sha256(prev_hash ‖ canonical_json(entry))`. SQLite triggers block UPDATE/DELETE, and `/api/audit/verify` recomputes the whole chain.
- Artifacts are stored at `data_dir/artifacts/<sha[:2]>/<sha>` and never rewritten.

## Knowledge rules (plan §2.3, §20, §21)

- A `KnowledgeEdge` can only be `validated` when it cites existing evidence artifacts.
- A `RunRecord` cannot carry its own evaluation. The evaluator must be a different actor from the proposer.
- LLM output (`llm_complete`) is stored as a transcript artifact. It is a hypothesis, never evidence.

## Adapters (plan §6)

Every adapter answers `get_capabilities()` for every op in `adapters.OPS`. Calling an unsupported op raises `Unsupported`, so a missing capability is never silently ignored.
