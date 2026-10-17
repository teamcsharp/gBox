# Game operation output

Unlocked game actions show their reported output over the game being viewed. The
overlay covers immediate PSO commands, published `game_live_controls` actions, and
session-bound inventory/modification tools. Agent-submitted jobs are discovered
through the audit feed; queued/running jobs supply their existing progress logs.

The text stays visible while a command/job is active. A result remains for 3.5 seconds,
then fades over one second. Failures remain for six seconds before fading. An
unverified result is labelled unverified. A lost status read says the outcome is
unknown and keeps checking status; it does not assume success or repeat a mutation.
Commands that do not publish intermediate logs show the request and its final
acknowledgment, without invented processing steps.

The output is pinned to the selected session. Switching games clears the view and
late responses for another session are ignored. Ordinary catalog/status reads and
unrelated background builds do not produce game text. Stored job logs remain
available in the job details after the overlay fades.

The browser draws text over the visible gameplay frame. The desktop uses one
transparent, click-through child window over native and GPU game surfaces. It follows
the game rectangle, zoom, application visibility and native menu cutouts, never takes
focus, and is destroyed once its output fades. This does not modify the emulator's
framebuffer or ROM, and gameplay-only emulator captures remain separate.

Output is bounded to four visible operations and six recent lines per operation;
credentials in reported text are redacted and text is inserted without HTML parsing.
The desktop reuses its existing jobs/audit snapshots, reading individual observed
jobs while they run. Standalone browser viewers additionally check audit events
while a session is selected. No worker or backend restart is needed for this client
change; an already-open desktop application needs reopening to load the main-process
overlay and updated preload bridge.

Tests cover request outcomes, progress, fading, concurrent/session isolation,
redaction, no mutation retries, real browser pointer passthrough, the native output
document's CSP, and mocked native window geometry/lifecycle. Interactive verification
over an operator's running native game has not been performed.
