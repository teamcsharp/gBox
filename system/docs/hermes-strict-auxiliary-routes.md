# Strict vision routing for a single Hermes cron job

`scripts/apply_hermes_strict_auxiliary_routes.py` applies a structurally checked,
idempotent maintenance patch to the installed Hermes `cron/scheduler.py` and
`agent/auxiliary_client.py`. It checks compatibility by default, backs up both
files before applying, and restores changed source if a later replacement fails.
It does not modify configuration or jobs, dispatch work, or call any provider.

This patch is opt-in through the stored job record:

```json
{
  "auxiliary_routes": {
    "vision": {
      "provider": "nous",
      "model": "anthropic/claude-opus-5.5",
      "strict": true
    }
  }
}
```

Use canonical provider identifiers and an explicit model. Invalid policies fail
before the agent is constructed. Provider/model pins on their own do not enable
the policy. Existing jobs without `auxiliary_routes` keep their original behavior.

The existing locked API preserves this additional field and all other jobs:

```python
from cron.jobs import update_job

update_job(job_id, {
    "auxiliary_routes": {
        "vision": {
            "provider": "nous",
            "model": "anthropic/claude-opus-5.5",
            "strict": True,
        }
    }
})
```

The policy uses a ContextVar bound around this job's execution and reset in its
`finally` block. Existing cron worker and tool thread context propagation carries
it into vision calls. Concurrent jobs cannot read each other's policy. An omitted
policy clears inherited state for that run and restores the outer state afterward.

For a strict vision call, the configured provider/model replaces both global
`auxiliary.vision` routing and conflicting direct call arguments. Global vision
endpoint, credential and fallback-chain settings are not inherited. The installed
provider resolver still obtains the selected provider's credentials and chooses
its supported transport. Nous Anthropic model identifiers retain the native
Anthropic transport.

Unavailable-client automatic routing and the later cross-provider recovery ladder
are disabled. Same-provider transient retry and credential refresh remain available.
A missing pinned Nous model does not switch to a Portal-recommended model. A
different resolved provider/model is rejected before a model request. An unsupported
vision model or exhausted account therefore fails explicitly instead of charging
another provider.

Successful primary and same-provider retry responses are attributed to the enforced
provider in the existing auxiliary ledger; the returned model remains the actual
`response.model`. This is token accounting, not proof of an invoiced charge.
Jobs without a strict policy retain the installed attribution behavior.

## Activation without disrupting existing workers

Keep the target job disabled while applying the patch. Check first:

```sh
python apply_hermes_strict_auxiliary_routes.py /path/to/hermes-agent
python apply_hermes_strict_auxiliary_routes.py /path/to/hermes-agent --apply
```

Then add the job field through `update_job`. Source edits do not update modules
already imported into a process. A fresh external cron worker imports the patch;
a cached in-process gateway requires a later safe restart. Do not resume a strict
job through a cached in-process scheduler and assume it has been activated.

The installed managed gateway already launched the prior #1216 job
`d5174789127a` through a fresh external worker. Execution
`c24476c2a40643449c710ceb3741e46e` recorded PID 163292, matching the worker
acknowledgement at `2026-10-11 02:30:40.839`. The handoff serializes the complete
job record, including `auxiliary_routes`, and the worker reads that record before
calling its freshly imported scheduler. Confirm the same handoff for the new
execution. No global launch flags or interruption of other workers are required.

## Validation

The portable fixture contains only selected installed runtime source functions,
with no credentials or configuration. Tests exercise the real patched resolver,
client selection, recovery gate, accounting validation and cron worker context
boundary using mock clients. They also cover concurrent async jobs, invalid
policies, nested restoration, failed construction, backup rollback and unknown
runtime refusal. No test calls a model. Native provider image acceptance still
requires a later authorized execution and its separate auxiliary ledger evidence.
