# Continuous local inspection builds

Builds has a Continuous inspection builds panel, with an enable/pause switch,
RAM reservation and per-game state/waiting reason. The server keeps the work;
closing a desktop does not discard it. Built images use unique `inspect_*` names
and appear in the normal Builds list and notifications. They never auto-launch.
Compilation/assembly success is **not** native gameplay or unlock-all acceptance.

The controller accepts reviewed `characters cast_swap` recipes (including explicit
single-slot assignments). Arbitrary shell commands, other compiler toolchains,
live session edits and automatic model repair are not provided by this queue.
Agents must implement suggestions and publish an updated plan; the controller
does not interpret text or silently acknowledge reports on their behalf.

Default local policy when enabled: JAYBUILTFINALE; one builder at a time; three
attempts per hour; 30 seconds for edits to settle; 8 GiB estimated working RAM
with at least 4 GiB left free and projected RAM use below 80%; 8 GiB estimated
output with another 20 GiB disk free. These are configurable admission
reservations, **not OS/RSS hard caps**. Profile unusually large writers and raise
their reservation before use. Running tools may exceed estimates; this does not
kill them or guarantee a fixed peak working set.

The existing measured CPU budget (normally 70%), Gaming mode checkbox and human
game ownership remain authoritative. With `allow_while_active:true`, source/image
assembly may start while the operator types, but automated emulator tests still
require idle time. CPU-only builds need not wait for an unrelated GPU inference
job; `requires_gpu:true` plans keep the GPU admission check. New builds wait during
human gameplay. A running build finishes its current unit rather than being
destroyed mid-write. Pause/offline/load preserves the latest desired revision.

The queue coalesces edits and never repeats an unchanged failed revision. Changed
source dependencies create a new revision after the debounce. New game-specific
operator messages/reports require exact review before continuing. Source hashes
advertised by workers are fixed at process startup; changed writer code waits for
a safe worker refresh rather than building with stale imported Python modules.
Memory/disk telemetry must be current; unknown capacity is never spare capacity.

## Agent/API contract

Use the audited `inspection_builds` tool:

- `op:status` gives policy, plans and recent run/job links.
- `op:configure,value:{enabled:true,node:"JAYBUILTFINALE",...}` enables the policy.
- `op:plan,game_id` returns current request fingerprints and durable build reports.
- After reading request text/images and implementing the changes,
  `op:publish,game_id,value` publishes:

```json
{
  "change_id": "Description / source or asset revision of the implemented change",
  "dependencies": ["gbox/cast_swap.py", "gbox/the_actual_writer.py"],
  "recipe": {"tool":"characters", "input":{
    "op":"cast_swap", "target_game":"catalog-game-id", "source":"sonic,mario",
    "slots":"all", "assignments":[], "launch":false
  }},
  "requests_ack": {"request-id":"fingerprint returned by plan"},
  "feedback_ack": {"report-id":1},
  "requires_gpu": false,
  "parent_request_id": "owning-request-id"
}
```

Paths are examples, not an actual writer plan. Dependencies must exist under
`gbox/`. Existing recipes can be enrolled with `draft:true` while their defects
await implementation. A draft never assembles anything or acknowledges feedback;
publish again without draft after reviewing and implementing the actual changes.
Dependencies are limited to
`gbox/`, at most 24 files. Change IDs must also change after extracted models or
other non-code build inputs change. Unread reports must not be acknowledged;
acknowledgement is not evidence the defect was fixed. Missing native writers or
budget failures stay blocked with an explanation. A recipe with no actual native
build output does not become Ready for inspection. Requests without game context
must be linked to the appropriate plan by the agent.

Equivalent authenticated routes: GET/POST `/api/inspection-builds`, GET/POST
`/api/inspection-builds/{game_id}`. Polling does not create research tickets or
launch emulators. Worker claim repeats policy, reviews, sources, recipe, headroom
and ownership checks. Submission intent is durable and uncertain outcomes are
reconciled by origin ID, never blindly retried. Existing local per-game retention
settings apply; this controller performs no deletion of builds, originals or saves.
