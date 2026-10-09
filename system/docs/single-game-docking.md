# One active emulator per worker

Every launch, including unmodified games, is serialized on its worker. Replacement files and local staging finish before the current game is saved. All previous games are checkpointed before any are stopped. The next emulator starts only after previous emulator processes have exited. Save failures keep the current games running; failed stops prevent another launch. Checkpoint artifacts are recorded in the new launch's `detail.previous_checkpoints`.

Closed sessions are explicitly published to the server before removal from the worker. Successful launch ingestion also records their ended state and retained checkpoint. This prevents stale session chips and controller routes after a switch.

The desktop chooses the newest local session, prevents overlapping polling and serializes native docking commands. The window helper verifies the app parent before docking. Switching or detaching hides the previous window and keeps it parented rather than restoring a visible desktop popup. The helper rejects a missing app window and prefers visible game windows over hidden auxiliary windows.

Validation includes concurrent launches, checkpoint ordering, save and stop failures, ended-session publication, native Windows attachment/switch/detach/invalid-parent checks, concurrent desktop IPC checks and an actual SmackDown launch switch followed by checkpoint restoration.
