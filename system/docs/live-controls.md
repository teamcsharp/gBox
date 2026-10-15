# Live game controls in Mods

The desktop/web Mods gallery has **Inventory, world controls & hidden content**.
Choose a game and a running session; **Refresh / check mode** checks the current
revision and scene. The same panel appears under Mods in a game's session.
There is no background memory-writing loop, startup scan, or Ghidra launch on Play.
PSO reuses the existing disc-derived item/equipment panel when checked.

Every catalog game can have controls; this does **not** mean every game already
has an inventory writer or a verified unlock patch. Missing categories remain
explicitly pending. **Research missing controls with Ghidra** creates one durable
request per game, retrying failed dispatch without duplicating the ticket.
Agents should record which operations are irrelevant and why in that request.
Published profiles can also include `assessments` keyed by category, with a
bounded `scope`, `reason` and `status` (`unsupported`, `not_relevant` or
`research_pending`). These explain verified gaps in the panel without creating
an executable control. An unsupported category cannot also publish an action.
The standing discovery targets include walk-through-walls/obstacles, named item
insertion, finish level, next checkpoint, unlimited ammunition and pistol-fired
rockets through the game's native projectile routine. Each assimilation
fingerprint and custom-build investigation carries this objective. Fingerprinting
does not enable an unverified action or launch background analysis automatically.
Existing discovery tickets are upgraded once when these requirements change;
their earlier findings and request IDs are preserved.

The shared **Require unlock-all in every custom build** preference uses the
existing custom_build_unlocks policy. It is the operator's standing requirement:
all hidden characters, costumes, stages, modes, items and extras should be
available by default in rebuilt games. The writer must apply a reusable ROM
patch or isolated build-save overlay and verify each exact build; a published
live action does not make a pending build badge verified. Preserve base ROMs and
personal saves. Never run experiments against an operator's ongoing game.

## Publishing Ghidra findings

Authenticated `GET /api/games/{game_id}/live-controls` returns the current
profile, research ticket, categories and unlock policy. Publish a complete
snapshot with `POST /api/games/{game_id}/live-controls/profile`:
Agents can use the audited `game_controls_research` tool with `op:get`,
`op:discover`, or `op:publish` and the `profile` object instead of making HTTP calls.
This fixed-endpoint metadata client uses `read` and `stage`; applying a control
still requires `memory_write`, and no general file-mutation permission is granted.

```json
{
  "executable_sha256": "<SHA256 of the analyzed executable>",
  "revision_label": "Owned USA revision 1",
  "guards": [{"address": 1234, "hex": "<at least 16 exact immutable loaded bytes>"}],
  "ghidra_artifacts": ["<stored Ghidra evidence artifact SHA256>"],
  "runtime_artifacts": ["<stored runtime evidence artifact SHA256>"],
  "actions": [{
    "id": "boss_hp", "category": "bosses", "label": "Set boss HP to zero",
    "scope": "Offline boss encounter, live boss object in fixed slot",
    "notes": "Explain verified effects, applicability and limitations.",
    "guards": [{"address": 5678, "hex": "<exact scene/object identity bytes>"}],
    "parameters": [],
    "binding": {"kind": "memory", "address": 9012, "width": 2, "byteorder": "little", "value": 0}
  }]
}
```

Addresses above are **schema examples, not game addresses**. Use only measured
findings. Artifacts must already exist in the artifact store. A source hash is
provenance; loaded revision fingerprints are the runtime identity check. Choose
fingerprints that distinguish all incompatible builds. Every action also needs
scene/mode guards that exclude loading, invalid objects, and unsupported modes.
Static addresses only: dynamic objects require a tested native tool adapter.

A profile may also include bounded category `assessments`, for example
`{"checkpoints":{"status":"unsupported","scope":"Reviewed on-foot mission sections",
"reason":"No authored ordered checkpoint route was established"}}`. Allowed
statuses are `unsupported`, `not_relevant`, and `research_pending`, with explicit
scope and reason. An assessment is displayed as a limitation; it never creates
an executable action or a verified unlock claim. A category containing published
actions may only retain a `research_pending` assessment for remaining gaps.

Categories: `items`, `inventory`, `upgrades`, `levels`, `bosses`, `pedestrians`,
`movement`, `checkpoints`, `ammunition`, `projectiles`, `unlocks`. Parameters have
a unique `id`, `label`, and `kind`: `integer` with `min/max/default`, `choice` with
`options:[{value,label}]` and `default`, or `boolean` with an explicit true/false
`default`. Booleans do not accept 0/1 or string coercions.
Memory bindings can reference an integer `parameter` instead of a fixed `value`.
Only unsigned 1/2/4-byte fields are supported, with explicit endian order and
readback; writes cannot overlap guards. This is a field setter, **not** a generic
item spawner, function caller or guaranteed transactional operation. A failed
readback reports failure; the game may already have changed. No blind retries.

For native item insertion, upgrades, pedestrian spawning or level completion,
use `binding:{kind:"native",tool:"...",input:{op:"...",...}}`. See the explicit
`NATIVE` allowlist in `gbox/live_controls.py`. Inputs are flat; `$parameter_id`
substitutes a validated declared parameter. `session_id` is always injected.
Example: `tool:"gta_mods",input:{op:"ped_rain",count:"$count"}` with a bounded
integer count and tested GTA revision/mode guards. Expanding to another native
routine requires implementing/testing its worker adapter and allowlist entry.
Never publish an untested adapter merely because the tool is installed.

Persistent switches use `control:"toggle"`, `toggle_parameter:"on"` and a boolean
parameter named `on`. They require a tested native binding with
`input:{op:"noclip",on:"$on"}` and `state_key:"noclip"`, for example, rather than
a memory field setter. The separate read-only inspector allowlist supplies the
actual current state; an unchecked default is never treated as a measured state.
Agent Under Fire's `auf_live` inspector provides exact booleans in `switches` and
authoritative per-operation booleans in `available`. A missing state, unknown
availability or failed revision probe keeps the switch unavailable. Inspection
calls `op:"inspect"` once per native tool; it cannot select a profile-supplied
arbitrary inspector operation. Enable/disable and restoration must be tested on
the exact owned revision before publication.
For `auf_live` item dropdowns, inspection also returns
`item_choices:{parameter:"item",values:[...]}` on the action. These are the
intersection of the published reviewed options and item IDs actually loaded in
the current mission; native inspection cannot add new labels or catalog entries.
Missing/empty catalogs keep insertion unavailable. Native per-operation
`unavailable_reasons` are surfaced with the action so an unsupported checkpoint
or missing projectile resource has a concrete explanation.

`POST /api/games/{gid}/live-controls/run` accepts `session_id`, `revision`,
`op:"inspect"|"apply"`, and for apply `action`, `values`. Jobs are pinned to that
session's worker. The worker fetches the authoritative profile, rejects stale
revisions or mismatched games, and rechecks every guard immediately before
execution. Missing research stays unavailable, including modes not yet tested.
Profile publication and jobs retain their normal audit and receipt records.

Apply requests carry a unique `command_id` (16–64 letters, digits, `_` or `-`) and
an `expires` Unix timestamp. The route supplies omitted IDs/deadlines for older
clients and limits commands to 15 seconds from submission, preserving any earlier
client deadline. The worker checks expiry again immediately before the memory
write/native call; adapters that support these fields receive both and repeat
the check after their own transaction locks. Direct `game_live_controls` apply
calls must supply both fields and a deadline no more than 30 seconds ahead.
Inspection needs neither field. The server reserves command IDs before submitting
jobs, returns the original receipt on an identical replay, rejects a reused ID
with different parameters, and never retries an uncertain submission. Late queue
delivery reports expiry rather than changing a later gameplay moment.

Profiles using `auf_live` additionally require the selected session's worker to
advertise both tools and current process-start hashes of `live_controls.py` and
`auf_live.py`. An old worker is asked to refresh safely when idle; it cannot probe
or execute a new profile with outdated toggle/expiry behavior.
