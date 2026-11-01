# PSO buddy session deployment and launch

The GameCube buddy controller targets Episode I & II Plus US, GPOE8P disc 0
revision 2 (3OE2). It is an experimental two-player campaign attempt. No full
campaign completion, room-by-room coverage, damage-free run, or 10x throughput
has been demonstrated.

## Launch contract

On the dedicated i9 worker, submit `launch_game` with the owned Plus catalog
entry, `debug: true`, `pso_coop: true`, and `pad: "keyboard"`. Do not select an
operator memory card or a jump state. Stop that host's MercMode rotation when
the replacement session is ready to launch so it cannot replace the campaign.

The launch creates a formatted, persistent card under
`<data_dir>/pso-buddies/<hostname>/<game_id>/dolphin/A.USA.raw`, using exclusive
creation. Subsequent launches reuse it. It never reformats an existing card or
changes the operator's selected cards. Its separate Dolphin User directory has
two independent pads. The session cannot be kept alongside another session
using the same buddy card. Relaunch preserves this configuration and confirms
the old session closed before reopening the card.

Start the returned session through `autoplay`:

```json
{
  "session_id": "<new-dolphin-session>",
  "op": "start",
  "mode": "playbook",
  "campaign": "pso-coop-episodes-1-2",
  "continuous": true,
  "demo": true,
  "owns_keyboard": true
}
```

This authorizes character creation only in this isolated session. Both pads
must pass independent native movement probes before combat or Player 2
equipment mutation is admitted. Randomized character preferences are plans
for the actual creator; they are not RAM-generated characters.

## Equipment and speed

The PSO controls expose a player selector for the supported native equipment
actions and per-player randomized gear. Player 2 requires verified mapping and
current native identity. Global/P1-only patches remain distinct from selected
character equipment. Enemy loot hooks and floor item drops are **not enemy
instance spawning**; enemy spawning remains unsupported.

The autoplay slider requests 1x, 2x, 4x, 8x, or 10x through Dolphin's native
speed hotkeys. Each dedicated launch establishes a 1x baseline and disables
VSync for speed scaling. Interrupted changes invalidate the tracked rate and
require relaunch instead of guessing. Input delivery alone never confirms
throughput. A guarded sampler compares the native GameCube clock with elapsed
host time, with bounded measurement uncertainty and fresh player/area identity.
Only valid samples can supply measured-rate feedback. Controller timing uses
the requested rate; it still needs live calibration at each faster setting.
The bot releases its controls while the rate changes. Windows rate sweeps
can take over twenty seconds; the speed operation has a longer reply window
than ordinary item commands. An unmeasured faster rate cannot teach persistent
wall observations from short movement inputs. Reset and state restore clear
speed evidence before input; measurements cannot span the resulting clock jump.
The sampler shares the equipment dispatcher lock, so it cannot overwrite an
equipment request. This code has not yet measured throughput on the i9.

Native behavior is grounded in Dolphin's
[HotkeyScheduler.cpp](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/DolphinQt/HotkeyScheduler.cpp),
whose rate controls change the emulation-speed setting in 0.1 steps.

## Evidence and deployment state

The final focused suites passed 118 native/controller/equipment tests, 68
controls/live tests (one optional owned-disc metadata check skipped), and 27
adapter/hotkey tests. Caption and JavaScript syntax checks passed. The isolated
browser harness failed during owned-process cleanup, so a clean browser UI
acceptance is not claimed; no active managed browser leases remained afterward.
These are local checks, not a live i9 campaign or speed measurement.

The i9 worker was online as `81dd9a7474aa4646` at `10.89.1.43` during this
implementation. Its running source hashes are retained in
`gbox-data/pso-coop-deploy/i9-loaded-baseline.json`. SSH port 22 timed out from
both the operator PC and Spark, including the documented `maste` account.
The administrative SMB share denied access. No PSO campaign was launched on
the i9 by this change; it still needs the updated worker code and live pad,
creator, equipment and navigation verification.

Non-bot changes (`adapters`, `tools`, controls, server) require a normal worker
refresh. MercMode's bot-only reload cannot activate them. Preserve concurrent
production edits, validate the staged source, and back up files before that
refresh. Do not overwrite production with a broad dirty-workspace copy.

## Recorded-play context (Crystal)

Both solo and buddy campaign planners now receive a bounded summary of recorded
control patterns through the existing gameplay-memory/style loader. The PSO
loader filters historical rows by the exact selected catalog game ID and
`dolphin` adapter before learning or looking up the cached model. It supplies
source run IDs without mutating the shared style model. The planner receives at
most six button-pattern frequency/example-duration summaries, with explicit
limits on source IDs, pattern count, step count and numeric values. Dolphin
keyboard directions are translated into separate main-stick and D-pad names.
Recorded bursts are never executed by the PSO campaign. Current native combat,
room identities, short-action limits, fresh-state checks and completion receipts
continue to control the game.

A read-only archive audit on 2026-11-01 found 13 Plus runs under GCZ game ID
`436e0bb84d5337d1`: 18,706 pad events, 401 sampled-pad events, five checkpoints,
and 35 mod-action receipts. Ten runs contain the pad events accepted by the
existing style learner. There were no note or frame events and no annotated
route, objective, switch, kill or completion supervision. Two runs have enough
checkpoint/card identity for approximate isolated demonstrations; that is not
proof of solved routes. ISO ID `7a3692dc0cbc9b82` and the third supported PSO ID
`6b55435e3c565370` had no recordings. Select the owned recorded GCZ entry when
this evidence is desired, while still requiring the runtime's exact 3OE2 check.
No cross-ID aliasing or historical modified-ROM equivalence is inferred.

Run `06b0733e5fa2464b-3c881ebcd15c41fb` was read through the supported events API
without executing it: 1,700 events produced 146 input bursts/103 pattern groups,
and the new context correctly exposed six bounded summaries with that source
ID. The context explicitly marks historical build equivalence and per-event
human ownership as unverified. Server receipt timing is approximate; pattern
frequencies do not establish successful behavior. Search and replay archives
are not a universal learned policy. The current archive cannot substantiate
goal or navigation lessons; that needs annotated objectives and human movement
observations aligned to native room/layout identity and measured outcomes.
The bot's own persistent blocked-edge observations remain separate from human
recordings and are not a full extracted collision mesh.

Focused validation passed **135 tests** (including 21 new evidence tests) with:

```powershell
# Run from system/ with TEMP/TMP set to a writable test directory.
..\.venv-session-audit\Scripts\python.exe -m pytest tests/test_pso_recorded_evidence.py tests/test_pso_campaign.py tests/test_pso_coop.py tests/test_pso_coop_speed.py -q -p no:cacheprovider
```

Tests cover provenance filtering before the style cache, copied model metadata,
distinct stick/D-pad names, malformed and oversized values, bounded summaries,
and actual solo/buddy planner delivery without recorded input execution. These
are local validation and read-only archive evidence; live i9 deployment and any
improvement in campaign completion remain unverified.
