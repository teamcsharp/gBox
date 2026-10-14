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

Categories: `items`, `inventory`, `upgrades`, `levels`, `bosses`, `pedestrians`,
`unlocks`. Parameters have a unique `id`, `label`, and `kind`: `integer` with
`min/max/default` or `choice` with `options:[{value,label}]` and `default`.
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

`POST /api/games/{gid}/live-controls/run` accepts `session_id`, `revision`,
`op:"inspect"|"apply"`, and for apply `action`, `values`. Jobs are pinned to that
session's worker. The worker fetches the authoritative profile, rejects stale
revisions or mismatched games, and rechecks every guard immediately before
execution. Missing research stays unavailable, including modes not yet tested.
Profile publication and jobs retain their normal audit and receipt records.
