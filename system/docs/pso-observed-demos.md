# PSO recorded actions and observed demonstrations

New human PSO sessions attach a recorder to the existing rewind ring. The recorder
keeps the first native checkpoint, then at most one periodic checkpoint every two
minutes, and every actual rewind restore. It copies the ring's completed file;
it does not take an extra save state, pause the game or select a human save slot.
Cloud memory-card working files are copied into immutable replay snapshots.
Original card bytes, identity and serial are retained. Test copies never acquire a
cloud-card lease or sync test changes into the player's card.

Completed live PSO commands are durably journaled beside controller observations,
including drops, inventory changes, stats, survival and MAG edits. Random rare
drops retain their resolved item codes. Each successful equipment-randomizer cycle
retains the codes actually equipped and the MAG properties read back; playback
does not start another random timer and hope it makes the same choices. Unverified
or unsupported individual actions remain visible as evidence and are skipped
explicitly, including queued cheats that have no verified live-session replay
handler. Their game-state effects can still be retained by subsequent native
checkpoints. Resident face texture changes are included in subsequent checkpoints;
standalone face paint actions are not currently reissued by the action player.

Capture first writes small local ordered outbox records. A background sender hashes
the owned ROM, emulator and core, streams native states/card snapshots with SHA-256
checks, and then writes the associated event into Spark's existing compressed,
searchable gameplay-memory SQLite database. Capture time is preserved separately
from network receipt time. Upload failure retains immutable local bytes and retries;
pending manifests from a stopped worker are recovered on the next human PSO launch.
There is no neural policy training: the search vectors remain signed feature hashes.

Completed human PSO runs with an archived checkpoint and card copy are discovered
automatically. The first available opted-in idle PC performs a single-pass test;
only a completed, visible-frame receipt enables subsequent automatic loops. One
automatic demonstration runs globally at a time, with at least five minutes
between dispatches for a run. A failed unchanged prefix is retained for inspection
and is not repeatedly relaunched; new archived data permits a fresh test after
the cooldown. Running human sessions and agent-created runs are never discovered
as automatic sources. An explicit disabled per-run preference is respected.

In **Settings → Gameplay memory**, a run with an archived checkpoint and card copy
also offers **Play observed demo**, **Loop**, and an idle screensaver toggle. Play selects
an available opted-in idle Windows PC, rechecks its resources and ownership at
execution, then launches a separate emulator with private cards and states. It
refuses an emulator/core/ROM hash mismatch. It never closes another session to make
room. The initial checkpoint is loaded, recorded inputs and native mod actions are
scheduled chronologically, and later native checkpoints realign the game. Mutation
read-back failures end only this demonstration. Operator input, loss of admission,
opt-out, control-plane loss or the one-hour runtime bound makes the test yield.
Idle dispatch waits for a completed single-pass test receipt before starting loops.

This is an **approximate observed-input demonstration**, not frame-exact TAS.
Physical controller observations can miss taps. Analog observations are quantized
to directions by the current injection adapters. Physical XInput RetroPad button
labels are translated to Dolphin's native bindings; streamed/UI inputs retain the
adapter buttons already requested. Flycast stick observations use its analog input
channel rather than its D-pad. Select is not reissued as an
emulator hotkey modifier: actual rewind branches come from their recorded state
restores. Fast-forward and paused wall-clock pacing are approximate rather than a
frame-exact recreation of the frontend's speed control. Checkpoints preserve actual game
state and rewind branches, but cannot reconstruct controller inputs that were never
recorded, prove that the same combat decisions occurred, or establish that a level
was completed. A successful receipt means the bounded recorded timeline and its
native actions finished; it does not certify the historical outcome. Previously
discarded sessions cannot be recovered retroactively.

Snapshots have a 128 MiB per-file bound, 20 GiB total local action-capture retention,
64 GiB Spark snapshot retention and a 4 GiB free-disk guard. Disposable demonstration
copies have a separate 20 GiB aggregate bound and are removed only after their own
emulator has exited. Failed copies remain bounded for inspection. No original recording
is automatically deleted when storage fills. Existing observation and native BSV/
SMB TAS budgets remain separate. A stopped or power-lost worker can retain a partial
outbox without a ready identity/card manifest; those bytes are preserved for repair
and are not advertised as a replay-ready run.

The native conformance receipt is
[pso-observed-demo-validation.json](pso-observed-demo-validation.json): a private
Spark emulator replayed two controller events, set ATP to 900 and dropped two SABERs,
restored its own slot-eight checkpoint, then repeated both native actions with
successful read-back. Its process, Xvfb display, cards and user folder were separate
from the operator. The full Windows archived-run launch still needs a captured
human run on a refreshed worker before it can be claimed as an end-to-end PSO demo.

Upstream Dolphin's [movie recorder](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/Movie.cpp)
and [state loader](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/State.cpp)
support native DTM/state integration, but gBox has not implemented or verified that
recording path. DTM functionality is therefore not used to claim exact PSO replay.
