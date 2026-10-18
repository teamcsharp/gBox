# Provider scope for the private gBox backlog

An operator can restrict a provider to public-source research independently of
local-only mode, quota state, saved feedback routes and model preferences. The
policy is opt-in for each installation. The repository does not restrict ZAI or
any other provider by default.

The private backlog always includes inbox messages, workspaces, owned game data
and diagnostics as potentially private context. A request's title, prompt,
context or model-written Hermes configuration cannot change that purpose. Public
research runs belong in the separate operator-managed research home, without
gBox MCP or private workspace access. This module does not create, configure or
otherwise change that research runner.

## Trusted local maintenance

The policy is `provider-scopes.json` in the existing gBox Hermes dispatch state
directory (`GBOX_HERMES_DISPATCH_STATE` when explicitly configured). It contains
only provider identifiers and endpoint DNS hosts. It is separate from Hermes
`config.yaml`, feedback, quota and inbox state. There is no API/MCP policy setter.
Only an authorized operator should run the local maintenance CLI or edit this
policy file; ordinary engineering agents must not change it. As with other local
configuration, filesystem write permission remains the trust boundary: this is
scheduler enforcement, not a sandbox against arbitrary privileged file writes.

From the canonical `system` directory, review an additive restriction first:

```sh
python -m gbox.hermes_provider_scope restrict --provider zai --endpoint-host api.z.ai
```

The default is a dry run. To apply the reviewed restriction:

```sh
python -m gbox.hermes_provider_scope restrict --provider zai --endpoint-host api.z.ai --apply
python -m gbox.hermes_provider_scope status
```

The writer uses the existing maintenance lock and an atomically replaced,
flushed file. It preserves other rules and never changes provider credentials,
Hermes routing configuration, local-only mode, jobs or active executions. The
CLI offers only additive restrictions; relaxing a policy requires an explicit
operator maintenance edit. Missing policy means no scope restriction. A present
invalid, oversized or unreadable policy blocks new private admission rather
than silently restoring unrestricted routing.

Example policy:

```json
{"schema": 1, "rules": [{"scope": "public_source_only", "providers": ["zai"], "endpoint_hosts": ["api.z.ai"]}]}
```

Names and hosts match case-insensitively. Hosts are obtained with URL parsing
from explicit route endpoints and matching `custom_providers`/`providers`
entries, including `custom:<name>`, display-name and legacy provider-key aliases.
The bounded resolver also covers installed built-in spelling aliases and
matching-provider `model.base_url`/`api_base` overrides, including bare `custom`
with an explicit cron provider. An automatic route, unresolved custom endpoint
or environment template defers admission; no credentials are resolved to guess
its identity. The installed scheduler has per-job `base_url`, but no independent
`cron.base_url` override. Normalization derives from the installed Hermes
`d923a5eb487a17c0a68801bba9ef0f56c81040a8` source; exact file hashes are in the
review receipt `hermes-provider-scope-runtime-shapes.json`. Host matching is exact, with an optional trailing DNS dot normalized;
it does not treat `api.z.ai.evil.example` as `api.z.ai`. Unknown upstream routing
behind an otherwise unrelated proxy is not inferred. Operator policy should
also name such a proxy explicitly if it forwards to the restricted provider.

## Admission and visibility

The quota route list filters current, fallback and saved feedback routes. The
supervisor cannot reinsert a restricted primary or honor a restricted preferred
route. Provider status retains known restricted rows and their observed usage,
with `availability: scope_restricted`, `private_backlog_eligible: false` and a
safe `provider_scope_reason` containing no endpoint credentials.

New queue work, checkpoint recovery, direct incident dispatch/retries, legacy
agent-controller resume and availability-triggered resume check the actual inherited primary
and raw fallback lists, including the installed legacy `fallback_model` key
and dictionary form. A stale restricted fallback blocks admission even if the
filtered route list looks safe. The existing supervisor can remove it at its
normal safe route-change boundary; a restricted legacy `fallback_model` entry
also remains an explicit admission blocker until the operator removes or
updates that legacy field. This policy does not interrupt active runs.
A fresh policy/config check immediately before a create/resume protects against
changes during queue selection. It is a bounded admission check, not an atomic
transaction with an external scheduler or simultaneous operator config writes.
The existing public quota query and minimal public `Reply OK.` availability
probe remain permitted; their success cannot authorize private scheduling.
No job is killed, cancelled or marked completed by this policy.

Validation covers opt-in defaults, additive dry-run/apply, saved/preferred/current
routes, URL aliases, inherited fallback leakage, invalid/unreadable policy,
request text that claims public purpose, final admission changes, and recovery
without consuming its retry budget. Live policy installation and source
activation are separate operator steps.
