# PSO GameCube Episode I & II completion loop

`gbox.pso_campaign` adds an explicit, experimental campaign controller for
**Episode I & II Plus US, GPOE8P disc 0 revision 2 (3OE2)**. It attempts offline
Episode I, then Episode II, then repeats with the same character. This is the
GameCube Episode I & II release, not the separate Dreamcast Ver.1/Ver.2 games.

The existing Forest 1 mission remains available. Ordinary F3 autoplay keeps its
existing behavior; campaign control must be selected explicitly.

## Start and observe

Launch the owned Plus disc on an authorized bot worker. Known Plus catalog IDs
are `7a3692dc0cbc9b82` and `436e0bb84d5337d1`; the live revision check is decisive.
Use the normal `autoplay` worker tool:

```json
{
  "session_id": "<running-dolphin-session>",
  "op": "start",
  "mode": "playbook",
  "campaign": "pso-episodes-1-2",
  "continuous": true,
  "demo": true,
  "owns_keyboard": true
}
```

`owns_keyboard` is appropriate for a PC dedicated to bots. Stop the current bot
before selecting a different campaign. `autoplay` with `op: "status"` reports
the current campaign state, target episode, visited/missing floors, native combat
and navigation results, recent route plans and completion receipts. The existing
telemetry feed carries the same live statistics. F3/`op: "stop"` releases input.

The start checks the disc revision and the configured vision service's available
models before announcing a started run. `agent.vision_url` is an explicit override;
otherwise the configured remote agent/LLM service is used. `agent.vision_model`
selects the model, defaulting to the existing `qwen2.5vl:7b` setting. The model must
support image input. A missing model or unavailable service fails the preflight.

## Driving and completion evidence

The controller reads the revision-guarded offline phase, episode, floor, player
and entity table. The existing semantic fighter handles nearby enemies; bounded
native door approaches help traverse cleared rooms. The visual planner handles
unrecorded routes, switches, transporters, dialogue, healing, equipment, save/quit
and episode selection. Input plans have at most four actions of 1.5 seconds each
and are discarded if the episode, floor, phase or player life state changes while
the model is responding. Five consecutive observation failures stop the attempt.

The controller uses normal gameplay input. It does not install hooks, teleport,
freeze HP, modify progress flags, replace saves or restore emulator states. It
refuses online free-play. The visual planner is instructed to flag card-format,
character-overwrite and similar prompts for the operator; a flagged prompt stops
input. Recognition of those prompts still depends on the vision model.

An episode receipt requires all of these observations:

- The attempt started at the first field floor and visited every main free-play
  field and boss floor for that episode.
- A boss-class entity in the final area was observed with valid positive HP and
  subsequently zero HP. A living boss part or new form revokes the zero evidence.
- Two distinct ending/credits frames, separated by at least two seconds, were
  recognized after that native observation. Despawns, empty rooms and loading
  screens do not count.

A finish without route coverage is recorded as `partial_episode_finish` and
retries that episode. A cycle counts only after Episode I and Episode II receipts
in order. Quitting/reloading an unfinished episode clears its route coverage.
Ending frames and `finishes.jsonl` are retained under the worker runtime's
`autoplay/pso-campaign/<session>/`; when available, frames are also uploaded to the
normal artifact store. Recent ledger state survives stopping/restarting the bot
on the same adapter; it does not manufacture continuity across a worker restart.

Main free-play floors are Episode I `0x01..0x0E` and Episode II `0x01..0x0F`.
Episode II `0x10` (Seaside at night) and `0x11` (Control Tower) are excluded. These
IDs and the final bosses are corroborated by newserv's
[floor definitions](https://github.com/fuzziqersoftware/newserv/blob/master/src/StaticGameData.cc)
and [GameCube map tables](https://github.com/fuzziqersoftware/newserv/blob/master/src/Map.cc).
The owned-build episode/floor addresses come from `pso_gc_adventure.py` and
`pso_gc_live.py`.

## Validation and remaining live work

Synthetic tests exercise ordered cycles, incomplete routes, loading/despawn false
positives, multi-part/form bosses, save/reload resets, endpoint selection, invalid
actions, online/revision refusal, card prompts and immediate button release.

**No full live campaign completion has been demonstrated by this change.** The
vision routes and menus need acceptance on the owned save. The existing generic
boss HP layout may not describe every final-boss form; if it does not, the
controller withholds a completion receipt until an exact native ending reader is
derived. Runtime receipts preserve evidence for review; test fixtures are not
evidence that the game has been completed. Normal difficulty is a planner goal,
not a memory-verified difficulty field. Existing game preferences may still apply
when gBox launches the game.
