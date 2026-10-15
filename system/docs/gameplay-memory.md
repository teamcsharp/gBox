# Gameplay memory and hourly cast mashups

PSO now also has [recorded actions and observed demonstrations](pso-observed-demos.md).
These replay sampled inputs, resolved mod actions and native checkpoint branches in
separate idle test sessions. They are approximate demonstrations; the native/exact
replay limitations below still apply.

Operator intent: preserve every human run for test reuse. Demonstrations belong in
**separate test sessions on available idle PCs**, never the human's live character,
save slots, inventory, or controller session.

## Implemented capture

The Spark owns `gbox-data/gameplay-memory/gameplay-memory.sqlite3` (SQLite WAL).
Worker physical-pad reports and UI input events are journaled with their receipt
times. Completed inventory, drop, character, cheat, graphics and session-control
jobs record bounded operator action receipts. A tool succeeding does not prove
the requested in-game effect happened. No raw RAM buffers are copied into this DB.

Runs, compressed events, and per-minute searchable vectors survive backend
restarts. Vectors use 128-dimensional signed feature hashing, **not neural
embeddings or a trained gameplay policy**. Search considers the latest 5,000 minute
segments; event paging is bounded. The observation DB stops new writes at 4 GiB
and retains old runs. WAL uses NORMAL synchronization: an OS/power failure may
lose its latest uncheckpointed tail.

Settings > Gameplay memory shows recent runs, searches annotations/actions, and
opens a scrollable event timeline. Notes can identify Forest completion or a
weapon sequence, but are labeled annotations rather than automatically detected
wins. The `gameplay_memory` typed tool exposes status/search/events to agents.
`GET /api/gameplay-memory` reports the actual archive and replay readiness.

Experimental **new human RetroArch launches** can request native `--bsvrecord`
when the installed binary advertises it and the worker's
`gameplay_native_replay_enabled = true`. This is **off by default**: native BSV can
reject loads of existing save states that belong to a different replay. Core and
save-state compatibility must be validated before enabling it for human play.
Each uses a unique worker-local file and manifest; no
personal replay slot or save-state slot is selected/overwritten. Core and emulator
hashes are computed off the launch path. Content has a stat fingerprint, not a
full content hash, so exact ROM identity is not claimed. Existing games are not
restarted or switched into recording. Dolphin's native DTM capture remains
unimplemented; PSO can instead use the checkpoint/action demonstration path above.

Native recording requires 8 GiB free to begin, stops its managed recording at
256 MiB or below 4 GiB free, and caps retained worker recordings at 20 GiB. It does
not stop the game. After ending, a stable file is streamed to Spark, SHA-256 checked,
and linked to its run. Spark's native archive has a separate 64 GiB cap. Failed
transfers retain local bytes/manifests (three immediate attempts; automatic orphan
recovery after worker restart is not implemented). No recording is automatically
deleted. `gameplay_memory_enabled = false` in a worker's config disables new native
capture; the same server setting disables observation journaling.

## Replay limits and next acceptance gate

Native SMB1 replay is now implemented separately: see [Native Mario replay](native-mario-tas.md).
Its Runs play/segment/loop controls and verified idle dispatch apply only to new supported
Mesen tapes. The limitations below still apply to sampled observations, BSV and PSO.

When no checkpoint-backed demonstration is ready, the UI reports
`waiting_for_validated_native_run`. **Exact PSO TAS recording/playback has not been
verified.** Approximate PSO observed demos can dispatch idle loops after a completed
test receipt, as described above. Pad receipt times can miss physical taps and cannot be
converted honestly into frame-accurate TAS data. Nothing can recover inputs already
discarded before capture was enabled.

Before auto-play may be enabled, a native run must be tested on an opted-in idle
worker with isolated saves/core options and no connection to the player's online
character. Verify content/core/config/initial checkpoint identity, replay progression
and screenshots against actual goals, mod-action timing and effects, black/frozen
frame recovery, bounded runtime, and yield on human return. Changed ROMs can desync;
their results must be new test receipts, never inherited success. A vector match is
not a validated input replay, and a recording file upload is not validation.

## Hourly build policy

`POST /api/showcase` can enable `roulette`, `source_pool` (default choices `sonic`,
`mario`, `sonic,mario`), `favorites: 200`, `recent: 0`, and `builds_per_hour: 1`.
The hour and game ID seed a reproducible target/donor draw. Its source, seed,
planned assignments, plan hash, and job ID are retained. It collects owned SA1/SA2
and Mario donors through existing readers, then uses routed native writers for
whole small casts/main casts. Missing writers enter the readiness queue.

One assembly runs at a time; unchanged plans are not rebuilt. The existing HDD
budget, running-build protection, operator exclusion, idle/70% resource admission,
and disk guards apply. Showcase assembly additionally needs at least 12 GiB free
and below 80% RAM usage (an 8 GiB estimate plus 4 GiB reserve, not an OS memory cap).
An unread operator report blocks roulette before eviction/submission; use reviewed
inspection recipes to address it. A fresh random seed does not bypass failed-writer
cooldown. Builds are **not auto-launched or certified playable**. The hourly setting
is an admission ceiling/attempt cadence, not a promise to finish a build every hour
despite missing writers, reports, resource pressure or failed verification.

Native command reference: https://docs.libretro.com/development/retroarch/network-control-interface/
